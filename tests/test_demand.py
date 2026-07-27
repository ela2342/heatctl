"""House demand, plant mode, and source engagement.

The rule being implemented (docs/DESIGN.md 4.3): engage the source only when
the house is far enough off target that the resulting valve openings still
give the pump flow. Two halves that must not drift apart - a plant that runs
with the manifold shut deadheads the only pump in the system.
"""
from __future__ import annotations

import pytest

from heatctl.demand import DemandController


@pytest.fixture
def demand(cfg):
    def _make(**overrides):
        # enabled=False (shadow) by default: `enabled` gates who ACTS on the
        # answer, not whether it is computed, and with it on the constructor
        # refuses auto_mode (heatctl cannot command the pump's mode yet).
        cfg["control"]["source_demand"] = {
            "enabled": False, "auto_mode": True, "min_open_pct": 40.0,
            "engage_deviation_c": 0.3, "mode_deadband_c": 1.0,
            "mode_dwell_s": 3600.0, "min_on_s": 600.0, "min_off_s": 600.0,
            **overrides,
        }
        # can_command_source_mode=True: these tests are about which mode the
        # house asks for, not about whether heatctl is allowed to command it.
        return DemandController(cfg, can_command_source_mode=True)
    return _make


# ---------- the flow proxy ----------

def test_unactuated_circuits_count_as_fully_open(demand):
    """They are open pipe - they pass water whatever we command.

    Getting this wrong would read the plant as starved while most of the house
    is wide open, and refuse to run the source at all.
    """
    d = demand()
    d.unactuated = {"valve_hk02", "valve_hk03"}
    # hk01 shut, the other two open pipe -> (0 + 100 + 100) / 3
    assert d.open_pct({"valve_hk01": 0.0, "valve_hk02": 0.0,
                       "valve_hk03": 0.0}) == pytest.approx(66.7, abs=0.1)


def test_flow_proxy_averages_all_water_carrying_circuits(demand):
    d = demand()
    d.unactuated = set()
    assert d.open_pct({"valve_hk01": 30.0, "valve_hk02": 60.0,
                       "valve_hk03": 0.0}) == pytest.approx(30.0)


def test_valves_not_assigned_to_a_circuit_are_excluded(demand):
    """A spare analog output carries no water and must not dilute the mean."""
    d = demand()
    d.unactuated = set()
    assert "valve_spare" not in d.circuit_valves


# ---------- house demand ----------

def test_mean_deviation_is_positive_when_too_cold(demand):
    d = demand()
    dev, n = d.mean_deviation({"a": 21.0, "b": 21.0}, {"a": 19.0, "b": 20.0})
    assert (dev, n) == (1.5, 2)


def test_mean_deviation_is_negative_when_too_warm(demand):
    d = demand()
    dev, n = d.mean_deviation({"a": 21.0}, {"a": 24.0})
    assert (dev, n) == (-3.0, 1)


def test_rooms_without_a_temperature_do_not_contribute(demand):
    """Only three of seven rooms have a sensor - the average is of those."""
    d = demand()
    dev, n = d.mean_deviation({"a": 21.0, "b": 21.0, "c": 21.0}, {"a": 20.0})
    assert (dev, n) == (1.0, 1)


# ---------- engagement ----------

def test_source_runs_when_the_house_wants_heat_and_flow_is_available(demand):
    d = demand()
    out = d.step("heating", {"a": 21.0}, {"a": 19.0},
                 {"valve_hk01": 80.0, "valve_hk02": 80.0, "valve_hk03": 80.0}, 0.0)
    assert out.source_request is True


def test_source_stops_when_the_house_is_satisfied(demand):
    d = demand()
    out = d.step("heating", {"a": 21.0}, {"a": 21.1},
                 {"valve_hk01": 80.0, "valve_hk02": 80.0, "valve_hk03": 80.0}, 0.0)
    assert out.source_request is False
    assert "satisfied" in out.reason


def test_source_stops_rather_than_running_the_pump_dry(demand):
    """The case this exists for.

    Real demand, but too little of the house open to give the pump flow.
    Running anyway is what trips Er03; stopping lets the rooms coast and the
    next engagement starts from parked-open valves.
    """
    d = demand()
    d.unactuated = set()
    out = d.step("heating", {"a": 21.0}, {"a": 18.0},
                 {"valve_hk01": 10.0, "valve_hk02": 10.0, "valve_hk03": 10.0}, 0.0)
    assert out.source_request is False
    assert "flow too low" in out.reason


def test_the_flow_floor_is_not_tripped_while_circuits_are_open_pipe(demand):
    """Today's plant: seven of nine circuits unactuated, so no stall risk."""
    d = demand()          # conftest marks none unactuated; simulate the real one
    d.unactuated = {"valve_hk02", "valve_hk03"}
    out = d.step("heating", {"a": 21.0}, {"a": 18.0},
                 {"valve_hk01": 0.0, "valve_hk02": 0.0, "valve_hk03": 0.0}, 0.0)
    assert out.source_request is True


def test_demand_is_never_taken_from_valve_position(demand):
    """Safety closes valves for reasons unrelated to whether the house wants
    heat. If a dew-point closure read as "no demand", the source would stop
    and the supply could never recover - the 2026-07-26 latch-up again.

    Here every valve is shut by safety, yet the rooms are cold: the controller
    must still see demand, and refuse only on the flow interlock.
    """
    d = demand()
    d.unactuated = set()
    out = d.step("cooling", {"a": 21.0}, {"a": 26.0},
                 {"valve_hk01": 0.0, "valve_hk02": 0.0, "valve_hk03": 0.0}, 0.0)
    assert out.mean_deviation_c == -5.0        # demand is seen
    assert "flow" in out.reason                # refused on flow, not on demand


def test_no_room_data_keeps_circulating(demand):
    """A total sensor outage must not stop the plant.

    The return-temperature loop still does useful work and the heat pump holds
    its own setpoint. This is also today's behaviour, so it is not a change.
    """
    d = demand()
    out = d.step("heating", {"a": 21.0}, {},
                 {"valve_hk01": 0.0, "valve_hk02": 0.0, "valve_hk03": 0.0}, 0.0)
    assert out.source_request is True
    assert out.reason == "no_room_data"


def test_mode_off_stops_the_source(demand):
    d = demand()
    out = d.step("off", {"a": 21.0}, {"a": 10.0},
                 {"valve_hk01": 100.0, "valve_hk02": 100.0, "valve_hk03": 100.0}, 0.0)
    assert out.source_request is False


def test_valves_park_open_while_the_source_is_idle(demand):
    """Position is irrelevant to flow with the pump stopped, so parking open
    costs nothing and means the next engagement has flow immediately instead
    of racing a multi-minute actuator stroke."""
    d = demand()
    out = d.step("heating", {"a": 21.0}, {"a": 21.5},
                 {"valve_hk01": 50.0, "valve_hk02": 50.0, "valve_hk03": 50.0}, 0.0)
    assert out.source_request is False
    assert out.park_valves_open is True


# ---------- anti-short-cycle ----------

def test_the_source_is_held_on_for_the_minimum_run_time(demand):
    d = demand()
    open_all = {"valve_hk01": 80.0, "valve_hk02": 80.0, "valve_hk03": 80.0}
    d.step("heating", {"a": 21.0}, {"a": 19.0}, open_all, 100.0)   # -> ON
    # Immediately satisfied; must not stop yet.
    out = d.step("heating", {"a": 21.0}, {"a": 21.5}, open_all, 200.0)
    assert out.source_request is True
    assert "held" in out.reason
    out = d.step("heating", {"a": 21.0}, {"a": 21.5}, open_all, 701.0)
    assert out.source_request is False


def test_the_source_is_held_off_for_the_minimum_idle_time(demand):
    d = demand()
    open_all = {"valve_hk01": 80.0, "valve_hk02": 80.0, "valve_hk03": 80.0}
    d.step("heating", {"a": 21.0}, {"a": 19.0}, open_all, 100.0)
    d.step("heating", {"a": 21.0}, {"a": 21.5}, open_all, 800.0)    # -> OFF
    out = d.step("heating", {"a": 21.0}, {"a": 19.0}, open_all, 900.0)
    assert out.source_request is False
    assert "held" in out.reason
    out = d.step("heating", {"a": 21.0}, {"a": 19.0}, open_all, 1500.0)
    assert out.source_request is True


# ---------- mode selection ----------

def test_mode_is_not_switched_inside_the_deadband(demand):
    d = demand()
    out = d.step("heating", {"a": 21.0}, {"a": 21.5}, {}, 0.0)   # -0.5 K
    assert out.mode == "heating"


def test_mode_switches_only_after_the_dwell_time(demand):
    """Switching the whole plant on a transient average is expensive and slow
    to undo."""
    d = demand()
    warm = ({"a": 21.0}, {"a": 24.0})                            # -3 K
    assert d.step("heating", *warm, {}, 0.0).mode == "heating"
    assert d.step("heating", *warm, {}, 3599.0).mode == "heating"
    assert d.step("heating", *warm, {}, 3601.0).mode == "cooling"


def test_a_transient_average_does_not_start_the_dwell_clock_running(demand):
    """The condition has to persist, not merely have occurred once."""
    d = demand()
    d.step("heating", {"a": 21.0}, {"a": 24.0}, {}, 0.0)         # too warm
    d.step("heating", {"a": 21.0}, {"a": 21.2}, {}, 100.0)       # back inside
    assert d.step("heating", {"a": 21.0}, {"a": 24.0}, {}, 3700.0).mode == "heating"


def test_auto_mode_off_never_changes_the_mode(demand):
    """Default: the owner picks the season, this only reports."""
    d = demand(auto_mode=False)
    assert d.step("heating", {"a": 21.0}, {"a": 30.0}, {}, 99_999.0).mode == "heating"


def test_shadow_mode_still_computes_everything(cfg):
    """Shadow is about who ACTS on the answer, not whether it is computed -
    the point is to watch it against the plant before it owns the heat pump."""
    cfg["control"]["source_demand"] = {"enabled": False}
    d = DemandController(cfg)
    out = d.step("heating", {"a": 21.0}, {"a": 19.0},
                 {"valve_hk01": 80.0, "valve_hk02": 80.0, "valve_hk03": 80.0}, 0.0)
    assert d.enabled is False
    assert out.mean_deviation_c == 2.0
    assert out.source_request is True


# ---------- the heat pump's own mode is NOT ours to switch (yet) ----------

def test_auto_mode_is_refused_while_the_pump_mode_cannot_be_commanded(cfg, caplog):
    """heatctl flipping its own mode while the heat pump stays put is worse
    than not switching: the valve loop would drive the wrong direction with
    the wrong water. Register 0 bit 0 (water pump) is the only writable bit
    established; the mode bit is unknown. See PLAN.md WP-B.
    """
    cfg["control"]["source_demand"] = {"enabled": True, "auto_mode": True}
    with caplog.at_level("ERROR", logger="heatctl.demand"):
        d = DemandController(cfg)
    assert d.auto_mode is False
    assert any("cannot command" in r.getMessage() for r in caplog.records)


def test_auto_mode_does_not_depend_on_the_source_enable(cfg):
    """Two independent switches: `enabled` decides whether the plant runs,
    `auto_mode` decides which mode it runs in. Conflating them would mean you
    cannot have heatctl choose the season without also handing it the on/off
    decision. What gates auto_mode is the CAPABILITY to command the pump."""
    cfg["control"]["source_demand"] = {"enabled": False, "auto_mode": True}
    assert DemandController(cfg, can_command_source_mode=True).auto_mode is True
    assert DemandController(cfg, can_command_source_mode=False).auto_mode is False


def test_auto_mode_is_allowed_once_the_pump_mode_can_be_commanded(cfg):
    """The capability is passed in, not assumed: it is true only when the heat
    pump client is enabled AND permitted to write."""
    cfg["control"]["source_demand"] = {"enabled": True, "auto_mode": True}
    d = DemandController(cfg, can_command_source_mode=True)
    assert d.auto_mode is True
