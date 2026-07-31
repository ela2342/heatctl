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
        elif satisfied and idle:
            # Back off. This is the efficiency half.
            delta = -self.step_c if mode == "heating" else self.step_c
            why = (f"house {deviation:+.2f} K and valves at {max_open:.0f}% - "
                   "water is more aggressive than needed")
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

    def _clamp(self, mode: str, value: float, dew_point: float | None,
               supply_limit: float | None = None,
               running_ceiling: float | None = None) -> float:
        if mode == "cooling":
            lo, hi = self.cooling_min_c, self.cooling_max_c
            # DYNAMIC FLOOR, and the honest one. The setpoint targets RETURN
            # water while condensation is about the water reaching the slab, so
            # the floor has to be the condensation limit PLUS however far below
            # the setpoint the leaving water actually lands - which is the
            # machine's measured delta-T, not a constant.
            #
            # `supply_limit` is already dew point + margin, so this reads
            # directly as "high enough that leaving water lands at or above the
            # limit". Measured 2026-07-29 the spread moved from 5.8 K to 2.0 K
            # within an hour on two register writes; no fixed offset can track
            # that, which is why the earlier attempt to tune one was withdrawn.
            # NO CONDENSATION FLOOR. Removed 2026-07-31 with WP-S change C.
            #
            # It used to be `supply_limit + measured spread`, and it was
            # CIRCULAR: spread is a consequence of the control action, so a
            # brief 73 Hz excursion latched a 3.2 K spread into the estimate,
            # raised the floor to 19.7, forced the SETPOINT UP from 19 to 20,
            # and the machine then throttled itself to its 35 Hz minimum. The
            # controller sabotaged itself through its own success, and making
            # the capacity loop more aggressive made it worse.
            #
            # Condensation is now served entirely inside the capacity loop,
            # whose actuator runs continuously from full frequency down to OFF
            # (capacity.py, STOP/RESUME). P04 carries no part of the constraint.
            #
            # What protects the slab if the capacity loop is wrong: it acts on
            # MEASURED supply every cycle, it lowers without a rate limit, and
            # below `min_hz` it stops the compressor outright while the pump
            # keeps circulating. The valve guard remains behind that.
            #
            # There is deliberately NO static backstop beside it. `dew_floor_
            # offset_c: 4.0` used to sit here behind a max() and won whenever
            # the measured spread was under 3 K - which is the regime silent
            # mode and the frequency ceiling exist to produce, so the measured
            # mechanism was dead exactly when it had something to say. It was
            # then briefly kept as a "start-up fallback", which was a softened
            # version of an instruction to remove it. The owner asked three
            # times. It is gone (D-030, 2026-07-31).
            #
            # Before any spread has been measured the cooling floor is just
            # `cooling_min_c`. That is acceptable and not an oversight: the trim
            # moves 1 K per 30 min so the setpoint cannot travel far, the spread
            # estimate populates within seconds of the compressor running, and
            # the capacity controller and the valve guard both act on MEASURED
            # supply regardless of what the setpoint asked for.
            # NO CAP HERE. A cap at `return water - restart differential` was
            # tried on 2026-07-30 and REVERTED the same hour: it let the setpoint
            # sit low enough that supply fell to 15.3 against a 16.0 limit, and
            # the hard guard then closed the valves - but only `hk01` and `hk02`
            # have actuators. The other eight circuits are open pipe and cannot
            # close, so cold water below the dew point kept flowing into the slab
            # through them, condensing inside it invisibly. That is exactly the
            # failure this whole guard exists to prevent.
            #
            # The lesson is not about the cap. It is that **the valve guard is
            # not effective protection while eight of ten circuits cannot be
            # closed**, so the SETPOINT is the only real control over what
            # reaches the slab, and it must stay above limit + spread even when
            # that means the compressor will not run.
            #
            # The resulting corner is genuine: at a 15.0 dew point and a
            # measured 4.5 K spread the minimum safe setpoint is 20.5 while the
            # maximum runnable one is 19.6. No setpoint satisfies both. Reducing
            # the SPREAD is the only exit; see BACKLOG.
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
