from __future__ import annotations


class BNOConfigError(Exception):
    """Base class for all BankNifty Observatory configuration errors."""


class BNOConfigMissingError(BNOConfigError):
    """A required BNO_ key is absent from the environment."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Required configuration key is absent: {key}")


class BNOConfigTypeError(BNOConfigError):
    """A BNO_ value could not be coerced to its declared type."""

    def __init__(self, key: str, expected_type: str) -> None:
        self.key = key
        self.expected_type = expected_type
        # Raw value is intentionally excluded — it may be a secret.
        super().__init__(
            f"Configuration key {key!r} has an invalid value for type "
            f"{expected_type!r}. Check your .env file."
        )


class BNOConfigVersionError(BNOConfigError):
    """BNO_CONFIG_SCHEMA_VERSION does not match the expected version."""

    def __init__(self, found: int | str, expected: int) -> None:
        self.found = found
        self.expected = expected
        super().__init__(
            f"BNO_CONFIG_SCHEMA_VERSION mismatch: found {found!r}, expected {expected}. "
            f"Synchronise your .env file with the current configuration schema."
        )


class BNOConfigEnvironmentError(BNOConfigError):
    """BNO_ENV is not a recognised environment name."""

    def __init__(self, found: str) -> None:
        self.found = found
        super().__init__(
            f"Unknown BNO_ENV value {found!r}. "
            f"Valid values: development, staging, production."
        )


class BNOConfigValidationError(BNOConfigError):
    """A cross-field or governance-rule validation failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
