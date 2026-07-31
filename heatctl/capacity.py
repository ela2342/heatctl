"""Compressor frequency ceiling: take as much spread as the dew point allows.

**Spread is how the plant delivers capacity**, not a hazard to be minimised.
Q = m_dot * c * dT, and flow is fixed by the pump, so the spread IS the
delivered power. Capping the compressor to shrink the spread trades away
capacity; the only reason to do it is that the spread also pushes the supply
temperature down toward the condensation limit.

So the objective is a maximisation with a constraint, not a minimisation:

    maximise spread  subject to  manifold supply >= condensation limit + margin

Measured 2026-07-30, which is what motivated this. Uncapped, the unit ran 79-80
Hz with a 4.5 K spread and drove the manifold supply to 15.3 against a 16.0
limit - a breach, valves forced shut, no cooling delivered. Capped by hand to
45 Hz it ran 44-45 Hz with a 1.4-2.5 K spread and 2.8 K of margin - safe, but
now leaving capacity unused on a 38 degC day. Neither hand-picked value is
right for long: the correct ceiling moves with the dew point, hour by hour.

**The actuator is `0x00F1` (R32, max frequency in silent cooling mode)**, which
was measured to actually bind - unlike `0x00C5` R13, whose name suggests the
same thing and which the unit ignores. It requires silent mode enabled
(`0x0001` bit 5), and that in turn requires `0x00F4` (D09, silent-mode fan cap)
to have been raised from its default of 60, which is 7.5 % of the ~800 RPM the
fan actually needs. This controller does NOT manage those two - it refuses to
act unless they are already right, because a frequency ceiling with a throttled
condenser fan is a high-pressure trip waiting to happen.

**Asymmetric by design, like every other guard here.** Raising the ceiling
spends capacity we might not get back if it breaches; lowering it protects the
slab. So increases are slow and rate-limited, decreases are immediate. And
every write wears the unit's flash (docs/HEATPUMP.md), so the cadence is minutes
rather than seconds and no-ops never reach the bus.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("heatctl.capacity")

HOLD, RAISE, LOWER, BLOCKED = "hold", "raise", "lower", "blocked"


@dataclass
class CapacityDecision:
    target_hz: float | None      # None = leave the ceiling alone
    reason: str
    kind: str = HOLD


class CapacityController:
    def __init__(self, cfg: dict):
        c = dict(cfg["control"].get("capacity") or {})
        self.enabled = bool(c.get("enabled", False))
        # How much margin to hold between the manifold supply and the
        # condensation limit. This is the setpoint of this loop: the controller
        # pushes frequency up until the supply sits this far above the limit.
        self.target_margin_c = float(c.get("target_margin_c", 1.0))
        self.deadband_c = float(c.get("deadband_c", 0.4))
        # PROPORTIONAL STEP, not a fixed one. The step is the error divided by
        # the plant's gain, so one write corrects the whole error instead of
        # walking toward it. Observed 2026-07-31 15:06 with a fixed 2 Hz step:
        # three writes in three consecutive seconds (46->44->42->40), because
        # lowering is deliberately un-rate-limited and each write only moved a
        # fraction of the error. Every one of those is a flash cycle.
        #
        # This is the P of the PI agreed with the owner. The integral term is
        # deliberately NOT here yet: it needs anti-windup for the two ways this
        # actuator saturates (max frequency, and the compressor modulating
        # BELOW the ceiling so the ceiling has no authority at all), and that
        # is worth doing properly rather than bolting on.
        self.supply_k_per_hz = float(c.get("supply_k_per_hz", 0.074))
        # Dimensionless loop gain. Closing the ENTIRE error in one move is
        # unstable on a plant with transport lag, so take a fraction of it and
        # let successive cycles converge - textbook proportional control.
        self.loop_gain = float(c.get("loop_gain", 0.5))
        self.step_min_hz = float(c.get("step_min_hz", 1.0))
        self.step_max_hz = float(c.get("step_max_hz", 10.0))
        # RAISE SETTLE TIME. Same reasoning as `lower_settle_s` below: wait for
        # the plant to respond before judging the error again. It was 600 s,
        # which made sense when the step was small and FIXED - many little
        # writes would otherwise burn flash. With a proportional step one move
        # closes the error, so the only thing left to wait for is the process.
        #
        # Measured 2026-07-31: raises at 16:15:28 and 16:25:28, exactly 600 s
        # apart and gated by the clock rather than the error - the controller
        # sat on ~1 K of unused margin, about 1.3 kW of cooling, for ten minutes
        # at a time all afternoon.
        #
        # 2x the lowering settle, deliberately: both directions face the same
        # 1-3 min process, but raising spends margin that a breach would cost
        # us, so the asymmetric CONSEQUENCE gets an asymmetric wait.
        self.raise_interval_s = float(c.get("raise_interval_s", 120.0))
        # SETTLE TIME ON THE LOWERING PATH. Not a rate limit for wear's sake -
        # it is control. The manifold transport plus compressor response is
        # 1-3 min, so writing again after one second means acting on an error
        # the previous write has not had time to correct. That is integrating
        # your own un-responded moves, and it is exactly what produced
        # 46->44->42->40 in three consecutive seconds on 2026-07-31.
        #
        # Deliberately much shorter than `raise_interval_s`: this is still the
        # protective direction and must not wait ten minutes. The FIRST move is
        # never delayed - only the follow-up.
        self.lower_settle_s = float(c.get("lower_settle_s", 60.0))
        self._last_lower: float | None = None
        self.min_hz = float(c.get("min_hz", 35.0))
        self.max_hz = float(c.get("max_hz", 90.0))
        # Frequency must be within this of the ceiling before raising it means
        # anything. If the unit is modulating well below the ceiling, the
        # ceiling is not what is limiting capacity and raising it buys nothing
        # but a flash cycle.
        self.at_ceiling_hz = float(c.get("at_ceiling_hz", 3.0))
        self._last_raise: float | None = None

    def step(self, mode: str, supply_temp: float | None,
             supply_limit: float | None, current_ceiling: float | None,
             compressor_hz: float | None, silent_ok: bool,
             now: float) -> CapacityDecision:
        """Decide the frequency ceiling. See the module docstring for why."""
        if not self.enabled or mode != "cooling":
            return CapacityDecision(None, "disabled")
        if current_ceiling is None:
            return CapacityDecision(None, "ceiling unknown")
        if not silent_ok:
            # Refuse rather than proceed: the ceiling only binds in silent mode,
            # and silent mode with the default fan cap throttles the condenser
            # to 7.5 % of what it needs. Acting here without both in place would
            # either do nothing or damage the unit.
            return CapacityDecision(
                None, "silent mode or fan cap not configured", BLOCKED)
        if supply_temp is None or supply_limit is None:
            # No measurement of the constrained quantity means no basis to
            # spend capacity. Holding is safe; the setpoint loop still runs.
            return CapacityDecision(None, "no supply measurement")

        margin = supply_temp - supply_limit
        err = margin - self.target_margin_c

        # LOWER: the first move is immediate - the protective direction must
        # never wait for a timer. Follow-ups wait `lower_settle_s` so the plant
        # can actually respond before we judge the error again.
        if err < -self.deadband_c:
            if (self._last_lower is not None
                    and now - self._last_lower < self.lower_settle_s):
                return CapacityDecision(
                    None, f"margin {margin:+.2f} K low, waiting for the last "
                          f"move to take effect")
            target = max(self.min_hz, current_ceiling - self._step_for(err))
            if target >= current_ceiling:
                return CapacityDecision(
                    None, f"margin {margin:+.2f} K but already at {self.min_hz:.0f} Hz",
                    BLOCKED)
            self._last_lower = now
            return CapacityDecision(
                target, f"margin {margin:+.2f} K below target "
                        f"{self.target_margin_c:.1f} - backing off", LOWER)

        if err <= self.deadband_c:
            self._last_raise = self._last_raise or now
            return CapacityDecision(None, f"margin {margin:+.2f} K - in band")

        # SEED ON FIRST USE, and do not act. Observed 2026-07-30: a deploy
        # restarts the App twice, and with `_last_raise` starting at None both
        # instances raised immediately - 45 -> 50 -> 55 Hz in 38 seconds against
        # a 600 s interval. A restart loop would ratchet the ceiling to its
        # maximum a step at a time, spending capacity nobody asked for and a
        # flash cycle each time.
        #
        # setpoint.py already documents fixing exactly this for its own trim
        # clock; the same reasoning applies here and the pattern should have been
        # carried over. Lowering is deliberately NOT gated this way - it is the
        # protective direction and must work from the first cycle after a start.
        if self._last_raise is None:
            self._last_raise = now
            return CapacityDecision(
                None, f"margin {margin:+.2f} K spare, settling after start-up")

        # RAISE: only if the ceiling is actually what is limiting the machine.
        if compressor_hz is None or compressor_hz < current_ceiling - self.at_ceiling_hz:
            return CapacityDecision(
                None, f"margin {margin:+.2f} K spare but running "
                      f"{compressor_hz or 0:.0f} Hz under a "
                      f"{current_ceiling:.0f} Hz ceiling - not the constraint")
        if self._last_raise is not None and now - self._last_raise < self.raise_interval_s:
            return CapacityDecision(None, f"margin {margin:+.2f} K spare, "
                                          "within the raise interval")
        target = min(self.max_hz, current_ceiling + self._step_for(err))
        if target <= current_ceiling:
            return CapacityDecision(
                None, f"margin {margin:+.2f} K spare but already at "
                      f"{self.max_hz:.0f} Hz")
        self._last_raise = now
        return CapacityDecision(
            target, f"margin {margin:+.2f} K above target "
                    f"{self.target_margin_c:.1f} at the ceiling - taking more "
                    "capacity", RAISE)

    def _step_for(self, err: float) -> float:
        """Hz needed to close `err` kelvin of margin, bounded.

        `supply_k_per_hz` is the plant gain - how far the manifold supply moves
        per Hz of compressor ceiling. It is POORLY KNOWN (see config.yaml) and
        the bounds are what make that survivable: too small a gain estimate
        merely takes two writes instead of one, too large is clamped.
        """
        raw = self.loop_gain * abs(err) / max(self.supply_k_per_hz, 1e-6)
        return min(self.step_max_hz, max(self.step_min_hz, round(raw)))

    def note_write(self, now: float) -> None:
        """Called after a ceiling write of either direction.

        A lowering also resets the raise clock, so the controller cannot
        immediately undo a back-off it just decided was necessary.
        """
        self._last_raise = now
