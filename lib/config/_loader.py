from __future__ import annotations

import re
from typing import NoReturn

from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from lib.config._errors import (
    BNOConfigError,
    BNOConfigEnvironmentError,
    BNOConfigMissingError,
    BNOConfigTypeError,
    BNOConfigValidationError,
)
from lib.config._settings import BNOSettings

_SETTINGS_ERROR_FIELD_RE = re.compile(r"field ['\"](\w+)['\"]")

_settings: BNOSettings | None = None

# pydantic v2 error types that map to a type-coercion failure
_TYPE_ERROR_KINDS: frozenset[str] = frozenset({
    "literal_error",
    "int_parsing",
    "int_type",
    "bool_parsing",
    "bool_type",
    "float_parsing",
    "float_type",
    "string_type",
    "value_error",
    "list_type",
})


def load_settings(env_file: str | None = ".env") -> BNOSettings:
    """
    Load and validate configuration. Call exactly once at application startup.

    Reads BNO_-prefixed environment variables. Loads the given env_file first
    (pass None to skip .env loading, e.g. in tests that set env vars directly).

    Raises a BNOConfigError subclass on any configuration problem.
    On success, the validated settings are available via get_settings().
    """
    global _settings

    kwargs: dict[str, object] = {}
    if env_file is not None:
        kwargs["_env_file"] = env_file

    try:
        _settings = BNOSettings(**kwargs)
    except BNOConfigError:
        # Our own validators raise directly — propagate as-is.
        raise
    except SettingsError as exc:
        # pydantic-settings raises SettingsError when a complex field (e.g.
        # list[str]) cannot be decoded from its env var value.  The most
        # common cause is a non-JSON value where a JSON array is required.
        _translate_settings_error(exc)
    except ValidationError as exc:
        _translate_pydantic_error(exc)

    return _settings


def get_settings() -> BNOSettings:
    """
    Return the validated settings singleton.

    Must be called after load_settings(). Raises RuntimeError if called first.
    Every module in the platform obtains configuration exclusively through this
    function — direct os.environ access is prohibited outside lib/config/.
    """
    if _settings is None:
        raise RuntimeError(
            "Configuration not initialised. "
            "Call lib.config.load_settings() at application startup "
            "before calling get_settings()."
        )
    return _settings


def _reset_settings() -> None:
    """Reset the singleton to None. For use in tests only."""
    global _settings
    _settings = None


def _translate_settings_error(exc: SettingsError) -> NoReturn:
    """Translate a pydantic-settings SettingsError into a BNOConfigTypeError.

    SettingsError fires when pydantic-settings cannot decode an env var value
    for a complex field (list, dict, etc.).  The canonical cause is a
    non-JSON string where a JSON-encoded value is required.
    """
    m = _SETTINGS_ERROR_FIELD_RE.search(str(exc))
    field_name = m.group(1) if m else "unknown"
    env_key = f"BNO_{field_name.upper()}"
    raise BNOConfigTypeError(
        key=env_key,
        expected_type="JSON-encoded value (e.g. list fields require a JSON array)",
    ) from exc


def _translate_pydantic_error(exc: ValidationError) -> NoReturn:
    """
    Convert the first significant pydantic ValidationError into a typed
    BNOConfigError and raise it.

    Raw field values are intentionally excluded from all error messages —
    a failing value may be a secret.
    """
    for error in exc.errors(include_url=False):
        loc = error.get("loc", ())
        field_name = str(loc[0]) if loc else "unknown"
        env_key = f"BNO_{field_name.upper()}"
        error_type = error.get("type", "")

        if error_type == "missing":
            raise BNOConfigMissingError(key=env_key)

        # BNO_ENV is a Literal — a literal_error means an unknown environment.
        if field_name == "env" and error_type == "literal_error":
            raw = error.get("input", "unknown")
            raise BNOConfigEnvironmentError(found=str(raw))

        if error_type in _TYPE_ERROR_KINDS:
            expected = str(error.get("ctx", {}).get("expected", "see schema"))
            raise BNOConfigTypeError(key=env_key, expected_type=expected)

    # Fallback: do not surface raw error detail (may contain secret values).
    raise BNOConfigValidationError(
        f"Configuration validation failed with {len(exc.errors())} error(s). "
        "Check that all required BNO_ environment variables are correctly set."
    )
