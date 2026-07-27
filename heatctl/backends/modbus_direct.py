"""Direct Modbus TCP backend for the WAGO 750-352 node.

Process image of this specific node (see docs/HARDWARE.md):
  input registers   0-11 : 750-652 RS485 (unused)
  input registers  12-27 : 4x 750-463, 16x PT1000, degC*10, two's complement
  holding registers 12-19: 2x 750-559, 0-10 V as 0..32767
  coils 0-3              : 2x 750-517 relays

This is the PRIMARY backend (see docs/MODBUS2MQTT.md for why the mqtt bridge
path was abandoned) and the designated transport for future fast loops
(DHW station), which must not run through a bridge.

Availability rules (deliberate, do not "simplify" away):
  - start() never raises. If the coupler is unreachable at boot, the control
    loop must still come up: safety (frost protection!) has to run, and the
    stale-data failsafe is the correct behaviour meanwhile. Refusing to
    start would leave the house with no controller at all after a transient.
  - read_state() never raises either. On any failure it returns the previous
    IOState *without* touching last_read_ts, so IOState.is_stale() reports
    honestly and Controller.step takes the "stale_data" failsafe path. That
    is semantically distinct from an unexpected bug, which surfaces as
    "cycle_error" - keep them distinguishable.
  - Reconnection is rate-limited with exponential backoff and every attempt
    is bounded by `timeout_s`, because this runs inside the 1 s control loop:
    a blocking reconnect would stall safety supervision.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from pymodbus.client import AsyncModbusTcpClient

from .base import IOBackend, IOState, decode_pt1000

log = logging.getLogger("heatctl.io.modbus")

RAW_FULLSCALE = 32767  # 750-559: 32767 = 10 V

# The coupler overlays the input and output process images in the same low
# address range, so FC3 at the address you wrote returns the INPUT image
# (temperatures), not your outputs. The output image is mirrored for reading
# at 0x0200 + word offset - verified on hardware, see docs/HARDWARE.md.
OUTPUT_MIRROR = 0x0200

# Coupler Modbus watchdog registers. Authoritative source: 750-352 Handbuch
# v1.2.0 sections 9.6 / 11.2.5 - see docs/HARDWARE.md, which also records which
# of these were previously mislabelled here.
WD_TIME = 0x1000        # R/W, time in units of 100 ms; writable only while stopped
WD_MASK_1_16 = 0x1001   # R/W, coding mask FC1..16; writing non-zero ARMS it
WD_TRIGGER = 0x1003     # R/W, toggle register; non-zero clears an error and starts it
WD_STATUS = 0x1006      # R,   0 = inactive, 1 = active, 2 = expired
WD_STATUS_INACTIVE, WD_STATUS_ACTIVE, WD_STATUS_EXPIRED = 0, 1, 2


class ModbusDirectBackend(IOBackend):
    def __init__(self, cfg: dict):
        m = cfg["io"]["modbus"]
        # Environment wins over the file for site-specific values, so the
        # committed config.yaml can carry a placeholder address. See README.
        self.host = os.environ.get("HEATCTL_MODBUS_HOST") or m["host"]
        self.port = int(os.environ.get("HEATCTL_MODBUS_PORT") or m["port"])
        self.timeout = m.get("timeout_s", 2.0)
        self.reconnect_delay = m.get("reconnect_delay_s", 1.0)
        self.reconnect_delay_max = m.get("reconnect_delay_max_s", 30.0)

        self.wd_enabled = bool(m.get("watchdog_enabled", False))
        # register unit is 100 ms
        self.wd_time_units = int(round(float(m.get("watchdog_timeout_s", 10.0)) * 10))
        self.wd_mask = int(m.get("watchdog_mask", 0x8020))
        self._wd_armed_logged = False
        self.client: AsyncModbusTcpClient | None = None
        # current backoff and the earliest monotonic time we may retry
        self._backoff = self.reconnect_delay
        self._next_attempt = 0.0
        self._ever_connected = False   # only to distinguish the log messages

        self.sensor_base = cfg["sensors"]["base_register"]
        self.sensor_channels = cfg["sensors"]["channels"]
        self.sensors = [c for c in self.sensor_channels if c.get("enabled", True)]
        # Read as far as the highest channel INDEX, not as many registers as
        # there are channel entries. Those differ the moment config.yaml lists
        # a subset - e.g. only the channels that are wired - and indexing a
        # short reply by channel index then raises IndexError, which surfaces
        # as a per-cycle "cycle_error" crash rather than any sane degradation.
        # config.yaml is hand-edited hardware truth; it must not be able to
        # crash the loop by being terse.
        self.sensor_count = max(c["index"] for c in self.sensor_channels)

        self.valve_base = cfg["valves"]["base_register"]
        self.valves = {c["name"]: c for c in cfg["valves"]["channels"]}
        self.valve_count = max(c["index"] for c in cfg["valves"]["channels"])
        self.readback = bool(m.get("valve_readback", True))
        self.readback_tol = float(m.get("valve_readback_tolerance_pct", 2.0))
        self._readback_warned = 0.0

        self.fault_raw = set(cfg["safety"]["sensor_fault_raw"])
        self.state = IOState()

    async def start(self) -> None:
        # pymodbus does its own transport-level reconnection; we still keep an
        # explicit guard below so recovery does not depend on library internals.
        self.client = AsyncModbusTcpClient(
            self.host, port=self.port, timeout=self.timeout,
            reconnect_delay=self.reconnect_delay,
            reconnect_delay_max=self.reconnect_delay_max)
        if not await self._ensure_connected():
            log.warning("modbus unreachable at startup (%s:%s) - continuing "
                        "with failsafe armed, retrying in background",
                        self.host, self.port)

    async def stop(self) -> None:
        if self.client:
            self.client.close()

    async def _ensure_connected(self) -> bool:
        """True if usable. Never raises, never blocks longer than timeout_s."""
        c = self.client
        if c is None:
            return False
        if c.connected:
            self._backoff = self.reconnect_delay
            return True
        now = time.monotonic()
        if now < self._next_attempt:
            return False          # still backing off; caller reports staleness
        # arm the next slot before attempting, so a hanging attempt still backs off
        self._next_attempt = now + self._backoff
        try:
            await asyncio.wait_for(c.connect(), timeout=self.timeout)
        except Exception as e:
            # Never propagate: unreachable hardware is a normal condition here.
            # asyncio.CancelledError derives from BaseException, so a real
            # shutdown still cancels us cleanly.
            log.debug("modbus connect attempt failed: %s", e)
        if c.connected:
            log.info("modbus %s: %s:%s",
                     "reconnected" if self._ever_connected else "connected",
                     self.host, self.port)
            self._ever_connected = True
            self._backoff = self.reconnect_delay
            return True
        self._backoff = min(self._backoff * 2.0, self.reconnect_delay_max)
        log.warning("modbus %s:%s unreachable, next attempt in %.0f s",
                    self.host, self.port, self._backoff)
        return False

    async def _reg_read(self, addr: int) -> int | None:
        """Single holding register, None on any failure. Never raises."""
        assert self.client is not None
        try:
            rr = await self.client.read_holding_registers(addr, count=1)
        except Exception as e:
            log.debug("register read 0x%04X failed: %s", addr, e)
            return None
        return None if rr.isError() else rr.registers[0]

    async def _reg_write(self, addr: int, value: int) -> bool:
        """Single holding register, False on any failure. Never raises."""
        assert self.client is not None
        try:
            wr = await self.client.write_register(addr, value)
        except Exception as e:
            log.debug("register write 0x%04X failed: %s", addr, e)
            return False
        return not wr.isError()

    async def _watchdog_kick_after_error(self) -> None:
        """Clear a possible watchdog trip. Safe to call on any I/O failure.

        0x1003 is a TOGGLE register: it is the *change* of value that clears a
        pending watchdog error and restarts the watchdog. Writing the value it
        already holds is rejected with exception 0x03 (illegal data value) and
        clears nothing.

        This is not a detail. An earlier version wrote a constant 1, which
        recovered exactly once - the first trip, when the register still held
        its power-on 0 - and then never again, because the register stayed at
        1. Field failure 2026-07-27: the coupler tripped overnight and stayed
        blocked for ~3.5 h, every read and write answered with exception 0x04,
        heatctl looping on the stale-data failsafe with no way back short of
        manual intervention. Read the current value and write the other one.
        """
        if not self.wd_enabled:
            return
        cur = await self._reg_read(WD_TRIGGER)
        # If the read failed we cannot know the current value, so try both:
        # one of them is guaranteed to be a change.
        candidates = [1 - cur] if cur in (0, 1) else [1, 0]
        for v in candidates:
            if await self._reg_write(WD_TRIGGER, v):
                log.warning("coupler watchdog trigger toggled %s -> %d after "
                            "I/O failure (clears a trip; outputs were zeroed "
                            "if it had expired)", cur, v)
                return
        log.error("coupler watchdog trigger write FAILED (was %s) - if the "
                  "watchdog has expired, control cannot recover by itself",
                  cur)

    async def _watchdog_maintain(self) -> None:
        """Arm the watchdog if it is not running. Called after a good read.

        Type "Standard" with a write-only coding mask (FC6 + FC16), so ONLY
        output writes retrigger it. That is the whole point: a satisfied
        watchdog then means "outputs are genuinely being driven", not merely
        "something is polling". heatctl's per-cycle valve write is therefore the
        heartbeat and no separate kick is needed.

        On time-out the coupler zeroes the physical outputs, which with NC
        actuators closes the valves. That is deliberate and is the right
        direction for a DEAD controller - see the failure-policy docstring in
        safety.py for why it does not contradict fail-open.
        """
        if not self.wd_enabled:
            return
        st = await self._reg_read(WD_STATUS)
        if st is None:
            return
        if st == WD_STATUS_EXPIRED:
            await self._watchdog_kick_after_error()
            return
        if st == WD_STATUS_ACTIVE:
            if not self._wd_armed_logged:
                log.info("coupler watchdog active (%.1f s, mask 0x%04X)",
                         self.wd_time_units / 10, self.wd_mask)
                self._wd_armed_logged = True
            return
        # Inactive: set the time first - 0x1000 is writable only while stopped -
        # then arm by writing a non-zero coding mask.
        await self._reg_write(WD_TIME, self.wd_time_units)
        if await self._reg_write(WD_MASK_1_16, self.wd_mask):
            log.info("coupler watchdog armed: %.1f s, mask 0x%04X (FC6+FC16)",
                     self.wd_time_units / 10, self.wd_mask)
            self._wd_armed_logged = True

    async def _read_back_valves(self) -> None:
        """Compare the coupler's actual outputs against what we commanded.

        heatctl otherwise treats `valves_pct` as truth, but it is only the
        last *command*. The gap matters: when the Modbus watchdog expires the
        coupler forces its outputs to zero, and nothing in the command path
        ever learns that happened. The per-cycle write does heal it within a
        second, so this is about observability, not correction - a silent
        self-healing failure is exactly the kind that goes unnoticed until it
        stops being transient.

        Failure here is not an error: a coupler without the mirror, or a
        different node layout, should cost one log line and then stop trying,
        never a per-cycle warning or a failed read_state.
        """
        if not self.readback:
            return
        assert self.client is not None
        try:
            rr = await self.client.read_holding_registers(
                OUTPUT_MIRROR + self.valve_base, count=self.valve_count)
        except Exception as e:
            log.info("valve read-back unavailable (%s), disabling it", e)
            self.readback = False
            return
        if rr.isError():
            log.info("valve read-back unavailable (%s), disabling it", rr)
            self.readback = False
            return

        self.state.valves_readback_pct.clear()
        self.state.valve_mismatch.clear()
        for name, ch in self.valves.items():
            pct = rr.registers[ch["index"] - 1] / RAW_FULLSCALE * 100.0
            self.state.valves_readback_pct[name] = pct
            cmd = self.state.valves_pct.get(name)
            if cmd is not None and abs(cmd - pct) > self.readback_tol:
                self.state.valve_mismatch.add(name)

        if self.state.valve_mismatch:
            now = time.monotonic()
            if now - self._readback_warned > 60:
                self._readback_warned = now
                detail = ", ".join(
                    f"{n} commanded {self.state.valves_pct[n]:.0f}% "
                    f"reads {self.state.valves_readback_pct[n]:.0f}%"
                    for n in sorted(self.state.valve_mismatch))
                log.warning("valve output mismatch (something other than "
                            "heatctl moved these - watchdog safe state?): %s",
                            detail)

    async def read_state(self) -> IOState:
        # Returns the previous state untouched on any failure: last_read_ts is
        # deliberately NOT refreshed, so is_stale() stays honest (see module
        # docstring). Faults are only recomputed on a successful read.
        if not await self._ensure_connected():
            return self.state
        assert self.client is not None
        try:
            rr = await self.client.read_input_registers(
                self.sensor_base, count=self.sensor_count)
        except Exception as e:
            log.warning("modbus read failed: %s", e)
            await self._watchdog_kick_after_error()
            return self.state
        if rr.isError():
            log.warning("modbus read error: %s", rr)
            await self._watchdog_kick_after_error()
            return self.state
        regs = rr.registers
        self.state.faults.clear()
        for ch in self.sensors:
            raw = regs[ch["index"] - 1]
            self.state.temps_raw[ch["name"]] = raw
            if raw in self.fault_raw:
                self.state.faults.add(ch["name"])
                self.state.temps.pop(ch["name"], None)
            else:
                self.state.temps[ch["name"]] = decode_pt1000(raw)
        self.state.last_read_ts = time.monotonic()
        await self._watchdog_maintain()
        await self._read_back_valves()
        return self.state

    async def write_valve(self, name: str, pct: float) -> None:
        # Unlike read_state this DOES raise: the IOBackend contract requires a
        # definite write failure to be visible so the caller can failsafe.
        if not await self._ensure_connected():
            raise IOError(f"modbus not connected, cannot write {name}")
        assert self.client is not None
        pct = max(0.0, min(100.0, pct))
        ch = self.valves[name]
        raw = int(pct / 100.0 * RAW_FULLSCALE)
        try:
            wr = await self.client.write_register(
                self.valve_base + ch["index"] - 1, raw)
        except Exception as e:
            raise IOError(f"modbus write failed for {name}: {e}") from e
        if wr.isError():
            raise IOError(f"modbus write failed for {name}: {wr}")
        self.state.valves_pct[name] = pct

    async def write_all_valves(self, pct: float) -> None:
        """Failsafe write to every valve. Never raises - best effort by design.

        Failures are summarised into ONE line, without a traceback. This runs
        once per second, so per-valve `log.exception` produced eight stack
        traces a second while the bus was down: on 2026-07-27 that flushed 3.5
        hours of history out of the container's log ring and destroyed the
        evidence of what had started the incident. A repeating, fully
        predictable failure must cost one line, not eight tracebacks.
        """
        failed: list[str] = []
        first = ""
        for name in self.valves:
            try:
                await self.write_valve(name, pct)
            except Exception as e:
                failed.append(name)
                first = first or str(e)
        if failed:
            log.warning("failsafe write to %.0f%% failed for %d/%d valves "
                        "(%s): %s", pct, len(failed), len(self.valves),
                        ",".join(failed), first)
