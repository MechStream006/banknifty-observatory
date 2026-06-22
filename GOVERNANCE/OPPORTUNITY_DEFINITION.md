# OPPORTUNITY_DEFINITION

> **Control Block**
> - **Purpose:** Define the single research target the observatory measures — what counts as an "opportunity" — in a way that is objectively measurable, labelable after the fact, strategy-agnostic, hypothesis-ready, net-of-cost aware, and regime-robust.
> - **Why it exists:** Everything downstream (data, labels, evidence, promotion) inherits from this definition. If the target is defined to secretly presuppose a strategy, the entire program measures the wrong thing precisely. This document fixes the target before any labeling code is written.
> - **Approval required:** Quant research director + research governance. Ratified via DECISION_LOG.
> - **Change-control:** A change to the definition invalidates the comparability of prior labels. Any change bumps the label-spec version, requires recompute of affected evidence, and is logged with a rationale. The Stage-2/Stage-4 firewall (below) may not be weakened.
> - **Status:** DRAFT.
> - **Version:** 0

---

## 1. The Definition

> **An opportunity is the net-of-cost forward realized displacement of a real tradeable BankNifty instrument, measured at executable (bid/ask) prices, over a defined horizon grid, expressed as a continuous signed magnitude — stored unconditionally alongside the ex-ante observable state and the regime tag.**

It is **not** "a move you could have captured." No entry, exit, direction, or holding rule is assumed. The observatory measures *exploitable structure that existed*, not *profit that would have been made*.

## 2. Required Properties (and how each is satisfied)

- **Objectively measurable** — it is a realized price difference at executable prices; no model.
- **Labelable after the fact** — computed only from matured, realized data.
- **Strategy-agnostic** — no threshold, no direction, no entry/exit baked in.
- **Hypothesis-ready** — ex-ante state stored beside ex-post outcome.
- **Net-of-cost aware** — the cost barrier comes from the ratified cost model; displacement that does not clear cost is, by definition, not opportunity.
- **Regime-robust** — labeled unconditionally and tagged by regime, so any regime slice is possible later.

## 3. The Opportunity Primitive (record shape, conceptual — not a schema)

Each labeled window stores:
- instrument identity (actual option / defined structure, at its own quotes)
- anchor time
- **vector of net-of-cost forward displacements across the horizon grid**
- MFE/MAE envelope, explicitly flagged as a *bound*, never as the opportunity
- cost applied + `cost_model_version`
- regime tag
- **ex-ante observable state vector** (OI, ΔOI, IV, volume, spread, depth, time-of-day, session phase, expiry distance, event flags)
- `label_spec_version`, full lineage

## 4. Complementary Lenses (not competing primitives)

- **MFE/MAE** — stored only as a bound.
- **Realized-minus-implied vol gap** — a standing descriptive view.
- **Mispricing vs. fair value** — deferred until a fair-value reference is *earned* from BankNifty's own data.
- **Microstructure dislocation** — deferred until data fidelity is proven.
- **Conditional distributional shift** — this is the **form hypotheses take**, never the form labels take.

## 5. The Stage-2 / Stage-4 Firewall (non-negotiable)

- **Labeling (Stage 2/3) is descriptive and unconditional.** Every eligible window is labeled. No thresholds, no direction, no conditioning state chosen at label time.
- **Conditioning (Stage 4) is hypothesis testing.** "How many opportunities were there" is answered by *querying* the corpus with a condition, never by the label itself.
- A conditioning opinion entering the labeling layer is a **contamination event** and must be logged and reverted.

## 6. Cost Dependency (non-negotiable)

No net-of-cost label is produced before a ratified `cost_model_version` exists. Until then the platform captures state and *unlabeled* forward displacement only. This is enforced in configuration and service gating.

## 7. What Is Explicitly Excluded

- Binary "opportunity / no opportunity" labels.
- Sign-filtered (favorable-direction-only) labels.
- Any label that embeds a fitted threshold.
- Any displacement measured on the index directly (the index is not tradeable; measure on instruments).

## 8. Example (illustrative)

```
window:
  instrument: BANKNIFTY <expiry> <strike> <CE/PE>
  anchor: 2026-08-04T10:32:00+05:30
  net_of_cost_displacement:
    60s:   -3.1
    300s:  +8.7
    900s:  +21.4
    3600s: +12.0
  mfe_mae_bound: { mfe: +27.5, mae: -9.2 }   # bound only
  cost_model_version: 1
  regime: high_vol_expiry_week
  state_vector: { ... ex-ante observables ... }
  label_spec_version: 1
```
