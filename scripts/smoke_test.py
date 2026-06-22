#!/usr/bin/env python
"""
scripts/smoke_test.py — BankNifty Observatory SmartAPI Smoke Test

Minimal single-pass verification that SmartAPI can authenticate and return
BankNifty spot and option-chain data. Runs once and exits.

Usage:
    python scripts/smoke_test.py --expiry DDMMMYYYY
    python scripts/smoke_test.py --expiry 26JUN2026 --output-dir data/smoke/custom

Prerequisites:
    pip install smartapi-python pyotp
    .env file with BNO_SMARTAPI_* credentials (see Config Dependencies in design doc)

Exit codes:
    0  PASS — authentication and option-chain both succeeded
    1  FAIL — any blocking check failed (auth or chain)

Output files written to data/smoke/<YYYYMMDD_HHMMSS>/ (one directory per run):
    auth_response.json   — verbatim generateSession() response (contains JWT — do not commit)
    spot_response.json   — verbatim ltpData() response
    chain_response.json  — verbatim getMarketData(mode="FULL") response for BANKNIFTY CE tokens
    smoke_summary.json   — structured summary with latencies and pass/fail verdict
    logs/bno.log         — structured JSON log for this run

Post-run actions (manual):
    1. Inspect chain_response.json to inventory all field names.
    2. Determine spot source: embedded in chain rows or separate call required.
    3. Update tests/fixtures/chain_response_fixture.json if field names differ.
    4. Record latency and byte measurements in the Discovery Report.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.config import BNOConfigError, load_settings
from lib.logging import bootstrap_logging, get_logger

# ── Constants ──────────────────────────────────────────────────────────────────

_BANKNIFTY_SPOT_EXCHANGE = "NSE"
_BANKNIFTY_SPOT_SYMBOL = "NIFTY BANK"
_BANKNIFTY_SPOT_TOKEN = "99926009"
_BANKNIFTY_CHAIN_SYMBOL = "BANKNIFTY"
_CHAIN_OPTION_TYPE = "CE"
_CHAIN_LATENCY_WARN_MS = 4000.0
_SUMMARY_SCHEMA_VERSION = 1


# ── JSON serialisation ─────────────────────────────────────────────────────────

class _JsonEncoder(json.JSONEncoder):
    """Serialises types that SmartAPI responses may contain."""

    def default(self, o: object) -> object:
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Path):
            return str(o)
        return super().default(o)


def _dump(obj: object) -> str:
    return json.dumps(obj, cls=_JsonEncoder, ensure_ascii=False, indent=2)


# ── Persistence ────────────────────────────────────────────────────────────────

def _save_json(path: Path, obj: object, log: logging.Logger) -> None:
    try:
        path.write_text(_dump(obj), encoding="utf-8")
    except OSError as exc:
        log.error("file_write_error", extra={"path": str(path), "error": str(exc)})


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="smoke_test",
        description="BankNifty Observatory — SmartAPI connectivity verification.",
    )
    parser.add_argument(
        "--expiry",
        required=True,
        metavar="DDMMMYYYY",
        help="Nearest active BankNifty weekly expiry, e.g. 26JUN2026",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="PATH",
        help="Override output directory (default: data/smoke/<YYYYMMDD_HHMMSS>)",
    )
    return parser.parse_args()


# ── Output directory ───────────────────────────────────────────────────────────

def _make_output_dir(override: str | None) -> Path:
    if override:
        out = Path(override)
    else:
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = Path("data") / "smoke" / stamp
    out.mkdir(parents=True, exist_ok=True)
    return out


# ── Step 4: Authentication (blocking) ─────────────────────────────────────────

def _step_authenticate(
    settings: Any,
    log: logging.Logger,
) -> tuple[dict[str, object], float, bool, str | None, Any]:
    """Authenticate with SmartAPI using TOTP.

    Returns (raw_response, latency_ms, ok, error_message, smart_instance).
    smart_instance is None on failure.
    Blocking: ok=False causes exit 1 in main().
    Security: JWT token, password, and TOTP code are never logged.
    """
    try:
        from SmartApi import SmartConnect  # type: ignore[import-untyped]
        import pyotp  # type: ignore[import-untyped]
    except ImportError as exc:
        msg = f"Missing dependency: {exc}. Run: pip install smartapi-python pyotp"
        log.error("auth_dependency_missing", extra={"detail": msg})
        return {"error": msg}, 0.0, False, msg, None

    api_key = settings.smartapi_api_key.get_secret_value()
    client_id: str = settings.smartapi_client_id
    password = settings.smartapi_password.get_secret_value()

    if settings.smartapi_totp_secret is None:
        msg = "BNO_SMARTAPI_TOTP_SECRET is None — required for local_seed provider"
        log.error("auth_totp_secret_missing")
        return {"error": msg}, 0.0, False, msg, None
    totp_secret = settings.smartapi_totp_secret.get_secret_value()

    smart = SmartConnect(api_key=api_key)
    totp_code: str = pyotp.TOTP(totp_secret).now()

    t0 = time.monotonic()
    try:
        response: dict[str, object] = smart.generateSession(
            clientCode=client_id,
            password=password,
            totp=totp_code,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        log.error(
            "auth_exception",
            extra={"latency_ms": round(latency_ms, 2), "exc_type": type(exc).__name__},
        )
        return {"error": msg}, latency_ms, False, msg, None

    latency_ms = (time.monotonic() - t0) * 1000

    if not isinstance(response, dict):
        msg = f"generateSession returned unexpected type: {type(response).__name__}"
        log.error("auth_unexpected_response_type", extra={"latency_ms": round(latency_ms, 2)})
        return {"error": msg, "raw": str(response)}, latency_ms, False, msg, None

    raw_data = response.get("data")
    data: dict[str, object] = raw_data if isinstance(raw_data, dict) else {}
    ok = bool(response.get("status")) and "jwtToken" in data
    error: str | None = None

    if ok:
        log.info(
            "auth_ok",
            extra={
                "latency_ms": round(latency_ms, 2),
                "jwt_present": True,
                "refresh_present": "refreshToken" in data,
                "feed_present": "feedToken" in data,
            },
        )
        return response, latency_ms, True, None, smart

    error = (
        f"status={response.get('status')} "
        f"errorcode={response.get('errorcode')!r} "
        f"message={response.get('message')!r}"
    )
    log.error(
        "auth_failed",
        extra={
            "latency_ms": round(latency_ms, 2),
            "errorcode": response.get("errorcode"),
            "message": response.get("message"),
        },
    )
    return response, latency_ms, False, error, None


# ── Step 5: Spot retrieval (non-blocking) ─────────────────────────────────────

def _step_spot(
    smart: Any,
    log: logging.Logger,
) -> tuple[dict[str, object], float, bool, float | None, str | None]:
    """Retrieve BankNifty spot LTP via ltpData().

    Returns (raw_response, latency_ms, ok, ltp, error_message).
    Non-blocking: ok=False records a warning and main() continues to the chain step.
    """
    t0 = time.monotonic()
    try:
        response: dict[str, object] = smart.ltpData(
            exchange=_BANKNIFTY_SPOT_EXCHANGE,
            tradingsymbol=_BANKNIFTY_SPOT_SYMBOL,
            symboltoken=_BANKNIFTY_SPOT_TOKEN,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        log.warning(
            "spot_exception",
            extra={"latency_ms": round(latency_ms, 2), "exc_type": type(exc).__name__},
        )
        return {"error": msg}, latency_ms, False, None, msg

    latency_ms = (time.monotonic() - t0) * 1000

    if not isinstance(response, dict):
        msg = f"ltpData returned unexpected type: {type(response).__name__}"
        log.warning("spot_unexpected_response_type", extra={"latency_ms": round(latency_ms, 2)})
        return {"error": msg, "raw": str(response)}, latency_ms, False, None, msg

    raw_data = response.get("data")
    raw_ltp = raw_data.get("ltp") if isinstance(raw_data, dict) else None
    ltp: float | None = (
        float(raw_ltp) if isinstance(raw_ltp, (int, float)) and raw_ltp != 0 else None
    )
    ok = bool(response.get("status")) and ltp is not None

    if ok:
        log.info(
            "spot_ok",
            extra={
                "latency_ms": round(latency_ms, 2),
                "ltp": ltp,
                "symbol_token": _BANKNIFTY_SPOT_TOKEN,
            },
        )
        return response, latency_ms, True, ltp, None

    error = (
        f"status={response.get('status')} "
        f"ltp={raw_ltp!r} "
        f"errorcode={response.get('errorcode')!r}"
    )
    log.warning(
        "spot_failed",
        extra={
            "latency_ms": round(latency_ms, 2),
            "errorcode": response.get("errorcode"),
            "ltp_raw": raw_ltp,
        },
    )
    return response, latency_ms, False, None, error


# ── Step 6: Option chain retrieval (blocking) ─────────────────────────────────

def _step_chain(
    smart: Any,
    expiry: str,
    log: logging.Logger,
) -> tuple[dict[str, object], float, bool, int, int, int, str | None]:
    """Retrieve BankNifty CE option chain for the given expiry.

    SmartConnect 1.5.5 has no optionChain() method. The correct approach:
      1. searchScrip("NFO", "BANKNIFTY") — discovers instrument tokens
      2. getMarketData(mode="FULL") — fetches market data for those tokens

    SmartAPI symbol format uses a two-digit year: "BANKNIFTY25JUN26C51000".
    The --expiry CLI arg uses four-digit year: "25JUN2026".
    Conversion: expiry[:5] + expiry[7:] → "25JUN26".

    Returns (raw_response, latency_ms, ok, row_count, expiry_count, response_bytes, error).
    Blocking: ok=False causes exit 1 in main().
    """
    # Convert DDMMMYYYY → DDMMMYY (SmartAPI symbol suffix format)
    expiry_2y = expiry[:5] + expiry[7:]  # "25JUN2026" → "25JUN26"

    t0 = time.monotonic()

    # Step 6a: Discover CE token IDs via searchScrip
    try:
        search_result: dict[str, object] = smart.searchScrip(
            exchange="NFO", searchscrip=_BANKNIFTY_CHAIN_SYMBOL
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        msg = f"searchScrip failed: {type(exc).__name__}: {exc}"
        log.error(
            "chain_scrip_search_exception",
            extra={"latency_ms": round(latency_ms, 2), "exc_type": type(exc).__name__},
        )
        return {"error": msg, "phase": "searchScrip"}, latency_ms, False, 0, 0, 0, msg

    scrip_data = search_result.get("data")
    all_scrips: list[object] = scrip_data if isinstance(scrip_data, list) else []

    ce_tokens: list[str] = []
    for item in all_scrips:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("tradingsymbol", ""))
        if expiry_2y.upper() in sym.upper() and _CHAIN_OPTION_TYPE in sym.upper():
            token = str(item.get("symboltoken", ""))
            if token:
                ce_tokens.append(token)

    if not ce_tokens:
        latency_ms = (time.monotonic() - t0) * 1000
        sample = [str(i.get("tradingsymbol", "")) for i in all_scrips[:8] if isinstance(i, dict)]
        msg = (
            f"No BANKNIFTY CE tokens found for expiry={expiry} (searched as {expiry_2y}). "
            f"searchScrip returned {len(all_scrips)} instruments. "
            f"Verify expiry date and DDMMMYYYY format."
        )
        log.error(
            "chain_no_tokens",
            extra={
                "expiry_arg": expiry,
                "expiry_2y": expiry_2y,
                "scrip_count": len(all_scrips),
                "sample_symbols": sample,
            },
        )
        return {
            "error": msg,
            "searchScrip_status": search_result.get("status"),
            "searchScrip_sample": all_scrips[:10],
        }, latency_ms, False, 0, 0, 0, msg

    log.info(
        "chain_tokens_found",
        extra={"ce_token_count": len(ce_tokens), "expiry_2y": expiry_2y},
    )

    # Step 6b: Fetch full market data — batched (SmartAPI limit: 50 tokens/call).
    # A monthly expiry produces 400+ CE tokens; sending all at once returns AB4029.
    _BATCH_SIZE = 50
    batches = [ce_tokens[i : i + _BATCH_SIZE] for i in range(0, len(ce_tokens), _BATCH_SIZE)]
    batch_count = len(batches)
    all_fetched: list[object] = []
    all_unfetched: list[object] = []
    total_bytes = 0

    for batch_idx, batch in enumerate(batches):
        try:
            batch_resp: dict[str, object] = smart.getMarketData(
                mode="FULL",
                exchangeTokens={"NFO": batch},
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            msg = (
                f"getMarketData failed: {type(exc).__name__}: {exc} "
                f"(batch {batch_idx + 1}/{batch_count})"
            )
            log.error(
                "chain_market_data_exception",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "exc_type": type(exc).__name__,
                    "batch_idx": batch_idx,
                    "batch_count": batch_count,
                },
            )
            return {"error": msg, "phase": "getMarketData"}, latency_ms, False, 0, 0, 0, msg

        if not isinstance(batch_resp, dict):
            latency_ms = (time.monotonic() - t0) * 1000
            msg = f"getMarketData returned unexpected type: {type(batch_resp).__name__}"
            log.error("chain_unexpected_response_type", extra={"latency_ms": round(latency_ms, 2)})
            return {"error": msg, "raw": str(batch_resp)}, latency_ms, False, 0, 0, 0, msg

        if not batch_resp.get("status"):
            latency_ms = (time.monotonic() - t0) * 1000
            total_bytes += len(_dump(batch_resp).encode("utf-8"))
            msg = (
                f"status={batch_resp.get('status')} "
                f"errorcode={batch_resp.get('errorcode')!r} "
                f"message={batch_resp.get('message')!r} "
                f"(batch {batch_idx + 1}/{batch_count})"
            )
            log.error(
                "chain_api_error",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "errorcode": batch_resp.get("errorcode"),
                    "batch_idx": batch_idx,
                    "batch_count": batch_count,
                },
            )
            return batch_resp, latency_ms, False, 0, 0, total_bytes, msg

        total_bytes += len(_dump(batch_resp).encode("utf-8"))
        raw_data = batch_resp.get("data")
        if isinstance(raw_data, dict):
            rows = raw_data.get("fetched")
            if isinstance(rows, list):
                all_fetched.extend(rows)
            uf = raw_data.get("unfetched")
            if isinstance(uf, list):
                all_unfetched.extend(uf)
        elif isinstance(raw_data, list):
            all_fetched.extend(raw_data)

    latency_ms = (time.monotonic() - t0) * 1000
    response_bytes = total_bytes

    # Synthesise a merged response (same schema as a single successful call)
    # so chain_response.json has a consistent, inspectable layout.
    response: dict[str, object] = {
        "status": True,
        "message": "SUCCESS",
        "errorcode": "",
        "data": {
            "fetched":   all_fetched,
            "unfetched": all_unfetched,
        },
    }
    fetched = all_fetched
    row_count = len(fetched)

    expiry_dates: set[str] = set()
    for row in fetched:
        if isinstance(row, dict):
            for key in ("expiryDate", "expiry", "ExpiryDate"):
                val = row.get(key)
                if isinstance(val, str):
                    expiry_dates.add(val)
                    break
    expiry_count = len(expiry_dates)

    ok = bool(response.get("status")) and row_count > 0

    if ok:
        if latency_ms > _CHAIN_LATENCY_WARN_MS:
            log.warning(
                "chain_latency_high",
                extra={
                    "latency_ms": round(latency_ms, 2),
                    "threshold_ms": _CHAIN_LATENCY_WARN_MS,
                    "note": "p95 above 4000ms may violate 5-second polling budget",
                },
            )
        log.info(
            "chain_ok",
            extra={
                "latency_ms": round(latency_ms, 2),
                "row_count": row_count,
                "expiry_count": expiry_count,
                "response_bytes": response_bytes,
                "expiry_arg": expiry,
            },
        )
        return response, latency_ms, True, row_count, expiry_count, response_bytes, None

    error = (
        f"status={response.get('status')} "
        f"row_count={row_count} "
        f"errorcode={response.get('errorcode')!r} "
        f"message={response.get('message')!r}"
    )
    log.error(
        "chain_failed",
        extra={
            "latency_ms": round(latency_ms, 2),
            "row_count": row_count,
            "errorcode": response.get("errorcode"),
            "expiry_arg": expiry,
        },
    )
    return response, latency_ms, False, row_count, expiry_count, response_bytes, error


# ── Summary construction ───────────────────────────────────────────────────────

def _build_summary(
    *,
    run_at: datetime,
    expiry_arg: str,
    output_dir: Path,
    auth_ok: bool,
    auth_latency_ms: float,
    auth_error: str | None,
    auth_data: dict[str, object],
    spot_ok: bool,
    spot_latency_ms: float,
    spot_ltp: float | None,
    spot_error: str | None,
    chain_ok: bool,
    chain_latency_ms: float,
    chain_row_count: int,
    chain_expiry_count: int,
    chain_response_bytes: int,
    chain_error: str | None,
) -> dict[str, object]:
    blocking: list[str] = []
    if not auth_ok:
        blocking.append(f"auth_failed: {auth_error}")
    if not chain_ok:
        blocking.append(f"chain_failed: {chain_error}")

    return {
        "schema_version": _SUMMARY_SCHEMA_VERSION,
        "run_at_utc": run_at.isoformat(),
        "expiry_arg": expiry_arg,
        "output_dir": str(output_dir),
        "auth": {
            "ok": auth_ok,
            "latency_ms": round(auth_latency_ms, 2),
            "jwt_present": "jwtToken" in auth_data,
            "refresh_present": "refreshToken" in auth_data,
            "feed_present": "feedToken" in auth_data,
            "error": auth_error,
        },
        "spot": {
            "ok": spot_ok,
            "latency_ms": round(spot_latency_ms, 2),
            "ltp": spot_ltp,
            "error": spot_error,
        },
        "chain": {
            "ok": chain_ok,
            "latency_ms": round(chain_latency_ms, 2),
            "row_count": chain_row_count,
            "expiry_count": chain_expiry_count,
            "response_bytes": chain_response_bytes,
            "error": chain_error,
        },
        "verdict": "PASS" if (auth_ok and chain_ok) else "FAIL",
        "blocking_issues": blocking,
        "files": {
            "auth_response": "auth_response.json",
            "spot_response": "spot_response.json",
            "chain_response": "chain_response.json",
        },
    }


# ── Console output ─────────────────────────────────────────────────────────────

def _print_summary(summary: dict[str, object], output_dir: Path) -> None:
    verdict = summary.get("verdict", "FAIL")
    bar = "=" * 60
    auth = summary.get("auth", {})
    spot = summary.get("spot", {})
    chain = summary.get("chain", {})

    print(bar)
    print("  BankNifty Observatory — SmartAPI Smoke Test")
    print(f"  Verdict : {verdict}")
    print(bar)
    print(
        f"  Auth    : {'PASS' if auth.get('ok') else 'FAIL'}"
        f"  ({auth.get('latency_ms', 0):.1f} ms)"
    )
    if auth.get("error"):
        print(f"            {auth['error']}")
    print(
        f"  Spot    : {'PASS' if spot.get('ok') else 'WARN'}"
        f"  ({spot.get('latency_ms', 0):.1f} ms)"
        f"  ltp={spot.get('ltp')}"
    )
    if spot.get("error"):
        print(f"            {spot['error']}")
    print(
        f"  Chain   : {'PASS' if chain.get('ok') else 'FAIL'}"
        f"  ({chain.get('latency_ms', 0):.1f} ms)"
        f"  rows={chain.get('row_count', 0)}"
        f"  bytes={chain.get('response_bytes', 0)}"
    )
    if chain.get("error"):
        print(f"            {chain['error']}")

    issues = summary.get("blocking_issues", [])
    if issues:
        print()
        print("  Blocking issues:")
        for issue in issues:
            print(f"    - {issue}")

    print(bar)
    print(f"  Output  : {output_dir}")
    print(bar)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()
    run_at = datetime.now(tz=timezone.utc)

    # Step 1: Load config — all credentials come from lib/config, never os.environ directly.
    try:
        settings = load_settings(env_file=".env")
    except BNOConfigError as exc:
        print(f"[FATAL] Config validation failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"[FATAL] Unexpected config error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    # Step 3: Create output directory before step 2 so log_dir can live inside it.
    try:
        output_dir = _make_output_dir(args.output_dir)
    except OSError as exc:
        print(f"[FATAL] Cannot create output directory: {exc}", file=sys.stderr)
        return 1

    # Step 2: Initialize logging — SecretScrubberFilter is registered here.
    # All subsequent log records are scrubbed before hitting the file handler.
    run_id: str
    try:
        run_id = bootstrap_logging(
            settings=settings,
            log_dir=str(output_dir / "logs"),
        )
    except Exception as exc:
        print(
            f"[WARNING] Logging init failed ({type(exc).__name__}: {exc}); continuing",
            file=sys.stderr,
        )
        run_id = "unavailable"

    log = get_logger("smoke_test")
    log.info(
        "smoke_test_start",
        extra={
            "run_id": run_id,
            "expiry_arg": args.expiry,
            "output_dir": str(output_dir),
        },
    )

    # Step 4: Authenticate — blocking.
    auth_response, auth_latency_ms, auth_ok, auth_error, smart = _step_authenticate(
        settings, log
    )
    _save_json(output_dir / "auth_response.json", auth_response, log)

    raw_auth_data = auth_response.get("data")
    auth_data: dict[str, object] = raw_auth_data if isinstance(raw_auth_data, dict) else {}

    if not auth_ok:
        summary = _build_summary(
            run_at=run_at,
            expiry_arg=args.expiry,
            output_dir=output_dir,
            auth_ok=False,
            auth_latency_ms=auth_latency_ms,
            auth_error=auth_error,
            auth_data=auth_data,
            spot_ok=False,
            spot_latency_ms=0.0,
            spot_ltp=None,
            spot_error="skipped: auth failed",
            chain_ok=False,
            chain_latency_ms=0.0,
            chain_row_count=0,
            chain_expiry_count=0,
            chain_response_bytes=0,
            chain_error="skipped: auth failed",
        )
        _save_json(output_dir / "smoke_summary.json", summary, log)
        _print_summary(summary, output_dir)
        log.error("smoke_test_end", extra={"verdict": "FAIL"})
        return 1

    # Step 5: Retrieve spot — non-blocking.
    spot_response, spot_latency_ms, spot_ok, spot_ltp, spot_error = _step_spot(smart, log)
    _save_json(output_dir / "spot_response.json", spot_response, log)

    # Step 6: Retrieve option chain — blocking.
    (
        chain_response,
        chain_latency_ms,
        chain_ok,
        chain_row_count,
        chain_expiry_count,
        chain_response_bytes,
        chain_error,
    ) = _step_chain(smart, args.expiry, log)
    _save_json(output_dir / "chain_response.json", chain_response, log)

    # Step 7: Write summary and exit.
    summary = _build_summary(
        run_at=run_at,
        expiry_arg=args.expiry,
        output_dir=output_dir,
        auth_ok=auth_ok,
        auth_latency_ms=auth_latency_ms,
        auth_error=auth_error,
        auth_data=auth_data,
        spot_ok=spot_ok,
        spot_latency_ms=spot_latency_ms,
        spot_ltp=spot_ltp,
        spot_error=spot_error,
        chain_ok=chain_ok,
        chain_latency_ms=chain_latency_ms,
        chain_row_count=chain_row_count,
        chain_expiry_count=chain_expiry_count,
        chain_response_bytes=chain_response_bytes,
        chain_error=chain_error,
    )
    _save_json(output_dir / "smoke_summary.json", summary, log)
    _print_summary(summary, output_dir)

    verdict = "PASS" if (auth_ok and chain_ok) else "FAIL"
    log.info("smoke_test_end", extra={"verdict": verdict})

    return 0 if (auth_ok and chain_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
