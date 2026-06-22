# EVIDENCE_STANDARD

> **Control Block**
> - **Purpose:** Fix, in advance, what counts as weak vs. strong evidence and the statistical standards a finding must meet — before any finding exists to lobby for softer standards.
> - **Why it exists:** The dominant failure mode of a self-run research program is manufacturing a convincing false positive and then negotiating the standard downward to accept it. Committing the standard now externalizes that conflict into process. The program is judged by the quality of what it rejects.
> - **Approval required:** Quant research director + research governance. Ratified via DECISION_LOG.
> - **Change-control:** The standard may be *strengthened* freely. *Weakening* it requires a DECISION_LOG entry justifying why, signed by the project owner, and an explicit note that prior conclusions must be re-evaluated under the change. A standard changed *after* seeing a result it would affect is presumed invalid.
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. Required Sections

1. Weak-evidence definition
2. Strong-evidence definition
3. Statistical standards
4. The false-positive asymmetry
5. Mandatory disqualifiers

## 2. Weak Evidence (hypothesis-generating only, never a verdict)

Any one of these makes a result weak:
- In-sample only, or no sealed holdout
- No cost model applied (gross result)
- Single regime
- Discovered after the fact (no pre-registration)
- No structural mechanism / no identified counterparty
- Sensitive to small parameter or sub-period changes
- "Almost significant" after dropping inconvenient periods

**A good-looking backtest is weak evidence by default.**

## 3. Strong Evidence (promotable)

All of the following, together:
- **Pre-registered** before touching test data ([[HYPOTHESIS_REGISTRY]])
- Survives a **sealed holdout touched exactly once**
- Survives **across multiple regimes tested separately**, not pooled
- **Net of measured BankNifty cost** (ratified cost-model version)
- **Robust** to parameter and sub-period perturbation
- Survives **multiple-testing correction** given the program's running test count
- Has a **named structural mechanism and counterparty**
- **Reproducible from raw** by an independent re-run

## 4. Statistical Standards

- **Economic significance over p-values.** An edge smaller than the spread is noise dressed as signal.
- **Significance thresholds pre-declared and multiplicity-adjusted.** The more ideas tested, the higher the bar each must clear.
- **Out-of-sample is the arbiter.** Report in-sample and holdout; weight the holdout.
- **Confidence intervals and estimate stability**, not point estimates. A CI straddling "below cost" is not an edge.
- **Effective sample size, not row count.** Options data is autocorrelated and event-clustered; treat naive n with suspicion.
- **Honest base rates.** At p<0.05 across 100 ideas, expect ~5 false winners; the bar accounts for shots taken.

## 5. The False-Positive Asymmetry

A false "no edge" costs a missed opportunity. A false "edge" costs real capital, conviction, and months of misdirected work. **Every standard is biased toward making false positives expensive to produce and cheap to detect.**

## 6. Mandatory Disqualifiers

A finding is automatically rejected if: it has no mechanism; it required post-hoc period selection; it cannot be reproduced from raw; it used an unversioned derivation; or it was produced without a ratified cost-model version.

## 7. Example Evidence Verdict (illustrative)

```
hypothesis_ref: HYP-2026-11-014
classification: WEAK
reasons:
  - survived in-sample and validation
  - FAILED single-touch holdout (effect halved, CI crossed cost barrier)
  - mechanism plausible but counterparty unidentified
disposition: rejected; retained permanently; no resurrection without new data
decision_log_ref: DL-2026-11-22-003
```
