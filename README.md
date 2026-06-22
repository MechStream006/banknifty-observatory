# BankNifty Observatory

A long-term market research instrument for the BankNifty index and options ecosystem.

---

## What this is

A continuously operating system that collects, validates, and derives metrics from BankNifty market data with the goal of producing **trustworthy, reproducible evidence** about market behaviour.

The observatory is complete and valuable at the observation stage alone. Whether or not it leads to strategy research is a consequence of evidence, not an assumption built into the architecture.

## What this is NOT

| Not this | Why it matters |
|---|---|
| **No live trading** | No order placement, no capital at risk, no execution engine |
| **No broker integration in scope** | Data-access credentials are a deployment concern, not a repository concern |
| **No strategy implementation** | Strategy gates are sealed; activation requires prior evidence and explicit sign-off |
| **No edge assumption** | The project null hypothesis is that no defensible edge exists — everything is earned |

## Purpose

1. **Evidence collection** — instrument-grade BankNifty snapshot data with full audit trail
2. **Hypothesis development** — structured framework for forming, testing, and retiring hypotheses
3. **Derived metric production** — versioned computation of OI, PCR, IV, regime indicators
4. **Reproducibility** — every derived value is traceable to raw data and a pinned methodology version

The equally valid outcome is a well-evidenced conclusion that **no exploitable pattern exists**. That saves capital and counts as success.

## Repository structure

```
banknifty-observatory/
├── docs/               # Project charter, roadmap, glossary
├── decisions/          # Engineering and research decision log
└── research/           # Hypothesis registry, observations, evidence log
```

## Key documents

| Document | Purpose |
|---|---|
| [Project Charter](docs/project_charter.md) | Mission, non-negotiables, scope boundaries |
| [Roadmap](docs/roadmap.md) | Research phases and current status |
| [Glossary](docs/glossary.md) | Domain and platform terminology |
| [Decision Log](decisions/decision_log.md) | Architectural and research decisions |
| [Hypotheses](research/hypotheses.md) | Active and retired hypothesis registry |
| [Evidence Log](research/evidence_log.md) | Evidence collected against each hypothesis |

## Research principles

1. **Assume no edge exists.** Every pattern claim requires evidence that survives the project's evidence standard.
2. **Observed data and derived interpretation are separate.** No derived value is computed without a pinned, versioned methodology.
3. **Rejected hypotheses are retained.** Resurrecting a rejected hypothesis requires new data or a new mechanism — not optimism.
4. **No label is produced without a ratified cost model.** Opportunity labeling is gated behind explicit cost-model ratification.
5. **Operational health and data integrity are alarmed separately.** A silent data gap is as serious as a system crash.

## Current status

| Phase | Status |
|---|---|
| Phase 0 — Infrastructure and governance | In progress |
| Phase 1 — Continuous data collection | In progress |
| Phase 2 — Hypothesis development and testing | Not started |
| Phase 3 — Pattern characterisation | Not started |

## License

MIT — see [LICENSE](LICENSE).
