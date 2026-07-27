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
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path

import yaml

from .backends.base import make_backend
from .mqtt_plane import ControlPlane
from .pid import PID
from .rl_gate import FLUSH, MEASURE, RLGate
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

        # Where the per-circuit return target comes from - see
        # _effective_return_sp() for why tracking the system return is the
        # useful choice and a fixed absolute number mostly is not.
        self.return_sp_source = c.get("return_setpoint_source", "fixed")
        self.system_return_sensor = c.get("system_return_sensor", "rl_total")
        self.system_return_bias = float(c.get("system_return_bias_c", 0.0))

        # Must run after the PIDs exist: mode decides their direction.
        self._apply_mode(self.mode, reset=False)

        # A closed circuit's RL sensor reads slab ambient, not loop water -
        # see rl_gate.py for why feeding that to the PID makes it hunt.
        self.rl_gate = RLGate(cfg)

        self.db = self._open_db(cfg["logging"]["state_db"])
        self._cycle = 0
        self._last_return_sp = self.return_sp   # for telemetry before first step
        # Failsafe log throttling - see failsafe().
        self._failsafe_reason: str | None = None
        self._failsafe_since = 0.0
        self._failsafe_logged = 0.0

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

    def _effective_return_sp(self, state) -> float:
        """Return-temperature target for the per-circuit fallback PIDs.

        With `return_setpoint_source: system_return` this tracks the mixed
        system return (`rl_total`, sensor 14) instead of a fixed number, which
        turns the inner loop into a *balancing* controller: a circuit returning
        warmer than the system average gets more flow in cooling, colder gets
        more flow in heating, so distribution evens out. The heat pump keeps
        owning the absolute water temperature via its own return setpoint, so
        this loop only decides *distribution* - which is exactly the job left
        to heatctl while per-room air sensors are missing.

        A fixed absolute target is close to useless in cooling: the slab return
        sits below any plausible target even while the rooms are warm, because
        the slab is always cooler than the air it is cooling. Measured
        2026-07-26: returns 18.5-19.2 degC against a 20.0 target commanded 0 %
        everywhere, i.e. no cooling at all, with rooms at 22-23 degC.

        `system_return_bias_c` is applied in whichever direction *increases*
        demand, so a positive bias always means "tend to open" in both modes.
        It exists because a pure system-return target makes "all valves closed"
        a valid equilibrium: with no flow every circuit equalises at slab
        temperature, the error is zero everywhere, and a controller that starts
        with an empty integrator therefore stays shut. Leave it at 0 only if
        something else guarantees flow.
        """
        if self.return_sp_source != "system_return":
            return self.return_sp
        sys_rl = state.temps.get(self.system_return_sensor)
        if sys_rl is None:
            return self.return_sp      # sensor faulted or stale -> fixed value
        if self.mode == "cooling":
            return sys_rl - self.system_return_bias
        return sys_rl + self.system_return_bias

    # ---------- commands from MQTT (layer 2 / HA) ----------
    def on_command(self, kind: str, key: str, payload: str) -> None:
        if kind == "mode" and payload in ("heating", "cooling", "off"):
            log.info("mode -> %s", payload)
            self._apply_mode(payload)
        elif kind == "setpoint" and key in self.room_setpoints:
            sp = self.safety.clamp_setpoint(float(payload))
            # Log only real changes: the wall-unit bridge republishes the dial
            # value every minute whether or not it moved, and logging each one
            # buries everything else.
            if sp != self.room_setpoints[key]:
                log.info("setpoint %s -> %.1f degC", key, sp)
            self.room_setpoints[key] = sp

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
        self._failsafe_cleared()

        # Dew point in, before safety runs: it sets the real condensation
        # limit for this cycle. Absent or stale simply leaves safety on its
        # static fallback, which is why layer 1 still works with no broker.
        self.safety.set_dew_point(self.plane.dew_point(self.safety.dew_max_age))

        # One target per cycle, shared by every circuit's fallback PID.
        return_sp = self._effective_return_sp(state)
        self._last_return_sp = return_sp

        now = time.monotonic()
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
                    # Room air drives the valve directly; RL is not consulted,
                    # so its validity is irrelevant on this path.
                    proposed = room_out
                else:
                    proposed = self._return_control(
                        valve, sensor, state, return_sp, dt, now)
                pct, reason = self.safety.apply(self.mode, state, sensor, proposed)
                await self.io.write_valve(valve, pct)
                # Record what the plant actually received, not what control
                # asked for - safety may have overridden it, and real flow is
                # what decides whether RL will mean anything.
                self.rl_gate.record_command(valve, pct, now)
                if reason:
                    await self.plane.publish(f"override/{valve}", reason)

        await self.telemetry(state)
        self._log_db(state)
        self._cycle += 1

    def _return_control(self, valve: str, sensor: str, state,
                        return_sp: float, dt: float, now: float) -> float:
        """Per-circuit return-temperature fallback, gated on RL validity.

        Used whenever a room has no fresh air temperature - which today is
        most of the house. See rl_gate.py for why the gating is not optional:
        ungated, this loop hunts, because a closed circuit's RL always drifts
        in the direction that reads as "more demand".
        """
        rl = state.temps.get(sensor)
        if rl is None:
            return self.safety.failsafe_pct       # lost knowledge -> fail open

        action = self.rl_gate.action(valve, now)
        if action is MEASURE:
            out = self.circuit_pids[sensor].step(return_sp, rl, dt)
            self.rl_gate.note_control(valve, out)
            return out
        if action is FLUSH:
            return self.rl_gate.flush_pct
        # Holding: never measured -> same fail-open policy as a dead sensor.
        # The integrator is deliberately NOT stepped; integrating an invalid
        # measurement is how the hunt builds up in the first place.
        return self.rl_gate.held(valve, self.safety.failsafe_pct)

    async def failsafe(self, reason: str) -> None:
        # Log the transition, then only once a minute. A failsafe that persists
        # (dead coupler, tripped watchdog) otherwise writes 3600 identical
        # lines an hour and pushes the *cause* out of the log ring - which is
        # exactly what happened on 2026-07-27. Staying in failsafe must remain
        # visible, but it is one fact, not one fact per second.
        now = time.monotonic()
        if reason != self._failsafe_reason or now - self._failsafe_logged > 60:
            if reason == self._failsafe_reason:
                log.warning("FAILSAFE: %s (still, since %.0f s)", reason,
                            now - self._failsafe_since)
            else:
                log.warning("FAILSAFE: %s", reason)
                self._failsafe_since = now
            self._failsafe_reason = reason
            self._failsafe_logged = now
        await self.io.write_all_valves(self.safety.failsafe_pct)
        await self.plane.publish("override/global", reason)

    def _failsafe_cleared(self) -> None:
        """Called on a good cycle, so recovery is visible in the log."""
        if self._failsafe_reason is not None:
            log.info("failsafe cleared (was %s for %.0f s)",
                     self._failsafe_reason,
                     time.monotonic() - self._failsafe_since)
            self._failsafe_reason = None

    async def telemetry(self, state) -> None:
        for n, t in state.temps.items():
            await self.plane.publish(f"temp/{n}", f"{t:.1f}")
        for n, p in state.valves_pct.items():
            await self.plane.publish(f"valve/{n}", f"{p:.0f}")
        await self.plane.publish("mode", self.mode, retain=True)
        await self.plane.publish("return_sp", f"{self._last_return_sp:.1f}")
        if self.mode == "cooling":
            # Publish the limit actually in force, not the configured one -
            # they differ whenever a dew point is available, and "why did that
            # valve shut" is unanswerable without it.
            await self.plane.publish(
                "cooling_supply_limit",
                f"{self.safety.cooling_supply_limit():.1f}")
        # State side of the HA "number" entities. Retained so HA shows the
        # right value after a restart; retaining STATE is fine, retaining
        # anything under set/ is not (see docs/DESIGN.md 2.2).
        for n, sp in self.room_setpoints.items():
            await self.plane.publish(f"setpoint/{n}", f"{sp:.1f}", retain=True)
        for f in state.faults:
            await self.plane.publish(f"fault/{f}", "1")
        # Only published when it disagrees with the command - a mismatch means
        # something other than heatctl moved the output, which is worth seeing
        # even though the next write corrects it.
        for n in state.valve_mismatch:
            await self.plane.publish(
                f"valve_mismatch/{n}", f"{state.valves_readback_pct[n]:.0f}")

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
    # Environment wins over the file, same rule as the host/credential
    # overrides, so a packaged deployment can set it without editing config.
    level = (os.environ.get("HEATCTL_LOG_LEVEL")
             or cfg["logging"]["level"]).upper()
    logging.basicConfig(level=level,
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
