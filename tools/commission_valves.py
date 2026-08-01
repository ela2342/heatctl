#!/usr/bin/env python3
"""Per-channel valve commissioning sweep - proves which output moves which circuit.

WHY THIS EXISTS. There is NO position feedback on the valve channels. The
coupler's `valve_readback` (0x0200 + reg) reports the output register's own
value, i.e. what heatctl last wrote - it proves the Modbus write path works and
says nothing about whether a wire reaches an actuator, or reaches the RIGHT
actuator. On 2026-07-31 that read-back was briefly mistaken for proof that ten
freshly-fitted actuators were good. It is not evidence.

config.yaml asserts a 1:1 map (analog output n drives circuit n, input n is
that circuit's return sensor). That assertion has been WRONG before: the
pre-2026-07-27 table skipped out-of-service circuits and shifted every index
after 4. This sweep is the test of it.

METHOD. The compressor stays OFF throughout, so this cannot create a
condensation hazard - the script only moves valves. That costs the obvious
tracer (supply/return dT) and uses a better one, the same physics D-009 rests
on: a circuit held SHUT stagnates, and its manifold-mounted sensor stops
measuring the circuit and starts measuring the CABINET. Circulating circuits
stay pinned to the mixed water temperature. So closing exactly one valve should
make exactly one sensor walk away from the pack, and which sensor walks is the
answer.

Nine of ten circuits stay open during every test, so flow stays well clear of
the exchanger minimum and this cannot provoke Er03.

COMMON MODE IS REMOVED. With the compressor off the whole plant drifts (the
water warms toward the slab), and that drift is far larger than the signal. Each
sensor's change is therefore reported RELATIVE TO THE MEDIAN change across all
sensors in the same window. The median is used rather than the mean because the
one genuinely diverging sensor would drag a mean toward itself and mask itself.

SAFETY. This script is the only writer while it runs - stop the heatctl add-on
first, or the two will fight over the same registers. Its per-cycle write is
also what feeds the coupler's Modbus watchdog (mask 0x8020, write-only), so it
must keep writing: if it dies, the watchdog zeroes the outputs after 10 s and
the NC actuators shut, which is the correct direction for a dead controller. On
every exit path - normal, exception, or Ctrl-C - it reopens every circuit.

    tools/commission_valves.py ./config.yaml --hold-open 900
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import signal
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heatctl.backends.base import make_backend  # noqa: E402

log = logging.getLogger("commission")

OPEN_PCT = 100.0
SHUT_PCT = 0.0


def circuit_pairs(cfg: dict) -> list[tuple[str, str]]:
    """(valve, sensor) for every water-carrying circuit, in config order."""
    out = []
    for room in cfg["rooms"]:
        for circ in room["circuits"]:
            if circ.get("valve") and circ.get("sensor"):
                out.append((circ["valve"], circ["sensor"]))
    return out


class Sweep:
    def __init__(self, cfg: dict, args: argparse.Namespace):
        self.cfg = cfg
        self.args = args
        self.backend = make_backend(cfg)
        self.pairs = circuit_pairs(cfg)
        self.valves = [v for v, _ in self.pairs]
        self.sensors = [s for _, s in self.pairs]
        # Everything else the coupler drives is parked shut, exactly as
        # heatctl parks unowned outputs - so this script leaves the plant in a
        # state heatctl recognises when it takes back over.
        self.all_valves = [c["name"] for c in cfg["valves"]["channels"]]
        self.commanded: dict[str, float] = {n: 0.0 for n in self.all_valves}
        self.rows: list[dict] = []
        self.stop = False

    async def _cycle(self, phase: str, target: str) -> None:
        """One 1 Hz tick: read everything, rewrite everything, log a row."""
        st = await self.backend.read_state()
        for name, pct in self.commanded.items():
            try:
                await self.backend.write_valve(name, pct)
            except Exception as e:              # keep the watchdog fed anyway
                log.warning("write %s failed: %s", name, e)
        row = {"ts": time.time(), "phase": phase, "target": target,
               "stale": int(st.is_stale(30.0))}
        for s in self.sensors + ["vl_total", "rl_total"]:
            row[s] = st.temps.get(s)
        self.rows.append(row)

    async def _run_for(self, seconds: float, phase: str, target: str) -> None:
        t_end = time.monotonic() + seconds
        last_report = 0.0
        while time.monotonic() < t_end and not self.stop:
            await self._cycle(phase, target)
            now = time.monotonic()
            if now - last_report > 60.0:
                last_report = now
                st = self.rows[-1]
                temps = " ".join(
                    f"{s.replace('rl_hk', '')}={st[s]:.1f}" if st[s] is not None
                    else f"{s.replace('rl_hk', '')}=--" for s in self.sensors)
                log.info("[%s %s] %4.0fs left  vl=%s  %s", phase, target or "-",
                         t_end - now,
                         f"{st['vl_total']:.1f}" if st["vl_total"] else "--",
                         temps)
            await asyncio.sleep(1.0)

    def _window(self, phase: str, target: str) -> dict[str, float]:
        """Signed drift per sensor over the settled part of a hold.

        Compares the mean of the last 60 s against the mean of the first 60 s
        of the measurement window, which starts `--measure-from` seconds into
        the hold - by then both the valve being shut AND the previous one being
        reopened have finished travelling.
        """
        rows = [r for r in self.rows if r["phase"] == phase and r["target"] == target]
        if not rows:
            return {}
        t0 = rows[0]["ts"] + self.args.measure_from
        win = [r for r in rows if r["ts"] >= t0]
        if len(win) < 120:
            return {}
        head, tail = win[:60], win[-60:]
        out = {}
        for s in self.sensors:
            a = [r[s] for r in head if r[s] is not None]
            b = [r[s] for r in tail if r[s] is not None]
            if len(a) >= 30 and len(b) >= 30:
                out[s] = sum(b) / len(b) - sum(a) / len(a)
        return out

    def verdict(self) -> None:
        print("\n=== commissioning sweep ===")
        print("For each output, the sensor that diverged most from the pack.")
        print("residual = that sensor's drift minus the median drift, in K.\n")
        print(f"{'output':<14}{'expected':<10}{'observed':<10}"
              f"{'resid':>7}{'runner-up':>11}{'  verdict'}")
        for valve, sensor in self.pairs:
            d = self._window("test", valve)
            if not d:
                print(f"{valve:<14}{sensor[3:]:<10}{'-':<10}{'':>7}{'':>11}"
                      f"  NO DATA")
                continue
            med = statistics.median(d.values())
            resid = {s: v - med for s, v in d.items()}
            ranked = sorted(resid.items(), key=lambda kv: -abs(kv[1]))
            best, best_v = ranked[0]
            second_v = abs(ranked[1][1]) if len(ranked) > 1 else 0.0
            margin = abs(best_v) - second_v
            if abs(best_v) < self.args.min_signal:
                verdict = "INCONCLUSIVE (no signal)"
            elif margin < self.args.min_margin:
                verdict = "INCONCLUSIVE (ambiguous)"
            elif best == sensor:
                verdict = "OK"
            else:
                verdict = f"CROSS-WIRED -> {best}"
            print(f"{valve:<14}{sensor[3:]:<10}{best[3:]:<10}"
                  f"{best_v:>+7.2f}{margin:>+11.2f}  {verdict}")
        print("\nA circuit held shut should drift TOWARD cabinet temperature, so")
        print("with the compressor off the expected residual sign is positive.")

    async def run(self) -> None:
        await self.backend.start()
        try:
            # Phase 1: everything open. This is also what makes it safe for the
            # owner to clear an Er03 lockout - full flow before the unit
            # retries. NC actuators need minutes to travel, so this is not
            # instant however long the register has said 100.
            for v in self.valves:
                self.commanded[v] = OPEN_PCT
            log.info("ALL CIRCUITS COMMANDED OPEN - actuators need ~3-5 min to travel")
            await self._run_for(self.args.hold_open, "open", "")
            if self.stop:
                return

            if self.args.open_only:
                log.info("--open-only: holding open, not sweeping")
                while not self.stop:
                    await self._cycle("open", "")
                    await asyncio.sleep(1.0)
                return

            # Phase 2: one circuit shut at a time. The previous circuit is
            # reopened in the SAME command, so its travel overlaps this hold
            # instead of costing a separate settling phase.
            for i, valve in enumerate(self.valves):
                if self.stop:
                    break
                for v in self.valves:
                    self.commanded[v] = OPEN_PCT
                self.commanded[valve] = SHUT_PCT
                log.info("--- test %d/%d: %s SHUT, all others open",
                         i + 1, len(self.valves), valve)
                await self._run_for(self.args.hold, "test", valve)
        finally:
            # Never leave the plant with a circuit shut, on any exit path.
            log.info("reopening every circuit")
            for v in self.valves:
                self.commanded[v] = OPEN_PCT
            for _ in range(5):
                try:
                    await self._cycle("restore", "")
                except Exception:
                    pass
                await asyncio.sleep(1.0)
            if self.args.out:
                with open(self.args.out, "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(self.rows[0].keys()))
                    w.writeheader()
                    w.writerows(self.rows)
                log.info("wrote %s (%d rows)", self.args.out, len(self.rows))
            await self.backend.stop()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("config")
    p.add_argument("--hold-open", type=float, default=900.0,
                   help="initial all-open phase, s (also the Er03-reset window)")
    p.add_argument("--hold", type=float, default=480.0,
                   help="how long each circuit is held shut, s")
    p.add_argument("--measure-from", type=float, default=240.0,
                   help="skip this much of each hold before measuring, s")
    p.add_argument("--min-signal", type=float, default=0.15,
                   help="smallest believable residual, K")
    p.add_argument("--min-margin", type=float, default=0.08,
                   help="how far the winner must beat the runner-up, K")
    p.add_argument("--open-only", action="store_true",
                   help="hold everything open forever, do not sweep")
    p.add_argument("--out", default="")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text())
    sweep = Sweep(cfg, args)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: setattr(sweep, "stop", True))

    await sweep.run()
    if not args.open_only:
        sweep.verdict()


if __name__ == "__main__":
    asyncio.run(main())
