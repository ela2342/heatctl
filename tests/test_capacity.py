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


def test_an_idle_compressor_is_stopped_once_without_walking_the_ceiling(cap):
    """Real defect, 2026-10-04 20:02-20:26, from the journal.

    The compressor was at 0 Hz throughout and the margin was -0.46..-0.75 K
    (a humid bathroom put the dew limit above the water). The LOWER path
    walked the ceiling 67 -> 64 -> 59 -> ... -> 30 Hz, one write per settle,
    then wrote STOP at the floor: nine flash writes to a compressor that was
    not running. The STOP was worth keeping - an idle unit restarts on its
    own setpoint, into water already below the limit - the walk was not.

    Mutation-verified: without the idle branch this returns LOWER 67 -> 57.
    """
    c = cap(min_hz=30.0, max_hz=90.0)
    d = call(c, supply=15.54, limit=16.0, ceiling=67.0, hz=0.0, now=0.0)
    assert d.kind == STOP and d.stops
    assert d.target_hz is None, "the ceiling must not be written"


def test_an_unreadable_frequency_is_not_treated_as_idle(cap):
    """Unknown is not idle. Without a frequency reading the protective walk
    stays in charge, because the compressor may well be running."""
    c = cap()
    d = call(c, supply=16.2, limit=16.0, ceiling=60.0, hz=None, now=0.0)
    assert d.kind == LOWER and d.target_hz == 55.0


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


def _ramp(c, trace, limit=15.1, t0=10_000.0, dt=30.0):
    """Feed (supply, ceiling, hz) samples every `dt` seconds, with 1 s cycles
    in between as the real loop does, and return the decisions at each sample.
    The trace opens just after a raise, as both measured ones did."""
    c._last_raise = t0
    out = []
    for i, (supply, ceiling, hz) in enumerate(trace):
        base = t0 + i * dt
        for k in range(int(dt)):
            d = call(c, supply=supply, limit=limit, ceiling=ceiling, hz=hz,
                     now=base + k)
            if d.kind == RAISE:
                out.append(d)
                break
        else:
            out.append(d)
    return out


def test_2026_09_28_a_falling_margin_is_not_spent(cap):
    """2026-09-28 14:30-14:35, the journal's trace at 30 s. The compressor was
    AT a 60 Hz ceiling and the margin (limit 15.1) was falling ~0.2 K every
    30 s from +3.1. The loop raised 60->70->80->86 on the level alone, and the
    supply went on to 13.7 - 0.4 K under the dew point itself - before the
    compressor backed off by its own setpoint.

    Mutation-verified: with the falling-margin veto removed this raises."""
    c = cap(target_margin_c=0.0, deadband_c=0.25, raise_interval_s=120.0)
    trace = [(18.2 - 0.1 * i, 60.0, 59.0) for i in range(12)]   # 18.2 -> 17.1
    decisions = _ramp(c, trace)
    assert not any(d.kind == RAISE for d in decisions)
    assert "still falling" in decisions[-1].reason


def test_a_flickering_steady_margin_still_raises(cap):
    """The veto must not cost steady-state capacity. 2026-09-28 15:00 the
    margin sat at +0.96/+1.06 - one count of flicker - for half an hour."""
    c = cap(target_margin_c=0.0, deadband_c=0.25, raise_interval_s=120.0)
    trace = [(16.2 if i % 2 else 16.1, 45.0, 45.0) for i in range(8)]
    assert any(d.kind == RAISE for d in _ramp(c, trace))


def test_a_margin_that_has_stopped_falling_is_spent(cap):
    """The veto withholds a raise; it does not forbid one. Once the drop has
    left the window the level decides again."""
    c = cap(target_margin_c=0.0, deadband_c=0.25, raise_interval_s=120.0)
    falling = [(18.0 - 0.1 * i, 45.0, 45.0) for i in range(4)]
    flat = [(17.7, 45.0, 45.0)] * 8
    decisions = _ramp(c, falling + flat)
    assert not any(d.kind == RAISE for d in decisions[:4])
    assert any(d.kind == RAISE for d in decisions[4:])


def test_a_falling_margin_does_not_delay_lowering(cap):
    """Direction of failure: the veto is on spending, never on protecting.
    A margin falling fast through the band must still back off at once."""
    c = cap(target_margin_c=0.0, deadband_c=0.25)
    for k in range(60):
        call(c, supply=16.0 - 0.01 * k, limit=15.1, ceiling=80.0, hz=80.0,
             now=10_000.0 + k)
    d = call(c, supply=14.7, limit=15.1, ceiling=80.0, hz=80.0, now=10_060.0)
    assert d.kind == LOWER and d.target_hz < 80.0


def test_a_compressor_over_its_ceiling_is_in_its_start_ramp(cap):
    """The ceiling does not grip in the first minute after a start (measured
    2026-08-12). 2026-09-28 14:31: 66 Hz against a 60 Hz ceiling, read as "at
    the ceiling", and the ceiling went up.

    Mutation-verified: without the over-the-ceiling check this raises."""
    d = call(cap(), supply=18.0, limit=16.0, ceiling=60.0, hz=66.0)
    assert d.kind != RAISE and "start ramp" in d.reason


def test_a_reading_gap_re_arms_the_start_up_settle(cap):
    """An empty history is not a flat one. After the supply reading drops out,
    the first readings back must not be spent before a trend has been watched.

    Mutation-verified: without the re-arm this raises on the first reading."""
    c = cap(target_margin_c=0.0, deadband_c=0.25, raise_interval_s=120.0)
    assert call(c, supply=None, limit=15.1, now=10_000.0).target_hz is None
    d = call(c, supply=16.1, limit=15.1, ceiling=45.0, hz=45.0, now=10_001.0)
    assert d.kind != RAISE and "settling" in d.reason
    for k in range(2, 125):
        d = call(c, supply=16.1, limit=15.1, ceiling=45.0, hz=45.0,
                 now=10_000.0 + k)
        if d.kind == RAISE:
            break
    assert d.kind == RAISE
