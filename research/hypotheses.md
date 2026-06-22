# Hypothesis Registry

A permanent record of all research hypotheses: active, confirmed, rejected, and retired.

**Rules:**
- Every hypothesis is registered here before any data is examined to test it.
- A hypothesis may not be modified after data examination begins. If a refinement is needed,
  retire the old hypothesis and register a new one.
- Rejected hypotheses are retained forever. They may only be resurrected with new data or a new
  proposed mechanism — not with a lower evidence threshold.
- The program-level null hypothesis is listed first and is never retired.

---

## Program-level null hypothesis

> **H-NULL: BankNifty contains no opportunity that survives this program's evidence standard,
> net of measured cost, across regimes.**

This is the default assumption. It is rejected only if one or more specific hypotheses reach
the Phase 2 exit criteria. It is confirmed by the accumulation of rejected or inconclusive
hypotheses across multiple regimes. Confirmation of H-NULL is a successful program outcome.

---

## Hypothesis entry format

```
### H-NNN — Title
**Status:** [ACTIVE | CONFIRMED | REJECTED | RETIRED]
**Registered:** YYYY-MM-DD
**Closed:** YYYY-MM-DD (if closed)
**Mechanism:** The proposed causal or structural reason this pattern would exist.

**Testable claim:**
A precise, falsifiable statement. If X is observed under conditions Y, then Z should follow.

**Rejection criteria (written before any test is run):**
Exact conditions under which this hypothesis is rejected.

**Evidence references:**
Links to entries in evidence_log.md (format: E-NNN).

**Notes:**
Observations, regime caveats, or context that does not constitute evidence.
```

---

## Active hypotheses

*No active hypotheses yet. Phase 1 data collection is in progress.*

---

## Closed hypotheses

*None yet.*

---

<!-- Register new hypotheses above the "Closed hypotheses" section. -->
<!-- Closed hypotheses move to the "Closed hypotheses" section and are never deleted. -->
