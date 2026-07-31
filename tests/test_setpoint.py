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
            "breach_jump_c": 6.0, **over,
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
    """RETARGETED 2026-07-31: the cadence is now regime-dependent.

    `call()` drives the SATURATED case - house too warm, valves wide - which
    moves at the plant's 1-3 min response rather than the slab's half hour.
    The comfort-trimming cadence is covered below.
    """
    c = sp()
    assert call(c, now=10_000.0).target is not None
    assert call(c, now=10_000.0 + 119).target is None
    assert call(c, now=10_000.0 + 121, current=19.0).target is not None


def test_the_slow_cadence_still_applies_when_only_trimming_for_comfort(sp):
    """The half hour was never wrong - it was applied to the wrong regime.

    Backing the water off because the house is satisfied is a comfort/COP
    decision on a slab with hours of thermal mass, and it keeps the slow
    cadence. Mutation-verified: using the saturated interval here lets it
    trim at 121 s and this fails.
    """
    c = sp()
    # satisfied and idle -> the "water is more aggressive than needed" branch
    assert call(c, dev=0.0, open_pct=10.0, now=10_000.0).target is not None
    assert call(c, dev=0.0, open_pct=10.0, now=10_000.0 + 200).target is None
    assert call(c, dev=0.0, open_pct=10.0,
                now=10_000.0 + 1801).target is not None


def test_holding_does_not_start_the_clock(sp):
    """Only an actual change should cost us the next half hour."""
    c = sp()
    call(c, open_pct=55.0, now=10_000.0)                   # hold
    assert call(c, open_pct=95.0, now=10_000.0 + 5).target is not None


# ---------- the condensation branch bypasses everything ----------

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

def test_without_a_measured_spread_the_dew_point_alone_floors_nothing(sp):
    """The counterpart, and the point of removing the static offset: a dew
    point on its own is NOT a floor on P04, because P04 targets RETURN water
    and the gap to leaving water is the machine's spread - which is dynamic and
    must be measured, not assumed."""
    c = sp()
    assert c.spread_estimate is None
    d = call(c, mode="cooling", dev=-2.0, open_pct=95.0, current=19.0, dew=15.0)
    assert d.target is not None and d.target < 19


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
    # `call()` is the saturated regime, so the wait is the plant cadence
    # (2026-07-31). The property under test - that a restart does not trim
    # immediately, so a restart LOOP cannot hammer the flash - is unchanged.
    assert call(c, now=50_000.0 + 119).target is None
    assert call(c, now=50_000.0 + 121).target is not None


# ---------- trim behaviour ----------

def test_a_less_aggressive_setpoint_is_still_allowed(sp):
    """Blocking 18 must not block 20. Only setpoints at or below the rejected
    one are known-infeasible; blocking everything would strand the plant."""
    c = sp()
    call(c, current=18.0, supply=14.5, limit=14.7, dew=12.7, now=0.0)
    d = call(c, current=21.0, dev=-1.0, open_pct=100.0, limit=14.7, now=2_000.0)
    assert d.target == 20 and d.kind == TRIM


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


def test_a_satisfied_house_at_the_limit_is_not_an_alarm(sp):
    """The mirror case. Backing off and finding the bound already reached is
    ordinary, not a shortfall - alarming on it would train the operator to
    ignore the alarm."""
    c = sp()
    d = call(c, mode="cooling", dev=0.0, open_pct=10.0, current=25.0,
             dew=12.0, limit=14.0, supply=25.0, now=5_000.0)
    assert d.target is None and not d.demand_unmet


# ---------- dynamic, spread-aware cooling floor ----------

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


def test_there_is_no_static_floor_before_any_measurement(sp):
    """REPLACES a test asserting the opposite. The static `dew_floor_offset_c`
    backstop is GONE, not demoted (D-030, owner's instruction, 2026-07-31).

    Before any spread is measured the cooling floor is just `cooling_min_c`.
    That is deliberate: the trim moves 1 K per 30 min so the setpoint cannot
    travel far, the spread estimate populates within seconds of the compressor
    running, and the capacity controller and valve guard both act on MEASURED
    supply regardless of what the setpoint asked for.

    Mutation-verified: reinstating `lo = max(lo, dew_point + 4.0)` makes this
    return 16 and the assertion fails.
    """
    c = sp()
    assert c.spread_estimate is None
    assert not hasattr(c, "dew_floor_offset_c")
    floor = c._clamp("cooling", 5.0, dew_point=12.0, supply_limit=14.0)
    assert floor == c.cooling_min_c


def test_the_spread_estimate_is_bounded(sp):
    """A garbage reading must not be able to drive the floor to absurdity."""
    c = sp()
    c.observe_spread(500.0)
    assert c.spread_estimate == c.spread_max_c
    d = sp()
    d.observe_spread(-3.0)                          # sign confusion upstream
    assert d.spread_estimate == pytest.approx(3.0)


def test_a_breach_is_not_declared_on_the_limit_itself(sp):
    """Strictly below, so sitting exactly on the limit is not a breach - the
    release hysteresis (D-023) exists precisely because load compensation parks
    the supply there on purpose."""
    c = sp()
    d = call(c, current=19.0, supply=15.0, limit=15.0, dew=14.0, now=5_000.0)
    assert d.kind != BREACH


def test_the_same_guard_holds_in_the_heating_direction(sp):
    """Symmetric: an upper bound must not be able to push heating water down
    while the branch is asking for more heat."""
    c = sp(heating_max_c=25.0)
    d = call(c, mode="heating", dev=+1.0, open_pct=95.0, current=30.0,
             limit=None, now=1e7)
    assert d.target is None or d.target >= 30.0


def test_a_legitimate_clamped_step_is_still_taken(sp):
    """The guard must only block REVERSALS, not a step that simply lands short
    of the full 1 K - otherwise the trim stops working near the floor."""
    c = sp()
    c.observe_spread(1.7)
    d = call(c, current=20.0, dev=-1.01, open_pct=100.0, dew=13.3,
             supply=16.0, limit=14.3, now=1e7)
    assert d.target == 19 and d.kind == TRIM


