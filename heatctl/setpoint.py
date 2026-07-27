"""Load compensation: house demand -> water temperature setpoint.

The missing third level of the cascade. Until this existed, the water
temperature was a constant that only ever moved upward, defensively, when the
condensation guard shoved it there - nothing connected "the house is 0.6 K too
warm" to "make water at N degC".

That matters because water temperature is the PRIMARY lever and the valves are
only distribution:

  * water too cold in cooling -> valves throttle down to compensate -> flow
    falls toward the pump's minimum -> a COP penalty and condensation risk
    carried to achieve exactly the same room temperature;
  * water too mild -> valves saturate at 100 % and the rooms never arrive,
    with nothing to signal that anything is wrong.

Both look like "working" if nobody measures the difference.

So the signal is BOTH halves: how far off target the house is, and how hard
the valves are having to work to get there. Valve saturation is what
distinguishes "not enough capacity" from "fine". And the idle branch - backing
off when the valves are barely open - is the efficiency half, and the half a
naive implementation leaves out.

Two properties that are not negotiable:

**Slow, integer, hysteretic.** 1 K every 30 min (owner, 2026-07-27). Every
write to the heat pump wears its flash (docs/HEATPUMP.md), and the slab has
hours of thermal mass, so a continuous controller here would be both damaging
and pointless. Roughly 4-10 writes a day.

**The condensation reaction bypasses the cadence.** A measured breach is a
safety event, not a trim, so it jumps immediately and ignores the interval.
Note P04 targets RETURN water while condensation is about the water reaching
the slab, so no clamp on the setpoint can guarantee anything - feedback on the
MEASURED leaving water is the actual mechanism, and the floor below is a
heuristic backstop.

Honest limitation while only two circuits are actuated: the other eight are
open pipe and cannot throttle, so `max_open` barely reflects load and this
loop effectively runs on house deviation alone. It gets much better when the
remaining actuators are fitted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("heatctl.setpoint")

HOLD, TRIM, BREACH = "hold", "trim", "breach"


@dataclass
class SetpointDecision:
    target: float | None      # None = leave the setpoint alone
    reason: str
    kind: str = HOLD


class SetpointController:
    def __init__(self, cfg: dict):
        s = dict(cfg["control"].get("water_setpoint") or {})
        self.enabled = bool(s.get("enabled", False))
        self.interval_s = float(s.get("interval_s", 1800.0))   # 30 min
        self.step_c = float(s.get("step_c", 1.0))
        # How open the valves must be before "not enough capacity" is the
        # right diagnosis rather than "the rooms are simply satisfied".
        self.saturated_pct = float(s.get("saturated_pct", 85.0))
        self.idle_pct = float(s.get("idle_pct", 30.0))
        self.deviation_band_c = float(s.get("deviation_band_c", 0.3))

        # Register limits are 7-30 (P04) and 15-50 (P05); these are the
        # narrower operating bounds we choose to run inside.
        self.cooling_min_c = float(s.get("cooling_min_c", 14.0))
        self.cooling_max_c = float(s.get("cooling_max_c", 25.0))
        self.heating_min_c = float(s.get("heating_min_c", 20.0))
        self.heating_max_c = float(s.get("heating_max_c", 40.0))

        # Heuristic floor on the cooling setpoint, relative to dew point, and
        # the jump target on an actual measured breach. Both inherited from
        # the HA supervisory loop this replaces.
        self.dew_floor_offset_c = float(s.get("dew_floor_offset_c", 4.0))
        self.breach_jump_c = float(s.get("breach_jump_c", 6.0))

        self._last_change = 0.0

    def step(self, mode: str, deviation: float | None, max_open: float | None,
             current: float | None, dew_point: float | None,
             leaving_water: float | None, supply_limit: float | None,
             now: float) -> SetpointDecision:
        if not self.enabled or mode not in ("heating", "cooling"):
            return SetpointDecision(None, "disabled")
        if current is None:
            return SetpointDecision(None, "setpoint unknown")

        # --- safety first, and it ignores the cadence ---
        if (mode == "cooling" and leaving_water is not None
                and supply_limit is not None and leaving_water < supply_limit
                and dew_point is not None):
            target = self._clamp(mode, dew_point + self.breach_jump_c, dew_point)
            if target > current:
                self._last_change = now
                return SetpointDecision(
                    target,
                    f"leaving water {leaving_water:.1f} below limit "
                    f"{supply_limit:.1f} - jumping",
                    BREACH)

        if now - self._last_change < self.interval_s:
            return SetpointDecision(None, "within interval")
        if deviation is None:
            return SetpointDecision(None, "no room data")

        # `deviation` is signed house demand: + = too cold, - = too warm.
        # Translate to "does the house want more from this mode".
        wants_more = deviation > self.deviation_band_c if mode == "heating" \
            else deviation < -self.deviation_band_c
        satisfied = abs(deviation) <= self.deviation_band_c or not wants_more
        saturated = max_open is not None and max_open >= self.saturated_pct
        idle = max_open is not None and max_open <= self.idle_pct

        if wants_more and saturated:
            # More aggressive water: hotter in heating, colder in cooling.
            delta = self.step_c if mode == "heating" else -self.step_c
            why = (f"house {deviation:+.2f} K and valves at {max_open:.0f}% - "
                   "not enough capacity")
        elif satisfied and idle:
            # Back off. This is the efficiency half.
            delta = -self.step_c if mode == "heating" else self.step_c
            why = (f"house {deviation:+.2f} K and valves at {max_open:.0f}% - "
                   "water is more aggressive than needed")
        else:
            return SetpointDecision(None, f"house {deviation:+.2f} K, valves "
                                          f"{max_open if max_open is None else round(max_open)}%")

        target = self._clamp(mode, current + delta, dew_point)
        if target == current:
            return SetpointDecision(None, f"{why} (already at the limit)")
        self._last_change = now
        return SetpointDecision(target, why, TRIM)

    def _clamp(self, mode: str, value: float, dew_point: float | None) -> float:
        if mode == "cooling":
            lo, hi = self.cooling_min_c, self.cooling_max_c
            if dew_point is not None:
                # Heuristic only - P04 targets RETURN water, so this cannot
                # guarantee the water reaching the slab is safe. The measured
                # -leaving-water branch above is the real mechanism.
                lo = max(lo, dew_point + self.dew_floor_offset_c)
        else:
            lo, hi = self.heating_min_c, self.heating_max_c
        return round(max(lo, min(hi, value)))
