from __future__ import annotations

import logging

from lib.logging._constants import BNO_LOGGER_ROOT


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given dotted service/module name.

    All BNO loggers share the "bno" root namespace so that bootstrap_logging()
    can configure them collectively while still supporting per-service file
    handlers via configure_service_log().

    Examples:
        get_logger("acquisition.session")  -> logging.getLogger("bno.acquisition.session")
        get_logger("derivation.iv")        -> logging.getLogger("bno.derivation.iv")
        get_logger("research.labeling")    -> logging.getLogger("bno.research.labeling")
    """
    return logging.getLogger(f"{BNO_LOGGER_ROOT}.{name}")
