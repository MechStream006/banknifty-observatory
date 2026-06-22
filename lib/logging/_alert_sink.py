from __future__ import annotations

import abc
import logging
from typing import Any

from lib.logging._context import get_instance_id, get_run_id


class AlertSink(abc.ABC):
    """
    Abstract interface for out-of-band alert delivery (e.g. Telegram).

    Implementations are registered via register_alert_sink() after
    bootstrap_logging(). The emit() method must not raise — any exception
    is silently suppressed so alerting never crashes the main process.
    """

    @abc.abstractmethod
    def emit(self, level: str, message: str, context: dict[str, Any]) -> None:
        """
        Deliver an alert.

        level:   levelname string ("ERROR", "CRITICAL")
        message: the already-scrubbed log message
        context: {"logger": str, "run_id": str, "instance_id": str}
        """
        ...


class AlertHandler(logging.Handler):
    """
    Logging handler that fans out to registered AlertSink instances.

    The handler level (default ERROR) controls which records trigger alerts.
    A SecretScrubberFilter should be added to this handler at bootstrap time.
    """

    def __init__(self, min_level: int = logging.ERROR) -> None:
        super().__init__(level=min_level)
        self._sinks: list[AlertSink] = []

    def add_sink(self, sink: AlertSink) -> None:
        self._sinks.append(sink)

    def emit(self, record: logging.LogRecord) -> None:
        context: dict[str, Any] = {
            "logger": record.name,
            "run_id": get_run_id(),
            "instance_id": get_instance_id(),
        }
        message = record.getMessage()
        for sink in self._sinks:
            try:
                sink.emit(record.levelname, message, context)
            except Exception:
                pass


_alert_handler: AlertHandler | None = None


def _set_alert_handler(handler: AlertHandler) -> None:
    global _alert_handler
    _alert_handler = handler


def _reset_alert_handler() -> None:
    global _alert_handler
    _alert_handler = None


def register_alert_sink(sink: AlertSink) -> None:
    """Register an AlertSink with the global alert handler.

    bootstrap_logging() must be called first.
    """
    if _alert_handler is None:
        raise RuntimeError(
            "Logging not bootstrapped. "
            "Call lib.logging.bootstrap_logging() first."
        )
    _alert_handler.add_sink(sink)
