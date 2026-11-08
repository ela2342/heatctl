"""Replay harness for the per-room model (optimizer/house.py).

    venv/bin/python -m optimizer.replay_rooms CONFIG JOURNAL.gz [JOURNAL.gz ...]
        [--params optimizer/params.yaml] [--set couplings.open.diele-wohnzimmer=150]
        [--warmup-h 24]

The same method as `optimizer/replay.py`, and the same gate: from the top of
every hour, run the model open-loop on the recorded inputs and compare each
room's predicted air with what its sensor said, against persistence. Read
that module's docstring for why the score is a best case (the weather is the
weather that happened).

What differs is the input. Per room, per minute:
- outdoor: the deployed estimator's `opt/state`, as in replay.py;
- solar: `opt/room/<room>/solar_w`, the facade model's per-room figure (0
  for a room it does not publish, which is a room with no modelled window);
- heat: each circuit's `m_dot c_p (VL - RL)` from `valve_actual/<valve>`,
  `temp/<sensor>` and `temp/vl_total`, as section 2.3 asks. No COP.

A room sensor is folded in only when it sends. A Shelly sends on a 0.5 K
change or every 7200 s, so for scoring a reading stands for up to
`READING_LIFE_S`: its silence says the room has not moved.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass

import yaml

from .house import (HouseFilter, HouseModel, build_couplings, build_rooms,
                    circuit_heat_w, occupancy_w)
from .params import load_params
from .replay import apply_overrides, read_journal
from .estimator import Reading

STEP_S = 60.0
HORIZONS_H = (3, 6, 12, 24)
INPUT_LIFE_S = 300.0        # an input older than this is no input
READING_LIFE_S = 7800.0     # the Shelly's 7200 s heartbeat, plus slack
R_AIR_K = math.sqrt(0.1 ** 2 + 0.5 ** 2 / 12.0)   # noise + 0.5 K quantisation

# RETURNS AS SLAB MEASUREMENTS (DESIGN_ESTIMATION_PLANNING 2.4).
# `returns="coast"`: only while the compressor has been off COAST_S and the
#   pump circulates - the supply is then the mixed return, so the water sits
#   at slab temperature and `a` hardly matters (taken as 1, its residual in R).
# `returns="all"`: also while the source runs, with each circuit's `a` learned
#   against the filter's own slab estimate. Adaptive and partly circular - the
#   slab it learns against was itself anchored by returns - which is why the
#   coast-only variant is the honest baseline.
# Validity is rl_gate's rule (D-009, D-041): open >= 27.5 % for >= 300 s.
RL_MIN_OPEN_PCT = 27.5
RL_SETTLE_S = 300.0
COAST_S = 1200.0
RETURN_EVERY_S = 600.0      # one update per circuit per 10 min: consecutive
                            # 1 Hz readings are not independent measurements
R_RETURN_K = math.sqrt(0.1 ** 2 + 0.1 ** 2 / 12.0 + 0.3 ** 2)  # sensor, 0.1 K
                            # step, and circuit-vs-room-node mismatch (0.3)
A_PRIOR, A_MIN, A_MAX, A_ALPHA = 0.7, 0.3, 1.0, 0.02


@dataclass
class Row:
    t: float
    x: tuple[float, ...]
    u: tuple[float, ...]
    air: dict[str, float]           # readings standing at t


class RoomReplay:
    def __init__(self, cfg: dict, params: dict, returns: str = "off",
                 gains: str = "house") -> None:
        if returns not in ("off", "coast", "all"):
            raise ValueError(f"returns must be off|coast|all, got {returns!r}")
        self.returns = returns
        b, f = params["building"], params["filter"]
        self.params = params
        self.sensor_offset = {n: float(x) for n, x in
                              (params.get("sensor_offset_per_k") or {}).items()}
        self.rooms = build_rooms(cfg, params)
        self.model = HouseModel(self.rooms, float(b["f_sol"]),
                                build_couplings(params), gains)
        self.fp = f
        self.t_ground = float(b["t_ground"])
        base = cfg.get("mqtt", {}).get("base_topic", "heatctl")
        self.base = base
        self.state_topic = f"{base}/opt/state"
        self.vl_topic = f"{base}/temp/vl_total"
        self.sol_topic = {r.name: f"{base}/opt/room/{r.name}/solar_w"
                          for r in self.rooms}
        self.room_of_topic = {r.temp_topic: r.name for r in self.rooms
                              if r.temp_topic}
        self.inputs: dict[str, Reading] = {}
        self.latest: dict[str, Reading] = {}       # room -> last reading
        self.pending: dict[str, float] = {}        # room -> unfolded sample
        self.filter: HouseFilter | None = None
        self.rows: list[Row] = []
        self.now = 0.0
        self._next: float | None = None
        self._unstepped = 0.0
        self.heat_mismatch = 0
        self.freq_topic = f"{base}/hp/compressor_freq"
        self.rl_total_topic = f"{base}/temp/rl_total"
        self._open_since: dict[str, float] = {}     # valve -> above threshold since
        self._running_until = 0.0                   # last time compressor > 0
        self._last_return: dict[str, float] = {}
        self.a: dict[str, float] = {}               # circuit -> learned a
        self.return_updates = {"coast": 0, "running": 0}

    def topics(self) -> set[str]:
        t = {self.state_topic, self.vl_topic, self.freq_topic,
             self.rl_total_topic} | set(self.sol_topic.values())
        t |= set(self.room_of_topic)
        for r in self.rooms:
            for sensor, valve in r.circuits:
                t.add(f"{self.base}/temp/{sensor}")
                t.add(f"{self.base}/valve_actual/{valve}")
        return t

    def _input(self, topic: str) -> float | None:
        r = self.inputs.get(topic)
        return r.value if r and r.fresh(INPUT_LIFE_S, self.now) else None

    def feed(self, t: float, topic: str, payload: str) -> None:
        if self._next is None:
            self._next = (math.floor(t / STEP_S) + 1) * STEP_S
        while t >= self._next:
            self._step(self._next)
            self._next += STEP_S
        self.now = t
        if topic == self.state_topic:
            import json
            try:
                self.inputs[topic] = Reading(float(json.loads(payload)["outdoor"]), t)
            except (ValueError, KeyError, TypeError):
                pass
            return
        try:
            v = float(payload)
        except ValueError:
            return
        if topic == self.freq_topic and v > 0.0:
            self._running_until = t
        if topic.startswith(f"{self.base}/valve_actual/"):
            valve = topic.rsplit("/", 1)[1]
            if v < RL_MIN_OPEN_PCT:
                self._open_since.pop(valve, None)
            else:
                self._open_since.setdefault(valve, t)
        room = self.room_of_topic.get(topic)
        if room is not None:
            # A sensor that is not where the room's mean is: Wohnzimmer's Shelly
            # sits in the warm part, with cold air pooling along the south side
            # (owner: 19.1 at the south wall vs 21.8 opposite; an unconnected
            # chimney with a fresh-air annulus draws). The model's air node is
            # the room mean, so the reading is corrected before it is used -
            # for the filter and the score alike - by a fraction of the
            # indoor-outdoor difference (`sensor_offset_per_k`), the same
            # form layer 1 uses.
            k = self.sensor_offset.get(room, 0.0)
            out = self._input(self.state_topic)
            if k and out is not None and v > out:
                v -= k * (v - out)
            self.latest[room] = Reading(v, t)
            self.pending[room] = v
        else:
            self.inputs[topic] = Reading(v, t)

    def heat_w(self) -> dict[str, float] | None:
        vl = self._input(self.vl_topic)
        if vl is None:
            return None
        out = {}
        for r in self.rooms:
            q = 0.0
            for sensor, valve in r.circuits:
                op = self._input(f"{self.base}/valve_actual/{valve}")
                rl = self._input(f"{self.base}/temp/{sensor}")
                if op is None or rl is None:
                    self.heat_mismatch += 1
                    continue
                q += circuit_heat_w(op, vl, rl)
            out[r.name] = q
        return out

    def u_now(self) -> list[float] | None:
        outdoor = self._input(self.state_topic)
        heat = self.heat_w()
        if outdoor is None or heat is None:
            return None
        m = self.model
        u = [0.0] * m.m
        u[m.U_OUT], u[m.U_GROUND], u[m.U_ONE] = outdoor, self.t_ground, 1.0
        lt = time.localtime(self.now)
        hour, weekend = lt.tm_hour + lt.tm_min / 60.0, lt.tm_wday >= 5
        for r in self.rooms:
            u[m.u_sol[r.name]] = self._input(self.sol_topic[r.name]) or 0.0
            u[m.u_heat[r.name]] = heat[r.name]
            u[m.u_occ[r.name]] = occupancy_w(self.params, r.name, hour, weekend)
        return u

    def standing(self) -> dict[str, float]:
        return {n: r.value for n, r in self.latest.items()
                if r.fresh(READING_LIFE_S, self.now)}

    def _step(self, t: float) -> None:
        self.now = t
        self._unstepped += STEP_S
        u = self.u_now()
        air = self.standing()
        if u is None:
            return
        if self.filter is None:
            if not air:
                return
            mean = sum(air.values()) / len(air)
            x0 = [air.get(r.name, mean) for r in self.rooms]
            x0 += [air.get(r.name, mean) for r in self.rooms if r.slab]
            f = self.fp
            self.filter = HouseFilter(self.model, x0, f["p0_air_k"],
                                      f["p0_slab_k"], f["q_air_k_per_h"],
                                      f["q_slab_k_per_h"],
                                      f.get("p0_b_out_k", 3.0),
                                      f.get("q_b_out_k_per_h", 0.3),
                                      f.get("p0_gain_w", 300.0),
                                      f.get("q_gain_w_per_h", 60.0))
            self.pending.clear()
            self._unstepped = 0.0
        else:
            self.filter.predict(self._last_u, self._unstepped)
            self._unstepped = 0.0
            for room, z in self.pending.items():
                self.filter.update_air(room, z, R_AIR_K)
            self.pending.clear()
            if self.returns != "off":
                self._fold_returns(t)
        # The input over [t, t+60) is the one standing at t.
        self._last_u = u
        self.rows.append(Row(t, tuple(self.filter.x), tuple(u), air))


    def _fold_returns(self, t: float) -> None:
        vl = self._input(self.vl_topic)
        freq = self._input(self.freq_topic)
        if vl is None or freq is None:
            return
        coast = freq == 0.0 and t - self._running_until >= COAST_S
        mixed = self._input(self.rl_total_topic)
        if coast and (mixed is None or abs(vl - mixed) > 0.3):
            coast = False         # supply not yet at the mixed return
        if not coast and self.returns != "all":
            return
        f = self.filter
        for r in self.rooms:
            if not r.slab:
                continue          # a fan coil's return is the water, not a slab
            for sensor, valve in r.circuits:
                since = self._open_since.get(valve)
                if since is None or t - since < RL_SETTLE_S:
                    continue      # stagnant: reads the cabinet (D-009)
                if t - self._last_return.get(sensor, -1e18) < RETURN_EVERY_S:
                    continue
                rl = self._input(f"{self.base}/temp/{sensor}")
                if rl is None:
                    continue
                self._last_return[sensor] = t
                slab = f.x[self.model.slab[r.name]]
                if coast:
                    f.update_return(sensor, r.name, rl, vl, 1.0, R_RETURN_K)
                    self.return_updates["coast"] += 1
                    continue
                a = self.a.get(sensor, A_PRIOR)
                # Learn a where it is observable: water well off the slab.
                if abs(vl - slab) > 1.5:
                    est = (vl - rl) / (vl - slab)
                    est = min(A_MAX, max(A_MIN, est))
                    self.a[sensor] = a = a + A_ALPHA * (est - a)
                # R grows with what `a` does not know: sigma_a 0.15 times the
                # supply-to-slab gap it multiplies.
                r_k = math.hypot(R_RETURN_K, 0.15 * abs(vl - slab))
                f.update_return(sensor, r.name, rl, vl, a, r_k)
                self.return_updates["running"] += 1


def score(rp: RoomReplay, horizons=HORIZONS_H, warmup_h: float = 24.0):
    """Per room and for the house mean: open-loop RMSE against persistence.

    The house figure averages the rooms that have a standing reading at
    both ends, prediction and measurement over the same rooms."""
    horizons = sorted(horizons)
    rows, m = rp.rows, rp.model
    names = [r.name for r in rp.rooms]
    by_t = {round(r.t): i for i, r in enumerate(rows)}
    keys = names + ["house"]
    acc = {k: {h: ([], []) for h in horizons} for k in keys}
    if not rows:
        return {}
    first = rows[0].t + warmup_h * 3600.0
    for i0, r0 in enumerate(rows):
        if r0.t < first or round(r0.t) % 3600 != 0:
            continue
        x = list(r0.x)
        i = i0
        for step in range(1, horizons[-1] * 60 + 1):
            j = by_t.get(round(r0.t + step * STEP_S))
            if j is None:
                break
            x = m.step(x, rows[i].u, STEP_S)
            i = j
            if step % 60 or step // 60 not in acc["house"]:
                continue
            h = step // 60
            end = rows[j].air
            both = [n for n in names if n in end and n in r0.air]
            for n in both:
                k = m.air[n]
                acc[n][h][0].append((x[k] - end[n]) ** 2)
                acc[n][h][1].append((r0.air[n] - end[n]) ** 2)
            if both:
                pm = sum(x[m.air[n]] for n in both) / len(both)
                em = sum(end[n] for n in both) / len(both)
                sm = sum(r0.air[n] for n in both) / len(both)
                acc["house"][h][0].append((pm - em) ** 2)
                acc["house"][h][1].append((sm - em) ** 2)
    out = {}
    for k in keys:
        out[k] = {}
        for h in horizons:
            e, p = acc[k][h]
            if not e:
                continue
            rmse, prmse = math.sqrt(sum(e) / len(e)), math.sqrt(sum(p) / len(p))
            out[k][h] = {"n": len(e), "rmse": rmse, "persistence_rmse": prmse,
                         "skill": 1.0 - rmse / prmse if prmse > 0 else float("nan")}
    return out


def run(cfg: dict, params: dict, journals: list[str],
        returns: str = "off", gains: str = "house") -> RoomReplay:
    rp = RoomReplay(cfg, params, returns, gains)
    for t, topic, payload in read_journal(journals, rp.topics()):
        rp.feed(t, topic, payload)
    return rp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("config")
    ap.add_argument("journals", nargs="+")
    ap.add_argument("--params", default="optimizer/params.yaml")
    ap.add_argument("--set", action="append", default=[], dest="sets")
    ap.add_argument("--warmup-h", type=float, default=24.0)
    ap.add_argument("--returns", choices=("off", "coast", "all"), default="off",
                    help="use circuit returns as slab measurements")
    ap.add_argument("--gains", choices=("house", "rooms"), default="house",
                    help="unknown heat: one outdoor bias, or one gain per room")
    a = ap.parse_args(argv)
    with open(a.config) as f:
        cfg = yaml.safe_load(f)
    params = load_params(a.params)
    apply_overrides(params, a.sets)
    rp = run(cfg, params, a.journals, a.returns, a.gains)
    print(f"{len(rp.rows)} minutes replayed, {len(rp.rooms)} rooms, "
          f"returns {a.returns} {rp.return_updates}"
          + (f", overrides: {' '.join(a.sets)}" if a.sets else ""))
    if rp.filter:
        if rp.model.b_out is not None:
            bo = [r.x[rp.model.b_out] for r in rp.rows]
            H = sum(r.ua_ao for r in rp.rooms)
            print(f"b_out: final {bo[-1]:+.2f} K, mean {sum(bo) / len(bo):+.2f} K"
                  f" (= {H * sum(bo) / len(bo):+.0f} W the model was missing)")
        if rp.model.gain:
            print("unknown gain per room, W (mean over the run, then last day):")
            tail = [r for r in rp.rows if r.t >= rp.rows[-1].t - 86400]
            tot = 0.0
            for n, i in rp.model.gain.items():
                m_all = sum(r.x[i] for r in rp.rows) / len(rp.rows)
                m_day = sum(r.x[i] for r in tail) / len(tail)
                tot += m_all
                area = next(r.area_m2 for r in rp.rooms if r.name == n)
                print(f"   {n:13s} {m_all:+6.0f}   {m_day:+6.0f}   ({m_all / area:+5.1f} W/m2)")
            print(f"   {'total':13s} {tot:+6.0f}")
        print("innovations   room            n    mean     sd    lag1")
        for n, v in rp.filter.innovations.items():
            if len(v) > 2:
                mu = sum(v) / len(v)
                var = sum((y - mu) ** 2 for y in v) / len(v)
                lag = (sum((v[i] - mu) * (v[i - 1] - mu) for i in range(1, len(v)))
                       / len(v) / var) if var > 0 else 0.0
                print(f"              {n:13s} {len(v):5d} {mu:+6.2f} {var ** .5:6.2f} {lag:+6.2f}")
        if rp.filter.return_innovations:
            print("return innovations  circuit  n    mean     sd   learned a")
            for c, v in sorted(rp.filter.return_innovations.items()):
                mu = sum(v) / len(v)
                sd = (sum((q - mu) ** 2 for q in v) / len(v)) ** 0.5
                print(f"                    {c:8s} {len(v):4d} {mu:+6.2f} {sd:6.2f}"
                      f"   {rp.a.get(c, float('nan')):.2f}")
    s = score(rp, warmup_h=a.warmup_h)
    print("skill (model RMSE / persistence RMSE)")
    hs = HORIZONS_H
    print("  room          " + "".join(f"{h:>18d} h" for h in hs))
    for k, by_h in s.items():
        cells = "".join(
            f"   {by_h[h]['rmse']:4.2f}/{by_h[h]['persistence_rmse']:4.2f} {by_h[h]['skill']:+6.2f}"
            if h in by_h else " " * 20 for h in hs)
        print(f"  {k:13s} {cells}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
