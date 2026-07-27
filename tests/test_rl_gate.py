"""RL validity gating.

The defect being fixed is subtle enough to be worth restating: an ungated
return PID hunts, because a closed circuit's RL drifts toward slab ambient,
and slab ambient reads as "more demand" in BOTH modes. So these tests care
about two things - that fiction is never fed to the controller, and that a
gated circuit can still find its way back to a real measurement.
"""
from __future__ import annotations

import pytest

from heatctl.rl_gate import FLUSH, HOLD, MEASURE, RLGate


@pytest.fixture
def gate(cfg):
    def _make(**overrides):
        cfg["control"]["rl_gating"] = {
            "enabled": True, "min_opening_pct": 15.0, "settle_s": 300.0,
            "flush_interval_s": 3600.0, "flush_pct": 100.0, **overrides,
        }
        return RLGate(cfg)
    return _make


# ---------- the core rule ----------

def test_a_closed_circuit_is_never_measured(gate):
    g = gate()
    g.record_command("valve_hk01", 0.0, 0.0)
    assert g.action("valve_hk01", 100.0) == HOLD


def test_a_barely_open_circuit_is_not_measured(gate):
    """Below the deadband there is no flow, whatever the command says."""
    g = gate()
    g.record_command("valve_hk01", 14.9, 0.0)
    assert g.action("valve_hk01", 10_000.0) == HOLD


def test_an_open_circuit_is_not_measured_until_it_has_settled(gate):
    """Water has to travel the loop before RL means anything."""
    g = gate()
    g.record_command("valve_hk01", 100.0, 0.0)
    assert g.action("valve_hk01", 299.0) == HOLD
    assert g.action("valve_hk01", 300.0) == MEASURE


def test_settling_restarts_when_the_circuit_closes_again(gate):
    g = gate()
    g.record_command("valve_hk01", 100.0, 0.0)
    assert g.action("valve_hk01", 300.0) == MEASURE
    g.record_command("valve_hk01", 0.0, 310.0)        # closed again
    g.record_command("valve_hk01", 100.0, 320.0)      # and reopened
    assert g.action("valve_hk01", 500.0) == HOLD      # not yet settled
    assert g.action("valve_hk01", 620.0) == MEASURE


def test_staying_open_keeps_the_circuit_measurable(gate):
    """A circuit control is actively modulating must not be gated off."""
    g = gate()
    for t in range(0, 1200, 10):
        g.record_command("valve_hk01", 40.0, float(t))
    assert g.action("valve_hk01", 1200.0) == MEASURE


# ---------- recovery: a held circuit must not be stranded ----------

def test_a_held_circuit_is_eventually_flushed(gate):
    g = gate()
    g.record_command("valve_hk01", 100.0, 0.0)
    assert g.action("valve_hk01", 300.0) == MEASURE    # trusted at t=300
    g.record_command("valve_hk01", 0.0, 310.0)
    assert g.action("valve_hk01", 3000.0) == HOLD
    assert g.action("valve_hk01", 3900.0) == FLUSH     # 3600 s after t=300


def test_a_flush_persists_until_the_circuit_settles(gate):
    """Otherwise the very next cycle would close it again and measure nothing."""
    g = gate()
    g.record_command("valve_hk01", 100.0, 0.0)
    g.action("valve_hk01", 300.0)
    g.record_command("valve_hk01", 0.0, 310.0)
    assert g.action("valve_hk01", 3900.0) == FLUSH
    g.record_command("valve_hk01", 100.0, 3900.0)      # caller opened it
    assert g.action("valve_hk01", 4000.0) == FLUSH     # still travelling
    assert g.action("valve_hk01", 4200.0) == MEASURE   # settled


def test_the_flush_clock_restarts_after_a_successful_measurement(gate):
    g = gate()
    g.record_command("valve_hk01", 100.0, 0.0)
    g.action("valve_hk01", 300.0)
    g.record_command("valve_hk01", 0.0, 310.0)
    assert g.action("valve_hk01", 3900.0) == FLUSH
    g.record_command("valve_hk01", 100.0, 3900.0)
    assert g.action("valve_hk01", 4200.0) == MEASURE   # re-measured
    g.record_command("valve_hk01", 0.0, 4210.0)
    assert g.action("valve_hk01", 5000.0) == HOLD      # clock restarted
    assert g.action("valve_hk01", 7801.0) == FLUSH


def test_a_never_measured_circuit_holds_rather_than_flushing(gate):
    """Start-up must not force a multi-minute full-open on every deploy.

    The caller's fail-open fallback opens the circuit anyway, which produces a
    real reading without a special case - so an explicit start-up flush would
    be both redundant and disruptive.
    """
    g = gate()
    assert g.action("valve_hk01", 0.0) == HOLD
    assert g.action("valve_hk01", 99_999.0) == HOLD


# ---------- held value ----------

def test_held_falls_back_to_the_caller_default_before_any_measurement(gate):
    """Never measured is lost knowledge, so the caller's fail-open applies."""
    g = gate()
    assert g.held("valve_hk01", 100.0) == 100.0


def test_held_returns_the_last_output_taken_while_trusted(gate):
    g = gate()
    g.note_control("valve_hk01", 37.0)
    assert g.held("valve_hk01", 100.0) == 37.0


# ---------- circuits with no actuator ----------

def test_unactuated_circuits_are_always_measurable(cfg):
    """Open pipe always flows, so gating on our command would be fiction."""
    cfg["valves"]["channels"] = [
        {"index": 1, "name": "valve_hk01", "fitted": True},
        {"index": 2, "name": "valve_hk02", "fitted": False},
    ]
    cfg["control"]["rl_gating"] = {"enabled": True}
    g = RLGate(cfg)
    assert g.action("valve_hk02", 0.0) == MEASURE
    assert g.action("valve_hk01", 0.0) == HOLD


def test_channels_default_to_fitted(cfg):
    """Absent `fitted` must mean 'assume it is there' - the safe reading.

    Assuming unfitted would silently disable gating on a real actuator.
    """
    cfg["valves"]["channels"] = [{"index": 1, "name": "valve_hk01"}]
    cfg["control"]["rl_gating"] = {"enabled": True}
    assert RLGate(cfg).action("valve_hk01", 0.0) == HOLD


# ---------- kill switch ----------

def test_gating_can_be_disabled(cfg):
    cfg["control"]["rl_gating"] = {"enabled": False}
    g = RLGate(cfg)
    g.record_command("valve_hk01", 0.0, 0.0)
    assert g.action("valve_hk01", 100.0) == MEASURE


def test_absent_config_section_still_gates(cfg):
    """The defect is real; a missing config block must not silently reopen it."""
    cfg["control"].pop("rl_gating", None)
    assert RLGate(cfg).action("valve_hk01", 0.0) == HOLD
