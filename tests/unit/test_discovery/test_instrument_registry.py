"""Tests for lib.discovery.instrument_registry: InstrumentRegistry.

This module is standalone per the L2 design — it is not wired into
ChainFetcher, DiscoveryController, or discovery_run.py. These tests exercise
InstrumentRegistry in isolation only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from lib.discovery._errors import RegistryBuildError
from lib.discovery.instrument_registry import (
    InstrumentRegistry,
    RegistrySnapshot,
    _to_expiry_2y,
)

_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Symbol helpers (mirrors tests/unit/test_discovery/test_chain_fetcher.py)
# ---------------------------------------------------------------------------

_EXPIRY_JUN   = "30JUN2026"   # expiry_2y = "30JUN26"
_EXPIRY_JUL   = "28JUL2026"   # expiry_2y = "28JUL26"


def _sym(underlying: str, expiry: str, strike: int, side: str) -> str:
    expiry_2y = _to_expiry_2y(expiry)
    return f"{underlying}{expiry_2y}{strike}{side}"


def _scrip_item(underlying: str, expiry: str, strike: int, side: str, token: str) -> dict[str, str]:
    return {"tradingsymbol": _sym(underlying, expiry, strike, side), "symboltoken": token}


def _scrip_with_strikes(
    underlying: str,
    expiry: str,
    strikes: list[int],
    ce_token_base: int = 1000,
    pe_token_base: int = 2000,
) -> list[dict[str, str]]:
    rows = []
    for i, s in enumerate(strikes):
        rows.append(_scrip_item(underlying, expiry, s, "CE", str(ce_token_base + i)))
        rows.append(_scrip_item(underlying, expiry, s, "PE", str(pe_token_base + i)))
    return rows


_STRIKES_JUN = [56000, 56500, 57000]
_STRIKES_JUL = [56000, 56500]

# Multi-expiry searchScrip response: JUN tokens 1000s/2000s, JUL tokens 3000s/4000s.
_ROWS_MULTI_EXPIRY = (
    _scrip_with_strikes("BANKNIFTY", _EXPIRY_JUN, _STRIKES_JUN, 1000, 2000)
    + _scrip_with_strikes("BANKNIFTY", _EXPIRY_JUL, _STRIKES_JUL, 3000, 4000)
)

_SCRIP_RESPONSE_OK: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": _ROWS_MULTI_EXPIRY,
}

_SCRIP_RESPONSE_FAIL: dict[str, object] = {
    "status": False,
    "message": "Invalid session",
    "errorcode": "AB1006",
    "data": None,
}

_SCRIP_RESPONSE_EMPTY: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": [],
}


def _mock_smart(
    *,
    scrip_result: dict[str, object] | list[object] | None = None,
    scrip_side_effect: list[object] | None = None,
) -> MagicMock:
    smart = MagicMock()
    if scrip_side_effect is not None:
        smart.searchScrip.side_effect = scrip_side_effect
    else:
        smart.searchScrip.return_value = scrip_result if scrip_result is not None else _SCRIP_RESPONSE_OK
    return smart


def _registry(underlying: str = "BANKNIFTY") -> InstrumentRegistry:
    return InstrumentRegistry(underlying=underlying)


# ===========================================================================
# _to_expiry_2y helper
# ===========================================================================


class TestToExpiry2y:
    def test_converts_ddmmmyyyy_to_ddmmmyy(self) -> None:
        assert _to_expiry_2y("30JUN2026") == "30JUN26"

    def test_matches_symbol_construction(self) -> None:
        assert _to_expiry_2y(_EXPIRY_JUL) == "28JUL26"


# ===========================================================================
# Construction / pre-build state
# ===========================================================================


class TestConstruction:
    def test_default_underlying_is_banknifty(self) -> None:
        assert _registry().underlying == "BANKNIFTY"

    def test_custom_underlying(self) -> None:
        assert InstrumentRegistry(underlying="NIFTY").underlying == "NIFTY"

    def test_not_built_initially(self) -> None:
        assert _registry().is_built is False

    def test_resolved_expiries_empty_initially(self) -> None:
        assert _registry().resolved_expiries == []

    def test_token_map_empty_before_build(self) -> None:
        assert _registry().token_map(_EXPIRY_JUN, "CE") == {}

    def test_snapshot_before_build(self) -> None:
        snap = _registry().snapshot()
        assert isinstance(snap, RegistrySnapshot)
        assert snap.built_at is None
        assert snap.token_counts == {}
        assert snap.retry_count == 0
        assert snap.underlying == "BANKNIFTY"

    def test_two_instances_are_independent(self) -> None:
        a, b = _registry(), _registry()
        smart = _mock_smart()
        a.build(smart, [_EXPIRY_JUN])
        assert a.is_built is True
        assert b.is_built is False


# ===========================================================================
# Successful build — searchScrip call parameters
# ===========================================================================


class TestSearchScripCallParameters:
    def test_calls_search_scrip_once(self) -> None:
        smart = _mock_smart()
        _registry().build(smart, [_EXPIRY_JUN])
        assert smart.searchScrip.call_count == 1

    def test_search_scrip_params_default_underlying(self) -> None:
        smart = _mock_smart()
        _registry().build(smart, [_EXPIRY_JUN])
        kwargs = smart.searchScrip.call_args.kwargs
        assert kwargs["exchange"] == "NFO"
        assert kwargs["searchscrip"] == "BANKNIFTY"

    def test_search_scrip_params_custom_underlying(self) -> None:
        underlying = "NIFTY"
        rows = _scrip_with_strikes(underlying, _EXPIRY_JUN, [24000, 24500])
        smart = _mock_smart(scrip_result={"status": True, "data": rows})
        InstrumentRegistry(underlying=underlying).build(smart, [_EXPIRY_JUN])
        kwargs = smart.searchScrip.call_args.kwargs
        assert kwargs["searchscrip"] == underlying

    def test_one_search_scrip_call_regardless_of_expiry_count(self) -> None:
        smart = _mock_smart()
        _registry().build(smart, [_EXPIRY_JUN, _EXPIRY_JUL])
        assert smart.searchScrip.call_count == 1


# ===========================================================================
# Successful build — token resolution correctness
# ===========================================================================


class TestTokenResolution:
    def test_is_built_true_after_success(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert registry.is_built is True

    def test_resolved_expiries_contains_configured_expiry(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert registry.resolved_expiries == [_EXPIRY_JUN]

    def test_resolved_expiries_preserves_input_order(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUL, _EXPIRY_JUN])
        assert registry.resolved_expiries == [_EXPIRY_JUL, _EXPIRY_JUN]

    def test_ce_token_map_correct(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        ce = registry.token_map(_EXPIRY_JUN, "CE")
        assert ce == {"1000": 56000, "1001": 56500, "1002": 57000}

    def test_pe_token_map_correct(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        pe = registry.token_map(_EXPIRY_JUN, "PE")
        assert pe == {"2000": 56000, "2001": 56500, "2002": 57000}

    def test_second_expiry_tokens_are_distinct(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, _EXPIRY_JUL])
        jul_ce = registry.token_map(_EXPIRY_JUL, "CE")
        assert jul_ce == {"3000": 56000, "3001": 56500}

    def test_ce_tokens_never_leak_into_pe_map(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        ce_tokens = set(registry.token_map(_EXPIRY_JUN, "CE"))
        pe_tokens = set(registry.token_map(_EXPIRY_JUN, "PE"))
        assert ce_tokens.isdisjoint(pe_tokens)

    def test_expiry_tokens_never_leak_across_expiries(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, _EXPIRY_JUL])
        jun_ce = set(registry.token_map(_EXPIRY_JUN, "CE"))
        jul_ce = set(registry.token_map(_EXPIRY_JUL, "CE"))
        assert jun_ce.isdisjoint(jul_ce)

    def test_token_map_side_is_case_insensitive(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert registry.token_map(_EXPIRY_JUN, "ce") == registry.token_map(_EXPIRY_JUN, "CE")

    def test_token_map_returns_a_copy_not_internal_reference(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        m = registry.token_map(_EXPIRY_JUN, "CE")
        m["9999"] = 12345
        assert "9999" not in registry.token_map(_EXPIRY_JUN, "CE")

    def test_custom_underlying_prefix_length_used_for_parsing(self) -> None:
        # "NIFTY" (5 chars) has a different prefix length than "BANKNIFTY" (9);
        # parsing must use the configured underlying's length, not a hard-coded one.
        underlying = "NIFTY"
        rows = _scrip_with_strikes(underlying, _EXPIRY_JUN, [24000, 24500], 500, 600)
        smart = _mock_smart(scrip_result={"status": True, "data": rows})
        registry = InstrumentRegistry(underlying=underlying)
        registry.build(smart, [_EXPIRY_JUN])
        assert registry.token_map(_EXPIRY_JUN, "CE") == {"500": 24000, "501": 24500}


# ===========================================================================
# Partial resolution — one expiry unresolved does not fail the whole build
# ===========================================================================


class TestPartialResolution:
    _MISSING_EXPIRY = "25AUG2026"

    def test_missing_expiry_does_not_raise(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, self._MISSING_EXPIRY])  # must not raise

    def test_missing_expiry_excluded_from_resolved(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, self._MISSING_EXPIRY])
        assert registry.resolved_expiries == [_EXPIRY_JUN]

    def test_missing_expiry_token_map_is_empty(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, self._MISSING_EXPIRY])
        assert registry.token_map(self._MISSING_EXPIRY, "CE") == {}

    def test_present_expiry_still_resolved_alongside_missing_one(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, self._MISSING_EXPIRY])
        assert registry.token_map(_EXPIRY_JUN, "CE") != {}

    def test_is_built_true_despite_partial_resolution(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, self._MISSING_EXPIRY])
        assert registry.is_built is True

    def test_empty_expiries_list_builds_successfully(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [])  # must not raise
        assert registry.is_built is True
        assert registry.resolved_expiries == []


# ===========================================================================
# Total build failure — searchScrip exception
# ===========================================================================


class TestBuildFailureException:
    def test_exception_on_both_attempts_raises_registry_build_error(self) -> None:
        smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), RuntimeError("down")])
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])

    def test_exception_error_contains_type_name(self) -> None:
        smart = _mock_smart(scrip_side_effect=[ValueError("boom"), ValueError("boom")])
        with pytest.raises(RegistryBuildError, match="ValueError"):
            _registry().build(smart, [_EXPIRY_JUN])

    def test_exception_error_excludes_message(self) -> None:
        smart = _mock_smart(scrip_side_effect=[ValueError("secret_detail"), ValueError("secret_detail")])
        try:
            _registry().build(smart, [_EXPIRY_JUN])
        except RegistryBuildError as exc:
            assert "secret_detail" not in str(exc)
        else:
            pytest.fail("expected RegistryBuildError")

    def test_exception_calls_search_scrip_twice(self) -> None:
        smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), RuntimeError("down")])
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])
        assert smart.searchScrip.call_count == 2

    def test_failed_build_leaves_is_built_false(self) -> None:
        registry = _registry()
        smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), RuntimeError("down")])
        with pytest.raises(RegistryBuildError):
            registry.build(smart, [_EXPIRY_JUN])
        assert registry.is_built is False

    def test_unexpected_response_type_raises(self) -> None:
        smart = _mock_smart(scrip_side_effect=[["not", "a", "dict"], ["not", "a", "dict"]])
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])

    def test_status_false_on_both_attempts_raises(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_RESPONSE_FAIL)
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])

    def test_status_false_error_contains_errorcode(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_RESPONSE_FAIL)
        with pytest.raises(RegistryBuildError, match="AB1006"):
            _registry().build(smart, [_EXPIRY_JUN])


# ===========================================================================
# Total build failure — empty response (no retry)
# ===========================================================================


class TestBuildFailureEmpty:
    def test_empty_data_raises_registry_build_error(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_RESPONSE_EMPTY)
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])

    def test_empty_data_error_mentions_underlying(self) -> None:
        smart = _mock_smart(scrip_result=_SCRIP_RESPONSE_EMPTY)
        with pytest.raises(RegistryBuildError, match="BANKNIFTY"):
            _registry().build(smart, [_EXPIRY_JUN])

    def test_empty_data_does_not_retry(self) -> None:
        # A syntactically successful-but-empty response is not a transport
        # failure, so it must not trigger the retry loop.
        smart = _mock_smart(scrip_result=_SCRIP_RESPONSE_EMPTY)
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])
        assert smart.searchScrip.call_count == 1

    def test_null_data_field_treated_as_empty(self) -> None:
        smart = _mock_smart(scrip_result={"status": True, "data": None})
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])

    def test_non_list_data_field_treated_as_empty(self) -> None:
        smart = _mock_smart(scrip_result={"status": True, "data": "not-a-list"})
        with pytest.raises(RegistryBuildError):
            _registry().build(smart, [_EXPIRY_JUN])


# ===========================================================================
# Retry recovery — transient failure then success
# ===========================================================================


class TestRetryRecovery:
    def test_recovers_after_transient_exception(self) -> None:
        smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), _SCRIP_RESPONSE_OK])
        registry = _registry()
        registry.build(smart, [_EXPIRY_JUN])  # must not raise
        assert registry.is_built is True

    def test_recovers_after_transient_status_false(self) -> None:
        smart = _mock_smart(scrip_side_effect=[_SCRIP_RESPONSE_FAIL, _SCRIP_RESPONSE_OK])
        registry = _registry()
        registry.build(smart, [_EXPIRY_JUN])
        assert registry.is_built is True

    def test_recovery_calls_search_scrip_twice(self) -> None:
        smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), _SCRIP_RESPONSE_OK])
        _registry().build(smart, [_EXPIRY_JUN])
        assert smart.searchScrip.call_count == 2

    def test_recovery_resolves_correct_tokens(self) -> None:
        smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), _SCRIP_RESPONSE_OK])
        registry = _registry()
        registry.build(smart, [_EXPIRY_JUN])
        assert registry.token_map(_EXPIRY_JUN, "CE") != {}

    def test_snapshot_retry_count_after_recovery(self) -> None:
        smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), _SCRIP_RESPONSE_OK])
        registry = _registry()
        registry.build(smart, [_EXPIRY_JUN])
        assert registry.snapshot().retry_count == 1

    def test_snapshot_retry_count_zero_on_first_attempt_success(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert registry.snapshot().retry_count == 0


# ===========================================================================
# Failed rebuild does not discard prior successful state
# ===========================================================================


class TestFailedRebuildPreservesState:
    def test_failed_rebuild_raises(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        bad_smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), RuntimeError("down")])
        with pytest.raises(RegistryBuildError):
            registry.rebuild(bad_smart, [_EXPIRY_JUN])

    def test_failed_rebuild_preserves_previous_token_map(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        previous = registry.token_map(_EXPIRY_JUN, "CE")

        bad_smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), RuntimeError("down")])
        with pytest.raises(RegistryBuildError):
            registry.rebuild(bad_smart, [_EXPIRY_JUN])

        assert registry.token_map(_EXPIRY_JUN, "CE") == previous

    def test_failed_rebuild_preserves_is_built_true(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        bad_smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), RuntimeError("down")])
        with pytest.raises(RegistryBuildError):
            registry.rebuild(bad_smart, [_EXPIRY_JUN])
        assert registry.is_built is True

    def test_failed_rebuild_preserves_resolved_expiries(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        bad_smart = _mock_smart(scrip_side_effect=[RuntimeError("down"), RuntimeError("down")])
        with pytest.raises(RegistryBuildError):
            registry.rebuild(bad_smart, [_EXPIRY_JUN])
        assert registry.resolved_expiries == [_EXPIRY_JUN]


# ===========================================================================
# rebuild() — explicit re-resolution, identical semantics to build()
# ===========================================================================


class TestRebuild:
    def test_rebuild_succeeds_like_build(self) -> None:
        registry = _registry()
        registry.rebuild(_mock_smart(), [_EXPIRY_JUN])
        assert registry.is_built is True
        assert registry.token_map(_EXPIRY_JUN, "CE") != {}

    def test_rebuild_replaces_previously_resolved_data(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        first = registry.token_map(_EXPIRY_JUN, "CE")

        new_rows = _scrip_with_strikes("BANKNIFTY", _EXPIRY_JUN, [58000], 9000, 9500)
        new_smart = _mock_smart(scrip_result={"status": True, "data": new_rows})
        registry.rebuild(new_smart, [_EXPIRY_JUN])

        assert registry.token_map(_EXPIRY_JUN, "CE") == {"9000": 58000}
        assert registry.token_map(_EXPIRY_JUN, "CE") != first

    def test_rebuild_calls_search_scrip(self) -> None:
        smart = _mock_smart()
        _registry().rebuild(smart, [_EXPIRY_JUN])
        assert smart.searchScrip.call_count == 1


# ===========================================================================
# snapshot() — provenance
# ===========================================================================


class TestSnapshot:
    def test_snapshot_underlying(self) -> None:
        registry = InstrumentRegistry(underlying="NIFTY")
        rows = _scrip_with_strikes("NIFTY", _EXPIRY_JUN, [24000])
        registry.build(_mock_smart(scrip_result={"status": True, "data": rows}), [_EXPIRY_JUN])
        assert registry.snapshot().underlying == "NIFTY"

    def test_snapshot_built_at_is_datetime_after_build(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert isinstance(registry.snapshot().built_at, datetime)

    def test_snapshot_built_at_is_utc(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert registry.snapshot().built_at.tzinfo == _UTC

    def test_snapshot_token_counts_reflect_resolution(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        counts = registry.snapshot().token_counts
        assert counts[_EXPIRY_JUN]["CE"] == 3
        assert counts[_EXPIRY_JUN]["PE"] == 3

    def test_snapshot_token_counts_zero_for_unresolved_expiry(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN, "25AUG2026"])
        counts = registry.snapshot().token_counts
        assert counts["25AUG2026"]["CE"] == 0
        assert counts["25AUG2026"]["PE"] == 0

    def test_snapshot_is_a_frozen_dataclass(self) -> None:
        snap = _registry().snapshot()
        with pytest.raises(Exception):
            snap.built_at = datetime.now(tz=_UTC)  # type: ignore[misc]


# ===========================================================================
# token_map() never raises
# ===========================================================================


class TestTokenMapNeverRaises:
    def test_never_raises_before_build(self) -> None:
        _registry().token_map(_EXPIRY_JUN, "CE")  # must not raise

    def test_never_raises_for_unknown_expiry(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        registry.token_map("99SEP2099", "CE")  # must not raise

    def test_never_raises_for_unknown_side(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert registry.token_map(_EXPIRY_JUN, "XX") == {}

    def test_always_returns_dict(self) -> None:
        registry = _registry()
        registry.build(_mock_smart(), [_EXPIRY_JUN])
        assert isinstance(registry.token_map(_EXPIRY_JUN, "CE"), dict)
        assert isinstance(registry.token_map("unknown", "CE"), dict)
