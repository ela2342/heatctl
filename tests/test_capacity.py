"""Compressor frequency ceiling.

Spread is how the plant delivers capacity, so this loop MAXIMISES it subject to
the manifold supply staying clear of the condensation limit. Tests assert the
direction of each move and the asymmetry between them - raising spends capacity
that may not come back, lowering protects the slab.
"""
from __future__ import annotations

import pytest

from heatctl.capacity import BLOCKED, LOWER, RAISE, CapacityController


@pytest.fixture
def cap(cfg):
    def _make(primed: bool = True, **over):
        """`primed` skips the post-start-up settling interval.

        The controller refuses to RAISE for a full interval after start-up (see
        the start-up tests at the bottom), which every other test here would
        otherwise have to work around. Pass primed=False to exercise it.
        """
        cfg["control"]["capacity"] = {
            "enabled": True, "target_margin_c": 1.0, "deadband_c": 0.4,
            "step_hz": 5.0, "raise_interval_s": 600.0, "min_hz": 35.0,
            "max_hz": 90.0, "at_ceiling_hz": 3.0, **over}
        c = CapacityController(cfg)
        if primed:
            c._last_raise = -1e6      # start-up settling already elapsed
        return c
    return _make


def call(c, supply=18.0, limit=16.0, ceiling=45.0, hz=45.0, silent=True,
         now=10_000.0, mode="cooling"):
    return c.step(mode=mode, supply_temp=supply, supply_limit=limit,
                  current_ceiling=ceiling, compressor_hz=hz,
                  silent_ok=silent, now=now)


def test_spare_margin_at_the_ceiling_takes_more_capacity(cap):
    """The whole point: 2 K of margin going unused on a 38 degC day is capacity
    left on the table, and the spread is how the plant delivers it."""
    d = call(cap(), supply=18.0, limit=16.0, ceiling=45.0, hz=45.0)
    assert d.kind == RAISE and d.target_hz == 50.0


def test_a_thin_margin_backs_off_immediately_with_no_rate_limit(cap):
    """Asymmetric on purpose. Measured 2026-07-30: uncapped, the supply hit 15.3
    against a 16.0 limit and the valves were forced shut - and with eight of ten
    circuits unactuated the guard could not stop cold water reaching the slab.
    Backing off must never wait for a timer."""
    c = cap()
    d = call(c, supply=16.2, limit=16.0, ceiling=60.0, now=0.0)
    assert d.kind == LOWER and d.target_hz == 55.0


def test_raising_is_rate_limited_but_lowering_is_not(cap):
    c = cap()
    assert call(c, supply=18.0, ceiling=45.0, now=0.0).kind == RAISE
    # a second raise moments later must be refused
    assert call(c, supply=18.0, ceiling=50.0, now=60.0).target_hz is None
    # but a back-off in the same moment is allowed
    assert call(c, supply=16.1, ceiling=50.0, now=61.0).kind == LOWER


def test_it_will_not_raise_when_the_ceiling_is_not_the_constraint(cap):
    """If the unit is modulating well under the ceiling, the ceiling is not what
    limits capacity - raising it buys nothing but a flash cycle."""
    d = call(cap(), supply=18.0, ceiling=60.0, hz=40.0)
    assert d.target_hz is None
    assert "not the constraint" in d.reason


def test_it_refuses_entirely_without_silent_mode_and_a_raised_fan_cap(cap):
    """The ceiling only binds in silent mode, and silent mode with the default
    fan cap throttles the condenser to 7.5 % of what it needs - which on a hot
    day is a high-pressure trip. Refuse rather than half-act."""
    d = call(cap(), silent=False)
    assert d.target_hz is None and d.kind == BLOCKED


def test_no_supply_measurement_holds(cap):
    """No measurement of the constrained quantity means no basis to spend
    capacity."""
    assert call(cap(), supply=None).target_hz is None
    assert call(cap(), limit=None).target_hz is None


def test_the_band_is_respected_in_both_directions(cap):
    c = cap()
    assert call(c, supply=17.2).target_hz is None      # +1.2, inside deadband
    assert call(c, supply=16.8).target_hz is None      # +0.8, inside deadband


def test_the_bounds_hold(cap):
    c = cap(min_hz=35.0, max_hz=90.0)
    assert call(c, supply=16.1, ceiling=35.0).kind == BLOCKED
    d = call(c, supply=20.0, ceiling=90.0, hz=90.0, now=99_999.0)
    assert d.target_hz is None


def test_heating_and_disabled_do_nothing(cap):
    assert call(cap(), mode="heating").target_hz is None
    assert call(cap(enabled=False)).target_hz is None


def test_no_raise_in_the_first_interval_after_start_up(cap):
    """REGRESSION, observed 2026-07-30. A deploy restarts the App twice, and with
    the raise clock starting empty both instances raised immediately - 45 to 50
    to 55 Hz in 38 seconds against a 600 s interval. A restart loop would ratchet
    the ceiling to maximum a step at a time, spending capacity nobody asked for
    and a flash cycle each time.

    setpoint.py already documents fixing exactly this for its own trim clock.
    """
    c = cap(primed=False)
    first = call(c, supply=18.0, ceiling=45.0, now=1_000.0)
    assert first.target_hz is None, "must not raise on the very first cycle"
    assert "settling" in first.reason
    # still refused inside the interval
    assert call(c, supply=18.0, ceiling=45.0, now=1_300.0).target_hz is None
    # allowed once a full interval has passed
    assert call(c, supply=18.0, ceiling=45.0, now=1_700.0).kind == RAISE


def test_lowering_is_NOT_delayed_by_the_start_up_seed(cap):
    """The protective direction must work from the first cycle. A plant that
    breaches thirty seconds after a restart cannot wait ten minutes."""
    c = cap(primed=False)
    d = call(c, supply=16.1, limit=16.0, ceiling=60.0, now=1_000.0)
    assert d.kind == LOWER and d.target_hz == 55.0
