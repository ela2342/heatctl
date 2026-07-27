"""Load compensation: house demand -> water temperature setpoint.

The loop that decides efficiency. Water colder than needed does not make the
house colder - the valves just throttle it back - so the error is invisible in
room temperature and shows up only as COP and condensation risk. Which is why
the "back off when the valves are barely open" branch matters as much as the
"not enough capacity" one, and is the half a naive implementation omits.
"""
from __future__ import annotations

import pytest

from heatctl.setpoint import BREACH, TRIM, SetpointController


@pytest.fixture
def sp(cfg):
    def _make(**over):
        cfg["control"]["water_setpoint"] = {
            "enabled": True, "interval_s": 1800.0, "step_c": 1.0,
            "saturated_pct": 85.0, "idle_pct": 30.0, "deviation_band_c": 0.3,
            "cooling_min_c": 14.0, "cooling_max_c": 25.0,
            "heating_min_c": 20.0, "heating_max_c": 40.0,
            "dew_floor_offset_c": 4.0, "breach_jump_c": 6.0, **over,
        }
        return SetpointController(cfg)
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
