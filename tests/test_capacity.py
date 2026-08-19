"""Compressor frequency ceiling.

Spread is how the plant delivers capacity, so this loop MAXIMISES it subject to
the manifold supply staying clear of the condensation limit. Tests assert the
direction of each move and the asymmetry between them - raising spends capacity
that may not come back, lowering protects the slab.
"""
from __future__ import annotations

import pytest

from heatctl.capacity import BLOCKED, LOWER, RAISE, RESUME, STOP, CapacityController


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
         now=10_000.0, mode="cooling", stopped=False):
    return c.step(mode=mode, supply_temp=supply, supply_limit=limit,
                  current_ceiling=ceiling, compressor_hz=hz,
                  silent_ok=silent, now=now, stopped=stopped)


def test_spare_margin_at_the_ceiling_takes_more_capacity(cap):
    """The whole point: 2 K of margin going unused on a 38 degC day is capacity
    left on the table, and the spread is how the plant delivers it."""
    RETARGETED = """The step is now PROPORTIONAL to the error, not fixed
    (2026-07-31). Margin 2.0 against a 1.0 target is a 1.0 K error, so at
    loop_gain 0.5 and 0.074 K/Hz that is 0.5*1.0/0.074 = 7 Hz, not the old
    flat 5. The behaviour under test - spare margin at the ceiling is taken as
    capacity - is unchanged; only the size of the move is derived now."""
    d = call(cap(), supply=18.0, limit=16.0, ceiling=45.0, hz=45.0)
    assert d.kind == RAISE and d.target_hz == 52.0


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
    """RETARGETED 2026-07-31: the bottom of the range is no longer BLOCKED.

    At `min_hz` with the supply still too cold there is no smaller step, and
    what lies below the frequency floor is OFF - so the decision is STOP, not
    "give up". Reaching for the setpoint instead is what the owner rejected:
    slow, a modulation rather than a stop, and it puts the condensation
    constraint back onto P04.
    """
    c = cap(min_hz=35.0, max_hz=90.0)
    assert call(c, supply=16.1, ceiling=35.0).kind == STOP
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
    RETARGETED = """Proportional step (2026-07-31): margin 0.1 against a 1.0
    target is a 0.9 K error, so 0.5*0.9/0.074 = 6 Hz. The property under test -
    that lowering is never delayed by the start-up seed - is unchanged."""
    c = cap(primed=False)
    d = call(c, supply=16.1, limit=16.0, ceiling=60.0, now=1_000.0)
    assert d.kind == LOWER and d.target_hz == 54.0


def test_one_write_closes_the_error_instead_of_walking_down(cap):
    """The defect this replaced. Measured 2026-07-31 15:06 with a fixed 2 Hz
    step: 46->44->42->40 in three consecutive seconds, three flash cycles to
    correct one error, because lowering is deliberately un-rate-limited and
    each write moved only a fraction of it.

    TWO fixes apply, and the settle time is the load-bearing one. A
    proportional step sizes the move to the error; a settle time then stops the
    loop judging that error again before the plant has responded to it. Within
    one second of a move, the answer must be "wait", not "move again".
    """
    c = cap()
    d = call(c, supply=16.3, limit=16.0, ceiling=46.0, hz=46.0, now=1_000.0)
    assert d.kind == LOWER and d.target_hz is not None
    c.note_write(1_000.0)
    # one second later, same error: the previous move cannot have taken effect
    again = call(c, supply=16.3, limit=16.0, ceiling=d.target_hz,
                 hz=d.target_hz, now=1_001.0)
    assert again.target_hz is None, "wrote again before the plant could respond"
    assert "waiting" in again.reason
    # after the settle time it may act again
    later = call(c, supply=16.3, limit=16.0, ceiling=d.target_hz,
                 hz=d.target_hz, now=1_100.0)
    assert later.kind == LOWER and later.target_hz is not None


def test_the_step_is_bounded_at_both_ends(cap):
    """The plant gain is POORLY known, and the bounds are what make that
    survivable: a bad estimate costs an extra cycle, never a lurch."""
    c = cap()
    assert c._step_for(0.001) == c.step_min_hz     # never write for nothing
    assert c._step_for(50.0) == c.step_max_hz      # nor lurch on one estimate


# ---------- the bottom of the range: STOP and RESUME ----------

def test_at_the_frequency_floor_and_still_too_cold_it_stops(cap):
    """There is no smaller step below `min_hz`; what is below it is OFF.

    Reaching for the SETPOINT here is what the owner rejected on 2026-07-31 -
    slow, a modulation rather than a stop, and it puts the condensation
    constraint back onto P04. Mutation-verified: returning BLOCKED instead
    leaves the plant running too cold with nothing left to do about it.
    """
    c = cap(min_hz=35.0)
    d = call(c, supply=16.0, limit=16.5, ceiling=35.0, hz=35.0, now=0.0)
    assert d.kind == STOP and d.stops
    assert d.target_hz is None, "a stop is not a frequency"


def test_a_stopped_compressor_does_not_restart_inside_the_anti_short_cycle(cap):
    """The machine already cycles ~10 min on / ~9 min off unaided. Restarting
    sooner than that fights its own rhythm and wears the compressor."""
    c = cap(min_hz=35.0, min_off_s=600.0)
    call(c, supply=16.0, limit=16.5, ceiling=35.0, hz=35.0, now=0.0)   # stop
    d = call(c, supply=20.0, limit=16.5, ceiling=35.0, hz=0.0, now=100.0,
             stopped=True)
    assert d.kind != RESUME and "anti-short-cycle" in d.reason


def test_it_resumes_once_the_margin_is_clearly_safe_and_the_wait_is_over(cap):
    c = cap(min_hz=35.0, min_off_s=600.0)
    call(c, supply=16.0, limit=16.5, ceiling=35.0, hz=35.0, now=0.0)   # stop
    d = call(c, supply=20.0, limit=16.5, ceiling=35.0, hz=0.0, now=1_000.0,
             stopped=True)
    assert d.kind == RESUME and d.resumes


def test_it_does_not_resume_onto_a_thin_margin(cap):
    """Hysteresis. Restarting at the same threshold that stopped us would
    chatter the compressor on the boundary."""
    c = cap(min_hz=35.0, min_off_s=600.0)
    call(c, supply=16.0, limit=16.5, ceiling=35.0, hz=35.0, now=0.0)
    d = call(c, supply=16.6, limit=16.5, ceiling=35.0, hz=0.0, now=1_000.0,
             stopped=True)
    assert d.kind != RESUME and "too thin" in d.reason


def test_a_stopped_compressor_with_no_supply_reading_stays_stopped(cap):
    """No basis to judge a restart is not a reason to restart."""
    c = cap(min_hz=35.0)
    d = call(c, supply=None, limit=16.5, ceiling=35.0, hz=0.0, now=9_999.0,
             stopped=True)
    assert d.kind != RESUME


def test_a_resume_does_not_immediately_spend_the_margin_its_own_stop_created(cap):
    """Regression, night of 2026-08-11/12: 22 stop/restart cycles in 5 hours.

    The stop is what warms the water, and warm water IS the resume condition.
    So on every restart the loop found a large positive margin, read it as
    steady-state headroom, and raised the ceiling 45 s later - into a plant
    that had not responded yet. It then had to walk the ceiling back down to
    the floor and stop again. Six flash writes per cycle, self-sustaining.

    The bug was that RESUME left `_last_raise` holding a timestamp from before
    the stop, and a stop lasts at least `min_off_s`, so the raise gate was
    always already satisfied on the way back up.
    """
    c = cap(min_hz=35.0, min_off_s=600.0, raise_interval_s=120.0)
    # Run for a while, then hit the floor and stop.
    call(c, supply=18.0, limit=16.5, ceiling=45.0, hz=45.0, now=0.0)
    call(c, supply=16.0, limit=16.5, ceiling=35.0, hz=35.0, now=100.0)   # STOP
    # Ten minutes off; the water has recovered well past the restart threshold.
    d = call(c, supply=20.0, limit=16.5, ceiling=35.0, hz=0.0, now=800.0,
             stopped=True)
    assert d.resumes
    # 45 s later, at the ceiling, with that same generous margin still showing.
    d = call(c, supply=19.8, limit=16.5, ceiling=35.0, hz=35.0, now=845.0)
    assert d.kind != RAISE, (
        "raised on the transient its own stop produced - this is the "
        "2026-08-12 limit cycle")
    assert d.target_hz is None
    # And it is the raise INTERVAL holding it, not some other refusal, so the
    # loop still takes real headroom once the plant has actually settled.
    d = call(c, supply=19.8, limit=16.5, ceiling=35.0, hz=35.0, now=800.0 + 200.0)
    assert d.kind == RAISE


def test_a_breach_stops_the_compressor_even_with_no_usable_ceiling(cap):
    """The stop must not be gated behind the ceiling's preconditions.

    `silent_ok` and a known `current_ceiling` are requirements of R32, the
    frequency ceiling. STOP is a setpoint write to a different register. They
    were checked first anyway, so anything that disabled silent mode also
    disabled the stop - and after D-035 that stop is the only condensation
    enforcement left, with nothing behind it.

    The live trigger for finding this: `0x00F4` reads an out-of-range 65512, so
    `silent_ok` is currently true only because a garbage value happens to
    compare large.
    """
    c = cap(min_hz=35.0)
    d = call(c, supply=15.0, limit=16.5, ceiling=45.0, hz=45.0, silent=False)
    assert d.kind == STOP and d.stops, (
        "a measured breach did not stop the compressor because silent mode "
        "was off")

    c = cap(min_hz=35.0)
    d = call(c, supply=15.0, limit=16.5, ceiling=None, hz=45.0, silent=True)
    assert d.kind == STOP and d.stops, (
        "a measured breach did not stop the compressor because the ceiling "
        "register had not been read yet")


def test_a_healthy_margin_with_no_usable_ceiling_still_just_blocks(cap):
    """The new stop path must not fire on anything but a breach - otherwise a
    missing register read would stop the plant on a perfectly good margin."""
    d = call(cap(), supply=18.0, limit=16.0, silent=False)
    assert d.kind == BLOCKED and d.target_hz is None
