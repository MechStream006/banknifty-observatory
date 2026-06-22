from __future__ import annotations

_run_id: str = ""
_instance_id: str = ""


def get_run_id() -> str:
    return _run_id


def get_instance_id() -> str:
    return _instance_id


def get_context_snapshot() -> dict[str, str]:
    """Return current run_id and instance_id for embedding in lineage records."""
    return {"run_id": _run_id, "instance_id": _instance_id}


def _init_context(*, run_id: str, instance_id: str) -> None:
    global _run_id, _instance_id
    _run_id = run_id
    _instance_id = instance_id


def _reset_context() -> None:
    global _run_id, _instance_id
    _run_id = ""
    _instance_id = ""
