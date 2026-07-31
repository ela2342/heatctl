"""Quantities computed from parameters, never stored (D-031, D-032).

Nothing in here may be pasted into a config file or a comment as a number. The
whole point is that re-measuring an input moves every dependent figure by
itself: when the flow was corrected 1.24 -> 1.44 m3/h on 2026-07-31, `ua_sa`,
`k`, `Q_max` and the pre-conditioning lead time all had to move together, and a
stored constant would have survived that silently.

**Uncertainty is propagated by Monte Carlo, deliberately.** Analytic Jacobians
would be faster and are the conventional choice, but they have to be
re-derived by hand every time a formula changes - and a stale Jacobian gives a
confidently wrong error bar, which is worse than none. Sampling re-derives
itself. It is also how the correlations stay honest: `ua_sa` is computed from
the same flow sample that `m_dot_c` uses, so their perfect correlation is
structural rather than something a covariance matrix has to remember.

Bounded parameters are sampled truncated to their bounds - `flow_m3_h` can sit
ON its upper bound, where a naive Gaussian would put half its mass above a flow
the exchanger physically cannot pass.

**Flow is telemetry, not a constant, and this file learned that the hard way.**
Two hours after params.yaml recorded the pump as "pinned at 100 %", it was
observed at 70 %. Anything still trusting the stored value would have overstated
delivered power by 43 %. Use `flow_from_pump()` with the live `dc_pump_speed`;
the stored value is a fallback for when that reading is missing.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .params import Param

N_SAMPLES = 4000
_SEED = 20260731          # fixed: a reproducible error bar beats a fresh one


@dataclass(frozen=True)
class Uncertain:
    """A derived value with a 1-sigma spread from sampling its inputs."""
    value: float
    sigma: float
    unit: str = ""

    def __str__(self) -> str:
        return f"{self.value:.4g} +- {self.sigma:.2g} {self.unit}".strip()


def _sample(p, rng: random.Random) -> float:
    """One draw, respecting bounds. Plain floats are treated as exact."""
    if not isinstance(p, Param) or p.sigma is None:
        return float(p)
    lo, hi = p.bounds if p.bounds else (-math.inf, math.inf)
    for _ in range(50):
        x = rng.gauss(float(p), p.sigma)
        if lo <= x <= hi:
            return x
    return min(max(float(p), lo), hi)     # degenerate bounds: fall back


def propagate(fn, params: dict, n: int = N_SAMPLES) -> Uncertain:
    """Monte-Carlo `fn` over sampled parameters.

    `fn` receives a dict of plain floats drawn jointly, so any quantity it
    computes from two dependent inputs inherits their dependence for free.
    """
    rng = random.Random(_SEED)
    flat = {k: v for k, v in params.items()}
    base = fn({k: float(v) for k, v in flat.items()})
    xs = []
    for _ in range(n):
        draw = {k: _sample(v, rng) for k, v in flat.items()}
        xs.append(fn(draw))
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    return Uncertain(base, math.sqrt(var))


# ---------- the derivations themselves ----------

def _inputs(p: dict, pump_pct: float | None = None) -> dict:
    """The raw parameters every quantity below is built from.

    `pump_pct` overrides the stored flow with the live telemetry value, which
    is the only correct thing to do once the pump modulates - and it does.
    """
    h, b = p["hydronics"], p["building"]
    idn = b["ua_sa_identification"]
    flow = h["flow_m3_h"] if pump_pct is None else Param(
        flow_from_pump(p, pump_pct), sigma=0.05, unit="m3/h",
        bounds=list(h["flow_m3_h"].bounds), kind="measured",
        derived_from=["dc_pump_speed"])
    return {
        "flow_m3_h": flow,
        "rho": h["water_density_kg_m3"],
        "cp": h["water_specific_heat_j_kg_k"],
        "manifold_dt_k": idn["manifold_dt_k"],
        "room_mean_c": idn["room_mean_c"],
        "water_mean_c": idn["water_mean_c"],
    }


def flow_from_pump(params: dict, pump_pct: float) -> float:
    """Flow in m3/h from the DC pump's speed telemetry (0x802A, %).

    Proportional, and the spec pins it: `flow_min / flow_max = 0.58/1.44 =
    40.3 %`, against an F8 "DC Pump Min Speed" default of 40 %. Both endpoints
    agree with `flow = flow_max * speed/100`.

    Clamped to the exchanger's specified range, because a speed below the
    pump's own minimum means the reading is wrong, not that the exchanger is
    being starved - and Er03 (water flow failure) is the machine's business,
    not ours.
    """
    f = params["hydronics"]["flow_m3_h"]
    lo, hi = f.bounds if isinstance(f, Param) and f.bounds else (0.58, 1.44)
    return min(hi, max(lo, hi * pump_pct / 100.0))


def _mdot_c(v: dict) -> float:
    return v["rho"] * v["cp"] * v["flow_m3_h"] / 3600.0


def _ua_sa(v: dict) -> float:
    """Room-to-water conductance, from the identification measurement.

    Q = m_dot_c * dT and UA = Q / (T_room - T_water). Because Q carries the
    flow, UA is PERFECTLY CORRELATED with it - which is exactly why this is
    computed rather than stored.
    """
    return _mdot_c(v) * v["manifold_dt_k"] / (v["room_mean_c"] - v["water_mean_c"])


def _k(v: dict) -> float:
    """s = k (T_room - P04) at steady state.

    **Invariant to the flow.** Scaling the flow scales `m_dot_c` and `ua_sa`
    identically, and they cancel here - which is why the constraint-optimal
    setpoint barely moved (19.27 -> 19.26) across a 16 % flow correction while
    Q_max moved by the full 16 %.
    """
    ua, mc = _ua_sa(v), _mdot_c(v)
    return ua / (mc - ua / 2.0)


def _q_max_coeff(v: dict) -> float:
    """Q_max = this * (T_room - limit). Carries a bare m_dot_c, so it scales."""
    k = _k(v)
    return _mdot_c(v) * k / (1.0 + k)


def mdot_c(p: dict) -> Uncertain:
    u = propagate(_mdot_c, _inputs(p));  return Uncertain(u.value, u.sigma, "W/K")


def ua_sa(p: dict) -> Uncertain:
    u = propagate(_ua_sa, _inputs(p));   return Uncertain(u.value, u.sigma, "W/K")


def k_spread(p: dict) -> Uncertain:
    u = propagate(_k, _inputs(p));       return Uncertain(u.value, u.sigma, "-")


def q_max_coeff(p: dict) -> Uncertain:
    u = propagate(_q_max_coeff, _inputs(p))
    return Uncertain(u.value, u.sigma, "W/K")


def p04_opt(p: dict, limit_c: float, room_c: float) -> Uncertain:
    """The constraint-optimal cooling setpoint: (limit + k*T_room) / (1 + k).

    Below it the condensation constraint binds and Q rises at m_dot_c per K;
    above it the room side binds and Q falls at m_dot_c*k/(1+k) per K. The peak
    is therefore SHARP and ASYMMETRIC - erring low costs about 2.4x erring
    high - so a controller in doubt should sit above this, not below.
    """
    def f(v: dict) -> float:
        k = _k(v)
        return (limit_c + k * room_c) / (1.0 + k)
    u = propagate(f, _inputs(p))
    return Uncertain(u.value, u.sigma, "degC")


def q_max(p: dict, limit_c: float, room_c: float) -> Uncertain:
    def f(v: dict) -> float:
        return _q_max_coeff(v) * (room_c - limit_c)
    u = propagate(f, _inputs(p))
    return Uncertain(u.value, u.sigma, "W")
