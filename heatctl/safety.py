"""Safety layer. Runs AFTER control and may override everything.

Principle: control proposes, safety decides. Every rule here must work
without MQTT command plane, without HA, without layer 2.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("heatctl.safety")


class Safety:
    def __init__(self, cfg: dict):
        s = cfg["safety"]
        self.setpoint_min = s["setpoint_min_c"]
        self.setpoint_max = s["setpoint_max_c"]
        self.vl_max_heating = s["vl_max_heating_c"]
        self.vl_min_cooling = s["vl_min_cooling_c"]
        self.frost_c = s["frost_protect_c"]
        self.stale_timeout = s["stale_data_timeout_s"]
        self.failsafe_pct = s["failsafe_valve_pct"]

        # Dew-point supervision. `vl_min_cooling_c` alone is a fixed guess at
        # a limit that is physically not fixed at all - it depends on indoor
        # humidity. Measured 2026-07-27: a 12.7 degC dew point against a 16.0
        # degC static limit shut circuits that were in no danger whatever.
        self.dew_margin = s.get("dew_point_margin_c", 2.0)
        self.dew_max_age = s.get("dew_point_max_age_s", 900)
        # Hard floor on what a dew-point reading may authorise, bounding the
        # damage from a stuck-low humidity sensor. Live data may relax the
        # static limit, but only this far.
        self.vl_min_cooling_floor = s.get("vl_min_cooling_floor_c", 12.0)
        self.cooling_requires_dew_point = s.get("cooling_requires_dew_point",
                                                True)
        self._dew: float | None = None
        self._dew_ts = 0.0
        self._dew_logged: float | None = None

    def clamp_setpoint(self, sp: float) -> float:
        return max(self.setpoint_min, min(self.setpoint_max, sp))

    def set_dew_point(self, dp: float | None, now: float | None = None) -> None:
        """Feed the latest measured dew point. None simply means no update."""
        if dp is None:
            return
        self._dew = dp
        self._dew_ts = time.monotonic() if now is None else now

    def dew_point_known(self, now: float | None = None) -> bool:
        """Is there a dew-point reading fresh enough to act on?"""
        now = time.monotonic() if now is None else now
        return self._dew is not None and now - self._dew_ts <= self.dew_max_age

    def cooling_supply_limit(self, now: float | None = None) -> float:
        """Lowest supply temperature cooling may run at, right now.

        With a fresh dew point this is `dew point + margin`, floored.

        The margin is EMPIRICAL: it matches the margin the existing HA
        supervisory loop has run at without condensation. It is a margin on
        the right quantity, though - the floor build-up is vapour-permeable,
        so condensation is not confined to the visible floor surface. Moist
        air reaches into the slab and condenses throughout it, including
        directly on the pipe wall, which sits essentially at water
        temperature. Supply temperature is therefore very nearly the surface
        that matters, with no hidden reserve behind a screed gradient. What
        the margin has to cover is measurement error and the spread of indoor
        dew point between rooms. Sizing it properly is a PLAN.md item.

        Worth knowing when tempted to relax any of this: condensation inside
        the slab is invisible. There is no wet patch to prompt anyone to
        intervene.

        Deviation from docs/DESIGN.md 3.5, which specifies
        `max(static, dew_point + margin)`: taking the max makes live data
        useless in the dry direction - it can only ever tighten the static
        guess, never relax it. Measured 2026-07-27: an 11.4 degC dew point
        would still have been clamped to 16.0, holding circuits shut with 4.6
        K of headroom to spare.

        Without a fresh reading this returns the static `vl_min_cooling_c`,
        but note that is only reached when `cooling_requires_dew_point` is
        off. That static value deserves suspicion: it arrived undocumented in
        the initial commit and it is NOT conservative - a 26 degC room at 60 %
        RH has a dew point of 17.6 degC, well above it. It looks like a safe
        floor and is not one, which is why the default is now to stop cooling
        rather than trust it.
        """
        now = time.monotonic() if now is None else now
        if not self.dew_point_known(now):
            if self._dew_logged is not None:
                log.warning("dew point stale or absent, falling back to the "
                            "static cooling supply limit %.1f degC",
                            self.vl_min_cooling)
                self._dew_logged = None
            return self.vl_min_cooling
        limit = max(self._dew + self.dew_margin, self.vl_min_cooling_floor)
        if self._dew_logged is None or abs(self._dew - self._dew_logged) >= 0.5:
            log.info("cooling supply limit %.1f degC (dew point %.1f + %.1f)",
                     limit, self._dew, self.dew_margin)
            self._dew_logged = self._dew
        return limit

    def apply(self, mode: str, state, circuit_sensor: str,
              proposed_pct: float) -> tuple[float, str | None]:
        """Returns (valve position, reason). reason != None => override active.

        Failure policy - two deliberately different directions:

        * FAIL OPEN when we have lost *knowledge* (sensor fault, stale data, a
          crashed controller). The heat pump's own controller holds a return
          water setpoint, so an open circuit with no supervision still gets
          water at a sane temperature. All that is lost is efficient
          distribution and per-room control - not safety. Driven by
          `safety.failsafe_valve_pct`.
        * FAIL CLOSED when the supply temperature is *known* to be dangerous:
          screed overtemp in heating, below-dew-point in cooling. Here opening
          is the actively harmful choice, and "the heat pump holds a setpoint"
          no longer applies because the measurement says it is not. These
          stay at 0 % on purpose - do not "make everything fail open".
        * FAIL CLOSED IN COOLING when the dew point is unknown, if
          `cooling_requires_dew_point`. Condensation is the one limit we
          cannot bound without a measurement, and the damage is wet floors
          rather than a warm screed the slab mass absorbs. See
          cooling_supply_limit() for why a static number is not a safe
          substitute.

        ORDER MATTERS, and not in the obvious way. The known-bad-supply rules
        are checked BEFORE the fail-open one, because they depend on the
        SUPPLY sensor and are independent of this circuit's return sensor.
        Checking fail-open first (as this did until 2026-07-27) meant a single
        faulted return sensor forced its circuit open even while the supply
        was measurably dangerous - condensation protection defeated by an
        unrelated sensor fault. Frost still outranks everything, because a
        burst pipe is unrecoverable and it needs a valid return reading.

        Note the hardware limit: per the legacy system's records the actuators
        are NC (normally closed), so a loss of signal or power closes them
        regardless of what we command. Fail-open therefore covers software and
        bridge failure (with the coupler's Modbus watchdog fallback set to full
        scale), not power loss. True fail-open would need NO actuators.
        """
        rl = state.temps.get(circuit_sensor)
        vl = state.temps.get("vl_total")
        rl_valid = circuit_sensor not in state.faults and rl is not None

        # Frost protection beats everything - needs a valid return reading.
        if rl_valid and rl < self.frost_c:
            return 100.0, "frost_protect"

        # Known-dangerous supply. Independent of this circuit's sensor, so
        # checked before the fail-open rule below - see the note above.
        if mode == "heating" and vl is not None and vl > self.vl_max_heating:
            return 0.0, "vl_overtemp"    # screed protection

        # Condensation guard. Deliberately NOT conditioned on the mode: what
        # condenses is decided by the water, not by the label we have put on
        # the plant. heatctl's mode and the heat pump's own mode are separate
        # things today - heatctl cannot even command the pump's mode yet (the
        # register bit is unknown; see PLAN.md WP-B) - so requiring them to
        # agree before protecting the slab would mean the guard switches off
        # in precisely the situation it exists for: heatctl believing it is
        # heating while chilled water is circulating.
        if self.dew_point_known() and vl is not None \
                and vl < self.cooling_supply_limit():
            return 0.0, "vl_undertemp"

        if mode == "cooling":
            # Whereas THIS one is mode-specific on purpose: heating needs no
            # dew point, so a missing reading must not stop it.
            if self.cooling_requires_dew_point and not self.dew_point_known():
                return 0.0, "dew_point_unknown"
            if vl is not None and vl < self.cooling_supply_limit():
                return 0.0, "vl_undertemp"   # static-fallback path

        # Lost knowledge of this circuit -> fail open (see policy above).
        if not rl_valid:
            return self.failsafe_pct, f"sensor_fault:{circuit_sensor}"

        return proposed_pct, None
