# DATA_CONTRACT

> **Control Block**
> - **Purpose:** Define exactly what data is captured, at what fidelity, how it is structured, how its quality is judged, and how it is retained — so that any research result can be traced to data of known provenance and known limitations.
> - **Why it exists:** A research result is only as trustworthy as the data beneath it. Without a contract, "the data" becomes an undocumented, drifting artifact, and no finding is reproducible or defensible years later. The contract is the scientific foundation; it also forces honesty about feed fidelity so downstream research never assumes resolution that was never captured.
> - **Approval required:** Platform/data engineering + research governance. Ratified via DECISION_LOG.
> - **Change-control:** Any change to captured fields, fidelity, source, or schema is a versioned, logged event. Breaking changes bump the data-contract version and require an assessment of whether existing evidence remains comparable. Silent schema changes are prohibited.
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. Required Sections (every ratified version must contain)

1. Data families in scope
2. Observed vs. derived classification
3. Source and fidelity declaration
4. Granularity and timestamping rules
5. Schema and versioning policy
6. Data-quality definition and scoring
7. Retention and tiering policy
8. Coverage and completeness expectations
9. Known limitations register

## 2. Data Families In Scope

| Family | Classification | Notes |
|---|---|---|
| Spot / index level | **Observed** | Highest-frequency capture the feed reliably provides |
| Option chain (per strike/expiry) | **Observed** | Full chain in scope, not only ATM |
| Quotes: bid/ask, depth | **Observed** | **Mandatory** — the foundation of the cost model |
| Open Interest, ΔOI | **Observed** | |
| Volume | **Observed** | |
| Expiry structure | **Observed** | Identification + roll rules defined below |
| Implied Volatility | **Derived** | Pinned to a methodology version |
| Greeks | **Derived** | Pinned to a methodology version |
| Put/Call ratios | **Derived** | Definition is ours, computed from raw |
| Regime tags | **Derived** | Descriptive only |
| Term structure | **Derived** | |
| Cost model outputs | **Derived** | Gated; required before labeling |

## 3. Observed vs. Derived (the seam)

Observed = captured as received, never interpreted. Derived = computed by us under a versioned methodology. The two are **never stored in the same table** and are **never conflated in the same field**. See [[METHODOLOGY_VERSIONING_POLICY]].

## 4. Source & Fidelity Declaration

- **Source:** SmartAPI (BankNifty application), data access only.
- **Fidelity is declared honestly:** capture cadence per family, whether each family is true-stream or snapshot/poll-throttled, and the gap between exchange timestamp and receipt timestamp.
- **Rule:** downstream research may not assume finer resolution than this declaration states. Over-claiming fidelity is a contract violation and a silent lookahead source.

## 5. Granularity & Timestamping

- Capture at the **finest cadence the source reliably provides**; downsampling is allowed later, upsampling never.
- Every record carries **both source/exchange timestamp and receipt timestamp**, in the exchange timezone (Asia/Kolkata) as canonical.
- Session phases (pre-open, regular, close) are tagged.

## 6. Schema & Versioning

- Schemas are explicit and versioned. The data-contract version is recorded on every dataset manifest.
- Expiry/strike identity and roll rules are defined here and frozen per version: how a strike is identified, how expiries roll, how a continuous view is reconstructed.

## 7. Data Quality Definition & Scoring

- **"Good" data** = complete (no unexplained gaps), schema-conformant, timestamps monotonic and plausible, values within physical bounds, duplicates removed.
- Each capture interval receives a **data-quality score** recorded in metadata. Scores are research inputs: low-quality windows are flagged, never silently used.

## 8. Retention & Tiering

| Tier | Retention |
|---|---|
| Raw | **Infinite** — never deleted; hot then cold, never destroyed |
| Curated | Long; rebuildable from raw |
| Derived | All versions referenced by any evidence record retained |
| Evidence & metadata | **Permanent** |

## 9. Completeness Expectations

- Expected data volume per family per time-of-day is baselined. Under-delivery raises an **integrity** alarm (distinct from operational alarms) and creates a data incident. See [[DATA_INCIDENT_POLICY]].

## 10. Known Limitations Register (example)

- Quote depth limited to vendor-provided levels; true full-book microstructure is **not** available — microstructure research scope is bounded accordingly.
- Snapshot throttling on the chain means sub-cadence events are not observable; labels and cost models must respect this.

## 11. Example Manifest Entry (illustrative, not a schema)

```
dataset: chain_snapshots
data_contract_version: 1
period: 2026-07-01 .. 2026-07-31
families: [chain, quotes, oi, volume]
fidelity: snapshot @ 3s; receipt-vs-exchange median lag recorded per day
quality_score_summary: { mean: 0.98, low_quality_windows: 4 }
incidents_linked: [INC-2026-07-12-001]
checksum: <hash of raw payload set>
```
