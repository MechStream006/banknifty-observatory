# config/ — Configuration Contracts

**Owner:** Platform + Governance (joint)
**Change gate:** Changes to mandatory keys require DECISION_LOG entry

## Responsibility

Configuration contracts and example files. All runtime configuration is environment-driven using `BNO_`-prefixed variables. This directory holds static configuration artifacts that are version-controlled — scope definitions, instrument lists, and configuration contracts.

## What lives here

| File | Purpose |
|------|---------|
| `instrument_scope.yml.example` | Defines which BankNifty strikes and expiries are in scope |

## Rules

- **Secrets are never committed.** The `.env.example` at the repository root is the only place secrets appear, as clearly marked placeholders.
- **Adding or removing a required `BNO_` key is a change-controlled event** — it must be reflected in `.env.example`, validated in `lib/config/`, and logged in DECISION_LOG if it affects the experimental record.
- **`BNO_CONFIG_SCHEMA_VERSION`** tracks breaking changes to the configuration contract. A mismatch between the running version and the config loader's expected version causes a startup rejection.

## Production secrets

In staging and production, secrets are retrieved from AWS Secrets Manager or SSM Parameter Store. The config loader supports both `.env` file mode (local/development) and secrets manager mode (staging/production), selected by `BNO_ENV`.
