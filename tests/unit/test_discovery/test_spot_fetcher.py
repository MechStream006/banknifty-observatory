"""Tests for lib.discovery.fetchers.spot: SpotFetcher."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lib.discovery._models import ChainResult, SpotResult
from lib.discovery.fetchers.spot import (
    SpotFetcher,
    _MODE_EMBEDDED,
    _MODE_SEPARATE,
    _MODE_UNAVAILABLE,
)

_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_LTP_VALUE = 52345.75

_LTP_RESPONSE_OK: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {"ltp": _LTP_VALUE, "tradingsymbol": "NIFTY BANK", "exchange": "NSE"},
}

_LTP_RESPONSE_FAIL: dict[str, object] = {
    "status": False,
    "message": "Invalid session",
    "errorcode": "AB1006",
    "data": None,
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


def _make_chain_result(
    success: bool = True,
    raw_response: dict[str, object] | None = None,
) -> ChainResult:
    """Build a minimal ChainResult for SpotFetcher tests."""
    if raw_response is None and success:
        raw_response = {
            "status": True,
            "data": {
                "fetched": [{"tradingSymbol": "BANKNIFTY26JUN26CE51000", "lastPrice": 125.0}],
                "unfetched": [],
            },
        }
    return ChainResult(
        fetched_at=datetime(2026, 6, 22, 9, 15, tzinfo=_UTC),
        latency_ms=45.0,
        http_status=None,
        response_bytes=1024,
        raw_response=raw_response,
        row_count=1 if success else 0,
        expiry_count=1 if success else 0,
        unfetched_count=0,
        error=None if success else "chain failed",
        success=success,
    )


# ===========================================================================
# Construction
# ===========================================================================


class TestSpotFetcherInit:
    def test_default_mode_is_separate_call(self) -> None:
        f = SpotFetcher()
        assert f.source_mode == "separate_call"

    def test_chain_embedded_mode_stored(self) -> None:
        f = SpotFetcher(source_mode="chain_embedded")
        assert f.source_mode == "chain_embedded"

    def test_invalid_mode_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid source_mode"):
            SpotFetcher(source_mode="something_else")

    def test_error_message_lists_valid_modes(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            SpotFetcher(source_mode="bad_mode")
        assert "separate_call" in str(exc_info.value)
        assert "chain_embedded" in str(exc_info.value)


# ===========================================================================
# separate_call — success
# ===========================================================================


class TestSeparateCallSuccess:
    def test_returns_spot_result(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert isinstance(result, SpotResult)

    def test_success_is_true(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert result.success is True

    def test_ltp_matches_response(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert result.ltp == _LTP_VALUE

    def test_source_is_separate_call(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert result.source == _MODE_SEPARATE

    def test_error_is_none(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert result.error is None

    def test_raw_response_is_preserved(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_OK

    def test_calls_ltp_data_with_nse_nifty_bank(self) -> None:
        smart = _mock_smart()
        SpotFetcher().fetch(smart)
        smart.ltpData.assert_called_once_with(
            exchange="NSE",
            tradingsymbol="NIFTY BANK",
            symboltoken="99926009",
        )

    def test_fetched_at_is_utc(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert result.fetched_at.tzinfo is _UTC

    def test_ltp_is_float(self) -> None:
        smart = _mock_smart(ltp_result={**_LTP_RESPONSE_OK, "data": {"ltp": 52000}})
        result = SpotFetcher().fetch(smart)
        assert isinstance(result.ltp, float)


# ===========================================================================
# separate_call — failure modes
# ===========================================================================


class TestSeparateCallFailure:
    def test_sdk_exception_returns_success_false(self) -> None:
        smart = _mock_smart(ltp_exc=ConnectionError("timeout"))
        result = SpotFetcher().fetch(smart)
        assert result.success is False

    def test_sdk_exception_source_is_separate_call(self) -> None:
        smart = _mock_smart(ltp_exc=ConnectionError("timeout"))
        result = SpotFetcher().fetch(smart)
        assert result.source == _MODE_SEPARATE

    def test_sdk_exception_error_contains_type_not_message(self) -> None:
        # SDK exception message is excluded to avoid leaking internal details
        smart = _mock_smart(ltp_exc=ValueError("internal_secret_detail"))
        result = SpotFetcher().fetch(smart)
        assert "ValueError" in (result.error or "")
        assert "internal_secret_detail" not in (result.error or "")

    def test_sdk_exception_raw_response_is_none(self) -> None:
        smart = _mock_smart(ltp_exc=OSError("socket closed"))
        result = SpotFetcher().fetch(smart)
        assert result.raw_response is None

    def test_status_false_returns_success_false(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        result = SpotFetcher().fetch(smart)
        assert result.success is False

    def test_status_false_error_contains_errorcode(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        result = SpotFetcher().fetch(smart)
        assert "AB1006" in (result.error or "")

    def test_status_false_raw_response_preserved(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        result = SpotFetcher().fetch(smart)
        assert result.raw_response is _LTP_RESPONSE_FAIL

    def test_ltp_zero_treated_as_invalid(self) -> None:
        response = {**_LTP_RESPONSE_OK, "data": {"ltp": 0}}
        smart = _mock_smart(ltp_result=response)
        result = SpotFetcher().fetch(smart)
        assert result.success is False
        assert result.ltp is None

    def test_ltp_none_treated_as_invalid(self) -> None:
        response = {**_LTP_RESPONSE_OK, "data": {"ltp": None}}
        smart = _mock_smart(ltp_result=response)
        result = SpotFetcher().fetch(smart)
        assert result.success is False
        assert result.ltp is None

    def test_missing_data_key_treated_as_invalid(self) -> None:
        response: dict[str, object] = {"status": True, "message": "SUCCESS", "errorcode": ""}
        smart = _mock_smart(ltp_result=response)
        result = SpotFetcher().fetch(smart)
        assert result.success is False


# ===========================================================================
# chain_embedded — success (underlyingValue present)
# ===========================================================================


class TestChainEmbeddedSuccess:
    def _chain_with_underlying(
        self, field: str, value: float, at_row_level: bool = False
    ) -> ChainResult:
        if at_row_level:
            raw = {
                "status": True,
                "data": {
                    "fetched": [{"tradingSymbol": "BN26JUN26CE51000", field: value}],
                    "unfetched": [],
                },
            }
        else:
            raw = {
                "status": True,
                "data": {
                    field: value,
                    "fetched": [{"tradingSymbol": "BN26JUN26CE51000"}],
                    "unfetched": [],
                },
            }
        return _make_chain_result(raw_response=raw)

    def test_success_when_underlying_value_in_data_dict(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100.0)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.success is True

    def test_ltp_extracted_from_underlying_value(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100.0)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.ltp == 52100.0

    def test_ltp_is_float(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100)  # int in response
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert isinstance(result.ltp, float)

    def test_source_is_chain_embedded(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100.0)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.source == _MODE_EMBEDDED

    def test_latency_is_zero(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100.0)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.latency_ms == 0.0

    def test_error_is_none(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100.0)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.error is None

    def test_raw_response_is_chain_raw_response(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100.0)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.raw_response is chain.raw_response

    def test_success_when_ind_close_price_in_data_dict(self) -> None:
        chain = self._chain_with_underlying("indClosePrice", 51900.5)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.success is True
        assert result.ltp == 51900.5

    def test_success_when_underlying_close_in_data_dict(self) -> None:
        chain = self._chain_with_underlying("underlyingClose", 52000.0)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.success is True
        assert result.ltp == 52000.0

    def test_success_when_underlying_value_in_first_row(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52200.0, at_row_level=True)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.success is True
        assert result.ltp == 52200.0

    def test_no_ltp_data_call_made(self) -> None:
        chain = self._chain_with_underlying("underlyingValue", 52100.0)
        smart = MagicMock()
        SpotFetcher(source_mode="chain_embedded").fetch(smart, chain)
        smart.ltpData.assert_not_called()


# ===========================================================================
# chain_embedded — unavailable cases
# ===========================================================================


class TestChainEmbeddedUnavailable:
    def test_none_chain_result_returns_unavailable(self) -> None:
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), None)
        assert result.source == _MODE_UNAVAILABLE
        assert result.success is False

    def test_failed_chain_result_returns_unavailable(self) -> None:
        chain = _make_chain_result(success=False, raw_response=None)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.source == _MODE_UNAVAILABLE

    def test_chain_with_none_raw_response_returns_unavailable(self) -> None:
        chain = _make_chain_result(success=True, raw_response=None)
        # Manually set success=True but raw_response=None (shouldn't normally happen)
        chain.success = True
        chain.raw_response = None
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.source == _MODE_UNAVAILABLE

    def test_no_embedded_field_returns_unavailable(self) -> None:
        chain = _make_chain_result()  # raw_response has no underlyingValue
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.source == _MODE_UNAVAILABLE
        assert result.success is False

    def test_no_embedded_field_error_mentions_candidate_keys(self) -> None:
        chain = _make_chain_result()
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert "underlyingValue" in (result.error or "")

    def test_no_embedded_field_latency_is_zero(self) -> None:
        chain = _make_chain_result()
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.latency_ms == 0.0

    def test_unavailable_raw_response_preserved_when_chain_successful(self) -> None:
        # Chain succeeded but field missing — raw_response is still returned
        chain = _make_chain_result()
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.raw_response is chain.raw_response

    def test_unavailable_raw_response_none_when_chain_failed(self) -> None:
        chain = _make_chain_result(success=False, raw_response=None)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.raw_response is None

    def test_zero_underlying_value_treated_as_missing(self) -> None:
        # Zero is not a valid index price — treated same as absent
        raw = {
            "status": True,
            "data": {"underlyingValue": 0, "fetched": [], "unfetched": []},
        }
        chain = _make_chain_result(raw_response=raw)
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.success is False


# ===========================================================================
# Latency tracking
# ===========================================================================


class TestLatencyTracking:
    def test_separate_call_latency_is_positive(self) -> None:
        smart = _mock_smart()
        result = SpotFetcher().fetch(smart)
        assert result.latency_ms >= 0.0

    def test_separate_call_latency_measured_correctly(self) -> None:
        with patch("lib.discovery.fetchers.spot._monotonic", side_effect=[100.0, 100.5]):
            smart = _mock_smart()
            result = SpotFetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(500.0, abs=1.0)

    def test_separate_call_latency_measured_on_exception(self) -> None:
        with patch("lib.discovery.fetchers.spot._monotonic", side_effect=[100.0, 100.3]):
            smart = _mock_smart(ltp_exc=ConnectionError("timeout"))
            result = SpotFetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(300.0, abs=1.0)

    def test_separate_call_latency_rounded_to_two_decimals(self) -> None:
        with patch("lib.discovery.fetchers.spot._monotonic", side_effect=[100.0, 100.123456]):
            smart = _mock_smart()
            result = SpotFetcher().fetch(smart)
        assert result.latency_ms == pytest.approx(123.46, abs=0.01)

    def test_chain_embedded_latency_always_zero(self) -> None:
        chain = _make_chain_result(raw_response={
            "status": True,
            "data": {"underlyingValue": 52000.0, "fetched": [], "unfetched": []},
        })
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.latency_ms == 0.0

    def test_chain_embedded_latency_zero_even_when_unavailable(self) -> None:
        chain = _make_chain_result()  # no underlyingValue
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.latency_ms == 0.0


# ===========================================================================
# fetch() — never raises
# ===========================================================================


class TestFetchNeverRaises:
    def test_returns_spot_result_on_sdk_exception(self) -> None:
        smart = _mock_smart(ltp_exc=RuntimeError("network"))
        result = SpotFetcher().fetch(smart)
        assert isinstance(result, SpotResult)

    def test_returns_spot_result_on_status_false(self) -> None:
        smart = _mock_smart(ltp_result=_LTP_RESPONSE_FAIL)
        result = SpotFetcher().fetch(smart)
        assert isinstance(result, SpotResult)

    def test_returns_spot_result_when_chain_none(self) -> None:
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), None)
        assert isinstance(result, SpotResult)

    def test_returns_spot_result_when_no_embedded_field(self) -> None:
        chain = _make_chain_result()
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert isinstance(result, SpotResult)


# ===========================================================================
# Source field semantics
# ===========================================================================


class TestSourceField:
    def test_separate_call_success_source(self) -> None:
        result = SpotFetcher().fetch(_mock_smart())
        assert result.source == "separate_call"

    def test_separate_call_failure_source(self) -> None:
        result = SpotFetcher().fetch(_mock_smart(ltp_exc=OSError("error")))
        assert result.source == "separate_call"

    def test_chain_embedded_success_source(self) -> None:
        chain = _make_chain_result(raw_response={
            "status": True,
            "data": {"underlyingValue": 52100.0, "fetched": [], "unfetched": []},
        })
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.source == "chain_embedded"

    def test_unavailable_source_when_field_missing(self) -> None:
        chain = _make_chain_result()  # no underlyingValue
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), chain)
        assert result.source == "unavailable"

    def test_unavailable_source_when_chain_is_none(self) -> None:
        result = SpotFetcher(source_mode="chain_embedded").fetch(MagicMock(), None)
        assert result.source == "unavailable"


# ===========================================================================
# Mode-switching behaviour
# ===========================================================================


class TestModeSwitching:
    def test_separate_call_mode_does_not_call_ltp_data_when_chain_embedded(self) -> None:
        # When mode is chain_embedded, ltpData must never be called
        chain = _make_chain_result(raw_response={
            "status": True,
            "data": {"underlyingValue": 52100.0, "fetched": [], "unfetched": []},
        })
        smart = MagicMock()
        SpotFetcher(source_mode="chain_embedded").fetch(smart, chain)
        smart.ltpData.assert_not_called()

    def test_separate_call_mode_ignores_chain_result(self) -> None:
        # When mode is separate_call, chain_result is unused
        smart = _mock_smart()
        chain = _make_chain_result()  # no underlyingValue — but should be ignored
        result = SpotFetcher(source_mode="separate_call").fetch(smart, chain)
        assert result.success is True
        assert result.ltp == _LTP_VALUE
        assert result.source == _MODE_SEPARATE
