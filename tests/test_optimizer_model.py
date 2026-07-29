"""Layer 2 model and filter.

Conventions follow the rest of the suite: where a test guards a direction of
failure it asserts the direction, not merely that something happened.
"""
from __future__ import annotations

import math

import pytest

from optimizer.kalman import (KalmanFilter, expm, eye, inverse, matmul,
                              transpose)
from optimizer.model import (N_INPUTS, U_HEAT, U_OUTDOOR, BuildingParams,
                             continuous, discretise, heat_demand_w,
                             net_load_w, steady_state_air)

PARAMS = BuildingParams(ua_ao=267.2, ua_sa=1000.0, ua_sg=29.0,
                        c_air_wh=6600.0, c_slab_wh=8691.0, f_sol=0.30)


# ---------- linear algebra ----------

def test_expm_matches_the_closed_form_for_a_diagonal_matrix():
    e = expm([[-0.5, 0.0], [0.0, -2.0]])
    assert e[0][0] == pytest.approx(math.exp(-0.5), rel=1e-9)
    assert e[1][1] == pytest.approx(math.exp(-2.0), rel=1e-9)
    assert e[0][1] == 0.0 and e[1][0] == 0.0


def test_expm_matches_the_closed_form_for_a_rotation_generator():
    """[[0,-t],[t,0]] exponentiates to a rotation by t - a case that catches
    a truncated series being stopped too early, because the off-diagonal
    terms only converge through the alternating higher-order terms."""
    t = 0.7
    e = expm([[0.0, -t], [t, 0.0]])
    assert e[0][0] == pytest.approx(math.cos(t), abs=1e-12)
    assert e[0][1] == pytest.approx(-math.sin(t), abs=1e-12)


def test_inverse_round_trips():
    a = [[4.0, 7.0, 2.0], [3.0, 6.0, 1.0], [2.0, 5.0, 3.0]]
    prod = matmul(a, inverse(a))
    for i in range(3):
        for j in range(3):
            assert prod[i][j] == pytest.approx(1.0 if i == j else 0.0, abs=1e-9)


def test_inverse_raises_on_a_singular_matrix_rather_than_guessing():
    """A silently wrong inverse corrupts the state covariance, and the filter
    then drifts for hours looking healthy. Failing loudly is the point."""
    with pytest.raises(ValueError):
        inverse([[1.0, 2.0], [2.0, 4.0]])


# ---------- model structure ----------

def test_time_constants_are_in_a_physically_sane_range():
    """Guards against a unit slip in params.yaml: C is quoted in Wh/K by the
    building survey and used in J/K internally, and a missing factor of 3600
    would put the building's time constants in seconds."""
    air_h, slab_h = PARAMS.time_constants_h()
    assert 1.0 < air_h < 100.0
    assert 1.0 < slab_h < 100.0


def test_discretisation_preserves_the_steady_state():
    """Stepping the discrete model from its own continuous-time equilibrium
    must not move it. This is the check that F and G were read off the Van
    Loan block in the right places - a transposed or swapped block still
    produces plausible-looking dynamics but a different fixed point."""
    outdoor, q_heat, ground = -5.0, 4000.0, 10.0
    air = steady_state_air(PARAMS, outdoor, ground, q_heat)
    a, b = continuous(PARAMS)
    # Recover the slab equilibrium from the air equation.
    slab = air + (PARAMS.ua_ao * (air - outdoor)) / PARAMS.ua_sa
    u = [0.0] * N_INPUTS
    u[U_OUTDOOR], u[U_HEAT] = outdoor, q_heat
    u[4] = ground
    F, G = discretise(PARAMS, 60.0)
    x = [air, slab]
    for _ in range(200):
        x = [sum(F[i][k] * x[k] for k in range(2))
             + sum(G[i][k] * u[k] for k in range(N_INPUTS)) for i in range(2)]
    assert x[0] == pytest.approx(air, abs=1e-6)
    assert x[1] == pytest.approx(slab, abs=1e-6)


def test_discretisation_is_independent_of_the_step_used_to_reach_a_time():
    """Twenty steps of 60 s must land where one step of 1200 s lands. If this
    fails the discretisation is an Euler approximation dressed up as an exact
    one, and every result would depend on the sample rate."""
    u = [0.0] * N_INPUTS
    u[U_OUTDOOR], u[U_HEAT], u[4] = 0.0, 3000.0, 10.0
    F1, G1 = discretise(PARAMS, 60.0)
    F2, G2 = discretise(PARAMS, 1200.0)
    x = [20.0, 22.0]
    for _ in range(20):
        x = [sum(F1[i][k] * x[k] for k in range(2))
             + sum(G1[i][k] * u[k] for k in range(N_INPUTS)) for i in range(2)]
    y = [sum(F2[i][k] * [20.0, 22.0][k] for k in range(2))
         + sum(G2[i][k] * u[k] for k in range(N_INPUTS)) for i in range(2)]
    assert x[0] == pytest.approx(y[0], abs=1e-6)
    assert x[1] == pytest.approx(y[1], abs=1e-6)


def test_a_colder_outside_needs_more_heat():
    warm = heat_demand_w(PARAMS, 21.0, 5.0, 10.0)
    cold = heat_demand_w(PARAMS, 21.0, -10.0, 10.0)
    assert cold > warm > 0.0


def test_demand_matches_the_measured_building_heat_loss_coefficient():
    """The whole point of ua_ao being 267 W/K is that it reproduces the
    measured loss. At a 20 K difference with no gains the answer must be
    close to 267*20, the small excess being the ground path."""
    q = heat_demand_w(PARAMS, 20.0, 0.0, 10.0)
    assert q == pytest.approx(267.2 * 20.0, rel=0.15)
    assert q > 267.2 * 20.0    # ground loss is additional, never a discount


def test_solar_gain_reduces_demand():
    dark = heat_demand_w(PARAMS, 21.0, 0.0, 10.0, q_sol=0.0)
    sunny = heat_demand_w(PARAMS, 21.0, 0.0, 10.0, q_sol=2000.0)
    assert sunny < dark


def test_demand_is_clamped_at_zero_and_never_reports_negative_heating():
    """Gains exceeding losses is a COOLING demand, a different question with
    a different safety envelope (condensation). Returning a negative heating
    figure would invite a caller to treat the two as one signed quantity."""
    assert heat_demand_w(PARAMS, 18.0, 17.0, 10.0, q_sol=20000.0) == 0.0


def test_steady_state_air_and_heat_demand_are_inverses():
    q = heat_demand_w(PARAMS, 21.5, -3.0, 10.0)
    assert steady_state_air(PARAMS, -3.0, 10.0, q) == pytest.approx(21.5,
                                                                    abs=0.05)


# ---------- filter ----------

def _filter() -> KalmanFilter:
    return KalmanFilter(x=[20.0, 20.0], P=[[1.0, 0.0], [0.0, 25.0]],
                        Q=[[1e-4, 0.0], [0.0, 1e-3]], R=[[0.25]],
                        H=[[1.0, 0.0]])


def test_the_filter_converges_towards_a_constant_measurement():
    f = _filter()
    for _ in range(50):
        f.predict(eye(2), [[0.0], [0.0]], [0.0])
        f.update([21.0])
    assert f.x[0] == pytest.approx(21.0, abs=0.05)
    assert f.P[0][0] < 1.0


def test_the_covariance_stays_symmetric_and_positive_over_a_long_run():
    """Joseph form exists for exactly this. The textbook (I-KH)P update is
    algebraically identical and loses symmetry to rounding over thousands of
    steps - and this filter is meant to run for months without a restart."""
    f = _filter()
    for i in range(3000):
        f.predict(eye(2), [[0.0], [0.0]], [0.0])
        f.update([20.0 + 0.1 * math.sin(i / 10.0)])
    assert f.P[0][1] == pytest.approx(f.P[1][0], abs=1e-12)
    assert f.P[0][0] > 0.0 and f.P[1][1] > 0.0
    assert f.P[0][0] * f.P[1][1] - f.P[0][1] * f.P[1][0] > 0.0


def test_the_unmeasured_slab_state_is_still_predicted_when_air_goes_quiet():
    """The reason to run a filter at all rather than difference readings. A
    room sensor dropping out must not stop the slab estimate advancing."""
    f = _filter()
    F, G = discretise(PARAMS, 600.0)
    u = [0.0] * N_INPUTS
    u[U_OUTDOOR], u[U_HEAT], u[4] = -5.0, 6000.0, 10.0
    before = f.x[1]
    for _ in range(12):
        f.predict(F, G, u)          # no update at all
    assert f.x[1] > before          # heat is going in, so the slab warms


def test_a_dimension_mismatch_raises_instead_of_truncating_the_state():
    """zip() truncates to the shorter operand, so a G with the wrong row
    count would silently SHORTEN the state vector and the filter would carry
    on emitting plausible numbers. Found by this suite passing a 1x1 G to a
    2-state filter and getting an IndexError three steps later, far from the
    cause."""
    f = _filter()
    with pytest.raises(ValueError):
        f.predict(eye(2), [[0.0]], [0.0])          # G has one row, needs two
    with pytest.raises(ValueError):
        f.predict([[1.0, 0.0]], [[0.0], [0.0]], [0.0])   # F is 1x2
    assert len(f.x) == 2


def test_innovation_statistics_detect_a_biased_model():
    """The WP-F acceptance gate is stated in innovation terms, so a biased
    model has to be visible in these numbers and not just in a plot."""
    f = _filter()
    for _ in range(200):
        f.predict(eye(2), [[0.0], [0.0]], [0.0])
        f.update([25.0])            # persistently 5 K above the initial state
    biased = f.innovation_stats()

    g = _filter()
    for _ in range(200):
        g.predict(eye(2), [[0.0], [0.0]], [0.0])
        g.update([20.0])            # the state it already believes
    ok = g.innovation_stats()

    # The contrast is the test. A single threshold on lag-1 would be brittle:
    # a converging filter drives its own innovations to zero, so a persistent
    # model error shows up as a large MEAN with correlated early residuals,
    # and the correlation dilutes as the run lengthens.
    assert abs(biased["mean"]) > 10.0 * abs(ok["mean"])
    assert biased["lag1"] > ok["lag1"]


# ---------- signed net load (the forward load forecast) ----------

def test_net_load_is_signed_and_positive_means_cooling():
    """The heating-only `heat_demand_w` clamps at zero, which is right for
    sizing a boiler and useless for asking whether a day needs heating or
    cooling. This is the signed balance."""
    hot = net_load_w(PARAMS, 24.0, 37.0, 10.0, q_sol=5000.0, q_int=350.0)
    cold = net_load_w(PARAMS, 21.0, -5.0, 10.0, q_sol=0.0, q_int=350.0)
    assert hot > 0.0, "37 degC outside with sun must read as cooling demand"
    assert cold < 0.0, "-5 degC outside must read as heating demand"


def test_net_load_reproduces_the_measured_loss_coefficient():
    q = net_load_w(PARAMS, 24.0, 4.0, 24.0, q_sol=0.0, q_int=0.0)
    assert q == pytest.approx(-267.2 * 20.0, rel=0.02)


def test_solar_and_internal_gains_push_the_load_toward_cooling():
    base = net_load_w(PARAMS, 24.0, 24.0, 10.0)
    with_sun = net_load_w(PARAMS, 24.0, 24.0, 10.0, q_sol=4000.0)
    assert with_sun - base == pytest.approx(4000.0)


def test_the_full_solar_term_is_used_with_no_f_sol_split():
    """At steady state every watt through the glazing leaves through the
    envelope regardless of whether it landed on air or floor. Applying f_sol
    here would silently discard 70 % of the solar load - the split governs the
    DYNAMICS only."""
    a = net_load_w(PARAMS, 24.0, 24.0, 10.0, q_sol=1000.0)
    b = net_load_w(PARAMS, 24.0, 24.0, 10.0, q_sol=0.0)
    assert a - b == pytest.approx(1000.0)      # not 300.0


def test_net_load_and_heat_demand_agree_where_both_are_valid():
    """Where heating genuinely is needed, the signed form must be the negative
    of the heating demand - otherwise one of them has the sign or the ground
    term wrong."""
    for outdoor in (-10.0, 0.0, 8.0):
        h = heat_demand_w(PARAMS, 21.0, outdoor, 10.0)
        n = net_load_w(PARAMS, 21.0, outdoor, 10.0)
        assert h > 0.0
        assert -n == pytest.approx(h, rel=0.05)
