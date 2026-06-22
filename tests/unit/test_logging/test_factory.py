"""Tests for get_logger() factory."""
from __future__ import annotations

import logging

from lib.logging._constants import BNO_LOGGER_ROOT
from lib.logging._factory import get_logger


class TestGetLogger:
    def test_returns_logging_logger_instance(self) -> None:
        assert isinstance(get_logger("acquisition.session"), logging.Logger)

    def test_logger_name_has_bno_prefix(self) -> None:
        logger = get_logger("derivation.iv")
        assert logger.name == f"{BNO_LOGGER_ROOT}.derivation.iv"

    def test_service_only_name(self) -> None:
        logger = get_logger("acquisition")
        assert logger.name == f"{BNO_LOGGER_ROOT}.acquisition"

    def test_same_name_returns_same_instance(self) -> None:
        a = get_logger("persistence.raw")
        b = get_logger("persistence.raw")
        assert a is b

    def test_different_names_return_different_loggers(self) -> None:
        a = get_logger("acquisition")
        b = get_logger("derivation")
        assert a is not b

    def test_logger_is_child_of_bno_root(self) -> None:
        logger = get_logger("research.labeling")
        assert logger.name.startswith(f"{BNO_LOGGER_ROOT}.")

    def test_deep_dotted_name(self) -> None:
        logger = get_logger("derivation.methodologies.iv")
        assert logger.name == f"{BNO_LOGGER_ROOT}.derivation.methodologies.iv"
