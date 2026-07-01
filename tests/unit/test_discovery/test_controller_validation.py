"""Tests for DiscoveryController's ValidationEngine wiring (L3 M2b).

Reuses the mock-based harness from test_controller.py (_make_controller,
_SchedulerStub, _DT_1/_DT_2/_DT_3), with added `validator` and
`quality_archiver` arguments.

Proves:
  1. validator=None (default, every current caller including discovery_run.py
     as of this milestone) preserves existing controller behaviour exactly —
     no evaluate() call, no quality write, no extra logging.
  2. validation is evaluated exactly once per tick.
  3. raw persistence always occurs — before any quality-stream write, and
     regardless of the validation outcome (including a FAIL verdict).
  4. quality_archiver write failure (ArchiverError) is caught, logged, and
     never aborts the run.
  5. a validator that raises (simulating an engine-level bug, not just an
     internal per-rule crash which ValidationEngine already contains) does
     not abort the run either — the controller's own defensive wrap.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call

from lib.discovery._errors import ArchiverError
from lib.discovery.controller import DiscoveryController, _STATE_ABORTED, _STATE_STOPPED
from lib.discovery.validation import ValidationFinding
from tests.unit.test_discovery.test_controller import (
    _DT_1,
    _DT_2,
    _DT_3,
    _SchedulerStub,
    _make_chain_result,
    _make_controller,
)


def _finding(rule_id: str = "some_rule", level: str = "PASS", message: str = "ok") -> ValidationFinding:
    return ValidationFinding(rule_id=rule_id, level=level, message=message)


def _make_validator(findings: list[ValidationFinding] | None = None, *, side_effect=None) -> MagicMock:
    validator = MagicMock()
    validator.ruleset_version = 1
    if side_effect is not None:
        validator.evaluate.side_effect = side_effect
    else:
        validator.evaluate.return_value = findings if findings is not None else [_finding()]
    return validator


def _make_quality_archiver(*, write_side_effect=None) -> MagicMock:
    qa = MagicMock()
    if write_side_effect is not None:
        qa.write.side_effect = write_side_effect
    return qa


def _make_chain_fetcher_mock() -> MagicMock:
    cf = MagicMock()
    cf.fetch.return_value = _make_chain_result()
    return cf


# ===========================================================================
# 1. validator=None preserves existing behaviour exactly
# ===========================================================================


class TestValidatorDisabledLegacyParity:
    def test_run_completes_normally(self) -> None:
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1, _DT_2))
        result = ctrl.run()
        assert result.ended_early is False
        assert ctrl.state == _STATE_STOPPED

    def test_no_validator_no_evaluate_call(self) -> None:
        # There is no validator to call evaluate() on — nothing to assert on
        # the validator itself; this documents the no-op path explicitly.
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1))
        ctrl.run()  # must not raise

    def test_quality_archiver_never_written_when_validator_none(self) -> None:
        quality_archiver = _make_quality_archiver()
        ctrl = _make_controller(quality_archiver=quality_archiver, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        quality_archiver.write.assert_not_called()

    def test_raw_archiver_still_written_when_validator_none(self) -> None:
        archiver = MagicMock()
        archiver.current_file_path = None
        ctrl = _make_controller(archiver=archiver, scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        ctrl.run()
        assert archiver.write.call_count == 3

    def test_ticks_processed_normally(self) -> None:
        ctrl = _make_controller(scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        result = ctrl.run()
        assert result.total_ticks == 3


# ===========================================================================
# 2. Validation executed exactly once per tick
# ===========================================================================


class TestValidationExecutedOncePerTick:
    def test_evaluate_called_once_for_single_tick(self) -> None:
        validator = _make_validator()
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert validator.evaluate.call_count == 1

    def test_evaluate_called_once_per_tick_across_multiple_ticks(self) -> None:
        validator = _make_validator()
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        ctrl.run()
        assert validator.evaluate.call_count == 3

    def test_evaluate_receives_the_observation_record(self) -> None:
        validator = _make_validator()
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        from lib.discovery._models import ObservationRecord
        args, _ = validator.evaluate.call_args
        assert isinstance(args[0], ObservationRecord)

    def test_zero_ticks_zero_evaluate_calls(self) -> None:
        validator = _make_validator()
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub())
        ctrl.run()
        assert validator.evaluate.call_count == 0


# ===========================================================================
# 3. Raw persistence always occurs, before quality write, regardless of verdict
# ===========================================================================


class TestRawPersistenceAlwaysOccurs:
    def test_raw_written_when_verdict_is_all_pass(self) -> None:
        validator = _make_validator([_finding(level="PASS")])
        archiver = MagicMock()
        archiver.current_file_path = None
        ctrl = _make_controller(validator=validator, archiver=archiver, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert archiver.write.call_count == 1

    def test_raw_written_when_verdict_has_fail(self) -> None:
        validator = _make_validator([_finding(level="FAIL", rule_id="vix_plausibility")])
        archiver = MagicMock()
        archiver.current_file_path = None
        ctrl = _make_controller(validator=validator, archiver=archiver, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        # A FAIL finding must never suppress or gate the raw write.
        assert archiver.write.call_count == 1

    def test_raw_write_happens_before_quality_write(self) -> None:
        validator = _make_validator([_finding(level="WARN")])
        quality_archiver = _make_quality_archiver()
        archiver = MagicMock()
        archiver.current_file_path = None

        call_order: list[str] = []
        archiver.write.side_effect = lambda *a, **k: call_order.append("raw")
        quality_archiver.write.side_effect = lambda *a, **k: call_order.append("quality")

        ctrl = _make_controller(
            validator=validator, archiver=archiver, quality_archiver=quality_archiver,
            scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        assert call_order == ["raw", "quality"]

    def test_evaluate_happens_before_raw_write(self) -> None:
        # "Evaluate before persistence" governs computation order — the
        # verdict is computed before any I/O for the tick, even though raw
        # persistence itself is unconditional and still happens first among
        # the two writes.
        archiver = MagicMock()
        archiver.current_file_path = None
        call_order: list[str] = []

        validator = MagicMock()
        validator.ruleset_version = 1

        def _evaluate(record):
            call_order.append("evaluate")
            return [_finding()]

        validator.evaluate.side_effect = _evaluate
        archiver.write.side_effect = lambda *a, **k: call_order.append("raw_write")

        ctrl = _make_controller(validator=validator, archiver=archiver, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert call_order == ["evaluate", "raw_write"]


# ===========================================================================
# 4. Quality write failure is caught, logged, never aborts
# ===========================================================================


class TestQualityWriteFailureNeverAborts:
    def test_run_completes_normally_despite_quality_write_failure(self) -> None:
        validator = _make_validator([_finding()])
        quality_archiver = _make_quality_archiver(write_side_effect=ArchiverError("disk full"))
        ctrl = _make_controller(
            validator=validator, quality_archiver=quality_archiver,
            scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        result = ctrl.run()  # must not raise
        assert result.ended_early is False
        assert ctrl.state == _STATE_STOPPED

    def test_raw_still_written_despite_quality_write_failure(self) -> None:
        validator = _make_validator([_finding()])
        quality_archiver = _make_quality_archiver(write_side_effect=ArchiverError("disk full"))
        archiver = MagicMock()
        archiver.current_file_path = None
        ctrl = _make_controller(
            validator=validator, quality_archiver=quality_archiver, archiver=archiver,
            scheduler=_SchedulerStub(_DT_1, _DT_2),
        )
        ctrl.run()
        assert archiver.write.call_count == 2

    def test_all_ticks_still_processed_despite_quality_write_failure(self) -> None:
        validator = _make_validator([_finding()])
        quality_archiver = _make_quality_archiver(write_side_effect=ArchiverError("disk full"))
        ctrl = _make_controller(
            validator=validator, quality_archiver=quality_archiver,
            scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3),
        )
        result = ctrl.run()
        assert result.total_ticks == 3

    def test_quality_write_failure_does_not_abort_even_on_first_tick(self) -> None:
        validator = _make_validator([_finding()])
        quality_archiver = _make_quality_archiver(write_side_effect=ArchiverError("boom"))
        ctrl = _make_controller(
            validator=validator, quality_archiver=quality_archiver,
            scheduler=_SchedulerStub(_DT_1),
        )
        result = ctrl.run()
        assert result.ended_early is False


# ===========================================================================
# 5. Validator/rule exception does not abort
# ===========================================================================


class TestValidatorExceptionDoesNotAbort:
    def test_validator_evaluate_raising_does_not_abort_run(self) -> None:
        validator = _make_validator(side_effect=RuntimeError("engine bug"))
        result = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1, _DT_2)).run()
        assert result.ended_early is False

    def test_raw_still_persisted_when_validator_raises(self) -> None:
        validator = _make_validator(side_effect=RuntimeError("engine bug"))
        archiver = MagicMock()
        archiver.current_file_path = None
        ctrl = _make_controller(validator=validator, archiver=archiver, scheduler=_SchedulerStub(_DT_1, _DT_2))
        ctrl.run()
        assert archiver.write.call_count == 2

    def test_all_ticks_processed_when_validator_raises_every_time(self) -> None:
        validator = _make_validator(side_effect=RuntimeError("engine bug"))
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1, _DT_2, _DT_3))
        result = ctrl.run()
        assert result.total_ticks == 3

    def test_quality_archiver_not_written_when_validator_raises(self) -> None:
        # No findings were produced, so there is nothing to persist to the
        # quality stream for that tick.
        validator = _make_validator(side_effect=RuntimeError("engine bug"))
        quality_archiver = _make_quality_archiver()
        ctrl = _make_controller(
            validator=validator, quality_archiver=quality_archiver, scheduler=_SchedulerStub(_DT_1),
        )
        ctrl.run()
        quality_archiver.write.assert_not_called()

    def test_state_is_stopped_not_aborted_when_validator_raises(self) -> None:
        validator = _make_validator(side_effect=ValueError("bad rule"))
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1))
        ctrl.run()
        assert ctrl.state == _STATE_STOPPED


# ===========================================================================
# WARN/FAIL logging (supplementary to the acceptance list, cheap to verify)
# ===========================================================================


class TestValidationLogging:
    def test_warn_finding_logs_warning(self) -> None:
        validator = _make_validator([_finding(level="WARN", rule_id="atm_resolution_coherence")])
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1))
        ctrl._log = MagicMock()
        ctrl.run()
        warn_calls = [c for c in ctrl._log.warning.call_args_list if c.args and c.args[0] == "validation_warn"]
        assert len(warn_calls) == 1
        assert warn_calls[0].kwargs["extra"]["warn_count"] == 1
        assert warn_calls[0].kwargs["extra"]["rules"] == ["atm_resolution_coherence"]

    def test_fail_finding_logs_error(self) -> None:
        validator = _make_validator([_finding(level="FAIL", rule_id="vix_plausibility")])
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1))
        ctrl._log = MagicMock()
        ctrl.run()
        error_calls = [c for c in ctrl._log.error.call_args_list if c.args and c.args[0] == "validation_fail"]
        assert len(error_calls) == 1
        assert error_calls[0].kwargs["extra"]["rules"] == ["vix_plausibility"]

    def test_pass_only_findings_log_neither(self) -> None:
        validator = _make_validator([_finding(level="PASS")])
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1))
        ctrl._log = MagicMock()
        ctrl.run()
        assert not any(c.args and c.args[0] == "validation_warn" for c in ctrl._log.warning.call_args_list)
        assert not any(c.args and c.args[0] == "validation_fail" for c in ctrl._log.error.call_args_list)

    def test_both_warn_and_fail_log_independently(self) -> None:
        validator = _make_validator([
            _finding(level="WARN", rule_id="chain_completeness"),
            _finding(level="FAIL", rule_id="spot_plausibility"),
        ])
        ctrl = _make_controller(validator=validator, scheduler=_SchedulerStub(_DT_1))
        ctrl._log = MagicMock()
        ctrl.run()
        warn_calls = [c for c in ctrl._log.warning.call_args_list if c.args and c.args[0] == "validation_warn"]
        fail_calls = [c for c in ctrl._log.error.call_args_list if c.args and c.args[0] == "validation_fail"]
        assert len(warn_calls) == 1
        assert len(fail_calls) == 1
