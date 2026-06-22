# STAGE_GATE_POLICY

> **Control Block**
> - **Purpose:** Define the stages of the program, the pre-committed exit and failure criteria for each, and the authority required to promote between them.
> - **Why it exists:** Without pre-committed gates, a research program only ever advances — it rationalizes its way forward and lowers standards to "succeed." Gates written before a stage's work begins make promotion an objective event, not a judgment made while invested in the outcome. Failure criteria matter as much as exit criteria.
> - **Approval required:** Promotion requires the project owner's sign-off against pre-committed criteria. The researcher who produced a stage's results may not be its sole promoter.
> - **Change-control:** A stage's criteria may not be edited after that stage's work has begun without a DECISION_LOG entry justifying the change and resetting any dependent results. Strengthening is always allowed; weakening is a logged, owner-signed exception.
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. Promotion Principles

- Criteria are **pre-committed** before a stage's work starts.
- Promotion requires meeting **exit criteria**; hitting a **failure criterion** halts or returns.
- **A well-evidenced "no edge" at Stage 4 is a successful terminal outcome**, not a failure to push through.
- Activation of any sealed future module is itself a gated, logged event.

## 2. The Stages

**Stage 1 — Research Foundation.** *Exit:* all Phase 0 governance ratified; separated infra; data contract in force. *Failure:* tempted to collect before governance exists.

**Stage 2 — Market Observatory.** *Exit:* validated, regime-diverse capture; quality scores trusted; **cost model ratified**; depth data present. *Failure:* unquantifiable gaps; no depth; no derivable cost model.

**Stage 3 — Opportunity Labeling.** *Exit:* unconditional net-of-cost labeling live; reproducible, lineage-tracked evidence corpus accruing. *Failure:* labeling attempted without a cost-model version; firewall breaches.

**Stage 4 — Hypothesis Testing.** *Exit:* ≥1 hypothesis clears [[EVIDENCE_STANDARD]] end-to-end. *Failure:* nothing survives honest testing → **invoke the program-level null; valid success; do not lower standards.**

**Stage 5 — Strategy Research.** *Exit:* a cost-robust, capacity-aware approach survives adversarial review and stress regimes. *Failure:* edge collapses under capacity/cost scaling → return to Stage 4. *(Activates sealed strategy module.)*

**Stage 6 — Paper Trading.** *Exit:* live execution behaviour matches modeled cost/edge within pre-declared tolerance, ₹0 at risk. *Failure:* live slippage exceeds model → return to Stage 2 (the cost model was wrong).

**Stage 7 — Production.** *Exit:* sustained out-of-sample live performance within tolerance, with edge-decay monitoring and kill switches active. *Failure:* decay/divergence beyond tolerance → automatic de-risk, return to research.

## 3. The Universal Rule

Advancement requires meeting criteria written *before* the stage's work began. No criterion is edited after seeing the stage's results without a logged, justified DECISION_LOG entry and reset of dependent results.

## 4. Example Promotion Record (illustrative)

```
gate: Stage 2 -> Stage 3
date: 2026-10-15
exit_criteria_met:
  - multi-regime capture sustained (trending, ranging, high_vol, expiry)
  - quality scores trusted; completeness within baseline
  - cost_model v1 ratified (DL-2026-10-12-001)
  - depth data present and validated
promoter: project owner
producer_self_rebuttal: attached ("how would I argue this is premature")
decision_log_ref: DL-2026-10-15-004
```
