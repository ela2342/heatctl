"""Forecast source with the local cold-pooling correction applied.

Open-Meteo wrapping DWD ICON. Uses `urllib` from the standard library on a
worker thread rather than adding an HTTP client to the dependency set - one
request an hour does not justify a new pin (see CLAUDE.md on the 30-year
promise).

**The correction is the point of this module.** Raw ICON is systematically
warm at this site on clear calm nights - by about 3 K, because the model at
~2 km cannot resolve a river valley that fills with cold air once radiative
cooling gets going and there is no wind to mix it out. That is exactly the
night before a cold morning, so an uncorrected forecast under-predicts
overnight loss precisely when the margin is thinnest. Derivation, sample
sizes and out-of-sample validation are in BACKLOG.md.

Everything here is failure-tolerant by contract: layer 2 is allowed to fail
(CLAUDE.md), and a forecast that cannot be fetched must leave the plant
running on layer 1's own defaults rather than propagating an exception.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("optimizer.weather")

_ENDPOINT = "https://api.open-meteo.com/v1/forecast"


def _at(hourly: dict, field: str, i: int) -> float:
    """Optional irradiance field, defaulting to zero.

    Beam and diffuse are separated because projecting global horizontal
    irradiance onto a vertical window with a cosine is meaningless: on an
    overcast day the beam is near zero and the gain is essentially all
    diffuse, which has no incidence angle. Missing fields degrade to zero
    rather than raising - a forecast without irradiance is still worth
    having for its temperature.
    """
    v = hourly.get(field)
    if not v or i >= len(v) or v[i] is None:
        return 0.0
    return float(v[i])


_FIELDS = ("temperature_2m,dew_point_2m,cloud_cover,wind_speed_10m,"
           "shortwave_radiation,direct_normal_irradiance,"
           "diffuse_radiation")


@dataclass(frozen=True)
class ForecastPoint:
    time: str            # ISO 8601, UTC
    temperature: float   # degC, CORRECTED
    raw_temperature: float
    dew_point: float     # degC, uncorrected - see note in fetch()
    cloud_cover: float   # %
    wind_speed: float    # km/h at 10 m
    shortwave: float     # W/m2, global horizontal (GHI)
    dni: float = 0.0     # W/m2, direct normal
    dhi: float = 0.0     # W/m2, diffuse horizontal

    @property
    def is_night(self) -> bool:
        return self.shortwave <= 0.0


def bias_correction(cloud_cover: float, wind_speed: float, shortwave: float,
                    a: float, w0: float, clamp: float) -> float:
    """Temperature the model over-predicts, in K (returns <= 0).

    Night only, and deliberately so. The daytime residual at this site is
    POSITIVE, which is the signature of the weather station's own radiation
    shield heating in sunlight rather than anything the atmosphere is doing -
    correcting for it would be fitting the instrument's error into the model
    of the building. See BACKLOG.md.
    """
    if shortwave > 0.0:
        return 0.0
    clear = max(0.0, 1.0 - cloud_cover / 100.0)
    calm = math.exp(-max(0.0, wind_speed) / w0)
    return -min(clamp, a * clear * calm)


class WeatherSource:
    """Hourly forecast with caching and a hard failure floor."""

    def __init__(self, latitude: float, longitude: float, cfg: dict,
                 min_interval_s: float = 1800.0) -> None:
        self.lat = latitude
        self.lon = longitude
        self.a = cfg.get("bias_a_k", 5.0)
        self.w0 = cfg.get("bias_w0_kmh", 8.0)
        self.clamp = cfg.get("bias_clamp_k", 5.0)
        self.min_interval = min_interval_s
        self._cache: list[ForecastPoint] = []
        self._fetched = 0.0

    @property
    def points(self) -> list[ForecastPoint]:
        return self._cache

    @property
    def age_s(self) -> float:
        return time.monotonic() - self._fetched if self._fetched else float("inf")

    def ahead(self, hours: int | None = None) -> list["ForecastPoint"]:
        """Forecast points from the CURRENT hour forward.

        `points` deliberately keeps every hour Open-Meteo returned, and the
        request starts at 00:00 UTC today - so `points[0]` is MIDNIGHT, not
        now, and it becomes staler as the day goes on.

        That caught us on 2026-08-09: `solar_w` read `points[0]` and therefore
        fed the Kalman filter 0 W of solar permanently, on the one disturbance
        this building is dominated by. The failure was invisible because 0 W is
        a perfectly plausible number at any hour and genuinely correct at
        night. Two callers had already grown their own inline "only future
        hours" comprehension; this is that filter, in one place, so the next
        caller inherits it instead of re-deriving it or forgetting to.
        """
        now = dt.datetime.now(dt.timezone.utc).replace(
            minute=0, second=0, microsecond=0)
        out = [p for p in self._cache
               if dt.datetime.fromisoformat(p.time).replace(
                   tzinfo=dt.timezone.utc) >= now]
        return out[:hours] if hours is not None else out

    def current(self) -> "ForecastPoint | None":
        """The forecast hour covering right now, or None if none is left."""
        nxt = self.ahead(1)
        return nxt[0] if nxt else None

    async def refresh(self, force: bool = False) -> bool:
        """Fetch if the cache is stale. True if fresh data arrived.

        Never raises. A failed fetch leaves the previous cache in place and
        lets `age_s` grow, so callers decide what a stale forecast is worth
        rather than having the decision made for them by an exception.
        """
        if not force and self.age_s < self.min_interval:
            return False
        url = (f"{_ENDPOINT}?latitude={self.lat}&longitude={self.lon}"
               f"&hourly={_FIELDS}&models=icon_seamless&forecast_days=3"
               f"&timezone=UTC")
        try:
            raw = await asyncio.to_thread(self._get, url)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            log.warning("forecast fetch failed (%s); cache is %.0f s old",
                        e, self.age_s)
            return False
        try:
            self._cache = self._parse(raw)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("forecast parse failed: %s", e)
            return False
        self._fetched = time.monotonic()
        log.info("forecast refreshed: %d hours, next-night correction %.2f K",
                 len(self._cache), self.next_night_correction())
        return True

    @staticmethod
    def _get(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)

    def _parse(self, raw: dict) -> list[ForecastPoint]:
        h = raw["hourly"]
        out: list[ForecastPoint] = []
        for i, t in enumerate(h["time"]):
            temp = h["temperature_2m"][i]
            cc = h["cloud_cover"][i]
            ws = h["wind_speed_10m"][i]
            sw = h["shortwave_radiation"][i]
            if temp is None or cc is None or ws is None:
                continue
            sw = 0.0 if sw is None else sw
            d = bias_correction(cc, ws, sw, self.a, self.w0, self.clamp)
            # Dew point is passed through UNCORRECTED and must stay that way.
            # At this site it runs ~1.3 K moister than the model in daytime -
            # the unsafe direction for cooling - but the condensation guard in
            # layer 1 uses the measured INDOOR maximum, which is both the
            # right quantity and the safe one. Nothing here may ever become an
            # input to that guard; this value is for planning only.
            out.append(ForecastPoint(
                time=t, temperature=temp + d, raw_temperature=temp,
                dew_point=h["dew_point_2m"][i] if h.get("dew_point_2m")
                else float("nan"),
                cloud_cover=cc, wind_speed=ws, shortwave=sw,
                dni=_at(h, 'direct_normal_irradiance', i),
                dhi=_at(h, 'diffuse_radiation', i)))
        if not out:
            raise ValueError("forecast contained no usable hours")
        return out

    def next_night_correction(self) -> float:
        """Largest correction over the coming night, for telemetry."""
        nights = [p for p in self._cache[:36] if p.is_night]
        return min((p.temperature - p.raw_temperature for p in nights),
                   default=0.0)

    def coldest_ahead(self, hours: int = 24) -> float | None:
        window = self._cache[:hours]
        return min((p.temperature for p in window), default=None)
