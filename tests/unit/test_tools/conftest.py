"""Fixtures and builders for Data Quality Toolkit tests.

Records are synthesised as plain dicts matching the on-disk serialized shape of
ObservationRecord (dataclasses.asdict + ISO datetimes), so the tests exercise
the toolkit exactly as it will see archived data — no dependency on lib models.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_BASE = datetime(2026, 6, 30, 3, 45, 0, tzinfo=timezone.utc)
_CONTINUITY_TOL = 0.5


def make_quote(strike, side, oi=1000, vol=5, ltp=100.0,
               underlying="BANKNIFTY", expiry="30JUN2026") -> dict:
    return {
        "underlying": underlying, "expiry": expiry, "strike": strike,
        "option_side": side, "oi": oi, "volume": vol, "ltp": ltp,
    }


def make_chain(expiry="30JUN2026", *, success=True, latency=120.0,
               unfetched=0, quotes=None) -> dict:
    quotes = quotes if quotes is not None else [
        make_quote(58000, "CE", oi=1000, expiry=expiry),
        make_quote(58000, "PE", oi=800, expiry=expiry),
    ]
    return {
        "fetched_at": _BASE.isoformat(),
        "latency_ms": latency,
        "http_status": None,
        "response_bytes": 100,
        "raw_response": {"data": {"fetched": [], "unfetched": []}} if success else None,
        "row_count": len(quotes) if success else 0,
        "expiry_count": 1 if success else 0,
        "unfetched_count": unfetched,
        "error": None if success else "chain_error",
        "success": success,
        "expiry": expiry,
        "quotes": quotes if success else [],
    }


def make_record(*, session_id="s1", poll_id="p1", polled_at=None, tick=1, interval=5,
                prev_id=None, prev_ts=None, actual=None, status="FIRST",
                chains=None, spot_ok=True, spot_latency=45.0,
                vix_ok=True, vix_latency=25.0, derived="auto",
                schema_version=2, chain_step_size=500) -> dict:
    polled_at = polled_at if polled_at is not None else _BASE
    chains = chains if chains is not None else [make_chain()]
    if derived == "auto":
        derived = _auto_derived(chains) if any(c["success"] for c in chains) else None
    return {
        "poll_id": poll_id,
        "session_id": session_id,
        "polled_at": polled_at.isoformat(),
        "phase": 1,
        "tick_number": tick,
        "interval_s": interval,
        "meta": {
            "schema_version": schema_version,
            "anchoring_spot": 58010.0,
            "resolved_atm": 58000,
            "expiry_set": [c["expiry"] for c in chains] or ["30JUN2026"],
            "window_steps": 15,
            "collection_contract_version": 1,
            "chain_step_size": chain_step_size,
        },
        "spot": {
            "fetched_at": polled_at.isoformat(), "latency_ms": spot_latency,
            "ltp": 58010.0 if spot_ok else None, "raw_response": None,
            "source": "separate_call", "error": None if spot_ok else "spot_error",
            "success": spot_ok,
        },
        "vix": {
            "fetched_at": polled_at.isoformat(), "latency_ms": vix_latency,
            "ltp": 14.5 if vix_ok else None, "raw_response": None,
            "error": None if vix_ok else "vix_error", "success": vix_ok,
        },
        "chains": chains,
        "derived": derived,
        "futures_result": None,
        "underlying": "BANKNIFTY",
        "continuity": {
            "previous_snapshot_id": prev_id,
            "previous_timestamp": prev_ts.isoformat() if prev_ts else None,
            "expected_interval_seconds": interval,
            "actual_interval_seconds": actual,
            "continuity_status": status,
        },
    }


def _auto_derived(chains) -> dict:
    total_ce, total_pe = {}, {}
    oi_pcr, vol_pcr = {}, {}
    for c in chains:
        if not c["success"]:
            continue
        exp = c["expiry"]
        ce = sum(q["oi"] for q in c["quotes"] if q["option_side"] == "CE")
        pe = sum(q["oi"] for q in c["quotes"] if q["option_side"] == "PE")
        total_ce[exp] = ce
        total_pe[exp] = pe
        oi_pcr[exp] = round(pe / ce, 4) if ce else None
        vol_pcr[exp] = None
    return {
        "total_ce_oi": total_ce, "total_pe_oi": total_pe,
        "oi_pcr": oi_pcr, "volume_pcr": vol_pcr, "oi_changes": None,
    }


def make_session(session_id, deltas, *, interval=5, start=_BASE,
                 chains_factory=None, spot_ok=True) -> list[dict]:
    """Build a continuity-correct session of len(deltas)+1 records.

    deltas: seconds between consecutive snapshots. A delta within ±50% of
    *interval* yields CONTIGUOUS; otherwise GAP — mirroring the collector.
    """
    lower, upper = interval * (1 - _CONTINUITY_TOL), interval * (1 + _CONTINUITY_TOL)
    records: list[dict] = []
    t = start
    prev = None
    n = len(deltas) + 1
    for i in range(n):
        if i > 0:
            t = t + timedelta(seconds=deltas[i - 1])
        if prev is None:
            status, actual, prev_id, prev_ts = "FIRST", None, None, None
        else:
            actual = deltas[i - 1]
            status = "CONTIGUOUS" if lower <= actual <= upper else "GAP"
            prev_id = prev["poll_id"]
            prev_ts = datetime.fromisoformat(prev["polled_at"])
        chains = chains_factory(i) if chains_factory else [make_chain()]
        rec = make_record(
            session_id=session_id, poll_id=f"{session_id}-{i}", polled_at=t,
            tick=i + 1, interval=interval, prev_id=prev_id, prev_ts=prev_ts,
            actual=actual, status=status, chains=chains, spot_ok=spot_ok,
        )
        records.append(rec)
        prev = rec
    return records


def make_manifest(run_id, *, total_ticks, successful, failed, status="completed",
                  schema=2, interval=5) -> dict:
    return {
        "run_id": run_id, "git_commit": "sha", "observation_schema_version": schema,
        "config_schema_version": 2, "collection_contract_version": 1,
        "started_at": _BASE.isoformat(), "host": "test-host",
        "expiries": ["30JUN2026"], "interval_seconds": interval,
        "window_steps": 15, "step_size": 500, "status": status,
        "ended_at": (_BASE + timedelta(hours=6)).isoformat() if status != "running" else None,
        "total_ticks": total_ticks, "successful_polls": successful, "failed_polls": failed,
    }


def write_jsonl(path: Path, records: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return path


@pytest.fixture
def clean_day(tmp_path):
    """A well-formed day: one 4-tick contiguous session + matching manifest."""
    records = make_session("run-a", [5, 5, 5], interval=5)
    jsonl = write_jsonl(tmp_path / "20260630.jsonl", records)
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "run-a.json").write_text(
        json.dumps(make_manifest("run-a", total_ticks=4, successful=4, failed=0)),
        encoding="utf-8",
    )
    return {"jsonl": jsonl, "manifest_dir": manifest_dir, "records": records}
