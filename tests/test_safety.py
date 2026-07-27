"""Safety rules. Project convention: every safety rule gets a test.

The point of these is not coverage, it is the DIRECTION of each failure. The
policy is deliberately asymmetric - fail OPEN on lost knowledge, fail CLOSED on
known-bad supply - so a test that only asserted "safety overrode the control
output" would pass just as happily with the directions swapped, which is the
one mistake that actually burns a screed or wets a floor.
"""
from __future__ import annotations

from heatctl.backends.base import IOState
from heatctl.safety import Safety


def state(**temps) -> IOState:
    s = IOState()
    s.temps = dict(temps)
    return s


# ---------- clamp_setpoint: the layer-2 boundary ----------

def test_clamp_setpoint_holds_the_layer2_boundary(cfg):
    s = Safety(cfg)
    assert s.clamp_setpoint(21.0) == 21.0          # inside: untouched
    assert s.clamp_setpoint(99.0) == 28.0          # above max
    assert s.clamp_setpoint(-40.0) == 15.0         # below min
    # Exactly on the bounds must be allowed, not rejected.
    assert s.clamp_setpoint(15.0) == 15.0
    assert s.clamp_setpoint(28.0) == 28.0


# ---------- FAIL OPEN: lost knowledge ----------

def test_sensor_fault_fails_open(cfg):
    s = Safety(cfg)
    st = state(rl_hk01=22.0, vl_total=30.0)
    st.faults.add("rl_hk01")
    pct, reason = s.apply("heating", st, "rl_hk01", 0.0)
    assert pct == cfg["safety"]["failsafe_valve_pct"] == 100
    assert reason == "sensor_fault:rl_hk01"


def test_missing_return_temperature_fails_open(cfg):
    """A sensor absent from temps is the same lost knowledge as a fault."""
    s = Safety(cfg)
    pct, reason = s.apply("heating", state(vl_total=30.0), "rl_hk01", 0.0)
    assert pct == 100
    assert reason == "sensor_fault:rl_hk01"


def test_frost_protection_forces_full_open(cfg):
    s = Safety(cfg)
    pct, reason = s.apply("heating", state(rl_hk01=5.9, vl_total=30.0),
                          "rl_hk01", 0.0)
    assert (pct, reason) == (100.0, "frost_protect")


def test_frost_protection_wins_over_supply_overtemp(cfg):
    """Ordering matters: freezing pipes beat a hot screed.

    Both rules can be true at once (frost-cold return, scalding supply). Frost
    must win, because a burst pipe is unrecoverable and a warm screed is not.
    """
    s = Safety(cfg)
    st = state(rl_hk01=2.0, vl_total=60.0)   # frost AND overtemp
    assert s.apply("heating", st, "rl_hk01", 0.0) == (100.0, "frost_protect")


def test_frost_threshold_is_exclusive(cfg):
    """At exactly the threshold we are not yet in frost protection."""
    s = Safety(cfg)
    _, reason = s.apply("heating", state(rl_hk01=6.0, vl_total=30.0),
                        "rl_hk01", 42.0)
    assert reason is None


# ---------- FAIL CLOSED: known-bad supply ----------

def test_supply_overtemp_in_heating_fails_closed(cfg):
    """Screed protection. Must be 0, NOT the fail-open position."""
    s = Safety(cfg)
    pct, reason = s.apply("heating", state(rl_hk01=25.0, vl_total=45.1),
                          "rl_hk01", 100.0)
    assert (pct, reason) == (0.0, "vl_overtemp")


def test_supply_undertemp_in_cooling_fails_closed(cfg):
    """Condensation guard. Must be 0, NOT the fail-open position."""
    s = Safety(cfg)
    pct, reason = s.apply("cooling", state(rl_hk01=20.0, vl_total=15.9),
                          "rl_hk01", 100.0)
    assert (pct, reason) == (0.0, "vl_undertemp")


def test_supply_limits_are_mode_specific(cfg):
    """The two supply rules must not leak into the wrong mode.

    A 15.9 C supply is a condensation risk in cooling and completely normal in
    heating; 45.1 C is a screed risk in heating and impossible-but-harmless in
    cooling. Applying either rule in both modes would deadlock the plant.
    """
    s = Safety(cfg)
    # cold supply, heating mode -> no override
    assert s.apply("heating", state(rl_hk01=20.0, vl_total=15.9),
                   "rl_hk01", 55.0) == (55.0, None)
    # hot supply, cooling mode -> no override
    assert s.apply("cooling", state(rl_hk01=20.0, vl_total=45.1),
                   "rl_hk01", 55.0) == (55.0, None)


def test_supply_thresholds_are_exclusive(cfg):
    """Exactly at the limit is still allowed; only beyond it trips."""
    s = Safety(cfg)
    assert s.apply("heating", state(rl_hk01=25.0, vl_total=45.0),
                   "rl_hk01", 70.0) == (70.0, None)
    assert s.apply("cooling", state(rl_hk01=20.0, vl_total=16.0),
                   "rl_hk01", 70.0) == (70.0, None)


def test_missing_supply_sensor_does_not_trip_the_closed_rules(cfg):
    """No supply reading must not be mistaken for a bad supply reading.

    Failing closed here would shut the whole house on a single dead sensor,
    which is the wrong direction for lost knowledge.
    """
    s = Safety(cfg)
    assert s.apply("heating", state(rl_hk01=25.0), "rl_hk01", 60.0) == (60.0, None)
    assert s.apply("cooling", state(rl_hk01=25.0), "rl_hk01", 60.0) == (60.0, None)


# ---------- pass-through ----------

def test_healthy_state_passes_control_through_untouched(cfg):
    s = Safety(cfg)
    st = state(rl_hk01=24.0, vl_total=32.0)
    assert s.apply("heating", st, "rl_hk01", 37.5) == (37.5, None)
