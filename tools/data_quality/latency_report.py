#!/usr/bin/env python
"""latency_report - API latency distribution for one JSONL day file.

Read-only. Reports min/max/mean/p50/p95/p99 latency (ms) per API surface
(spot, vix, chain), computed over every fetch recorded in the file - including
failed fetches, whose latency represents real round-trip / timeout duration.

Usage (PYTHONPATH=. or `python -m tools.data_quality.latency_report`):
    python -m tools.data_quality.latency_report --jsonl DAY.jsonl [--csv OUT.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.data_quality._common import (
    describe,
    fmt,
    load_jsonl,
    print_section,
    record_chains,
    record_spot,
    record_vix,
    write_csv,
)

_SOURCES = ("spot", "vix", "chain")


def build_latency_report(records: list[dict]) -> dict:
    """Return {source: describe(latencies)} for spot, vix, and chain fetches."""
    spot_lat = [record_spot(r).get("latency_ms") for r in records]
    vix_lat = [record_vix(r).get("latency_ms") for r in records]
    chain_lat = [c.get("latency_ms") for r in records for c in record_chains(r)]
    return {
        "spot": describe(spot_lat),
        "vix": describe(vix_lat),
        "chain": describe(chain_lat),
    }


def render(report: dict, jsonl_path: str) -> None:
    print(f"\nLatency report - {jsonl_path}")
    print_section("Latency ms by source")
    header = f"  {'source':<7} {'count':>7} {'min':>9} {'mean':>9} {'p50':>9} {'p95':>9} {'p99':>9} {'max':>9}"
    print(header)
    for src in _SOURCES:
        d = report[src]
        print(f"  {src:<7} {d['count']:>7} {fmt(d['min']):>9} {fmt(d['mean']):>9} "
              f"{fmt(d['p50']):>9} {fmt(d['p95']):>9} {fmt(d['p99']):>9} {fmt(d['max']):>9}")


def _csv_rows(report: dict) -> list[list]:
    rows = []
    for src in _SOURCES:
        d = report[src]
        rows.append([src, d["count"], d["min"], d["mean"], d["p50"],
                     d["p95"], d["p99"], d["max"]])
    return rows


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="latency_report", description=__doc__)
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--csv", default=None)
    args = parser.parse_args(argv)

    records, _ = load_jsonl(args.jsonl)
    report = build_latency_report(records)
    render(report, args.jsonl)
    if args.csv:
        write_csv(args.csv,
                  ["source", "count", "min", "mean", "p50", "p95", "p99", "max"],
                  _csv_rows(report))
        print(f"\n  CSV written: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
