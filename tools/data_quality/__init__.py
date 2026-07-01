"""BankNifty Observatory - Data Quality Toolkit.

Read-only forensic validation and reporting over the collected observatory
corpus (JSONL observation records + per-run provenance manifests).

Nothing in this package writes to, mutates, or migrates archived data. Tools
read ``phase{N}/raw/{YYYYMMDD}.jsonl`` and ``phase{N}/manifests/{run_id}.json``
and emit terminal reports plus optional CSV. This is consistent with the
Phase-1 freeze invariant that the corpus is never rewritten.

Tools
-----
* validate_day        - continuity, missing/duplicate snapshots, manifest &
                        JSONL integrity checks (exit 1 on errors).
* summary             - daily summary: counts, coverage, latency, success rates.
* coverage            - expected vs captured observations, missing intervals.
* latency_report      - API latency distribution (min/max/mean/p95/p99).
* option_chain_report - per-expiry coverage, CE/PE counts, OI totals, unfetched.
"""
