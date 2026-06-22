# Deployment

This directory contains all assets needed to deploy BankNifty Observatory on a Linux VPS.

---

## Quick reference

| Task | Document |
|---|---|
| First-time server setup | [server_setup.md](server_setup.md) |
| Production environment config | [env.example](env.example) |
| systemd service unit | [systemd/banknifty-observatory.service](systemd/banknifty-observatory.service) |
| systemd timer (daily auto-start) | [systemd/banknifty-observatory.timer](systemd/banknifty-observatory.timer) |

---

## Deployment model

The observatory runs as a single systemd service on one VPS. It:

1. Starts automatically at **09:10 IST** on weekdays (5 minutes before market open)
2. Authenticates, then polls BankNifty spot + VIX + option chains every 5 seconds
3. Writes each tick as a JSONL line to `/srv/bno/data/phase1/raw/`
4. Exits cleanly at **15:30 IST** when the market session ends
5. The timer fires again the next trading day

Raw data is replicated to S3 via `BNO_S3_BUCKET`. The local JSONL archive is the primary source of truth; S3 is the off-instance backup.

---

## Configuration

All runtime configuration uses `BNO_` environment variables. The production config file lives at:

```
/etc/banknifty-observatory/discovery.env
```

This file is root-owned, group-readable by `bno` (the service user), and never committed to the repository. See [env.example](env.example) for all required fields.

**Weekly action required:** Update `BNO_CHAIN_EXPIRIES` every Thursday evening before the active weekly expiry rolls.

---

## Data flow

```
SmartAPI (read-only)
        │
        ▼
discovery_run.py  ──→  /srv/bno/data/phase1/raw/YYYYMMDD.jsonl  ──→  S3 bucket
                   └──→ PostgreSQL (analysis queries, optional)
```

No order placement. No capital at risk. SmartAPI access is data-only.

---

## Security checklist

- [ ] `/etc/banknifty-observatory/discovery.env` is `640 root:bno`
- [ ] `bno` user has no sudo access
- [ ] API key, password, TOTP secret are NOT stored in the git repository
- [ ] `data/smoke/*/auth_response.json` is excluded from backups or only retained locally
- [ ] S3 bucket has versioning enabled (raw data immutability)
- [ ] Log files containing SmartAPI request headers are not publicly accessible
- [ ] Server firewall allows only SSH (port 22) inbound; all outbound is allowed

---

## Differences from the existing `ops/systemd/` unit

The legacy `ops/systemd/banknifty-observatory.service` was written before M-C6 (multi-expiry controller). The `deployment/systemd/` units are updated for the current codebase:

| Change | Old (`ops/`) | New (`deployment/`) |
|---|---|---|
| Expiry source | `--expiry ${BNO_EXPIRY}` CLI arg | `BNO_CHAIN_EXPIRIES` env var (config framework) |
| VIX fetcher | Not wired | Wired via `VIXFetcher()` |
| Multi-expiry | Single expiry | List from `settings.chain_expiries` |
| `After=` dependency | `network-online.target` | Adds `postgresql.service` |
