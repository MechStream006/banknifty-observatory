#!/usr/bin/env python
"""summary - daily summary of one JSONL day file.

Read-only. Reports snapshot count, time coverage, latency statistics, and
chain/spot success rates.

Usage (PYTHONPATH=. or `python -m tools.data_quality.summary`):
    python -m tools.data_quality.summary --jsonl DAY.jsonl [--csv OUT.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.data_quality._common import (
    describe,
    fmt,
    load_jsonl,
    print_kv,
    print_section,
    record_chains,
    record_is_successful,
    record_polled_at,
    record_spot,
    record_vix,
    write_csv,
)


def build_summary(records: list[dict]) -> dict:
    """Compute the daily summary dict. Pure; operates on parsed records only."""
    n = len(records)
    times = [dt for dt in (record_polled_at(r) for r in records) if dt is not None]
    first = min(times) if times else None
    last = max(times) if times else None
    duration_s = (last - first).total_seconds() if first and last else None

    spot_lat = [record_spot(r).get("latency_ms") for r in records]
    vix_lat = [record_vix(r).get("latency_ms") for r in records]
    chain_lat = [c.get("latency_ms") for r in records for c in record_chains(r)]

    poll_success = sum(1 for r in records if record_is_successful(r))
    spot_success = sum(1 for r in records if record_spot(r).get("success"))
    vix_success = sum(1 for r in records if record_vix(r).get("success"))

    chain_total = sum(len(record_chains(r)) for r in records)
    chain_ok = sum(1 for r in records for c in record_chains(r) if c.get("success"))

    def rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    return {
        "snapshot_count": n,
        "first_polled_at": first.isoformat() if first else None,
        "last_polled_at": last.isoformat() if last else None,
        "coverage_seconds": duration_s,
        "spot_latency_ms": describe(spot_lat),
        "vix_latency_ms": describe(vix_lat),
        "chain_latency_ms": describe(chain_lat),
        "poll_success_rate": rate(poll_success, n),
        "spot_success_rate": rate(spot_success, n),
        "vix_success_rate": rate(vix_success, n),
        "chain_fetch_success_rate": rate(chain_ok, chain_total),
        "chain_fetches": chain_total,
    }


def render(summary: dict, jsonl_path: str) -> None:
    print(f"\nDaily summary - {jsonl_path}")
    print_section("Coverage")
    print_kv([
        ("snapshots", summary["snapshot_count"]),
        ("first", summary["first_polled_at"]),
        ("last", summary["last_polled_at"]),
        ("coverage_seconds", summary["coverage_seconds"]),
    ])
    print_section("Success rates")
    print_kv([
        ("poll (any chain ok)", summary["poll_success_rate"]),
        ("spot", summary["spot_success_rate"]),
        ("vix", summary["vix_success_rate"]),
        ("chain fetch", summary["chain_fetch_success_rate"]),
    ])
    print_section("Latency ms (mean / p95 / max)")
    for label, key in (("spot", "spot_latency_ms"), ("vix", "vix_latency_ms"),
                       ("chain", "chain_latency_ms")):
        d = summary[key]
        value = (f"{fmt(d['mean'])} / {fmt(d['p95'])} / {fmt(d['max'])}"
                 if d["count"] else "-")
        print_kv([(label, value)])


def _csv_rows(summary: dict) -> list[list]:
    rows = [
        ["snapshot_count", summary["snapshot_count"]],
        ["first_polled_at", summary["first_polled_at"]],
        ["last_polled_at", summary["last_polled_at"]],
        ["coverage_seconds", summary["coverage_seconds"]],
        ["poll_success_rate", summary["poll_success_rate"]],
        ["spot_success_rate", summary["spot_success_rate"]],
        ["vix_success_rate", summary["vix_success_rate"]],
        ["chain_fetch_success_rate", summary["chain_fetch_success_rate"]],
    ]
    for key in ("spot_latency_ms", "vix_latency_ms", "chain_latency_ms"):
        d = summary[key]
        for stat in ("count", "min", "mean", "max", "p95", "p99"):
            rows.append([f"{key}.{stat}", d[stat]])
    return rows


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="summary", description=__doc__)
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--csv", default=None)
    args = parser.parse_args(argv)

    records, _ = load_jsonl(args.jsonl)
    summary = build_summary(records)
    render(summary, args.jsonl)
    if args.csv:
        write_csv(args.csv, ["metric", "value"], _csv_rows(summary))
        print(f"\n  CSV written: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
