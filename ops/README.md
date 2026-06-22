# ops/ — Layer 6: Observability and Operations

**Owner:** Platform / Data Engineering
**Change gate:** Standard code review; alert routing changes require review

## Responsibility

Systemd service definitions, monitoring configuration (two independent planes), Telegram alert routing, and operational runbooks.

## What lives here

| Subdirectory | Purpose |
|-------------|---------|
| `systemd/` | Service and timer unit files for all `bno-*` services |
| `monitoring/` | Prometheus scrape config, Grafana dashboard definitions |
| `alerts/` | Alert routing rules, Telegram integration config, throttle rules |
| `runbooks/` | Step-by-step operational procedures for every failure scenario |

## Two monitoring planes — never conflated

| Dashboard | Answers | What it alarms on |
|-----------|---------|-------------------|
| Ops Health | Is the service running? | Process down, CPU/disk/memory thresholds |
| Data Integrity | Is the data honest? | Gaps, duplicates, quality failures, silent feed death |

These are separate dashboards. A green Ops Health board makes no claim about data completeness. See [`GOVERNANCE/DATA_INCIDENT_POLICY.md`](../GOVERNANCE/DATA_INCIDENT_POLICY.md).

## Services (long-running)

| Service | Role |
|---------|------|
| `bno-session` | SmartAPI auth, token lifecycle |
| `bno-collectors` | All data family capture workers |
| `bno-integrity` | Integrity plane monitoring |
| `bno-watchdog` | Heartbeat supervision, crash-loop escalation |

## Timers (post-session batch)

`bno-curate`, `bno-derive`, `bno-label` (gated), `bno-evidence`, `bno-backup`, `bno-report`

## Alert severity routing

`INFO`/`WARNING` → daily report digest
`ERROR`/`CRITICAL` → immediate Telegram, throttled by `BNO_ALERT_THROTTLE_SECONDS`
