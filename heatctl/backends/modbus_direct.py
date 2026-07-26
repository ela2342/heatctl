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
        self.client: AsyncModbusTcpClient | None = None
        # current backoff and the earliest monotonic time we may retry
        self._backoff = self.reconnect_delay
        self._next_attempt = 0.0
        self._ever_connected = False   # only to distinguish the log messages

        self.sensor_base = cfg["sensors"]["base_register"]
        self.sensor_channels = cfg["sensors"]["channels"]
        self.sensors = [c for c in self.sensor_channels if c.get("enabled", True)]

        self.valve_base = cfg["valves"]["base_register"]
        self.valves = {c["name"]: c for c in cfg["valves"]["channels"]}

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

    async def read_state(self) -> IOState:
        # Returns the previous state untouched on any failure: last_read_ts is
        # deliberately NOT refreshed, so is_stale() stays honest (see module
        # docstring). Faults are only recomputed on a successful read.
        if not await self._ensure_connected():
            return self.state
        assert self.client is not None
        try:
            rr = await self.client.read_input_registers(
                self.sensor_base, count=len(self.sensor_channels))
        except Exception as e:
            log.warning("modbus read failed: %s", e)
            return self.state
        if rr.isError():
            log.warning("modbus read error: %s", rr)
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
        for name in self.valves:
            try:
                await self.write_valve(name, pct)
            except Exception:
                log.exception("failsafe write failed: %s", name)
