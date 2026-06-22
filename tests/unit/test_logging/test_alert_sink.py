"""Tests for AlertSink interface and AlertHandler routing."""
from __future__ import annotations

import logging
from typing import Any

import pytest

from lib.logging._alert_sink import (
    AlertHandler,
    AlertSink,
    _reset_alert_handler,
    _set_alert_handler,
    register_alert_sink,
)
from lib.logging._context import _init_context, _reset_context


class _SpySink(AlertSink):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def emit(self, level: str, message: str, context: dict[str, Any]) -> None:
        self.calls.append((level, message, context))


class TestAlertHandlerRouting:
    def test_sink_called_for_record_at_threshold(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        sink = _SpySink()
        handler.add_sink(sink)
        record = logging.LogRecord("bno.test", logging.ERROR, "", 0, "Error happened", None, None)
        handler.handle(record)
        assert len(sink.calls) == 1
        assert sink.calls[0][0] == "ERROR"

    def test_sink_not_called_below_threshold(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        sink = _SpySink()
        handler.add_sink(sink)
        record = logging.LogRecord("bno.test", logging.WARNING, "", 0, "Just a warning", None, None)
        handler.handle(record)
        assert len(sink.calls) == 0

    def test_sink_called_for_critical(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        sink = _SpySink()
        handler.add_sink(sink)
        record = logging.LogRecord("bno.test", logging.CRITICAL, "", 0, "Critical failure", None, None)
        handler.handle(record)
        assert len(sink.calls) == 1
        assert sink.calls[0][0] == "CRITICAL"

    def test_sink_not_called_for_info_with_error_threshold(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        sink = _SpySink()
        handler.add_sink(sink)
        record = logging.LogRecord("bno.test", logging.INFO, "", 0, "Info msg", None, None)
        handler.handle(record)
        assert len(sink.calls) == 0

    def test_multiple_sinks_all_notified(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        sink1, sink2 = _SpySink(), _SpySink()
        handler.add_sink(sink1)
        handler.add_sink(sink2)
        record = logging.LogRecord("bno.test", logging.ERROR, "", 0, "Error", None, None)
        handler.handle(record)
        assert len(sink1.calls) == 1
        assert len(sink2.calls) == 1

    def test_failing_sink_does_not_propagate_exception(self) -> None:
        class _CrashingSink(AlertSink):
            def emit(self, level: str, message: str, context: dict[str, Any]) -> None:
                raise RuntimeError("Sink exploded")

        handler = AlertHandler(min_level=logging.ERROR)
        handler.add_sink(_CrashingSink())
        record = logging.LogRecord("bno.test", logging.ERROR, "", 0, "Error", None, None)
        handler.handle(record)  # Must not raise.

    def test_context_includes_run_id_and_instance_id(self) -> None:
        _init_context(run_id="test-run", instance_id="test-host")
        try:
            handler = AlertHandler(min_level=logging.ERROR)
            sink = _SpySink()
            handler.add_sink(sink)
            record = logging.LogRecord("bno.test", logging.ERROR, "", 0, "Error", None, None)
            handler.handle(record)
            context = sink.calls[0][2]
            assert context["run_id"] == "test-run"
            assert context["instance_id"] == "test-host"
            assert context["logger"] == "bno.test"
        finally:
            _reset_context()

    def test_context_includes_logger_name(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        sink = _SpySink()
        handler.add_sink(sink)
        record = logging.LogRecord("bno.acquisition.session", logging.ERROR, "", 0, "Err", None, None)
        handler.handle(record)
        assert sink.calls[0][2]["logger"] == "bno.acquisition.session"


class TestRegisterAlertSink:
    def test_register_before_bootstrap_raises_runtime_error(self) -> None:
        with pytest.raises(RuntimeError, match="bootstrap_logging"):
            register_alert_sink(_SpySink())

    def test_register_after_set_handler_succeeds(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        _set_alert_handler(handler)
        sink = _SpySink()
        register_alert_sink(sink)
        assert sink in handler._sinks

    def test_registered_sink_receives_alerts(self) -> None:
        handler = AlertHandler(min_level=logging.ERROR)
        _set_alert_handler(handler)
        sink = _SpySink()
        register_alert_sink(sink)
        record = logging.LogRecord("bno.test", logging.ERROR, "", 0, "Fire", None, None)
        handler.handle(record)
        assert len(sink.calls) == 1
