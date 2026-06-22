"""
SpotFetcher — BankNifty spot index LTP retrieval.

Two source modes are supported at construction time:

``separate_call`` (default)
    Issues an independent ``ltpData()`` call for the ``"NIFTY BANK"`` index
    token (NSE:99926009). Latency is measured and reported. Use this when
    the ``getMarketData`` response does not include the underlying value.

``chain_embedded``
    Attempts to extract the underlying index price from a ``ChainResult``
    that has already been fetched this tick. No additional network call is
    made; ``latency_ms`` is always ``0.0``.

    Candidate fields searched in order, at two nesting levels:

    Level 1 — ``response["data"]`` (dict):
        ``underlyingValue``, ``indClosePrice``, ``underlyingClose``

    Level 2 — ``response["data"]["fetched"][0]`` (first row):
        same keys

    If none of the candidates is found, ``SpotResult.source`` is
    ``"unavailable"`` and ``success`` is ``False``.

Mode selection rationale
------------------------
The synthetic fixture ``tests/fixtures/chain_response_fixture.json`` has
**no embedded spot price** at any nesting level, so it cannot determine
whether the live API includes one. The smoke test (``scripts/smoke_test.py``)
uses a separate ``ltpData()`` call, which is the conservative path and
is therefore the default.

Once the smoke test produces a real ``chain_response.json``, inspect it for
the candidate field names listed above. If present, switch to
``chain_embedded`` to save one API call per tick.

fetch() ALWAYS returns SpotResult — it never raises.

Constants used for the separate call match ``scripts/smoke_test.py``:
    exchange      = ``"NSE"``
    tradingsymbol = ``"NIFTY BANK"``
    symboltoken   = ``"99926009"``
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from lib.discovery._errors import SpotFetchError  # noqa: F401 — re-exported for callers
from lib.discovery._models import ChainResult, SpotResult
from lib.logging._factory import get_logger

if TYPE_CHECKING:
    from SmartApi import SmartConnect

# ── Constants ──────────────────────────────────────────────────────────────────

_EXCHANGE     = "NSE"
_SYMBOL       = "NIFTY BANK"
_TOKEN        = "99926009"

# Field names to probe for an embedded underlying price in a getMarketData response.
# Searched at data-dict level first, then at the first fetched row.
# Only populated once a live smoke-test response confirms the field name.
_EMBEDDED_KEYS: tuple[str, ...] = (
    "underlyingValue",   # most common in SmartAPI FULL-mode responses
    "indClosePrice",     # alternate observed in some SDK versions
    "underlyingClose",   # seen in older SDK docs
)

# Valid source_mode strings
_MODE_SEPARATE = "separate_call"
_MODE_EMBEDDED = "chain_embedded"
_MODE_UNAVAILABLE = "unavailable"
_VALID_MODES: frozenset[str] = frozenset({_MODE_SEPARATE, _MODE_EMBEDDED})


# ── Mockable helpers ───────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _monotonic() -> float:
    return time.monotonic()


# ── SpotFetcher ────────────────────────────────────────────────────────────────


class SpotFetcher:
    """BankNifty spot index LTP retrieval with pluggable source mode.

    Parameters
    ----------
    source_mode:
        ``"separate_call"`` (default) or ``"chain_embedded"``.
        See module docstring for mode selection guidance.

    Raises
    ------
    ValueError
        If *source_mode* is not one of the valid mode strings.

    Usage::

        # Conservative default — always works
        spot_fetcher = SpotFetcher(source_mode="separate_call")

        # After smoke test confirms underlyingValue is present in chain response
        spot_fetcher = SpotFetcher(source_mode="chain_embedded")

        for tick in scheduler.ticks():
            chain_result = chain_fetcher.fetch(session.smart)
            spot_result  = spot_fetcher.fetch(session.smart, chain_result)
            archiver.write({"chain": chain_result.raw_response,
                            "spot_ltp": spot_result.ltp})
    """

    def __init__(self, source_mode: str = _MODE_SEPARATE) -> None:
        if source_mode not in _VALID_MODES:
            raise ValueError(
                f"Invalid source_mode: {source_mode!r}. "
                f"Must be one of: {sorted(_VALID_MODES)}"
            )
        self._source_mode = source_mode
        self._log = get_logger("spot_fetcher")

    # ── Public interface ───────────────────────────────────────────────────────

    @property
    def source_mode(self) -> str:
        """The configured source mode string."""
        return self._source_mode

    def fetch(
        self,
        smart: SmartConnect,
        chain_result: ChainResult | None = None,
    ) -> SpotResult:
        """Retrieve the BankNifty spot LTP.

        Always returns a ``SpotResult`` — never raises. Errors from the
        SmartAPI SDK or missing embedded fields are captured in
        ``SpotResult(success=False, error=...)``.

        Parameters
        ----------
        smart:
            Authenticated ``SmartConnect`` instance. Used only in
            ``"separate_call"`` mode; ignored in ``"chain_embedded"`` mode
            but still required so the call signature is uniform.
        chain_result:
            Required in ``"chain_embedded"`` mode — must be a successful
            ``ChainResult`` with a populated ``raw_response``. Ignored in
            ``"separate_call"`` mode.

        Returns
        -------
        SpotResult
            ``source`` is ``"separate_call"``, ``"chain_embedded"``, or
            ``"unavailable"``. ``success=True`` only when ``ltp`` is a
            positive finite float.
        """
        if self._source_mode == _MODE_EMBEDDED:
            return self._fetch_embedded(chain_result)
        return self._fetch_separate(smart)

    # ── Internal — separate call ───────────────────────────────────────────────

    def _fetch_separate(self, smart: SmartConnect) -> SpotResult:
        """Issue an independent ltpData() call for the NIFTY BANK index."""
        fetched_at = _utc_now()
        t0 = _monotonic()

        try:
            response: dict[str, object] = smart.ltpData(
                exchange=_EXCHANGE,
                tradingsymbol=_SYMBOL,
                symboltoken=_TOKEN,
            )
        except Exception as exc:
            latency_ms = (_monotonic() - t0) * 1000
            error = f"ltpData raised {type(exc).__name__}"
            self._log.error(
                "spot_separate_call_error",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "exc_type": type(exc).__name__,
                },
            )
            return SpotResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=None,
                source=_MODE_SEPARATE,
                error=error,
                success=False,
            )

        latency_ms = (_monotonic() - t0) * 1000

        if not isinstance(response, dict):
            error = f"ltpData returned unexpected type: {type(response).__name__}"
            self._log.error(
                "spot_unexpected_response_type",
                extra={"latency_ms": round(latency_ms, 2)},
            )
            return SpotResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=None,
                source=_MODE_SEPARATE,
                error=error,
                success=False,
            )

        if not response.get("status"):
            errorcode = str(response.get("errorcode") or "")
            message   = str(response.get("message") or "unknown error")
            error = f"ltpData failed [{errorcode}]: {message}"
            self._log.error(
                "spot_api_error",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "errorcode": errorcode,
                },
            )
            return SpotResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=response,
                source=_MODE_SEPARATE,
                error=error,
                success=False,
            )

        raw_data = response.get("data")
        raw_ltp = raw_data.get("ltp") if isinstance(raw_data, dict) else None
        ltp: float | None = (
            float(raw_ltp)
            if isinstance(raw_ltp, (int, float)) and raw_ltp != 0
            else None
        )

        if ltp is None:
            error = f"ltpData returned status=true but ltp={raw_ltp!r} is not a valid price"
            self._log.warning(
                "spot_invalid_ltp",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "ltp_raw": str(raw_ltp),
                },
            )
            return SpotResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=response,
                source=_MODE_SEPARATE,
                error=error,
                success=False,
            )

        self._log.info(
            "spot_ok",
            extra={
                "latency_ms": round(latency_ms, 2),
                "ltp": ltp,
                "source": _MODE_SEPARATE,
            },
        )
        return SpotResult(
            fetched_at=fetched_at,
            latency_ms=round(latency_ms, 2),
            ltp=ltp,
            raw_response=response,
            source=_MODE_SEPARATE,
            error=None,
            success=True,
        )

    # ── Internal — chain embedded ──────────────────────────────────────────────

    def _fetch_embedded(self, chain_result: ChainResult | None) -> SpotResult:
        """Extract spot LTP from a ChainResult already fetched this tick."""
        fetched_at = _utc_now()

        if chain_result is None or not chain_result.success or chain_result.raw_response is None:
            error = (
                "chain_embedded mode requires a successful ChainResult with raw_response "
                "— call chain_fetcher.fetch() first and pass the result"
            )
            self._log.warning(
                "spot_embedded_no_chain",
                extra={"chain_present": chain_result is not None},
            )
            return SpotResult(
                fetched_at=fetched_at,
                latency_ms=0.0,
                ltp=None,
                raw_response=None,
                source=_MODE_UNAVAILABLE,
                error=error,
                success=False,
            )

        ltp = self._extract_embedded_ltp(chain_result.raw_response)

        if ltp is None:
            candidates = ", ".join(_EMBEDDED_KEYS)
            error = (
                f"No embedded spot price found in chain response. "
                f"Searched: {candidates}. "
                "Switch source_mode to 'separate_call' or update _EMBEDDED_KEYS "
                "after inspecting a live chain_response.json."
            )
            self._log.warning(
                "spot_embedded_field_not_found",
                extra={"keys_searched": list(_EMBEDDED_KEYS)},
            )
            return SpotResult(
                fetched_at=fetched_at,
                latency_ms=0.0,
                ltp=None,
                raw_response=chain_result.raw_response,
                source=_MODE_UNAVAILABLE,
                error=error,
                success=False,
            )

        self._log.info(
            "spot_ok",
            extra={"ltp": ltp, "source": _MODE_EMBEDDED},
        )
        return SpotResult(
            fetched_at=fetched_at,
            latency_ms=0.0,
            ltp=ltp,
            raw_response=chain_result.raw_response,
            source=_MODE_EMBEDDED,
            error=None,
            success=True,
        )

    def _extract_embedded_ltp(
        self, raw_response: dict[str, object]
    ) -> float | None:
        """Search candidate field names at data-dict and first-row levels.

        Returns the first positive numeric value found, or None if none is
        present. Only called by ``_fetch_embedded()``.
        """
        data = raw_response.get("data")
        if not isinstance(data, dict):
            return None

        # Level 1: top of the data dict
        for key in _EMBEDDED_KEYS:
            val = data.get(key)
            if isinstance(val, (int, float)) and val > 0:
                return float(val)

        # Level 2: first fetched row
        fetched = data.get("fetched")
        if isinstance(fetched, list) and fetched:
            first_row = fetched[0]
            if isinstance(first_row, dict):
                for key in _EMBEDDED_KEYS:
                    val = first_row.get(key)
                    if isinstance(val, (int, float)) and val > 0:
                        return float(val)

        return None
