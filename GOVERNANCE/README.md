# GOVERNANCE — BankNifty Observatory Platform

This directory is the program's constitution. It exists **before** implementation and governs it. No code, schema, collector, or label is built until the documents below are ratified.

The **[[PROJECT_CHARTER]] is supreme.** Where any document conflicts with it, the charter governs.

## Reading / Ratification Order

Ratify top-down — each depends on the ones above it.

| # | Document | Governs | Status |
|---|---|---|---|
| 1 | [PROJECT_CHARTER](PROJECT_CHARTER.md) | mission, non-negotiables, program-level null | DRAFT |
| 2 | [DATA_CONTRACT](DATA_CONTRACT.md) | what data, what fidelity, what quality | DRAFT |
| 3 | [OPPORTUNITY_DEFINITION](OPPORTUNITY_DEFINITION.md) | the single research target | DRAFT |
| 4 | [METHODOLOGY_VERSIONING_POLICY](METHODOLOGY_VERSIONING_POLICY.md) | every derived value | DRAFT |
| 5 | [EVIDENCE_STANDARD](EVIDENCE_STANDARD.md) | weak vs. strong evidence | DRAFT |
| 6 | [HYPOTHESIS_REGISTRY](HYPOTHESIS_REGISTRY.md) | how hypotheses live and die | DRAFT |
| 7 | [DECISION_LOG_TEMPLATE](DECISION_LOG_TEMPLATE.md) | the append-only memory | DRAFT |
| 8 | [DATA_INCIDENT_POLICY](DATA_INCIDENT_POLICY.md) | gaps, corruption, integrity | DRAFT |
| 9 | [STAGE_GATE_POLICY](STAGE_GATE_POLICY.md) | promotion between stages | DRAFT |
| 10 | [REPOSITORY_RULES](REPOSITORY_RULES.md) | structure as enforcement | DRAFT |

## The Three Load-Bearing Principles

1. **Observed ≠ derived.** Every interpretation is version-pinned. (Docs 2, 4)
2. **No label without a cost model; no conditioning in labels.** (Doc 3)
3. **Raw is immutable and off-instance; silent gaps alarm as loudly as crashes.** (Docs 2, 8)

## Ratification

Phase 0 is complete when every document above is moved from **DRAFT** to **IN FORCE** via a dated entry in the live DECISION_LOG (instantiated from Doc 7). Implementation (Stage 1 work) may not begin before that.

> Status of the package as a whole: **DRAFT — awaiting ratification.**
