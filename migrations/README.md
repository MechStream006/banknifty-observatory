# migrations/ — Database Migrations

**Owner:** Platform / Data Engineering
**Change gate:** Every migration is a one-way, versioned, reviewed change. Migrations affecting the `raw` schema require explicit immutability review.

## Responsibility

Alembic-managed database migrations. Each migration is versioned, sequential, and reviewed before being applied to any environment above development.

## Rules

- Migrations are applied in order. They are never edited after being applied.
- Migrations that touch the `raw` schema must confirm that immutability guarantees are preserved (no UPDATE/DELETE grants introduced).
- Down-migrations for destructive operations (DROP TABLE, DROP COLUMN) must be reviewed with extra care — raw data is permanent.
- The migration history is tracked in `alembic_version` in the database. The migration files here are the source of truth.

## Naming convention

`{revision}_{short_description}.py`

Example: `001_foundation_schemas.py`, `002_add_timescale_hypertables.py`
