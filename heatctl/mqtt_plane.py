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
        # OUTDOOR AIR TEMPERATURE, for the slab-target feedforward. The heat
        # pump has its own ambient register and it is notoriously unreliable -
        # mounted on the unit, it read 45.6 degC on 2026-08-04 against a true
        # air temperature near 30. The outdoor weather stations are far better,
        # so they are preferred and the register is only the fallback for when
        # this broker is gone. `UA_ao * (T_set - AT)` multiplies this error by
        # the whole house conductance, so it is the largest single term to get
        # wrong.
        self.outdoor_topic = m.get("outdoor_temp_topic") or None
        # A SHORT MEDIAN, because this comes straight off a 433 MHz decoder and
        # rtl_433 emits occasional garbled frames. Observed 2026-08-06: the
        # station published 13.4 degC while both its own HA entities and the
        # heat pump agreed on ~27. A single bad sample moves the slab target by
        # UA_ao * dT / UA_sa = 240 * 14 / 490 = 6.9 K, so one frame could swing
        # the whole feedforward. A median of three rejects isolated spikes and
        # is explainable, which a filter with state and tuning is not.
        self._outdoor_avg: float | None = None
        self._outdoor_avg_ts = 0.0
        self._outdoor_buf: list[tuple[float, float]] = []
        self._outdoor_window = int(m.get("outdoor_median_samples", 3))
        # Layer 2's pre-conditioning delta, in K, applied as
        # `active = dial + delta`. SIGNED and mode-independent on purpose:
        # negative asks for a cooler target (pre-cool before a hot afternoon),
        # positive for a warmer one (pre-heat before a cold night). Deriving the
        # direction from the plant mode instead would make "aim cooler while
        # heating" unexpressible, and that is a real case - anticipating strong
        # solar gain, or a setback.
        #
        # Safety comes from bounding the MAGNITUDE and clamping the result, not
        # from restricting the sign. Ages out to 0.0, i.e. back to exactly what
        # the dial says, which is why a dead layer 2 is harmless here.
        self._sp_delta = 0.0
        self._sp_delta_ts = 0.0

        self._client: aiomqtt.Client | None = None

    def room_temp(self, room: str, max_age_s: float = 300) -> float | None:
        """Room air temperature if fresh enough, else None."""
        ts = self.room_temp_ts.get(room)
        if ts is None or time.monotonic() - ts > max_age_s:
            return None
        return self.room_temps.get(room)

    def outdoor_temp(self, max_age_s: float = 900) -> float | None:
        """Outdoor air from the weather station, or None if stale/absent.

        None is a real answer and the caller must handle it: falling back to
        the heat pump's own sensor is a DEGRADATION, not an equivalent, and
        whoever does it should know they have done it.
        """
        now = time.monotonic()
        fresh = [v for ts, v in self._outdoor_buf if now - ts <= max_age_s]
        if not fresh:
            return None
        # Median over whatever is fresh, including a single sample: refusing to
        # answer until the buffer fills would leave layer 1 on the heat pump's
        # biased register for the first minutes after every restart, which is
        # the worse failure.
        return sorted(fresh)[len(fresh) // 2]

    def outdoor_avg(self, max_age_s: float = 3600) -> float | None:
        """Layer 2's forecast-averaged outdoor, or None if stale/absent.

        Longer default staleness than a live sensor on purpose: this is a
        forecast average over hours, refreshed when the forecast is, so a value
        an hour old is still a fair description of the window it covers.
        """
        if (self._outdoor_avg is None
                or time.monotonic() - self._outdoor_avg_ts > max_age_s):
            return None
        return self._outdoor_avg

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
                    # Layer 2's pre-conditioning delta. Under opt/, not set/:
                    # the optimizer publishes status and layer 1 chooses to
                    # consult it, with the same staleness contract as the dew
                    # point above.
                    await client.subscribe(f"{self.base}/opt/setpoint_delta")
                    # Layer 2's forecast-averaged outdoor. A PARAMETER, not a
                    # command: it describes the weather, layer 1 decides what
                    # to do about it and falls back to its own sensor when this
                    # goes stale.
                    await client.subscribe(f"{self.base}/opt/outdoor_avg_c")
                    for topic in self.room_topics:
                        await client.subscribe(topic)
                    if self.dew_topic:
                        await client.subscribe(self.dew_topic)
                    if self.outdoor_topic:
                        await client.subscribe(self.outdoor_topic)
                    log.info("control plane connected: %s", self.host)
                    async for msg in client.messages:
                        self._dispatch(str(msg.topic), msg.payload.decode())
            except Exception as e:
                self._client = None
                log.warning("control plane disconnected (%s), retry in 10 s", e)
                await asyncio.sleep(10)

    def _dispatch(self, topic: str, payload: str) -> None:
        if self.outdoor_topic and topic == self.outdoor_topic:
            try:
                v = float(payload)
            except ValueError:
                log.debug("non-numeric outdoor temp on %s: %r", topic, payload)
                return
            self._outdoor_buf.append((time.monotonic(), v))
            del self._outdoor_buf[:-self._outdoor_window]
            return
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
        if topic == f"{self.base}/opt/outdoor_avg_c":
            try:
                self._outdoor_avg = float(payload)
                self._outdoor_avg_ts = time.monotonic()
            except ValueError:
                pass
            return
        if topic == f"{self.base}/opt/setpoint_delta":
            try:
                v = float(payload)
            except ValueError:
                return
            self._sp_delta = v
            self._sp_delta_ts = time.monotonic()
            return
        if topic == f"{self.base}/set/mode":
            self.on_command("mode", "", payload)
        elif topic.startswith(f"{self.base}/set/valve/"):
            self.on_command("valve", topic.rsplit("/", 1)[1], payload)
        elif topic.startswith(f"{self.base}/set/setpoint/"):
            room = topic.rsplit("/", 1)[1]
            self.on_command("setpoint", room, payload)
        elif topic.startswith(f"{self.base}/hp/set/"):
            # Heat pump register writes. Routed, not handled here: this file
            # owns MQTT, not the register map.
            self.on_command("hp", topic[len(f"{self.base}/hp/set/"):], payload)

    def setpoint_delta(self, max_age_s: float) -> float:
        """Layer 2's signed pre-conditioning delta in K, 0.0 if stale/absent.

        Zero is the safe value and the reason this needs no command TTL
        machinery: expiry returns the plant to exactly the dial setting, which
        is what a human chose. A hung optimizer therefore degrades to normal
        comfort control rather than leaving the house steered.

        DELIBERATELY UNBOUNDED HERE. The caller applies
        `safety.clamp_setpoint` to the RESULT, and that absolute bound is the
        real protection - a second arbitrary limit on the delta would just be a
        number nobody derived, sitting in front of one that is meant to mean
        something.

        And the magnitude is not where the risk lives. Even a winter storm
        dropping the outdoor temperature 20 K over six hours is
        20 K x 267 W/K x 6 h = 32 kWh, which against a building capacity of
        15.3 kWh/K is only ~2.1 K of target shift. The outdoor swing does not
        set this quantity's scale; the building's thermal mass does. What has to
        be survivable is a WRONG value, and the absolute clamp is what makes it
        survivable - so that clamp being sanely set matters more than it did
        before (see BACKLOG on setpoint_min_c).
        """
        if time.monotonic() - self._sp_delta_ts > max_age_s:
            return 0.0
        return self._sp_delta

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
        # The setpoint-saturation alarm. NOT diagnostic-only and NOT a plain
        # sensor: "the house wants more and the plant cannot legally supply it"
        # is the condition that hid a whole afternoon's limit cycle (D-029), so
        # it gets a problem device class and shows up as a real alarm.
        await disc("binary_sensor", "water_sp_blocked", {
            "name": "Water setpoint saturated",
            "state_topic": f"{self.base}/water_sp/blocked",
            "payload_on": "1", "payload_off": "0",
            "device_class": "problem",
        })
        # The measured leaving/return spread that sets the dynamic condensation
        # floor. Worth surfacing because it is the quantity that turned out to
        # govern how much cooling the plant can actually deliver.
        await sensor("water_sp_spread_est", "Spread estimate (floor input)",
                     "water_sp/spread_est", "K")
        # The condensation limit actually in force. Published since the start
        # but never DISCOVERED, so it has been invisible in Home Assistant -
        # and it is the number that answers "why did that valve shut". Plotted
        # against leaving water it is the whole cooling story on one axis.
        await sensor("cooling_supply_limit", "Cooling supply limit",
                     "cooling_supply_limit", "°C", "temperature")
        # The pre-conditioning delta ACTUALLY IN FORCE, after staleness and the
        # absolute clamp. Discovered because it was invisible: layer 2 published
        # a number, layer 1 consumed it, and nothing showed whether the two
        # agreed - which made "will it do the right thing tonight?" unanswerable
        # without reading code. A control input that cannot be observed cannot be
        # trusted.
        await sensor("setpoint_delta_active", "Pre-conditioning delta",
                     "setpoint_delta/active", "K")

        # --- house demand / source engagement (diagnostic) ---
        # What heatctl is holding the heat pump's power at. It is a
        # reconciler, so in normal operation this simply reads on (D-016).
        await disc("binary_sensor", "source_request", {
            "name": "Source request",
            "state_topic": f"{self.base}/demand/source_request",
            "payload_on": "1", "payload_off": "0",
            "entity_category": "diagnostic",
        })
        await sensor("demand_deviation", "House deviation",
                     "demand/deviation", "K")
        await sensor("demand_peak", "Peak circuit demand", "demand/peak", "%")
        await sensor("hp_spread", "HP spread", "hp/spread", "K")
        # Named COMPRESSOR, not "HP", since 2026-08-02: it is 218*I from the
        # compressor current register and excludes fan and pump, which that
        # register does not see. Calling it "HP power" invited exactly the
        # boundary confusion that put a fan+pump intercept into it.
        await sensor("hp_power_estimate", "Compressor power (electrical)",
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
