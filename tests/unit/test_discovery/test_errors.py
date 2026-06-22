"""Tests for lib.discovery._errors: complete error hierarchy."""
from __future__ import annotations

import pytest

from lib.discovery._errors import (
    ArchiverError,
    BNODiscoveryError,
    ChainFetchError,
    PhaseAbortedError,
    ReportGenerationError,
    SessionAcquireError,
    SessionRefreshError,
    SmokeTestFailedError,
    SpotFetchError,
    StoreError,
)

# All 9 concrete subclasses of BNODiscoveryError (base not included).
_SUBCLASSES: list[type[BNODiscoveryError]] = [
    SessionAcquireError,
    SessionRefreshError,
    ChainFetchError,
    SpotFetchError,
    ArchiverError,
    StoreError,
    ReportGenerationError,
    SmokeTestFailedError,
    PhaseAbortedError,
]


def _instantiate(cls: type[BNODiscoveryError]) -> BNODiscoveryError:
    """Construct an instance of any error class with appropriate arguments."""
    if cls is SmokeTestFailedError:
        return cls(blocking_issues=["test_issue"])
    if cls is SessionAcquireError:
        return cls("auth failed")
    if cls is PhaseAbortedError:
        return cls(phase=1, reason="test reason")
    return cls("test error message")  # type: ignore[call-arg]


# ── Hierarchy ─────────────────────────────────────────────────────────────────


class TestErrorHierarchy:
    def test_bno_discovery_error_is_exception(self) -> None:
        assert issubclass(BNODiscoveryError, Exception)

    def test_ten_classes_total(self) -> None:
        # BNODiscoveryError base + 9 subclasses = 10 error classes.
        assert len(_SUBCLASSES) == 9

    @pytest.mark.parametrize("cls", _SUBCLASSES)
    def test_each_subclass_inherits_base(self, cls: type[BNODiscoveryError]) -> None:
        assert issubclass(cls, BNODiscoveryError)

    @pytest.mark.parametrize("cls", _SUBCLASSES)
    def test_each_subclass_inherits_exception(
        self, cls: type[BNODiscoveryError]
    ) -> None:
        assert issubclass(cls, Exception)

    def test_base_catches_any_subclass(self) -> None:
        for cls in _SUBCLASSES:
            with pytest.raises(BNODiscoveryError):
                raise _instantiate(cls)

    @pytest.mark.parametrize("cls", _SUBCLASSES)
    def test_each_error_independently_catchable(
        self, cls: type[BNODiscoveryError]
    ) -> None:
        instance = _instantiate(cls)
        with pytest.raises(cls):
            raise instance

    @pytest.mark.parametrize("cls", _SUBCLASSES)
    def test_instances_have_str_representation(
        self, cls: type[BNODiscoveryError]
    ) -> None:
        instance = _instantiate(cls)
        assert isinstance(str(instance), str)
        assert len(str(instance)) > 0


# ── SessionAcquireError ───────────────────────────────────────────────────────


class TestSessionAcquireError:
    def test_message_preserved(self) -> None:
        err = SessionAcquireError("TOTP window mismatch")
        assert "TOTP window mismatch" in str(err)

    def test_attempt_default_is_one(self) -> None:
        err = SessionAcquireError("failed")
        assert err.attempt == 1

    def test_attempt_custom(self) -> None:
        err = SessionAcquireError("failed", attempt=2)
        assert err.attempt == 2

    def test_attempt_carried_through_raise(self) -> None:
        try:
            raise SessionAcquireError("network error", attempt=2)
        except SessionAcquireError as exc:
            assert exc.attempt == 2

    def test_catchable_as_bno_discovery_error(self) -> None:
        with pytest.raises(BNODiscoveryError):
            raise SessionAcquireError("test")


# ── SmokeTestFailedError ──────────────────────────────────────────────────────


class TestSmokeTestFailedError:
    def test_carries_blocking_issues(self) -> None:
        err = SmokeTestFailedError(["auth_failed", "chain_unreachable"])
        assert err.blocking_issues == ["auth_failed", "chain_unreachable"]

    def test_message_includes_first_issue(self) -> None:
        err = SmokeTestFailedError(["auth_failed"])
        assert "auth_failed" in str(err)

    def test_empty_blocking_issues(self) -> None:
        err = SmokeTestFailedError([])
        assert err.blocking_issues == []
        assert "unknown" in str(err)

    def test_multiple_issues_in_message(self) -> None:
        err = SmokeTestFailedError(["issue_a", "issue_b"])
        msg = str(err)
        assert "issue_a" in msg
        assert "issue_b" in msg

    def test_blocking_issues_list_is_mutable(self) -> None:
        err = SmokeTestFailedError(["a"])
        err.blocking_issues.append("b")
        assert "b" in err.blocking_issues

    def test_catchable_as_bno_discovery_error(self) -> None:
        with pytest.raises(BNODiscoveryError):
            raise SmokeTestFailedError(["test_issue"])


# ── PhaseAbortedError ─────────────────────────────────────────────────────────


class TestPhaseAbortedError:
    def test_carries_phase_number(self) -> None:
        err = PhaseAbortedError(phase=3, reason="disk full")
        assert err.phase == 3

    def test_carries_reason(self) -> None:
        err = PhaseAbortedError(phase=2, reason="auth retry exhausted")
        assert err.reason == "auth retry exhausted"

    def test_message_includes_phase(self) -> None:
        err = PhaseAbortedError(phase=2, reason="test")
        assert "2" in str(err)

    def test_message_includes_reason(self) -> None:
        err = PhaseAbortedError(phase=1, reason="disk full")
        assert "disk full" in str(err)

    def test_catchable_as_bno_discovery_error(self) -> None:
        with pytest.raises(BNODiscoveryError):
            raise PhaseAbortedError(phase=1, reason="test")

    def test_phase_zero_allowed(self) -> None:
        err = PhaseAbortedError(phase=0, reason="smoke test failure")
        assert err.phase == 0


# ── Simple error classes (message only) ───────────────────────────────────────


class TestSimpleErrorClasses:
    @pytest.mark.parametrize(
        "cls",
        [
            SessionRefreshError,
            ChainFetchError,
            SpotFetchError,
            ArchiverError,
            StoreError,
            ReportGenerationError,
        ],
    )
    def test_accepts_message_string(self, cls: type[BNODiscoveryError]) -> None:
        err = cls("descriptive error message")  # type: ignore[call-arg]
        assert "descriptive error message" in str(err)

    @pytest.mark.parametrize(
        "cls",
        [
            SessionRefreshError,
            ChainFetchError,
            SpotFetchError,
            ArchiverError,
            StoreError,
            ReportGenerationError,
        ],
    )
    def test_is_catchable_independently(self, cls: type[BNODiscoveryError]) -> None:
        with pytest.raises(cls):
            raise cls("error")  # type: ignore[call-arg]
