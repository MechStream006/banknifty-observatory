from __future__ import annotations

import logging
import logging.handlers
import socket
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from lib.logging._alert_sink import (
    AlertHandler,
    _reset_alert_handler,
    _set_alert_handler,
)
from lib.logging._constants import BNO_LOGGER_ROOT, DEFAULT_LOG_DIR, LOG_FILE_ENCODING
from lib.logging._context import _init_context, _reset_context
from lib.logging._formatter import BNOJsonFormatter
from lib.logging._scrubber import SecretScrubberFilter

if TYPE_CHECKING:
    from lib.config._settings import BNOSettings

_scrubber: SecretScrubberFilter | None = None


def bootstrap_logging(
    *,
    settings: "BNOSettings",
    log_dir: str | None = None,
    run_id: str | None = None,
    instance_id: str | None = None,
) -> str:
    """Initialise the BNO logging framework.

    Must be called once at process startup, after load_settings().
    Calling twice replaces handlers rather than accumulating them (safe for tests).

    Args:
        settings:    Loaded BNOSettings — used for log_level, alert_min_level,
                     and secret extraction for the scrubber.
        log_dir:     Directory for log files. Defaults to /var/log/bno.
                     Created if it does not exist.
        run_id:      Override the auto-generated UUID4 run identifier.
                     Useful for test determinism or resuming a known session.
        instance_id: Override the default of socket.gethostname().
                     Embed an EC2 instance tag or deployment label here.

    Returns:
        run_id: UUID string for this process run. Embed in all lineage records
                via get_context_snapshot().
    """
    global _scrubber

    effective_run_id = run_id or str(uuid.uuid4())
    effective_instance_id = instance_id or socket.gethostname()
    _init_context(run_id=effective_run_id, instance_id=effective_instance_id)

    effective_log_dir = Path(log_dir or DEFAULT_LOG_DIR)
    effective_log_dir.mkdir(parents=True, exist_ok=True)

    # Extract all SecretStr values from settings for the scrubber.
    # This is the only place get_secret_value() is called by the framework.
    from pydantic import SecretStr

    secrets: set[str] = set()
    for field_name in settings.model_fields:
        value = getattr(settings, field_name)
        if isinstance(value, SecretStr):
            secrets.add(value.get_secret_value())
    _scrubber = SecretScrubberFilter(frozenset(secrets))

    # Remove any handlers from a prior bootstrap call.
    bno_logger = logging.getLogger(BNO_LOGGER_ROOT)
    for h in bno_logger.handlers[:]:
        bno_logger.removeHandler(h)
        h.close()
    bno_logger.setLevel(settings.log_level)
    bno_logger.propagate = False

    # Combined log: all BNO services in one file for correlation and incident search.
    combined_handler = _make_watched_handler(
        effective_log_dir / "bno.log", _scrubber
    )
    bno_logger.addHandler(combined_handler)

    # Alert handler: fans out to registered AlertSink instances at/above threshold.
    alert_handler = AlertHandler(
        min_level=getattr(logging, settings.alert_min_level, logging.ERROR)
    )
    alert_handler.addFilter(_scrubber)
    bno_logger.addHandler(alert_handler)
    _set_alert_handler(alert_handler)

    return effective_run_id


def configure_service_log(service_name: str, log_dir: str | None = None) -> None:
    """Add a per-service log file for bno.<service_name>.

    Records from this service subtree appear in both the service log and
    bno.log (via propagation). The service log contains only records from
    this subtree, enabling per-service rotation and retention policies.

    Must be called after bootstrap_logging().

    Example:
        configure_service_log("acquisition")
        -> writes bno.acquisition.* records to acquisition.log
    """
    if _scrubber is None:
        raise RuntimeError(
            "Logging not bootstrapped. "
            "Call lib.logging.bootstrap_logging() first."
        )

    effective_log_dir = Path(log_dir or DEFAULT_LOG_DIR)
    service_logger = logging.getLogger(f"{BNO_LOGGER_ROOT}.{service_name}")

    # Remove an existing service-level file handler if reconfiguring.
    for h in service_logger.handlers[:]:
        if isinstance(h, logging.handlers.WatchedFileHandler):
            service_logger.removeHandler(h)
            h.close()

    handler = _make_watched_handler(
        effective_log_dir / f"{service_name}.log", _scrubber
    )
    service_logger.addHandler(handler)
    # propagate=True (default): records also flow to bno logger -> bno.log


def _reset_logging() -> None:
    """Reset all logging state. For tests only — not part of the public API."""
    global _scrubber
    bno_logger = logging.getLogger(BNO_LOGGER_ROOT)
    for h in bno_logger.handlers[:]:
        bno_logger.removeHandler(h)
        h.close()
    # Also clear handlers from any service child loggers.
    for name, logger in logging.Logger.manager.loggerDict.items():
        if name.startswith(f"{BNO_LOGGER_ROOT}.") and isinstance(logger, logging.Logger):
            for h in logger.handlers[:]:
                logger.removeHandler(h)
                h.close()
    _scrubber = None
    _reset_alert_handler()
    _reset_context()


def _make_watched_handler(
    path: Path, scrubber: SecretScrubberFilter
) -> logging.handlers.WatchedFileHandler:
    handler = logging.handlers.WatchedFileHandler(path, encoding=LOG_FILE_ENCODING)
    handler.setFormatter(BNOJsonFormatter())
    handler.addFilter(scrubber)
    return handler
