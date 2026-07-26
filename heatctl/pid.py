"""Simple, robust PID with anti-windup. Deliberately boring."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PID:
    kp: float
    ki: float
    kd: float = 0.0
    out_min: float = 0.0
    out_max: float = 100.0
    invert: bool = False   # cooling mode: flip the error sign

    _i: float = 0.0
    _last_pv: float | None = None

    def reset(self) -> None:
        self._i = 0.0
        self._last_pv = None

    def step(self, setpoint: float, pv: float, dt: float) -> float:
        e = setpoint - pv
        if self.invert:
            e = -e
        p = self.kp * e
        self._i += self.ki * e * dt
        # anti-windup: clamp integrator to a sensible band
        self._i = max(self.out_min - abs(p), min(self.out_max + abs(p), self._i))
        d = 0.0
        if self.kd and self._last_pv is not None and dt > 0:
            dpv = (pv - self._last_pv) / dt
            d = -self.kd * (-dpv if self.invert else dpv)
        self._last_pv = pv
        out = p + self._i + d
        return max(self.out_min, min(self.out_max, out))
