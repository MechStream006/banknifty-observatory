"""Tests for BNOJsonFormatter: schema, timestamps, field extraction."""
from __future__ import annotations

import datetime
import json
import logging
from collections.abc import Generator

import pytest

from lib.logging._constants import LOG_SCHEMA_VERSION
from lib.logging._context import _init_context, _reset_context
from lib.logging._formatter import BNOJsonFormatter


@pytest.fixture(autouse=True)
def _set_context() -> Generator[None, None, None]:
    _init_context(run_id="test-run-123", instance_id="test-host-01")
    yield
    _reset_context()


def _make_record(
    name: str = "bno.acquisition.session",
    msg: str = "test message",
    level: int = logging.INFO,
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name, level=level,
        pathname="", lineno=0, msg=msg, args=None, exc_info=None,
    )


class TestJsonSchema:
    def test_output_is_valid_json(self) -> None:
        output = BNOJsonFormatter().format(_make_record())
        assert isinstance(json.loads(output), dict)

    def test_single_line_output(self) -> None:
        output = BNOJsonFormatter().format(_make_record())
        assert "\n" not in output

    def test_required_fields_present(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        for field in ("schema", "ts", "level", "logger", "service", "run_id", "instance_id", "msg"):
            assert field in parsed, f"Missing required field: {field!r}"

    def test_schema_version(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        assert parsed["schema"] == LOG_SCHEMA_VERSION


class TestTimestamp:
    def test_timestamp_is_utc(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        dt = datetime.datetime.fromisoformat(parsed["ts"])
        assert dt.tzinfo is not None
        assert dt.utcoffset() == datetime.timedelta(0)

    def test_timestamp_is_recent(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        dt = datetime.datetime.fromisoformat(parsed["ts"])
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        assert abs((now - dt).total_seconds()) < 5


class TestFieldExtraction:
    def test_service_extracted_from_three_part_name(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record(name="bno.derivation.iv")))
        assert parsed["service"] == "derivation"

    def test_service_extracted_from_two_part_name(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record(name="bno.research")))
        assert parsed["service"] == "research"

    def test_run_id_injected(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        assert parsed["run_id"] == "test-run-123"

    def test_instance_id_injected(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        assert parsed["instance_id"] == "test-host-01"

    def test_level_name_correct_for_warning(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record(level=logging.WARNING)))
        assert parsed["level"] == "WARNING"

    def test_level_name_correct_for_critical(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record(level=logging.CRITICAL)))
        assert parsed["level"] == "CRITICAL"

    def test_logger_name_preserved(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record(name="bno.integrity.completeness")))
        assert parsed["logger"] == "bno.integrity.completeness"


class TestExtraFields:
    def test_data_field_included_when_provided(self) -> None:
        record = _make_record()
        record.data = {"symbol": "BANKNIFTY", "tick_count": 42}
        parsed = json.loads(BNOJsonFormatter().format(record))
        assert "data" in parsed
        assert parsed["data"]["symbol"] == "BANKNIFTY"
        assert parsed["data"]["tick_count"] == 42

    def test_data_field_absent_when_not_provided(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        assert "data" not in parsed

    def test_exc_field_absent_when_no_exception(self) -> None:
        parsed = json.loads(BNOJsonFormatter().format(_make_record()))
        assert "exc" not in parsed

    def test_exc_field_present_when_exc_text_set(self) -> None:
        record = _make_record()
        record.exc_text = "Traceback (most recent call last): ..."
        parsed = json.loads(BNOJsonFormatter().format(record))
        assert "exc" in parsed
        assert "Traceback" in parsed["exc"]
