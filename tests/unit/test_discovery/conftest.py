"""Shared fixtures for discovery subsystem tests.

At M4A-1 only foundation fixtures are available. Fixtures that depend on
later components (tmp_db → SQLiteAnalysisStore, mock_session → SmartAPISession)
are added in their respective milestones.
"""
from __future__ import annotations

import json
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib.config import load_settings
from lib.config._loader import _reset_settings
from lib.logging._bootstrap import _reset_logging

from lib.discovery._models import ChainResult


@pytest.fixture(autouse=True)
def _reset_singletons() -> Generator[None, None, None]:
    """Reset config and logging singletons before and after every test."""
    _reset_settings()
    _reset_logging()
    yield
    _reset_settings()
    _reset_logging()


@pytest.fixture
def minimal_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Minimum valid BNO_ environment for discovery tests."""
    env: dict[str, str] = {
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
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def settings(minimal_env: dict[str, str]):  # type: ignore[no-untyped-def]
    """Validated BNOSettings instance built from minimal_env."""
    return load_settings(env_file=None)


@pytest.fixture
def chain_fixture() -> ChainResult:
    """ChainResult built from the synthetic fixture file.

    Represents a successful Phase 1 poll: 20 option rows across 2 expiries,
    5 strikes per expiry, CE + PE per strike. Updated after Phase 0 if the
    real API response diverges from this synthetic shape.
    """
    fixture_path = (
        Path(__file__).parents[2] / "fixtures" / "chain_response_fixture.json"
    )
    raw: dict[str, object] = json.loads(fixture_path.read_text(encoding="utf-8"))

    fetched_rows: list[object] = []
    data = raw.get("data")
    if isinstance(data, dict):
        rows = data.get("fetched")
        if isinstance(rows, list):
            fetched_rows = rows
        unfetched = data.get("unfetched")
        unfetched_count = len(unfetched) if isinstance(unfetched, list) else 0
    else:
        unfetched_count = 0

    expiry_dates: set[str] = set()
    for row in fetched_rows:
        if isinstance(row, dict):
            expiry = row.get("expiryDate")
            if isinstance(expiry, str):
                expiry_dates.add(expiry)

    payload = json.dumps(raw).encode()

    return ChainResult(
        fetched_at=datetime.now(tz=timezone.utc),
        latency_ms=45.0,
        http_status=200,
        response_bytes=len(payload),
        raw_response=raw,
        row_count=len(fetched_rows),
        expiry_count=len(expiry_dates),
        unfetched_count=unfetched_count,
        error=None,
        success=True,
    )
