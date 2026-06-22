# Project Charter

> **Status:** DRAFT — not in force until a ratification entry exists in the Decision Log.
> **Version:** 0 (pre-ratification)
> **Authority:** This document is supreme over all implementation decisions. Where any code or
> configuration conflicts with what is written here, the charter governs and the code must change.

---

## 1. Mission

The BankNifty Observatory is a long-term quantitative research instrument. Its primary product is
**trustworthy evidence** about the behaviour of the BankNifty index and its options ecosystem.

Its long-term goal is to determine whether BankNifty contains statistically defensible and repeatable
patterns that could, with sufficient evidence, justify strategy research, paper trading, and eventually
production trading. It begins — and may remain indefinitely — as an observatory. Strategy is a possible
consequence of evidence, never a premise.

## 2. What this project is

- A continuously operating instrument that observes, validates, stores, derives, labels, and measures
  BankNifty market data.
- An evidence-generation system whose outputs are reproducible, lineage-tracked, and auditable for years.
- A platform that is **complete and valuable at the observatory stage**, even if no strategy is ever built.

## 3. What this project is NOT

- **Not a trading bot.** No execution, no order placement, no capital at risk during the observatory life.
- **Not a port or clone of any prior system.** No market assumption, threshold, indicator, or conclusion is
  inherited from any other instrument or codebase.
- **Not a notebook or script.** This is production-grade research infrastructure.
- **Not complete when it makes money.** Success is achieved when it produces evidence good enough to bet on
  — including the evidence that there is nothing to bet on.

## 4. Non-negotiables

These may not be weakened. They may only be clarified or strengthened by an amendment that records the
prior text, new text, rationale, and date in the Decision Log. Weakening any non-negotiable terminates the
project's claim to being evidence-first and must be recorded as such.

1. **Assume no edge exists.** Everything is earned through evidence.
2. **Observed data and derived interpretation are separate.** Every derived value is pinned to a versioned
   methodology. Changing a methodology creates a new version — it does not overwrite.
3. **No opportunity label is produced without a ratified cost-model version.** Labeling without a
   cost model conflates gross movement with net opportunity.
4. **Raw data is immutable, append-only, and replicated off-instance.** It is the one irreplaceable asset.
5. **The platform automates measurement, never interpretation.** Hypothesis promotion, methodology changes,
   and "this is edge" conclusions require human sign-off and a gate.
6. **Operational health and data integrity are alarmed separately.** A silent data gap is as serious
   as a system crash.
7. **Rejected hypotheses are retained forever** and may not be resurrected without new mechanism or new data.
8. **No stage is entered without meeting pre-committed exit criteria.** Stage gates are written before
   the data is collected, not after.

## 5. Success definition

- **Primary success:** a trustworthy, reproducible, multi-regime evidence corpus.
- **Equally valid success:** a well-evidenced conclusion that no defensible edge exists for us, reached
  without lowering the evidence standard. This saves capital and is a win, not a failure.

## 6. Program-level null hypothesis and kill condition

The program maintains a pre-committed null hypothesis about itself:

> *"BankNifty contains no opportunity that survives this program's evidence standard, net of measured
> cost, across regimes."*

The conditions under which this null is accepted — and the program is wound down or narrowed — are
defined before data collection begins and are recorded in the Decision Log. The program is forbidden from
quietly redefining success to avoid confronting its own null.

## 7. Scope boundaries

**In scope for Phase 1:**
- BankNifty spot, near-month options, and the metrics derivable from them (OI, PCR, IV, greeks, regime)
- Infrastructure to collect, persist, and quality-check that data continuously

**Out of scope now, gated for future phases:**
- Any other instrument or index
- Live order placement or capital deployment
- Strategy, paper trading, execution, risk, and portfolio engines
- Comparison to external benchmarks

## 8. Change control

Amendments to this charter require a Decision Log entry that states:
- The prior text verbatim
- The new text
- The rationale
- The date and approver

The Non-Negotiables section may not be weakened.
