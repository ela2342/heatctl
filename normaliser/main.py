"""Normalise room-sensor topics: one payload shape, retained, with an expiry.

Neither layer 1 nor layer 2. This is **plumbing**: it does not decide anything,
it republishes what the sensors say in a form the control core can consume
safely. It runs on the PFC200 next to heatctl, in its own container, and
heatctl works exactly as well without it - just blind for one sleep period
after every restart, which is the problem it exists to remove.

## The problem

The Shelly H&T G3 **sleeps, and the sleep cannot be disabled**: an always-on
CPU self-heats and distorts the very measurement the device exists to make. So
a room temperature is an inherently *sampled* signal, one sample every wake
period (600 s reported by the device, 360 s observed - see `interval_s` below,
which exists to settle that).

Three consequences follow, and this module answers all three in one place:

1. **The status topics are not retained** (verified on the broker, 2026-08-20:
   only `.../online` is). A subscriber that joins mid-cycle sees nothing until
   the next wake. For heatctl that means every restart is blind, per room, for
   up to a wake period - and on the PFC a restart is every deploy. It also
   blocks D-044's start-up mode decision, which needs a complete room set.
2. **Retain alone would make that worse, not better.** heatctl times staleness
   from *arrival* (`room_temp_ts`, against `room_temp_max_age_s`), and a
   retained message is delivered with no indication of when it was produced. A
   three-hour-old reading would arrive looking zero seconds old. Retain needs a
   second signal beside it.
3. **The device cannot supply that signal itself.** Its own clock is unset
   immediately after wake (`"time":null,"unixtime":null` in the first `sys`
   status), which is precisely the window every message occupies. And `online`
   is false ~357 s in every 360, so it is a wake *event* marker, never a
   freshness gate. Both of those were proposed and both are closed.

## The answer: let the broker hold the deadline

Every accepted sample is republished **retained, with an MQTT 5 message-expiry
interval**. mosquitto then owns the deadline: it serves the value to a new
subscriber only while it is younger than `ttl_s`, decrements the remaining
interval as it sits there, and deletes it when it runs out - across a broker
restart too, because the expiry is persisted. Verified against mosquitto 2.1.2
on 2026-08-20, including that an **MQTT 3.1.1 subscriber still receives it**
(without the property, per spec). That last point is why heatctl needs no
change at all: it connects as v3.1.1 and reads a bare float, as it always has.

The clock is ours, on the box heatctl runs on, and it is only ever used to
*withhold* data. Nothing here can make a value look fresher than it is.

## Two independent enforcers, and deliberately not one

`ttl_s` should equal heatctl's `room_temp_max_age_s`, because they are the same
judgement - "older than this is not a measurement any more" - and there is no
reason for the plant to hold two different opinions about it.

What this module does **not** do is republish periodically to keep that value
alive. It would be easy, and it would be a mistake: heatctl's own staleness
window would then be measuring *this process's* liveness instead of the
sensor's, and a normaliser that froze while still publishing would be
undetectable. One publish per sample keeps heatctl's window pointed at the real
sensor cadence, so the two enforcers fail independently:

  - this process dies      -> the broker still expires the value at `ttl_s`
  - the broker loses state -> heatctl still ages the value out at max_age
  - the sensor goes quiet  -> both notice, separately

The cost is one known bound: heatctl restarting just before a retained value
expires will accept it and then hold it for its own full window, so the
worst-case age of a believed reading is `ttl_s + room_temp_max_age_s`. With
900 s each that is 30 minutes, against a slab whose time constant is hours.
That is a bound worth having, not a leak worth closing with a mechanism that
weakens the failure model.

## What it publishes, per room

    sensors/room/<room>/temperature_c   bare float, retained, expiring
    sensors/room/<room>/humidity_pct    bare float, retained, expiring
    sensors/room/<room>/sample_ts       unix seconds at receipt, same lifetime
    sensors/room/<room>/interval_s      seconds since the previous temperature
    sensors/room/<room>/max_age_s       the window derived from this device

`sample_ts` is the receipt time of the room's last **accepted** sample of any
field - a rejected reading does not advance it, or a dashboard would show
"fresh" over a value that is nothing of the kind. It exists because the expiry
property does not survive the v3.1.1 bridge to Home Assistant, so it is the
only way the age is visible on that side. Informational: nothing in the control
path reads it.

`interval_s` is derived from the temperature source only - the one field every
room has, and the one control depends on.

## The window is learned from the device, not configured

`max_age_s` is the important one, and it exists because **one global number
cannot be right for two devices with a twelve-fold difference in cadence.** The
same Shelly H&T model reports `wakeup_period: 600` on mains and **7200 on
battery**, and the manual's guarantee is "when a reading changes by more than
the configured delta, or every wake period at the latest".

**Both halves of that guarantee are live, and the first one dominates.** The
five consecutive wakes measured exactly 7200 s apart on 2026-08-23 were a quiet
night, not the device's nature: the delta is 0.5 K, and any room crossing it
reports at once. Gästebad has run at `interval_s` 124 and Bad at 420. So the
wake period is a CEILING on silence, not a cadence - which is exactly what a
freshness window needs, and is why this mechanism is unaffected by the
correction. What it does affect is any claim about how much data a battery
room yields; see BACKLOG.

Against the hand-set 900 s, a battery room was therefore stale 88 % of the
time. That is how the bathroom - the room that actually drives the house dew
point - contributed to it for fifteen minutes in every two hours, and why the
local dew point read 12.3 when the true house maximum was 14.1.

So `status/sys` is subscribed per room and the window comes from the device
itself: `wake_factor` x its own reported period, floored at `ttl_s` and capped
at `ttl_max_s`. Nothing to configure per room, nothing to keep in step with a
device someone re-flashes. heatctl reads the published value and adopts it,
within its own clamp - a broker-supplied number may not talk the control core
into believing a measurement for arbitrarily long.

The factor covers **jitter, not a missed wake**: the period is a guarantee, so
silence beyond it means something went wrong and should surface as stale rather
than be smoothed over.

## Rejection, not correction

A payload that will not parse, or a value outside the physical band configured
for that source, is **logged and dropped**. Nothing is published, so the
previous retained value stands until it expires on its own - which is right: a
six-minute-old real reading beats a fresh implausible one, and the value
disappearing by itself is the alarm. The bands are wide on purpose. This module
rejects what cannot be a measurement; deciding what is merely *surprising* is
the control core's job, not the plumbing's (`heatctl/dewpoint.py` refuses 0 %
RH for its own reasons, and should keep doing so).

Rooms are mapped **explicitly** in the config, never inferred from a topic
segment that happens to look like a room name.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass

import aiomqtt
import yaml
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

log = logging.getLogger("normaliser")

TEMPERATURE = "temperature_c"
# The field the normaliser publishes its own derived freshness window on, for
# heatctl to adopt. Named for what a consumer does with it, not for where it
# came from.
MAX_AGE = "max_age_s"

# Wide bands, and only as a default: what cannot be a measurement at all. A
# disconnected channel and a saturated one both land outside these.
DEFAULT_BANDS: dict[str, tuple[float, float]] = {
    TEMPERATURE: (-40.0, 60.0),
    "humidity_pct": (0.0, 100.0),
}


@dataclass(frozen=True)
class Source:
    """One input topic and what it means. `json_key` absent = a bare number."""
    topic: str
    room: str
    field: str
    json_key: str | None = None
    lo: float = -1e9
    hi: float = 1e9


@dataclass(frozen=True)
class Publication:
    """One output message. `expiry_s` None means no expiry (never used for a
    measurement - a measurement without a deadline is the fossil this module
    exists to prevent)."""
    topic: str
    payload: str
    expiry_s: int | None = None
    retain: bool = True


def parse_value(payload: str, json_key: str | None) -> float | None:
    """A sensor payload as a number: bare, or one named field of a JSON object.

    Deliberately the same contract as `heatctl.mqtt_plane.extract`, including
    its refusal to fall back to `float(payload)` when a key is configured and
    missing. Duplicated rather than imported because this process must not
    depend on the control core's package - they ship in different images, and
    the plumbing being unable to break the core is the point.
    """
    if json_key is not None:
        try:
            payload = json.loads(payload)[json_key]
        except (ValueError, TypeError, KeyError):
            return None
    try:
        return float(payload)
    except (TypeError, ValueError):
        return None


class Normaliser:
    """Pure message-in, publications-out. No I/O, so the rules are testable."""

    def __init__(self, sources: list[Source], out_prefix: str, ttl_s: int,
                 wake_topics: dict[str, str] | None = None,
                 wake_factor: float = 1.5, ttl_max_s: int = 14400):
        self.by_topic: dict[str, list[Source]] = {}
        for s in sources:
            self.by_topic.setdefault(s.topic, []).append(s)
        self.out_prefix = out_prefix.rstrip("/")
        self.ttl_s = int(ttl_s)
        # room -> the `status/sys` topic that reports its wake period, and the
        # window learned from it. See `_learn_window`.
        self.wake_topics = {topic: room
                            for room, topic in (wake_topics or {}).items()}
        self.wake_factor = float(wake_factor)
        self.ttl_max_s = int(ttl_max_s)
        self._room_ttl: dict[str, int] = {}
        # Monotonic time of the last accepted sample per (room, field), for
        # `interval_s` and for deciding what is worth logging. Monotonic, not
        # wall clock: an NTP step must not be reported as a wake period.
        self._last: dict[tuple[str, str], float] = {}

    def on_message(self, topic: str, payload: str, *,
                   wall: float, mono: float) -> list[Publication]:
        room = self.wake_topics.get(topic)
        if room is not None:
            # Arrives ~0.1 ms BEFORE the measurements in the same wake
            # (measured 2026-08-23), so the window is already correct by the
            # time the reading it applies to is published.
            return self._learn_window(room, payload)
        sources = self.by_topic.get(topic)
        if not sources:
            # Only reachable if the subscription and the map disagree, which
            # is a bug rather than a sensor problem. Say so.
            log.warning("message on unmapped topic %s", topic)
            return []
        out: list[Publication] = []
        for s in sources:
            v = parse_value(payload, s.json_key)
            if v is None:
                log.warning("%s/%s: unreadable payload on %s: %r",
                            s.room, s.field, topic, payload[:120])
                continue
            if not (s.lo <= v <= s.hi):
                log.warning("%s/%s: %.3f outside [%.1f, %.1f], dropped - the "
                            "previous value stands until it expires",
                            s.room, s.field, v, s.lo, s.hi)
                continue
            prev = self._last.get((s.room, s.field))
            self._last[(s.room, s.field)] = mono
            # AT INFO WHEN A ROOM (RE)APPEARS, DEBUG once it is just running.
            # The gap that matters is `ttl_s`: longer than that and the value
            # had already expired off the broker, so the room really was gone
            # rather than merely slow. Everything in between is the normal
            # sampled cadence and does not need a line every six minutes.
            if prev is None or mono - prev > self.ttl_s:
                log.info("%s/%s: %s%s", s.room, s.field, _fmt(v),
                         "" if prev is None else
                         f" (back after {mono - prev:.0f} s)")
            else:
                log.debug("%s/%s: %s", s.room, s.field, _fmt(v))

            out.append(self._pub(s.room, s.field, _fmt(v)))
            out.append(self._pub(s.room, "sample_ts", f"{wall:.0f}"))
            if s.field == TEMPERATURE and prev is not None and mono > prev:
                out.append(self._pub(s.room, "interval_s",
                                     f"{mono - prev:.0f}"))
        return out

    def _pub(self, room: str, field: str, payload: str) -> Publication:
        return Publication(f"{self.out_prefix}/{room}/{field}", payload,
                           expiry_s=self._room_ttl.get(room, self.ttl_s))

    def _learn_window(self, room: str, payload: str) -> list[Publication]:
        """Derive this room's freshness window from what its device says.

        THE DEVICE KNOWS ITS OWN CADENCE AND WE DO NOT. A Shelly H&T on mains
        reports `wakeup_period: 600`; the same model on battery reports 7200,
        and the manual's guarantee is "when a reading changes by more than the
        configured delta, or every wake period at the latest".

        WE WANT THE SECOND HALF OF THAT GUARANTEE, and only it. The 0.5 K delta
        fires far more often in practice (Gästebad has run at 124 s), but it is
        conditional on the room moving, so nothing may be built on it. The wake
        period is the unconditional bound on silence, which is precisely the
        question `max_age_s` asks.

        So one global `room_temp_max_age_s` cannot be right for both. At 900 s
        a battery room is stale 88 % of the time - which is how the bathroom,
        the room that actually drives the house dew point, contributed to it
        for fifteen minutes in every two hours.

        `wake_factor` covers jitter, NOT a missed wake. That is deliberate: the
        period is a guarantee, so silence beyond it means something went wrong
        and should surface as stale rather than be papered over. 1.5x turns the
        mains device's 600 s into exactly the 900 s that was hand-chosen for
        it, which is a mild reassurance that the factor is sane.

        `ttl_max_s` is the backstop. A device that reported an absurd period -
        misconfigured, or a payload we misread - must not be able to talk us
        into believing a measurement for a day.
        """
        try:
            period = float(json.loads(payload)["wakeup_period"])
        except (ValueError, TypeError, KeyError):
            return []
        if not (1.0 <= period <= 86400.0):
            log.warning("%s: implausible wakeup_period %r, ignored",
                        room, period)
            return []
        ttl = int(min(self.ttl_max_s, max(self.ttl_s, period * self.wake_factor)))
        if self._room_ttl.get(room) == ttl:
            return []
        self._room_ttl[room] = ttl
        log.info("%s: wake period %.0f s -> freshness window %d s",
                 room, period, ttl)
        # RETAINED WITHOUT AN EXPIRY, and it is the one topic here that may be.
        #
        # The first version gave it the room's own window and published it only
        # when it changed. Both are individually reasonable and together they
        # are a bug: the value expired at its own deadline and was never
        # re-published, so within three hours every window vanished from the
        # broker and the next heatctl restart silently reverted every room to
        # the 900 s default. Caught 2026-08-23 by noticing that Wohnzimmer -
        # the shortest window, so the first to go - was missing from the
        # adoptions after a restart while the other two were present.
        #
        # A window is a PROPERTY OF THE DEVICE, not a measurement of the room.
        # It does not go stale when the room stops being sampled; it stops
        # being true only when the device is reconfigured, and then the device
        # tells us and this overwrites it. Nothing is at risk if it outlives
        # the device: the measurements it governs expire on their own, so the
        # room falls back regardless, and heatctl clamps whatever it reads.
        return [Publication(f"{self.out_prefix}/{room}/{MAX_AGE}", str(ttl),
                            expiry_s=None)]

    @property
    def topics(self) -> list[str]:
        return sorted(set(self.by_topic) | set(self.wake_topics))


def _fmt(v: float) -> str:
    """Trim float noise without losing resolution. 23.6 must not become
    23.600000000000001 on a topic a human reads.

    Fixed decimals rather than significant digits: `%.4g` would silently drop
    a digit once a value passed 1000, which is the kind of magnitude-dependent
    surprise that only shows up in the one reading that mattered.
    """
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

def load_sources(cfg: dict) -> list[Source]:
    """Build the source list, failing loudly on anything ambiguous.

    A misconfigured room here becomes a room that silently never updates, so
    every error is fatal at start-up rather than a warning in a log nobody
    reads.
    """
    out: list[Source] = []
    for i, raw in enumerate(cfg.get("sources") or []):
        try:
            topic, room, fld = raw["topic"], raw["room"], raw["field"]
        except KeyError as e:
            raise SystemExit(f"sources[{i}]: missing {e}")
        band = DEFAULT_BANDS.get(fld)
        if band is None and ("min" not in raw or "max" not in raw):
            raise SystemExit(
                f"sources[{i}] ({room}/{fld}): no default plausibility band "
                f"for field {fld!r} - give explicit min/max")
        lo = float(raw.get("min", band[0] if band else 0.0))
        hi = float(raw.get("max", band[1] if band else 0.0))
        if lo >= hi:
            raise SystemExit(f"sources[{i}] ({room}/{fld}): min >= max")
        out.append(Source(topic=topic, room=room, field=fld,
                          json_key=raw.get("json_key"), lo=lo, hi=hi))
    if not out:
        raise SystemExit("no sources configured - nothing to normalise")
    return out


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------

@dataclass
class BrokerConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    retry_s: float = 10.0


def _expiry_properties(seconds: int) -> Properties:
    p = Properties(PacketTypes.PUBLISH)
    p.MessageExpiryInterval = seconds
    return p


async def run(norm: Normaliser, broker: BrokerConfig) -> None:
    """Connect, subscribe, republish. Never exits; reconnects for ever.

    MQTT **5** on this connection, unlike heatctl's - it is the only way to set
    a message-expiry interval. Subscribers may be either version.
    """
    while True:
        try:
            async with aiomqtt.Client(
                broker.host, broker.port,
                username=broker.username, password=broker.password,
                protocol=aiomqtt.ProtocolVersion.V5,
                identifier="normaliser",
            ) as client:
                for t in norm.topics:
                    await client.subscribe(t)
                log.info("connected to %s:%d, %d source topics, ttl %d s",
                         broker.host, broker.port, len(norm.topics),
                         norm.ttl_s)
                async for msg in client.messages:
                    for p in norm.on_message(
                            str(msg.topic), msg.payload.decode(errors="replace"),
                            wall=time.time(), mono=time.monotonic()):
                        await client.publish(
                            p.topic, p.payload, qos=1, retain=p.retain,
                            properties=(_expiry_properties(p.expiry_s)
                                        if p.expiry_s else None))
        except Exception as e:                       # noqa: BLE001
            log.warning("broker connection lost (%s), retry in %.0f s",
                        e, broker.retry_s)
            await asyncio.sleep(broker.retry_s)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config", nargs="?", default="/config/normaliser.yaml")
    args = ap.parse_args()

    with open(args.config) as fh:
        cfg = yaml.safe_load(fh) or {}

    logging.basicConfig(
        level=os.environ.get("NORMALISER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    m = cfg.get("mqtt") or {}
    broker = BrokerConfig(
        host=os.environ.get("NORMALISER_MQTT_HOST") or m.get("host", "mqtt-broker"),
        port=int(os.environ.get("NORMALISER_MQTT_PORT") or m.get("port", 1883)),
        username=os.environ.get("NORMALISER_MQTT_USERNAME") or m.get("username") or None,
        password=os.environ.get("NORMALISER_MQTT_PASSWORD") or m.get("password") or None,
    )
    norm = Normaliser(load_sources(cfg),
                      out_prefix=cfg.get("out_prefix", "sensors/room"),
                      ttl_s=int(cfg.get("ttl_s", 900)),
                      wake_topics=cfg.get("wake_topics") or {},
                      wake_factor=float(cfg.get("wake_factor", 1.5)),
                      ttl_max_s=int(cfg.get("ttl_max_s", 14400)))
    asyncio.run(run(norm, broker))


if __name__ == "__main__":
    main()
