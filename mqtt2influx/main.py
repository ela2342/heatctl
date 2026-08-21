"""Forward the MQTT stream into the InfluxDB that already exists on the HA host.

The query half of the debugging story. `journal/` on the PFC is the other half,
and the split is deliberate:

    journal/     everything, forever-ish, on the 119 GB card next to the plant.
                 Survives the network. Answers "what exactly happened at
                 11:47:49" with zgrep. No query engine.
    mqtt2influx/ the measurement stream, a bounded window, on the box that
                 already has InfluxDB, Grafana and Chronograf. Answers "show me
                 the ceiling against the margin for the last week" as a graph.

Neither replaces the other, and the space is where the difference bites: the
PFC has **110 GB free**, the Home Assistant host has **9.4 GB** (83 % full,
measured 2026-08-21). So the long history lives with the plant and the short
queryable window lives with the query engine. `retention_days` is not a tuning
knob here, it is what stops a debugging tool filling the disk that Home
Assistant, the broker and the bridge all run on.

## Why not Telegraf

It is the obvious answer and it would work. It is not installed, there is no
Telegraf add-on in the repositories this Supervisor has, and adding a
third-party repository to get a Go binary is a larger permanent dependency than
these ~120 lines against the two libraries the project already pins. If that
trade ever looks wrong, the schema below is Telegraf's default `mqtt_consumer`
shape and swapping is a configuration change, not a migration.

## Schema

One measurement, one tag, two possible fields:

    mqtt,topic=heatctl/temp/vl_total value=24.1 1787313600000000000
    mqtt,topic=heatctl/capacity/reason text="margin -1.00 K low, ..." ...

Numeric payloads become `value`, everything else becomes `text`. Keeping the
strings is the point rather than an afterthought - `capacity/reason` and
`water_sp/reason` explain every decision the plant makes, and a debugging store
that dropped them would have been useless for the one investigation that
prompted it.

`topic` as a TAG makes it indexed and templatable in Grafana. 759 distinct
topics is unremarkable cardinality for InfluxDB 1.x.

## What it will not do

- **It never blocks the plant, because it cannot reach it.** It runs on the
  Home Assistant host, subscribes read-only, and writes to a database.
- **It drops rather than grows.** If InfluxDB is down the batch is discarded
  after one retry and the gap is the record, exactly as in `journal/`. An
  unbounded buffer in a forwarder is how a forwarder becomes the outage.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import aiomqtt

log = logging.getLogger("mqtt2influx")

MEASUREMENT = "mqtt"
# Long enough for every reason string the plant emits; short enough that a
# retained Home Assistant discovery blob cannot bloat a shard if someone widens
# `topics` to include one.
MAX_TEXT = 512


def esc_tag(s: str) -> str:
    """Line-protocol tag escaping: comma, equals, space, backslash.

    MQTT topics do not normally contain any of these, which is precisely why
    it would go unnoticed the day one does.
    """
    return (s.replace("\\", "\\\\").replace(",", "\\,")
             .replace("=", "\\=").replace(" ", "\\ "))


def esc_str_field(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def line(topic: str, payload: str, ts_ns: int) -> str | None:
    """One point, or None if the payload carries nothing to store.

    An empty payload is a RETAIN CLEAR, not a measurement of zero - the
    normaliser and the operator both use it that way, and recording it as a
    number would put a spurious zero in the middle of a graph.
    """
    if payload == "":
        return None
    tag = f"{MEASUREMENT},topic={esc_tag(topic)}"
    try:
        v = float(payload)
    except ValueError:
        text = payload[:MAX_TEXT]
        return f'{tag} text="{esc_str_field(text)}" {ts_ns}'
    # NaN and infinity are not storable and are not measurements either.
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return f"{tag} value={v} {ts_ns}"


class Writer:
    """Batches points and POSTs them. Synchronous on purpose - it is called
    from a thread so the event loop keeps draining the subscription."""

    def __init__(self, url: str, db: str, user: str | None, password: str | None,
                 batch_max: int = 2000, timeout_s: float = 10.0):
        self.url = url.rstrip("/")
        self.db = db
        self.user = user
        self.password = password
        self.batch_max = int(batch_max)
        self.timeout_s = float(timeout_s)
        self.dropped = 0
        self.written = 0
        # Remembered only so the "create the database" hint can quote the
        # duration the operator should use.
        self.retention = "30d"
        # Persistent failures are logged at most this often - see write().
        self.complain_every_s = 60.0
        self._last_complaint = -1e9

    def _request(self, path: str, data: bytes, query: dict) -> None:
        q = dict(query)
        if self.user:
            q["u"] = self.user
            q["p"] = self.password or ""
        req = urllib.request.Request(
            f"{self.url}{path}?{urllib.parse.urlencode(q)}", data=data,
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            r.read()

    def ensure_db(self, retention_days: int) -> None:
        """Create the database if we are allowed to, and say which case we are
        in. Re-running CREATE DATABASE is not an error in InfluxQL.

        The retention policy is set WITH the database rather than left at
        InfluxDB's default of `INF`, because infinite retention on a host with
        9.4 GB free is a slow-motion outage.

        THE NORMAL CASE HERE IS A 403. The Home Assistant InfluxDB account is
        not an admin, so this only succeeds where someone has granted more.
        That is fine when the database already exists - and saying "403,
        continuing" every start, as the first version did, reads like a fault
        when it is the expected state. So a refusal is checked against whether
        the database is actually there, and only the genuinely broken case
        warns.
        """
        dur = f"{int(retention_days)}d" if retention_days > 0 else "INF"
        self.retention = dur
        stmt = f'CREATE DATABASE "{self.db}" WITH DURATION {dur}'
        try:
            self._request("/query",
                          urllib.parse.urlencode({"q": stmt}).encode(), {})
            log.info("database %s created or confirmed, retention %s",
                     self.db, dur)
            return
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
        if self.db in self.databases():
            log.info("database %s exists; this account cannot verify its "
                     "retention policy, which needs admin", self.db)
        else:
            log.warning(
                "database %r does not exist and this account cannot create "
                'it. As an InfluxDB ADMIN, once:  CREATE DATABASE "%s" WITH '
                'DURATION %s ;  GRANT ALL ON "%s" TO "%s"',
                self.db, self.db, dur, self.db, self.user)

    def databases(self) -> set[str]:
        """Names visible to this account, or an empty set if it cannot ask."""
        try:
            q = {"q": "SHOW DATABASES"}
            if self.user:
                q["u"], q["p"] = self.user, self.password or ""
            with urllib.request.urlopen(
                    f"{self.url}/query?{urllib.parse.urlencode(q)}",
                    timeout=self.timeout_s) as r:
                data = json.load(r)
            series = data["results"][0].get("series") or [{}]
            return {v[0] for v in series[0].get("values", [])}
        except Exception:                            # noqa: BLE001
            return set()

    def write(self, lines: list[str]) -> bool:
        if not lines:
            return True
        body = ("\n".join(lines) + "\n").encode()
        for attempt in (1, 2):
            try:
                self._request("/write", body,
                              {"db": self.db, "precision": "ns"})
                self.written += len(lines)
                return True
            except (urllib.error.URLError, OSError) as e:
                if attempt == 2:
                    # DROP, do not accumulate. The gap is the record.
                    self.dropped += len(lines)
                    # THROTTLED. A missing database or a stopped InfluxDB is a
                    # condition, not an event: at one flush every five seconds
                    # it would write seventeen thousand identical lines a day
                    # and bury whatever else the log had to say. Same reasoning
                    # as heatctl's failsafe logging. The running total is on
                    # every line that does get written, so nothing is hidden.
                    now = time.monotonic()
                    if now - self._last_complaint >= self.complain_every_s:
                        self._last_complaint = now
                        log.warning("dropping points (%s); %d dropped in "
                                    "total", e, self.dropped)
                    # THE ONE FAILURE WORTH NAMING. The Home Assistant
                    # InfluxDB account is not an admin (verified 2026-08-21:
                    # CREATE DATABASE returns "requires admin privilege"), so
                    # if nobody has made the database this will fail for ever
                    # while looking like a transient network problem.
                    if (getattr(e, "code", None) in (403, 404)
                            and now == self._last_complaint):
                        log.warning(
                            "database %r is missing or not writable by this "
                            "account. As an InfluxDB ADMIN, once:  "
                            'CREATE DATABASE "%s" WITH DURATION %s ;  '
                            'GRANT ALL ON "%s" TO "%s"',
                            self.db, self.db, self.retention, self.db,
                            self.user)
                    return False
                time.sleep(1.0)
        return False


async def run(writer: Writer, host: str, port: int, username: str | None,
              password: str | None, topics: list[str],
              flush_interval_s: float = 5.0, retry_s: float = 10.0) -> None:
    pending: list[str] = []
    last_flush = time.monotonic()

    async def flush() -> None:
        nonlocal pending, last_flush
        batch, pending = pending, []
        last_flush = time.monotonic()
        if batch:
            await asyncio.to_thread(writer.write, batch)

    while True:
        try:
            async with aiomqtt.Client(host, port, username=username,
                                      password=password,
                                      identifier="mqtt2influx") as client:
                for t in topics:
                    await client.subscribe(t, qos=0)
                log.info("forwarding %s from %s:%d to %s/%s",
                         ",".join(topics), host, port, writer.url, writer.db)
                async for msg in client.messages:
                    pt = line(str(msg.topic),
                              msg.payload.decode("utf-8", errors="replace"),
                              time.time_ns())
                    if pt is not None:
                        pending.append(pt)
                    if (len(pending) >= writer.batch_max
                            or time.monotonic() - last_flush >= flush_interval_s):
                        await flush()
        except Exception as e:                       # noqa: BLE001
            log.warning("broker connection lost (%s), retry in %.0f s",
                        e, retry_s)
            await flush()
            await asyncio.sleep(retry_s)


def load_options() -> dict:
    """Home Assistant App options. Read straight from the Supervisor's
    options.json rather than through bashio - one less layer between the
    manifest and the code, and it makes the whole thing importable in a test."""
    path = os.environ.get("OPTIONS_JSON", "/data/options.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        log.warning("no usable %s (%s), falling back to the environment", path, e)
        return {}


def main() -> None:
    opts = load_options()
    logging.basicConfig(
        level=str(opts.get("log_level", "info")).upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    writer = Writer(
        url=opts.get("influx_url") or "http://a0d7b954-influxdb:8086",
        db=opts.get("influx_db") or "mqtt",
        user=opts.get("influx_username") or None,
        password=opts.get("influx_password") or None,
        batch_max=int(opts.get("batch_max", 2000)))
    try:
        writer.ensure_db(int(opts.get("retention_days", 30)))
    except (urllib.error.URLError, OSError) as e:
        # NOT fatal: the database usually already exists, and refusing to start
        # because a one-time setup call failed would make an outage permanent.
        log.warning("could not create/verify the database (%s) - continuing", e)

    asyncio.run(run(
        writer,
        # Options win; the environment is what run.sh got from the Supervisor.
        # Both fall back, because the broker credentials are not knowable at
        # the time the options file is written.
        host=opts.get("mqtt_host") or os.environ.get("MQTT_HOST") or "core-mosquitto",
        port=int(opts.get("mqtt_port") or os.environ.get("MQTT_PORT") or 1883),
        username=(opts.get("mqtt_username")
                  or os.environ.get("MQTT_USERNAME") or None),
        password=(opts.get("mqtt_password")
                  or os.environ.get("MQTT_PASSWORD") or None),
        topics=list(opts.get("topics") or ["heatctl/#", "sensors/#"]),
        flush_interval_s=float(opts.get("flush_interval_s", 5.0))))


if __name__ == "__main__":
    main()
