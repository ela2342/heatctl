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

**Computed, not walked** (D-051, 2026-09-28). The setpoint is WHERE THE
RETURN WATER SHOULD BE, computed from the house slab target, and written in one
step:

    P0x = T_target - (ua_sa / m_dot_c) / 2 * (T_target - T_set)

P04/P05 target the heat pump's RETURN water. In the lumped model the slab
target already is the water mean temperature that holds the rooms at setpoint
(`Q = ua_sa * (T_target - T_set)`, the balance checked to 1 % against the
plant on 2026-07-31), and return sits half a spread from the mean on the side
the water gives heat away: `s = Q / m_dot_c`. `ua_sa / m_dot_c` is derived from
its measurement, `dT / (T_air - T_water)`, and is invariant to the flow, the
worst-known number in the model.

No integrator anywhere: the only feedback is the room-air recovery term inside
the slab target, which is proportional. The 1 K / 30 min walk it replaces was
an integrator on the sign of a few conditions, and an integrator on a plant
that answers in hours overshoots by construction - 2026-09-25 and 09-28.

Flash is still honoured, as a RATE limit rather than a step size: a move needs
the target 0.5 + `hysteresis_c` away, sustained for `confirm_s`, and at least
`min_write_interval_s` since the last write. One write where the walk took five.

**The walk remains as the FALLBACK**, with the charging gate, for when no fresh
house target exists (no outdoor temperature, energy model not yet run).

**The condensation reaction bypasses the cadence.** A measured breach is a
safety event, not a trim, so it jumps immediately and ignores the interval.
Note P04 targets RETURN water while condensation is about the water reaching
the slab, so no clamp on the setpoint can guarantee anything - feedback on the
MEASURED supply is the actual mechanism, and the floor below is a heuristic
backstop.

**It reads the same sensor the safety guard does** (`vl_total`, the manifold
PT1000 at 0.1 K) rather than the heat pump's leaving-water register (scaled
0.5, so quantised to 0.5 K). Two controllers answering the same physical
question - "is the water reaching the slab dangerous" - from two different
sensors at two different resolutions is a defect in itself, quite apart from
the precision: it means the soft loop and the hard guard can disagree about
whether a breach is happening. The heat pump register remains as a FALLBACK
for when the manifold sensor is faulted, because some reading beats none.

**Stored energy bounds the charge** (D-048). Valve idleness alone cannot
trigger the back-off, because one warm room holds the peak open: the trim also
backs off while the smoothed slab is over-charged for this mode, or the air
over-shoots, and the air is not asking for more. It never switches the mode.

**`max_open` under-reports load**, so in practice this loop runs mostly on
house deviation. Why, and how far, is measured in
`docs/FLOW_CHARACTERISATION.md` - do not restate the numbers here, they have
already gone stale once.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

log = logging.getLogger("heatctl.setpoint")

HOLD, TRIM, BREACH, BLOCKED = "hold", "trim", "breach", "blocked"
DIRECT = "direct"


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
        self.interval_s = float(s.get("interval_s", 1800.0))
        # Cadence while the house is under-served - see the two-regime note in
        # step(). Matched to the plant's 1-3 min response, like the capacity
        # loop's settle times, rather than to the slab.
        self.saturated_interval_s = float(
            s.get("saturated_interval_s", 120.0))
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
        # CONSTRAINT MEMORY REMOVED 2026-07-31 with WP-S change C. It existed
        # to stop the trim re-proposing a setpoint the condensation guard had
        # already rejected (D-029). With the condensation floor and the breach
        # branch both gone from this file, nothing here can be rejected on
        # condensation grounds and its only writer was the breach branch - it
        # was dead code that still looked live.
        # The most aggressive cooling setpoint known to breach, and the supply
        # limit that was in force when we learned it. Lower setpoints are
        # strictly harder, so a single pair covers every setpoint below it.

        # --- measured leaving/return spread (2026-07-29) ---
        # The clamp below needs to know how far BELOW the setpoint the water
        # reaching the slab will land, and that distance is the machine's own
        # delta-T. It is a measured, dynamic quantity - never a constant.
        self.spread_decay = float(s.get("spread_decay", 0.995))
        self.spread_min_c = float(s.get("spread_min_c", 1.0))
        self.spread_max_c = float(s.get("spread_max_c", 8.0))
        self._spread_est: float | None = None

        # --- the charging gate (D-048, 2026-09-28) ---
        # Stored energy, as kelvin of whole slab, smoothed. See observe_excess.
        self.overcharge_slab_k = float(s.get("overcharge_slab_k", 1.0))
        self.gate_smoothing_s = float(s.get("gate_smoothing_s", 3600.0))
        self._excess_k: float | None = None
        self._excess_t: float | None = None

        # --- the direct law (D-051, 2026-09-28) ---
        # "direct" computes the setpoint from the house slab target; "trim" is
        # the old walk, kept as the fallback either way.
        self.law = str(s.get("law", "direct"))
        # ua_sa / m_dot_c, dimensionless, DERIVED from its measurement (D-031,
        # D-032): the manifold spread over the air-to-water difference that
        # produced it, 2026-07-31. The flow cancels (490/1438 = 568/1670), which
        # is why neither factor appears. Defaults mirror params.yaml.
        ident = dict(s.get("spread_identification") or {})
        dt = float(ident.get("manifold_dt_k", 2.10))
        drive = (float(ident.get("room_mean_c", 25.37))
                 - float(ident.get("water_mean_c", 19.20)))
        if dt <= 0.0 or drive <= 0.0:
            raise ValueError(
                f"spread_identification must be positive: dT {dt}, "
                f"air - water {drive}")
        self.spread_ratio = dt / drive
        self.hysteresis_c = float(s.get("hysteresis_c", 0.25))
        self.confirm_s = float(s.get("confirm_s", 600.0))
        self.min_write_interval_s = float(s.get("min_write_interval_s", 900.0))
        self.target_max_age_s = float(s.get("target_max_age_s", 300.0))
        self._house: tuple[float, float] | None = None
        self._house_t: float | None = None
        self._pending: tuple[float, float] | None = None   # (value, since)

    def observe_spread(self, spread: float | None) -> None:
        """Feed the measured leaving/return delta-T. None means "not running".

        Deliberately a DECAYING MAXIMUM rather than an average: this feeds a
        safety floor, so it must rise immediately when the machine starts
        producing a wide spread and relax only slowly afterwards. An average
        would sit in the middle of the distribution and let half of all
        excursions through.

        Only sample while the compressor runs - the spread is meaningless when
        it is off, and feeding those zeros in would collapse the estimate and
        quietly remove the floor.
        """
        if spread is None:
            return
        spread = min(self.spread_max_c, max(self.spread_min_c, abs(spread)))
        if self._spread_est is None:
            self._spread_est = spread
        else:
            self._spread_est = max(spread, self._spread_est * self.spread_decay)

    @property
    def spread_estimate(self) -> float | None:
        return self._spread_est

    def observe_excess(self, excess_wh: float | None,
                       capacity_wh_per_k: float | None, now: float) -> None:
        """Feed the house slab excess (`energy.house_excess_wh`). None = blind.

        Held as KELVIN OF WHOLE SLAB so the band survives a change of floor
        area, the same unit D-046 chose for the mode deadband.

        SMOOTHED, first order, `gate_smoothing_s`. The slab estimate falls back
        to the raw return temperature, and a flowing return moves with the
        water within minutes - so unsmoothed, this gate would react to its own
        actuator. That is the mechanism of the 78-minute `auto_mode`
        oscillation of 2026-08-19. One hour is 20x the water loop's 1-3 min
        settling and ~6x below the fast mode, so it rejects the actuator's echo
        and keeps real slab motion.

        A blind model leaves the last value in place for one smoothing
        constant and then forgets it: stale energy is not evidence.
        """
        if excess_wh is None or not capacity_wh_per_k:
            if (self._excess_t is not None
                    and now - self._excess_t > self.gate_smoothing_s):
                self._excess_k = None
            return
        k = excess_wh / capacity_wh_per_k
        if self._excess_k is None or self._excess_t is None:
            self._excess_k = k
        else:
            dt = max(0.0, now - self._excess_t)
            a = 1.0 - math.exp(-dt / self.gate_smoothing_s)
            self._excess_k += a * (k - self._excess_k)
        self._excess_t = now

    @property
    def slab_excess_k(self) -> float | None:
        return self._excess_k

    def observe_house_target(self, target: tuple[float, float] | None,
                             now: float) -> None:
        """Feed `(slab target, setpoint)` for the house, capacity-weighted.

        None means the energy model could not form one; the last value then
        ages out after `target_max_age_s` and the trim takes over.
        """
        if target is None:
            return
        self._house = target
        self._house_t = now

    def direct_value(self, now: float) -> float | None:
        """The continuous return-water setpoint the law asks for, or None.

        Mode-independent on purpose, like `slab_target_c`: a house that needs
        heat has T_target above T_set and the return lands below the target,
        one that needs cooling the mirror image. Nothing here knows the season.
        """
        if (self._house is None or self._house_t is None
                or now - self._house_t > self.target_max_age_s):
            return None
        t, sp = self._house
        return t - self.spread_ratio / 2.0 * (t - sp)

    def overcharged(self, mode: str) -> bool:
        """Is the slab past target in the direction this mode charges it?

        Heating charges heat, so a SURPLUS is over-charged; cooling charges
        coolth, so a DEFICIT is. Unknown is not over-charged - the gate then
        falls back to the air over-shoot, see step().
        """
        e = self._excess_k
        if e is None:
            return False
        if mode == "heating":
            return e > self.overcharge_slab_k
        if mode == "cooling":
            return e < -self.overcharge_slab_k
        return False

    def step(self, mode: str, deviation: float | None, max_open: float | None,
             current: float | None, dew_point: float | None,
             supply_temp: float | None, supply_limit: float | None,
             now: float,
             running_ceiling: float | None = None) -> SetpointDecision:
        if not self.enabled or mode not in ("heating", "cooling"):
            return SetpointDecision(None, "disabled")
        if current is None:
            return SetpointDecision(None, "setpoint unknown")

        # --- safety first, and it ignores the cadence ---
        # NO BREACH BRANCH. Removed 2026-07-31 with WP-S change C.
        #
        # It jumped the SETPOINT upward on a measured breach - condensation
        # logic living on P04, and the direct cause of the 2026-07-30 09:14
        # incident where a 0.1 K breach jumped the setpoint 18 -> 21, parked
        # return water inside the unit's restart dead zone, stopped the
        # compressor entirely and let the house climb 3 K on a 38 degC day.
        #
        # A breach is now answered where it happens: the capacity loop cuts
        # frequency immediately (its first lowering move is never delayed) and
        # stops the compressor at the frequency floor, and the valve guard trips
        # behind that. The setpoint is not part of it.

        if self._last_change is None:
            self._last_change = now
            return SetpointDecision(None, "settling after start-up")

        x = self.direct_value(now) if self.law == "direct" else None
        if x is not None:
            return self._direct(mode, x, deviation, current, supply_limit, now)
        self._pending = None
        if deviation is None:
            return SetpointDecision(None, "no room data")

        # TWO REGIMES, TWO CADENCES (2026-07-31).
        #
        # The 30-minute interval was justified by flash wear and the slab's
        # thermal mass. Neither holds while the house is under-served:
        #   - one write per 30 min against a 30/hour budget is not binding;
        #   - the slab is the setpoint's PURPOSE, not its EFFECT. Changing P04
        #     changes what the compressor modulates toward, and the water loop
        #     settles in 1-3 min - the same process the capacity loop waits on.
        #     The hours-long constant belongs to the house.
        #
        # So: move at the PLANT's speed when the house wants everything it can
        # get, and at the HOUSE's speed when trimming for comfort and COP.
        #
        # Measured the evening this landed: with the condensation floor gone,
        # P04 became the binding constraint (compressor easing off at 49 Hz
        # against a 73 Hz ceiling because return was 0.5 K from setpoint) and
        # the walk from 19 to 16 would have taken 90 minutes purely on cadence.
        #
        # INTERIM. The owner's preference is a PI here, as in capacity.py -
        # this fixed step at two speeds is a coarse stand-in for proportional
        # action. See BACKLOG.
        #
        # `deviation` is signed house demand: + = too cold, - = too warm.
        # Translate to "does the house want more from this mode".
        wants_more = deviation > self.deviation_band_c if mode == "heating" \
            else deviation < -self.deviation_band_c
        satisfied = abs(deviation) <= self.deviation_band_c or not wants_more
        saturated = max_open is not None and max_open >= self.saturated_pct
        idle = max_open is not None and max_open <= self.idle_pct
        # THE CHARGING GATE (D-048). The back-off used to need `idle` - the
        # MOST demanding valve nearly shut - and one warm room defeats that.
        # 2026-09-25: P05 held at 25 with the house at 27 degC and 66.7 kWh
        # banked. 2026-09-28: P04 held at 15 for three days while Arbeitszimmer
        # kept peak demand at 100 and the slab went 85.9 kWh short.
        #
        # So the air over-shooting its band, or the slab being over-charged
        # for this mode, is also reason to back off. Only ever toward neutral
        # and only on the comfort cadence, and only when the air is not asking
        # for more (`satisfied`): a cold slab under a warm house on an August
        # night keeps cooling. The charging branch is untouched; it already
        # requires the air to want more.
        overshoot = (deviation < -self.deviation_band_c if mode == "heating"
                     else deviation > self.deviation_band_c)
        overcharged = self.overcharged(mode)

        # The cadence gate, now that the regime is known.
        interval = (self.saturated_interval_s if (wants_more and saturated)
                    else self.interval_s)
        if now - self._last_change < interval:
            return SetpointDecision(
                None, f"within interval ({interval:.0f} s)")

        wants_capacity = False
        if wants_more and saturated:
            # More aggressive water: hotter in heating, colder in cooling.
            wants_capacity = True
            delta = self.step_c if mode == "heating" else -self.step_c
            why = (f"house {deviation:+.2f} K and valves at {max_open:.0f}% - "
                   "not enough capacity")
        elif satisfied and (idle or overshoot or overcharged):
            # Back off. This is the efficiency half, and the charging gate.
            delta = -self.step_c if mode == "heating" else self.step_c
            if idle:
                why = (f"house {deviation:+.2f} K and valves at "
                       f"{max_open:.0f}% - water is more aggressive than needed")
            elif overcharged:
                why = (f"house {deviation:+.2f} K and slab "
                       f"{self._excess_k:+.2f} K past target - over-charged")
            else:
                why = (f"house {deviation:+.2f} K past its band - "
                       "over-shooting")
        else:
            return SetpointDecision(None, f"house {deviation:+.2f} K, valves "
                                          f"{max_open if max_open is None else round(max_open)}%")

        target = self._clamp(mode, current + delta, dew_point, supply_limit,
                             running_ceiling)
        # A BRANCH MUST NEVER MOVE THE SETPOINT AGAINST ITS OWN INTENT.
        #
        # Measured 2026-07-30 08:20: the capacity branch asked for 19 (colder),
        # the dynamic floor - inflated to 6.7 K by a transient spread spike -
        # returned 21, and the code accepted it and logged "not enough
        # capacity" while making the water WARMER on the morning of a 38 degC
        # day. Before the floor was dynamic `lo` was static and almost never
        # above `current`, so this path was unreachable and the `target ==
        # current` test below was sufficient. It is not any more.
        #
        # Reversal means the constraint is binding harder than one step, which
        # is exactly the blocked condition - not a trim in the other direction.
        if (delta < 0 and target > current) or (delta > 0 and target < current):
            return SetpointDecision(
                None,
                f"{why} (clamped to {target:.0f} - constraint binds harder "
                f"than one step)",
                BLOCKED if wants_capacity else HOLD)
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

    def _direct(self, mode: str, x: float, deviation: float | None,
                current: float, supply_limit: float | None,
                now: float) -> SetpointDecision:
        """Write the computed setpoint, rate-limited. See the module docstring."""
        lo, hi = self._bounds(mode, supply_limit)
        want = float(max(lo, min(hi, round(x))))
        head = f"direct: {x:.1f}"
        # DEMAND UNMET: the law asks past the aggressive bound and the air
        # agrees it wants more. Same alarm the walk raised from its capacity
        # branch; which mechanism found it is not the operator's concern.
        aggressive_cut = x > hi + 0.5 if mode == "heating" else x < lo - 0.5
        wants_more = deviation is not None and (
            deviation > self.deviation_band_c if mode == "heating"
            else deviation < -self.deviation_band_c)
        kind = BLOCKED if (aggressive_cut and wants_more) else HOLD
        if kind == BLOCKED:
            head += f" (limit {want:.0f}, house {deviation:+.2f} K)"

        # HYSTERESIS on the continuous value, so a target sitting on x.5 cannot
        # toggle the register. Skipped when `current` is outside the legal
        # band: then the move is a correction, not a preference.
        inside = lo <= current <= hi
        if want == current or (inside and
                               abs(x - current) < 0.5 + self.hysteresis_c):
            self._pending = None
            return SetpointDecision(None, f"{head}, holding {current:.0f}", kind)

        # PERSISTENCE: the wish must hold its direction for `confirm_s`. The
        # room air arrives in 0.5 K steps, event-triggered, and a single step
        # moves the house target by a fraction of that - but a fraction of a
        # kelvin is exactly what sits on a rounding edge.
        up = want > current
        if self._pending is None or (self._pending[0] > current) != up:
            self._pending = (want, now)
        else:
            self._pending = (want, self._pending[1])
        waited = now - self._pending[1]
        if waited < self.confirm_s:
            return SetpointDecision(
                None, f"{head} -> {want:.0f}, confirming "
                      f"({waited:.0f}/{self.confirm_s:.0f} s)", kind)
        since = now - self._last_change
        if since < self.min_write_interval_s:
            return SetpointDecision(
                None, f"{head} -> {want:.0f}, rate limit "
                      f"({since:.0f}/{self.min_write_interval_s:.0f} s)", kind)
        self._pending = None
        self._last_change = now
        return SetpointDecision(want, f"{head} -> {want:.0f}",
                                BLOCKED if kind == BLOCKED else DIRECT)

    def _bounds(self, mode: str,
                supply_limit: float | None = None) -> tuple[int, int]:
        """Integer operating band for this mode, bounds rounded OUTWARD."""
        if mode == "cooling":
            lo, hi = self.cooling_min_c, self.cooling_max_c
            # CONDENSATION FLOOR - see _clamp; D-036 carries the argument.
            if supply_limit is not None:
                lo = max(lo, supply_limit)
        else:
            lo, hi = self.heating_min_c, self.heating_max_c
        lo_i, hi_i = math.ceil(lo), math.floor(hi)
        if lo_i > hi_i:
            # In cooling warmer is the safe direction: the floor wins.
            hi_i = lo_i
        return lo_i, hi_i

    def _clamp(self, mode: str, value: float, dew_point: float | None,
               supply_limit: float | None = None,
               running_ceiling: float | None = None) -> float:
        if mode == "cooling":
            lo, hi = self.cooling_min_c, self.cooling_max_c
            # CONDENSATION FLOOR: the setpoint may not ask for water colder
            # than the limit it is supposed to respect. NOT capped at what the
            # unit will start at - if the only runnable setpoint condenses,
            # the answer is not to run (D-039).
            #
            # D-036 carries the argument, including why the floor is
            # `supply_limit` and never `supply_limit + spread`, and what
            # happened the three previous times this was changed (D-030,
            # D-035, D-039). Do not re-derive it here.
            if supply_limit is not None:
                lo = max(lo, supply_limit)
        else:
            lo, hi = self.heating_min_c, self.heating_max_c
        # Round the VALUE, but round the BOUNDS outward. A lower bound that
        # rounds DOWN is not a lower bound: `round(max(18.2, ...))` returns 18
        # and hands back up to 0.5 K of the margin the bound exists to hold.
        # Small in effect, but wrong regardless of how much it happens to
        # matter on any given day.
        lo_i, hi_i = math.ceil(lo), math.floor(hi)
        if lo_i > hi_i:
            # Dew point demands a setpoint above our chosen operating band. In
            # cooling, warmer is the safe direction, so the safety floor wins
            # over the efficiency preference - deliberately, not accidentally.
            return float(lo_i)
        return float(max(lo_i, min(hi_i, round(value))))
