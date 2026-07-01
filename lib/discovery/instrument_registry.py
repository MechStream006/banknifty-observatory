"""
InstrumentRegistry — session-scoped instrument-universe discovery.

Resolves the full (expiry, side) -> {symboltoken: strike} token universe for
one underlying via a single searchScrip() call per build, replacing the
per-tick, per-expiry searchScrip calls that today live inside
ChainFetcher.fetch() (the proven cause of the 25AUG2026 SmartAPI
rate-limiting failures: ~24 identical searchScrip("BANKNIFTY") calls/minute
across two expiries — 100% of the observed failures were
"searchScrip raised DataException").

Design constraints (frozen — L2 Instrument Registry design)
------------------------------------------------------------
- build() issues exactly one searchScrip call per invocation (plus at most
  one retry on transport/API failure, mirroring SmartAPISession.connect()'s
  one-retry pattern). It is intended to be called once per run, at
  controller startup, after session.connect() — but nothing in this module
  enforces that; it is a plain, stateless-per-call resolver.
- There is no automatic mid-run refresh anywhere in this module. rebuild()
  exists only for explicit, caller-invoked re-resolution (test harnesses,
  future long-lived-process designs) — it is never called automatically.
- A totally empty searchScrip response (zero rows for the configured
  underlying) is immediately fatal (RegistryBuildError) — not retried,
  since a syntactically valid but semantically empty response will not
  change on a second identical call.
- A single configured expiry resolving to zero CE tokens does NOT fail the
  build: it is logged and excluded from resolved_expiries; other expiries
  are unaffected.
- token_map() never raises: unresolved (expiry, side) pairs, or querying
  before any successful build, return {}.
- A failed build()/rebuild() call never mutates previously resolved state —
  if a prior build succeeded, that data remains queryable after a
  subsequent failed rebuild() attempt.
- This module is standalone: it is not wired into ChainFetcher, the
  DiscoveryController, or scripts/discovery_run.py. Nothing outside this
  file changes behavior as a result of its existence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from lib.discovery._errors import RegistryBuildError
from lib.logging._factory import get_logger

if TYPE_CHECKING:
    from SmartApi import SmartConnect

# ── Constants ───────────────────────────────────────────────────────────────

_NFO = "NFO"
_CE = "CE"
_PE = "PE"
_SIDES = (_CE, _PE)

# searchScrip response rows use lowercase keys.
_SCRIP_SYMBOL_KEY = "tradingsymbol"
_SCRIP_TOKEN_KEY = "symboltoken"

# Symbol format: <underlying> + <expiry_2y, DDMMMYY, 7 chars> + <strike digits> + <side, 2 chars>
_EXPIRY_2Y_LEN = 7
_SIDE_LEN = 2


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _to_expiry_2y(expiry: str) -> str:
    """Convert a DDMMMYYYY expiry to the DDMMMYY form used in symbol names.

    Example: "30JUN2026" -> "30JUN26".
    """
    return expiry[:5] + expiry[7:]


@dataclass(frozen=True)
class RegistrySnapshot:
    """Provenance snapshot of one InstrumentRegistry's current state.

    Not consumed by any Phase-1 logic yet — reserved for a future additive
    RunManifest field. built_at is None before the first successful build.
    """

    underlying: str
    built_at: datetime | None
    token_counts: dict[str, dict[str, int]]
    retry_count: int


# ── InstrumentRegistry ────────────────────────────────────────────────────────


class InstrumentRegistry:
    """Session-scoped instrument-universe resolver for one underlying.

    One instance resolves one underlying's full instrument universe from a
    single searchScrip() call. Multi-underlying support (e.g. a future
    NIFTY registry) is one additional instance, not a feature of this class.

    Usage::

        registry = InstrumentRegistry(underlying="BANKNIFTY")
        registry.build(session.smart, expiries=["30JUN2026", "28JUL2026"])
        ce_tokens = registry.token_map("30JUN2026", "CE")
    """

    def __init__(self, underlying: str = "BANKNIFTY") -> None:
        self._underlying = underlying
        self._prefix_len = len(underlying) + _EXPIRY_2Y_LEN
        self._log = get_logger("instrument_registry")

        self._tokens: dict[str, dict[str, dict[str, int]]] = {}
        self._resolved_expiries: list[str] = []
        self._built_at: datetime | None = None
        self._last_retry_count: int = 0

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def underlying(self) -> str:
        """The configured underlying symbol (e.g. "BANKNIFTY")."""
        return self._underlying

    @property
    def is_built(self) -> bool:
        """True once build()/rebuild() has completed successfully at least once."""
        return self._built_at is not None

    @property
    def resolved_expiries(self) -> list[str]:
        """Configured expiries (in build() order) that resolved >=1 CE token."""
        return list(self._resolved_expiries)

    # ── Public interface ────────────────────────────────────────────────────

    def build(self, smart: SmartConnect, expiries: list[str]) -> None:
        """Resolve the instrument universe for *expiries* via one searchScrip call.

        Parameters
        ----------
        smart:
            Authenticated SmartConnect instance.
        expiries:
            Configured expiry strings in DDMMMYYYY format.

        Raises
        ------
        RegistryBuildError
            If searchScrip fails on both attempts, returns an unusable
            response shape, or returns zero instruments for the configured
            underlying. Previously resolved state (if any) is left intact.
        """
        self._do_build(smart, expiries)

    def rebuild(self, smart: SmartConnect, expiries: list[str]) -> None:
        """Explicit re-resolution with identical semantics to build().

        Never invoked automatically by this module or any Phase-1 caller —
        reserved for test harnesses and future long-lived-process designs.
        A failed rebuild() never discards a previously successful build().
        """
        self._do_build(smart, expiries)

    def token_map(self, expiry: str, side: str) -> dict[str, int]:
        """token -> strike for one (expiry, side).

        Returns {} for an unresolved expiry/side or before any successful
        build. Never raises.
        """
        return dict(self._tokens.get(expiry, {}).get(side.upper(), {}))

    def snapshot(self) -> RegistrySnapshot:
        """Provenance snapshot of the current (possibly unbuilt) state."""
        counts = {
            expiry: {side: len(tokens) for side, tokens in sides.items()}
            for expiry, sides in self._tokens.items()
        }
        return RegistrySnapshot(
            underlying=self._underlying,
            built_at=self._built_at,
            token_counts=counts,
            retry_count=self._last_retry_count,
        )

    # ── Internal — build orchestration ──────────────────────────────────────

    def _do_build(self, smart: SmartConnect, expiries: list[str]) -> None:
        response, error, retry_count = self._search_with_retry(smart)
        self._last_retry_count = retry_count

        if error is not None:
            self._log.error(
                "registry_build_failed",
                extra={
                    "underlying": self._underlying,
                    "error": error,
                    "retry_count": retry_count,
                },
            )
            raise RegistryBuildError(error)

        data = response.get("data") if response is not None else None
        rows: list[object] = data if isinstance(data, list) else []

        if not rows:
            error = (
                f"searchScrip returned 0 instruments for "
                f"underlying={self._underlying!r}"
            )
            self._log.error(
                "registry_build_empty",
                extra={"underlying": self._underlying, "retry_count": retry_count},
            )
            raise RegistryBuildError(error)

        tokens: dict[str, dict[str, dict[str, int]]] = {}
        resolved: list[str] = []

        for expiry in expiries:
            expiry_2y = _to_expiry_2y(expiry)
            ce_map = self._filter_tokens(rows, expiry_2y, _CE)
            pe_map = self._filter_tokens(rows, expiry_2y, _PE)
            tokens[expiry] = {_CE: ce_map, _PE: pe_map}

            if ce_map:
                resolved.append(expiry)
            else:
                self._log.error(
                    "registry_expiry_unresolved",
                    extra={
                        "underlying": self._underlying,
                        "expiry": expiry,
                        "expiry_2y": expiry_2y,
                        "scrip_count": len(rows),
                    },
                )

        self._tokens = tokens
        self._resolved_expiries = resolved
        self._built_at = _utc_now()

        self._log.info(
            "registry_built",
            extra={
                "underlying": self._underlying,
                "expiries_configured": len(expiries),
                "expiries_resolved": len(resolved),
                "scrip_count": len(rows),
                "retry_count": retry_count,
            },
        )

    def _search_with_retry(
        self, smart: SmartConnect
    ) -> tuple[dict[str, object] | None, str | None, int]:
        """One searchScrip call, retried once on transport/API failure.

        Never raises. Returns (response, None, retry_count) on success, or
        (None, error_message, retry_count) if both attempts failed. An
        empty-but-successful response (status=true, data=[]) is treated as
        success here — emptiness is judged by the caller, not retried here.
        """
        retry_count = 0
        error: str | None = None

        for attempt in (1, 2):
            try:
                response: object = smart.searchScrip(
                    exchange=_NFO, searchscrip=self._underlying
                )
            except Exception as exc:
                error = f"searchScrip raised {type(exc).__name__}"
                self._log.error(
                    "registry_search_error",
                    extra={"exc_type": type(exc).__name__, "attempt": attempt},
                )
            else:
                if not isinstance(response, dict):
                    error = (
                        f"searchScrip returned unexpected type: "
                        f"{type(response).__name__}"
                    )
                    self._log.error(
                        "registry_search_unexpected_response_type",
                        extra={
                            "response_type": type(response).__name__,
                            "attempt": attempt,
                        },
                    )
                elif not response.get("status"):
                    errorcode = str(response.get("errorcode") or "")
                    message = str(response.get("message") or "unknown error")
                    error = f"searchScrip failed [{errorcode}]: {message}"
                    self._log.error(
                        "registry_search_api_error",
                        extra={"errorcode": errorcode, "attempt": attempt},
                    )
                else:
                    return response, None, retry_count

            if attempt == 1:
                retry_count += 1

        return None, error, retry_count

    # ── Internal — parsing ───────────────────────────────────────────────────

    def _filter_tokens(
        self, rows: list[object], expiry_2y: str, side: str
    ) -> dict[str, int]:
        """Build a token -> strike map for one (expiry_2y, side) from raw rows.

        Matching rules mirror ChainFetcher._filter_tokens exactly: a
        case-insensitive side-suffix match plus an expiry_2y substring
        match, with the strike parsed from the fixed-offset slice between
        the underlying+expiry prefix and the side suffix.
        """
        token_map: dict[str, int] = {}
        expiry_upper = expiry_2y.upper()
        side_upper = side.upper()

        for item in rows:
            if not isinstance(item, dict):
                continue
            sym = str(item.get(_SCRIP_SYMBOL_KEY, "")).upper()
            if not sym.endswith(side_upper):
                continue
            if expiry_upper not in sym:
                continue
            if len(sym) <= self._prefix_len + _SIDE_LEN:
                continue
            strike_str = sym[self._prefix_len : -_SIDE_LEN]
            try:
                strike = int(strike_str)
            except ValueError:
                continue
            token = str(item.get(_SCRIP_TOKEN_KEY, ""))
            if token:
                token_map[token] = strike
        return token_map
