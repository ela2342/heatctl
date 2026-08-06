"""Slab energy: target, estimate and excess.

This is feedforward, so nothing downstream will notice if it is quietly wrong -
which is exactly why the sign conventions and the refusal paths are tested
harder than the arithmetic.
"""
from __future__ import annotations

import math

import pytest

from heatctl.energy import EnergyDemand, slab_estimate_c, slab_target_c


CFG = {
    "control": {"energy": {"building": {
        "ua_ao_w_per_k": 240.0, "ua_sa_w_per_k": 490.0,
        "c_slab_wh_per_m2_k": 63.7, "q_internal_w": 350.0}}},
    "rooms": [
        {"name": "wohnzimmer", "floor_area_m2": 40.0, "circuits": []},
        {"name": "bad", "floor_area_m2": 10.0, "circuits": []},
        {"name": "unmeasured", "circuits": []},          # no area on purpose
    ],
}


class TestSlabTarget:
    def test_heating_puts_the_slab_above_the_room(self):
        """Cold outside -> the floor must be warmer than the room."""
        t = slab_target_c(21.0, outdoor_c=-5.0, ua_ao=240.0, ua_sa=490.0)
        assert t > 21.0

    def test_cooling_puts_the_slab_below_the_room(self):
        """The same expression, no cooling branch.

        The whole reason §2 is written as a balance rather than as a heating
        curve is that the sign falls out. A regression here would most likely
        arrive as someone 'fixing' cooling with an `if mode ==` - this fails
        if they do.
        """
        t = slab_target_c(23.0, outdoor_c=33.0, ua_ao=240.0, ua_sa=490.0)
        assert t < 23.0

    def test_solar_gain_lowers_the_required_slab_temperature(self):
        """Free heat means the floor has to supply less of it."""
        dark = slab_target_c(21.0, -5.0, 240.0, 490.0, q_sol_w=0.0)
        sunny = slab_target_c(21.0, -5.0, 240.0, 490.0, q_sol_w=800.0)
        assert sunny < dark

    def test_at_thermal_equilibrium_the_slab_sits_at_room_temperature(self):
        """No loss and no gains -> nothing for the floor to do."""
        t = slab_target_c(22.0, outdoor_c=22.0, ua_ao=240.0, ua_sa=490.0,
                          q_sol_w=0.0, q_int_w=0.0)
        assert t == pytest.approx(22.0)

    def test_a_zero_conductance_raises_rather_than_returning_infinity(self):
        with pytest.raises(ValueError):
            slab_target_c(21.0, -5.0, ua_ao=240.0, ua_sa=0.0)


class TestSlabEstimate:
    def test_without_ntu_it_falls_back_to_the_return_reading(self):
        """The low-flow approximation, used everywhere today."""
        assert slab_estimate_c(24.0, vl_c=30.0, ntu=None) == 24.0

    def test_a_large_ntu_means_the_water_reached_slab_temperature(self):
        """High NTU = long residence = RL has equilibrated with the slab."""
        assert slab_estimate_c(24.0, vl_c=30.0, ntu=8.0) == pytest.approx(
            24.0, abs=0.02)

    def test_a_small_ntu_implies_a_slab_far_from_the_return_reading(self):
        """Little exchange: RL is still near VL, so the slab must be far off.

        This is the correction the fallback cannot make, and the reason
        NTU(opening) is on the identification ladder rather than optional.
        """
        est = slab_estimate_c(rl_c=29.0, vl_c=30.0, ntu=0.2)
        assert est < 25.0

    def test_the_inversion_round_trips(self):
        """Forward model and inverse must agree, or the algebra is wrong."""
        slab, vl, ntu = 22.0, 30.0, 1.3
        rl = slab + (vl - slab) * math.exp(-ntu)
        assert slab_estimate_c(rl, vl, ntu) == pytest.approx(slab, abs=1e-9)


class TestRoomEnergy:
    def test_a_warm_slab_in_cooling_reads_as_stored_excess(self):
        """Sign convention, stated once and pinned here: + = too much energy."""
        e = EnergyDemand(CFG)
        r = e.room("wohnzimmer", setpoint_c=23.0, outdoor_c=33.0,
                   rl_c=26.0, vl_c=18.0)
        assert r.valid and r.excess_wh > 0

    def test_excess_scales_with_room_size(self):
        """Same temperature error, four times the floor, four times the energy."""
        e = EnergyDemand(CFG)
        big = e.room("wohnzimmer", 23.0, 33.0, rl_c=26.0, vl_c=18.0)
        small = e.room("bad", 23.0, 33.0, rl_c=26.0, vl_c=18.0)
        assert big.excess_wh == pytest.approx(4.0 * small.excess_wh, rel=1e-6)

    @pytest.mark.parametrize("kwargs,reason", [
        (dict(outdoor_c=None, rl_c=24.0), "no outdoor temp"),
        (dict(outdoor_c=30.0, rl_c=None), "no return temp"),
    ])
    def test_missing_inputs_refuse_rather_than_guess(self, kwargs, reason):
        """A target built on an absent input is fabricated, not degraded.

        The caller has to be able to tell those apart, so the cause survives
        in `reason` instead of collapsing into a None.
        """
        e = EnergyDemand(CFG)
        r = e.room("wohnzimmer", 23.0, vl_c=18.0, **kwargs)
        assert not r.valid and r.reason == reason
        assert r.excess_wh is None

    def test_an_invalid_rl_still_yields_a_target(self):
        """The target is feedforward - it does not need the measurement.

        Worth keeping: it means a circuit whose RL is untrustworthy still has
        somewhere to aim once the reading returns.
        """
        e = EnergyDemand(CFG)
        r = e.room("wohnzimmer", 23.0, 33.0, rl_c=26.0, vl_c=18.0,
                   rl_valid=False)
        assert not r.valid and r.target_c is not None

    def test_a_room_with_no_floor_area_is_refused(self):
        """Every per-room split runs off area, so an absent one is not usable."""
        e = EnergyDemand(CFG)
        r = e.room("unmeasured", 23.0, 33.0, rl_c=26.0, vl_c=18.0)
        assert not r.valid and r.reason == "no floor area"

    def test_the_house_total_understates_rather_than_extrapolates(self):
        """Two of three rooms estimable -> sum those two, do not scale up.

        Extrapolating a partially instrumented house to a whole one is how a
        plant confidently does the wrong amount. Understating only makes it do
        less than it might.
        """
        e = EnergyDemand(CFG)
        rooms = [e.room("wohnzimmer", 23.0, 33.0, 26.0, 18.0),
                 e.room("bad", 23.0, 33.0, 26.0, 18.0),
                 e.room("unmeasured", 23.0, 33.0, 26.0, 18.0)]
        total = e.house_excess_wh(rooms)
        assert total == pytest.approx(rooms[0].excess_wh + rooms[1].excess_wh)

    def test_no_estimable_room_gives_none_not_zero(self):
        """Zero would read as 'nothing to do'; None reads as 'do not know'."""
        e = EnergyDemand(CFG)
        rooms = [e.room("wohnzimmer", 23.0, None, 26.0, 18.0)]
        assert e.house_excess_wh(rooms) is None

    def test_layer2_parameters_are_accepted_and_used(self):
        """Refinement arrives as parameters, never as commands."""
        e = EnergyDemand(CFG)
        before = e.room("wohnzimmer", 23.0, 33.0, rl_c=20.0, vl_c=16.0)
        e.update_params(ntu={"wohnzimmer": 0.3})
        after = e.room("wohnzimmer", 23.0, 33.0, rl_c=20.0, vl_c=16.0)
        assert after.slab_c != before.slab_c


class TestRecoveryTerm:
    """The error term - the only feedback in the scheme, and it was missing.

    Caught on 2026-08-06 by checking the first version against the live plant:
    Wohnzimmer 2.6 K above setpoint produced a holding target of 19.84 degC
    against a slab measuring 15-17, i.e. "nothing to do" while the room was
    plainly too warm. A steady-state target holds; it cannot recover.
    """

    def test_a_warm_room_pulls_the_target_below_the_holding_value(self):
        """Mutation-verified: dropping the q_recover term makes these equal."""
        hold = slab_target_c(23.0, 28.0, 240.0, 490.0)
        recover = slab_target_c(23.0, 28.0, 240.0, 490.0,
                                room_c=25.6, c_air_wh=6600.0 * 0.3)
        assert recover < hold

    def test_a_cold_room_in_heating_pulls_the_target_up(self):
        """The same term, opposite sign - no mode branch."""
        hold = slab_target_c(21.0, -5.0, 240.0, 490.0)
        recover = slab_target_c(21.0, -5.0, 240.0, 490.0,
                                room_c=18.0, c_air_wh=6600.0 * 0.3)
        assert recover > hold

    def test_a_room_at_setpoint_gets_exactly_the_holding_target(self):
        """No error, no correction - the terms must not interfere."""
        hold = slab_target_c(23.0, 28.0, 240.0, 490.0)
        at_sp = slab_target_c(23.0, 28.0, 240.0, 490.0,
                              room_c=23.0, c_air_wh=6600.0 * 0.3)
        assert at_sp == pytest.approx(hold)

    def test_an_unknown_room_temperature_gives_the_holding_target(self):
        """Four of seven rooms today. Hold where they are, do not guess."""
        hold = slab_target_c(23.0, 28.0, 240.0, 490.0)
        unknown = slab_target_c(23.0, 28.0, 240.0, 490.0,
                                room_c=None, c_air_wh=6600.0 * 0.3)
        assert unknown == pytest.approx(hold)

    def test_a_shorter_recovery_time_demands_a_colder_slab(self):
        """tau is the policy knob: faster correction costs a colder floor.

        It must never go below the plant's fast mode (5.62 h) - asking the
        building to move quicker than it can is what produced 1.2 K of
        overnight undershoot from a 0.39 K pre-charge request.
        """
        slow = slab_target_c(23.0, 28.0, 240.0, 490.0, room_c=25.6,
                             c_air_wh=6600.0 * 0.3, tau_recover_h=12.0)
        fast = slab_target_c(23.0, 28.0, 240.0, 490.0, room_c=25.6,
                             c_air_wh=6600.0 * 0.3, tau_recover_h=6.0)
        assert fast < slow

    def test_a_zero_recovery_time_raises(self):
        with pytest.raises(ValueError):
            slab_target_c(23.0, 28.0, 240.0, 490.0, room_c=25.0,
                          c_air_wh=2000.0, tau_recover_h=0.0)


class TestEmitterType:
    """Floor area does not imply thermal storage.

    Arbeitszimmer is 31.20 m2 on the OG with a fan coil. Multiplying that by
    `c_slab_wh_per_m2` invented 1987 Wh/K - 24 % of the assumed house total -
    in a room with no slab. And `c_slab_wh` is derived from the 136.40 m2
    GROUND FLOOR area, which does not contain that room, so the figure was
    wrong twice over.
    """

    CFG_FC = {
        "control": {"energy": {"building": {
            "ua_ao_w_per_k": 240.0, "ua_sa_w_per_k": 490.0,
            "c_slab_wh_per_m2_k": 63.7, "q_internal_w": 350.0}}},
        "rooms": [
            {"name": "wohnzimmer", "floor_area_m2": 42.11, "circuits": []},
            {"name": "arbeitszimmer", "floor_area_m2": 31.20,
             "emitter": "fan_coil", "circuits": []},
        ],
    }

    def test_a_fan_coil_room_is_refused_a_slab_excess(self):
        """Mutation-verified: dropping the has_slab check returns an excess."""
        e = EnergyDemand(self.CFG_FC)
        r = e.room("arbeitszimmer", 23.0, 33.0, rl_c=26.0, vl_c=18.0)
        assert not r.valid
        assert r.excess_wh is None
        assert "no slab" in r.reason

    def test_a_fan_coil_room_still_gets_a_target(self):
        """The target says what water the room wants - that part is valid.

        Only the ENERGY figure is meaningless without a capacity, so the
        refusal is scoped to `excess`, not to the whole result.
        """
        e = EnergyDemand(self.CFG_FC)
        r = e.room("arbeitszimmer", 23.0, 33.0, rl_c=26.0, vl_c=18.0)
        assert r.target_c is not None

    def test_a_fan_coil_room_keeps_its_UA_share(self):
        """It is a real room losing heat through a real envelope.

        Excluding it from the area total would silently re-weight every other
        room's UA and slab share - a 24 % error introduced by a fix.
        """
        e = EnergyDemand(self.CFG_FC)
        assert e.room_share("arbeitszimmer") == pytest.approx(
            31.20 / (42.11 + 31.20))

    def test_slab_rooms_are_unaffected(self):
        e = EnergyDemand(self.CFG_FC)
        r = e.room("wohnzimmer", 23.0, 33.0, rl_c=26.0, vl_c=18.0)
        assert r.valid and r.excess_wh > 0

    def test_the_house_total_skips_the_fan_coil_room(self):
        """It contributes no slab energy, so it must not contribute a number."""
        e = EnergyDemand(self.CFG_FC)
        rooms = [e.room("wohnzimmer", 23.0, 33.0, 26.0, 18.0),
                 e.room("arbeitszimmer", 23.0, 33.0, 26.0, 18.0)]
        assert e.house_excess_wh(rooms) == pytest.approx(rooms[0].excess_wh)
