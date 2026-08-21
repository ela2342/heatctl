"""MQTT -> InfluxDB forwarding: the line protocol and what is refused.

A forwarder's damage is quiet: a mis-escaped tag makes a series unqueryable, a
retain-clear stored as zero puts a spurious dip in a graph someone later reasons
from, and an unbounded buffer turns a broker outage into a memory one. These
test those three, and the string path - because `capacity/reason` is the single
most useful thing in the stream and a numeric-only forwarder would have thrown
away the entire 2026-08-21 investigation.
"""
from __future__ import annotations

import pytest

from mqtt2influx.main import MAX_TEXT, Writer, esc_tag, line

TS = 1787313600000000000


class TestTheLineProtocol:
    def test_a_numeric_payload_becomes_a_value_field(self):
        assert line("heatctl/temp/vl_total", "24.1", TS) == \
            "mqtt,topic=heatctl/temp/vl_total value=24.1 1787313600000000000"

    def test_a_string_payload_becomes_a_text_field(self):
        """The reason strings are the point. A forwarder that kept only
        numbers would have dropped every line of the log that explained the
        ceiling's behaviour."""
        got = line("heatctl/capacity/reason", "margin -1.00 K low, waiting", TS)
        assert got == ('mqtt,topic=heatctl/capacity/reason '
                       'text="margin -1.00 K low, waiting" 1787313600000000000')

    def test_a_comma_in_a_string_field_needs_no_escaping(self):
        """Only tag values and quotes do. Escaping the comma here would put a
        literal backslash in every reason string."""
        assert '\\,' not in line("t", "a, b", TS)

    def test_quotes_and_backslashes_in_a_string_are_escaped(self):
        got = line("t", 'he said "\\o/"', TS)
        assert got == 'mqtt,topic=t text="he said \\"\\\\o/\\"" 1787313600000000000'

    def test_negative_and_exponent_payloads_are_numbers(self):
        assert "value=-1.2" in line("t", "-1.2", TS)
        assert "value=" in line("t", "1e-3", TS)

    def test_a_long_string_is_truncated(self):
        """A retained discovery blob must not be able to bloat a shard if
        someone widens the topic list."""
        got = line("t", "x" * (MAX_TEXT + 500), TS)
        field = got[got.index('text="') + 6:got.rindex('"')]
        assert len(field) == MAX_TEXT


class TestTagEscaping:
    def test_the_ordinary_topic_shapes_pass_through(self):
        for t in ("heatctl/temp/vl_total",
                  "sensors/shellies/wohnzimmer/status/temperature:0",
                  "heatctl/hp/raw/0x8011"):
            assert esc_tag(t) == t

    @pytest.mark.parametrize("raw,want", [
        ("a,b", "a\\,b"), ("a=b", "a\\=b"), ("a b", "a\\ b"),
        ("a\\b", "a\\\\b"),
    ])
    def test_the_four_characters_that_break_a_tag(self, raw, want):
        """MQTT topics do not normally contain any of these, which is exactly
        why the day one does would otherwise go unnoticed - the series would
        simply be missing."""
        assert esc_tag(raw) == want

    def test_a_space_in_a_topic_is_escaped_in_place(self):
        """Line protocol ends the tag section at the first UNESCAPED space, so
        an unescaped one here would make the rest of the topic look like the
        field section and the point would be rejected."""
        got = line("odd topic", "1", TS)
        assert got.startswith("mqtt,topic=odd\\ topic ")


class TestWhatIsRefused:
    def test_an_empty_payload_is_a_retain_clear_not_a_zero(self):
        """The normaliser and the operator both clear retained topics with an
        empty payload. Recording it as 0.0 would draw a dip that never
        happened, in the middle of the graph someone is reasoning from."""
        assert line("heatctl/override/global", "", TS) is None

    @pytest.mark.parametrize("p", ["nan", "inf", "-inf", "NaN", "Infinity"])
    def test_nan_and_infinity_are_not_measurements(self, p):
        """float() accepts all of these and InfluxDB stores none of them."""
        assert line("t", p, TS) is None

    def test_unavailable_becomes_text_not_a_gap(self):
        """Home Assistant publishes these as plain strings. They are real
        events worth seeing on a graph's annotation row."""
        assert 'text="unavailable"' in line("t", "unavailable", TS)


class TestTheWriterDropsRatherThanGrows:
    class _Boom(Writer):
        def __init__(self):
            super().__init__("http://x", "mqtt", None, None)
            self.calls = 0

        def _request(self, path, data, query):
            self.calls += 1
            raise OSError("influx is down")

    def test_a_failed_write_is_dropped_after_one_retry(self, monkeypatch):
        """An unbounded buffer in a forwarder is how a forwarder becomes the
        outage. The gap in the data is the record instead."""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        w = self._Boom()
        assert w.write(["mqtt,topic=t value=1 1"]) is False
        assert w.calls == 2
        assert w.dropped == 1
        assert w.written == 0

    def test_a_persistent_failure_is_logged_once_a_minute_not_every_flush(
            self, monkeypatch, caplog):
        """A missing database is a CONDITION, not an event. At one flush every
        five seconds an untrottled warning writes seventeen thousand identical
        lines a day and buries everything else - the same reasoning heatctl's
        failsafe logging already follows. The running total rides on every line
        that is written, so nothing is concealed."""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        w = self._Boom()
        with caplog.at_level("WARNING", logger="mqtt2influx"):
            for _ in range(20):
                w.write(["mqtt,topic=t value=1 1"])
        assert w.dropped == 20
        assert caplog.text.count("dropping points") == 1

    def test_an_empty_batch_is_not_a_request(self):
        w = self._Boom()
        assert w.write([]) is True
        assert w.calls == 0


class TestRetentionIsNotOptional:
    def test_the_database_is_created_with_a_finite_duration(self):
        """The Home Assistant host was 83 % full when this was written, with
        9.4 GB free. InfluxDB's default retention is INF, and a debugging tool
        must not be the reason the box that runs HA, the broker and the bridge
        runs out of disk."""
        seen = {}

        class W(Writer):
            def _request(self, path, data, query):
                seen["path"] = path
                seen["data"] = data.decode()

        W("http://x", "mqtt", None, None).ensure_db(30)
        assert seen["path"] == "/query"
        assert 'CREATE+DATABASE+%22mqtt%22+WITH+DURATION+30d' in seen["data"]

    class _Forbidden(Writer):
        """An account that may write but may not CREATE DATABASE - which is
        exactly the Home Assistant InfluxDB account."""

        present: set = set()

        def _request(self, path, data, query):
            import urllib.error
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

        def databases(self):
            return self.present

    def test_an_existing_database_is_not_reported_as_a_problem(self, caplog):
        """403 on CREATE DATABASE is the EXPECTED state here. Warning about it
        every start reads like a fault when the database is simply there."""
        w = self._Forbidden("http://x", "mqtt", "homeassistant", "p")
        w.present = {"homeassistant", "mqtt"}
        with caplog.at_level("DEBUG", logger="mqtt2influx"):
            w.ensure_db(30)
        assert [r.levelname for r in caplog.records] == ["INFO"]

    def test_a_genuinely_missing_database_still_warns_with_the_fix(self, caplog):
        w = self._Forbidden("http://x", "mqtt", "homeassistant", "p")
        w.present = {"homeassistant"}
        with caplog.at_level("DEBUG", logger="mqtt2influx"):
            w.ensure_db(30)
        assert [r.levelname for r in caplog.records] == ["WARNING"]
        assert 'CREATE DATABASE "mqtt" WITH DURATION 30d' in caplog.text

    def test_zero_days_is_explicit_infinity_not_an_accident(self):
        """Someone may genuinely want it, but they have to type 0 - it is not
        what an unset or malformed value produces, because the default in the
        manifest is 30."""
        seen = {}

        class W(Writer):
            def _request(self, path, data, query):
                seen["data"] = data.decode()

        W("http://x", "mqtt", None, None).ensure_db(0)
        assert "DURATION+INF" in seen["data"]

    def test_the_shipped_manifest_defaults_to_a_bounded_window(self):
        import pathlib

        import yaml
        root = pathlib.Path(__file__).resolve().parent.parent
        cfg = yaml.safe_load(
            (root / "deploy" / "ha-addon-mqtt2influx" / "config.yaml").read_text())
        assert 0 < cfg["options"]["retention_days"] <= 90
        # NOT homeassistant/#: discovery configs are not measurements, and the
        # journal on the PFC already keeps everything.
        assert "homeassistant/#" not in cfg["options"]["topics"]
