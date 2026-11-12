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
        # ANTI-WINDUP, tightened 2026-11-12. The integral used to be clamped
        # to out_max + |p|, which let a long-saturated loop bank ~125 % and
        # then hold the valve fully open for hours after the error reversed
        # (Badezimmer, 0.5 K over its lowered setpoint at 50 %). Now: do not
        # integrate further INTO saturation, and bound the integral to the
        # output range itself, so a reversal leaves the rail at once.
        i_new = self._i + self.ki * e * dt
        # Grow the integral only until P + I reaches the limit (never shrink
        # it on that account - only the error does that).
        if e > 0:
            i_new = min(i_new, max(self._i, self.out_max - p))
        elif e < 0:
            i_new = max(i_new, min(self._i, self.out_min - p))
        self._i = max(self.out_min, min(self.out_max, i_new))
        d = 0.0
        if self.kd and self._last_pv is not None and dt > 0:
            dpv = (pv - self._last_pv) / dt
            d = -self.kd * (-dpv if self.invert else dpv)
        self._last_pv = pv
        out = p + self._i + d
        return max(self.out_min, min(self.out_max, out))
