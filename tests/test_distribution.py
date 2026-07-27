"""Valve distribution.

The objective is efficiency, not pump protection: maximise flow, minimise the
leaving/return spread, let the water sit closer to room temperature. Throttling
is a cost paid only to share energy between rooms, so these tests care about
*ratios preserved* and *flow not thrown away* — and about the two numerical
traps at the bottom of the demand range.
"""
from __future__ import annotations

import pytest

from heatctl.distribution import Distributor


@pytest.fixture
def dist(cfg):
    def _make(**over):
        cfg["control"]["distribution"] = {
            "enabled": True, "eps": 5.0, "max_peak_step_per_cycle": 1e9,
            "open_threshold_pct": 0.0, "full_open_pct": 100.0, **over,
        }
        return Distributor(cfg)
    return _make


def test_the_most_demanding_circuit_is_driven_fully_open(dist):
    """The whole point: never leave flow on the table."""
    out = dist().apply({"a": 80.0, "b": 5.0, "c": 5.0})
    assert out["a"] == 100.0


def test_ratios_between_rooms_are_preserved(dist):
    """That is what distribution MEANS - the absolute level is the water
    temperature's job, not the valves'."""
    out = dist().apply({"a": 80.0, "b": 5.0, "c": 5.0})
    assert out["b"] == out["c"] < out["a"]
    assert out["b"] == pytest.approx(11.8, abs=0.1)   # (5+5)/(80+5)


def test_perfect_equilibrium_opens_everything(dist):
    """The 0/0 case. Not a degenerate case being papered over: with nothing to
    distribute there is no reason to throttle anything, and maximum flow is
    exactly what is wanted."""
    out = dist().apply({"a": 0.0, "b": 0.0, "c": 0.0})
    assert out == {"a": 100.0, "b": 100.0, "c": 100.0}


def test_low_demand_converges_toward_all_open_rather_than_amplifying_noise(dist):
    """Naive d/max would turn [0.001, 0.0005] into [100, 50] - a ratio of
    noise. Discrimination has to fade out as demand falls."""
    out = dist().apply({"a": 0.001, "b": 0.0005})
    assert out["a"] == 100.0
    assert out["b"] > 99.0


def test_discrimination_returns_as_demand_grows(dist):
    """eps must not flatten a genuinely uneven house."""
    out = dist().apply({"a": 100.0, "b": 0.0})
    assert out["a"] == 100.0
    assert out["b"] < 10.0


def test_eps_trades_flow_against_discrimination(dist):
    """The knob is a real engineering trade-off, so its direction matters:
    larger eps -> flatter -> more flow -> better COP, less per-room control."""
    demands = {"a": 50.0, "b": 10.0}
    flat = dist(eps=50.0).apply(demands)
    sharp = dist(eps=1.0).apply(demands)
    assert flat["b"] > sharp["b"]


def test_a_single_circuit_is_simply_opened(dist):
    assert dist().apply({"a": 3.0}) == {"a": 100.0}


def test_nothing_to_do_with_no_circuits(dist):
    assert dist().apply({}) == {}


def test_disabled_passes_demands_through_untouched(dist):
    d = dist(enabled=False)
    assert d.apply({"a": 40.0, "b": 0.0}) == {"a": 40.0, "b": 0.0}


# ---------- coupling ----------

def test_the_reference_peak_is_slew_limited(dist):
    """Normalisation couples the circuits: a change in the most-demanding room
    rescales every other one. Unlimited, one room's transient would re-throttle
    the whole house at once, against actuators that take minutes to move."""
    d = dist(max_peak_step_per_cycle=2.0)
    d.apply({"a": 100.0, "b": 50.0})          # seeds the peak at 100
    out = d.apply({"a": 0.0, "b": 50.0})      # peak collapses
    assert d._peak == 98.0                     # moved by 2, not 100
    assert out["b"] < 60.0                     # b has not jumped wide open yet


def test_the_peak_is_seeded_without_limiting_on_the_first_cycle(dist):
    """Otherwise start-up would crawl from zero for minutes."""
    d = dist(max_peak_step_per_cycle=2.0)
    d.apply({"a": 90.0})
    assert d._peak == 90.0


# ---------- actuator deadband mapping ----------

def test_the_effective_range_is_mapped_when_measured(dist):
    """docs/DESIGN.md 4.1.2. 'Fully open' means the measured full_open_pct,
    not the number 100 - and there is a deadband at the bottom that probably
    mirrors one at the top."""
    d = dist(open_threshold_pct=20.0, full_open_pct=80.0)
    out = d.apply({"a": 100.0, "b": 0.0})
    assert out["a"] == 80.0                    # peak -> measured full open
    assert out["b"] >= 20.0                    # nothing below the threshold


def test_the_default_mapping_is_identity(cfg):
    """Unmeasured today: two actuators, no flow meters. Identity until there
    are real numbers, so the mapping cannot silently distort anything."""
    cfg["control"]["distribution"] = {"enabled": True}
    d = Distributor(cfg)
    assert (d.open_threshold_pct, d.full_open_pct) == (0.0, 100.0)
