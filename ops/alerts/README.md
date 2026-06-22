# ops/alerts/ — Alert Routing Configuration

Telegram alert routing rules and throttle configuration. Implemented in Milestone 5 (Monitoring Foundation).

Severity routing:
- `INFO` / `WARNING` → queued for daily report
- `ERROR` / `CRITICAL` → immediate Telegram, subject to `BNO_ALERT_THROTTLE_SECONDS` de-dup

Integrity-plane alerts and ops-plane alerts are labeled distinctly so the recipient immediately knows whether the issue is a service failure or a data gap.
