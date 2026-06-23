# Server Setup Guide

Step-by-step instructions for deploying BankNifty Observatory on a Linux VPS.

**Target:** Ubuntu 22.04 LTS (tested), any Debian-based distro should work.
**Minimum spec:** 1 vCPU, 1 GB RAM, 20 GB SSD. Recommended: 2 vCPU, 2 GB RAM.
**Timezone:** Server should be in UTC. The application handles IST via `BNO_TIMEZONE`.

---

## 1. Initial server preparation

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install system dependencies
sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib \
    git curl unzip \
    build-essential libpq-dev \
    logrotate

# Confirm Python version
python3.11 --version
```

**NTP — verify clock sync before anything else.**
TOTP codes are valid for 30-second windows. Clock drift over ~15 seconds causes every
generated code to be rejected, breaking authentication silently at session start.
Ubuntu 22.04 ships `systemd-timesyncd` but it may not be active on all VPS images.

```bash
# Check current sync state
timedatectl status
# Required: "System clock synchronized: yes"
# Required: "NTP service: active"

# If NTP service is inactive:
sudo systemctl enable --now systemd-timesyncd
timedatectl timesync-status
# Expected: a "Last successful sync:" timestamp within the last few minutes
```

---

## 2. Create the application user

The service runs as an unprivileged user `bno`. It has no sudo access.

```bash
sudo useradd --system --create-home --shell /bin/bash --groups bno bno
sudo mkdir -p /srv/bno/data /srv/bno/data/buffer
sudo chown -R bno:bno /srv/bno
```

---

## 3. Clone the repository

```bash
sudo -u bno git clone https://github.com/MechStream006/banknifty-observatory.git \
    /home/bno/banknifty-observatory

# Confirm the clone
ls /home/bno/banknifty-observatory
```

---

## 4. Create the Python virtual environment

```bash
sudo -u bno python3.11 -m venv /home/bno/.venv

# Install runtime dependencies
sudo -u bno /home/bno/.venv/bin/pip install --upgrade pip

# Install all runtime dependencies declared in pyproject.toml
sudo -u bno /home/bno/.venv/bin/pip install /home/bno/banknifty-observatory

# Confirm installation
sudo -u bno /home/bno/.venv/bin/python -c "from SmartApi import SmartConnect; print('SmartAPI OK')"
sudo -u bno /home/bno/.venv/bin/python -c "import pyotp; print('pyotp OK')"

# Optional: install database extras when lib/db/ is implemented
# sudo -u bno /home/bno/.venv/bin/pip install "/home/bno/banknifty-observatory[db]"
```

> **Note:** `smartapi-python` is the broker data API client. `pyotp` is used for TOTP
> authentication. Neither is used for order placement.

---

## 5. Configure PostgreSQL

```bash
sudo -u postgres psql <<'SQL'
CREATE USER bno_app WITH PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';
CREATE DATABASE bno OWNER bno_app;
-- Application role: INSERT-only on raw schema (immutability guarantee)
GRANT CONNECT ON DATABASE bno TO bno_app;
SQL
```

---

## 6. Create the environment configuration file

```bash
sudo mkdir -p /etc/banknifty-observatory

# Copy the production template
sudo cp /home/bno/banknifty-observatory/deployment/env.example \
    /etc/banknifty-observatory/discovery.env

# Edit with real values
sudo nano /etc/banknifty-observatory/discovery.env

# Restrict access: only root can read; bno group can read (service user)
sudo chmod 640 /etc/banknifty-observatory/discovery.env
sudo chown root:bno /etc/banknifty-observatory/discovery.env
```

**Required values to fill in** (`REPLACE_ME` fields):
| Field | Description |
|---|---|
| `BNO_DB_PASSWORD` | PostgreSQL password for `bno_app` user |
| `BNO_S3_BUCKET` | S3 bucket name for raw data replication |
| `BNO_SMARTAPI_API_KEY` | API key from AngelOne developer portal |
| `BNO_SMARTAPI_CLIENT_ID` | Your client code |
| `BNO_SMARTAPI_PASSWORD` | Your login password |
| `BNO_TELEGRAM_BOT_TOKEN` | Telegram bot token for alerts |
| `BNO_TELEGRAM_CHAT_ID` | Telegram channel ID for alerts |
| `BNO_CHAIN_EXPIRIES` | Active BankNifty expiries, e.g. `26JUN2026,03JUL2026` |

---

## 7. Run a smoke test (pre-flight check)

Before installing the systemd service, confirm the stack works end-to-end:

```bash
cd /home/bno/banknifty-observatory
sudo -u bno PYTHONPATH=. /home/bno/.venv/bin/python scripts/smoke_test.py \
    --expiry 26JUN2026

# Check output — expect "Verdict : PASS"
# Auth response is written to data/smoke/<timestamp>/auth_response.json
# WARNING: auth_response.json contains JWT session tokens — never share or commit it.
```

If the smoke test fails:
- `Auth FAIL` → check API key, client ID, password, TOTP setup
- `Chain FAIL` → check expiry date format (DDMMMYYYY) and market hours
- Config error → verify `/etc/banknifty-observatory/discovery.env`

---

## 8. Install and start the systemd service

```bash
# Install service and timer units
sudo cp /home/bno/banknifty-observatory/deployment/systemd/banknifty-observatory.service \
    /etc/systemd/system/

sudo cp /home/bno/banknifty-observatory/deployment/systemd/banknifty-observatory.timer \
    /etc/systemd/system/

sudo systemctl daemon-reload

# Enable the timer (auto-starts at 09:10 IST on weekdays)
sudo systemctl enable --now banknifty-observatory.timer

# Confirm timer is active
systemctl list-timers banknifty-observatory.timer

# Manual start (for testing outside market hours):
# sudo systemctl start banknifty-observatory
```

---

## 9. Verify the service is running

```bash
# Service status
sudo systemctl status banknifty-observatory

# Live logs (journal)
journalctl -u banknifty-observatory -f

# Structured JSON logs (one file per session)
ls /srv/bno/data/phase1/logs/
tail -f /srv/bno/data/phase1/logs/<latest>.log | python3 -m json.tool
```

---

## 10. Weekly maintenance

Every **Thursday evening** (before market close, before the expiry rolls):

1. Update `BNO_CHAIN_EXPIRIES` in `/etc/banknifty-observatory/discovery.env`
2. Reload the environment (service picks it up on next start — no restart needed today):
   ```bash
   sudo systemctl restart banknifty-observatory  # only if running right now
   ```
3. Confirm the new expiry in Friday's startup logs

---

## 11. Log rotation

```bash
sudo tee /etc/logrotate.d/banknifty-observatory <<'EOF'
/srv/bno/data/phase1/logs/*.log {
    daily
    rotate 90
    compress
    delaycompress
    missingok
    notifempty
    create 640 bno bno
}
EOF
```

---

## Security notes

- The `bno` user has no sudo access and no write access outside `/srv/bno/data` and the project logs directory.
- `/etc/banknifty-observatory/discovery.env` is `640 root:bno` — readable by the service user, not world-readable.
- The SmartAPI Python library logs request headers at ERROR level, which **includes the API key** (`X-PrivateKey`). These logs are written to `/srv/bno/data/phase1/logs/` (not gitignored on the server, only locally). Ensure log files are not transmitted or shared.
- The `data/smoke/` directory contains JWT session tokens in `auth_response.json`. Never share or back up these files publicly.
- Raw data files (`*.jsonl`) are gitignored and must be replicated to S3 via the configured bucket. They are never committed to the repository.

---

## Startup sequence (what happens at 09:10 IST)

1. Timer fires → systemd starts `banknifty-observatory.service`
2. `discovery_run.py` loads config from `/etc/banknifty-observatory/discovery.env`
3. Logging is bootstrapped; a new session log file is created
4. `SmartAPISession.connect()` authenticates and stores the JWT
5. `PollScheduler.ticks()` begins firing at `BNO_CHAIN_POLL_INTERVAL_S` intervals
6. Each tick: spot → VIX → chains (per expiry) → derived → JSONL write
7. At 15:30 IST: `ticks()` is exhausted → `controller.run()` returns → exit 0
8. systemd records the clean exit; timer fires again next trading day at 09:10 IST
