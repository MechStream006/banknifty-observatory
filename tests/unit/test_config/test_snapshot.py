"""
Tests for the redacted configuration snapshot.
"""
from __future__ import annotations

import json

import pytest

from lib.config import get_redacted_snapshot, load_settings

_SECRET_VALUES = [
    "test_api_key_value",
    "test_password_value",
    "test_totp_secret_value",
    "test_db_password_value",
    "test_telegram_token_value",
]

_SECRET_FIELD_NAMES = {
    "smartapi_api_key",
    "smartapi_password",
    "smartapi_totp_secret",
    "db_password",
    "telegram_bot_token",
}


class TestSnapshotRedaction:
    def test_all_secret_fields_are_redacted(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        for field in _SECRET_FIELD_NAMES:
            assert snapshot[field] == "[REDACTED]", (
                f"Secret field {field!r} was not redacted in snapshot."
            )

    def test_secret_values_absent_from_snapshot_string(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        snapshot_str = str(snapshot)
        for secret in _SECRET_VALUES:
            assert secret not in snapshot_str, (
                f"Secret value {secret!r} found in snapshot string representation."
            )

    def test_optional_secret_none_is_not_redacted(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BNO_SMARTAPI_TOTP_PROVIDER", "authenticator_app")
        monkeypatch.delenv("BNO_SMARTAPI_TOTP_SECRET", raising=False)
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        # None means "not configured" — distinct from "[REDACTED]" (configured but hidden).
        assert snapshot["smartapi_totp_secret"] is None


class TestSnapshotContent:
    def test_non_secret_fields_are_present_with_actual_values(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        assert snapshot["env"] == "development"
        assert snapshot["config_schema_version"] == 2
        assert snapshot["instrument_symbol"] == "BANKNIFTY"
        assert snapshot["timezone"] == "Asia/Kolkata"
        assert snapshot["strategy_active"] is False
        assert snapshot["labeling_active"] is False

    def test_snapshot_includes_all_fields(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        for field_name in settings.model_fields:
            assert field_name in snapshot, (
                f"Field {field_name!r} is missing from snapshot."
            )

    def test_snapshot_has_metadata_keys(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        assert "_snapshot_type" in snapshot
        assert "_snapshot_at" in snapshot
        assert snapshot["_snapshot_type"] == "bno_config_snapshot_v1"

    def test_snapshot_at_is_iso_string(
        self, minimal_env: dict[str, str]
    ) -> None:
        import datetime

        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        # Should parse as a valid ISO 8601 datetime.
        dt = datetime.datetime.fromisoformat(snapshot["_snapshot_at"])
        assert dt.tzinfo is not None  # timezone-aware

    def test_horizon_grid_is_list_of_ints(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        grid = snapshot["opportunity_horizon_grid_ms"]
        assert isinstance(grid, list)
        assert all(isinstance(x, int) for x in grid)


class TestSnapshotSerialisation:
    def test_snapshot_is_json_serialisable(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot = get_redacted_snapshot(settings)
        serialised = json.dumps(snapshot)
        parsed = json.loads(serialised)
        assert parsed["env"] == "development"
        assert parsed["smartapi_api_key"] == "[REDACTED]"

    def test_snapshot_round_trips_cleanly(
        self, minimal_env: dict[str, str]
    ) -> None:
        settings = load_settings(env_file=None)
        snapshot1 = get_redacted_snapshot(settings)
        snapshot2 = get_redacted_snapshot(settings)
        # Two calls on the same settings object must produce identical content
        # (except _snapshot_at which changes per call — exclude it).
        for key in snapshot1:
            if key == "_snapshot_at":
                continue
            assert snapshot1[key] == snapshot2[key]
