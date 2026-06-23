#!/usr/bin/env bash
# Pre-flight disk space check.
# Called via ExecStartPre= in the systemd service unit before each session.
# Fails hard (exit 1) if less than 2 GB is free on the data directory,
# preventing a session that would run but write nothing.
set -euo pipefail

DATA_DIR="${BNO_DATA_DIR:-/srv/bno/data}"
THRESHOLD_KB=2097152  # 2 GB in kibibytes

avail=$(df --output=avail "$DATA_DIR" | tail -1)

if [[ "$avail" -le "$THRESHOLD_KB" ]]; then
    echo "ABORT: less than 2 GB free on ${DATA_DIR} (${avail} kB available)." >&2
    echo "Free disk space before starting the market session." >&2
    exit 1
fi

echo "Disk check OK: ${avail} kB free on ${DATA_DIR}"
