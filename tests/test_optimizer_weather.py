"""Forecast bias correction, and the structural ban on set commands.

The bias tests assert DIRECTION throughout. A correction with the wrong sign
would make the planner believe cold clear nights are milder than forecast -
the opposite of the truth, applied on exactly the nights with the least
margin - and it would still look like "a correction is being applied".
"""
from __future__ import annotations

import asyncio

import pytest

from optimizer.estimator import Estimator
from optimizer.weather import ForecastPoint, WeatherSource, bias_correction

A, W0, CLAMP = 5.0, 8.0, 5.0


def corr(cloud: float, wind: float, sw: float = 0.0) -> float:
    return bias_correction(cloud, wind, sw, A, W0, CLAMP)


def test_the_correction_only_ever_makes_the_forecast_COLDER():
    """The valley pools cold air; the model does not know that. A positive
    correction here would be the sign error that matters."""
    for cloud in (0, 25, 50, 90, 100):
        for wind in (0, 2, 5, 10, 30):
            assert corr(cloud, wind) <= 0.0


def test_no_correction_is_applied_in_daylight():
    """The daytime residual at this site is POSITIVE, and it is the station's
    own radiation shield heating in sun - an instrument error, not weather.
    Correcting for it would fit the sensor's fault into the building model."""
    assert corr(0, 0, sw=1.0) == 0.0
    assert corr(0, 0, sw=800.0) == 0.0


def test_the_correction_is_largest_when_clear_and_calm():
    """The cold-pooling signature: radiative cooling needs a clear sky, and
    the inversion only stands if there is no wind to mix it away."""
    clear_calm = corr(0, 0)
    assert clear_calm < corr(0, 20)       # wind destroys it
    assert clear_calm < corr(100, 0)      # cloud destroys it
    assert clear_calm < corr(100, 20)


def test_the_measured_clear_calm_magnitude_is_reproduced():
    """Winter data put the median at about -3 K for a clear, calm night.
    The fitted form must land in that neighbourhood at representative
    conditions, or the constants in params.yaml have drifted from the
    evidence in BACKLOG.md."""
    assert -4.0 < corr(cloud=10, wind=3) < -2.0


def test_overcast_and_windy_is_effectively_uncorrected():
    """The null case. Measured median there was -0.10 K, i.e. nothing."""
    assert abs(corr(cloud=95, wind=15)) < 0.15


def test_the_correction_is_clamped():
    """A refit that goes wrong must degrade to something bounded rather than
    steering the planner with an arbitrary number."""
    assert bias_correction(0, 0, 0, a=50.0, w0=8.0, clamp=5.0) == -5.0


def test_parsing_applies_the_correction_and_keeps_the_raw_value():
    src = WeatherSource(0.0, 0.0, {"bias_a_k": A, "bias_w0_kmh": W0,
                                   "bias_clamp_k": CLAMP})
    pts = src._parse({"hourly": {
        "time": ["2026-01-01T02:00", "2026-01-01T12:00"],
        "temperature_2m": [-2.0, 5.0],
        "dew_point_2m": [-3.0, 1.0],
        "cloud_cover": [0.0, 0.0],
        "wind_speed_10m": [0.0, 0.0],
        "shortwave_radiation": [0.0, 500.0]}})
    assert pts[0].temperature < pts[0].raw_temperature   # night: corrected
    assert pts[1].temperature == pts[1].raw_temperature  # day: untouched
    assert pts[0].is_night and not pts[1].is_night


def test_a_forecast_with_no_usable_hours_is_rejected_not_silently_empty():
    src = WeatherSource(0.0, 0.0, {})
    with pytest.raises(ValueError):
        src._parse({"hourly": {"time": ["2026-01-01T00:00"],
                               "temperature_2m": [None],
                               "cloud_cover": [None],
                               "wind_speed_10m": [None],
                               "shortwave_radiation": [None]}})


def test_a_failed_fetch_leaves_the_cache_and_lets_its_age_grow():
    """Layer 2 is allowed to fail, but it must fail visibly. Callers decide
    what a stale forecast is worth; an exception would take that away."""
    src = WeatherSource(0.0, 0.0, {}, min_interval_s=0.0)
    src._cache = [ForecastPoint("t", 1.0, 1.0, 0.0, 0.0, 0.0, 0.0)]
    src._get = lambda url: (_ for _ in ()).throw(OSError("no network"))
    assert asyncio.run(src.refresh()) is False
    assert len(src._cache) == 1


# ---------- the structural ban ----------

def _estimator(cfg_extra: dict | None = None) -> Estimator:
    cfg = {"mqtt": {"host": "127.0.0.1", "base_topic": "heatctl"},
           "rooms": [], "safety": {"stale_data_timeout_s": 300}}
    cfg.update(cfg_extra or {})
    params = {
        "building": {"ua_ao": 267.2, "ua_sa": 1000.0, "ua_sg": 29.0,
                     "c_air_wh": 6600.0, "c_slab_wh": 8691.0, "f_sol": 0.3,
                     "t_ground": 10.0, "solar_aperture_m2": 8.0,
                     "q_internal_w": 350.0},
        "filter": {"q_air_k_per_h": 0.15, "q_slab_k_per_h": 0.4,
                   "r_air_k": 0.5, "p0_air_k": 1.0, "p0_slab_k": 5.0},
        "heat_input": {"assumed_cop": 3.35, "standby_w": 250.0},
        "weather": {"latitude": None, "longitude": None}}
    return Estimator(cfg, params)


def test_layer_two_cannot_publish_a_set_command():
    """WP-F is status-only, and not merely as staging discipline: DESIGN.md
    2.2 records that ControlPlane applies commands immediately with no TTL
    and no expiry sweep. A layer 2 that hung after sending a setpoint would
    leave the house steered by its last thought indefinitely. The guard is
    structural so that the property survives someone adding a publish call
    without reading this."""
    est = _estimator()
    captured: list[str] = []

    class FakeClient:
        async def publish(self, topic, payload):
            captured.append(topic)

    est._client = FakeClient()
    asyncio.run(est._publish("state", "{}"))
    assert captured == ["heatctl/opt/state"]
    assert not any("/set/" in t for t in captured)

    for escape in ("/heatctl/set/mode", "../set/mode", "../../set/setpoint/x"):
        with pytest.raises(ValueError):
            asyncio.run(est._publish(escape, "cooling"))


def test_process_noise_scales_with_the_step_length():
    """Variance grows linearly in time, so using the per-hour figure directly
    at a 60 s step would make the filter trust the model ~60x less than
    intended - which looks like a well-behaved but sluggish estimator."""
    est = _estimator()
    q60 = est._process_noise(60.0)
    q3600 = est._process_noise(3600.0)
    assert q3600[0][0] == pytest.approx(q60[0][0] * 60.0, rel=1e-9)
    assert q3600[1][1] == pytest.approx(0.4 ** 2, rel=1e-9)


def test_standby_power_is_not_integrated_into_the_slab_as_heat():
    """A pump idling at 200 W is not delivering 670 W of heat to the floor.
    Without this the slab estimate climbs whenever the plant is doing
    nothing, which is the direction that hides a real heating shortfall."""
    from optimizer.estimator import Reading
    est = _estimator()
    est.readings["heatctl/hp/power_estimate"] = Reading(200.0)
    assert est.heat_input_w() == 0.0
    est.readings["heatctl/hp/power_estimate"] = Reading(1000.0)
    assert est.heat_input_w() == pytest.approx(3350.0)


def test_stale_readings_are_not_used():
    """Same principle as layer 1's stale-data failsafe: a value that stopped
    arriving is not a value."""
    from optimizer.estimator import Reading
    est = _estimator({"rooms": [{"name": "a", "room_temp_topic": "r/a"}]})
    est.readings["r/a"] = Reading(21.0, ts=-10_000.0)
    assert est.house_air() is None


def test_the_estimator_waits_rather_than_guessing_with_no_inputs():
    est = _estimator()
    assert est.step(60.0) is None


def test_the_optimizer_honours_the_same_mqtt_env_overrides_as_layer_1(tmp_path):
    """Regression: the optimizer read mqtt.host straight from config.yaml, which
    ships a PLACEHOLDER address, so it sat in a reconnect loop while layer 1
    talked to the Supervisor's broker two processes away. Both layers must
    resolve the broker the same way."""
    import os
    from optimizer.main import load
    cfg = tmp_path / "c.yaml"
    cfg.write_text("mqtt:\n  host: 192.0.2.1\n  port: 1883\n  base_topic: heatctl\n"
                   "rooms: []\n")
    params = tmp_path / "p.yaml"
    params.write_text("weather: {}\n")
    old = dict(os.environ)
    os.environ.update({"HEATCTL_MQTT_HOST": "core-mosquitto",
                       "HEATCTL_MQTT_PORT": "1884"})
    try:
        c, _ = load(str(cfg), str(params))
    finally:
        os.environ.clear(); os.environ.update(old)
    assert c["mqtt"]["host"] == "core-mosquitto"
    assert c["mqtt"]["port"] == 1884        # and coerced to int, not "1884"


# ---------- the pre-conditioning delta layer 1 consumes ----------

import datetime as _dt

from optimizer.weather import ForecastPoint as _FP


def _est_with_forecast(loads_ahead):
    """An estimator whose forecast is `loads_ahead` hours of given outdoor temps,
    starting at the current hour. Solar is zero so the load is fabric-only and
    the arithmetic stays checkable by hand."""
    est = _estimator()
    est.params["solar"] = {"albedo": 0.2, "facades": []}
    from optimizer.solar import SolarModel
    est.solar = SolarModel([], 52.0, 13.0)
    now = _dt.datetime.now(_dt.timezone.utc).replace(
        minute=0, second=0, microsecond=0)

    class _W:
        points = [_FP(time=(now + _dt.timedelta(hours=i)).isoformat()[:19],
                      temperature=t, raw_temperature=t, dew_point=10.0,
                      cloud_cover=100.0, wind_speed=5.0, shortwave=0.0)
                  for i, t in enumerate(loads_ahead)]
    est.weather = _W()
    return est


def test_a_hot_window_ahead_gives_a_NEGATIVE_delta():
    """`active = dial + delta`, so pre-cooling is negative. A sign error here
    would pre-HEAT the house before a hot afternoon, the most expensive mistake
    available."""
    # Ceiling deliberately low so the fabric-only load exceeds it: at 45 degC
    # with no solar the load is 5.55 kW, just UNDER the real 5.7 kW ceiling, so
    # using the real one would test nothing. Real days exceed it mainly via
    # solar, which this synthetic forecast has none of.
    est = _est_with_forecast([45.0] * 12)
    assert est.setpoint_delta(24.0, 2000.0) < 0


def test_a_cold_window_ahead_gives_a_POSITIVE_delta():
    """The winter case: pre-charge before a storm drops the outdoor temperature,
    which means aiming WARMER than the dial."""
    est = _est_with_forecast([-25.0] * 12)
    assert est.setpoint_delta(21.0, 2000.0) > 0


def test_a_benign_window_asks_for_nothing():
    """Zero is the common case and must stay cheap - it means the plant does
    exactly what the occupant's dial says."""
    est = _est_with_forecast([22.0] * 12)
    assert est.setpoint_delta(22.0, 2000.0) == 0.0


def test_only_hours_AHEAD_are_counted():
    """REGRESSION. The forecast window begins at MIDNIGHT, so the earlier
    calendar-day version kept seeing "today has 9 hours over the ceiling" at
    23:00 and would have pre-cooled overnight for a day already finished -
    measured 2026-07-30 as asking 1.44 K when the next day needed 0.28.
    """
    est = _est_with_forecast([22.0] * 12)      # nothing ahead needs storing
    CEIL = 2000.0
    now = _dt.datetime.now(_dt.timezone.utc).replace(
        minute=0, second=0, microsecond=0)
    # prepend twelve brutally hot hours that are already PAST
    past = [_FP(time=(now - _dt.timedelta(hours=i + 1)).isoformat()[:19],
                temperature=45.0, raw_temperature=45.0, dew_point=10.0,
                cloud_cover=100.0, wind_speed=5.0, shortwave=0.0)
            for i in range(12)]
    est.weather.points = past[::-1] + list(est.weather.points)
    assert est.setpoint_delta(22.0, CEIL) == 0.0, \
        "past excess must not drive a pre-charge"


def test_no_forecast_asks_for_nothing():
    est = _estimator()
    assert est.setpoint_delta(24.0, 5700.0) == 0.0
