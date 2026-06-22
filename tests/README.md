# tests/ — Test Suite

**Owner:** Platform / Data Engineering + Quant Research (by layer)
**Change gate:** Standard code review

## Responsibility

Platform test suite. Unit tests for pure logic; integration tests for anything that requires a database or external service.

## Structure

| Directory | Purpose |
|-----------|---------|
| `unit/` | Pure logic tests. No I/O, no DB, no external calls. Fast. |
| `integration/` | Tests requiring a real database or real service. |

## Integration test policy

**Integration tests must use a real database, not mocks.**

Mocked DB tests have historically masked migration divergence between test and production environments. Integration tests spin up a real PostgreSQL + TimescaleDB instance (local or CI-provisioned) and run against it. This is non-negotiable.

## Running tests

```bash
# Unit tests only (fast)
pytest tests/unit/

# All tests (requires DB)
pytest tests/

# With coverage
pytest --cov=. tests/
```

## Naming convention

- Unit tests: `test_{module_name}.py` mirroring the source tree
- Integration tests: `test_integration_{feature}.py`
