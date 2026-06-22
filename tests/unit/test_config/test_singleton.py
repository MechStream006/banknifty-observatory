"""
Tests for the singleton lifecycle: initialisation, retrieval, and reset.
"""
from __future__ import annotations

import pytest

from lib.config import BNOConfigMissingError, get_settings, load_settings
from lib.config._loader import _reset_settings


class TestSingletonLifecycle:
    def test_get_settings_before_load_raises_runtime_error(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            get_settings()
        assert "load_settings" in str(exc_info.value)

    def test_load_settings_returns_settings_object(
        self, minimal_env: dict[str, str]
    ) -> None:
        from lib.config import BNOSettings

        settings = load_settings(env_file=None)
        assert isinstance(settings, BNOSettings)

    def test_get_settings_returns_same_instance_as_load(
        self, minimal_env: dict[str, str]
    ) -> None:
        loaded = load_settings(env_file=None)
        retrieved = get_settings()
        assert loaded is retrieved

    def test_get_settings_returns_same_instance_on_repeated_calls(
        self, minimal_env: dict[str, str]
    ) -> None:
        load_settings(env_file=None)
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_reset_clears_singleton(
        self, minimal_env: dict[str, str]
    ) -> None:
        load_settings(env_file=None)
        _reset_settings()
        with pytest.raises(RuntimeError):
            get_settings()

    def test_failed_load_does_not_leave_stale_singleton(
        self, minimal_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BNO_S3_BUCKET", raising=False)
        with pytest.raises(BNOConfigMissingError):
            load_settings(env_file=None)
        # Singleton must still be None after a failed load.
        with pytest.raises(RuntimeError):
            get_settings()
