#!/usr/bin/env python
"""validate_day - integrity & continuity validator for one JSONL day file.

Read-only. Checks, per file (which may contain several runs / session_ids):
  * JSONL integrity   - every line parses; required keys present; schema known.
  * Duplicates        - duplicate poll_id (error) / duplicate timestamp (warn).
  * Continuity        - embedded continuity chain is intact and consistent with
                        the recomputed inter-snapshot interval.
  * Missing snapshots - estimated from GAP boundaries and the interval grid.
  * Manifest          - per-session manifest exists, is terminal, and its
                        counts/schema agree with the records.

Exit code: 0 when there are no ERROR-level issues, 1 otherwise.

Usage (PYTHONPATH=. or `python -m tools.data_quality.validate_day`):
    python -m tools.data_quality.validate_day --jsonl DAY.jsonl \
        [--manifest-dir DIR] [--csv OUT.csv]
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tools.data_quality._common import (
    KNOWN_SCHEMA_VERSIONS,
    LineError,
    load_jsonl,
    load_manifests,
    record_continuity,
    record_is_successful,
    record_meta,
    record_poll_id,
    record_polled_at,
    record_session_id,
    group_by_session,
    sort_by_time,
    write_csv,
)

_ERROR = "ERROR"
_WARN = "WARN"

# Recompute-vs-embedded interval mismatch tolerance (seconds).
_INTERVAL_MISMATCH_TOL = 1.0
# A required top-level key set for a Phase-1 observation record.
_REQUIRED_KEYS = frozenset(
    {"poll_id", "session_id", "polled_at", "meta", "spot", "vix", "chains", "continuity"}
)


@dataclass(frozen=True)
class Issue:
    severity: str  # "ERROR" | "WARN"
    category: str  # integrity | duplicate | continuity | missing | manifest
    message: str


@dataclass
class ValidationReport:
    jsonl_path: str
    record_count: int
    session_ids: list[str]
    estimated_missing: int
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == _ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == _WARN]

    @property
    def ok(self) -> bool:
        return not self.errors


# ── Checks ───────────────────────────────────────────────────────────────────


def check_jsonl_integrity(records: list[dict], line_errors: list[LineError]) -> list[Issue]:
    issues: list[Issue] = []
    for le in line_errors:
        issues.append(Issue(_ERROR, "integrity", f"line {le.line_no}: {le.message}"))
    for idx, rec in enumerate(records):
        missing = _REQUIRED_KEYS - set(rec)
        if missing:
            issues.append(
                Issue(_ERROR, "integrity",
                      f"record {idx} ({record_poll_id(rec) or '?'}) missing keys: "
                      f"{sorted(missing)}")
            )
        if record_polled_at(rec) is None:
            issues.append(
                Issue(_ERROR, "integrity",
                      f"record {idx} ({record_poll_id(rec) or '?'}) has unparseable polled_at")
            )
        sv = record_meta(rec).get("schema_version")
        if sv is not None and sv not in KNOWN_SCHEMA_VERSIONS:
            issues.append(
                Issue(_WARN, "integrity",
                      f"record {idx} has unrecognised schema_version={sv} "
                      f"(known: {sorted(KNOWN_SCHEMA_VERSIONS)})")
            )
    return issues


def check_duplicates(records: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    seen_poll: dict[str, int] = {}
    for r in records:
        pid = record_poll_id(r)
        if pid:
            seen_poll[pid] = seen_poll.get(pid, 0) + 1
    for pid, n in seen_poll.items():
        if n > 1:
            issues.append(Issue(_ERROR, "duplicate", f"poll_id {pid} appears {n} times"))

    for sid, recs in group_by_session(records).items():
        seen_ts: dict[str, int] = {}
        for r in recs:
            dt = record_polled_at(r)
            if dt is not None:
                key = dt.isoformat()
                seen_ts[key] = seen_ts.get(key, 0) + 1
        for ts, n in seen_ts.items():
            if n > 1:
                issues.append(
                    Issue(_WARN, "duplicate",
                          f"session {sid[:8]}: {n} snapshots share timestamp {ts}")
                )
    return issues


def check_continuity(records: list[dict]) -> list[Issue]:
    """Validate the embedded continuity chain within each session."""
    issues: list[Issue] = []
    for sid, recs in group_by_session(records).items():
        ordered = sort_by_time(recs)
        prev = None
        for pos, r in enumerate(ordered):
            cont = record_continuity(r)
            status = cont.get("continuity_status")
            if pos == 0:
                if status != "FIRST":
                    issues.append(
                        Issue(_WARN, "continuity",
                              f"session {sid[:8]}: first snapshot has status={status!r} "
                              f"(expected FIRST - file may start mid-run)")
                    )
            else:
                prev_id = cont.get("previous_snapshot_id")
                if prev_id != record_poll_id(prev):
                    issues.append(
                        Issue(_ERROR, "continuity",
                              f"session {sid[:8]}: broken chain at {record_poll_id(r)[:8]} "
                              f"- previous_snapshot_id={str(prev_id)[:8]} != "
                              f"prior poll_id={record_poll_id(prev)[:8]}")
                    )
                if status == "GAP":
                    issues.append(
                        Issue(_WARN, "continuity",
                              f"session {sid[:8]}: GAP at {record_poll_id(r)[:8]} "
                              f"(actual={cont.get('actual_interval_seconds')}s)")
                    )
                # Cross-check embedded interval against recomputed interval.
                a, b = record_polled_at(prev), record_polled_at(r)
                embedded = cont.get("actual_interval_seconds")
                if a is not None and b is not None and isinstance(embedded, (int, float)):
                    recomputed = (b - a).total_seconds()
                    if abs(recomputed - embedded) > _INTERVAL_MISMATCH_TOL:
                        issues.append(
                            Issue(_WARN, "continuity",
                                  f"session {sid[:8]}: interval mismatch at "
                                  f"{record_poll_id(r)[:8]} - embedded={embedded}s "
                                  f"recomputed={recomputed:.1f}s")
                        )
            prev = r
    return issues


def estimate_missing(records: list[dict]) -> int:
    """Estimate missing snapshots from GAP boundaries: round(actual/expected)-1."""
    missing = 0
    for recs in group_by_session(records).values():
        for r in sort_by_time(recs):
            cont = record_continuity(r)
            if cont.get("continuity_status") != "GAP":
                continue
            actual = cont.get("actual_interval_seconds")
            expected = cont.get("expected_interval_seconds")
            if isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and expected > 0:
                missing += max(0, round(actual / expected) - 1)
    return missing


def check_manifest_consistency(
    records: list[dict], manifests: dict[str, dict]
) -> list[Issue]:
    issues: list[Issue] = []
    for sid, recs in group_by_session(records).items():
        manifest = manifests.get(sid)
        if manifest is None:
            issues.append(
                Issue(_ERROR, "manifest",
                      f"session {sid[:8]}: no manifest found for this run_id")
            )
            continue

        status = manifest.get("status")
        if status == "running":
            issues.append(
                Issue(_WARN, "manifest",
                      f"session {sid[:8]}: manifest status='running' - run did not "
                      f"finish cleanly (possible hard kill)")
            )

        total = manifest.get("total_ticks")
        if isinstance(total, int) and total != len(recs):
            issues.append(
                Issue(_ERROR, "manifest",
                      f"session {sid[:8]}: manifest total_ticks={total} != "
                      f"{len(recs)} records in file")
            )

        succ = manifest.get("successful_polls")
        if isinstance(succ, int):
            recomputed = sum(1 for r in recs if record_is_successful(r))
            if succ != recomputed:
                issues.append(
                    Issue(_WARN, "manifest",
                          f"session {sid[:8]}: manifest successful_polls={succ} != "
                          f"recomputed {recomputed}")
                )

        m_schema = manifest.get("observation_schema_version")
        rec_schemas = {record_meta(r).get("schema_version") for r in recs}
        rec_schemas.discard(None)
        if m_schema is not None and rec_schemas and rec_schemas != {m_schema}:
            issues.append(
                Issue(_ERROR, "manifest",
                      f"session {sid[:8]}: manifest schema={m_schema} != "
                      f"record schema(s) {sorted(rec_schemas)}")
            )
    return issues


def validate_day(jsonl_path: Path | str, manifest_dir: Path | str | None = None) -> ValidationReport:
    """Run every check over one day file. Pure w.r.t. the filesystem (read-only)."""
    records, line_errors = load_jsonl(jsonl_path)
    manifests = load_manifests(manifest_dir) if manifest_dir else {}

    issues: list[Issue] = []
    issues += check_jsonl_integrity(records, line_errors)
    issues += check_duplicates(records)
    issues += check_continuity(records)
    if manifest_dir is not None:
        issues += check_manifest_consistency(records, manifests)

    missing = estimate_missing(records)
    if missing:
        issues.append(
            Issue(_WARN, "missing", f"estimated {missing} missing snapshot(s) across GAP boundaries")
        )

    return ValidationReport(
        jsonl_path=str(jsonl_path),
        record_count=len(records),
        session_ids=sorted({record_session_id(r) for r in records}),
        estimated_missing=missing,
        issues=issues,
    )


# ── Rendering / CLI ──────────────────────────────────────────────────────────


def render(report: ValidationReport) -> None:
    print(f"\nValidation - {report.jsonl_path}")
    print(f"  records: {report.record_count}   sessions: {len(report.session_ids)}   "
          f"estimated missing: {report.estimated_missing}")
    if not report.issues:
        print("  OK - no issues found.")
    else:
        for sev in (_ERROR, _WARN):
            for i in (x for x in report.issues if x.severity == sev):
                print(f"  [{i.severity}] {i.category}: {i.message}")
    print(f"\n  {len(report.errors)} error(s), {len(report.warnings)} warning(s) - "
          f"{'PASS' if report.ok else 'FAIL'}")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate_day", description=__doc__)
    parser.add_argument("--jsonl", required=True, help="Path to a {YYYYMMDD}.jsonl day file")
    parser.add_argument("--manifest-dir", default=None, help="Directory of {run_id}.json manifests")
    parser.add_argument("--csv", default=None, help="Optional CSV output of issues")
    args = parser.parse_args(argv)

    report = validate_day(args.jsonl, args.manifest_dir)
    render(report)
    if args.csv:
        write_csv(
            args.csv,
            ["severity", "category", "message"],
            [[i.severity, i.category, i.message] for i in report.issues],
        )
        print(f"  CSV written: {args.csv}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(run())
