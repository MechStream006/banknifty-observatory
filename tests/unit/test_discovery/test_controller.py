"""Unit tests for lib.discovery.controller.DiscoveryController.

Dependency injection pattern: all components are MagicMock stubs.
The scheduler stub yields a fixed sequence of datetimes; tests control
the sequence length to bound how many ticks the controller processes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from lib.discovery._errors import (
    ArchiverError,
    SessionAcquireError,
    SessionRefreshError,
    StoreError,
)
from lib.discovery._models import (
    OBSERVATION_SCHEMA_VERSION,
    ChainResult,
    ObservationRecord,
    PhaseConfig,
    PhaseResult,
    VIXResult,
)
from lib.discovery.controller import (
    DiscoveryController,
    _STATE_ABORTED,
    _STATE_IDLE,
    _STATE_RUNNING,
    _STATE_STOPPED,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────────

_DT_BASE = datetime(2026, 6, 23, 4, 0, 0, tzinfo=timezone.utc)
_DT_1    = datetime(2026, 6, 23, 4, 0, 5, tzinfo=timezone.utc)
_DT_2    = datetime(2026, 6, 23, 4, 0, 10, tzinfo=timezone.utc)
_DT_3    = datetime(2026, 6, 23, 4, 0, 15, tzinfo=timezone.utc)

_DATA_DIR = Path("/tmp/bno_test")
_DB_PATH  = _DATA_DIR / "discovery.db"

# Phase-1 derived-observation test fixtures
_EXPIRY    = "26JUN2026"
_EXPIRY_2Y = "26JUN26"   # 7-char 2-digit-year used in live symbols


def _sym(strike: int, side: str) -> str:
    return f"BANKNIFTY{_EXPIRY_2Y}{strike}{side}"


def _row(strike: int, side: str, oi: int, vol: int = 0) -> dict:
    # "tradeVolume" is the real SmartAPI FULL-mode field name (matches the live
    # NFO payload). Do not revert to "tradVol"/"volume" — those matched no real
    # row and masked the production null-volume_pcr bug.
    return {
        "tradingSymbol": _sym(strike, side),
        "expiryDate": _EXPIRY,
        "ltp": 100.0,
        "opnInterest": oi,
        "tradeVolume": vol,
    }


def _make_config(
    *,
    phase: int = 1,
    interval_seconds: int = 5,
    max_duration_seconds: int | None = None,
) -> PhaseConfig:
    return PhaseConfig(
        phase=phase,
        interval_seconds=interval_seconds,
        max_duration_seconds=max_duration_seconds,
        data_dir=_DATA_DIR,
        db_path=_DB_PATH,
    )


def _make_chain_result(*, success: bool = True) -> ChainResult:
    return ChainResult(
        fetched_at=_DT_BASE,
        latency_ms=120.0,
        http_status=None,
        response_bytes=4096,
        raw_response={"status": True, "data": {"fetched": [], "unfetched": []}} if success else None,
        row_count=10 if success else 0,
        expiry_count=1 if success else 0,
        unfetched_count=0,
        error=None if success else "chain_api_error",
        success=success,
    )


def _make_chain_result_with_rows(rows: list[dict]) -> ChainResult:
    return ChainResult(
        fetched_at=_DT_BASE,
        latency_ms=120.0,
        http_status=None,
        response_bytes=4096,
        raw_response={"status": True, "data": {"fetched": rows, "unfetched": []}},
        row_count=len(rows),
        expiry_count=1,
        unfetched_count=0,
        error=None,
        success=True,
    )


def _make_spot_result(*, success: bool = True, ltp: float = 47000.0):
    from lib.discovery._models import SpotResult
    return SpotResult(
        fetched_at=_DT_BASE,
        latency_ms=45.0,
        ltp=ltp if success else None,
        raw_response={"status": True, "data": {"ltp": ltp}} if success else None,
        source="separate_call",
        error=None if success else "spot_api_error",
        success=success,
    )


def _make_vix_result(*, success: bool = True) -> VIXResult:
    return VIXResult(
        fetched_at=_DT_BASE,
        latency_ms=25.0,
        ltp=14.5 if success else None,
        raw_response={"status": True, "data": {"ltp": 14.5}} if success else None,
        error=None if success else "vix_api_error",
        success=success,
    )


class _SchedulerStub:
    """Yields a fixed sequence of UTC datetimes, then stops."""

    def __init__(self, *tick_dts: datetime) -> None:
        self._ticks = list(tick_dts)

    def ticks(self):  # type: ignore[return]
        yield from self._ticks


def _make_archiver(*, file_path: Path | None = None) -> MagicMock:
    arch = MagicMock()
    arch.current_file_path = file_path or (_DATA_DIR / "raw" / "20260623.jsonl")
    return arch


def _make_session() -> MagicMock:
    sess = MagicMock()
    sess.refresh_if_needed.return_value = False
    sess.smart = MagicMock()
    return sess


def _make_controller(
    *,
    config: PhaseConfig | None = None,
    session: MagicMock | None = None,
    chain_fetchers: list[MagicMock] | None = None,
    spot_fetcher: MagicMock | None = None,
    vix_fetcher: MagicMock | None = None,
    expiries: list[str] | None = None,
    chain_step_size: int = 500,
    chain_window_steps: int = 15,
    scheduler: _SchedulerStub | None = None,
    archiver: MagicMock | None = None,
    store: MagicMock | None = None,
    underlying: str = "BANKNIFTY",
    run_id: str | None = None,
    registry: MagicMock | None = None,
    validator: MagicMock | None = None,
    quality_archiver: MagicMock | None = None,
) -> DiscoveryController:
    if config is None:
        config = _make_config()
    if session is None:
        session = _make_session()
    if chain_fetchers is None:
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result()
        chain_fetchers = [cf]
    if expiries is None:
        expiries = [f"EXP{i}" for i in range(len(chain_fetchers))]
    if spot_fetcher is None:
        spot_fetcher = MagicMock()
        spot_fetcher.fetch.return_value = _make_spot_result()
    if vix_fetcher is None:
        vix_fetcher = MagicMock()
        vix_fetcher.fetch.return_value = _make_vix_result()
    if scheduler is None:
        scheduler = _SchedulerStub(_DT_1, _DT_2)
    if archiver is None:
        archiver = _make_archiver()
    return DiscoveryController(
        config=config,
        session=session,
        chain_fetchers=chain_fetchers,
        spot_fetcher=spot_fetcher,
        vix_fetcher=vix_fetcher,
        expiries=expiries,
        chain_step_size=chain_step_size,
        chain_window_steps=chain_window_steps,
        scheduler=scheduler,
        archiver=archiver,
        store=store,
        underlying=underlying,
        run_id=run_id,
        registry=registry,
        validator=validator,
        quality_archiver=quality_archiver,
    )


# ── Initial state ────────────────────────────────────────────────────────────────


class TestInitialState:
    def test_state_is_idle_before_run(self) -> None:
        ctrl = _make_controller()
        assert ctrl.state == _STATE_IDLE

    def test_state_property_is_read_only(self) -> None:
        ctrl = _make_controller()
        with pytest.raises(AttributeError):
            ctrl.state = "running"  # type: ignore[misc]


# ── Normal startup and run ───────────────────────────────────────────────────────


class TestNormalRun:
    def test_run_returns_phase_result(self) -> None:
        ctrl = _make_controller()
        result = ctrl.run()
        assert isinstance(result, PhaseResult)

    def test_state_is_stopped_after_normal_run(self) -> None:
        ctrl = _make_controller()
        ctrl.run()
        assert ctrl.state == _STATE_STOPPED

    def test_archiver_opened_once(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch)
        ctrl.run()
        arch.open.assert_called_once()

    def test_archiver_closed_after_normal_run(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch)
        ctrl.run()
        arch.close.assert_called_once()

    def test_session_connect_called_once(self) -> None:
        sess = _make_session()
        ctrl = _make_controller(session=sess)
        ctrl.run()
        sess.connect.assert_called_once()

    def test_archiver_opened_before_session_connect(self) -> None:
        call_order: list[str] = []
        arch = _make_archiver()
        arch.open.side_effect = lambda: call_order.append("archiver.open")
        sess = _make_session()
        sess.connect.side_effect = lambda: call_order.append("session.connect")
        ctrl = _make_controller(session=sess, archiver=arch)
        ctrl.run()
        assert call_order == ["archiver.open", "session.connect"]

    def test_result_phase_matches_config(self) -> None:
        ctrl = _make_controller(config=_make_config(phase=3))
        result = ctrl.run()
        assert result.phase == 3

    def test_result_ended_early_false_on_normal_run(self) -> None:
        ctrl = _make_controller()
        result = ctrl.run()
        assert result.ended_early is False

    def test_result_db_path_matches_config(self) -> None:
        ctrl = _make_controller()
        result = ctrl.run()
        assert result.db_path == _DB_PATH

    def test_result_jsonl_path_from_archiver(self) -> None:
        expected_path = _DATA_DIR / "raw" / "20260623.jsonl"
        arch = _make_archiver(file_path=expected_path)
        ctrl = _make_controller(archiver=arch)
        result = ctrl.run()
        assert result.jsonl_path == expected_path

    def test_result_session_id_is_nonempty_string(self) -> None:
        ctrl = _make_controller()
        result = ctrl.run()
        assert isinstance(result.session_id, str)
        assert len(result.session_id) > 0

    def test_result_started_at_before_ended_at(self) -> None:
        ctrl = _make_controller()
        result = ctrl.run()
        assert result.started_at <= result.ended_at

    def test_result_jsonl_path_fallback_when_archiver_has_no_path(self) -> None:
        arch = _make_archiver()
        arch.current_file_path = None
        ctrl = _make_controller(archiver=arch)
        result = ctrl.run()
        assert result.jsonl_path == _DATA_DIR / "raw" / "unavailable.jsonl"


# ── Startup failure: archiver ────────────────────────────────────────────────────


class TestStartupArchiverFailure:
    def test_archiver_open_failure_returns_phase_result(self) -> None:
        arch = _make_archiver()
        arch.open.side_effect = ArchiverError("disk full")
        ctrl = _make_controller(archiver=arch)
        result = ctrl.run()
        assert isinstance(result, PhaseResult)

    def test_archiver_open_failure_sets_ended_early(self) -> None:
        arch = _make_archiver()
        arch.open.side_effect = ArchiverError("disk full")
        ctrl = _make_controller(archiver=arch)
        result = ctrl.run()
        assert result.ended_early is True

    def test_session_not_connected_when_archiver_fails(self) -> None:
        arch = _make_archiver()
        arch.open.side_effect = ArchiverError("disk full")
        sess = _make_session()
        ctrl = _make_controller(session=sess, archiver=arch)
        ctrl.run()
        sess.connect.assert_not_called()

    def test_state_is_aborted_after_archiver_open_failure(self) -> None:
        arch = _make_archiver()
        arch.open.side_effect = ArchiverError("disk full")
        ctrl = _make_controller(archiver=arch)
        ctrl.run()
        assert ctrl.state == _STATE_ABORTED

    def test_zero_ticks_on_archiver_failure(self) -> None:
        arch = _make_archiver()
        arch.open.side_effect = ArchiverError("permission denied")
        ctrl = _make_controller(archiver=arch)
        result = ctrl.run()
        assert result.total_ticks == 0


# ── Startup failure: session ─────────────────────────────────────────────────────


class TestStartupSessionFailure:
    def test_session_connect_failure_returns_phase_result(self) -> None:
        sess = _make_session()
        sess.connect.side_effect = SessionAcquireError("both attempts failed", attempt=2)
        ctrl = _make_controller(session=sess)
        result = ctrl.run()
        assert isinstance(result, PhaseResult)

    def test_session_connect_failure_sets_ended_early(self) -> None:
        sess = _make_session()
        sess.connect.side_effect = SessionAcquireError("both attempts failed", attempt=2)
        ctrl = _make_controller(session=sess)
        result = ctrl.run()
        assert result.ended_early is True

    def test_archiver_closed_when_session_connect_fails(self) -> None:
        arch = _make_archiver()
        sess = _make_session()
        sess.connect.side_effect = SessionAcquireError("both attempts failed", attempt=2)
        ctrl = _make_controller(session=sess, archiver=arch)
        ctrl.run()
        arch.close.assert_called_once()

    def test_state_is_aborted_after_session_connect_failure(self) -> None:
        sess = _make_session()
        sess.connect.side_effect = SessionAcquireError("both attempts failed", attempt=2)
        ctrl = _make_controller(session=sess)
        ctrl.run()
        assert ctrl.state == _STATE_ABORTED

    def test_zero_ticks_when_session_connect_fails(self) -> None:
        sess = _make_session()
        sess.connect.side_effect = SessionAcquireError("both attempts failed", attempt=2)
        ctrl = _make_controller(session=sess)
        result = ctrl.run()
        assert result.total_ticks == 0


# ── Poll loop behaviour ──────────────────────────────────────────────────────────


class TestPollLoop:
    def test_tick_count_equals_scheduler_ticks(self) -> None:
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        result = ctrl.run()
        assert result.total_ticks == 3

    def test_chain_fetchers_called_per_tick(self) -> None:
        chain = MagicMock()
        chain.fetch.return_value = _make_chain_result()
        ctrl = _make_controller(
            chain_fetchers=[chain], scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        assert chain.fetch.call_count == 2

    def test_spot_fetcher_called_per_tick(self) -> None:
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result()
        ctrl = _make_controller(spot_fetcher=spot, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        assert spot.fetch.call_count == 2

    def test_spot_fetcher_called_with_smart(self) -> None:
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result()
        sess = _make_session()
        ctrl = _make_controller(
            session=sess, spot_fetcher=spot,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        spot.fetch.assert_called_once_with(sess.smart)

    def test_chain_fetcher_receives_smart_and_spot_ltp(self) -> None:
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(ltp=47000.0)
        chain = MagicMock()
        chain.fetch.return_value = _make_chain_result()
        sess = _make_session()
        ctrl = _make_controller(
            session=sess, spot_fetcher=spot, chain_fetchers=[chain],
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        chain.fetch.assert_called_once()
        args = chain.fetch.call_args[0]
        assert args[0] is sess.smart
        assert args[1] == 47000.0

    def test_refresh_called_before_each_tick(self) -> None:
        call_order: list[str] = []
        sess = _make_session()
        sess.refresh_if_needed.side_effect = lambda: call_order.append("refresh")
        chain = MagicMock()
        chain.fetch.side_effect = lambda *a: (call_order.append("chain"), _make_chain_result())[1]
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result()
        ctrl = _make_controller(
            session=sess, chain_fetchers=[chain], spot_fetcher=spot,
            scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        # refresh is called first each tick; spot/vix happen before chain
        assert call_order == ["refresh", "chain", "refresh", "chain"]

    def test_archiver_write_called_per_tick(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        assert arch.write.call_count == 2

    def test_poll_record_is_dict_in_archiver_write(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        written = arch.write.call_args[0][0]
        assert isinstance(written, dict)

    def test_written_dict_contains_poll_id(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        written = arch.write.call_args[0][0]
        assert "poll_id" in written

    def test_written_dict_contains_chains_spot_and_vix(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        written = arch.write.call_args[0][0]
        assert "chains" in written
        assert "spot" in written
        assert "vix" in written
        assert "meta" in written

    def test_tick_numbers_are_sequential_from_one(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        ctrl.run()
        tick_numbers = [arch.write.call_args_list[i][0][0]["tick_number"] for i in range(3)]
        assert tick_numbers == [1, 2, 3]

    def test_session_id_is_constant_within_run(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        ids = [arch.write.call_args_list[i][0][0]["session_id"] for i in range(2)]
        assert ids[0] == ids[1]

    def test_session_id_in_records_matches_result(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        result = ctrl.run()
        written_session_id = arch.write.call_args[0][0]["session_id"]
        assert written_session_id == result.session_id

    def test_poll_ids_are_unique_across_ticks(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        ctrl.run()
        poll_ids = [arch.write.call_args_list[i][0][0]["poll_id"] for i in range(3)]
        assert len(set(poll_ids)) == 3

    def test_session_ids_differ_across_separate_runs(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        result1 = ctrl.run()
        ctrl._scheduler = _SchedulerStub(_DT_2)
        result2 = ctrl.run()
        assert result1.session_id != result2.session_id

    def test_all_successful_polls_counted(self) -> None:
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        result = ctrl.run()
        assert result.successful_polls == 3
        assert result.failed_polls == 0


# ── Recoverable failures ─────────────────────────────────────────────────────────


class TestRecoverableFailures:
    def test_chain_failure_does_not_abort_phase(self) -> None:
        chain = MagicMock()
        chain.fetch.return_value = _make_chain_result(success=False)
        ctrl = _make_controller(
            chain_fetchers=[chain], scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        result = ctrl.run()
        assert result.ended_early is False

    def test_chain_failure_counted_as_failed_poll(self) -> None:
        chain = MagicMock()
        chain.fetch.side_effect = [
            _make_chain_result(success=False),
            _make_chain_result(success=True),
        ]
        ctrl = _make_controller(
            chain_fetchers=[chain], scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        result = ctrl.run()
        assert result.failed_polls == 1
        assert result.successful_polls == 1

    def test_spot_failure_does_not_abort_phase(self) -> None:
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        ctrl = _make_controller(
            spot_fetcher=spot, scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        result = ctrl.run()
        assert result.ended_early is False

    def test_spot_failure_counts_as_failed_poll(self) -> None:
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        ctrl = _make_controller(
            spot_fetcher=spot, scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        result = ctrl.run()
        # spot failure gates chain fetch → chains=[] → any([]) is False → failed
        assert result.failed_polls == 2
        assert result.successful_polls == 0

    def test_record_written_even_when_chain_fails(self) -> None:
        arch = _make_archiver()
        chain = MagicMock()
        chain.fetch.return_value = _make_chain_result(success=False)
        ctrl = _make_controller(
            archiver=arch, chain_fetchers=[chain], scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        assert arch.write.call_count == 2

    def test_store_write_failure_does_not_abort_phase(self) -> None:
        store = MagicMock()
        store.insert.side_effect = StoreError("SQLite write failed")
        ctrl = _make_controller(
            store=store, scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        result = ctrl.run()
        assert result.ended_early is False

    def test_store_write_failure_does_not_interrupt_poll_loop(self) -> None:
        store = MagicMock()
        store.insert.side_effect = StoreError("SQLite write failed")
        arch = _make_archiver()
        ctrl = _make_controller(
            store=store, archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        assert arch.write.call_count == 2


# ── Fatal failures ────────────────────────────────────────────────────────────────


class TestFatalFailures:
    def test_archiver_write_failure_aborts_phase(self) -> None:
        arch = _make_archiver()
        arch.write.side_effect = ArchiverError("disk full")
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.ended_early is True

    def test_archiver_write_failure_stops_after_first_error(self) -> None:
        arch = _make_archiver()
        arch.write.side_effect = ArchiverError("disk full")
        chain = MagicMock()
        chain.fetch.return_value = _make_chain_result()
        ctrl = _make_controller(
            archiver=arch, chain_fetchers=[chain],
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        ctrl.run()
        assert chain.fetch.call_count == 1

    def test_archiver_closed_after_write_failure(self) -> None:
        arch = _make_archiver()
        arch.write.side_effect = ArchiverError("disk full")
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        arch.close.assert_called_once()

    def test_state_aborted_after_archiver_write_failure(self) -> None:
        arch = _make_archiver()
        arch.write.side_effect = ArchiverError("disk full")
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert ctrl.state == _STATE_ABORTED

    def test_session_refresh_failure_aborts_phase(self) -> None:
        sess = _make_session()
        sess.refresh_if_needed.side_effect = SessionRefreshError("token expired")
        ctrl = _make_controller(session=sess, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.ended_early is True

    def test_session_refresh_failure_stops_after_first_error(self) -> None:
        sess = _make_session()
        sess.refresh_if_needed.side_effect = SessionRefreshError("token expired")
        chain = MagicMock()
        chain.fetch.return_value = _make_chain_result()
        ctrl = _make_controller(
            session=sess, chain_fetchers=[chain],
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        ctrl.run()
        chain.fetch.assert_not_called()

    def test_archiver_closed_after_refresh_failure(self) -> None:
        arch = _make_archiver()
        sess = _make_session()
        sess.refresh_if_needed.side_effect = SessionRefreshError("token expired")
        ctrl = _make_controller(session=sess, archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        arch.close.assert_called_once()

    def test_state_aborted_after_refresh_failure(self) -> None:
        sess = _make_session()
        sess.refresh_if_needed.side_effect = SessionRefreshError("token expired")
        ctrl = _make_controller(session=sess, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert ctrl.state == _STATE_ABORTED

    def test_refresh_failure_tick_not_written_to_archiver(self) -> None:
        arch = _make_archiver()
        sess = _make_session()
        sess.refresh_if_needed.side_effect = SessionRefreshError("token expired")
        ctrl = _make_controller(
            session=sess, archiver=arch, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        arch.write.assert_not_called()


# ── Max duration cap ─────────────────────────────────────────────────────────────


class TestMaxDuration:
    def test_max_duration_stops_poll_loop(self) -> None:
        times = iter([
            datetime(2026, 6, 23, 4, 0, 0, tzinfo=timezone.utc),   # started_at
            datetime(2026, 6, 23, 4, 0, 3, tzinfo=timezone.utc),   # tick 1: 3s < 10s
            datetime(2026, 6, 23, 4, 0, 7, tzinfo=timezone.utc),   # tick 2: 7s < 10s
            datetime(2026, 6, 23, 4, 0, 11, tzinfo=timezone.utc),  # tick 3: 11s ≥ 10s → break
            datetime(2026, 6, 23, 4, 0, 12, tzinfo=timezone.utc),  # ended_at
        ])
        with patch("lib.discovery.controller._utc_now", side_effect=lambda: next(times)):
            ctrl = _make_controller(
                config=_make_config(max_duration_seconds=10),
                scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
            )
            result = ctrl.run()
        assert result.total_ticks == 2

    def test_max_duration_exit_is_not_ended_early(self) -> None:
        times = iter([
            datetime(2026, 6, 23, 4, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 23, 4, 0, 11, tzinfo=timezone.utc),  # 11s ≥ 10s → break
            datetime(2026, 6, 23, 4, 0, 12, tzinfo=timezone.utc),
        ])
        with patch("lib.discovery.controller._utc_now", side_effect=lambda: next(times)):
            ctrl = _make_controller(
                config=_make_config(max_duration_seconds=10),
                scheduler=_SchedulerStub(_DT_1, _DT_2),
            )
            result = ctrl.run()
        assert result.ended_early is False

    def test_no_max_duration_runs_all_ticks(self) -> None:
        ctrl = _make_controller(
            config=_make_config(max_duration_seconds=None),
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        result = ctrl.run()
        assert result.total_ticks == 3


# ── Keyboard interrupt ───────────────────────────────────────────────────────────


class TestKeyboardInterrupt:
    def test_keyboard_interrupt_returns_phase_result(self) -> None:
        sess = _make_session()
        sess.refresh_if_needed.side_effect = [False, KeyboardInterrupt]
        ctrl = _make_controller(session=sess, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert isinstance(result, PhaseResult)

    def test_keyboard_interrupt_not_ended_early(self) -> None:
        sess = _make_session()
        sess.refresh_if_needed.side_effect = [False, KeyboardInterrupt]
        ctrl = _make_controller(session=sess, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.ended_early is False

    def test_archiver_closed_on_keyboard_interrupt(self) -> None:
        arch = _make_archiver()
        sess = _make_session()
        sess.refresh_if_needed.side_effect = [False, KeyboardInterrupt]
        ctrl = _make_controller(
            session=sess, archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        arch.close.assert_called_once()

    def test_keyboard_interrupt_counts_completed_ticks(self) -> None:
        arch = _make_archiver()
        sess = _make_session()
        sess.refresh_if_needed.side_effect = [False, KeyboardInterrupt]
        ctrl = _make_controller(
            session=sess, archiver=arch, scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        result = ctrl.run()
        assert result.total_ticks == 1
        assert arch.write.call_count == 1


# ── Unhandled exceptions ─────────────────────────────────────────────────────────


class TestUnhandledException:
    def test_unhandled_exception_propagates_from_run(self) -> None:
        sess = _make_session()
        sess.refresh_if_needed.side_effect = RuntimeError("unexpected internal error")
        ctrl = _make_controller(session=sess, scheduler=_SchedulerStub(_DT_1))
        with pytest.raises(RuntimeError, match="unexpected internal error"):
            ctrl.run()

    def test_archiver_closed_on_unhandled_exception(self) -> None:
        arch = _make_archiver()
        sess = _make_session()
        sess.refresh_if_needed.side_effect = RuntimeError("unexpected internal error")
        ctrl = _make_controller(
            session=sess, archiver=arch, scheduler=_SchedulerStub(_DT_1),
        )
        with pytest.raises(RuntimeError):
            ctrl.run()
        arch.close.assert_called_once()


# ── Store integration ────────────────────────────────────────────────────────────


class TestStoreIntegration:
    def test_store_insert_called_per_tick_when_provided(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        assert store.insert.call_count == 2

    def test_store_insert_not_called_when_store_is_none(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=None, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        store.insert.assert_not_called()

    def test_store_insert_receives_observation_record(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert isinstance(record, ObservationRecord)

    def test_jsonl_written_before_store_insert(self) -> None:
        call_order: list[str] = []
        arch = _make_archiver()
        arch.write.side_effect = lambda *a: call_order.append("jsonl")
        store = MagicMock()
        store.insert.side_effect = lambda *a: call_order.append("store")
        ctrl = _make_controller(
            archiver=arch, store=store, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        assert call_order == ["jsonl", "store"]

    def test_store_insert_tick_count_matches_archiver_write_count(self) -> None:
        store = MagicMock()
        arch = _make_archiver()
        ctrl = _make_controller(
            archiver=arch, store=store, scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        ctrl.run()
        assert store.insert.call_count == arch.write.call_count == 3


# ── Multi-expiry chain fetch ──────────────────────────────────────────────────────


class TestMultiExpiryChains:
    def test_each_chain_fetcher_called_once_per_tick(self) -> None:
        cf1 = MagicMock()
        cf1.fetch.return_value = _make_chain_result()
        cf2 = MagicMock()
        cf2.fetch.return_value = _make_chain_result()
        ctrl = _make_controller(
            chain_fetchers=[cf1, cf2], expiries=["26JUN2026", "30JUN2026"],
            scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        assert cf1.fetch.call_count == 2
        assert cf2.fetch.call_count == 2

    def test_chains_list_length_matches_expiry_count(self) -> None:
        store = MagicMock()
        cf1 = MagicMock()
        cf1.fetch.return_value = _make_chain_result()
        cf2 = MagicMock()
        cf2.fetch.return_value = _make_chain_result()
        ctrl = _make_controller(
            chain_fetchers=[cf1, cf2], expiries=["26JUN2026", "30JUN2026"],
            store=store, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert len(record.chains) == 2

    def test_expiry_set_in_meta_matches_constructor_expiries(self) -> None:
        store = MagicMock()
        expiries = ["26JUN2026", "30JUN2026"]
        cf1 = MagicMock()
        cf1.fetch.return_value = _make_chain_result()
        cf2 = MagicMock()
        cf2.fetch.return_value = _make_chain_result()
        ctrl = _make_controller(
            chain_fetchers=[cf1, cf2], expiries=expiries,
            store=store, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.meta.expiry_set == expiries

    def test_partial_chain_success_counts_as_successful_poll(self) -> None:
        cf1 = MagicMock()
        cf1.fetch.return_value = _make_chain_result(success=True)
        cf2 = MagicMock()
        cf2.fetch.return_value = _make_chain_result(success=False)
        ctrl = _make_controller(
            chain_fetchers=[cf1, cf2], expiries=["26JUN2026", "30JUN2026"],
            scheduler=_SchedulerStub(_DT_1),
        )
        result = ctrl.run()
        assert result.successful_polls == 1
        assert result.failed_polls == 0

    def test_all_chain_failures_count_as_failed_poll(self) -> None:
        cf1 = MagicMock()
        cf1.fetch.return_value = _make_chain_result(success=False)
        cf2 = MagicMock()
        cf2.fetch.return_value = _make_chain_result(success=False)
        ctrl = _make_controller(
            chain_fetchers=[cf1, cf2], expiries=["26JUN2026", "30JUN2026"],
            scheduler=_SchedulerStub(_DT_1),
        )
        result = ctrl.run()
        assert result.successful_polls == 0
        assert result.failed_polls == 1


# ── VIX integration ──────────────────────────────────────────────────────────────


class TestVIXIntegration:
    def test_vix_fetcher_called_per_tick(self) -> None:
        vix = MagicMock()
        vix.fetch.return_value = _make_vix_result()
        ctrl = _make_controller(vix_fetcher=vix, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        assert vix.fetch.call_count == 2

    def test_vix_result_stored_in_observation_record(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert isinstance(record.vix, VIXResult)

    def test_vix_failure_does_not_abort_phase(self) -> None:
        vix = MagicMock()
        vix.fetch.return_value = _make_vix_result(success=False)
        ctrl = _make_controller(vix_fetcher=vix, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.ended_early is False

    def test_vix_failure_does_not_affect_poll_success_count(self) -> None:
        vix = MagicMock()
        vix.fetch.return_value = _make_vix_result(success=False)
        ctrl = _make_controller(vix_fetcher=vix, scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        # chain success drives the counter; VIX is independent
        assert result.successful_polls == 2


# ── Spot failure gate ────────────────────────────────────────────────────────────


class TestSpotFailureGate:
    def test_spot_failure_skips_chain_fetchers(self) -> None:
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        cf = MagicMock()
        ctrl = _make_controller(
            chain_fetchers=[cf], spot_fetcher=spot, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        cf.fetch.assert_not_called()

    def test_spot_failure_record_has_empty_chains(self) -> None:
        store = MagicMock()
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        ctrl = _make_controller(
            spot_fetcher=spot, store=store, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.chains == []

    def test_spot_failure_record_has_none_derived(self) -> None:
        store = MagicMock()
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        ctrl = _make_controller(
            spot_fetcher=spot, store=store, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is None

    def test_spot_failure_still_fetches_vix(self) -> None:
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        vix = MagicMock()
        vix.fetch.return_value = _make_vix_result()
        ctrl = _make_controller(
            spot_fetcher=spot, vix_fetcher=vix, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        vix.fetch.assert_called_once()


# ── OI state tracking across ticks ───────────────────────────────────────────────


class TestOIStateAcrossTicks:
    def test_oi_changes_none_on_first_tick(self) -> None:
        store = MagicMock()
        rows = [_row(58000, "CE", oi=1000), _row(58000, "PE", oi=800)]
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is not None
        assert record.derived.oi_changes is None

    def test_oi_changes_populated_from_second_tick(self) -> None:
        store = MagicMock()
        cf = MagicMock()
        cf.fetch.side_effect = [
            _make_chain_result_with_rows([_row(58000, "CE", oi=1000)]),
            _make_chain_result_with_rows([_row(58000, "CE", oi=1200)]),
        ]
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        record_tick2 = store.insert.call_args_list[1][0][0]
        assert record_tick2.derived is not None
        assert record_tick2.derived.oi_changes is not None

    def test_oi_delta_computed_correctly(self) -> None:
        store = MagicMock()
        cf = MagicMock()
        cf.fetch.side_effect = [
            _make_chain_result_with_rows([_row(58000, "CE", oi=1000)]),
            _make_chain_result_with_rows([_row(58000, "CE", oi=1200)]),
        ]
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        record_tick2 = store.insert.call_args_list[1][0][0]
        changes = record_tick2.derived.oi_changes
        assert len(changes) == 1
        assert changes[0].side == "CE"
        assert changes[0].strike == 58000
        assert changes[0].delta == 200  # 1200 - 1000

    def test_oi_state_retained_when_chain_fails(self) -> None:
        store = MagicMock()
        cf = MagicMock()
        cf.fetch.side_effect = [
            _make_chain_result_with_rows([_row(58000, "CE", oi=1000)]),
            _make_chain_result(success=False),
            _make_chain_result_with_rows([_row(58000, "CE", oi=1200)]),
        ]
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        ctrl.run()
        record_tick3 = store.insert.call_args_list[2][0][0]
        # delta compares to tick 1 because tick 2 failure retained tick 1 OI state
        assert record_tick3.derived is not None
        assert record_tick3.derived.oi_changes is not None
        assert record_tick3.derived.oi_changes[0].delta == 200

    def test_spot_failure_does_not_update_oi_state(self) -> None:
        store = MagicMock()
        cf = MagicMock()
        cf.fetch.side_effect = [
            _make_chain_result_with_rows([_row(58000, "CE", oi=1000)]),
            # tick 2: spot fails → chain not called
            _make_chain_result_with_rows([_row(58000, "CE", oi=1200)]),
        ]
        spot_mock = MagicMock()
        spot_mock.fetch.side_effect = [
            _make_spot_result(success=True),
            _make_spot_result(success=False),
            _make_spot_result(success=True),
        ]
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY],
            spot_fetcher=spot_mock, store=store,
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        ctrl.run()
        record_tick3 = store.insert.call_args_list[2][0][0]
        assert record_tick3.derived is not None
        assert record_tick3.derived.oi_changes is not None
        # tick 2 spot failure left _prev_oi from tick 1 intact
        assert record_tick3.derived.oi_changes[0].delta == 200


# ── DerivedObservation correctness ───────────────────────────────────────────────


class TestDerivedObservation:
    def test_derived_totals_computed_from_chain_rows(self) -> None:
        store = MagicMock()
        rows = [
            _row(58000, "CE", oi=2000, vol=500),
            _row(57500, "CE", oi=1500, vol=300),
            _row(58000, "PE", oi=3000, vol=600),
        ]
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is not None
        assert record.derived.total_ce_oi[_EXPIRY] == 3500
        assert record.derived.total_pe_oi[_EXPIRY] == 3000

    def test_oi_pcr_computed_correctly(self) -> None:
        store = MagicMock()
        rows = [_row(58000, "CE", oi=1000), _row(58000, "PE", oi=800)]
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is not None
        assert record.derived.oi_pcr[_EXPIRY] == 0.8  # 800 / 1000

    def test_volume_pcr_computed_correctly(self) -> None:
        store = MagicMock()
        rows = [
            _row(58000, "CE", oi=1000, vol=400),
            _row(58000, "PE", oi=800,  vol=600),
        ]
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is not None
        assert record.derived.volume_pcr[_EXPIRY] == 1.5  # 600 / 400

    def test_volume_read_from_live_tradeVolume_field(self) -> None:
        """Locks the real SmartAPI field name.

        Builds rows with the literal "tradeVolume" key exactly as the live NFO
        FULL-mode payload delivers it — deliberately NOT via the _row helper —
        so this fails if the parser stops reading "tradeVolume". This is the
        regression guard for the production null-volume_pcr incident.
        """
        store = MagicMock()
        rows = [
            {"tradingSymbol": _sym(58000, "CE"), "expiryDate": _EXPIRY,
             "ltp": 100.0, "opnInterest": 1000, "tradeVolume": 12150},
            {"tradingSymbol": _sym(58000, "PE"), "expiryDate": _EXPIRY,
             "ltp": 100.0, "opnInterest": 800, "tradeVolume": 24300},
        ]
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is not None
        assert record.derived.volume_pcr[_EXPIRY] == 2.0  # 24300 / 12150

    def test_volume_pcr_none_when_ce_volume_zero(self) -> None:
        store = MagicMock()
        rows = [
            _row(58000, "CE", oi=1000, vol=0),
            _row(58000, "PE", oi=800,  vol=500),
        ]
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived.volume_pcr[_EXPIRY] is None

    def test_oi_pcr_none_when_ce_oi_zero(self) -> None:
        store = MagicMock()
        rows = [_row(58000, "PE", oi=800)]
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        ctrl = _make_controller(
            chain_fetchers=[cf], expiries=[_EXPIRY], store=store,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived.oi_pcr[_EXPIRY] is None

    def test_derived_none_when_all_chains_fail(self) -> None:
        store = MagicMock()
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result(success=False)
        ctrl = _make_controller(
            chain_fetchers=[cf], store=store, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is None

    def test_derived_present_when_at_least_one_chain_succeeds(self) -> None:
        store = MagicMock()
        rows = [_row(58000, "CE", oi=1000)]
        cf1 = MagicMock()
        cf1.fetch.return_value = _make_chain_result_with_rows(rows)
        cf2 = MagicMock()
        cf2.fetch.return_value = _make_chain_result(success=False)
        ctrl = _make_controller(
            chain_fetchers=[cf1, cf2], expiries=["26JUN2026", "30JUN2026"],
            store=store, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.derived is not None


# ── ObservationRecord persistence shape ─────────────────────────────────────────


class TestObservationRecordPersistence:
    def test_store_insert_receives_observation_record(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert isinstance(record, ObservationRecord)

    def test_written_dict_has_required_keys(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        written = arch.write.call_args[0][0]
        for key in ("poll_id", "session_id", "chains", "spot", "vix", "meta", "derived"):
            assert key in written

    def test_written_dict_chains_is_list(self) -> None:
        arch = _make_archiver()
        ctrl = _make_controller(archiver=arch, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        written = arch.write.call_args[0][0]
        assert isinstance(written["chains"], list)

    def test_meta_schema_version_is_observation_schema_version(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        record = store.insert.call_args[0][0]
        assert record.meta.schema_version == OBSERVATION_SCHEMA_VERSION
