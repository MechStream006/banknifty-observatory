# Glossary

Domain and platform terms used throughout this repository. Where a term has a platform-specific
meaning that differs from common usage, the platform definition governs.

---

## Market domain

**ATM (At-the-money)**
The strike price closest to the current spot price of the underlying. The exact ATM strike is
resolved by rounding the spot price to the nearest step size (500 points for BankNifty). The
resolved ATM is recorded in every snapshot's metadata so that derived metrics are reproducible
even if the methodology for ATM resolution changes later.

**BankNifty**
The NSE India Banking Sector Index. Tracks a float-adjusted, market-cap-weighted basket of the
most liquid large-cap banking stocks listed on NSE. The observatory focuses exclusively on this
index and its options ecosystem.

**CE / PE**
Call option / Put option. A CE at strike K gives the right to buy BankNifty at K at expiry.
A PE at strike K gives the right to sell at K. Used as field suffixes in option chain data.

**Expiry**
The date on which an option contract expires and is settled. NSE BankNifty options have weekly
and monthly expiries. The observatory tracks the configured set of near-month expiries; the
expiry set in use is stored in every snapshot.

**India VIX**
The NSE volatility index, derived from Nifty 50 option prices. Used as a market-wide implied
volatility proxy. Tracked as an independent data series alongside option chain data.

**OI (Open Interest)**
The total number of outstanding option contracts that have not been settled or expired. OI is
a measure of market participation at a strike. **OI delta** is the change in OI between two
consecutive snapshots for the same (expiry, strike, side) tuple — a positive delta indicates
new positions opened, a negative delta indicates positions closed.

**Option chain**
The full matrix of call and put option quotes across all strikes for a given expiry, captured
at a point in time. A snapshot contains windowed chains for each configured expiry.

**PCR (Put-Call Ratio)**
The ratio of put open interest (or volume) to call open interest (or volume). PCR > 1 indicates
more puts than calls are outstanding. The platform computes both OI-based and volume-based PCR.
Neither should be interpreted in isolation without a hypothesis that specifies what PCR level
means, in what regime, and over what horizon.

**Strike ladder**
The discrete set of valid strike prices for BankNifty options. Strikes are spaced at 100-point
intervals but the observatory uses a 500-point backbone for ATM resolution and window selection.
The window captures ±N strikes on each side of the resolved ATM.

**Window**
The subset of strikes captured in each snapshot: the ATM ± window_steps × step_size. The window
is configurable and recorded in every snapshot's metadata. Expanding the window is a configuration
change that should be recorded in the Decision Log.

---

## Platform

**Derived observation**
A set of values computed from one snapshot's raw chain rows: OI totals, PCR, volume totals, and
inter-tick OI deltas. Derived values are computed deterministically from raw data using a pinned
methodology version. They are reproduced from the JSONL archive if needed; the raw data is the
source of truth.

**Evidence corpus**
The accumulated set of evidence records, each linking a specific measurement result to the
hypothesis it was intended to test. A hypothesis is only considered "confirmed" if the evidence
corpus contains sufficient records meeting the project's evidence standard.

**Evidence standard**
The pre-committed criteria a body of evidence must meet before a conclusion is accepted. Includes
statistical thresholds, minimum sample sizes, regime coverage requirements, and reproducibility
requirements. Defined in the evidence standard document before any testing begins.

**Hypothesis**
A falsifiable, pre-registered claim about BankNifty behaviour. Every hypothesis must state the
exact conditions under which it would be rejected before any data is examined. Hypotheses are
tracked in the Hypothesis Registry with status: `ACTIVE`, `CONFIRMED`, `REJECTED`, or `RETIRED`.

**Labeling**
The process of assigning a net-of-cost outcome label to each historical snapshot. Labels are
computed only after a cost model has been ratified. They answer: "if you had taken a position at
this snapshot, what would the net-of-cost outcome have been at horizon H?" Labeling is a gated
operation; running labeling without a ratified cost model is prohibited.

**Methodology version**
A pinned, immutable description of exactly how a derived metric is computed. Changing any aspect
of the computation — smoothing window, formula, normalization — creates a new version. Old
versions are retained. Derived values in the archive are annotated with the methodology version
used to produce them.

**ObservationRecord**
The platform's data type for a single collection tick. Contains: spot price, VIX, windowed option
chains for each configured expiry, snapshot metadata (ATM, expiry set, window size, schema
version), and the derived observation (OI sums, PCR, OI deltas). Written as a JSONL line and
optionally stored in the analysis database.

**Schema version**
An integer that identifies the ObservationRecord JSONL line format. Incremented when the record
shape changes incompatibly. Replay tooling checks the schema version of each line before parsing.
The current Phase 1 schema is version 2.

**Session**
A single continuous run of the data collection controller, identified by a UUID. Each snapshot
within a session shares the same session ID. Sessions are bounded by market open/close; a new
session ID is generated at each startup.

**Smoke test**
A Phase 0 validation run that verifies the full collection stack end-to-end: authentication,
option chain retrieval, spot price retrieval, data parsing, and persistence — all without
committing to a full session. A smoke test must pass before Phase 1 collection begins.

**Snapshot**
The complete market state captured at one scheduled tick: spot + VIX + windowed chains for all
configured expiries. Snapshots are immutable once written. The raw JSONL archive is the canonical
form; derived values can be recomputed.

**Stage gate**
A formal checkpoint that must be passed before moving to the next stage of the project. Gate
criteria are written before the prior stage begins. Gates require explicit sign-off, not just
hitting a number. See the Decision Log for gate status.

---

## Conventions

**DDMMMYYYY**
The date format used for expiry strings in this codebase. Example: `26JUN2026`. DD is zero-padded,
MMM is a three-letter month abbreviation, YYYY is the four-digit year.

**BNO_**
The environment variable prefix for all runtime configuration. Example: `BNO_CHAIN_EXPIRIES`.
No runtime configuration is hard-coded; all deployment-specific values use this prefix.
