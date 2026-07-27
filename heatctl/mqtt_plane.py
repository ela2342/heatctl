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
import os
import time

import aiomqtt

log = logging.getLogger("heatctl.mqtt")


class ControlPlane:
    def __init__(self, cfg: dict, on_command):
        m = cfg["mqtt"]
        # Environment wins over the file for site-specific values, so the
        # committed config.yaml can carry placeholders. See README.
        self.host = os.environ.get("HEATCTL_MQTT_HOST") or m["host"]
        self.port = int(os.environ.get("HEATCTL_MQTT_PORT") or m["port"])
        # Credentials come from the environment so they are never committed.
        # In the target deployment mosquitto runs on the same machine and may
        # allow anonymous local connections, in which case both stay unset.
        self.user = os.environ.get("HEATCTL_MQTT_USERNAME") or m.get("username") or None
        self.pw = os.environ.get("HEATCTL_MQTT_PASSWORD") or m.get("password") or None
        self.base = m["base_topic"]
        self.disc = m.get("ha_discovery", True)
        self.disc_prefix = m.get("ha_discovery_prefix", "homeassistant")
        self.cfg = cfg
        self.on_command = on_command  # callback(kind, key, payload)

        self.room_topics = {r["room_temp_topic"]: r["name"]
                            for r in cfg["rooms"] if r.get("room_temp_topic")}
        self.room_temps: dict[str, float] = {}
        self.room_temp_ts: dict[str, float] = {}

        # Optional. Without it, safety falls back to the static cooling limit.
        self.dew_topic = m.get("dew_point_topic") or None
        self._dew: float | None = None
        self._dew_ts = 0.0

        self._client: aiomqtt.Client | None = None

    def room_temp(self, room: str, max_age_s: float = 300) -> float | None:
        """Room air temperature if fresh enough, else None."""
        ts = self.room_temp_ts.get(room)
        if ts is None or time.monotonic() - ts > max_age_s:
            return None
        return self.room_temps.get(room)

    def dew_point(self, max_age_s: float = 900) -> float | None:
        """Latest dew point if fresh enough, else None.

        Freshness is judged by arrival time, so a retained message that stops
        being republished correctly ages out instead of looking current
        forever (docs/DESIGN.md 2.2).
        """
        if self._dew is None or time.monotonic() - self._dew_ts > max_age_s:
            return None
        return self._dew

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
                    await client.subscribe(f"{self.base}/hp/set/#")
                    for topic in self.room_topics:
                        await client.subscribe(topic)
                    if self.dew_topic:
                        await client.subscribe(self.dew_topic)
                    log.info("control plane connected: %s", self.host)
                    async for msg in client.messages:
                        self._dispatch(str(msg.topic), msg.payload.decode())
            except Exception as e:
                self._client = None
                log.warning("control plane disconnected (%s), retry in 10 s", e)
                await asyncio.sleep(10)

    def _dispatch(self, topic: str, payload: str) -> None:
        if self.dew_topic and topic == self.dew_topic:
            try:
                self._dew = float(payload)
                self._dew_ts = time.monotonic()
            except ValueError:
                # HA publishes "unknown"/"unavailable" as plain strings when a
                # source sensor drops out. Not an error - just no new value,
                # so the existing one ages out and safety falls back.
                log.debug("non-numeric dew point on %s: %r", topic, payload)
            return
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
        elif topic.startswith(f"{self.base}/hp/set/"):
            # Heat pump register writes. Routed, not handled here: this file
            # owns MQTT, not the register map.
            self.on_command("hp", topic[len(f"{self.base}/hp/set/"):], payload)

    async def stop(self) -> None:
        """Say goodbye explicitly, while still connected.

        The LWT only fires on an *unexpected* disconnect. A clean shutdown
        sends a proper MQTT DISCONNECT, which suppresses the will - so without
        this the retained "online" status survives and HA keeps presenting the
        last telemetry as current. Stale sensor values shown as live are
        exactly what misleads during an incident.

        Must be called BEFORE the run() task is cancelled.
        """
        if not self._client:
            return
        try:
            await self._client.publish(f"{self.base}/status", "offline",
                                       retain=True)
        except Exception:
            pass

    async def discover(self, component: str, uid: str, conf: dict) -> None:
        """Publish one HA discovery config. Public so other modules (the heat
        pump client) can register their own entities without this file needing
        to know about their register maps."""
        if not self._client or not self.disc:
            return
        conf = {"unique_id": f"heatctl_{uid}",
                "availability_topic": f"{self.base}/status",
                "device": {"identifiers": ["heatctl_wago"], "name": "heatctl",
                           "manufacturer": "heatctl",
                           "model": "WAGO 750-352 node"},
                **conf}
        try:
            await self._client.publish(
                f"{self.disc_prefix}/{component}/heatctl/{uid}/config",
                json.dumps(conf), retain=True)
        except Exception:
            pass

    async def publish(self, suffix: str, payload, retain: bool = False) -> None:
        if not self._client:
            return
        try:
            await self._client.publish(f"{self.base}/{suffix}", str(payload),
                                       retain=retain)
        except Exception:
            pass

    async def _publish_discovery(self) -> None:
        """Publish HA MQTT-discovery configs (retained, so they survive restarts).

        Read-only sensors AND controls: without the `select`/`number` entities
        below, `heatctl/set/mode` and `heatctl/set/setpoint/<room>` are
        subscribed but nothing in HA can reach them, so the plant would be
        display-only from HA's side.
        """
        dev = {"identifiers": ["heatctl_wago"], "name": "heatctl",
               "manufacturer": "heatctl", "model": "WAGO 750-352 node"}

        async def disc(component: str, uid: str, conf: dict) -> None:
            conf = {"unique_id": f"heatctl_{uid}",
                    "availability_topic": f"{self.base}/status",
                    "device": dev, **conf}
            await self._client.publish(
                f"{self.disc_prefix}/{component}/heatctl/{uid}/config",
                json.dumps(conf), retain=True)

        async def undisc(component: str, uid: str) -> None:
            """Remove a previously discovered entity.

            Discovery configs are retained, so an entity we stop publishing
            would otherwise linger in HA forever. An empty retained payload is
            the documented way to delete one.
            """
            await self._client.publish(
                f"{self.disc_prefix}/{component}/heatctl/{uid}/config",
                b"", retain=True)

        async def sensor(uid: str, name: str, state_topic: str, unit: str,
                         device_class: str | None = None):
            conf = {"name": name, "state_topic": f"{self.base}/{state_topic}",
                    "unit_of_measurement": unit, "state_class": "measurement"}
            if device_class:
                conf["device_class"] = device_class
            await disc("sensor", uid, conf)

        for ch in self.cfg["sensors"]["channels"]:
            if ch.get("enabled", True):
                await sensor(ch["name"], ch.get("label", ch["name"]),
                             f"temp/{ch['name']}", "°C", "temperature")
        # Only channels assigned to a circuit. An unassigned analog output is
        # never commanded, so discovering it would create an entity that reads
        # `unknown` forever - the same clutter we spent 2026-07-27 removing.
        assigned = {c["valve"] for r in self.cfg["rooms"] for c in r["circuits"]
                    if c.get("valve")}
        for ch in self.cfg["valves"]["channels"]:
            if ch["name"] in assigned:
                await sensor(ch["name"], ch["name"], f"valve/{ch['name']}", "%")
            else:
                await undisc("sensor", ch["name"])

        # Actual output position, read back from the coupler. Recorded
        # separately from the command because the two diverge only when
        # something else moved the outputs - invisible unless both exist.
        for ch in self.cfg["valves"]["channels"]:
            if ch["name"] in assigned:
                await sensor(f"{ch['name']}_actual", f"{ch['name']} actual",
                             f"valve_actual/{ch['name']}", "%")

        await disc("binary_sensor", "hp_mode_agrees", {
            "name": "Plant and heat pump modes disagree",
            "state_topic": f"{self.base}/hp/mode_agrees",
            "payload_on": "0", "payload_off": "1",   # a problem when they differ
            "device_class": "problem",
            "entity_category": "diagnostic",
        })
        await disc("sensor", "water_sp_reason", {
            "name": "Water setpoint decision",
            "state_topic": f"{self.base}/water_sp/reason",
            "entity_category": "diagnostic",
        })

        # --- house demand / source engagement (diagnostic) ---
        # Discovered even while the demand controller is in shadow mode: the
        # entire point of shadow mode is being able to plot what heatctl WOULD
        # command against what the HA automations actually do, before it takes
        # the heat pump over. Compare `heatctl_source_request` against
        # `binary_sensor.heat_pump_pump_request`.
        await disc("binary_sensor", "source_request", {
            "name": "Source request (shadow)",
            "state_topic": f"{self.base}/demand/source_request",
            "payload_on": "1", "payload_off": "0",
            "entity_category": "diagnostic",
        })
        await sensor("demand_deviation", "House deviation",
                     "demand/deviation", "K")
        await sensor("demand_peak", "Peak circuit demand", "demand/peak", "%")
        await sensor("hp_spread", "HP spread", "hp/spread", "K")
        await sensor("hp_power_estimate", "HP power estimate",
                     "hp/power_estimate", "W", "power")
        await sensor("demand_open_pct", "Circuit opening (flow proxy)",
                     "demand/open_pct", "%")
        await disc("sensor", "demand_reason", {
            "name": "Source decision",
            "state_topic": f"{self.base}/demand/reason",
            "entity_category": "diagnostic",
        })

        # --- controls (write side of the MQTT contract) ---
        await disc("select", "mode", {
            "name": "Mode",
            "state_topic": f"{self.base}/mode",
            "command_topic": f"{self.base}/set/mode",
            "options": ["heating", "cooling", "off"],
        })

        # Per-room thermostats. A `climate` entity rather than a bare `number`:
        # it shows current AND target temperature together and gets a proper
        # thermostat card, which a slider with no notion of "now" cannot.
        #
        # Only for rooms that actually have a room temperature source. For the
        # others the room setpoint is inert - they run the return-temperature
        # fallback, which never reads it - so offering a control would be a lie.
        #
        # Bounds come from the same safety clamp that would reject an
        # out-of-range value anyway, so HA cannot even offer an invalid one. And
        # because temperature_state_topic is wired, HA displays what heatctl
        # actually adopted after clamping rather than what was requested.
        #
        # NOTE mode is deliberately the GLOBAL heatctl mode on every room's
        # thermostat: heatctl has one plant mode, not one per room, so changing
        # it on any thermostat changes all of them. That is honest rather than
        # convenient; do not fake per-room modes here.
        s = self.cfg["safety"]
        for room in self.cfg["rooms"]:
            n = room["name"]
            uid = f"sp_{n}"
            if room.get("room_temp_topic"):
                await disc("climate", uid, {
                    "name": room.get("label", n),
                    "current_temperature_topic": f"{self.base}/room/{n}/temp",
                    "temperature_state_topic": f"{self.base}/setpoint/{n}",
                    "temperature_command_topic": f"{self.base}/set/setpoint/{n}",
                    "mode_state_topic": f"{self.base}/mode",
                    "mode_state_template":
                        "{{ 'heat' if value == 'heating'"
                        " else 'cool' if value == 'cooling' else 'off' }}",
                    "mode_command_topic": f"{self.base}/set/mode",
                    "mode_command_template":
                        "{{ 'heating' if value == 'heat'"
                        " else 'cooling' if value == 'cool' else 'off' }}",
                    "modes": ["off", "heat", "cool"],
                    "min_temp": s["setpoint_min_c"],
                    "max_temp": s["setpoint_max_c"],
                    "temp_step": 0.5,
                    "temperature_unit": "C",
                })
            else:
                await undisc("climate", uid)
            # The old number entity is superseded by the thermostat above.
            # Clearing it is a one-time migration and harmless when repeated.
            await undisc("number", uid)
