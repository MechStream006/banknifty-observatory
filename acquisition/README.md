# acquisition/ — Layer 1: Market Data Acquisition

**Owner:** Platform / Data Engineering
**Change gate:** Standard code review

## Responsibility

Owns the SmartAPI session lifecycle and all per-family market data collectors. This layer captures raw market observations and hands them to the persistence layer. Nothing else.

## What lives here

| Submodule | Purpose |
|-----------|---------|
| `session/` | SmartAPI authentication, TOTP, token lifecycle, reconnection |
| `collectors/spot/` | BankNifty spot price capture |
| `collectors/chain/` | Full option chain polling (all strikes, all expiries) |
| `collectors/oi/` | Open interest and delta-OI capture |
| `collectors/volume/` | Volume capture |
| `collectors/depth/` | Bid/ask quotes and order book depth — mandatory for cost model |
| `buffer/` | Durable local buffer for DB-unavailable scenarios |

## What does NOT live here

- No derived values (IV, greeks, PCR). Those belong in `derivation/`.
- No business logic beyond: capture, timestamp, write.
- No strategy or signal logic. Ever.

## Timestamping rule

Every record produced by this layer carries two timestamps:
1. `source_ts` — exchange-provided timestamp where available; receipt time otherwise
2. `receipt_ts` — local system time when the record was received

Both in ISO 8601, Asia/Kolkata canonical timezone.

## Failure behavior

If the database is unavailable, collectors continue writing to `buffer/`. Raw is never lost due to a DB outage. See [`GOVERNANCE/DATA_INCIDENT_POLICY.md`](../GOVERNANCE/DATA_INCIDENT_POLICY.md).
