# REPOSITORY_RULES

> **Control Block**
> - **Purpose:** Define the structural and contribution rules that make the repository enforce governance by construction — including ownership boundaries, the observed/derived seam, and the sealed-module rule.
> - **Why it exists:** Governance that lives only in documents erodes. Encoding it into the repository's structure makes the wrong thing *physically awkward* to do — a strategy cannot be wired in by accident, raw cannot be mutated casually, derived cannot masquerade as observed. The repo layout is itself a control.
> - **Approval required:** Platform architect + research governance. Ratified via DECISION_LOG.
> - **Change-control:** Changes to ownership boundaries, the seam, or the sealed-module rule require a DECISION_LOG entry. Adding or activating anything under `future/` requires stage authorization per [[STAGE_GATE_POLICY]].
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. Structural Rules

1. **`GOVERNANCE/` is supreme and self-documenting.** Every governance doc carries a Control Block and links related docs.
2. **The observed/derived seam is enforced by layout.** Observed-data code/storage and derived-data code/storage live in separate trees and never share a module or table.
3. **`lib/` is strategy-free by construction.** No `strategy/`, `execution/`, `risk/`, `signals/` directories exist in the active tree.
4. **Future modules are sealed and named to resist accidental activation** (e.g., `future/_DISABLED_strategy_engine/`). Their presence documents intent; their naming prevents wiring-in.
5. **Raw is immutable at the permission level**, not just by convention — the application role cannot mutate or delete raw.

## 2. Ownership Boundaries

| Area | Owner | Change gate |
|---|---|---|
| `GOVERNANCE/`, `derivation/methodologies/` | research governance | DECISION_LOG entry |
| `acquisition/`, `persistence/`, `integrity/` | platform / data eng | standard review |
| `research/` (labeling, evidence, registry) | quant research | governance review |
| `future/_DISABLED_*` | sealed | stage authorization |
| `config/` contracts | platform + governance | DECISION_LOG for mandatory keys |

## 3. Contribution Rules

- Anything that changes **what evidence means** (governance, methodology, cost model, opportunity definition) requires a DECISION_LOG entry.
- Research parameters (horizons, label spec, cost-model version) are **versioned experimental inputs**, not casual config.
- The labeling subsystem ships present-but-dormant until a ratified `cost_model_version` exists.
- No commit may activate a `future/` module without a logged stage authorization.

## 4. Reproducibility Rules

- Every derived/evidence artifact must be reproducible from raw + versioned spec + versioned config.
- Raw payloads and large data are excluded from version control; **manifests, checksums, and lineage are tracked.**
- The effective configuration of every run is snapshotted (secrets redacted) into the run's lineage record.

## 5. Prohibited

- Mutating or deleting raw.
- Storing derived values as if observed.
- Introducing any threshold, direction, or conditioning into the labeling layer ([[OPPORTUNITY_DEFINITION]] firewall).
- Activating trading-related modules outside a stage gate.
- Editing the DECISION_LOG or any append-only register.

## 6. Example Ownership Note (illustrative)

```
path: derivation/methodologies/cost_model/
owner: research governance
rule: any change is a methodology version event (METHODOLOGY_VERSIONING_POLICY)
      requiring DECISION_LOG entry + recompute assessment of net-of-cost labels.
```
