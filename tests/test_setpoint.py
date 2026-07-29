"""Load compensation: house demand -> water temperature setpoint.

The loop that decides efficiency. Water colder than needed does not make the
house colder - the valves just throttle it back - so the error is invisible in
room temperature and shows up only as COP and condensation risk. Which is why
the "back off when the valves are barely open" branch matters as much as the
"not enough capacity" one, and is the half a naive implementation omits.
"""
from __future__ import annotations

import pytest

from heatctl.setpoint import (BLOCKED, BREACH, TRIM,
                              SetpointController)


@pytest.fixture
def sp(cfg):
    def _make(primed: bool = True, **over):
        """`primed` skips the post-start-up settling interval.

        The controller refuses to trim for a full interval after start-up (see
        the restart tests at the bottom), which every other test here would
        otherwise have to work around. Pass primed=False to exercise it.
        """
        cfg["control"]["water_setpoint"] = {
            "enabled": True, "interval_s": 1800.0, "step_c": 1.0,
            "saturated_pct": 85.0, "idle_pct": 30.0, "deviation_band_c": 0.3,
            "cooling_min_c": 14.0, "cooling_max_c": 25.0,
            "heating_min_c": 20.0, "heating_max_c": 40.0,
            "dew_floor_offset_c": 4.0, "breach_jump_c": 6.0, **over,
        }
        c = SetpointController(cfg)
        if primed:
            c._last_change = -1e6      # start-up settling already elapsed
        return c
    return _make


def call(c, mode="cooling", dev=-1.0, open_pct=95.0, current=20.0,
         dew=12.0, leaving=20.0, limit=14.0, now=10_000.0):
    return c.step(mode=mode, deviation=dev, max_open=open_pct, current=current,
                  dew_point=dew, leaving_water=leaving, supply_limit=limit,
                  now=now)


# ---------- the capacity branch ----------

def test_saturated_valves_and_a_warm_house_make_colder_water(sp):
    c = sp()
    d = call(c, mode="cooling", dev=-1.0, open_pct=95.0, current=20.0)
    assert d.target == 19 and d.kind == TRIM


def test_saturated_valves_and_a_cold_house_make_hotter_water(sp):
    c = sp()
    d = call(c, mode="heating", dev=+1.0, open_pct=95.0, current=30.0)
    assert d.target == 31 and d.kind == TRIM


# ---------- the efficiency branch ----------

def test_idle_valves_and_a_satisfied_house_back_the_water_off(sp):
    """Cooling with warmer water is cheaper and safer. Without this branch the
    setpoint only ever ratchets toward more capacity."""
    c = sp()
    d = call(c, mode="cooling", dev=0.0, open_pct=10.0, current=20.0)
    assert d.target == 21


def test_idle_valves_in_heating_back_off_downward(sp):
    c = sp()
    d = call(c, mode="heating", dev=0.0, open_pct=10.0, current=30.0)
    assert d.target == 29


def test_a_house_off_target_with_idle_valves_is_left_alone(sp):
    """Valves shut but the house still wants something means the demand
    controller or safety is holding them - not a water temperature problem."""
    c = sp()
    assert call(c, mode="cooling", dev=-2.0, open_pct=5.0).target is None


def test_mid_range_valves_hold(sp):
    """Between the two thresholds the plant is working as intended."""
    c = sp()
    assert call(c, mode="cooling", dev=-1.0, open_pct=55.0).target is None


# ---------- cadence ----------

def test_a_trim_starts_the_interval_clock(sp):
    c = sp()
    assert call(c, now=10_000.0).target is not None
    assert call(c, now=10_000.0 + 1799).target is None
    assert call(c, now=10_000.0 + 1801, current=19.0).target is not None


def test_holding_does_not_start_the_clock(sp):
    """Only an actual change should cost us the next half hour."""
    c = sp()
    call(c, open_pct=55.0, now=10_000.0)                   # hold
    assert call(c, open_pct=95.0, now=10_000.0 + 5).target is not None


# ---------- the condensation branch bypasses everything ----------

def test_a_measured_breach_jumps_immediately(sp):
    """A breach is a safety event, not a trim, so it ignores the cadence."""
    c = sp()
    call(c, now=10_000.0)                                   # consume the interval
    d = c.step(mode="cooling", deviation=-2.0, max_open=95.0, current=16.0,
               dew_point=14.0, leaving_water=15.0, supply_limit=16.0,
               now=10_000.0 + 10)
    assert d.kind == BREACH
    assert d.target == 20                                   # dew 14 + 6


def test_a_breach_never_lowers_the_setpoint(sp):
    """If the setpoint is already above the jump target, leave it there."""
    c = sp()
    d = c.step(mode="cooling", deviation=-2.0, max_open=95.0, current=24.0,
               dew_point=14.0, leaving_water=15.0, supply_limit=16.0,
               now=10_000.0)
    assert d.kind != BREACH


def test_no_breach_when_the_supply_is_above_the_limit(sp):
    c = sp()
    d = c.step(mode="cooling", deviation=0.0, max_open=10.0, current=20.0,
               dew_point=12.0, leaving_water=20.0, supply_limit=14.0,
               now=10_000.0)
    assert d.kind == TRIM


# ---------- clamps ----------

def test_the_dew_point_floors_the_cooling_setpoint(sp):
    """Heuristic, not a guarantee - P04 targets RETURN water. The measured
    branch above is the real protection."""
    c = sp()
    d = call(c, mode="cooling", dev=-2.0, open_pct=95.0, current=19.0, dew=15.0)
    assert d.target is None or d.target >= 19    # floor is 15+4 = 19


def test_operating_bounds_are_respected(sp):
    c = sp()
    assert call(c, mode="cooling", dev=0.0, open_pct=5.0,
                current=25.0).target is None          # already at max
    c2 = sp()
    assert call(c2, mode="heating", dev=+2.0, open_pct=95.0,
                current=40.0).target is None          # already at max


# ---------- degradation ----------

def test_disabled_does_nothing(sp):
    assert call(sp(enabled=False)).target is None


def test_mode_off_does_nothing(sp):
    assert call(sp(), mode="off").target is None


def test_an_unknown_current_setpoint_does_nothing(sp):
    """Never read the register -> a trim would be a blind write."""
    assert call(sp(), current=None).target is None


def test_no_room_data_holds_the_setpoint(sp):
    """Without room temperatures there is no demand signal to compensate to."""
    assert call(sp(), dev=None).target is None


def test_a_missing_valve_reading_does_not_trim(sp):
    """max_open is the signal that distinguishes 'no capacity' from 'happy'."""
    assert call(sp(), open_pct=None).target is None


# ---------- the cadence must survive a restart ----------

def test_no_trim_in_the_first_interval_after_start_up(sp):
    """Real defect, 2026-07-27. `_last_change` started at 0.0, so the very
    first cycle saw `now - 0 >= interval` and trimmed immediately. The 30 min
    cadence was therefore not honoured across restarts, and a restart loop
    would have hammered the pump's flash - precisely what the cadence exists
    to prevent. Caught because P04 moved during a deploy.
    """
    c = sp(primed=False)
    assert call(c, now=50_000.0).target is None      # first sight: settle
    assert call(c, now=50_000.0 + 1799).target is None
    assert call(c, now=50_000.0 + 1801).target is not None


def test_the_breach_branch_still_acts_during_start_up_settling(sp):
    """Safety is not subject to the settling delay."""
    c = sp(primed=False)
    d = c.step(mode="cooling", deviation=-2.0, max_open=95.0, current=16.0,
               dew_point=14.0, leaving_water=15.0, supply_limit=16.0,
               now=50_000.0)
    assert d.kind == BREACH


# ---------- constraint memory (the 2026-07-29 limit cycle) ----------

def test_a_setpoint_the_condensation_guard_rejected_is_not_retried(sp):
    """THE REGRESSION TEST FOR THE 2026-07-29 LIMIT CYCLE.

    That afternoon the trim stepped the setpoint down, the condensation guard
    shoved it back up ~6 min later, and 30 min after that the rate limiter
    expired and it attempted the identical step again - fourteen times between
    12:24 and 20:19, while the house drifted from 0.32 K to 1.25 K off target.
    Roughly 30 of every 36 minutes were spent a full kelvin warmer than the
    plant could sustain.

    A setpoint rejected at a given supply limit is infeasible FOR THAT LIMIT.
    No amount of waiting changes that; only the constraint moving does.
    """
    c = sp()
    # 12:24 - trim down to 18.
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=14.7, now=0.0)
    assert d.target == 18 and d.kind == TRIM
    # 12:31 - leaving water breaches at 18; the guard jumps it back to 19.
    d = call(c, current=18.0, leaving=14.5, limit=14.7, dew=12.7, now=420.0)
    assert d.kind == BREACH and d.target > 18
    # 13:01 - the interval has elapsed and the house is still warm. Before the
    # fix this trimmed straight back to 18 and the cycle began again.
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, leaving=20.0,
             limit=14.8, dew=12.8, now=2_300.0)
    assert d.target is None
    assert d.kind == BLOCKED
    assert d.demand_unmet


def test_the_block_lifts_when_the_supply_limit_actually_falls(sp):
    """The constraint moving is the ONLY thing that may re-open the attempt.
    Air drying out is real new information; the clock is not."""
    c = sp()
    call(c, current=18.0, leaving=14.5, limit=14.7, dew=12.7, now=0.0)
    blocked = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=14.7,
                   now=2_000.0)
    assert blocked.kind == BLOCKED
    # Dew point falls by more than the retry margin: try again.
    freed = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=14.0,
                 dew=12.0, now=4_000.0)
    assert freed.target == 18 and freed.kind == TRIM


def test_a_rising_limit_does_not_lift_the_block(sp):
    """The failure mode of a naive 'has anything changed' test. On 2026-07-29
    the limit rose all afternoon, 14.1 to 16.1 degC - which makes the rejected
    setpoint MORE infeasible, not less."""
    c = sp()
    call(c, current=18.0, leaving=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=16.1, dew=14.1,
             now=9_000.0)
    assert d.kind == BLOCKED


def test_a_less_aggressive_setpoint_is_still_allowed(sp):
    """Blocking 18 must not block 20. Only setpoints at or below the rejected
    one are known-infeasible; blocking everything would strand the plant."""
    c = sp()
    call(c, current=18.0, leaving=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=21.0, dev=-1.0, open_pct=100.0, limit=14.7, now=2_000.0)
    assert d.target == 20 and d.kind == TRIM


def test_the_memory_keeps_the_least_aggressive_failure(sp):
    """If 19 breaches, 18 certainly would too. Remembering 18 instead would
    leave 19 to be rediscovered the hard way, one wasted cycle at a time."""
    c = sp()
    call(c, current=18.0, leaving=14.0, limit=14.7, dew=12.7, now=0.0)
    call(c, current=19.0, leaving=14.5, limit=14.7, dew=12.7, now=60.0)
    d = call(c, current=20.0, dev=-1.0, open_pct=100.0, limit=14.7, now=2_000.0)
    assert d.kind == BLOCKED          # 19 is blocked, so 19 must not be tried


def test_heating_is_unaffected_by_the_cooling_constraint_memory(sp):
    """The memory is about condensation, which does not exist in heating.
    Carrying it across would silently cap the heating setpoint."""
    c = sp()
    call(c, current=18.0, leaving=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, mode="heating", dev=+1.0, open_pct=95.0, current=30.0,
             limit=None, now=2_000.0)
    assert d.target == 31 and d.kind == TRIM


def test_an_unknown_limit_fails_toward_trying(sp):
    """The measured-breach branch is the real protection, so an extra attempt
    costs one wasted step - while wrongly blocking would strand the plant at a
    setpoint it could have improved on."""
    c = sp()
    call(c, current=18.0, leaving=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=None, now=2_000.0)
    assert d.target == 18 and d.kind == TRIM


def test_backing_off_is_never_blocked(sp):
    """The efficiency branch raises the cooling setpoint, which can only make
    condensation less likely. Blocking it would trap the plant cold."""
    c = sp()
    call(c, current=18.0, leaving=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=18.0, dev=0.0, open_pct=10.0, limit=14.7, now=2_000.0)
    assert d.target == 19 and d.kind == TRIM


def test_the_full_afternoon_settles_instead_of_oscillating(sp):
    """Replay of the measured day: a warm house, saturated valves, and a
    supply limit rising from 14.1 to 16.1 degC over eight hours.

    Before the fix this produced 14 setpoint changes. It must now converge and
    then stop writing - every write wears the heat pump's flash, and the
    oscillation bought nothing."""
    c = sp()
    limits = [14.1 + 0.25 * i for i in range(9)]      # 14.1 .. 16.1
    writes, blocked_cycles = 0, 0
    current, t = 19.0, 0.0
    for limit in limits:
        for _ in range(4):                            # four 30-min slots/hour
            t += 1800.0
            d = call(c, current=current, dev=-1.0, open_pct=100.0,
                     leaving=limit + 0.4, limit=limit, dew=limit - 2.0, now=t)
            if d.kind == BLOCKED:
                blocked_cycles += 1
            if d.target is not None:
                writes += 1
                current = d.target
                # The guard reacts to the colder water within the next cycle.
                t += 360.0
                b = call(c, current=current, leaving=limit - 0.2, limit=limit,
                         dew=limit - 2.0, now=t)
                if b.target is not None:
                    writes += 1
                    current = b.target
    assert writes <= 6, f"still oscillating: {writes} setpoint writes"
    assert blocked_cycles > 0, "the saturation condition was never reported"
