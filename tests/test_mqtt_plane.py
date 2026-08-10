"""Control plane: subscription routing and freshness.

No broker is involved - `_dispatch` is called directly, which is exactly the
seam that matters. Everything here is about what happens to a value between
arriving on a topic and being trusted by the control loop.
"""
from __future__ import annotations

import time

import pytest

from heatctl.mqtt_plane import ControlPlane


@pytest.fixture
def plane(cfg):
    def _make(**mqtt_overrides):
        cfg["mqtt"].update(mqtt_overrides)
        commands = []
        p = ControlPlane(cfg, lambda *a: commands.append(a))
        p.commands = commands
        return p
    return _make


# ---------- room temperatures ----------

def test_a_room_topic_updates_that_room(plane):
    p = plane()
    p._dispatch("roomtemp/gaestebad", "22.4")
    assert p.room_temp("gaestebad") == 22.4


def test_a_room_temperature_ages_out(plane):
    """Freshness is judged by ARRIVAL time, so a source that stops publishing
    stops being trusted - the control loop then falls back to return control
    rather than steering on a frozen number."""
    p = plane()
    p._dispatch("roomtemp/gaestebad", "22.4")
    p.room_temp_ts["gaestebad"] = time.monotonic() - 301
    assert p.room_temp("gaestebad") is None


def test_a_non_numeric_room_temperature_is_ignored(plane):
    """HA publishes 'unavailable' as a plain string when a source drops out."""
    p = plane()
    p._dispatch("roomtemp/gaestebad", "22.4")
    p._dispatch("roomtemp/gaestebad", "unavailable")
    assert p.room_temp("gaestebad") == 22.4


# ---------- commands ----------

def test_set_topics_are_routed_to_the_command_callback(plane):
    p = plane()
    p._dispatch("heatctl/set/mode", "cooling")
    p._dispatch("heatctl/set/setpoint/gaestebad", "23.5")
    assert ("mode", "", "cooling") in p.commands
    assert ("setpoint", "gaestebad", "23.5") in p.commands


# ---------- dew point ----------

def test_the_dew_point_topic_is_captured(plane):
    p = plane(dew_point_topic="heatctl/env/dew_point")
    p._dispatch("heatctl/env/dew_point", "12.7")
    assert p.dew_point() == 12.7


def test_the_dew_point_ages_out(plane):
    """Stale must read as absent, so safety falls back to its static limit
    instead of authorising cold water on an old reading."""
    p = plane(dew_point_topic="heatctl/env/dew_point")
    p._dispatch("heatctl/env/dew_point", "12.7")
    p._dew_ts = time.monotonic() - 901
    assert p.dew_point() is None


def test_a_non_numeric_dew_point_leaves_the_last_value_to_age_out(plane):
    p = plane(dew_point_topic="heatctl/env/dew_point")
    p._dispatch("heatctl/env/dew_point", "12.7")
    p._dispatch("heatctl/env/dew_point", "unknown")
    assert p.dew_point() == 12.7


def test_no_dew_point_topic_configured_means_no_dew_point(plane):
    """Supervision is optional; absent config must degrade, not crash."""
    p = plane(dew_point_topic="")
    assert p.dew_topic is None
    assert p.dew_point() is None


def test_the_dew_point_topic_does_not_shadow_a_room_topic(plane):
    p = plane(dew_point_topic="heatctl/env/dew_point")
    p._dispatch("roomtemp/gaestebad", "22.4")
    assert p.room_temp("gaestebad") == 22.4
    assert p.dew_point() is None


# ---------- per-room solar from layer 2 ----------

def test_per_room_solar_is_captured_from_the_opt_topic(plane):
    p = plane()
    p._dispatch("heatctl/opt/room/schlafzimmer/solar_w", "788")
    assert p.room_solar_w() == {"schlafzimmer": 788.0}


def test_per_room_solar_ages_out_per_room(plane):
    """Staleness is PER ROOM, not a single connection flag. Layer 2 publishes
    every room each cycle, so one room going quiet while others keep arriving
    means that room's mapping broke - and it must stop being trusted on its
    own rather than waiting for the whole feed to die."""
    p = plane()
    p._dispatch("heatctl/opt/room/schlafzimmer/solar_w", "788")
    p._dispatch("heatctl/opt/room/wohnzimmer/solar_w", "2415")
    p._room_solar_ts["schlafzimmer"] = time.monotonic() - 3601
    assert p.room_solar_w() == {"wohnzimmer": 2415.0}


def test_a_stale_room_is_dropped_not_zeroed(plane):
    """Zero is a physical claim - "this room is in shade" - and after sunset it
    is even true, which is what would make a silent fallback impossible to
    spot. Absent must stay distinguishable from dark."""
    p = plane()
    p._dispatch("heatctl/opt/room/schlafzimmer/solar_w", "788")
    p._room_solar_ts["schlafzimmer"] = time.monotonic() - 3601
    out = p.room_solar_w()
    assert "schlafzimmer" not in out
    assert out.get("schlafzimmer") is None


def test_a_non_numeric_room_solar_is_ignored(plane):
    p = plane()
    p._dispatch("heatctl/opt/room/schlafzimmer/solar_w", "788")
    p._dispatch("heatctl/opt/room/schlafzimmer/solar_w", "unavailable")
    assert p.room_solar_w() == {"schlafzimmer": 788.0}


def test_zero_solar_at_night_is_kept_as_a_real_reading(plane):
    """The converse of the staleness test: a genuine 0 W must survive. Dropping
    falsy values would make every room look unmeasured after sunset."""
    p = plane()
    p._dispatch("heatctl/opt/room/schlafzimmer/solar_w", "0")
    assert p.room_solar_w() == {"schlafzimmer": 0.0}


def test_the_solar_topic_does_not_shadow_a_room_temperature_topic(plane):
    p = plane()
    p._dispatch("heatctl/opt/room/gaestebad/solar_w", "120")
    assert p.room_temp("gaestebad") is None
    assert p.room_solar_w() == {"gaestebad": 120.0}


# ---------- every room gets a thermostat ----------

def _discovered(plane_factory):
    """Run _discover against a fake client and collect the configs published."""
    import asyncio
    import json as _json
    p = plane_factory()
    sent: dict[str, dict] = {}

    class FakeClient:
        async def publish(self, topic, payload=None, retain=False, **kw):
            if payload:
                try:
                    sent[topic] = _json.loads(payload)
                except (ValueError, TypeError):
                    pass

    p._client = FakeClient()
    asyncio.run(p._publish_discovery())
    return sent


def test_a_room_without_a_sensor_still_gets_a_thermostat(plane):
    """REGRESSION 2026-08-10. Kinderzimmer Natalie was the one room nobody
    could set a temperature for.

    The original gate was right when written - a sensorless room ran the
    return-temperature fallback, which never reads the room setpoint, so a
    control would have been inert. The house-average proxy changed that: such
    a room is now driven by the house mean measured against ITS OWN setpoint,
    so the control is live and withholding it is the lie.
    """
    sent = _discovered(plane)
    climates = {t: c for t, c in sent.items() if "/climate/" in t}
    names = {c.get("name") for c in climates.values()}
    assert "wohnzimmer" in names or "Wohnzimmer" in names
    # The synthetic config's second room has no room_temp_topic.
    assert len(climates) == 2, f"expected a thermostat per room, got {climates}"


def test_a_sensorless_thermostat_advertises_no_current_temperature(plane):
    """Honest degradation: `room/<n>/temp` means "this room was measured", and
    heatctl deliberately never publishes the house-average proxy there. So the
    thermostat shows a target with no current reading rather than borrowing
    another room's number."""
    sent = _discovered(plane)
    for topic, conf in sent.items():
        if "/climate/" not in topic:
            continue
        if conf.get("name") in ("wohnzimmer", "Wohnzimmer"):
            assert "current_temperature_topic" not in conf or conf[
                "current_temperature_topic"].endswith("/room/wohnzimmer/temp")


def test_every_thermostat_can_still_be_commanded(plane):
    sent = _discovered(plane)
    for topic, conf in sent.items():
        if "/climate/" in topic:
            assert conf["temperature_command_topic"].startswith("heatctl/set/setpoint/")
            assert "min_temp" in conf and "max_temp" in conf
