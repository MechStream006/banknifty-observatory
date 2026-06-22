"""Tests for lib.discovery.session: SmartAPISession."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from lib.discovery._errors import SessionAcquireError, SessionRefreshError
from lib.discovery._models import SessionToken
from lib.discovery.session import SmartAPISession, _SESSION_DURATION_MINUTES

_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_API_KEY   = "test_api_key_value"
_CLIENT_ID = "TEST123"
_PASSWORD  = "test_password_value"
_TOTP_SECRET = "JBSWY3DPEHPK3PXP"
_TOTP_CODE   = "482916"

_SUCCESS_DATA = {
    "jwtToken":     "Bearer eyJ.test.jwt",
    "refreshToken": "test_refresh_token",
    "feedToken":    "test_feed_token",
    "clientcode":   _CLIENT_ID,
    "name":         "Test User",
}

_FAIL_RESPONSE = {
    "status":    False,
    "message":   "Invalid OTP",
    "errorcode": "AB1010",
    "data":      None,
}

_SUCCESS_RESPONSE = {
    "status":    True,
    "message":   "SUCCESS",
    "errorcode": "",
    "data":      _SUCCESS_DATA,
}


def _mock_settings(**overrides: object) -> MagicMock:
    """Return a MagicMock that mimics BNOSettings for session tests."""
    s = MagicMock()
    s.smartapi_api_key.get_secret_value.return_value = _API_KEY
    s.smartapi_client_id = _CLIENT_ID
    s.smartapi_password.get_secret_value.return_value = _PASSWORD
    s.smartapi_totp_provider = "local_seed"
    s.smartapi_totp_secret = MagicMock()
    s.smartapi_totp_secret.get_secret_value.return_value = _TOTP_SECRET
    s.smartapi_token_refresh_buffer_minutes = 10
    for key, val in overrides.items():
        setattr(s, key, val)
    return s


def _mock_sc_cls(
    *,
    status: bool = True,
    data: dict | None = None,
    errorcode: str = "",
    message: str = "SUCCESS",
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Return a mock SmartConnect *class* with configurable generateSession behaviour."""
    instance = MagicMock()
    if raise_exc is not None:
        instance.generateSession.side_effect = raise_exc
    else:
        instance.generateSession.return_value = {
            "status":    status,
            "message":   message,
            "errorcode": errorcode,
            "data":      data if data is not None else (_SUCCESS_DATA if status else None),
        }
    cls = MagicMock(return_value=instance)
    return cls


def _patched_session(
    sc_cls: MagicMock | None = None,
    totp_code: str = _TOTP_CODE,
    settings: MagicMock | None = None,
) -> tuple[SmartAPISession, MagicMock, MagicMock]:
    """Context-manager helper that patches SmartConnect and pyotp."""
    # Not used as a context manager directly — callers open their own with-blocks.
    raise NotImplementedError  # intentionally not used; callers patch inline


# ===========================================================================
# Initial state
# ===========================================================================


class TestInitialState:
    def test_is_not_connected_after_init(self) -> None:
        session = SmartAPISession(_mock_settings())
        assert session.is_connected is False

    def test_smart_raises_before_connect(self) -> None:
        session = SmartAPISession(_mock_settings())
        with pytest.raises(SessionAcquireError, match="not connected"):
            _ = session.smart

    def test_token_raises_before_connect(self) -> None:
        session = SmartAPISession(_mock_settings())
        with pytest.raises(SessionAcquireError, match="not connected"):
            _ = session.token


# ===========================================================================
# TOTP generation
# ===========================================================================


class TestTotpGeneration:
    def test_calls_pyotp_with_secret(self) -> None:
        session = SmartAPISession(_mock_settings())
        with patch("lib.discovery.session.pyotp") as mock_pyotp:
            mock_pyotp.TOTP.return_value.now.return_value = _TOTP_CODE
            session._generate_totp()
        mock_pyotp.TOTP.assert_called_once_with(_TOTP_SECRET)

    def test_calls_get_secret_value_on_secret_field(self) -> None:
        settings = _mock_settings()
        session = SmartAPISession(settings)
        with patch("lib.discovery.session.pyotp") as mock_pyotp:
            mock_pyotp.TOTP.return_value.now.return_value = _TOTP_CODE
            session._generate_totp()
        settings.smartapi_totp_secret.get_secret_value.assert_called_once()

    def test_returns_code_from_pyotp_now(self) -> None:
        session = SmartAPISession(_mock_settings())
        with patch("lib.discovery.session.pyotp") as mock_pyotp:
            mock_pyotp.TOTP.return_value.now.return_value = "999888"
            code = session._generate_totp()
        assert code == "999888"

    def test_generates_fresh_code_on_each_call(self) -> None:
        session = SmartAPISession(_mock_settings())
        with patch("lib.discovery.session.pyotp") as mock_pyotp:
            mock_totp_inst = MagicMock()
            mock_pyotp.TOTP.return_value = mock_totp_inst
            mock_totp_inst.now.side_effect = ["111111", "222222"]
            c1 = session._generate_totp()
            c2 = session._generate_totp()
        assert c1 == "111111"
        assert c2 == "222222"
        assert mock_totp_inst.now.call_count == 2

    def test_unsupported_provider_raises(self) -> None:
        settings = _mock_settings(smartapi_totp_provider="authenticator_app")
        session = SmartAPISession(settings)
        with pytest.raises(SessionAcquireError, match="Unsupported TOTP provider"):
            session._generate_totp()

    def test_missing_totp_secret_raises(self) -> None:
        settings = _mock_settings(smartapi_totp_secret=None)
        session = SmartAPISession(settings)
        with pytest.raises(SessionAcquireError, match="TOTP_SECRET"):
            session._generate_totp()


# ===========================================================================
# connect() — success
# ===========================================================================


class TestConnectSuccess:
    def test_is_connected_after_connect(self) -> None:
        sc = _mock_sc_cls()
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        assert session.is_connected is True

    def test_creates_smart_connect_with_api_key(self) -> None:
        sc = _mock_sc_cls()
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        sc.assert_called_once_with(api_key=_API_KEY)

    def test_calls_generate_session_with_correct_args(self) -> None:
        sc = _mock_sc_cls()
        instance = sc.return_value
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        instance.generateSession.assert_called_once_with(
            clientCode=_CLIENT_ID,
            password=_PASSWORD,
            totp=_TOTP_CODE,
        )

    def test_smart_property_returns_smart_connect_instance(self) -> None:
        sc = _mock_sc_cls()
        instance = sc.return_value
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        assert session.smart is instance


# ===========================================================================
# connect() — failure and retry
# ===========================================================================


class TestConnectRetry:
    def test_retries_once_on_first_failure(self) -> None:
        instance = MagicMock()
        instance.generateSession.side_effect = [_FAIL_RESPONSE, _SUCCESS_RESPONSE]
        sc = MagicMock(return_value=instance)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        assert instance.generateSession.call_count == 2
        assert session.is_connected is True

    def test_second_attempt_uses_fresh_totp(self) -> None:
        instance = MagicMock()
        instance.generateSession.side_effect = [_FAIL_RESPONSE, _SUCCESS_RESPONSE]
        sc = MagicMock(return_value=instance)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mock_totp_inst = MagicMock()
            mt.return_value = mock_totp_inst
            mock_totp_inst.now.side_effect = ["111111", "222222"]
            session = SmartAPISession(_mock_settings())
            session.connect()
        # TOTP.now() called once per _do_auth call → twice total
        assert mock_totp_inst.now.call_count == 2

    def test_raises_with_attempt_2_after_two_failures(self) -> None:
        sc = _mock_sc_cls(status=False, errorcode="AB1010", message="Invalid OTP")
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            with pytest.raises(SessionAcquireError) as exc_info:
                session.connect()
        assert exc_info.value.attempt == 2

    def test_raises_session_acquire_error_on_sdk_exception(self) -> None:
        sc = _mock_sc_cls(raise_exc=ConnectionError("host unreachable"))
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            with pytest.raises(SessionAcquireError):
                session.connect()


# ===========================================================================
# SmartConnect reuse
# ===========================================================================


class TestSmartConnectReuse:
    def test_smart_connect_created_only_once_during_connect(self) -> None:
        sc = _mock_sc_cls()
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        sc.assert_called_once()

    def test_refresh_reuses_existing_smart_connect(self) -> None:
        sc = _mock_sc_cls()
        instance = sc.return_value
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        t1 = t0 + timedelta(minutes=471)

        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE

            with patch("lib.discovery.session._utc_now", return_value=t0):
                session = SmartAPISession(_mock_settings())
                session.connect()

            with patch("lib.discovery.session._utc_now", return_value=t1):
                session.refresh_if_needed()

        sc.assert_called_once()  # SmartConnect created only once
        assert instance.generateSession.call_count == 2  # connect + refresh


# ===========================================================================
# _needs_refresh
# ===========================================================================


class TestNeedsRefresh:
    def _connected_session(self, acquired_at: datetime) -> SmartAPISession:
        sc = _mock_sc_cls()
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=acquired_at):
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        return session

    def test_false_before_connect(self) -> None:
        session = SmartAPISession(_mock_settings())
        assert session._needs_refresh() is False

    def test_false_when_token_is_fresh(self) -> None:
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(t0)
        t_fresh = t0 + timedelta(minutes=30)
        with patch("lib.discovery.session._utc_now", return_value=t_fresh):
            assert session._needs_refresh() is False

    def test_true_when_token_exceeds_threshold(self) -> None:
        # Threshold = (480 − 10) × 60 = 28 200 s = 470 min
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(t0)
        t_stale = t0 + timedelta(minutes=471)
        with patch("lib.discovery.session._utc_now", return_value=t_stale):
            assert session._needs_refresh() is True

    def test_boundary_just_below_threshold_is_false(self) -> None:
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(t0)
        t_just_under = t0 + timedelta(minutes=469)
        with patch("lib.discovery.session._utc_now", return_value=t_just_under):
            assert session._needs_refresh() is False

    def test_boundary_exactly_at_threshold_is_true(self) -> None:
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(t0)
        t_exact = t0 + timedelta(minutes=470)
        with patch("lib.discovery.session._utc_now", return_value=t_exact):
            assert session._needs_refresh() is True

    def test_respects_configured_buffer_minutes(self) -> None:
        # buffer_minutes = 20 → threshold at 460 min
        settings = _mock_settings(smartapi_token_refresh_buffer_minutes=20)
        sc = _mock_sc_cls()
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=t0):
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(settings)
            session.connect()

        t_461 = t0 + timedelta(minutes=461)
        t_459 = t0 + timedelta(minutes=459)
        with patch("lib.discovery.session._utc_now", return_value=t_461):
            assert session._needs_refresh() is True
        with patch("lib.discovery.session._utc_now", return_value=t_459):
            assert session._needs_refresh() is False


# ===========================================================================
# refresh_if_needed()
# ===========================================================================


class TestRefreshIfNeeded:
    def _connected_session(self, sc: MagicMock, t0: datetime) -> SmartAPISession:
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=t0):
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        return session

    def test_returns_false_when_not_needed(self) -> None:
        sc = _mock_sc_cls()
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(sc, t0)
        t_fresh = t0 + timedelta(minutes=30)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=t_fresh):
            mt.return_value.now.return_value = _TOTP_CODE
            result = session.refresh_if_needed()
        assert result is False

    def test_returns_true_when_refresh_performed(self) -> None:
        sc = _mock_sc_cls()
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(sc, t0)
        t_stale = t0 + timedelta(minutes=471)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=t_stale):
            mt.return_value.now.return_value = _TOTP_CODE
            result = session.refresh_if_needed()
        assert result is True

    def test_raises_session_refresh_error_if_not_connected(self) -> None:
        session = SmartAPISession(_mock_settings())
        with pytest.raises(SessionRefreshError, match="not been acquired"):
            session.refresh_if_needed()

    def test_raises_session_refresh_error_on_api_failure(self) -> None:
        sc = _mock_sc_cls()
        instance = sc.return_value
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(sc, t0)

        # Make the *next* generateSession call fail (refresh attempt)
        instance.generateSession.return_value = _FAIL_RESPONSE

        t_stale = t0 + timedelta(minutes=471)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=t_stale):
            mt.return_value.now.return_value = _TOTP_CODE
            with pytest.raises(SessionRefreshError):
                session.refresh_if_needed()

    def test_no_retry_on_refresh_failure(self) -> None:
        # Unlike connect(), refresh_if_needed() does NOT retry on failure.
        sc = _mock_sc_cls()
        instance = sc.return_value
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(sc, t0)

        # Record call count after connect (= 1), then make refresh fail
        calls_after_connect = instance.generateSession.call_count
        instance.generateSession.return_value = _FAIL_RESPONSE

        t_stale = t0 + timedelta(minutes=471)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=t_stale):
            mt.return_value.now.return_value = _TOTP_CODE
            with pytest.raises(SessionRefreshError):
                session.refresh_if_needed()

        # Exactly one refresh attempt — no retry
        assert instance.generateSession.call_count == calls_after_connect + 1

    def test_fresh_totp_used_for_refresh(self) -> None:
        sc = _mock_sc_cls()
        instance = sc.return_value
        t0 = datetime(2026, 6, 22, 9, 15, tzinfo=_UTC)
        session = self._connected_session(sc, t0)

        t_stale = t0 + timedelta(minutes=471)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=t_stale):
            mock_totp_inst = MagicMock()
            mt.return_value = mock_totp_inst
            mock_totp_inst.now.return_value = "refresh_code"
            session.refresh_if_needed()

        # Verify the TOTP code used for the refresh call
        last_call_kwargs = instance.generateSession.call_args
        assert last_call_kwargs.kwargs["totp"] == "refresh_code"


# ===========================================================================
# Token structure
# ===========================================================================


class TestTokenStructure:
    def _session_with_data(self, data: dict) -> SmartAPISession:
        sc = _mock_sc_cls(data=data)
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        return session

    def test_jwt_token_populated_from_response(self) -> None:
        session = self._session_with_data({**_SUCCESS_DATA, "jwtToken": "my_jwt"})
        assert session.token.jwt_token == "my_jwt"

    def test_refresh_token_populated_from_response(self) -> None:
        session = self._session_with_data({**_SUCCESS_DATA, "refreshToken": "my_refresh"})
        assert session.token.refresh_token == "my_refresh"

    def test_feed_token_populated_from_response(self) -> None:
        session = self._session_with_data({**_SUCCESS_DATA, "feedToken": "my_feed"})
        assert session.token.feed_token == "my_feed"

    def test_acquired_at_is_utc_timezone(self) -> None:
        session = self._session_with_data(_SUCCESS_DATA)
        assert session.token.acquired_at.tzinfo is _UTC

    def test_acquired_at_reflects_auth_time(self) -> None:
        fixed_time = datetime(2026, 6, 22, 9, 15, 0, tzinfo=_UTC)
        sc = _mock_sc_cls()
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt, \
             patch("lib.discovery.session._utc_now", return_value=fixed_time):
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            session.connect()
        assert session.token.acquired_at == fixed_time

    def test_user_profile_contains_response_fields(self) -> None:
        data = {**_SUCCESS_DATA, "extraField": "extraValue"}
        session = self._session_with_data(data)
        assert "extraField" in session.token.user_profile
        assert session.token.user_profile["extraField"] == "extraValue"

    def test_token_is_session_token_instance(self) -> None:
        session = self._session_with_data(_SUCCESS_DATA)
        assert isinstance(session.token, SessionToken)


# ===========================================================================
# Secret safety in exception messages
# ===========================================================================


class TestSecretSafety:
    def test_exception_message_excludes_password(self) -> None:
        sc = _mock_sc_cls(status=False, errorcode="AB1010", message="Invalid OTP")
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            with pytest.raises(SessionAcquireError) as exc_info:
                session.connect()
        assert _PASSWORD not in str(exc_info.value)

    def test_exception_message_excludes_api_key(self) -> None:
        sc = _mock_sc_cls(raise_exc=RuntimeError("sdk_internal_error"))
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            with pytest.raises(SessionAcquireError) as exc_info:
                session.connect()
        assert _API_KEY not in str(exc_info.value)

    def test_exception_message_excludes_totp_code(self) -> None:
        distinctive_code = "987654"
        sc = _mock_sc_cls(status=False, errorcode="AB1010", message="OTP expired")
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = distinctive_code
            session = SmartAPISession(_mock_settings())
            with pytest.raises(SessionAcquireError) as exc_info:
                session.connect()
        assert distinctive_code not in str(exc_info.value)

    def test_sdk_exception_type_included_not_message(self) -> None:
        # The SDK exception message is NOT included; only the type name is.
        sc = _mock_sc_cls(raise_exc=ValueError("secret_credential_in_error"))
        with patch("lib.discovery.session.SmartConnect", sc), \
             patch("lib.discovery.session.pyotp.TOTP") as mt:
            mt.return_value.now.return_value = _TOTP_CODE
            session = SmartAPISession(_mock_settings())
            with pytest.raises(SessionAcquireError) as exc_info:
                session.connect()
        error_str = str(exc_info.value)
        assert "ValueError" in error_str
        assert "secret_credential_in_error" not in error_str


# ===========================================================================
# Session duration constant
# ===========================================================================


class TestSessionDurationConstant:
    def test_session_duration_is_480_minutes(self) -> None:
        assert _SESSION_DURATION_MINUTES == 480
