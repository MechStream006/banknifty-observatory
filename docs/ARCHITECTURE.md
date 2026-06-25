# BankNifty Observatory — Architecture

**Scope:** This document describes the Phase 1 platform as deployed. It is intended for
a new engineer who needs to understand how the system works without reading the source.
References to Phase 2 and beyond describe planned extensions, not current behaviour.

**Principle:** The observatory is a pure data recorder. It holds no positions, issues no
orders, and makes no trading decisions. Every design choice in this document flows from
that constraint.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Component Diagram](#2-component-diagram)
3. [Data Flow](#3-data-flow)
4. [Startup Sequence](#4-startup-sequence)
5. [Failure Paths](#5-failure-paths)
6. [Storage Layout](#6-storage-layout)
7. [Service Boundaries](#7-service-boundaries)
8. [Deployment Topology](#8-deployment-topology)

---

## 1. System Overview

### Purpose

The observatory collects BankNifty options market data on every trading day and stores
it in a raw, append-only archive. The archive is the foundation for later research
phases (derivation, labeling, analysis). No research conclusions are drawn in Phase 1 —
only data is collected.

### Platform phases

| Phase | Name | Status | Description |
|---|---|---|---|
| 0 | Smoke test | Implemented | One-shot connectivity and auth validation |
| 1 | Discovery | **Active** | 5-second polling during market hours |
| 2 | Derivation | Planned | Compute IV surface, Greeks, term structure |
| 3 | Labeling | Planned | Label outcomes against ratified cost model |

The system enforces phase separation: `BNO_STRATEGY_ACTIVE=true` is rejected at
startup. Phase 3 (labeling) cannot run without a ratified cost model version.

### What it collects each tick (every 5 seconds, 09:15–15:30 IST)

- BankNifty spot LTP (separate API call)
- India VIX LTP (independent API call)
- BankNifty option chain for each configured expiry — ±15 strikes around ATM on a
  500-point backbone (31 strikes × 2 sides × N expiries per tick)
- Derived values computed from the raw rows: total OI, total volume, OI put-call ratio,
  volume PCR, per-instrument OI change since the last tick

All data is immutable once written. The JSONL archive is never modified after append.

### Key constraints

- All configuration enters the process through `lib.config` only. No component reads
  `os.environ` directly.
- Credentials (`SecretStr` fields) are never written to log records, error messages,
  or snapshots.
- The SmartAPI Python library logs HTTP request headers at ERROR level, which includes
  the API key (`X-PrivateKey`). This is third-party behaviour outside our control.
  Log files at `/srv/bno/data/phase1/logs/` must not be shipped to external aggregators.

---

## 2. Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  External                                                                       │
│                                                                                 │
│  ┌──────────────────┐       ┌────────────────────┐     ┌──────────────────┐    │
│  │  SmartAPI / NSE  │       │  Telegram Bot API  │     │   AWS S3         │    │
│  │  (read-only)     │       │  (alert sink)      │     │   (raw backup)   │    │
│  └────────┬─────────┘       └────────┬───────────┘     └──────┬───────────┘    │
│           │ HTTPS outbound           │ HTTPS outbound          │ HTTPS outbound │
└───────────┼──────────────────────────┼─────────────────────────┼────────────────┘
            │                          │                          │
┌───────────┼──────────────────────────┼─────────────────────────┼────────────────┐
│  Process boundary (discovery_run.py) │                          │               │
│                                      │                          │               │
│  ┌──────────────────────────────┐    │                          │               │
│  │  lib.config                  │    │                          │               │
│  │  BNOSettings (pydantic)      │    │                          │               │
│  │  Reads BNO_* env vars once   │    │                          │               │
│  │  at startup; validates;      │    │                          │               │
│  │  singleton for process life  │    │                          │               │
│  └──────────────┬───────────────┘    │                          │               │
│                 │ settings           │                          │               │
│  ┌──────────────▼──────────────────────────────────────────┐   │               │
│  │  lib.logging                                            │   │               │
│  │  bootstrap_logging() → JSON-structured bno.* logger     │   │               │
│  │  SecretScrubberFilter attached to every Handler          │   │               │
│  │  AlertSink → Telegram ──────────────────────────────────┼───┘               │
│  └──────────────────────────────────────────────────────────┘                  │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  DiscoveryController                                                      │  │
│  │                                                                            │  │
│  │  ┌──────────────────┐   ┌────────────────┐   ┌─────────────────────────┐ │  │
│  │  │  SmartAPISession │   │  PollScheduler │   │  JSONLArchiver          │ │  │
│  │  │                  │   │                │   │                         │ │  │
│  │  │  connect()       │   │  ticks()       │   │  open() / write() /     │ │  │
│  │  │  refresh_if_     │   │  yields UTC dt │   │  close()                │ │  │
│  │  │  needed()        │   │  [09:15,15:30) │   │  YYYYMMDD.jsonl         │ │  │
│  │  │                  │   │  IST, Mon-Fri  │   │  append-only            │ │  │
│  │  │  → SmartConnect  │   │  drift-        │   │  auto-rotates midnight  │ │  │
│  │  │    (SmartAPI SDK)│   │  compensated   │   └─────────────────────────┘ │  │
│  │  └──────────────────┘   └────────────────┘                               │  │
│  │                                                                            │  │
│  │  Per-tick fetchers (called in order each tick):                            │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────────┐   │  │
│  │  │  SpotFetcher    │  │  VIXFetcher     │  │  ChainFetcher × N      │   │  │
│  │  │  ltpData call   │  │  ltpData call   │  │  getMarketData FULL     │   │  │
│  │  │  → LTP anchor   │  │  independent    │  │  ±15 strikes, 500pt    │   │  │
│  │  │  gates chains   │  │  of spot        │  │  one per expiry        │   │  │
│  │  └─────────────────┘  └─────────────────┘  └────────────────────────┘   │  │
│  │                                                                            │  │
│  │  _build_derived(): OI totals, PCRs, OI deltas (computed, not fetched)     │  │
│  │  _persist(): dataclasses.asdict() → JSONLArchiver.write()                 │  │
│  │                                                                            │  │
│  │  store=None (SQLiteAnalysisStore not yet implemented)                      │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                │                                │
│                         ┌──────────────────────┘                                │
│                         ▼                                                       │
│              /srv/bno/data/phase1/raw/YYYYMMDD.jsonl  ──(manual sync)──────────┼──► S3
│              /srv/bno/data/phase1/logs/bno.log                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow

### 3.1 Per-tick flow (every 5 seconds during market hours)

```
PollScheduler.ticks() yields tick_dt
         │
         ▼
session.refresh_if_needed()          ← noop unless token age ≥ 470 min
         │
         ▼
SpotFetcher.fetch(smart)
         │
         ├── success: ltp → resolved_atm = round(ltp / 500) * 500
         │
         └── failure: record written with empty chains[], derived=None
                      tick still completes (recoverable)
         │
         ▼ (parallel, independent of spot)
VIXFetcher.fetch(smart)              ← always attempted regardless of spot
         │
         ▼ (only if spot succeeded)
ChainFetcher.fetch(smart, spot) × N  ← one call per expiry in BNO_CHAIN_EXPIRIES
         │
         ▼
_build_derived(chain_results)
    total_ce_oi, total_pe_oi  per expiry (sum over window strikes)
    oi_pcr = total_pe_oi / total_ce_oi  per expiry (None if ce_oi == 0)
    volume_pcr                per expiry
    oi_changes: list[OIChange] = current_oi - prev_oi  (None on first tick)
    updates self._prev_oi for next tick
         │
         ▼
ObservationRecord assembled:
    poll_id: uuid4
    session_id: uuid4 (constant per phase run)
    polled_at: UTC timestamp
    meta: SnapshotMeta(schema_version=2, anchoring_spot, resolved_atm,
                       expiry_set, window_steps=15)
    spot: SpotResult
    vix: VIXResult
    chains: list[ChainResult]  (one per expiry, in expiry_set order)
    derived: DerivedObservation | None
    futures_result: None  (reserved for Phase 2)
         │
         ▼
dataclasses.asdict(record)
         │
         ▼
JSONLArchiver.write(record_dict)
    json.dumps → one line → append to /srv/bno/data/phase1/raw/YYYYMMDD.jsonl
    flush() on every write (no buffering)
```

### 3.2 JSONL record structure (schema version 2)

Each line in the archive is a single JSON object. The top-level fields are:

| Field | Type | Notes |
|---|---|---|
| `poll_id` | string (uuid4) | Unique per tick |
| `session_id` | string (uuid4) | Unique per phase run; constant across ticks |
| `polled_at` | ISO 8601 datetime | UTC |
| `phase` | int | Always 1 in current deployment |
| `tick_number` | int | 1-based counter within the session |
| `interval_s` | int | Configured interval (normally 5) |
| `meta` | object | `schema_version`, `anchoring_spot`, `resolved_atm`, `expiry_set`, `window_steps` |
| `spot` | object | `SpotResult`: `ltp`, `latency_ms`, `success`, `error`, `source` |
| `vix` | object | `VIXResult`: `ltp`, `latency_ms`, `success`, `error` |
| `chains` | array | One `ChainResult` per expiry — contains raw SmartAPI response |
| `derived` | object \| null | `DerivedObservation`: OI totals, PCRs, OI deltas |
| `futures_result` | null | Reserved; always null in Phase 1 |

**Reproducibility invariant:** Every value in `derived` is computable from `chains`. The
derived fields are stored as a convenience; they are not the authoritative source.

### 3.3 ATM window calculation

```
resolved_atm = round(spot_ltp / 500) * 500

Example: spot_ltp = 52347
         resolved_atm = round(52347 / 500) * 500
                      = round(104.694) * 500
                      = 105 * 500
                      = 52500

Window strikes: [52500 - (15×500), ..., 52500, ..., 52500 + (15×500)]
              = [45000, 45500, ..., 52500, ..., 59500, 60000]
              = 31 strikes total per expiry
```

---

## 4. Startup Sequence

### 4.1 Timeline (09:10 IST = 03:40 UTC on trading days)

```
03:40 UTC ── systemd timer fires
              │
              ▼
         ExecStartPre (1): scripts/check_disk_space.sh
              reads BNO_DATA_DIR from EnvironmentFile
              df --output=avail /srv/bno/data
              abort (exit 1) if < 2 GB free → systemd marks session FAILED
              │
              ▼
         ExecStartPre (2): scripts/validate_expiries.sh
              reads BNO_CHAIN_EXPIRIES from EnvironmentFile
              parses each entry with datetime.strptime(exp, "%d%b%Y")
              abort (exit 1) if any expiry is in the past or malformed
              │
              ▼
         discovery_run.py starts (User=bno)
              │
              ├── load_settings(env_file=".env")
              │       Reads all BNO_* vars from EnvironmentFile (injected by systemd)
              │       Validates schema version == 2
              │       Validates production rejects local_seed TOTP provider ⚠
              │       Validates BNO_STRATEGY_ACTIVE must be false
              │       Exits 1 on any validation failure
              │
              ├── _resolve_paths()
              │       Creates /srv/bno/data/phase1/raw/ and /logs/ if absent
              │
              ├── bootstrap_logging()
              │       JSON-structured handler to /srv/bno/data/phase1/logs/bno.log
              │       SecretScrubberFilter attached to all Handlers
              │       AlertSink → Telegram for ERROR and above
              │
              ├── Assemble components (no I/O yet):
              │       SmartAPISession(settings)
              │       ChainFetcher × N  (one per expiry in BNO_CHAIN_EXPIRIES)
              │       SpotFetcher(source_mode="separate_call")
              │       VIXFetcher()
              │       PollScheduler(interval_seconds=5)
              │       JSONLArchiver(output_dir=raw_dir)
              │       DiscoveryController(all above, store=None)
              │
              └── controller.run()
                       │
                       ├── archiver.open()
                       │       creates YYYYMMDD.jsonl for today
                       │
                       ├── session.connect()
                       │       generates TOTP (local_seed only) ⚠
                       │       SmartAPI generateSession() → JWT
                       │       retries once on failure
                       │
                       └── Wait for market open (09:15 IST)
                               PollScheduler sleeps in 1-second increments
                               until is_market_open() returns True
                               │
                               ▼
                          09:15 IST — tick loop begins
                               5-second drift-compensated intervals
                               until is_market_closed_for_day() at 15:30 IST
```

### 4.2 TOTP provider constraint (known implementation gap)

The config validator rejects `local_seed` in production. The session code only
implements `local_seed` — any other value raises `SessionAcquireError` at
`session.connect()`. The result:

| `BNO_SMARTAPI_TOTP_PROVIDER` | `BNO_ENV=production` | `BNO_ENV=development` |
|---|---|---|
| `local_seed` | Config error at startup (rejected by validator) | Works |
| `authenticator_app` | Config loads, then `SessionAcquireError` at auth | `SessionAcquireError` at auth |
| `secrets_manager` | Config loads, then `SessionAcquireError` at auth | `SessionAcquireError` at auth |

**Practical implication:** Production currently requires `BNO_ENV=development` or a
custom `local_seed` production config (bypassing the production validator check) to
operate. `authenticator_app` and `secrets_manager` are defined in the schema for future
implementation. See `lib/discovery/session.py:_generate_totp()`.

---

## 5. Failure Paths

### 5.1 Controller state machine

```
     IDLE
      │
      │ controller.run() called
      ▼
   STARTING
      │
      ├── archiver.open() raises ArchiverError ────────────────────────► ABORTED
      │                                                                    exit 1
      ├── session.connect() raises SessionAcquireError (both retries) ──► ABORTED
      │                                                                    exit 1
      ▼
   RUNNING  ◄────────────────────────────────────────────────────────────────┐
      │                                                                       │
      ├── session.refresh_if_needed() raises SessionRefreshError ──────────► ABORTED
      │                                                                    exit 1
      ├── archiver.write() raises ArchiverError ────────────────────────► ABORTED
      │                                                                    exit 1
      │
      │  Recoverable per tick (tick completes, poll_failed_count++):
      ├── SpotResult(success=False) → chains=[], derived=None, record written
      ├── VIXResult(success=False)  → vix.success=False in record, chains continue
      ├── ChainResult(success=False) → that expiry fails, others continue
      └── StoreError (DB write) → WARNING logged, tick continues
      │
      │ 15:30 IST reached / max_duration exceeded / KeyboardInterrupt / SIGTERM
      ▼
   STOPPING
      │
      └── archiver.close()
      ▼
   STOPPED ──────────────────────────────────────────────────────────────► exit 0
```

### 5.2 What happens for each failure class

| Failure | Scope | Recovery | Log event |
|---|---|---|---|
| NTP clock drift (TOTP invalid) | Session | Manual: verify `timedatectl`, fix clock, restart | `session_acquire_retrying` then `SessionAcquireError` |
| Stale expiry in `BNO_CHAIN_EXPIRIES` | Pre-flight | Automatic: validate_expiries.sh blocks startup | Script prints `ABORT:`, exits 1, systemd marks FAILED |
| Disk full | Pre-flight | Manual: free space, restart timer | Script prints `ABORT:`, exits 1 |
| Disk full mid-session | Archiver | Fatal — ABORTED | `ArchiverError`: Write failed |
| Bad API key / password | Session | Manual: fix credentials, restart | `SessionAcquireError` (attempt 2) |
| SmartAPI rate limit | Single tick | Auto: next tick retried normally | `ChainResult(success=False)` |
| SmartAPI down | Multiple ticks | Auto: continues with spot/VIX, chains fail | Per-tick `failed_polls++` |
| Token expires mid-session | Session | Auto: `refresh_if_needed()` re-auths | `session_refresh_triggered` |
| Token refresh fails | Session | Fatal — ABORTED | `session_refresh_abort` then `SessionRefreshError` |
| VPS reboot mid-session | All | `Persistent=true` restarts service at next timer | Systemd restart; existing JSONL append-continues |
| `KeyboardInterrupt` / `SIGTERM` | Session | Graceful stop | `controller_interrupted` |
| Unhandled Python exception | Session | Fatal — ABORTED | `controller_unhandled_error` (CRITICAL) |

### 5.3 SIGTERM handling

systemd sends SIGTERM when stopping the service. `discovery_run.py` maps
`SIGTERM → KeyboardInterrupt`. The controller catches `KeyboardInterrupt`,
transitions to `STOPPING`, closes the archiver cleanly, and returns `PhaseResult`.
The process exits 0. systemd does not mark this as a failure.

If the process does not exit within 30 seconds (`TimeoutStopSec=30`), systemd
sends `SIGKILL`. At that point, the current JSONL line may be incomplete or
absent; all previously flushed lines are intact.

### 5.4 Session restart mid-day

If the service crashes (exit 1) during a session and `Restart=on-failure` fires:
- The existing `YYYYMMDD.jsonl` file is preserved (not truncated on re-open; the
  archiver uses `open(..., "a")`).
- The restarted process appends to the existing file.
- `tick_number` resets to 1 and `session_id` changes. The file therefore contains
  data from two or more sessions with a gap at the timestamps of the crash.
- `oi_changes` on the first tick of the new session is `None` (no prev_oi carried
  across process restart).

---

## 6. Storage Layout

### 6.1 Filesystem

```
/srv/bno/
├── data/
│   ├── phase1/
│   │   ├── raw/
│   │   │   └── YYYYMMDD.jsonl        ← one file per calendar day
│   │   │       append-only; auto-rotated at midnight
│   │   │       each line: one ObservationRecord as JSON
│   │   ├── logs/
│   │   │   └── bno.log               ← structured JSON, one line per log event
│   │   │       rotated daily by logrotate (90-day retention)
│   │   └── discovery.db              ← SQLite (future; never created in Phase 1)
│   └── buffer/
│       └── (reserved; not used in Phase 1)
/etc/banknifty-observatory/
└── discovery.env                     ← 640 root:bno; loaded by systemd EnvironmentFile=
/home/bno/
├── banknifty-observatory/            ← source tree (git clone)
│   ├── lib/                          ← importable library
│   ├── scripts/                      ← entrypoints + pre-flight utilities
│   ├── tests/
│   ├── deployment/
│   └── pyproject.toml
└── .venv/                            ← Python 3.11 virtual environment
/etc/systemd/system/
├── banknifty-observatory.service
└── banknifty-observatory.timer
/etc/logrotate.d/
└── banknifty-observatory
```

### 6.2 JSONL naming and rotation

The archiver derives the filename from `date.today()` at the time of the first write
each day. If a session runs past midnight (which does not happen in normal market-hours
operation, but could during a manual `--max-duration` run), the archiver rotates to a
new file automatically on the first write after midnight.

Files are never deleted by the application. Retention is managed by the operator
(compress and remove after confirming S3 sync; see `deployment/production_checklist.md`
Section 9).

### 6.3 Log file

`bno.log` is a newline-delimited JSON file written by the `bno.*` logger hierarchy.
Each line is one log event. Fields include: `timestamp`, `level`, `logger`, `message`,
and any `extra` dict fields passed by the caller.

**Warning:** The SmartAPI library (`smartapi-python`) also creates its own log artefacts
in the working directory using `logzero`. These are created when `SmartConnect` is
instantiated and may contain `X-PrivateKey: <API_KEY>` in HTTP request headers logged
at ERROR level. These files are gitignored but must be treated as sensitive on the
server. Do not ship `/srv/bno/data/phase1/logs/` to an external log aggregator.

### 6.4 Database (not active in Phase 1)

PostgreSQL is provisioned but not connected. `store=None` is passed to the controller
in every Phase 1 invocation. `lib/db/` is an empty stub. When the store is activated
in a future phase, the controller's `_persist()` will call `store.insert(record)` after
the mandatory JSONL write. A `StoreError` from the store is non-fatal (logged as
WARNING); an `ArchiverError` from JSONL is fatal (ABORTED).

The design intent is that JSONL is always the primary, authoritative archive, and the
database is a secondary query-optimised store that can be rebuilt from JSONL at any
time.

---

## 7. Service Boundaries

### 7.1 External API calls (outbound only)

| Destination | Protocol | Auth | Purpose | Failure handling |
|---|---|---|---|---|
| SmartAPI (AngelOne) | HTTPS | JWT + API key + TOTP | Market data fetch (spot, VIX, chains) | `*Result(success=False)` — tick continues |
| SmartAPI — session | HTTPS | API key + TOTP | `generateSession()` → JWT | `SessionAcquireError` — retried once, then fatal |
| Telegram Bot API | HTTPS | Bot token | ERROR/CRITICAL alerts | Best-effort; failure does not affect data collection |
| AWS S3 | HTTPS | IAM credentials | Raw data backup | Manual sync only (not automated in Phase 1) |

The process makes no inbound connections. There is no HTTP server, no health endpoint,
and no inter-process communication.

### 7.2 Configuration boundary

`lib.config` is the single entry point for all configuration. The `BNOSettings` singleton
is loaded once at startup and passed by reference to every component that needs it.

**Architectural rule enforced by `test_access_enforcement.py`:** No Python file outside
`lib/config/` may access `os.environ` directly. All configuration must flow through
`lib.config.get_settings()`. Violations are caught as test failures.

### 7.3 Secret boundary

Credentials are stored as pydantic `SecretStr` fields. `.get_secret_value()` is called
only in `SmartAPISession._do_auth()` and `SmartAPISession._generate_totp()`. Credentials
are never logged, never passed to exception constructors, and never appear in `repr()`
output. `SecretScrubberFilter` is attached to every log handler as a defence-in-depth
measure.

### 7.4 Persistence boundary

The only persistent writes the process makes are:

1. `JSONLArchiver.write()` → append to `/srv/bno/data/phase1/raw/YYYYMMDD.jsonl`
2. `logging.Handler` → append to `/srv/bno/data/phase1/logs/bno.log`
3. SmartAPI SDK (`logzero`) → its own log files in the working directory (not under our
   control)

`ProtectSystem=strict` in the systemd unit confines all writes to `ReadWritePaths=/srv/bno/data`.
The source tree at `/home/bno/banknifty-observatory/` is read-only from the service's
perspective.

### 7.5 Component dependencies

```
discovery_run.py
 ├── lib.config              (no external deps)
 ├── lib.logging             (no external deps except Telegram outbound)
 └── lib.discovery
      ├── SmartAPISession    (depends on: SmartApi SDK, pyotp, lib.config)
      ├── PollScheduler      (depends on: stdlib only)
      ├── JSONLArchiver      (depends on: stdlib only)
      ├── SpotFetcher        (depends on: SmartApi SDK)
      ├── VIXFetcher         (depends on: SmartApi SDK)
      ├── ChainFetcher       (depends on: SmartApi SDK)
      └── DiscoveryController (orchestrates all above; no external deps itself)
```

Components are assembled in `discovery_run.py` and passed as constructor arguments.
No component imports any other component directly — all dependencies are injected.
This is why the test suite can substitute mock fetchers and a fake archiver without
patching any module-level globals.

---

## 8. Deployment Topology

### 8.1 Current topology (Phase 1)

```
┌──────────────────────────────────────────────────────────────┐
│  VPS (Ubuntu 22.04)                                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  systemd                                               │  │
│  │                                                        │  │
│  │  banknifty-observatory.timer                           │  │
│  │    OnCalendar=Mon..Fri 03:40:00 UTC                    │  │
│  │    Persistent=true                                     │  │
│  │       │                                                │  │
│  │       ▼                                                │  │
│  │  banknifty-observatory.service                         │  │
│  │    User=bno                                            │  │
│  │    EnvironmentFile=/etc/banknifty-observatory/         │  │
│  │                     discovery.env                      │  │
│  │    ExecStartPre=scripts/check_disk_space.sh            │  │
│  │    ExecStartPre=scripts/validate_expiries.sh           │  │
│  │    ExecStart=python scripts/discovery_run.py --phase 1 │  │
│  │    ProtectSystem=strict                                │  │
│  │    ReadWritePaths=/srv/bno/data                        │  │
│  │    MemoryMax=512M                                      │  │
│  │    Restart=on-failure  (3 attempts / 5 min)            │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  /srv/bno/data/phase1/raw/  ────(manual aws s3 sync)──────────┼──► S3
│  /srv/bno/data/phase1/logs/                                  │
│  /etc/banknifty-observatory/discovery.env  (640 root:bno)    │
│                                                              │
│  postgresql (localhost:5432)  ← provisioned, not connected   │
└──────────────────────────────────────────────────────────────┘
         │ outbound HTTPS only
         ▼
  api.smartapi.in  (market data)
  api.telegram.org (alerts)
  s3.ap-south-1.amazonaws.com (backup)
```

### 8.2 Network policy

The VPS firewall allows only inbound SSH (port 22). All application traffic is outbound
HTTPS (port 443). The application has no inbound ports. PostgreSQL listens on localhost
only — no external database connections.

### 8.3 Process lifecycle per trading day

```
03:40 UTC   timer fires → pre-flight scripts → process starts
03:40–09:15 PollScheduler waits (1-second sleeps) for market open
09:15 IST   tick loop begins (5-second intervals)
15:30 IST   PollScheduler returns → controller transitions STOPPING → STOPPED
            archiver.close() → process exits 0
            systemd records clean exit
03:40 UTC   next trading day: timer fires again
```

On public holidays, the market is not open at 09:15 IST. `PollScheduler.is_market_open()`
returns False, the scheduler reaches `_market_closed_for_day()` at 15:30 IST, and the
process exits 0 having collected 0 ticks. No data corruption occurs; the JSONL file for
that day is not created (archiver only opens a file on first write).

### 8.4 What is not deployed

The following exist in the codebase but are not active in the current deployment:

| Component | Location | Status |
|---|---|---|
| PostgreSQL store | `lib/db/` (empty stub) | `store=None` always |
| Buffer directory | `/srv/bno/data/buffer/` | Created, never written |
| Labeling pipeline | `BNO_LABELING_ACTIVE=false` | Blocked by startup validator |
| Strategy modules | `future/` (sealed directory) | Excluded from installed package |
| Phase 2 futures | `futures_result` field | Always `None` in Phase 1 records |

### 8.5 Scaling considerations (not current)

Phase 1 is designed to run on a single VPS with no horizontal scaling. All state is in
the JSONL archive (immutable, append-only), so a replacement instance can resume from
the same S3-synced files with no coordination. A multi-expiry run with 3+ expiries
may approach the 512 MB memory cap; measure actual RSS with `ps aux` or
`systemctl status` before adding expiries beyond the current 2-expiry default.
