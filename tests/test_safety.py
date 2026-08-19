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

def test_without_a_dew_point_there_is_no_limit_at_all(cfg):
    """Layer 1 must work with no broker at all - that is the whole premise."""
    s = Safety(cfg)
    # None, not a number. REPLACES a test asserting the static 16.0 fallback,
    # removed 2026-07-31: that value sat BELOW the live limit on a normal
    # summer afternoon, so losing the dew point RELAXED the constraint. Callers
    # must treat None as "do not cool" rather than substituting anything.
    assert s.cooling_supply_limit() is None


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


def test_a_stale_dew_point_yields_no_limit(cfg):
    s = Safety(cfg)
    now = 10_000.0
    s.set_dew_point(12.7, now=now)
    assert s.cooling_supply_limit(now=now + 899) == pytest.approx(14.7)
    assert s.cooling_supply_limit(now=now + 901) is None


def test_the_limit_tracks_the_dew_point_with_no_lower_floor(cfg):
    """D-024: the `vl_min_cooling_floor_c` clamp was REMOVED 2026-07-28.

    It never once bound in ten days of recorded data (dew point 11.2-15.1,
    so a limit of 13.2-17.1 against a 12.0 floor), and it could not do the
    job its comment claimed. A floor low enough to permit useful cooling is
    not safe - 12 degC dew point is an ordinary 22 degC at 53 % RH - and one
    high enough to be safe blocks cooling, which is the static limit this
    whole mechanism replaced.

    This test exists to stop it being reintroduced by reflex. If a bad
    reading needs bounding, bound the READING (plausibility, cross-room
    agreement, staleness), not the limit computed from it - clamping the
    output just moves a wrong number somewhere harder to see.
    """
    s = Safety(cfg)
    s.set_dew_point(5.0)
    assert s.cooling_supply_limit() == pytest.approx(7.0)


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

    RETARGETED 2026-08-01: the refusal moved from the VALVES to the SOURCE.
    heatctl now commands the compressor OFF itself over Modbus while the dew
    point is unknown (see `Controller._trim_capacity`), which does not depend
    on Home Assistant either - so the concern in the paragraph above is still
    answered, by an actuator that can actually stop cold water being made.

    Closing valves could never do that: it cannot stop the compressor, and it
    starved the pump into a latched Er03 on every restart, because the dew
    point arrives over MQTT ~30 s after start-up. Measured 2026-08-01.

    So at THIS layer the assertion is now the opposite: valve position is left
    exactly as control proposed. The source-side half is asserted in
    tests/test_controller.py.
    """
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=25.0)    # supply nowhere near dew point
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (60.0, None)


def test_a_stale_dew_point_also_stops_cooling(cfg):
    """Stale must read as absent - a dew point from an hour ago says nothing
    about the air now, and acting on it is how the guard gets defeated."""
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=25.0)
    s.set_dew_point(11.0)
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (60.0, None)
    s._dew_ts -= cfg["safety"]["dew_point_max_age_s"] + 1
    # RETARGETED 2026-08-01 with the rest of the dew-point-unknown handling:
    # staleness still reads as absent, but "absent" now stops the SOURCE rather
    # than the valves. Asserted here only that the valves are not touched; the
    # compressor-off half lives in tests/test_controller.py.
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (60.0, None)
    assert not s.dew_point_known()


def test_an_unknown_dew_point_does_not_stop_heating(cfg):
    """Heating has no condensation risk; stopping it would be a bug."""
    s = Safety(cfg)
    assert s.apply("heating", state(rl_hk01=20.0, vl_total=30.0),
                   "rl_hk01", 60.0) == (60.0, None)


def test_there_is_no_way_to_switch_the_dew_point_requirement_off(cfg):
    """REPLACES a test that exercised `cooling_requires_dew_point: False`.

    That flag chose between stopping and trusting a made-up static limit; both
    it and the static limit were removed on 2026-07-31. Without a dew point the
    condensation limit is unknowable, so cooling stops - there is no setting
    that says otherwise, and a config carrying the old key must not silently
    re-enable anything.
    """
    cfg["safety"]["cooling_requires_dew_point"] = False      # stale key
    s = Safety(cfg)
    st = state(rl_hk01=20.0, vl_total=25.0)
    # RETARGETED 2026-08-01: the refusal moved to the SOURCE, so what must be
    # unfalsifiable here is that the dew point is still reported as UNKNOWN
    # whatever stale keys a config carries - that is the signal main.py acts
    # on to command the compressor off. The valves are deliberately untouched.
    assert not s.dew_point_known()
    assert s.apply("cooling", st, "rl_hk01", 60.0) == (60.0, None)


def test_frost_protection_still_outranks_the_dew_point_rule(cfg):
    """A burst pipe is unrecoverable; a missing dew point is not."""
    s = Safety(cfg)
    assert s.apply("cooling", state(rl_hk01=2.0, vl_total=25.0),
                   "rl_hk01", 0.0) == (100.0, "frost_protect")


# ---------- rule ORDER: known-bad supply outranks a faulted circuit sensor ----------

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


def test_heating_still_runs_without_any_dew_point(cfg):
    """Only cooling requires a dew point; heating must not be stopped by a
    missing one."""
    s = Safety(cfg)
    st = state(rl_hk01=22.0, vl_total=30.0)
    assert s.apply("heating", st, "rl_hk01", 60.0) == (60.0, None)


# ---------- release hysteresis on the condensation guard (D-023) ----------

def test_an_untripped_guard_does_not_hold_the_margin_against_control(cfg):
    """The margin applies only after a trip.

    Without the latch check a supply sitting between the limit and the margin
    would be treated as bad, silently tightening the condensation limit by
    the release margin for every circuit, all the time.
    """
    s = Safety(cfg)
    s.set_dew_point(12.5)                                  # guard trips at 12.5
    assert s.apply("cooling", state(rl_hk01=20.0, vl_total=12.6),
                   "rl_hk01", 80.0) == (80.0, None)




# ---------- condensation is a SOURCE-side rule, not a valve rule ----------
#
# Ten tests were removed here on 2026-08-10, all asserting that a
# below-dew-point supply forces every owned valve to 0 %. They were correct
# about the behaviour they described and several were mutation-verified; the
# POLICY changed, not the code's fidelity to it. Owner: "the risk of triggering
# Er03 and leading to an unrecoverable state is too high. Shutting down the
# compressor is the only legitimate mechanism."
#
# Their arguments are carried into the tests below wherever they still apply,
# because the reasoning outlived the rule.

def test_a_supply_below_the_dew_point_does_NOT_close_valves(cfg):
    """THE DIRECTION THAT MATTERS, and the inverse of what this file asserted
    until 2026-08-10.

    Shutting valves cannot reach the compressor. It removes the load, collapses
    flow and starves the unit into Er03, which latches and needs a person at the
    machine - trading a wet floor for a dead plant in summer. Screed overtemp
    keeps failing closed because there closing genuinely removes the danger: a
    hot slab is already hot and the mass carries the rest.
    """
    s = Safety(cfg)
    s.set_dew_point(15.0, now=0.0)
    st = state(rl_hk01=20.0, vl_total=10.0)        # 5 K below the dew point
    assert s.apply("cooling", st, "rl_hk01", 100.0, now=1.0) == (100.0, None)
    # and it stays open however long it persists - there is no dwell any more
    assert s.apply("cooling", st, "rl_hk01", 100.0,
                   now=100_000.0) == (100.0, None)


def test_screed_overtemp_still_fails_closed(cfg):
    """The asymmetry is deliberate and physical. Do not "make everything fail
    open" any more than the reverse."""
    s = Safety(cfg)
    st = state(rl_hk01=20.0,
               vl_total=cfg["safety"]["vl_max_heating_c"] + 1.0)
    assert s.apply("heating", st, "rl_hk01", 100.0) == (0.0, "vl_overtemp")


def test_the_live_condensation_limit_survives_the_removal(cfg):
    """`cooling_supply_limit()` is the useful half of the guard and is what
    capacity.py regulates against. Removing the valve action must not remove the
    limit - that would leave the source side with nothing to aim at.

    Inherited from the deleted `test_the_condensation_guard_uses_the_live_limit`.
    """
    s = Safety(cfg)
    m = cfg["safety"]["dew_point_margin_c"]
    s.set_dew_point(14.0, now=0.0)
    assert s.cooling_supply_limit(now=1.0) == pytest.approx(14.0 + m)
    s.set_dew_point(18.0, now=2.0)
    assert s.cooling_supply_limit(now=3.0) == pytest.approx(18.0 + m)


def test_an_unknown_dew_point_yields_no_limit_and_still_moves_no_valve(cfg):
    """Two halves of the same 2026-08-01 decision, now consistent with the
    2026-08-10 one: an absent dew point produces no limit, so callers must
    refuse to cool at the SOURCE, and it produces no valve action either."""
    s = Safety(cfg)
    assert s.cooling_supply_limit(now=1.0) is None
    st = state(rl_hk01=20.0, vl_total=10.0)
    assert s.apply("cooling", st, "rl_hk01", 100.0, now=1.0) == (100.0, None)


def test_a_faulted_return_sensor_still_fails_open_under_a_cold_supply(cfg):
    """Inherited from `test_a_faulted_circuit_sensor_does_not_defeat_the_
    condensation_guard`, with the expectation inverted.

    That test defended an ORDERING property: known-bad-supply rules run before
    the fail-open rule, so an unrelated sensor fault could not defeat
    condensation protection. With no condensation valve rule left there is
    nothing to defeat, and D-003 governs alone - lost knowledge fails OPEN. The
    ordering itself still matters for screed overtemp, covered above.
    """
    s = Safety(cfg)
    s.set_dew_point(15.0, now=0.0)
    st = state(rl_hk01=20.0, vl_total=10.0)
    st.faults.add("rl_hk01")
    pct, reason = s.apply("cooling", st, "rl_hk01", 100.0, now=1.0)
    assert pct == cfg["safety"]["failsafe_valve_pct"]
    assert reason == "sensor_fault:rl_hk01"


def test_frost_protection_still_outranks_everything(cfg):
    """Re-asserted here because the branch below it moved: a burst pipe is
    unrecoverable, so frost wins even against a supply far below the dew
    point."""
    s = Safety(cfg)
    s.set_dew_point(15.0, now=0.0)
    st = state(rl_hk01=cfg["safety"]["frost_protect_c"] - 1.0, vl_total=10.0)
    assert s.apply("cooling", st, "rl_hk01", 0.0,
                   now=1.0) == (100.0, "frost_protect")
