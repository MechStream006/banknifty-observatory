"""Tests for bootstrap_logging() and configure_service_log()."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import pytest

from lib.logging._bootstrap import bootstrap_logging, configure_service_log
from lib.logging._constants import BNO_LOGGER_ROOT
from lib.logging._context import get_instance_id, get_run_id
from lib.logging._factory import get_logger


class TestBootstrapLifecycle:
    def test_returns_run_id_string(self, settings: object, tmp_path: Path) -> None:
        run_id = bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        assert isinstance(run_id, str) and len(run_id) > 0

    def test_returned_run_id_is_valid_uuid(self, settings: object, tmp_path: Path) -> None:
        run_id = bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        uuid.UUID(run_id)  # raises ValueError if invalid

    def test_custom_run_id_is_honoured(self, settings: object, tmp_path: Path) -> None:
        run_id = bootstrap_logging(
            settings=settings, log_dir=str(tmp_path), run_id="fixed-run-id"
        )
        assert run_id == "fixed-run-id"
        assert get_run_id() == "fixed-run-id"

    def test_custom_instance_id_is_honoured(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(
            settings=settings, log_dir=str(tmp_path), instance_id="ec2-prod-01"
        )
        assert get_instance_id() == "ec2-prod-01"

    def test_creates_log_directory(self, settings: object, tmp_path: Path) -> None:
        log_dir = tmp_path / "nested" / "bno"
        bootstrap_logging(settings=settings, log_dir=str(log_dir))
        assert log_dir.exists()

    def test_creates_combined_bno_log_file(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        assert (tmp_path / "bno.log").exists()

    def test_second_call_does_not_accumulate_file_handlers(
        self, settings: object, tmp_path: Path
    ) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        bno_logger = logging.getLogger(BNO_LOGGER_ROOT)
        file_handlers = [
            h for h in bno_logger.handlers
            if isinstance(h, logging.handlers.WatchedFileHandler)
        ]
        assert len(file_handlers) == 1


class TestJsonOutput:
    def test_log_records_written_as_json(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        get_logger("test").info("hello from test")
        lines = (tmp_path / "bno.log").read_text().strip().splitlines()
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["msg"] == "hello from test"

    def test_run_id_present_in_log_output(self, settings: object, tmp_path: Path) -> None:
        run_id = bootstrap_logging(
            settings=settings, log_dir=str(tmp_path), run_id="log-run-id"
        )
        get_logger("test").info("run id check")
        content = (tmp_path / "bno.log").read_text()
        parsed = json.loads(content.strip().splitlines()[-1])
        assert parsed["run_id"] == run_id

    def test_instance_id_present_in_log_output(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(
            settings=settings, log_dir=str(tmp_path), instance_id="my-instance"
        )
        get_logger("test").info("instance check")
        content = (tmp_path / "bno.log").read_text()
        parsed = json.loads(content.strip().splitlines()[-1])
        assert parsed["instance_id"] == "my-instance"


class TestSecretScrubbing:
    def test_api_key_not_in_log_output(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        get_logger("test").info("key is test_api_key_value")
        content = (tmp_path / "bno.log").read_text()
        assert "test_api_key_value" not in content

    def test_db_password_not_in_log_output(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        get_logger("test").info("pw=%s", "test_db_password_value")
        content = (tmp_path / "bno.log").read_text()
        assert "test_db_password_value" not in content

    def test_telegram_token_not_in_log_output(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        get_logger("test").warning("token=test_telegram_token_value")
        content = (tmp_path / "bno.log").read_text()
        assert "test_telegram_token_value" not in content


class TestConfigureServiceLog:
    def test_service_log_file_created(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        configure_service_log("acquisition", log_dir=str(tmp_path))
        assert (tmp_path / "acquisition.log").exists()

    def test_service_record_in_service_log(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        configure_service_log("acquisition", log_dir=str(tmp_path))
        get_logger("acquisition.session").info("acquisition started")
        content = (tmp_path / "acquisition.log").read_text().strip()
        parsed = json.loads(content.splitlines()[-1])
        assert "acquisition started" in parsed["msg"]

    def test_service_record_also_in_combined_log(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        configure_service_log("acquisition", log_dir=str(tmp_path))
        get_logger("acquisition.session").info("combined check")
        combined = (tmp_path / "bno.log").read_text()
        assert "combined check" in combined

    def test_non_service_record_not_in_service_log(
        self, settings: object, tmp_path: Path
    ) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        configure_service_log("acquisition", log_dir=str(tmp_path))
        get_logger("derivation.iv").info("iv computed")
        content = (tmp_path / "acquisition.log").read_text()
        assert "iv computed" not in content

    def test_configure_before_bootstrap_raises(
        self, settings: object, tmp_path: Path
    ) -> None:
        with pytest.raises(RuntimeError, match="bootstrap_logging"):
            configure_service_log("acquisition", log_dir=str(tmp_path))

    def test_service_log_secrets_redacted(self, settings: object, tmp_path: Path) -> None:
        bootstrap_logging(settings=settings, log_dir=str(tmp_path))
        configure_service_log("acquisition", log_dir=str(tmp_path))
        get_logger("acquisition.session").info("key=test_api_key_value")
        content = (tmp_path / "acquisition.log").read_text()
        assert "test_api_key_value" not in content
