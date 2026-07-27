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

    def cooling_supply_limit(self, now: float | None = None) -> float:
        """Lowest supply temperature cooling may run at, right now.

        With a fresh dew point this is `dew point + margin`, floored; without
        one it is the static `vl_min_cooling_c`. Note the fallback is
        deliberately NOT the maximum of the two: the whole point is accuracy
        in both directions - permitting colder water when the air is dry, and
        forbidding water the static limit would have allowed when it is
        humid. Falling back on staleness is what keeps that safe.
        """
        now = time.monotonic() if now is None else now
        if self._dew is None or now - self._dew_ts > self.dew_max_age:
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
          no longer applies because the measurement says it is not. These two
          stay at 0 % on purpose - do not "make everything fail open".

        Note the hardware limit: per the legacy system's records the actuators
        are NC (normally closed), so a loss of signal or power closes them
        regardless of what we command. Fail-open therefore covers software and
        bridge failure (with the coupler's Modbus watchdog fallback set to full
        scale), not power loss. True fail-open would need NO actuators.
        """
        rl = state.temps.get(circuit_sensor)
        vl = state.temps.get("vl_total")

        # lost knowledge of this circuit -> fail open (see policy above)
        if circuit_sensor in state.faults or rl is None:
            return self.failsafe_pct, f"sensor_fault:{circuit_sensor}"

        # frost protection beats everything
        if rl < self.frost_c:
            return 100.0, "frost_protect"

        # known-dangerous supply: these two are the deliberate fail-CLOSED cases
        if mode == "heating" and vl is not None and vl > self.vl_max_heating:
            return 0.0, "vl_overtemp"    # screed protection

        if mode == "cooling" and vl is not None and vl < self.cooling_supply_limit():
            return 0.0, "vl_undertemp"   # condensation guard

        return proposed_pct, None
