"""Controller wiring: mode handling, control paths, failsafe, telemetry.

These are the tests that would have caught the defects this project actually
hit. Every bug found so far was found by running the plant, not by reading the
code, so the bar here is "would this have failed before the fix".
"""
from __future__ import annotations

import time

import pytest


# ---------- REGRESSION (a), mandated by PLAN.md Milestone 1 ----------

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
    # hk03 returns 24 C, already above target -> shut.
    assert w["valve_hk02"] > 0
    assert w["valve_hk03"] == 0


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
    """Safety changes real flow, so it must drive the validity clock too."""
    ctl = controller(
        control={"mode": "cooling"},
        temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
               "vl_total": 12.0},              # condensation guard -> force 0
        room_temps={"gaestebad": 28.0},        # control wants 100 %
    )
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
