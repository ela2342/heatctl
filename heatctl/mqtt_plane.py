"""Control-plane MQTT: telemetry out, setpoints/commands and room sensors in.

Optional and failure-tolerant: the control core keeps running with a dead
broker (falling back to return-temperature control and default setpoints).

Topics (base = heatctl):
  heatctl/status                    online/offline (LWT, retained)
  heatctl/temp/<name>               circuit/supply temperatures degC
  heatctl/room/<room>/temp          room air temp as used by control
  heatctl/valve/<name>              valve position %
  heatctl/mode                      heating|cooling|off (retained)
  heatctl/set/mode                  command
  heatctl/set/setpoint/<room>       command (degC, clamped by safety)
  heatctl/override/<name>           active safety overrides

Room air sensors (e.g. Shelly H&T) are subscribed from arbitrary topics
configured per room (`room_temp_topic`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import aiomqtt

log = logging.getLogger("heatctl.mqtt")


class ControlPlane:
    def __init__(self, cfg: dict, on_command):
        m = cfg["mqtt"]
        self.host, self.port = m["host"], m["port"]
        self.user = m.get("username") or None
        self.pw = m.get("password") or None
        self.base = m["base_topic"]
        self.disc = m.get("ha_discovery", True)
        self.disc_prefix = m.get("ha_discovery_prefix", "homeassistant")
        self.cfg = cfg
        self.on_command = on_command  # callback(kind, key, payload)

        self.room_topics = {r["room_temp_topic"]: r["name"]
                            for r in cfg["rooms"] if r.get("room_temp_topic")}
        self.room_temps: dict[str, float] = {}
        self.room_temp_ts: dict[str, float] = {}

        self._client: aiomqtt.Client | None = None

    def room_temp(self, room: str, max_age_s: float = 300) -> float | None:
        """Room air temperature if fresh enough, else None."""
        ts = self.room_temp_ts.get(room)
        if ts is None or time.monotonic() - ts > max_age_s:
            return None
        return self.room_temps.get(room)

    async def run(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(
                    self.host, self.port, username=self.user, password=self.pw,
                    will=aiomqtt.Will(f"{self.base}/status", "offline",
                                      retain=True),
                ) as client:
                    self._client = client
                    await client.publish(f"{self.base}/status", "online",
                                         retain=True)
                    if self.disc:
                        await self._publish_discovery()
                    await client.subscribe(f"{self.base}/set/#")
                    for topic in self.room_topics:
                        await client.subscribe(topic)
                    log.info("control plane connected: %s", self.host)
                    async for msg in client.messages:
                        self._dispatch(str(msg.topic), msg.payload.decode())
            except Exception as e:
                self._client = None
                log.warning("control plane disconnected (%s), retry in 10 s", e)
                await asyncio.sleep(10)

    def _dispatch(self, topic: str, payload: str) -> None:
        room = self.room_topics.get(topic)
        if room is not None:
            try:
                self.room_temps[room] = float(payload)
                self.room_temp_ts[room] = time.monotonic()
            except ValueError:
                log.warning("bad room temp on %s: %r", topic, payload)
            return
        if topic == f"{self.base}/set/mode":
            self.on_command("mode", "", payload)
        elif topic.startswith(f"{self.base}/set/setpoint/"):
            room = topic.rsplit("/", 1)[1]
            self.on_command("setpoint", room, payload)

    async def publish(self, suffix: str, payload, retain: bool = False) -> None:
        if not self._client:
            return
        try:
            await self._client.publish(f"{self.base}/{suffix}", str(payload),
                                       retain=retain)
        except Exception:
            pass

    async def _publish_discovery(self) -> None:
        dev = {"identifiers": ["heatctl_wago"], "name": "heatctl",
               "manufacturer": "heatctl", "model": "WAGO 750-352 node"}

        async def sensor(uid: str, name: str, state_topic: str, unit: str,
                         device_class: str | None = None):
            conf = {"name": name, "unique_id": f"heatctl_{uid}",
                    "state_topic": f"{self.base}/{state_topic}",
                    "unit_of_measurement": unit,
                    "state_class": "measurement",
                    "availability_topic": f"{self.base}/status", "device": dev}
            if device_class:
                conf["device_class"] = device_class
            await self._client.publish(
                f"{self.disc_prefix}/sensor/heatctl/{uid}/config",
                json.dumps(conf), retain=True)

        for ch in self.cfg["sensors"]["channels"]:
            if ch.get("enabled", True):
                await sensor(ch["name"], ch.get("label", ch["name"]),
                             f"temp/{ch['name']}", "°C", "temperature")
        for ch in self.cfg["valves"]["channels"]:
            await sensor(ch["name"], ch["name"], f"valve/{ch['name']}", "%")
