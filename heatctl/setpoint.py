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
import math
from dataclasses import dataclass

log = logging.getLogger("heatctl.setpoint")

HOLD, TRIM, BREACH, BLOCKED = "hold", "trim", "breach", "blocked"


@dataclass
class SetpointDecision:
    target: float | None      # None = leave the setpoint alone
    reason: str
    kind: str = HOLD

    @property
    def demand_unmet(self) -> bool:
        """The house wants more and the plant cannot legally give it.

        Distinct from merely holding: this says the constraint is binding and
        the shortfall will not resolve itself, which is the condition worth
        alarming on rather than the oscillation that used to hide it.
        """
        return self.kind == BLOCKED


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

        # None, not 0.0. With 0.0 the first cycle after EVERY restart sees
        # `now - 0 >= interval` and trims immediately, so the 30 min cadence
        # is silently not honoured across restarts - and a restart loop would
        # hammer the pump's flash, which is exactly what the cadence exists to
        # prevent. Observed 2026-07-27: P04 moved on a deploy, correctly in
        # direction but at the wrong time. Seeded on first use instead, so the
        # first trim waits a full interval after start-up.
        self._last_change: float | None = None

        # --- constraint memory (2026-07-29) ---
        # How far the supply limit must FALL before a setpoint the condensation
        # guard has already rejected is worth attempting again. See
        # `_blocked_setpoint` below for why this exists at all.
        self.retry_margin_c = float(s.get("constraint_retry_margin_c", 0.5))
        # The most aggressive cooling setpoint known to breach, and the supply
        # limit that was in force when we learned it. Lower setpoints are
        # strictly harder, so a single pair covers every setpoint below it.
        self._blocked_setpoint: float | None = None
        self._blocked_limit: float | None = None

    def _remember_breach(self, setpoint: float, limit: float) -> None:
        """Record that `setpoint` breached while the limit was `limit`.

        Keeps the LEAST aggressive failure. If 19 degC breaches, 18 certainly
        would too, so remembering 19 blocks both; remembering 18 instead would
        leave 19 to be rediscovered the hard way.
        """
        if self._blocked_setpoint is None or setpoint > self._blocked_setpoint:
            self._blocked_setpoint = setpoint
            self._blocked_limit = limit

    def _is_known_infeasible(self, target: float,
                             limit: float | None) -> bool:
        """Would this cooling setpoint just re-run a failure we already had?

        THE FIX FOR THE 2026-07-29 LIMIT CYCLE. That day the trim stepped the
        setpoint down, the condensation guard shoved it back up six minutes
        later, and thirty minutes after that the rate limiter expired and it
        attempted the identical step again - fourteen times, while the house
        drifted from 0.32 K to 1.25 K off target. The trim was integrating
        against a saturated actuator and forgetting the saturation between
        attempts.

        The insight is that a setpoint rejected at a given supply limit is
        infeasible FOR THAT LIMIT, so a clock cannot make it succeed. Only the
        constraint moving can. Retry is therefore gated on the limit falling by
        `retry_margin_c`, not on time passing.

        Fails toward TRYING when the limit is unknown: the measured-breach
        branch is the real protection, so an extra attempt costs one wasted
        step, while wrongly blocking would strand the plant at a setpoint it
        could have improved on.
        """
        if self._blocked_setpoint is None or limit is None:
            return False
        if self._blocked_limit is not None \
                and limit <= self._blocked_limit - self.retry_margin_c:
            # The constraint genuinely relaxed - forget and let it try again.
            self._blocked_setpoint = None
            self._blocked_limit = None
            return False
        return target <= self._blocked_setpoint

    def _forget_constraint(self) -> None:
        self._blocked_setpoint = None
        self._blocked_limit = None

    def step(self, mode: str, deviation: float | None, max_open: float | None,
             current: float | None, dew_point: float | None,
             leaving_water: float | None, supply_limit: float | None,
             now: float) -> SetpointDecision:
        if not self.enabled or mode not in ("heating", "cooling"):
            return SetpointDecision(None, "disabled")
        if current is None:
            return SetpointDecision(None, "setpoint unknown")

        # Leaving cooling invalidates everything the memory knows: it is all
        # about the condensation limit, which does not apply in heating.
        if mode != "cooling":
            self._forget_constraint()

        # --- safety first, and it ignores the cadence ---
        if (mode == "cooling" and leaving_water is not None
                and supply_limit is not None and leaving_water < supply_limit
                and dew_point is not None):
            # Record BEFORE deciding whether to jump. The breach is real
            # information about this setpoint whether or not the jump is
            # actionable, and dropping it when `target <= current` would leave
            # the trim to rediscover the same failure later.
            self._remember_breach(current, supply_limit)
            target = self._clamp(mode, dew_point + self.breach_jump_c, dew_point)
            if target > current:
                self._last_change = now
                return SetpointDecision(
                    target,
                    f"leaving water {leaving_water:.1f} below limit "
                    f"{supply_limit:.1f} - jumping",
                    BREACH)

        if self._last_change is None:
            self._last_change = now
            return SetpointDecision(None, "settling after start-up")
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

        wants_capacity = False
        if wants_more and saturated:
            # More aggressive water: hotter in heating, colder in cooling.
            wants_capacity = True
            delta = self.step_c if mode == "heating" else -self.step_c
            why = (f"house {deviation:+.2f} K and valves at {max_open:.0f}% - "
                   "not enough capacity")
            if mode == "cooling":
                proposed = self._clamp(mode, current + delta, dew_point)
                if self._is_known_infeasible(proposed, supply_limit):
                    # Do not burn a 30-minute cycle re-proving this. Report it
                    # instead: the house wants more, the plant cannot legally
                    # supply it, and that is an alarm rather than a wait.
                    return SetpointDecision(
                        None,
                        f"{why}, but {proposed:.0f} degC breached at limit "
                        f"{self._blocked_limit:.1f} and the limit is now "
                        f"{supply_limit:.1f} - condensation-limited",
                        BLOCKED)
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
            # Reached from the capacity branch this is NOT a quiet hold: the
            # house wants more and the plant cannot legally supply it, which is
            # the same demand-unmet condition the constraint memory reports.
            # Which mechanism stopped us - the dew-point floor here, or the
            # remembered breach above - is an implementation detail; the
            # operator-visible fact is identical, so it must alarm identically.
            return SetpointDecision(None, f"{why} (already at the limit)",
                                    BLOCKED if wants_capacity else HOLD)
        self._last_change = now
        return SetpointDecision(target, why, TRIM)

    def _clamp(self, mode: str, value: float, dew_point: float | None) -> float:
        if mode == "cooling":
            lo, hi = self.cooling_min_c, self.cooling_max_c
            if dew_point is not None:
                # Heuristic only - P04 targets RETURN water, so this cannot
                # guarantee the water reaching the slab is safe. The measured
                # -leaving-water branch above is the real mechanism.
                #
                # COARSE BACKSTOP ONLY. Do not tighten this into a real
                # condensation guard by deriving it from the setpoint-to-supply
                # gap: that gap is the leaving/return spread, which is DYNAMIC
                # in flow, load and modulation, so no constant can represent
                # it. See config.yaml for the withdrawn attempt and why its
                # evidence was selection-biased.
                lo = max(lo, dew_point + self.dew_floor_offset_c)
        else:
            lo, hi = self.heating_min_c, self.heating_max_c
        # Round the VALUE, but round the BOUNDS outward. A lower bound that
        # rounds DOWN is not a lower bound: `round(max(18.2, ...))` returns 18
        # and hands back up to 0.5 K of the margin the bound exists to hold.
        # Small here, because this floor is only a coarse backstop - but it is
        # wrong regardless of how much it happens to matter today.
        lo_i, hi_i = math.ceil(lo), math.floor(hi)
        if lo_i > hi_i:
            # Dew point demands a setpoint above our chosen operating band. In
            # cooling, warmer is the safe direction, so the safety floor wins
            # over the efficiency preference - deliberately, not accidentally.
            return float(lo_i)
        return float(max(lo_i, min(hi_i, round(value))))
