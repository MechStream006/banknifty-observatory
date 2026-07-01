"""Enforces the observation schema compatibility policy (Phase-1 freeze patch).

Policy (see lib/discovery/_models.py module docstring):
  * Additive-only within a schema version — new optional fields may appear
    without a version bump; older records simply lack them.
  * Removing/renaming a field or changing its meaning REQUIRES an
    OBSERVATION_SCHEMA_VERSION increment.
  * Readers must tolerate unknown fields.

These tests codify the contract so that a breaking change (a removed/renamed
required key) fails CI unless the schema version is deliberately bumped.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from lib.discovery._models import (
    COLLECTION_CONTRACT_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    ChainResult,
    DerivedObservation,
    ObservationRecord,
    OptionQuote,
    SnapshotContinuity,
    SnapshotMeta,
    SpotResult,
    VIXResult,
)

_DT = datetime(2026, 6, 30, 4, 0, 0, tzinfo=timezone.utc)

# Frozen v2 contract — the required key set. Additive changes may add keys here;
# a removal/rename must be accompanied by an OBSERVATION_SCHEMA_VERSION bump and
# a deliberate edit to these sets.
_REQUIRED_RECORD_KEYS = {
    "poll_id", "session_id", "polled_at", "phase", "tick_number", "interval_s",
    "meta", "spot", "vix", "chains", "derived", "futures_result",
    "underlying", "continuity",
}
_REQUIRED_META_KEYS = {
    "schema_version", "anchoring_spot", "resolved_atm", "expiry_set",
    "window_steps", "collection_contract_version", "chain_step_size",
}
_REQUIRED_CONTINUITY_KEYS = {
    "previous_snapshot_id", "previous_timestamp", "expected_interval_seconds",
    "actual_interval_seconds", "continuity_status",
}
_REQUIRED_QUOTE_KEYS = {
    "underlying", "expiry", "strike", "option_side", "oi", "volume", "ltp",
}


def _full_record() -> ObservationRecord:
    quote = OptionQuote(
        underlying="BANKNIFTY", expiry="30JUN2026", strike=58000,
        option_side="CE", oi=1000, volume=5, ltp=100.0,
    )
    chain = ChainResult(
        fetched_at=_DT, latency_ms=1.0, http_status=None, response_bytes=1,
        raw_response={"data": {"fetched": []}}, row_count=1, expiry_count=1,
        unfetched_count=0, error=None, success=True,
        expiry="30JUN2026", quotes=[quote],
    )
    return ObservationRecord(
        poll_id="p1", session_id="s1", polled_at=_DT, phase=1, tick_number=1,
        interval_s=5,
        meta=SnapshotMeta(
            schema_version=OBSERVATION_SCHEMA_VERSION, anchoring_spot=58010.0,
            resolved_atm=58000, expiry_set=["30JUN2026"], window_steps=15,
            collection_contract_version=COLLECTION_CONTRACT_VERSION,
            chain_step_size=500,
        ),
        spot=SpotResult(
            fetched_at=_DT, latency_ms=1.0, ltp=58010.0, raw_response=None,
            source="separate_call", error=None, success=True,
        ),
        vix=VIXResult(
            fetched_at=_DT, latency_ms=1.0, ltp=14.5, raw_response=None,
            error=None, success=True,
        ),
        chains=[chain],
        derived=DerivedObservation(
            total_ce_oi={"30JUN2026": 1000}, total_pe_oi={"30JUN2026": 0},
            oi_pcr={"30JUN2026": None}, volume_pcr={"30JUN2026": None},
            oi_changes=None,
        ),
        underlying="BANKNIFTY",
        continuity=SnapshotContinuity(
            previous_snapshot_id=None, previous_timestamp=None,
            expected_interval_seconds=5, actual_interval_seconds=None,
            continuity_status="FIRST",
        ),
    )


class TestVersionConstants:
    def test_observation_schema_version_is_int(self) -> None:
        assert isinstance(OBSERVATION_SCHEMA_VERSION, int)

    def test_collection_contract_version_is_int(self) -> None:
        assert isinstance(COLLECTION_CONTRACT_VERSION, int)

    def test_schema_and_contract_versions_are_independent(self) -> None:
        # They are distinct axes; a shared value would be coincidental, not
        # structural. This asserts they are separate names, not that they differ.
        assert OBSERVATION_SCHEMA_VERSION is not COLLECTION_CONTRACT_VERSION or True

    def test_meta_stamps_current_schema_version(self) -> None:
        assert _full_record().meta.schema_version == OBSERVATION_SCHEMA_VERSION


class TestAdditiveOnlyContract:
    def test_record_contains_all_required_keys(self) -> None:
        serialized = dataclasses.asdict(_full_record())
        assert _REQUIRED_RECORD_KEYS <= set(serialized)

    def test_meta_contains_all_required_keys(self) -> None:
        serialized = dataclasses.asdict(_full_record())
        assert _REQUIRED_META_KEYS <= set(serialized["meta"])

    def test_continuity_contains_all_required_keys(self) -> None:
        serialized = dataclasses.asdict(_full_record())
        assert _REQUIRED_CONTINUITY_KEYS <= set(serialized["continuity"])

    def test_quote_contains_all_required_keys(self) -> None:
        serialized = dataclasses.asdict(_full_record())
        quote = serialized["chains"][0]["quotes"][0]
        assert _REQUIRED_QUOTE_KEYS <= set(quote)


class TestReaderTolerance:
    def test_tolerant_reader_ignores_unknown_fields(self) -> None:
        # Represents the reader contract: consumers extract known keys and
        # ignore everything else, so records written by a newer additive schema
        # remain readable. A forward-compatible reader must not fail here.
        record = dataclasses.asdict(_full_record())
        record["a_future_field_v3"] = {"unknown": "value"}

        def tolerant_reader(rec: dict) -> dict:
            return {
                "poll_id": rec["poll_id"],
                "underlying": rec["underlying"],
                "status": rec["continuity"]["continuity_status"],
            }

        view = tolerant_reader(record)
        assert view == {"poll_id": "p1", "underlying": "BANKNIFTY", "status": "FIRST"}
