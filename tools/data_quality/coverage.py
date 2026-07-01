#!/usr/bin/env python
"""coverage - expected-vs-captured observation coverage for one JSONL day file.

Read-only. Per run (session_id) it compares the number of captured snapshots to
the number expected across the run's active window, and reports every gap.
Gaps are read from the embedded continuity metadata (authoritative) and the
expected count is derived from the poll interval grid.

Usage (PYTHONPATH=. or `python -m tools.data_quality.coverage`):
    python -m tools.data_quality.coverage --jsonl DAY.jsonl \
        [--interval SECONDS] [--csv OUT.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.data_quality._common import (
    fmt,
    group_by_session,
    load_jsonl,
    modal_interval,
    print_kv,
    print_section,
    record_continuity,
    record_poll_id,
    record_polled_at,
    sort_by_time,
    write_csv,
)


def _session_coverage(sid: str, recs: list[dict], interval: int) -> dict:
    ordered = sort_by_time(recs)
    times = [record_polled_at(r) for r in ordered if record_polled_at(r) is not None]
    captured = len(ordered)
    first = times[0] if times else None
    last = times[-1] if times else None

    if first and last and interval > 0:
        span = (last - first).total_seconds()
        expected = round(span / interval) + 1
    else:
        expected = captured

    gaps = []
    prev = None
    for r in ordered:
        if prev is not None:
            cont = record_continuity(r)
            if cont.get("continuity_status") == "GAP":
                a, b = record_polled_at(prev), record_polled_at(r)
                gap_s = (b - a).total_seconds() if a and b else cont.get("actual_interval_seconds")
                missing = (max(0, round(gap_s / interval) - 1)
                           if isinstance(gap_s, (int, float)) and interval > 0 else 0)
                gaps.append({
                    "session_id": sid,
                    "after_poll_id": record_poll_id(prev),
                    "from": a.isoformat() if a else None,
                    "to": b.isoformat() if b else None,
                    "gap_seconds": gap_s,
                    "missing_estimate": missing,
                })
        prev = r

    missing_total = max(0, expected - captured)
    return {
        "session_id": sid,
        "first": first.isoformat() if first else None,
        "last": last.isoformat() if last else None,
        "captured": captured,
        "expected": expected,
        "missing": missing_total,
        "coverage_pct": round(100.0 * captured / expected, 2) if expected else None,
        "gaps": gaps,
    }


def build_coverage(records: list[dict], interval: int | None = None) -> dict:
    """Per-session coverage + gap report. interval defaults to the modal interval_s."""
    iv = interval if interval is not None else modal_interval(records, fallback=0)
    sessions = [
        _session_coverage(sid, recs, iv)
        for sid, recs in group_by_session(records).items()
    ]
    captured = sum(s["captured"] for s in sessions)
    expected = sum(s["expected"] for s in sessions)
    gaps = [g for s in sessions for g in s["gaps"]]
    return {
        "interval_seconds": iv,
        "sessions": sessions,
        "total_captured": captured,
        "total_expected": expected,
        "total_missing": max(0, expected - captured),
        "coverage_pct": round(100.0 * captured / expected, 2) if expected else None,
        "gaps": gaps,
    }


def render(cov: dict, jsonl_path: str) -> None:
    print(f"\nCoverage - {jsonl_path}  (interval={cov['interval_seconds']}s)")
    print_section("Totals")
    print_kv([
        ("captured", cov["total_captured"]),
        ("expected", cov["total_expected"]),
        ("missing", cov["total_missing"]),
        ("coverage_pct", cov["coverage_pct"]),
    ])
    print_section("Per session")
    for s in cov["sessions"]:
        print(f"  {s['session_id'][:8]}  captured={s['captured']:<6} "
              f"expected={s['expected']:<6} missing={s['missing']:<5} "
              f"coverage={fmt(s['coverage_pct'])}%")
    if cov["gaps"]:
        print_section("Gaps")
        for g in cov["gaps"]:
            print(f"  {g['session_id'][:8]}  {g['from']} -> {g['to']}  "
                  f"gap={fmt(g['gap_seconds'])}s  missing~{g['missing_estimate']}")
    else:
        print_section("Gaps")
        print("  none")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coverage", description=__doc__)
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--interval", type=int, default=None,
                        help="Override poll interval seconds (default: modal interval_s)")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args(argv)

    records, _ = load_jsonl(args.jsonl)
    cov = build_coverage(records, args.interval)
    render(cov, args.jsonl)
    if args.csv:
        rows = [[g["session_id"], g["after_poll_id"], g["from"], g["to"],
                 g["gap_seconds"], g["missing_estimate"]] for g in cov["gaps"]]
        write_csv(args.csv,
                  ["session_id", "after_poll_id", "from", "to", "gap_seconds", "missing_estimate"],
                  rows)
        print(f"\n  CSV written: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
