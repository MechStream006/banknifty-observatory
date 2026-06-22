# PROJECT_CHARTER

> **Control Block**
> - **Purpose:** Define what the BankNifty Observatory Platform is, what it is not, and the immovable principles every other document inherits.
> - **Why it exists:** To prevent mission drift over a multi-year horizon. When a tempting result or a delivery deadline pressures the team to cut a corner, the charter is the fixed reference that says whether the corner is allowed to be cut. It is the constitution; all other governance documents are subordinate to it.
> - **Approval required:** Project owner. Ratification is a dated DECISION_LOG entry. The charter is in force only once that entry exists.
> - **Change-control:** Amendments require a DECISION_LOG entry stating the prior text, new text, rationale, and date. The **Non-Negotiables** section (below) may not be weakened — only clarified or strengthened. Weakening any non-negotiable terminates the program's claim to being evidence-first and must be recorded as such.
> - **Status:** DRAFT — not in force until ratified.
> - **Version:** 0 (pre-ratification)

---

## 1. Mission

The BankNifty Observatory Platform is a long-term quantitative **research instrument** whose primary product is **trustworthy evidence** about the behaviour of the BankNifty index and its options ecosystem.

Its long-term objective is to determine whether BankNifty contains **statistically defensible and repeatable opportunities** that could justify strategy research, paper trading, and eventually production trading.

It begins, and may remain indefinitely, as an **observatory**. Strategy is a possible consequence of evidence, never an assumption.

## 2. What This Project Is

- A continuously operating instrument that observes, validates, stores, derives, labels, and measures BankNifty market data.
- An evidence-generation system whose outputs are reproducible, lineage-tracked, and auditable for years.
- A platform that is **complete and valuable at the observatory stage**, even if no strategy is ever built.

## 3. What This Project Is NOT

- It is **not** a trading bot. No execution, no order placement, no capital at risk during the observatory life.
- It is **not** a port, clone, or descendant of any prior trading system. No market assumption, threshold, indicator, or conclusion is inherited from any other instrument or codebase.
- It is **not** a notebook or a script. It is production-grade infrastructure.
- It is **not** complete when it makes money — it is successful when it produces evidence good enough to bet on, **including the evidence that there is nothing to bet on.**

## 4. Non-Negotiables (may not be weakened)

1. **Assume no edge exists.** Everything is earned through evidence.
2. **Observed data and derived interpretation are separate.** Every derived value is pinned to a versioned methodology. (See [[METHODOLOGY_VERSIONING_POLICY]].)
3. **No net-of-cost label is produced without a ratified cost-model version.** (See [[OPPORTUNITY_DEFINITION]].)
4. **Raw data is immutable, append-only, and replicated off-instance.** It is the one irreplaceable asset.
5. **The platform automates measurement, never interpretation.** Promotion, methodology changes, and "this is edge" conclusions require a human and a gate.
6. **Operational health and data integrity are alarmed separately.** A silent data gap is as serious as a crash.
7. **Rejected hypotheses are retained forever** and are not resurrected without new mechanism or new data.
8. **No stage is entered without meeting pre-committed exit criteria.** (See [[STAGE_GATE_POLICY]].)

## 5. Success Definition

- **Primary success:** a trustworthy, reproducible, multi-regime evidence corpus.
- **Equally valid success:** a well-evidenced conclusion that **no defensible edge exists for us**, reached without lowering standards. This saves capital and is a win, not a failure.

## 6. Program-Level Null & Kill Condition

The program maintains a pre-committed **null hypothesis about itself**: *"BankNifty contains no opportunity that survives this program's evidence standard, net of measured cost, across regimes."*

The conditions under which this null is accepted — and the program is wound down or narrowed — are defined now, while sunk cost is zero, and recorded in the DECISION_LOG. The program is forbidden from quietly redefining success to avoid confronting its own null.

## 7. Scope Boundaries

- **In scope:** BankNifty spot, options, and the metrics derivable from them.
- **Out of scope (this phase):** any other instrument; comparison to any other index; live order placement; capital deployment.
- **Future, gated, inert today:** strategy, paper, execution, risk, and portfolio engines exist only as sealed extension points.

## 8. Roles & Authority

- **Project owner** — ratifies the charter, owns the program-level null, holds final promotion authority.
- **Research governance** — enforces evidence and methodology standards; may block, not promote.
- **Platform / data engineering** — owns reliability, integrity, and security.
- **The researcher who produced a result may not be its sole promoter.** Role separation is temporal where the team is one person: a cooling-off period and a written self-rebuttal precede any promotion.

## 9. Relationship to Other Governance Documents

This charter is supreme. Where any other document conflicts with it, the charter governs and the other document must be corrected. All documents link back here.
