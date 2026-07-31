"""The cooling floor uses the MEASURED spread, not the coarse constant.

Regression tests for D-030. The constant `dew_floor_offset_c` was combined with
the measured floor by `max()`, so it won whenever the measured spread was below
3.0 K - the regime silent mode and the frequency ceiling are designed to
produce. It has been REMOVED, not demoted: the owner asked three times, and
"keep it as a start-up fallback" was the second softening of the same
instruction.
"""
from __future__ import annotations

import pytest

from heatctl.setpoint import SetpointController


def _ctl(**over):
    s = {"interval_s": 1800, "step_c": 1.0, "cooling_min_c": 15.0,
         "cooling_max_c": 25.0, "heating_min_c": 20.0, "heating_max_c": 40.0,
         "saturated_pct": 85.0, "idle_pct": 30.0,
         "deviation_band_c": 0.3}
    s.update(over)
    return SetpointController({"control": {"water_setpoint": s}})


class TestFloorUsesMeasuredSpread:
    def test_the_constant_does_not_bind_when_the_spread_is_measured(self):
        """The defect: at spread < 3 K the constant beat the derived floor.

        Mutation-verified - restoring `max(lo, dew + offset)` as a second
        unconditional term makes this return 22 instead of 21 and the test
        fails. Numbers are the live ones from 2026-07-31 11:17: dew 17.2,
        limit 18.2, measured spread 2.17, so the honest floor is 20.4 (ceil 21)
        while the constant would demand 21.2 (ceil 22).
        """
        c = _ctl()
        c.observe_spread(2.17)
        got = c._clamp("cooling", 15.0, dew_point=17.2, supply_limit=18.2)
        assert got == 21.0

    def test_a_wide_measured_spread_still_raises_the_floor_above_the_constant(self):
        """The measured floor must dominate in BOTH directions, not just down.

        A 4.5 K spread against an 18.2 limit needs 22.7 -> 23, well above the
        constant's 21.2. If the change had merely swapped max() for the
        constant this would fail.
        """
        c = _ctl()
        c.observe_spread(4.5)
        assert c._clamp("cooling", 15.0, dew_point=17.2, supply_limit=18.2) == 23.0

    def test_no_floor_at_all_before_a_spread_is_measured(self):
        """The constant is GONE, not demoted to a start-up prior.

        The owner asked three times for `dew + 4` to be removed; it was first
        kept behind a max(), then kept as a "start-up fallback", which was the
        same softening a second time. Neither survives.
        """
        c = _ctl()
        assert c.spread_estimate is None
        assert c._clamp("cooling", 15.0, dew_point=17.2, supply_limit=18.2) == 15.0

    def test_no_floor_when_the_limit_is_missing(self):
        """A measured spread is useless without a limit to add it to - and with
        no limit there is nothing to derive a floor FROM, so there isn't one."""
        c = _ctl()
        c.observe_spread(2.17)
        assert c._clamp("cooling", 15.0, dew_point=17.2, supply_limit=None) == 15.0

    def test_the_estimate_holds_while_the_compressor_is_off(self):
        """`None` means not running and must NOT decay the estimate.

        main.py passes None whenever frequency is 0. If that ever started
        feeding zeros instead, the floor would collapse toward the spread
        minimum and the machine would restart into a floor computed for a
        spread it does not have.
        """
        c = _ctl()
        c.observe_spread(4.0)
        for _ in range(2000):
            c.observe_spread(None)
        assert c.spread_estimate == pytest.approx(4.0)
