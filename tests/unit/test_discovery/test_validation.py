"""Tests for lib.discovery.validation: ValidationEngine (L3 M2a).

Standalone per the L3 design — not wired into DiscoveryController, the
runner, or any persistence/alerting path. These tests exercise the six
frozen rules and the engine in isolation only, over synthetic
ObservationRecord fixtures.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from lib.discovery._models import (
    OBSERVATION_SCHEMA_VERSION,
    ChainResult,
    ObservationRecord,
    OptionQuote,
    SnapshotContinuity,
    SnapshotMeta,
    SpotResult,
    VIXResult,
)
from lib.discovery.validation import (
    VALIDATION_RULESET_VERSION,
    ValidationEngine,
    ValidationFinding,
    _RULE_ATM_COHERENCE,
    _RULE_CHAIN_COMPLETENESS,
    _RULE_CONTINUITY_CONSISTENCY,
    _RULE_IDENTITY_CONSISTENCY,
    _RULE_SPOT_PLAUSIBILITY,
    _RULE_VIX_PLAUSIBILITY,
    _rule_atm_coherence,
    _rule_chain_completeness,
    _rule_continuity_self_consistency,
    _rule_identity_consistency,
    _rule_spot_plausibility,
    _rule_vix_plausibility,
)

_DT = datetime(2026, 6, 30, 4, 0, 0, tzinfo=timezone.utc)
_EXPIRY = "30JUN2026"
_PASS, _WARN, _FAIL = "PASS", "WARN", "FAIL"

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _quote(
    *,
    expiry: str = _EXPIRY,
    underlying: str = "BANKNIFTY",
    strike: int = 57000,
    side: str = "CE",
    oi: int = 1000,
    volume: int = 10,
    ltp: float | None = 100.0,
) -> OptionQuote:
    return OptionQuote(
        underlying=underlying, expiry=expiry, strike=strike,
        option_side=side, oi=oi, volume=volume, ltp=ltp,
    )


def _chain(
    *,
    expiry: str = _EXPIRY,
    success: bool = True,
    quotes: list[OptionQuote] | None = None,
) -> ChainResult:
    quotes = quotes if quotes is not None else ([_quote(expiry=expiry)] if success else [])
    return ChainResult(
        fetched_at=_DT, latency_ms=10.0, http_status=None, response_bytes=256,
        raw_response={"status": True} if success else None,
        row_count=len(quotes), expiry_count=1 if success else 0, unfetched_count=0,
        error=None if success else "chain_api_error", success=success,
        expiry=expiry, quotes=quotes,
    )


def _spot(*, ltp: float | None = 57000.0, success: bool = True) -> SpotResult:
    return SpotResult(
        fetched_at=_DT, latency_ms=5.0, ltp=ltp if success else None,
        raw_response={"status": True} if success else None,
        source="separate_call", error=None if success else "spot_api_error", success=success,
    )


def _vix(*, ltp: float | None = 15.0, success: bool = True) -> VIXResult:
    return VIXResult(
        fetched_at=_DT, latency_ms=5.0, ltp=ltp if success else None,
        raw_response={"status": True} if success else None,
        error=None if success else "vix_api_error", success=success,
    )


def _meta(
    *,
    anchoring_spot: float = 57000.0,
    resolved_atm: int = 57000,
    expiry_set: list[str] | None = None,
    chain_step_size: int = 500,
) -> SnapshotMeta:
    return SnapshotMeta(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        anchoring_spot=anchoring_spot,
        resolved_atm=resolved_atm,
        expiry_set=expiry_set if expiry_set is not None else [_EXPIRY],
        window_steps=2,
        chain_step_size=chain_step_size,
    )


def _continuity(
    *,
    status: str = "CONTIGUOUS",
    actual: float | None = 5.0,
    expected: int = 5,
) -> SnapshotContinuity:
    return SnapshotContinuity(
        previous_snapshot_id="prev-poll-id",
        previous_timestamp=_DT,
        expected_interval_seconds=expected,
        actual_interval_seconds=actual,
        continuity_status=status,
    )


def _record(**overrides: object) -> ObservationRecord:
    defaults: dict[str, object] = dict(
        poll_id="poll-1",
        session_id="sess-1",
        polled_at=_DT,
        phase=1,
        tick_number=1,
        interval_s=5,
        meta=_meta(),
        spot=_spot(),
        vix=_vix(),
        chains=[_chain()],
        derived=None,
        underlying="BANKNIFTY",
        continuity=_continuity(),
    )
    defaults.update(overrides)
    return ObservationRecord(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# ValidationFinding
# ===========================================================================


class TestValidationFinding:
    def test_construction(self) -> None:
        f = ValidationFinding(rule_id="x", level=_PASS, message="ok")
        assert f.rule_id == "x"
        assert f.level == _PASS
        assert f.message == "ok"

    def test_is_frozen(self) -> None:
        f = ValidationFinding(rule_id="x", level=_PASS, message="ok")
        with pytest.raises(Exception):
            f.level = _FAIL  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        a = ValidationFinding(rule_id="x", level=_PASS, message="ok")
        b = ValidationFinding(rule_id="x", level=_PASS, message="ok")
        assert a == b


# ===========================================================================
# R1 — identity consistency
# ===========================================================================


class TestIdentityConsistency:
    def test_pass_when_consistent(self) -> None:
        record = _record(chains=[_chain(quotes=[_quote(expiry=_EXPIRY, underlying="BANKNIFTY")])])
        finding = _rule_identity_consistency(record)
        assert finding.level == _PASS
        assert finding.rule_id == _RULE_IDENTITY_CONSISTENCY

    def test_fail_on_quote_expiry_mismatch(self) -> None:
        bad_quote = _quote(expiry="31JUL2026")
        record = _record(chains=[_chain(expiry=_EXPIRY, quotes=[bad_quote])])
        finding = _rule_identity_consistency(record)
        assert finding.level == _FAIL
        assert "expiry" in finding.message

    def test_fail_on_quote_underlying_mismatch(self) -> None:
        bad_quote = _quote(underlying="NIFTY")
        record = _record(underlying="BANKNIFTY", chains=[_chain(quotes=[bad_quote])])
        finding = _rule_identity_consistency(record)
        assert finding.level == _FAIL
        assert "underlying" in finding.message

    def test_pass_when_no_chains(self) -> None:
        record = _record(chains=[])
        assert _rule_identity_consistency(record).level == _PASS

    def test_pass_when_chain_has_no_quotes(self) -> None:
        record = _record(chains=[_chain(quotes=[])])
        assert _rule_identity_consistency(record).level == _PASS

    def test_fail_detected_across_multiple_chains(self) -> None:
        good_chain = _chain(expiry=_EXPIRY, quotes=[_quote(expiry=_EXPIRY)])
        bad_chain = _chain(expiry="31JUL2026", quotes=[_quote(expiry="01JAN2099")])
        record = _record(chains=[good_chain, bad_chain])
        assert _rule_identity_consistency(record).level == _FAIL

    def test_multiple_consistent_quotes_in_one_chain_pass(self) -> None:
        chain = _chain(quotes=[
            _quote(expiry=_EXPIRY, strike=56000, side="CE"),
            _quote(expiry=_EXPIRY, strike=56000, side="PE"),
        ])
        record = _record(chains=[chain])
        assert _rule_identity_consistency(record).level == _PASS


# ===========================================================================
# R2 — VIX plausibility
# ===========================================================================


class TestVixPlausibility:
    def test_pass_within_band(self) -> None:
        record = _record(vix=_vix(ltp=15.0))
        finding = _rule_vix_plausibility(record)
        assert finding.level == _PASS
        assert finding.rule_id == _RULE_VIX_PLAUSIBILITY

    def test_pass_at_lower_edge(self) -> None:
        record = _record(vix=_vix(ltp=1.0))
        assert _rule_vix_plausibility(record).level == _PASS

    def test_pass_at_upper_edge(self) -> None:
        record = _record(vix=_vix(ltp=100.0))
        assert _rule_vix_plausibility(record).level == _PASS

    def test_fail_below_band(self) -> None:
        record = _record(vix=_vix(ltp=0.5))
        assert _rule_vix_plausibility(record).level == _FAIL

    def test_fail_above_band(self) -> None:
        record = _record(vix=_vix(ltp=1721.5))  # the proven HDFCBANK-price bug class
        assert _rule_vix_plausibility(record).level == _FAIL

    def test_pass_when_vix_unsuccessful(self) -> None:
        record = _record(vix=_vix(success=False, ltp=None))
        assert _rule_vix_plausibility(record).level == _PASS

    def test_pass_when_ltp_none_despite_success(self) -> None:
        # Defensive: shouldn't happen per VIXResult's contract, but must not crash.
        record = _record(vix=VIXResult(
            fetched_at=_DT, latency_ms=1.0, ltp=None,
            raw_response=None, error=None, success=True,
        ))
        assert _rule_vix_plausibility(record).level == _PASS


# ===========================================================================
# R3 — spot plausibility
# ===========================================================================


class TestSpotPlausibility:
    def test_pass_within_band(self) -> None:
        record = _record(spot=_spot(ltp=57000.0))
        finding = _rule_spot_plausibility(record)
        assert finding.level == _PASS
        assert finding.rule_id == _RULE_SPOT_PLAUSIBILITY

    def test_pass_at_lower_edge(self) -> None:
        record = _record(spot=_spot(ltp=10_000.0))
        assert _rule_spot_plausibility(record).level == _PASS

    def test_pass_at_upper_edge(self) -> None:
        record = _record(spot=_spot(ltp=150_000.0))
        assert _rule_spot_plausibility(record).level == _PASS

    def test_fail_below_band(self) -> None:
        record = _record(spot=_spot(ltp=500.0))
        assert _rule_spot_plausibility(record).level == _FAIL

    def test_fail_above_band(self) -> None:
        record = _record(spot=_spot(ltp=999_999.0))
        assert _rule_spot_plausibility(record).level == _FAIL

    def test_pass_when_spot_unsuccessful(self) -> None:
        record = _record(spot=_spot(success=False, ltp=None))
        assert _rule_spot_plausibility(record).level == _PASS


# ===========================================================================
# R4 — ATM resolution coherence
# ===========================================================================


class TestAtmResolutionCoherence:
    def test_pass_when_exact_match(self) -> None:
        record = _record(meta=_meta(anchoring_spot=57000.0, resolved_atm=57000, chain_step_size=500))
        finding = _rule_atm_coherence(record)
        assert finding.level == _PASS
        assert finding.rule_id == _RULE_ATM_COHERENCE

    def test_pass_within_one_step(self) -> None:
        record = _record(meta=_meta(anchoring_spot=57200.0, resolved_atm=57000, chain_step_size=500))
        assert _rule_atm_coherence(record).level == _PASS

    def test_pass_at_exactly_one_step(self) -> None:
        record = _record(meta=_meta(anchoring_spot=57500.0, resolved_atm=57000, chain_step_size=500))
        assert _rule_atm_coherence(record).level == _PASS

    def test_warn_between_one_and_five_steps(self) -> None:
        record = _record(meta=_meta(anchoring_spot=58500.0, resolved_atm=57000, chain_step_size=500))
        assert _rule_atm_coherence(record).level == _WARN

    def test_pass_at_exactly_five_steps(self) -> None:
        record = _record(meta=_meta(anchoring_spot=59500.0, resolved_atm=57000, chain_step_size=500))
        assert _rule_atm_coherence(record).level == _WARN

    def test_fail_beyond_five_steps(self) -> None:
        record = _record(meta=_meta(anchoring_spot=60100.0, resolved_atm=57000, chain_step_size=500))
        assert _rule_atm_coherence(record).level == _FAIL

    def test_pass_on_spot_failure_zeroed_record(self) -> None:
        # Controller zeroes anchoring_spot/resolved_atm on spot failure — gap is 0.
        record = _record(meta=_meta(anchoring_spot=0.0, resolved_atm=0, chain_step_size=500))
        assert _rule_atm_coherence(record).level == _PASS

    def test_defensive_on_zero_step_size(self) -> None:
        record = _record(meta=_meta(anchoring_spot=57000.0, resolved_atm=57000, chain_step_size=0))
        finding = _rule_atm_coherence(record)  # must not raise (no division)
        assert finding.level == _PASS


# ===========================================================================
# R5 — chain completeness
# ===========================================================================


class TestChainCompleteness:
    def test_pass_when_spot_unsuccessful(self) -> None:
        record = _record(spot=_spot(success=False, ltp=None), chains=[])
        finding = _rule_chain_completeness(record)
        assert finding.level == _PASS
        assert finding.rule_id == _RULE_CHAIN_COMPLETENESS

    def test_pass_when_no_expiries_configured(self) -> None:
        record = _record(meta=_meta(expiry_set=[]), chains=[])
        assert _rule_chain_completeness(record).level == _PASS

    def test_pass_when_all_expiries_successful(self) -> None:
        record = _record(
            meta=_meta(expiry_set=["30JUN2026", "31JUL2026"]),
            chains=[_chain(expiry="30JUN2026"), _chain(expiry="31JUL2026")],
        )
        assert _rule_chain_completeness(record).level == _PASS

    def test_warn_when_some_expiries_failed(self) -> None:
        record = _record(
            meta=_meta(expiry_set=["30JUN2026", "31JUL2026"]),
            chains=[_chain(expiry="30JUN2026"), _chain(expiry="31JUL2026", success=False)],
        )
        assert _rule_chain_completeness(record).level == _WARN

    def test_fail_when_all_expiries_failed(self) -> None:
        record = _record(
            meta=_meta(expiry_set=["30JUN2026", "31JUL2026"]),
            chains=[_chain(expiry="30JUN2026", success=False), _chain(expiry="31JUL2026", success=False)],
        )
        assert _rule_chain_completeness(record).level == _FAIL

    def test_fail_when_configured_expiry_has_no_chain_result_at_all(self) -> None:
        record = _record(meta=_meta(expiry_set=["30JUN2026", "31JUL2026"]), chains=[])
        assert _rule_chain_completeness(record).level == _FAIL

    def test_warn_when_one_expiry_missing_entirely(self) -> None:
        record = _record(
            meta=_meta(expiry_set=["30JUN2026", "31JUL2026"]),
            chains=[_chain(expiry="30JUN2026")],
        )
        assert _rule_chain_completeness(record).level == _WARN


# ===========================================================================
# R6 — continuity self-consistency
# ===========================================================================


class TestContinuitySelfConsistency:
    def test_pass_when_continuity_is_none(self) -> None:
        record = _record(continuity=None)
        finding = _rule_continuity_self_consistency(record)
        assert finding.level == _PASS
        assert finding.rule_id == _RULE_CONTINUITY_CONSISTENCY

    def test_pass_when_first(self) -> None:
        record = _record(continuity=_continuity(status="FIRST", actual=None, expected=5))
        assert _rule_continuity_self_consistency(record).level == _PASS

    def test_pass_when_contiguous_and_actually_within_tolerance(self) -> None:
        record = _record(continuity=_continuity(status="CONTIGUOUS", actual=5.0, expected=5))
        assert _rule_continuity_self_consistency(record).level == _PASS

    def test_pass_when_gap_and_actually_outside_tolerance(self) -> None:
        record = _record(continuity=_continuity(status="GAP", actual=30.0, expected=5))
        assert _rule_continuity_self_consistency(record).level == _PASS

    def test_warn_when_labeled_contiguous_but_actually_outside_tolerance(self) -> None:
        record = _record(continuity=_continuity(status="CONTIGUOUS", actual=30.0, expected=5))
        finding = _rule_continuity_self_consistency(record)
        assert finding.level == _WARN

    def test_warn_when_labeled_gap_but_actually_within_tolerance(self) -> None:
        record = _record(continuity=_continuity(status="GAP", actual=5.0, expected=5))
        assert _rule_continuity_self_consistency(record).level == _WARN

    def test_warn_when_actual_is_none_for_non_first_status(self) -> None:
        record = _record(continuity=_continuity(status="CONTIGUOUS", actual=None, expected=5))
        assert _rule_continuity_self_consistency(record).level == _WARN

    def test_pass_at_tolerance_boundary(self) -> None:
        # expected=10, tolerance +-50% -> [5, 15]; actual=15 is still CONTIGUOUS.
        record = _record(continuity=_continuity(status="CONTIGUOUS", actual=15.0, expected=10))
        assert _rule_continuity_self_consistency(record).level == _PASS


# ===========================================================================
# ValidationEngine
# ===========================================================================


class TestValidationEngine:
    def test_ruleset_version(self) -> None:
        assert ValidationEngine().ruleset_version == VALIDATION_RULESET_VERSION
        assert VALIDATION_RULESET_VERSION == 1

    def test_evaluate_returns_list_of_findings(self) -> None:
        findings = ValidationEngine().evaluate(_record())
        assert isinstance(findings, list)
        assert all(isinstance(f, ValidationFinding) for f in findings)

    def test_evaluate_returns_exactly_six_findings(self) -> None:
        findings = ValidationEngine().evaluate(_record())
        assert len(findings) == 6

    def test_healthy_record_is_all_pass(self) -> None:
        findings = ValidationEngine().evaluate(_record())
        assert all(f.level == _PASS for f in findings)

    def test_findings_in_fixed_deterministic_order(self) -> None:
        findings = ValidationEngine().evaluate(_record())
        rule_ids = [f.rule_id for f in findings]
        assert rule_ids == [
            _RULE_IDENTITY_CONSISTENCY,
            _RULE_VIX_PLAUSIBILITY,
            _RULE_SPOT_PLAUSIBILITY,
            _RULE_ATM_COHERENCE,
            _RULE_CHAIN_COMPLETENESS,
            _RULE_CONTINUITY_CONSISTENCY,
        ]

    def test_evaluate_is_deterministic_across_calls(self) -> None:
        record = _record()
        engine = ValidationEngine()
        assert engine.evaluate(record) == engine.evaluate(record)

    def test_evaluate_does_not_mutate_record(self) -> None:
        record = _record()
        chains_before = record.chains
        continuity_before = record.continuity
        ValidationEngine().evaluate(record)
        assert record.chains is chains_before
        assert record.continuity is continuity_before

    def test_corrupted_record_surfaces_multiple_findings(self) -> None:
        record = _record(
            vix=_vix(ltp=1721.5),  # HDFCBANK-price bug class
            meta=_meta(anchoring_spot=60100.0, resolved_atm=57000, chain_step_size=500),
        )
        findings = ValidationEngine().evaluate(record)
        by_rule = {f.rule_id: f for f in findings}
        assert by_rule[_RULE_VIX_PLAUSIBILITY].level == _FAIL
        assert by_rule[_RULE_ATM_COHERENCE].level == _FAIL
        # Unrelated rules over an otherwise-healthy record are unaffected.
        assert by_rule[_RULE_IDENTITY_CONSISTENCY].level == _PASS
        assert by_rule[_RULE_CHAIN_COMPLETENESS].level == _PASS

    def test_rule_exception_yields_fail_finding_not_a_crash(self) -> None:
        with patch(
            "lib.discovery.validation._rule_vix_plausibility",
            side_effect=RuntimeError("boom"),
        ):
            engine = ValidationEngine()
            findings = engine.evaluate(_record())  # must not raise

        assert len(findings) == 6
        by_rule = {f.rule_id: f for f in findings}
        assert by_rule[_RULE_VIX_PLAUSIBILITY].level == _FAIL
        assert "RuntimeError" in by_rule[_RULE_VIX_PLAUSIBILITY].message

    def test_other_rules_unaffected_when_one_rule_crashes(self) -> None:
        with patch(
            "lib.discovery.validation._rule_spot_plausibility",
            side_effect=ValueError("bad"),
        ):
            engine = ValidationEngine()
            findings = engine.evaluate(_record())

        by_rule = {f.rule_id: f for f in findings}
        assert by_rule[_RULE_SPOT_PLAUSIBILITY].level == _FAIL
        assert by_rule[_RULE_IDENTITY_CONSISTENCY].level == _PASS
        assert by_rule[_RULE_ATM_COHERENCE].level == _PASS
        assert by_rule[_RULE_CHAIN_COMPLETENESS].level == _PASS
        assert by_rule[_RULE_CONTINUITY_CONSISTENCY].level == _PASS

    def test_crash_error_message_excludes_original_exception_text(self) -> None:
        # Consistent with the rest of the codebase's sanitised-error convention.
        with patch(
            "lib.discovery.validation._rule_chain_completeness",
            side_effect=ValueError("secret_internal_detail"),
        ):
            engine = ValidationEngine()
            findings = engine.evaluate(_record())

        message = next(f.message for f in findings if f.rule_id == _RULE_CHAIN_COMPLETENESS)
        assert "secret_internal_detail" not in message
        assert "ValueError" in message

    def test_evaluate_never_raises_even_if_every_rule_crashes(self) -> None:
        with patch("lib.discovery.validation._rule_identity_consistency", side_effect=RuntimeError()), \
             patch("lib.discovery.validation._rule_vix_plausibility", side_effect=RuntimeError()), \
             patch("lib.discovery.validation._rule_spot_plausibility", side_effect=RuntimeError()), \
             patch("lib.discovery.validation._rule_atm_coherence", side_effect=RuntimeError()), \
             patch("lib.discovery.validation._rule_chain_completeness", side_effect=RuntimeError()), \
             patch("lib.discovery.validation._rule_continuity_self_consistency", side_effect=RuntimeError()):
            engine = ValidationEngine()
            findings = engine.evaluate(_record())  # must not raise

        assert len(findings) == 6
        assert all(f.level == _FAIL for f in findings)
