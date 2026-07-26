"""heatctl - layer 1: self-sufficient base control for a WAGO 750 node.

Design rules (please still honor these in 30 years):
  1. The control core has exactly two hard dependencies: pymodbus + PyYAML
     (aiomqtt for the mqtt paths). The control-plane broker may die at any
     time; the mqtt *I/O* backend degrades to failsafe via staleness +
     the coupler's own Modbus watchdog.
  2. Safety runs after control and always wins.
  3. No state that must survive a restart: restart == safe state.

Control strategy per room:
  - room air sensor available & fresh: cascade-ish -> room PID drives all
    valves of that room's circuits.
  - otherwise: per-circuit return-temperature PID (classic UFH fallback).
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sqlite3
import sys
import time
from pathlib import Path

import yaml

from .backends.base import make_backend
from .mqtt_plane import ControlPlane
from .pid import PID
from .safety import Safety

log = logging.getLogger("heatctl")


class Controller:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.io = make_backend(cfg)
        self.safety = Safety(cfg)
        self.plane = ControlPlane(cfg, self.on_command)

        c = cfg["control"]
        self.mode: str = c["mode"]
        self.rooms = cfg["rooms"]

        self.room_setpoints: dict[str, float] = {}
        self.room_pids: dict[str, PID] = {}
        self.circuit_pids: dict[str, PID] = {}
        pr, pc = c["pid_room"], c["pid_return"]
        for room in self.rooms:
            n = room["name"]
            self.room_setpoints[n] = (
                c["default_setpoint_heating_c"] if self.mode == "heating"
                else c["default_setpoint_cooling_c"])
            self.room_pids[n] = PID(pr["kp"], pr["ki"], pr["kd"],
                                    pr["out_min"], pr["out_max"])
            for circ in room["circuits"]:
                self.circuit_pids[circ["sensor"]] = PID(
                    pc["kp"], pc["ki"], pc["kd"], pc["out_min"], pc["out_max"])

        # Must run after the PIDs exist: mode decides their direction.
        self._apply_mode(self.mode, reset=False)

        self.db = self._open_db(cfg["logging"]["state_db"])
        self._cycle = 0

    def _apply_mode(self, mode: str, reset: bool = True) -> None:
        """Apply a mode to BOTH the PID direction and the return setpoint.

        These two must never be applied independently: setting the cooling
        setpoint while leaving the PIDs in heating direction inverts the
        control sense, so the controller closes valves when cooling is needed
        and opens them when the slab is already too cold. This used to live
        duplicated in __init__ and on_command, and __init__ was missing the
        invert half - hence one function, called from both.
        """
        self.mode = mode
        inv = mode == "cooling"
        for pid in (*self.room_pids.values(), *self.circuit_pids.values()):
            pid.invert = inv
            if reset:
                pid.reset()
        c = self.cfg["control"]
        self.return_sp = (c["return_temp_setpoint_heating_c"]
                          if mode == "heating"
                          else c["return_temp_setpoint_cooling_c"])

    # ---------- commands from MQTT (layer 2 / HA) ----------
    def on_command(self, kind: str, key: str, payload: str) -> None:
        if kind == "mode" and payload in ("heating", "cooling", "off"):
            log.info("mode -> %s", payload)
            self._apply_mode(payload)
        elif kind == "setpoint" and key in self.room_setpoints:
            sp = self.safety.clamp_setpoint(float(payload))
            self.room_setpoints[key] = sp
            log.info("setpoint %s -> %.1f degC", key, sp)

    # ---------- main loop ----------
    async def run(self) -> None:
        await self.io.start()
        plane_task = asyncio.create_task(self.plane.run())
        interval = self.cfg["control"]["loop_interval_s"]
        last = time.monotonic()
        try:
            while True:
                t0 = time.monotonic()
                dt, last = t0 - last, t0
                try:
                    await self.step(dt)
                except Exception:
                    log.exception("cycle failed")
                    await self.failsafe("cycle_error")
                await asyncio.sleep(max(0.05, interval - (time.monotonic() - t0)))
        finally:
            # Order matters: mark ourselves offline while the client is still
            # connected, only then tear the plane down.
            await self.plane.stop()
            plane_task.cancel()
            await self.io.stop()

    async def step(self, dt: float) -> None:
        state = await self.io.read_state()

        if state.is_stale(self.safety.stale_timeout):
            await self.failsafe("stale_data")
            return

        for room in self.rooms:
            n = room["name"]
            room_t = self.plane.room_temp(n)
            room_out: float | None = None
            if room_t is not None:
                room_out = self.room_pids[n].step(
                    self.room_setpoints[n], room_t, dt)
                await self.plane.publish(f"room/{n}/temp", f"{room_t:.1f}")

            for circ in room["circuits"]:
                valve = circ.get("valve")
                if not valve:
                    continue
                sensor = circ["sensor"]
                if self.mode == "off":
                    proposed = 0.0
                elif room_out is not None:
                    proposed = room_out
                else:
                    rl = state.temps.get(sensor)
                    proposed = (self.safety.failsafe_pct if rl is None else
                                self.circuit_pids[sensor].step(
                                    self.return_sp, rl, dt))
                pct, reason = self.safety.apply(self.mode, state, sensor, proposed)
                await self.io.write_valve(valve, pct)
                if reason:
                    await self.plane.publish(f"override/{valve}", reason)

        await self.telemetry(state)
        self._log_db(state)
        self._cycle += 1

    async def failsafe(self, reason: str) -> None:
        log.warning("FAILSAFE: %s", reason)
        await self.io.write_all_valves(self.safety.failsafe_pct)
        await self.plane.publish("override/global", reason)

    async def telemetry(self, state) -> None:
        for n, t in state.temps.items():
            await self.plane.publish(f"temp/{n}", f"{t:.1f}")
        for n, p in state.valves_pct.items():
            await self.plane.publish(f"valve/{n}", f"{p:.0f}")
        await self.plane.publish("mode", self.mode, retain=True)
        # State side of the HA "number" entities. Retained so HA shows the
        # right value after a restart; retaining STATE is fine, retaining
        # anything under set/ is not (see docs/DESIGN.md 2.2).
        for n, sp in self.room_setpoints.items():
            await self.plane.publish(f"setpoint/{n}", f"{sp:.1f}", retain=True)
        for f in state.faults:
            await self.plane.publish(f"fault/{f}", "1")

    # ---------- history for system identification (layer 2) ----------
    def _open_db(self, path: str) -> sqlite3.Connection:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE IF NOT EXISTS samples("
                   "ts REAL, name TEXT, value REAL)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON samples(ts)")
        return db

    def _log_db(self, state) -> None:
        if self._cycle % self.cfg["logging"]["log_every_n_cycles"]:
            return
        ts = time.time()
        rows = [(ts, n, t) for n, t in state.temps.items()]
        rows += [(ts, f"valve:{n}", p) for n, p in state.valves_pct.items()]
        for room in self.rooms:
            t = self.plane.room_temp(room["name"])
            if t is not None:
                rows.append((ts, f"room:{room['name']}", t))
        with self.db:
            self.db.executemany("INSERT INTO samples VALUES (?,?,?)", rows)


def main() -> None:
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "/etc/heatctl/config.yaml"
    cfg = yaml.safe_load(Path(cfg_path).read_text())
    logging.basicConfig(level=cfg["logging"]["level"],
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ctl = Controller(cfg)
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)
    try:
        loop.run_until_complete(ctl.run())
    except (KeyboardInterrupt, RuntimeError):
        pass


if __name__ == "__main__":
    main()
