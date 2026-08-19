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

**AMENDED 2026-08-19.** Two of the claims above were measured and found false,
so a `max(lo, supply_limit)` floor is back in `_clamp` and the two tests that
forbade *any* dew-point influence have been rewritten below. What changed:

  * "runs continuously down to OFF" - it does not. STOP/RESUME has a 600 s
    minimum off time and the frequency ceiling does not bind during a start
    ramp at all (compressor reached 50 Hz under a 30 Hz ceiling, 2026-08-12).
    On the night of 08-11/12 that produced 22 compressor cycles in five hours.
  * "with the valve guard behind that" - there is no valve guard any more
    (D-035, 2026-08-19).

**The distinction this file now defends is narrower and sharper: no SPREAD term
in the floor, ever.** Spread is a consequence of the control action and that is
what made the old floor circular; dew point is not, and cannot latch. The test
that encodes the actual 2026-07-31 incident,
`test_a_latched_spread_cannot_push_the_setpoint_up`, is unchanged and still
passes - which is the evidence that the restored floor is on the right side of
that argument rather than a quiet re-run of it.
"""
from __future__ import annotations

import pytest

from heatctl.setpoint import SetpointController


def _ctl(**over):
    # `enabled` was missing here until 2026-08-19, so every test that went
    # through `step()` got an immediate "disabled" and asserted nothing. Both
    # such tests were written as `assert d.target is None or ...`, which passes
    # on the None. Found by mutation-verifying the dead-zone cap: the mutation
    # went in and the test stayed green.
    s = {"enabled": True,
         "interval_s": 1800, "step_c": 1.0, "cooling_min_c": 15.0,
         "cooling_max_c": 25.0, "heating_min_c": 20.0, "heating_max_c": 40.0,
         "saturated_pct": 85.0, "idle_pct": 30.0, "deviation_band_c": 0.3}
    s.update(over)
    c = SetpointController({"control": {"water_setpoint": s}})
    c._last_change = -1e6          # start-up settling already elapsed
    return c


class TestNoCondensationFloor:
    def test_the_floor_is_the_limit_itself_and_never_the_limit_plus_spread(self):
        """SUPERSEDES `test_the_dew_point_does_not_floor_the_setpoint`.

        That test asserted the dew point may not floor the setpoint at all,
        and was mutation-verified against `lo = max(lo, supply_limit + spread)`
        returning 21. The mutation it guarded is still forbidden; the blanket
        claim is not, because the capacity loop turned out not to be the
        continuous actuator this file assumed (see the module docstring).

        So: with a 3.2 K spread observed and a limit of 18.2, the floor must be
        19 (ceil of the limit) and NOT 21 (ceil of limit + spread). The 2 K
        between those two numbers is the entire difference between a floor that
        can latch and one that cannot.
        """
        c = _ctl()
        c.observe_spread(3.2)
        assert c._clamp("cooling", 15.0, dew_point=17.2, supply_limit=18.2) == 19.0

    def test_no_supply_limit_means_no_floor(self):
        """A missing dew point must not silently invent one. It stops the
        compressor a layer up (D-010), so `cooling_min_c` is the only bound
        left here and that is deliberate, not a fallback worth tuning."""
        c = _ctl()
        assert c._clamp("cooling", 5.0, dew_point=None, supply_limit=None) == 15.0

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

    def test_the_band_and_the_limit_bound_the_setpoint_and_nothing_else(self):
        """SUPERSEDES `test_only_the_configured_band_bounds_the_setpoint`.

        The ceiling is still `cooling_max_c` alone - the floor is the only
        thing the limit touches, and warmer is the safe direction in cooling,
        so nothing derived from the dew point may ever cap the setpoint.
        """
        c = _ctl()
        assert c._clamp("cooling", 5.0, dew_point=15.5, supply_limit=16.5) == 17.0
        assert c._clamp("cooling", 99.0, dew_point=15.5, supply_limit=16.5) == 25.0
        # Below the band the band still wins: a limit under `cooling_min_c`
        # must not drag the floor DOWN.
        assert c._clamp("cooling", 5.0, dew_point=9.0, supply_limit=10.0) == 15.0


class TestNoBreachBranch:
    def test_a_measured_breach_does_not_move_the_setpoint(self):
        """A breach is answered where it happens - the capacity loop cuts
        frequency immediately and stops the compressor at the frequency floor.
        The setpoint is not part of it. ("with the valve guard behind that"
        stood here until D-035, 2026-08-19, removed the valve guard; the
        capacity loop is now the whole of it.)

        This test only started asserting anything on 2026-08-19, when `enabled`
        was added to `_ctl` - before that `step()` returned "disabled" and the
        `is None or` below swallowed it. It passes on its own merits now:
        target 18.0 against a current of 19.0.

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


class TestTheFloorCannotParkTheCompressor:
    """The condensation floor must never ask for a setpoint the unit ignores.

    Added 2026-08-19 with the floor itself. `running_ceiling` had been an
    unused parameter of `_clamp` ever since the 2026-07-30 cap was reverted,
    and restoring a floor above it is what made it reachable again.
    """

    def test_the_floor_is_capped_at_the_setpoint_the_machine_will_run_at(self):
        """A humid day: dew point 20, limit 21, return 21 with a 2 K dead zone.

        The floor wants 21; above 19 the compressor simply will not start. Ask
        for 21 and the plant stops cooling silently and completely - the
        2026-07-30 09:14 failure, where the house climbed 3 K on a 38 degC day.
        """
        c = _ctl()
        assert c._clamp("cooling", 15.0, dew_point=20.0, supply_limit=21.0,
                        running_ceiling=19.0) == 19.0

    def test_the_cap_never_drags_the_floor_below_the_configured_band(self):
        """A cold return makes `running_ceiling` low. The band still wins -
        and idling is correct there, because a return that cold means the
        house already has the cooling it asked for."""
        c = _ctl()
        assert c._clamp("cooling", 5.0, dew_point=16.0, supply_limit=17.0,
                        running_ceiling=8.0) == 15.0

    def test_without_a_running_ceiling_the_floor_still_applies(self):
        """No return reading is not a reason to drop the condensation floor."""
        c = _ctl()
        assert c._clamp("cooling", 15.0, dew_point=20.0, supply_limit=21.0,
                        running_ceiling=None) == 21.0

    def test_the_efficiency_branch_cannot_jump_the_setpoint_into_the_dead_zone(self):
        """End to end, and the branch `step()`'s reversal guard does NOT cover.

        The capacity branch is protected - a target above `current` when it
        asked for colder returns BLOCKED. The efficiency branch asks for
        warmer, so no reversal is detected and the jump would be written.
        """
        c = _ctl()
        d = c.step(mode="cooling", deviation=0.0, max_open=10.0, current=15.0,
                   dew_point=20.0, supply_temp=19.0, supply_limit=21.0,
                   running_ceiling=19.0, now=10_000.0)
        # Assert the branch actually FIRED before asserting what it did. The
        # `is None or ...` form this replaces was green against the bug.
        assert d.target is not None, f"branch did not fire: {d.reason}"
        assert d.target <= 19.0, (
            "the floor jumped the setpoint past the restart dead zone")
