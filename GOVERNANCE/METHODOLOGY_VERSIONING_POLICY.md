# METHODOLOGY_VERSIONING_POLICY

> **Control Block**
> - **Purpose:** Govern every *derived* value (IV, greeks, PCR, regime tags, term structure, cost model) so that each is pinned to an explicit, versioned methodology and the multi-year dataset stays internally consistent.
> - **Why it exists:** Derived values are interpretations, not observations. A silent change to an IV or greek calculation in month 4 corrupts all prior "observations" while they still look fine. Versioning makes interpretation reproducible, replaceable, and auditable — and protects the program's single most under-appreciated risk: a dataset that is inconsistent with itself.
> - **Approval required:** Research governance (methodology correctness) + quant research director. Ratified via DECISION_LOG.
> - **Change-control:** Methodology changes are governed events. A new version never overwrites an old one; both persist. Evidence records cite the version they used. Changes that affect evidence trigger controlled recompute. Silent recalculation is prohibited.
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. Scope

Applies to **all derived data**. Observed data is out of scope (it is captured, not computed). The observed/derived boundary is defined in [[DATA_CONTRACT]].

## 2. Core Rules

1. **Every derived value has a methodology spec** stating inputs, calculation approach, assumptions, and known limitations — in prose, not code.
2. **Every derived value is stamped with its `methodology_version`** at the point of computation.
3. **Versions are immutable and additive.** v2 does not replace v1; both are retained as long as any evidence references them.
4. **No evidence record may reference an unversioned derivation.**
5. **A methodology change is a DECISION_LOG event** with: what changed, why, which prior version, the comparability impact, and the recompute plan.

## 3. Required Sections of a Methodology Spec

1. Name and version
2. Inputs (observed fields + their data-contract version)
3. Calculation approach (prose)
4. Assumptions and where they may fail
5. Known limitations
6. Validation evidence (how the methodology was checked)
7. Changelog vs. prior version

## 4. The Cost Model Is a Methodology

The cost model is a derived methodology with the **highest governance weight**: changing it invalidates the comparability of all net-of-cost labels produced under the prior version and triggers recompute. A cost-model version must be ratified before any labeling occurs ([[OPPORTUNITY_DEFINITION]]).

## 5. Recompute Policy

- When a methodology version changes, affected **derived** and **evidence** records are recomputed under the new version; prior-version records are retained, not deleted.
- Recompute is a logged, reproducible operation, run on settled data, never racing live capture.

## 6. Comparability Rule

Two evidence records are only directly comparable if they share methodology versions for every derivation they depend on. Cross-version comparisons must be explicitly justified and logged.

## 7. Example Methodology Changelog Entry (illustrative)

```
methodology: implied_volatility
version: 2  (supersedes 1)
date: 2026-09-10
change: switched root-finding tolerance and handling of near-expiry quotes
reason: v1 produced unstable IV in the final session before expiry
comparability_impact: IV-dependent evidence after labeling must be recomputed;
                      pre-label exploratory observations annotated, not deleted
recompute_plan: rebuild derived.iv and dependent evidence for full history
decision_log_ref: DL-2026-09-10-002
```
