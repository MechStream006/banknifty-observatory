"""
ChainFetcher — windowed BankNifty CE + PE option-chain retrieval.

Three-phase design:
  Phase 1   searchScrip("NFO", "BANKNIFTY")  → discover CE and PE token maps
            for the configured expiry (token_string → strike_int).
  Phase 1.5 StrikeLadder selects the ±window_steps backbone-strike window
            around ATM = round(spot / step_size) * step_size for CE, then
            derives the matching PE tokens for the same strikes.
  Phase 2   getMarketData(mode="FULL", exchangeTokens={"NFO": batch})  →
            fetch full market data for windowed CE+PE tokens in batches of at
            most _BATCH_SIZE tokens.  SmartAPI rejects requests with more than
            50 tokens per exchange per call (error AB4029).  For a 500-pt
            window of ±15 steps: 31 CE + 31 PE = 62 tokens → 2 batches.

Symbol format (confirmed live, 22 Jun 2026):
  searchScrip tradingsymbol : BANKNIFTY26JUN2651000CE
                                ^^^^^^^^^ = underlying
                                         ^^^^^^^ = expiry_2y (DDMMMYY)
                                                ^^^^^ = strike
                                                     ^^ = side (CE or PE)
  getMarketData tradingSymbol : same format (camelCase key)

Design constraints:
- fetch() ALWAYS returns ChainResult — it never raises.
- raw_response on success is a synthetic merged dict covering all batches'
  CE+PE rows.  It is NOT a verbatim single-call response.
- On any batch failure the remaining batches are abandoned immediately.
- Latency covers the full three-phase operation.
- http_status is always None — the SDK does not expose the HTTP status code.
- response_bytes is the sum of compact UTF-8 JSON sizes across all batch
  responses (success path), or the size of the failing batch response.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from lib.discovery._errors import ChainFetchError  # noqa: F401 — re-exported for callers
from lib.discovery._models import ChainResult
from lib.discovery.fetchers.strike_ladder import StrikeLadder
from lib.logging._factory import get_logger

if TYPE_CHECKING:
    from SmartApi import SmartConnect

_NFO = "NFO"
_BANKNIFTY = "BANKNIFTY"
_CE = "CE"
_PE = "PE"
_FULL = "FULL"

# SmartAPI hard limit: 50 tokens per exchange per getMarketData call (error AB4029).
_BATCH_SIZE = 50

# searchScrip uses lowercase keys; getMarketData uses camelCase.
_SCRIP_SYMBOL_KEY = "tradingsymbol"
_SCRIP_TOKEN_KEY  = "symboltoken"

# Keys tried in order when extracting expiryDate from getMarketData rows.
_EXPIRY_KEYS = ("expiryDate", "expiry", "ExpiryDate")

# Prefix length: len("BANKNIFTY") = 9; expiry_2y is always 7 chars (DDMMMYY).
_UNDERLYING_LEN = 9
_EXPIRY_2Y_LEN  = 7
_SIDE_LEN       = 2
_SYMBOL_PREFIX_LEN = _UNDERLYING_LEN + _EXPIRY_2Y_LEN  # = 16


# ── Mockable helpers ────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _monotonic() -> float:
    return time.monotonic()


def _json_size(obj: object) -> int:
    """Compact UTF-8 byte length of *obj* serialised to JSON."""
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


# ── ChainFetcher ────────────────────────────────────────────────────────────────


class ChainFetcher:
    """Windowed BankNifty CE + PE option-chain retrieval for one expiry.

    Fetches both CE and PE sides, restricted to the ±window_steps backbone
    strikes around the current ATM derived from spot.

    Parameters
    ----------
    expiry:
        Active BankNifty expiry in **DDMMMYYYY** format (e.g. ``"30JUN2026"``).
        Converted internally to the two-digit year form used in SmartAPI
        symbol names (e.g. ``"30JUN26"``).
    window_steps:
        Half-width of the backbone window: fetches strikes at
        ATM ± window_steps × step_size.  Default 15 gives a 31-strike
        window on the 500-pt backbone (= ±7 500 index points).
    step_size:
        Backbone grid spacing in index points.  Passed to StrikeLadder.
        Default 500 matches the Phase-1 "liquid 500-pt ladder" contract.

    Usage::

        fetcher = ChainFetcher(expiry="30JUN2026")
        for tick in scheduler.ticks():
            session.refresh_if_needed()
            result = fetcher.fetch(session.smart, spot=spot_result.ltp)
            if result.success:
                archiver.write(dataclasses.asdict(result))
    """

    def __init__(
        self,
        expiry: str,
        window_steps: int = 15,
        step_size: int = 500,
    ) -> None:
        self._expiry = expiry
        # SmartAPI symbol names embed a two-digit year: "BANKNIFTY30JUN2643000CE"
        # Input "30JUN2026" → [:5]="30JUN", [7:]="26" → "30JUN26"
        self._expiry_2y: str = expiry[:5] + expiry[7:]
        self._window_steps = window_steps
        self._step_size = step_size
        self._log = get_logger("chain_fetcher")

    # ── Properties ──────────────────────────────────────────────────────────────

    @property
    def expiry(self) -> str:
        """Configured expiry in DDMMMYYYY format."""
        return self._expiry

    @property
    def expiry_2y(self) -> str:
        """Expiry converted to two-digit year format for symbol matching."""
        return self._expiry_2y

    @property
    def window_steps(self) -> int:
        """Number of backbone steps on each side of ATM to include."""
        return self._window_steps

    @property
    def step_size(self) -> int:
        """Backbone grid spacing in index points."""
        return self._step_size

    # ── Public interface ─────────────────────────────────────────────────────────

    def fetch(self, smart: SmartConnect, spot: float) -> ChainResult:
        """Fetch the windowed CE + PE chain for the configured expiry.

        Always returns a ``ChainResult`` — never raises.  Any error is
        captured in ``ChainResult(success=False, error=...)``.

        Parameters
        ----------
        smart:
            Authenticated ``SmartConnect`` instance (from SmartAPISession).
        spot:
            Current BankNifty index LTP.  Used by StrikeLadder to resolve ATM
            and select the ±window_steps backbone window.

        Returns
        -------
        ChainResult
            On success: ``success=True``, ``raw_response`` is a synthetic
            merged dict with all CE+PE rows, ``row_count >= 1``.
            On failure: ``success=False``, ``error`` describes which phase
            failed.  Exception messages are NOT propagated (only type names)
            to prevent internal details from leaking into logs.
        """
        fetched_at = _utc_now()
        t0 = _monotonic()

        # ── Phase 1: token discovery ───────────────────────────────────────────
        try:
            search_result: dict[str, object] = smart.searchScrip(
                exchange=_NFO, searchscrip=_BANKNIFTY
            )
        except Exception as exc:
            latency_ms = (_monotonic() - t0) * 1000
            self._log.error(
                "chain_scrip_search_error",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "exc_type": type(exc).__name__,
                    "expiry": self._expiry,
                },
            )
            return self._failure(
                fetched_at, latency_ms,
                f"searchScrip raised {type(exc).__name__}",
                raw_response=None, response_bytes=0,
            )

        ce_token_map = self._filter_tokens(search_result, _CE)
        pe_token_map = self._filter_tokens(search_result, _PE)

        if not ce_token_map:
            latency_ms = (_monotonic() - t0) * 1000
            scrip_data = search_result.get("data")
            scrip_count = len(scrip_data) if isinstance(scrip_data, list) else 0
            error = (
                f"No BANKNIFTY CE tokens found for expiry={self._expiry!r} "
                f"(searched as {self._expiry_2y!r}). "
                f"searchScrip returned {scrip_count} instruments."
            )
            self._log.error(
                "chain_no_ce_tokens",
                extra={
                    "expiry": self._expiry,
                    "expiry_2y": self._expiry_2y,
                    "scrip_count": scrip_count,
                },
            )
            return self._failure(fetched_at, latency_ms, error, raw_response=None, response_bytes=0)

        # ── Phase 1.5: window selection via StrikeLadder ───────────────────────
        ladder = StrikeLadder(ce_token_map, step_size=self._step_size)
        ce_window_tokens = ladder.window(spot, steps=self._window_steps)

        if not ce_window_tokens:
            latency_ms = (_monotonic() - t0) * 1000
            error = (
                f"StrikeLadder window is empty for expiry={self._expiry!r} "
                f"(spot={spot}, steps={self._window_steps}, step_size={self._step_size}). "
                f"CE backbone has {len(ladder.backbone_strikes)} strikes."
            )
            self._log.error(
                "chain_empty_window",
                extra={
                    "expiry": self._expiry,
                    "spot": spot,
                    "window_steps": self._window_steps,
                    "backbone_count": len(ladder.backbone_strikes),
                },
            )
            return self._failure(fetched_at, latency_ms, error, raw_response=None, response_bytes=0)

        # Derive PE window: same backbone strikes as CE window, via PE token map.
        window_strikes = [ce_token_map[t] for t in ce_window_tokens]
        pe_strike_to_token: dict[int, str] = {s: t for t, s in pe_token_map.items()}
        pe_window_tokens = [
            pe_strike_to_token[s]
            for s in window_strikes
            if s in pe_strike_to_token
        ]

        all_window_tokens = ce_window_tokens + pe_window_tokens

        self._log.info(
            "chain_window_selected",
            extra={
                "expiry": self._expiry,
                "spot": spot,
                "resolved_atm": ladder.resolved_atm(spot),
                "ce_window": len(ce_window_tokens),
                "pe_window": len(pe_window_tokens),
                "total_window": len(all_window_tokens),
            },
        )

        # ── Phase 2: batched market data fetch ─────────────────────────────────
        batches = [
            all_window_tokens[i : i + _BATCH_SIZE]
            for i in range(0, len(all_window_tokens), _BATCH_SIZE)
        ]
        batch_count = len(batches)
        all_fetched:   list[object] = []
        all_unfetched: list[object] = []
        total_bytes = 0

        for batch_idx, batch in enumerate(batches):
            try:
                response: dict[str, object] = smart.getMarketData(
                    mode=_FULL,
                    exchangeTokens={_NFO: batch},
                )
            except Exception as exc:
                latency_ms = (_monotonic() - t0) * 1000
                error = (
                    f"getMarketData raised {type(exc).__name__} "
                    f"(batch {batch_idx + 1}/{batch_count})"
                )
                self._log.error(
                    "chain_market_data_error",
                    extra={
                        "latency_ms": round(latency_ms, 2),
                        "exc_type": type(exc).__name__,
                        "batch_idx": batch_idx,
                        "batch_count": batch_count,
                        "expiry": self._expiry,
                    },
                )
                return self._failure(
                    fetched_at, latency_ms, error, raw_response=None, response_bytes=0
                )

            if not isinstance(response, dict):
                latency_ms = (_monotonic() - t0) * 1000
                error = (
                    f"getMarketData returned unexpected type: {type(response).__name__} "
                    f"(batch {batch_idx + 1}/{batch_count})"
                )
                self._log.error(
                    "chain_unexpected_response_type",
                    extra={
                        "latency_ms": round(latency_ms, 2),
                        "batch_idx": batch_idx,
                    },
                )
                return self._failure(
                    fetched_at, latency_ms, error, raw_response=None, response_bytes=0
                )

            if not response.get("status"):
                latency_ms = (_monotonic() - t0) * 1000
                batch_bytes = _json_size(response)
                errorcode = str(response.get("errorcode") or "")
                message   = str(response.get("message") or "unknown error")
                error = (
                    f"getMarketData failed [{errorcode}]: {message} "
                    f"(batch {batch_idx + 1}/{batch_count})"
                )
                self._log.error(
                    "chain_api_error",
                    extra={
                        "latency_ms": round(latency_ms, 2),
                        "errorcode": errorcode,
                        "batch_idx": batch_idx,
                        "batch_count": batch_count,
                    },
                )
                return self._failure(
                    fetched_at, latency_ms, error,
                    raw_response=response, response_bytes=batch_bytes,
                )

            total_bytes += _json_size(response)
            batch_fetched, batch_unfetched = self._parse_rows(response)
            all_fetched.extend(batch_fetched)
            all_unfetched.extend(batch_unfetched)

        latency_ms = (_monotonic() - t0) * 1000

        merged_response: dict[str, object] = {
            "status": True,
            "message": "SUCCESS",
            "errorcode": "",
            "data": {
                "fetched":   all_fetched,
                "unfetched": all_unfetched,
            },
        }

        row_count       = len(all_fetched)
        unfetched_count = len(all_unfetched)
        expiry_count    = self._count_expiries(all_fetched)

        if row_count == 0:
            error = "getMarketData returned status=true but fetched list is empty"
            self._log.warning(
                "chain_empty_rows",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "unfetched_count": unfetched_count,
                    "expiry": self._expiry,
                },
            )
            return ChainResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                http_status=None,
                response_bytes=total_bytes,
                raw_response=merged_response,
                row_count=0,
                expiry_count=0,
                unfetched_count=unfetched_count,
                error=error,
                success=False,
            )

        self._log.info(
            "chain_ok",
            extra={
                "latency_ms": round(latency_ms, 2),
                "row_count": row_count,
                "expiry_count": expiry_count,
                "unfetched_count": unfetched_count,
                "response_bytes": total_bytes,
                "batch_count": batch_count,
                "expiry": self._expiry,
            },
        )
        return ChainResult(
            fetched_at=fetched_at,
            latency_ms=round(latency_ms, 2),
            http_status=None,
            response_bytes=total_bytes,
            raw_response=merged_response,
            row_count=row_count,
            expiry_count=expiry_count,
            unfetched_count=unfetched_count,
            error=None,
            success=True,
        )

    # ── Internal ─────────────────────────────────────────────────────────────────

    def _filter_tokens(
        self, search_result: dict[str, object], side: str
    ) -> dict[str, int]:
        """Build a token → strike map for the given side from a searchScrip response.

        Only includes instruments whose tradingsymbol ends with *side* (CE or PE)
        and contains the configured expiry_2y substring.  The strike is extracted
        from the symbol: the characters between the 16-char prefix
        (BANKNIFTY + expiry_2y) and the 2-char side suffix.

        Symbol format: BANKNIFTY + DDMMMYY + strike_digits + CE|PE
        Example      : BANKNIFTY26JUN2651000CE  →  strike = 51000

        searchScrip uses lowercase keys; filtering is case-insensitive.
        """
        scrip_data = search_result.get("data")
        all_scrips: list[object] = scrip_data if isinstance(scrip_data, list) else []
        token_map: dict[str, int] = {}
        expiry_upper = self._expiry_2y.upper()
        side_upper = side.upper()

        for item in all_scrips:
            if not isinstance(item, dict):
                continue
            sym = str(item.get(_SCRIP_SYMBOL_KEY, "")).upper()
            if not sym.endswith(side_upper):
                continue
            if expiry_upper not in sym:
                continue
            # Extract strike: chars between the 16-char prefix and the 2-char side suffix
            if len(sym) <= _SYMBOL_PREFIX_LEN + _SIDE_LEN:
                continue
            strike_str = sym[_SYMBOL_PREFIX_LEN : -_SIDE_LEN]
            try:
                strike = int(strike_str)
            except ValueError:
                continue
            token = str(item.get(_SCRIP_TOKEN_KEY, ""))
            if token:
                token_map[token] = strike
        return token_map

    def _parse_rows(
        self, response: dict[str, object]
    ) -> tuple[list[object], list[object]]:
        """Extract (fetched_rows, unfetched_rows) from a getMarketData response.

        Tolerates both ``{"data": {"fetched": [...]}}`` and the flat
        ``{"data": [...]}`` layout observed in some SDK versions.
        """
        raw_data = response.get("data")
        fetched:   list[object] = []
        unfetched: list[object] = []
        if isinstance(raw_data, dict):
            rows = raw_data.get("fetched")
            if isinstance(rows, list):
                fetched = rows
            uf = raw_data.get("unfetched")
            if isinstance(uf, list):
                unfetched = uf
        elif isinstance(raw_data, list):
            fetched = raw_data
        return fetched, unfetched

    def _count_expiries(self, rows: list[object]) -> int:
        """Count distinct expiryDate values across a list of getMarketData rows."""
        expiry_dates: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in _EXPIRY_KEYS:
                val = row.get(key)
                if isinstance(val, str) and val:
                    expiry_dates.add(val)
                    break
        return len(expiry_dates)

    def _failure(
        self,
        fetched_at: datetime,
        latency_ms: float,
        error: str,
        raw_response: dict[str, object] | None,
        response_bytes: int,
    ) -> ChainResult:
        return ChainResult(
            fetched_at=fetched_at,
            latency_ms=round(latency_ms, 2),
            http_status=None,
            response_bytes=response_bytes,
            raw_response=raw_response,
            row_count=0,
            expiry_count=0,
            unfetched_count=0,
            error=error,
            success=False,
        )
