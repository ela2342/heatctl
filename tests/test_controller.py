"""Controller wiring: mode handling, control paths, failsafe, telemetry.

These are the tests that would have caught the defects this project actually
hit. Every bug found so far was found by running the plant, not by reading the
code, so the bar here is "would this have failed before the fix".
"""
from __future__ import annotations

import time

import pytest


# ---------- REGRESSION (a), mandated by ROADMAP.md Milestone 1 ----------

def test_starting_in_cooling_from_config_inverts_the_pids(controller):
    """Real defect, 2026-07-26, found by a hardware test.

    `Controller.__init__` applied the mode to the return setpoints but not to
    `pid.invert`, so a controller configured with `mode: cooling` ran its PIDs
    in the heating direction: it opened valves when a room was too COLD. It
    looked completely healthy - plausible percentages, no errors - which is
    why only the plant revealed it.
    """
    ctl = controller(control={"mode": "cooling"})
    assert ctl.mode == "cooling"
    assert ctl.room_pids, "no room PIDs built - test is not checking anything"
    assert all(p.invert for p in ctl.room_pids.values())
    assert all(p.invert for p in ctl.circuit_pids.values())


def test_starting_in_heating_from_config_leaves_pids_uninverted(controller):
    ctl = controller(control={"mode": "heating"})
    assert not any(p.invert for p in ctl.room_pids.values())
    assert not any(p.invert for p in ctl.circuit_pids.values())


def test_config_mode_also_selects_the_return_setpoint(controller):
    """The half that was already right - assert it so it stays right."""
    assert controller(control={"mode": "heating"}).return_sp == 22.0
    assert controller(control={"mode": "cooling"}).return_sp == 20.0


def test_mode_command_switches_direction_and_setpoint_together(controller):
    """Mode must never be applied to one of the two and not the other."""
    ctl = controller(control={"mode": "heating"})
    ctl.on_command("mode", "", "cooling")
    assert ctl.mode == "cooling"
    assert ctl.return_sp == 20.0
    assert all(p.invert for p in ctl.circuit_pids.values())
    ctl.on_command("mode", "", "heating")
    assert ctl.return_sp == 22.0
    assert not any(p.invert for p in ctl.circuit_pids.values())


def test_mode_command_resets_integrators(controller):
    """A heating integral applied to cooling would drive the wrong way hard."""
    ctl = controller(control={"mode": "heating"})
    pid = next(iter(ctl.circuit_pids.values()))
    pid._i = 55.0
    ctl.on_command("mode", "", "cooling")
    assert pid._i == 0.0


def test_unknown_mode_command_is_ignored(controller):
    ctl = controller(control={"mode": "heating"})
    ctl.on_command("mode", "", "banana")
    assert ctl.mode == "heating"


# ---------- setpoint commands ----------

def test_setpoint_command_is_clamped_by_safety(controller):
    """Layer 2 may not exceed the safety bounds, by construction."""
    ctl = controller()
    ctl.on_command("setpoint", "gaestebad", "99")
    assert ctl.room_setpoints["gaestebad"] == 28.0
    ctl.on_command("setpoint", "gaestebad", "-5")
    assert ctl.room_setpoints["gaestebad"] == 15.0


def test_setpoint_command_for_unknown_room_is_ignored(controller):
    ctl = controller()
    before = dict(ctl.room_setpoints)
    ctl.on_command("setpoint", "narnia", "22")
    assert ctl.room_setpoints == before


# ---------- control paths ----------

async def test_room_pid_drives_every_circuit_of_that_room(controller):
    """One room output is applied to ALL circuits in the room."""
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 30.0, "rl_total": 24.0},
        room_temps={"wohnzimmer": 18.0},        # 3 K below the 21.0 default
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    w = ctl.io.last_write
    assert w["valve_hk02"] == w["valve_hk03"] > 0


async def test_circuit_falls_back_to_return_pid_without_a_room_sensor(controller):
    """No room temperature -> each circuit runs its own return-temp PID.

    With every `room_temp_topic` unset in the field config this is currently
    the ONLY live control path, so it matters more than the room path does.
    """
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 18.0, "rl_hk03": 24.0,
               "vl_total": 30.0, "rl_total": 22.0},
        room_temps={},                           # no room sensors at all
    )
    ctl.io.touch(time.monotonic())
    # Both circuits have been open long enough for RL to mean something -
    # otherwise the validity gate correctly refuses to use it (test_rl_gate).
    now = time.monotonic()
    for v in ("valve_hk02", "valve_hk03"):
        ctl.rl_gate.record_command(v, 100.0, now - 3600)

    await ctl.step(1.0)

    w = ctl.io.last_write
    # hk02 returns 18 C against a 22 C target in heating -> demand;
    # hk03 returns 24 C, already above target -> no demand of its own.
    # Note hk03 is NOT driven to 0: distribution normalises the set so the
    # most-demanding circuit is fully open, and a zero-demand circuit still
    # gets a trickle rather than being shut. Throttling costs flow, and flow
    # is what minimises the spread (distribution.py).
    assert w["valve_hk02"] > w["valve_hk03"]
    # hk01 has never had a trustworthy RL reading, so it fails open at 100 and
    # is therefore the peak the others are normalised against.
    assert w["valve_hk01"] == 100.0


async def test_circuit_with_no_return_reading_fails_open(controller):
    """Lost knowledge of a circuit opens it (see safety.py policy)."""
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk03": 24.0, "vl_total": 30.0},
        room_temps={},                           # rl_hk02 absent entirely
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.io.last_write["valve_hk02"] == 100


async def test_mode_off_closes_every_valve(controller):
    ctl = controller(
        control={"mode": "off"},
        temps={"rl_hk01": 24.0, "rl_hk02": 18.0, "rl_hk03": 18.0,
               "vl_total": 30.0},
        room_temps={"gaestebad": 15.0},          # would otherwise demand heat
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert set(ctl.io.last_write.values()) == {0.0}


async def test_safety_overrides_the_control_output(controller):
    """Control proposes, safety decides - end to end through step()."""
    ctl = controller(
        control={"mode": "cooling"},
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 12.0},                # below dew-point guard
        room_temps={"gaestebad": 28.0},          # maximum cooling demand
        dew_point=14.0,                          # limit 16.0
    )
    # Dwell neutralised: this test is about the override PROPAGATING, not
    # about when it fires. The 2026-08-01 trip dwell has its own tests in
    # test_safety.py; leaving it in would make these depend on wall time.
    ctl.safety.undertemp_dwell_s = 0.0
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.io.last_write["valve_hk01"] == 0.0
    assert ctl.plane.topic("override/valve_hk01") == "vl_undertemp"


# ---------- RL validity gating (present defect, docs/DESIGN.md 4) ----------

async def test_the_return_pid_is_not_fed_an_untrusted_rl(controller):
    """The defect: with no flow, the manifold-mounted RL sensor measures the
    manifold cabinet, not its circuit. Integrating that is how the circuit
    talks itself into staying shut."""
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 5.0, "rl_hk03": 24.0,
               "vl_total": 30.0},
        room_temps={},
    )
    ctl.io.touch(time.monotonic())
    pid = ctl.circuit_pids["rl_hk02"]

    await ctl.step(1.0)                       # valve was never open

    assert pid._i == 0.0, "integrated an RL reading that means nothing"


async def test_a_settled_open_circuit_is_controlled_normally(controller):
    """Gating must not disable control, only postpone it until RL is real."""
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 18.0, "rl_hk03": 24.0,
               "vl_total": 30.0},
        room_temps={},
    )
    ctl.io.touch(time.monotonic())
    now = time.monotonic()
    # Pretend the circuit has been open and settled for an hour.
    ctl.rl_gate.record_command("valve_hk02", 100.0, now - 3600)

    await ctl.step(1.0)

    assert ctl.io.last_write["valve_hk02"] > 0
    assert ctl.circuit_pids["rl_hk02"]._i != 0.0


async def test_an_unmeasured_circuit_fails_open(controller):
    """No trustworthy RL is lost knowledge - same policy as a dead sensor."""
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 30.0},
        room_temps={},
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.io.last_write["valve_hk02"] == 100


async def test_the_gate_records_what_safety_wrote_not_what_control_proposed(
        controller):
    """Safety changes real flow, so it must drive the validity clock too.

    RETARGETED 2026-08-01: this used to reach 0 % via `dew_point_unknown`,
    because it passed no dew point at all. That path was removed - an unknown
    dew point now stops the SOURCE and leaves valves alone - so the test was
    silently exercising a rule that no longer exists. Given a real dew point it
    trips on `vl_undertemp` instead, which is the same question it meant to ask.
    """
    ctl = controller(
        control={"mode": "cooling"},
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 12.0},              # condensation guard -> force 0
        room_temps={"gaestebad": 28.0},        # control wants 100 %
        dew_point=14.0,                        # guard trips at 14.0
    )
    # Dwell neutralised: this test is about the override PROPAGATING, not
    # about when it fires. The 2026-08-01 trip dwell has its own tests in
    # test_safety.py; leaving it in would make these depend on wall time.
    ctl.safety.undertemp_dwell_s = 0.0
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.io.last_write["valve_hk01"] == 0.0
    # Safety wrote 0, so the circuit must NOT be counted as opening.
    assert ctl.rl_gate._circuit("valve_hk01").open_since is None


async def test_the_room_pid_path_is_unaffected_by_gating(controller):
    """With a room sensor, RL is not consulted at all."""
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 30.0},
        room_temps={"gaestebad": 15.0},        # far below target -> full demand
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.io.last_write["valve_hk01"] == 100.0


# ---------- staleness / failsafe ----------

async def test_stale_data_triggers_the_failsafe_and_skips_control(controller):
    ctl = controller(temps={"rl_hk01": 24.0, "vl_total": 30.0})
    ctl.io.touch(time.monotonic() - 3600)        # far beyond the 15 s timeout
    await ctl.step(1.0)
    assert ctl.io.all_valve_writes == [100]      # failsafe_valve_pct
    assert ctl.io.writes == []                   # no per-circuit control ran
    assert ctl.plane.topic("override/global") == "stale_data"


async def test_failsafe_is_logged_once_not_once_per_cycle(controller, caplog):
    """Real defect, 2026-07-27: a persistent failsafe flooded the log.

    Staying in failsafe is one fact, not one fact per second. The flood pushed
    3.5 h of history - including the cause - out of the container's log ring
    before anyone could read it.
    """
    ctl = controller(temps={"rl_hk01": 24.0})
    ctl.io.touch(time.monotonic() - 3600)
    with caplog.at_level("WARNING", logger="heatctl"):
        for _ in range(50):
            await ctl.step(1.0)
    lines = [r for r in caplog.records if "FAILSAFE" in r.getMessage()]
    assert len(lines) == 1, f"{len(lines)} failsafe lines for 50 cycles"


async def test_an_unknown_dew_point_stops_the_source_not_the_valves(controller):
    """The 2026-08-01 replacement for `dew_point_unknown` closing valves.

    The old rule shut every owned valve until the first dew-point message
    arrived over MQTT - measured at 33 s on EVERY restart, which starves the
    pump into a latched Er03 that needs a person at the unit. It also inverted
    D-003 by failing CLOSED on lost knowledge.

    The refusal now happens where it can actually work: no dew point means no
    cold water is MADE. Closing valves never could stop the compressor.

    BOTH halves are asserted. Checking only that the compressor stops would
    pass just as happily if the valve slam were still there, which is the
    regression this exists to catch.

    The real HeatPump is kept and only the two methods under test are replaced;
    an earlier version of this used a stub object and simply grew a new
    attribute every time `step()` reached further into it.
    """
    ctl = controller(
        control={"mode": "cooling"},
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 25.0},              # supply nowhere near any limit
        room_temps={"gaestebad": 28.0},        # control wants cooling
        dew_point=None,                        # ...and we have no dew point
    )
    ctl.io.touch(time.monotonic())
    ctl.capacity.enabled = True
    ctl.hp.allow_writes = True

    calls: list[tuple[float | None, str]] = []

    async def _record(setpoint, why):
        calls.append((setpoint, why))
        return True

    ctl.hp.set_cooling = _record
    ctl.hp.cooling_is_off = lambda: False

    await ctl.step(1.0)

    assert calls, "compressor was not commanded off - source side did nothing"
    assert calls[0][0] is None, "must write the OFF sentinel, not a setpoint"
    assert all(p > 0.0 for p in ctl.io.last_write.values()), \
        "valves were shut on an unknown dew point - that is the removed rule"


async def test_safety_overrides_are_logged_once_not_once_per_cycle(controller,
                                                                  caplog):
    """Real defect, 2026-08-01: safety overrides were not logged AT ALL.

    `Safety.apply` returned a reason, `step()` published it to
    `override/<valve>`, and nothing logged it - nor was any HA entity ever
    discovered for those topics. So the most consequential action heatctl
    takes, forcing circuits shut because supply reached the dew point, was
    invisible in both places an operator would look.

    It cost a diagnosis the same day: the plant tripped Er03 three times, the
    suspected chain being dew-point trip -> valves shut -> flow collapse ->
    flow interlock, and the first link could be neither confirmed nor refuted.

    One line per REASON, not per valve - a dew-point trip hits every circuit at
    once and that is one fact, not ten.
    """
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 15.0},          # supply well under the dew point
        dew_point=20.0,
        control={"mode": "cooling"},
    )
    # Dwell neutralised: this test is about the override PROPAGATING, not
    # about when it fires. The 2026-08-01 trip dwell has its own tests in
    # test_safety.py; leaving it in would make these depend on wall time.
    ctl.safety.undertemp_dwell_s = 0.0
    ctl.io.touch(time.monotonic())

    with caplog.at_level("INFO", logger="heatctl"):
        for _ in range(50):
            ctl.io.touch(time.monotonic())
            await ctl.step(1.0)

    overridden = [v for v, p in ctl.io.last_write.items() if p == 0.0]
    assert overridden, "no circuit was overridden - test is vacuous"
    lines = [r for r in caplog.records
             if "SAFETY OVERRIDE" in r.getMessage()]
    assert len(lines) == 1, f"{len(lines)} override lines for 50 cycles"
    assert "vl_undertemp" in lines[0].getMessage()


async def test_flow_floor_is_logged_once_not_once_per_cycle(controller, caplog):
    """Real defect, 2026-08-01: a continuously binding flow floor flooded the log.

    Raising `min_open_pct` 40 -> 55 to stop heatctl throttling itself into the
    heat pump's Er03 made the floor bind on EVERY cycle. The log line had always
    been unthrottled; it had simply never been reachable, because with eight
    circuits marked unfitted `need` came out negative and the floor could not
    fire. Within minutes 96 of the last 100 lines in the container's log ring
    were this one message, which is the same evidence-destroying flood that
    `failsafe()` and `write_all_valves` already carry throttles for.

    The assertion on `_flow_floor_pct` is load-bearing: without it this test
    passes just as happily when the floor never fires at all, which is exactly
    how the first live check of the fix fooled me.
    """
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 30.0},
        room_temps={"gaestebad": 25.0},      # well above the 21 degC target
    )
    ctl.io.touch(time.monotonic())
    # Gästebad is the only room with a sensor, so it is the only circuit the
    # ROOM pid drives - and the room path is ungated, so it can actually reach
    # 0 %. Wohnzimmer's two circuits have no room sensor, so rl_gate distrusts
    # their returns and holds them OPEN at the failsafe position. That pins the
    # mean at ~67 %, which is why the floor has to be lifted above it to make
    # this condition reachable at all.
    ctl.demand.min_open_pct = 90.0

    with caplog.at_level("INFO", logger="heatctl"):
        for _ in range(50):
            ctl.io.touch(time.monotonic())
            await ctl.step(1.0)

    assert ctl._flow_floor_pct is not None, "floor never fired - test is vacuous"
    lines = [r for r in caplog.records if "flow floor" in r.getMessage()]
    assert len(lines) == 1, f"{len(lines)} flow-floor lines for 50 cycles"


async def test_failsafe_recovery_is_logged(controller, caplog):
    """Entering failsafe is visible; leaving it must be too."""
    ctl = controller(temps={"rl_hk01": 24.0, "rl_hk02": 24.0,
                            "rl_hk03": 24.0, "vl_total": 30.0})
    ctl.io.touch(time.monotonic() - 3600)
    await ctl.step(1.0)
    with caplog.at_level("INFO", logger="heatctl"):
        ctl.io.touch(time.monotonic())
        await ctl.step(1.0)
    assert any("failsafe cleared" in r.getMessage() for r in caplog.records)


# ---------- system-return tracking ----------

def test_fixed_return_setpoint_ignores_the_system_return(controller):
    ctl = controller(control={"return_setpoint_source": "fixed"})
    ctl.io.state.temps = {"rl_total": 18.0}
    assert ctl._effective_return_sp(ctl.io.state) == 22.0


def test_system_return_tracking_follows_the_mixed_return(controller):
    """The inner loop becomes a balancing controller (see config.yaml)."""
    ctl = controller(control={"return_setpoint_source": "system_return"})
    ctl.io.state.temps = {"rl_total": 18.5}
    assert ctl._effective_return_sp(ctl.io.state) == 18.5


def test_system_return_bias_always_increases_demand(controller):
    """Positive bias must mean 'tend to open' in BOTH modes.

    In heating that means a higher target, in cooling a lower one. Getting the
    sign wrong here would make the bias close valves in one of the two modes,
    which is the opposite of what the knob is for.
    """
    heat = controller(control={"return_setpoint_source": "system_return",
                               "system_return_bias_c": 1.0,
                               "mode": "heating"})
    heat.io.state.temps = {"rl_total": 20.0}
    assert heat._effective_return_sp(heat.io.state) == 21.0

    cool = controller(control={"return_setpoint_source": "system_return",
                               "system_return_bias_c": 1.0,
                               "mode": "cooling"})
    cool.io.state.temps = {"rl_total": 20.0}
    assert cool._effective_return_sp(cool.io.state) == 19.0


def test_system_return_falls_back_when_the_sensor_is_missing(controller):
    """A dead rl_total must not take the control loop with it."""
    ctl = controller(control={"return_setpoint_source": "system_return"})
    ctl.io.state.temps = {}
    assert ctl._effective_return_sp(ctl.io.state) == 22.0


# ---------- telemetry ----------

async def test_telemetry_publishes_temps_valves_and_setpoints(controller):
    ctl = controller(
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 30.0, "rl_total": 24.0},
        room_temps={"gaestebad": 22.0},
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.plane.topic("temp/rl_hk01") == "24.0"
    assert ctl.plane.topic("valve/valve_hk01") is not None
    assert ctl.plane.topic("mode") == "heating"
    assert ctl.plane.topic("setpoint/gaestebad") == "21.0"
    assert ctl.plane.topic("room/gaestebad/temp") == "22.0"


async def test_setpoint_state_is_retained_but_nothing_else_is(controller):
    """Retaining a `set/` topic would defeat command expiry (DESIGN.md 2.2).

    heatctl only publishes state, but the retain flags still encode the rule:
    state that HA must show correctly after a restart is retained, live
    measurements are not.
    """
    ctl = controller(temps={"rl_hk01": 24.0, "rl_hk02": 24.0,
                            "rl_hk03": 24.0, "vl_total": 30.0})
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    retained = {s for s, _, r in ctl.plane.published if r}
    assert "setpoint/gaestebad" in retained
    assert "mode" in retained
    assert not any(s.startswith("temp/") for s in retained)


async def test_faults_are_published(controller):
    ctl = controller(temps={"rl_hk02": 24.0, "rl_hk03": 24.0, "vl_total": 30.0},
                     faults={"rl_hk01"})
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.plane.topic("fault/rl_hk01") == "1"


@pytest.mark.parametrize("mode", ["heating", "cooling", "off"])
async def test_a_cycle_completes_in_every_mode(controller, mode):
    """Smoke test: no mode may raise on a perfectly ordinary state."""
    ctl = controller(
        control={"mode": mode},
        temps={"rl_hk01": 22.0, "rl_hk02": 22.0, "rl_hk03": 22.0,
               "vl_total": 28.0, "rl_total": 22.0},
        room_temps={"gaestebad": 21.5},
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert len(ctl.io.writes) == 3


# ---------- outputs heatctl does not own ----------

async def test_the_failsafe_only_touches_circuits_we_control(controller):
    """Real defect, observed 2026-07-27.

    config.yaml declares more analog outputs than there are circuits - genuine
    spares, plus the two out-of-service circuits. The failsafe used to sweep
    every declared channel to 100 % and then never command them again, because
    nothing else does, leaving them parked wide open indefinitely. Harmless
    while no actuator is fitted there; wrong the moment one is.
    """
    ctl = controller(temps={"rl_hk01": 24.0})
    ctl.io.touch(time.monotonic() - 3600)
    await ctl.step(1.0)
    assert ctl.io.all_valve_names == ctl.owned_valves
    assert "valve_spare" not in (ctl.io.all_valve_names or [])


async def test_unowned_outputs_are_parked_closed(controller):
    """An output heatctl does not manage should not be passing water, and
    should have a DEFINITE value rather than whatever a past failsafe left."""
    ctl = controller(temps={"rl_hk01": 24.0, "rl_hk02": 24.0,
                            "rl_hk03": 24.0, "vl_total": 30.0})
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    for name in ctl.unowned_valves:
        assert ctl.io.last_write[name] == 0.0


def test_ownership_is_derived_from_the_room_topology(controller):
    ctl = controller()
    assert set(ctl.owned_valves) == {"valve_hk01", "valve_hk02", "valve_hk03"}
    assert ctl.unowned_valves == []


async def test_auto_mode_actually_applies_the_picked_mode(controller):
    """Defect found on wiring auto_mode up, 2026-07-27: the demand controller
    computed a mode into its shadow output and the controller never read it,
    so turning the flag on would have done nothing at all."""
    ctl = controller(
        control={"mode": "heating"},
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 30.0},
        room_temps={"gaestebad": 30.0},       # 9 K above target -> wants cooling
    )
    ctl.demand.auto_mode = True
    ctl.demand.mode_dwell_s = 0.0             # skip the hour of dwell
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    await ctl.step(1.0)                       # dwell needs a second observation
    assert ctl.mode == "cooling"
    assert all(p.invert for p in ctl.circuit_pids.values()), \
        "mode applied without flipping the PID direction"


async def test_auto_mode_off_leaves_the_mode_alone(controller):
    ctl = controller(
        control={"mode": "heating"},
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 30.0},
        room_temps={"gaestebad": 30.0},
    )
    ctl.demand.auto_mode = False
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl.mode == "heating"


async def test_off_mode_is_not_normalised_into_wide_open(controller):
    """Defect caught on wiring distribution up, 2026-07-27.

    In `off` every demand is zero, and normalising an all-zero set correctly
    yields all-valves-open - which is right at thermal equilibrium and exactly
    wrong when the plant is meant to be off. `off` bypasses distribution.
    """
    ctl = controller(
        control={"mode": "off"},
        temps={"rl_hk01": 24.0, "rl_hk02": 18.0, "rl_hk03": 18.0,
               "vl_total": 30.0},
        room_temps={"gaestebad": 15.0},
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert set(ctl.io.last_write.values()) == {0.0}


# ---------- pump minimum flow vs safety: ordering ----------

async def test_safety_still_forces_a_circuit_shut_after_the_flow_floor(controller):
    """Ordering invariant: the flow floor runs BEFORE safety, so safety wins.

    Both want to move the same valve in opposite directions. The floor opens
    valves to keep the pump alive; safety closes them when the supply is known
    dangerous. If these ever swap order, heatctl would hold a circuit open into
    below-dew-point water to protect the pump - trading an invisible wet slab
    for a recoverable fault code. That is the wrong trade, so pin the order.
    """
    ctl = controller(
        temps={"rl_hk01": 20.0, "rl_hk02": 20.0, "rl_hk03": 20.0,
               "vl_total": 10.0},          # supply far below any dew limit
        dew_point=14.0,                    # limit 16.0 -> supply is bad
        control={"mode": "cooling"},
    )
    # Dwell neutralised: this test is about the override PROPAGATING, not
    # about when it fires. The 2026-08-01 trip dwell has its own tests in
    # test_safety.py; leaving it in would make these depend on wall time.
    ctl.safety.undertemp_dwell_s = 0.0
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    written = ctl.io.last_write
    assert written, "nothing written - test is not checking anything"
    for valve in ("valve_hk01", "valve_hk02", "valve_hk03"):
        assert written[valve] == 0.0, (
            f"{valve} left open at {written[valve]} % into below-dew-point "
            "supply - the flow floor overrode safety")


async def test_the_flow_floor_does_not_fire_in_off_mode(controller):
    """`off` means no flow is wanted and the source is not running.

    Raising valves for a pump that is not turning would be pure confusion,
    and it would undo the deliberate all-closed state that `off` exists for.
    """
    ctl = controller(
        temps={"rl_hk01": 20.0, "rl_hk02": 20.0, "rl_hk03": 20.0,
               "vl_total": 20.0},
        control={"mode": "off"},
    )
    ctl.io.touch(time.monotonic())
    await ctl.step(1.0)
    assert ctl._flow_floor_pct is None


# ---------- pre-conditioning delta (active = dial + delta) ----------

# Live temperatures on every mapped sensor: without them step() takes the
# stale-data failsafe and returns before any of this is reached.
_TEMPS = {f"rl_hk{n:02d}": 21.0 for n in (1, 2, 3, 4, 6, 7, 8, 9, 10, 11)}
_TEMPS.update({"vl_total": 18.0, "rl_total": 21.0})

async def test_a_negative_delta_pre_cools_every_room(controller):
    """`active = dial + delta`, so negative aims cooler - the summer pre-charge.

    This is what reactive control structurally cannot do. The trim aims at
    comfort and stops when the air is comfortable, so it can never store energy
    in the slab: measured 2026-07-30, the plant idled 6 h 44 min before a 38 degC
    day because the air was at target while the slab sat uncharged.
    """
    ctl = controller(temps=_TEMPS, room_temps={"gaestebad": 24.0},
                     dew_point=12.0)
    ctl.io.touch(time.monotonic())
    dial = dict(ctl.room_setpoints)
    ctl.plane.sp_delta = -1.5
    await ctl.step(1.0)
    assert ctl._sp_delta_active == -1.5
    # The dial is untouched - the bridge still owns it.
    assert ctl.room_setpoints == dial


async def test_a_positive_delta_pre_heats(controller):
    """Signed and mode-independent: positive aims warmer, which is the winter
    case - pre-charging before a storm drops the outdoor temperature."""
    ctl = controller(temps=_TEMPS, room_temps={"gaestebad": 20.0},
                     dew_point=8.0)
    ctl.io.touch(time.monotonic())
    ctl.plane.sp_delta = +1.5
    await ctl.step(1.0)
    assert ctl._sp_delta_active == +1.5


async def test_a_stale_delta_returns_the_plant_to_the_dial(controller):
    """Expiry is why this needs no command-TTL machinery: zero means exactly
    what the occupant set, so a hung layer 2 degrades to comfort control rather
    than leaving the house steered by its last thought."""
    ctl = controller(temps=_TEMPS, room_temps={"gaestebad": 24.0},
                     dew_point=12.0)
    ctl.io.touch(time.monotonic())
    ctl.plane.sp_delta = 0.0          # what a stale value resolves to
    await ctl.step(1.0)
    assert ctl._sp_delta_active == 0.0


async def test_the_absolute_clamp_bounds_the_result_not_the_delta(controller):
    """There is deliberately no separate bound on the delta - the absolute
    setpoint clamp is the real protection, and a second arbitrary limit would
    just be a number nobody derived sitting in front of one that means
    something. A wildly wrong delta must land on the clamp, not past it."""
    ctl = controller(temps=_TEMPS, room_temps={"gaestebad": 24.0},
                     dew_point=12.0)
    ctl.io.touch(time.monotonic())
    lo = ctl.safety.setpoint_min
    ctl.plane.sp_delta = -50.0
    await ctl.step(1.0)
    published = {t: v for t, v, _ in ctl.plane.published}
    assert float(published["setpoint_delta/active"]) == -50.0
    # every effective target still inside the absolute bound
    for n in ctl.room_setpoints:
        assert ctl.safety.clamp_setpoint(ctl.room_setpoints[n] - 50.0) >= lo


async def test_the_house_average_sees_the_shifted_target(controller):
    """The delta has to reach the DEMAND calculation too, not just the room
    PIDs. If the house average kept using the dial, the plant would report
    itself satisfied while layer 2 was asking for more - which is precisely the
    blindness that lost the overnight pre-charge."""
    warm = controller(temps=_TEMPS, room_temps={"gaestebad": 23.0},
                      dew_point=12.0)
    warm.io.touch(time.monotonic())
    warm.plane.sp_delta = 0.0
    await warm.step(1.0)
    base = warm._last_demand.mean_deviation_c

    cool = controller(temps=_TEMPS, room_temps={"gaestebad": 23.0},
                      dew_point=12.0)
    cool.io.touch(time.monotonic())
    cool.plane.sp_delta = -2.0
    await cool.step(1.0)
    shifted = cool._last_demand.mean_deviation_c

    assert shifted is not None and base is not None
    assert shifted < base, "a pre-cool delta must increase apparent cooling demand"


class _ResumeHP:
    """Heat pump stub for the RESUME dead-zone test."""

    def __init__(self, return_c: float, dead_zone_k: float):
        import heatctl.heatpump_map as hpm
        self.allow_writes = True
        self.enabled = True
        self._config_seen = False
        self.calls: list[tuple[float | None, str]] = []
        self.status = {hpm.by_name("return_water").addr: int(return_c * 10),
                       hpm.by_name("compressor_freq").addr: 0}
        self.config = {hpm.by_name("restart_diff_c").addr: int(dead_zone_k)}

    def cooling_is_off(self):
        return True

    def cooling_setpoint(self):
        return None

    def mode_disagrees(self, mode):
        return None

    async def sync_mode(self, mode):
        return None

    async def set_cooling(self, setpoint, why):
        self.calls.append((setpoint, why))
        return True


async def test_resume_clears_the_restart_dead_zone(controller):
    """Real defect, 2026-08-02: a RESUME that lands in the dead zone does nothing.

    P01 is the unit's restart differential, pinned at its 2 K minimum. The
    compressor will not start until RETURN water exceeds P04 by that much, so
    restoring the previous setpoint is not sufficient on its own.

    Measured that morning: resumed at P04 20.0 with return 21.9 - 1.9 K against
    a 2.0 K dead zone. The compressor stayed off for eleven minutes and started
    only when the house warmed the return to 22.0. heatctl reported a running
    plant throughout.
    """
    ctl = controller(control={"mode": "cooling"},
                     temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
                            "vl_total": 22.0},
                     dew_point=12.0)
    ctl.io.touch(time.monotonic())
    ctl.capacity.enabled = True
    hp = _ResumeHP(return_c=21.9, dead_zone_k=2.0)
    ctl.hp = hp
    ctl._sp_before_off = 20.0

    from heatctl.capacity import RESUME, CapacityDecision
    ctl.capacity.step = lambda **kw: CapacityDecision(None, "test", RESUME)

    await ctl.step(1.0)

    assert hp.calls, "no setpoint written on resume"
    sp = hp.calls[0][0]
    assert sp is not None, "resume must write a setpoint, not the OFF sentinel"
    # 21.9 - 2.0 = 19.9 is the edge; the write must be clear of it, not on it.
    assert sp < 19.9, f"resume wrote {sp}, inside the dead zone - a no-op"
    assert sp <= 20.0, "resume must never raise the setpoint above what was asked"


async def test_resume_does_not_lower_the_setpoint_when_it_already_starts(
        controller):
    """The clamp must only ever bite when it has to.

    Lowering the setpoint costs colder water than intended, so it is justified
    only when the dead zone would otherwise block the start. With plenty of
    difference, the previous setpoint must be restored untouched.
    """
    ctl = controller(control={"mode": "cooling"},
                     temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
                            "vl_total": 26.0},
                     dew_point=12.0)
    ctl.io.touch(time.monotonic())
    ctl.capacity.enabled = True
    hp = _ResumeHP(return_c=26.0, dead_zone_k=2.0)   # 6 K of headroom
    ctl.hp = hp
    ctl._sp_before_off = 20.0

    from heatctl.capacity import RESUME, CapacityDecision
    ctl.capacity.step = lambda **kw: CapacityDecision(None, "test", RESUME)

    await ctl.step(1.0)
    assert hp.calls[0][0] == 20.0, "clamp bit when the compressor would start anyway"
