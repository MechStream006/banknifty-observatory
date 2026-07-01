#!/usr/bin/env python
"""option_chain_report - per-expiry option-chain coverage for one JSONL day file.

Read-only. For each configured expiry, aggregates across the day:
  * chain snapshots and fetch success rate,
  * average CE / PE contract counts per successful snapshot,
  * average CE / PE OI totals (from the record's derived block),
  * unfetched-instrument statistics.

Usage (PYTHONPATH=. or `python -m tools.data_quality.option_chain_report`):
    python -m tools.data_quality.option_chain_report --jsonl DAY.jsonl [--csv OUT.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.data_quality._common import (
    fmt,
    load_jsonl,
    print_section,
    record_chains,
    record_derived,
    write_csv,
)


def _avg(xs: list) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def build_option_chain_report(records: list[dict]) -> dict:
    """Per-expiry aggregation across the day. Pure; reads parsed records only."""
    acc: dict[str, dict] = {}

    def bucket(expiry: str) -> dict:
        return acc.setdefault(expiry, {
            "expiry": expiry, "snapshots": 0, "success": 0,
            "ce_counts": [], "pe_counts": [], "ce_oi": [], "pe_oi": [], "unfetched": [],
        })

    for r in records:
        derived = record_derived(r)
        for c in record_chains(r):
            expiry = c.get("expiry") or "?"
            b = bucket(expiry)
            b["snapshots"] += 1
            uf = c.get("unfetched_count")
            if isinstance(uf, int):
                b["unfetched"].append(uf)
            if not c.get("success"):
                continue
            b["success"] += 1
            quotes = c.get("quotes") or []
            b["ce_counts"].append(sum(1 for q in quotes if q.get("option_side") == "CE"))
            b["pe_counts"].append(sum(1 for q in quotes if q.get("option_side") == "PE"))
            if derived:
                ce_oi = (derived.get("total_ce_oi") or {}).get(expiry)
                pe_oi = (derived.get("total_pe_oi") or {}).get(expiry)
                if isinstance(ce_oi, (int, float)):
                    b["ce_oi"].append(ce_oi)
                if isinstance(pe_oi, (int, float)):
                    b["pe_oi"].append(pe_oi)

    expiries = []
    for expiry in sorted(acc):
        b = acc[expiry]
        expiries.append({
            "expiry": expiry,
            "snapshots": b["snapshots"],
            "success": b["success"],
            "success_rate": round(b["success"] / b["snapshots"], 4) if b["snapshots"] else None,
            "avg_ce_count": _avg(b["ce_counts"]),
            "avg_pe_count": _avg(b["pe_counts"]),
            "avg_ce_oi": _avg(b["ce_oi"]),
            "avg_pe_oi": _avg(b["pe_oi"]),
            "total_unfetched": sum(b["unfetched"]),
            "avg_unfetched": _avg(b["unfetched"]),
        })
    return {"expiries": expiries}


def render(report: dict, jsonl_path: str) -> None:
    print(f"\nOption-chain report - {jsonl_path}")
    print_section("Per expiry")
    header = (f"  {'expiry':<11} {'snaps':>6} {'ok%':>6} {'ce#':>6} {'pe#':>6} "
              f"{'ce_oi':>12} {'pe_oi':>12} {'unfetch':>8}")
    print(header)
    for e in report["expiries"]:
        ok_pct = round(100 * e["success_rate"], 1) if e["success_rate"] is not None else None
        print(f"  {e['expiry']:<11} {e['snapshots']:>6} {fmt(ok_pct):>6} "
              f"{fmt(e['avg_ce_count']):>6} {fmt(e['avg_pe_count']):>6} "
              f"{fmt(e['avg_ce_oi']):>12} {fmt(e['avg_pe_oi']):>12} "
              f"{fmt(e['total_unfetched']):>8}")
    if not report["expiries"]:
        print("  (no chain data)")


def _csv_rows(report: dict) -> list[list]:
    return [[e["expiry"], e["snapshots"], e["success"], e["success_rate"],
             e["avg_ce_count"], e["avg_pe_count"], e["avg_ce_oi"], e["avg_pe_oi"],
             e["total_unfetched"], e["avg_unfetched"]] for e in report["expiries"]]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="option_chain_report", description=__doc__)
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--csv", default=None)
    args = parser.parse_args(argv)

    records, _ = load_jsonl(args.jsonl)
    report = build_option_chain_report(records)
    render(report, args.jsonl)
    if args.csv:
        write_csv(args.csv,
                  ["expiry", "snapshots", "success", "success_rate", "avg_ce_count",
                   "avg_pe_count", "avg_ce_oi", "avg_pe_oi", "total_unfetched", "avg_unfetched"],
                  _csv_rows(report))
        print(f"\n  CSV written: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
