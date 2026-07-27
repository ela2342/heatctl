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
