# derivation/ — Layer 4: Versioned Derivation Framework

**Owner (methodologies/):** Research Governance — changes require DECISION_LOG entry
**Owner (pipeline/):** Platform / Data Engineering
**Change gate:** Methodology changes = DECISION_LOG entry + recompute assessment

## Responsibility

Computes derived metrics from curated data. Every derived value is permanently pinned to the methodology version that produced it. Derived values live in the `derived` schema only — never in `raw` or `curated`.

## What lives here

| Submodule | Purpose |
|-----------|---------|
| `methodologies/iv/` | Implied volatility computation (versioned) |
| `methodologies/greeks/` | Option greeks (versioned) |
| `methodologies/pcr/` | Put/call ratio (versioned) |
| `methodologies/term_structure/` | Term structure computation (versioned) |
| `methodologies/regime/` | Regime classification (versioned, descriptive only) |
| `pipeline/` | Post-session derivation job orchestration |

## The observed/derived seam

This is the hard boundary that separates what was observed from what was computed. It is enforced by:
1. Separate DB schemas (`curated` vs `derived`)
2. Separate directory trees (`acquisition/` vs `derivation/`)
3. Explicit prohibition in [`GOVERNANCE/REPOSITORY_RULES.md`](../GOVERNANCE/REPOSITORY_RULES.md)

**A derived value may never be stored in the `raw` or `curated` schema.** This is not a convention — it is a permission-enforced database rule.

## Versioning rule

Every derived record carries `methodology_version`. Changing the methodology creates new records. It never overwrites existing ones. See [`GOVERNANCE/METHODOLOGY_VERSIONING_POLICY.md`](../GOVERNANCE/METHODOLOGY_VERSIONING_POLICY.md).

## Regime tags

Regime tags are descriptive classifications produced by `methodologies/regime/`. They are not labels, not outcomes, and not conditioning variables. They describe the market environment at observation time. Any change to the regime classification methodology is a DECISION_LOG event.
