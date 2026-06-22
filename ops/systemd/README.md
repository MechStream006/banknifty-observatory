# ops/systemd/ — Systemd Service and Timer Unit Files

Service files for all `bno-*` units. Implemented in Milestone 16 (Operational Hardening).

## Planned units

**Services (long-running):**
- `bno-session.service`
- `bno-collectors.service`
- `bno-integrity.service`
- `bno-watchdog.service`

**Timers (post-session oneshot):**
- `bno-curate.timer` / `bno-curate.service`
- `bno-derive.timer` / `bno-derive.service`
- `bno-label.timer` / `bno-label.service`
- `bno-evidence.timer` / `bno-evidence.service`
- `bno-backup.timer` / `bno-backup.service`
- `bno-report.timer` / `bno-report.service`
- `bno-heartbeat.timer` / `bno-heartbeat.service`
