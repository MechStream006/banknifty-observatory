"""
ValidationEngine — pure, per-snapshot correctness checks over an assembled
ObservationRecord (L3 M2a).

Design constraints (frozen — L3 Validation Framework design)
--------------------------------------------------------------
- Every rule is a pure function of ONE ObservationRecord — no prior-tick
  state, no external I/O, no hidden engine state across calls. This keeps
  every rule trivially unit-testable and keeps the same rule body reusable
  later by an offline forensic pass over archived records.
- evaluate() ALWAYS returns exactly one ValidationFinding per registered
  rule, in a fixed, deterministic order — never raises. A rule that raises
  is caught and recorded as a FAIL finding for that rule (fail-safe, not
  fail-silent) without affecting any other rule's evaluation.
- Exactly three levels: PASS, WARN, FAIL. There is no fourth "unknown"
  bucket — a rule that cannot be evaluated as invalid is PASS (nothing
  proven wrong), and a rule that crashes is FAIL (cannot be trusted).
- This module performs NO persistence and NO alerting. It is not wired
  into the controller, the runner, or any writer. evaluate() returns a
  plain list[ValidationFinding] for a future caller to do something with.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.discovery._models import ObservationRecord

# ── Versioning ────────────────────────────────────────────────────────────────

# Independent versioning axis for the rule set itself — sibling to
# OBSERVATION_SCHEMA_VERSION / COLLECTION_CONTRACT_VERSION, but governs
# neither the record layout nor the collection intent; it governs which
# rules judged a given record. Bump when a rule's pass/fail semantics change.
VALIDATION_RULESET_VERSION: Final[int] = 1

# ── Levels ──────────────────────────────────────────────────────────────────

_PASS = "PASS"
_WARN = "WARN"
_FAIL = "FAIL"

# ── Rule identifiers ──────────────────────────────────────────────────────────

_RULE_IDENTITY_CONSISTENCY   = "identity_consistency"
_RULE_VIX_PLAUSIBILITY       = "vix_plausibility"
_RULE_SPOT_PLAUSIBILITY      = "spot_plausibility"
_RULE_ATM_COHERENCE          = "atm_resolution_coherence"
_RULE_CHAIN_COMPLETENESS     = "chain_completeness"
_RULE_CONTINUITY_CONSISTENCY = "continuity_self_consistency"

# ── Plausibility bands ────────────────────────────────────────────────────────

# India VIX has never traded outside roughly 5-90 historically; this band is
# a deliberately generous safety net (matches the VIXFetcher L1 sanity check),
# checked again here — independently — as corpus-wide defense in depth.
_VIX_MIN = 1.0
_VIX_MAX = 100.0

# BankNifty index — a wide, generous historical band sized to never reject a
# genuine index move; only catches gross corruption (e.g. a mis-resolved
# token returning some other instrument's price).
_SPOT_MIN = 10_000.0
_SPOT_MAX = 150_000.0

# ATM-resolution coherence thresholds, expressed in multiples of chain_step_size.
_ATM_WARN_MULTIPLE = 1
_ATM_FAIL_MULTIPLE = 5

# Continuity self-consistency tolerance — mirrors the controller's own
# _CONTINUITY_TOLERANCE so a rule never disagrees with the value it is
# independently re-checking for internal consistency.
_CONTINUITY_TOLERANCE = 0.5

_CONTINUITY_FIRST = "FIRST"
_CONTINUITY_CONTIGUOUS = "CONTIGUOUS"
_CONTINUITY_GAP = "GAP"


@dataclass(frozen=True)
class ValidationFinding:
    """One rule's verdict for one ObservationRecord.

    rule_id identifies which rule produced this finding (stable across
    ruleset versions unless the rule itself is renamed). level is one of
    PASS/WARN/FAIL. message is a human-readable, non-secret description —
    safe to log or persist verbatim.
    """

    rule_id: str
    level: str
    message: str


# ── Rules ─────────────────────────────────────────────────────────────────────
# Each rule is a pure function: ObservationRecord -> ValidationFinding.
# No rule mutates its input or holds state between calls.


def _rule_identity_consistency(record: ObservationRecord) -> ValidationFinding:
    """R1 — every OptionQuote's expiry/underlying matches its parent record.

    Every quote's expiry must equal the ChainResult it was parsed onto, and
    every quote's underlying must equal the record's underlying. Generalises
    the VIX-token identity lesson (a value silently drifting from its label)
    to the option-chain data path. FAIL on any mismatch; PASS if there is
    nothing to check (no chains, or chains with no parsed quotes yet).
    """
    for chain in record.chains:
        for quote in chain.quotes:
            if quote.expiry != chain.expiry:
                return ValidationFinding(
                    rule_id=_RULE_IDENTITY_CONSISTENCY,
                    level=_FAIL,
                    message=(
                        f"quote expiry={quote.expiry!r} does not match "
                        f"parent chain expiry={chain.expiry!r}"
                    ),
                )
            if quote.underlying != record.underlying:
                return ValidationFinding(
                    rule_id=_RULE_IDENTITY_CONSISTENCY,
                    level=_FAIL,
                    message=(
                        f"quote underlying={quote.underlying!r} does not match "
                        f"record underlying={record.underlying!r}"
                    ),
                )
    return ValidationFinding(
        rule_id=_RULE_IDENTITY_CONSISTENCY,
        level=_PASS,
        message="all quote identities consistent with parent chain/record",
    )


def _rule_vix_plausibility(record: ObservationRecord) -> ValidationFinding:
    """R2 — VIX value is within a plausible band (defense in depth).

    Independently re-checks what VIXFetcher's L1 sanity check already
    guards, so this safety net does not depend on that fetcher-level
    constant staying correct. Skipped (PASS) when the VIX fetch itself was
    unsuccessful or carries no value — that is not this rule's concern.
    """
    vix = record.vix
    if not vix.success or vix.ltp is None:
        return ValidationFinding(
            rule_id=_RULE_VIX_PLAUSIBILITY,
            level=_PASS,
            message="vix fetch unsuccessful or no value — check skipped",
        )
    if _VIX_MIN <= vix.ltp <= _VIX_MAX:
        return ValidationFinding(
            rule_id=_RULE_VIX_PLAUSIBILITY,
            level=_PASS,
            message=f"vix.ltp={vix.ltp} within [{_VIX_MIN}, {_VIX_MAX}]",
        )
    return ValidationFinding(
        rule_id=_RULE_VIX_PLAUSIBILITY,
        level=_FAIL,
        message=f"vix.ltp={vix.ltp} outside plausible band [{_VIX_MIN}, {_VIX_MAX}]",
    )


def _rule_spot_plausibility(record: ObservationRecord) -> ValidationFinding:
    """R3 — BankNifty spot value is within a plausible historical band.

    Same defense-in-depth rationale as R2, for the spot index. Skipped
    (PASS) when the spot fetch itself was unsuccessful or carries no value.
    """
    spot = record.spot
    if not spot.success or spot.ltp is None:
        return ValidationFinding(
            rule_id=_RULE_SPOT_PLAUSIBILITY,
            level=_PASS,
            message="spot fetch unsuccessful or no value — check skipped",
        )
    if _SPOT_MIN <= spot.ltp <= _SPOT_MAX:
        return ValidationFinding(
            rule_id=_RULE_SPOT_PLAUSIBILITY,
            level=_PASS,
            message=f"spot.ltp={spot.ltp} within [{_SPOT_MIN}, {_SPOT_MAX}]",
        )
    return ValidationFinding(
        rule_id=_RULE_SPOT_PLAUSIBILITY,
        level=_FAIL,
        message=f"spot.ltp={spot.ltp} outside plausible band [{_SPOT_MIN}, {_SPOT_MAX}]",
    )


def _rule_atm_coherence(record: ObservationRecord) -> ValidationFinding:
    """R4 — resolved_atm is a coherent distance from anchoring_spot.

    Catches a step_size/config-resolution bug class. Graduated severity:
    within one chain_step_size is PASS, within _ATM_FAIL_MULTIPLE steps is
    WARN, beyond that is FAIL. chain_step_size<=0 is treated defensively
    (only PASS is reachable, since a zero/negative step never exceeds the
    WARN/FAIL thresholds below it) rather than raising.
    """
    meta = record.meta
    gap = abs(meta.resolved_atm - meta.anchoring_spot)
    step = meta.chain_step_size

    if step <= 0 or gap <= step * _ATM_WARN_MULTIPLE:
        return ValidationFinding(
            rule_id=_RULE_ATM_COHERENCE,
            level=_PASS,
            message=f"resolved_atm gap={gap} within {_ATM_WARN_MULTIPLE}x step_size={step}",
        )
    if gap <= step * _ATM_FAIL_MULTIPLE:
        return ValidationFinding(
            rule_id=_RULE_ATM_COHERENCE,
            level=_WARN,
            message=(
                f"resolved_atm gap={gap} exceeds {_ATM_WARN_MULTIPLE}x step_size={step} "
                f"but within {_ATM_FAIL_MULTIPLE}x"
            ),
        )
    return ValidationFinding(
        rule_id=_RULE_ATM_COHERENCE,
        level=_FAIL,
        message=f"resolved_atm gap={gap} exceeds {_ATM_FAIL_MULTIPLE}x step_size={step}",
    )


def _rule_chain_completeness(record: ObservationRecord) -> ValidationFinding:
    """R5 — every configured expiry has a successful chain result.

    Only meaningful when spot succeeded — chains are gated on spot upstream,
    so a spot-failure record's empty chains list is a known, separate
    condition, not a completeness defect (PASS, not applicable). WARN when
    some (not all) configured expiries failed; FAIL when spot succeeded but
    every configured expiry failed (a systemic chain-fetch defect, not one
    flaky expiry).
    """
    if not record.spot.success:
        return ValidationFinding(
            rule_id=_RULE_CHAIN_COMPLETENESS,
            level=_PASS,
            message="spot fetch unsuccessful — chain completeness not applicable",
        )

    expiry_set = record.meta.expiry_set
    if not expiry_set:
        return ValidationFinding(
            rule_id=_RULE_CHAIN_COMPLETENESS,
            level=_PASS,
            message="no expiries configured — nothing to check",
        )

    successful_expiries = {c.expiry for c in record.chains if c.success}
    missing = [e for e in expiry_set if e not in successful_expiries]

    if not missing:
        return ValidationFinding(
            rule_id=_RULE_CHAIN_COMPLETENESS,
            level=_PASS,
            message=f"all {len(expiry_set)} configured expiries successful",
        )
    if len(missing) == len(expiry_set):
        return ValidationFinding(
            rule_id=_RULE_CHAIN_COMPLETENESS,
            level=_FAIL,
            message=f"all {len(expiry_set)} configured expiries failed: {missing}",
        )
    return ValidationFinding(
        rule_id=_RULE_CHAIN_COMPLETENESS,
        level=_WARN,
        message=f"{len(missing)}/{len(expiry_set)} configured expiries failed: {missing}",
    )


def _rule_continuity_self_consistency(record: ObservationRecord) -> ValidationFinding:
    """R6 — the embedded continuity_status agrees with its own interval fields.

    Recomputes CONTIGUOUS/GAP from the record's own
    actual_interval_seconds/expected_interval_seconds (same ±50% tolerance
    the controller itself uses) and confirms it matches the embedded
    continuity_status — a self-consistency check on the record alone, not
    a claim about prior records. PASS when continuity is absent (ad-hoc
    construction) or FIRST (nothing to recompute against).
    """
    continuity = record.continuity
    if continuity is None:
        return ValidationFinding(
            rule_id=_RULE_CONTINUITY_CONSISTENCY,
            level=_PASS,
            message="no continuity metadata present — check skipped",
        )
    if continuity.continuity_status == _CONTINUITY_FIRST:
        return ValidationFinding(
            rule_id=_RULE_CONTINUITY_CONSISTENCY,
            level=_PASS,
            message="FIRST snapshot — nothing to recompute against",
        )

    actual = continuity.actual_interval_seconds
    expected = continuity.expected_interval_seconds
    if actual is None:
        return ValidationFinding(
            rule_id=_RULE_CONTINUITY_CONSISTENCY,
            level=_WARN,
            message=(
                f"continuity_status={continuity.continuity_status!r} but "
                f"actual_interval_seconds is None"
            ),
        )

    lower = expected * (1.0 - _CONTINUITY_TOLERANCE)
    upper = expected * (1.0 + _CONTINUITY_TOLERANCE)
    recomputed_status = _CONTINUITY_CONTIGUOUS if lower <= actual <= upper else _CONTINUITY_GAP

    if recomputed_status == continuity.continuity_status:
        return ValidationFinding(
            rule_id=_RULE_CONTINUITY_CONSISTENCY,
            level=_PASS,
            message=(
                f"continuity_status={continuity.continuity_status!r} consistent with "
                f"actual={actual}s vs expected={expected}s"
            ),
        )
    return ValidationFinding(
        rule_id=_RULE_CONTINUITY_CONSISTENCY,
        level=_WARN,
        message=(
            f"continuity_status={continuity.continuity_status!r} but recomputed "
            f"status={recomputed_status!r} from actual={actual}s vs expected={expected}s"
        ),
    )


# ── ValidationEngine ──────────────────────────────────────────────────────────


class ValidationEngine:
    """Runs the six frozen per-snapshot rules over one ObservationRecord.

    Pure — evaluate() performs no I/O, no logging, no persistence, no
    alerting. It is not wired into DiscoveryController, discovery_run.py, or
    any writer in this milestone.

    Usage::

        engine = ValidationEngine()
        findings = engine.evaluate(record)
        overall_fail = any(f.level == "FAIL" for f in findings)
    """

    def __init__(self) -> None:
        self._rules: list[tuple[str, Callable[[ObservationRecord], ValidationFinding]]] = [
            (_RULE_IDENTITY_CONSISTENCY, _rule_identity_consistency),
            (_RULE_VIX_PLAUSIBILITY, _rule_vix_plausibility),
            (_RULE_SPOT_PLAUSIBILITY, _rule_spot_plausibility),
            (_RULE_ATM_COHERENCE, _rule_atm_coherence),
            (_RULE_CHAIN_COMPLETENESS, _rule_chain_completeness),
            (_RULE_CONTINUITY_CONSISTENCY, _rule_continuity_self_consistency),
        ]

    @property
    def ruleset_version(self) -> int:
        """The VALIDATION_RULESET_VERSION this engine's rules implement."""
        return VALIDATION_RULESET_VERSION

    def evaluate(self, record: ObservationRecord) -> list[ValidationFinding]:
        """Run every rule over *record*.

        Always returns exactly one ValidationFinding per registered rule, in
        registration order. Never raises: a rule that raises is caught and
        recorded as a FAIL finding for that rule, and every other rule still
        runs normally.
        """
        findings: list[ValidationFinding] = []
        for rule_id, rule in self._rules:
            try:
                findings.append(rule(record))
            except Exception as exc:  # noqa: BLE001 — a rule must never crash evaluate()
                findings.append(
                    ValidationFinding(
                        rule_id=rule_id,
                        level=_FAIL,
                        message=f"rule raised {type(exc).__name__}",
                    )
                )
        return findings
