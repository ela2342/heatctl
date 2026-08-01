"""Parameters carry their uncertainty, and correlations stay structural (D-032).

The load-bearing test here is `test_k_is_invariant_to_the_flow`. Everything
else is schema hygiene; that one is the thesis.
"""
from __future__ import annotations

import copy

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
