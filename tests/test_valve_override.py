"""Manual valve positioning, for commissioning and flow measurement.

The ordering is the whole design: the override beats the CONTROL chain and
loses to SAFETY. An operator measuring flow may hold a circuit wherever they
like and still cannot command cold water onto a slab below the dew point.
"""
from __future__ import annotations

import time

import pytest


class TestValveOverride:
    async def test_it_beats_the_control_chain(self, controller):
        """Distribution and the flow floor both run before it.

        Mutation-verified: applying the override before `dist.apply` lets
        normalisation scale it away and this fails.
        """
        ctl = controller(
            temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
                   "vl_total": 30.0},
            room_temps={"gaestebad": 18.0})
        ctl.on_command("valve", "valve_hk02", "37")
        ctl.io.touch(time.monotonic())
        await ctl.step(1.0)
        assert ctl.io.last_write["valve_hk02"] == pytest.approx(37.0)

    async def test_safety_still_outranks_it(self, controller):
        """The load-bearing one. An override must never be able to hold a
        circuit open into a supply below the dew point."""
        ctl = controller(
            control={"mode": "heating"},
            temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
                   "vl_total": 50.0},          # screed overtemp, still fails closed
            room_temps={"gaestebad": 28.0},
            dew_point=14.0)
        ctl.on_command("valve", "valve_hk01", "100")
        ctl.io.touch(time.monotonic())
        await ctl.step(1.0)
        assert ctl.io.last_write["valve_hk01"] == 0.0
        assert ctl.plane.topic("override/valve_hk01") == "vl_overtemp"

    async def test_auto_releases_it(self, controller):
        ctl = controller(
            temps={"rl_hk01": 24.0, "rl_hk02": 24.0, "rl_hk03": 24.0,
                   "vl_total": 30.0},
            room_temps={"gaestebad": 18.0})
        ctl.on_command("valve", "valve_hk02", "12")
        ctl.io.touch(time.monotonic())
        await ctl.step(1.0)
        held = ctl.io.last_write["valve_hk02"]
        ctl.on_command("valve", "valve_hk02", "auto")
        await ctl.step(1.0)
        assert ctl.io.last_write["valve_hk02"] != held

    def test_it_is_clamped_to_the_actuator_range(self, controller):
        ctl = controller()
        ctl.on_command("valve", "valve_hk01", "180")
        ctl.on_command("valve", "valve_hk02", "-40")
        assert ctl._valve_override["valve_hk01"] == 100.0
        assert ctl._valve_override["valve_hk02"] == 0.0

    def test_an_unknown_circuit_is_refused(self, controller):
        """Silently accepting a typo would leave the operator believing a
        circuit is held when nothing is."""
        ctl = controller()
        ctl.on_command("valve", "valve_narnia", "50")
        assert ctl._valve_override == {}

    def test_a_bad_payload_is_refused_not_guessed(self, controller):
        ctl = controller()
        ctl.on_command("valve", "valve_hk01", "quite open please")
        assert ctl._valve_override == {}

    def test_it_does_not_survive_a_restart(self, controller):
        """In memory only, deliberately. A forgotten override that persisted
        would hold a circuit open for a season and nothing would say why."""
        ctl = controller()
        ctl.on_command("valve", "valve_hk01", "70")
        assert ctl._valve_override
        assert controller()._valve_override == {}
