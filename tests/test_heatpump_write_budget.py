"""The write budget warns loudly; it does not silently drop writes.

Owner's call, 2026-07-31: "Being unable to correct plant deviations can hurt us
more than a soft limit like flash writes." The budget was a gate that refused
writes at 30/hour with nothing visible outside the log. It is now a warning
threshold with an alarm, and the gate sits an order of magnitude higher.
"""
from __future__ import annotations

import time

import pytest

from heatctl.heatpump import HeatPump


class _Plane:
    base = "heatctl"

    def __init__(self):
        self.published: dict[str, str] = {}

    async def publish(self, topic, payload):
        # Mirror ControlPlane: it prefixes with the base topic. A fake that
        # does not would let a wrong topic pass here and fail on the broker.
        self.published[f"{self.base}/{topic}"] = str(payload)

    async def discover(self, *a, **kw):
        pass


def _hp(**over):
    h = {"enabled": True, "allow_writes": True, "write_budget_per_hour": 30}
    h.update(over)
    plane = _Plane()
    return HeatPump({"heatpump": h}, plane), plane


class TestBudgetIsAWarningNotAGate:
    def test_the_hard_limit_defaults_to_ten_times_the_budget(self):
        hp, _ = _hp()
        assert hp.write_hard_limit_per_hour == 300

    async def test_over_budget_still_permits_the_write(self):
        """The behaviour that changed, and the reason for the change.

        Mutation-verified: restoring `return False` on the soft threshold makes
        this fail. A refused write here means an uncorrected plant deviation,
        which is the failure the owner ranked above flash wear.
        """
        hp, _ = _hp()
        hp._writes = [time.monotonic()] * 50            # well over the 30/h budget
        assert await hp._check_budget(0x0090) is True

    async def test_over_budget_raises_a_user_visible_alarm(self):
        """Logging alone is not visibility - the runaway case happens at 03:00."""
        hp, plane = _hp()
        hp._writes = [time.monotonic()] * 50
        await hp._check_budget(0x0090)
        assert plane.published["heatctl/hp/write_budget_exceeded"] == "1"
        assert plane.published["heatctl/hp/writes_last_hour"] == "50"

    async def test_the_hard_limit_does_refuse(self):
        hp, plane = _hp()
        hp._writes = [time.monotonic()] * 300
        assert await hp._check_budget(0x0090) is False
        assert plane.published["heatctl/hp/write_hard_limit_hit"] == "1"

    async def test_the_alarm_clears_when_the_rate_falls_back(self):
        """A latched alarm that never clears is one nobody trusts."""
        hp, plane = _hp()
        hp._writes = [time.monotonic()] * 50
        await hp._check_budget(0x0090)
        assert plane.published["heatctl/hp/write_budget_exceeded"] == "1"
        hp._writes = []
        await hp._check_budget(0x0090)
        assert plane.published["heatctl/hp/write_budget_exceeded"] == "0"

    async def test_within_budget_publishes_the_count_and_no_alarm(self):
        hp, plane = _hp()
        hp._writes = [time.monotonic()] * 5
        assert await hp._check_budget(0x0090) is True
        assert plane.published["heatctl/hp/writes_last_hour"] == "5"
        assert "heatctl/hp/write_budget_exceeded" not in plane.published

    async def test_stale_writes_age_out_of_the_window(self):
        """The window is a rolling hour, so a past burst must not gate forever."""
        hp, _ = _hp()
        hp._writes = [time.monotonic() - 4000] * 500     # all older than 1 h
        assert hp.writes_last_hour() == 0
        assert await hp._check_budget(0x0090) is True
