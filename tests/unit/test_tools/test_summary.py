"""Tests for tools.data_quality.summary."""
from __future__ import annotations

from tools.data_quality import summary as S

from tests.unit.test_tools.conftest import make_chain, make_record, make_session


class TestBuildSummary:
    def test_snapshot_count(self) -> None:
        recs = make_session("s1", [5, 5, 5], interval=5)
        assert S.build_summary(recs)["snapshot_count"] == 4

    def test_time_coverage(self) -> None:
        recs = make_session("s1", [5, 5, 5], interval=5)  # 15s span
        out = S.build_summary(recs)
        assert out["coverage_seconds"] == 15.0
        assert out["first_polled_at"] is not None
        assert out["last_polled_at"] is not None

    def test_success_rates_all_ok(self) -> None:
        recs = make_session("s1", [5, 5], interval=5)
        out = S.build_summary(recs)
        assert out["poll_success_rate"] == 1.0
        assert out["spot_success_rate"] == 1.0
        assert out["chain_fetch_success_rate"] == 1.0

    def test_spot_failure_lowers_rate(self) -> None:
        recs = [
            make_record(session_id="s1", poll_id="a", spot_ok=True),
            make_record(session_id="s1", poll_id="b", spot_ok=False,
                        status="CONTIGUOUS", prev_id="a", actual=5),
        ]
        out = S.build_summary(recs)
        assert out["spot_success_rate"] == 0.5

    def test_chain_success_rate_partial(self) -> None:
        rec = make_record(chains=[make_chain(success=True), make_chain(success=False)])
        out = S.build_summary([rec])
        assert out["chain_fetches"] == 2
        assert out["chain_fetch_success_rate"] == 0.5
        # poll still counts as successful (at least one chain ok)
        assert out["poll_success_rate"] == 1.0

    def test_latency_stats_present(self) -> None:
        recs = make_session("s1", [5, 5], interval=5)
        out = S.build_summary(recs)
        assert out["spot_latency_ms"]["count"] == 3
        assert out["chain_latency_ms"]["mean"] == 120.0

    def test_empty_records(self) -> None:
        out = S.build_summary([])
        assert out["snapshot_count"] == 0
        assert out["poll_success_rate"] is None

    def test_csv_output(self, tmp_path) -> None:
        recs = make_session("s1", [5], interval=5)
        import json
        p = tmp_path / "d.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
        out_csv = tmp_path / "summary.csv"
        assert S.run(["--jsonl", str(p), "--csv", str(out_csv)]) == 0
        assert out_csv.exists()
        assert "snapshot_count" in out_csv.read_text(encoding="utf-8")
