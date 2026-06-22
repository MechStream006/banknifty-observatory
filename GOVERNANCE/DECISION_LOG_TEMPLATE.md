# DECISION_LOG_TEMPLATE

> **Control Block**
> - **Purpose:** Provide the fixed format for the append-only record of every material decision in the program, and define what must be logged.
> - **Why it exists:** Over a multi-year horizon, memory and rationalization replace facts. The decision log is the program's external memory and, for a solo or small team, its substitute for a second pair of eyes. When you later ask "why did we threshold it this way," the answer must *exist*, not be reconstructed (i.e., rationalized after the fact).
> - **Approval required:** Entries are authored by whoever made the decision and counter-noted by governance for anything affecting evidence, methodology, or promotion. The log itself needs no approval to append — appending is mandatory.
> - **Change-control:** **Append-only. Entries are never edited or deleted.** A superseded decision is corrected by a *new* entry that references the old one. Editing history is a governance violation.
> - **Status:** DRAFT (template).
> - **Version:** 0

---

## 1. What Must Be Logged

- Ratification or amendment of any governance document
- Any methodology version change ([[METHODOLOGY_VERSIONING_POLICY]])
- Any cost-model ratification or change
- Any change to the opportunity definition or label spec
- Any stage promotion or stage failure ([[STAGE_GATE_POLICY]])
- Any change to the evidence standard
- Any data incident of material severity ([[DATA_INCIDENT_POLICY]])
- Any activation of a previously sealed future module
- Any decision that changes what evidence *means*

## 2. Required Fields (per entry)

1. **ID** — `DL-YYYY-MM-DD-NNN`
2. **Date**
3. **Author / role**
4. **Decision** — what was decided, stated plainly
5. **Context** — what prompted it
6. **Rationale** — why this choice over alternatives
7. **Impact** — what it changes (data, methodology, evidence, scope)
8. **Supersedes / references** — prior entries or documents affected
9. **Reversibility** — how to undo, if applicable

## 3. Rules

- One decision per entry.
- Entries are immutable once written.
- Every governance document amendment must cite its DECISION_LOG ID and vice versa.
- The log is mirrored into platform metadata so it is queryable alongside the data it governs.

## 4. Example Entry (illustrative)

```
id: DL-2026-09-10-002
date: 2026-09-10
author: research governance
decision: Ratify implied_volatility methodology v2; deprecate v1 for new computation.
context: v1 produced unstable IV in the final pre-expiry session.
rationale: v2's near-expiry quote handling is validated against <checks>; v1 retained
           for lineage of prior records.
impact: triggers recompute of IV-dependent derived + evidence; comparability note added.
supersedes: methodology iv v1 (retained, not deleted)
references: METHODOLOGY_VERSIONING_POLICY, DATA_CONTRACT v1
reversibility: revert to v1 by re-pinning; would require its own log entry + recompute.
```
