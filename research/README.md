# research/ — Layer 5: Research Pipeline

**Owner:** Quant Research
**Change gate:** Governance review for anything affecting what evidence means

## Responsibility

Assembles the observation corpus, applies net-of-cost labeling (gated), and produces evidence records with full lineage. This is the layer where captured market observations become testable research artifacts.

## What lives here

| Submodule | Purpose |
|-----------|---------|
| `observations/` | Observation builder: assembles state-at-time-T records from curated + derived |
| `labeling/` | Net-of-cost forward realized displacement labeler — **dormant until activated** |
| `evidence/` | Evidence record assembly with full lineage |
| `hypothesis_registry/` | Pre-registration and lifecycle of research hypotheses |

## The labeling gate

`research/labeling/` is present but dormant. It will not produce output until:

1. `BNO_COST_MODEL_VERSION` is set to a ratified cost model version.
2. `BNO_LABELING_ACTIVE=true` is set.
3. Both conditions are validated at startup; missing either causes a clean exit.

The cost model version is ratified via a DECISION_LOG entry. See [`GOVERNANCE/STAGE_GATE_POLICY.md`](../GOVERNANCE/STAGE_GATE_POLICY.md).

## The Stage-2/Stage-4 firewall

Labels are unconditional continuous values — net-of-cost forward realized displacement as a signed magnitude. **No binary classification. No direction filter. No embedded thresholds.** Conditioning is hypothesis testing, done later by query against the evidence corpus. See [`GOVERNANCE/OPPORTUNITY_DEFINITION.md`](../GOVERNANCE/OPPORTUNITY_DEFINITION.md).

## Evidence lineage requirement

Every evidence record traces: observation → curated source records → raw record IDs → cost_model_version → methodology_versions → quality_score. Lineage is not optional.
