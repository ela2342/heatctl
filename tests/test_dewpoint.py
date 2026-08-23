"""Dew point computed in heatctl instead of in Home Assistant.

The number the whole condensation defence rests on. After D-035 the limit has
exactly one enforcer, so these tests care about ONE direction above all: a
wrong dew point must never come out LOW. Low is the direction that condenses,
and D-039 says there is no safe amount of that.
"""
from __future__ import annotations

import pytest

from heatctl.dewpoint import dew_point_c, house_dew_point


class TestTheFormula:
    def test_it_matches_the_home_assistant_helper_it_replaces(self):
        """Same Magnus coefficients as the HA template, so the changeover is
        not also a change of number. Reference points computed from the helper
        it replaces, and one measured on the plant: Arbeitszimmer read 23.2 degC
        at 57.0 % on 2026-08-19 and the helper published 14.21."""
        assert dew_point_c(23.2, 57.0) == pytest.approx(14.21, abs=0.02)
        assert dew_point_c(20.0, 50.0) == pytest.approx(9.26, abs=0.02)
        assert dew_point_c(25.0, 60.0) == pytest.approx(16.69, abs=0.02)

    def test_saturated_air_has_its_own_temperature_as_dew_point(self):
        assert dew_point_c(18.0, 100.0) == pytest.approx(18.0, abs=0.01)

    def test_dew_point_never_exceeds_air_temperature(self):
        for t in (0.0, 12.5, 24.0, 35.0):
            for rh in (5.0, 40.0, 90.0, 100.0):
                assert dew_point_c(t, rh) <= t + 1e-9, (t, rh)


class TestItRefusesRatherThanGuesses:
    """None means no knowledge, and the caller must treat it as such - a
    missing dew point stops the compressor (D-010), it does not license
    colder water."""

    @pytest.mark.parametrize("t,rh", [
        (None, 50.0), (20.0, None), (None, None),
        (20.0, 0.0),        # a disconnected RH channel reads 0; log(0) is undefined
        (20.0, -5.0),
        (20.0, 101.0),      # above saturation is not a wetter room, it is a fault
        (-60.0, 50.0),      # outside the range the formula means anything in
        (99.0, 50.0),
    ])
    def test_implausible_inputs_give_no_answer(self, t, rh):
        assert dew_point_c(t, rh) is None

    def test_a_fault_is_not_a_dry_room(self):
        """The failure that matters: garbage must not read as a LOW dew point,
        which would raise the permitted cold and condense. None is the only
        safe answer."""
        assert dew_point_c(20.0, 0.0) is None


class TestTheHouseTakesTheMaximum:
    def test_the_wettest_room_decides(self):
        """One supply temperature serves every circuit, so the wettest room
        sets what is safe. Averaging would protect the average room and
        condense in the worst one."""
        val, room, n = house_dew_point({
            "wohnzimmer": (23.0, 45.0),
            "badezimmer": (22.0, 75.0),      # wettest
            "schlafzimmer": (24.0, 50.0),
        })
        assert room == "badezimmer"
        assert n == 3
        assert val == pytest.approx(dew_point_c(22.0, 75.0))

    def test_it_is_a_maximum_and_not_a_mean(self):
        mean_ish = (dew_point_c(23.0, 45.0) + dew_point_c(22.0, 75.0)) / 2
        val, _room, _n = house_dew_point({
            "a": (23.0, 45.0), "b": (22.0, 75.0)})
        assert val > mean_ish

    def test_unusable_rooms_are_skipped_and_not_counted(self):
        """A room with a broken sensor must not contribute a fake low value,
        and must not inflate the count that is supposed to reveal it."""
        val, room, n = house_dew_point({
            "good": (22.0, 60.0),
            "no_humidity": (22.0, None),
            "faulted": (22.0, 0.0),
        })
        assert n == 1 and room == "good"
        assert val == pytest.approx(dew_point_c(22.0, 60.0))

    def test_no_usable_room_gives_no_dew_point_and_a_zero_count(self):
        """The 2026-08-10 shape. The count is what makes it visible: a dew
        point is plausible at any room count, so the value alone can never
        show that the rooms went away."""
        val, room, n = house_dew_point({"a": (None, None), "b": (22.0, 0.0)})
        assert val is None and room is None and n == 0

    def test_the_count_reports_contributors_not_candidates(self):
        _val, _room, n = house_dew_point({
            "a": (22.0, 60.0), "b": (23.0, 55.0), "c": (24.0, None)})
        assert n == 2


# ---------- the migration path: payloads and the combination rule ----------

from heatctl.mqtt_plane import ControlPlane, extract      # noqa: E402


class TestPayloadExtraction:
    """Rooms migrate one at a time, so both payload shapes are live at once."""

    def test_a_bare_number_still_works(self):
        assert extract("22.5", None) == 22.5

    def test_a_shelly_json_payload(self):
        """Measured on the wire, 2026-08-19:
        sensors/shellies/wohnzimmer/status/temperature:0"""
        assert extract('{"id":0,"tC":23.7,"tF":74.6}', "tC") == 23.7
        assert extract('{"id":0,"rh":62.9}', "rh") == 62.9

    def test_a_configured_key_is_not_silently_abandoned(self):
        """If the key is configured and the payload is not JSON with it, that
        is a misconfiguration. Falling back to float(payload) would turn it
        into a room that mysteriously never updates - the silent shape."""
        assert extract("22.5", "tC") is None
        assert extract('{"id":0,"tF":74.6}', "tC") is None

    def test_garbage_never_becomes_a_number(self):
        for p in ("", "null", "unavailable", "{", '{"tC":"warm"}'):
            assert extract(p, "tC") is None
        assert extract("unavailable", None) is None


class TestCombiningTheTwoSources:
    """During the migration only some rooms publish humidity to heatctl, so a
    locally computed value is a max over a SUBSET and can only be too low.
    """

    def _plane(self, cfg):
        return ControlPlane(cfg, on_command=lambda *a: None)

    def test_the_higher_source_wins(self, cfg):
        """Max over the union, so neither source can silently relax the limit
        as rooms move. This is the 2026-08-10 guard: a local value computed
        from two rooms read 12.0 while the true house maximum was 17.3."""
        p = self._plane(cfg)
        p._dew, p._dew_ts = 17.3, __import__("time").monotonic()
        p.room_temps["gaestebad"] = 22.0
        p.room_hum["gaestebad"] = 40.0                     # dew ~8 degC, LOW
        p.room_temp_ts["gaestebad"] = p.room_hum_ts["gaestebad"] = p._dew_ts
        assert p.dew_point(900) == pytest.approx(17.3)

    def test_a_local_value_above_the_external_one_also_wins(self, cfg):
        p = self._plane(cfg)
        now = __import__("time").monotonic()
        p._dew, p._dew_ts = 12.0, now
        p.room_temps["gaestebad"] = 24.0
        p.room_hum["gaestebad"] = 80.0                     # dew ~20.3, HIGH
        p.room_temp_ts["gaestebad"] = p.room_hum_ts["gaestebad"] = now
        assert p.dew_point(900) > 20.0

    def test_either_source_alone_is_enough(self, cfg):
        p = self._plane(cfg)
        now = __import__("time").monotonic()
        p._dew, p._dew_ts = 15.0, now
        assert p.dew_point(900) == pytest.approx(15.0)

    def test_no_fresh_source_means_no_dew_point(self, cfg):
        """Which stops the compressor (D-010). It must not fall through to a
        number."""
        p = self._plane(cfg)
        assert p.dew_point(900) is None

    def test_a_stale_half_pair_contributes_nothing(self, cfg):
        """Pairing a current temperature with an hour-old humidity would
        produce a confident number from a measurement nobody took."""
        p = self._plane(cfg)
        now = __import__("time").monotonic()
        p.room_temps["gaestebad"] = 24.0
        p.room_hum["gaestebad"] = 80.0
        p.room_temp_ts["gaestebad"] = now
        p.room_hum_ts["gaestebad"] = now - 5000            # stale humidity
        val, _room, n = p.local_dew_point(900)
        assert val is None and n == 0


class TestThePerRoomFreshnessWindow:
    """Adopted from the normaliser, which derives it from what each device
    reports about its own cadence.

    The bathroom is why this matters. Its Shelly is on battery and wakes every
    7200 s; against the global 900 s it was stale 88 % of the time, so the room
    that actually drives the house dew point contributed to it for fifteen
    minutes in every two hours. On 2026-08-23 the local dew point read 12.3
    from the living room alone while the bathroom's own reading implied 14.1.
    """

    def _plane(self, cfg):
        return ControlPlane(cfg, on_command=lambda *a: None)

    def _stale_pair(self, p, room, age):
        now = __import__("time").monotonic()
        p.room_temps[room], p.room_hum[room] = 24.0, 80.0
        p.room_temp_ts[room] = p.room_hum_ts[room] = now - age

    def test_a_room_beyond_the_default_but_inside_its_own_window_counts(self, cfg):
        p = self._plane(cfg)
        p._set_max_age("gaestebad", "10800")
        self._stale_pair(p, "gaestebad", 3000)          # > 900, < 10800
        val, room, n = p.local_dew_point(900)
        assert n == 1 and room == "gaestebad" and val is not None

    def test_without_the_published_window_the_default_still_applies(self, cfg):
        """No adoption, no change: a room whose device has said nothing keeps
        the behaviour it has always had."""
        p = self._plane(cfg)
        self._stale_pair(p, "gaestebad", 3000)
        assert p.local_dew_point(900)[2] == 0

    def test_room_temp_uses_it_too(self, cfg):
        p = self._plane(cfg)
        p._set_max_age("gaestebad", "10800")
        p.room_temps["gaestebad"] = 21.5
        p.room_temp_ts["gaestebad"] = __import__("time").monotonic() - 3000
        assert p.room_temp("gaestebad", 900) == 21.5

    def test_it_can_only_lengthen_the_window_to_the_ceiling(self, cfg):
        """It arrives over the broker, and lengthening a staleness window is a
        safety-relevant act. The clamp does not depend on the ACL continuing to
        keep other writers off the topic."""
        cfg["control"]["room_temp_max_age_ceiling_s"] = 14400.0
        p = self._plane(cfg)
        p._set_max_age("gaestebad", "999999")
        assert p.room_max_age["gaestebad"] == 14400.0

    def test_it_can_never_shorten_below_the_configured_default(self, cfg):
        """Shortening is the safe direction, but it is not this mechanism's
        job - a broker message must not be able to make rooms drop out."""
        p = self._plane(cfg)
        p._set_max_age("gaestebad", "10")
        assert p.room_max_age["gaestebad"] == 900.0

    @pytest.mark.parametrize("payload", ["", "soon", "unavailable"])
    def test_an_unusable_or_cleared_value_returns_to_the_default(self, cfg,
                                                                 payload):
        """A retain-clear means the normaliser has stopped asserting a window.
        Continuing to honour the last one heard would be believing a claim
        nobody is making any more."""
        p = self._plane(cfg)
        p._set_max_age("gaestebad", "10800")
        p._set_max_age("gaestebad", payload)
        expected = 900.0 if payload == "" else 10800.0
        assert p.room_max_age.get("gaestebad", 900.0) == expected

    def test_the_topic_is_subscribed_per_room(self, cfg):
        p = self._plane(cfg)
        assert "sensors/room/gaestebad/max_age_s" in p.room_max_age_topics
        assert p.room_max_age_topics["sensors/room/gaestebad/max_age_s"] \
            == "gaestebad"
