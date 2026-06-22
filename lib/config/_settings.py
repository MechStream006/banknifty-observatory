from __future__ import annotations

import re
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from lib.config._constants import EXPECTED_CONFIG_SCHEMA_VERSION
from lib.config._errors import (
    BNOConfigValidationError,
    BNOConfigVersionError,
)


class BNOSettings(BaseSettings):
    """
    Single source of truth for all platform configuration.

    Reads BNO_-prefixed environment variables (case-insensitive).
    Field names are the env var name with BNO_ stripped and lowercased.

    Access ONLY via lib.config.get_settings() — never via os.environ directly.
    SecretStr fields are never written to logs, repr, or snapshots.
    """

    model_config = SettingsConfigDict(
        env_prefix="BNO_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── [INFRA] ───────────────────────────────────────────────────────────────
    env: Literal["development", "staging", "production"]
    config_schema_version: int
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    data_dir: str = "/srv/bno/data"
    buffer_dir: str = "/srv/bno/data/buffer"
    s3_bucket: str
    s3_region: str = "ap-south-1"
    s3_prefix: str = "raw/"

    # ── [SMARTAPI] ────────────────────────────────────────────────────────────
    smartapi_api_key: SecretStr
    smartapi_client_id: str
    smartapi_password: SecretStr
    smartapi_totp_provider: Literal[
        "local_seed", "authenticator_app", "secrets_manager"
    ] = "local_seed"
    # Required only when totp_provider == "local_seed"; cross-validated below.
    smartapi_totp_secret: SecretStr | None = None
    smartapi_token_refresh_buffer_minutes: int = 10

    # ── [DATABASE] ────────────────────────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "bno"
    db_user: str = "bno_app"
    db_password: SecretStr
    db_pool_max: int = 10
    db_pool_min: int = 2

    # ── [NOTIFY] ──────────────────────────────────────────────────────────────
    telegram_bot_token: SecretStr
    telegram_chat_id: str
    alert_min_level: Literal[
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    ] = "ERROR"
    alert_throttle_seconds: int = 60

    # ── [MARKET] ──────────────────────────────────────────────────────────────
    instrument_symbol: str = "BANKNIFTY"
    chain_poll_interval_s: int = 5
    session_open_time: str = "09:15"
    session_close_time: str = "15:30"
    session_close_buffer_min: int = 15
    timezone: str = "Asia/Kolkata"

    # ── [CHAIN] ───────────────────────────────────────────────────────────────
    # BNO_CHAIN_EXPIRIES: comma-separated expiry list in DDMMMYYYY format.
    # Required — no default because expiries roll monthly and cannot be
    # hard-coded. Example: "26JUN2026,30JUN2026"
    chain_expiries: list[str]
    chain_window_steps: int = 15
    chain_step_size: int = 500

    # ── [RESEARCH] ────────────────────────────────────────────────────────────
    cost_model_version: str = ""
    methodology_version: str = ""
    # Parsed from a comma-separated string: "60000,300000,900000"
    opportunity_horizon_grid_ms: list[int] = [
        60_000, 300_000, 900_000, 1_800_000, 3_600_000
    ]

    # ── [FLAGS] ───────────────────────────────────────────────────────────────
    strategy_active: bool = False
    labeling_active: bool = False

    # ── Field validators ──────────────────────────────────────────────────────

    @field_validator("chain_expiries", mode="before")
    @classmethod
    def _parse_chain_expiries(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x).strip().upper() for x in v]
        if isinstance(v, str):
            return [x.strip().upper() for x in v.split(",") if x.strip()]
        raise ValueError(
            "Cannot parse BNO_CHAIN_EXPIRIES: expected a comma-separated string or list. "
            "Example: '26JUN2026,30JUN2026'"
        )

    @field_validator("chain_expiries", mode="after")
    @classmethod
    def _validate_chain_expiries(cls, v: list[str]) -> list[str]:
        if not v:
            raise BNOConfigValidationError(
                "BNO_CHAIN_EXPIRIES must not be empty. "
                "Provide at least one expiry in DDMMMYYYY format (e.g. '26JUN2026')."
            )
        _expiry_re = re.compile(r"^\d{2}([A-Z]{3})\d{4}$")
        _valid_months: frozenset[str] = frozenset({
            "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
            "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
        })
        for entry in v:
            m = _expiry_re.match(entry)
            if not m:
                raise BNOConfigValidationError(
                    f"BNO_CHAIN_EXPIRIES contains an entry that does not match "
                    f"DDMMMYYYY format (e.g. '26JUN2026'). "
                    f"Offending entry has {len(entry)} characters."
                )
            if m.group(1) not in _valid_months:
                raise BNOConfigValidationError(
                    f"BNO_CHAIN_EXPIRIES contains an unrecognised month abbreviation. "
                    f"Valid months: {', '.join(sorted(_valid_months))}."
                )
        return v

    @field_validator("opportunity_horizon_grid_ms", mode="before")
    @classmethod
    def _parse_horizon_grid(cls, v: object) -> list[int]:
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            parts = [x.strip() for x in v.split(",") if x.strip()]
            return [int(p) for p in parts]
        raise ValueError(
            f"Cannot parse BNO_OPPORTUNITY_HORIZON_GRID_MS from {type(v).__name__!r}. "
            f"Expected a comma-separated string of integers."
        )

    @field_validator("config_schema_version", mode="after")
    @classmethod
    def _check_schema_version(cls, v: int) -> int:
        if v != EXPECTED_CONFIG_SCHEMA_VERSION:
            raise BNOConfigVersionError(found=v, expected=EXPECTED_CONFIG_SCHEMA_VERSION)
        return v

    # ── Model validators (cross-field rules) ──────────────────────────────────

    @model_validator(mode="after")
    def _validate_production_totp_provider(self) -> "BNOSettings":
        if self.env == "production" and self.smartapi_totp_provider == "local_seed":
            raise BNOConfigValidationError(
                "BNO_SMARTAPI_TOTP_PROVIDER=local_seed is not permitted in production. "
                "Use 'authenticator_app' or 'secrets_manager'."
            )
        return self

    @model_validator(mode="after")
    def _validate_totp_secret_for_local_seed(self) -> "BNOSettings":
        if (
            self.smartapi_totp_provider == "local_seed"
            and self.smartapi_totp_secret is None
        ):
            raise BNOConfigValidationError(
                "BNO_SMARTAPI_TOTP_SECRET is required when "
                "BNO_SMARTAPI_TOTP_PROVIDER=local_seed."
            )
        return self

    @model_validator(mode="after")
    def _validate_labeling_gate(self) -> "BNOSettings":
        if self.labeling_active and not self.cost_model_version:
            raise BNOConfigValidationError(
                "BNO_LABELING_ACTIVE=true requires BNO_COST_MODEL_VERSION to be set. "
                "Ratify a cost model via DECISION_LOG before enabling labeling. "
                "See GOVERNANCE/STAGE_GATE_POLICY.md."
            )
        return self

    @model_validator(mode="after")
    def _validate_strategy_gate(self) -> "BNOSettings":
        if self.strategy_active:
            raise BNOConfigValidationError(
                "BNO_STRATEGY_ACTIVE=true is not permitted at the current stage. "
                "Strategy activation requires a stage-authorization token per "
                "GOVERNANCE/STAGE_GATE_POLICY.md."
            )
        return self
