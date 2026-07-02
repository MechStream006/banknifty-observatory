"""
DiscoveryController — single-phase discovery lifecycle coordinator.

Drives one collection phase: startup → poll loop → shutdown.
All data production and persistence is delegated to injected components.

State machine:
    IDLE → STARTING → RUNNING → STOPPING → STOPPED
    STARTING → ABORTED  (ArchiverError, SessionAcquireError, or RegistryBuildError)
    RUNNING  → ABORTED  (SessionRefreshError or ArchiverError)

Recoverable within RUNNING (poll continues):
    ChainResult(success=False), SpotResult(success=False),
    VIXResult(success=False), StoreError

Fatal (transition to ABORTED):
    ArchiverError, SessionRefreshError

Unhandled exceptions propagate from run() after archiver.close().
run() always returns PhaseResult for expected fatal conditions.

Phase-1 collection order per tick:
    1. spot_fetcher.fetch(smart)              — ATM anchor; gates chain fetch
    2. vix_fetcher.fetch(smart)               — independent, always attempted
    3. chain_fetcher.fetch(smart, spot) × N   — one per configured expiry
    4. _build_derived()                        — OI sums, PCRs, OI deltas
    5. _persist(ObservationRecord)
"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from lib.discovery._errors import (
    ArchiverError,
    RegistryBuildError,
    SessionAcquireError,
    SessionRefreshError,
    StoreError,
)
from lib.discovery._models import (
    COLLECTION_CONTRACT_VERSION,
    OBSERVATION_SCHEMA_VERSION,
    ChainResult,
    DerivedObservation,
    ObservationRecord,
    OIChange,
    OptionQuote,
    PhaseConfig,
    PhaseResult,
    SnapshotContinuity,
    SnapshotMeta,
)
from lib.logging._factory import get_logger

if TYPE_CHECKING:
    from lib.discovery.archiver import JSONLArchiver
    from lib.discovery.fetchers.chain import ChainFetcher
    from lib.discovery.fetchers.spot import SpotFetcher
    from lib.discovery.fetchers.vix import VIXFetcher
    from lib.discovery.instrument_registry import InstrumentRegistry
    from lib.discovery.scheduler import PollScheduler
    from lib.discovery.session import SmartAPISession
    from lib.discovery.validation import ValidationEngine, ValidationFinding

# ── State constants ─────────────────────────────────────────────────────────────

_STATE_IDLE     = "idle"
_STATE_STARTING = "starting"
_STATE_RUNNING  = "running"
_STATE_STOPPING = "stopping"
_STATE_STOPPED  = "stopped"
_STATE_ABORTED  = "aborted"

# Symbol parsing constants (BankNifty Phase-1).
# Format: BANKNIFTY (9) + expiry_2y (7) + strike_digits + side (2)
_SYMBOL_PREFIX_LEN = 16   # len("BANKNIFTY") + len("DDMMMYY")
_SIDE_LEN          = 2    # len("CE") or len("PE")
_SYMBOL_MIN_LEN    = _SYMBOL_PREFIX_LEN + 1 + _SIDE_LEN  # at least 1 strike digit

# Snapshot continuity classification.
_CONTINUITY_FIRST      = "FIRST"
_CONTINUITY_CONTIGUOUS = "CONTIGUOUS"
_CONTINUITY_GAP        = "GAP"
# A snapshot is CONTIGUOUS when the actual interval since the previous snapshot
# is within ±50% of the expected poll interval; otherwise it is a GAP. The
# band absorbs normal scheduler drift while still flagging a missed, delayed,
# or duplicated poll.
_CONTINUITY_TOLERANCE  = 0.5


# ── Mockable helper ─────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── DiscoveryController ─────────────────────────────────────────────────────────


class DiscoveryController:
    """Single-phase discovery lifecycle coordinator (Phase-1 contract).

    Parameters
    ----------
    config:
        Frozen phase configuration.
    session:
        Constructed but not yet connected SmartAPISession.
    chain_fetchers:
        One ChainFetcher per configured expiry, in expiry_set order.
    registry:
        Optional InstrumentRegistry. When supplied, build() is called once
        during startup — after session.connect() succeeds — and the same
        instance is then injected into every chain_fetchers entry via its
        registry setter, replacing each fetcher's own searchScrip() Phase 1
        with registry-sourced token maps. RegistryBuildError during startup
        is fatal (STARTING -> ABORTED), matching SessionAcquireError. None
        (the default) preserves today's behaviour exactly: no build call,
        no injection — each ChainFetcher keeps whatever registry it was
        constructed with (None, for all current callers).
    spot_fetcher:
        Constructed SpotFetcher.  Must be called before chain_fetchers each
        tick — the returned spot LTP is the ATM anchor for window selection.
    vix_fetcher:
        Constructed VIXFetcher.  Called independently of spot success.
    expiries:
        Ordered list of expiry strings matching chain_fetchers.  Copied into
        every SnapshotMeta.expiry_set.
    chain_step_size:
        Backbone spacing used to compute resolved_atm in SnapshotMeta.
        Must match the step_size passed to each ChainFetcher.
    chain_window_steps:
        Stored in SnapshotMeta.window_steps; must match ChainFetcher config.
    scheduler:
        Constructed PollScheduler.
    archiver:
        Constructed but not yet opened JSONLArchiver.
    store:
        Optional SQLiteAnalysisStore.  None until store is implemented.
    validator:
        Optional ValidationEngine. When supplied, evaluate(record) is called
        once per tick — before any persistence I/O for that tick — and the
        resulting findings are (a) best-effort persisted to quality_archiver
        if supplied, and (b) logged at WARNING/ERROR per finding level (see
        quality_archiver below). Raw persistence is never gated on the
        outcome: archiver.write() always runs first, unconditionally,
        regardless of validation result. None (the default) preserves
        today's behaviour exactly: no evaluation, no quality stream, no
        extra logging.
    quality_archiver:
        Optional JSONLArchiver, pointed at a separate quality/ directory.
        Written to only when validator is also supplied. Write failures
        (ArchiverError) are logged and never abort the run — unlike the
        raw archiver, whose ArchiverError is fatal.
    """

    def __init__(
        self,
        config: PhaseConfig,
        session: SmartAPISession,
        chain_fetchers: list[ChainFetcher],
        spot_fetcher: SpotFetcher,
        vix_fetcher: VIXFetcher,
        expiries: list[str],
        chain_step_size: int,
        chain_window_steps: int,
        scheduler: PollScheduler,
        archiver: JSONLArchiver,
        store: object = None,
        underlying: str = "BANKNIFTY",
        run_id: str | None = None,
        registry: InstrumentRegistry | None = None,
        validator: ValidationEngine | None = None,
        quality_archiver: JSONLArchiver | None = None,
    ) -> None:
        self._config             = config
        self._session            = session
        self._chain_fetchers     = chain_fetchers
        self._spot_fetcher       = spot_fetcher
        self._vix_fetcher        = vix_fetcher
        self._expiries           = list(expiries)
        self._chain_step_size    = chain_step_size
        self._chain_window_steps = chain_window_steps
        self._scheduler          = scheduler
        self._archiver           = archiver
        self._store              = store
        self._underlying         = underlying
        self._registry           = registry
        self._validator          = validator
        self._quality_archiver   = quality_archiver
        # Externally supplied run identity. When provided (by the CLI), it is
        # used as the session_id stamped on every record, so a pre-run manifest
        # keyed on the same id stays joinable to this run's records even if the
        # process is killed before run() returns. None → generated at startup.
        self._run_id             = run_id
        self._log                = get_logger("discovery.controller")
        self._state: str         = _STATE_IDLE
        # Keyed: expiry → {(side, strike): oi}.  None until first successful tick.
        self._prev_oi: dict[str, dict[tuple[str, int], int]] | None = None
        # Snapshot continuity tracking — identity and timestamp of the previous
        # persisted snapshot. None until the first snapshot of the run.
        self._prev_snapshot_id: str | None       = None
        self._prev_polled_at:   datetime | None   = None

    # ── Public interface ────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        """Current lifecycle state string. Read-only."""
        return self._state

    def run(self) -> PhaseResult:
        """Execute the discovery phase: startup → poll loop → shutdown.

        Returns
        -------
        PhaseResult
            Always returned for expected fatal conditions.
            ``ended_early=True`` when the phase aborted before its
            natural stop condition.
        """
        session_id    = ""
        started_at    = _utc_now()
        tick_number   = 0
        completed_ticks  = 0
        successful_polls = 0
        failed_polls     = 0
        abort_reason: str | None = None

        try:
            self._state = _STATE_STARTING
            session_id  = self._startup()
            self._state = _STATE_RUNNING

            for tick_dt in self._scheduler.ticks():
                if self._config.max_duration_seconds is not None:
                    elapsed = (_utc_now() - started_at).total_seconds()
                    if elapsed >= self._config.max_duration_seconds:
                        break

                tick_number += 1
                self._session.refresh_if_needed()

                record = self._poll_once(tick_dt, tick_number, session_id)
                self._persist(record)
                completed_ticks += 1

                chain_any_ok = any(c.success for c in record.chains)
                if chain_any_ok:
                    successful_polls += 1
                else:
                    failed_polls += 1

                self._log.info(
                    "tick_complete",
                    extra={
                        "tick_number":    tick_number,
                        "session_id":     session_id,
                        "phase":          self._config.phase,
                        "chains_ok":      chain_any_ok,
                        "chains_count":   len(record.chains),
                        "spot_ok":        record.spot.success,
                        "vix_ok":         record.vix.success,
                        "spot_latency_ms": record.spot.latency_ms,
                    },
                )

            self._state = _STATE_STOPPING

        except (SessionAcquireError, ArchiverError, RegistryBuildError) as exc:
            abort_reason = f"{type(exc).__name__}: {exc}"
            self._state  = _STATE_ABORTED
            self._log.error(
                "controller_fatal_error",
                extra={"reason": abort_reason, "phase": self._config.phase},
            )

        except SessionRefreshError as exc:
            abort_reason = f"SessionRefreshError: {exc}"
            self._state  = _STATE_ABORTED
            self._log.error(
                "controller_refresh_abort",
                extra={
                    "reason":      abort_reason,
                    "tick_number": tick_number,
                    "phase":       self._config.phase,
                },
            )

        except KeyboardInterrupt:
            self._state = _STATE_STOPPING
            self._log.info(
                "controller_interrupted",
                extra={"tick_number": tick_number, "phase": self._config.phase},
            )

        except Exception as exc:
            self._log.critical(
                "controller_unhandled_error",
                extra={
                    "exc_type":    type(exc).__name__,
                    "tick_number": tick_number,
                    "phase":       self._config.phase,
                },
            )
            raise

        finally:
            try:
                self._archiver.close()
            except Exception:  # noqa: BLE001
                pass

        ended_early = abort_reason is not None
        self._state = _STATE_ABORTED if ended_early else _STATE_STOPPED
        ended_at    = _utc_now()

        jsonl_path = (
            self._archiver.current_file_path
            or self._config.data_dir / "raw" / "unavailable.jsonl"
        )

        self._log.info(
            "phase_ended",
            extra={
                "session_id":      session_id,
                "phase":           self._config.phase,
                "total_ticks":     completed_ticks,
                "successful_polls": successful_polls,
                "failed_polls":    failed_polls,
                "ended_early":     ended_early,
                "abort_reason":    abort_reason,
            },
        )

        return PhaseResult(
            session_id=session_id,
            phase=self._config.phase,
            started_at=started_at,
            ended_at=ended_at,
            total_ticks=completed_ticks,
            successful_polls=successful_polls,
            failed_polls=failed_polls,
            jsonl_path=jsonl_path,
            db_path=self._config.db_path,
            ended_early=ended_early,
        )

    # ── Private — startup ───────────────────────────────────────────────────────

    def _startup(self) -> str:
        self._archiver.open()
        self._session.connect()

        if self._registry is not None:
            self._registry.build(self._session.smart, self._expiries)
            for fetcher in self._chain_fetchers:
                fetcher.registry = self._registry
            self._log.info(
                "registry_wired",
                extra={
                    "resolved_expiries": len(self._registry.resolved_expiries),
                    "chain_fetchers": len(self._chain_fetchers),
                },
            )

        session_id = self._run_id or str(uuid.uuid4())
        self._log.info(
            "phase_started",
            extra={
                "session_id":      session_id,
                "phase":           self._config.phase,
                "interval_seconds": self._config.interval_seconds,
                "data_dir":        str(self._config.data_dir),
            },
        )
        return session_id

    # ── Private — poll ──────────────────────────────────────────────────────────

    def _poll_once(
        self,
        tick_dt: datetime,
        tick_number: int,
        session_id: str,
    ) -> ObservationRecord:
        """Fetch spot, VIX, and all configured expiry chains for one tick.

        Execution order:
          1. spot  — provides ATM anchor; gates chain fetch on success
          2. vix   — always attempted, independent of spot
          3. chains — skipped (empty list) when spot failed
          4. derived — None when spot failed or all chains failed

        Never raises: all component errors are captured in their result objects.
        """
        smart = self._session.smart
        poll_id = str(uuid.uuid4())

        # ── 0. Continuity ───────────────────────────────────────────────────────
        # Classify this snapshot against the previous one, then advance the
        # previous-snapshot cursor. Computed for every snapshot (including
        # spot-failure snapshots) so the continuity chain is unbroken.
        continuity = self._compute_continuity(tick_dt)
        self._prev_snapshot_id = poll_id
        self._prev_polled_at   = tick_dt
        is_contiguous = continuity.continuity_status == _CONTINUITY_CONTIGUOUS

        # ── 1. Spot ────────────────────────────────────────────────────────────
        spot_result = self._spot_fetcher.fetch(smart)

        # ── 2. VIX (independent of spot) ───────────────────────────────────────
        vix_result = self._vix_fetcher.fetch(smart)

        # ── 3. Spot failure gate ────────────────────────────────────────────────
        if not spot_result.success or spot_result.ltp is None:
            return ObservationRecord(
                poll_id=poll_id,
                session_id=session_id,
                polled_at=tick_dt,
                phase=self._config.phase,
                tick_number=tick_number,
                interval_s=self._config.interval_seconds,
                meta=SnapshotMeta(
                    schema_version=OBSERVATION_SCHEMA_VERSION,
                    anchoring_spot=0.0,
                    resolved_atm=0,
                    expiry_set=list(self._expiries),
                    window_steps=self._chain_window_steps,
                    collection_contract_version=COLLECTION_CONTRACT_VERSION,
                    chain_step_size=self._chain_step_size,
                ),
                spot=spot_result,
                vix=vix_result,
                chains=[],
                derived=None,
                underlying=self._underlying,
                continuity=continuity,
            )

        spot = spot_result.ltp
        resolved_atm = int(round(spot / self._chain_step_size)) * self._chain_step_size

        # ── 4. Multi-expiry chain fetch ─────────────────────────────────────────
        chain_results = [f.fetch(smart, spot) for f in self._chain_fetchers]

        # ── 4b. Parse immutable instrument identity per chain ───────────────────
        # Populate expiry + structured quotes on each ChainResult during
        # collection, so later analysis never re-parses tradingSymbol. The raw
        # payload on each ChainResult is left untouched.
        for expiry, chain_result in zip(self._expiries, chain_results):
            chain_result.expiry = expiry
            chain_result.quotes = self._parse_quotes(expiry, chain_result)

        # ── 5. SnapshotMeta ─────────────────────────────────────────────────────
        meta = SnapshotMeta(
            schema_version=OBSERVATION_SCHEMA_VERSION,
            anchoring_spot=spot,
            resolved_atm=resolved_atm,
            expiry_set=list(self._expiries),
            window_steps=self._chain_window_steps,
            collection_contract_version=COLLECTION_CONTRACT_VERSION,
            chain_step_size=self._chain_step_size,
        )

        # ── 6. DerivedObservation ───────────────────────────────────────────────
        if any(c.success for c in chain_results):
            derived: DerivedObservation | None = self._build_derived(
                chain_results, is_contiguous=is_contiguous
            )
        else:
            derived = None

        return ObservationRecord(
            poll_id=poll_id,
            session_id=session_id,
            polled_at=tick_dt,
            phase=self._config.phase,
            tick_number=tick_number,
            interval_s=self._config.interval_seconds,
            meta=meta,
            spot=spot_result,
            vix=vix_result,
            chains=chain_results,
            derived=derived,
            underlying=self._underlying,
            continuity=continuity,
        )

    # ── Private — continuity ─────────────────────────────────────────────────────

    def _compute_continuity(self, tick_dt: datetime) -> SnapshotContinuity:
        """Classify this snapshot's continuity against the previous snapshot.

        FIRST when there is no predecessor. Otherwise CONTIGUOUS when the actual
        interval is within ±_CONTINUITY_TOLERANCE of the expected poll interval,
        else GAP. Uses the persisted ``polled_at`` timestamps so the classification
        reflects exactly what the archive records.
        """
        expected = self._config.interval_seconds
        prev_id  = self._prev_snapshot_id
        prev_ts  = self._prev_polled_at

        if prev_id is None or prev_ts is None:
            return SnapshotContinuity(
                previous_snapshot_id=None,
                previous_timestamp=None,
                expected_interval_seconds=expected,
                actual_interval_seconds=None,
                continuity_status=_CONTINUITY_FIRST,
            )

        actual = (tick_dt - prev_ts).total_seconds()
        lower  = expected * (1.0 - _CONTINUITY_TOLERANCE)
        upper  = expected * (1.0 + _CONTINUITY_TOLERANCE)
        status = (
            _CONTINUITY_CONTIGUOUS if lower <= actual <= upper else _CONTINUITY_GAP
        )
        return SnapshotContinuity(
            previous_snapshot_id=prev_id,
            previous_timestamp=prev_ts,
            expected_interval_seconds=expected,
            actual_interval_seconds=actual,
            continuity_status=status,
        )

    # ── Private — quote parsing ──────────────────────────────────────────────────

    def _parse_quotes(
        self,
        expiry: str,
        chain_result: ChainResult,
    ) -> list[OptionQuote]:
        """Parse a chain's raw rows into structured OptionQuote instances.

        Returns an empty list for a failed or empty chain. Rows whose symbol
        cannot be parsed are skipped (same tolerance as derived computation).
        The raw payload is read but never mutated.
        """
        if not chain_result.success or chain_result.raw_response is None:
            return []
        data = chain_result.raw_response.get("data")
        if not isinstance(data, dict):
            return []
        fetched = data.get("fetched")
        if not isinstance(fetched, list):
            return []

        quotes: list[OptionQuote] = []
        for row in fetched:
            if not isinstance(row, dict):
                continue
            raw_sym = row.get("tradingSymbol") or row.get("tradingsymbol") or ""
            sym = str(raw_sym).upper()
            if len(sym) < _SYMBOL_MIN_LEN:
                continue
            side = sym[-_SIDE_LEN:]
            if side not in ("CE", "PE"):
                continue
            try:
                strike = int(sym[_SYMBOL_PREFIX_LEN:-_SIDE_LEN])
            except (ValueError, IndexError):
                continue

            oi  = int(row.get("opnInterest") or 0)
            # SmartAPI FULL mode reports traded volume as "tradeVolume"
            # (mirrors the "opnInterest" field above), verified against the live
            # NFO option payload. The earlier "tradVol" primary matched no real
            # row, so volume_pcr was always null; it is retained only as a
            # fallback alongside "volume" for legacy synthetic fixtures.
            vol = int(
                row.get("tradeVolume")
                or row.get("tradVol")
                or row.get("volume")
                or 0
            )
            raw_ltp = row.get("ltp")
            ltp = float(raw_ltp) if isinstance(raw_ltp, (int, float)) else None

            quotes.append(
                OptionQuote(
                    underlying=self._underlying,
                    expiry=expiry,
                    strike=strike,
                    option_side=side,
                    oi=oi,
                    volume=vol,
                    ltp=ltp,
                )
            )
        return quotes

    # ── Private — derived computation ──────────────────────────────────────────

    def _build_derived(
        self,
        chain_results: list[ChainResult],
        is_contiguous: bool,
    ) -> DerivedObservation:
        """Compute per-tick derived values from the parsed chain quotes.

        Computes per-expiry OI and volume totals, PCR ratios, and inter-tick
        OI deltas.  Updates self._prev_oi for successful expiries so the next
        tick can compute OI changes.

        Consumes the OptionQuote list already parsed onto each ChainResult
        (never re-parses the raw payload).

        is_contiguous gates the path-dependent OI-delta computation: deltas are
        produced only when this snapshot is contiguous with the previous one.
        Across a GAP (or on the first snapshot) oi_changes is None, so a delta
        never silently spans a missed interval. _prev_oi is still advanced so a
        subsequent contiguous snapshot resumes correct single-interval deltas.

        Called only when at least one ChainResult.success is True.
        """
        total_ce_oi:  dict[str, int] = {e: 0 for e in self._expiries}
        total_pe_oi:  dict[str, int] = {e: 0 for e in self._expiries}
        total_ce_vol: dict[str, int] = {e: 0 for e in self._expiries}
        total_pe_vol: dict[str, int] = {e: 0 for e in self._expiries}
        current_oi:   dict[str, dict[tuple[str, int], int]] = {
            e: {} for e in self._expiries
        }

        for expiry, chain_result in zip(self._expiries, chain_results):
            if not chain_result.success:
                continue
            for quote in chain_result.quotes:
                current_oi[expiry][(quote.option_side, quote.strike)] = quote.oi
                if quote.option_side == "CE":
                    total_ce_oi[expiry]  += quote.oi
                    total_ce_vol[expiry] += quote.volume
                else:
                    total_pe_oi[expiry]  += quote.oi
                    total_pe_vol[expiry] += quote.volume

        # OI and volume put-call ratios
        oi_pcr:     dict[str, float | None] = {}
        volume_pcr: dict[str, float | None] = {}
        for expiry in self._expiries:
            ce_oi  = total_ce_oi[expiry]
            pe_oi  = total_pe_oi[expiry]
            ce_vol = total_ce_vol[expiry]
            pe_vol = total_pe_vol[expiry]
            oi_pcr[expiry]     = round(pe_oi  / ce_oi,  4) if ce_oi  > 0 else None
            volume_pcr[expiry] = round(pe_vol / ce_vol, 4) if ce_vol > 0 else None

        # OI changes from previous tick — only across a contiguous snapshot pair.
        oi_changes: list[OIChange] | None = None
        if self._prev_oi is not None and is_contiguous:
            oi_changes = []
            for expiry in self._expiries:
                curr = current_oi[expiry]
                prev = self._prev_oi.get(expiry, {})
                for (side, strike), curr_oi in curr.items():
                    delta = curr_oi - prev.get((side, strike), 0)
                    oi_changes.append(
                        OIChange(expiry=expiry, side=side, strike=strike, delta=delta)
                    )

        # Update _prev_oi: carry forward existing entries, overwrite with
        # current data for any expiry whose chain fetch succeeded this tick.
        new_prev: dict[str, dict[tuple[str, int], int]] = {}
        if self._prev_oi is not None:
            new_prev.update(self._prev_oi)
        for expiry, chain_result in zip(self._expiries, chain_results):
            if chain_result.success and current_oi[expiry]:
                new_prev[expiry] = current_oi[expiry]
        self._prev_oi = new_prev if new_prev else None

        return DerivedObservation(
            total_ce_oi=total_ce_oi,
            total_pe_oi=total_pe_oi,
            oi_pcr=oi_pcr,
            volume_pcr=volume_pcr,
            oi_changes=oi_changes,
        )

    # ── Private — persistence ───────────────────────────────────────────────────

    def _persist(self, record: ObservationRecord) -> None:
        """Validate (if configured), then write the record to JSONL
        (mandatory) and SQLite store (optional).

        Ordering (frozen — see docs/PHASE1_FREEZE.md and the L3 Validation
        Framework design): validation is evaluated first, before any I/O for
        this tick, but raw persistence is never gated on its outcome —
        archiver.write() always runs next, unconditionally, exactly as
        before validation existed. The quality-stream write happens last and
        is best-effort only.

        Raises
        ------
        ArchiverError
            Propagates from archiver.write() (the raw archive) — fatal,
            aborts the phase. quality_archiver failures never propagate
            from here; see _persist_quality().
        """
        findings = self._evaluate_validation(record)

        record_dict = dataclasses.asdict(record)
        self._archiver.write(record_dict)

        if findings is not None:
            self._persist_quality(record, findings)
            self._log_validation_outcome(record, findings)

        if self._store is not None:
            try:
                self._store.insert(record)
            except StoreError as exc:
                self._log.warning(
                    "store_write_failed",
                    extra={
                        "exc_type": type(exc).__name__,
                        "poll_id":  record.poll_id,
                    },
                )

    def _evaluate_validation(
        self, record: ObservationRecord
    ) -> list[ValidationFinding] | None:
        """Run the validator over *record*, if one is configured.

        Returns None when no validator is configured (preserving today's
        behaviour exactly). ValidationEngine.evaluate() is itself contracted
        never to raise (a crashing rule becomes a FAIL finding internally),
        but this is wrapped defensively anyway — the assurance layer must
        never crash collection, even if that contract were ever violated.
        """
        if self._validator is None:
            return None
        try:
            return self._validator.evaluate(record)
        except Exception as exc:  # noqa: BLE001 — validation must never abort a tick
            self._log.error(
                "validation_engine_error",
                extra={"poll_id": record.poll_id, "exc_type": type(exc).__name__},
            )
            return None

    def _persist_quality(
        self, record: ObservationRecord, findings: list[ValidationFinding]
    ) -> None:
        """Best-effort write of *findings* to the quality stream.

        Never raises and never aborts the run: an ArchiverError here (disk
        full, permission error, etc.) is logged and swallowed, unlike the
        same exception from the raw archiver, which is fatal. Losing a
        quality-stream write is not an existential threat the way losing raw
        observation data is — mirrors the existing best-effort pattern
        discovery_run.py already uses for manifest writes.
        """
        if self._quality_archiver is None:
            return
        verdict_dict = {
            "poll_id": record.poll_id,
            "session_id": record.session_id,
            "polled_at": record.polled_at,
            "ruleset_version": self._validator.ruleset_version if self._validator else None,
            "findings": [dataclasses.asdict(f) for f in findings],
        }
        try:
            self._quality_archiver.write(verdict_dict)
        except ArchiverError as exc:
            self._log.error(
                "quality_write_failed",
                extra={"poll_id": record.poll_id, "exc_type": type(exc).__name__},
            )

    def _log_validation_outcome(
        self, record: ObservationRecord, findings: list[ValidationFinding]
    ) -> None:
        """Log WARN if any WARN findings exist; log ERROR if any FAIL
        findings exist. These are independent conditions — a record with
        both a WARN and a FAIL finding logs both lines, so neither is ever
        silently shadowed by the other.
        """
        warn_findings = [f for f in findings if f.level == "WARN"]
        fail_findings = [f for f in findings if f.level == "FAIL"]

        if warn_findings:
            self._log.warning(
                "validation_warn",
                extra={
                    "poll_id": record.poll_id,
                    "warn_count": len(warn_findings),
                    "rules": [f.rule_id for f in warn_findings],
                },
            )
        if fail_findings:
            self._log.error(
                "validation_fail",
                extra={
                    "poll_id": record.poll_id,
                    "fail_count": len(fail_findings),
                    "rules": [f.rule_id for f in fail_findings],
                },
            )
