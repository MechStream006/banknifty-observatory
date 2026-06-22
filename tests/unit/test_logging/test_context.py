"""Tests for run_id / instance_id context propagation."""
from __future__ import annotations

from lib.logging._context import (
    _init_context,
    _reset_context,
    get_context_snapshot,
    get_instance_id,
    get_run_id,
)


class TestContextLifecycle:
    def test_values_empty_before_init(self) -> None:
        # autouse fixture already called _reset_context() before this test.
        assert get_run_id() == ""
        assert get_instance_id() == ""

    def test_run_id_returned_after_init(self) -> None:
        _init_context(run_id="run-abc-123", instance_id="host-01")
        assert get_run_id() == "run-abc-123"

    def test_instance_id_returned_after_init(self) -> None:
        _init_context(run_id="run-abc-123", instance_id="host-01")
        assert get_instance_id() == "host-01"

    def test_reset_clears_run_id(self) -> None:
        _init_context(run_id="run-abc-123", instance_id="host-01")
        _reset_context()
        assert get_run_id() == ""

    def test_reset_clears_instance_id(self) -> None:
        _init_context(run_id="run-abc-123", instance_id="host-01")
        _reset_context()
        assert get_instance_id() == ""

    def test_reinit_overwrites_previous_values(self) -> None:
        _init_context(run_id="run-first", instance_id="host-a")
        _init_context(run_id="run-second", instance_id="host-b")
        assert get_run_id() == "run-second"
        assert get_instance_id() == "host-b"


class TestContextSnapshot:
    def test_snapshot_is_dict(self) -> None:
        _init_context(run_id="r", instance_id="h")
        assert isinstance(get_context_snapshot(), dict)

    def test_snapshot_contains_run_id(self) -> None:
        _init_context(run_id="run-xyz", instance_id="host-02")
        assert get_context_snapshot()["run_id"] == "run-xyz"

    def test_snapshot_contains_instance_id(self) -> None:
        _init_context(run_id="run-xyz", instance_id="host-02")
        assert get_context_snapshot()["instance_id"] == "host-02"

    def test_snapshot_is_independent_copy(self) -> None:
        _init_context(run_id="run-a", instance_id="host-a")
        snap = get_context_snapshot()
        _init_context(run_id="run-b", instance_id="host-b")
        # Snapshot taken before reinit must not reflect new values.
        assert snap["run_id"] == "run-a"
        assert snap["instance_id"] == "host-a"
