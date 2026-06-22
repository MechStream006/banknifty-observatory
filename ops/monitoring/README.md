# ops/monitoring/ — Monitoring Configuration

Prometheus scrape configuration and Grafana dashboard definitions. Implemented in Milestone 5 (Monitoring Foundation).

Two dashboards are maintained separately:
- `ops_health.json` — is the platform running?
- `data_integrity.json` — is the data honest and complete?

These dashboards are never merged. A green ops board makes no claim about data completeness.
