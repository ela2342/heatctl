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
        """Returns (valve position, reason). reason != None => override active."""
        rl = state.temps.get(circuit_sensor)
        vl = state.temps.get("vl_total")

        # sensor fault on this circuit: conservative mid position
        if circuit_sensor in state.faults or rl is None:
            return self.failsafe_pct, f"sensor_fault:{circuit_sensor}"

        # frost protection beats everything
        if rl < self.frost_c:
            return 100.0, "frost_protect"

        if mode == "heating" and vl is not None and vl > self.vl_max_heating:
            return 0.0, "vl_overtemp"    # screed protection

        if mode == "cooling" and vl is not None and vl < self.vl_min_cooling:
            return 0.0, "vl_undertemp"   # condensation guard (conservative)

        return proposed_pct, None
