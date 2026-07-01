"""Tests for tools.data_quality.latency_report."""
from __future__ import annotations

from tools.data_quality import latency_report as L

from tests.unit.test_tools.conftest import make_chain, make_record


class TestBuildLatencyReport:
    def test_per_source_distribution(self) -> None:
        recs = [
            make_record(poll_id="a", spot_latency=10.0, vix_latency=5.0,
                        chains=[make_chain(latency=100.0)]),
            make_record(poll_id="b", spot_latency=20.0, vix_latency=15.0,
                        chains=[make_chain(latency=200.0)], status="CONTIGUOUS",
                        prev_id="a", actual=5),
        ]
        out = L.build_latency_report(recs)
        assert out["spot"]["count"] == 2
        assert out["spot"]["min"] == 10.0
        assert out["spot"]["max"] == 20.0
        assert out["spot"]["mean"] == 15.0
        assert out["vix"]["mean"] == 10.0
        assert out["chain"]["mean"] == 150.0

    def test_chain_latency_aggregates_across_expiries(self) -> None:
        rec = make_record(chains=[
            make_chain("30JUN2026", latency=100.0),
            make_chain("28JUL2026", latency=300.0),
        ])
        out = L.build_latency_report([rec])
        assert out["chain"]["count"] == 2
        assert out["chain"]["mean"] == 200.0

    def test_percentiles_present(self) -> None:
        recs = [
            make_record(poll_id=str(i), spot_latency=float(i),
                        status="FIRST" if i == 0 else "CONTIGUOUS",
                        prev_id=None if i == 0 else str(i - 1),
                        actual=None if i == 0 else 5)
            for i in range(100)
        ]
        out = L.build_latency_report(recs)
        assert out["spot"]["p95"] is not None
        assert out["spot"]["p99"] is not None
        assert out["spot"]["p95"] <= out["spot"]["p99"]

    def test_empty(self) -> None:
        out = L.build_latency_report([])
        assert out["spot"]["count"] == 0

    def test_csv_output(self, tmp_path) -> None:
        import json
        rec = make_record()
        p = tmp_path / "d.jsonl"
        p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        out_csv = tmp_path / "lat.csv"
        assert L.run(["--jsonl", str(p), "--csv", str(out_csv)]) == 0
        text = out_csv.read_text(encoding="utf-8")
        assert "source" in text and "p95" in text
