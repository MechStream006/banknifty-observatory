"""Integration test for L2 M1d: InstrumentRegistry wired end-to-end through
DiscoveryController with real (non-mocked) ChainFetcher and InstrumentRegistry
instances across multiple expiries.

This exercises the exact composition scripts/discovery_run.py performs (one
InstrumentRegistry, shared by every expiry's ChainFetcher, injected via
DiscoveryController) — only the SmartAPI boundary (SmartConnect) and the
surrounding infrastructure (session, archiver, scheduler) are mocked. The
controller, the registry, and every ChainFetcher are the real production
classes.

Proves:
  1. Exactly one searchScrip() call for the whole run, regardless of tick
     count or expiry count (the actual regression test for the 25AUG2026
     SmartAPI rate-limiting failures this milestone eliminates).
  2. Every expiry's ChainFetcher ends up sharing the identical registry
     instance (not just equal, the same object).
  3. Multi-expiry collection still succeeds — every tick's ObservationRecord
     has successful chain results for every configured expiry.
  4. No behavior regression — the registry-wired run produces the same
     tick/success/failure counts as the equivalent legacy (registry=None,
     per-tick searchScrip) run over the same data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from lib.discovery._models import PhaseConfig, SpotResult, VIXResult
from lib.discovery.controller import DiscoveryController
from lib.discovery.fetchers.chain import ChainFetcher
from lib.discovery.instrument_registry import InstrumentRegistry

# ---------------------------------------------------------------------------
# Multi-expiry fixture data
# ---------------------------------------------------------------------------

_UNDERLYING = "BANKNIFTY"
_EXPIRY_A = "30JUN2026"
_EXPIRY_B = "28JUL2026"
_STRIKES_A = [56000, 56500, 57000]
_STRIKES_B = [56000, 56500]
_SPOT = 56500.0


def _expiry_2y(expiry: str) -> str:
    return expiry[:5] + expiry[7:]


def _scrip_item(expiry: str, strike: int, side: str, token: str) -> dict[str, str]:
    return {
        "tradingsymbol": f"{_UNDERLYING}{_expiry_2y(expiry)}{strike}{side}",
        "symboltoken": token,
    }


def _scrip_rows(expiry: str, strikes: list[int], ce_base: int, pe_base: int) -> list[dict[str, str]]:
    rows = []
    for i, s in enumerate(strikes):
        rows.append(_scrip_item(expiry, s, "CE", str(ce_base + i)))
        rows.append(_scrip_item(expiry, s, "PE", str(pe_base + i)))
    return rows


# One combined searchScrip response covering both configured expiries —
# exactly what a single real searchScrip("BANKNIFTY") call returns live.
_ALL_SCRIP_ROWS = (
    _scrip_rows(_EXPIRY_A, _STRIKES_A, 1000, 2000)
    + _scrip_rows(_EXPIRY_B, _STRIKES_B, 3000, 4000)
)
_SEARCH_SCRIP_RESPONSE: dict[str, object] = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": _ALL_SCRIP_ROWS,
}


def _market_row(expiry: str, strike: int, side: str, token: str) -> dict[str, object]:
    return {
        "tradingSymbol": f"{_UNDERLYING}{_expiry_2y(expiry)}{strike}{side}",
        "symbolToken": token,
        "expiryDate": expiry,
        "ltp": 100.0,
        "opnInterest": 1000,
        "tradVol": 10,
    }


_TOKEN_TO_ROW: dict[str, dict[str, object]] = {}
for _i, _s in enumerate(_STRIKES_A):
    _TOKEN_TO_ROW[str(1000 + _i)] = _market_row(_EXPIRY_A, _s, "CE", str(1000 + _i))
    _TOKEN_TO_ROW[str(2000 + _i)] = _market_row(_EXPIRY_A, _s, "PE", str(2000 + _i))
for _i, _s in enumerate(_STRIKES_B):
    _TOKEN_TO_ROW[str(3000 + _i)] = _market_row(_EXPIRY_B, _s, "CE", str(3000 + _i))
    _TOKEN_TO_ROW[str(4000 + _i)] = _market_row(_EXPIRY_B, _s, "PE", str(4000 + _i))


def _get_market_data_side_effect(mode: str, exchangeTokens: dict[str, list[str]]) -> dict[str, object]:
    tokens = exchangeTokens["NFO"]
    fetched = [_TOKEN_TO_ROW[t] for t in tokens if t in _TOKEN_TO_ROW]
    unfetched = [t for t in tokens if t not in _TOKEN_TO_ROW]
    return {
        "status": True,
        "message": "SUCCESS",
        "errorcode": "",
        "data": {"fetched": fetched, "unfetched": unfetched},
    }


# ---------------------------------------------------------------------------
# Harness — mocks only the SmartAPI boundary and surrounding infrastructure
# ---------------------------------------------------------------------------


class _TickScheduler:
    """Yields N tick datetimes 5s apart, then stops."""

    def __init__(self, n_ticks: int) -> None:
        base = datetime(2026, 6, 30, 4, 0, 0, tzinfo=timezone.utc)
        self._ticks = [base + timedelta(seconds=5 * i) for i in range(n_ticks)]

    def ticks(self):  # type: ignore[return]
        yield from self._ticks


def _make_mock_smart() -> MagicMock:
    smart = MagicMock()
    smart.searchScrip.return_value = _SEARCH_SCRIP_RESPONSE
    smart.getMarketData.side_effect = _get_market_data_side_effect
    return smart


def _make_mock_session(smart: MagicMock) -> MagicMock:
    session = MagicMock()
    session.smart = smart
    session.connect.return_value = None
    session.refresh_if_needed.return_value = False
    return session


def _make_mock_archiver() -> MagicMock:
    archiver = MagicMock()
    archiver.current_file_path = Path("/tmp/bno_it/raw/20260630.jsonl")
    return archiver


def _make_mock_spot_fetcher() -> MagicMock:
    spot_fetcher = MagicMock()
    spot_fetcher.fetch.return_value = SpotResult(
        fetched_at=datetime(2026, 6, 30, 4, 0, 0, tzinfo=timezone.utc),
        latency_ms=10.0,
        ltp=_SPOT,
        raw_response={"status": True, "data": {"ltp": _SPOT}},
        source="separate_call",
        error=None,
        success=True,
    )
    return spot_fetcher


def _make_mock_vix_fetcher() -> MagicMock:
    vix_fetcher = MagicMock()
    vix_fetcher.fetch.return_value = VIXResult(
        fetched_at=datetime(2026, 6, 30, 4, 0, 0, tzinfo=timezone.utc),
        latency_ms=8.0,
        ltp=14.2,
        raw_response={"status": True, "data": {"ltp": 14.2}},
        error=None,
        success=True,
    )
    return vix_fetcher


def _make_config() -> PhaseConfig:
    return PhaseConfig(
        phase=1,
        interval_seconds=5,
        max_duration_seconds=None,
        data_dir=Path("/tmp/bno_it"),
        db_path=Path("/tmp/bno_it/discovery.db"),
    )


def _run_with_registry(n_ticks: int, registry: InstrumentRegistry | None):
    """Assemble real ChainFetchers + DiscoveryController exactly as
    scripts/discovery_run.py does, and run() them. Returns
    (result, smart_mock, chain_fetchers)."""
    smart = _make_mock_smart()
    session = _make_mock_session(smart)
    archiver = _make_mock_archiver()

    chain_fetchers = [
        ChainFetcher(expiry=_EXPIRY_A, window_steps=2, step_size=500),
        ChainFetcher(expiry=_EXPIRY_B, window_steps=2, step_size=500),
    ]

    controller = DiscoveryController(
        config=_make_config(),
        session=session,
        chain_fetchers=chain_fetchers,
        spot_fetcher=_make_mock_spot_fetcher(),
        vix_fetcher=_make_mock_vix_fetcher(),
        expiries=[_EXPIRY_A, _EXPIRY_B],
        chain_step_size=500,
        chain_window_steps=2,
        scheduler=_TickScheduler(n_ticks),
        archiver=archiver,
        store=None,
        registry=registry,
    )
    result = controller.run()
    return result, smart, chain_fetchers, archiver


# ===========================================================================
# 1. Exactly one searchScrip() call per run
# ===========================================================================


class TestExactlyOneSearchScripCallPerRun:
    def test_one_call_across_five_ticks_two_expiries(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        result, smart, _, _ = _run_with_registry(5, registry)
        assert smart.searchScrip.call_count == 1

    def test_one_call_regardless_of_more_ticks(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        result, smart, _, _ = _run_with_registry(20, registry)
        assert smart.searchScrip.call_count == 1

    def test_get_market_data_still_called_per_tick_per_expiry(self) -> None:
        # searchScrip collapses to 1 call; getMarketData is unaffected and
        # still runs every tick for every expiry (Phase 2 is unchanged).
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        result, smart, _, _ = _run_with_registry(3, registry)
        assert smart.getMarketData.call_count >= 3 * 2  # >=1 batch per (tick, expiry)


# ===========================================================================
# 2. Multiple expiries share the same registry instance
# ===========================================================================


class TestSharedRegistryInstance:
    def test_all_chain_fetchers_share_identical_registry(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        _, _, chain_fetchers, _ = _run_with_registry(2, registry)
        assert chain_fetchers[0].registry is registry
        assert chain_fetchers[1].registry is registry
        assert chain_fetchers[0].registry is chain_fetchers[1].registry

    def test_registry_resolved_both_expiries(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        _run_with_registry(2, registry)
        assert set(registry.resolved_expiries) == {_EXPIRY_A, _EXPIRY_B}

    def test_registry_token_maps_are_distinct_per_expiry(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        _run_with_registry(1, registry)
        ce_a = set(registry.token_map(_EXPIRY_A, "CE"))
        ce_b = set(registry.token_map(_EXPIRY_B, "CE"))
        assert ce_a.isdisjoint(ce_b)


# ===========================================================================
# 3. Multi-expiry collection still succeeds
# ===========================================================================


class TestMultiExpiryCollectionSucceeds:
    def test_all_ticks_complete(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        result, _, _, _ = _run_with_registry(4, registry)
        assert result.total_ticks == 4

    def test_all_polls_successful(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        result, _, _, _ = _run_with_registry(4, registry)
        assert result.successful_polls == 4
        assert result.failed_polls == 0

    def test_not_ended_early(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        result, _, _, _ = _run_with_registry(4, registry)
        assert result.ended_early is False

    def test_every_persisted_record_has_both_expiries_successful(self) -> None:
        registry = InstrumentRegistry(underlying=_UNDERLYING)
        _, _, _, archiver = _run_with_registry(3, registry)
        for call in archiver.write.call_args_list:
            record_dict = call.args[0]
            chains = record_dict["chains"]
            assert len(chains) == 2
            assert all(c["success"] for c in chains)
            assert {c["expiry"] for c in chains} == {_EXPIRY_A, _EXPIRY_B}


# ===========================================================================
# 4. No behavior regression vs the legacy (registry=None) path
# ===========================================================================


class TestNoRegressionVsLegacyPath:
    def test_same_tick_and_success_counts_as_legacy(self) -> None:
        registry_result, _, _, _ = _run_with_registry(4, InstrumentRegistry(underlying=_UNDERLYING))
        legacy_result, _, _, _ = _run_with_registry(4, None)

        assert registry_result.total_ticks == legacy_result.total_ticks
        assert registry_result.successful_polls == legacy_result.successful_polls
        assert registry_result.failed_polls == legacy_result.failed_polls
        assert registry_result.ended_early == legacy_result.ended_early

    def test_legacy_path_calls_search_scrip_per_tick_per_expiry(self) -> None:
        # Sanity check that the "legacy" comparison run in this harness is
        # actually exercising the old per-tick behaviour, not accidentally
        # also using the registry — otherwise the parity test above would
        # be vacuous.
        _, smart, chain_fetchers, _ = _run_with_registry(3, None)
        assert smart.searchScrip.call_count == 3 * 2  # 3 ticks x 2 expiries
        assert all(f.registry is None for f in chain_fetchers)

    def test_legacy_path_also_fully_succeeds(self) -> None:
        legacy_result, _, _, _ = _run_with_registry(3, None)
        assert legacy_result.successful_polls == 3
        assert legacy_result.failed_polls == 0
