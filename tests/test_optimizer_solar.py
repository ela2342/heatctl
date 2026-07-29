"""Per-facade solar gain.

These tests are mostly about GEOMETRY BEING RIGHT rather than about magnitude,
because the magnitude carries large honest uncertainty (frame, shading, dirt)
while the shape does not. A solar model with the right total and the wrong
diurnal shape is the failure that matters here: it charges the slab at the
wrong time of day, and the daily energy still looks correct.
"""
from __future__ import annotations

import datetime as dt
import math

import pytest

from optimizer.solar import (DEFAULT_ALBEDO, Facade, SolarModel,
                             incidence_cos, plane_of_array, solar_position)

# Berlin-ish, deliberately not the real site.
LAT, LON = 52.5, 13.4
FACADES = [Facade("N", 16.3, 1.550), Facade("E", 106.3, 6.785),
           Facade("S", 196.3, 6.180), Facade("W", 286.3, 1.588)]


def utc(y, m, d, h, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=dt.timezone.utc)


# ---------- astronomy ----------

def test_a_naive_datetime_is_rejected_rather_than_assumed_to_be_utc():
    """Local timestamps are everywhere in this project. Assuming UTC would
    shift the sun by up to two hours in summer, which looks exactly like a
    plausible shading effect rather than like a bug."""
    with pytest.raises(ValueError):
        solar_position(dt.datetime(2026, 6, 21, 12), LAT, LON)


def test_the_sun_is_highest_near_local_solar_noon_in_summer():
    elevs = {h: solar_position(utc(2026, 6, 21, h), LAT, LON)[0]
             for h in range(24)}
    peak = max(elevs, key=lambda h: elevs[h])
    assert peak in (10, 11)                    # ~12:12 local solar time
    assert 58.0 < elevs[peak] < 63.0           # 90 - 52.5 + 23.44 = 60.9


def test_midwinter_noon_elevation_matches_the_closed_form():
    elev, _ = solar_position(utc(2026, 12, 21, 11), LAT, LON)
    assert elev == pytest.approx(90.0 - LAT - 23.44, abs=1.5)


def test_the_sun_is_below_the_horizon_at_local_midnight():
    assert solar_position(utc(2026, 6, 21, 23), LAT, LON)[0] < 0.0


def test_the_sun_rises_in_the_east_and_sets_in_the_west():
    """Azimuth convention check: 0 = north, 90 = east. Getting this backwards
    swaps the morning and afternoon facades, which for this building means
    swapping its largest glazing with its smallest."""
    _, morning = solar_position(utc(2026, 6, 21, 4), LAT, LON)
    _, evening = solar_position(utc(2026, 6, 21, 18), LAT, LON)
    assert 30.0 < morning < 110.0
    assert 250.0 < evening < 330.0


def test_azimuth_is_due_south_at_solar_noon():
    _, az = solar_position(utc(2026, 3, 20, 11, 12), LAT, LON)
    assert az == pytest.approx(180.0, abs=6.0)


# ---------- projection ----------

def test_the_incidence_factor_is_never_negative():
    """A negative cosine means the sun is behind the wall. Left unclipped it
    would SUBTRACT gain, making a north facade appear to cool the house on a
    sunny afternoon."""
    north = Facade("N", 16.3, 1.0)
    for hour in range(24):
        elev, az = solar_position(utc(2026, 6, 21, hour), LAT, LON)
        assert incidence_cos(north, elev, az) >= 0.0


def test_a_facade_is_fully_lit_when_the_sun_is_on_its_normal():
    """Sun at the horizon, dead ahead of a vertical wall: cos = 1."""
    f = Facade("test", 180.0, 1.0)
    assert incidence_cos(f, 0.001, 180.0) == pytest.approx(1.0, abs=1e-3)


def test_no_beam_gain_when_the_sun_is_down_but_diffuse_still_arrives():
    """On an overcast day the beam is near zero and essentially all gain is
    diffuse - which is why GHI must not simply be projected with a cosine."""
    f = Facade("S", 196.3, 1.0)
    poa = plane_of_array(f, dni=0.0, dhi=120.0, ghi=120.0,
                         sun_elev=-5.0, sun_azim=200.0)
    assert poa > 0.0
    assert poa == pytest.approx(120.0 * 0.5 + 120.0 * DEFAULT_ALBEDO * 0.5,
                                rel=1e-9)


def test_the_east_facade_peaks_before_the_south_one():
    """The building's defining solar feature, and the thing a lumped aperture
    cannot represent: 21.5 m2 of ESE glazing that is lit from dawn while the
    SSW glazing is still in shade."""
    model = SolarModel(FACADES, LAT, LON)
    hours = range(2, 20)
    east, south = {}, {}
    for h in hours:
        when = utc(2026, 6, 21, h)
        elev, az = solar_position(when, LAT, LON)
        per = model.per_facade_w(when, dni=800.0, dhi=100.0, ghi=600.0)
        east[h], south[h] = per["E"], per["S"]
    assert max(east, key=lambda h: east[h]) < max(south, key=lambda h: south[h])


def test_the_true_azimuth_keeps_the_east_facade_lit_longer_than_due_east():
    """The building is rotated 16.3 deg off north, so its 'Ost' wall really
    faces ESE - 16 deg towards the south. Taking the drawing label literally
    does NOT shift the morning peak earlier (both peak at sunrise, where the
    low sun makes the elevation term dominate); what it does is under-collect
    through the entire rest of the morning and cut the facade off an hour
    early, because the sun tracks away from a due-east normal much sooner.

    At the equinox the gap reaches ~50 % by mid-morning on 21.5 m2 of
    glazing, which is kilowatts - and it lands on the room that holds over
    half the house's windows."""
    true_e = SolarModel([Facade("E", 106.3, 6.785)], LAT, LON)
    nominal_e = SolarModel([Facade("E", 90.0, 6.785)], LAT, LON)
    lit_true = lit_nominal = 0
    for h in range(4, 14):
        when = utc(2026, 3, 20, h)
        t = true_e.gain_w(when, 800.0, 80.0, 300.0)
        n = nominal_e.gain_w(when, 800.0, 80.0, 300.0)
        assert t >= n                       # never worse, at any hour
        lit_true += t > 500.0
        lit_nominal += n > 500.0
    assert lit_true > lit_nominal           # and lit for longer
    mid = utc(2026, 3, 20, 10)
    assert true_e.gain_w(mid, 800.0, 80.0, 300.0) > \
        1.4 * nominal_e.gain_w(mid, 800.0, 80.0, 300.0)


def test_total_gain_is_the_sum_of_the_facades():
    model = SolarModel(FACADES, LAT, LON)
    when = utc(2026, 6, 21, 9)
    per = model.per_facade_w(when, 700.0, 120.0, 550.0)
    assert model.gain_w(when, 700.0, 120.0, 550.0) == pytest.approx(sum(
        per.values()), rel=1e-12)


def test_summer_midday_gain_is_kilowatts_not_watts_or_megawatts():
    """A blunt magnitude sanity check. Catches an aperture entered in cm2, or
    a percentage mistaken for a fraction - the unit slips that a shape test
    would happily pass."""
    model = SolarModel(FACADES, LAT, LON)
    g = model.gain_w(utc(2026, 6, 21, 10), dni=850.0, dhi=110.0, ghi=780.0)
    assert 1_000.0 < g < 12_000.0


def test_night_gain_is_zero_with_no_irradiance():
    model = SolarModel(FACADES, LAT, LON)
    assert model.gain_w(utc(2026, 1, 15, 2), 0.0, 0.0, 0.0) == 0.0


def test_from_config_reads_the_facade_table():
    model = SolarModel.from_config(
        {"albedo": 0.25,
         "facades": [{"name": "E", "azimuth_deg": 106.3, "aperture_m2": 6.785}]},
        LAT, LON)
    assert model.albedo == 0.25
    assert model.facades[0].name == "E"
    assert model.facades[0].tilt_deg == 90.0
