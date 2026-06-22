"""
VIXFetcher — India VIX LTP retrieval via SmartAPI.

Issues a single ``ltpData()`` call for the India VIX index (NSE:1333) and
packages the result into a ``VIXResult``.

Design constraints (matching SpotFetcher):
- fetch() ALWAYS returns VIXResult — it never raises.
- Exception messages are NOT propagated; only the exception type name is
  recorded in VIXResult.error.  This prevents internal details from
  leaking into logs or persisted records.
- A VIX LTP of zero is treated as invalid: the exchange should never
  publish a non-positive index value during market hours.
- raw_response is set to the verbatim API dict on all code paths that
  reach a dict response (including status=False responses); None only
  when the SDK raises or returns a non-dict value.
- latency_ms covers the full ltpData() round trip, rounded to 2 dp.
- fetched_at is the UTC wall-clock instant before the API call.

Live SmartAPI parameters (India VIX):
    exchange      = "NSE"
    tradingsymbol = "India VIX"
    symboltoken   = "1333"
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
_SYMBOL   = "India VIX"
_TOKEN    = "1333"


# ── Mockable helpers ─────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _monotonic() -> float:
    return time.monotonic()


# ── VIXFetcher ────────────────────────────────────────────────────────────────────


class VIXFetcher:
    """India VIX LTP retrieval via a single ltpData() call.

    No constructor parameters — the exchange, symbol, and token are fixed
    (NSE:India VIX:1333) and do not vary between deployments.

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

    def fetch(self, smart: SmartConnect) -> VIXResult:
        """Retrieve the India VIX LTP.

        Always returns a ``VIXResult`` — never raises.  Any error from the
        SmartAPI SDK or a failed API status is captured in
        ``VIXResult(success=False, error=...)``.

        Parameters
        ----------
        smart:
            Authenticated ``SmartConnect`` instance (from SmartAPISession).

        Returns
        -------
        VIXResult
            On success: ``success=True``, ``ltp`` is a positive float,
            ``raw_response`` is the verbatim API response dict.
            On failure: ``success=False``, ``error`` is a sanitised
            description; ``ltp`` is None.
        """
        fetched_at = _utc_now()
        t0 = _monotonic()

        try:
            response: dict[str, object] = smart.ltpData(
                exchange=_EXCHANGE,
                tradingsymbol=_SYMBOL,
                symboltoken=_TOKEN,
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
        raw_ltp  = raw_data.get("ltp") if isinstance(raw_data, dict) else None
        ltp: float | None = (
            float(raw_ltp)
            if isinstance(raw_ltp, (int, float)) and raw_ltp > 0
            else None
        )

        if ltp is None:
            error = f"ltpData returned status=true but ltp={raw_ltp!r} is not a valid VIX value"
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
