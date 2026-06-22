from __future__ import annotations

# Bumped whenever a required key is added, removed, or its type changes.
# Must match BNO_CONFIG_SCHEMA_VERSION in the running environment.
#   version 1 — initial Phase-0 schema
#   version 2 — Phase-1 contract: adds BNO_CHAIN_EXPIRIES (required)
EXPECTED_CONFIG_SCHEMA_VERSION: int = 2

KNOWN_ENVIRONMENTS: frozenset[str] = frozenset({
    "development",
    "staging",
    "production",
})
