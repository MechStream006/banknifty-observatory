# Production Deployment Checklist — Ubuntu 22.04

**Purpose:** Step-by-step runbook for deploying BankNifty Observatory on a fresh VPS.
Complete every checkbox before moving to the next section.
Do not skip verification steps — they catch configuration errors before the market opens.

**Reference files:**
- `deployment/env.example` — production environment template
- `deployment/server_setup.md` — narrative context for each section
- `deployment/systemd/` — service and timer unit files

**Estimated time:** 45–60 minutes on a fresh instance.

---

## Section 1 — System packages

- [ ] **1.1** Update package index and upgrade existing packages

  ```bash
  sudo apt update && sudo apt upgrade -y
  ```

- [ ] **1.2** Install all required system dependencies

  ```bash
  sudo apt install -y \
      python3.11 python3.11-venv python3.11-dev \
      postgresql postgresql-contrib \
      git curl tzdata build-essential libpq-dev \
      logrotate ufw
  ```

- [ ] **1.3** Verify Python version

  ```bash
  python3.11 --version
  # Expected: Python 3.11.x
  ```

- [ ] **1.4** Verify PostgreSQL is running

  ```bash
  sudo systemctl status postgresql
  # Expected: active (running)
  ```

- [ ] **1.5** Verify timezone data is present

  ```bash
  python3.11 -c "import zoneinfo; zoneinfo.ZoneInfo('Asia/Kolkata'); print('tzdata OK')"
  # Expected: tzdata OK
  # If this fails: sudo apt install -y python3-tzdata
  ```

- [ ] **1.6** Configure firewall (allow SSH only; application makes outbound connections only)

  ```bash
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw allow ssh
  sudo ufw --force enable
  sudo ufw status
  # Expected: Status: active, 22/tcp ALLOW
  ```

- [ ] **1.7** Verify NTP clock sync is active

  TOTP authentication requires the server clock to be accurate within ~15 seconds.
  Clock drift causes every generated code to be rejected, breaking auth at session
  start with no useful error message.

  ```bash
  timedatectl status
  # Required: "System clock synchronized: yes"
  # Required: "NTP service: active"
  ```

  If NTP is not active:

  ```bash
  sudo systemctl enable --now systemd-timesyncd
  timedatectl timesync-status
  # Expected: "Last successful sync:" timestamp within the last few minutes
  ```

  Do not proceed until both lines show the required values.

---

## Section 2 — Service account creation

- [ ] **2.1** Create the `bno` system user with a home directory

  ```bash
  sudo useradd \
      --system \
      --create-home \
      --shell /bin/bash \
      --comment "BankNifty Observatory service account" \
      bno
  ```

- [ ] **2.2** Verify the account exists and has no sudo rights

  ```bash
  id bno
  # Expected: uid=NNN(bno) gid=NNN(bno) groups=NNN(bno)

  sudo -l -U bno
  # Expected: User bno is not allowed to run sudo on ...
  ```

- [ ] **2.3** Confirm the home directory was created

  ```bash
  ls -la /home/bno
  # Expected: directory owned by bno:bno
  ```

---

## Section 3 — Directory permissions

- [ ] **3.1** Create the data directory tree

  ```bash
  sudo mkdir -p \
      /srv/bno/data \
      /srv/bno/data/buffer \
      /srv/bno/data/phase1/raw \
      /srv/bno/data/phase1/logs
  ```

- [ ] **3.2** Assign ownership to the service account

  ```bash
  sudo chown -R bno:bno /srv/bno
  ```

- [ ] **3.3** Set directory permissions (service user only; no world access)

  ```bash
  sudo chmod -R 750 /srv/bno
  ```

- [ ] **3.4** Create the configuration directory (root-owned)

  ```bash
  sudo mkdir -p /etc/banknifty-observatory
  sudo chmod 750 /etc/banknifty-observatory
  sudo chown root:bno /etc/banknifty-observatory
  ```

- [ ] **3.5** Verify directory ownership

  ```bash
  ls -la /srv/bno/
  # Expected: drwxr-x--- bno bno  data/

  ls -la /etc/ | grep banknifty
  # Expected: drwxr-x--- root bno  banknifty-observatory/
  ```

---

## Section 4 — Python environment

- [ ] **4.1** Clone the repository as the service user

  ```bash
  sudo -u bno git clone \
      https://github.com/MechStream006/banknifty-observatory.git \
      /home/bno/banknifty-observatory
  ```

- [ ] **4.2** Verify the clone

  ```bash
  ls /home/bno/banknifty-observatory
  # Expected: deployment/ lib/ scripts/ tests/ pyproject.toml ...
  ```

- [ ] **4.3** Create the virtual environment

  ```bash
  sudo -u bno python3.11 -m venv /home/bno/.venv
  ```

- [ ] **4.4** Upgrade pip

  ```bash
  sudo -u bno /home/bno/.venv/bin/pip install --upgrade pip
  ```

- [ ] **4.5** Install all runtime dependencies from `pyproject.toml`

  ```bash
  sudo -u bno /home/bno/.venv/bin/pip install /home/bno/banknifty-observatory
  ```

- [ ] **4.6** Verify all critical imports resolve

  ```bash
  sudo -u bno /home/bno/.venv/bin/python -c "
  from SmartApi import SmartConnect
  import pyotp
  import pydantic
  import pydantic_settings
  print('All runtime imports OK')
  print('pydantic:', pydantic.__version__)
  "
  # Expected: All runtime imports OK
  ```

- [ ] **4.7** Verify the internal library loads without import errors

  ```bash
  sudo -u bno bash -c '
      PYTHONPATH=/home/bno/banknifty-observatory \
      /home/bno/.venv/bin/python -c "
  from lib.config import load_settings
  from lib.discovery.controller import DiscoveryController
  from lib.discovery.fetchers.chain import ChainFetcher
  from lib.discovery.fetchers.vix import VIXFetcher
  from lib.logging import bootstrap_logging
  print(\"Library imports OK\")
  "
  '
  # Expected: Library imports OK
  ```

---

## Section 5 — PostgreSQL setup

> **Note:** `lib/db/` is not yet implemented. This section provisions the database for
> when the store is activated. The discovery phase runs without it (`store=None`).

- [ ] **5.1** Create the application database user

  ```bash
  sudo -u postgres psql -c \
      "CREATE USER bno_app WITH PASSWORD 'CHOOSE_A_STRONG_PASSWORD';"
  # Use the same password you will put in BNO_DB_PASSWORD
  ```

- [ ] **5.2** Create the application database

  ```bash
  sudo -u postgres psql -c "CREATE DATABASE bno OWNER bno_app;"
  ```

- [ ] **5.3** Grant connect privilege

  ```bash
  sudo -u postgres psql -c "GRANT CONNECT ON DATABASE bno TO bno_app;"
  ```

- [ ] **5.4** Verify the connection works

  ```bash
  sudo -u bno bash -c \
      "PGPASSWORD='YOUR_PASSWORD' psql -h localhost -U bno_app -d bno -c '\conninfo'"
  # Expected: You are connected to database "bno" as user "bno_app"
  ```

- [ ] **5.5** Confirm PostgreSQL starts on boot

  ```bash
  sudo systemctl is-enabled postgresql
  # Expected: enabled
  ```

---

## Section 6 — Environment file placement

- [ ] **6.1** Copy the production template

  ```bash
  sudo cp /home/bno/banknifty-observatory/deployment/env.example \
      /etc/banknifty-observatory/discovery.env
  ```

- [ ] **6.2** Edit the file and fill in every `REPLACE_ME` value

  ```bash
  sudo nano /etc/banknifty-observatory/discovery.env
  ```

  Required fields:

  | Variable | Value source |
  |---|---|
  | `BNO_DB_PASSWORD` | Password set in Section 5.1 |
  | `BNO_S3_BUCKET` | Your S3 bucket name |
  | `BNO_SMARTAPI_API_KEY` | AngelOne developer portal |
  | `BNO_SMARTAPI_CLIENT_ID` | Your client code |
  | `BNO_SMARTAPI_PASSWORD` | Your login password |
  | `BNO_TELEGRAM_BOT_TOKEN` | Telegram BotFather |
  | `BNO_TELEGRAM_CHAT_ID` | Your observatory channel ID |
  | `BNO_CHAIN_EXPIRIES` | Active expiries, e.g. `26JUN2026,03JUL2026` |

  > **Weekly action:** `BNO_CHAIN_EXPIRIES` must be updated every **Thursday evening**
  > before the active weekly expiry rolls. The service will refuse to start (via
  > `scripts/validate_expiries.sh`) if any configured expiry has already passed.

  Fields to confirm are correct (not REPLACE_ME but must match codebase):

  | Variable | Required value |
  |---|---|
  | `BNO_ENV` | `production` |
  | `BNO_CONFIG_SCHEMA_VERSION` | `2` |
  | `BNO_SMARTAPI_TOTP_PROVIDER` | `local_seed` |
  | `BNO_DATA_DIR` | `/srv/bno/data` |
  | `BNO_STRATEGY_ACTIVE` | `false` |

- [ ] **6.3** Lock down permissions

  ```bash
  sudo chmod 640 /etc/banknifty-observatory/discovery.env
  sudo chown root:bno /etc/banknifty-observatory/discovery.env
  ```

- [ ] **6.4** Confirm the service user can read the file but not world

  ```bash
  sudo -u bno cat /etc/banknifty-observatory/discovery.env | head -3
  # Expected: first 3 lines of the file (not "permission denied")

  ls -la /etc/banknifty-observatory/discovery.env
  # Expected: -rw-r----- root bno
  ```

- [ ] **6.5** Confirm no `REPLACE_ME` values remain

  ```bash
  grep "REPLACE_ME" /etc/banknifty-observatory/discovery.env
  # Expected: no output
  ```

- [ ] **6.6** Confirm config loads cleanly (startup validation)

  ```bash
  sudo -u bno bash -c '
      PYTHONPATH=/home/bno/banknifty-observatory \
      /home/bno/.venv/bin/python -c "
  import os; os.chdir(\"/home/bno/banknifty-observatory\")
  from lib.config import load_settings
  s = load_settings(env_file=\"/etc/banknifty-observatory/discovery.env\")
  print(\"Config OK — env:\", s.env)
  print(\"Expiries:\", s.chain_expiries)
  "
  '
  # Expected: Config OK — env: production
  #           Expiries: ['26JUN2026', '03JUL2026']  (or your configured values)
  ```

---

## Section 7 — systemd installation

- [ ] **7.1** Install the service unit

  ```bash
  sudo cp /home/bno/banknifty-observatory/deployment/systemd/banknifty-observatory.service \
      /etc/systemd/system/
  ```

- [ ] **7.2** Install the timer unit

  ```bash
  sudo cp /home/bno/banknifty-observatory/deployment/systemd/banknifty-observatory.timer \
      /etc/systemd/system/
  ```

- [ ] **7.3** Reload systemd and validate unit files

  ```bash
  sudo systemctl daemon-reload
  sudo systemd-analyze verify banknifty-observatory.service
  sudo systemd-analyze verify banknifty-observatory.timer
  # Expected: no output (silent = valid)
  ```

- [ ] **7.4** Enable the timer (do NOT start the service manually yet)

  ```bash
  sudo systemctl enable banknifty-observatory.timer
  ```

- [ ] **7.5** Confirm the timer is enabled and shows the next trigger time

  ```bash
  systemctl list-timers banknifty-observatory.timer --no-pager
  # Expected: NEXT column shows a weekday at 03:40:00 UTC
  ```

- [ ] **7.6** Confirm the service unit is valid and not masked

  ```bash
  sudo systemctl status banknifty-observatory.service
  # Expected: Loaded: loaded (/etc/systemd/system/...)
  #           Active: inactive (dead)    ← correct before first run
  ```

- [ ] **7.7** Verify pre-flight scripts are executable

  The service unit runs `check_disk_space.sh` and `validate_expiries.sh` as
  `ExecStartPre=` steps before each session. Both must be executable.

  ```bash
  ls -la /home/bno/banknifty-observatory/scripts/check_disk_space.sh \
         /home/bno/banknifty-observatory/scripts/validate_expiries.sh
  # Expected: -rwxr-xr-x (or -rwxr-x---) for both files
  ```

  If the executable bit is missing (can happen if the repo was cloned with
  a git client that strips permissions):

  ```bash
  chmod +x /home/bno/banknifty-observatory/scripts/check_disk_space.sh
  chmod +x /home/bno/banknifty-observatory/scripts/validate_expiries.sh
  ```

- [ ] **7.8** Run the pre-flight scripts manually to confirm they pass

  ```bash
  sudo -u bno bash -c '
      source /etc/banknifty-observatory/discovery.env
      export BNO_DATA_DIR BNO_CHAIN_EXPIRIES
      /home/bno/banknifty-observatory/scripts/check_disk_space.sh
      /home/bno/banknifty-observatory/scripts/validate_expiries.sh
  '
  # Expected:
  #   Disk check OK: NNNNNN kB free on /srv/bno/data
  #   Expiry validation OK: 26JUN2026,03JUL2026
  ```

  If `check_disk_space.sh` fails: free disk space before proceeding.
  If `validate_expiries.sh` fails: update `BNO_CHAIN_EXPIRIES` with current expiries.

---

## Section 8 — Log rotation

- [ ] **8.1** Create the logrotate configuration

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
      sharedscripts
      postrotate
          systemctl kill --signal=HUP banknifty-observatory.service 2>/dev/null || true
      endscript
  }
  EOF
  ```

- [ ] **8.2** Test the configuration without rotating

  ```bash
  sudo logrotate --debug /etc/logrotate.d/banknifty-observatory
  # Expected: no errors; "log needs rotating" message is normal
  ```

---

## Section 9 — Backup verification

- [ ] **9.1** Confirm the S3 bucket exists and is reachable

  ```bash
  # Install AWS CLI if not present
  sudo apt install -y awscli

  aws s3 ls s3://YOUR_BUCKET_NAME/
  # Expected: listing (possibly empty) — not "NoSuchBucket" or auth error
  ```

- [ ] **9.2** Confirm S3 versioning is enabled on the raw data bucket

  ```bash
  aws s3api get-bucket-versioning --bucket YOUR_BUCKET_NAME
  # Expected: { "Status": "Enabled" }
  # If not enabled: aws s3api put-bucket-versioning \
  #     --bucket YOUR_BUCKET_NAME \
  #     --versioning-configuration Status=Enabled
  ```

- [ ] **9.3** Write a test file to confirm write access

  ```bash
  echo "deployment-check $(date -u)" | \
      aws s3 cp - s3://YOUR_BUCKET_NAME/raw/deploy-check.txt
  aws s3 ls s3://YOUR_BUCKET_NAME/raw/deploy-check.txt
  # Expected: file appears with a timestamp
  aws s3 rm s3://YOUR_BUCKET_NAME/raw/deploy-check.txt
  ```

- [ ] **9.4** Confirm the server has IAM permissions to write to `raw/` prefix

  ```bash
  aws s3api put-object \
      --bucket YOUR_BUCKET_NAME \
      --key raw/test-iam-check.txt \
      --body /dev/null
  aws s3 rm s3://YOUR_BUCKET_NAME/raw/test-iam-check.txt
  # Expected: no "AccessDenied" error
  ```

---

## Section 10 — First-run validation (smoke test)

Run this section during **market hours** (09:15–15:30 IST) on a trading day, or at any time if testing with a valid current expiry.

- [ ] **10.1** Run the smoke test as the service user

  ```bash
  sudo -u bno bash -c '
      cd /home/bno/banknifty-observatory
      PYTHONPATH=/home/bno/banknifty-observatory \
      /home/bno/.venv/bin/python scripts/smoke_test.py \
          --expiry 26JUN2026
  '
  # Expected: Verdict : PASS
  #           Auth    : PASS  (NNN.N ms)
  #           Spot    : PASS  (NNN.N ms)  ltp=NNNNN.N
  #           Chain   : PASS  (NNN.N ms)  rows=NNN  bytes=NNNNNN
  ```

  If `Verdict : FAIL`:
  - **Auth FAIL** → check `BNO_SMARTAPI_API_KEY`, `BNO_SMARTAPI_CLIENT_ID`, `BNO_SMARTAPI_PASSWORD`, `BNO_SMARTAPI_TOTP_PROVIDER`
  - **Chain FAIL** → check `BNO_CHAIN_EXPIRIES` format (must be DDMMMYYYY, e.g. `26JUN2026`)
  - **Config error** → check `BNO_CONFIG_SCHEMA_VERSION=2` and all required fields set

- [ ] **10.2** Verify smoke test output files were written

  ```bash
  ls -la /home/bno/banknifty-observatory/data/smoke/
  # Expected: one timestamped directory containing:
  #   auth_response.json   ← contains JWT tokens — never share
  #   spot_response.json
  #   chain_response.json
  #   smoke_summary.json
  #   logs/bno.log
  ```

- [ ] **10.3** Verify the smoke summary verdict

  ```bash
  SMOKE_DIR=$(ls -td /home/bno/banknifty-observatory/data/smoke/*/ | head -1)
  python3 -c "
  import json
  s = json.load(open('${SMOKE_DIR}smoke_summary.json'))
  print('Verdict:', s['verdict'])
  print('Auth latency:', s['auth']['latency_ms'], 'ms')
  print('Chain rows:', s['chain']['row_count'])
  "
  # Expected: Verdict: PASS
  ```

- [ ] **10.4** Confirm the smoke test log contains no credential leaks

  ```bash
  SMOKE_DIR=$(ls -td /home/bno/banknifty-observatory/data/smoke/*/ | head -1)
  grep -i "password\|secret\|totp\|SUoyscYa\|jwtToken.*ey" \
      "${SMOKE_DIR}logs/bno.log" || echo "No credential leaks in BNO log"
  # Expected: No credential leaks in BNO log
  # Note: The SmartAPI library's own internal log may contain X-PrivateKey headers.
  # This is a third-party library behaviour — our code does not log secrets.
  ```

- [ ] **10.5** Run a short timed phase to confirm the full controller loop

  ```bash
  sudo -u bno bash -c '
      cd /home/bno/banknifty-observatory
      PYTHONPATH=/home/bno/banknifty-observatory \
      /home/bno/.venv/bin/python scripts/discovery_run.py \
          --phase 1 \
          --max-duration 30
  '
  # Expected: [DONE] Phase 1 completed. Ticks: N, OK: N, Failed: 0
  # (Run during market hours; outside market hours ticks=0 is normal)
  ```

- [ ] **10.6** Verify JSONL data was written (run during market hours only)

  ```bash
  ls -lh /srv/bno/data/phase1/raw/
  # Expected: one YYYYMMDD.jsonl file, size > 0
  wc -l /srv/bno/data/phase1/raw/*.jsonl
  # Expected: one line per tick collected
  ```

---

## Section 11 — Health checks

- [ ] **11.1** Start the timer and confirm it is active

  ```bash
  sudo systemctl start banknifty-observatory.timer
  sudo systemctl is-active banknifty-observatory.timer
  # Expected: active
  ```

- [ ] **11.2** Check next scheduled trigger

  ```bash
  systemctl list-timers --no-pager | grep banknifty
  # Expected: NEXT shows tomorrow (or today) at 03:40 UTC on a weekday
  ```

- [ ] **11.3** Verify the service exits cleanly after the market session ends

  ```bash
  # Check the day after a full session:
  sudo systemctl status banknifty-observatory.service
  # Expected: Active: inactive (dead)
  #           Main PID: NNNNN (code=exited, status=0/SUCCESS)
  ```

- [ ] **11.4** Confirm the journal captured session start and end events

  ```bash
  journalctl -u banknifty-observatory --since "today" --no-pager | \
      grep -E "discovery_run_start|phase_ended|DONE|ABORT"
  # Expected: discovery_run_start entry followed by phase_ended / DONE
  ```

- [ ] **11.5** Confirm JSONL file is non-empty and parseable after a session

  ```bash
  JSONL=$(ls -t /srv/bno/data/phase1/raw/*.jsonl | head -1)
  wc -l "$JSONL"
  tail -1 "$JSONL" | python3 -c "import sys,json; d=json.load(sys.stdin); print('schema_version:', d['meta']['schema_version'])"
  # Expected: schema_version: 2
  ```

- [ ] **11.6** Confirm log file exists and is growing

  ```bash
  ls -lh /srv/bno/data/phase1/logs/
  # Expected: bno.log, non-empty, owned by bno:bno
  ```

- [ ] **11.7** Confirm no unhandled errors in today's session

  ```bash
  journalctl -u banknifty-observatory --since "today" --no-pager | \
      grep -c "CRITICAL\|controller_unhandled_error"
  # Expected: 0
  ```

---

## Section 12 — Recovery procedure

### 12.1 Service crash loop

If `sudo systemctl status banknifty-observatory` shows repeated restart attempts:

```bash
# Stop the restart loop
sudo systemctl stop banknifty-observatory

# Read the crash reason
journalctl -u banknifty-observatory -n 50 --no-pager

# Common causes and fixes:
#   BNOConfigError  → missing or wrong BNO_ env var in discovery.env
#   SessionAcquireError → API key/password/TOTP wrong or expired
#   ArchiverError   → /srv/bno/data not writable (check permissions)
#   PhaseAbortedError → check logs for root cause

# After fixing the root cause, the timer restarts it automatically next trading day.
# For immediate restart (market hours only):
sudo systemctl start banknifty-observatory
```

### 12.2 TOTP authentication failure

```bash
# Symptom: SessionAcquireError in logs, Auth FAIL in smoke test

# Verify the TOTP provider and secret are set
grep BNO_SMARTAPI_TOTP_PROVIDER /etc/banknifty-observatory/discovery.env
# Required: local_seed

grep -c BNO_SMARTAPI_TOTP_SECRET /etc/banknifty-observatory/discovery.env
# Expected: 1 (must be set and non-empty)

# Verify the TOTP seed generates the correct code (cross-check against
# your authenticator app — both should show the same 6-digit code):
sudo -u bno bash -c '
    TOTP_SECRET=$(grep BNO_SMARTAPI_TOTP_SECRET \
        /etc/banknifty-observatory/discovery.env | cut -d= -f2)
    /home/bno/.venv/bin/python -c "
import pyotp, sys
secret = sys.argv[1]
print(\"Current TOTP code:\", pyotp.TOTP(secret).now())
" "$TOTP_SECRET"
'
# If the code does not match your authenticator app, the seed is wrong.
# Retrieve the correct base32 seed from AngelOne and update discovery.env.

# Also verify clock sync — TOTP codes expire every 30 seconds:
timedatectl status | grep "System clock synchronized"
# Required: yes
```

### 12.3 Disk pressure

```bash
# Check available space
df -h /srv/bno /home/bno

# JSONL files are the main consumers. Check size:
du -sh /srv/bno/data/phase1/raw/
du -sh /srv/bno/data/phase1/logs/

# NEVER delete raw/ files without first confirming S3 replication.
# Verify the most recent JSONL is in S3:
LATEST=$(ls -t /srv/bno/data/phase1/raw/*.jsonl | head -1 | xargs basename)
aws s3 ls s3://YOUR_BUCKET/raw/ | grep "$LATEST"

# Only after S3 confirmation — compress old JSONL files:
gzip /srv/bno/data/phase1/raw/$(date -d "30 days ago" +%Y%m%d).jsonl
```

### 12.4 PostgreSQL down

```bash
# Symptom: store_write_failed warnings in logs (non-fatal — JSONL writes continue)

sudo systemctl status postgresql
sudo systemctl start postgresql

# Verify DB accepts connections:
sudo -u postgres psql -c "\l" | grep bno

# The controller continues writing to JSONL even when DB is unavailable.
# No data is lost — the JSONL archive is the primary store.
```

### 12.5 Full instance recovery (new VPS from scratch)

```bash
# Step 1: Complete Sections 1–9 above on the new instance.
# Step 2: Restore JSONL data from S3:
aws s3 sync s3://YOUR_BUCKET/raw/ /srv/bno/data/phase1/raw/
sudo chown -R bno:bno /srv/bno/data

# Step 3: Run smoke test (Section 10.1) to confirm connectivity.
# Step 4: Start the timer (Section 11.1).

# The new instance is operational. No code changes required —
# all state is in S3 and the environment file.
```

### 12.6 Expiry rollover missed (stale BNO_CHAIN_EXPIRIES)

```bash
# Symptom: chain_no_tokens errors in logs for a specific expiry

# Identify the expired expiry from logs:
journalctl -u banknifty-observatory --since "today" | grep "chain_no_tokens"

# Update the env file with the new active expiry:
sudo nano /etc/banknifty-observatory/discovery.env
# Change BNO_CHAIN_EXPIRIES to the current valid expiry

# The service picks this up on next start (no restart needed today).
# If the service is currently running, restart it:
sudo systemctl restart banknifty-observatory
```

---

## Sign-off

Complete this table before considering the deployment production-ready.

| Section | Completed by | Date | Notes |
|---|---|---|---|
| 1 — System packages | | | |
| 2 — Service account | | | |
| 3 — Directory permissions | | | |
| 4 — Python environment | | | |
| 5 — PostgreSQL setup | | | |
| 6 — Environment file | | | |
| 7 — systemd installation | | | |
| 8 — Log rotation | | | |
| 9 — Backup verification | | | |
| 10 — First-run validation | | | |
| 11 — Health checks | | | |
| 12 — Recovery procedure reviewed | | | |

**Deployment is production-ready when all rows are signed off and Section 10 (smoke test) returned `Verdict: PASS`.**
