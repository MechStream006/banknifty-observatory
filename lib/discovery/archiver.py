"""
JSONLArchiver — append-only JSONL persistence for discovery poll records.

Writes one JSON line per record to a dated file::

    {output_dir}/{YYYYMMDD}.jsonl

Rotates to a new file automatically on the first write after midnight.
All write errors propagate as ArchiverError — never swallowed silently,
so the controller can decide whether to abort the phase.

The module-level ``_today`` helper is a thin wrapper around
``date.today()`` so that tests can patch it for rotation scenarios.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import IO, Any

from lib.discovery._errors import ArchiverError


# ── Mockable helper ────────────────────────────────────────────────────────────


def _today() -> date:
    return date.today()


# ── JSON serialisation ─────────────────────────────────────────────────────────


def _json_default(obj: object) -> str:
    """Fallback serialiser: datetimes/dates → ISO 8601, Path → str, others → str."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


# ── JSONLArchiver ──────────────────────────────────────────────────────────────


class JSONLArchiver:
    """Append-only JSONL archiver with automatic daily file rotation.

    Parameters
    ----------
    output_dir:
        Directory where dated JSONL files are written. Created automatically
        (including parents) if it does not exist.

    Use as a context manager for automatic open/close::

        with JSONLArchiver(output_dir=data_dir / "raw") as archiver:
            archiver.write(poll_record_dict)

    Or call ``open()`` and ``close()`` explicitly for long-lived instances.

    Thread safety
    -------------
    Not thread-safe. Designed for single-threaded use by the controller.
    """

    def __init__(self, output_dir: Path | str) -> None:
        self._output_dir = Path(output_dir)
        self._file: IO[str] | None = None
        self._current_date: date | None = None
        self._line_count: int = 0
        self._byte_count: int = 0

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def line_count(self) -> int:
        """Total lines written across all rotation files in this session."""
        return self._line_count

    @property
    def byte_count(self) -> int:
        """Total UTF-8 bytes written across all rotation files in this session."""
        return self._byte_count

    @property
    def current_file_path(self) -> Path | None:
        """Absolute path of the currently open JSONL file, or None if closed."""
        if self._current_date is None:
            return None
        return self._output_dir / f"{self._current_date:%Y%m%d}.jsonl"

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    def open(self) -> None:
        """Open the archiver for writing, creating *output_dir* if absent.

        Idempotent: calling ``open()`` when already open is a no-op.

        Raises
        ------
        ArchiverError
            If the output directory cannot be created or the file cannot
            be opened for appending.
        """
        if self._file is not None:
            return
        self._rotate()

    def close(self) -> None:
        """Flush and close the current JSONL file. Idempotent."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> JSONLArchiver:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

    # ── Write ───────────────────────────────────────────────────────────────────

    def write(self, record: dict[str, Any]) -> None:
        """Serialise *record* as a JSON line and append it to the active file.

        Rotates the output file if the calendar date has changed since
        the last write (midnight boundary).

        Parameters
        ----------
        record:
            A JSON-serialisable dict. Datetime and Path values are coerced
            to strings via ``_json_default``.

        Raises
        ------
        ArchiverError
            If the archiver is not open, the record contains a circular
            reference, or a filesystem write fails.
        """
        if self._file is None:
            raise ArchiverError(
                "JSONLArchiver is not open — call open() or use as context manager."
            )

        today = _today()
        if today != self._current_date:
            self._rotate()

        try:
            line = json.dumps(record, default=_json_default)
        except (TypeError, ValueError) as exc:
            raise ArchiverError(f"Record is not JSON-serialisable: {exc}") from exc

        payload = line + "\n"
        encoded_len = len(payload.encode("utf-8"))

        try:
            self._file.write(payload)
            self._file.flush()
        except OSError as exc:
            raise ArchiverError(f"Write failed: {exc}") from exc

        self._line_count += 1
        self._byte_count += encoded_len

    # ── Internal ────────────────────────────────────────────────────────────────

    def _rotate(self) -> None:
        """Close the current file (if any) and open a new one for today."""
        if self._file is not None:
            self._file.close()
            self._file = None

        today = _today()
        self._current_date = today
        self._output_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._output_dir / f"{today:%Y%m%d}.jsonl"

        try:
            # newline="\n" ensures Unix line endings on all platforms,
            # keeping byte counts consistent with len(payload.encode("utf-8")).
            self._file = open(file_path, "a", encoding="utf-8", newline="\n")  # noqa: SIM115
        except OSError as exc:
            raise ArchiverError(f"Cannot open {file_path}: {exc}") from exc
