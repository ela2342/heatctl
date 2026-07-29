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
         dew=12.0, supply=20.0, limit=14.0, now=10_000.0):
    return c.step(mode=mode, deviation=dev, max_open=open_pct, current=current,
                  dew_point=dew, supply_temp=supply, supply_limit=limit,
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
               dew_point=14.0, supply_temp=15.0, supply_limit=16.0,
               now=10_000.0 + 10)
    assert d.kind == BREACH
    assert d.target == 20                                   # dew 14 + 6


def test_a_breach_never_lowers_the_setpoint(sp):
    """If the setpoint is already above the jump target, leave it there."""
    c = sp()
    d = c.step(mode="cooling", deviation=-2.0, max_open=95.0, current=24.0,
               dew_point=14.0, supply_temp=15.0, supply_limit=16.0,
               now=10_000.0)
    assert d.kind != BREACH


def test_no_breach_when_the_supply_is_above_the_limit(sp):
    c = sp()
    d = c.step(mode="cooling", deviation=0.0, max_open=10.0, current=20.0,
               dew_point=12.0, supply_temp=20.0, supply_limit=14.0,
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
               dew_point=14.0, supply_temp=15.0, supply_limit=16.0,
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
    d = call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=420.0)
    assert d.kind == BREACH and d.target > 18
    # 13:01 - the interval has elapsed and the house is still warm. Before the
    # fix this trimmed straight back to 18 and the cycle began again.
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, supply=20.0,
             limit=14.8, dew=12.8, now=2_300.0)
    assert d.target is None
    assert d.kind == BLOCKED
    assert d.demand_unmet


def test_the_block_lifts_when_the_supply_limit_actually_falls(sp):
    """The constraint moving is the ONLY thing that may re-open the attempt.
    Air drying out is real new information; the clock is not."""
    c = sp()
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
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
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=16.1, dew=14.1,
             now=9_000.0)
    assert d.kind == BLOCKED


def test_a_less_aggressive_setpoint_is_still_allowed(sp):
    """Blocking 18 must not block 20. Only setpoints at or below the rejected
    one are known-infeasible; blocking everything would strand the plant."""
    c = sp()
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=21.0, dev=-1.0, open_pct=100.0, limit=14.7, now=2_000.0)
    assert d.target == 20 and d.kind == TRIM


def test_the_memory_keeps_the_least_aggressive_failure(sp):
    """If 19 breaches, 18 certainly would too. Remembering 18 instead would
    leave 19 to be rediscovered the hard way, one wasted cycle at a time."""
    c = sp()
    call(c, current=18.0, supply=14.0, limit=14.7, dew=12.7, now=0.0)
    call(c, current=19.0, supply=14.5, limit=14.7, dew=12.7, now=60.0)
    d = call(c, current=20.0, dev=-1.0, open_pct=100.0, limit=14.7, now=2_000.0)
    assert d.kind == BLOCKED          # 19 is blocked, so 19 must not be tried


def test_heating_is_unaffected_by_the_cooling_constraint_memory(sp):
    """The memory is about condensation, which does not exist in heating.
    Carrying it across would silently cap the heating setpoint."""
    c = sp()
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, mode="heating", dev=+1.0, open_pct=95.0, current=30.0,
             limit=None, now=2_000.0)
    assert d.target == 31 and d.kind == TRIM


def test_an_unknown_limit_fails_toward_trying(sp):
    """The measured-breach branch is the real protection, so an extra attempt
    costs one wasted step - while wrongly blocking would strand the plant at a
    setpoint it could have improved on."""
    c = sp()
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=None, now=2_000.0)
    assert d.target == 18 and d.kind == TRIM


def test_backing_off_is_never_blocked(sp):
    """The efficiency branch raises the cooling setpoint, which can only make
    condensation less likely. Blocking it would trap the plant cold."""
    c = sp()
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
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
                     supply=limit + 0.4, limit=limit, dew=limit - 2.0, now=t)
            if d.kind == BLOCKED:
                blocked_cycles += 1
            if d.target is not None:
                writes += 1
                current = d.target
                # The guard reacts to the colder water within the next cycle.
                t += 360.0
                b = call(c, current=current, supply=limit - 0.2, limit=limit,
                         dew=limit - 2.0, now=t)
                if b.target is not None:
                    writes += 1
                    current = b.target
    assert writes <= 6, f"still oscillating: {writes} setpoint writes"
    assert blocked_cycles > 0, "the saturation condition was never reported"


def test_the_dew_floor_binding_also_reports_demand_unmet(sp):
    """Whichever mechanism stops the trim - the dew-point floor or a
    remembered breach - the operator-visible fact is the same: the house wants
    more and the plant cannot legally supply it. Reporting one as an alarm and
    the other as a quiet hold would make the alarm depend on an implementation
    detail."""
    c = sp()
    # dew 14.1 -> floor 18.1 -> ceil 19, so 19 cannot be trimmed below.
    d = call(c, current=19.0, dev=-1.0, open_pct=100.0, dew=14.1, limit=16.1,
             supply=19.0, now=5_000.0)
    assert d.target is None
    assert d.kind == BLOCKED and d.demand_unmet


def test_a_satisfied_house_at_the_limit_is_not_an_alarm(sp):
    """The mirror case. Backing off and finding the bound already reached is
    ordinary, not a shortfall - alarming on it would train the operator to
    ignore the alarm."""
    c = sp()
    d = call(c, mode="cooling", dev=0.0, open_pct=10.0, current=25.0,
             dew=12.0, limit=14.0, supply=25.0, now=5_000.0)
    assert d.target is None and not d.demand_unmet


def test_a_plant_change_invalidates_the_constraint_memory(sp):
    """The memory reasons about machine behaviour but watches only the dew
    point for release, so a change to the machine must invalidate it
    explicitly.

    Measured 2026-07-29: clearing powerful_mode took the compressor from 85-89
    Hz bursts to a steady 39-40 Hz and the spread from 4.7-5.8 K to 1.9-2.5 K.
    Every recorded-infeasible setpoint became feasible with ~1.8 K to spare,
    while the dew point barely moved - so nothing would have released the
    block, and the plant would have sat needlessly warm.
    """
    c = sp()
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
    assert call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=14.7,
                now=2_000.0).kind == BLOCKED
    c.forget_constraint()               # the plant was reconfigured
    freed = call(c, current=19.0, dev=-1.0, open_pct=100.0, limit=14.7,
                 now=4_000.0)
    assert freed.target == 18 and freed.kind == TRIM


# ---------- dynamic, spread-aware cooling floor ----------

def test_the_cooling_floor_tracks_the_MEASURED_spread_not_a_constant(sp):
    """The setpoint targets RETURN water; condensation is about the water
    reaching the slab. So the floor must be the condensation limit plus however
    far below the setpoint the leaving water actually lands - the machine's
    measured delta-T.

    Measured 2026-07-29: the spread moved from 5.8 K to 2.0 K within an hour on
    two register writes (F10 and powerful_mode). No constant can track that,
    which is why the earlier attempt to tune one was withdrawn.
    """
    wide = sp()
    for _ in range(5):
        wide.observe_spread(5.8)
    narrow = sp()
    for _ in range(5):
        narrow.observe_spread(2.0)
    limit = 16.2
    floor_wide = wide._clamp("cooling", 5.0, dew_point=14.2, supply_limit=limit)
    floor_narrow = narrow._clamp("cooling", 5.0, dew_point=14.2,
                                 supply_limit=limit)
    assert floor_wide > floor_narrow, "the floor must follow the spread"
    # Each must place leaving water at or above the condensation limit.
    assert floor_wide - 5.8 >= limit - 0.5
    assert floor_narrow - 2.0 >= limit - 0.5


def test_the_spread_estimate_rises_at_once_and_relaxes_slowly(sp):
    """A decaying MAXIMUM, not an average. This feeds a safety floor, so it
    must jump the moment the machine produces a wide spread; an average would
    sit mid-distribution and let half of all excursions through."""
    c = sp()
    c.observe_spread(2.0)
    c.observe_spread(6.0)
    assert c.spread_estimate == pytest.approx(6.0)   # instant rise
    for _ in range(20):
        c.observe_spread(2.0)
    assert 2.0 < c.spread_estimate < 6.0             # slow relaxation


def test_an_idle_compressor_does_not_erase_the_floor(sp):
    """With the compressor off the spread collapses to ~0. Sampling that would
    remove the floor exactly when the next start is about to produce a real
    spread - so `None` must be ignored, not treated as zero."""
    c = sp()
    for _ in range(5):
        c.observe_spread(5.0)
    before = c.spread_estimate
    for _ in range(50):
        c.observe_spread(None)
    assert c.spread_estimate == before


def test_the_static_offset_survives_as_a_backstop_before_any_measurement(sp):
    """Start-up, and any moment the limit is unknown: there is no estimate yet,
    so the old constant must still hold the line rather than leaving no floor
    at all."""
    c = sp()
    assert c.spread_estimate is None
    floor = c._clamp("cooling", 5.0, dew_point=12.0, supply_limit=14.0)
    assert floor >= 12.0 + c.dew_floor_offset_c


def test_the_dynamic_floor_can_only_tighten_the_static_one(sp):
    """Taken with max(), so a small measured spread can never relax the floor
    below the static backstop - the two are belt and braces, not alternatives."""
    c = sp()
    for _ in range(5):
        c.observe_spread(1.0)                       # very narrow
    floor = c._clamp("cooling", 5.0, dew_point=12.0, supply_limit=14.0)
    assert floor >= 12.0 + c.dew_floor_offset_c


def test_the_spread_estimate_is_bounded(sp):
    """A garbage reading must not be able to drive the floor to absurdity."""
    c = sp()
    c.observe_spread(500.0)
    assert c.spread_estimate == c.spread_max_c
    d = sp()
    d.observe_spread(-3.0)                          # sign confusion upstream
    assert d.spread_estimate == pytest.approx(3.0)


def test_the_breach_branch_reads_the_precise_manifold_sensor(sp):
    """The trim and the safety guard must answer "is the water reaching the
    slab dangerous" from the SAME sensor.

    The trim used to read the heat pump's leaving-water register, scaled 0.5 and
    so quantised to 0.5 K, while Safety.apply reads vl_total - a manifold PT1000
    at 0.1 K. Two controllers on the same physical question at different
    resolutions can disagree about whether a breach is happening, quite apart
    from the precision loss. This asserts the trim reacts at 0.1 K granularity,
    which is only possible on the manifold sensor.
    """
    c = sp()
    limit = 15.0
    # 0.1 K below the limit: invisible to a 0.5 K-quantised reading.
    d = call(c, current=19.0, supply=14.9, limit=limit, dew=14.0, now=5_000.0)
    assert d.kind == BREACH, "a 0.1 K breach must be seen"
    assert "supply 14.9" in d.reason


def test_a_breach_is_not_declared_on_the_limit_itself(sp):
    """Strictly below, so sitting exactly on the limit is not a breach - the
    release hysteresis (D-023) exists precisely because load compensation parks
    the supply there on purpose."""
    c = sp()
    d = call(c, current=19.0, supply=15.0, limit=15.0, dew=14.0, now=5_000.0)
    assert d.kind != BREACH
