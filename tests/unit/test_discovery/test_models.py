"""Tests for lib.discovery._models: all shared dataclasses."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib.discovery._models import (
    OBSERVATION_SCHEMA_VERSION,
    ChainResult,
    DerivedObservation,
    OIChange,
    ObservationRecord,
    PhaseConfig,
    PhaseResult,
    PollRecord,
    SessionToken,
    SnapshotMeta,
    SmokeTestResult,
    SpotResult,
    VIXResult,
)

_NOW = datetime(2026, 1, 15, 9, 15, 0, tzinfo=timezone.utc)


# ── helpers ───────────────────────────────────────────────────────────────────


def _phase_config(**overrides: object) -> PhaseConfig:
    kwargs: dict[str, object] = dict(
        phase=1,
        interval_seconds=30,
        max_duration_seconds=None,
        data_dir=Path("/tmp/discovery"),
        db_path=Path("/tmp/discovery/analysis.db"),
    )
    kwargs.update(overrides)
    return PhaseConfig(**kwargs)  # type: ignore[arg-type]


def _session_token(**overrides: object) -> SessionToken:
    kwargs: dict[str, object] = dict(
        jwt_token="test-jwt-abc",
        refresh_token="test-refresh-abc",
        feed_token="test-feed-abc",
        acquired_at=_NOW,
        user_profile={"clientcode": "A123456", "name": "Test User"},
    )
    kwargs.update(overrides)
    return SessionToken(**kwargs)  # type: ignore[arg-type]


def _chain_result(**overrides: object) -> ChainResult:
    kwargs: dict[str, object] = dict(
        fetched_at=_NOW,
        latency_ms=87.5,
        http_status=200,
        response_bytes=143291,
        raw_response={"data": {"fetched": [], "unfetched": []}},
        row_count=312,
        expiry_count=3,
        unfetched_count=0,
        error=None,
        success=True,
    )
    kwargs.update(overrides)
    return ChainResult(**kwargs)  # type: ignore[arg-type]


def _spot_result(**overrides: object) -> SpotResult:
    kwargs: dict[str, object] = dict(
        fetched_at=_NOW,
        latency_ms=12.3,
        ltp=48250.0,
        raw_response={"ltp": 48250.0},
        source="chain_embedded",
        error=None,
        success=True,
    )
    kwargs.update(overrides)
    return SpotResult(**kwargs)  # type: ignore[arg-type]


def _poll_record(**overrides: object) -> PollRecord:
    kwargs: dict[str, object] = dict(
        poll_id="poll-uuid-0001",
        session_id="session-uuid-0001",
        polled_at=_NOW,
        phase=1,
        tick_number=1,
        interval_s=30,
        chain=_chain_result(),
        spot=_spot_result(),
    )
    kwargs.update(overrides)
    return PollRecord(**kwargs)  # type: ignore[arg-type]


def _vix_result(**overrides: object) -> VIXResult:
    kwargs: dict[str, object] = dict(
        fetched_at=_NOW,
        latency_ms=22.5,
        ltp=14.35,
        raw_response={"status": True, "data": {"ltp": 14.35}},
        error=None,
        success=True,
    )
    kwargs.update(overrides)
    return VIXResult(**kwargs)  # type: ignore[arg-type]


def _snapshot_meta(**overrides: object) -> SnapshotMeta:
    kwargs: dict[str, object] = dict(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        anchoring_spot=57845.95,
        resolved_atm=58000,
        expiry_set=["30JUN2026", "28JUL2026"],
        window_steps=15,
    )
    kwargs.update(overrides)
    return SnapshotMeta(**kwargs)  # type: ignore[arg-type]


def _oi_change(**overrides: object) -> OIChange:
    kwargs: dict[str, object] = dict(
        expiry="30JUN2026",
        side="CE",
        strike=58000,
        delta=5400,
    )
    kwargs.update(overrides)
    return OIChange(**kwargs)  # type: ignore[arg-type]


def _derived_observation(**overrides: object) -> DerivedObservation:
    kwargs: dict[str, object] = dict(
        total_ce_oi={"30JUN2026": 1_200_000, "28JUL2026": 400_000},
        total_pe_oi={"30JUN2026": 900_000, "28JUL2026": 350_000},
        oi_pcr={"30JUN2026": 0.75, "28JUL2026": 0.875},
        volume_pcr={"30JUN2026": 0.82, "28JUL2026": None},
    )
    kwargs.update(overrides)
    return DerivedObservation(**kwargs)  # type: ignore[arg-type]


def _observation_record(**overrides: object) -> ObservationRecord:
    kwargs: dict[str, object] = dict(
        poll_id="obs-poll-uuid-0001",
        session_id="obs-session-uuid-0001",
        polled_at=_NOW,
        phase=1,
        tick_number=1,
        interval_s=180,
        meta=_snapshot_meta(),
        spot=_spot_result(),
        vix=_vix_result(),
        chains=[_chain_result()],
    )
    kwargs.update(overrides)
    return ObservationRecord(**kwargs)  # type: ignore[arg-type]


# ── PhaseConfig ───────────────────────────────────────────────────────────────


class TestPhaseConfig:
    def test_instantiates(self) -> None:
        cfg = _phase_config()
        assert cfg.phase == 1

    def test_is_frozen(self) -> None:
        cfg = _phase_config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.phase = 99  # type: ignore[misc]

    def test_interval_seconds_stored(self) -> None:
        cfg = _phase_config(interval_seconds=5)
        assert cfg.interval_seconds == 5

    def test_max_duration_none(self) -> None:
        cfg = _phase_config(max_duration_seconds=None)
        assert cfg.max_duration_seconds is None

    def test_max_duration_int(self) -> None:
        cfg = _phase_config(max_duration_seconds=3600)
        assert cfg.max_duration_seconds == 3600

    def test_data_dir_is_path(self) -> None:
        cfg = _phase_config()
        assert isinstance(cfg.data_dir, Path)

    def test_db_path_is_path(self) -> None:
        cfg = _phase_config()
        assert isinstance(cfg.db_path, Path)

    def test_smoke_test_phase_zero(self) -> None:
        cfg = _phase_config(phase=0, interval_seconds=0)
        assert cfg.phase == 0
        assert cfg.interval_seconds == 0


# ── SessionToken ──────────────────────────────────────────────────────────────


class TestSessionToken:
    def test_instantiates(self) -> None:
        token = _session_token()
        assert token.jwt_token == "test-jwt-abc"

    def test_is_frozen(self) -> None:
        token = _session_token()
        with pytest.raises(dataclasses.FrozenInstanceError):
            token.jwt_token = "mutated"  # type: ignore[misc]

    def test_refresh_token_accessible(self) -> None:
        assert _session_token().refresh_token == "test-refresh-abc"

    def test_feed_token_accessible(self) -> None:
        assert _session_token().feed_token == "test-feed-abc"

    def test_acquired_at_is_datetime(self) -> None:
        assert isinstance(_session_token().acquired_at, datetime)

    def test_user_profile_is_dict(self) -> None:
        token = _session_token()
        assert isinstance(token.user_profile, dict)
        assert token.user_profile["clientcode"] == "A123456"

    def test_frozen_prevents_profile_replacement(self) -> None:
        token = _session_token()
        with pytest.raises(dataclasses.FrozenInstanceError):
            token.user_profile = {}  # type: ignore[misc]


# ── ChainResult ───────────────────────────────────────────────────────────────


class TestChainResult:
    def test_instantiates_success(self) -> None:
        result = _chain_result()
        assert result.success is True

    def test_is_not_frozen(self) -> None:
        result = _chain_result()
        result.row_count = 0
        assert result.row_count == 0

    def test_accepts_none_raw_response(self) -> None:
        result = _chain_result(raw_response=None, success=False, error="timeout")
        assert result.raw_response is None
        assert result.success is False

    def test_accepts_none_http_status(self) -> None:
        result = _chain_result(http_status=None, success=False, error="network")
        assert result.http_status is None

    def test_none_error_on_success(self) -> None:
        assert _chain_result(error=None, success=True).error is None

    def test_row_count_is_int(self) -> None:
        assert isinstance(_chain_result().row_count, int)

    def test_expiry_count_is_int(self) -> None:
        assert isinstance(_chain_result().expiry_count, int)

    def test_latency_ms_is_float(self) -> None:
        assert isinstance(_chain_result().latency_ms, float)

    def test_response_bytes_is_int(self) -> None:
        assert isinstance(_chain_result().response_bytes, int)

    def test_unfetched_count_is_int(self) -> None:
        assert isinstance(_chain_result().unfetched_count, int)


# ── SpotResult ────────────────────────────────────────────────────────────────


class TestSpotResult:
    def test_instantiates_success(self) -> None:
        result = _spot_result()
        assert result.success is True

    def test_is_not_frozen(self) -> None:
        result = _spot_result()
        result.ltp = 48300.0
        assert result.ltp == 48300.0

    def test_accepts_none_ltp(self) -> None:
        result = _spot_result(ltp=None, success=False, error="unavailable")
        assert result.ltp is None

    def test_accepts_none_raw_response(self) -> None:
        assert _spot_result(raw_response=None).raw_response is None

    @pytest.mark.parametrize(
        "source", ["chain_embedded", "separate_call", "unavailable"]
    )
    def test_valid_source_values(self, source: str) -> None:
        result = _spot_result(source=source)
        assert result.source == source

    def test_latency_ms_is_float(self) -> None:
        assert isinstance(_spot_result().latency_ms, float)


# ── PollRecord ────────────────────────────────────────────────────────────────


class TestPollRecord:
    def test_instantiates(self) -> None:
        record = _poll_record()
        assert record.poll_id == "poll-uuid-0001"

    def test_is_not_frozen(self) -> None:
        record = _poll_record()
        record.tick_number = 99
        assert record.tick_number == 99

    def test_carries_chain_result(self) -> None:
        chain = _chain_result()
        record = _poll_record(chain=chain)
        assert isinstance(record.chain, ChainResult)
        assert record.chain is chain

    def test_carries_spot_result(self) -> None:
        spot = _spot_result()
        record = _poll_record(spot=spot)
        assert isinstance(record.spot, SpotResult)
        assert record.spot is spot

    def test_session_id_stored(self) -> None:
        record = _poll_record(session_id="my-session")
        assert record.session_id == "my-session"

    def test_interval_s_stored(self) -> None:
        record = _poll_record(interval_s=5)
        assert record.interval_s == 5

    def test_polled_at_is_datetime(self) -> None:
        assert isinstance(_poll_record().polled_at, datetime)


# ── SmokeTestResult ───────────────────────────────────────────────────────────


class TestSmokeTestResult:
    def test_instantiates_passing(self) -> None:
        result = SmokeTestResult(
            passed=True,
            auth_latency_ms=120.0,
            chain_reachable=True,
            spot_reachable=True,
            sample_row_count=312,
            sample_expiry_count=3,
            blocking_issues=[],
        )
        assert result.passed is True
        assert result.blocking_issues == []

    def test_instantiates_failing(self) -> None:
        result = SmokeTestResult(
            passed=False,
            auth_latency_ms=0.0,
            chain_reachable=False,
            spot_reachable=False,
            sample_row_count=0,
            sample_expiry_count=0,
            blocking_issues=["auth_failed", "chain_unreachable"],
        )
        assert result.passed is False
        assert len(result.blocking_issues) == 2

    def test_blocking_issues_is_list(self) -> None:
        result = SmokeTestResult(
            passed=True,
            auth_latency_ms=50.0,
            chain_reachable=True,
            spot_reachable=True,
            sample_row_count=100,
            sample_expiry_count=2,
            blocking_issues=[],
        )
        assert isinstance(result.blocking_issues, list)

    def test_is_not_frozen(self) -> None:
        result = SmokeTestResult(
            passed=True,
            auth_latency_ms=50.0,
            chain_reachable=True,
            spot_reachable=True,
            sample_row_count=100,
            sample_expiry_count=2,
            blocking_issues=[],
        )
        result.passed = False
        assert result.passed is False


# ── PhaseResult ───────────────────────────────────────────────────────────────


class TestPhaseResult:
    def _make(self, **overrides: object) -> PhaseResult:
        kwargs: dict[str, object] = dict(
            session_id="session-uuid",
            phase=1,
            started_at=datetime(2026, 1, 15, 9, 15, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 15, 15, 30, 0, tzinfo=timezone.utc),
            total_ticks=750,
            successful_polls=748,
            failed_polls=2,
            jsonl_path=Path("/tmp/discovery/phase1/session.jsonl"),
            db_path=Path("/tmp/discovery/analysis.db"),
        )
        kwargs.update(overrides)
        return PhaseResult(**kwargs)  # type: ignore[arg-type]

    def test_instantiates(self) -> None:
        result = self._make()
        assert result.session_id == "session-uuid"
        assert result.phase == 1

    def test_ended_early_defaults_false(self) -> None:
        result = self._make()
        assert result.ended_early is False

    def test_ended_early_can_be_set_true(self) -> None:
        result = self._make(ended_early=True)
        assert result.ended_early is True

    def test_is_not_frozen(self) -> None:
        result = self._make()
        result.total_ticks = 999
        assert result.total_ticks == 999

    def test_jsonl_path_is_path(self) -> None:
        assert isinstance(self._make().jsonl_path, Path)

    def test_db_path_is_path(self) -> None:
        assert isinstance(self._make().db_path, Path)

    def test_poll_counts_stored(self) -> None:
        result = self._make(successful_polls=10, failed_polls=2, total_ticks=12)
        assert result.successful_polls == 10
        assert result.failed_polls == 2
        assert result.total_ticks == 12


# ── VIXResult ─────────────────────────────────────────────────────────────────


class TestVIXResult:
    def test_instantiates_success(self) -> None:
        result = _vix_result()
        assert result.success is True
        assert result.ltp == 14.35

    def test_is_not_frozen(self) -> None:
        result = _vix_result()
        result.ltp = 15.0
        assert result.ltp == 15.0

    def test_accepts_none_ltp_on_failure(self) -> None:
        result = _vix_result(ltp=None, success=False, error="ltpData failed [AB1006]")
        assert result.ltp is None
        assert result.success is False

    def test_accepts_none_raw_response(self) -> None:
        result = _vix_result(raw_response=None, success=False, error="timeout")
        assert result.raw_response is None

    def test_failure_carries_error_string(self) -> None:
        result = _vix_result(success=False, error="network error", ltp=None)
        assert result.error is not None
        assert len(result.error) > 0

    def test_latency_ms_is_float(self) -> None:
        assert isinstance(_vix_result().latency_ms, float)

    def test_fetched_at_is_datetime(self) -> None:
        assert isinstance(_vix_result().fetched_at, datetime)


# ── SnapshotMeta ──────────────────────────────────────────────────────────────


class TestSnapshotMeta:
    def test_instantiates(self) -> None:
        meta = _snapshot_meta()
        assert meta.resolved_atm == 58000

    def test_is_frozen(self) -> None:
        meta = _snapshot_meta()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.resolved_atm = 57500  # type: ignore[misc]

    def test_schema_version_matches_module_constant(self) -> None:
        meta = _snapshot_meta()
        assert meta.schema_version == OBSERVATION_SCHEMA_VERSION
        assert meta.schema_version == 2

    def test_resolved_atm_stored(self) -> None:
        meta = _snapshot_meta(resolved_atm=57500)
        assert meta.resolved_atm == 57500

    def test_anchoring_spot_stored(self) -> None:
        meta = _snapshot_meta(anchoring_spot=57245.75)
        assert meta.anchoring_spot == 57245.75

    def test_expiry_set_stored(self) -> None:
        meta = _snapshot_meta(expiry_set=["30JUN2026", "28JUL2026"])
        assert meta.expiry_set == ["30JUN2026", "28JUL2026"]

    def test_window_steps_stored(self) -> None:
        meta = _snapshot_meta(window_steps=15)
        assert meta.window_steps == 15

    def test_three_expiry_set(self) -> None:
        meta = _snapshot_meta(expiry_set=["30JUN2026", "28JUL2026", "25AUG2026"])
        assert len(meta.expiry_set) == 3
        assert "25AUG2026" in meta.expiry_set


# ── OIChange ──────────────────────────────────────────────────────────────────


class TestOIChange:
    def test_instantiates(self) -> None:
        change = _oi_change()
        assert change.expiry == "30JUN2026"
        assert change.side == "CE"
        assert change.strike == 58000

    def test_is_frozen(self) -> None:
        change = _oi_change()
        with pytest.raises(dataclasses.FrozenInstanceError):
            change.delta = 0  # type: ignore[misc]

    def test_positive_delta_indicates_oi_build(self) -> None:
        change = _oi_change(delta=10800)
        assert change.delta > 0

    def test_negative_delta_indicates_oi_unwind(self) -> None:
        change = _oi_change(delta=-5400)
        assert change.delta < 0

    def test_zero_delta_accepted(self) -> None:
        change = _oi_change(delta=0)
        assert change.delta == 0

    def test_pe_side_accepted(self) -> None:
        change = _oi_change(side="PE", strike=57500, delta=-3600)
        assert change.side == "PE"
        assert change.strike == 57500


# ── DerivedObservation ────────────────────────────────────────────────────────


class TestDerivedObservation:
    def test_instantiates(self) -> None:
        obs = _derived_observation()
        assert isinstance(obs.total_ce_oi, dict)

    def test_is_not_frozen(self) -> None:
        obs = _derived_observation()
        obs.oi_pcr["30JUN2026"] = 0.8
        assert obs.oi_pcr["30JUN2026"] == 0.8

    def test_oi_changes_defaults_to_none(self) -> None:
        obs = _derived_observation()
        assert obs.oi_changes is None

    def test_total_oi_dicts_keyed_by_expiry(self) -> None:
        obs = _derived_observation()
        assert "30JUN2026" in obs.total_ce_oi
        assert "28JUL2026" in obs.total_pe_oi
        assert obs.total_ce_oi["30JUN2026"] == 1_200_000

    def test_pcr_none_value_accepted_per_expiry(self) -> None:
        obs = _derived_observation(oi_pcr={"30JUN2026": None, "28JUL2026": 0.9})
        assert obs.oi_pcr["30JUN2026"] is None
        assert obs.oi_pcr["28JUL2026"] == 0.9

    def test_volume_pcr_none_for_zero_volume_expiry(self) -> None:
        obs = _derived_observation()
        assert obs.volume_pcr["28JUL2026"] is None

    def test_oi_changes_list_accepted(self) -> None:
        changes = [
            _oi_change(strike=58000, delta=5400),
            _oi_change(strike=57500, side="PE", delta=-3600),
        ]
        obs = _derived_observation(oi_changes=changes)
        assert obs.oi_changes is not None
        assert len(obs.oi_changes) == 2
        assert isinstance(obs.oi_changes[0], OIChange)


# ── ObservationRecord ─────────────────────────────────────────────────────────


class TestObservationRecord:
    def test_instantiates_with_required_fields(self) -> None:
        record = _observation_record()
        assert record.poll_id == "obs-poll-uuid-0001"
        assert record.phase == 1

    def test_is_not_frozen(self) -> None:
        record = _observation_record()
        record.tick_number = 42
        assert record.tick_number == 42

    def test_derived_defaults_to_none(self) -> None:
        record = _observation_record()
        assert record.derived is None

    def test_futures_result_defaults_to_none(self) -> None:
        record = _observation_record()
        assert record.futures_result is None

    def test_futures_result_is_none_in_phase1(self) -> None:
        # Phase-1 contract: futures_result must never be populated.
        record = _observation_record()
        assert record.futures_result is None
        assert record.phase == 1

    def test_carries_chains_list(self) -> None:
        record = _observation_record()
        assert isinstance(record.chains, list)
        assert all(isinstance(c, ChainResult) for c in record.chains)

    def test_chains_can_hold_multiple_expiries(self) -> None:
        chains = [_chain_result(), _chain_result(expiry_count=1)]
        record = _observation_record(chains=chains)
        assert len(record.chains) == 2

    def test_carries_vix_result(self) -> None:
        vix = _vix_result()
        record = _observation_record(vix=vix)
        assert isinstance(record.vix, VIXResult)
        assert record.vix is vix

    def test_carries_spot_result(self) -> None:
        spot = _spot_result()
        record = _observation_record(spot=spot)
        assert isinstance(record.spot, SpotResult)
        assert record.spot is spot

    def test_asdict_produces_serializable_graph(self) -> None:
        record = _observation_record(
            derived=_derived_observation(
                oi_changes=[_oi_change(), _oi_change(side="PE", delta=-100)]
            )
        )
        d = dataclasses.asdict(record)
        assert isinstance(d, dict)
        assert d["meta"]["schema_version"] == OBSERVATION_SCHEMA_VERSION
        assert d["futures_result"] is None
        assert isinstance(d["chains"], list)
        assert isinstance(d["derived"]["oi_changes"], list)
        assert len(d["derived"]["oi_changes"]) == 2


# ── Cross-cutting: frozen vs mutable ─────────────────────────────────────────


class TestFrozenContracts:
    """Assert exactly which dataclasses are frozen and which are not."""

    def test_phase_config_is_frozen(self) -> None:
        assert _phase_config().__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_session_token_is_frozen(self) -> None:
        assert _session_token().__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_chain_result_is_not_frozen(self) -> None:
        assert _chain_result().__dataclass_params__.frozen is False  # type: ignore[attr-defined]

    def test_spot_result_is_not_frozen(self) -> None:
        assert _spot_result().__dataclass_params__.frozen is False  # type: ignore[attr-defined]

    def test_poll_record_is_not_frozen(self) -> None:
        assert _poll_record().__dataclass_params__.frozen is False  # type: ignore[attr-defined]

    def test_phase_result_is_not_frozen(self) -> None:
        result = PhaseResult(
            session_id="s",
            phase=1,
            started_at=_NOW,
            ended_at=_NOW,
            total_ticks=0,
            successful_polls=0,
            failed_polls=0,
            jsonl_path=Path("/tmp/x.jsonl"),
            db_path=Path("/tmp/x.db"),
        )
        assert result.__dataclass_params__.frozen is False  # type: ignore[attr-defined]

    def test_snapshot_meta_is_frozen(self) -> None:
        assert _snapshot_meta().__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_oi_change_is_frozen(self) -> None:
        assert _oi_change().__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_vix_result_is_not_frozen(self) -> None:
        assert _vix_result().__dataclass_params__.frozen is False  # type: ignore[attr-defined]

    def test_derived_observation_is_not_frozen(self) -> None:
        assert _derived_observation().__dataclass_params__.frozen is False  # type: ignore[attr-defined]

    def test_observation_record_is_not_frozen(self) -> None:
        assert _observation_record().__dataclass_params__.frozen is False  # type: ignore[attr-defined]


# ── Fixture integration ───────────────────────────────────────────────────────


class TestChainFixture:
    """Verify the synthetic fixture produces a valid ChainResult."""

    def test_fixture_row_count(self, chain_fixture: ChainResult) -> None:
        assert chain_fixture.row_count == 20

    def test_fixture_expiry_count(self, chain_fixture: ChainResult) -> None:
        assert chain_fixture.expiry_count == 2

    def test_fixture_unfetched_zero(self, chain_fixture: ChainResult) -> None:
        assert chain_fixture.unfetched_count == 0

    def test_fixture_success(self, chain_fixture: ChainResult) -> None:
        assert chain_fixture.success is True

    def test_fixture_has_raw_response(self, chain_fixture: ChainResult) -> None:
        assert chain_fixture.raw_response is not None

    def test_fixture_response_bytes_positive(self, chain_fixture: ChainResult) -> None:
        assert chain_fixture.response_bytes > 0

    def test_fixture_http_status_200(self, chain_fixture: ChainResult) -> None:
        assert chain_fixture.http_status == 200
