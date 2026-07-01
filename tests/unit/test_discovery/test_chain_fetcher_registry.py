"""Tests for lib.discovery.fetchers.chain: ChainFetcher's optional
InstrumentRegistry-sourced Phase 1 (L2 M1b).

Reuses fixtures/helpers from test_chain_fetcher.py so the legacy and
registry-sourced paths are compared against the exact same data. This
module proves three things, per the M1b acceptance scope:

  1. registry=None reproduces today's behaviour byte-for-byte (the existing
     test_chain_fetcher.py suite already covers this; the parity tests here
     additionally prove the registry path matches it field-for-field).
  2. registry-supplied fetch() returns a ChainResult identical to the
     legacy path for the same underlying data.
  3. registry-supplied fetch() calls searchScrip() zero times.

fetch(smart, spot)'s signature is unchanged in both cases; only the
constructor gained an optional `registry` parameter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from lib.discovery._models import ChainResult
from lib.discovery.fetchers.chain import ChainFetcher
from lib.discovery.instrument_registry import InstrumentRegistry
from tests.unit.test_discovery.test_chain_fetcher import (
    _CHAIN_RESPONSE,
    _EXPIRY_JUN,
    _MARKET_DATA_SUCCESS,
    _SCRIP_3,
    _SCRIP_CE_ONLY,
    _SCRIP_NOV23,
    _SCRIP_WINDOW,
    _SPOT,
    _mock_smart,
    _scrip_item,
)

_FIXED_DT = datetime(2026, 6, 22, 9, 30, 0, tzinfo=timezone.utc)


def _build_registry(scrip_result: dict[str, object], expiries: list[str], underlying: str = "BANKNIFTY") -> InstrumentRegistry:
    """Build a real InstrumentRegistry from the same searchScrip fixture a
    legacy-path test would use, so its token maps match _filter_tokens()
    exactly."""
    registry = InstrumentRegistry(underlying=underlying)
    smart = MagicMock()
    smart.searchScrip.return_value = scrip_result
    registry.build(smart, expiries)
    return registry


def _run_with_frozen_clock(fetcher: ChainFetcher, smart: MagicMock, spot: float) -> ChainResult:
    """Run fetch() with _utc_now/_monotonic frozen, so timing fields are
    directly comparable across two independent fetch() calls."""
    with patch("lib.discovery.fetchers.chain._utc_now", return_value=_FIXED_DT), \
         patch("lib.discovery.fetchers.chain._monotonic", side_effect=[100.0, 101.5, 101.5, 101.5]):
        return fetcher.fetch(smart, spot)


# ===========================================================================
# Construction — registry parameter
# ===========================================================================


class TestRegistryConstruction:
    def test_registry_defaults_to_none(self) -> None:
        # No public accessor is added for the private attribute; this is
        # exercised behaviourally by the rest of this module (registry=None
        # reproduces the legacy searchScrip path).
        ChainFetcher(expiry=_EXPIRY_JUN)  # must not raise

    def test_accepts_registry_keyword(self) -> None:
        registry = InstrumentRegistry()
        ChainFetcher(expiry=_EXPIRY_JUN, registry=registry)  # must not raise

    def test_fetch_signature_unchanged(self) -> None:
        import inspect
        sig = inspect.signature(ChainFetcher.fetch)
        assert list(sig.parameters) == ["self", "smart", "spot"]


# ===========================================================================
# searchScrip call count — the core M1b acceptance criterion
# ===========================================================================


class TestSearchScripCallCount:
    def test_legacy_path_calls_search_scrip_once(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(smart, _SPOT)
        assert smart.searchScrip.call_count == 1

    def test_registry_path_calls_search_scrip_zero_times(self) -> None:
        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert smart.searchScrip.call_count == 0

    def test_registry_path_zero_search_scrip_across_many_ticks(self) -> None:
        # The whole point of L2: N ticks must not multiply searchScrip calls.
        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        fetcher = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry)
        for _ in range(10):
            fetcher.fetch(smart, _SPOT)
        assert smart.searchScrip.call_count == 0

    def test_registry_path_still_calls_get_market_data(self) -> None:
        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert smart.getMarketData.call_count >= 1


# ===========================================================================
# Result parity — registry path vs legacy path, same underlying data
# ===========================================================================


class TestRegistryLegacyParity:
    def test_identical_chain_result_success_case(self) -> None:
        legacy_smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        legacy_result = _run_with_frozen_clock(
            ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2), legacy_smart, _SPOT
        )

        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        registry_smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        registry_result = _run_with_frozen_clock(
            ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry),
            registry_smart, _SPOT,
        )

        assert registry_result == legacy_result

    def test_identical_row_count(self) -> None:
        legacy_smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        legacy_result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(legacy_smart, _SPOT)

        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        registry_smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        registry_result = ChainFetcher(
            expiry=_EXPIRY_JUN, window_steps=2, registry=registry
        ).fetch(registry_smart, _SPOT)

        assert registry_result.row_count == legacy_result.row_count
        assert registry_result.success == legacy_result.success

    def test_identical_raw_response(self) -> None:
        legacy_smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        legacy_result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(legacy_smart, _SPOT)

        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        registry_smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        registry_result = ChainFetcher(
            expiry=_EXPIRY_JUN, window_steps=2, registry=registry
        ).fetch(registry_smart, _SPOT)

        assert registry_result.raw_response == legacy_result.raw_response

    def test_identical_tokens_sent_to_get_market_data(self) -> None:
        legacy_smart = _mock_smart(scrip_result=_SCRIP_WINDOW, market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(legacy_smart, _SPOT)
        legacy_tokens = {
            t for call in legacy_smart.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }

        registry = _build_registry(_SCRIP_WINDOW, [_EXPIRY_JUN])
        registry_smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(registry_smart, _SPOT)
        registry_tokens = {
            t for call in registry_smart.getMarketData.call_args_list
            for t in call.kwargs["exchangeTokens"]["NFO"]
        }

        assert registry_tokens == legacy_tokens

    def test_identical_multi_expiry_count(self) -> None:
        legacy_smart = _mock_smart(scrip_result=_SCRIP_NOV23, market_data_result=_CHAIN_RESPONSE)
        legacy_result = ChainFetcher(expiry="23NOV2023", window_steps=2).fetch(legacy_smart, 47200.0)

        registry = _build_registry(_SCRIP_NOV23, ["23NOV2023"])
        registry_smart = _mock_smart(market_data_result=_CHAIN_RESPONSE)
        registry_result = ChainFetcher(
            expiry="23NOV2023", window_steps=2, registry=registry
        ).fetch(registry_smart, 47200.0)

        assert registry_result.expiry_count == legacy_result.expiry_count
        assert registry_result.row_count == legacy_result.row_count

    def test_ce_only_scrip_behaves_identically(self) -> None:
        legacy_smart = _mock_smart(scrip_result=_SCRIP_CE_ONLY, market_data_result=_MARKET_DATA_SUCCESS)
        legacy_result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(legacy_smart, _SPOT)

        registry = _build_registry(_SCRIP_CE_ONLY, [_EXPIRY_JUN])
        registry_smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        registry_result = ChainFetcher(
            expiry=_EXPIRY_JUN, window_steps=2, registry=registry
        ).fetch(registry_smart, _SPOT)

        assert registry_result.success == legacy_result.success


# ===========================================================================
# Registry path — failure modes
# ===========================================================================


class TestRegistryPathFailureModes:
    def test_registry_has_no_ce_tokens_returns_success_false(self) -> None:
        # Registry built for a different expiry only — the requested expiry
        # resolves to {} via token_map(), same shape as an unresolved expiry.
        registry = _build_registry(_SCRIP_3, ["01JAN2099"])
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert result.success is False

    def test_registry_has_no_ce_tokens_error_mentions_expiry(self) -> None:
        registry = _build_registry(_SCRIP_3, ["01JAN2099"])
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert _EXPIRY_JUN in (result.error or "")

    def test_registry_has_no_ce_tokens_does_not_call_get_market_data(self) -> None:
        registry = _build_registry(_SCRIP_3, ["01JAN2099"])
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        smart.getMarketData.assert_not_called()

    def test_registry_has_no_ce_tokens_does_not_call_search_scrip(self) -> None:
        registry = _build_registry(_SCRIP_3, ["01JAN2099"])
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert smart.searchScrip.call_count == 0

    def test_unbuilt_registry_treated_as_no_tokens(self) -> None:
        # A registry that was constructed but never built() returns {} for
        # every token_map() query — never raises.
        registry = InstrumentRegistry()
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert result.success is False
        assert smart.searchScrip.call_count == 0

    def test_registry_path_never_raises(self) -> None:
        registry = InstrumentRegistry()
        smart = _mock_smart(market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, registry=registry).fetch(smart, _SPOT)  # must not raise


# ===========================================================================
# getMarketData phase is unaffected by the registry path (Phase 2 unchanged)
# ===========================================================================


class TestRegistryPathPhase2Unaffected:
    def test_get_market_data_exception_still_fails_via_registry_path(self) -> None:
        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        smart = _mock_smart(market_data_exc=RuntimeError("reset"))
        result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert result.success is False
        assert "RuntimeError" in (result.error or "")

    def test_get_market_data_status_false_still_fails_via_registry_path(self) -> None:
        registry = _build_registry(_SCRIP_3, [_EXPIRY_JUN])
        fail: dict[str, object] = {
            "status": False, "message": "expired", "errorcode": "AB1006", "data": None,
        }
        smart = _mock_smart(market_data_result=fail)
        result = ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=registry).fetch(smart, _SPOT)
        assert result.success is False
        assert "AB1006" in (result.error or "")


# ===========================================================================
# Legacy path is byte-for-byte unaffected by the new constructor parameter
# ===========================================================================


class TestLegacyPathUnaffectedByNewParameter:
    def test_registry_none_still_calls_search_scrip(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2, registry=None).fetch(smart, _SPOT)
        smart.searchScrip.assert_called_once_with(exchange="NFO", searchscrip="BANKNIFTY")

    def test_registry_omitted_entirely_still_calls_search_scrip(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_3, market_data_result=_MARKET_DATA_SUCCESS)
        ChainFetcher(expiry=_EXPIRY_JUN, window_steps=2).fetch(smart, _SPOT)
        smart.searchScrip.assert_called_once_with(exchange="NFO", searchscrip="BANKNIFTY")

    def test_legacy_search_scrip_failure_path_unaffected(self) -> None:
        scrip = {"status": True, "data": []}
        smart = _mock_smart(scrip_result=scrip)
        result = ChainFetcher(expiry=_EXPIRY_JUN, registry=None).fetch(smart, _SPOT)
        assert result.success is False
        assert "searchScrip returned" in (result.error or "")
