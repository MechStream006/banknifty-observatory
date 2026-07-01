"""Shared dataclasses for the discovery infrastructure.

All components import types from here. No component defines its own
protocol-level types.

Frozen dataclasses (immutable after construction): PhaseConfig, SessionToken,
SnapshotMeta, OIChange.

Mutable dataclasses: ChainResult, SpotResult, VIXResult, PollRecord,
SmokeTestResult, PhaseResult, DerivedObservation, ObservationRecord.

OBSERVATION_SCHEMA_VERSION identifies the ObservationRecord JSONL line schema.
  version 2 — Phase-1 observatory contract (current)
  version 3 — reserved for Phase-2 futures addition

COLLECTION_CONTRACT_VERSION identifies *what the collector was configured to
observe* (underlying, expiries, window, step). It is orthogonal to the schema
version: schema describes record layout, contract describes observation intent.
A record can keep the same schema_version while the collection contract changes
(e.g. a different expiry set) and vice versa.

Schema compatibility policy (enforced by test_schema_policy.py)
--------------------------------------------------------------
Within a single OBSERVATION_SCHEMA_VERSION:
  * Changes are ADDITIVE ONLY. New optional fields (with defaults) may be added
    without a version bump. Two records sharing a schema_version may therefore
    carry different key sets — an older record simply lacks the newer keys.
  * Removing a field, renaming a field, or changing the meaning/units of an
    existing field REQUIRES an OBSERVATION_SCHEMA_VERSION increment.
  * READERS MUST TOLERATE UNKNOWN FIELDS. Any consumer of the JSONL archive
    must ignore keys it does not recognise rather than failing, so that records
    written by a newer additive schema remain readable by older tooling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final


# Increment when ObservationRecord fields change incompatibly (see the schema
# compatibility policy in the module docstring). Additive fields do NOT bump it.
# Phase-1 observatory contract: version 2.
# Phase-2 futures: bump to 3 and populate futures_result.
OBSERVATION_SCHEMA_VERSION: Final[int] = 2

# Identifies what the collector was configured to observe. Bump when the
# observation intent changes in a way analysis must distinguish (e.g. a change
# to how the ATM window or step grid is defined). Independent of the schema
# version — see the module docstring.
COLLECTION_CONTRACT_VERSION: Final[int] = 1


@dataclass(frozen=True)
class PhaseConfig:
    """Configuration for a single discovery phase run.

    Frozen: constructed once by the CLI and passed through unchanged.
    All Path values should be absolute before construction.
    """

    phase: int
    interval_seconds: int
    max_duration_seconds: int | None
    data_dir: Path
    db_path: Path


@dataclass(frozen=True)
class SessionToken:
    """Authentication token bundle returned by SmartAPI on successful login.

    Frozen: token values must not change after acquisition; any refresh
    produces a new SessionToken instance rather than mutating this one.

    Note: user_profile is a mutable dict stored inside a frozen dataclass.
    The frozen constraint prevents reassignment of the attribute, not
    mutation of the dict itself. Callers must not mutate user_profile.
    Calling hash() on a SessionToken instance will raise TypeError at
    runtime due to the dict field; this is acceptable since SessionToken
    is never used as a dict key or set member.
    """

    jwt_token: str
    refresh_token: str
    feed_token: str
    acquired_at: datetime
    user_profile: dict[str, object]


@dataclass(frozen=True)
class OptionQuote:
    """One parsed option contract observation within a chain snapshot.

    Immutable instrument identity plus its point-in-time metrics, extracted
    from the raw chain row during collection so that later analysis never has
    to re-parse ``tradingSymbol``. The raw payload is preserved unchanged on
    the parent ChainResult; this is a structured, additive projection of it.

    underlying / expiry / strike / option_side fully identify the instrument.
    ltp is best-effort (None when the raw row carried no last-traded price).
    """

    underlying: str
    expiry: str
    strike: int
    option_side: str  # "CE" or "PE"
    oi: int
    volume: int
    ltp: float | None


@dataclass
class ChainResult:
    """Result of one BankNifty option chain API call.

    Always returned by ChainFetcher.fetch() — never raised. On API failure,
    success=False and error carries a sanitised description (no secrets).
    raw_response is None on failure; the full parsed JSON dict on success.

    expiry and quotes are populated by the controller after fetch (additive,
    Phase-1 freeze patch). raw_response is never modified. quotes is the
    parsed instrument-identity projection of the raw rows; expiry is the
    configured expiry this chain was fetched for.
    """

    fetched_at: datetime
    latency_ms: float
    http_status: int | None
    response_bytes: int
    raw_response: dict[str, object] | None
    row_count: int
    expiry_count: int
    unfetched_count: int
    error: str | None
    success: bool
    expiry: str = ""
    quotes: list[OptionQuote] = field(default_factory=list)


@dataclass
class SpotResult:
    """Result of one BankNifty spot index level retrieval.

    Always returned by SpotFetcher.fetch() — never raised. source indicates
    how the value was obtained: "chain_embedded" means it was extracted from
    the chain response (no extra API call), "separate_call" means an
    independent market-data call was issued, "unavailable" means neither
    source produced a value.
    """

    fetched_at: datetime
    latency_ms: float
    ltp: float | None
    raw_response: dict[str, object] | None
    source: str  # "chain_embedded" | "separate_call" | "unavailable"
    error: str | None
    success: bool


@dataclass
class VIXResult:
    """Result of one India VIX LTP retrieval.

    Always returned by VIXFetcher.fetch() — never raised. On API failure,
    success=False and error carries a sanitised description (no secrets).
    Unlike SpotFetcher there is no source_mode: VIXFetcher always issues
    an independent ltpData call.
    """

    fetched_at: datetime
    latency_ms: float
    ltp: float | None
    raw_response: dict[str, object] | None
    error: str | None
    success: bool


@dataclass(frozen=True)
class SnapshotMeta:
    """Per-snapshot context: when, where, and how the ATM window was resolved.

    Frozen: constructed once per tick from immutable inputs and passed through
    unchanged. Embedded in every ObservationRecord.

    schema_version should always be set to OBSERVATION_SCHEMA_VERSION at
    construction time. It is stored explicitly in the record so that JSONL
    replay tooling can identify the schema without external metadata.

    Note: expiry_set is a mutable list stored inside a frozen dataclass.
    The frozen constraint prevents reassignment of the attribute, not
    mutation of the list itself. Callers must not mutate expiry_set.

    collection_contract_version and chain_step_size are additive provenance
    fields (Phase-1 freeze patch). chain_step_size makes the requested strike
    grid (resolved_atm ± i·chain_step_size for i in 0..window_steps) fully
    reconstructable from the record alone, without external config.
    """

    schema_version: int
    anchoring_spot: float
    resolved_atm: int
    expiry_set: list[str]
    window_steps: int
    collection_contract_version: int = COLLECTION_CONTRACT_VERSION
    chain_step_size: int = 0


@dataclass(frozen=True)
class SnapshotContinuity:
    """Snapshot-level continuity metadata linking this snapshot to the prior one.

    Lets any consumer decide whether two consecutive persisted snapshots are
    contiguous (exactly one poll interval apart) without assuming the archive
    has no gaps. Derived path-dependent metrics (e.g. OI deltas) are computed
    only across CONTIGUOUS snapshots; across a GAP they are withheld rather
    than silently spanning the gap.

    continuity_status:
        "FIRST"      — first snapshot of the run; no predecessor.
        "CONTIGUOUS" — actual interval within tolerance of the expected interval.
        "GAP"        — actual interval outside tolerance (a poll was missed,
                       delayed, or duplicated); path-dependent derivations are
                       not valid across this boundary.
    actual_interval_seconds is None only when continuity_status is "FIRST".
    """

    previous_snapshot_id: str | None
    previous_timestamp: datetime | None
    expected_interval_seconds: int
    actual_interval_seconds: float | None
    continuity_status: str


@dataclass(frozen=True)
class OIChange:
    """OI change for one (expiry, side, strike) instrument, derived from
    consecutive ticks.

    Frozen: constructed from a prior/current snapshot diff; values must not
    change. delta is positive when OI builds (new positions opened), negative
    when OI unwinds (positions closed). Zero is valid (no OI change that tick).

    This is a derived value — not read from the API. The SmartAPI
    getMarketData FULL response does not include a changeInOI field.
    """

    expiry: str
    side: str    # "CE" or "PE"
    strike: int
    delta: int   # current_oi - prior_oi


@dataclass
class DerivedObservation:
    """Per-snapshot derived values computed from raw option rows.

    None of these fields are read from the API — all are computed from the
    raw ChainResult rows stored in the parent ObservationRecord. Every value
    is therefore reproducible from the raw JSONL archive.

    Keys in per-expiry dicts match the strings in SnapshotMeta.expiry_set.
    PCR values are None for an expiry when the denominator is zero (zero CE OI
    or zero CE volume), indicating an unresolvable ratio, not a missing
    computation.

    oi_changes is None on the first tick of a session because no prior snapshot
    exists to compute the delta against. It is populated from the second tick
    onward by the controller.
    """

    total_ce_oi: dict[str, int]
    total_pe_oi: dict[str, int]
    oi_pcr: dict[str, float | None]       # None where total_ce_oi == 0
    volume_pcr: dict[str, float | None]   # None where total CE volume == 0
    oi_changes: list[OIChange] | None = field(default=None)


@dataclass
class ObservationRecord:
    """Complete record of one Phase-1 scheduled observation tick.

    Replaces PollRecord for the Phase-1 observatory contract. PollRecord is
    retained for Phase 0 (smoke test) tooling backwards compatibility.

    poll_id is a uuid4 string. session_id identifies the phase run.

    chains contains one ChainResult per configured expiry. Order matches
    SnapshotMeta.expiry_set. After M-C3 each ChainResult carries windowed
    CE and PE rows for that expiry.

    derived is None when no chain data was available to compute derived values
    (e.g. all expiry fetches failed for the tick).

    futures_result is a reserved slot for Phase-2 futures collection, which is
    deferred from Phase-1. It is always None in Phase-1 records and must not
    be read or populated by Phase-1 code. Its presence as a typed slot ensures
    that Phase-2 can populate it without an ObservationRecord schema change
    beyond a schema_version increment.

    underlying names the instrument this record observes (Phase-1: "BANKNIFTY").
    It is stored explicitly so the corpus is self-describing and multi-symbol
    ready without a schema break. The per-contract underlying is also carried
    on every OptionQuote.

    continuity carries snapshot-level linkage to the previous snapshot. It is
    always populated by the controller for persisted records; the default of
    None applies only to ad-hoc constructions in tests.
    """

    poll_id: str
    session_id: str
    polled_at: datetime
    phase: int
    tick_number: int
    interval_s: int
    meta: SnapshotMeta
    spot: SpotResult
    vix: VIXResult
    chains: list[ChainResult]
    derived: DerivedObservation | None = field(default=None)
    futures_result: dict[str, object] | None = field(default=None)
    underlying: str = "BANKNIFTY"
    continuity: SnapshotContinuity | None = field(default=None)


@dataclass
class PollRecord:
    """Complete record of one scheduled poll tick.

    Written to JSONL and the SQLite analysis store by the controller.
    poll_id is a uuid4 string. session_id identifies the phase run.
    """

    poll_id: str
    session_id: str
    polled_at: datetime
    phase: int
    tick_number: int
    interval_s: int
    chain: ChainResult
    spot: SpotResult


@dataclass
class SmokeTestResult:
    """Outcome of the Phase 0 smoke test.

    passed=True only when auth succeeded, chain was reachable, and
    blocking_issues is empty. The CLI raises SmokeTestFailedError when
    passed=False so the process exits with code 1.
    """

    passed: bool
    auth_latency_ms: float
    chain_reachable: bool
    spot_reachable: bool
    sample_row_count: int
    sample_expiry_count: int
    blocking_issues: list[str]


@dataclass
class PhaseResult:
    """Summary of a completed (or aborted) discovery phase run.

    ended_early=True when the controller stopped before the natural stop
    condition (market close or max_duration) due to an unrecoverable error.
    jsonl_path and db_path are absolute paths to the output artefacts.
    """

    session_id: str
    phase: int
    started_at: datetime
    ended_at: datetime
    total_ticks: int
    successful_polls: int
    failed_polls: int
    jsonl_path: Path
    db_path: Path
    ended_early: bool = field(default=False)
