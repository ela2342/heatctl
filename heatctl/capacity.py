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
        self.step_hz = float(c.get("step_hz", 5.0))
        self.raise_interval_s = float(c.get("raise_interval_s", 600.0))
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

        # LOWER: immediate, no rate limit. This is the protective direction and
        # the supply is already closer to the limit than intended.
        if err < -self.deadband_c:
            target = max(self.min_hz, current_ceiling - self.step_hz)
            if target >= current_ceiling:
                return CapacityDecision(
                    None, f"margin {margin:+.2f} K but already at {self.min_hz:.0f} Hz",
                    BLOCKED)
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
        target = min(self.max_hz, current_ceiling + self.step_hz)
        if target <= current_ceiling:
            return CapacityDecision(
                None, f"margin {margin:+.2f} K spare but already at "
                      f"{self.max_hz:.0f} Hz")
        self._last_raise = now
        return CapacityDecision(
            target, f"margin {margin:+.2f} K above target "
                    f"{self.target_margin_c:.1f} at the ceiling - taking more "
                    "capacity", RAISE)

    def note_write(self, now: float) -> None:
        """Called after a ceiling write of either direction.

        A lowering also resets the raise clock, so the controller cannot
        immediately undo a back-off it just decided was necessary.
        """
        self._last_raise = now
