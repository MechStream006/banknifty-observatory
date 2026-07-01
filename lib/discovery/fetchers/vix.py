"""
VIXFetcher — India VIX LTP retrieval via SmartAPI.

Issues a single ``ltpData()`` call per tick against the fixed India VIX
instrument identity and packages the result into a ``VIXResult``.

Why a hard-coded token (and why this one is trustworthy)
----------------------------------------------------------
An earlier version hard-coded ``symboltoken="1333"``, which in fact resolves
to HDFCBANK-EQ, not India VIX — ``ltpData`` keys off ``symboltoken`` and
silently ignores a mismatched ``tradingsymbol`` label, so every VIX value
ever collected under that token was a corrupted equity price.

A later revision attempted to eliminate hard-coded tokens entirely by
resolving India VIX via ``searchScrip(exchange="NSE", searchscrip=...)`` at
runtime. Live verification against the production SmartAPI showed this does
not work: India VIX is an index instrument (``instrumenttype: AMXIDX`` in
Angel One's own scrip master), and ``searchScrip`` only searches the
tradable-instrument index — it returned zero matches for "INDIA VIX",
"INDIAVIX", and "VIX" alike. This is the same reason ``SpotFetcher`` already
hard-codes the NIFTY BANK index token (99926009) rather than discovering it.

The constants below were verified directly against Angel One's official
``OpenAPIScripMaster.json`` (the canonical instrument master), cross-checked
against Angel's own SmartAPI forum announcement and sample ``ltpData``
response for India VIX. There is exactly one VIX entry in the scrip master:
``{"token": "99926017", "symbol": "India VIX", "name": "INDIA VIX",
"exch_seg": "NSE", "instrumenttype": "AMXIDX"}``.

Design constraints (matching SpotFetcher / ChainFetcher):
- fetch() ALWAYS returns VIXResult — it never raises.
- Exception messages are NOT propagated; only the exception type name is
  recorded in VIXResult.error. This prevents internal details from
  leaking into logs or persisted records.
- raw_response is set to the verbatim ltpData API dict on all code paths
  that reach a dict response (including status=False responses); None only
  when the SDK raises or returns a non-dict value.
- latency_ms covers the full fetch() call (the single ltpData round trip),
  rounded to 2 dp.
- fetched_at is the UTC wall-clock instant before work begins.

Sanity checks
-------------
- Response identity: if the live ltpData response carries a
  ``tradingsymbol`` that does not normalise (upper-case, spaces stripped) to
  "INDIAVIX", the result is rejected. This guards against the same failure
  class as the original token=1333 bug recurring (e.g. broker-side token
  remapping) even though the token is no longer runtime-discovered.
- Value range: ltp must be a finite number in [_VIX_MIN, _VIX_MAX]. India
  VIX has never traded outside roughly 5-90 historically; the configured
  band is a deliberately generous safety net, wide enough to never reject
  genuine VIX prints but tight enough to catch gross mismatches (e.g. an
  equity LTP in the hundreds or thousands).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from lib.discovery._models import VIXResult
from lib.logging._factory import get_logger

if TYPE_CHECKING:
    from SmartApi import SmartConnect

# ── Constants ───────────────────────────────────────────────────────────────────

_EXCHANGE = "NSE"

# Verified against Angel One's official OpenAPIScripMaster.json — the only
# India VIX entry in the instrument master (instrumenttype: AMXIDX).
_TRADINGSYMBOL = "India VIX"
_SYMBOLTOKEN = "99926017"

# Normalised (upper-case, whitespace-stripped) identity every live ltpData
# response's tradingsymbol must match.
_EXPECTED_IDENTITY = "INDIAVIX"

# Plausibility band for a genuine India VIX value. Deliberately generous —
# this exists to catch gross identity errors (e.g. an equity LTP), not to
# second-guess legitimate volatility spikes.
_VIX_MIN = 1.0
_VIX_MAX = 100.0


def _normalize(symbol: str) -> str:
    """Case/whitespace-insensitive identity key for a tradingsymbol."""
    return symbol.strip().upper().replace(" ", "")


# ── Mockable helpers ─────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _monotonic() -> float:
    return time.monotonic()


# ── VIXFetcher ────────────────────────────────────────────────────────────────────


class VIXFetcher:
    """India VIX LTP retrieval via a fixed (tradingsymbol, symboltoken).

    No constructor parameters. The instrument identity (India VIX,
    NSE, token 99926017) is fixed and verified against Angel One's official
    instrument master — see module docstring.

    Usage::

        vix_fetcher = VIXFetcher()
        for tick in scheduler.ticks():
            session.refresh_if_needed()
            vix_result = vix_fetcher.fetch(session.smart)
            if vix_result.success:
                record.vix = vix_result
    """

    def __init__(self) -> None:
        self._log = get_logger("vix_fetcher")

    @property
    def token(self) -> str:
        """The fixed India VIX symboltoken."""
        return _SYMBOLTOKEN

    @property
    def symbol(self) -> str:
        """The fixed India VIX tradingsymbol."""
        return _TRADINGSYMBOL

    def fetch(self, smart: SmartConnect) -> VIXResult:
        """Retrieve the India VIX LTP.

        Always returns a ``VIXResult`` — never raises. Any error from the
        SmartAPI SDK, a failed API status, or a failed sanity check is
        captured in ``VIXResult(success=False, error=...)``.

        Parameters
        ----------
        smart:
            Authenticated ``SmartConnect`` instance (from SmartAPISession).

        Returns
        -------
        VIXResult
            On success: ``success=True``, ``ltp`` is a float within the
            plausible VIX band, ``raw_response`` is the verbatim ltpData
            response dict.
            On failure: ``success=False``, ``error`` is a sanitised
            description; ``ltp`` is None.
        """
        fetched_at = _utc_now()
        t0 = _monotonic()

        try:
            response: dict[str, object] = smart.ltpData(
                exchange=_EXCHANGE,
                tradingsymbol=_TRADINGSYMBOL,
                symboltoken=_SYMBOLTOKEN,
            )
        except Exception as exc:
            latency_ms = (_monotonic() - t0) * 1000
            error = f"ltpData raised {type(exc).__name__}"
            self._log.error(
                "vix_call_error",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "exc_type": type(exc).__name__,
                },
            )
            return VIXResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=None,
                error=error,
                success=False,
            )

        latency_ms = (_monotonic() - t0) * 1000

        if not isinstance(response, dict):
            error = f"ltpData returned unexpected type: {type(response).__name__}"
            self._log.error(
                "vix_unexpected_response_type",
                extra={"latency_ms": round(latency_ms, 2)},
            )
            return VIXResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=None,
                error=error,
                success=False,
            )

        if not response.get("status"):
            errorcode = str(response.get("errorcode") or "")
            message   = str(response.get("message") or "unknown error")
            error = f"ltpData failed [{errorcode}]: {message}"
            self._log.error(
                "vix_api_error",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "errorcode": errorcode,
                },
            )
            return VIXResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=response,
                error=error,
                success=False,
            )

        raw_data = response.get("data")
        returned_symbol = raw_data.get("tradingsymbol") if isinstance(raw_data, dict) else None

        if returned_symbol is not None and _normalize(str(returned_symbol)) != _EXPECTED_IDENTITY:
            error = (
                f"ltpData returned tradingsymbol={returned_symbol!r}, expected "
                f"India VIX — rejecting result"
            )
            self._log.error(
                "vix_identity_mismatch",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "returned_symbol": str(returned_symbol),
                    "expected_token": _SYMBOLTOKEN,
                },
            )
            return VIXResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=response,
                error=error,
                success=False,
            )

        raw_ltp = raw_data.get("ltp") if isinstance(raw_data, dict) else None
        ltp: float | None = (
            float(raw_ltp)
            if isinstance(raw_ltp, (int, float)) and _VIX_MIN <= raw_ltp <= _VIX_MAX
            else None
        )

        if ltp is None:
            error = (
                f"ltpData returned status=true but ltp={raw_ltp!r} is not a valid "
                f"VIX value (expected numeric in [{_VIX_MIN}, {_VIX_MAX}])"
            )
            self._log.warning(
                "vix_invalid_ltp",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "ltp_raw": str(raw_ltp),
                },
            )
            return VIXResult(
                fetched_at=fetched_at,
                latency_ms=round(latency_ms, 2),
                ltp=None,
                raw_response=response,
                error=error,
                success=False,
            )

        self._log.info(
            "vix_ok",
            extra={"latency_ms": round(latency_ms, 2), "ltp": ltp},
        )
        return VIXResult(
            fetched_at=fetched_at,
            latency_ms=round(latency_ms, 2),
            ltp=ltp,
            raw_response=response,
            error=None,
            success=True,
        )
