from __future__ import annotations


class BNODiscoveryError(Exception):
    """Base class for all BankNifty Observatory discovery errors."""


class SessionAcquireError(BNODiscoveryError):
    """SmartAPI session could not be acquired.

    Raised when initial authentication fails, including TOTP failures that
    exhaust the one-retry allowance. Carries the attempt count so callers
    can distinguish a first-attempt failure from a retry-exhausted failure.
    """

    def __init__(self, message: str, attempt: int = 1) -> None:
        self.attempt = attempt
        super().__init__(message)


class SessionRefreshError(BNODiscoveryError):
    """SmartAPI session token could not be refreshed mid-session."""


class ChainFetchError(BNODiscoveryError):
    """Option chain data could not be fetched from SmartAPI.

    Not raised by ChainFetcher.fetch() — that method always returns a
    ChainResult(success=False). Reserved for callers that need to signal
    a hard chain-fetch failure upward without returning a result object.
    """


class SpotFetchError(BNODiscoveryError):
    """BankNifty spot index level could not be obtained.

    Not raised by SpotFetcher.fetch() — that method always returns a
    SpotResult(success=False). Reserved for callers signalling hard failures.
    """


class ArchiverError(BNODiscoveryError):
    """JSONL archiver encountered an unrecoverable I/O error.

    Raised on disk-full, permission errors, or writes to an un-opened
    archiver. The controller treats this as a phase-stopping condition.
    """


class StoreError(BNODiscoveryError):
    """SQLite analysis store encountered an unrecoverable error.

    Write failures from the store are normally logged as WARNING and
    suppressed (JSONL is the source of truth). This exception is reserved
    for initialisation failures (e.g., cannot create the DB file).
    """


class ReportGenerationError(BNODiscoveryError):
    """Discovery report could not be generated from the analysis store."""


class SmokeTestFailedError(BNODiscoveryError):
    """Phase 0 smoke test failed with one or more blocking issues.

    Raised by scripts/discovery_run.py --phase 0 when
    SmokeTestResult.passed is False, so the process exits with code 1.
    Carries the list of blocking issues for logging and CLI output.
    """

    def __init__(self, blocking_issues: list[str]) -> None:
        self.blocking_issues: list[str] = blocking_issues
        summary = "; ".join(blocking_issues) if blocking_issues else "unknown"
        super().__init__(f"Smoke test failed: {summary}")


class PhaseAbortedError(BNODiscoveryError):
    """A discovery phase was aborted before its natural stop condition.

    Raised when the DiscoveryController stops a phase early due to an
    unrecoverable error (e.g., ArchiverError on disk-full, or session
    re-acquire failure after the one allowed retry). The CLI uses this
    to distinguish a clean phase completion from an early abort.
    """

    def __init__(self, phase: int, reason: str) -> None:
        self.phase = phase
        self.reason = reason
        super().__init__(f"Phase {phase} aborted: {reason}")
