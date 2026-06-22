from __future__ import annotations

import datetime
import json
import logging

from lib.logging._constants import BNO_LOGGER_ROOT, LOG_SCHEMA_VERSION
from lib.logging._context import get_instance_id, get_run_id


def _service_from_name(logger_name: str) -> str:
    """Extract the top-level service label from a dotted logger name.

    "bno.acquisition.session" -> "acquisition"
    "bno.derivation"          -> "derivation"
    "bno"                     -> "bno"
    "third_party.lib"         -> "third_party"
    """
    parts = logger_name.split(".")
    if len(parts) >= 2 and parts[0] == BNO_LOGGER_ROOT:
        return parts[1]
    return parts[0]


class BNOJsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON (NDJSON).

    Always-present fields:
        schema, ts (UTC ISO 8601), level, logger, service,
        run_id, instance_id, msg

    Conditional fields:
        exc  — exception traceback string (omitted when no exception)
        data — extra structured context (omitted when caller omits it)

    The SecretScrubberFilter is expected to have run before this formatter,
    so record.msg is already rendered and record.args is None.
    """

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "schema": LOG_SCHEMA_VERSION,
            "ts": datetime.datetime.fromtimestamp(
                record.created, tz=datetime.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": _service_from_name(record.name),
            "run_id": get_run_id(),
            "instance_id": get_instance_id(),
            "msg": record.getMessage(),
        }

        data = getattr(record, "data", None)
        if data is not None:
            event["data"] = data

        if record.exc_text:
            event["exc"] = record.exc_text
        elif record.exc_info and record.exc_info[0] is not None:
            event["exc"] = self.formatException(record.exc_info)

        return json.dumps(event, default=str)
