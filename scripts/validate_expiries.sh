#!/usr/bin/env bash
# Pre-flight expiry validation.
# Called via ExecStartPre= in the systemd service unit before each session.
# Fails hard (exit 1) if any configured expiry in BNO_CHAIN_EXPIRIES has
# already passed, preventing a session that would collect stale or empty chains.
#
# Environment variables are injected by systemd from EnvironmentFile= before
# this script runs — no need to source the env file manually.
set -euo pipefail

if [[ -z "${BNO_CHAIN_EXPIRIES:-}" ]]; then
    echo "ABORT: BNO_CHAIN_EXPIRIES is not set." >&2
    echo "Update /etc/banknifty-observatory/discovery.env (every Thursday evening)." >&2
    exit 1
fi

/home/bno/.venv/bin/python3 - <<'PYEOF'
import os
import sys
from datetime import datetime, timezone

expiries_raw = os.environ.get("BNO_CHAIN_EXPIRIES", "")
today = datetime.now(timezone.utc).date()
errors = []

for raw in expiries_raw.split(","):
    exp = raw.strip().upper()
    if not exp:
        continue
    try:
        exp_date = datetime.strptime(exp, "%d%b%Y").date()
    except ValueError:
        errors.append(f"Cannot parse '{exp}' — expected DDMMMYYYY (e.g. 26JUN2026)")
        continue
    if exp_date < today:
        errors.append(f"Expiry {exp} ({exp_date.isoformat()}) has already passed.")

if errors:
    for e in errors:
        print(f"ABORT: {e}", file=sys.stderr)
    print(
        "Update BNO_CHAIN_EXPIRIES in /etc/banknifty-observatory/discovery.env.",
        file=sys.stderr,
    )
    sys.exit(1)

print(f"Expiry validation OK: {expiries_raw}")
PYEOF
