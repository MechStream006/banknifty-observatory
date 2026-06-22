from __future__ import annotations

import io
import logging
import traceback

from lib.logging._constants import SCRUB_PLACEHOLDER


class SecretScrubberFilter(logging.Filter):
    """
    Logging filter that redacts registered secret values before any handler
    writes the record. Must be attached to each Handler (not the Logger) to
    guarantee coverage regardless of which logger hierarchy emits the record.

    Covers three output paths:
      - The rendered log message (record.msg after %-interpolation)
      - The formatted exception traceback (stored as record.exc_text)
      - Any pre-set record.exc_text from a prior call
    """

    def __init__(self, secrets: frozenset[str]) -> None:
        super().__init__()
        # Exclude empty strings — replacing "" everywhere would corrupt output.
        self._secrets: frozenset[str] = frozenset(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)

        record.msg = self._scrub(msg)
        record.args = None

        if record.exc_info and record.exc_info[0] is not None and not record.exc_text:
            buf = io.StringIO()
            traceback.print_exception(*record.exc_info, file=buf)
            record.exc_text = self._scrub(buf.getvalue().rstrip())
        elif record.exc_text:
            record.exc_text = self._scrub(record.exc_text)

        return True

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, SCRUB_PLACEHOLDER)
        return text
