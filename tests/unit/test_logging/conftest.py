"""Shared fixtures for logging subsystem tests."""
from __future__ import annotations

from collections.abc import Generator

import pytest

from lib.config import load_settings
from lib.config._loader import _reset_settings
from lib.logging._bootstrap import _reset_logging


@pytest.fixture(autouse=True)
def _reset_all_singletons() -> Generator[None, None, None]:
    """Reset config and logging singletons before and after every test."""
    _reset_settings()
    _reset_logging()
    yield
    _reset_settings()
    _reset_logging()


@pytest.fixture
def minimal_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    env = {
        "BNO_ENV": "development",
        "BNO_CONFIG_SCHEMA_VERSION": "1",
        "BNO_SMARTAPI_API_KEY": "test_api_key_value",
        "BNO_SMARTAPI_CLIENT_ID": "test_client_id",
        "BNO_SMARTAPI_PASSWORD": "test_password_value",
        "BNO_SMARTAPI_TOTP_PROVIDER": "local_seed",
        "BNO_SMARTAPI_TOTP_SECRET": "test_totp_secret_value",
        "BNO_DB_PASSWORD": "test_db_password_value",
        "BNO_TELEGRAM_BOT_TOKEN": "test_telegram_token_value",
        "BNO_TELEGRAM_CHAT_ID": "test_chat_id",
        "BNO_S3_BUCKET": "test-bno-bucket",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def settings(minimal_env: dict[str, str]):
    return load_settings(env_file=None)
