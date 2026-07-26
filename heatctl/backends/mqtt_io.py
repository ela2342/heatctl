"""MQTT backend: WAGO I/O via a Modbus-to-MQTT bridge (e.g. modbus2mqtt).

The bridge polls the coupler and publishes raw register values; valve writes
are published to command topics the bridge translates into register writes.

Design notes / hard requirements for this transport:
  - Per-sensor staleness tracking: a topic that stops updating marks that
    sensor as failed after `stale_after_s`. Never serve old data silently.
  - The WAGO coupler's own Modbus watchdog MUST be enabled (see
    docs/HARDWARE.md) so outputs fall back to a safe state if the bridge
    dies mid-operation. That watchdog is the only failsafe layer that
    survives a bridge crash.
  - All bridge-specific topic knowledge lives in this file only, so the
    bridge can be replaced without touching anything else.
"""
from __future__ import annotations

import asyncio
import logging
import time

import aiomqtt

from .base import IOBackend, IOState, decode_pt1000

log = logging.getLogger("heatctl.io.mqtt")


class MqttIOBackend(IOBackend):
    def __init__(self, cfg: dict):
        io = cfg["io"]["mqtt_io"]
        m = cfg["mqtt"]
        self.host, self.port = m["host"], m["port"]
        self.user = m.get("username") or None
        self.pw = m.get("password") or None

        self.temp_topic_tpl = io["temp_topic"]
        self.valve_topic_tpl = io["valve_topic"]
        self.raw_scale = io.get("raw_scale", 32767)
        self.stale_after = io.get("stale_after_s", 10)

        self.sensors = [c for c in cfg["sensors"]["channels"]
                        if c.get("enabled", True)]
        self.valve_names = [c["name"] for c in cfg["valves"]["channels"]]
        self.fault_raw = set(cfg["safety"]["sensor_fault_raw"])

        # topic -> sensor name reverse map
        self._topic2sensor = {
            self.temp_topic_tpl.format(name=c["name"]): c["name"]
            for c in self.sensors}

        self.state = IOState()
        self._last_seen: dict[str, float] = {}
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        # give the subscription a moment; control loop handles staleness anyway
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=10)
        except asyncio.TimeoutError:
            log.warning("mqtt io backend not ready yet, continuing (failsafe armed)")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(self.host, self.port,
                                          username=self.user,
                                          password=self.pw) as client:
                    self._client = client
                    await client.subscribe(
                        self.temp_topic_tpl.format(name="+"))
                    self._ready.set()
                    log.info("mqtt io backend connected: %s", self.host)
                    async for msg in client.messages:
                        self._ingest(str(msg.topic), msg.payload.decode())
            except Exception as e:
                self._client = None
                log.warning("mqtt io disconnected (%s), retry in 5 s", e)
                await asyncio.sleep(5)

    def _ingest(self, topic: str, payload: str) -> None:
        name = self._topic2sensor.get(topic)
        if name is None:
            return
        try:
            raw = int(float(payload))
        except ValueError:
            log.warning("unparseable payload on %s: %r", topic, payload)
            return
        now = time.monotonic()
        self._last_seen[name] = now
        self.state.temps_raw[name] = raw
        if raw in self.fault_raw:
            self.state.faults.add(name)
            self.state.temps.pop(name, None)
        else:
            self.state.faults.discard(name)
            self.state.temps[name] = decode_pt1000(raw)
        self.state.last_read_ts = now

    async def read_state(self) -> IOState:
        # Promote per-sensor staleness to faults.
        now = time.monotonic()
        for c in self.sensors:
            name = c["name"]
            seen = self._last_seen.get(name, 0.0)
            if now - seen > self.stale_after:
                self.state.faults.add(name)
                self.state.temps.pop(name, None)
        return self.state

    async def write_valve(self, name: str, pct: float) -> None:
        if self._client is None:
            raise IOError("mqtt io backend not connected")
        pct = max(0.0, min(100.0, pct))
        raw = int(pct / 100.0 * self.raw_scale)
        await self._client.publish(
            self.valve_topic_tpl.format(name=name), str(raw))
        self.state.valves_pct[name] = pct

    async def write_all_valves(self, pct: float) -> None:
        for name in self.valve_names:
            try:
                await self.write_valve(name, pct)
            except Exception:
                log.exception("failsafe write failed: %s", name)
