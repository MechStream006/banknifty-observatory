"""Shared read-only helpers for the Data Quality Toolkit.

Loaders, record accessors, statistics, and output helpers. No function here
writes to or mutates archived data - the only write path is ``write_csv``,
which writes derived reports to a caller-chosen location, never the corpus.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Single source of truth for the recognised record schema, when the library is
# importable. The toolkit stays usable against an archived corpus without the
# library on the path, so the import is guarded.
try:  # pragma: no cover - trivial import guard
    from lib.discovery._models import OBSERVATION_SCHEMA_VERSION as _CURRENT_SCHEMA

    KNOWN_SCHEMA_VERSIONS: frozenset[int] = frozenset({_CURRENT_SCHEMA})
except Exception:  # pragma: no cover
    KNOWN_SCHEMA_VERSIONS = frozenset({2})


# ── Loading ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LineError:
    """A JSONL line that could not be parsed into a record object."""

    line_no: int
    message: str


def parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into a datetime, or None if unparseable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_jsonl(path: Path | str) -> tuple[list[dict], list[LineError]]:
    """Read a JSONL day file. Returns (records, line_errors).

    Blank lines are skipped. Lines that are not valid JSON objects are reported
    as LineError rather than raised, so a single corrupt line never aborts the
    whole validation. The file is opened read-only.
    """
    records: list[dict] = []
    errors: list[LineError] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as exc:
                errors.append(LineError(i, f"invalid JSON: {exc}"))
                continue
            if not isinstance(obj, dict):
                errors.append(LineError(i, "line is not a JSON object"))
                continue
            records.append(obj)
    return records, errors


def load_manifest(path: Path | str) -> dict:
    """Load a single manifest JSON file (read-only)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_manifests(directory: Path | str) -> dict[str, dict]:
    """Load every ``*.json`` manifest in *directory*, keyed by run_id.

    Missing directory → empty dict. Unreadable/corrupt manifests are skipped.
    """
    out: dict[str, dict] = {}
    d = Path(directory)
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        run_id = m.get("run_id") or f.stem
        out[str(run_id)] = m
    return out


# ── Record accessors ─────────────────────────────────────────────────────────


def record_session_id(rec: dict) -> str:
    return str(rec.get("session_id", ""))


def record_poll_id(rec: dict) -> str:
    return str(rec.get("poll_id", ""))


def record_polled_at(rec: dict) -> datetime | None:
    return parse_dt(rec.get("polled_at"))


def record_meta(rec: dict) -> dict:
    m = rec.get("meta")
    return m if isinstance(m, dict) else {}


def record_spot(rec: dict) -> dict:
    s = rec.get("spot")
    return s if isinstance(s, dict) else {}


def record_vix(rec: dict) -> dict:
    v = rec.get("vix")
    return v if isinstance(v, dict) else {}


def record_continuity(rec: dict) -> dict:
    c = rec.get("continuity")
    return c if isinstance(c, dict) else {}


def record_chains(rec: dict) -> list[dict]:
    c = rec.get("chains")
    return [x for x in c if isinstance(x, dict)] if isinstance(c, list) else []


def record_derived(rec: dict) -> dict | None:
    d = rec.get("derived")
    return d if isinstance(d, dict) else None


def record_is_successful(rec: dict) -> bool:
    """Mirror the collector's poll-success rule: any chain fetch succeeded."""
    return any(bool(c.get("success")) for c in record_chains(rec))


def group_by_session(records: list[dict]) -> dict[str, list[dict]]:
    """Group records by session_id, preserving input order within each group."""
    out: dict[str, list[dict]] = {}
    for r in records:
        out.setdefault(record_session_id(r), []).append(r)
    return out


def sort_by_time(records: list[dict]) -> list[dict]:
    """Records sorted by polled_at (unparseable timestamps sort last)."""
    far_future = datetime.max
    return sorted(
        records,
        key=lambda r: (record_polled_at(r) or far_future.replace(tzinfo=None)),
    )


# ── Statistics ───────────────────────────────────────────────────────────────


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile of *values*. None for empty input."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def describe(values: list[Any]) -> dict:
    """min/max/mean/p50/p95/p99/count over the numeric members of *values*."""
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    if not vals:
        return {
            "count": 0, "min": None, "max": None, "mean": None,
            "p50": None, "p95": None, "p99": None,
        }
    return {
        "count": len(vals),
        "min": min(vals),
        "max": max(vals),
        "mean": sum(vals) / len(vals),
        "p50": percentile(vals, 50),
        "p95": percentile(vals, 95),
        "p99": percentile(vals, 99),
    }


def modal_interval(records: list[dict], fallback: int = 0) -> int:
    """Most common interval_s across records; *fallback* when none present."""
    counts: dict[int, int] = {}
    for r in records:
        iv = r.get("interval_s")
        if isinstance(iv, int) and iv > 0:
            counts[iv] = counts.get(iv, 0) + 1
    if not counts:
        return fallback
    return max(counts, key=lambda k: counts[k])


# ── Output ───────────────────────────────────────────────────────────────────


def fmt(value: Any, nd: int = 2) -> str:
    """Compact human formatting: floats rounded, None → '-'."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{nd}f}"
    return str(value)


def print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def print_kv(pairs: list[tuple[str, Any]]) -> None:
    width = max((len(k) for k, _ in pairs), default=0)
    for k, v in pairs:
        print(f"  {k.ljust(width)} : {fmt(v)}")


def write_csv(path: Path | str, header: list[str], rows: list[list[Any]]) -> Path:
    """Write a derived report to CSV at *path* (never the corpus). Returns path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return p
