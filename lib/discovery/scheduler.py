"""
PollScheduler — drift-compensated, market-hours-aware poll scheduler.

Yields one UTC datetime tick per interval during NSE equity derivative
trading hours: [09:15, 15:30) IST, Monday through Friday.

Drift compensation: each tick measures actual elapsed time in the caller
and sleeps ``max(0, interval_seconds - elapsed)`` so that wall-clock
drift does not accumulate across long collection sessions.

The three module-level helpers (_utc_now, _monotonic, _sleep) are
thin wrappers around stdlib functions so that tests can patch them
without touching the stdlib modules themselves.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

_IST = timezone(timedelta(hours=5, minutes=30))
_OPEN_MINUTES: int = 9 * 60 + 15    # 555 — 09:15 IST
_CLOSE_MINUTES: int = 15 * 60 + 30  # 930 — 15:30 IST


# ── Mockable time helpers ──────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _monotonic() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


# ── Public market-hours helpers ────────────────────────────────────────────────


def is_market_open(dt: datetime) -> bool:
    """Return True if *dt* falls within NSE F&O trading hours.

    Window: [09:15:00, 15:30:00) IST, Monday–Friday only.
    Boundary semantics: 09:15 is open-inclusive, 15:30 is close-exclusive.
    *dt* must be timezone-aware; converted to IST internally.
    """
    ist = dt.astimezone(_IST)
    if ist.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    minutes = ist.hour * 60 + ist.minute
    return _OPEN_MINUTES <= minutes < _CLOSE_MINUTES


def _market_closed_for_day(dt: datetime) -> bool:
    """Return True if the market will not open again today (IST date of *dt*).

    True for: weekends, and any time on or after 15:30 IST on a weekday.
    False for: any weekday time strictly before 15:30 IST.
    """
    ist = dt.astimezone(_IST)
    if ist.weekday() >= 5:
        return True
    minutes = ist.hour * 60 + ist.minute
    return minutes >= _CLOSE_MINUTES


# ── PollScheduler ──────────────────────────────────────────────────────────────


class PollScheduler:
    """Drift-compensated poll scheduler restricted to NSE market hours.

    Parameters
    ----------
    interval_seconds:
        Target number of seconds between consecutive tick yields. Must be
        a positive integer. Matches ``PhaseConfig.interval_seconds``.

    Usage::

        scheduler = PollScheduler(interval_seconds=5)
        for tick_dt in scheduler.ticks():
            result = fetcher.fetch()   # caller does work
            archiver.write(result)     # elapsed time compensated on next sleep

    Behaviour
    ---------
    - If started before market open on a weekday, waits in 1-second
      increments until 09:15 IST, then begins yielding.
    - If started after 15:30 IST, or on a weekend, yields nothing and
      returns immediately.
    - Stops automatically once the market closes for the day.
    - Never sleeps a negative duration; overruns are absorbed silently.
    """

    def __init__(self, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError(
                f"interval_seconds must be positive, got {interval_seconds!r}"
            )
        self.interval_seconds = interval_seconds

    def ticks(self) -> Iterator[datetime]:
        """Yield one UTC datetime per poll interval during market hours.

        Each yielded value is the UTC timestamp at the *start* of the tick
        (before the caller's work begins). Drift compensation ensures that
        the next tick fires ``interval_seconds`` after the *previous* tick
        started, not after the caller's work finished.
        """
        while True:
            now = _utc_now()
            if is_market_open(now):
                t0 = _monotonic()
                yield now
                elapsed = _monotonic() - t0
                sleep_for = max(0.0, self.interval_seconds - elapsed)
                if sleep_for > 0.0:
                    _sleep(sleep_for)
            elif _market_closed_for_day(now):
                return
            else:
                # Before market open on a trading day — wait in short increments.
                _sleep(1.0)
