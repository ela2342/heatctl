"""P04 carries the setpoint OR OFF, and nothing else may see the sentinel.

Owner, 2026-07-31: "Conceptually, we write the setpoint or OFF to P04. But we
do not mess with the setpoint in a way that is visible to anyone."
"""
from __future__ import annotations

import pytest

# `hp` builds a HeatPump with a FakePump client, so writes reach a fake bus
# instead of failing to connect. `cfg` comes from conftest.
from tests.test_heatpump import FakePump, hp                   # noqa: F401


class TestTheSentinelNeverEscapes:
    def test_a_normal_setpoint_reads_back_as_itself(self, hp):
        hp, _, _ = hp()
        hp.config[0x0090] = 19
        assert hp.cooling_setpoint() == 19.0
        assert hp.cooling_is_off() is False

    def test_the_off_sentinel_reads_back_as_None_not_as_30(self, hp):
        """The whole point. `setpoint.py` computes its next move from the
        current setpoint - handing it 30 would poison the trim, the constraint
        memory and the reversal guard at once.
        """
        hp, _, _ = hp()
        hp.config[0x0090] = 30
        assert hp.cooling_setpoint() is None
        assert hp.cooling_is_off() is True

    def test_an_unknown_register_is_not_mistaken_for_off(self, hp):
        hp, _, _ = hp()
        assert hp.cooling_setpoint() is None      # unknown
        assert hp.cooling_is_off() is False       # but NOT off

    async def test_a_real_setpoint_colliding_with_the_sentinel_is_refused(self, hp):
        """30 must mean OFF and only OFF. A setpoint that happened to be 30
        would be indistinguishable, so it is rejected rather than written."""
        hp, _, _ = hp()
        hp.config[0x0090] = 19
        assert await hp.set_cooling(30.0, "test") is False
        assert hp.config[0x0090] == 19            # unchanged


class TestTheStopSurvivesAndSelfHeals:
    async def test_writing_off_writes_the_sentinel(self, hp):
        hp, _, _ = hp()
        hp.config[0x0090] = 19
        assert await hp.set_cooling(None, "ceiling saturated") is True
        assert hp.config[0x0090] == 30
        assert hp.cooling_is_off() is True
        assert hp.cooling_setpoint() is None

    async def test_restoring_a_setpoint_clears_off(self, hp):
        hp, _, _ = hp()
        hp.config[0x0090] = 30
        assert await hp.set_cooling(19.0, "restart") is True
        assert hp.cooling_setpoint() == 19.0
        assert hp.cooling_is_off() is False

    async def test_writing_off_twice_is_a_no_op_on_the_bus(self, hp):
        """The stop must not cost a flash cycle per loop iteration. no-op
        writes are dropped before the bus, so re-asserting OFF is free."""
        hp, _, _ = hp()
        hp.config[0x0090] = 19
        await hp.set_cooling(None, "first")
        n = hp.writes_last_hour()
        assert await hp.set_cooling(None, "again") is False
        assert hp.writes_last_hour() == n


class TestTheTrimNeverSeesTheSentinel:
    async def test_the_trim_holds_while_the_compressor_is_commanded_off(
            self, controller):
        """THE MUTATION THIS EXISTS TO CATCH.

        `setpoint.py` computes its next move from the CURRENT setpoint. If the
        trim reads the raw register while OFF is written, it sees 30 - the top
        of P04's range - and concludes the setpoint has been walked all the way
        up. Every downstream mechanism then reasons from a number that is not a
        setpoint: the trim's own step, the constraint memory, the reversal
        guard.

        Mutation-verified: replacing `self.hp.cooling_setpoint()` with
        `self.hp.config.get(addr)` in `_trim_water_setpoint` makes this fail.
        """
        ctl = controller()
        ctl.mode = "cooling"
        ctl.hp.allow_writes = True
        ctl.hp._config_seen = True
        ctl.hp.config[0x0090] = 30                 # OFF is written
        ctl.water_sp.enabled = True

        seen = {}
        orig = ctl.water_sp.step

        def spy(**kw):
            seen.update(kw)
            return orig(**kw)

        ctl.water_sp.step = spy
        await ctl._trim_water_setpoint(ctl.io.state, now=10_000.0)

        # There are TWO protections and they mask each other, so this asserts
        # the outer one specifically: the trim must not run at all while the
        # compressor is deliberately stopped. (The inner one - that
        # `cooling_setpoint()` decodes 30 to None rather than 30.0 - is covered
        # by TestTheSentinelNeverEscapes above. An earlier version of this test
        # checked `current != 30` and passed against BOTH mutations, because
        # removing either left the other one covering it.)
        assert seen == {}, \
            f"the trim ran while the compressor was commanded OFF: {seen}"

    async def test_a_stale_off_is_cleared_on_start_up(self, controller):
        """The stop lives in the pump's flash and survives a heatctl crash,
        and nothing else would restore it - that is how a house sits uncooled
        until someone notices. A clean start clears it; the capacity loop
        re-asserts within a cycle if the condition still holds.
        """
        ctl = controller()
        ctl.mode = "cooling"
        ctl.hp.allow_writes = True
        ctl.hp._config_seen = True
        ctl.hp.client = FakePump()          # the controller fixture has no bus
        ctl.hp.config[0x0090] = 30

        await ctl._clear_stale_cooling_off()
        assert ctl.hp.cooling_is_off() is False
        assert ctl.hp.cooling_setpoint() == ctl.default_cooling_sp

    async def test_start_up_clearing_runs_once_not_every_cycle(self, controller):
        """Otherwise it would fight the capacity loop's own OFF every second."""
        ctl = controller()
        ctl.mode = "cooling"
        ctl.hp.allow_writes = True
        ctl.hp._config_seen = True
        ctl.hp.client = FakePump()
        ctl.hp.config[0x0090] = 19
        await ctl._clear_stale_cooling_off()       # first pass, nothing to do
        ctl.hp.config[0x0090] = 30                 # capacity loop stops it
        await ctl._clear_stale_cooling_off()
        assert ctl.hp.cooling_is_off() is True, "start-up clearing fought the loop"
