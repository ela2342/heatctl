"""Per-facade solar gain from forecast irradiance.

Replaces a single lumped "effective aperture" figure. The lump was wrong for
this building in a way no amount of tuning fixes: the glazing is very
unevenly distributed - one room carries over half of it, on the two facades
that see sun from dawn to mid-afternoon - so the gain has a strong diurnal
SHAPE, not just a magnitude. A single number can be fitted to the daily total
and still be badly wrong at every hour of the day, which is precisely the
error a slab-charging planner cannot absorb.

Three things have to be right, and each has bitten this project already:

* **True azimuth, not the drawing labels.** The building is not square to
  north; the elevations named "Nord/Ost/Sued/West" actually face 16.3 deg,
  106.3 deg, 196.3 deg and 286.3 deg. The east glazing therefore peaks well
  before solar noon minus six hours would suggest.
* **Beam and diffuse must be separated.** Projecting global horizontal
  irradiance onto a vertical plane with a cosine is meaningless - on an
  overcast day the beam component is near zero and essentially all the gain
  is diffuse, which has no incidence angle at all.
* **The incidence factor is computed, not assumed.** The building survey's
  "effective collector area" folds in a flat 0.9 for non-perpendicular
  incidence. That constant is superseded here by the real geometry, so it
  must NOT be applied on top - doing so would double-count and quietly
  under-predict gain by ~10 %.

Astronomy is the standard NOAA low-precision algorithm, good to about 0.01
deg, which is far below the uncertainty in the shading and frame factors.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

# Ground reflectance. Grass and gravel sit near here; fresh snow reaches 0.8
# and would matter for the winter case this model is mostly for, so it is a
# parameter rather than a literal.
DEFAULT_ALBEDO = 0.20


@dataclass(frozen=True)
class Facade:
    """One glazed plane.

    `aperture_m2` is brutto glazing times frame, shading and g-value - but
    NOT any incidence-angle allowance, which this module computes hourly.
    """
    name: str
    azimuth_deg: float      # true bearing the glazing faces, 0 = N, 90 = E
    aperture_m2: float
    tilt_deg: float = 90.0  # vertical glazing


def solar_position(when: dt.datetime, lat: float,
                   lon: float) -> tuple[float, float]:
    """Sun elevation and azimuth in degrees (azimuth 0 = N, 90 = E).

    `when` must be timezone-aware UTC. A naive datetime is rejected rather
    than assumed to be UTC: the forecast arrives in UTC but local timestamps
    are everywhere in this project, and a silent four-hour azimuth error
    would look like a plausible shading effect.
    """
    if when.tzinfo is None:
        raise ValueError("solar_position requires a timezone-aware datetime")
    when = when.astimezone(dt.timezone.utc)

    # Fractional Julian day and century.
    a = (14 - when.month) // 12
    y = when.year + 4800 - a
    m = when.month + 12 * a - 3
    jdn = (when.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100
           + y // 400 - 32045)
    frac = (when.hour - 12) / 24.0 + when.minute / 1440.0 + when.second / 86400.0
    jd = jdn + frac
    t = (jd - 2451545.0) / 36525.0

    mean_long = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    ma = math.radians(mean_anom)
    centre = (math.sin(ma) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * ma) * (0.019993 - 0.000101 * t)
              + math.sin(3 * ma) * 0.000289)
    true_long = mean_long + centre
    omega = math.radians(125.04 - 1934.136 * t)
    app_long = math.radians(true_long - 0.00569 - 0.00478 * math.sin(omega))

    obliq = (23.0 + (26.0 + ((21.448 - t * (46.815 + t * (0.00059
             - t * 0.001813)))) / 60.0) / 60.0)
    obliq_corr = math.radians(obliq + 0.00256 * math.cos(omega))

    decl = math.asin(math.sin(obliq_corr) * math.sin(app_long))

    vary = math.tan(obliq_corr / 2.0) ** 2
    ml = math.radians(mean_long)
    eot = 4.0 * math.degrees(
        vary * math.sin(2 * ml) - 2 * ecc * math.sin(ma)
        + 4 * ecc * vary * math.sin(ma) * math.cos(2 * ml)
        - 0.5 * vary * vary * math.sin(4 * ml)
        - 1.25 * ecc * ecc * math.sin(2 * ma))

    minutes = when.hour * 60.0 + when.minute + when.second / 60.0
    true_solar = (minutes + eot + 4.0 * lon) % 1440.0
    hour_angle = math.radians(true_solar / 4.0 - 180.0
                              if true_solar / 4.0 >= 0 else
                              true_solar / 4.0 + 180.0)

    latr = math.radians(lat)
    zenith = math.acos(max(-1.0, min(1.0,
        math.sin(latr) * math.sin(decl)
        + math.cos(latr) * math.cos(decl) * math.cos(hour_angle))))
    elevation = 90.0 - math.degrees(zenith)

    if abs(math.sin(zenith)) < 1e-9:
        azimuth = 180.0
    else:
        c = ((math.sin(latr) * math.cos(zenith) - math.sin(decl))
             / (math.cos(latr) * math.sin(zenith)))
        azimuth = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        azimuth = (azimuth + 180.0) % 360.0 if hour_angle > 0 else \
            (540.0 - azimuth) % 360.0
    return elevation, azimuth


def incidence_cos(facade: Facade, sun_elev: float, sun_azim: float) -> float:
    """cos of the angle between the sun and the facade normal, clipped at 0.

    Clipped because a negative cosine means the sun is behind the wall. Left
    unclipped it would SUBTRACT gain, which is the sign error that makes a
    north facade appear to cool the house on a sunny afternoon.
    """
    if sun_elev <= 0.0:
        return 0.0
    e, tilt = math.radians(sun_elev), math.radians(facade.tilt_deg)
    da = math.radians(sun_azim - facade.azimuth_deg)
    return max(0.0, math.sin(e) * math.cos(tilt)
               + math.cos(e) * math.sin(tilt) * math.cos(da))


def plane_of_array(facade: Facade, dni: float, dhi: float, ghi: float,
                   sun_elev: float, sun_azim: float,
                   albedo: float = DEFAULT_ALBEDO) -> float:
    """Irradiance on the facade, W/m2: beam + isotropic sky + ground reflected.

    Isotropic sky diffuse rather than an anisotropic model (Perez, Hay-Davies)
    on purpose. The anisotropic models mainly improve circumsolar and horizon
    brightening, which matter for tilted PV; against the frame, shading and
    dirt factors already carrying tens of percent of uncertainty here, the
    extra fidelity would be invisible.
    """
    tilt = math.radians(facade.tilt_deg)
    beam = dni * incidence_cos(facade, sun_elev, sun_azim)
    sky = dhi * (1.0 + math.cos(tilt)) / 2.0
    ground = ghi * albedo * (1.0 - math.cos(tilt)) / 2.0
    return beam + sky + ground


class SolarModel:
    def __init__(self, facades: list[Facade], latitude: float,
                 longitude: float, albedo: float = DEFAULT_ALBEDO) -> None:
        self.facades = facades
        self.lat = latitude
        self.lon = longitude
        self.albedo = albedo

    @classmethod
    def from_config(cls, cfg: dict, latitude: float,
                    longitude: float) -> "SolarModel":
        return cls([Facade(name=f["name"], azimuth_deg=f["azimuth_deg"],
                           aperture_m2=f["aperture_m2"],
                           tilt_deg=f.get("tilt_deg", 90.0))
                    for f in cfg["facades"]],
                   latitude, longitude, cfg.get("albedo", DEFAULT_ALBEDO))

    def gain_w(self, when: dt.datetime, dni: float, dhi: float,
               ghi: float) -> float:
        """Total solar power entering through all glazing, W."""
        elev, azim = solar_position(when, self.lat, self.lon)
        return sum(plane_of_array(f, dni, dhi, ghi, elev, azim, self.albedo)
                   * f.aperture_m2 for f in self.facades)

    def per_facade_w(self, when: dt.datetime, dni: float, dhi: float,
                     ghi: float) -> dict[str, float]:
        """Same, broken out - this is what makes the model checkable.

        The east facade peaking mid-morning and the south around solar noon
        is a prediction that can be falsified against room temperatures on a
        clear day, which a single total cannot be.
        """
        elev, azim = solar_position(when, self.lat, self.lon)
        return {f.name: plane_of_array(f, dni, dhi, ghi, elev, azim,
                                       self.albedo) * f.aperture_m2
                for f in self.facades}
