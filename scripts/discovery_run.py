#!/usr/bin/env python
"""
scripts/discovery_run.py — BankNifty Observatory Discovery Phase Runner

Assembles all discovery components and runs one phase. Exits 0 on natural
market-close completion, exits 1 on phase abort or configuration error.

Usage:
    python scripts/discovery_run.py --phase 1
    python scripts/discovery_run.py --phase 1 --interval 5
    python scripts/discovery_run.py --phase 1 --max-duration 21600

    # Override expiry for a single-expiry test run (bypasses BNO_CHAIN_EXPIRIES):
    python scripts/discovery_run.py --phase 1 --expiry 26JUN2026

Arguments:
    --phase           Phase number (1 = primary 5-second polling)
    --expiry          Override expiry for ad-hoc single-expiry runs (DDMMMYYYY).
                      Default: BNO_CHAIN_EXPIRIES from config (supports multi-expiry).
    --interval        Poll interval in seconds (default: chain_poll_interval_s from config)
    --max-duration    Maximum phase duration in seconds; no cap if omitted
    --data-dir        Override data root directory (default: settings.data_dir)

Exit codes:
    0   Phase completed naturally (market closed or max-duration reached)
    1   Phase aborted (auth failure, disk-full, etc.) or config error

Prerequisites:
    pip install smartapi-python pyotp
    .env file with all required BNO_ variables (see deployment/env.example)
    PYTHONPATH=. (project root must be on the path)

Security:
    All credentials are read through lib.config — never via os.environ directly.
    Secrets never appear in logs, error messages, or stdout.
"""
from __future__ import annotations

import argparse
import signal
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lib.config import BNOConfigError, load_settings
from lib.discovery._errors import ArchiverError, PhaseAbortedError
from lib.discovery._models import (
    COLLECTION_CONTRACT_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    PhaseConfig,
)
from lib.discovery.archiver import JSONLArchiver
from lib.discovery.controller import DiscoveryController
from lib.discovery.fetchers.chain import ChainFetcher
from lib.discovery.fetchers.spot import SpotFetcher
from lib.discovery.fetchers.vix import VIXFetcher
from lib.discovery.instrument_registry import InstrumentRegistry
from lib.discovery.manifest import RunManifest, resolve_git_commit, write_manifest
from lib.discovery.scheduler import PollScheduler
from lib.discovery.session import SmartAPISession
from lib.logging import bootstrap_logging, get_logger


# ── Signal handling ──────────────────────────────────────────────────────────────


def _install_sigterm_handler() -> None:
    """Map SIGTERM → KeyboardInterrupt for graceful systemd shutdown."""
    def _handle(sig: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handle)


# ── CLI ──────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="discovery_run",
        description="BankNifty Observatory — Discovery Phase Runner",
    )
    parser.add_argument(
        "--phase",
        type=int,
        required=True,
        metavar="N",
        help="Phase number (1 = 5-second polling, 2 = 1-minute polling, etc.)",
    )
    parser.add_argument(
        "--expiry",
        required=False,
        default=None,
        metavar="DDMMMYYYY",
        help=(
            "Override active expiry for single-expiry ad-hoc runs (e.g. 26JUN2026). "
            "Default: BNO_CHAIN_EXPIRIES from config (supports multi-expiry)."
        ),
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Override poll interval (default: BNO_CHAIN_POLL_INTERVAL_S from config)",
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        default=None,
        dest="max_duration",
        metavar="SECONDS",
        help="Hard cap on phase duration; market-close is still honoured if it arrives first",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        dest="data_dir",
        metavar="PATH",
        help="Override data root directory (default: BNO_DATA_DIR from config)",
    )
    return parser.parse_args()


# ── Directory layout ─────────────────────────────────────────────────────────────


def _resolve_paths(
    data_dir_override: str | None,
    settings_data_dir: str,
    phase: int,
) -> tuple[Path, Path, Path]:
    """Return (phase_dir, raw_dir, db_path) for this phase.

    Layout::
        {data_dir}/phase{phase}/raw/        ← JSONL files (one per calendar day)
        {data_dir}/phase{phase}/discovery.db ← SQLite analysis store (future)
        {data_dir}/phase{phase}/logs/        ← log files (created by bootstrap_logging)
    """
    root = Path(data_dir_override) if data_dir_override else Path(settings_data_dir)
    phase_dir = root / f"phase{phase}"
    raw_dir   = phase_dir / "raw"
    db_path   = phase_dir / "discovery.db"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return phase_dir, raw_dir, db_path


# ── Entry point ──────────────────────────────────────────────────────────────────


def main() -> int:  # noqa: C901
    _install_sigterm_handler()
    args = _parse_args()

    # ── Step 1: Load config ─────────────────────────────────────────────────────
    try:
        settings = load_settings(env_file=".env")
    except BNOConfigError as exc:
        print(f"[FATAL] Config error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"[FATAL] Unexpected config error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    # ── Step 2: Resolve paths ───────────────────────────────────────────────────
    try:
        phase_dir, raw_dir, db_path = _resolve_paths(
            args.data_dir, settings.data_dir, args.phase
        )
    except OSError as exc:
        print(f"[FATAL] Cannot create data directories: {exc}", file=sys.stderr)
        return 1

    # ── Step 3: Bootstrap logging ───────────────────────────────────────────────
    run_id: str
    try:
        run_id = bootstrap_logging(
            settings=settings,
            log_dir=str(phase_dir / "logs"),
        )
    except Exception as exc:
        print(
            f"[WARNING] Logging init failed ({type(exc).__name__}: {exc}); continuing",
            file=sys.stderr,
        )
        run_id = "unavailable"

    log = get_logger("discovery_run")
    log.info(
        "discovery_run_start",
        extra={
            "run_id": run_id,
            "phase": args.phase,
            "phase_dir": str(phase_dir),
        },
    )

    # ── Step 4: Resolve expiry list ─────────────────────────────────────────────
    # --expiry overrides BNO_CHAIN_EXPIRIES for single-expiry ad-hoc runs.
    # Normal scheduled operation uses BNO_CHAIN_EXPIRIES from config.
    if args.expiry is not None:
        expiries = [args.expiry.upper()]
        log.info(
            "expiry_override",
            extra={"expiries": expiries, "source": "--expiry flag"},
        )
    else:
        expiries = settings.chain_expiries
        log.info(
            "expiry_from_config",
            extra={"expiries": expiries, "source": "BNO_CHAIN_EXPIRIES"},
        )

    # ── Step 5: Build PhaseConfig ───────────────────────────────────────────────
    interval_seconds = args.interval if args.interval is not None else settings.chain_poll_interval_s

    config = PhaseConfig(
        phase=args.phase,
        interval_seconds=interval_seconds,
        max_duration_seconds=args.max_duration,
        data_dir=phase_dir,
        db_path=db_path,
    )

    log.info(
        "phase_config",
        extra={
            "phase": config.phase,
            "interval_seconds": config.interval_seconds,
            "max_duration_seconds": config.max_duration_seconds,
            "expiries": expiries,
            "chain_step_size": settings.chain_step_size,
            "chain_window_steps": settings.chain_window_steps,
        },
    )

    # ── Run identity + manifest scaffolding ─────────────────────────────────────
    # run_uid is generated here — not inside the controller — so the pre-run
    # "running" manifest and every record share one session_id. A run killed
    # before it returns therefore leaves a manifest that is still joinable to
    # the records it produced, instead of an orphan file.
    run_uid      = str(uuid.uuid4())
    started_at   = datetime.now(tz=timezone.utc)
    manifest_dir = phase_dir / "manifests"
    git_commit   = resolve_git_commit()

    def _build_manifest(
        status: str,
        *,
        ended_at: datetime | None = None,
        result: object = None,
    ) -> RunManifest:
        return RunManifest(
            run_id=run_uid,
            git_commit=git_commit,
            observation_schema_version=OBSERVATION_SCHEMA_VERSION,
            config_schema_version=settings.config_schema_version,
            collection_contract_version=COLLECTION_CONTRACT_VERSION,
            started_at=started_at,
            host=socket.gethostname(),
            expiries=list(expiries),
            interval_seconds=config.interval_seconds,
            window_steps=settings.chain_window_steps,
            step_size=settings.chain_step_size,
            status=status,
            ended_at=ended_at,
            total_ticks=getattr(result, "total_ticks", None),
            successful_polls=getattr(result, "successful_polls", None),
            failed_polls=getattr(result, "failed_polls", None),
        )

    def _write_manifest_safe(
        status: str,
        *,
        ended_at: datetime | None = None,
        result: object = None,
    ) -> None:
        # Best-effort: the observation data is authoritative, so a manifest
        # write failure is logged but never changes the exit code.
        try:
            path = write_manifest(
                _build_manifest(status, ended_at=ended_at, result=result),
                manifest_dir,
            )
            log.info(
                "run_manifest_written",
                extra={"run_id": run_uid, "status": status, "manifest_path": str(path)},
            )
        except ArchiverError as exc:
            log.error(
                "run_manifest_failed",
                extra={"run_id": run_uid, "status": status, "exc_type": type(exc).__name__},
            )

    # ── Step 6: Assemble components ─────────────────────────────────────────────
    session      = SmartAPISession(settings)
    # One InstrumentRegistry per run, shared by every expiry's ChainFetcher via
    # the controller's startup wiring (registry.build() once, then injected into
    # each chain_fetchers entry) — replaces the old per-tick, per-expiry
    # searchScrip() calls with a single searchScrip() call for the whole run.
    registry     = InstrumentRegistry(underlying="BANKNIFTY")
    chain_fetchers = [
        ChainFetcher(
            expiry=exp,
            window_steps=settings.chain_window_steps,
            step_size=settings.chain_step_size,
        )
        for exp in expiries
    ]
    spot_fetcher = SpotFetcher(source_mode="separate_call")
    vix_fetcher  = VIXFetcher()
    scheduler    = PollScheduler(interval_seconds=interval_seconds)
    archiver     = JSONLArchiver(output_dir=raw_dir)

    controller = DiscoveryController(
        config=config,
        session=session,
        chain_fetchers=chain_fetchers,
        spot_fetcher=spot_fetcher,
        vix_fetcher=vix_fetcher,
        expiries=expiries,
        chain_step_size=settings.chain_step_size,
        chain_window_steps=settings.chain_window_steps,
        scheduler=scheduler,
        archiver=archiver,
        store=None,  # SQLiteAnalysisStore not yet implemented
        run_id=run_uid,
        registry=registry,
    )

    # ── Step 6b: Write the "running" manifest before the poll loop ──────────────
    _write_manifest_safe("running")

    # ── Step 7: Run ─────────────────────────────────────────────────────────────
    try:
        result = controller.run()
    except Exception as exc:
        log.critical(
            "discovery_run_unhandled_error",
            extra={"exc_type": type(exc).__name__, "phase": args.phase},
        )
        print(
            f"[FATAL] Unhandled error in phase {args.phase}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    # ── Step 7b: Finalize the manifest (completed / aborted) ────────────────────
    # Overwrites the "running" manifest with the terminal outcome. A hard kill
    # before this point leaves the "running" manifest in place as the record
    # that this run started but did not finish cleanly.
    _write_manifest_safe(
        "aborted" if result.ended_early else "completed",
        ended_at=result.ended_at,
        result=result,
    )

    # ── Step 8: Report result ───────────────────────────────────────────────────
    log.info(
        "discovery_run_end",
        extra={
            "phase": result.phase,
            "session_id": result.session_id,
            "total_ticks": result.total_ticks,
            "successful_polls": result.successful_polls,
            "failed_polls": result.failed_polls,
            "ended_early": result.ended_early,
            "jsonl_path": str(result.jsonl_path),
        },
    )

    if result.ended_early:
        print(
            f"[ABORT] Phase {result.phase} ended early. "
            f"Ticks completed: {result.total_ticks}. "
            f"Check logs in {phase_dir / 'logs'}",
            file=sys.stderr,
        )
        raise PhaseAbortedError(
            phase=result.phase,
            reason=f"ended_early after {result.total_ticks} tick(s)",
        )

    print(
        f"[DONE] Phase {result.phase} completed. "
        f"Ticks: {result.total_ticks}, "
        f"OK: {result.successful_polls}, "
        f"Failed: {result.failed_polls}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PhaseAbortedError:
        sys.exit(1)
