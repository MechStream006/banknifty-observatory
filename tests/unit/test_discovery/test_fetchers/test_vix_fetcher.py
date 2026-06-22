"""Tests for lib.discovery.fetchers.vix: VIXFetcher."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lib.discovery._models import VIXResult
from lib.discovery.fetchers.vix import VIXFetcher, _EXCHANGE, _SYMBOL, _TOKEN

_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VIX_LTP = 14.37

_LTP_RESPONSE_OK: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "exchange":      _EXCHANGE,
        "tradingsymbol": _SYMBOL,
        "symboltoken":   _TOKEN,
        "ltp":           _VIX_LTP,
    },
}

_LTP_RESPONSE_FAIL: dict[str, object] = {
    "status": False,
    "message": "Invalid session",
    "errorcode": "AB1006",
    "data": None,
}

_LTP_RESPONSE_MISSING_LTP: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "exchange": _EXCHANGE,
        "tradingsymbol": _SYMBOL,
        # "ltp" key absent
    },
}

_LTP_RESPONSE_ZERO_LTP: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {"ltp": 0},
}

_LTP_RESPONSE_NULL_LTP: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {"ltp": None},
}


def _mock_smart(
    *,
    ltp_result: dict[str, object] | None = None,
    ltp_exc: Exception | None = None,
) -> MagicMock:
    smart = MagicMock()
    if ltp_exc is not None:
        smart.ltpData.side_effect = ltp_exc
    else:
        smart.ltpData.return_value = ltp_result or _LTP_RESPONSE_OK
    return smart


def _fetcher() -> VIXFetcher:
    return VIXFetcher()


# ===========================================================================
# Construction
# ===========================================================================


class TestVIXFetcherInit:
    def test_instantiates_without_arguments(self) -> None:
        assert VIXFetcher() is not None

    def test_two_instances_are_independent(self) -> None:
        a, b = VIXFetcher(), VIXFetcher()
        assert a is not b


# ===========================================================================
# API call parameters
# ===========================================================================


class TestAPICallParameters:
    def test_calls_ltp_data_once(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        assert smart.ltpData.call_count == 1

    def test_passes_correct_exchange(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        assert smart.ltpData.call_args.kwargs["exchange"] == "NSE"

    def test_passes_correct_tradingsymbol(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        assert smart.ltpData.call_args.kwargs["tradingsymbol"] == "India VIX"

    def test_passes_correct_symboltoken(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        assert smart.ltpData.call_args.kwargs["symboltoken"] == "1333"

    def test_module_constants_match_call(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        kwargs = smart.ltpData.call_args.kwargs
        assert kwargs["exchange"] == _EXCHANGE
        assert kwargs["tradingsymbol"] == _SYMBOL
        assert kwargs["symboltoken"] == _TOKEN


# ===========================================================================
# Successful response
# ===========================================================================


class TestFetchSuccess:
    def test_returns_vix_result(self) -> None:
        smart = _mock_smart()
        assert isinstance(_fetcher().fetch(smart), VIXResult)

    def test_success_is_true(self) -> None:
        smart = _mock_smart()
        assert _fetcher().fetch(smart).success is True

    def test_ltp_equals_response_value(self) -> None:
        smart = _mock_smart()
        assert _fetcher().fetch(smart).ltp == _VIX_LTP

    def test_ltp_is_float(self) -> None:
        smart = _mock_smart()
        assert isinstance(_fetcher().fetch(smart).ltp, float)

    def test_error_is_none(self) -> None:
        smart = _mock_smart()
        assert _fetcher().fetch(smart).error is None

    def test_raw_response_is_the_api_response(self) -> None:
        smart = _mock_smart()
        result = _fetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_OK

    def test_integer_ltp_coerced_to_float(self) -> None:
        # API may return ltp as int (e.g. 14 not 14.0)
        response = {**_LTP_RESPONSE_OK, "data": {"ltp": 14}}
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is True
        assert result.ltp == 14.0
        assert isinstance(result.ltp, float)


# ===========================================================================
# UTC timestamp
# ===========================================================================


class TestUTCTimestamp:
    def test_fetched_at_is_datetime(self) -> None:
        smart = _mock_smart()
        assert isinstance(_fetcher().fetch(smart).fetched_at, datetime)

    def test_fetched_at_tzinfo_is_utc(self) -> None:
        smart = _mock_smart()
        assert _fetcher().fetch(smart).fetched_at.tzinfo == _UTC

    def test_fetched_at_tzinfo_is_utc_on_failure(self) -> None:
        smart = _mock_smart(ltp_exc=RuntimeError("down"))
        assert _fetcher().fetch(smart).fetched_at.tzinfo == _UTC

    def test_fetched_at_uses_utc_now_mockable(self) -> None:
        fixed = datetime(2026, 6, 22, 9, 30, 0, tzinfo=_UTC)
        with patch("lib.discovery.fetchers.vix._utc_now", return_value=fixed):
            smart = _mock_smart()
            result = _fetcher().fetch(smart)
        assert result.fetched_at == fixed


# ===========================================================================
# Latency tracking
# ===========================================================================


class TestLatencyTracking:
    def test_latency_is_non_negative_on_success(self) -> None:
        smart = _mock_smart()
        assert _fetcher().fetch(smart).latency_ms >= 0.0

    def test_latency_is_non_negative_on_failure(self) -> None:
        smart = _mock_smart(ltp_exc=RuntimeError("fail"))
        assert _fetcher().fetch(smart).latency_ms >= 0.0

    def test_latency_measured_from_t0_to_return(self) -> None:
        monotonic_vals = [100.0, 101.5]  # 1500 ms
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=monotonic_vals):
            smart = _mock_smart()
            result = _fetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(1500.0, abs=1.0)

    def test_latency_rounded_to_two_decimal_places(self) -> None:
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=[100.0, 100.123456]):
            smart = _mock_smart()
            result = _fetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(123.46, abs=0.01)

    def test_latency_measured_on_sdk_exception(self) -> None:
        monotonic_vals = [100.0, 100.25]  # 250 ms until exception raised
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=monotonic_vals):
            smart = _mock_smart(ltp_exc=ConnectionError("reset"))
            result = _fetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(250.0, abs=1.0)

    def test_latency_measured_on_api_failure(self) -> None:
        monotonic_vals = [100.0, 100.1]
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=monotonic_vals):
            smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
            result = _fetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(100.0, abs=1.0)


# ===========================================================================
# SDK exception handling
# ===========================================================================


class TestSDKException:
    def test_returns_vix_result_not_raises(self) -> None:
        smart = _mock_smart(ltp_exc=RuntimeError("connection reset"))
        assert isinstance(_fetcher().fetch(smart), VIXResult)

    def test_success_is_false(self) -> None:
        smart = _mock_smart(ltp_exc=RuntimeError("connection reset"))
        assert _fetcher().fetch(smart).success is False

    def test_ltp_is_none(self) -> None:
        smart = _mock_smart(ltp_exc=RuntimeError("reset"))
        assert _fetcher().fetch(smart).ltp is None

    def test_raw_response_is_none(self) -> None:
        smart = _mock_smart(ltp_exc=ConnectionError("refused"))
        assert _fetcher().fetch(smart).raw_response is None

    def test_error_contains_exception_type_name(self) -> None:
        smart = _mock_smart(ltp_exc=ValueError("internal"))
        error = _fetcher().fetch(smart).error or ""
        assert "ValueError" in error

    def test_error_does_not_contain_exception_message(self) -> None:
        smart = _mock_smart(ltp_exc=ValueError("secret_internal_detail"))
        error = _fetcher().fetch(smart).error or ""
        assert "secret_internal_detail" not in error

    def test_connection_error_handled(self) -> None:
        smart = _mock_smart(ltp_exc=ConnectionError("no route to host"))
        assert _fetcher().fetch(smart).success is False

    def test_os_error_handled(self) -> None:
        smart = _mock_smart(ltp_exc=OSError("socket timeout"))
        assert _fetcher().fetch(smart).success is False


# ===========================================================================
# API-level failure (status=False)
# ===========================================================================


class TestAPIFailure:
    def test_success_is_false_on_status_false(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        assert _fetcher().fetch(smart).success is False

    def test_ltp_is_none_on_status_false(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        assert _fetcher().fetch(smart).ltp is None

    def test_raw_response_preserved_on_status_false(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        assert _fetcher().fetch(smart).raw_response is _LTP_RESPONSE_FAIL

    def test_error_contains_errorcode(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        error = _fetcher().fetch(smart).error or ""
        assert "AB1006" in error

    def test_error_contains_message(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        error = _fetcher().fetch(smart).error or ""
        assert "Invalid session" in error

    def test_empty_errorcode_in_error_string(self) -> None:
        fail_no_code: dict[str, object] = {
            "status": False, "message": "Rate limit hit", "errorcode": "", "data": None,
        }
        smart = _mock_smart(ltp_result=fail_no_code)
        error = _fetcher().fetch(smart).error or ""
        # errorcode is empty → [] appears in error string
        assert "Rate limit hit" in error

    def test_returns_vix_result_not_raises(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        assert isinstance(_fetcher().fetch(smart), VIXResult)

    def test_unexpected_response_type_returns_failure(self) -> None:
        smart = MagicMock()
        smart.ltpData.return_value = ["not", "a", "dict"]
        result = _fetcher().fetch(smart)
        assert result.success is False
        assert result.raw_response is None

    def test_unexpected_response_type_error_mentions_type(self) -> None:
        smart = MagicMock()
        smart.ltpData.return_value = ["not", "a", "dict"]
        error = _fetcher().fetch(smart).error or ""
        assert "list" in error


# ===========================================================================
# Missing LTP
# ===========================================================================


class TestMissingLTP:
    def test_absent_ltp_key_returns_failure(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP)
        assert _fetcher().fetch(smart).success is False

    def test_absent_ltp_key_ltp_is_none(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP)
        assert _fetcher().fetch(smart).ltp is None

    def test_absent_ltp_key_raw_response_preserved(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP)
        assert _fetcher().fetch(smart).raw_response is _LTP_RESPONSE_MISSING_LTP

    def test_none_ltp_value_returns_failure(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_NULL_LTP)
        assert _fetcher().fetch(smart).success is False

    def test_none_ltp_value_ltp_is_none(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_NULL_LTP)
        assert _fetcher().fetch(smart).ltp is None

    def test_none_ltp_raw_response_preserved(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_NULL_LTP)
        assert _fetcher().fetch(smart).raw_response is _LTP_RESPONSE_NULL_LTP

    def test_data_field_not_dict_returns_failure(self) -> None:
        response = {"status": True, "message": "SUCCESS", "errorcode": "", "data": None}
        smart = _mock_smart(ltp_result=response)
        assert _fetcher().fetch(smart).success is False

    def test_string_ltp_returns_failure(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"ltp": "14.37"},  # string, not numeric
        }
        smart = _mock_smart(ltp_result=response)
        assert _fetcher().fetch(smart).success is False

    def test_error_mentions_invalid_ltp_value(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP)
        error = _fetcher().fetch(smart).error or ""
        assert "ltp" in error.lower()


# ===========================================================================
# Zero LTP
# ===========================================================================


class TestZeroLTP:
    def test_zero_ltp_returns_failure(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        assert _fetcher().fetch(smart).success is False

    def test_zero_ltp_ltp_is_none(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        assert _fetcher().fetch(smart).ltp is None

    def test_zero_ltp_raw_response_preserved(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        assert _fetcher().fetch(smart).raw_response is _LTP_RESPONSE_ZERO_LTP

    def test_zero_ltp_error_mentions_value(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        error = _fetcher().fetch(smart).error or ""
        assert "0" in error

    def test_negative_ltp_also_treated_as_invalid(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"ltp": -5.0},
        }
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is False
        assert result.ltp is None


# ===========================================================================
# Raw payload preservation
# ===========================================================================


class TestRawPayloadPreservation:
    def test_raw_response_is_verbatim_api_dict_on_success(self) -> None:
        smart = _mock_smart()
        result = _fetcher().fetch(smart)
        # raw_response is the exact object returned by the mock
        assert result.raw_response is _LTP_RESPONSE_OK

    def test_raw_response_contains_ltp_on_success(self) -> None:
        smart = _mock_smart()
        result = _fetcher().fetch(smart)
        assert result.raw_response is not None
        assert result.raw_response["data"]["ltp"] == _VIX_LTP  # type: ignore[index]

    def test_raw_response_is_none_on_sdk_exception(self) -> None:
        smart = _mock_smart(ltp_exc=RuntimeError("down"))
        assert _fetcher().fetch(smart).raw_response is None

    def test_raw_response_preserved_on_api_failure(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        result = _fetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_FAIL

    def test_raw_response_preserved_on_missing_ltp(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP)
        result = _fetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_MISSING_LTP

    def test_raw_response_preserved_on_zero_ltp(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        result = _fetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_ZERO_LTP

    def test_raw_response_is_none_on_non_dict_response(self) -> None:
        smart = MagicMock()
        smart.ltpData.return_value = 42
        result = _fetcher().fetch(smart)
        assert result.raw_response is None


# ===========================================================================
# fetch() never raises
# ===========================================================================


class TestFetchNeverRaises:
    def test_does_not_raise_on_sdk_exception(self) -> None:
        smart = _mock_smart(ltp_exc=Exception("any error"))
        _fetcher().fetch(smart)  # must not raise

    def test_does_not_raise_on_status_false(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        _fetcher().fetch(smart)

    def test_does_not_raise_on_missing_ltp(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP)
        _fetcher().fetch(smart)

    def test_does_not_raise_on_zero_ltp(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        _fetcher().fetch(smart)

    def test_does_not_raise_on_non_dict_response(self) -> None:
        smart = MagicMock()
        smart.ltpData.return_value = None
        _fetcher().fetch(smart)

    def test_always_returns_vix_result(self) -> None:
        cases = [
            _mock_smart(),
            _mock_smart(ltp_exc=RuntimeError("fail")),
            _mock_smart(ltp_result=_LTP_RESPONSE_FAIL),
            _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP),
            _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP),
        ]
        for smart in cases:
            assert isinstance(_fetcher().fetch(smart), VIXResult)
