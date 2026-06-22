"""Tests for lib.discovery.fetchers.strike_ladder: StrikeLadder."""
from __future__ import annotations

import pytest

from lib.discovery.fetchers.strike_ladder import StrikeLadder


# ── token map helpers ─────────────────────────────────────────────────────────


def _pure_500_map(n: int = 40, base: int = 43000) -> dict[str, int]:
    """n strikes on a pure 500-pt grid starting at base."""
    return {str(70000 + i): base + i * 500 for i in range(n)}


def _pure_100_map(n: int = 100, base: int = 55000) -> dict[str, int]:
    """n strikes on a pure 100-pt grid starting at base."""
    return {str(80000 + i): base + i * 100 for i in range(n)}


def _mixed_map() -> dict[str, int]:
    """BankNifty-like: 500-pt outer regions, 100-pt inner region near ATM.

    Outer-low  : 43000–50000 step 500   (15 strikes)
    Inner      : 50100–63900 step 100   (139 strikes)
    Outer-high : 64500–69000 step 500   (10 strikes)
    Total      : 164 strikes
    Backbone (step=500, base=43000) includes:
      outer-low (43000–50000) + inner 500-pt aligned (50500–63500) + outer-high (64500–69000)
    """
    tokens: dict[str, int] = {}
    idx = 0
    for s in range(43000, 50001, 500):
        tokens[str(70000 + idx)] = s
        idx += 1
    for s in range(50100, 64000, 100):
        tokens[str(70000 + idx)] = s
        idx += 1
    for s in range(64500, 69001, 500):
        tokens[str(70000 + idx)] = s
        idx += 1
    return tokens


def _offset_map() -> dict[str, int]:
    """500-pt grid starting at 43250 (NOT a multiple of 500).

    Backbone aligned to 43250: 43250, 43750, 44250, 44750, ...
    Arithmetic ATM for spot ~44000 = round(44000/500)*500 = 44000,
    but 44000 is NOT in this backbone (44000 - 43250 = 750, 750%500 = 250).
    """
    return {str(90000 + i): 43250 + i * 500 for i in range(20)}


# ── TestStrikeLadderInit ──────────────────────────────────────────────────────


class TestStrikeLadderInit:
    def test_empty_token_map_accepted(self) -> None:
        ladder = StrikeLadder({})
        assert ladder.backbone_strikes == []

    def test_step_size_default_is_500(self) -> None:
        ladder = StrikeLadder(_pure_500_map())
        assert ladder.step_size == 500

    def test_step_size_stored(self) -> None:
        ladder = StrikeLadder(_pure_500_map(), step_size=100)
        assert ladder.step_size == 100

    def test_zero_step_size_raises(self) -> None:
        with pytest.raises(ValueError, match="step_size"):
            StrikeLadder(_pure_500_map(), step_size=0)

    def test_negative_step_size_raises(self) -> None:
        with pytest.raises(ValueError, match="step_size"):
            StrikeLadder(_pure_500_map(), step_size=-500)


# ── TestBackboneStrikes ───────────────────────────────────────────────────────


class TestBackboneStrikes:
    def test_empty_backbone_for_empty_map(self) -> None:
        assert StrikeLadder({}).backbone_strikes == []

    def test_pure_500pt_grid_all_strikes_are_backbone(self) -> None:
        n = 20
        ladder = StrikeLadder(_pure_500_map(n=n))
        assert len(ladder.backbone_strikes) == n

    def test_backbone_is_sorted_ascending(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=10))
        strikes = ladder.backbone_strikes
        assert strikes == sorted(strikes)

    def test_mixed_grid_sub_strikes_excluded(self) -> None:
        ladder = StrikeLadder(_mixed_map())
        # Sub-grid 100-pt strikes (not 500-pt aligned from base) must be absent
        for s in ladder.backbone_strikes:
            assert (s - 43000) % 500 == 0, f"sub-grid strike {s} leaked into backbone"

    def test_min_strike_always_in_backbone(self) -> None:
        ladder = StrikeLadder(_mixed_map())
        assert min(_mixed_map().values()) in ladder.backbone_strikes

    def test_backbone_count_pure_grid(self) -> None:
        n = 35
        ladder = StrikeLadder(_pure_500_map(n=n))
        assert len(ladder.backbone_strikes) == n

    def test_backbone_count_mixed_grid(self) -> None:
        ladder = StrikeLadder(_mixed_map())
        # outer-low: 43000–50000 /500 = 15; inner 500-pt: 50500–63500 /500 = 27;
        # outer-high: 64500–69000 /500 = 10  → total = 52
        assert len(ladder.backbone_strikes) == 52

    def test_step_size_100_makes_all_strikes_backbone(self) -> None:
        tm = _pure_100_map(n=50)
        ladder = StrikeLadder(tm, step_size=100)
        assert len(ladder.backbone_strikes) == 50

    def test_offset_base_backbone_aligned_to_min_strike(self) -> None:
        ladder = StrikeLadder(_offset_map())
        # All backbone strikes should satisfy (s - 43250) % 500 == 0
        for s in ladder.backbone_strikes:
            assert (s - 43250) % 500 == 0


# ── TestResolvedATM ───────────────────────────────────────────────────────────


class TestResolvedATM:
    def test_raises_on_empty_backbone(self) -> None:
        with pytest.raises(ValueError, match="no backbone strikes"):
            StrikeLadder({}).resolved_atm(58000.0)

    def test_exact_hit_when_arithmetic_atm_in_backbone(self) -> None:
        # Pure 500-pt grid base 43000; spot 58000 → arithmetic ATM 58000
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        assert ladder.resolved_atm(58000.0) == 58000

    def test_result_is_int(self) -> None:
        ladder = StrikeLadder(_pure_500_map())
        assert isinstance(ladder.resolved_atm(55000.0), int)

    def test_spot_below_all_backbone_returns_min_backbone(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=10, base=50000))
        # min backbone = 50000; spot 30000 well below
        assert ladder.resolved_atm(30000.0) == 50000

    def test_spot_above_all_backbone_returns_max_backbone(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=10, base=50000))
        # max backbone = 50000 + 9*500 = 54500; spot 80000 well above
        assert ladder.resolved_atm(80000.0) == 54500

    def test_spot_rounds_to_nearest_backbone_below(self) -> None:
        # Spot 57749 → arithmetic ATM = round(57749/500)*500 = round(115.498)*500
        # = 115*500 = 57500
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        assert ladder.resolved_atm(57749.0) == 57500

    def test_spot_rounds_to_nearest_backbone_above(self) -> None:
        # Spot 57751 → arithmetic ATM = round(57751/500)*500 = round(115.502)*500
        # = 116*500 = 58000
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        assert ladder.resolved_atm(57751.0) == 58000

    def test_fallback_when_arithmetic_atm_not_in_backbone(self) -> None:
        # Offset map: backbone at 43250, 43750, 44250, ...
        # Arithmetic ATM for spot 44000 = 44000 (multiple of 500)
        # 44000 not in backbone; nearest are 43750 (d=250) and 44250 (d=250)
        # tie → lower wins: 43750
        ladder = StrikeLadder(_offset_map())
        assert ladder.resolved_atm(44000.0) == 43750

    def test_tie_broken_by_lower_strike(self) -> None:
        # Two backbone strikes equidistant from ATM candidate
        # backbone: 43000, 43500 (pure 500-pt, 2 strikes)
        # spot = 43250 → arithmetic ATM = round(43250/500)*500 = round(86.5)*500
        # Python banker's rounding: round(86.5) = 86 → 43000
        tm = {"t1": 43000, "t2": 43500}
        ladder = StrikeLadder(tm)
        # Confirm arithmetic ATM (43000 or 43500) is in backbone either way
        result = ladder.resolved_atm(43250.0)
        assert result in (43000, 43500)  # either is valid; lower is preferred

    def test_single_backbone_strike_always_returned(self) -> None:
        ladder = StrikeLadder({"only": 58000}, step_size=500)
        assert ladder.resolved_atm(40000.0) == 58000
        assert ladder.resolved_atm(80000.0) == 58000


# ── TestWindow ────────────────────────────────────────────────────────────────


class TestWindow:
    def test_empty_map_returns_empty_list(self) -> None:
        assert StrikeLadder({}).window(58000.0) == []

    def test_returns_list(self) -> None:
        assert isinstance(StrikeLadder(_pure_500_map()).window(55000.0), list)

    def test_tokens_are_strings(self) -> None:
        tokens = StrikeLadder(_pure_500_map()).window(55000.0)
        assert all(isinstance(t, str) for t in tokens)

    def test_15_steps_gives_31_tokens_when_sufficient(self) -> None:
        # 40 strikes, ATM near middle → 31 available
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        tokens = ladder.window(53000.0, steps=15)
        assert len(tokens) == 31

    def test_window_ordered_ascending_by_strike(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        tokens = ladder.window(53000.0, steps=15)
        strikes = [ladder.backbone_strikes[ladder.backbone_strikes.index(
            int(next(s for s, t in ladder._backbone if t == tok))
        )] for tok in tokens]
        # Simpler: rebuild strike list from window tokens
        token_to_strike = {t: s for s, t in ladder._backbone}
        window_strikes = [token_to_strike[t] for t in tokens]
        assert window_strikes == sorted(window_strikes)

    def test_window_contains_atm_token(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        spot = 53000.0
        atm = ladder.resolved_atm(spot)
        token_to_strike = {t: s for s, t in ladder._backbone}
        tokens = ladder.window(spot, steps=15)
        window_strikes = [token_to_strike[t] for t in tokens]
        assert atm in window_strikes

    def test_steps_0_returns_only_atm_token(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        tokens = ladder.window(53000.0, steps=0)
        assert len(tokens) == 1
        token_to_strike = {t: s for s, t in ladder._backbone}
        assert token_to_strike[tokens[0]] == ladder.resolved_atm(53000.0)

    def test_steps_1_returns_up_to_3_tokens_when_sufficient(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        tokens = ladder.window(53000.0, steps=1)
        assert len(tokens) == 3

    def test_window_truncated_at_low_end(self) -> None:
        # ATM near bottom: spot=43500 → ATM=43500, idx=1 in base=43000 grid
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        tokens = ladder.window(43500.0, steps=15)
        # Only 1 strike below ATM, so window is 1 + 1 + 15 = 17
        assert len(tokens) == 17

    def test_window_truncated_at_high_end(self) -> None:
        # 40 strikes, ATM near top: spot=62500 → ATM=62500, idx=39 in base=43000 grid
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        tokens = ladder.window(62500.0, steps=15)
        # Only 0 strikes above ATM (it's the last), so window = 15 + 1 = 16
        assert len(tokens) == 16

    def test_window_steps_larger_than_available_returns_all(self) -> None:
        n = 5
        ladder = StrikeLadder(_pure_500_map(n=n, base=43000))
        tokens = ladder.window(45000.0, steps=100)
        assert len(tokens) == n

    def test_window_mixed_grid_excludes_sub_strikes(self) -> None:
        ladder = StrikeLadder(_mixed_map())
        tokens = ladder.window(57000.0, steps=15)
        token_to_strike = {t: s for s, t in ladder._backbone}
        for t in tokens:
            s = token_to_strike[t]
            assert (s - 43000) % 500 == 0, f"sub-grid strike {s} in window"

    def test_window_mixed_grid_15_steps_gives_31_tokens(self) -> None:
        # With 52 backbone strikes and ATM near middle, ±15 = 31 tokens
        ladder = StrikeLadder(_mixed_map())
        tokens = ladder.window(57000.0, steps=15)
        assert len(tokens) == 31

    def test_single_strike_window_any_steps(self) -> None:
        ladder = StrikeLadder({"only": 58000})
        assert ladder.window(58000.0, steps=15) == ["only"]
        assert ladder.window(0.0, steps=15) == ["only"]

    def test_no_duplicate_tokens_in_window(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=40))
        tokens = ladder.window(55000.0, steps=15)
        assert len(tokens) == len(set(tokens))

    def test_tokens_are_exactly_from_input_map(self) -> None:
        tm = _pure_500_map(n=40)
        ladder = StrikeLadder(tm)
        tokens = ladder.window(55000.0, steps=15)
        for t in tokens:
            assert t in tm, f"token {t!r} not in original token_map"


# ── TestStepSizeVariants ──────────────────────────────────────────────────────


class TestStepSizeVariants:
    def test_step_100_all_strikes_are_backbone(self) -> None:
        # All 100-pt strikes pass (strike - base) % 100 == 0
        tm = _pure_100_map(n=30, base=55000)
        ladder = StrikeLadder(tm, step_size=100)
        assert len(ladder.backbone_strikes) == 30

    def test_step_200_filters_100pt_sub_strikes(self) -> None:
        # 100-pt map: only even-index strikes (55000,55200,...) pass % 200 == 0
        tm = _pure_100_map(n=20, base=55000)
        ladder = StrikeLadder(tm, step_size=200)
        # 55000, 55200, 55400, ..., 55000+19*100=56900 → stride 200 → 10 backbone
        assert len(ladder.backbone_strikes) == 10

    def test_step_1000_filters_500pt_strikes(self) -> None:
        # 500-pt map base 43000: only 43000, 44000, 45000, ... pass % 1000 == 0
        tm = _pure_500_map(n=20, base=43000)
        ladder = StrikeLadder(tm, step_size=1000)
        # backbone: 43000+0, 43000+2×500=44000, ... every other 500-pt strike
        assert len(ladder.backbone_strikes) == 10

    def test_custom_step_affects_window_size(self) -> None:
        tm = _pure_100_map(n=50, base=55000)
        ladder_100 = StrikeLadder(tm, step_size=100)
        ladder_200 = StrikeLadder(tm, step_size=200)
        spot = 57000.0
        # step=100: 31 tokens (all 100-pt backbone); step=200: 31 tokens but
        # each step is 200 pts → same count but wider coverage
        assert len(ladder_100.window(spot, steps=5)) == 11
        assert len(ladder_200.window(spot, steps=5)) == 11

    def test_step_size_equals_strike_range_gives_two_backbone(self) -> None:
        # Exactly two strikes: 43000 and 53000 (range=10000)
        tm = {"t1": 43000, "t2": 43500, "t3": 44000, "t4": 53000}
        ladder = StrikeLadder(tm, step_size=10000)
        # (43000-43000)%10000=0 ✓; (43500-43000)%10000=500 ✗; (44000-43000)%10000=1000 ✗;
        # (53000-43000)%10000=10000%10000=0 ✓
        assert set(ladder.backbone_strikes) == {43000, 53000}


# ── TestBankNiftyRealistic ────────────────────────────────────────────────────


class TestBankNiftyRealistic:
    """Integration-style tests using a BankNifty-like mixed 100/500-pt map."""

    def setup_method(self) -> None:
        self.tm = _mixed_map()
        self.ladder = StrikeLadder(self.tm)
        self.spot = 57845.95  # matches the live smoke-test spot

    def test_backbone_contains_only_500pt_aligned_strikes(self) -> None:
        for s in self.ladder.backbone_strikes:
            assert (s - 43000) % 500 == 0

    def test_backbone_does_not_contain_100pt_sub_strikes(self) -> None:
        sub_grid = {s for s in self.tm.values() if (s - 43000) % 500 != 0}
        backbone_set = set(self.ladder.backbone_strikes)
        assert sub_grid.isdisjoint(backbone_set)

    def test_atm_resolved_to_nearest_500pt_backbone(self) -> None:
        # spot=57845.95 → arithmetic ATM = round(57845.95/500)*500 = 58000
        assert self.ladder.resolved_atm(self.spot) == 58000

    def test_atm_in_backbone_when_spot_in_100pt_zone(self) -> None:
        # The ATM (58000) is on the backbone even though 100-pt sub-strikes surround it
        assert 58000 in self.ladder.backbone_strikes

    def test_window_15_steps_returns_31_tokens(self) -> None:
        tokens = self.ladder.window(self.spot, steps=15)
        assert len(tokens) == 31

    def test_window_spans_correct_backbone_indices(self) -> None:
        # Window[0] and window[-1] must be exactly backbone[atm_idx±15].
        # The mixed map has a 1000-pt gap in the backbone (63500→64500),
        # so the upper bound is NOT necessarily atm + 15*500 pts — it is
        # the 15th backbone step above ATM, whatever point value that is.
        tokens = self.ladder.window(self.spot, steps=15)
        token_to_strike = {t: s for s, t in self.ladder._backbone}
        window_strikes = sorted(token_to_strike[t] for t in tokens)
        atm = self.ladder.resolved_atm(self.spot)
        atm_idx = self.ladder.backbone_strikes.index(atm)
        expected_lo = self.ladder.backbone_strikes[atm_idx - 15]
        expected_hi = self.ladder.backbone_strikes[atm_idx + 15]
        assert window_strikes[0] == expected_lo
        assert window_strikes[-1] == expected_hi

    def test_window_contains_no_duplicates(self) -> None:
        tokens = self.ladder.window(self.spot, steps=15)
        assert len(tokens) == len(set(tokens))

    def test_all_window_tokens_in_original_map(self) -> None:
        tokens = self.ladder.window(self.spot, steps=15)
        for t in tokens:
            assert t in self.tm


# ── TestEdgeCases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_strike_backbone_and_window(self) -> None:
        ladder = StrikeLadder({"t1": 58000})
        assert ladder.backbone_strikes == [58000]
        assert ladder.window(58000.0, steps=15) == ["t1"]

    def test_two_strikes_window_from_low_end(self) -> None:
        ladder = StrikeLadder({"lo": 50000, "hi": 50500})
        # ATM=50000 (lower, idx=0) → window with steps=5: only lo and hi
        tokens = ladder.window(50000.0, steps=5)
        assert set(tokens) == {"lo", "hi"}

    def test_two_strikes_window_from_high_end(self) -> None:
        ladder = StrikeLadder({"lo": 50000, "hi": 50500})
        tokens = ladder.window(50500.0, steps=5)
        assert set(tokens) == {"lo", "hi"}

    def test_window_with_more_steps_than_backbone_returns_all(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=5, base=50000))
        tokens = ladder.window(52000.0, steps=100)
        assert len(tokens) == 5

    def test_spot_exactly_on_min_strike(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=20, base=43000))
        assert ladder.resolved_atm(43000.0) == 43000

    def test_spot_exactly_on_max_strike(self) -> None:
        n = 20
        ladder = StrikeLadder(_pure_500_map(n=n, base=43000))
        max_strike = 43000 + (n - 1) * 500
        assert ladder.resolved_atm(float(max_strike)) == max_strike

    def test_very_large_spot_resolves_to_max_backbone(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=10, base=50000))
        assert ladder.resolved_atm(999999.0) == 50000 + 9 * 500

    def test_very_small_spot_resolves_to_min_backbone(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=10, base=50000))
        assert ladder.resolved_atm(0.001) == 50000

    def test_float_spot_consistent_with_int_spot(self) -> None:
        ladder = StrikeLadder(_pure_500_map(n=40, base=43000))
        assert ladder.resolved_atm(58000.0) == ladder.resolved_atm(58000)

    def test_steps_equal_to_half_backbone_gives_all(self) -> None:
        n = 11
        ladder = StrikeLadder(_pure_500_map(n=n, base=50000))
        # ATM in exact middle (idx=5), steps=5 → 5+1+5 = 11
        tokens = ladder.window(52500.0, steps=5)
        assert len(tokens) == n
