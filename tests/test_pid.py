"""PID: direction, anti-windup, clamping.

`invert` is the interesting part. It is what makes one controller serve both
heating and cooling, and getting it wrong does not crash or look odd in a unit
- it silently drives the plant the wrong way. See test_controller.py for the
regression that caught exactly that in the wiring.
"""
from __future__ import annotations

from heatctl.pid import PID


def test_heating_opens_when_the_room_is_too_cold():
    pid = PID(kp=10.0, ki=0.0)
    assert pid.step(21.0, 19.0, 1.0) == 20.0     # 2 K below target -> open


def test_heating_closes_when_the_room_is_too_warm():
    pid = PID(kp=10.0, ki=0.0)
    assert pid.step(21.0, 23.0, 1.0) == 0.0      # clamped at out_min


def test_cooling_inverts_the_direction():
    """Same error, opposite response - the whole point of `invert`."""
    heat = PID(kp=10.0, ki=0.0)
    cool = PID(kp=10.0, ki=0.0, invert=True)
    # Room ABOVE setpoint: heating shuts, cooling opens.
    assert heat.step(21.0, 23.0, 1.0) == 0.0
    assert cool.step(21.0, 23.0, 1.0) == 20.0
    # Room BELOW setpoint: the reverse.
    heat.reset(); cool.reset()
    assert heat.step(21.0, 19.0, 1.0) == 20.0
    assert cool.step(21.0, 19.0, 1.0) == 0.0


def test_output_is_clamped_to_configured_band():
    pid = PID(kp=1000.0, ki=0.0, out_min=0.0, out_max=100.0)
    assert pid.step(21.0, 0.0, 1.0) == 100.0
    pid.reset()
    assert pid.step(21.0, 99.0, 1.0) == 0.0


def test_integrator_accumulates_towards_the_setpoint():
    pid = PID(kp=0.0, ki=1.0)                    # pure integral
    first = pid.step(21.0, 20.0, 1.0)
    second = pid.step(21.0, 20.0, 1.0)
    assert 0 < first < second                    # 1 K error, 1 s per step


def test_anti_windup_bounds_the_integrator_while_saturated():
    """A long saturated period must not build an unrecoverable integral.

    Without anti-windup the integrator keeps growing while the output is
    already pinned at 100 %, and the controller then refuses to close for as
    long as it took to wind up. In a heating system that is hours of overshoot.
    """
    pid = PID(kp=1.0, ki=5.0, out_min=0.0, out_max=100.0)
    for _ in range(1000):                        # far beyond saturation
        pid.step(30.0, 0.0, 1.0)
    assert pid.step(30.0, 0.0, 1.0) == 100.0
    # The error reverses; the output must come off the rail promptly.
    out = [pid.step(30.0, 60.0, 1.0) for _ in range(5)]
    assert out[-1] == 0.0, f"still saturated after windup: {out}"


def test_reset_clears_integral_and_derivative_history():
    pid = PID(kp=0.0, ki=1.0, kd=1.0)
    for _ in range(10):
        pid.step(21.0, 20.0, 1.0)
    pid.reset()
    assert pid._i == 0.0
    assert pid._last_pv is None
    # First step after reset behaves like a fresh controller.
    assert pid.step(21.0, 20.0, 1.0) == PID(kp=0.0, ki=1.0, kd=1.0).step(
        21.0, 20.0, 1.0)


def test_derivative_opposes_rapid_approach_in_both_directions():
    """Derivative must follow `invert` too, or it destabilises cooling."""
    heat = PID(kp=0.0, ki=0.0, kd=1.0, out_min=-100.0, out_max=100.0)
    heat.step(21.0, 19.0, 1.0)
    rising = heat.step(21.0, 20.0, 1.0)          # pv climbing toward target
    cool = PID(kp=0.0, ki=0.0, kd=1.0, invert=True,
               out_min=-100.0, out_max=100.0)
    cool.step(21.0, 23.0, 1.0)
    falling = cool.step(21.0, 22.0, 1.0)         # pv falling toward target
    # Both are "approaching the setpoint", so both must brake, i.e. same sign.
    assert rising < 0 and falling < 0


def test_zero_dt_does_not_divide_by_zero():
    """The loop can be called twice within one clock tick."""
    pid = PID(kp=1.0, ki=1.0, kd=1.0)
    pid.step(21.0, 20.0, 1.0)
    pid.step(21.0, 20.0, 0.0)                    # must not raise
