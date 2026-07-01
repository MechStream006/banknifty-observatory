"""Tests for lib.discovery.fetchers.vix: VIXFetcher (fixed-token ltpData)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lib.discovery._models import VIXResult
from lib.discovery.fetchers.vix import (
    VIXFetcher,
    _EXCHANGE,
    _EXPECTED_IDENTITY,
    _SYMBOLTOKEN,
    _TRADINGSYMBOL,
    _VIX_MAX,
    _VIX_MIN,
    _normalize,
)

_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VIX_LTP = 14.37
_VIX_SYMBOL = "INDIA VIX"

_LTP_RESPONSE_OK: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "exchange":      _EXCHANGE,
        "tradingsymbol": _VIX_SYMBOL,
        "symboltoken":   _SYMBOLTOKEN,
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
        "tradingsymbol": _VIX_SYMBOL,
        # "ltp" key absent
    },
}

_LTP_RESPONSE_ZERO_LTP: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": 0},
}

_LTP_RESPONSE_NULL_LTP: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": None},
}

# The proven production bug: token 1333 actually resolves to HDFCBANK-EQ.
# If the broker ever remaps/misroutes the fixed token again, the identity
# check must catch it via the response's own tradingsymbol.
_LTP_RESPONSE_WRONG_IDENTITY: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "exchange": _EXCHANGE,
        "tradingsymbol": "HDFCBANK-EQ",
        "symboltoken": "1333",
        "ltp": 1721.5,
    },
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
        smart.ltpData.return_value = ltp_result if ltp_result is not None else _LTP_RESPONSE_OK
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

    def test_token_is_fixed_verified_value(self) -> None:
        f = _fetcher()
        assert f.token == "99926017"
        assert f.symbol == "India VIX"

    def test_token_and_symbol_identical_across_instances(self) -> None:
        a, b = _fetcher(), _fetcher()
        assert a.token == b.token
        assert a.symbol == b.symbol


# ===========================================================================
# Normalisation helper
# ===========================================================================


class TestNormalize:
    def test_strips_and_uppercases(self) -> None:
        assert _normalize(" india vix ") == "INDIAVIX"

    def test_removes_internal_spaces(self) -> None:
        assert _normalize("India VIX") == "INDIAVIX"

    def test_matches_expected_identity_constant(self) -> None:
        assert _normalize("India VIX") == _EXPECTED_IDENTITY


# ===========================================================================
# Fixed-token ltpData call — no discovery, no searchScrip
# ===========================================================================


class TestFixedTokenCall:
    def test_ltp_data_called_once(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        assert smart.ltpData.call_count == 1

    def test_ltp_data_called_with_verified_token(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        kwargs = smart.ltpData.call_args.kwargs
        assert kwargs["symboltoken"] == "99926017"
        assert kwargs["tradingsymbol"] == _TRADINGSYMBOL
        assert kwargs["exchange"] == _EXCHANGE

    def test_no_search_scrip_attribute_accessed(self) -> None:
        smart = _mock_smart()
        _fetcher().fetch(smart)
        smart.searchScrip.assert_not_called()

    def test_ltp_data_called_once_per_tick_across_multiple_ticks(self) -> None:
        smart = _mock_smart()
        fetcher = _fetcher()
        fetcher.fetch(smart)
        fetcher.fetch(smart)
        fetcher.fetch(smart)
        assert smart.ltpData.call_count == 3
        smart.searchScrip.assert_not_called()

    def test_no_discovery_state_between_instances(self) -> None:
        smart = _mock_smart()
        a, b = _fetcher(), _fetcher()
        a.fetch(smart)
        assert a.token == b.token == "99926017"


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

    def test_raw_response_is_the_ltp_api_response(self) -> None:
        smart = _mock_smart()
        result = _fetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_OK

    def test_integer_ltp_coerced_to_float(self) -> None:
        response = {**_LTP_RESPONSE_OK, "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": 14}}
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
        monotonic_vals = [100.0, 100.5]  # 500 ms, single ltpData call
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=monotonic_vals):
            smart = _mock_smart()
            result = _fetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(500.0, abs=1.0)

    def test_latency_measured_on_sdk_exception(self) -> None:
        monotonic_vals = [100.0, 100.25]  # 250 ms
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=monotonic_vals):
            smart = _mock_smart(ltp_exc=ConnectionError("reset"))
            result = _fetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(250.0, abs=1.0)

    def test_latency_measured_on_api_failure(self) -> None:
        monotonic_vals = [100.0, 100.1]  # 100 ms
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=monotonic_vals):
            smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
            result = _fetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(100.0, abs=1.0)

    def test_latency_consistent_across_repeated_ticks(self) -> None:
        smart = _mock_smart()
        fetcher = _fetcher()
        fetcher.fetch(smart)
        monotonic_vals = [200.0, 200.05]
        with patch("lib.discovery.fetchers.vix._monotonic", side_effect=monotonic_vals):
            result = fetcher.fetch(smart)
        assert result.latency_ms == pytest.approx(50.0, abs=1.0)


# ===========================================================================
# SDK exception handling (ltpData)
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
        assert "Rate limit hit" in error

    def test_returns_vix_result_not_raises(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        assert isinstance(_fetcher().fetch(smart), VIXResult)

    def test_unexpected_response_type_returns_failure(self) -> None:
        smart = _mock_smart()
        smart.ltpData.return_value = ["not", "a", "dict"]
        result = _fetcher().fetch(smart)
        assert result.success is False
        assert result.raw_response is None

    def test_unexpected_response_type_error_mentions_type(self) -> None:
        smart = _mock_smart()
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
            "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": "14.37"},  # string, not numeric
        }
        smart = _mock_smart(ltp_result=response)
        assert _fetcher().fetch(smart).success is False

    def test_error_mentions_invalid_ltp_value(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP)
        error = _fetcher().fetch(smart).error or ""
        assert "ltp" in error.lower()


# ===========================================================================
# Value sanity band (zero / negative / out-of-band)
# ===========================================================================


class TestValueSanityBand:
    def test_zero_ltp_returns_failure(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        assert _fetcher().fetch(smart).success is False

    def test_zero_ltp_ltp_is_none(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        assert _fetcher().fetch(smart).ltp is None

    def test_zero_ltp_raw_response_preserved(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP)
        assert _fetcher().fetch(smart).raw_response is _LTP_RESPONSE_ZERO_LTP

    def test_negative_ltp_also_treated_as_invalid(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": -5.0},
        }
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is False
        assert result.ltp is None

    def test_ltp_above_band_treated_as_invalid(self) -> None:
        # e.g. an equity-scale price wrongly returned for the VIX token.
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": 1721.5},
        }
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is False
        assert result.ltp is None

    def test_ltp_at_lower_band_edge_is_valid(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": _VIX_MIN},
        }
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is True
        assert result.ltp == _VIX_MIN

    def test_ltp_at_upper_band_edge_is_valid(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": _VIX_MAX},
        }
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is True
        assert result.ltp == _VIX_MAX

    def test_just_below_lower_band_is_invalid(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": _VIX_MIN - 0.01},
        }
        smart = _mock_smart(ltp_result=response)
        assert _fetcher().fetch(smart).success is False

    def test_just_above_upper_band_is_invalid(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"tradingsymbol": _VIX_SYMBOL, "ltp": _VIX_MAX + 0.01},
        }
        smart = _mock_smart(ltp_result=response)
        assert _fetcher().fetch(smart).success is False


# ===========================================================================
# Response identity check — the regression guard for the token=1333 bug
# ===========================================================================


class TestResponseIdentityCheck:
    def test_wrong_identity_in_ltp_response_returns_failure(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_WRONG_IDENTITY)
        result = _fetcher().fetch(smart)
        assert result.success is False
        assert result.ltp is None

    def test_wrong_identity_error_mentions_mismatch(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_WRONG_IDENTITY)
        error = _fetcher().fetch(smart).error or ""
        assert "HDFCBANK-EQ" in error

    def test_wrong_identity_does_not_affect_fixed_token(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_WRONG_IDENTITY)
        fetcher = _fetcher()
        fetcher.fetch(smart)
        assert fetcher.token == "99926017"
        assert fetcher.symbol == "India VIX"

    def test_identity_mismatch_still_calls_ltp_data_fixed_token_next_tick(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_WRONG_IDENTITY)
        fetcher = _fetcher()
        fetcher.fetch(smart)
        fetcher.fetch(smart)
        assert smart.ltpData.call_count == 2
        for call in smart.ltpData.call_args_list:
            assert call.kwargs["symboltoken"] == "99926017"

    def test_raw_response_preserved_on_identity_mismatch(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_WRONG_IDENTITY)
        result = _fetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_WRONG_IDENTITY

    def test_missing_tradingsymbol_in_response_does_not_fail_identity_check(self) -> None:
        # Some SDK/response shapes may omit tradingsymbol entirely — must not
        # be treated as a mismatch (backward-compatible with older responses).
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"ltp": _VIX_LTP},
        }
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is True

    def test_correct_identity_case_insensitive_accepted(self) -> None:
        response = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"tradingsymbol": "india vix", "ltp": _VIX_LTP},
        }
        smart = _mock_smart(ltp_result=response)
        result = _fetcher().fetch(smart)
        assert result.success is True


# ===========================================================================
# Raw payload preservation
# ===========================================================================


class TestRawPayloadPreservation:
    def test_raw_response_is_verbatim_api_dict_on_success(self) -> None:
        smart = _mock_smart()
        result = _fetcher().fetch(smart)
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
        smart = _mock_smart()
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
        smart = _mock_smart()
        smart.ltpData.return_value = None
        _fetcher().fetch(smart)

    def test_always_returns_vix_result(self) -> None:
        cases = [
            _mock_smart(),
            _mock_smart(ltp_exc=RuntimeError("fail")),
            _mock_smart(ltp_result=_LTP_RESPONSE_FAIL),
            _mock_smart(ltp_result=_LTP_RESPONSE_MISSING_LTP),
            _mock_smart(ltp_result=_LTP_RESPONSE_ZERO_LTP),
            _mock_smart(ltp_result=_LTP_RESPONSE_WRONG_IDENTITY),
        ]
        for smart in cases:
            assert isinstance(_fetcher().fetch(smart), VIXResult)
