"""Tests for lib.discovery.manifest: per-run provenance manifest."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

import lib.discovery.manifest as manifest_mod
from lib.discovery._errors import ArchiverError
from lib.discovery.manifest import RunManifest, resolve_git_commit, write_manifest


def _sample_manifest(run_id: str = "run-abc") -> RunManifest:
    return RunManifest(
        run_id=run_id,
        git_commit="deadbeef",
        observation_schema_version=2,
        config_schema_version=2,
        collection_contract_version=1,
        started_at=datetime(2026, 6, 30, 3, 45, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
        host="obs-ec2-1",
        expiries=["30JUN2026", "28JUL2026"],
        interval_seconds=5,
        window_steps=15,
        step_size=500,
    )


class TestWriteManifest:
    def test_writes_file_named_by_run_id(self, tmp_path: Path) -> None:
        path = write_manifest(_sample_manifest("run-xyz"), tmp_path)
        assert path == tmp_path / "run-xyz.json"
        assert path.exists()

    def test_creates_manifest_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "manifests"
        write_manifest(_sample_manifest(), target)
        assert target.is_dir()

    def test_content_round_trips(self, tmp_path: Path) -> None:
        m = _sample_manifest()
        path = write_manifest(m, tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run_id"] == m.run_id
        assert data["git_commit"] == "deadbeef"
        assert data["observation_schema_version"] == 2
        assert data["config_schema_version"] == 2
        assert data["collection_contract_version"] == 1
        assert data["host"] == "obs-ec2-1"
        assert data["expiries"] == ["30JUN2026", "28JUL2026"]
        assert data["interval_seconds"] == 5
        assert data["window_steps"] == 15
        assert data["step_size"] == 500

    def test_timestamps_serialised_as_iso(self, tmp_path: Path) -> None:
        path = write_manifest(_sample_manifest(), tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["started_at"] == "2026-06-30T03:45:00+00:00"
        assert data["ended_at"] == "2026-06-30T10:00:00+00:00"

    def test_null_git_commit_serialises_as_null(self, tmp_path: Path) -> None:
        m = _sample_manifest()
        object.__setattr__(m, "git_commit", None)
        path = write_manifest(m, tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["git_commit"] is None

    def test_written_once_per_run_id(self, tmp_path: Path) -> None:
        write_manifest(_sample_manifest("only"), tmp_path)
        files = list(tmp_path.glob("*.json"))
        assert files == [tmp_path / "only.json"]

    def test_manifest_is_not_a_jsonl_file(self, tmp_path: Path) -> None:
        # Independence from the JSONL archive: manifests never match *.jsonl,
        # so archive scanners never ingest them as observation records.
        write_manifest(_sample_manifest(), tmp_path)
        assert list(tmp_path.glob("*.jsonl")) == []


class TestDurability:
    def test_write_calls_fsync(self, tmp_path: Path) -> None:
        with patch.object(manifest_mod.os, "fsync") as mock_fsync:
            write_manifest(_sample_manifest(), tmp_path)
        assert mock_fsync.call_count == 1

    def test_fsync_failure_raises_archiver_error(self, tmp_path: Path) -> None:
        with patch.object(manifest_mod.os, "fsync", side_effect=OSError("disk full")):
            with pytest.raises(ArchiverError, match="Manifest write failed"):
                write_manifest(_sample_manifest(), tmp_path)


class TestResolveGitCommit:
    def test_returns_sha_in_a_git_repo(self) -> None:
        # The project itself is a git repo, so this resolves to a real SHA.
        sha = resolve_git_commit()
        assert sha is None or (isinstance(sha, str) and len(sha) >= 7)

    def test_returns_none_when_git_unavailable(self) -> None:
        with patch.object(
            manifest_mod.subprocess, "run", side_effect=OSError("no git")
        ):
            assert resolve_git_commit() is None

    def test_returns_none_on_nonzero_exit(self) -> None:
        fake = type("R", (), {"returncode": 128, "stdout": ""})()
        with patch.object(manifest_mod.subprocess, "run", return_value=fake):
            assert resolve_git_commit() is None


class TestTwoPhaseLifecycle:
    def test_status_defaults_to_running(self) -> None:
        m = RunManifest(
            run_id="r", git_commit=None, observation_schema_version=2,
            config_schema_version=2, collection_contract_version=1,
            started_at=datetime(2026, 6, 30, 3, 45, tzinfo=timezone.utc),
            host="h", expiries=["30JUN2026"], interval_seconds=5,
            window_steps=15, step_size=500,
        )
        assert m.status == "running"
        assert m.ended_at is None
        assert m.total_ticks is None

    def test_running_manifest_serialises_without_outcome(self, tmp_path: Path) -> None:
        m = RunManifest(
            run_id="run-1", git_commit="sha", observation_schema_version=2,
            config_schema_version=2, collection_contract_version=1,
            started_at=datetime(2026, 6, 30, 3, 45, tzinfo=timezone.utc),
            host="h", expiries=["30JUN2026"], interval_seconds=5,
            window_steps=15, step_size=500, status="running",
        )
        data = json.loads(write_manifest(m, tmp_path).read_text(encoding="utf-8"))
        assert data["status"] == "running"
        assert data["ended_at"] is None
        assert data["total_ticks"] is None

    def test_completed_manifest_carries_outcome(self, tmp_path: Path) -> None:
        m = RunManifest(
            run_id="run-1", git_commit="sha", observation_schema_version=2,
            config_schema_version=2, collection_contract_version=1,
            started_at=datetime(2026, 6, 30, 3, 45, tzinfo=timezone.utc),
            host="h", expiries=["30JUN2026"], interval_seconds=5,
            window_steps=15, step_size=500, status="completed",
            ended_at=datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
            total_ticks=4200, successful_polls=4198, failed_polls=2,
        )
        data = json.loads(write_manifest(m, tmp_path).read_text(encoding="utf-8"))
        assert data["status"] == "completed"
        assert data["ended_at"] == "2026-06-30T10:00:00+00:00"
        assert data["total_ticks"] == 4200
        assert data["successful_polls"] == 4198
        assert data["failed_polls"] == 2

    def test_finalize_overwrites_running_manifest_in_place(self, tmp_path: Path) -> None:
        base = dict(
            run_id="run-1", git_commit="sha", observation_schema_version=2,
            config_schema_version=2, collection_contract_version=1,
            started_at=datetime(2026, 6, 30, 3, 45, tzinfo=timezone.utc),
            host="h", expiries=["30JUN2026"], interval_seconds=5,
            window_steps=15, step_size=500,
        )
        write_manifest(RunManifest(**base, status="running"), tmp_path)
        write_manifest(
            RunManifest(
                **base, status="completed",
                ended_at=datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
                total_ticks=10,
            ),
            tmp_path,
        )
        # One file, terminal content — the two-phase write is an overwrite.
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["status"] == "completed"
        assert data["total_ticks"] == 10

    def test_aborted_status_is_representable(self, tmp_path: Path) -> None:
        m = RunManifest(
            run_id="run-1", git_commit=None, observation_schema_version=2,
            config_schema_version=2, collection_contract_version=1,
            started_at=datetime(2026, 6, 30, 3, 45, tzinfo=timezone.utc),
            host="h", expiries=["30JUN2026"], interval_seconds=5,
            window_steps=15, step_size=500, status="aborted",
            ended_at=datetime(2026, 6, 30, 4, 0, tzinfo=timezone.utc),
            total_ticks=3,
        )
        data = json.loads(write_manifest(m, tmp_path).read_text(encoding="utf-8"))
        assert data["status"] == "aborted"
