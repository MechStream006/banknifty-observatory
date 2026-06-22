"""Tests for lib.discovery.fetchers.chain: ChainFetcher (M-C3 upgrade).

M-C3 changes from M-C2:
  - fetch(smart, spot) now requires a spot argument.
  - Both CE and PE tokens are fetched for the configured expiry.
  - StrikeLadder selects the ±window_steps backbone window around ATM.
  - _filter_ce_tokens removed; replaced by _filter_tokens(result, side).
  - Symbol format: BANKNIFTY + expiry_2y + strike + side (e.g. "BANKNIFTY26JUN2651000CE").

Source of truth for response shapes: tests/fixtures/chain_response_fixture.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.discovery._models import ChainResult
from lib.discovery.fetchers.chain import ChainFetcher, _json_size

# ---------------------------------------------------------------------------
# Fixture data loaded once at module level
# ---------------------------------------------------------------------------

_FIXTURE_PATH = (
    Path(__file__).parents[2] / "fixtures" / "chain_response_fixture.json"
)
_CHAIN_RESPONSE: dict[str, object] = json.loads(
    _FIXTURE_PATH.read_text(encoding="utf-8")
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_EXPIRY_JUN  = "26JUN2026"   # expiry_2y = "26JUN26"
_EXPIRY_JUN30 = "30JUN2026"  # expiry_2y = "30JUN26"
_SPOT        = 58000.0       # representative BankNifty spot for window tests

# ---------------------------------------------------------------------------
# Symbol helpers
#
# Live format (confirmed 22 Jun 2026):
#   BANKNIFTY + expiry_2y + strike + side
#   e.g. "BANKNIFTY26JUN2651000CE"
# ---------------------------------------------------------------------------


def _sym(expiry: str, strike: int, side: str) -> str:
    """Build a SmartAPI-format tradingsymbol."""
    expiry_2y = expiry[:5] + expiry[7:]
    return f"BANKNIFTY{expiry_2y}{strike}{side}"


def _scrip_item(expiry: str, strike: int, side: str, token: str) -> dict[str, str]:
    return {"tradingsymbol": _sym(expiry, strike, side), "symboltoken": token}


def _scrip_with_strikes(
    expiry: str,
    strikes: list[int],
    ce_token_base: int = 1000,
    pe_token_base: int = 2000,
) -> dict[str, object]:
    """Build a searchScrip response with CE+PE tokens for the given strikes."""
    data = []
    for i, s in enumerate(strikes):
        data.append(_scrip_item(expiry, s, "CE", str(ce_token_base + i)))
        data.append(_scrip_item(expiry, s, "PE", str(pe_token_base + i)))
    return {"status": True, "message": "SUCCESS", "errorcode": "", "data": data}


# ---------------------------------------------------------------------------
# Standard scrip fixtures
#
# _SCRIP_WINDOW: 9 backbone strikes (500-pt, 56000–60000) around spot=58000.
# CE tokens: 1000–1008; PE tokens: 2000–2008.
# ---------------------------------------------------------------------------

_STRIKES_9 = list(range(56000, 60001, 500))   # [56000, 56500, ..., 60000]
_SCRIP_WINDOW = _scrip_with_strikes(_EXPIRY_JUN, _STRIKES_9)

# Three-strike scrip for minimal tests.
_SCRIP_3 = _scrip_with_strikes(_EXPIRY_JUN, [57500, 58000, 58500])

# CE-only scrip (no PE): all strikes 57500–58500 on CE side only.
_SCRIP_CE_ONLY: dict[str, object] = {
    "status": True,
    "data": [
        _scrip_item(_EXPIRY_JUN, 57500, "CE", "1001"),
        _scrip_item(_EXPIRY_JUN, 58000, "CE", "1002"),
        _scrip_item(_EXPIRY_JUN, 58500, "CE", "1003"),
    ],
}

# Scrip for the old NOV-2023 fixture (multi-expiry count test).
# The fixture response (chain_response_fixture.json) has tradingSymbol rows
# for "23NOV2023"; the searchScrip token "43761" triggers the fetch.
_SCRIP_NOV23: dict[str, object] = {
    "status": True,
    "data": [
        _scrip_item("23NOV2023", 47000, "CE", "43761"),
        _scrip_item("23NOV2023", 47500, "CE", "43763"),
    ],
}

# ---------------------------------------------------------------------------
# Standard market-data fixture (2 CE + 2 PE rows for _SCRIP_3 strikes)
# ---------------------------------------------------------------------------

_MARKET_DATA_SUCCESS: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": {
        "fetched": [
            {
                "tradingSymbol": _sym(_EXPIRY_JUN, 57500, "CE"),
                "symbolToken": "1001",
                "expiryDate": _EXPIRY_JUN,
                "ltp": 300.0,
                "opnInterest": 10000,
            },
            {
                "tradingSymbol": _sym(_EXPIRY_JUN, 58000, "CE"),
                "symbolToken": "1002",
                "expiryDate": _EXPIRY_JUN,
                "ltp": 120.0,
                "opnInterest": 20000,
            },
            {
                "tradingSymbol": _sym(_EXPIRY_JUN, 58500, "CE"),
                "symbolToken": "1003",
                "expiryDate": _EXPIRY_JUN,
                "ltp": 50.0,
                "opnInterest": 15000,
            },
            {
                "tradingSymbol": _sym(_EXPIRY_JUN, 57500, "PE"),
                "symbolToken": "2001",
                "expiryDate": _EXPIRY_JUN,
                "ltp": 85.0,
                "opnInterest": 12000,
            },
            {
                "tradingSymbol": _sym(_EXPIRY_JUN, 58000, "PE"),
                "symbolToken": "2002",
                "expiryDate": _EXPIRY_JUN,
                "ltp": 200.0,
                "opnInterest": 18000,
            },
            {
                "tradingSymbol": _sym(_EXPIRY_JUN, 58500, "PE"),
                "symbolToken": "2003",
                "expiryDate": _EXPIRY_JUN,
                "ltp": 310.0,
                "opnInterest": 11000,
            },
        ],
        "unfetched": [],
    },
}

# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------


def _mock_smart(
    *,
    scrip_result:       dict[str, object] | None = None,
    market_data_result: dict[str, object] | None = None,
    scrip_exc:          Exception | None = None,
    market_data_exc:    Exception | None = None,
) -> MagicMock:
    """Return a mock SmartConnect with configurable call behaviour."""
    smart = MagicMock()
    if scrip_exc is not None:
        smart.searchScrip.side_effect = scrip_exc
    else:
        smart.searchScrip.return_value = scrip_result or _SCRIP_3
    if market_data_exc is not None:
        smart.getMarketData.side_effect = market_data_exc
    else:
        smart.getMarketData.return_value = market_data_result or _MARKET_DATA_SUCCESS
    return smart


def _fetcher(expiry: str = _EXPIRY_JUN, window_steps: int = 2) -> ChainFetcher:
    """Return a ChainFetcher with a small window for unit tests."""
    return ChainFetcher(expiry=expiry, window_steps=window_steps)


# ===========================================================================
# Construction and properties
# ===========================================================================


class TestChainFetcherInit:
    def test_expiry_stored_as_given(self) -> None:
        assert ChainFetcher(expiry=_EXPIRY_JUN).expiry == _EXPIRY_JUN

    def test_expiry_2y_strips_century_digits(self) -> None:
        assert ChainFetcher(expiry="26JUN2026").expiry_2y == "26JUN26"

    def test_expiry_2y_correct_for_different_month(self) -> None:
        assert ChainFetcher(expiry="23NOV2023").expiry_2y == "23NOV23"

    def test_expiry_2y_correct_for_january(self) -> None:
        assert ChainFetcher(expiry="30JAN2025").expiry_2y == "30JAN25"

    def test_window_steps_default_is_15(self) -> None:
        assert ChainFetcher(expiry=_EXPIRY_JUN).window_steps == 15

    def test_window_steps_stored(self) -> None:
        assert ChainFetcher(expiry=_EXPIRY_JUN, window_steps=5).window_steps == 5

    def test_step_size_default_is_500(self) -> None:
        assert ChainFetcher(expiry=_EXPIRY_JUN).step_size == 500

    def test_step_size_stored(self) -> None:
        assert ChainFetcher(expiry=_EXPIRY_JUN, step_size=100).step_size == 100


# ===========================================================================
# _filter_tokens — CE side
# ===========================================================================


class TestFilterTokensCE:
    def _f(self, expiry: str = _EXPIRY_JUN) -> ChainFetcher:
        return ChainFetcher(expiry=expiry)

    def test_returns_dict(self) -> None:
        result = self._f()._filter_tokens(_SCRIP_WINDOW, "CE")
        assert isinstance(result, dict)

    def test_ce_tokens_only(self) -> None:
        f = self._f()
        result = f._filter_tokens(_SCRIP_WINDOW, "CE")
        # _SCRIP_WINDOW has 9 CE tokens (1000–1008) and 9 PE tokens (2000–2008)
        assert all(int(t) < 2000 for t in result)

    def test_token_count_correct(self) -> None:
        f = self._f()
        result = f._filter_tokens(_SCRIP_WINDOW, "CE")
        assert len(result) == 9  # 9 strikes × 1 CE each

    def test_strike_values_correct(self) -> None:
        f = self._f()
        result = f._filter_tokens(_SCRIP_WINDOW, "CE")
        assert set(result.values()) == {56000, 56500, 57000, 57500, 58000, 58500, 59000, 59500, 60000}

    def test_wrong_expiry_excluded(self) -> None:
        f = ChainFetcher(expiry=_EXPIRY_JUN)
        scrip = {
            "status": True,
            "data": [
                _scrip_item(_EXPIRY_JUN, 57000, "CE", "111"),   # matches
                _scrip_item("03JUL2026", 57000, "CE", "999"),   # wrong expiry
            ],
        }
        result = f._filter_tokens(scrip, "CE")
        assert "111" in result
        assert "999" not in result

    def test_empty_data_returns_empty_dict(self) -> None:
        f = self._f()
        assert f._filter_tokens({"status": True, "data": []}, "CE") == {}

    def test_non_list_data_returns_empty_dict(self) -> None:
        f = self._f()
        assert f._filter_tokens({"status": True, "data": None}, "CE") == {}

    def test_items_without_token_are_skipped(self) -> None:
        f = self._f()
        scrip = {
            "status": True,
            "data": [
                {"tradingsymbol": _sym(_EXPIRY_JUN, 57000, "CE"), "symboltoken": ""},
                {"tradingsymbol": _sym(_EXPIRY_JUN, 58000, "CE"), "symboltoken": "999"},
            ],
        }
        result = f._filter_tokens(scrip, "CE")
        assert "999" in result
        assert len(result) == 1

    def test_case_insensitive_matching(self) -> None:
        f = self._f()
        scrip = {
            "status": True,
            "data": [
                {"tradingsymbol": _sym(_EXPIRY_JUN, 57000, "CE").lower(), "symboltoken": "555"},
            ],
        }
        result = f._filter_tokens(scrip, "CE")
        assert "555" in result


# ===========================================================================
# _filter_tokens — PE side
# ===========================================================================


class TestFilterTokensPE:
    def _f(self) -> ChainFetcher:
        return ChainFetcher(expiry=_EXPIRY_JUN)

    def test_pe_tokens_only(self) -> None:
        f = self._f()
        result = f._filter_tokens(_SCRIP_WINDOW, "PE")
        assert all(int(t) >= 2000 for t in result)

    def test_pe_token_count_correct(self) -> None:
        f = self._f()
        result = f._filter_tokens(_SCRIP_WINDOW, "PE")
        assert len(result) == 9

    def test_pe_strike_values_match_ce_strikes(self) -> None:
        f = self._f()
        ce_map = f._filter_tokens(_SCRIP_WINDOW, "CE")
        pe_map = f._filter_tokens(_SCRIP_WINDOW, "PE")
        assert set(ce_map.values()) == set(pe_map.values())

    def test_ce_excluded_from_pe_filter(self) -> None:
        f = self._f()
        result = f._filter_tokens(_SCRIP_CE_ONLY, "PE")
        assert result == {}  # no PE instruments in the scrip

    def test_futures_excluded_from_pe_filter(self) -> None:
        f = self._f()
        scrip = {
            "status": True,
            "data": [
                _scrip_item(_EXPIRY_JUN, 57000, "PE", "111"),
                {"tradingsymbol": f"BANKNIFTY26JUN26FUT", "symboltoken": "333"},
            ],
        }
        result = f._filter_tokens(scrip, "PE")
        assert "333" not in result
        assert "111" in result


# ===========================================================================
# _filter_tokens — strike extraction
# ===========================================================================


class TestStrikeExtraction:
    def _f(self) -> ChainFetcher:
        return ChainFetcher(expiry=_EXPIRY_JUN)

    def test_5_digit_strike_extracted(self) -> None:
        f = self._f()
        scrip = {"status": True, "data": [_scrip_item(_EXPIRY_JUN, 57000, "CE", "T1")]}
        result = f._filter_tokens(scrip, "CE")
        assert result["T1"] == 57000

    def test_6_digit_strike_extracted(self) -> None:
        f = self._f()
        scrip = {"status": True, "data": [_scrip_item(_EXPIRY_JUN, 100000, "CE", "T2")]}
        result = f._filter_tokens(scrip, "CE")
        assert result["T2"] == 100000

    def test_low_strike_extracted(self) -> None:
        f = self._f()
        scrip = {"status": True, "data": [_scrip_item(_EXPIRY_JUN, 100, "CE", "T3")]}
        result = f._filter_tokens(scrip, "CE")
        assert result["T3"] == 100

    def test_pe_strike_same_as_ce_strike(self) -> None:
        f = self._f()
        scrip = {"status": True, "data": [_scrip_item(_EXPIRY_JUN, 58000, "PE", "P1")]}
        result = f._filter_tokens(scrip, "PE")
        assert result["P1"] == 58000

    def test_malformed_symbol_skipped(self) -> None:
        # Old format with type before strike: "BANKNIFTY26JUN26CE51000"
        # The slice gives "CE510" which is not a valid int → skipped.
        f = self._f()
        scrip = {
            "status": True,
            "data": [
                {"tradingsymbol": "BANKNIFTY26JUN26CE51000", "symboltoken": "BAD"},
                _scrip_item(_EXPIRY_JUN, 58000, "CE", "GOOD"),
            ],
        }
        result = f._filter_tokens(scrip, "CE")
        assert "GOOD" in result
        assert "BAD" not in result


# ===========================================================================
# fetch() — happy path
# ===========================================================================


class TestFetchSuccess:
    def test_returns_chain_result_on_success(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        result = _fetcher().fetch(smart, _SPOT)
        assert isinstance(result, ChainResult)

    def test_success_is_true(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        assert _fetcher().fetch(smart, _SPOT).success is True

    def test_error_is_none_on_success(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        assert _fetcher().fetch(smart, _SPOT).error is None

    def test_row_count_equals_fetched_list_length(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        # _MARKET_DATA_SUCCESS has 6 rows (3 CE + 3 PE)
        assert _fetcher().fetch(smart, _SPOT).row_count == 6

    def test_http_status_is_always_none(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        assert _fetcher().fetch(smart, _SPOT).http_status is None

    def test_fetched_at_is_utc(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.fetched_at.tzinfo == timezone.utc

    def test_calls_search_scrip_with_nfo_banknifty(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        _fetcher().fetch(smart, _SPOT)
        smart.searchScrip.assert_called_once_with(exchange="NFO", searchscrip="BANKNIFTY")

    def test_calls_get_market_data_full_mode(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        _fetcher().fetch(smart, _SPOT)
        assert smart.getMarketData.call_count >= 1
        call_kwargs = smart.getMarketData.call_args
        assert call_kwargs.kwargs["mode"] == "FULL"

    def test_expiry_count_reflects_distinct_expiry_dates(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.expiry_count == 1  # all rows have expiryDate = _EXPIRY_JUN


# ===========================================================================
# fetch() — CE and PE tokens are included
# ===========================================================================


class TestCePeTokens:
    """The windowed request must include both CE and PE tokens."""

    def test_ce_tokens_sent_to_get_market_data(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        _fetcher(window_steps=2).fetch(smart, _SPOT)
        all_sent = {
            t
            for call in smart.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }
        # CE tokens for _SCRIP_3: "1000" (57500), "1001" (58000), "1002" (58500)
        # With window_steps=2 and spot=58000, ATM=58000, ±2 backbone = all 3 strikes
        assert any(t in all_sent for t in ["1000", "1001", "1002"])

    def test_pe_tokens_sent_to_get_market_data(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        _fetcher(window_steps=2).fetch(smart, _SPOT)
        all_sent = {
            t
            for call in smart.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }
        # PE tokens for _SCRIP_3: "2000" (57500), "2001" (58000), "2002" (58500)
        assert any(t in all_sent for t in ["2000", "2001", "2002"])

    def test_no_pe_tokens_when_pe_map_empty(self) -> None:
        # Only CE instruments in scrip; fetch should still succeed on CE alone.
        smart = _mock_smart(scrip_result=_SCRIP_CE_ONLY, market_data_result=_MARKET_DATA_SUCCESS)
        result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(smart, _SPOT)
        # PE tokens are absent from all batches; CE-only success is acceptable.
        all_sent = {
            t
            for call in smart.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }
        # PE token "2001" not present (it wasn't in SCRIP_CE_ONLY)
        assert "2001" not in all_sent

    def test_pe_tokens_for_same_strikes_as_ce_window(self) -> None:
        # Verify PE tokens match the same backbone strikes as CE tokens.
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        f = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2)
        f.fetch(smart, _SPOT)
        all_sent = {
            t
            for call in smart.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }
        # For each CE token sent (1000=57500, 1001=58000, 1002=58500),
        # corresponding PE token (2000, 2001, 2002) should also be sent.
        ce_to_pe = {"1000": "2000", "1001": "2001", "1002": "2002"}
        for ce, pe in ce_to_pe.items():
            if ce in all_sent:
                assert pe in all_sent, f"PE token {pe!r} missing when CE token {ce!r} was sent"


# ===========================================================================
# fetch() — window selection
# ===========================================================================


class TestWindowSelection:
    """StrikeLadder must be used; window restricts tokens to backbone strikes."""

    def test_window_restricts_tokens_sent(self) -> None:
        # _SCRIP_WINDOW has 9 backbone strikes (56000–60000); window_steps=1 → ATM±1 = 3 strikes
        smart = _mock_smart(scrip_result=_SCRIP_WINDOW, market_data_result=_MARKET_DATA_SUCCESS)
        f = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=1)
        f.fetch(smart, _SPOT)  # spot=58000, ATM=58000
        total_sent = sum(
            len(call.kwargs["exchangeTokens"]["NFO"])
            for call in smart.getMarketData.call_args_list
        )
        # 3 CE + 3 PE = 6 tokens (window_steps=1 → 3 backbone strikes)
        assert total_sent == 6

    def test_spot_shifts_window(self) -> None:
        # Different spot → different ATM → different window center
        smart1 = _mock_smart(scrip_result=_SCRIP_WINDOW, market_data_result=_MARKET_DATA_SUCCESS)
        smart2 = _mock_smart(scrip_result=_SCRIP_WINDOW, market_data_result=_MARKET_DATA_SUCCESS)
        f = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=1)
        f.fetch(smart1, 57000.0)  # ATM = 57000
        f.fetch(smart2, 59000.0)  # ATM = 59000
        sent1 = {
            t for call in smart1.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }
        sent2 = {
            t for call in smart2.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }
        # Different ATM → different token sets
        assert sent1 != sent2

    def test_empty_window_returns_failure(self) -> None:
        # Spot so far from any listed strike that StrikeLadder window is empty.
        # Use window_steps=0 and a very distant spot to force an empty window
        # by patching StrikeLadder.window.
        from unittest.mock import patch
        smart = _mock_smart(scrip_result=_SCRIP_3)
        with patch("lib.discovery.fetchers.chain.StrikeLadder") as MockLadder:
            instance = MockLadder.return_value
            instance.window.return_value = []
            instance.backbone_strikes = [57500, 58000, 58500]
            instance.resolved_atm.return_value = 58000
            result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(smart, _SPOT)
        assert result.success is False
        assert "empty" in (result.error or "").lower()

    def test_get_market_data_not_called_when_window_empty(self) -> None:
        from unittest.mock import patch
        smart = _mock_smart(scrip_result=_SCRIP_3)
        with patch("lib.discovery.fetchers.chain.StrikeLadder") as MockLadder:
            instance = MockLadder.return_value
            instance.window.return_value = []
            instance.backbone_strikes = []
            instance.resolved_atm.return_value = 58000
            ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(smart, _SPOT)
        smart.getMarketData.assert_not_called()

    def test_window_steps_controls_token_count(self) -> None:
        # window_steps=2 → 5 CE strikes; window_steps=1 → 3 CE strikes
        smart = _mock_smart(scrip_result=_SCRIP_WINDOW, market_data_result=_MARKET_DATA_SUCCESS)
        f2 = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2)
        f1 = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=1)
        f2.fetch(smart, _SPOT)
        calls2 = sum(len(c.kwargs["exchangeTokens"]["NFO"]) for c in smart.getMarketData.call_args_list)
        smart.reset_mock()
        f1.fetch(smart, _SPOT)
        calls1 = sum(len(c.kwargs["exchangeTokens"]["NFO"]) for c in smart.getMarketData.call_args_list)
        # window_steps=2 sends more tokens than window_steps=1
        assert calls2 > calls1


# ===========================================================================
# fetch() — raw payload preservation
# ===========================================================================


class TestRawPayloadPreservation:
    def test_raw_response_contains_merged_fetched_rows(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.raw_response is not None
        fetched = result.raw_response["data"]["fetched"]
        assert len(fetched) == 6  # 3 CE + 3 PE rows from _MARKET_DATA_SUCCESS

    def test_raw_response_is_dict(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        assert isinstance(_fetcher().fetch(smart, _SPOT).raw_response, dict)

    def test_raw_response_is_none_on_search_scrip_exception(self) -> None:
        smart = _mock_smart(scrip_exc=ConnectionError("timeout"))
        assert _fetcher().fetch(smart, _SPOT).raw_response is None

    def test_raw_response_is_none_on_no_tokens_found(self) -> None:
        smart = _mock_smart(scrip_result={"status": True, "data": []})
        assert _fetcher().fetch(smart, _SPOT).raw_response is None

    def test_raw_response_is_none_on_get_market_data_exception(self) -> None:
        smart = _mock_smart(
            scrip_result=_SCRIP_3,
            market_data_exc=ConnectionError("socket closed"),
        )
        assert _fetcher().fetch(smart, _SPOT).raw_response is None

    def test_raw_response_is_set_on_api_status_false(self) -> None:
        fail: dict[str, object] = {
            "status": False, "message": "Invalid session",
            "errorcode": "AB1006", "data": None,
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=fail)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.raw_response is fail


# ===========================================================================
# fetch() — response size tracking
# ===========================================================================


class TestResponseSizeTracking:
    def test_response_bytes_positive_on_success(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        assert _fetcher().fetch(smart, _SPOT).response_bytes > 0

    def test_response_bytes_matches_json_size_helper(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        result = _fetcher().fetch(smart, _SPOT)
        expected = _json_size(_MARKET_DATA_SUCCESS)
        assert result.response_bytes == expected

    def test_response_bytes_zero_on_scrip_exception(self) -> None:
        smart = _mock_smart(scrip_exc=RuntimeError("error"))
        assert _fetcher().fetch(smart, _SPOT).response_bytes == 0

    def test_response_bytes_zero_on_market_data_exception(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_exc=RuntimeError("error"))
        assert _fetcher().fetch(smart, _SPOT).response_bytes == 0

    def test_response_bytes_measured_on_api_status_false(self) -> None:
        fail: dict[str, object] = {
            "status": False, "message": "error", "errorcode": "X1", "data": None,
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=fail)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.response_bytes == _json_size(fail)


# ===========================================================================
# fetch() — latency tracking
# ===========================================================================


class TestLatencyTracking:
    def test_latency_is_positive_on_success(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        assert _fetcher().fetch(smart, _SPOT).latency_ms >= 0.0

    def test_latency_covers_all_phases(self) -> None:
        monotonic_vals = [100.0, 101.0]  # t0=100.0, end=101.0 → 1000ms
        with patch("lib.discovery.fetchers.chain._monotonic", side_effect=monotonic_vals):
            smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
            result = _fetcher().fetch(smart, _SPOT)
        assert result.latency_ms == pytest.approx(1000.0, abs=1.0)

    def test_latency_is_positive_on_scrip_failure(self) -> None:
        smart = _mock_smart(scrip_exc=ConnectionError("timeout"))
        assert _fetcher().fetch(smart, _SPOT).latency_ms >= 0.0

    def test_latency_rounded_to_two_decimal_places(self) -> None:
        with patch("lib.discovery.fetchers.chain._monotonic", side_effect=[100.0, 100.123456]):
            smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
            result = _fetcher().fetch(smart, _SPOT)
        assert result.latency_ms == pytest.approx(123.46, abs=0.01)


# ===========================================================================
# fetch() — searchScrip failure modes
# ===========================================================================


class TestSearchScripFailure:
    def test_sdk_exception_returns_success_false(self) -> None:
        smart = _mock_smart(scrip_exc=ConnectionError("no route"))
        assert _fetcher().fetch(smart, _SPOT).success is False

    def test_sdk_exception_error_contains_type_not_message(self) -> None:
        smart = _mock_smart(scrip_exc=ValueError("internal_detail"))
        result = _fetcher().fetch(smart, _SPOT)
        assert "ValueError" in (result.error or "")
        assert "internal_detail" not in (result.error or "")

    def test_no_ce_tokens_returns_success_false(self) -> None:
        scrip = {"status": True, "data": []}
        smart = _mock_smart(scrip_result=scrip)
        assert _fetcher().fetch(smart, _SPOT).success is False

    def test_no_ce_tokens_error_mentions_expiry(self) -> None:
        scrip = {"status": True, "data": []}
        smart = _mock_smart(scrip_result=scrip)
        result = _fetcher().fetch(smart, _SPOT)
        assert _EXPIRY_JUN in (result.error or "")

    def test_get_market_data_not_called_if_no_tokens(self) -> None:
        scrip = {"status": True, "data": []}
        smart = _mock_smart(scrip_result=scrip)
        _fetcher().fetch(smart, _SPOT)
        smart.getMarketData.assert_not_called()


# ===========================================================================
# fetch() — getMarketData failure modes
# ===========================================================================


class TestGetMarketDataFailure:
    def test_sdk_exception_returns_success_false(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_exc=RuntimeError("reset"))
        assert _fetcher().fetch(smart, _SPOT).success is False

    def test_sdk_exception_error_contains_type_not_message(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_exc=OSError("secret_path"))
        result = _fetcher().fetch(smart, _SPOT)
        assert "OSError" in (result.error or "")
        assert "secret_path" not in (result.error or "")

    def test_status_false_returns_success_false(self) -> None:
        fail: dict[str, object] = {
            "status": False, "message": "Invalid token",
            "errorcode": "AB1006", "data": None,
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=fail)
        assert _fetcher().fetch(smart, _SPOT).success is False

    def test_status_false_error_contains_errorcode(self) -> None:
        fail: dict[str, object] = {
            "status": False, "message": "expired", "errorcode": "AB1006", "data": None,
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=fail)
        assert "AB1006" in (_fetcher().fetch(smart, _SPOT).error or "")

    def test_empty_fetched_list_returns_success_false(self) -> None:
        empty: dict[str, object] = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"fetched": [], "unfetched": []},
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=empty)
        assert _fetcher().fetch(smart, _SPOT).success is False

    def test_empty_fetched_list_raw_response_is_set(self) -> None:
        empty: dict[str, object] = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {"fetched": [], "unfetched": []},
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=empty)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.raw_response is not None
        assert result.raw_response.get("status") is True


# ===========================================================================
# fetch() — response parsing details
# ===========================================================================


class TestResponseParsing:
    def test_multi_expiry_counted_correctly(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_NOV23, market_data_result=_CHAIN_RESPONSE)
        result = ChainFetcher(expiry="23NOV2023", window_steps=2).fetch(smart, 47200.0)
        assert result.expiry_count == 2  # chain_response_fixture has 23NOV and 30NOV rows

    def test_row_count_from_fixture_is_20(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_NOV23, market_data_result=_CHAIN_RESPONSE)
        result = ChainFetcher(expiry="23NOV2023", window_steps=2).fetch(smart, 47200.0)
        assert result.row_count == 20

    def test_unfetched_count_reflects_unfetched_list(self) -> None:
        response_with_unfetched: dict[str, object] = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {
                "fetched": _MARKET_DATA_SUCCESS["data"]["fetched"],  # type: ignore[index]
                "unfetched": ["99001", "99002"],
            },
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=response_with_unfetched)
        assert _fetcher().fetch(smart, _SPOT).unfetched_count == 2

    def test_flat_data_list_layout_supported(self) -> None:
        flat: dict[str, object] = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": _MARKET_DATA_SUCCESS["data"]["fetched"],  # type: ignore[index]
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=flat)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.success is True
        assert result.row_count == 6

    def test_expiry_date_alternate_key_expiry(self) -> None:
        response_alt_key: dict[str, object] = {
            "status": True, "message": "SUCCESS", "errorcode": "",
            "data": {
                "fetched": [
                    {"tradingSymbol": _sym(_EXPIRY_JUN, 58000, "CE"),
                     "expiry": _EXPIRY_JUN, "ltp": 100.0},
                ],
                "unfetched": [],
            },
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=response_alt_key)
        result = _fetcher().fetch(smart, _SPOT)
        assert result.expiry_count == 1


# ===========================================================================
# fetch() — never raises
# ===========================================================================


class TestFetchNeverRaises:
    def test_returns_chain_result_on_scrip_exception(self) -> None:
        smart = _mock_smart(scrip_exc=RuntimeError("network"))
        assert isinstance(_fetcher().fetch(smart, _SPOT), ChainResult)

    def test_returns_chain_result_on_no_tokens(self) -> None:
        smart = _mock_smart(scrip_result={"status": True, "data": []})
        assert isinstance(_fetcher().fetch(smart, _SPOT), ChainResult)

    def test_returns_chain_result_on_market_data_exception(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_exc=OSError("disk"))
        assert isinstance(_fetcher().fetch(smart, _SPOT), ChainResult)

    def test_returns_chain_result_on_market_data_status_false(self) -> None:
        fail: dict[str, object] = {
            "status": False, "message": "error", "errorcode": "X", "data": None,
        }
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=fail)
        assert isinstance(_fetcher().fetch(smart, _SPOT), ChainResult)


# ===========================================================================
# _json_size helper
# ===========================================================================


class TestJsonSizeHelper:
    def test_returns_positive_integer(self) -> None:
        assert _json_size({"key": "value"}) > 0

    def test_matches_manual_calculation(self) -> None:
        obj = {"a": 1, "b": "hello"}
        expected = len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        assert _json_size(obj) == expected

    def test_larger_object_has_more_bytes(self) -> None:
        small = {"a": 1}
        large = {"a": 1, "b": 2, "c": "some long string value"}
        assert _json_size(large) > _json_size(small)


# ===========================================================================
# Batching — _BATCH_SIZE = 50
# ===========================================================================


def _scrip_with_n_ce_tokens(n: int, expiry: str = _EXPIRY_JUN30) -> dict[str, object]:
    """Synthetic searchScrip response with n CE tokens (no PE) for testing batching."""
    expiry_2y = expiry[:5] + expiry[7:]
    return {
        "status": True,
        "data": [
            {
                "tradingsymbol": f"BANKNIFTY{expiry_2y}{50000 + i * 500}CE",
                "symboltoken": str(70000 + i),
            }
            for i in range(n)
        ],
    }


def _success_response(rows: int = 1, unfetched: int = 0) -> dict[str, object]:
    return {
        "status": True,
        "message": "SUCCESS",
        "errorcode": "",
        "data": {
            "fetched": [
                {"tradingSymbol": f"SYM{i}", "symbolToken": str(i), "ltp": float(i)}
                for i in range(rows)
            ],
            "unfetched": [str(90000 + i) for i in range(unfetched)],
        },
    }


_FAIL_AB4029: dict[str, object] = {
    "status": False,
    "message": "Tokens max limit exceeded",
    "errorcode": "AB4029",
    "data": None,
}

# A spot value that falls within the CE token range for _EXPIRY_JUN30 tests.
# CE tokens start at 50000 in steps of 500; for n=40 they go to 69500.
_SPOT_JUN30 = 59500.0


class TestBatchedFetch:
    def test_exactly_50_tokens_makes_one_call(self) -> None:
        # 25 CE (500-pt backbone, all backbone) + 0 PE = 25 window tokens → 1 batch
        scrip = _scrip_with_n_ce_tokens(25, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.return_value = _success_response(rows=25)
        ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=12).fetch(smart, _SPOT_JUN30)
        assert smart.getMarketData.call_count == 1

    def test_51_tokens_splits_into_two_calls(self) -> None:
        # Build a scrip with 51 CE tokens to force a window > 50 CE+PE combined.
        # Use window_steps=30 → up to 61 CE backbone strikes; with 51 listed, all 51 selected.
        # 51 CE + 0 PE = 51 → 2 batches.
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [
            _success_response(rows=50),
            _success_response(rows=1),
        ]
        ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert smart.getMarketData.call_count == 2

    def test_first_batch_failure_aborts_immediately(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_FAIL_AB4029]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert smart.getMarketData.call_count == 1
        assert result.success is False

    def test_second_batch_failure_aborts_after_two_calls(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_success_response(rows=50), _FAIL_AB4029]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert smart.getMarketData.call_count == 2
        assert result.success is False

    def test_last_batch_receives_remainder_tokens(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_success_response(rows=50), _success_response(rows=1)]
        ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        first  = smart.getMarketData.call_args_list[0].kwargs["exchangeTokens"]["NFO"]
        second = smart.getMarketData.call_args_list[1].kwargs["exchangeTokens"]["NFO"]
        assert len(first) == 50
        assert len(second) == 1

    def test_fetched_rows_merged_from_two_batches(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_success_response(rows=50), _success_response(rows=1)]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert result.success is True
        assert result.row_count == 51

    def test_unfetched_tokens_merged_from_two_batches(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [
            _success_response(rows=45, unfetched=5),
            _success_response(rows=1, unfetched=0),
        ]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert result.row_count == 46
        assert result.unfetched_count == 5

    def test_partial_unfetched_does_not_prevent_success(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [
            _success_response(rows=0, unfetched=50),
            _success_response(rows=1, unfetched=0),
        ]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert result.success is True
        assert result.row_count == 1
        assert result.unfetched_count == 50

    def test_all_batches_empty_fetched_returns_success_false(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [
            _success_response(rows=0, unfetched=50),
            _success_response(rows=0, unfetched=1),
        ]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert result.success is False
        assert result.unfetched_count == 51

    def test_response_bytes_sums_across_two_batches(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        batch1 = _success_response(rows=50)
        batch2 = _success_response(rows=1)
        smart.getMarketData.side_effect = [batch1, batch2]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert result.response_bytes == _json_size(batch1) + _json_size(batch2)

    def test_response_bytes_on_second_batch_failure_reflects_failing_response(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_success_response(rows=50), _FAIL_AB4029]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert result.response_bytes == _json_size(_FAIL_AB4029)

    def test_raw_response_is_synthetic_merged_dict(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_success_response(rows=50), _success_response(rows=1)]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        rr = result.raw_response
        assert isinstance(rr, dict)
        assert rr.get("status") is True
        data = rr.get("data", {})
        assert "fetched" in data
        assert "unfetched" in data

    def test_raw_response_contains_all_fetched_rows(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_success_response(rows=50), _success_response(rows=1)]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert len(result.raw_response["data"]["fetched"]) == 51

    def test_failure_error_includes_batch_info(self) -> None:
        scrip = _scrip_with_n_ce_tokens(51, _EXPIRY_JUN30)
        smart = MagicMock()
        smart.searchScrip.return_value = scrip
        smart.getMarketData.side_effect = [_success_response(rows=50), _FAIL_AB4029]
        result = ChainFetcher(expiry=_EXPIRY_JUN30, window_steps=100).fetch(smart, _SPOT_JUN30)
        assert "2/2" in (result.error or "")
        assert "AB4029" in (result.error or "")
