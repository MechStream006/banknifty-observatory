"""Tests for lib.discovery.archiver: JSONLArchiver."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.discovery._errors import ArchiverError
from lib.discovery.archiver import JSONLArchiver


# ===========================================================================
# Helpers
# ===========================================================================


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _read_lines(path: Path) -> list[str]:
    """Return non-empty stripped lines from *path*."""
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ===========================================================================
# Directory and file creation
# ===========================================================================


class TestDirectoryAndFileCreation:
    def test_creates_output_directory_on_open(self, tmp_path: Path) -> None:
        nested = tmp_path / "discovery" / "phase1"
        with JSONLArchiver(output_dir=nested) as archiver:
            archiver.write({"key": "value"})
        assert nested.is_dir()

    def test_creates_dated_jsonl_file(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write({"key": "value"})
        assert (tmp_path / f"{_today_str()}.jsonl").exists()

    def test_accepts_string_output_dir(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=str(tmp_path)) as archiver:
            archiver.write({"n": 1})
        assert archiver.byte_count > 0


# ===========================================================================
# Write content correctness
# ===========================================================================


class TestWriteContent:
    def test_written_line_is_valid_json(self, tmp_path: Path) -> None:
        record = {"poll": 1, "ltp": 52000.5}
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write(record)
        line = _read_lines(tmp_path / f"{_today_str()}.jsonl")[0]
        assert json.loads(line) == record

    def test_each_line_ends_with_newline(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write({"a": 1})
            archiver.write({"b": 2})
        raw = (tmp_path / f"{_today_str()}.jsonl").read_bytes()
        assert raw.count(b"\n") == 2

    def test_multiple_writes_preserve_order(self, tmp_path: Path) -> None:
        records = [{"seq": i} for i in range(5)]
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            for r in records:
                archiver.write(r)
        lines = _read_lines(tmp_path / f"{_today_str()}.jsonl")
        assert [json.loads(ln)["seq"] for ln in lines] == list(range(5))

    def test_datetime_serialised_as_iso_string(self, tmp_path: Path) -> None:
        dt = datetime(2026, 6, 22, 9, 15, 0, tzinfo=timezone.utc)
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write({"ts": dt, "value": 42})
        line = _read_lines(tmp_path / f"{_today_str()}.jsonl")[0]
        data = json.loads(line)
        assert data["ts"] == "2026-06-22T09:15:00+00:00"

    def test_path_serialised_as_string(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write({"path": Path("/data/raw")})
        line = _read_lines(tmp_path / f"{_today_str()}.jsonl")[0]
        data = json.loads(line)
        assert isinstance(data["path"], str)

    def test_unicode_content_written_correctly(self, tmp_path: Path) -> None:
        record = {"name": "日本語", "value": "αβγ"}
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write(record)
        line = _read_lines(tmp_path / f"{_today_str()}.jsonl")[0]
        assert json.loads(line) == record


# ===========================================================================
# Line count and byte count
# ===========================================================================


class TestCounts:
    def test_line_count_starts_at_zero(self, tmp_path: Path) -> None:
        archiver = JSONLArchiver(output_dir=tmp_path)
        assert archiver.line_count == 0

    def test_byte_count_starts_at_zero(self, tmp_path: Path) -> None:
        archiver = JSONLArchiver(output_dir=tmp_path)
        assert archiver.byte_count == 0

    def test_line_count_increments_per_write(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            for i in range(4):
                archiver.write({"i": i})
        assert archiver.line_count == 4

    def test_byte_count_matches_file_size(self, tmp_path: Path) -> None:
        record = {"tick": 1, "ltp": 52000.5}
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write(record)
        file_path = tmp_path / f"{_today_str()}.jsonl"
        assert archiver.byte_count == file_path.stat().st_size

    def test_byte_count_accumulates_across_writes(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write({"a": 1})
            after_first = archiver.byte_count
            archiver.write({"b": 2})
            after_second = archiver.byte_count
        assert after_second > after_first


# ===========================================================================
# Context manager and lifecycle
# ===========================================================================


class TestLifecycle:
    def test_context_manager_allows_writing(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            archiver.write({"ok": True})
        assert archiver.line_count == 1

    def test_open_is_idempotent(self, tmp_path: Path) -> None:
        archiver = JSONLArchiver(output_dir=tmp_path)
        archiver.open()
        first_file = archiver._file
        archiver.open()  # second call is a no-op
        assert archiver._file is first_file
        archiver.close()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        archiver = JSONLArchiver(output_dir=tmp_path)
        archiver.open()
        archiver.close()
        archiver.close()  # should not raise

    def test_current_file_path_is_none_before_open(self, tmp_path: Path) -> None:
        archiver = JSONLArchiver(output_dir=tmp_path)
        assert archiver.current_file_path is None

    def test_current_file_path_matches_dated_pattern(self, tmp_path: Path) -> None:
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            expected = tmp_path / f"{_today_str()}.jsonl"
            assert archiver.current_file_path == expected


# ===========================================================================
# Error handling
# ===========================================================================


class TestErrorHandling:
    def test_write_before_open_raises_archiver_error(self, tmp_path: Path) -> None:
        archiver = JSONLArchiver(output_dir=tmp_path)
        with pytest.raises(ArchiverError, match="not open"):
            archiver.write({"key": "value"})

    def test_circular_reference_raises_archiver_error(self, tmp_path: Path) -> None:
        cycle: dict = {}
        cycle["self"] = cycle
        with JSONLArchiver(output_dir=tmp_path) as archiver:
            with pytest.raises(ArchiverError, match="not JSON-serialisable"):
                archiver.write(cycle)

    def test_os_error_on_write_raises_archiver_error(self, tmp_path: Path) -> None:
        archiver = JSONLArchiver(output_dir=tmp_path)
        archiver.open()
        # Replace the real file handle with a mock that fails on write
        mock_file = MagicMock()
        mock_file.write.side_effect = OSError("disk full")
        archiver._file = mock_file
        with pytest.raises(ArchiverError, match="disk full"):
            archiver.write({"key": "value"})
        # Prevent close() from failing on the mock
        mock_file.close.return_value = None
        archiver.close()

    def test_archiver_error_is_subclass_of_bno_discovery_error(self) -> None:
        from lib.discovery._errors import BNODiscoveryError
        assert issubclass(ArchiverError, BNODiscoveryError)


# ===========================================================================
# Daily file rotation
# ===========================================================================


class TestDailyRotation:
    def test_rotation_creates_new_dated_file(self, tmp_path: Path) -> None:
        day1 = date(2026, 6, 22)
        day2 = date(2026, 6, 23)
        # _today() call order: _rotate() on open, write#1 check, write#2 check,
        # _rotate() triggered by write#2.
        with patch(
            "lib.discovery.archiver._today",
            side_effect=[day1, day1, day2, day2],
        ):
            with JSONLArchiver(output_dir=tmp_path) as archiver:
                archiver.write({"tick": 1})
                archiver.write({"tick": 2})

        assert (tmp_path / "20260622.jsonl").exists()
        assert (tmp_path / "20260623.jsonl").exists()

    def test_rotation_writes_to_correct_files(self, tmp_path: Path) -> None:
        day1 = date(2026, 6, 22)
        day2 = date(2026, 6, 23)
        with patch(
            "lib.discovery.archiver._today",
            side_effect=[day1, day1, day2, day2],
        ):
            with JSONLArchiver(output_dir=tmp_path) as archiver:
                archiver.write({"tick": 1})
                archiver.write({"tick": 2})

        lines_day1 = _read_lines(tmp_path / "20260622.jsonl")
        lines_day2 = _read_lines(tmp_path / "20260623.jsonl")
        assert len(lines_day1) == 1
        assert json.loads(lines_day1[0])["tick"] == 1
        assert len(lines_day2) == 1
        assert json.loads(lines_day2[0])["tick"] == 2

    def test_line_count_spans_rotation(self, tmp_path: Path) -> None:
        day1 = date(2026, 6, 22)
        day2 = date(2026, 6, 23)
        with patch(
            "lib.discovery.archiver._today",
            side_effect=[day1, day1, day2, day2],
        ):
            with JSONLArchiver(output_dir=tmp_path) as archiver:
                archiver.write({"tick": 1})
                archiver.write({"tick": 2})
        # Total lines across both files
        assert archiver.line_count == 2
