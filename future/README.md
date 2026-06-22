# future/ — Sealed Future Modules

**Owner:** Sealed — no active owner
**Change gate:** Activation of any module here requires a stage-authorization token + DECISION_LOG entry + project owner sign-off per STAGE_GATE_POLICY

## Purpose

This directory documents intent without enabling it. Each `_DISABLED_*` subdirectory represents a module that will be needed at a future stage but must not be activated prematurely.

The `_DISABLED_` prefix and the `raise ImportError` in each `__init__.py` make accidental wiring-in impossible — the module will loudly refuse to import.

## Sealed modules

| Module | Activation stage | Gate |
|--------|-----------------|------|
| `_DISABLED_strategy_engine/` | Stage 5 (Strategy Research) | Stage 5 promotion in DECISION_LOG |
| `_DISABLED_execution_engine/` | Stage 6 (Paper Trading) | Stage 6 promotion in DECISION_LOG |
| `_DISABLED_risk_manager/` | Stage 6 (Paper Trading) | Stage 6 promotion in DECISION_LOG |
| `_DISABLED_paper_trading/` | Stage 6 (Paper Trading) | Stage 6 promotion in DECISION_LOG |
| `_DISABLED_live_trading/` | Stage 7 (Production) | Stage 7 promotion in DECISION_LOG |

## Activation procedure

1. A stage gate review is completed with the pre-committed exit criteria met.
2. The project owner signs the promotion in DECISION_LOG (a second reviewer must be present).
3. A stage-authorization token is issued in the log entry.
4. The module's `__init__.py` is updated to remove the `raise ImportError` guard.
5. The module is moved from `future/` to the active tree.

No module may be activated outside this procedure. See [`GOVERNANCE/STAGE_GATE_POLICY.md`](../GOVERNANCE/STAGE_GATE_POLICY.md) and [`GOVERNANCE/REPOSITORY_RULES.md`](../GOVERNANCE/REPOSITORY_RULES.md).
