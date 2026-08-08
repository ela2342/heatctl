"""Registers are checked against the ranges the map itself declares.

`Reg.lo`/`Reg.hi` existed for WRITE validation only, so nothing ever checked
what the device sends back. That cost real time on 2026-08-08:
`silent_max_fan_cooling` is declared 0-1000 and reads 65512, and the capacity
loop's `fan_cap >= fan_cap_min` gate accepts it because 65512 > 400. The check
meant to confirm the condenser is not throttled had been passing on a value the
map calls impossible, and it surfaced only during an unrelated conversation.
"""
from __future__ import annotations

import logging

import pytest

from heatctl import heatpump_map as hm


class _HP:
    """Just the range-checking behaviour, without a bus or an event loop."""
    def __init__(self):
        self._range_warned: dict[int, int] = {}
    from heatctl.heatpump import HeatPump as _R
    _check_ranges = _R._check_ranges


FAN = hm.by_name("silent_max_fan_cooling")


class TestRangeCheck:
    def test_the_real_case_is_caught(self, caplog):
        """Mutation-verified: dropping the check makes this silent."""
        hp = _HP()
        with caplog.at_level(logging.WARNING):
            hp._check_ranges({FAN.addr: 65512})
        assert "out of its documented range" in caplog.text
        assert "silent_max_fan_cooling" in caplog.text

    def test_a_plausible_value_says_nothing(self, caplog):
        hp = _HP()
        with caplog.at_level(logging.WARNING):
            hp._check_ranges({FAN.addr: 700})
        assert caplog.text == ""

    def test_it_warns_once_not_once_per_poll(self, caplog):
        """The whole point. A 5 s poll would otherwise bury the log the way
        the pymodbus frame dumps did - an implausible reading is usually a
        constant, so it must fire once and then stay quiet."""
        hp = _HP()
        with caplog.at_level(logging.WARNING):
            for _ in range(50):
                hp._check_ranges({FAN.addr: 65512})
        assert caplog.text.count("out of its documented range") == 1

    def test_a_changed_bad_value_warns_again(self, caplog):
        """Silence must mean 'unchanged', not 'already given up looking'."""
        hp = _HP()
        with caplog.at_level(logging.WARNING):
            hp._check_ranges({FAN.addr: 65512})
            hp._check_ranges({FAN.addr: 65512})
            hp._check_ranges({FAN.addr: 60000})
        assert caplog.text.count("out of its documented range") == 2

    def test_recovery_rearms_the_warning(self, caplog):
        """If it goes good then bad again, that is news both times."""
        hp = _HP()
        with caplog.at_level(logging.WARNING):
            hp._check_ranges({FAN.addr: 65512})
            hp._check_ranges({FAN.addr: 700})       # recovered
            hp._check_ranges({FAN.addr: 65512})     # bad again
        assert caplog.text.count("out of its documented range") == 2

    def test_registers_without_a_declared_range_are_skipped(self, caplog):
        """Most STATUS registers carry no lo/hi; they must not warn."""
        hp = _HP()
        reg = next(r for r in hm.STATUS if r.lo is None or r.hi is None)
        with caplog.at_level(logging.WARNING):
            hp._check_ranges({reg.addr: 65535})
        assert caplog.text == ""

    def test_unknown_addresses_are_skipped(self, caplog):
        hp = _HP()
        with caplog.at_level(logging.WARNING):
            hp._check_ranges({0x7FFE: 12345})
        assert caplog.text == ""
