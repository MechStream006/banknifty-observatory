"""
StrikeLadder — ATM-centered option window selection from a live token map.

Purpose
-------
Receives the token→strike mapping produced by searchScrip for one
(expiry, side) pair and selects the ±N backbone strikes around ATM for
use as the getMarketData token list.

Backbone definition
-------------------
The exchange lists both a coarse backbone grid (e.g. 500-pt for BankNifty)
and finer sub-grid strikes near ATM (e.g. 100-pt).  Only backbone strikes
are included in the window; sub-grid strikes are excluded.

The backbone is derived from the live token map using a modular alignment
filter anchored at the minimum listed strike:

    backbone = {s : (s - min_strike) % step_size == 0}

This avoids hard-coding an expected strike range or applying a spacing
comparison threshold (e.g. "gap >= 200").  The step_size parameter
(default 500) is explicit configuration, not a guessed threshold.

Live validation (BankNifty 30JUN2026, CE side, 22 Jun 2026)
------------------------------------------------------------
  Total tokens from searchScrip : 410
  Fetched by getMarketData       : 194  (43000–69000, mixed 100/500-pt)
  Backbone step=500              :  49 strikes (45 sub-grid strikes excluded)
  ±15 backbone window, ATM=58000 :  31 tokens (50500–65500, span 15000 pts)

ATM resolution
--------------
The arithmetic ATM candidate is round(spot / step_size) * step_size.
If that value is not a listed backbone strike (e.g. the backbone is
offset from multiples of step_size), the nearest backbone strike by
absolute distance is used.  In a tie the lower strike wins.
"""
from __future__ import annotations


_DEFAULT_STEP: int = 500


class StrikeLadder:
    """ATM-centered backbone window selector for one expiry/side token set.

    Parameters
    ----------
    token_map:
        Token-string → strike-value mapping for one (expiry, side) pair,
        built from searchScrip results.  An empty map is accepted; all
        window operations return [] and resolved_atm() raises ValueError.
    step_size:
        Backbone grid spacing in index points.  Every listed strike where
        ``(strike - min_strike) % step_size == 0`` is a backbone strike;
        the rest are sub-grid strikes excluded from the window.
        Default 500 matches the Phase-1 "liquid 500-pt ladder" contract.

    Raises
    ------
    ValueError
        If step_size is not a positive integer.
    """

    def __init__(
        self,
        token_map: dict[str, int],
        step_size: int = _DEFAULT_STEP,
    ) -> None:
        if not isinstance(step_size, int) or step_size <= 0:
            raise ValueError(f"step_size must be a positive integer, got {step_size!r}")

        self._step_size = step_size

        if not token_map:
            self._backbone: list[tuple[int, str]] = []
            return

        min_strike = min(token_map.values())
        self._backbone = sorted(
            (strike, token)
            for token, strike in token_map.items()
            if (strike - min_strike) % step_size == 0
        )

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def step_size(self) -> int:
        """Backbone grid spacing in index points."""
        return self._step_size

    @property
    def backbone_strikes(self) -> list[int]:
        """Sorted list of backbone strike values. Empty when token_map was empty."""
        return [s for s, _ in self._backbone]

    # ── Public interface ────────────────────────────────────────────────────────

    def resolved_atm(self, spot: float) -> int:
        """Nearest backbone strike to the arithmetic ATM derived from spot.

        The arithmetic ATM candidate is ``round(spot / step_size) * step_size``.
        If that value is not a listed backbone strike (e.g. the backbone is
        offset from multiples of step_size), the nearest backbone strike is
        used.  In a tie the lower strike wins.

        Raises
        ------
        ValueError
            When token_map was empty and no backbone strikes exist.
        """
        if not self._backbone:
            raise ValueError(
                "Cannot resolve ATM: StrikeLadder has no backbone strikes. "
                "Ensure token_map is non-empty and step_size aligns with the listed strikes."
            )

        atm_candidate = int(round(spot / self._step_size) * self._step_size)
        # (abs_distance, strike) as key keeps the lower strike in a tie.
        return min(self.backbone_strikes, key=lambda s: (abs(s - atm_candidate), s))

    def window(self, spot: float, steps: int = 15) -> list[str]:
        """Token strings for the ±steps backbone strikes centered on ATM.

        The returned list is ordered from lowest to highest strike.

        If fewer than ``steps`` backbone strikes exist on one or both sides
        of ATM, the window is truncated to the available strikes rather than
        raising an error.

        Parameters
        ----------
        spot:
            Current BankNifty index LTP.  Used to resolve ATM via
            :meth:`resolved_atm`.
        steps:
            Number of backbone steps on each side of ATM to include.
            Default 15 produces a 31-strike window on the 500-pt backbone
            (= ±7 500 index points).

        Returns
        -------
        list[str]
            Token strings suitable for direct use as a getMarketData batch.
            Empty when token_map was empty.
        """
        if not self._backbone:
            return []

        atm = self.resolved_atm(spot)
        atm_idx = self.backbone_strikes.index(atm)

        lo = max(0, atm_idx - steps)
        hi = min(len(self._backbone) - 1, atm_idx + steps)

        return [token for _, token in self._backbone[lo : hi + 1]]
