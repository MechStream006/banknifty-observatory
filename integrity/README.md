# integrity/ — Layer 3a: Data Integrity Monitoring

**Owner:** Platform / Data Engineering
**Change gate:** Standard code review; severity-classification changes require governance review

## Responsibility

Runs as `bno-integrity` — a separate service, independent of operational monitoring. Detects gaps, duplicates, quality failures, and silent feed deaths. Creates incident records in `meta.data_incidents`. Alarms on the **integrity plane**, not the ops plane.

**A system where every service shows "up" but data stopped arriving must trigger an integrity alarm.** That is the entire reason this module is a separate service.

## What lives here

| Submodule | Purpose |
|-----------|---------|
| `completeness/` | Gap detection against per-time-of-day expected-volume baseline |
| `incidents/` | Incident record creation, classification, and closure logic |
| `quality/` | Per-record and per-window quality scoring |

## The two-plane distinction

| Plane | Answers | Alarm source |
|-------|---------|-------------|
| Ops health | Is the service running? | `bno-watchdog`, systemd |
| Data integrity | Is the data honest and complete? | `bno-integrity` (this module) |

These are never conflated. See [`GOVERNANCE/DATA_INCIDENT_POLICY.md`](../GOVERNANCE/DATA_INCIDENT_POLICY.md).

## No-fabrication rule

Missing windows are marked missing. No interpolation or back-fill is written into raw. A recovered service with an un-annotated gap is **not** a closed incident.
