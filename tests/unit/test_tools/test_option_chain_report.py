"""Tests for tools.data_quality.option_chain_report."""
from __future__ import annotations

from tools.data_quality import option_chain_report as O

from tests.unit.test_tools.conftest import make_chain, make_quote, make_record


def _by_expiry(report):
    return {e["expiry"]: e for e in report["expiries"]}


class TestBuildOptionChainReport:
    def test_per_expiry_snapshot_counts(self) -> None:
        rec = make_record(chains=[
            make_chain("30JUN2026"),
            make_chain("28JUL2026"),
        ])
        report = O.build_option_chain_report([rec])
        by = _by_expiry(report)
        assert set(by) == {"30JUN2026", "28JUL2026"}
        assert by["30JUN2026"]["snapshots"] == 1

    def test_success_rate(self) -> None:
        recs = [
            make_record(poll_id="a", chains=[make_chain("30JUN2026", success=True)]),
            make_record(poll_id="b", chains=[make_chain("30JUN2026", success=False)],
                        status="CONTIGUOUS", prev_id="a", actual=5),
        ]
        report = O.build_option_chain_report(recs)
        e = _by_expiry(report)["30JUN2026"]
        assert e["snapshots"] == 2
        assert e["success"] == 1
        assert e["success_rate"] == 0.5

    def test_ce_pe_counts(self) -> None:
        quotes = [
            make_quote(58000, "CE"), make_quote(58500, "CE"),
            make_quote(58000, "PE"),
        ]
        rec = make_record(chains=[make_chain("30JUN2026", quotes=quotes)])
        e = _by_expiry(O.build_option_chain_report([rec]))["30JUN2026"]
        assert e["avg_ce_count"] == 2
        assert e["avg_pe_count"] == 1

    def test_oi_totals_from_derived(self) -> None:
        quotes = [make_quote(58000, "CE", oi=1000), make_quote(58000, "PE", oi=800)]
        rec = make_record(chains=[make_chain("30JUN2026", quotes=quotes)])
        e = _by_expiry(O.build_option_chain_report([rec]))["30JUN2026"]
        assert e["avg_ce_oi"] == 1000
        assert e["avg_pe_oi"] == 800

    def test_unfetched_statistics(self) -> None:
        recs = [
            make_record(poll_id="a", chains=[make_chain("30JUN2026", unfetched=2)]),
            make_record(poll_id="b", chains=[make_chain("30JUN2026", unfetched=4)],
                        status="CONTIGUOUS", prev_id="a", actual=5),
        ]
        e = _by_expiry(O.build_option_chain_report(recs))["30JUN2026"]
        assert e["total_unfetched"] == 6
        assert e["avg_unfetched"] == 3.0

    def test_failed_chain_counts_snapshot_not_success(self) -> None:
        rec = make_record(chains=[make_chain("30JUN2026", success=False, unfetched=5)])
        e = _by_expiry(O.build_option_chain_report([rec]))["30JUN2026"]
        assert e["snapshots"] == 1
        assert e["success"] == 0
        assert e["avg_ce_count"] is None  # no successful snapshot
        assert e["total_unfetched"] == 5  # unfetched still recorded

    def test_empty(self) -> None:
        assert O.build_option_chain_report([])["expiries"] == []

    def test_csv_output(self, tmp_path) -> None:
        import json
        rec = make_record()
        p = tmp_path / "d.jsonl"
        p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        out_csv = tmp_path / "chain.csv"
        assert O.run(["--jsonl", str(p), "--csv", str(out_csv)]) == 0
        assert "expiry" in out_csv.read_text(encoding="utf-8")
