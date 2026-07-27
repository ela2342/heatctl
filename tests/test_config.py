"""The real config.yaml is hardware truth - check it stays self-consistent.

Distinct from the rest of the suite, which uses a synthetic config: this asks
whether the *site* file is coherent, not whether the control logic is right. A
typo here is a wiring bug, and the field config is edited far more often than
the code.

These assertions are deliberately structural. They must not encode the current
wiring (which circuits exist, which valves are fitted) or they would fail on
every rewiring - the very thing that is expected to change.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from heatctl.backends.base import decode_pt1000
from heatctl.pid import PID
from heatctl.safety import Safety

CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def real_cfg():
    return yaml.safe_load(CONFIG.read_text())


def test_config_parses(real_cfg):
    assert real_cfg["io"]["backend"] in ("modbus_direct", "mqtt")


def test_every_circuit_sensor_exists(real_cfg):
    known = {c["name"] for c in real_cfg["sensors"]["channels"]}
    for room in real_cfg["rooms"]:
        for circ in room["circuits"]:
            assert circ["sensor"] in known, \
                f"{room['name']}: unknown sensor {circ['sensor']}"


def test_every_assigned_valve_exists(real_cfg):
    known = {c["name"] for c in real_cfg["valves"]["channels"]}
    for room in real_cfg["rooms"]:
        for circ in room["circuits"]:
            valve = circ.get("valve")
            if valve:                      # unassigned is legitimate (see PLAN)
                assert valve in known, \
                    f"{room['name']}: unknown valve {valve}"


def test_no_valve_is_driven_by_two_circuits(real_cfg):
    """One actuator, one circuit - a duplicate means two PIDs fighting."""
    seen: dict[str, str] = {}
    for room in real_cfg["rooms"]:
        for circ in room["circuits"]:
            valve = circ.get("valve")
            if not valve:
                continue
            assert valve not in seen, \
                f"{valve} claimed by {seen[valve]} and {room['name']}"
            seen[valve] = room["name"]


def test_no_sensor_is_used_by_two_circuits(real_cfg):
    seen: dict[str, str] = {}
    for room in real_cfg["rooms"]:
        for circ in room["circuits"]:
            s = circ["sensor"]
            assert s not in seen, f"{s} used by {seen[s]} and {room['name']}"
            seen[s] = room["name"]


def test_channel_indices_are_unique(real_cfg):
    for section in ("sensors", "valves"):
        idx = [c["index"] for c in real_cfg[section]["channels"]]
        assert len(idx) == len(set(idx)), f"duplicate index in {section}"


def test_room_names_are_unique(real_cfg):
    names = [r["name"] for r in real_cfg["rooms"]]
    assert len(names) == len(set(names))


def test_valve_channel_count_fits_the_fitted_modules(real_cfg):
    """Two 750-559 modules = 8 analog outputs. More would not be addressable."""
    assert len(real_cfg["valves"]["channels"]) <= 8


def test_safety_limits_are_ordered_sanely(real_cfg):
    s = real_cfg["safety"]
    assert s["setpoint_min_c"] < s["setpoint_max_c"]
    assert s["frost_protect_c"] < s["setpoint_min_c"]
    # The two supply-water limits bound the water, NOT the room air, so they
    # are deliberately not compared against the room setpoint range: a 16 C
    # supply against a 15 C room target is perfectly ordinary. What must hold
    # is that they leave a usable window and sit above freezing.
    assert s["frost_protect_c"] < s["vl_min_cooling_c"] < s["vl_max_heating_c"]
    assert s["stale_data_timeout_s"] > 0
    assert 0 <= s["failsafe_valve_pct"] <= 100


def test_default_setpoints_survive_the_safety_clamp(real_cfg):
    """A default outside the clamp would be silently rewritten at runtime."""
    safety = Safety(real_cfg)
    c = real_cfg["control"]
    for key in ("default_setpoint_heating_c", "default_setpoint_cooling_c"):
        assert safety.clamp_setpoint(c[key]) == c[key], f"{key} is out of range"


def test_pid_gains_are_usable(real_cfg):
    for key in ("pid_room", "pid_return"):
        p = real_cfg["control"][key]
        pid = PID(**p)
        assert pid.out_min < pid.out_max
        assert pid.kp >= 0 and pid.ki >= 0 and pid.kd >= 0
        # A controller with no proportional AND no integral term does nothing.
        assert pid.kp or pid.ki, f"{key} would never act"


def test_mode_is_one_of_the_three(real_cfg):
    assert real_cfg["control"]["mode"] in ("heating", "cooling", "off")


def test_system_return_sensor_exists_when_it_is_used(real_cfg):
    c = real_cfg["control"]
    if c.get("return_setpoint_source") == "system_return":
        known = {ch["name"] for ch in real_cfg["sensors"]["channels"]}
        assert c["system_return_sensor"] in known


def test_committed_config_carries_no_site_addresses(real_cfg):
    """This file is public. Real addresses live in the environment.

    RFC 5737 documentation ranges are the placeholders; anything else here
    would mean a site address was committed.
    """
    hosts = [real_cfg["io"]["modbus"]["host"], real_cfg["mqtt"]["host"]]
    for h in hosts:
        assert h.startswith(("192.0.2.", "198.51.100.", "203.0.113.")) \
            or h in ("localhost", "127.0.0.1", ""), f"non-placeholder host: {h}"


def test_committed_config_carries_no_credentials(real_cfg):
    assert not real_cfg["mqtt"].get("username")
    assert not real_cfg["mqtt"].get("password")


def test_sensor_fault_values_decode_outside_any_plausible_temperature(real_cfg):
    """The fault markers must not collide with a real reading.

    "Plausible" means plausible for water in a hydronic floor circuit inside a
    house: roughly -20 C (a hard frost in an unheated shell) to +90 C. The
    saturation values sit outside that on purpose - currently 150.0 C for a
    short circuit and -30.0 C for a wire break - so a genuine reading can
    never be mistaken for a fault, or the reverse.
    """
    for raw in real_cfg["safety"]["sensor_fault_raw"]:
        t = decode_pt1000(raw)
        assert t < -20 or t > 90, f"raw {raw:#06x} decodes to a plausible {t} C"
