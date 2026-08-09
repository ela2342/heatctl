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


# ---------- per-room split ----------

ROOMS = {"wohnzimmer": {"E": 4.470, "S": 3.314},
         "schlafzimmer": {"E": 1.559},
         "kind_naomi": {"S": 0.794},
         "kind_natalie": {"S": 0.794},
         "arbeitszimmer": {"N": 0.756, "E": 0.756, "S": 1.280, "W": 0.605}}


def test_room_apertures_do_not_exceed_the_facades_they_come_from():
    """The per-room table is a SPLIT of the facade table, not a second opinion.

    A room's windows are windows the facade total already counted, so the
    assigned apertures can only sum to less than or equal to it. Exceeding it
    means a window was double-assigned or a decimal slipped, and the symptom
    would be a house that predicts more solar per room than it admits in
    total - invisible in any single-room check.
    """
    per_facade = {f.name: f.aperture_m2 for f in FACADES}
    assigned: dict[str, float] = {}
    for split in ROOMS.values():
        for facade, area in split.items():
            assigned[facade] = assigned.get(facade, 0.0) + area
    for facade, total in assigned.items():
        assert total <= per_facade[facade] + 0.005, (
            f"{facade}: rooms claim {total} of {per_facade[facade]}")


def test_east_and_south_are_fully_assigned():
    """Closure, and it is EVIDENCE rather than bookkeeping.

    The window-to-room assignment was read off a floor plan, and the check that
    it is right is that the ground-floor windows sum exactly to the certificate
    per-facade totals minus the upper floor. East and south are the facades
    that carry the gain and both close to within rounding; north and west are
    knowingly incomplete. If a future edit breaks this, the assignment stopped
    matching the survey and the numbers are no longer the audited ones.
    """
    assigned: dict[str, float] = {}
    for split in ROOMS.values():
        for facade, area in split.items():
            assigned[facade] = assigned.get(facade, 0.0) + area
    per_facade = {f.name: f.aperture_m2 for f in FACADES}
    assert assigned["E"] == pytest.approx(per_facade["E"], abs=0.005)
    assert assigned["S"] == pytest.approx(per_facade["S"], abs=0.005)


def test_rooms_that_exactly_split_a_facade_recover_its_whole_gain():
    """Conservation: the split moves gain between rooms, it does not create or
    destroy it. Stated on a facade partitioned exactly, so the assertion is
    about the arithmetic rather than about the real table's rounding."""
    facades = [Facade("E", 106.3, 6.0)]
    model = SolarModel(facades, LAT, LON,
                       rooms={"a": {"E": 4.0}, "b": {"E": 2.0}})
    when = utc(2026, 8, 9, 8)
    rooms = model.per_room_w(when, 700.0, 120.0, 550.0)
    assert sum(rooms.values()) == pytest.approx(
        model.gain_w(when, 700.0, 120.0, 550.0), rel=1e-12)
    assert rooms["a"] == pytest.approx(2.0 * rooms["b"], rel=1e-12)


def test_real_room_table_accounts_for_east_and_south_within_rounding():
    """The two facades that carry the gain are fully assigned, so the rooms
    must reproduce their combined gain. Tolerance is the 0.002 m2 of decimal
    rounding in the config, not slack for a missing window."""
    east_south = [f for f in FACADES if f.name in ("E", "S")]
    whole = SolarModel(east_south, LAT, LON)
    split = SolarModel(east_south, LAT, LON,
                       rooms={r: {f: a for f, a in s.items() if f in ("E", "S")}
                              for r, s in ROOMS.items()})
    when = utc(2026, 8, 9, 8)
    assert sum(split.per_room_w(when, 700.0, 120.0, 550.0).values()) == (
        pytest.approx(whole.gain_w(when, 700.0, 120.0, 550.0), rel=2e-4))


def test_east_room_peaks_in_the_morning_and_south_room_after_noon():
    """THE WHOLE POINT OF DOING THIS PER ROOM.

    A house-average solar term cannot express that Schlafzimmer takes its day
    between 07:00 and 11:00 while Kind Naomi takes it after noon; it hands both
    the same shape. Getting the ORDER wrong would pre-cool the wrong room at
    the wrong hour while the daily energy still looked right.
    """
    model = SolarModel(FACADES, LAT, LON, rooms=ROOMS)

    def peak_hour(room: str) -> int:
        best, best_h = -1.0, -1
        for h in range(3, 21):
            w = model.per_room_w(utc(2026, 8, 9, h), 700.0, 120.0, 550.0)[room]
            if w > best:
                best, best_h = w, h
        return best_h

    east, south = peak_hour("schlafzimmer"), peak_hour("kind_naomi")
    assert east < south, f"east peaked at {east}h, south at {south}h"
    assert south - east >= 3


def test_room_with_no_glazing_is_absent_not_zero():
    """Absent and zero are different claims and must not be conflated.

    gaestebad has no assigned windows because nobody has read them off the
    plan yet, not because it is windowless. Reporting 0.0 W would let layer 1
    treat an unassigned room as confidently sunless - and after sunset that
    would even look correct.
    """
    model = SolarModel(FACADES, LAT, LON, rooms=ROOMS)
    out = model.per_room_w(utc(2026, 8, 9, 9), 700.0, 120.0, 550.0)
    assert "gaestebad" not in out
    assert "schlafzimmer" in out


def test_unknown_facade_in_a_room_is_rejected_at_construction():
    """Fail at startup, not silently at runtime. A typo'd facade key would
    otherwise drop that window's gain and understate the room forever."""
    with pytest.raises(ValueError, match="unknown facade"):
        SolarModel(FACADES, LAT, LON, rooms={"schlafzimmer": {"East": 1.559}})


def test_no_rooms_configured_yields_no_room_gains():
    model = SolarModel(FACADES, LAT, LON)
    assert model.per_room_w(utc(2026, 8, 9, 9), 700.0, 120.0, 550.0) == {}


def test_from_config_reads_the_room_table():
    model = SolarModel.from_config(
        {"facades": [{"name": "E", "azimuth_deg": 106.3, "aperture_m2": 6.785}],
         "rooms": {"schlafzimmer": {"E": 1.559}}}, LAT, LON)
    assert model.rooms == {"schlafzimmer": {"E": 1.559}}
