"""Safety layer. Runs AFTER control and may override everything.

Principle: control proposes, safety decides. Every rule here must work
without MQTT command plane, without HA, without layer 2.
"""
from __future__ import annotations

import logging

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

    def clamp_setpoint(self, sp: float) -> float:
        return max(self.setpoint_min, min(self.setpoint_max, sp))

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

        if mode == "cooling" and vl is not None and vl < self.vl_min_cooling:
            return 0.0, "vl_undertemp"   # condensation guard

        return proposed_pct, None
