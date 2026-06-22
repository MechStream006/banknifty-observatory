"""
lib.config — BankNifty Observatory Configuration Framework
===========================================================

Public API
----------
    load_settings(env_file)  → initialise the singleton at startup
    get_settings()           → retrieve it from anywhere in the platform
    get_redacted_snapshot()  → safe dict for lineage records / logs

    BNOSettings              → the settings model (for type hints and tests)

Error hierarchy
---------------
    BNOConfigError               (base)
    ├── BNOConfigMissingError    required key absent
    ├── BNOConfigTypeError       value cannot be coerced to declared type
    ├── BNOConfigVersionError    BNO_CONFIG_SCHEMA_VERSION mismatch
    ├── BNOConfigEnvironmentError BNO_ENV is not a known environment
    └── BNOConfigValidationError cross-field or governance-rule failure

Rules
-----
    - Direct os.environ access anywhere outside this package is prohibited.
    - All configuration flows through get_settings().
    - Secret values (SecretStr fields) never appear in logs, error messages,
      repr output, or snapshots.
"""

from lib.config._errors import (
    BNOConfigEnvironmentError,
    BNOConfigError,
    BNOConfigMissingError,
    BNOConfigTypeError,
    BNOConfigValidationError,
    BNOConfigVersionError,
)
from lib.config._loader import _reset_settings, get_settings, load_settings
from lib.config._settings import BNOSettings
from lib.config._snapshot import get_redacted_snapshot

__all__ = [
    # Core API
    "load_settings",
    "get_settings",
    "get_redacted_snapshot",
    "BNOSettings",
    # Error hierarchy
    "BNOConfigError",
    "BNOConfigMissingError",
    "BNOConfigTypeError",
    "BNOConfigVersionError",
    "BNOConfigEnvironmentError",
    "BNOConfigValidationError",
    # Testing only
    "_reset_settings",
]
