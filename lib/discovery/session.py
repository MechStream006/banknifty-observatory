"""
SmartAPISession — authentication lifecycle manager for SmartAPI access.

Handles initial session acquisition, TOTP code generation from the
``local_seed`` provider, token-age tracking, and proactive refresh before
the JWT expires. A single ``SmartConnect`` instance is created once and
reused across all refreshes to avoid multiplying logzero artefacts in the
working directory.

Security constraints
--------------------
- API key, password, TOTP secret, and generated TOTP codes are never
  written to structured log fields or exception messages.
- SDK exceptions are wrapped with only the exception *type* name; the
  original message (which may contain request parameters) is preserved
  only as the exception ``__cause__``, not in the log record.
- ``client_id`` (non-secret) is logged for correlation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pyotp
from SmartApi import SmartConnect

from lib.discovery._errors import SessionAcquireError, SessionRefreshError
from lib.discovery._models import SessionToken
from lib.logging._factory import get_logger

if TYPE_CHECKING:
    from lib.config._settings import BNOSettings

# Angel One JWT tokens expire after ~8 hours. Refresh is triggered when
# token age ≥ SESSION_DURATION_MINUTES − settings.smartapi_token_refresh_buffer_minutes.
_SESSION_DURATION_MINUTES: int = 480


# ── Mockable helper ────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── SmartAPISession ────────────────────────────────────────────────────────────


class SmartAPISession:
    """Authentication lifecycle manager for one discovery phase run.

    Parameters
    ----------
    settings:
        Platform settings. The session reads ``smartapi_api_key``,
        ``smartapi_client_id``, ``smartapi_password``,
        ``smartapi_totp_provider``, ``smartapi_totp_secret``, and
        ``smartapi_token_refresh_buffer_minutes``.

    Usage::

        session = SmartAPISession(settings)
        session.connect()                  # initial auth; retries once

        for tick in scheduler.ticks():
            session.refresh_if_needed()    # noop if token is fresh
            data = chain_fetcher.fetch(session.smart)
    """

    def __init__(self, settings: BNOSettings) -> None:
        self._settings = settings
        self._smart: SmartConnect | None = None
        self._token: SessionToken | None = None
        self._log = get_logger("session")

    # ── Public properties ──────────────────────────────────────────────────────

    @property
    def smart(self) -> SmartConnect:
        """Return the authenticated ``SmartConnect`` instance.

        Raises
        ------
        SessionAcquireError
            If ``connect()`` has not completed successfully.
        """
        if self._smart is None:
            raise SessionAcquireError(
                "Session not connected — call connect() first."
            )
        return self._smart

    @property
    def token(self) -> SessionToken:
        """Return the current ``SessionToken``.

        Raises
        ------
        SessionAcquireError
            If ``connect()`` has not completed successfully.
        """
        if self._token is None:
            raise SessionAcquireError(
                "Session not connected — call connect() first."
            )
        return self._token

    @property
    def is_connected(self) -> bool:
        """True if ``connect()`` has completed successfully at least once."""
        return self._token is not None

    # ── Public methods ─────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Acquire the initial session token. Retries once on failure.

        A second attempt is made with a freshly generated TOTP code so that
        a code that expired between generation and the server-side check does
        not permanently block authentication.

        Raises
        ------
        SessionAcquireError
            If both authentication attempts fail. The ``attempt`` attribute
            on the exception is 2 when this is raised from ``connect()``.
        """
        try:
            self._do_auth(attempt=1)
        except SessionAcquireError:
            self._log.warning(
                "session_acquire_retrying",
                extra={"client_id": self._settings.smartapi_client_id, "attempt": 1},
            )
            self._do_auth(attempt=2)

    def refresh_if_needed(self) -> bool:
        """Refresh the session token if it is approaching expiry.

        Returns
        -------
        bool
            True if a refresh was performed; False if the token is still
            within the valid window.

        Raises
        ------
        SessionRefreshError
            If the session has not been acquired (``connect()`` not called),
            or if re-authentication fails during the refresh attempt.
            Unlike ``connect()``, refresh does not retry.
        """
        if self._token is None:
            raise SessionRefreshError(
                "Cannot refresh: session has not been acquired. "
                "Call connect() first."
            )
        if not self._needs_refresh():
            return False

        age_minutes = int(
            (_utc_now() - self._token.acquired_at).total_seconds() / 60
        )
        self._log.info(
            "session_refresh_triggered",
            extra={
                "client_id": self._settings.smartapi_client_id,
                "token_age_minutes": age_minutes,
            },
        )
        try:
            self._do_auth(attempt=1)
        except SessionAcquireError as exc:
            raise SessionRefreshError(f"Session refresh failed: {exc}") from exc
        return True

    # ── Internal ───────────────────────────────────────────────────────────────

    def _needs_refresh(self) -> bool:
        """Return True if the token age has reached the proactive-refresh threshold."""
        if self._token is None:
            return False
        age_s = (_utc_now() - self._token.acquired_at).total_seconds()
        threshold_s = (
            _SESSION_DURATION_MINUTES
            - self._settings.smartapi_token_refresh_buffer_minutes
        ) * 60
        return age_s >= threshold_s

    def _do_auth(self, attempt: int = 1) -> None:
        """Perform one authentication attempt.

        Creates the ``SmartConnect`` instance on the first call and reuses it
        on subsequent calls (refresh). TOTP is generated fresh on every call.

        Raises
        ------
        SessionAcquireError
            On API failure (``status: false``) or SDK exception.
        """
        settings = self._settings
        api_key: str = settings.smartapi_api_key.get_secret_value()
        client_id: str = settings.smartapi_client_id
        password: str = settings.smartapi_password.get_secret_value()

        # Generate TOTP before touching SmartConnect so partial state is avoided
        # if TOTP generation fails (e.g., missing secret).
        totp_code = self._generate_totp()

        # Create SmartConnect once; refresh reuses the existing instance to
        # avoid creating multiple logzero log files in the working directory.
        if self._smart is None:
            self._smart = SmartConnect(api_key=api_key)

        try:
            response: dict[str, object] = self._smart.generateSession(
                clientCode=client_id,
                password=password,
                totp=totp_code,
            )
        except Exception as exc:
            # Do NOT propagate str(exc) — SmartAPI SDK exceptions may include
            # request parameters (API key, password) in the message string.
            raise SessionAcquireError(
                f"generateSession raised {type(exc).__name__} (attempt {attempt})",
                attempt=attempt,
            ) from exc

        if not response.get("status"):
            error_code = str(response.get("errorcode") or "")
            message = str(response.get("message") or "unknown error")
            raise SessionAcquireError(
                f"Authentication failed [{error_code}]: {message} (attempt {attempt})",
                attempt=attempt,
            )

        data: dict[str, object] = dict(response.get("data") or {})
        acquired_at = _utc_now()

        self._token = SessionToken(
            jwt_token=str(data.get("jwtToken", "")),
            refresh_token=str(data.get("refreshToken", "")),
            feed_token=str(data.get("feedToken", "")),
            acquired_at=acquired_at,
            user_profile=data,
        )

        self._log.info(
            "session_acquired",
            extra={
                "client_id": client_id,
                "attempt": attempt,
                "jwt_present": bool(data.get("jwtToken")),
                "refresh_present": bool(data.get("refreshToken")),
                "feed_present": bool(data.get("feedToken")),
            },
        )

    def _generate_totp(self) -> str:
        """Generate a fresh TOTP code from the ``local_seed`` provider."""
        settings = self._settings
        provider: str = settings.smartapi_totp_provider

        if provider != "local_seed":
            raise SessionAcquireError(
                f"Unsupported TOTP provider: {provider!r}. "
                "Only 'local_seed' is supported in the discovery phase."
            )
        if settings.smartapi_totp_secret is None:
            raise SessionAcquireError(
                "BNO_SMARTAPI_TOTP_SECRET is required for the local_seed provider "
                "but is not set."
            )

        secret: str = settings.smartapi_totp_secret.get_secret_value()
        # pyotp.TOTP.now() returns the current 30-second window code.
        # A new TOTP object is created on every call so the code is always fresh.
        return pyotp.TOTP(secret).now()
