# Roadmap

Phases are sequential and gated. A phase does not begin until the prior phase's exit criteria are met
and recorded in the Decision Log. Exit criteria are written before data collection starts, not after.

---

## Phase 0 — Infrastructure and governance  `[IN PROGRESS]`

**Goal:** Establish the foundation that makes evidence trustworthy before any data is collected.

**Exit criteria:**
- [ ] Project charter ratified (Decision Log entry)
- [ ] Evidence standard ratified
- [ ] Stage gate policy ratified
- [ ] Data collection pipeline passing smoke tests
- [ ] Data integrity monitoring active
- [ ] Off-instance replication confirmed

**Deliverables:**
- Governance document package
- Configuration framework with secret-safe credential handling
- Data collection infrastructure (market data snapshots)
- JSONL + database persistence layer
- Logging and alerting pipeline

---

## Phase 1 — Continuous data collection  `[IN PROGRESS]`

**Goal:** Accumulate a trustworthy, multi-session, multi-regime dataset covering at least one full
expiry cycle. Breadth over analysis; no derived conclusions yet.

**Exit criteria:**
- [ ] Minimum N trading sessions of clean snapshot data (N defined in Decision Log before Phase 1 starts)
- [ ] Data completeness above threshold across all sessions
- [ ] Data quality report reviewed and accepted
- [ ] At least one full monthly expiry cycle captured

**Deliverables:**
- Raw JSONL archive of every snapshot
- Session completeness dashboard
- Data quality report

---

## Phase 2 — Hypothesis development and testing  `[NOT STARTED]`

**Goal:** Form structured, falsifiable hypotheses about BankNifty behaviour. Test them against the
Phase 1 corpus. Do not act on patterns; characterise them.

**Pre-condition:** Phase 1 exit criteria met, cost model ratified (required for labeling).

**Guiding constraint:** Every hypothesis must state the conditions under which it would be rejected
before any test is run.

**Exit criteria (gate into Phase 3):**
- At least one hypothesis has reached statistical significance threshold (defined in advance)
- All tested hypotheses — whether confirmed or rejected — are recorded in the Evidence Log
- No hypothesis has been modified after seeing the data that was used to test it

---

## Phase 3 — Pattern characterisation  `[NOT STARTED]`

**Goal:** Move from binary pass/fail hypothesis results to characterising the regime-dependence,
stability, and magnitude of confirmed patterns.

**Pre-condition:** At least one hypothesis reaches Phase 2 exit criteria.

---

## Gated stages (not phases — require explicit unlock)

These are not time-based milestones. They are locked by policy and require both evidence AND explicit
sign-off against pre-committed criteria. They are listed here only to show that the path exists.

| Stage | Gate condition |
|---|---|
| Paper trading | Pattern characterised, edge estimate with confidence interval, risk controls designed |
| Live trading | Paper trading results meet pre-committed criteria over sufficient time |

**These stages may never be reached.** The null hypothesis may be confirmed in Phase 2, in which case
the program concludes successfully at that point.

---

## What is not on this roadmap

- Real-time signal generation
- Automated trading decisions
- Portfolio management
- Integration with any brokerage beyond read-only market data access
