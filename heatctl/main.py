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
from .capacity import CapacityController
from .demand import DemandController
from .distribution import Distributor
from . import heatpump_map as hpm
from .heatpump import HeatPump
from .mqtt_plane import ControlPlane
from .pid import PID
from .rl_gate import FLUSH, MEASURE, RLGate
from .safety import Safety
from .setpoint import SetpointController

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

        # The RL sensors are at the manifold, so a circuit with no flow is not
        # measured at all - see rl_gate.py for why feeding that to the PID
        # locks the circuit shut.
        # Analog outputs heatctl actually drives, i.e. those assigned to a
        # circuit. Declared-but-unassigned channels exist (spares, and the two
        # out-of-service circuits) and must NOT be swept up by the failsafe:
        # doing so parked them at 100 % and left them there, because nothing
        # ever commands them again. Observed 2026-07-27.
        self.owned_valves = [c["valve"] for r in cfg["rooms"]
                             for c in r["circuits"] if c.get("valve")]
        self.unowned_valves = [c["name"] for c in cfg["valves"]["channels"]
                               if c["name"] not in self.owned_valves]

        self.rl_gate = RLGate(cfg)

        # House demand / source engagement. A RECONCILER, not an on/off
        # controller: it holds the unit powered and only powers down on an
        # explicit `off` (D-016). It also picks the plant mode when auto_mode
        # is on (D-020).
        # Heat pump client. Its own task at its own (slow) cadence - the
        # device documents a 200 ms minimum between transactions, so it must
        # never share the 1 s valve loop. See docs/HEATPUMP.md.
        self.hp = HeatPump(cfg, self.plane)

        # Load compensation: house demand -> water temperature setpoint. The
        # third level of the cascade; see setpoint.py.
        self.water_sp = SetpointController(cfg)
        # Frequency ceiling: takes as much spread as the dew point allows.
        # Spread is how the plant delivers capacity, so this MAXIMISES it under
        # a constraint rather than minimising it - see capacity.py.
        self.capacity = CapacityController(cfg)
        # Below this the silent-mode fan cap is throttling the condenser.
        self.capacity_fan_min = float(
            (cfg['control'].get('capacity') or {}).get('fan_cap_min', 400))
        self._sp_blocked = False        # edge detector for the saturation alarm
        d = cfg["control"].get("setpoint_delta") or {}
        self.sp_delta_max_age_s = float(d.get("max_age_s", 3600.0))
        self._sp_delta_active = 0.0

        # Valve distribution. Scales demands so the most-demanding circuit is
        # fully open: maximum flow, minimum spread, best COP - throttling is a
        # cost paid only to share energy between rooms. See distribution.py.
        self.dist = Distributor(cfg)
        # Pre-normalisation peak demand. This, NOT the commanded position, is
        # what tells the water-setpoint loop whether there is enough capacity:
        # normalisation pins the commanded maximum at 100 % by construction, so
        # reading valve position there would report "saturated" forever and
        # drive the water colder without limit.
        self._peak_demand: float | None = None
        self._flow_floor_pct: float | None = None

        self.demand = DemandController(
            cfg, can_command_source_mode=self.hp.enabled and self.hp.allow_writes)
        self._last_demand = None
        self._mode_warned: str | None = None

        self.db = self._open_db(cfg["logging"]["state_db"])
        self._cycle = 0
        self._last_return_sp = self.return_sp   # for telemetry before first step
        # Failsafe log throttling - see failsafe().
        self._failsafe_reason: str | None = None
        self._failsafe_since = 0.0
        self._failsafe_logged = 0.0
        # Flow-floor log throttling - same reason, see step(). None means the
        # floor is not currently binding, which is what distinguishes a fresh
        # transition from a continuing one.
        self._flow_floor_since: float | None = None
        self._flow_floor_logged = 0.0
        # Safety-override log throttling, keyed by reason - see _log_overrides().
        self._override_since: dict[str, float] = {}
        self._override_logged: dict[str, float] = {}

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
        # Default water setpoint, used to clear a stale OFF sentinel left by a
        # controller that died while the compressor was stopped.
        self.default_cooling_sp = float(c["return_temp_setpoint_cooling_c"])
        self._off_checked = False
        # The setpoint in force when the compressor was stopped, restored on
        # resume so the plant returns to its operating point rather than to a
        # default it had already trimmed away from.
        self._sp_before_off: float | None = None
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
        elif kind == "hp":
            # Heat pump register write. Async work from a sync callback, so it
            # is scheduled rather than awaited; the client serialises the bus
            # itself and drops no-ops before they cost a flash cycle.
            asyncio.create_task(self._hp_command(key, payload))

    async def _hp_command(self, key: str, payload: str) -> None:
        try:
            if key.startswith("raw/"):
                addr = int(key.split("/", 1)[1], 0)
                await self.hp.write_register(addr, int(payload, 0), "mqtt raw")
            elif key == "power":
                await self.hp.set_power(payload.strip() in ("1", "on", "true"),
                                        "mqtt")
            elif key == "mode":
                await self.hp.set_mode(payload.strip(), "mqtt")
            elif key.startswith("bit/"):
                # Named bit in a shared control register. Routed separately
                # from write_named because these are not standalone registers -
                # see HeatPump.set_control_bit on why only read-modify-write
                # against a real read is safe.
                await self.hp.set_control_bit(
                    key.split("/", 1)[1],
                    payload.strip() in ("1", "on", "true"), "mqtt")
            else:
                await self.hp.write_named(key, float(payload), "mqtt")
        except Exception:
            log.exception("heat pump command failed: %s = %r", key, payload)

    async def _trim_capacity(self, state, now: float) -> None:
        """Move the compressor frequency ceiling (R32) to spend spare margin.

        Only acts when silent mode is on AND the silent-mode fan cap has been
        raised, because R32 only binds in silent mode and silent mode with the
        default 60 RPM fan cap throttles the condenser to 7.5 % of the ~800 RPM
        it needs. Both conditions are CHECKED, not assumed - measured
        2026-07-30, that fan cap was still at its default and enabling silent
        mode without lifting it would have been a high-pressure trip.
        """
        if not self.capacity.enabled or not self.hp.allow_writes:
            return
        # NO DEW POINT -> DO NOT MAKE COLD WATER. This is the source-side half
        # of the change on 2026-08-01; `Safety.apply` used to answer an unknown
        # dew point by slamming every valve shut, which starved the pump into a
        # latched Er03 on every restart and could not stop the compressor
        # anyway. Refusing at the source is the action that actually addresses
        # the risk: no cold water is made, and valve position is left alone.
        if self.mode == "cooling" and not self.safety.dew_point_known():
            if not self.hp.cooling_is_off():
                await self.hp.set_cooling(
                    None, "dew point unknown - refusing to cool")
            await self.plane.publish("capacity/reason", "dew point unknown")
            return
        flags1 = self.hp.config.get(0x0001)
        fan_cap = self.hp.config.get(hpm.by_name("silent_max_fan_cooling").addr)
        silent_ok = (flags1 is not None and bool(flags1 >> 5 & 1)
                     and fan_cap is not None and fan_cap >= self.capacity_fan_min)
        ceiling_reg = hpm.by_name("silent_max_freq_cooling_hz")
        ceiling = self.hp.config.get(ceiling_reg.addr)
        freq = self.hp.status.get(hpm.by_name("compressor_freq").addr)
        d = self.capacity.step(
            mode=self.mode,
            supply_temp=(None if "vl_total" in state.faults
                         else state.temps.get("vl_total")),
            supply_limit=(self.safety.cooling_supply_limit()
                          if self.mode == "cooling" else None),
            current_ceiling=None if ceiling is None else float(ceiling),
            compressor_hz=None if freq is None else float(freq),
            silent_ok=silent_ok, now=now,
            stopped=self.hp.cooling_is_off())
        await self.plane.publish("capacity/reason", d.reason)

        # STOP and RESUME are the bottom of this actuator's range, not a
        # separate mechanism. The setpoint register is the transport (see
        # HeatPump.set_cooling); it is NOT being modulated.
        if d.stops:
            keep = self.hp.cooling_setpoint()
            if keep is not None:
                self._sp_before_off = keep
            log.warning("compressor STOP: %s", d.reason)
            self.log_event("compressor_stop", d.reason)
            await self.hp.set_cooling(None, d.reason)
            await self.plane.publish("capacity/compressor_stopped", "1")
            return
        if d.resumes:
            restore = self._sp_before_off or self.default_cooling_sp
            log.warning("compressor RESUME at %.0f degC: %s", restore, d.reason)
            self.log_event("compressor_resume", f"{restore:.0f}: {d.reason}")
            await self.hp.set_cooling(restore, d.reason)
            await self.plane.publish("capacity/compressor_stopped", "0")
            return
        await self.plane.publish("capacity/compressor_stopped",
                                 "1" if self.hp.cooling_is_off() else "0")

        if d.target_hz is None:
            return
        log.info("frequency ceiling %s -> %.0f Hz (%s)",
                 ceiling, d.target_hz, d.reason)
        self.log_event("capacity",
                       f"R32 {ceiling} -> {d.target_hz:.0f}: {d.reason}")
        if await self.hp.write_named(ceiling_reg.name, d.target_hz,
                                     f"capacity: {d.reason}"):
            self.capacity.note_write(now)

    # ---------- main loop ----------
    async def run(self) -> None:
        await self.io.start()
        plane_task = asyncio.create_task(self.plane.run())
        hp_task = asyncio.create_task(self.hp.run())
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
            hp_task.cancel()
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
        demands: dict[str, tuple[float, str]] = {}

        # House demand / source engagement. Computed from the PREVIOUS cycle's
        # valve positions, which is correct: the flow proxy describes the
        # manifold as it currently stands, not as this cycle is about to
        # command it.
        room_temps = {r["name"]: t for r in self.rooms
                      if (t := self.plane.room_temp(r["name"])) is not None}

        # PRE-CONDITIONING DELTA. `active = dial + delta`, computed ONCE here so
        # the wall dial and layer 2 can never fight over one value - the bridge
        # keeps owning what the occupant asked for, and layer 2 only ever shifts
        # it. Signed: negative pre-cools before a hot afternoon, positive
        # pre-heats before a cold night.
        #
        # This is what reactive control structurally cannot do. The trim aims at
        # comfort and stops when the air is comfortable, so it can never store
        # energy in the slab - measured 2026-07-30, when the plant idled for
        # 6 h 44 min before a 38 degC day because the air was at target while
        # the slab sat uncharged.
        #
        # Every consumer below reads `targets`, never `self.room_setpoints`, so
        # the house average, the room PIDs and the telemetry all see the same
        # number. Safety still clamps each one.
        delta = self.plane.setpoint_delta(self.sp_delta_max_age_s)
        targets = {n: self.safety.clamp_setpoint(sp + delta)
                   for n, sp in self.room_setpoints.items()}
        self._sp_delta_active = delta
        await self.plane.publish("setpoint_delta/active", f"{delta:+.2f}")

        self._last_demand = self.demand.step(
            self.mode, targets, room_temps, state.valves_pct, now)

        # Apply the mode the house asked for. Gated on auto_mode alone, NOT on
        # source_demand.enabled: choosing the season and choosing whether to
        # run are separate decisions, and conflating them would mean you
        # cannot have one without the other. _apply_mode flips the PID
        # direction and the return setpoint together; _sync_pump_mode further
        # down then makes the heat pump follow.
        if self.demand.auto_mode and self._last_demand.mode != self.mode:
            log.warning("plant mode %s -> %s (house average %.2f K)",
                        self.mode, self._last_demand.mode,
                        self._last_demand.mean_deviation_c or 0.0)
            self.log_event("mode", f"{self.mode} -> {self._last_demand.mode} "
                                   f"(house {self._last_demand.mean_deviation_c})")
            self._apply_mode(self._last_demand.mode)

        for room in self.rooms:
            n = room["name"]
            room_t = self.plane.room_temp(n)
            room_out: float | None = None
            if room_t is not None:
                room_out = self.room_pids[n].step(targets[n], room_t, dt)
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
                demands[valve] = (proposed, sensor)

        # Normalise across ALL circuits before safety sees anything: the
        # distribution is a property of the whole manifold, not of one room.
        raw = {v: d for v, (d, _) in demands.items()}
        self._peak_demand = max(raw.values()) if raw else None
        # `off` bypasses distribution entirely. Normalising a set of all-zero
        # demands correctly yields all-valves-open - which is right at thermal
        # equilibrium and exactly wrong when the plant is meant to be off.
        commanded = raw if self.mode == "off" else self.dist.apply(raw)

        # Pump minimum flow. Runs AFTER distribution (it needs the final
        # openings) and BEFORE safety (which must still be able to force a
        # circuit shut for frost or dew point, and outrank this). `off` is
        # exempt: no flow is wanted at all, and the source is not running.
        self._flow_floor_pct = None
        if self.mode != "off":
            commanded, raised = self.demand.enforce_flow_floor(commanded)
            if raised is not None:
                self._flow_floor_pct = raised
                # Log the TRANSITION, then at most once a minute. This fires
                # every cycle whenever the floor binds continuously, which is
                # the normal state once min_open_pct is set above what
                # distribution wants - on 2026-08-01 it was 96 of the last 100
                # lines in the container's log ring, having flushed the rest
                # out. That is the same defect `write_all_valves` and
                # `failsafe()` already carry throttles for: a persistent,
                # fully predictable condition must cost one line, not one line
                # per second, or it destroys the evidence for whatever happens
                # next.
                now = time.monotonic()
                if (self._flow_floor_since is None
                        or now - self._flow_floor_logged > 60):
                    if self._flow_floor_since is None:
                        self._flow_floor_since = now
                        log.info("flow floor: valves raised to %.0f%% mean",
                                 raised)
                    else:
                        log.info("flow floor: valves raised to %.0f%% mean "
                                 "(still, since %.0f s)", raised,
                                 now - self._flow_floor_since)
                    self._flow_floor_logged = now
            else:
                if self._flow_floor_since is not None:
                    log.info("flow floor released (was binding for %.0f s)",
                             time.monotonic() - self._flow_floor_since)
                self._flow_floor_since = None

        overrides: dict[str, list[str]] = {}
        for valve, (_, sensor) in demands.items():
            proposed = commanded[valve]
            pct, reason = self.safety.apply(self.mode, state, sensor, proposed,
                                            now)
            await self.io.write_valve(valve, pct)
                # Record what the plant actually received, not what control
                # asked for - safety may have overridden it, and real flow is
                # what decides whether RL will mean anything.
            self.rl_gate.record_command(valve, pct, now)
            if reason:
                overrides.setdefault(reason, []).append(valve)
                await self.plane.publish(f"override/{valve}", reason)
        self._log_overrides(overrides, now)

        await self._hold_source_power()
        await self._clear_stale_cooling_off()
        await self._trim_water_setpoint(state, now)
        await self._trim_capacity(state, now)

        # Make the heat pump's own mode follow the plant's, and shout if it
        # does not. Cheap to call every cycle: the client drops a write that
        # would change nothing BEFORE touching the bus, so a matching mode
        # costs nothing and no flash cycle.
        await self._sync_pump_mode()

        # Unassigned outputs get a definite, safe value rather than whatever
        # a past failsafe left them at. 0 with NC actuators means closed: an
        # output heatctl does not manage should not be passing water.
        for name in self.unowned_valves:
            await self.io.write_valve(name, 0.0)

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

    async def _hold_source_power(self) -> None:
        """Keep the unit powered, and only power it down on an explicit off.

        Powering a heat pump down is a measure of last resort, not a control
        action: the unit regulates itself, starting and stopping its own
        compressor and varying its power from the leaving/return spread. So
        this is a RECONCILER, not a controller - it replaces the HA automation
        that used to hold the bit set, which nothing has done since that
        automation was disabled.

        Costs nothing per cycle: a write that would not change the register is
        dropped before it reaches the bus, so a unit already in the right state
        never sees a flash cycle.
        """
        d = self._last_demand
        if d is None or not self.demand.enabled or not self.hp.allow_writes:
            return
        if not self.hp._config_seen:
            return          # nothing read yet; set_power would refuse anyway
        await self.hp.set_power(d.source_request, d.reason)

    async def _clear_stale_cooling_off(self) -> None:
        """Undo an OFF left written by a controller that died while stopped.

        The stop is written to the pump's FLASH, so unlike a valve command it
        survives heatctl crashing - and nothing else would ever restore it. For
        condensation that is the safe direction, but it is how a house sits
        uncooled until a human notices, which is exactly the 2026-07-31 17:03
        outage shape.

        Restart == safe state, and the safe state on a CLEAN start is normal
        control: clear the sentinel and let the capacity loop re-assert OFF
        within a cycle if the condition that caused it still holds. Runs once,
        after the first config read.
        """
        if self._off_checked or not self.hp._config_seen:
            return
        self._off_checked = True
        if self.mode != "cooling" or not self.hp.cooling_is_off():
            return
        log.warning("P04 was left at the OFF sentinel by a previous run - "
                    "restoring %.0f degC. If the stop is still warranted the "
                    "capacity loop will re-assert it within a cycle.",
                    self.default_cooling_sp)
        self.log_event("cooling_off_cleared", "stale OFF sentinel on start-up")
        await self.hp.set_cooling(self.default_cooling_sp,
                                  "clearing a stale OFF from a previous run")

    async def _trim_water_setpoint(self, state, now: float) -> None:
        """Move the heat pump's water setpoint to match the house's demand.

        Slow and integer by design (1 K / 30 min): every write wears the
        pump's flash, and the slab has hours of thermal mass, so a continuous
        controller here would be damaging and pointless alike.
        """
        if not self.water_sp.enabled or not self.hp.allow_writes:
            return
        d = self._last_demand
        reg = "setpoint_cooling" if self.mode == "cooling" else "setpoint_heating"
        addr = 0x0090 if self.mode == "cooling" else 0x0091
        if self.mode == "cooling":
            # THE LOGICAL SETPOINT, never the raw register. P04 carries either
            # the setpoint or the OFF sentinel, and the trim computes its next
            # move FROM the current value - so handing it the sentinel would
            # poison the trim, the constraint memory and the reversal guard at
            # once. See HeatPump.set_cooling.
            if self.hp.cooling_is_off():
                # Deliberately stopped. The trim has nothing to say about a
                # machine that is not running; restarting it is the capacity
                # loop's decision, not this one's.
                await self.plane.publish("water_sp/reason",
                                         "compressor commanded OFF")
                return
            current = self.hp.cooling_setpoint()
        else:
            current = self.hp.config.get(addr)
        # The MANIFOLD supply sensor, same one Safety.apply reads, and for the
        # same reason: condensation is about the water reaching the slab. It is
        # also a PT1000 at 0.1 K against the heat pump register's 0.5 K, so the
        # soft loop and the hard guard can no longer disagree about whether a
        # breach is happening. Heat pump leaving water stays as the fallback -
        # decoded through the register map, never with a hardcoded factor
        # (see heatpump_map.py on the 0.5-for-both bug).
        supply = state.temps.get("vl_total")
        if supply is None or "vl_total" in state.faults:
            lw = hpm.by_name("leaving_water")
            raw = self.hp.status.get(lw.addr)
            supply = None if raw is None else hpm.decode(lw, raw)
        dp = self.plane.dew_point(self.safety.dew_max_age)
        # Above `return water - restart differential` the unit will not start,
        # because P01 (0x008D) is pinned at its 2 K minimum. Passed in so the
        # predictive condensation floor can never push the setpoint into the
        # range where the machine simply idles - see _clamp for the measured
        # loop this broke three times on 2026-07-30.
        rw = hpm.by_name("return_water")
        rw_raw = self.hp.status.get(rw.addr)
        rd = self.hp.config.get(hpm.by_name("restart_diff_c").addr)
        ceiling = (None if rw_raw is None or rd is None
                   else hpm.decode(rw, rw_raw) - float(rd))

        decision = self.water_sp.step(
            mode=self.mode,
            deviation=None if d is None else d.mean_deviation_c,
            max_open=self._peak_demand,
            current=None if current is None else float(current),
            dew_point=dp,
            supply_temp=supply,
            running_ceiling=ceiling,
            supply_limit=(self.safety.cooling_supply_limit()
                          if self.mode == "cooling" else None),
            now=now)
        await self.plane.publish("water_sp/reason", decision.reason)
        # Setpoint-saturation alarm. Logged on the EDGE only: the blocked state
        # is re-evaluated every cycle and persists for hours, so logging it
        # each time would bury everything else - but never logging it at all
        # would make "the plant cannot meet demand" the quietest state in the
        # system, which is how the 2026-07-29 limit cycle went unnoticed for a
        # full afternoon.
        if decision.demand_unmet != self._sp_blocked:
            self._sp_blocked = decision.demand_unmet
            if decision.demand_unmet:
                log.warning("water setpoint SATURATED: %s", decision.reason)
                self.log_event("water_setpoint_blocked", decision.reason)
            else:
                log.info("water setpoint no longer saturated")
                self.log_event("water_setpoint_unblocked", decision.reason)
        await self.plane.publish("water_sp/blocked",
                                 "1" if decision.demand_unmet else "0")
        if decision.target is None:
            return
        log.info("water setpoint %s: %s -> %.0f degC (%s)",
                 reg, current, decision.target, decision.reason)
        self.log_event("water_setpoint",
                       f"{reg} {current} -> {decision.target:.0f}: {decision.reason}")
        if self.mode == "cooling":
            await self.hp.set_cooling(decision.target, decision.reason)
        else:
            await self.hp.write_named(reg, decision.target, decision.reason)

    def _max_owned_opening(self) -> float | None:
        """Highest commanded opening across circuits that can actually throttle.

        Unactuated circuits are excluded: they are open pipe, so including
        them would peg this at 100 % and permanently read as "saturated".
        """
        vals = [p for n, p in self.io.state.valves_pct.items()
                if n in self.owned_valves and n not in self.rl_gate.unactuated]
        return max(vals) if vals else None

    async def _sync_pump_mode(self) -> None:
        """Keep the pump's mode register aligned with the plant mode.

        Divergence is not cosmetic. heatctl's mode decides which way the valve
        PIDs run; the pump's decides what temperature the water is. Diverged,
        the valve loop drives the wrong direction with the wrong water - and
        the condensation guard is scoped to the plant's cooling mode, so it
        would be switched off exactly while chilled water circulated.
        """
        disagree = self.hp.mode_disagrees(self.mode)
        if disagree is None:
            self._mode_warned = None
        elif disagree != self._mode_warned:
            log.warning("heat pump is in %s mode but the plant is %s - "
                        "correcting", disagree, self.mode)
            self._mode_warned = disagree
        if self.hp.allow_writes:
            await self.hp.sync_mode(self.mode)
        await self.plane.publish("hp/mode_agrees", "0" if disagree else "1")

    def _log_overrides(self, overrides: dict[str, list[str]], now: float) -> None:
        """Make safety overrides visible in the log. They were not, at all.

        WHY THIS EXISTS. `Safety.apply` returns a reason, `step()` published it
        to `override/<valve>`, and nothing ever logged it. Worse, the publish is
        conditional on there BEING a reason, so an override that ends leaves the
        last value sitting on the topic - and no HA entity was discovered for it
        either. The single most consequential thing heatctl does - forcing a
        circuit shut because supply reached the dew point - was invisible in the
        log AND unobservable in Home Assistant.

        That cost a real diagnosis on 2026-08-01: the plant tripped Er03 for the
        third time that day, the likely chain being dew-point trip -> valves shut
        -> flow collapse -> flow interlock, and it could not be confirmed or
        refuted because the first link left no trace.

        Aggregated BY REASON, not per valve: one dew-point trip across ten
        circuits is one fact. Throttled to a transition plus one line a minute,
        for the reason `failsafe()` documents - a persistent, fully predictable
        condition must not flush the log ring that holds its own cause.
        """
        for reason, valves in sorted(overrides.items()):
            if reason not in self._override_since:
                self._override_since[reason] = now
                self._override_logged[reason] = now
                log.warning("SAFETY OVERRIDE %s on %d circuit(s): %s", reason,
                            len(valves), ", ".join(sorted(valves)))
            elif now - self._override_logged.get(reason, 0.0) > 60:
                self._override_logged[reason] = now
                log.warning("SAFETY OVERRIDE %s (still, since %.0f s) on "
                            "%d circuit(s)", reason,
                            now - self._override_since[reason], len(valves))
        for reason in [r for r in self._override_since if r not in overrides]:
            log.info("safety override %s cleared (was active for %.0f s)",
                     reason, now - self._override_since.pop(reason))
            self._override_logged.pop(reason, None)

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
        # Only the circuits we control. Driving unassigned outputs open
        # achieves nothing and strands them there.
        await self.io.write_all_valves(self.safety.failsafe_pct,
                                       self.owned_valves)
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
                # None when no dew point is known - publish it as such rather
                # than inventing a number, which is the whole point of removing
                # the static fallback.
                (f"{lim:.1f}" if (lim := self.safety.cooling_supply_limit())
                 is not None else "unknown"))
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
        for n, pct in state.valves_readback_pct.items():
            await self.plane.publish(f"valve_actual/{n}", f"{pct:.0f}")
        for n in state.valve_mismatch:
            await self.plane.publish(
                f"valve_mismatch/{n}", f"{state.valves_readback_pct[n]:.0f}")

        # The signals the evaluation in docs/DESIGN.md 4.5 is built on.
        # Leaving/return spread: the efficiency indicator. Maximising flow
        # minimises it, which is the whole point of the distribution design.
        # Decoded through the register map, NEVER with a hardcoded factor:
        # return water is scaled 0.1 and leaving water 0.5, four registers
        # apart. A first version of this used 0.5 for both and published 84 K
        # when the true spread was 0 - a plausible-looking number, which is
        # exactly the failure heatpump_map.py warns about.
        lw_reg = hpm.by_name("leaving_water")
        rw_reg = hpm.by_name("return_water")
        lw, rw = self.hp.status.get(lw_reg.addr), self.hp.status.get(rw_reg.addr)
        if lw is not None and rw is not None:
            spread = hpm.decode(rw_reg, rw) - hpm.decode(lw_reg, lw)
            await self.plane.publish("hp/spread", f"{spread:.1f}")
            # Feed the water-setpoint floor. ONLY while the compressor runs:
            # with it off the spread collapses to ~0, and an idle machine's
            # zero would erase the floor exactly when the next start is about
            # to produce a real one.
            freq = self.hp.status.get(hpm.by_name("compressor_freq").addr)
            # THE FLOOR NEEDS return -> MANIFOLD SUPPLY, not return -> leaving
            # water. The setpoint targets RETURN water and the condensation
            # guard measures the MANIFOLD supply, so the quantity that predicts
            # "how far below the setpoint will the guarded temperature sit" is
            # the drop between exactly those two points.
            #
            # Measured 2026-07-30: the manifold runs 0.8-1.1 K WARMER than the
            # heat pump's leaving water (pickup or mixing in the run between
            # them), while the two return sensors agree to 0.1 K. Feeding the
            # machine-side spread therefore over-predicted the drop by ~0.9 K
            # and cost a whole setpoint step of usable range.
            #
            # Measured end-to-end, so no model of pipe gain or mixing is needed
            # - and it uses the manifold PT1000 at 0.1 K rather than the heat
            # pump register at 0.5 K.
            eff = None
            vl_manifold = state.temps.get("vl_total")
            if vl_manifold is not None and "vl_total" not in state.faults:
                eff = hpm.decode(rw_reg, rw) - vl_manifold
                await self.plane.publish("hp/spread_effective", f"{eff:.2f}")
            self.water_sp.observe_spread(
                (eff if eff is not None else spread) if freq else None)
            est = self.water_sp.spread_estimate
            if est is not None:
                await self.plane.publish("water_sp/spread_est", f"{est:.2f}")
        amps = self.hp.status.get(0x8025)
        if amps is not None:
            # CALIBRATED against the utility meter over 129 days of winter data
            # (D-027). 0x8025 is AC MAINS current - proven, not assumed: the
            # grid meter's phase-A RMS current tracks it 0.92 A per reported A,
            # and the DC-link hypothesis is dead because V_bus x I would give
            # 3366 W where 2011 W was measured.
            #
            #   P_el = 198 * I + 200 W        R2 = 0.994 over 0-12 A
            #
            # The 200 W is fan + circulation pump + electronics and switches
            # with UNIT POWER, not with the compressor - event-based fits
            # return an intercept near zero precisely because those are already
            # running when the compressor starts. So it is added whenever the
            # unit is on, which is when this code runs.
            #
            # The old estimate was `I * 230`: 16 % too steep on slope, but
            # omitting the overhead partly cancelled it. Net error was only
            # +2..4 % at the 9-10 A where the machine lives, and 14 % LOW at
            # 3 A - a SHAPE error, worst at part load, which is exactly where a
            # future optimizer needs it to be right.
            i_a = hpm.decode(hpm.by_name("compressor_current"), amps)
            # MEASURED 2026-08-02: P = 2.0 * f * I. NOT a watts-per-amp constant.
            #
            # This published `198*I + 200` (D-027), which was wrong in both
            # terms - that regression ran against a utility-meter phase also
            # carrying household load, which depresses a slope and parks the
            # residual in an intercept.
            #
            # Replacing it with a measured 147 W/A was still wrong, in a more
            # interesting way. Binning the grid meter's ACTIVE POWER by
            # compressor frequency shows watts-per-amp is not constant at all:
            #
            #   freq band   W/A     W/(A*Hz)
            #    5-35       38.2      1.91
            #   35-50       92.2      2.17
            #   50-65      132.7      2.31
            #   65-80      146.5      2.02
            #   80-120     174.6      1.75
            #
            # W/A varies 4.6x across the range; dividing by frequency collapses
            # that to +-15 %. THE REGISTER IS ON THE INVERTER OUTPUT, not the
            # mains: motor voltage scales with frequency under V/f control, so
            # mains power goes as f*I. The "0.639 mains-amps per reported amp"
            # is not a scaling factor, it is simply the value that holds at the
            # ~70 Hz the plant usually sits at.
            #
            # A per-sample regression is impossible here and that is not a
            # tooling problem: household load on the same phase varies by ~760 W
            # sample to sample, so R2 tops out at 0.33 with ~900 W RMSE.
            # Averaging within frequency bins is what makes the signal visible.
            #
            # Fan and pump are NOT in this number - the register cannot see
            # them. It is COMPRESSOR power and named so, and a faulted plant
            # reports 0 W rather than the fictitious 200 W it showed for the
            # 14 hours Er03 was latched on 2026-08-01/02.
            hz = self.hp.status.get(hpm.by_name("compressor_freq").addr)
            hz_f = 0.0 if hz is None else float(
                hpm.decode(hpm.by_name("compressor_freq"), hz))
            await self.plane.publish("hp/power_estimate",
                                     f"{2.0 * hz_f * i_a:.0f}")
        if self._peak_demand is not None:
            # PRE-normalisation peak. The commanded maximum is pinned at 100 %
            # by construction, so only this says whether there is enough
            # capacity - it is the signal the water setpoint loop uses.
            await self.plane.publish("demand/peak", f"{self._peak_demand:.0f}")

        d = self._last_demand
        if d is not None:
            await self.plane.publish("demand/source_request",
                                     "1" if d.source_request else "0")
            await self.plane.publish("demand/reason", d.reason)
            await self.plane.publish("demand/mode", d.mode)
            if d.mean_deviation_c is not None:
                await self.plane.publish("demand/deviation",
                                         f"{d.mean_deviation_c:+.2f}")
            if d.open_pct is not None:
                await self.plane.publish("demand/open_pct", f"{d.open_pct:.0f}")

    # ---------- history for system identification (layer 2) ----------
    def _open_db(self, path: str) -> sqlite3.Connection:
        """History for system identification (docs/DESIGN.md 7).

        Two tables, because two different questions get asked of this data
        later. `samples` is the long/narrow time series you fit models
        against. `events` is the discrete record - mode changes, writes to the
        heat pump, faults appearing and clearing, failsafe entries and exits -
        which is what you actually need when reconstructing *why* the plant
        did something months afterwards. A time series alone never answers
        that, and by then nobody remembers.
        """
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE IF NOT EXISTS samples("
                   "ts REAL, name TEXT, value REAL)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON samples(ts)")
        db.execute("CREATE TABLE IF NOT EXISTS events("
                   "ts REAL, kind TEXT, detail TEXT)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ev_ts ON events(ts)")
        return db

    def _prune_db(self) -> None:
        """Drop samples older than the retention window.

        Without this the file grows without bound on an appliance nobody
        watches - roughly a GB a year at this width. Events are kept much
        longer than samples: they are tiny and they are what answers "why did
        it do that" long after the raw series has rolled off.
        """
        days = self.cfg["logging"].get("retention_days", 0)
        if not days:
            return
        cutoff = time.time() - days * 86400
        try:
            with self.db:
                self.db.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
                self.db.execute("DELETE FROM events WHERE ts < ?",
                                (time.time() - days * 10 * 86400,))
        except Exception:
            log.exception("history pruning failed")

    def log_event(self, kind: str, detail: str) -> None:
        """Record a discrete happening. Cheap, and never in the hot path."""
        try:
            with self.db:
                self.db.execute("INSERT INTO events VALUES (?,?,?)",
                                (time.time(), kind, detail))
        except Exception:
            log.exception("event logging failed: %s %s", kind, detail)

    def _log_db(self, state) -> None:
        """Sample everything that moves, once per `log_every_n_cycles`.

        Deliberately wide: the point is that every system parameter should be
        improvable later from this file alone, and a series nobody recorded
        cannot be recovered retrospectively. Config registers are NOT sampled
        here - they change rarely and are captured as events instead, which
        keeps the row count proportional to what actually moves.

        Note the `settled:` series. Data taken while an actuator is still
        travelling is poison for identification (docs/DESIGN.md 4.1.4): flow
        is unknown, so return temperature means nothing. Recording the flag
        alongside lets a later fit exclude those samples instead of silently
        averaging them in.
        """
        if self._cycle % self.cfg["logging"]["log_every_n_cycles"]:
            return
        ts = time.time()
        now = time.monotonic()
        rows = [(ts, n, t) for n, t in state.temps.items()]
        rows += [(ts, f"valve:{n}", p) for n, p in state.valves_pct.items()]
        # Commanded vs actual: they diverge when something other than heatctl
        # moved the outputs, and the difference is only visible if both are
        # kept.
        rows += [(ts, f"valve_actual:{n}", p)
                 for n, p in state.valves_readback_pct.items()]
        for room in self.rooms:
            t = self.plane.room_temp(room["name"])
            if t is not None:
                rows.append((ts, f"room:{room['name']}", t))
            rows.append((ts, f"setpoint:{room['name']}",
                         self.room_setpoints[room["name"]]))
        for valve in self.owned_valves:
            c = self.rl_gate._circuit(valve)
            settled = (c.open_since is not None
                       and now - c.open_since >= self.rl_gate.settle_s)
            rows.append((ts, f"settled:{valve}", 1.0 if settled else 0.0))

        rows.append((ts, "mode", {"heating": 1, "cooling": 2}.get(self.mode, 0)))
        rows.append((ts, "return_sp", self._last_return_sp))
        dp = self.plane.dew_point(self.safety.dew_max_age)
        # Above `return water - restart differential` the unit will not start,
        # because P01 (0x008D) is pinned at its 2 K minimum. Passed in so the
        # predictive condensation floor can never push the setpoint into the
        # range where the machine simply idles - see _clamp for the measured
        # loop this broke three times on 2026-07-30.
        rw = hpm.by_name("return_water")
        rw_raw = self.hp.status.get(rw.addr)
        rd = self.hp.config.get(hpm.by_name("restart_diff_c").addr)
        ceiling = (None if rw_raw is None or rd is None
                   else hpm.decode(rw, rw_raw) - float(rd))
        if dp is not None:
            rows.append((ts, "dew_point", dp))
        if self.mode == "cooling":
            rows.append((ts, "cooling_supply_limit",
                         self.safety.cooling_supply_limit()))
        d = self._last_demand
        if d is not None:
            rows.append((ts, "demand:source_request",
                         1.0 if d.source_request else 0.0))
            if d.mean_deviation_c is not None:
                rows.append((ts, "demand:deviation", d.mean_deviation_c))
            if d.open_pct is not None:
                rows.append((ts, "demand:open_pct", d.open_pct))
        # The heat pump: every decoded status value, plus its commanded state.
        # This is the other half of any thermal model - without compressor
        # frequency, current and water temperatures there is no way to
        # attribute a slab response to an input.
        for reg in (*hpm.STATUS, *hpm.WRITABLE):
            raw = self.hp.status.get(reg.addr, self.hp.config.get(reg.addr))
            if raw is not None:
                rows.append((ts, f"hp:{reg.name}", hpm.decode(reg, raw)))
        for (addr, bit), name in {**hpm.OUTPUT_BITS, **hpm.CONTROL_BITS,
                                  **hpm.MODE_STATUS_BITS}.items():
            raw = self.hp.status.get(addr, self.hp.config.get(addr))
            if raw is not None:
                rows.append((ts, f"hp:{name}", float(raw >> bit & 1)))
        with self.db:
            self.db.executemany("INSERT INTO samples VALUES (?,?,?)", rows)
        # Once an hour is plenty; DELETE is cheap against the ts index.
        if self._cycle % 3600 == 0:
            self._prune_db()


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
