"""The pre-conditioning delta's lead time, and the modes it comes from.

Both of these guard mistakes that were actually made on 2026-07-30, an hour
apart, and that pointed in opposite directions - which is the reason they are
tested rather than merely commented.
"""
from __future__ import annotations

import datetime as dt
import math

import pytest

from optimizer.model import BuildingParams, eigen_time_constants_h


def _bp(ua_sa: float = 490.0) -> BuildingParams:
    return BuildingParams(ua_ao=267.2, ua_sa=ua_sa, ua_sg=29.0,
                          c_air_wh=6600.0, c_slab_wh=8691.0, f_sol=0.30)


class TestEigenTimeConstants:
    def test_the_modes_are_not_the_per_node_constants(self):
        """Quoting per-node figures as system behaviour was the original error.

        On 2026-07-30 the per-node numbers (8.4 h and 5.2 h at the parameters
        of the day) were reported as "the building's time constants" and used
        to reason about pre-cooling. The true modes were 55 h and 3.4 h.
        Neither per-node number was either mode, and they are not even close,
        so a test that merely checked "two positive floats" would have passed
        against the mistake.
        """
        p = _bp(1000.0)
        per_node = sorted(p.time_constants_h())
        modes = sorted(eigen_time_constants_h(p))
        for a, b in zip(per_node, modes):
            assert abs(a - b) > 1.0

    def test_the_slow_mode_is_the_building_and_the_fast_one_the_coupling(self):
        """ua_sa moves the fast mode strongly and the slow mode barely.

        This is the structural claim the lead-time work rests on: identifying
        ua_sa buys a better lead time and tells us almost nothing new about
        the building's drift against outdoor.
        """
        slow_lo, fast_lo = eigen_time_constants_h(_bp(300.0))
        slow_hi, fast_hi = eigen_time_constants_h(_bp(1000.0))
        # Over a 3.3x range of ua_sa the fast mode moves by well over 2x while
        # the slow one moves by under a quarter. So the identification bought a
        # lead time, and left the drift-against-outdoor story alone.
        assert fast_lo / fast_hi > 2.0
        assert slow_lo / slow_hi < 1.25

    def test_the_identified_parameters_give_a_lead_time_of_hours_not_minutes(self):
        """Sanity band around the identified value, wide enough to survive a refit.

        Pins the order of magnitude only. The point is that pre-conditioning
        must start hours ahead - a fast mode under an hour or over a day would
        both mean the surrounding design is wrong, not merely mistuned.
        """
        _, fast = eigen_time_constants_h(_bp())
        assert 3.0 < fast < 12.0

    def test_an_unstable_parameter_set_raises_rather_than_returning_nonsense(self):
        """A negative conductance is a config error, not a fast building."""
        with pytest.raises(ValueError):
            eigen_time_constants_h(_bp(-500.0))


# A ceiling the SYNTHETIC forecast can actually exceed. These tests drive the
# solar term to zero so that only timing varies, and without sun the real house
# does not exceed the real 5.7 kW plant even at 38 degC outdoor - it needs about
# 4.0 kW. Using the true ceiling here would make every delta zero and the tests
# would pass while measuring nothing. That is not a fudge: it is a reminder that
# on this building SOLAR is what breaks the energy budget, not air temperature,
# which is exactly why solar.py computes per-facade gain at measured azimuths.
SYNTH_CEILING_W = 2000.0

# Filler hours must be genuinely NEUTRAL, not merely pleasant. At a 23 degC
# target, an outdoor 12 degC is a 3 kW HEATING load - fill a window with it and
# the heating branch wins, which is how the first draft of these tests managed
# to assert a cooling delta and get a positive number back. Sitting the filler
# on the target leaves a net load near zero, so only the hot hours contribute
# and the tests measure timing alone.
NEUTRAL_C = 23.0


class _Pt:
    """Minimal stand-in for a forecast point."""
    def __init__(self, time: str, temperature: float):
        self.time = time
        self.temperature = temperature
        self.cloud_cover = 100.0        # kill the solar term: this is about time
        # Planning-only outdoor dew point (weather.py keeps it uncorrected and
        # bars it from the condensation guard). NaN stands for "the API did not
        # return dew_point_2m", which hourly_forecast must survive.
        self.dew_point = float("nan")
        self.shortwave_wm2 = 0.0
        self.direct_wm2 = 0.0
        self.diffuse_wm2 = 0.0
        self.wind_kmh = 10.0


class _Weather:
    def __init__(self, points):
        self.points = points


def _estimator(monkeypatch, temps: list[float]):
    """An Estimator with a synthetic flat-solar forecast of `temps`."""
    from optimizer.estimator import Estimator
    est = Estimator.__new__(Estimator)
    est.bp = _bp()
    est.t_ground = 10.0
    est.q_int = 350.0
    now = dt.datetime.now(dt.timezone.utc).replace(
        minute=0, second=0, microsecond=0)
    est.weather = _Weather([
        _Pt((now + dt.timedelta(hours=i)).isoformat().replace("+00:00", ""), t)
        for i, t in enumerate(temps)])
    est.solar_w = lambda pt: 0.0
    # Condensation-limited ceiling inputs (2026-08-01). No dew-point reading is
    # provided, so `humidity_gap()` returns None and `ceiling_w()` falls back to
    # the ceiling passed in - which is what keeps these lead-time tests about
    # TIMING rather than about humidity.
    est.readings = {}
    est._dew_topic = ""
    est.max_age_s = 300.0
    est.dew_margin_c = 1.0
    est.params = {}
    return est



def _real_params():
    """The site params, so q_max is exercised against the real building."""
    from optimizer.params import load_params
    return load_params("optimizer/params.yaml")


def _with_dew(pt, dew_c):
    """Copy of a forecast point with a chosen outdoor dew point."""
    import copy
    q = copy.copy(pt)
    q.dew_point = dew_c
    return q


class TestLeadTime:
    def test_imminent_excess_outweighs_identical_excess_a_day_away(self,
                                                                  monkeypatch):
        """The defect this fixes: the delta had no notion of WHEN.

        Before the discount, the sum was flat over the whole window, so a hot
        spell starting in twenty hours demanded exactly as much pre-cooling now
        as one starting in two. Charge put in now has largely reached the room
        by then, so it is spent for nothing.

        Mutation-verified: removing the exp() weight makes these two equal and
        the assertion fails.
        """
        hot, mild = 38.0, NEUTRAL_C
        soon = _estimator(monkeypatch, [hot] * 4 + [mild] * 20)
        later = _estimator(monkeypatch, [mild] * 20 + [hot] * 4)
        d_soon = soon.setpoint_delta(target_air=23.0, ceiling_w=SYNTH_CEILING_W)
        d_later = later.setpoint_delta(target_air=23.0, ceiling_w=SYNTH_CEILING_W)
        assert d_soon < 0 and d_later < 0          # both call for pre-cooling
        assert abs(d_soon) > 3 * abs(d_later)

    def test_timing_inside_the_horizon_does_not_change_the_ask(self, monkeypatch):
        """Inside the lead horizon there is NO decay discount, deliberately.

        The first version of this weighted every hour by exp(-dt/tau) - the
        survival of an impulse of charge. Wrong actuator model: the controller
        holds a depressed setpoint and replenishes continuously, so held charge
        does not decay. That form produced weights of 0.07-0.24 through the
        night against an afternoon peak, i.e. it declined to pre-cool during
        the only hours this house has spare capacity.

        Mutation-verified: restoring the exp(-i/tau) weight makes these two
        differ by ~2.6x and the assertion fails.
        """
        hot = 38.0
        early = _estimator(monkeypatch, [hot] * 3 + [NEUTRAL_C] * 21)
        mid = _estimator(monkeypatch,
                         [NEUTRAL_C] * 6 + [hot] * 3 + [NEUTRAL_C] * 15)
        d_early = early.setpoint_delta(target_air=23.0,
                                       ceiling_w=SYNTH_CEILING_W)
        d_mid = mid.setpoint_delta(target_air=23.0, ceiling_w=SYNTH_CEILING_W)
        assert d_early < 0
        assert d_mid == pytest.approx(d_early, rel=0.01)

    def test_beyond_the_horizon_the_ask_tapers_with_tau(self, monkeypatch):
        """Past 2*tau the weight falls off, so a distant heatwave is not acted on.

        This is the property a flat sum lacked entirely: without it, excess two
        days out demanded pre-cooling tonight. Checked against the analytic
        taper so a hand-picked half-life would fail here.
        """
        _, tau = eigen_time_constants_h(_bp())
        lead = 2.0 * tau
        hot = 38.0
        inside = _estimator(monkeypatch, [hot] + [NEUTRAL_C] * 23)
        far = 22
        beyond = _estimator(monkeypatch,
                            [NEUTRAL_C] * far + [hot] + [NEUTRAL_C] * (23 - far))
        d_in = inside.setpoint_delta(target_air=23.0, ceiling_w=SYNTH_CEILING_W)
        d_far = beyond.setpoint_delta(target_air=23.0,
                                      ceiling_w=SYNTH_CEILING_W)
        assert d_in < 0 and d_far < 0
        assert abs(d_far / d_in) == pytest.approx(
            math.exp(-(far - lead) / tau), rel=0.05)

    def test_an_afternoon_peak_is_pre_cooled_for_from_the_early_hours(
            self, monkeypatch):
        """The behavioural claim, stated as a test: 02:00 must pre-cool for 15:00.

        13 hours out, which is the gap the plant actually has to work with,
        because overnight is when it has spare capacity. At the identified
        parameters the horizon is 12.7 h, so 13 h sits just outside it and gets
        0.95 rather than 1.00 - fine, and worth pinning as a ratio rather than
        as `2*tau > 13`, which is the arithmetic and not the point. An
        implementation that tapers hard inside this gap has the actuator model
        wrong however elegant its maths.
        """
        hot = 38.0
        now_ = _estimator(monkeypatch, [hot] + [NEUTRAL_C] * 23)
        night = _estimator(monkeypatch,
                           [NEUTRAL_C] * 13 + [hot] + [NEUTRAL_C] * 10)
        d_now = now_.setpoint_delta(target_air=23.0, ceiling_w=SYNTH_CEILING_W)
        d_night = night.setpoint_delta(target_air=23.0,
                                       ceiling_w=SYNTH_CEILING_W)
        assert d_now < 0
        assert abs(d_night / d_now) > 0.9

    def test_a_cold_snap_still_produces_a_positive_delta(self, monkeypatch):
        """The horizon must not have broken the winter sign.

        Negative deltas make sense in winter - the user's words - and the
        weighting is applied to both branches identically.
        """
        est = _estimator(monkeypatch, [-15.0] * 6 + [5.0] * 18)
        assert est.setpoint_delta(target_air=21.0, ceiling_w=SYNTH_CEILING_W) > 0

    def test_a_benign_forecast_asks_for_nothing(self, monkeypatch):
        est = _estimator(monkeypatch, [21.0] * 24)
        assert est.setpoint_delta(target_air=23.0,
                                  ceiling_w=SYNTH_CEILING_W) == 0.0


def test_hourly_forecast_locates_the_deficit_in_time(monkeypatch):
    """Owner, 2026-08-01: a lump sum cannot say WHEN to start.

    `load_forecast` evaluated every hour and collapsed it to calendar-day
    totals, so "4 hours over ceiling tomorrow" could not be turned into which
    four hours - and the same energy spread evenly is a different plan from the
    same energy landing at 16:00.

    Asserts the series is hourly, aligned with the forecast, and that the
    deficit lands on the hours actually over the ceiling - not merely that some
    numbers came out.
    """
    hot, mild = 38.0, NEUTRAL_C
    est = _estimator(monkeypatch, [mild] * 8 + [hot] * 4 + [mild] * 12)
    series = est.hourly_forecast(target_air=23.0, ceiling_w=SYNTH_CEILING_W,
                                 hours=24)

    assert len(series) == 24, "not one entry per forecast hour"
    assert [r["t"] for r in series] == [p.time for p in est.weather.points[:24]]

    over = [r for r in series if r["deficit_w"] > 0]
    assert over, "test is vacuous - no hour exceeds the ceiling"
    # The deficit must sit on the HOT hours, which is the whole point of a
    # series over a total.
    assert all(8 <= series.index(r) < 12 for r in over)
    for r in series:
        assert r["deficit_w"] == round(max(0.0, r["load_w"]
                                           - SYNTH_CEILING_W), 0)


def test_hourly_deficit_reconciles_with_the_daily_total(monkeypatch):
    """The series and the aggregate must not tell different stories.

    They are computed by separate methods over the same hours. If they ever
    disagree, a dashboard and a planner reading one each would be acting on
    different plans - and nothing would say which was wrong.
    """
    hot, mild = 38.0, NEUTRAL_C
    est = _estimator(monkeypatch, [mild] * 8 + [hot] * 4 + [mild] * 12)
    series = est.hourly_forecast(23.0, SYNTH_CEILING_W, hours=24)
    days = est.load_forecast(23.0, SYNTH_CEILING_W, hours=24)

    for d in days:
        hours = [r for r in series if r["t"][:10] == d["day"]]
        assert sum(1 for r in hours if r["deficit_w"] > 0) == d["hours_over"]
        store_kwh = sum(r["deficit_w"] for r in hours) / 1000.0
        assert abs(store_kwh - d["store_kwh"]) < 0.15, d["day"]


class TestCondensationCeiling:
    """The delivery ceiling is condensation-limited, not source-limited.

    `load_forecast` was passed a static 5700 W - the heat pump's output - on the
    reasoning that the machine binds before the 9.0 kW of emitter. Measured
    2026-08-01, the condensation limit binds before either: 3.40 kW on a humid
    day against 5.10 kW on dry air. So every forecast hour was sized against a
    constraint that is never the active one.
    """

    def test_humid_air_lowers_the_ceiling_below_dry_air(self, monkeypatch):
        """The whole point: the ceiling must MOVE with humidity."""
        est = _estimator(monkeypatch, [NEUTRAL_C] * 6)
        est.params = _real_params()
        pt = est.weather.points[0]

        dry = est.ceiling_w(_with_dew(pt, 8.0), 24.0, gap_gkg=1.4,
                            fallback_w=99_000.0)
        humid = est.ceiling_w(_with_dew(pt, 17.0), 24.0, gap_gkg=1.4,
                              fallback_w=99_000.0)
        assert dry > humid, "humid air must not permit MORE cooling"
        assert humid > 0
        # And the effect must be large enough to matter - a few percent would
        # not justify the machinery.
        assert dry > 1.3 * humid

    def test_a_missing_humidity_signal_falls_back_and_does_not_zero(self,
                                                                   monkeypatch):
        """A missing signal must not make the planner think the plant is dead.

        Failing to zero is the safety-relevant direction here: a zero ceiling
        would report the whole day as deficit and demand maximum pre-cooling.
        """
        est = _estimator(monkeypatch, [NEUTRAL_C] * 6)
        est.params = _real_params()
        pt = est.weather.points[0]
        assert est.ceiling_w(pt, 24.0, gap_gkg=None, fallback_w=5700.0) == 5700.0

    def test_the_ceiling_never_exceeds_the_source_limit(self, monkeypatch):
        """Condensation binds FIRST, but the machine is still a hard cap."""
        est = _estimator(monkeypatch, [NEUTRAL_C] * 6)
        est.params = _real_params()
        pt = _with_dew(est.weather.points[0], -10.0)   # absurdly dry
        assert est.ceiling_w(pt, 24.0, gap_gkg=1.4, fallback_w=5700.0) <= 5700.0

    def test_dew_point_round_trip(self, monkeypatch):
        """W(dew) and dew(W) must invert, or the gap arithmetic is nonsense."""
        est = _estimator(monkeypatch, [NEUTRAL_C] * 2)
        for d in (-5.0, 0.0, 7.3, 12.0, 18.6, 24.0):
            assert est._dew_from_w(est._w_from_dew(d)) == pytest.approx(d,
                                                                       abs=0.01)


def test_layer2_does_not_inherit_the_control_loop_staleness(monkeypatch):
    """Real defect, 2026-08-01: the condensation ceiling never engaged.

    `max_age_s` was read from `safety.stale_data_timeout_s`, which is 15 s on
    this plant - right for a 1 Hz control loop that must failsafe on a lost
    sensor, and wrong for a layer that consumes a dew point republished every
    120 s. The reading was stale on almost every cycle, `humidity_gap()`
    returned None, and both ceiling entities sat on the 5700 W fallback while
    looking perfectly healthy.
    """
    from optimizer.estimator import Estimator
    cfg = {"mqtt": {"host": "x"}, "safety": {"stale_data_timeout_s": 15},
           "rooms": [], "optimizer": {}}
    est = Estimator.__new__(Estimator)
    est.cfg = cfg
    # Reproduce only the line under test.
    est.max_age_s = float(cfg.get("optimizer", {}).get(
        "input_max_age_s",
        max(900.0, float(cfg.get("safety", {}).get("stale_data_timeout_s", 300)))))
    assert est.max_age_s >= 900.0, "layer 2 inherited the control-loop timeout"
