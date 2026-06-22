from __future__ import annotations

from lib.logging._alert_sink import AlertSink, register_alert_sink
from lib.logging._bootstrap import bootstrap_logging, configure_service_log
from lib.logging._context import get_context_snapshot, get_instance_id, get_run_id
from lib.logging._factory import get_logger

__all__ = [
    "bootstrap_logging",
    "configure_service_log",
    "get_logger",
    "get_run_id",
    "get_instance_id",
    "get_context_snapshot",
    "AlertSink",
    "register_alert_sink",
]
