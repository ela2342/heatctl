"""MQTT black box: every message, timestamped, on local disk.

Neither layer 1 nor layer 2, and not even plumbing - this is a **recorder**. It
does not subscribe, decide, or publish. It reads already-formatted records on
stdin and is responsible for exactly three things: which file they go in, when
that file rolls, and when old ones are deleted.

## Why

On 2026-08-21 a cooling ramp drove the supply 1.0 K under the condensation
limit for five minutes and then recovered unaided. That behaviour is now
understood - the capacity loop's raise path spends transient headroom - and it
is understood *only* because someone happened to be sampling six topics by hand
at the time. An earlier ramp the same morning was overridden and produced no
record at all. Whether the plant's own safety enforcer works should not depend
on whether anybody was watching.

heatctl already logs to SQLite, and that is not this: it records what heatctl
**models**, once every `log_every_n_cycles`. The question that mattered was what
the *frequency ceiling* did between two raises, and no model knows to store
that. The MQTT stream is the superset.

## Why `mosquitto_sub` does the subscribing

The first version used aiomqtt and **lost about 40 % of the traffic**: 1496
records against roughly 2500 published in the same minute, with mosquitto
logging `Outgoing messages are being dropped for client journal`. Not because
it was CPU-hungry (6 %) but because this box has one ARMv7 core with no idle
time, so the reader only runs in slices and per-message work in Python loses
the race. `mosquitto_sub` alone, same box and window, kept up completely at
4.35 %. A recorder that drops messages under exactly the load worth
investigating is worse than none, so the MQTT half is C and this is what is
left. Verified after the change: **2376 records against 2366** seen by an
independent subscriber over the identical wall-clock window.

BEWARE THE MEASUREMENT. Comparing against a freshly-connected `mosquitto_sub`
overstates the loss by the **retained snapshot** - 809 messages here - which a
new subscriber receives at connect and a long-running recorder never sees. That
artifact is what made the working version look 25 % short, and it cost two
rounds of chasing a bug that was not there. Compare by wall-clock window on the
timestamps, not by counting lines.

`mosquitto_sub -F '%U %t %p'` already emits the target format, so this process
does no formatting in the common case - it parses one float per line to decide
which day-file the record belongs to, and writes.

## The record

    <epoch.nanos> <topic> <payload>

Space-separated, payload last so it may contain spaces and needs no quoting.
Plain text on purpose: `grep`, `awk` and `zgrep` are the query language, they
will still exist in thirty years, and a truncated line at the end of a crashed
file costs one message rather than a corrupt database.

Files roll at UTC midnight and the closed one is gzipped; this traffic
compresses roughly 10:1, so a day costs tens of MB against the card's 110 GB
free. `JOURNAL_RETAIN_DAYS` prunes the tail.

## One message is one line, and `mosquitto_sub` does not guarantee that

It does not escape newlines in payloads, so a multi-line payload arrives here
as several lines. That is recoverable rather than fatal, because **a real
record always begins with a plausible epoch timestamp**: any line that does not
is a continuation, and gets folded back into the previous record with its
newline escaped. The invariant is restored on the way to disk.

The residual ambiguity is a payload whose own second line begins with a number
that looks like a current unix timestamp. `looks_like_record` requires the
leading token to parse as a float inside a sane epoch window, which makes that
unlikely rather than impossible. Noted rather than solved.

## What it is careful about

- **It cannot perturb the plant.** No Modbus, no broker write permission (the
  `journal` account has `topic read #` and no write rule), its own container at
  `--cpu-shares 128` so heatctl wins the core 8:1 under contention.
- **It does not fsync per message.** Worst-case loss is the buffered second.
- **Its own failures are visible in what it records.** A gap in the timestamps
  is the outage; there is no separate health topic to go stale.
"""
from __future__ import annotations

import gzip
import io
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("journal")

# Bounds for "is this a record or a continuation line". 2023-11-14 to 2096-10-02
# - wide enough never to reject a real record, narrow enough that a payload
# would have to contain a plausible current timestamp to be mistaken for one.
EPOCH_MIN = 1_700_000_000.0
EPOCH_MAX = 4_000_000_000.0


def day_key(now: float) -> str:
    """UTC date stamp for the file a record at `now` belongs in.

    UTC, not local: the roll must not happen twice on one October night, nor
    skip an hour in March. The record timestamps are epoch anyway.
    """
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%d")


def looks_like_record(line: str) -> float | None:
    """The record's timestamp, or None if this is a payload continuation."""
    head = line.partition(" ")[0]
    try:
        ts = float(head)
    except ValueError:
        return None
    return ts if EPOCH_MIN <= ts <= EPOCH_MAX else None


def escape(text: str) -> str:
    """Escape what would otherwise forge a record boundary. Backslash first, or
    a literal backslash-n becomes indistinguishable from a real newline."""
    return (text.replace("\\", "\\\\").replace("\n", "\\n")
                .replace("\r", "\\r"))


def prune(dirpath: Path, retain_days: int, now: float) -> list[Path]:
    """Delete gzipped days older than `retain_days`. Returns what it removed.

    Works on the NAME, not the mtime: gzipping rewrites the mtime, and
    restoring a backup resets all of them at once - which is exactly when
    deleting the history would be worst.
    """
    if retain_days <= 0:
        return []
    cutoff = (datetime.fromtimestamp(now, timezone.utc)
              - timedelta(days=retain_days)).strftime("%Y%m%d")
    gone = []
    for f in sorted(dirpath.glob("mqtt-*.log.gz")):
        stamp = f.name[len("mqtt-"):-len(".log.gz")]
        if len(stamp) == 8 and stamp.isdigit() and stamp < cutoff:
            f.unlink()
            gone.append(f)
    return gone


class Journal:
    """Append-only writer with a daily roll."""

    def __init__(self, dirpath: Path | str, retain_days: int = 90,
                 flush_interval_s: float = 1.0):
        self.dir = Path(dirpath)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.retain_days = int(retain_days)
        self.flush_interval_s = float(flush_interval_s)
        self._day: str | None = None
        self._fh = None
        self._last_flush = 0.0
        self.written = 0
        # THE RECORD IN HAND, not yet terminated. A record is only complete
        # once the next one starts, because until then the following input line
        # may turn out to be a continuation of this payload rather than a new
        # message. Holding one record is the whole cost of keeping "one message
        # is one line" true against a source that does not guarantee it.
        self._pending: tuple[float, str] | None = None
        self._sec: int | None = None
        self._sec_day: str | None = None

    def path_for(self, day: str) -> Path:
        return self.dir / f"mqtt-{day}.log"

    def write(self, ts: float, line: str) -> None:
        """`line` is the WHOLE record as `mosquitto_sub` emitted it.

        Stored VERBATIM: it is already the target format, so re-parsing and
        re-formatting it would spend a float format and a string build per
        message to produce the same bytes, and would round `mosquitto_sub`'s
        sub-second precision to milliseconds on the way.

        Honest provenance: this and the cached day lookup below were written to
        close a 25 % capture gap that turned out to be a measurement artifact
        (see the module docstring). They are cheaper and simpler than what they
        replaced, so they stayed - but no measurement shows they were needed.
        """
        self._commit()
        self._pending = (ts, escape(line) if "\\" in line else line)

    def append_continuation(self, text: str) -> None:
        """A payload line that carried a newline. Folded into the record in
        hand with the break escaped, so it stays one line on disk."""
        if self._pending is None:
            return          # continuation with nothing to continue; drop it
        ts, sofar = self._pending
        self._pending = (ts, f"{sofar}\\n{escape(text)}")

    def _commit(self) -> None:
        if self._pending is None:
            return
        ts, text = self._pending
        self._pending = None
        # DAY LOOKUP IS CACHED PER WHOLE SECOND. `day_key` builds a datetime
        # and formats it, and the answer can only change once a second - so
        # doing it per message was about fifty times more often than useful.
        sec = int(ts)
        if sec != self._sec:
            self._sec = sec
            self._sec_day = day_key(ts)
        day = self._sec_day
        if day != self._day:
            self._roll(day, ts)
        self._fh.write(text)
        self._fh.write("\n")
        self.written += 1
        if ts - self._last_flush >= self.flush_interval_s:
            self._fh.flush()
            self._last_flush = ts

    def _roll(self, day: str, now: float) -> None:
        closed = None
        if self._fh is not None:
            self._fh.close()
            closed = self.path_for(self._day)
        self._day = day
        # APPEND, never truncate. A restart mid-day must not discard the
        # morning - which is the half most likely to explain why it restarted.
        self._fh = open(self.path_for(day), "a", buffering=1 << 16)
        self._last_flush = now
        if closed is not None and closed.exists():
            self._compress(closed)
        for f in prune(self.dir, self.retain_days, now):
            log.info("pruned %s", f.name)

    def _compress(self, path: Path) -> None:
        """gzip the closed day. The original is unlinked only after the archive
        is complete, so an interrupted compression leaves a partial `.gz`
        beside an intact `.log` and the next roll overwrites it."""
        gz = path.with_suffix(".log.gz")
        try:
            raw_mb = path.stat().st_size / 1e6
            with open(path, "rb") as src, gzip.open(gz, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
            path.unlink()
            log.info("archived %s: %.1f MB -> %.1f MB", gz.name, raw_mb,
                     gz.stat().st_size / 1e6)
        except OSError as e:
            log.warning("could not archive %s: %s", path.name, e)

    def close(self) -> None:
        self._commit()
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None
            self._day = None


def pump(stream, journal: Journal, log_every: int = 100_000) -> None:
    """Read records from `stream` until it ends. Malformed input never stops
    the recorder - a line that cannot be placed is still worth keeping."""
    for raw in stream:
        line = raw.rstrip("\n")
        if not line:
            continue
        ts = looks_like_record(line)
        if ts is None:
            journal.append_continuation(line)
            continue
        journal.write(ts, line)
        if journal.written % log_every == 0:
            log.info("%d records", journal.written)


def main() -> None:
    # Line-buffered explicitly, so the container does not need
    # PYTHONUNBUFFERED to make the log readable - see the stdin note below for
    # what that variable costs when it applies to the whole process.
    sys.stderr.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=os.environ.get("JOURNAL_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    journal = Journal(
        os.environ.get("JOURNAL_DIR", "/data"),
        retain_days=int(os.environ.get("JOURNAL_RETAIN_DAYS", "90")),
        flush_interval_s=float(os.environ.get("JOURNAL_FLUSH_S", "1.0")))
    # Roll and prune once at start-up, so a machine that was off over a day
    # boundary still archives and expires without waiting for the next roll.
    now = time.time()
    journal.write(now, f"{now:.3f} journal/started 1")
    log.info("recording into %s, retain %d days",
             journal.dir, journal.retain_days)
    # STDIN IS WRAPPED WITH AN EXPLICIT LARGE BUFFER so that the process does
    # not depend on how it was launched. `PYTHONUNBUFFERED=1` applies to stdin
    # as well as the log streams, which would turn `for line in sys.stdin` into
    # roughly one read() syscall per message; reading through our own 256 KB
    # buffer takes the environment variable out of the hot path. Defensive
    # rather than demonstrated - it was written while chasing a capture gap
    # that proved to be a measurement artifact.
    stream = io.TextIOWrapper(open(0, "rb", buffering=1 << 18),
                              encoding="utf-8", errors="replace")
    try:
        pump(stream, journal)
    except KeyboardInterrupt:
        pass
    finally:
        journal.close()
        log.info("stopped after %d records", journal.written)


if __name__ == "__main__":
    main()
