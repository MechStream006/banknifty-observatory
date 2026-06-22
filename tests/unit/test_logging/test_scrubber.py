"""Tests for SecretScrubberFilter: secrets must never appear in log output."""
from __future__ import annotations

import logging
import sys

import pytest

from lib.logging._constants import SCRUB_PLACEHOLDER
from lib.logging._scrubber import SecretScrubberFilter

_SECRETS = frozenset(["super_secret_password", "api_key_12345", "totp_seed_abc"])


@pytest.fixture
def scrubber() -> SecretScrubberFilter:
    return SecretScrubberFilter(_SECRETS)


def _make_record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="bno.test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )


class TestMessageScrubbing:
    def test_secret_in_format_arg_is_replaced(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("password is %s", "super_secret_password")
        scrubber.filter(record)
        assert "super_secret_password" not in record.msg
        assert SCRUB_PLACEHOLDER in record.msg

    def test_secret_inline_in_message_is_replaced(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("connecting with key=super_secret_password")
        scrubber.filter(record)
        assert "super_secret_password" not in record.msg
        assert SCRUB_PLACEHOLDER in record.msg

    def test_multiple_secrets_in_one_message(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("key=%s token=%s", "api_key_12345", "totp_seed_abc")
        scrubber.filter(record)
        assert "api_key_12345" not in record.msg
        assert "totp_seed_abc" not in record.msg

    def test_non_secret_text_preserved(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("Session started for instrument BANKNIFTY")
        scrubber.filter(record)
        assert "BANKNIFTY" in record.msg
        assert "Session started" in record.msg

    def test_args_cleared_after_filter(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("val=%s", "not_a_secret")
        scrubber.filter(record)
        assert record.args is None

    def test_filter_always_returns_true(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("some message")
        assert scrubber.filter(record) is True

    def test_empty_secret_not_used_for_scrubbing(self) -> None:
        scrubber_with_empty = SecretScrubberFilter(frozenset(["", "real_secret"]))
        record = _make_record("hello world real_secret")
        scrubber_with_empty.filter(record)
        assert "real_secret" not in record.msg
        assert record.msg == f"hello world {SCRUB_PLACEHOLDER}"


class TestExceptionScrubbing:
    def test_preexisting_exc_text_is_scrubbed(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("error occurred")
        record.exc_text = "ValueError: bad value super_secret_password"
        scrubber.filter(record)
        assert "super_secret_password" not in record.exc_text
        assert SCRUB_PLACEHOLDER in record.exc_text

    def test_exc_info_rendered_and_scrubbed(self, scrubber: SecretScrubberFilter) -> None:
        try:
            raise ValueError("contains super_secret_password in traceback")
        except ValueError:
            exc_info = sys.exc_info()

        record = _make_record("something failed")
        record.exc_info = exc_info
        scrubber.filter(record)
        assert record.exc_text is not None
        assert "super_secret_password" not in record.exc_text
        assert SCRUB_PLACEHOLDER in record.exc_text

    def test_no_exc_leaves_exc_text_none(self, scrubber: SecretScrubberFilter) -> None:
        record = _make_record("normal message")
        scrubber.filter(record)
        assert record.exc_text is None
