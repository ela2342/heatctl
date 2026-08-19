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


def test_the_source_stays_on_when_the_house_is_satisfied(demand):
    """Corrected 2026-07-27 (owner): "satisfied" is the unit's own business.

    The heat pump idles its own compressor and costs almost nothing;
    power-cycling it is expensive and slow. Stopping the plant because the
    rooms are comfortable is not a control strategy, it is a way to short-cycle
    an appliance that was already handling it.
    """
    d = demand()
    out = d.step("heating", {"a": 21.0}, {"a": 21.1},
                 {"valve_hk01": 80.0, "valve_hk02": 80.0, "valve_hk03": 80.0}, 0.0)
    assert out.source_request is True


def test_low_flow_does_not_stop_the_source(demand):
    """Low flow is a reason to OPEN VALVES, not to stop the source.

    The old behaviour was also circular: the valve positions are heatctl's own
    output, so it switched the plant off in response to its own decision.
    `min_open_pct` constrains how far heatctl may throttle; it is not a
    shutdown trigger.
    """
    d = demand()
    d.unactuated = set()
    out = d.step("heating", {"a": 21.0}, {"a": 18.0},
                 {"valve_hk01": 10.0, "valve_hk02": 10.0, "valve_hk03": 10.0}, 0.0)
    assert out.source_request is True


def test_demand_is_still_measured_even_though_it_no_longer_gates_the_source(demand):
    """The house deviation is what drives the WATER SETPOINT (setpoint.py),
    which is the real modulation lever. It still has to be right."""
    d = demand()
    d.unactuated = set()
    out = d.step("cooling", {"a": 21.0}, {"a": 26.0},
                 {"valve_hk01": 0.0, "valve_hk02": 0.0, "valve_hk03": 0.0}, 0.0)
    assert out.mean_deviation_c == -5.0
    assert out.open_pct == 0.0


def test_no_room_data_keeps_the_source_running(demand):
    d = demand()
    out = d.step("heating", {"a": 21.0}, {},
                 {"valve_hk01": 0.0, "valve_hk02": 0.0, "valve_hk03": 0.0}, 0.0)
    assert out.source_request is True
    assert out.reason == "no_room_data"


def test_mode_off_is_the_one_thing_that_stops_the_source(demand):
    """Powering the unit down is a measure of last resort - deliberately, an
    explicit off is the only route to it here."""
    d = demand()
    out = d.step("off", {"a": 21.0}, {"a": 10.0},
                 {"valve_hk01": 100.0, "valve_hk02": 100.0, "valve_hk03": 100.0}, 0.0)
    assert out.source_request is False
    assert out.reason == "mode_off"


def test_the_minimum_run_time_still_damps_an_off_transition(demand):
    """The anti-short-cycle limits remain, because `off` is still reachable and
    a power cycle is the expensive transition."""
    d = demand()
    open_all = {"valve_hk01": 80.0, "valve_hk02": 80.0, "valve_hk03": 80.0}
    d.step("heating", {"a": 21.0}, {"a": 19.0}, open_all, 100.0)     # ON
    out = d.step("off", {"a": 21.0}, {"a": 19.0}, open_all, 200.0)
    assert out.source_request is True and "held" in out.reason
    out = d.step("off", {"a": 21.0}, {"a": 19.0}, open_all, 701.0)
    assert out.source_request is False


# ---------- mode selection ----------

def test_mode_is_not_switched_inside_the_deadband(demand):
    d = demand()
    out = d.step("heating", {"a": 21.0}, {"a": 21.5}, {}, 0.0)   # -0.5 K
    assert out.mode == "heating"


def test_mode_switches_only_after_the_dwell_time(demand):
    """Switching the whole plant on a transient average is expensive and slow
    to undo.

    The first reading here is deliberately IN BAND: it spends the start-up
    one-shot (2026-08-19), which by design skips the dwell because the mode it
    would replace is a config seed rather than a decision. Everything after
    that is an in-operation switch and the dwell applies in full - which is
    what this test has always been about.
    """
    d = demand()
    warm = ({"a": 21.0}, {"a": 24.0})                            # -3 K
    assert d.step("heating", {"a": 21.0}, {"a": 21.0}, {}, 0.0).mode == "heating"
    assert d.step("heating", *warm, {}, 1.0).mode == "heating"
    assert d.step("heating", *warm, {}, 3599.0).mode == "heating"
    assert d.step("heating", *warm, {}, 3601.0).mode == "cooling"


def test_the_first_decision_after_a_start_skips_the_dwell(demand):
    """Owner, 2026-08-19: "auto mode should fire on startup, not wait for an
    hour for correction."

    The dwell protects a mode the plant is already running. At start-up there
    is no such mode - `current` is whatever `control.mode` says. Measured that
    day: a rebuild at 18:51 came up heating with the house 1.6 K too warm and
    would have idled until 19:52.
    """
    d = demand()
    assert d.step("heating", {"a": 21.0}, {"a": 24.0}, {}, 0.0).mode == "cooling"


def test_the_start_up_one_shot_is_spent_even_when_it_changes_nothing(demand):
    """A complete reading inside the deadband IS a decision - the seed mode is
    fine. If it did not spend the one-shot, the next drift out of band would
    be treated as a start-up rather than as the in-operation transient it is,
    and would skip the dwell it deserves."""
    d = demand()
    assert d.step("heating", {"a": 21.0}, {"a": 21.0}, {}, 0.0).mode == "heating"
    assert d.step("heating", {"a": 21.0}, {"a": 24.0}, {}, 1.0).mode == "heating"


def test_the_one_shot_does_not_arm_on_a_partial_room_set(demand, cfg):
    """Room temperatures arrive over the first seconds, and a partial average
    is not the house - Elternschlafzimmer alone reads -5.8 K against its 19.0
    target and would flip the plant on its own. With a room missing, the
    dwell applies as before: the safe degradation."""
    cfg["rooms"] = [dict(cfg["rooms"][0]),
                    {"name": "b", "label": "B", "circuits": [],
                     "room_temp_topic": "roomtemp/b"}]
    d = demand()
    assert d.expected_rooms == 2
    # Only one of the two has reported.
    assert d.step("heating", {"a": 21.0}, {"a": 24.0}, {}, 0.0).mode == "heating"


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
    established; the mode bit is unknown. See BACKLOG.md and D-012.
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


# ---------- pump minimum flow: enforce_flow_floor ----------
#
# The plant has a HARD minimum water flow enforced by its own flow switch: the
# BLP08P1V1MR32 wants >= 0.16 l/s and throws Er03 and STOPS below it. The owner
# tripped it instantly on 2026-07-28 by shutting every valve but one. heatctl
# can do the same to itself once every circuit has an actuator, because
# distribution is free to drive them all down to `open_threshold_pct`.

def test_flow_floor_leaves_adequate_flow_alone(demand):
    d = demand(min_open_pct=40.0)
    cmd = {"valve_hk01": 80.0, "valve_hk02": 60.0, "valve_hk03": 70.0}
    out, raised = d.enforce_flow_floor(cmd)
    assert out == cmd
    assert raised is None, "must not touch valves that already have flow"


def test_flow_floor_OPENS_valves_and_never_closes_them(demand):
    """THE test. Direction is the whole point.

    Too little flow is a reason to OPEN valves. A version that throttled
    instead would deadhead the pump faster - strictly worse than no protection
    at all - and it would look like 'the flow logic ran' in any test that only
    asserted that something changed.
    """
    d = demand(min_open_pct=40.0)
    cmd = {"valve_hk01": 5.0, "valve_hk02": 5.0, "valve_hk03": 5.0}
    out, raised = d.enforce_flow_floor(cmd)
    for v, before in cmd.items():
        assert out[v] >= before, f"{v} was CLOSED to relieve low flow"
    assert raised is not None and raised >= 40.0


def test_flow_floor_preserves_relative_proportions(demand):
    """D-017's normalisation, applied at the bottom end instead of the top.

    One common scale factor, so the distribution decided upstream survives.
    """
    d = demand(min_open_pct=40.0)
    cmd = {"valve_hk01": 10.0, "valve_hk02": 20.0, "valve_hk03": 30.0}
    out, _ = d.enforce_flow_floor(cmd)
    assert out["valve_hk02"] / out["valve_hk01"] == pytest.approx(2.0)
    assert out["valve_hk03"] / out["valve_hk01"] == pytest.approx(3.0)
    assert sum(out.values()) / 3 == pytest.approx(40.0)


def test_flow_floor_clips_at_100_and_redistributes(demand):
    """A valve cannot exceed 100 %, so the shortfall moves to the others.

    This is the one place proportionality genuinely cannot be kept, and the
    floor matters more than the ratio.
    """
    d = demand(min_open_pct=80.0)
    cmd = {"valve_hk01": 5.0, "valve_hk02": 50.0, "valve_hk03": 60.0}
    out, raised = d.enforce_flow_floor(cmd)
    assert max(out.values()) <= 100.0
    assert raised == pytest.approx(80.0)


def test_flow_floor_opens_everything_when_the_floor_is_unreachable(demand):
    """Wide open still short: offer the most flow available, do not give up.

    Returning the input unchanged here would be the dangerous failure - it
    reads as 'nothing to do' when in fact the plant is about to fault.
    """
    d = demand(min_open_pct=100.0)
    cmd = {"valve_hk01": 5.0, "valve_hk02": 5.0, "valve_hk03": 5.0}
    out, _ = d.enforce_flow_floor(cmd)
    assert all(v == 100.0 for v in out.values())


def test_flow_floor_can_lift_valves_off_zero(demand):
    """Scaling cannot escape zero, so there is an additive path.

    Reachable whenever distribution's open_threshold_pct is 0, which it was
    until 2026-07-28 and may be again.
    """
    d = demand(min_open_pct=40.0)
    cmd = {"valve_hk01": 0.0, "valve_hk02": 0.0, "valve_hk03": 0.0}
    out, raised = d.enforce_flow_floor(cmd)
    assert all(v > 0.0 for v in out.values())
    assert raised == pytest.approx(40.0)


def test_flow_floor_counts_open_pipe_circuits_as_already_flowing(cfg):
    """Unactuated circuits are open pipe: full flow, and commanding them is a
    fiction. They must count toward the floor, or heatctl will pointlessly
    force the few actuated circuits open on a manifold that is already wide
    open - which is exactly today's plant, 8 of 10 circuits unactuated.
    """
    cfg["control"]["source_demand"] = {
        "enabled": False, "auto_mode": True, "min_open_pct": 40.0,
        "engage_deviation_c": 0.3, "mode_deadband_c": 1.0,
        "mode_dwell_s": 3600.0, "min_on_s": 600.0, "min_off_s": 600.0,
    }
    for ch in cfg["valves"]["channels"]:
        ch["fitted"] = ch["name"] == "valve_hk01"      # only hk01 actuated
    d = DemandController(cfg, can_command_source_mode=True)
    cmd = {"valve_hk01": 5.0, "valve_hk02": 5.0, "valve_hk03": 5.0}
    out, raised = d.enforce_flow_floor(cmd)
    # hk02/hk03 are open pipe -> 100 each -> mean already 68 % >= 40 %.
    assert out == cmd
    assert raised is None


# ---------- the flow floor must not credit dead range (D-041) ----------

def test_the_flow_floor_never_raises_a_circuit_past_saturation(cfg, demand):
    """Opening a valve beyond the point where flow stops increasing buys no
    water, so crediting it is fictitious flow - in the one calculation whose
    job is to stay clear of Er03.

    Before D-041 this loop raised toward a hardcoded 100, which was harmless
    only while `full_open_pct` was also 100. The owner's calibration puts
    saturation at 50 % command, so a floor satisfied by commanding 80 % would
    have reported flow the plant was not passing.
    """
    cfg["control"]["distribution"] = {"open_threshold_pct": 20.0,
                                      "full_open_pct": 50.0}
    d = demand(min_open_pct=41.0)
    # A SPREAD set, not a uniform one. Scaling a uniform set toward a 41 %
    # mean lands every circuit on 41 and never reaches the clipping path at
    # all - the first version of this test was green against the bug for
    # exactly that reason.
    vs = d.circuit_valves
    valves = {v: (45.0 if i % 2 else 20.0) for i, v in enumerate(vs)}
    out, proxy = d.enforce_flow_floor(dict(valves))
    assert out, "floor did not act on a set well below it"
    worst = max(out.values())
    assert worst <= 50.0, (
        f"raised a circuit to {worst} %, past the 50 % saturation point - "
        "that is flow on paper only")
    assert proxy is not None and proxy <= 50.0


def test_the_unreachable_branch_also_stops_at_saturation(cfg, demand):
    """The escape hatch had its own hardcoded 100. A floor that cannot be met
    should open everything to the point where opening still does something,
    and then say so - not command into dead range and look satisfied."""
    cfg["control"]["distribution"] = {"open_threshold_pct": 20.0,
                                      "full_open_pct": 50.0}
    d = demand(min_open_pct=90.0)                     # impossible by design
    out, _ = d.enforce_flow_floor({v: 20.0 for v in d.circuit_valves})
    assert set(out.values()) == {50.0}, (
        f"unreachable floor commanded into the dead range: {sorted(set(out.values()))}")


def test_auto_mode_never_overrules_an_explicit_off(demand):
    """Regression, found while adding the start-up one-shot on 2026-08-19.

    `off` is not a season, it is an operator stopping the plant, and
    `_want_source` treats it as the only route to a stopped source. The dwell
    path could already overrule it after an hour; the one-shot would have done
    it within seconds of every restart - so a plant parked off would have come
    back on by itself on the next deploy.
    """
    d = demand()
    for now in (0.0, 1.0, 10_000.0):
        out = d.step("off", {"a": 21.0}, {"a": 10.0}, {}, now)   # +11 K, wants heat
        assert out.mode == "off", f"auto_mode left `off` at t={now}"
        assert out.source_request is False
