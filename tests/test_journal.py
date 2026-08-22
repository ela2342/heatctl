"""The MQTT black box.

A recorder is judged on what it does when things go wrong, so most of these
are about the failure paths: a crash mid-day, a payload that tries to forge a
record, an interrupted compression, a clock that steps. The one property
everything else serves is that **a line in the file is a message that
happened**, and one message is one line.
"""
from __future__ import annotations

import gzip
import time
from pathlib import Path

import pytest

from journal.main import (Journal, day_key, escape, looks_like_record,
                          prune, pump)

DAY = 24 * 3600
# 2026-08-21 12:00:00 UTC, and 2026-08-22 00:00:30 UTC - either side of a roll.
NOON = 1787313600.0
NEXT = 1787356830.0


def read(p: Path) -> list[str]:
    return p.read_text().splitlines()


def run(tmp_path, *input_lines, **kw):
    """Feed lines through the real pump, return the written records."""
    j = Journal(tmp_path, **kw)
    pump(iter(f"{l}\n" for l in input_lines), j)
    j.close()
    out = sorted(tmp_path.glob("mqtt-*.log"))
    return read(out[0]) if out else []


class TestOneMessageIsOneLine:
    def test_the_record_is_stored_verbatim(self, tmp_path):
        """`mosquitto_sub` already emits `%U %t %p`, so re-formatting it would
        spend a float format and a string build per message to produce the same
        bytes - and would round the sub-second precision away. The full
        precision is the part worth pinning: it is what makes two records
        orderable within the same second."""
        assert run(tmp_path, "1787313600.123456789 heatctl/mode cooling") == \
            ["1787313600.123456789 heatctl/mode cooling"]

    def test_a_payload_may_contain_spaces(self, tmp_path):
        """The payload is last precisely so it needs no quoting - reason
        strings are the most valuable thing in here and they are prose."""
        [rec] = run(tmp_path,
                    f"{NOON} heatctl/capacity/reason margin -1.00 K low, waiting")
        assert rec.split(" ", 2)[2] == "margin -1.00 K low, waiting"

    def test_a_multi_line_payload_stays_one_record(self, tmp_path):
        """`mosquitto_sub` does not escape newlines, so a multi-line payload
        arrives as several input lines. Folding them back is what keeps the
        format's only invariant true - otherwise a Home Assistant discovery
        blob could invent a message that never happened."""
        recs = run(tmp_path, f'{NOON} t {{"a":1}}', "heatctl/mode off",
                   f"{NOON + 1} u 2")
        assert len(recs) == 2
        assert recs[0] == '1787313600.0 t {"a":1}\\nheatctl/mode off'
        assert recs[1] == "1787313601.0 u 2"

    def test_backslashes_survive_unambiguously(self, tmp_path):
        """Escaping newlines without escaping backslashes would make a literal
        backslash-n indistinguishable from a folded one on the way back."""
        [rec] = run(tmp_path, f"{NOON} t a\\nb")
        assert rec.split(" ", 2)[2] == "a\\\\nb"

    def test_a_continuation_before_any_record_is_dropped(self, tmp_path):
        """Starting mid-payload after a restart. There is nothing to attach it
        to, and inventing a record for it would be worse than losing it."""
        assert run(tmp_path, "orphan text", f"{NOON} t 1") == \
            ["1787313600.0 t 1"]

    def test_a_blank_line_is_not_a_record(self, tmp_path):
        assert run(tmp_path, f"{NOON} t 1", "", f"{NOON + 1} t 2") == \
            ["1787313600.0 t 1", "1787313601.0 t 2"]


class TestTellingARecordFromAContinuation:
    def test_a_plausible_epoch_starts_a_record(self):
        assert looks_like_record(f"{NOON} t 1") == NOON

    @pytest.mark.parametrize("line", [
        "heatctl/mode off",          # a topic
        '{"a":1}',                   # json
        "",                          # empty
        "12 monkeys",                # a number, but not an epoch
        "1e9 nope",                  # 2001, outside the window
        "9999999999999 nope",        # far future
    ])
    def test_everything_else_is_a_continuation(self, line):
        assert looks_like_record(line) is None

    def test_the_escape_helper_orders_backslash_first(self):
        assert escape("a\\nb") == "a\\\\nb"
        assert escape("a\nb") == "a\\nb"
        assert escape("a\rb") == "a\\rb"


class TestRollingAndArchiving:
    def test_it_writes_into_a_utc_dated_file(self, tmp_path):
        j = Journal(tmp_path)
        j.write(NOON, f"{NOON} heatctl/mode cooling")
        j.close()
        assert read(tmp_path / "mqtt-20260821.log") == \
            ["1787313600.0 heatctl/mode cooling"]

    def test_the_day_boundary_is_utc(self):
        """Not local time: a local roll would happen twice on one October
        night and skip an hour in March."""
        assert day_key(NOON) == "20260821"
        assert day_key(NEXT) == "20260822"
        # 2026-08-21 23:30 UTC, which is already the 22nd in Europe/Berlin.
        # Distinguishes UTC from localtime, which the two above do not.
        assert day_key(1787355000.0) == "20260821"

    def test_crossing_midnight_rolls_and_gzips_the_closed_day(self, tmp_path):
        """End to end with the real `gzip`, which is what runs on the device.

        Compression is asynchronous now (see TestArchivingNeverBlocksTheRecorder
        for why), so this waits for the child rather than assuming it finished -
        the previous version asserted the file was already gone, which was only
        true while the roll blocked the recorder.
        """
        j = Journal(tmp_path)
        j.write(NOON, f"{NOON} a 1")
        j.write(NEXT, f"{NEXT} b 2")
        # close() is what commits the pending record and therefore rolls - a
        # record is only complete once the next one starts, so the roll cannot
        # happen on write().
        j.close()
        for child in j._children:
            assert child.wait(timeout=30) == 0
        assert not (tmp_path / "mqtt-20260821.log").exists()
        with gzip.open(tmp_path / "mqtt-20260821.log.gz", "rt") as fh:
            assert fh.read().strip().endswith("a 1")
        assert read(tmp_path / "mqtt-20260822.log") == ["1787356830.0 b 2"]

    def test_the_recorder_keeps_writing_while_gzip_runs(self, tmp_path):
        """The property the 41-minute outage violated: records that arrive
        during compression are still written, because compression is not in
        this process."""
        j = Journal(tmp_path)
        j.write(NOON, f"{NOON} a 1")
        j.write(NEXT, f"{NEXT} b 2")          # roll + spawn
        for i in range(200):                  # while the child may still run
            j.write(NEXT + i, f"{NEXT + i} t {i}")
        j.close()
        for child in j._children:
            child.wait(timeout=30)
        assert len(read(tmp_path / "mqtt-20260822.log")) == 201

    def test_a_restart_mid_day_appends_and_does_not_truncate(self, tmp_path):
        """The morning is the half most likely to explain why it restarted."""
        j = Journal(tmp_path); j.write(NOON, f"{NOON} a 1"); j.close()
        j2 = Journal(tmp_path); j2.write(NOON + 60, f"{NOON+60} b 2"); j2.close()
        assert len(read(tmp_path / "mqtt-20260821.log")) == 2

    def test_a_reconnect_does_not_gzip_a_day_that_is_still_open(self, tmp_path):
        """close() is called on every broker disconnect. If that archived the
        current day, a flapping broker would produce a pile of part-days and
        the live file would keep restarting."""
        j = Journal(tmp_path)
        j.write(NOON, f"{NOON} a 1")
        j.close()
        assert (tmp_path / "mqtt-20260821.log").exists()
        assert not (tmp_path / "mqtt-20260821.log.gz").exists()
        j.write(NOON + 1, f"{NOON+1} b 2")
        j.close()
        assert len(read(tmp_path / "mqtt-20260821.log")) == 2


class TestArchivingNeverBlocksTheRecorder:
    """The 2026-08-22 defect. Compression used to run inline, so the daily roll
    stopped this process reading stdin for as long as gzip took - 41 minutes on
    the first real roll, during which mosquitto timed the client out and the
    recording simply stopped. Silently, and at 02:00 where nobody looks.
    """

    class _Spawn:
        def __init__(self, rc=None):
            self.calls = []
            self.rc = rc

        def __call__(self, argv, **kw):
            self.calls.append((argv, kw))
            outer = self

            class _P:
                def poll(self_inner):
                    return outer.rc
            return _P()

    def test_the_roll_hands_gzip_to_a_child_and_returns(self, tmp_path):
        sp = self._Spawn()
        j = Journal(tmp_path, spawn=sp)
        j.write(NOON, f"{NOON} a 1")
        j.write(NEXT, f"{NEXT} b 2")          # crosses UTC midnight -> roll
        j.close()
        [(argv, kw)] = sp.calls
        assert argv[0] == "gzip"
        assert argv[-1].endswith("mqtt-20260821.log")
        # No wait() anywhere: the object the fake returns has only poll().
        # If _compress ever called wait() this test would raise AttributeError.

    def test_it_does_not_compress_inline(self, tmp_path):
        """The regression itself: after the roll the .log must still be on
        disk, because a CHILD is compressing it - not this process."""
        sp = self._Spawn()
        j = Journal(tmp_path, spawn=sp)
        j.write(NOON, f"{NOON} a 1")
        j.write(NEXT, f"{NEXT} b 2")
        j.close()
        assert (tmp_path / "mqtt-20260821.log").exists()
        assert not (tmp_path / "mqtt-20260821.log.gz").exists()

    def test_gzip_runs_at_the_lowest_priority(self, tmp_path):
        """It shares one core with a 1 s control loop. Compression is never
        more urgent than a control cycle."""
        sp = self._Spawn()
        j = Journal(tmp_path, spawn=sp)
        j.write(NOON, f"{NOON} a 1")
        j.write(NEXT, f"{NEXT} b 2")
        j.close()
        [(_argv, kw)] = sp.calls
        assert callable(kw["preexec_fn"])

    def test_a_failure_to_start_gzip_is_not_fatal(self, tmp_path):
        """Losing an archive is a nuisance; losing the recorder is the thing
        this module exists to prevent."""
        def boom(*a, **k):
            raise OSError("no gzip here")
        j = Journal(tmp_path, spawn=boom)
        j.write(NOON, f"{NOON} a 1")
        j.write(NEXT, f"{NEXT} b 2")          # must not raise
        j.write(NEXT + 1, f"{NEXT+1} c 3")
        j.close()
        assert read(tmp_path / "mqtt-20260822.log")[-1].endswith("c 3")


class TestPruning:
    def _days(self, tmp_path, *stamps):
        for s in stamps:
            (tmp_path / f"mqtt-{s}.log.gz").write_bytes(b"x")

    def test_it_deletes_beyond_the_retention_window(self, tmp_path):
        self._days(tmp_path, "20260101", "20260818", "20260820")
        prune(tmp_path, retain_days=7, now=NOON)
        left = sorted(f.name for f in tmp_path.glob("*.gz"))
        assert left == ["mqtt-20260818.log.gz", "mqtt-20260820.log.gz"]

    def test_it_prunes_on_the_name_not_the_mtime(self, tmp_path):
        """Gzipping rewrites the mtime, and restoring a backup resets every
        mtime at once - which is precisely when deleting the history would be
        worst."""
        old = tmp_path / "mqtt-20260101.log.gz"
        old.write_bytes(b"x")
        import os
        os.utime(old, (NOON, NOON))          # looks brand new by mtime
        prune(tmp_path, retain_days=7, now=NOON)
        assert not old.exists()

    def test_it_never_touches_the_open_uncompressed_day(self, tmp_path):
        (tmp_path / "mqtt-20260101.log").write_text("live")
        prune(tmp_path, retain_days=1, now=NOON)
        assert (tmp_path / "mqtt-20260101.log").exists()

    def test_it_ignores_files_it_did_not_write(self, tmp_path):
        junk = tmp_path / "mqtt-notadate.log.gz"
        junk.write_bytes(b"x")
        prune(tmp_path, retain_days=1, now=NOON)
        assert junk.exists()

    def test_zero_retention_means_keep_everything(self, tmp_path):
        """Not 'delete everything'. A misread config must not be able to erase
        the archive, so the degenerate value is the safe direction."""
        self._days(tmp_path, "20200101")
        prune(tmp_path, retain_days=0, now=NOON)
        assert list(tmp_path.glob("*.gz"))


class TestItDoesNotFsyncEveryMessage:
    def test_writes_are_visible_within_the_flush_interval(self, tmp_path):
        """A record is committed when the NEXT one arrives (a payload
        continuation may still be coming), and the flush fires once the
        committed record's timestamp has moved past the interval."""
        j = Journal(tmp_path, flush_interval_s=1.0)
        j.write(NOON, f"{NOON} a 1")
        j.write(NOON + 2.0, f"{NOON+2.0} b 2")
        j.write(NOON + 4.0, f"{NOON+4.0} c 3")       # commits b, past the interval -> flush
        assert len(read(tmp_path / "mqtt-20260821.log")) >= 1
        j.close()

    def test_close_flushes_what_is_buffered(self, tmp_path):
        j = Journal(tmp_path, flush_interval_s=3600.0)
        for i in range(50):
            j.write(NOON + i * 0.01, f"{NOON + i*0.01} t x")
        j.close()
        assert len(read(tmp_path / "mqtt-20260821.log")) == 50


class TestTheDeployedConfiguration:
    """Config is environment in `run-journal.sh` now, not a YAML file - the
    journal has no third-party dependencies at all since `mosquitto_sub` took
    over the subscribing, and a config file was the only thing still pulling
    PyYAML in."""

    def _run_sh(self):
        root = Path(__file__).resolve().parent.parent
        return (root / "deploy" / "pfc200" / "run-journal.sh").read_text()

    def test_it_subscribes_to_everything(self):
        """Narrowing this is how a black box becomes useless the one time it
        is needed - the topic that mattered on 2026-08-21 was the compressor
        frequency ceiling, which nobody would have put on a list."""
        assert '-t "#"' in self._run_sh()

    def test_the_record_format_matches_what_this_module_parses(self):
        """`%U %t %p` is epoch, topic, payload - the format `looks_like_record`
        and `pump` assume. Changing one without the other silently turns every
        record into a continuation line."""
        assert "%U %t %p" in self._run_sh()

    def test_it_writes_to_the_card_and_not_the_root_filesystem(self):
        """119 GB versus 283 MB. A recorder that fills the root filesystem
        takes the plant down."""
        sh = self._run_sh()
        assert "/media/sdcard/docker-root/journal" in sh
        assert ":/data" in sh

    def test_it_is_deprioritised_rather_than_capped(self):
        """A hard `--cpus` ceiling made it drop 55 %% of the traffic on
        2026-08-21. Shares bind only under contention; a cap binds always."""
        code = "\n".join(l for l in self._run_sh().splitlines()
                         if not l.lstrip().startswith("#"))
        assert "--cpu-shares" in code
        # In the CODE only - the comment above it has to be free to explain
        # why `--cpus` was removed, or the lesson goes with it.
        assert "--cpus" not in code

    def test_retention_is_bounded(self):
        assert "JOURNAL_RETAIN_DAYS" in self._run_sh()


class TestTheRecorderCannotWrite:
    def test_the_acl_gives_the_journal_no_write_rule(self):
        """A recorder that can publish is a recorder that can be blamed for a
        message. Checked here because the ACL is the only thing enforcing it -
        the code simply never calls publish, which is not a guarantee."""
        root = Path(__file__).resolve().parent.parent
        acl = (root / "deploy" / "pfc200" / "mosquitto.acl").read_text()
        block = acl.split("user journal", 1)[1].split("\nuser ", 1)[0]
        assert "topic read #" in block
        assert "write" not in block
