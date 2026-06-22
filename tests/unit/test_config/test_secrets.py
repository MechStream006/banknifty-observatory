"""
Tests that secret values are never exposed in repr, str, or error messages.

Secret fields: smartapi_api_key, smartapi_password, smartapi_totp_secret,
               db_password, telegram_bot_token.
"""
from __future__ import annotations

import pytest

from lib.config import load_settings
from lib.config._errors import BNOConfigError

# The test values used in conftest.minimal_env.
# Any of these appearing outside get_secret_value() is a test failure.
_SECRET_VALUES = [
    "test_api_key_value",
    "test_password_value",
    "test_totp_secret_value",
    "test_db_password_value",
    "test_telegram_token_value",
]


class TestSettingsRepr:
    def test_secret_values_absent_from_repr(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        output = repr(settings)
        for secret in _SECRET_VALUES:
            assert secret not in output, (
                f"Secret value {secret!r} found in settings repr. "
                f"This is a security violation."
            )

    def test_secret_values_absent_from_str(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        output = str(settings)
        for secret in _SECRET_VALUES:
            assert secret not in output, (
                f"Secret value {secret!r} found in str(settings). "
                f"This is a security violation."
            )

    def test_secret_fields_accessible_via_get_secret_value(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        # The runtime must be able to retrieve the actual value when needed.
        assert settings.smartapi_api_key.get_secret_value() == "test_api_key_value"
        assert settings.smartapi_password.get_secret_value() == "test_password_value"
        assert settings.db_password.get_secret_value() == "test_db_password_value"
        assert (
            settings.telegram_bot_token.get_secret_value()
            == "test_telegram_token_value"
        )


class TestErrorMessages:
    def test_type_error_message_excludes_raw_value(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Use a distinctive string as the bad value for a non-secret field.
        bad_value = "CANARY_VALUE_SHOULD_NOT_APPEAR"
        monkeypatch.setenv("BNO_DB_PORT", bad_value)
        with pytest.raises(BNOConfigError) as exc_info:
            load_settings(env_file=None)
        assert bad_value not in str(exc_info.value)

    def test_missing_key_error_does_not_leak_other_secret_values(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BNO_S3_BUCKET", raising=False)
        with pytest.raises(BNOConfigError) as exc_info:
            load_settings(env_file=None)
        error_text = str(exc_info.value)
        for secret in _SECRET_VALUES:
            assert secret not in error_text, (
                f"Secret value {secret!r} leaked into error message."
            )

    def test_validation_error_message_excludes_secret_values(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_STRATEGY_ACTIVE", "true")
        with pytest.raises(BNOConfigError) as exc_info:
            load_settings(env_file=None)
        error_text = str(exc_info.value)
        for secret in _SECRET_VALUES:
            assert secret not in error_text


class TestSecretFieldIdentity:
    def test_optional_totp_secret_is_none_when_not_local_seed(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_SMARTAPI_TOTP_PROVIDER", "authenticator_app")
        monkeypatch.delenv("BNO_SMARTAPI_TOTP_SECRET", raising=False)
        settings = load_settings(env_file=None)
        assert settings.smartapi_totp_secret is None

    def test_totp_secret_is_secret_str_when_provided(
        self, minimal_env: dict[str, str]
    ) -> None:
        from pydantic import SecretStr

        settings = load_settings(env_file=None)
        assert isinstance(settings.smartapi_totp_secret, SecretStr)
