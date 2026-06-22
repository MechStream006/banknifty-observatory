# Decision Log

A permanent, append-only record of significant engineering and research decisions.

**Rules:**
- Entries are never edited or deleted after the decision date. If a decision is reversed, add a new
  entry that supersedes the old one and references it.
- Every entry must state: what was decided, why, what alternatives were considered, and the date.
- Stage gate ratifications are recorded here.
- Charter amendments are recorded here.

---

## Entry format

```
### D-NNN — Title
**Date:** YYYY-MM-DD
**Type:** [Architecture | Research | Governance | Stage Gate | Charter Amendment]
**Status:** [In force | Superseded by D-XXX]

**Decision:**
What was decided, stated precisely.

**Rationale:**
Why this option and not the alternatives. What tradeoffs were accepted.

**Alternatives considered:**
What else was evaluated and why it was not chosen.

**Consequences:**
What this decision constrains or enables going forward.
```

---

## Log

### D-001 — Observatory-only scope for Phase 1
**Date:** 2026-06-17
**Type:** Governance
**Status:** In force

**Decision:**
Phase 1 is exclusively an observatory. No strategy, execution, order placement, or capital
deployment is in scope. Trading modules exist only as sealed, disabled extension points. They
are not activated without explicit stage gate sign-off backed by Phase 2 evidence.

**Rationale:**
Starting with a trading assumption biases data collection and analysis toward confirming that
assumption. Treating the observatory as the primary deliverable keeps the evidence standard
honest. The equally valid outcome — no exploitable pattern — requires the same infrastructure.

**Alternatives considered:**
- Collect data and build strategy in parallel: rejected. Parallel strategy development creates
  pressure to confirm patterns rather than test them, and increases scope before the data quality
  constraints are understood.

**Consequences:**
All feature requests for strategy or execution code are deferred to Phase 3+ gating.

---

### D-002 — JSONL as primary archive format; database as query layer
**Date:** 2026-06-17
**Type:** Architecture
**Status:** In force

**Decision:**
Every snapshot is written to a JSONL archive first. The database is a downstream query layer.
The JSONL archive is the source of truth; all derived values can be recomputed from it.

**Rationale:**
JSONL is append-only, human-readable, trivially replicated, and requires no schema migration
when fields are added. A database write failure is recoverable from the JSONL archive; a JSONL
write failure is not recoverable from the database. Separating persistence concerns also means
the database can be wiped and repopulated without data loss.

**Alternatives considered:**
- Database-first: rejected. A database failure during collection loses data. The dual-write
  approach with JSONL as primary avoids this at negligible cost.
- Parquet: considered for later analysis phases. JSONL is chosen for Phase 1 because it is
  appendable at runtime without a schema compile step.

**Consequences:**
The JSONL archive is immutable. Schema changes create a new `schema_version` field.
Archive replay is the canonical path for recomputing derived values.

---

### D-003 — Pydantic-settings for configuration; all config via BNO_ env vars
**Date:** 2026-06-17
**Type:** Architecture
**Status:** In force

**Decision:**
All runtime configuration is read from `BNO_`-prefixed environment variables via
pydantic-settings. No configuration is hard-coded. Secrets are validated for presence and
format but never logged or echoed. Direct `os.environ` access outside `lib/config/` is
prohibited.

**Rationale:**
Centralising configuration in one validated loader prevents the scattered `os.getenv` pattern
that makes secret exposure difficult to audit. Pydantic provides type coercion and validation
at startup, so misconfiguration fails fast with a clear error rather than silently at runtime.

**Alternatives considered:**
- YAML/TOML config files: rejected for secrets. Files checked into the repo accidentally expose
  credentials. Environment variables with a strict prefix are safer.
- argparse: rejected. CLI flags are inappropriate for long-running service configuration.

**Consequences:**
All deployment documentation must reference `BNO_` env vars. `.env` files are gitignored.
A `BNO_CONFIG_SCHEMA_VERSION` guard detects stale environment configurations.

---

### D-004 — Option chain window: ±15 strikes on 500-point backbone
**Date:** 2026-06-19
**Type:** Research
**Status:** In force

**Decision:**
Each expiry's option chain snapshot captures strikes within ±15 steps of the resolved ATM,
where each step is 500 points. This gives a ±7500-point window (15 strikes on each side + ATM).

**Rationale:**
BankNifty rarely moves more than 2000–3000 points in a single session. A ±7500 window covers
multiple standard-deviation moves and captures most of the liquid option surface without
exceeding the API's per-call token limit (50 tokens per exchange per call).

**Alternatives considered:**
- ±10 strikes: window might miss significant OI buildup at outer strikes during high-volatility
  sessions.
- ±20 strikes: would require multiple API calls per expiry per tick, doubling latency and API
  credit consumption.

**Consequences:**
The window size is stored in every snapshot's metadata (`window_steps=15`). Changing the window
creates a structural break in the time series that must be noted in the Decision Log and handled
in any analysis that spans the break.

---

<!-- Add new entries above this line. Entries are append-only. -->
