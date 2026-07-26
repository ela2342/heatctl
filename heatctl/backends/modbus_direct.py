"""Direct Modbus TCP backend for the WAGO 750-352 node.

Process image of this specific node (see docs/HARDWARE.md):
  input registers   0-11 : 750-652 RS485 (unused)
  input registers  12-27 : 4x 750-463, 16x PT1000, degC*10, two's complement
  holding registers 12-19: 2x 750-559, 0-10 V as 0..32767
  coils 0-3              : 2x 750-517 relays

This backend is the fallback / insurance path and the designated transport
for future fast loops (DHW station), which must not run through a bridge.
"""
from __future__ import annotations

import logging
import time

from pymodbus.client import AsyncModbusTcpClient

from .base import IOBackend, IOState, decode_pt1000

log = logging.getLogger("heatctl.io.modbus")

RAW_FULLSCALE = 32767  # 750-559: 32767 = 10 V


class ModbusDirectBackend(IOBackend):
    def __init__(self, cfg: dict):
        m = cfg["io"]["modbus"]
        self.host, self.port = m["host"], m["port"]
        self.timeout = m.get("timeout_s", 2.0)
        self.client: AsyncModbusTcpClient | None = None

        self.sensor_base = cfg["sensors"]["base_register"]
        self.sensor_channels = cfg["sensors"]["channels"]
        self.sensors = [c for c in self.sensor_channels if c.get("enabled", True)]

        self.valve_base = cfg["valves"]["base_register"]
        self.valves = {c["name"]: c for c in cfg["valves"]["channels"]}

        self.fault_raw = set(cfg["safety"]["sensor_fault_raw"])
        self.state = IOState()

    async def start(self) -> None:
        self.client = AsyncModbusTcpClient(self.host, port=self.port,
                                           timeout=self.timeout)
        await self.client.connect()
        log.info("modbus connected: %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self.client:
            self.client.close()

    async def read_state(self) -> IOState:
        assert self.client is not None
        rr = await self.client.read_input_registers(
            self.sensor_base, count=len(self.sensor_channels))
        if rr.isError():
            raise IOError(f"modbus read failed: {rr}")
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
        assert self.client is not None
        pct = max(0.0, min(100.0, pct))
        ch = self.valves[name]
        raw = int(pct / 100.0 * RAW_FULLSCALE)
        wr = await self.client.write_register(
            self.valve_base + ch["index"] - 1, raw)
        if wr.isError():
            raise IOError(f"modbus write failed for {name}: {wr}")
        self.state.valves_pct[name] = pct

    async def write_all_valves(self, pct: float) -> None:
        for name in self.valves:
            try:
                await self.write_valve(name, pct)
            except Exception:
                log.exception("failsafe write failed: %s", name)
