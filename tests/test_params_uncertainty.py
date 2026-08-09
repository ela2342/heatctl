"""Parameters carry their uncertainty, and correlations stay structural (D-032).

The load-bearing test here is `test_k_is_invariant_to_the_flow`. Everything
else is schema hygiene; that one is the thesis.
"""
from __future__ import annotations

import copy
import pathlib

import pytest
import yaml

from optimizer import derived
from optimizer.params import Param, _convert, load_params

PARAMS = "optimizer/params.yaml"


class TestParamBehavesAsANumber:
    def test_it_is_a_float_so_existing_readers_did_not_change(self):
        """The migration touched no consumer. `b["ua_ao"] * 2` still works."""
        p = load_params(PARAMS)
        ua = p["building"]["ua_ao"]
        assert isinstance(ua, float)
        assert ua * 2 == pytest.approx(534.4)
        # RETARGETED 2026-08-01: kind was "measured". The owner confirmed the
        # 267.2 figure comes from the BUILDING PERMIT CALCULATION, and a design
        # calculation cannot corroborate itself - so it is a `prior`. The point
        # of this test is that Param still behaves as a float for existing
        # readers, which is unaffected; the kind is asserted only so a silent
        # provenance change cannot slip through unnoticed.
        assert ua.sigma == 20.0 and ua.kind == "prior"

    def test_plain_scalars_still_load_so_migration_can_be_partial(self):
        """A schema change that forces a big-bang rewrite of a safety-adjacent
        file is a schema change that gets rushed."""
        got = _convert({"a": {"value": 1.0, "kind": "measured"}, "b": 2.0})
        assert isinstance(got["a"], Param) and got["a"].kind == "measured"
        assert got["b"] == 2.0 and not isinstance(got["b"], Param)

    def test_relative_sigma(self):
        assert Param(200.0, sigma=20.0).relative_sigma == pytest.approx(0.1)
        assert Param(200.0).relative_sigma is None


class TestSchemaRejectsNonsense:
    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="unknown kind"):
            _convert({"x": {"value": 1.0, "kind": "vibes"}})

    def test_a_value_outside_its_own_bounds_is_refused(self):
        """Caught a real class of error: bounds that contradict the value mean
        one of them is stale, and silently trusting either is worse."""
        with pytest.raises(ValueError, match="outside bounds"):
            _convert({"x": {"value": 2.0, "bounds": [0.0, 1.0]}})

    def test_negative_sigma_is_refused(self):
        with pytest.raises(ValueError, match="negative sigma"):
            _convert({"x": {"value": 1.0, "sigma": -1.0}})


class TestCorrelationsAreStructural:
    def test_k_is_invariant_to_the_flow(self):
        """THE POINT OF THE WHOLE SCHEME.

        `ua_sa` is identified as Q/(T_room - T_water) with Q = m_dot_c*dT, so it
        is perfectly correlated with the flow. In k = ua_sa/(mc - ua_sa/2) that
        error cancels exactly. On 2026-07-31 the flow was corrected 1.24 -> 1.44
        (+16 %) and k moved by well under a percent, which is why the
        constraint-optimal setpoint barely moved while Q_max moved by the full
        16 %.

        Mutation-verified: storing `ua_sa` as a fixed 568 instead of deriving it
        makes k move by ~14 % here and this fails.
        """
        p = load_params(PARAMS)
        lo = copy.deepcopy(p); hi = copy.deepcopy(p)
        lo["hydronics"]["flow_m3_h"] = Param(1.24, unit="m3/h", kind="specified")
        hi["hydronics"]["flow_m3_h"] = Param(1.44, unit="m3/h", kind="specified")
        k_lo, k_hi = derived.k_spread(lo).value, derived.k_spread(hi).value
        assert abs(k_hi - k_lo) / k_lo < 0.01

    def test_q_max_does_scale_with_the_flow(self):
        """The counterpart. Q_max carries a bare m_dot_c, so a 16 % flow error
        is a 16 % Q_max error - and treating flow and ua_sa as INDEPENDENT
        would have understated exactly this."""
        p = load_params(PARAMS)
        lo = copy.deepcopy(p); hi = copy.deepcopy(p)
        lo["hydronics"]["flow_m3_h"] = Param(1.24, unit="m3/h", kind="specified")
        hi["hydronics"]["flow_m3_h"] = Param(1.44, unit="m3/h", kind="specified")
        r = derived.q_max_coeff(hi).value / derived.q_max_coeff(lo).value
        assert r == pytest.approx(1.44 / 1.24, rel=0.01)

    def test_ua_sa_matches_the_hand_identification(self):
        """m_dot_c 1670 * 2.10 K / (25.37 - 19.20) = 568 W/K."""
        p = load_params(PARAMS)
        assert derived.ua_sa(p).value == pytest.approx(568.0, rel=0.01)


class TestSamplingRespectsPhysics:
    def test_a_bounded_parameter_is_never_sampled_past_its_bound(self):
        """`flow_m3_h` sits ON its upper bound - the pump is pinned at 100 % -
        so an untruncated Gaussian would put half its mass above a flow the
        exchanger physically cannot pass."""
        import random
        from optimizer.derived import _sample
        f = Param(1.44, sigma=0.07, bounds=[0.58, 1.44], kind="specified")
        rng = random.Random(1)
        draws = [_sample(f, rng) for _ in range(500)]
        assert max(draws) <= 1.44 and min(draws) >= 0.58

    def test_derived_quantities_report_a_real_spread(self):
        p = load_params(PARAMS)
        for u in (derived.mdot_c(p), derived.ua_sa(p), derived.q_max_coeff(p)):
            assert u.sigma > 0
        # P04_opt must be known better than the 1 K register quantisation, or
        # the controller cannot pick the right integer.
        assert derived.p04_opt(p, 16.5, 26.0).sigma < 0.5


class TestSolarRoomSplit:
    """The real params.yaml, not a synthetic copy.

    tests/test_optimizer_solar.py exercises the mechanism against its own
    table; this checks that the file actually shipped agrees with it. Without
    this, a decimal slip in params.yaml would leave every unit test green while
    the plant quietly misattributed sunshine between rooms.
    """

    @staticmethod
    def _solar() -> dict:
        return yaml.safe_load(pathlib.Path(PARAMS).read_text())["solar"]

    def test_every_room_facade_exists_in_the_facade_table(self):
        s = self._solar()
        known = {f["name"] for f in s["facades"]}
        for room, split in (s.get("rooms") or {}).items():
            assert set(split) <= known, f"{room} references unknown facade"

    def test_rooms_never_claim_more_aperture_than_the_facade_has(self):
        """A window belongs to exactly one room. Over-assignment means one got
        counted twice, and the house would predict more gain per room than it
        admits in total."""
        s = self._solar()
        per_facade = {f["name"]: f["aperture_m2"] for f in s["facades"]}
        claimed: dict[str, float] = {}
        for split in (s.get("rooms") or {}).values():
            for facade, area in split.items():
                claimed[facade] = claimed.get(facade, 0.0) + area
        for facade, total in claimed.items():
            assert total <= per_facade[facade] + 0.005, (
                f"{facade}: rooms claim {total} of {per_facade[facade]}")

    def test_east_and_south_stay_fully_assigned(self):
        """The closure that is EVIDENCE the floor-plan reading was right.

        The assigned ground-floor windows sum exactly to the certificate's
        per-facade totals minus the upper floor, on both facades that carry
        the gain. Breaking this means the assignment no longer matches the
        survey it was audited against - so the numbers stop being the audited
        ones even if they still look plausible.
        """
        s = self._solar()
        per_facade = {f["name"]: f["aperture_m2"] for f in s["facades"]}
        claimed: dict[str, float] = {}
        for split in (s.get("rooms") or {}).values():
            for facade, area in split.items():
                claimed[facade] = claimed.get(facade, 0.0) + area
        for facade in ("E", "S"):
            assert claimed[facade] == pytest.approx(per_facade[facade],
                                                    abs=0.005)

    def test_room_names_are_rooms_heatctl_actually_has(self):
        """A typo here is silent: layer 1 looks the room up by name, misses,
        and falls back to zero gain - which looks exactly like night."""
        s = self._solar()
        rooms = {r["name"] for r in yaml.safe_load(
            pathlib.Path("config.yaml").read_text())["rooms"]}
        assert set(s.get("rooms") or {}) <= rooms
