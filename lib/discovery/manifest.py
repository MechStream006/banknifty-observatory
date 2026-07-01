"""Per-run provenance manifest for the BankNifty Observatory.

Each discovery run emits exactly one manifest, written independently of the
JSONL observation archive. The manifest answers "what code, what configuration,
and what observation contract produced this run's records?" — provenance that
cannot be reconstructed after the fact.

Design notes
------------
* The manifest is a sidecar JSON file under ``{phase_dir}/manifests/{run_id}.json``.
  It never lives inside the raw JSONL directory, so archive tooling that scans
  ``raw/`` for ``*.jsonl`` never sees it.
* run_id equals the controller's session_id, which is also stamped on every
  ObservationRecord, so a manifest joins to its records by that key.
* git commit resolution is best-effort: a detached/absent git environment
  yields None rather than failing the run.
* The manifest is written with flush + fsync for the same durability guarantee
  as the observation archive.

This module introduces no new runtime behaviour beyond writing the manifest;
it is pure provenance.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from lib.discovery._errors import ArchiverError


@dataclass(frozen=True)
class RunManifest:
    """Immutable provenance record for one discovery run.

    schema_version / config_schema_version / collection_contract_version
    capture the three independent versioning axes:
      * observation_schema_version — record layout (OBSERVATION_SCHEMA_VERSION)
      * config_schema_version      — configuration contract (BNO_CONFIG_SCHEMA_VERSION)
      * collection_contract_version — what the collector observed (COLLECTION_CONTRACT_VERSION)

    Two-phase lifecycle
    -------------------
    The manifest is written twice to the same ``{run_id}.json`` file:
      1. Before the poll loop — status="running", ended_at/outcome fields unset.
      2. After the run ends    — status="completed" (clean stop) or "aborted"
         (early stop), with ended_at and the tick outcome filled in.
    A hard kill (SIGKILL/OOM/instance-stop) between the two writes leaves the
    manifest at status="running" with no ended_at — an explicit, joinable
    record that this run started, produced records, and did not finish cleanly,
    rather than an orphan file with no provenance at all. run_id equals the
    session_id stamped on every record, so the manifest joins to its records
    even when only phase 1 was written.
    """

    run_id: str
    git_commit: str | None
    observation_schema_version: int
    config_schema_version: int
    collection_contract_version: int
    started_at: datetime
    host: str
    expiries: list[str]
    interval_seconds: int
    window_steps: int
    step_size: int
    status: str = "running"  # "running" | "completed" | "aborted"
    ended_at: datetime | None = None
    total_ticks: int | None = None
    successful_polls: int | None = None
    failed_polls: int | None = None


def resolve_git_commit() -> str | None:
    """Return the current git commit SHA, or None if unavailable.

    Best-effort: any failure (git not installed, not a repository, timeout)
    resolves to None. Never raises.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def write_manifest(manifest: RunManifest, manifest_dir: Path | str) -> Path:
    """Write *manifest* as JSON to ``{manifest_dir}/{run_id}.json``, durably.

    Called twice per run (two-phase): the "running" phase before the poll loop
    and the terminal "completed"/"aborted" phase after it, overwriting the same
    file. Independent of the JSONL archive.

    Returns
    -------
    Path
        The absolute path of the written manifest file.

    Raises
    ------
    ArchiverError
        If the manifest directory cannot be created or the file cannot be
        written and fsynced. Callers may choose to log-and-continue: the
        observation data is already persisted by the time the manifest is
        written, so a manifest failure does not invalidate the run's records.
    """
    directory = Path(manifest_dir)
    file_path = directory / f"{manifest.run_id}.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(manifest), default=_json_default, indent=2)
        with open(file_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        raise ArchiverError(f"Manifest write failed: {exc}") from exc
    return file_path
