"""The outdoor temperature feed for the slab-target feedforward.

`UA_ao * (T_set - AT) / UA_sa` multiplies this input by 240/490, so an error
here lands on the target at about half size. It is the largest single term and
it arrives over a 433 MHz radio link, which is a combination worth testing.
"""
from __future__ import annotations

import time

import pytest

from heatctl.mqtt_plane import ControlPlane


def _plane(**mqtt):
    cfg = {"mqtt": {"host": "x", "port": 1883, "username": "", "password": "",
                    "base_topic": "heatctl", "ha_discovery": False,
                    "outdoor_temp_topic": "rtl/out", **mqtt},
           "rooms": [], "safety": {}}
    return ControlPlane(cfg, lambda *a: None)


class TestOutdoorMedian:
    def test_a_single_garbled_frame_is_rejected(self):
        """The real one, 2026-08-06: the station published 13.4 degC while both
        its own HA entities and the heat pump agreed on ~27.

        Mutation-verified: taking the latest sample instead of the median
        returns 13.4 and this fails.
        """
        p = _plane()
        # Bad frame LAST, which is the case that matters: a filter that only
        # survives a spike in the middle of its buffer would still hand the
        # controller garbage the moment one arrived most recently.
        for v in ("27.0", "27.2", "13.4"):
            p._dispatch("rtl/out", v)
        assert p.outdoor_temp() == pytest.approx(27.0)

    def test_a_real_trend_still_gets_through(self):
        """A filter that rejects genuine movement is worse than none."""
        p = _plane()
        for v in ("20.0", "24.0", "28.0"):
            p._dispatch("rtl/out", v)
        assert p.outdoor_temp() == pytest.approx(24.0)

    def test_one_sample_is_answered_not_withheld(self):
        """Waiting for a full buffer would leave layer 1 on the heat pump's
        biased register for minutes after every restart - the worse failure."""
        p = _plane()
        p._dispatch("rtl/out", "21.5")
        assert p.outdoor_temp() == pytest.approx(21.5)

    def test_stale_samples_are_not_used(self):
        """Absent must be distinguishable from old, or the fallback never fires."""
        p = _plane()
        p._dispatch("rtl/out", "21.5")
        p._outdoor_buf = [(time.monotonic() - 5000, 21.5)]
        assert p.outdoor_temp(max_age_s=900) is None

    def test_no_topic_configured_means_no_reading(self):
        cfg = {"mqtt": {"host": "x", "port": 1883, "username": "",
                        "password": "", "base_topic": "heatctl",
                        "ha_discovery": False},
               "rooms": [], "safety": {}}
        assert ControlPlane(cfg, lambda *a: None).outdoor_temp() is None

    def test_non_numeric_payloads_do_not_poison_the_buffer(self):
        """HA publishes 'unknown'/'unavailable' as plain strings."""
        p = _plane()
        p._dispatch("rtl/out", "27.0")
        p._dispatch("rtl/out", "unavailable")
        assert p.outdoor_temp() == pytest.approx(27.0)
