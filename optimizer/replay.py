"""Replay harness: run the estimator over a recorded journal and score its
predictions against persistence (DESIGN_ESTIMATION_PLANNING section 7,
phase 2).

    venv/bin/python -m optimizer.replay CONFIG JOURNAL.gz [JOURNAL.gz ...]
        [--params optimizer/params.yaml] [--set building.ua_ao=216 ...]
        [--warmup-h 24]

WHY THIS EXISTS. On 2026-10-18 the model was scored by hand for the first
time, and persistence ("the air stays where it is") beat it at every horizon
from 3 h to 24 h (LOGBOOK). A planner can only be as good as the prediction
under it, so the design gates the planner on this number. A gate needs a
tool that anyone can rerun after every parameter change, and this is that
tool.

WHAT IS REPLAYED. The estimator's own code runs: `Estimator.step()`, its
filter, its staleness rules, and its signed heat input from the recorded
`hp/power_estimate` and `hp/mode_name`. The room topics come from CONFIG,
which should be the LIVE config, because that is what the plant read. Time
is journal time, through `Estimator.clock`, so a replayed day sees the same
staleness the live one did.

**Outdoor and solar come from the deployed estimator's own `opt/state`, not
from raw measurements.** No outdoor station is configured; the plant's
outdoor figure is the forecast's current hour, and solar is the forecast run
through the facade model. Neither is in the journal in any other form.
Two consequences:
- a minute with no `opt/state` (the optimizer was down) has no outdoor, and
  `step()` skips it, exactly as it would live;
- the open-loop score uses the weather and the plant's own heat input AS THEY
  HAPPENED. It is therefore the model's best case, a perfect forecast. A
  model that loses here loses to any real forecast too.

HOW IT IS SCORED. From the top of every hour after the warm-up, take the
filter's state and run the model forward open-loop, one minute at a time, on
the recorded inputs. At each horizon, compare the predicted air with the
measured house air. Persistence is scored on the same starts. `skill` is
`1 - model_rmse / persistence_rmse`: positive beats persistence, negative
loses to it. A start that runs into a gap in the inputs is dropped, not
bridged.

Fetching journals off the PFC: `cat` the `.gz` over ssh and decompress here,
never on the PFC (one core, a 1 s control loop):

    ssh root@<pfc> cat /media/sdcard/docker-root/journal/data/mqtt-YYYYMMDD.log.gz > j.gz

The files are named by UTC date, one line per message: `epoch topic payload`.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import yaml

from .estimator import Estimator, Reading
from .model import N_INPUTS, U_GROUND, U_HEAT, U_INTERNAL, U_OUTDOOR, U_SOLAR
from .model import BuildingParams, discretise
from .params import Param, load_params

STEP_S = 60.0
HORIZONS_H = (3, 6, 12, 24)


def read_journal(paths: Iterable[str],
                 topics: set[str]) -> Iterator[tuple[float, str, str]]:
    """(epoch, topic, payload) for the wanted topics, in file order.

    Pass the files oldest first. Malformed lines are skipped: the recorder
    writes whatever the broker carried, and one truncated line at a file
    boundary must not end a two-month replay.
    """
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split(" ", 2)
                if len(parts) < 3 or parts[1] not in topics:
                    continue
                try:
                    t = float(parts[0])
                except ValueError:
                    continue
                yield t, parts[1], parts[2]


@dataclass
class Row:
    """One replayed minute: the filter's state and the inputs it stepped on."""
    t: float
    x: tuple[float, float]
    air: float | None
    u: tuple[float, ...]


class Replay:
    """Drives an `Estimator` from journal messages on journal time."""

    def __init__(self, est: Estimator) -> None:
        self.est = est
        self.now = 0.0
        est.clock = lambda: self.now
        # The weather the deployed estimator used, from its own opt/state.
        # A replay does not fetch forecasts: they would be today's, not the
        # day being replayed.
        self._outdoor: Reading | None = None
        self._solar: Reading | None = None
        est.outdoor_c = self._logged_outdoor
        est.solar_w = self._logged_solar
        self.rows: list[Row] = []
        self._next_step: float | None = None

    def topics(self) -> set[str]:
        b = self.est.base
        return set(self.est.room_topics) | {
            f"{b}/hp/power_estimate", f"{b}/hp/mode_name", f"{b}/opt/state"}

    def _logged_outdoor(self) -> float | None:
        r = self._outdoor
        return r.value if r and r.fresh(self.est.max_age_s, self.now) else None

    def _logged_solar(self, point=None) -> float:
        r = self._solar
        return r.value if r and r.fresh(self.est.max_age_s, self.now) else 0.0

    def feed(self, t: float, topic: str, payload: str) -> None:
        if self._next_step is None:
            # On the minute, so the top of every hour is a step to score from.
            self._next_step = (math.floor(t / STEP_S) + 1) * STEP_S
        while t >= self._next_step:
            self._step(self._next_step)
            self._next_step += STEP_S
        self.now = t
        if topic == f"{self.est.base}/opt/state":
            try:
                s = json.loads(payload)
                self._outdoor = Reading(float(s["outdoor"]), t)
                self._solar = Reading(float(s.get("q_solar_w") or 0.0), t)
            except (ValueError, KeyError, TypeError):
                pass
            return
        self.est._on_message(topic, payload)

    def _step(self, t: float) -> None:
        self.now = t
        if self.est.step(STEP_S) is None:
            return
        f = self.est.filter
        assert f is not None
        u = [0.0] * N_INPUTS
        u[U_OUTDOOR] = self.est.outdoor_c() or 0.0
        u[U_SOLAR] = self.est.solar_w()
        u[U_INTERNAL] = float(self.est.q_int)
        u[U_HEAT] = self.est.heat_input_w()
        u[U_GROUND] = float(self.est.t_ground)
        self.rows.append(Row(t, (f.x[0], f.x[1]), self.est.house_air(),
                             tuple(u)))


def score(rows: list[Row], bp: BuildingParams,
          horizons: Iterable[int] = HORIZONS_H,
          warmup_h: float = 24.0) -> dict[int, dict[str, float]]:
    """Open-loop prediction error per horizon, against persistence."""
    horizons = sorted(horizons)
    F, G = discretise(bp, STEP_S)
    by_t = {round(r.t): i for i, r in enumerate(rows)}
    sq = {h: [] for h in horizons}
    err = {h: [] for h in horizons}
    psq = {h: [] for h in horizons}
    if not rows:
        return {}
    first = rows[0].t + warmup_h * 3600.0
    for i0, r0 in enumerate(rows):
        if r0.t < first or round(r0.t) % 3600 != 0 or r0.air is None:
            continue
        x = list(r0.x)
        i = i0
        for step in range(1, horizons[-1] * 60 + 1):
            # The input over [t, t+60) is the one recorded at t; the next row
            # must be exactly one step later or the start has hit a gap.
            j = by_t.get(round(r0.t + step * STEP_S))
            if j is None:
                break
            u = rows[i].u
            x = [sum(F[a][b] * x[b] for b in range(2))
                 + sum(G[a][b] * u[b] for b in range(N_INPUTS))
                 for a in range(2)]
            i = j
            if step % 60 == 0 and step // 60 in sq:
                h = step // 60
                air = rows[j].air
                if air is not None:
                    e = x[0] - air
                    sq[h].append(e * e)
                    err[h].append(e)
                    psq[h].append((r0.air - air) ** 2)
    out = {}
    for h in horizons:
        n = len(sq[h])
        if not n:
            continue
        rmse = math.sqrt(sum(sq[h]) / n)
        prmse = math.sqrt(sum(psq[h]) / n)
        out[h] = {"n": float(n), "rmse": rmse, "bias": sum(err[h]) / n,
                  "persistence_rmse": prmse,
                  "skill": 1.0 - rmse / prmse if prmse > 0 else float("nan")}
    return out


def apply_overrides(params: dict, sets: Iterable[str]) -> None:
    """`--set building.ua_ao=216`: replace one value, marked as an override.

    The replaced value keeps no provenance from the file. It is an
    experiment, and the result says so.
    """
    for s in sets:
        path, _, value = s.partition("=")
        if not value:
            raise ValueError(f"--set wants path=value, got {s!r}")
        *parents, leaf = path.split(".")
        node = params
        for p in parents:
            node = node[p]
        if leaf not in node:
            raise KeyError(f"--set {path}: no such parameter")
        node[leaf] = Param(float(value), kind="prior", note="replay override")


def run(cfg: dict, params: dict, journals: list[str]) -> Replay:
    params.setdefault("weather", {})
    params["weather"]["latitude"] = None   # no forecast fetches in a replay
    est = Estimator(cfg, params)
    rp = Replay(est)
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
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    with open(a.config) as f:
        cfg = yaml.safe_load(f)
    params = load_params(a.params)
    apply_overrides(params, a.sets)
    rp = run(cfg, params, a.journals)
    est = rp.est
    print(f"{len(rp.rows)} minutes replayed, ua_ao {float(est.bp.ua_ao):g}, "
          f"ua_sa {float(est.bp.ua_sa):.0f}"
          + (f", overrides: {' '.join(a.sets)}" if a.sets else ""))
    if est.filter is not None:
        s = est.filter.innovation_stats()
        print(f"innovations: n {s['n']:.0f}  mean {s['mean']:+.3f}  "
              f"sd {s['sd']:.3f}  lag1 {s['lag1']:.3f}")
    print(" horizon     n   model RMSE    bias   persistence   skill")
    for h, r in score(rp.rows, est.bp, warmup_h=a.warmup_h).items():
        print(f"  {h:3d} h  {r['n']:5.0f}   {r['rmse']:7.2f} K  "
              f"{r['bias']:+6.2f}   {r['persistence_rmse']:7.2f} K  "
              f"{r['skill']:+6.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
