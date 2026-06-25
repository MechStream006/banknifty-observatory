from __future__ import annotations

import pytest

from lib.config._loader import _reset_settings

# All env var values used here are inert test strings — they are never
# submitted to any real API or service.
_MINIMAL_VALID_ENV: dict[str, str] = {
    "BNO_ENV": "development",
    "BNO_CONFIG_SCHEMA_VERSION": "2",
    "BNO_SMARTAPI_API_KEY": "test_api_key_value",
    "BNO_SMARTAPI_CLIENT_ID": "test_client_id",
    "BNO_SMARTAPI_PASSWORD": "test_password_value",
    "BNO_SMARTAPI_TOTP_PROVIDER": "local_seed",
    "BNO_SMARTAPI_TOTP_SECRET": "test_totp_secret_value",
    "BNO_DB_PASSWORD": "test_db_password_value",
    "BNO_TELEGRAM_BOT_TOKEN": "test_telegram_token_value",
    "BNO_TELEGRAM_CHAT_ID": "-100123456789",
    "BNO_S3_BUCKET": "test-bno-bucket",
    "BNO_CHAIN_EXPIRIES": "26JUN2026,30JUN2026",
}


@pytest.fixture(autouse=True)
def _reset_config_singleton() -> None:
    """Ensure the settings singleton is cleared between every test."""
    _reset_settings()
    yield  # type: ignore[misc]
    _reset_settings()


@pytest.fixture
def minimal_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """
    Set the minimum valid set of BNO_ environment variables and return them.

    Pass env_file=None to load_settings() when using this fixture so that
    pydantic-settings reads from the monkeypatched environment only.
    """
    for key, value in _MINIMAL_VALID_ENV.items():
        monkeypatch.setenv(key, value)
    return dict(_MINIMAL_VALID_ENV)
