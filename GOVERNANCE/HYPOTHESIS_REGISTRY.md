# HYPOTHESIS_REGISTRY

> **Control Block**
> - **Purpose:** Govern how hypotheses are created, pre-registered, tested, and rejected — and ensure every hypothesis ever tested (especially the rejected ones) is retained permanently.
> - **Why it exists:** Pre-registration is the primary defense against p-hacking and confirmation bias. The registry is also the anti-noise asset: it stops the program from re-discovering the same noise next quarter and calling it new. Rejected hypotheses are the most valuable records the program owns.
> - **Approval required:** A hypothesis is *admitted* by research governance before any test data is touched. Promotion of a *result* follows [[EVIDENCE_STANDARD]] and [[STAGE_GATE_POLICY]].
> - **Change-control:** Registry entries are append-only. A registered hypothesis is never edited or deleted; status transitions (registered → tested → verdict) are appended. Resurrection of a rejected hypothesis requires a *new* entry citing new mechanism or new data.
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. Required Sections (per hypothesis entry)

1. ID and registration date
2. Falsifiable claim
3. Structural mechanism + identified counterparty
4. Pre-declared success metric and threshold
5. Sample / period / regimes to be used
6. Pre-declared stopping rule
7. Holdout designation (sealed)
8. Status and verdict (appended later)

## 2. Creation Rules

- Hypotheses originate from **descriptive observations** (Stage 2/3), never from imported beliefs. "BankNifty does X" must be something *seen*, not *expected*.
- A hypothesis with **no plausible mechanism or counterparty is rejected at creation**, before any test.
- Registration happens **before test data is touched.** A retroactive hypothesis is not a hypothesis.

## 3. Testing Rules

- Strict train / validation / **sealed holdout**; the holdout is touched **once** and every touch is logged. A peeked holdout is burned and recut.
- Tested **across regimes separately**, not pooled.
- **Cost model mandatory** (ratified version).
- **Multiple-testing tracked.** The registry maintains a running count of tests; significance bars adjust accordingly.
- **Adversarial robustness:** perturb parameters, sub-periods, assumptions; fragility implies overfit.

## 4. Rejection Rules

- **Rejection is the default and expected outcome.** A registry with few rejections is broken.
- Rejected hypotheses are **retained forever**, dated, with reasons.
- **No resurrection without new evidence** — a new mechanism or new data, as a new entry. Tweaking-until-it-passes is prohibited.
- "Almost worked" is **rejected**, not "promising." No partial credit in inference.

## 5. Multiplicity Ledger

The registry includes a running **test-count ledger** so the program always knows how many shots it has taken. This ledger feeds the multiplicity adjustment in [[EVIDENCE_STANDARD]].

## 6. Example Registry Entry (illustrative)

```
id: HYP-2026-11-014
registered: 2026-11-09
claim: Under <observable ex-ante state S>, the net-of-cost forward displacement
       distribution at the 900s horizon shifts vs. its unconditional baseline.
mechanism: <named structural reason>; counterparty: <who pays, why they persist>
success_metric: pre-declared effect size, net of cost, with CI excluding barrier
sample: <period>; regimes tested separately: [trending, ranging, high_vol, expiry]
stopping_rule: <pre-declared>
holdout: <sealed period>, single touch
status_history:
  - 2026-11-09 registered
  - 2026-11-20 tested
  - 2026-11-22 verdict: REJECTED (failed holdout) -> retained, see DL-2026-11-22-003
```
