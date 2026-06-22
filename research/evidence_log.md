# Evidence Log

A permanent record of evidence collected against each registered hypothesis.

**Rules:**
- Evidence entries are linked to a specific hypothesis (H-NNN).
- Each entry records the dataset used, the methodology version, the test performed, the result,
  and whether the result supports, contradicts, or is inconclusive with respect to the hypothesis.
- Evidence may not be collected against a hypothesis that has not been registered.
- Evidence collected using a different methodology version creates a separate entry.
- The evidence standard (minimum sample size, statistical thresholds, regime coverage) is defined
  in the governance documents before any evidence entry can be created.

---

## Evidence entry format

```
### E-NNN — Hypothesis H-NNN: [one-line hypothesis title]
**Date:** YYYY-MM-DD
**Hypothesis:** H-NNN
**Dataset:** Date range, session count, regime coverage
**Methodology version:** [Version string or "not yet versioned"]
**Test performed:** What was measured and how.

**Result:**
Quantitative result. Include confidence intervals, sample sizes, and regime breakdown.

**Verdict:**
[Supports | Contradicts | Inconclusive] the hypothesis, per the evidence standard.

**Notes:**
Caveats, data quality issues, or context that does not change the verdict but should be
considered when reviewing this entry.
```

---

## Evidence log

*No evidence entries yet. Awaiting Phase 1 data and cost model ratification (required for
labeling).*

---

## Evidence standard summary

*The evidence standard has not yet been ratified. Until it is, no evidence entry can reach a
binding "Confirms" or "Rejects" verdict. This section will be populated with the ratified
thresholds once D-00X (evidence standard ratification) is recorded in the Decision Log.*

---

<!-- Evidence entries are append-only. Do not edit past entries. -->
