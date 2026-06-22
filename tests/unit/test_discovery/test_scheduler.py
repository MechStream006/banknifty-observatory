"""Tests for lib.discovery.scheduler: is_market_open and PollScheduler."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from lib.discovery.scheduler import (
    PollScheduler,
    _market_closed_for_day,
    is_market_open,
)

_IST = timezone(timedelta(hours=5, minutes=30))
_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
# Reference schedule: 2026-06-22 is Monday, 2026-06-27 is Saturday,
# 2026-06-28 is Sunday.


def _ist(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    """UTC datetime equivalent to the given IST wall-clock time."""
    return datetime(year, month, day, hour, minute, second, tzinfo=_IST)


_MON_OPEN = _ist(2026, 6, 22, 12, 0)    # Monday 12:00 IST — mid-session
_MON_PRE  = _ist(2026, 6, 22, 9, 0)     # Monday 09:00 IST — before open
_MON_POST = _ist(2026, 6, 22, 16, 0)    # Monday 16:00 IST — after close
_FRI_OPEN = _ist(2026, 6, 26, 12, 0)    # Friday  12:00 IST — open
_SAT_NOON = _ist(2026, 6, 27, 12, 0)    # Saturday noon  — weekend
_SUN_NOON = _ist(2026, 6, 28, 12, 0)    # Sunday noon    — weekend


# ===========================================================================
# is_market_open
# ===========================================================================


class TestIsMarketOpen:
    def test_true_during_trading_hours(self) -> None:
        assert is_market_open(_MON_OPEN) is True

    def test_true_at_open_boundary(self) -> None:
        # 09:15:00 IST — inclusive lower bound
        assert is_market_open(_ist(2026, 6, 22, 9, 15, 0)) is True

    def test_false_one_minute_before_open(self) -> None:
        assert is_market_open(_ist(2026, 6, 22, 9, 14, 59)) is False

    def test_false_at_close_boundary(self) -> None:
        # 15:30:00 IST — exclusive upper bound; market is closed at this exact minute
        assert is_market_open(_ist(2026, 6, 22, 15, 30, 0)) is False

    def test_true_one_minute_before_close(self) -> None:
        # 15:29:59 IST — last minute is open
        assert is_market_open(_ist(2026, 6, 22, 15, 29, 59)) is True

    def test_false_before_open(self) -> None:
        assert is_market_open(_MON_PRE) is False

    def test_false_after_close(self) -> None:
        assert is_market_open(_MON_POST) is False

    def test_false_saturday(self) -> None:
        assert is_market_open(_SAT_NOON) is False

    def test_false_sunday(self) -> None:
        assert is_market_open(_SUN_NOON) is False

    def test_true_on_friday(self) -> None:
        assert is_market_open(_FRI_OPEN) is True

    def test_accepts_utc_datetime(self) -> None:
        # 12:00 IST = 06:30 UTC; should be open on a Monday
        utc_dt = datetime(2026, 6, 22, 6, 30, 0, tzinfo=_UTC)
        assert is_market_open(utc_dt) is True


# ===========================================================================
# _market_closed_for_day
# ===========================================================================


class TestMarketClosedForDay:
    def test_false_before_open_on_weekday(self) -> None:
        assert _market_closed_for_day(_MON_PRE) is False

    def test_false_during_market_hours(self) -> None:
        assert _market_closed_for_day(_MON_OPEN) is False

    def test_true_after_close_on_weekday(self) -> None:
        assert _market_closed_for_day(_MON_POST) is True

    def test_true_at_close_time(self) -> None:
        assert _market_closed_for_day(_ist(2026, 6, 22, 15, 30)) is True

    def test_true_saturday(self) -> None:
        assert _market_closed_for_day(_SAT_NOON) is True

    def test_true_sunday(self) -> None:
        assert _market_closed_for_day(_SUN_NOON) is True


# ===========================================================================
# PollScheduler — construction
# ===========================================================================


class TestPollSchedulerInit:
    def test_positive_interval_accepted(self) -> None:
        s = PollScheduler(interval_seconds=5)
        assert s.interval_seconds == 5

    def test_zero_interval_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            PollScheduler(interval_seconds=0)

    def test_negative_interval_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            PollScheduler(interval_seconds=-1)


# ===========================================================================
# PollScheduler.ticks()
# ===========================================================================


class TestPollSchedulerTicks:
    """Drive ticks() with controlled time helpers to avoid real sleeps."""

    def _run(
        self,
        now_sequence: list[datetime],
        monotonic_sequence: list[float],
        interval: int = 5,
    ) -> tuple[list[datetime], list[float]]:
        """Exhaust ticks() under mocked time; return (yielded_dts, sleep_durations)."""
        yielded: list[datetime] = []
        sleep_calls: list[float] = []

        with (
            patch("lib.discovery.scheduler._utc_now", side_effect=now_sequence),
            patch("lib.discovery.scheduler._monotonic", side_effect=monotonic_sequence),
            patch(
                "lib.discovery.scheduler._sleep",
                side_effect=lambda s: sleep_calls.append(s),
            ),
        ):
            scheduler = PollScheduler(interval_seconds=interval)
            for tick in scheduler.ticks():
                yielded.append(tick)

        return yielded, sleep_calls

    # -- basic yield / stop behaviour ------------------------------------------

    def test_yields_tick_during_market_hours(self) -> None:
        open_dt = _MON_OPEN.astimezone(_UTC)
        post_dt = _MON_POST.astimezone(_UTC)
        yielded, _ = self._run([open_dt, post_dt], [100.0, 103.0])
        assert len(yielded) == 1
        assert yielded[0] == open_dt

    def test_tick_value_is_utc_datetime(self) -> None:
        open_dt = _MON_OPEN.astimezone(_UTC)
        post_dt = _MON_POST.astimezone(_UTC)
        yielded, _ = self._run([open_dt, post_dt], [100.0, 102.0])
        assert yielded[0].tzinfo is _UTC

    def test_yields_nothing_when_already_closed(self) -> None:
        post_dt = _MON_POST.astimezone(_UTC)
        yielded, sleep_calls = self._run([post_dt], [])
        assert yielded == []
        assert sleep_calls == []

    def test_yields_nothing_on_saturday(self) -> None:
        sat_dt = _SAT_NOON.astimezone(_UTC)
        yielded, sleep_calls = self._run([sat_dt], [])
        assert yielded == []
        assert sleep_calls == []

    def test_yields_nothing_on_sunday(self) -> None:
        sun_dt = _SUN_NOON.astimezone(_UTC)
        yielded, sleep_calls = self._run([sun_dt], [])
        assert yielded == []
        assert sleep_calls == []

    # -- pre-market wait -------------------------------------------------------

    def test_waits_before_market_open_then_yields(self) -> None:
        pre_dt  = _MON_PRE.astimezone(_UTC)
        open_dt = _MON_OPEN.astimezone(_UTC)
        post_dt = _MON_POST.astimezone(_UTC)
        yielded, sleep_calls = self._run(
            [pre_dt, pre_dt, open_dt, post_dt],
            [100.0, 103.0],
        )
        assert len(yielded) == 1
        assert yielded[0] == open_dt
        # First two sleeps are 1 s waits; third is drift compensation (5-3=2 s)
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 1.0
        assert sleep_calls[2] == 2.0

    # -- drift compensation ----------------------------------------------------

    def test_sleeps_remainder_of_interval(self) -> None:
        # 3 s elapsed, 5 s interval → sleep 2 s
        open_dt = _MON_OPEN.astimezone(_UTC)
        post_dt = _MON_POST.astimezone(_UTC)
        _, sleep_calls = self._run([open_dt, post_dt], [100.0, 103.0])
        assert sleep_calls == [2.0]

    def test_no_sleep_when_elapsed_exceeds_interval(self) -> None:
        # 6 s elapsed > 5 s interval → sleep omitted entirely
        open_dt = _MON_OPEN.astimezone(_UTC)
        post_dt = _MON_POST.astimezone(_UTC)
        _, sleep_calls = self._run([open_dt, post_dt], [100.0, 106.0])
        assert sleep_calls == []

    def test_no_sleep_when_elapsed_equals_interval(self) -> None:
        # Exactly 5 s elapsed → sleep 0 → omitted
        open_dt = _MON_OPEN.astimezone(_UTC)
        post_dt = _MON_POST.astimezone(_UTC)
        _, sleep_calls = self._run([open_dt, post_dt], [100.0, 105.0])
        assert sleep_calls == []

    # -- multi-tick sequences --------------------------------------------------

    def test_three_consecutive_ticks(self) -> None:
        open1 = _ist(2026, 6, 22, 12, 0).astimezone(_UTC)
        open2 = _ist(2026, 6, 22, 12, 1).astimezone(_UTC)
        open3 = _ist(2026, 6, 22, 12, 2).astimezone(_UTC)
        post  = _MON_POST.astimezone(_UTC)
        yielded, sleep_calls = self._run(
            [open1, open2, open3, post],
            # Tick 1: t0=100, elapsed=103 → 3 s → sleep 2
            # Tick 2: t0=200, elapsed=204 → 4 s → sleep 1
            # Tick 3: t0=300, elapsed=302 → 2 s → sleep 3
            [100.0, 103.0, 200.0, 204.0, 300.0, 302.0],
        )
        assert yielded == [open1, open2, open3]
        assert sleep_calls == [2.0, 1.0, 3.0]

    def test_stops_immediately_after_last_valid_tick(self) -> None:
        # Second call to _utc_now sees post-close time → generator returns
        open_dt = _ist(2026, 6, 22, 15, 29).astimezone(_UTC)
        post_dt = _ist(2026, 6, 22, 15, 31).astimezone(_UTC)
        yielded, _ = self._run([open_dt, post_dt], [100.0, 100.5])
        assert len(yielded) == 1
