# DATA_INCIDENT_POLICY

> **Control Block**
> - **Purpose:** Define how data gaps, feed interruptions, corruption, duplication, and completeness failures are detected, recorded, classified, and closed — and ensure they are never silently healed away.
> - **Why it exists:** A continuously self-healing platform can hide data loss behind a green operations dashboard. A reconnect that restores service still leaves a permanent hole in the dataset. Research credibility depends on every gap being a recorded, first-class fact. This policy enforces the separation of *operational health* from *data integrity*.
> - **Approval required:** Platform/data engineering owns detection and recording; research governance reviews severity classification for anything that could affect evidence.
> - **Change-control:** The incident register is **append-only**. Classifications may be revised by appended notes, never by editing the original record. Detection thresholds are versioned and logged.
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. Required Sections

1. Incident types
2. Detection requirements
3. Severity classification
4. Recording requirements
5. The no-fabrication rule
6. Closure criteria

## 2. Incident Types

- Feed interruption (process alive, data absent — "silent feed death")
- Process crash / crash-loop affecting capture
- Gap (missing expected records)
- Duplicate records
- Schema break / impossible values
- Completeness shortfall vs. baseline
- Corruption discovered downstream (e.g., methodology bug)

## 3. Detection Requirements

- **Integrity detection is independent of operational health.** Absence of expected data raises an integrity alarm even when every service reports "up."
- Completeness is judged against a per-time-of-day **expected-volume baseline**.
- Duplicate and schema checks run continuously at the curation/integrity layer.

## 4. Severity Classification

| Severity | Meaning | Response |
|---|---|---|
| Low | Cosmetic / fully recovered, no evidence impact | Log + daily report line |
| Medium | Real gap/quality loss, bounded window | Log, annotate curated, alert |
| High | Affects data feeding evidence, or unbounded | Log, alert, governance review, possible recompute |
| Critical | Raw integrity threatened / loss risk | Page human, invoke playbook, DECISION_LOG entry |

## 5. Recording Requirements

Every incident record contains: id, detection time, type, affected family/window, severity, suspected cause, recovery action, dataset annotation reference, and closure note. Records link to the affected dataset manifests.

## 6. The No-Fabrication Rule (non-negotiable)

- Recovery **never invents data.** Missing windows are marked missing.
- No interpolation or back-fill is written into **raw**. Vendor-sourced historical back-fill, if ever used, lands in a clearly flagged separate lane, never the trusted raw lane.

## 7. Closure Criteria

An incident is closed only when **both** are true:
1. Operational service is restored, and
2. The dataset is annotated and the gap recorded.

A restored service with an un-annotated gap is **not** closed.

## 8. Example Incident Record (illustrative)

```
id: INC-2026-07-12-001
detected: 2026-07-12T11:04:00+05:30
type: feed_interruption (silent)
affected: chain + quotes, 11:01:30 .. 11:09:10
severity: Medium
suspected_cause: websocket stall; process alive, heartbeat ok, ticks absent
recovery: auto-reconnect + re-subscribe at 11:09:10
dataset_annotation: curated.chain marked missing for window; quality score lowered
no_fabrication: confirmed — window left missing, not interpolated
closure: closed 2026-07-12 (service restored AND dataset annotated)
```
