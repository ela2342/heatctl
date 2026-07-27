"""Safety rules. Project convention: every safety rule gets a test.

The point of these is not coverage, it is the DIRECTION of each failure. The
policy is deliberately asymmetric - fail OPEN on lost knowledge, fail CLOSED on
known-bad supply - so a test that only asserted "safety overrode the control
output" would pass just as happily with the directions swapped, which is the
one mistake that actually burns a screed or wets a floor.
"""
from __future__ import annotations

import pytest

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
    s.set_dew_point(14.0)                      # limit 16.0
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
    s.set_dew_point(11.0)
    # cold supply, heating mode -> no override
    assert s.apply("heating", state(rl_hk01=20.0, vl_total=15.9),
                   "rl_hk01", 55.0) == (55.0, None)
    # hot supply, cooling mode -> no override
    assert s.apply("cooling", state(rl_hk01=20.0, vl_total=45.1),
                   "rl_hk01", 55.0) == (55.0, None)


def test_supply_thresholds_are_exclusive(cfg):
    """Exactly at the limit is still allowed; only beyond it trips."""
    s = Safety(cfg)
    s.set_dew_point(14.0)                      # limit 16.0
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
    s.set_dew_point(11.0)
    assert s.apply("heating", state(rl_hk01=25.0), "rl_hk01", 60.0) == (60.0, None)
    assert s.apply("cooling", state(rl_hk01=25.0), "rl_hk01", 60.0) == (60.0, None)


# ---------- pass-through ----------

def test_healthy_state_passes_control_through_untouched(cfg):
    s = Safety(cfg)
    st = state(rl_hk01=24.0, vl_total=32.0)
    assert s.apply("heating", st, "rl_hk01", 37.5) == (37.5, None)


# ---------- dew-point supervision ----------

def test_without_a_dew_point_the_static_limit_applies(cfg):
    """Layer 1 must work with no broker at all - that is the whole premise."""
    s = Safety(cfg)
    assert s.cooling_supply_limit() == 16.0


def test_a_fresh_dew_point_replaces_the_static_limit(cfg):
    """It cuts BOTH ways, which is the point.

    Dry air permits colder supply than the static guess allows (measured
    2026-07-27: dew point 12.7 against a 16.0 static limit was shutting
    circuits in no danger); humid air forbids supply the static value would
    have permitted.
    """
    s = Safety(cfg)
    s.set_dew_point(12.7)
    assert s.cooling_supply_limit() == pytest.approx(14.7)   # relaxed
    s.set_dew_point(15.5)
    assert s.cooling_supply_limit() == pytest.approx(17.5)   # tightened


def test_a_stale_dew_point_falls_back_to_the_static_limit(cfg):
    s = Safety(cfg)
    now = 10_000.0
    s.set_dew_point(12.7, now=now)
    assert s.cooling_supply_limit(now=now + 899) == pytest.approx(14.7)
    assert s.cooling_supply_limit(now=now + 901) == 16.0


def test_a_dew_point_cannot_authorise_below_the_hard_floor(cfg):
    """Bounds the damage from a stuck-low humidity sensor."""
    s = Safety(cfg)
    s.set_dew_point(-40.0)
    assert s.cooling_supply_limit() == cfg["safety"]["vl_min_cooling_floor_c"]


def test_set_dew_point_ignores_none(cfg):
    """'No new reading' must not erase the last good one."""
    s = Safety(cfg)
    s.set_dew_point(12.7)
    s.set_dew_point(None)
    assert s.cooling_supply_limit() == pytest.approx(14.7)


def test_cooling_stops_when_the_dew_point_is_unknown(cfg):
    """Condensation is the one limit that cannot be bounded without measuring
    the air, so no reading means no cooling - NOT a fall back to the static
    guess, which is not conservative anyway (a 26 degC room at 60 % RH has a
    dew point of 17.6 degC, above the 16.0 static value).

    This also covers the case the HA-side automation cannot: if the dew point
    is missing because Home Assistant died, its source-side pump shutdown died
    with it and this is the only protection left.
    """
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=25.0)    # supply nowhere near dew point
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (0.0, "dew_point_unknown")


def test_a_stale_dew_point_also_stops_cooling(cfg):
    """Stale must read as absent - a dew point from an hour ago says nothing
    about the air now, and acting on it is how the guard gets defeated."""
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=25.0)
    s.set_dew_point(11.0)
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (60.0, None)
    s._dew_ts -= cfg["safety"]["dew_point_max_age_s"] + 1
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (0.0, "dew_point_unknown")


def test_an_unknown_dew_point_does_not_stop_heating(cfg):
    """Heating has no condensation risk; stopping it would be a bug."""
    s = Safety(cfg)
    assert s.apply("heating", state(rl_hk01=20.0, vl_total=30.0),
                   "rl_hk01", 60.0) == (60.0, None)


def test_requiring_a_dew_point_can_be_switched_off(cfg):
    """For a deployment with no dew-point source, the static limit is all
    there is - the behaviour before 2026-07-27."""
    cfg["safety"]["cooling_requires_dew_point"] = False
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=25.0)
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (60.0, None)
    assert s.apply("cooling", state(rl_hk01=20.0, vl_total=15.9),
                   "rl_hk01", 60.0) == (0.0, "vl_undertemp")


def test_frost_protection_still_outranks_the_dew_point_rule(cfg):
    """A burst pipe is unrecoverable; a missing dew point is not."""
    s = Safety(cfg)
    assert s.apply("cooling", state(rl_hk01=2.0, vl_total=25.0),
                   "rl_hk01", 0.0) == (100.0, "frost_protect")


# ---------- rule ORDER: known-bad supply outranks a faulted circuit sensor ----------

def test_a_faulted_circuit_sensor_does_not_defeat_the_condensation_guard(cfg):
    """Real ordering defect, fixed 2026-07-27.

    Fail-open used to be checked first, so one faulted return sensor forced
    its circuit open even while the SUPPLY was measurably below the dew point.
    The two sensors are unrelated: a dead return sensor says nothing about
    whether the supply water is safe, and opening into water known to condense
    is the actively harmful choice.
    """
    s = Safety(cfg)
    s.set_dew_point(14.0)                      # limit 16.0
    st = state(vl_total=15.0)                  # supply known bad
    st.faults.add("rl_hk01")                   # and the circuit sensor is dead
    assert s.apply("cooling", st, "rl_hk01", 50.0) == (0.0, "vl_undertemp")


def test_a_faulted_circuit_sensor_does_not_defeat_screed_protection(cfg):
    s = Safety(cfg)
    st = state(vl_total=60.0)
    st.faults.add("rl_hk01")
    assert s.apply("heating", st, "rl_hk01", 50.0) == (0.0, "vl_overtemp")


def test_a_faulted_sensor_still_fails_open_when_the_supply_is_fine(cfg):
    """The reordering must not quietly turn fail-open into fail-closed."""
    s = Safety(cfg)
    st = state(vl_total=30.0)
    st.faults.add("rl_hk01")
    assert s.apply("heating", st, "rl_hk01", 50.0) == (100, "sensor_fault:rl_hk01")


def test_the_condensation_guard_uses_the_live_limit(cfg):
    """End to end: the same supply is safe on dry air and not on humid air."""
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=15.0)

    s.set_dew_point(11.0)                      # limit 13.0 -> 15.0 is fine
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (60.0, None)

    s.set_dew_point(14.0)                      # limit 16.0 -> 15.0 is not
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (0.0, "vl_undertemp")


def test_a_missing_dew_point_does_not_stop_heating(cfg):
    """Only cooling requires a dew point.

    Note this is NOT "heating ignores the dew point" - it used to be, until
    2026-07-27. The condensation guard now applies in any mode when the supply
    is measurably below the limit, because heatctl's mode and the heat pump's
    mode are separate things. What heating does not need is a dew point in
    order to run at all.
    """
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=30.0)
    assert s.apply("heating", st, "rl_hk01", 60.0) == (60.0, None)


def test_the_condensation_guard_is_scoped_to_cooling(cfg):
    """Owner's call, 2026-07-27. A cold supply in HEATING is not a
    condensation event to act on - it is a plant that has not warmed up yet,
    and closing valves there would block the house heating.

    The divergence risk that argued for a mode-independent guard is instead
    handled by detecting a disagreement between heatctl's mode and the pump's
    own mode register, which heatctl now reads.
    """
    s = Safety(cfg)
    s.set_dew_point(14.0)                      # limit 16.0
    st = state(rl_hk01=20.0, vl_total=15.0)    # cold supply
    assert s.apply("heating", st, "rl_hk01", 60.0) == (60.0, None)
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (0.0, "vl_undertemp")


def test_heating_still_runs_without_any_dew_point(cfg):
    """Only cooling requires a dew point; heating must not be stopped by a
    missing one."""
    s = Safety(cfg)
    st = state(rl_hk01=22.0, vl_total=30.0)
    assert s.apply("heating", st, "rl_hk01", 60.0) == (60.0, None)
