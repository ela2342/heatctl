"""The sensor-topic normaliser: retain with a deadline, and refuse the rest.

This module sits in front of the control core's only view of the rooms, so its
failures are silent by nature - a room that quietly stops updating falls back
to house-average control with nothing said. The tests are written around that:
most of them assert that **nothing** was published, and which direction the
absence protects.

The one invariant everything else hangs off: a measurement is never retained
without an expiry. A retained value with no deadline is the 2022 rtl_433 fossil
that read 13.4 degC into the slab target against a true 17.2.
"""
from __future__ import annotations

import pytest

from normaliser.main import (DEFAULT_BANDS, Normaliser, Publication, Source,
                             load_sources, parse_value)

TTL = 900


def shelly(room: str = "wohnzimmer") -> list[Source]:
    """The real Wohnzimmer pilot topics, as measured on the wire 2026-08-19."""
    return [
        Source(f"sensors/shellies/{room}/status/temperature:0", room,
               "temperature_c", "tC", *DEFAULT_BANDS["temperature_c"]),
        Source(f"sensors/shellies/{room}/status/humidity:0", room,
               "humidity_pct", "rh", *DEFAULT_BANDS["humidity_pct"]),
    ]


def norm(sources=None, ttl=TTL) -> Normaliser:
    return Normaliser(sources or shelly(), "sensors/room", ttl)


def feed(n: Normaliser, topic: str, payload: str, *, wall=1_700_000_000.0,
         mono=100.0) -> dict[str, Publication]:
    """Deliver one message; return the publications keyed by topic suffix."""
    return {p.topic.rsplit("/", 1)[1]: p
            for p in n.on_message(topic, payload, wall=wall, mono=mono)}


T = "sensors/shellies/wohnzimmer/status/temperature:0"
H = "sensors/shellies/wohnzimmer/status/humidity:0"


class TestTheHappyPath:
    def test_a_shelly_json_payload_becomes_a_bare_float(self):
        """heatctl reads a bare number and needs no change to consume this -
        that is the whole point of doing the reshaping out here."""
        out = feed(norm(), T, '{"id":0,"tC":23.6,"tF":74.4}')
        assert out["temperature_c"].topic == "sensors/room/wohnzimmer/temperature_c"
        assert out["temperature_c"].payload == "23.6"

    def test_humidity_too(self):
        out = feed(norm(), H, '{"id":0,"rh":58.7}')
        assert out["humidity_pct"].payload == "58.7"
        assert out["humidity_pct"].topic == "sensors/room/wohnzimmer/humidity_pct"

    def test_a_bare_number_source_is_still_supported(self):
        """Rooms migrate one at a time, so the HA-bridge shape stays live."""
        s = [Source("roomtemp/gaestebad", "gaestebad", "temperature_c",
                    None, -40.0, 60.0)]
        out = feed(norm(s), "roomtemp/gaestebad", "22.5")
        assert out["temperature_c"].payload == "22.5"

    def test_float_noise_does_not_reach_the_topic(self):
        out = feed(norm(), T, '{"tC":23.600000000000001}')
        assert out["temperature_c"].payload == "23.6"

    def test_resolution_survives_a_large_value(self):
        """`%.4g` would have made this 1234. Sensor fields are small today;
        the format must not be the reason a future one loses a digit."""
        s = [Source("x", "r", "pressure_pa", None, 0.0, 1e6)]
        assert feed(norm(s), "x", "1234.5")["pressure_pa"].payload == "1234.5"


class TestEveryMeasurementCarriesADeadline:
    """The invariant. Without it this module makes staleness WORSE than not
    retaining at all: heatctl times from arrival, so a retained value with no
    expiry arrives looking zero seconds old however old it is."""

    def test_all_publications_are_retained_and_expiring(self):
        n = norm()
        pubs = (n.on_message(T, '{"tC":23.6}', wall=1.0, mono=1.0)
                + n.on_message(T, '{"tC":23.7}', wall=400.0, mono=400.0)
                + n.on_message(H, '{"rh":58.7}', wall=400.0, mono=400.0))
        assert len(pubs) >= 4
        for p in pubs:
            assert p.retain is True, p.topic
            assert p.expiry_s == TTL, p.topic

    def test_the_ttl_is_the_configured_one(self):
        out = feed(norm(ttl=1234), T, '{"tC":23.6}')
        assert out["temperature_c"].expiry_s == 1234


class TestItRefusesRatherThanRepublishes:
    """A dropped sample leaves the PREVIOUS retained value standing until it
    expires on its own. That is the intended behaviour: a six-minute-old real
    reading beats a fresh implausible one, and the value vanishing by itself
    is the alarm."""

    @pytest.mark.parametrize("payload", [
        "", "null", "unavailable", "{", '{"tC":"warm"}', '{"id":0}',
    ])
    def test_unreadable_payloads_publish_nothing(self, payload):
        assert feed(norm(), T, payload) == {}

    def test_a_configured_key_is_never_abandoned_for_the_bare_payload(self):
        """`{"tC":...}` is configured, so a bare `23.6` on that topic is a
        misconfiguration, not a reading. Falling back to float() would turn a
        broken map into a room that mysteriously works."""
        assert feed(norm(), T, "23.6") == {}

    @pytest.mark.parametrize("v", [-41.0, 60.1, 999.0, -273.0])
    def test_impossible_temperatures_are_dropped_in_both_directions(self, v):
        """Both directions on purpose. A stuck-low sensor and a stuck-high one
        are the same class of fault, and only one of them looks alarming."""
        assert feed(norm(), T, f'{{"tC":{v}}}') == {}

    @pytest.mark.parametrize("v", [-0.1, 100.1, 6553.5])
    def test_impossible_humidities_are_dropped(self, v):
        assert feed(norm(), H, f'{{"rh":{v}}}') == {}

    def test_the_band_edges_themselves_are_accepted(self):
        """Rejecting what cannot be a measurement, not what is merely
        surprising. 100 % RH is a bathroom, not a fault."""
        assert feed(norm(), H, '{"rh":100.0}')["humidity_pct"].payload == "100"
        assert feed(norm(), H, '{"rh":0.0}')["humidity_pct"].payload == "0"

    def test_a_rejected_sample_does_not_advance_sample_ts(self):
        """Otherwise a dashboard reports the room as freshly sampled while the
        value on the topic is anything but."""
        assert "sample_ts" not in feed(norm(), T, '{"tC":999.0}')

    def test_an_unmapped_topic_publishes_nothing(self):
        """Rooms are mapped explicitly. A topic segment that looks like a room
        name is a hypothesis, not a mapping."""
        assert feed(norm(), "sensors/shellies/kuche/status/temperature:0",
                    '{"tC":23.6}') == {}


class TestSampleAgeAndTheWakePeriod:
    def test_sample_ts_is_the_wall_clock_at_receipt(self):
        """Wall clock, because it is read on the far side of a v3.1.1 bridge
        that drops the expiry property - it is the only way the age is visible
        in Home Assistant."""
        out = feed(norm(), T, '{"tC":23.6}', wall=1_755_000_000.7)
        assert out["sample_ts"].payload == "1755000001"
        assert out["sample_ts"].expiry_s == TTL

    def test_no_interval_on_the_first_sample(self):
        """There is nothing to measure yet, and inventing a zero would show up
        in the trend that exists to settle the wake period."""
        assert "interval_s" not in feed(norm(), T, '{"tC":23.6}')

    def test_the_interval_is_the_gap_between_temperature_samples(self):
        """The measurement that settles 600-reported against 360-observed."""
        n = norm()
        n.on_message(T, '{"tC":23.6}', wall=0.0, mono=1000.0)
        out = feed(n, T, '{"tC":23.7}', wall=0.0, mono=1360.0)
        assert out["interval_s"].payload == "360"

    def test_the_interval_uses_the_monotonic_clock(self):
        """An NTP step must not be published as a wake period. Wall clock jumps
        back an hour here; the interval still reflects elapsed time."""
        n = norm()
        n.on_message(T, '{"tC":23.6}', wall=1_755_003_600.0, mono=1000.0)
        out = feed(n, T, '{"tC":23.7}', wall=1_755_000_000.0, mono=1360.0)
        assert out["interval_s"].payload == "360"

    def test_humidity_does_not_produce_an_interval(self):
        """One number per room, from the field every room has and control
        actually depends on."""
        n = norm()
        n.on_message(H, '{"rh":58.0}', wall=0.0, mono=1000.0)
        assert "interval_s" not in feed(n, H, '{"rh":58.7}', mono=1360.0)

    def test_a_rejected_sample_does_not_reset_the_interval_clock(self):
        """Otherwise a single garbage frame would halve the reported wake
        period and corrupt the very measurement being taken."""
        n = norm()
        n.on_message(T, '{"tC":23.6}', wall=0.0, mono=1000.0)
        n.on_message(T, '{"tC":999.0}', wall=0.0, mono=1200.0)
        out = feed(n, T, '{"tC":23.7}', wall=0.0, mono=1360.0)
        assert out["interval_s"].payload == "360"

    def test_rooms_keep_separate_clocks(self):
        n = Normaliser(shelly("wohnzimmer") + shelly("gaestebad"),
                       "sensors/room", TTL)
        n.on_message(T, '{"tC":23.6}', wall=0.0, mono=1000.0)
        g = "sensors/shellies/gaestebad/status/temperature:0"
        assert "interval_s" not in feed(n, g, '{"tC":24.0}', mono=1100.0)


class TestWhatItSaysOutLoud:
    """Routine samples must not fill the log - a room reports every few
    minutes for years. But a room appearing, or coming back from long enough
    that its value had already expired off the broker, is an event.
    """

    def test_the_first_sample_of_a_room_is_announced(self, caplog):
        with caplog.at_level("INFO", logger="normaliser"):
            feed(norm(), T, '{"tC":23.6}')
        assert "wohnzimmer/temperature_c: 23.6" in caplog.text

    def test_routine_samples_are_not(self, caplog):
        n = norm()
        n.on_message(T, '{"tC":23.6}', wall=0.0, mono=0.0)
        caplog.clear()
        with caplog.at_level("INFO", logger="normaliser"):
            n.on_message(T, '{"tC":23.7}', wall=0.0, mono=360.0)
        assert caplog.text == ""

    def test_a_room_returning_after_its_value_expired_is_announced(self, caplog):
        """The gap that matters is the TTL, because beyond it the broker had
        already dropped the value and the room genuinely was gone."""
        n = norm(ttl=900)
        n.on_message(T, '{"tC":23.6}', wall=0.0, mono=0.0)
        caplog.clear()
        with caplog.at_level("INFO", logger="normaliser"):
            n.on_message(T, '{"tC":23.7}', wall=0.0, mono=901.0)
        assert "back after 901 s" in caplog.text


class TestPayloadExtraction:
    def test_bare_and_keyed(self):
        assert parse_value("22.5", None) == 22.5
        assert parse_value('{"id":0,"tC":23.7}', "tC") == 23.7

    def test_a_json_payload_read_without_a_key_is_not_a_number(self):
        assert parse_value('{"id":0,"tC":23.7}', None) is None


class TestConfigFailsAtStartUpOrNotAtAll:
    """A misconfigured room becomes a room that silently never updates, which
    is the one failure this whole module is trying to remove. Every one of
    these is fatal at start-up rather than a line in a log nobody reads."""

    def _cfg(self, **over):
        src = {"topic": "t", "room": "r", "field": "temperature_c"}
        src.update(over)
        return {"sources": [src]}

    def test_a_good_source_loads(self):
        [s] = load_sources(self._cfg(json_key="tC"))
        assert (s.room, s.field, s.json_key) == ("r", "temperature_c", "tC")
        assert (s.lo, s.hi) == DEFAULT_BANDS["temperature_c"]

    @pytest.mark.parametrize("missing", ["topic", "room", "field"])
    def test_a_missing_key_is_fatal(self, missing):
        cfg = self._cfg()
        del cfg["sources"][0][missing]
        with pytest.raises(SystemExit):
            load_sources(cfg)

    def test_an_unknown_field_needs_an_explicit_band(self):
        """No silent default band for a field nobody has thought about - that
        would be this module inventing a plausibility rule."""
        with pytest.raises(SystemExit):
            load_sources(self._cfg(field="co2_ppm"))
        [s] = load_sources(self._cfg(field="co2_ppm", min=0, max=5000))
        assert (s.lo, s.hi) == (0.0, 5000.0)

    def test_an_inverted_band_is_fatal(self):
        with pytest.raises(SystemExit):
            load_sources(self._cfg(min=50, max=10))

    def test_no_sources_is_fatal(self):
        with pytest.raises(SystemExit):
            load_sources({})

    def test_the_shipped_config_is_loadable_and_agrees_with_heatctl(self):
        """The reference config in the repo, checked the way test_config.py
        checks heatctl's: that it parses, and that its `ttl_s` still equals
        heatctl's `room_temp_max_age_s`. They are one judgement expressed
        twice, and the pair drifting apart is exactly the kind of thing that
        goes unnoticed for months."""
        import pathlib

        import yaml
        root = pathlib.Path(__file__).resolve().parent.parent
        cfg = yaml.safe_load((root / "normaliser" / "config.yaml").read_text())
        sources = load_sources(cfg)
        assert cfg["out_prefix"] == "sensors/room"

        heat = yaml.safe_load((root / "config.yaml").read_text())
        assert cfg["ttl_s"] == heat["control"]["room_temp_max_age_s"]

        rooms = {r["name"] for r in heat["rooms"]}
        for s in sources:
            assert s.room in rooms, f"{s.room} is not a heatctl room"

    def test_the_pins_match_the_control_cores(self):
        """The normaliser ships in its own image from its own requirements
        file, so nothing but this stops the two drifting to different versions
        of the same library. A range that re-resolved has already cost this
        project two days once."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent

        def pins(path):
            return {ln.split("==")[0].strip(): ln.strip()
                    for ln in path.read_text().splitlines()
                    if "==" in ln and not ln.lstrip().startswith("#")}

        core = pins(root / "requirements.txt")
        mine = pins(root / "normaliser" / "requirements.txt")
        assert mine, "the normaliser must pin its dependencies"
        assert set(mine) <= set(core), (
            f"not a subset of the control core's: {set(mine) - set(core)}")
        for name, line in mine.items():
            assert line == core[name], f"{name}: {line!r} vs {core[name]!r}"


class TestTheWindowIsLearnedFromTheDevice:
    """One global window cannot serve two devices whose cadence differs
    twelve-fold. The same Shelly H&T model reports `wakeup_period: 600` on
    mains and 7200 on battery, and the manual's guarantee is "on a delta, or
    every wake period at the latest". Against a hand-set 900 s a battery room
    is stale 88 % of the time - which is how the bathroom, the room that drives
    the house dew point, contributed for fifteen minutes in every two hours.
    """

    SYS = "sensors/shellies/wohnzimmer/status/sys"

    def norm(self, period_topic=None, **kw):
        return Normaliser(shelly(), "sensors/room", TTL,
                          wake_topics={"wohnzimmer": period_topic or self.SYS},
                          **kw)

    def test_the_period_becomes_the_window(self):
        n = self.norm()
        out = feed(n, self.SYS, '{"wakeup_period":7200,"mac":"x"}')
        assert out["max_age_s"].payload == "10800"       # 1.5 x 7200

    def test_it_then_applies_to_that_room_s_measurements(self):
        """The point of the whole exercise: the reading must outlive the
        default window, or the room is stale between wakes."""
        n = self.norm()
        n.on_message(self.SYS, '{"wakeup_period":7200}', wall=0.0, mono=0.0)
        out = feed(n, T, '{"tC":23.6}')
        assert out["temperature_c"].expiry_s == 10800

    def test_a_room_with_no_wake_topic_keeps_the_default(self):
        n = Normaliser(shelly("gaestebad"), "sensors/room", TTL)
        g = "sensors/shellies/gaestebad/status/temperature:0"
        assert feed(n, g, '{"tC":22.0}')["temperature_c"].expiry_s == TTL

    def test_the_mains_device_lands_on_the_hand_chosen_number(self):
        """1.5 x 600 is exactly the 900 s that was chosen by hand for the mains
        device. A reassuring coincidence rather than a derivation, but it would
        be a bad sign if the factor disagreed with it."""
        n = self.norm()
        assert feed(n, self.SYS, '{"wakeup_period":600}')["max_age_s"].payload \
            == "900"

    def test_the_floor_is_the_configured_ttl(self):
        """A very short period must not shorten the window below what the rest
        of the plant is built around."""
        n = self.norm()
        assert feed(n, self.SYS, '{"wakeup_period":60}')["max_age_s"].payload \
            == str(TTL)

    def test_an_absurd_period_is_capped(self):
        """A misconfigured device, or a payload we misread, must not talk the
        plant into believing a measurement for a day."""
        n = self.norm(ttl_max_s=14400)
        assert feed(n, self.SYS, '{"wakeup_period":86000}')["max_age_s"].payload \
            == "14400"

    @pytest.mark.parametrize("payload", [
        "{}", "not json", '{"wakeup_period":"soon"}', '{"wakeup_period":0}',
        '{"wakeup_period":-5}', '{"wakeup_period":999999}',
    ])
    def test_an_unusable_period_changes_nothing(self, payload):
        """Keep the previous window rather than inventing one. Silence is the
        safe direction: the default already works, just poorly."""
        n = self.norm()
        n.on_message(self.SYS, '{"wakeup_period":7200}', wall=0.0, mono=0.0)
        assert feed(n, self.SYS, payload) == {}
        assert feed(n, T, '{"tC":23.6}')["temperature_c"].expiry_s == 10800

    def test_it_is_published_only_when_it_changes(self):
        """The device sends `sys` on every wake. Re-publishing an unchanged
        window would be churn, and on a retained topic it buys nothing."""
        n = self.norm()
        assert feed(n, self.SYS, '{"wakeup_period":7200}')
        assert feed(n, self.SYS, '{"wakeup_period":7200}') == {}

    def test_the_wake_topic_is_subscribed(self):
        assert self.SYS in self.norm().topics
