# lib/ — Shared Platform Utilities

**Owner:** Platform / Data Engineering
**Change gate:** Standard code review

## Responsibility

Shared utilities consumed by all other layers. This directory is **strategy-free by construction**. No strategy, signals, execution, or risk modules may exist here or anywhere in the active tree.

## What lives here

| Submodule | Purpose |
|-----------|---------|
| `config/` | Configuration loader: validates BNO_ env vars, rejects missing required keys, produces redacted snapshot for lineage |
| `logging/` | Structured JSON logging with secret scrubbing, per-service log files, run-id tagging |
| `metrics/` | Prometheus metrics endpoint: ops-plane and integrity-plane metric families — kept separate |
| `db/` | Database connection pool, health check, migration runner interface |

## Strategy-free rule

`lib/` contains no imports from `future/`, no references to strategy, execution, risk, or trading concepts. Any addition to `lib/` that introduces such a reference is a REPOSITORY_RULES violation.

## Secret handling

`lib/logging/` applies a secret scrubber to all log records. Any value matching `*_PASSWORD`, `*_SECRET`, `*_TOKEN`, `*_KEY` patterns is replaced with `[REDACTED]` before writing. This scrubber is applied at the framework level, not per callsite.

`lib/config/` validates presence of secrets but never logs their values.
