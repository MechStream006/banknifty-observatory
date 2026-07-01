"""Tests for tools.data_quality._common."""
from __future__ import annotations

from datetime import datetime, timezone

from tools.data_quality import _common as C

from tests.unit.test_tools.conftest import make_chain, make_record, make_manifest


class TestParseDt:
    def test_valid_iso(self) -> None:
        dt = C.parse_dt("2026-06-30T09:15:00+00:00")
        assert dt == datetime(2026, 6, 30, 9, 15, tzinfo=timezone.utc)

    def test_invalid_returns_none(self) -> None:
        assert C.parse_dt("not-a-date") is None

    def test_non_string_returns_none(self) -> None:
        assert C.parse_dt(12345) is None


class TestLoadJsonl:
    def test_reads_valid_records(self, tmp_path) -> None:
        p = tmp_path / "d.jsonl"
        p.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
        records, errors = C.load_jsonl(p)
        assert len(records) == 2
        assert errors == []

    def test_blank_lines_skipped(self, tmp_path) -> None:
        p = tmp_path / "d.jsonl"
        p.write_text('{"a":1}\n\n  \n{"b":2}\n', encoding="utf-8")
        records, errors = C.load_jsonl(p)
        assert len(records) == 2 and errors == []

    def test_corrupt_line_captured_not_raised(self, tmp_path) -> None:
        p = tmp_path / "d.jsonl"
        p.write_text('{"a":1}\n{bad json\n{"b":2}\n', encoding="utf-8")
        records, errors = C.load_jsonl(p)
        assert len(records) == 2
        assert len(errors) == 1
        assert errors[0].line_no == 2

    def test_non_object_line_is_error(self, tmp_path) -> None:
        p = tmp_path / "d.jsonl"
        p.write_text('[1,2,3]\n{"a":1}\n', encoding="utf-8")
        records, errors = C.load_jsonl(p)
        assert len(records) == 1 and len(errors) == 1


class TestLoadManifests:
    def test_keyed_by_run_id(self, tmp_path) -> None:
        import json
        (tmp_path / "run-a.json").write_text(
            json.dumps(make_manifest("run-a", total_ticks=4, successful=4, failed=0)),
            encoding="utf-8")
        manifests = C.load_manifests(tmp_path)
        assert set(manifests) == {"run-a"}

    def test_missing_dir_returns_empty(self, tmp_path) -> None:
        assert C.load_manifests(tmp_path / "nope") == {}


class TestStatistics:
    def test_percentile_known(self) -> None:
        vals = [10, 20, 30, 40, 50]
        assert C.percentile(vals, 50) == 30.0
        assert C.percentile(vals, 0) == 10.0
        assert C.percentile(vals, 100) == 50.0

    def test_percentile_empty_none(self) -> None:
        assert C.percentile([], 95) is None

    def test_describe_basic(self) -> None:
        d = C.describe([1, 2, 3, 4])
        assert d["count"] == 4
        assert d["min"] == 1 and d["max"] == 4
        assert d["mean"] == 2.5

    def test_describe_empty(self) -> None:
        d = C.describe([])
        assert d["count"] == 0 and d["mean"] is None

    def test_describe_ignores_non_numeric(self) -> None:
        d = C.describe([1, None, "x", 3])
        assert d["count"] == 2


class TestRecordAccessors:
    def test_record_is_successful_true_when_any_chain_ok(self) -> None:
        rec = make_record(chains=[make_chain(success=False), make_chain(success=True)])
        assert C.record_is_successful(rec) is True

    def test_record_is_successful_false_when_no_chains(self) -> None:
        rec = make_record(chains=[])
        assert C.record_is_successful(rec) is False

    def test_modal_interval(self) -> None:
        recs = [make_record(interval=5), make_record(interval=5), make_record(interval=60)]
        assert C.modal_interval(recs) == 5

    def test_modal_interval_fallback(self) -> None:
        assert C.modal_interval([{"interval_s": 0}], fallback=7) == 7


class TestWriteCsv:
    def test_writes_header_and_rows(self, tmp_path) -> None:
        out = C.write_csv(tmp_path / "sub" / "r.csv", ["a", "b"], [[1, 2], [3, 4]])
        text = out.read_text(encoding="utf-8")
        assert "a,b" in text and "1,2" in text and "3,4" in text
