# curation/ — Layer 3b: Post-Session Curation Pipeline

**Owner:** Platform / Data Engineering
**Change gate:** Standard code review

## Responsibility

Runs as `bno-curate` — a post-session timer job. Reads settled raw for the completed session, applies deduplication, annotates gap windows, computes quality scores, and writes to the `curated` schema. Curated records are rebuilt interpretations of raw — not raw itself.

## What lives here

| Submodule | Purpose |
|-----------|---------|
| `pipeline/` | Curation job orchestration: read raw → deduplicate → annotate → write curated |

## Invariants

- **Raw is never touched.** Curation reads from raw; it never modifies it.
- **Gaps are annotated as missing, never filled.** A gap window in curated has an explicit `gap_flag`, not an interpolated value. This is the no-fabrication rule from [`GOVERNANCE/DATA_INCIDENT_POLICY.md`](../GOVERNANCE/DATA_INCIDENT_POLICY.md).
- **Curated record count ≤ raw record count.** Deduplication reduces; it never invents.
- **Idempotent.** Re-running curation for a session produces identical output.
- **Every curated record links back to its source raw record ID.** Full lineage is mandatory.

## Timing

The `bno-curate` timer fires at least `BNO_SESSION_CLOSE_BUFFER_MIN` after session close. It never races the live collectors.
