"""Tests for tools.data_quality.coverage."""
from __future__ import annotations

from tools.data_quality import coverage as CV

from tests.unit.test_tools.conftest import make_session


class TestBuildCoverage:
    def test_contiguous_is_full_coverage(self) -> None:
        recs = make_session("s1", [5, 5, 5], interval=5)
        out = CV.build_coverage(recs)
        assert out["total_captured"] == 4
        assert out["total_expected"] == 4
        assert out["total_missing"] == 0
        assert out["coverage_pct"] == 100.0
        assert out["gaps"] == []

    def test_gap_reduces_coverage(self) -> None:
        # deltas 5, 30, 5 → one 30s gap (missing ~5 at interval 5)
        recs = make_session("s1", [5, 30, 5], interval=5)
        out = CV.build_coverage(recs)
        assert out["total_missing"] > 0
        assert len(out["gaps"]) == 1
        assert out["gaps"][0]["missing_estimate"] == 5
        assert out["coverage_pct"] < 100.0

    def test_interval_override(self) -> None:
        recs = make_session("s1", [5, 5], interval=5)
        out = CV.build_coverage(recs, interval=5)
        assert out["interval_seconds"] == 5

    def test_per_session_split(self) -> None:
        a = make_session("run-a", [5, 5], interval=5)
        b = make_session("run-b", [5], interval=5)
        out = CV.build_coverage(a + b)
        assert len(out["sessions"]) == 2
        assert out["total_captured"] == 5  # 3 + 2

    def test_gap_records_boundary_timestamps(self) -> None:
        recs = make_session("s1", [30], interval=5)
        out = CV.build_coverage(recs)
        gap = out["gaps"][0]
        assert gap["from"] is not None and gap["to"] is not None
        assert gap["gap_seconds"] == 30.0

    def test_csv_output_of_gaps(self, tmp_path) -> None:
        import json
        recs = make_session("s1", [30], interval=5)
        p = tmp_path / "d.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
        out_csv = tmp_path / "gaps.csv"
        assert CV.run(["--jsonl", str(p), "--csv", str(out_csv)]) == 0
        assert "missing_estimate" in out_csv.read_text(encoding="utf-8")
