"""
Tests for configuration validation: missing keys, type errors,
schema-version checks, and cross-field governance rules.
"""
from __future__ import annotations

import pytest

from lib.config import (
    BNOConfigMissingError,
    BNOConfigTypeError,
    BNOConfigValidationError,
    BNOConfigVersionError,
    load_settings,
)


class TestRequiredKeys:
    """Every required key, when absent, must produce BNOConfigMissingError
    with the correct key name."""

    REQUIRED_KEYS = [
        "BNO_ENV",
        "BNO_CONFIG_SCHEMA_VERSION",
        "BNO_SMARTAPI_API_KEY",
        "BNO_SMARTAPI_CLIENT_ID",
        "BNO_SMARTAPI_PASSWORD",
        "BNO_SMARTAPI_TOTP_SECRET",
        "BNO_DB_PASSWORD",
        "BNO_TELEGRAM_BOT_TOKEN",
        "BNO_TELEGRAM_CHAT_ID",
        "BNO_S3_BUCKET",
        "BNO_CHAIN_EXPIRIES",
    ]

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_missing_required_key_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, key: str
    ) -> None:
        monkeypatch.delenv(key, raising=False)
        with pytest.raises(BNOConfigMissingError) as exc_info:
            load_settings(env_file=None)
        assert exc_info.value.key == key

    def test_all_required_keys_present_loads_successfully(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        assert settings.env == "development"
        assert settings.config_schema_version == 2


class TestTypeErrors:
    """Invalid values for typed fields must produce BNOConfigTypeError."""

    def test_non_integer_schema_version(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CONFIG_SCHEMA_VERSION", "not_an_integer")
        with pytest.raises(BNOConfigTypeError) as exc_info:
            load_settings(env_file=None)
        assert "CONFIG_SCHEMA_VERSION" in exc_info.value.key

    def test_non_integer_db_port(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_DB_PORT", "not_a_port")
        with pytest.raises(BNOConfigTypeError) as exc_info:
            load_settings(env_file=None)
        assert "DB_PORT" in exc_info.value.key

    def test_invalid_bool_for_strategy_active(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_STRATEGY_ACTIVE", "maybe")
        with pytest.raises((BNOConfigTypeError, BNOConfigValidationError)):
            load_settings(env_file=None)

    def test_invalid_log_level(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_LOG_LEVEL", "VERBOSE")
        with pytest.raises(BNOConfigTypeError) as exc_info:
            load_settings(env_file=None)
        assert "LOG_LEVEL" in exc_info.value.key

    def test_invalid_alert_min_level(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_ALERT_MIN_LEVEL", "SILENT")
        with pytest.raises(BNOConfigTypeError) as exc_info:
            load_settings(env_file=None)
        assert "ALERT_MIN_LEVEL" in exc_info.value.key

    def test_type_error_message_does_not_contain_raw_value(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_DB_PORT", "secret_looking_string_12345")
        with pytest.raises(BNOConfigTypeError) as exc_info:
            load_settings(env_file=None)
        assert "secret_looking_string_12345" not in str(exc_info.value)


class TestSchemaVersion:
    def test_wrong_version_raises_version_error(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CONFIG_SCHEMA_VERSION", "99")
        with pytest.raises(BNOConfigVersionError) as exc_info:
            load_settings(env_file=None)
        assert exc_info.value.found == 99
        assert exc_info.value.expected == 2

    def test_correct_version_passes(self, minimal_env: dict[str, str]) -> None:
        settings = load_settings(env_file=None)
        assert settings.config_schema_version == 2

    def test_version_error_message_states_both_versions(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CONFIG_SCHEMA_VERSION", "5")
        with pytest.raises(BNOConfigVersionError) as exc_info:
            load_settings(env_file=None)
        message = str(exc_info.value)
        assert "5" in message
        assert "2" in message


class TestEnvironmentValidation:
    def test_valid_environments_accepted(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for env_name in ("development", "staging"):
            _reset_for_env(monkeypatch, minimal_env, env_name)
            settings = load_settings(env_file=None)
            assert settings.env == env_name
            from lib.config._loader import _reset_settings
            _reset_settings()

    def test_unknown_environment_raises_type_error(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_ENV", "dev")
        from lib.config._errors import BNOConfigEnvironmentError
        with pytest.raises((BNOConfigEnvironmentError, BNOConfigTypeError)):
            load_settings(env_file=None)


class TestCrossFieldRules:
    """Governance-level cross-field validations."""

    def test_production_allows_local_seed_totp(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # local_seed is the only implemented TOTP provider. Production must
        # accept it; blocking it while secrets_manager is unimplemented would
        # make the service undeployable.
        monkeypatch.setenv("BNO_ENV", "production")
        monkeypatch.setenv("BNO_SMARTAPI_TOTP_PROVIDER", "local_seed")
        settings = load_settings(env_file=None)
        assert settings.env == "production"
        assert settings.smartapi_totp_provider == "local_seed"

    def test_local_seed_without_totp_secret_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_SMARTAPI_TOTP_PROVIDER", "local_seed")
        monkeypatch.delenv("BNO_SMARTAPI_TOTP_SECRET", raising=False)
        with pytest.raises((BNOConfigMissingError, BNOConfigValidationError)):
            load_settings(env_file=None)

    def test_labeling_active_without_cost_model_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_LABELING_ACTIVE", "true")
        monkeypatch.delenv("BNO_COST_MODEL_VERSION", raising=False)
        with pytest.raises(BNOConfigValidationError) as exc_info:
            load_settings(env_file=None)
        message = str(exc_info.value).lower()
        assert "cost_model_version" in message or "cost model" in message

    def test_labeling_active_with_cost_model_passes(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_LABELING_ACTIVE", "true")
        monkeypatch.setenv("BNO_COST_MODEL_VERSION", "1")
        settings = load_settings(env_file=None)
        assert settings.labeling_active is True
        assert settings.cost_model_version == "1"

    def test_strategy_active_always_rejected(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_STRATEGY_ACTIVE", "true")
        with pytest.raises(BNOConfigValidationError) as exc_info:
            load_settings(env_file=None)
        assert "stage" in str(exc_info.value).lower()

    def test_strategy_inactive_by_default(self, minimal_env: dict[str, str]) -> None:
        settings = load_settings(env_file=None)
        assert settings.strategy_active is False
        assert settings.labeling_active is False


class TestHorizonGridParsing:
    def test_parses_comma_separated_string(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_OPPORTUNITY_HORIZON_GRID_MS", "60000,300000,900000")
        settings = load_settings(env_file=None)
        assert settings.opportunity_horizon_grid_ms == [60_000, 300_000, 900_000]

    def test_parses_string_with_spaces(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_OPPORTUNITY_HORIZON_GRID_MS", "60000, 300000, 900000")
        settings = load_settings(env_file=None)
        assert settings.opportunity_horizon_grid_ms == [60_000, 300_000, 900_000]

    def test_default_horizon_grid_is_all_integers(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        assert isinstance(settings.opportunity_horizon_grid_ms, list)
        assert all(isinstance(x, int) for x in settings.opportunity_horizon_grid_ms)
        assert len(settings.opportunity_horizon_grid_ms) >= 1


class TestChainExpiriesValidation:
    """BNO_CHAIN_EXPIRIES parsing, normalisation, and format validation.

    Both formats are accepted:
        BNO_CHAIN_EXPIRIES=26JUN2026,30JUN2026         (documented CSV format)
        BNO_CHAIN_EXPIRIES=["26JUN2026","30JUN2026"]   (JSON array, also valid)
    """

    def test_single_expiry_parses_to_list(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26JUN2026"]')
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026"]

    def test_two_expiries_parse_to_list(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26JUN2026","30JUN2026"]')
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026", "30JUN2026"]

    def test_three_expiries_parse_to_list(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26JUN2026","30JUN2026","31JUL2026"]')
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026", "30JUN2026", "31JUL2026"]

    def test_whitespace_stripped_within_entries(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # JSON-decoded elements that contain surrounding whitespace are trimmed.
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '[" 26JUN2026 "," 30JUN2026 "]')
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026", "30JUN2026"]

    def test_lowercase_entries_uppercased(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26jun2026"]')
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026"]

    def test_mixed_case_entries_uppercased(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26Jun2026"]')
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026"]

    def test_result_is_list_of_strings(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26JUN2026","30JUN2026"]')
        settings = load_settings(env_file=None)
        assert isinstance(settings.chain_expiries, list)
        assert all(isinstance(e, str) for e in settings.chain_expiries)

    def test_order_preserved(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["30JUN2026","26JUN2026"]')
        settings = load_settings(env_file=None)
        assert settings.chain_expiries[0] == "30JUN2026"
        assert settings.chain_expiries[1] == "26JUN2026"

    def test_all_twelve_month_abbreviations_accepted(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json
        months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        expiries = [f"26{m}2026" for m in months]
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", json.dumps(expiries))
        settings = load_settings(env_file=None)
        assert len(settings.chain_expiries) == 12

    def test_csv_format_parses_correctly(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", "26JUN2026,30JUN2026")
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026", "30JUN2026"]

    def test_empty_json_array_raises_validation_error(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", "[]")
        with pytest.raises(BNOConfigValidationError):
            load_settings(env_file=None)

    def test_iso_date_format_entry_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["2026-06-26"]')
        with pytest.raises(BNOConfigValidationError):
            load_settings(env_file=None)

    def test_invalid_month_abbreviation_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26XYZ2026"]')
        with pytest.raises(BNOConfigValidationError):
            load_settings(env_file=None)

    def test_single_digit_day_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["6JUN2026"]')
        with pytest.raises(BNOConfigValidationError):
            load_settings(env_file=None)

    def test_two_digit_year_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26JUN26"]')
        with pytest.raises(BNOConfigValidationError):
            load_settings(env_file=None)

    def test_one_valid_one_invalid_entry_raises(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_EXPIRIES", '["26JUN2026","INVALID"]')
        with pytest.raises(BNOConfigValidationError):
            load_settings(env_file=None)

    def test_minimal_env_default_expiries_loaded(
        self, minimal_env: dict[str, str]
    ) -> None:
        # Validates that the conftest minimal env sets chain_expiries correctly.
        settings = load_settings(env_file=None)
        assert settings.chain_expiries == ["26JUN2026", "30JUN2026"]


class TestChainWindowSteps:
    """BNO_CHAIN_WINDOW_STEPS — optional int, default 15."""

    def test_default_is_15(self, minimal_env: dict[str, str]) -> None:
        settings = load_settings(env_file=None)
        assert settings.chain_window_steps == 15

    def test_custom_value_stored(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_WINDOW_STEPS", "20")
        settings = load_settings(env_file=None)
        assert settings.chain_window_steps == 20

    def test_zero_accepted(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_WINDOW_STEPS", "0")
        settings = load_settings(env_file=None)
        assert settings.chain_window_steps == 0

    def test_non_integer_raises_type_error(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_WINDOW_STEPS", "fifteen")
        with pytest.raises(BNOConfigTypeError) as exc_info:
            load_settings(env_file=None)
        assert "CHAIN_WINDOW_STEPS" in exc_info.value.key


class TestChainStepSize:
    """BNO_CHAIN_STEP_SIZE — optional int, default 500."""

    def test_default_is_500(self, minimal_env: dict[str, str]) -> None:
        settings = load_settings(env_file=None)
        assert settings.chain_step_size == 500

    def test_custom_value_stored(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_STEP_SIZE", "100")
        settings = load_settings(env_file=None)
        assert settings.chain_step_size == 100

    def test_non_integer_raises_type_error(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_CHAIN_STEP_SIZE", "hundred")
        with pytest.raises(BNOConfigTypeError) as exc_info:
            load_settings(env_file=None)
        assert "CHAIN_STEP_SIZE" in exc_info.value.key


def _reset_for_env(
    monkeypatch: pytest.MonkeyPatch, base_env: dict[str, str], env_name: str
) -> None:
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BNO_ENV", env_name)
    if env_name == "staging":
        monkeypatch.setenv("BNO_SMARTAPI_TOTP_PROVIDER", "authenticator_app")
