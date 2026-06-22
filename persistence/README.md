# persistence/ — Layer 2: Raw Data Persistence

**Owner:** Platform / Data Engineering
**Change gate:** Standard code review

## Responsibility

Writes every captured record to three destinations reliably: local disk, PostgreSQL (`raw` schema), and S3. Owns the local durable buffer replay. Computes and stores checksums and manifests.

## What lives here

| Submodule | Purpose |
|-----------|---------|
| `raw/` | Write pipeline: buffer → DB raw schema → local disk |
| `s3/` | Continuous ship-on-write to S3 (system-of-record) |
| `manifest/` | Checksum computation and manifest file management |

## Three-destination rule

Raw must land in all three before a record is considered persisted:

```
collector → local buffer (immediate, synchronous)
          → DB raw schema (async, INSERT-only)
          → S3 (async, non-blocking to capture path)
```

S3 is the system-of-record for raw. The DB is the query index. Local disk is the hot working copy.

## Immutability

The application DB role has INSERT on `raw` only — no UPDATE, no DELETE. This is enforced at the database permission level, not by convention. See [`GOVERNANCE/PROJECT_CHARTER.md`](../GOVERNANCE/PROJECT_CHARTER.md).

## Buffer replay

When the DB recovers after an outage, `buffer/` is replayed with checksum verification before being cleared. Replay is idempotent.
