"""Tests for tools.data_quality.validate_day."""
from __future__ import annotations

import json

from tools.data_quality import validate_day as V

from tests.unit.test_tools.conftest import (
    make_chain,
    make_manifest,
    make_record,
    make_session,
    write_jsonl,
)


class TestCleanDay:
    def test_no_issues(self, clean_day) -> None:
        report = V.validate_day(clean_day["jsonl"], clean_day["manifest_dir"])
        assert report.ok
        assert report.errors == []
        assert report.record_count == 4

    def test_run_exit_zero(self, clean_day) -> None:
        code = V.run(["--jsonl", str(clean_day["jsonl"]),
                      "--manifest-dir", str(clean_day["manifest_dir"])])
        assert code == 0


class TestIntegrity:
    def test_corrupt_line_is_error(self, tmp_path) -> None:
        p = tmp_path / "20260630.jsonl"
        p.write_text(json.dumps(make_record()) + "\n{bad\n", encoding="utf-8")
        report = V.validate_day(p)
        assert not report.ok
        assert any(i.category == "integrity" for i in report.errors)

    def test_missing_required_key_is_error(self, tmp_path) -> None:
        rec = make_record()
        del rec["continuity"]
        p = write_jsonl(tmp_path / "d.jsonl", [rec])
        report = V.validate_day(p)
        assert any("missing keys" in i.message for i in report.errors)

    def test_unknown_schema_is_warning(self, tmp_path) -> None:
        rec = make_record(schema_version=99)
        p = write_jsonl(tmp_path / "d.jsonl", [rec])
        report = V.validate_day(p)
        assert any("schema_version" in i.message and i.severity == "WARN"
                   for i in report.issues)


class TestDuplicates:
    def test_duplicate_poll_id_is_error(self, tmp_path) -> None:
        r1 = make_record(poll_id="dup", session_id="s1")
        r2 = make_record(poll_id="dup", session_id="s1", status="CONTIGUOUS",
                         prev_id="dup", actual=5)
        p = write_jsonl(tmp_path / "d.jsonl", [r1, r2])
        report = V.validate_day(p)
        assert any(i.category == "duplicate" and i.severity == "ERROR" for i in report.issues)


class TestContinuity:
    def test_broken_chain_is_error(self, tmp_path) -> None:
        recs = make_session("s1", [5, 5], interval=5)
        # Corrupt the 2nd record's back-pointer.
        recs[1]["continuity"]["previous_snapshot_id"] = "wrong-id"
        p = write_jsonl(tmp_path / "d.jsonl", recs)
        report = V.validate_day(p)
        assert any(i.category == "continuity" and i.severity == "ERROR" for i in report.issues)

    def test_gap_is_warning_and_counts_missing(self, tmp_path) -> None:
        # deltas: 5 (contiguous), 30 (gap of ~5 missing at interval 5)
        recs = make_session("s1", [5, 30], interval=5)
        p = write_jsonl(tmp_path / "d.jsonl", recs)
        report = V.validate_day(p)
        assert any(i.category == "continuity" and "GAP" in i.message for i in report.warnings)
        assert report.estimated_missing == 5  # round(30/5)-1

    def test_first_not_first_is_warning(self, tmp_path) -> None:
        rec = make_record(status="CONTIGUOUS", prev_id="x", actual=5)
        p = write_jsonl(tmp_path / "d.jsonl", [rec])
        report = V.validate_day(p)
        assert any("expected FIRST" in i.message for i in report.warnings)

    def test_interval_mismatch_is_warning(self, tmp_path) -> None:
        recs = make_session("s1", [5], interval=5)
        recs[1]["continuity"]["actual_interval_seconds"] = 999  # contradicts timestamps
        p = write_jsonl(tmp_path / "d.jsonl", recs)
        report = V.validate_day(p)
        assert any("interval mismatch" in i.message for i in report.warnings)


class TestManifestConsistency:
    def test_missing_manifest_is_error(self, tmp_path) -> None:
        recs = make_session("s1", [5], interval=5)
        p = write_jsonl(tmp_path / "d.jsonl", recs)
        mdir = tmp_path / "manifests"
        mdir.mkdir()
        report = V.validate_day(p, mdir)
        assert any(i.category == "manifest" and "no manifest" in i.message for i in report.errors)

    def test_total_ticks_mismatch_is_error(self, tmp_path) -> None:
        recs = make_session("run-a", [5, 5, 5], interval=5)  # 4 records
        p = write_jsonl(tmp_path / "d.jsonl", recs)
        mdir = tmp_path / "manifests"
        mdir.mkdir()
        (mdir / "run-a.json").write_text(
            json.dumps(make_manifest("run-a", total_ticks=99, successful=4, failed=0)),
            encoding="utf-8")
        report = V.validate_day(p, mdir)
        assert any("total_ticks" in i.message and i.severity == "ERROR" for i in report.issues)

    def test_running_status_is_warning(self, tmp_path) -> None:
        recs = make_session("run-a", [5], interval=5)  # 2 records
        p = write_jsonl(tmp_path / "d.jsonl", recs)
        mdir = tmp_path / "manifests"
        mdir.mkdir()
        (mdir / "run-a.json").write_text(
            json.dumps(make_manifest("run-a", total_ticks=None, successful=None,
                                     failed=None, status="running")),
            encoding="utf-8")
        report = V.validate_day(p, mdir)
        assert any("running" in i.message and i.severity == "WARN" for i in report.issues)

    def test_schema_mismatch_is_error(self, tmp_path) -> None:
        recs = make_session("run-a", [5], interval=5)
        p = write_jsonl(tmp_path / "d.jsonl", recs)
        mdir = tmp_path / "manifests"
        mdir.mkdir()
        (mdir / "run-a.json").write_text(
            json.dumps(make_manifest("run-a", total_ticks=2, successful=2, failed=0, schema=3)),
            encoding="utf-8")
        report = V.validate_day(p, mdir)
        assert any("schema" in i.message and i.severity == "ERROR" for i in report.issues)

    def test_run_exit_one_on_error(self, tmp_path) -> None:
        rec = make_record()
        del rec["meta"]
        p = write_jsonl(tmp_path / "d.jsonl", [rec])
        assert V.run(["--jsonl", str(p)]) == 1
