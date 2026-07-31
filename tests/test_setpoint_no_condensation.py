"""The setpoint carries NO condensation logic (WP-S change C, 2026-07-31).

This file replaces `test_setpoint_floor.py` and seventeen tests in
`test_setpoint.py` that guarded three mechanisms now deleted from
`setpoint.py`: the `limit + measured spread` floor, the breach branch that
jumped the setpoint upward, and the constraint memory whose only writer was
that branch.

**Why they went.** The floor was CIRCULAR: spread is a consequence of the
control action, so a brief 73 Hz excursion latched a 3.2 K spread, raised the
floor to 19.7, forced the setpoint UP from 19 to 20, and the machine throttled
itself to its 35 Hz minimum. The controller sabotaged itself through its own
success, and making the capacity loop more aggressive made it worse.

Condensation now lives entirely in `capacity.py`, whose actuator runs
continuously from full frequency down to OFF. What these tests guard is that it
does not creep back here.
"""
from __future__ import annotations

import pytest

from heatctl.setpoint import SetpointController


def _ctl(**over):
    s = {"interval_s": 1800, "step_c": 1.0, "cooling_min_c": 15.0,
         "cooling_max_c": 25.0, "heating_min_c": 20.0, "heating_max_c": 40.0,
         "saturated_pct": 85.0, "idle_pct": 30.0, "deviation_band_c": 0.3}
    s.update(over)
    return SetpointController({"control": {"water_setpoint": s}})


class TestNoCondensationFloor:
    def test_the_dew_point_does_not_floor_the_setpoint(self):
        """Mutation-verified: restoring `lo = max(lo, supply_limit + spread)`
        returns 21 instead of 15 and this fails."""
        c = _ctl()
        c.observe_spread(3.2)
        assert c._clamp("cooling", 15.0, dew_point=17.2,
                        supply_limit=18.2) == 15.0

    def test_a_latched_spread_cannot_push_the_setpoint_up(self):
        """THE INCIDENT THIS EXISTS TO PREVENT, 2026-07-31 18:00.

        A 3.2 K spread latched from a brief excursion raised the floor to 19.7
        and forced the setpoint from 19 to 20 - upward, against a house that
        wanted more cooling, throttling the machine to its minimum. No spread
        value may move the setpoint now.
        """
        c = _ctl()
        low = c._clamp("cooling", 15.0, dew_point=15.5, supply_limit=16.5)
        c.observe_spread(3.2)
        high = c._clamp("cooling", 15.0, dew_point=15.5, supply_limit=16.5)
        assert low == high, "the spread estimate still moves the setpoint"

    def test_only_the_configured_band_bounds_the_setpoint(self):
        c = _ctl()
        assert c._clamp("cooling", 5.0, dew_point=15.5, supply_limit=16.5) == 15.0
        assert c._clamp("cooling", 99.0, dew_point=15.5, supply_limit=16.5) == 25.0


class TestNoBreachBranch:
    def test_a_measured_breach_does_not_move_the_setpoint(self):
        """A breach is answered where it happens - the capacity loop cuts
        frequency immediately and stops the compressor at the frequency floor,
        with the valve guard behind that. The setpoint is not part of it.

        The 2026-07-30 09:14 incident is why: a 0.1 K breach jumped the
        setpoint 18 -> 21, parked return water inside the unit's restart dead
        zone, stopped the compressor entirely, and let the house climb 3 K on a
        38 degC day.
        """
        c = _ctl()
        d = c.step(mode="cooling", deviation=-2.0, max_open=100.0,
                   current=19.0, dew_point=15.5, supply_temp=15.0,
                   supply_limit=16.5, now=10_000.0)
        assert d.target is None or d.target <= 19.0, \
            "a breach pushed the setpoint upward again"

    def test_the_controller_has_no_constraint_memory_left(self):
        """Its only writer was the breach branch, so it could never populate -
        dead code that still looked live."""
        c = _ctl()
        for gone in ("_remember_breach", "_is_known_infeasible",
                     "forget_constraint", "_blocked_setpoint"):
            assert not hasattr(c, gone), f"{gone} survived the removal"
