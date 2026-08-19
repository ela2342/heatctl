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

from . import dewpoint

log = logging.getLogger("heatctl.mqtt")


def extract(payload: str, key: str | None) -> float | None:
    """A sensor payload as a number: bare, or one field of a JSON object.

    The bare form is what the rtl_433 bridge and the HA room bridges publish.
    The JSON form is what a Shelly publishes when it talks to the broker
    directly - `{"id":0,"tC":23.7,"tF":74.6}` on
    `sensors/shellies/<room>/status/temperature:0`.

    `key` is configured per room, never guessed. Auto-detecting the field would
    be picking a name out of a payload and hoping, and this project has a rule
    about that.

    Returns None on anything it cannot read, and the caller logs. Deliberately
    NOT tolerant of a missing key on a JSON payload: that is a configuration
    error, and silently falling back to `float(payload)` would turn it into a
    room that mysteriously never updates.
    """
    if key is not None:
        try:
            payload = json.loads(payload)[key]
        except (ValueError, TypeError, KeyError):
            return None
    try:
        return float(payload)
    except (TypeError, ValueError):
        return None


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
        # Per-room JSON field, absent for a bare-number publisher. See
        # `extract`. Keyed by room name, not topic, because the humidity topic
        # for the same room needs its own.
        self.room_temp_key = {r["name"]: r.get("room_temp_json_key")
                              for r in cfg["rooms"]}
        self.room_temps: dict[str, float] = {}
        self.room_temp_ts: dict[str, float] = {}

        # HUMIDITY, for computing the dew point here instead of in Home
        # Assistant - see heatctl/dewpoint.py for why that matters. Optional
        # per room and absent everywhere until the Shellys publish direct, so
        # this degrades to "no local dew point" rather than to a wrong one.
        self.room_hum_topics = {r["room_humidity_topic"]: r["name"]
                                for r in cfg["rooms"]
                                if r.get("room_humidity_topic")}
        self.room_hum_key = {r["name"]: r.get("room_humidity_json_key")
                             for r in cfg["rooms"]}
        self.room_hum: dict[str, float] = {}
        self.room_hum_ts: dict[str, float] = {}

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
        self._room_solar: dict[str, float] = {}
        self._room_solar_ts: dict[str, float] = {}
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

    def room_solar_w(self, max_age_s: float = 3600) -> dict[str, float]:
        """Layer 2's per-room solar gain, W, fresh entries only.

        Same staleness argument as `outdoor_avg`: the forecast has hourly
        resolution, so an hour-old value still describes the hour it covers.

        Stale rooms are DROPPED rather than zeroed. Zero is a physical claim -
        "this room is in shade" - and after sunset it happens to be true, which
        is exactly what would make a silent fallback impossible to notice. An
        absent room lets `EnergyDemand` keep its own default and lets the
        telemetry say how many rooms layer 2 is actually describing.
        """
        now = time.monotonic()
        return {r: w for r, w in self._room_solar.items()
                if now - self._room_solar_ts.get(r, 0.0) <= max_age_s}

    def local_dew_point(self, max_age_s: float = 900,
                        ) -> tuple[float | None, str | None, int]:
        """Dew point computed here, from the rooms that report humidity.

        Returns (value, wettest room, contributing room count). The count is
        published, because a dew point is plausible at any room count and the
        value alone cannot show that rooms have dropped out - see
        heatctl/dewpoint.py.

        Both halves of a pair must be individually fresh. Pairing a current
        temperature with an hour-old humidity would produce a confident number
        from a measurement nobody took.
        """
        now = time.monotonic()
        pairs: dict[str, tuple[float | None, float | None]] = {}
        for room, rh in self.room_hum.items():
            if now - self.room_hum_ts.get(room, 0.0) > max_age_s:
                continue
            if now - self.room_temp_ts.get(room, 0.0) > max_age_s:
                continue
            pairs[room] = (self.room_temps.get(room), rh)
        return dewpoint.house_dew_point(pairs)

    def dew_point(self, max_age_s: float = 900) -> float | None:
        """Latest dew point if fresh enough, else None.

        Freshness is judged by arrival time, so a retained message that stops
        being republished correctly ages out instead of looking current
        forever (docs/DESIGN.md 2.2).

        THE MAXIMUM OF THE EXTERNAL AND THE LOCAL VALUE, when both are fresh.
        Not a preference between them, and deliberately not "local wins once it
        exists": during the migration only some rooms publish humidity here, so
        a local value computed from three of seven rooms is a max over a SUBSET
        and can only be too low. Too low is the direction that condenses - it
        is exactly the 2026-08-10 failure, where a reference over two rooms
        read 12.0 against Bad's actual 17.3.

        Taking the max makes the two sources a max over their union, so
        whichever is more protective wins and neither can silently relax the
        limit as rooms move. When the external one is retired the max is over
        one source and this reduces to the local computation.
        """
        fresh = time.monotonic() - self._dew_ts <= max_age_s
        external = self._dew if (self._dew is not None and fresh) else None
        local, _room, _n = self.local_dew_point(max_age_s)
        if external is None:
            return local
        if local is None:
            return external
        return max(external, local)

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
                    # Layer 2's per-room solar gain. Also a parameter: it says
                    # how much sun each room is taking, and the slab target
                    # subtracts it. Stale or absent means every room falls back
                    # to zero gain, which is the pre-2026-08-09 behaviour and
                    # merely conservative - it understates cooling need, it
                    # never invents one.
                    await client.subscribe(f"{self.base}/opt/room/+/solar_w")
                    for topic in self.room_topics:
                        await client.subscribe(topic)
                    for topic in self.room_hum_topics:
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
            v = extract(payload, self.room_temp_key.get(room))
            if v is None:
                log.warning("bad room temp on %s: %r", topic, payload)
            else:
                self.room_temps[room] = v
                self.room_temp_ts[room] = time.monotonic()
            return
        room = self.room_hum_topics.get(topic)
        if room is not None:
            v = extract(payload, self.room_hum_key.get(room))
            if v is None:
                log.warning("bad room humidity on %s: %r", topic, payload)
            else:
                self.room_hum[room] = v
                self.room_hum_ts[room] = time.monotonic()
            return
        if (topic.startswith(f"{self.base}/opt/room/")
                and topic.endswith("/solar_w")):
            room = topic[len(f"{self.base}/opt/room/"):-len("/solar_w")]
            try:
                self._room_solar[room] = float(payload)
                self._room_solar_ts[room] = time.monotonic()
            except ValueError:
                log.debug("non-numeric room solar on %s: %r", topic, payload)
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

    async def publish(self, suffix: str, payload,
                      retain: bool = True) -> None:
        """Publish one state topic. RETAINED BY DEFAULT.

        WHY THE DEFAULT FLIPPED (2026-08-08). It was False, so every value was
        a fire-and-forget event: a subscriber joining between publishes saw
        NOTHING and had to wait a whole interval to learn the plant's state.
        For the energy shadow that is 60 s of blindness per lookup, and it is
        not only a nuisance for an operator - a dashboard after a reload, or HA
        after a restart, is equally blind, and "no value" is indistinguishable
        from "no data" at a glance. That ambiguity has cost real time here.

        Retaining is safe because staleness is already handled elsewhere: the
        LWT publishes `status` offline, every discovered entity carries
        `availability_topic: heatctl/status`, and the consumers that must not
        act on old data (dew point, room temperature, layer 2's delta) all
        judge freshness by ARRIVAL TIME and expire independently. So a retained
        value can be read immediately and still cannot be mistaken for a live
        one by anything that matters.
        """
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

        async def sensor(uid: str, name: str, state_topic: str,
                         unit: str | None,
                         device_class: str | None = None):
            conf = {"name": name, "state_topic": f"{self.base}/{state_topic}"}
            # A TEXT sensor gets neither. `state_class: measurement` on a
            # non-numeric state makes HA log a warning every update and drops
            # it from statistics; a unit on a room name is meaningless.
            if unit is not None:
                conf["unit_of_measurement"] = unit
                conf["state_class"] = "measurement"
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
        # heatctl's OWN dew point, and what it rests on. Discovered separately
        # from the HA helper's `system_dew_point_*` so the two can be compared
        # while both exist - the changeover is only trustworthy if they agree
        # before the helper is retired.
        await sensor("dew_point_local", "Dew point (computed here)",
                     "dew_point/local", "°C", "temperature")
        await sensor("dew_point_rooms", "Dew point rooms", "dew_point/rooms",
                     "rooms", None)
        await sensor("dew_point_source", "Dew point source", "dew_point/source",
                     None, None)
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
        # ENERGY SHADOW (docs/DESIGN_ENERGY_DEMAND.md). Discovered so the
        # figures become HA entities and therefore land in InfluxDB with
        # history - without this they were MQTT-only, which meant the one part
        # of the system whose whole purpose is to be watched could not be
        # watched over time, and every question about it needed a live
        # subscribe.
        await sensor("energy_house_excess", "House slab excess",
                     "energy/house_excess_wh", "Wh", "energy_storage")
        await sensor("energy_house_actionable", "House demand (actionable)",
                     "energy/house_actionable_wh", "Wh", "energy_storage")
        await sensor("energy_house_blocked", "House demand (wrong mode)",
                     "energy/house_blocked_wh", "Wh", "energy_storage")
        await sensor("energy_rooms_valid", "Rooms with a slab estimate",
                     "energy/rooms_valid", "")
        # How many rooms layer 2 is currently describing the sun for. Worth an
        # entity because the failure it detects is SILENT: if the optimizer
        # dies or a room name stops matching, every room quietly reverts to
        # zero gain and the slab targets go back to being wrong in the summer
        # without anything looking broken. A count that drops to 0 at noon is
        # the visible symptom.
        await sensor("energy_solar_rooms", "Rooms with a solar estimate",
                     "energy/solar_rooms", "")
        await sensor("energy_outdoor", "Outdoor used for slab target",
                     "energy/outdoor_c", "°C", "temperature")
        await disc("binary_sensor", "energy_stale",
                   {"name": "Energy shadow blind",
                    "state_topic": f"{self.base}/energy/status",
                    "payload_on": "stale: no I/O", "payload_off": "ok",
                    "device_class": "problem"})
        await disc("sensor", "energy_outdoor_source",
                   {"name": "Outdoor source",
                    "state_topic": f"{self.base}/energy/outdoor_source",
                    "icon": "mdi:thermometer-check"})
        await disc("sensor", "valve_override",
                   {"name": "Valve override",
                    "state_topic": f"{self.base}/valve_override",
                    "icon": "mdi:hand-back-right"})
        for room in self.cfg["rooms"]:
            n = room["name"]
            await sensor(f"energy_{n}_slab", f"{n} slab estimate",
                         f"energy/{n}/slab", "°C", "temperature")
            await sensor(f"energy_{n}_slab_target", f"{n} slab target",
                         f"energy/{n}/slab_target", "°C", "temperature")
            await sensor(f"energy_{n}_excess", f"{n} slab excess",
                         f"energy/{n}/excess_wh", "Wh", "energy_storage")
            await sensor(f"energy_{n}_actionable", f"{n} demand (actionable)",
                         f"energy/{n}/actionable_wh", "Wh", "energy_storage")
            # Which measurement drives this room: sensor, house average, or the
            # return loop. Invisible before, and it decides how much the room's
            # comfort figure is worth.
            await disc("sensor", f"room_{n}_source", {
                "name": f"{n} control source",
                "state_topic": f"{self.base}/room/{n}/source",
                "icon": "mdi:thermometer-lines"})
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
        # EVERY room gets one, including those with no sensor. REVERSED
        # 2026-08-10 (owner: "Natalie might not have a sensor, but it still
        # needs a setpoint controller"), and the old reasoning is kept here
        # because it was correct when written:
        #
        #   "Only for rooms that actually have a room temperature source. For
        #    the others the room setpoint is inert - they run the return-
        #    temperature fallback, which never reads it - so offering a control
        #    would be a lie."
        #
        # That stopped being true when the house-average proxy landed. A room
        # with no sensor is now driven by `house_avg` measured against ITS OWN
        # setpoint (`<room>_control_source` says which), and its slab target is
        # computed from that setpoint. The control is live, so withholding it
        # is now the lie - it left Kinderzimmer Natalie as the one room nobody
        # could set a temperature for.
        #
        # The difference that remains is honest and visible: a sensorless room
        # gets NO `current_temperature_topic`, because heatctl deliberately
        # never publishes the house-average proxy on `room/<n>/temp` - that
        # topic means "this room was measured". So HA shows a target with no
        # current reading, which is exactly the truth.
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
            conf = {
                    "name": room.get("label", n),
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
            }
            if room.get("room_temp_topic"):
                conf["current_temperature_topic"] = f"{self.base}/room/{n}/temp"
            await disc("climate", uid, conf)
            # The old number entity is superseded by the thermostat above.
            # Clearing it is a one-time migration and harmless when repeated.
            await undisc("number", uid)
