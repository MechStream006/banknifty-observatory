"""Phase-1 freeze-patch tests for DiscoveryController: provenance & continuity.

Reuses the dependency-injection harness from test_controller (all collaborators
are MagicMock stubs; the scheduler stub yields a fixed datetime sequence).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from lib.discovery._models import COLLECTION_CONTRACT_VERSION

from tests.unit.test_discovery.test_controller import (
    _DT_1,
    _DT_2,
    _DT_3,
    _EXPIRY,
    _SchedulerStub,
    _make_chain_result,
    _make_chain_result_with_rows,
    _make_controller,
    _make_spot_result,
    _row,
)


def _records_from(store: MagicMock) -> list:
    """ObservationRecord objects passed to store.insert(), in tick order."""
    return [c.args[0] for c in store.insert.call_args_list]


# ── Underlying (self-describing corpus) ──────────────────────────────────────────


class TestUnderlyingProvenance:
    def test_default_underlying_is_banknifty(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert _records_from(store)[0].underlying == "BANKNIFTY"

    def test_custom_underlying_flows_into_record(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(
            store=store, scheduler=_SchedulerStub(_DT_1), underlying="NIFTY"
        )
        ctrl.run()
        assert _records_from(store)[0].underlying == "NIFTY"

    def test_underlying_present_on_spot_failure_record(self) -> None:
        store = MagicMock()
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        ctrl = _make_controller(
            store=store, spot_fetcher=spot, scheduler=_SchedulerStub(_DT_1)
        )
        ctrl.run()
        assert _records_from(store)[0].underlying == "BANKNIFTY"


# ── SnapshotMeta provenance (contract version + step size) ───────────────────────


class TestSnapshotMetaProvenance:
    def test_meta_carries_collection_contract_version(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert (
            _records_from(store)[0].meta.collection_contract_version
            == COLLECTION_CONTRACT_VERSION
        )

    def test_meta_carries_chain_step_size(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(
            store=store, chain_step_size=500, scheduler=_SchedulerStub(_DT_1)
        )
        ctrl.run()
        assert _records_from(store)[0].meta.chain_step_size == 500

    def test_spot_failure_meta_also_carries_provenance(self) -> None:
        store = MagicMock()
        spot = MagicMock()
        spot.fetch.return_value = _make_spot_result(success=False)
        ctrl = _make_controller(
            store=store,
            spot_fetcher=spot,
            chain_step_size=500,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        rec = _records_from(store)[0]
        assert rec.meta.chain_step_size == 500
        assert rec.meta.collection_contract_version == COLLECTION_CONTRACT_VERSION


# ── Immutable instrument identity (parsed quotes) ────────────────────────────────


class TestInstrumentQuotes:
    def _controller_with_rows(self, store, rows, *, scheduler=None):
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result_with_rows(rows)
        return _make_controller(
            store=store,
            chain_fetchers=[cf],
            expiries=[_EXPIRY],
            scheduler=scheduler or _SchedulerStub(_DT_1),
        )

    def test_quotes_populated_with_full_identity(self) -> None:
        store = MagicMock()
        ctrl = self._controller_with_rows(store, [_row(58000, "CE", oi=1000, vol=5)])
        ctrl.run()
        chain = _records_from(store)[0].chains[0]
        assert len(chain.quotes) == 1
        q = chain.quotes[0]
        assert q.underlying == "BANKNIFTY"
        assert q.expiry == _EXPIRY
        assert q.strike == 58000
        assert q.option_side == "CE"
        assert q.oi == 1000
        assert q.volume == 5
        assert q.ltp == 100.0

    def test_chain_result_expiry_is_set(self) -> None:
        store = MagicMock()
        ctrl = self._controller_with_rows(store, [_row(58000, "PE", oi=1)])
        ctrl.run()
        assert _records_from(store)[0].chains[0].expiry == _EXPIRY

    def test_raw_payload_preserved_unchanged(self) -> None:
        store = MagicMock()
        rows = [_row(58000, "CE", oi=1000)]
        ctrl = self._controller_with_rows(store, rows)
        ctrl.run()
        chain = _records_from(store)[0].chains[0]
        assert chain.raw_response["data"]["fetched"] == rows

    def test_failed_chain_has_empty_quotes(self) -> None:
        store = MagicMock()
        cf = MagicMock()
        cf.fetch.return_value = _make_chain_result(success=False)
        ctrl = _make_controller(
            store=store,
            chain_fetchers=[cf],
            expiries=[_EXPIRY],
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        assert _records_from(store)[0].chains[0].quotes == []


# ── Snapshot continuity ──────────────────────────────────────────────────────────


class TestSnapshotContinuity:
    def test_first_snapshot_is_first(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        cont = _records_from(store)[0].continuity
        assert cont.continuity_status == "FIRST"
        assert cont.previous_snapshot_id is None
        assert cont.actual_interval_seconds is None
        assert cont.expected_interval_seconds == 5

    def test_second_contiguous_snapshot_links_to_first(self) -> None:
        store = MagicMock()
        # _DT_1 → _DT_2 is exactly 5s, matching interval_seconds=5.
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        recs = _records_from(store)
        second = recs[1].continuity
        assert second.continuity_status == "CONTIGUOUS"
        assert second.previous_snapshot_id == recs[0].poll_id
        assert second.previous_timestamp == recs[0].polled_at
        assert second.actual_interval_seconds == 5.0

    def test_long_interval_is_a_gap(self) -> None:
        store = MagicMock()
        gap_dt = datetime(2026, 6, 23, 4, 0, 35, tzinfo=timezone.utc)  # +30s
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1, gap_dt))
        ctrl.run()
        second = _records_from(store)[1].continuity
        assert second.continuity_status == "GAP"
        assert second.actual_interval_seconds == 30.0

    def test_continuity_chain_unbroken_through_spot_failure(self) -> None:
        # A spot-failure snapshot still advances the continuity cursor, so the
        # following snapshot links to it rather than skipping it.
        store = MagicMock()
        spot = MagicMock()
        spot.fetch.side_effect = [
            _make_spot_result(success=True),
            _make_spot_result(success=False),
            _make_spot_result(success=True),
        ]
        ctrl = _make_controller(
            store=store,
            spot_fetcher=spot,
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        ctrl.run()
        recs = _records_from(store)
        assert recs[2].continuity.previous_snapshot_id == recs[1].poll_id


# ── OI-delta gating on continuity ────────────────────────────────────────────────


class TestOIDeltaContinuityGating:
    def _two_tick_controller(self, store, scheduler):
        cf = MagicMock()
        cf.fetch.side_effect = [
            _make_chain_result_with_rows([_row(58000, "CE", oi=1000)]),
            _make_chain_result_with_rows([_row(58000, "CE", oi=1200)]),
        ]
        return _make_controller(
            store=store, chain_fetchers=[cf], expiries=[_EXPIRY], scheduler=scheduler
        )

    def test_oi_changes_computed_across_contiguous_snapshots(self) -> None:
        store = MagicMock()
        ctrl = self._two_tick_controller(store, _SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        derived = _records_from(store)[1].derived
        assert derived.oi_changes is not None
        deltas = {(c.side, c.strike): c.delta for c in derived.oi_changes}
        assert deltas[("CE", 58000)] == 200

    def test_oi_changes_withheld_across_a_gap(self) -> None:
        store = MagicMock()
        gap_dt = datetime(2026, 6, 23, 4, 0, 35, tzinfo=timezone.utc)  # +30s gap
        ctrl = self._two_tick_controller(store, _SchedulerStub(_DT_1, gap_dt))
        ctrl.run()
        # Totals/PCRs still computed; only the path-dependent delta is withheld.
        derived = _records_from(store)[1].derived
        assert derived is not None
        assert derived.oi_changes is None

    def test_prev_oi_still_advances_after_gap(self) -> None:
        # tick1=1000, tick2 (gap)=1200 → oi_changes None; tick3 (contiguous)=1500
        # → delta computed against 1200 (=+300), proving the cursor advanced.
        store = MagicMock()
        cf = MagicMock()
        cf.fetch.side_effect = [
            _make_chain_result_with_rows([_row(58000, "CE", oi=1000)]),
            _make_chain_result_with_rows([_row(58000, "CE", oi=1200)]),
            _make_chain_result_with_rows([_row(58000, "CE", oi=1500)]),
        ]
        gap_dt = datetime(2026, 6, 23, 4, 0, 35, tzinfo=timezone.utc)  # +30s gap
        after = datetime(2026, 6, 23, 4, 0, 40, tzinfo=timezone.utc)  # +5s (contiguous)
        ctrl = _make_controller(
            store=store,
            chain_fetchers=[cf],
            expiries=[_EXPIRY],
            scheduler=_SchedulerStub(_DT_1, gap_dt, after),
        )
        ctrl.run()
        recs = _records_from(store)
        assert recs[1].derived.oi_changes is None  # gap tick
        deltas = {(c.side, c.strike): c.delta for c in recs[2].derived.oi_changes}
        assert deltas[("CE", 58000)] == 300


# ── Run identity (manifest ↔ record join key) ────────────────────────────────────


class TestRunIdPassthrough:
    def test_supplied_run_id_becomes_session_id(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(
            store=store, scheduler=_SchedulerStub(_DT_1, _DT_2), run_id="fixed-run-99"
        )
        result = ctrl.run()
        recs = _records_from(store)
        assert result.session_id == "fixed-run-99"
        assert all(r.session_id == "fixed-run-99" for r in recs)

    def test_absent_run_id_falls_back_to_generated_uuid(self) -> None:
        store = MagicMock()
        ctrl = _make_controller(store=store, scheduler=_SchedulerStub(_DT_1))
        result = ctrl.run()
        # A uuid4 string is generated when no run_id is supplied.
        assert result.session_id
        assert _records_from(store)[0].session_id == result.session_id
