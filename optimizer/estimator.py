"""Layer 2 state estimator: runs the model, publishes what it believes.

**This module deliberately cannot steer the plant.** WP-F in docs/DESIGN.md
is scoped "status only, no set commands yet", and there is a concrete reason
beyond staging discipline: DESIGN.md 2.2 records that `ControlPlane` applies
commands immediately with no receive timestamp and no expiry sweep, so the
TTL that every layer 2 -> layer 1 command is supposed to carry does not exist
yet. Until it does, a layer 2 that sent setpoints would be a process which,
if it hung, left the house steered by its last thought forever.

The restriction is structural rather than a matter of care: every publish
goes through `_publish()`, which prefixes `<base>/opt/` and rejects any
attempt to escape that namespace. `heatctl/set/...` is unreachable from here.
There is a test that holds this.

What it does instead is accumulate the evidence that WP-F's gate asks for -
two weeks of innovation whiteness on the model - so that when this layer is
eventually allowed to act, the decision rests on measurements rather than on
the model having looked reasonable.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import math
import logging
import time
from dataclasses import dataclass, field

import aiomqtt

from . import derived
from .kalman import KalmanFilter, eye
from .model import (N_INPUTS, U_GROUND, U_HEAT, U_INTERNAL, U_OUTDOOR,
                    U_SOLAR, BuildingParams, discretise, heat_demand_w,
                    eigen_time_constants_h, net_load_w)
from .solar import SolarModel
from .weather import WeatherSource

log = logging.getLogger("optimizer.estimator")


@dataclass
class Reading:
    """A value with the time it arrived, so staleness is always answerable."""
    value: float
    ts: float = field(default_factory=time.monotonic)

    def fresh(self, max_age_s: float) -> bool:
        return time.monotonic() - self.ts <= max_age_s


class Estimator:
    def __init__(self, cfg: dict, params: dict) -> None:
        self.cfg = cfg
        self.params = params
        b = params["building"]
        # ua_sa is DERIVED from its identification measurement and the flow,
        # not stored (D-032), so the flow error propagates structurally instead
        # of being annotated and forgotten.
        #
        # The stored fallback is kept on purpose and is not dead code: the same
        # partial-migration rule the loader follows. A synthetic config in a
        # test, or a params file not yet converted, gives a plain `ua_sa` and
        # must still load - a schema change that forces a big-bang rewrite of a
        # safety-adjacent file is one that gets rushed.
        if "ua_sa_identification" in b:
            ua_sa = derived.ua_sa(params).value
        else:
            ua_sa = b["ua_sa"]
        self.bp = BuildingParams(
            ua_ao=b["ua_ao"], ua_sa=ua_sa, ua_sg=b["ua_sg"],
            c_air_wh=b["c_air_wh"], c_slab_wh=b["c_slab_wh"],
            f_sol=b["f_sol"])
        self.t_ground = b["t_ground"]
        self.q_int = b["q_internal_w"]

        hi = params["heat_input"]
        self.cop = hi["assumed_cop"]
        self.standby_w = hi["standby_w"]

        # Pre-conditioning lead horizon in hours; None means 2*tau_fast from
        # the identified parameters, which is the original behaviour. Set it
        # to reach from the charging opportunity to the demand - see the long
        # comment in `setpoint_delta` for why that distance is a judgement
        # about capacity rather than something the parameters decide.
        # ONE FULL DIURNAL CYCLE, not the 0-5 h that 4 specifies for
        # `RL_curve`. That window was written for heating, where the near-term
        # outdoor IS what the floor compensates. In summer it makes the slab
        # target a function of TIME OF DAY: measured 2026-08-06 at 23:00, the
        # 5 h mean was 16.6 degC - the coldest part of the night - and the
        # target came back at ~25 degC, i.e. "this house needs heating", for a
        # house at 24-25 degC discharging the day's heat.
        #
        # A window shorter than the forcing period cannot describe a mass whose
        # slow mode is 58 h. 24 h is the shortest one that removes the
        # diurnal artefact, and it is the same horizon the pre-charge already
        # uses (`lead_horizon_h`). Not tuned until the number looked nice: a
        # daily mean is the coarsest thing that is still honest about a
        # building this slow.
        self.outdoor_avg_hours = int(
            cfg.get("optimizer", {}).get("outdoor_avg_hours", 24))
        lh = cfg.get("optimizer", {}).get("lead_horizon_h")
        self.lead_horizon_h = None if lh is None else float(lh)

        m = cfg["mqtt"]
        self.base = m.get("base_topic", "heatctl")
        self._host, self._port = m["host"], m.get("port", 1883)
        self._user = m.get("username") or None
        self._pass = m.get("password") or None

        # Room air topics that actually exist. Four of seven rooms have none;
        # the mean over the two that do is a biased estimate of house air
        # temperature and is knowingly used as one - see the class docstring
        # of model.py on why this stage is a stepping stone.
        self.room_topics = [r["room_temp_topic"] for r in cfg.get("rooms", [])
                            if r.get("room_temp_topic")]
        self.readings: dict[str, Reading] = {}
        # Indoor dew point, published by layer 1 / HA on the same topic the
        # condensation guard reads. Subscribed here so the humidity gap can be
        # MEASURED rather than assumed - see `humidity_gap`.
        self._dew_topic = m.get("dew_point_topic") or ""
        # The same margin safety adds to the dew point, so the planner sizes
        # against the limit layer 1 will actually enforce rather than a second,
        # separately-drifting number.
        self.dew_margin_c = float(cfg.get("safety", {})
                                  .get("dew_point_margin_c", 1.0))

        w = params["weather"]
        lat, lon = w.get("latitude"), w.get("longitude")
        self.weather = WeatherSource(lat, lon, w) if lat is not None else None
        # Per-facade solar needs the site's coordinates for solar position, so
        # it shares the forecast's gating: no coordinates, no solar model, and
        # the estimator runs with zero gain rather than a guess. That is the
        # honest degradation - a wrong gain shape is worse than none, because
        # it biases the slab estimate in a way the innovation cannot separate
        # from a genuine heating shortfall.
        self.solar = (SolarModel.from_config(params["solar"], lat, lon)
                      if lat is not None and params.get("solar") else None)

        self.filter: KalmanFilter | None = None
        # INPUT STALENESS IS LAYER 2's OWN, not layer 1's. This used to read
        # `safety.stale_data_timeout_s`, which is 15 s on this plant - a
        # CONTROL-LOOP timeout, correct for a 1 Hz loop that must failsafe on
        # lost sensors. Layer 2 consumes slow signals: room temperatures every
        # ~60 s, and the indoor dew point republished every 120 s. Against a
        # 15 s window the dew point read as stale ~87 % of the time, so
        # `humidity_gap()` returned None on almost every cycle and the
        # condensation ceiling silently sat on its fallback - which is exactly
        # what it looked like after the 2026-08-01 deploy: both ceiling
        # entities pinned at 5700 W.
        #
        # Being generous here is the safe direction: a slightly old dew point
        # still predicts tomorrow's humidity far better than no dew point at
        # all, and nothing in this module actuates.
        self.max_age_s = float(cfg.get("optimizer", {}).get(
            "input_max_age_s",
            max(900.0, float(cfg.get("safety", {})
                             .get("stale_data_timeout_s", 300)))))
        self._client: aiomqtt.Client | None = None
        self._last_load_summary: str | None = None
        self._last_delta: float | None = None

    # ---------- inputs ----------

    def house_air(self) -> float | None:
        """Mean of the fresh room readings, or None if none are fresh."""
        vals = [r.value for t, r in self.readings.items()
                if t in self.room_topics and r.fresh(self.max_age_s)]
        return sum(vals) / len(vals) if vals else None

    def heat_input_w(self) -> float:
        """Thermal watts into the slab. See params.yaml `heat_input`."""
        p = self.readings.get(f"{self.base}/hp/power_estimate")
        if p is None or not p.fresh(self.max_age_s) or p.value < self.standby_w:
            return 0.0
        return p.value * self.cop

    def solar_w(self, point=None) -> float:
        """Solar power through the glazing, per facade, at the forecast hour."""
        if not self.solar or not self.weather:
            return 0.0
        p = point or (self.weather.points[0] if self.weather.points else None)
        if p is None:
            return 0.0
        # `_when` attaches UTC explicitly rather than letting solar_position
        # assume it: that function rejects naive datetimes precisely so a
        # local-time stamp cannot silently shift the sun by hours.
        when = self._when(p)
        if when is None:
            return 0.0
        return self.solar.gain_w(when, p.dni, p.dhi, p.shortwave)

    @staticmethod
    def _when(point) -> dt.datetime | None:
        """Forecast point timestamp as aware UTC, or None if unusable."""
        try:
            when = dt.datetime.fromisoformat(point.time)
        except ValueError:
            return None
        # Open-Meteo is asked for timezone=UTC and returns naive stamps.
        return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)

    def room_solar_w(self, point=None) -> dict[str, float]:
        """Solar power into each room at the forecast hour, W.

        THE CURRENT HOUR, not a lead-window average, and that is a deliberate
        difference from `outdoor_avg_c`. The two feed different things.
        `outdoor_avg_c` sets a target for a mass with a 5.62 h time constant,
        so a spot value would ask the slab to chase weather noise. This feeds
        `slab_target_c`, which is a room energy BALANCE - `UA_sa(T_slab-T_room)
        = UA_ao(T_room-AT) - Q_sol - Q_int` - and the Q_sol in that equation is
        the gain the room is under right now. Averaging it away would state a
        load the room does not have.

        That the slab cannot follow a four-hour morning pulse is a physical
        fact about the building, not a reason to misreport the disturbance.
        The recovery term in `slab_target_c` is what answers the resulting
        error, and starting EARLIER than the pulse is a scheduling decision
        that belongs to the planner, not to this feedforward term. See
        `room_solar_hourly` for the series that makes such a plan possible.

        Empty dict when there is no forecast or no per-room mapping, so a
        consumer can tell "no data" from "no sun".
        """
        if not self.solar or not self.weather or not self.solar.rooms:
            return {}
        p = point or (self.weather.points[0] if self.weather.points else None)
        if p is None:
            return {}
        when = self._when(p)
        if when is None:
            return {}
        return self.solar.per_room_w(when, p.dni, p.dhi, p.shortwave)

    def room_solar_hourly(self, hours: int = 24) -> list[dict]:
        """Per-room solar gain, hour by hour, for the forecast window.

        A SERIES, NOT A SCHEDULE - the same distinction `hourly_forecast`
        makes. It says which room gets how much and when; turning that into a
        pre-cooling start time needs the trajectory simulation in WP-H.

        What it buys before that exists is that the shape is visible at all.
        The east rooms peaking mid-morning while the south peaks after noon is
        a falsifiable prediction, and per room it is checkable against the
        room's own sensor rather than against a house average that averages
        the effect away.
        """
        if not self.solar or not self.weather or not self.solar.rooms:
            return []
        out = []
        for pt in self.weather.points[:hours]:
            when = self._when(pt)
            if when is None:
                continue
            out.append({
                "t": pt.time,
                "rooms": {r: round(w, 0) for r, w in self.solar.per_room_w(
                    when, pt.dni, pt.dhi, pt.shortwave).items()},
            })
        return out

    def room_solar_peak(self, hours: int = 24) -> dict[str, dict]:
        """Each room's peak solar gain in the window, and when it lands.

        The operator-facing scalar behind the series. "Schlafzimmer peaks 788 W
        at 10:00" is something a human can read off a dashboard and check
        against a thermometer; a 24-element JSON blob is not.
        """
        peaks: dict[str, dict] = {}
        for row in self.room_solar_hourly(hours):
            for room, w in row["rooms"].items():
                if room not in peaks or w > peaks[room]["peak_w"]:
                    peaks[room] = {"peak_w": w, "at": row["t"]}
        return peaks

    def outdoor_c(self) -> float | None:
        """Measured outdoor first; forecast only as a fallback.

        Order matters. The forecast carries the valley's cold-pooling bias
        even after correction, and the correction is a statistical fit, not a
        measurement. When the station is alive its reading wins outright.
        """
        r = self.readings.get(self._outdoor_topic())
        if r is not None and r.fresh(self.max_age_s):
            return r.value
        if self.weather and self.weather.points:
            return self.weather.points[0].temperature
        return None

    def _outdoor_topic(self) -> str:
        for room in self.cfg.get("rooms", []):
            if room.get("name", "").lower() in ("aussen", "outdoor", "außen"):
                return room.get("room_temp_topic", "")
        return self.cfg.get("optimizer", {}).get("outdoor_topic", "")

    # ---------- filter ----------

    def ensure_filter(self, air: float) -> None:
        if self.filter is not None:
            return
        f = self.params["filter"]
        # The slab is initialised AT air temperature rather than at anything
        # cleverer, with a deliberately large p0 to say we do not believe it.
        # Seeding it from the supply temperature would be better when the pump
        # is running and much worse when it is not, and the filter converges
        # out of this within a few hours either way.
        self.filter = KalmanFilter(
            x=[air, air],
            P=[[f["p0_air_k"] ** 2, 0.0], [0.0, f["p0_slab_k"] ** 2]],
            Q=[[0.0, 0.0], [0.0, 0.0]],   # rebuilt per step, dt-dependent
            R=[[f["r_air_k"] ** 2]],
            H=[[1.0, 0.0]])
        log.info("filter initialised at air %.2f degC", air)

    def _process_noise(self, dt_s: float) -> list[list[float]]:
        """Q scaled to the step: variance grows linearly in time, so sd
        grows with the square root of it. Getting this wrong by using the
        per-hour figure directly at a 60 s step would make the filter trust
        the model roughly sixty times less than intended."""
        f = self.params["filter"]
        h = dt_s / 3600.0
        return [[(f["q_air_k_per_h"] ** 2) * h, 0.0],
                [0.0, (f["q_slab_k_per_h"] ** 2) * h]]

    def step(self, dt_s: float) -> dict | None:
        air = self.house_air()
        outdoor = self.outdoor_c()
        if outdoor is None:
            return None
        if self.filter is None:
            if air is None:
                return None
            self.ensure_filter(air)
        assert self.filter is not None

        u = [0.0] * N_INPUTS
        u[U_OUTDOOR] = outdoor
        u[U_SOLAR] = self.solar_w()
        u[U_INTERNAL] = self.q_int
        u[U_HEAT] = self.heat_input_w()
        u[U_GROUND] = self.t_ground

        F, G = discretise(self.bp, dt_s)
        self.filter.Q = self._process_noise(dt_s)
        self.filter.predict(F, G, u)
        innov = self.filter.update([air])[0] if air is not None else None

        out = {
            "t_air_est": round(self.filter.x[0], 3),
            "t_slab_est": round(self.filter.x[1], 3),
            "p_air": round(self.filter.P[0][0] ** 0.5, 3),
            "p_slab": round(self.filter.P[1][1] ** 0.5, 3),
            "outdoor": round(outdoor, 2),
            "q_heat_w": round(u[U_HEAT], 0),
            "q_solar_w": round(u[U_SOLAR], 0),
            "air_measured": round(air, 2) if air is not None else None,
            "innovation": round(innov, 3) if innov is not None else None,
        }
        out.update({f"innov_{k}": round(v, 4)
                    for k, v in self.filter.innovation_stats().items()})
        return out

    def demand_forecast(self, target_air: float, hours: int = 24) -> dict:
        """Steady-state heat demand over the forecast window.

        Steady state, NOT a simulation of the trajectory: with the slab's time
        constant this understates what pre-charging could achieve and says
        nothing about when to start. It is an energy figure to size the day,
        not a plan. Producing an actual schedule is WP-H, and it needs the
        filter's slab estimate to have earned trust first.
        """
        if not self.weather or not self.weather.points:
            return {}
        pts = self.weather.points[:hours]
        demands = [heat_demand_w(self.bp, target_air, p.temperature,
                                 self.t_ground, q_sol=self.solar_w(p),
                                 q_int=self.q_int) for p in pts]
        corr = [p.temperature - p.raw_temperature for p in pts]
        return {
            "hours": len(pts),
            "peak_w": round(max(demands), 0),
            "mean_w": round(sum(demands) / len(demands), 0),
            "energy_kwh": round(sum(demands) / 1000.0, 2),
            "coldest_c": round(min(p.temperature for p in pts), 2),
            "bias_applied_k": round(min(corr), 2),
        }

    def load_forecast(self, target_air: float, ceiling_w: float,
                      hours: int = 48) -> list[dict]:
        """Hourly signed load, split by day, against a delivery ceiling.

        This is the calculation that answers "what does tomorrow need", and it
        deliberately does NOT go through the Kalman filter. It uses only the
        heat loss coefficient, the solar geometry and the forecast - all
        measured or surveyed - so it is usable now, whereas the filter's slab
        estimate is still waiting on a heat meter and per-room sensors. The two
        were conflated for most of a day; they are separate.

        `ceiling_w` is what the plant can actually deliver. For this house that
        is the SOURCE limit, not the emitter limit: slab 4.8 kW plus fan coil
        4.2 kW is 9.0 kW of emitter against a heat pump good for 5.7 kW, so the
        machine binds first (docs/HARDWARE.md). Passing the slab figure alone
        overstates the deficit by about half.

        The `store_kwh` figure is the day's energy that arrives faster than the
        ceiling can remove it, and therefore has to come out of building mass.
        Divided by the thermal capacity it gives the pre-charge in kelvin -
        which has to be in place roughly one fast time constant before the
        deficit, or not at all.

        DO NOT WRITE THAT CONSTANT HERE AS A NUMBER. It is `eigen_time_constants_h(
        self.bp)[1]`, it moves with `ua_sa`, and by 2026-08-01 three different
        hand-written values were in circulation for it - "8 h" in this
        docstring, "3.4 h" in BACKLOG, and the 5.62 h the code actually derives
        at the current parameters. Whichever is quoted in prose goes stale the
        next time a parameter is re-measured, silently, which is exactly what
        D-031/D-032 and `optimizer/derived.py` exist to prevent.
        """
        if not self.weather or not self.weather.points:
            return []
        by_day: dict[str, list[float]] = {}
        for pt in self.weather.points[:hours]:
            net = net_load_w(self.bp, target_air, pt.temperature,
                             self.t_ground, q_sol=self.solar_w(pt),
                             q_int=self.q_int)
            by_day.setdefault(pt.time[:10], []).append(net)
        cap_kwh = (self.bp.c_slab_wh + self.bp.c_air_wh) / 1000.0
        out = []
        for day, loads in by_day.items():
            if len(loads) < 20:            # partial day - do not report it
                continue
            store = sum(max(0.0, x - ceiling_w) for x in loads) / 1000.0
            out.append({
                "day": day,
                "peak_kw": round(max(loads) / 1000.0, 2),
                "cooling_kwh": round(sum(max(0.0, x) for x in loads) / 1000, 1),
                "free_kwh": round(sum(max(0.0, -x) for x in loads) / 1000, 1),
                "hours_over": sum(1 for x in loads if x > ceiling_w),
                "store_kwh": round(store, 1),
                "precharge_k": round(store / cap_kwh, 2),
            })
        return out

    # ---------- condensation-limited delivery ceiling ----------

    @staticmethod
    def _w_from_dew(dew_c: float, p_pa: float = 101325.0) -> float:
        """Humidity ratio in g/kg from a dew point, via Magnus."""
        e = 610.94 * math.exp(17.625 * dew_c / (dew_c + 243.04))
        return 0.622 * e / (p_pa - e) * 1000.0

    @staticmethod
    def _dew_from_w(w_gkg: float, p_pa: float = 101325.0) -> float:
        """Inverse of `_w_from_dew`."""
        w = max(w_gkg, 1e-4) / 1000.0
        e = p_pa * w / (0.622 + w)
        lg = math.log(e / 610.94)
        return 243.04 * lg / (17.625 - lg)

    def humidity_gap(self) -> float | None:
        """Measured `W_indoor - W_outdoor`, in g/kg. The whole predictor.

        WHY A GAP AND NOT A MOISTURE MODEL. Fitting the balance
        `dW/dt = n(W_out - W) + G/(rho V)` was attempted on five months of
        archive on 2026-08-01 and FAILED to identify `n`: the house sits near
        moisture steady state, so `dW ~= 0` and the dynamics carry almost no
        information, while what variance `dW` has comes from unmeasured
        occupancy. See BACKLOG.

        What that same work DID establish tightly is the steady state itself -
        `<W_in - W_out> = 1.442 +- 0.018 g/kg` over 3002 hours. So the gap is
        the identifiable quantity, and predicting indoor humidity from a
        forecast outdoor one needs nothing else.

        MEASURED LIVE, NOT HARD-CODED, and that is deliberate: 1.442 is a
        WINTER figure with windows shut. On 2026-08-01 the owner opened the
        windows on humid outdoor air and the indoor dew point ROSE - the gap can
        go to zero or negative. A live estimate tracks the regime; a constant
        would have been confidently wrong on exactly the days that matter.
        """
        dew_in = self.readings.get(self._dew_topic) if self._dew_topic else None
        if dew_in is None or not dew_in.fresh(self.max_age_s):
            return None
        if not self.weather or not self.weather.points:
            return None
        dew_out = self.weather.points[0].dew_point
        if dew_out != dew_out:                      # NaN: API gave no dew point
            return None
        return self._w_from_dew(dew_in.value) - self._w_from_dew(dew_out)

    def ceiling_w(self, pt, target_air: float, gap_gkg: float | None,
                  fallback_w: float) -> float:
        """Deliverable cooling power for one forecast hour, W.

        THE SOURCE LIMIT NEVER BINDS IN COOLING. `load_forecast` was passed a
        static 5700 W - the heat pump's output - on the reasoning that the
        machine binds before the 9.0 kW of emitter. Measured 2026-08-01 through
        `derived.q_max`, the CONDENSATION limit binds before either: 3.40 kW on
        a humid day, 2.77 K on a very humid one, and even on dry air 5.10 kW.
        So every hour of the forecast was sized against a constraint that is
        never the active one, and `hours_over`, `store_kwh` and `precharge_k`
        all inherited that.

        Chain: forecast outdoor dew point -> add the measured gap -> indoor dew
        point -> condensation limit (dew + margin) -> `q_max` at that limit.

        Falls back to `fallback_w` when the gap or the dew point is unavailable,
        because a missing humidity signal must not silently zero the ceiling and
        make the planner think the plant can do nothing.
        """
        if gap_gkg is None:
            return fallback_w
        dew_out = pt.dew_point
        if dew_out != dew_out:
            return fallback_w
        w_in = self._w_from_dew(dew_out) + gap_gkg
        limit = self._dew_from_w(w_in) + self.dew_margin_c
        if target_air - limit <= 0:
            return 0.0                # supply cannot be below the room: no cooling
        q = derived.q_max(self.params, limit, target_air)
        return max(0.0, min(fallback_w, q.value))

    def hourly_forecast(self, target_air: float, ceiling_w: float,
                        hours: int = 48) -> list[dict]:
        """The per-hour series `load_forecast` computes and then throws away.

        Owner, 2026-08-01: *"it would make sense to have a prediction hour by
        hour for the forecast window instead of a lump sum, so we can start
        pre-cooling (or pre-heating) at the right moment."*

        `load_forecast` already evaluates every hour and immediately collapses
        the result into calendar-day totals, so "4 hours over ceiling tomorrow"
        cannot be turned into WHICH four hours. That is the difference between
        an energy figure and something you can act on: the same 15 kWh spread
        evenly is a different plan from the same 15 kWh at 16:00.

        THIS IS A SERIES, NOT A SCHEDULE, and the distinction is the same one
        `demand_forecast` makes: it says what is coming and when, not when to
        start. Turning it into a start time needs the trajectory simulation in
        WP-H. What it buys now is that the shape is visible at all - to a human
        reading the dashboard, and to the planner when it exists.

        `deficit_w` is signed the way the rest of this module signs load:
        positive means the hour needs more cooling than `ceiling_w` can supply.
        """
        if not self.weather or not self.weather.points:
            return []
        out = []
        gap = self.humidity_gap()
        for pt in self.weather.points[:hours]:
            load = net_load_w(self.bp, target_air, pt.temperature,
                              self.t_ground, q_sol=self.solar_w(pt),
                              q_int=self.q_int)
            cap = self.ceiling_w(pt, target_air, gap, ceiling_w)
            out.append({
                "t": pt.time,
                "load_w": round(load, 0),
                "ceiling_w": round(cap, 0),
                "outdoor_c": round(pt.temperature, 1),
                # Outdoor dew point, UNCORRECTED and for planning only - the
                # condensation guard uses the measured INDOOR maximum and must
                # never see this (see weather.py). Carried because the delivery
                # ceiling is condensation-limited, not source-limited, and this
                # is the only forward-looking humidity signal available.
                "dew_point_c": (None if pt.dew_point != pt.dew_point
                                else round(pt.dew_point, 1)),
                "deficit_w": round(max(0.0, load - cap), 0),
            })
        return out

    def lead_h(self) -> float:
        """Effective pre-conditioning lead horizon in hours.

        One place, so the logged number and the number actually weighting the
        sum cannot drift apart - the log used to print tau and call it the
        lead time, which is off by the factor of two.
        """
        if getattr(self, "lead_horizon_h", None) is not None:
            return float(self.lead_horizon_h)
        return 2.0 * eigen_time_constants_h(self.bp)[1]

    def outdoor_avg_c(self, hours: int | None = None) -> float | None:
        """Mean forecast outdoor temperature over the lead window.

        The window is the one 4 specifies for `RL_curve` - forecast-averaged,
        default 0-5 h ahead - not an instantaneous reading. Feeding a spot
        value to a target that governs a mass with a 5.62 h time constant asks
        the slab to chase weather noise, and at night it asks it to chase the
        one number that is least representative of the day ahead.

        Returns None rather than a stale figure when there is no forecast, so
        layer 1 can fall back to its own sensor and say which it used.
        """
        if not self.weather or not self.weather.points:
            return None
        n = hours if hours is not None else self.outdoor_avg_hours
        now = dt.datetime.now(dt.timezone.utc).replace(
            minute=0, second=0, microsecond=0)
        ahead = [pt.temperature for pt in self.weather.points
                 if dt.datetime.fromisoformat(pt.time).replace(
                     tzinfo=dt.timezone.utc) >= now][:n]
        return sum(ahead) / len(ahead) if ahead else None

    def setpoint_delta(self, target_air: float, ceiling_w: float,
                       hours: int = 24) -> float:
        """Signed pre-conditioning delta in K: `active = dial + delta`.

        DERIVED, not chosen: the excess energy still AHEAD of us, divided by the
        building's thermal capacity - i.e. exactly how far below target the mass
        has to start for that excess to land in it rather than in the room.

        **Forward-looking from the current hour, and that is the whole point.**
        The earlier version worked off calendar-day totals from `load_forecast`,
        and the forecast window begins at MIDNIGHT - so "today still has 9 hours
        over the ceiling" stayed true at 23:00, and the delta would have
        pre-cooled overnight for a day that was already finished. Measured
        2026-07-30: that would have asked for 1.44 K when the next day needed
        0.28 K, over-cooling the house by more than a kelvin for nothing.

        Summing forward also removes the day-boundary logic entirely. Excess
        does not care which calendar day it falls in; the mass has to absorb
        whatever is coming.

        **Excess beyond a lead horizon is tapered away**, which is what gives
        the delta a lead time at all. See the comment on the sum below for why
        it is a horizon and not a decay - the obvious exp(-dt/tau) form is
        wrong for an actuator that holds a setpoint rather than injecting a
        lump of charge - and for why the horizon itself is configurable.
        """
        if not self.weather or not self.weather.points:
            return 0.0
        now = dt.datetime.now(dt.timezone.utc).replace(
            minute=0, second=0, microsecond=0)
        ahead = [pt for pt in self.weather.points
                 if dt.datetime.fromisoformat(pt.time).replace(
                     tzinfo=dt.timezone.utc) >= now][:hours]
        if not ahead:
            return 0.0
        # HORIZON, NOT DECAY - and the difference matters, because getting it
        # backwards was the first attempt at this.
        #
        # The tempting form is to weight each future hour by exp(-dt/tau): the
        # fraction of a charge put in now that survives until then. That is the
        # survival of an IMPULSE, and it is the wrong model for this actuator.
        # The controller does not inject a lump of coolth and walk away - it
        # holds the setpoint down, continuously replenishing against the decay.
        # Held charge does not decay; only abandoned charge does.
        #
        # Weighting by impulse survival therefore under-charges exactly when
        # charging is possible. Measured against a 15:00 peak it gives weights
        # of 0.07-0.24 through the night, i.e. ~0.05 K of pre-cooling, and only
        # ramps up mid-morning once the rising load has already eaten the
        # plant's spare capacity. Overnight is the ONLY time this house has
        # spare capacity; a rule that declines to use it is worse than the flat
        # sum it replaced.
        #
        # So: full weight inside a lead horizon, tapering beyond it. The
        # default horizon is 2*tau_fast - two fill constants ahead of the
        # excess is where holding the setpoint down starts to pay - and the
        # taper beyond it falls off with tau_fast.
        #
        # WHY THE HORIZON IS A KNOB (2026-08-02). The default rests on an
        # argument that is sound but incomplete: the delta is recomputed every
        # minute, so it needs only enough lead to FILL the store (tau_fast),
        # and asking earlier spends comfort and standing loss on a charge a
        # later cycle could have put in just as well. True as far as it goes.
        #
        # What it does not model is whether that later cycle will still have
        # the capacity. Measured this night: tomorrow forecast 7 h over
        # ceiling needing 0.43 K, and its 15:00 peak - 17 h out - was weighted
        # 0.36, so the delta read -0.20 K. Waiting until the peak is inside
        # the horizon means charging from ~09:00, by which time the load is
        # rising and the spare capacity that makes charging possible is going
        # away. Overnight is when this house has capacity to spare; a horizon
        # shorter than the night-to-afternoon distance cannot use it.
        #
        # Neither argument is decidable from the parameters - it turns on
        # whether spare capacity persists, which nothing here measures yet. So
        # the horizon is explicit and configurable rather than silently one or
        # the other, and `optimizer.lead_horizon_h` in config.yaml carries the
        # value actually being run. Default preserves the original behaviour.
        _, tau_h = eigen_time_constants_h(self.bp)
        lead_h = self.lead_h()
        loads, weights = [], []
        for i, pt in enumerate(ahead):
            loads.append(net_load_w(self.bp, target_air, pt.temperature,
                                    self.t_ground, q_sol=self.solar_w(pt),
                                    q_int=self.q_int))
            weights.append(1.0 if i <= lead_h
                           else math.exp(-(i - lead_h) / tau_h))
        cool_excess = sum(max(0.0, x - ceiling_w) * w
                          for x, w in zip(loads, weights)) / 1000.0
        heat_excess = sum(max(0.0, -x - ceiling_w) * w
                          for x, w in zip(loads, weights)) / 1000.0
        cap = (self.bp.c_slab_wh + self.bp.c_air_wh) / 1000.0
        if cool_excess >= heat_excess:
            return 0.0 if cool_excess <= 0 else -round(cool_excess / cap, 2)
        return 0.0 if heat_excess <= 0 else round(heat_excess / cap, 2)

    # ---------- MQTT, status only ----------

    async def _discover(self) -> None:
        """Register the layer-2 outputs as HA entities.

        WHY THIS EXISTS. Everything this module produced was publish-only to
        MQTT with NO discovery, so none of it was visible in Home Assistant -
        `setpoint_delta`, the day totals, the forecast, all of it. The module
        already carries a comment noting that answering "what is the optimizer
        asking for right now" meant hunting an MQTT client twice; the fix for
        that was to LOG the value, which helps whoever is reading logs and
        nobody else.

        A separate HA device from layer 1 on purpose: these are predictions,
        not measurements, and an operator should never mistake one for the
        other on a dashboard.
        """
        if self._client is None:
            return
        for uid, name, unit, dclass, icon in (
                ("opt_humidity_gap", "Humidity gap (indoor - outdoor)",
                 "g/kg", None, "mdi:water-percent"),
                ("opt_ceiling_now", "Delivery ceiling now",
                 "W", "power", "mdi:speedometer"),
                ("opt_ceiling_min_24h", "Delivery ceiling min 24 h",
                 "W", "power", "mdi:speedometer-slow"),
                ("opt_deficit_24h", "Cooling deficit 24 h",
                 "kWh", "energy", "mdi:alert-decagram-outline"),
                ("opt_setpoint_delta", "Pre-conditioning delta",
                 "K", None, "mdi:thermometer-chevron-down")):
            conf = {
                "unique_id": uid,
                "name": name,
                "state_topic": f"{self.base}/opt/{uid.removeprefix('opt_')}",
                "state_class": "measurement",
                "device": {"identifiers": ["heatctl_optimizer"],
                           "name": "heatctl optimizer",
                           "manufacturer": "heatctl",
                           "model": "layer 2 (prediction only)"},
            }
            if unit:
                conf["unit_of_measurement"] = unit
            if dclass:
                conf["device_class"] = dclass
            if icon:
                conf["icon"] = icon
            with contextlib.suppress(Exception):
                await self._client.publish(
                    f"homeassistant/sensor/heatctl_opt/{uid}/config",
                    json.dumps(conf), retain=True)

        # Per-room solar, one entity per room. Discovered rather than left as
        # raw topics for the same reason as everything above: a number nobody
        # can graph is a number nobody checks, and this one is a PREDICTION
        # that badly needs checking against the room's own thermometer.
        for room in sorted((self.solar.rooms if self.solar else {})):
            for suffix, label, icon in (
                    ("solar_w", "solar gain", "mdi:weather-sunny"),
                    ("solar_peak_w", "solar peak 24 h",
                     "mdi:weather-sunny-alert")):
                uid = f"opt_room_{room}_{suffix}"
                conf = {
                    "unique_id": uid,
                    "name": f"{room} {label}",
                    "state_topic": f"{self.base}/opt/room/{room}/{suffix}",
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "state_class": "measurement",
                    "icon": icon,
                    "device": {"identifiers": ["heatctl_optimizer"],
                               "name": "heatctl optimizer",
                               "manufacturer": "heatctl",
                               "model": "layer 2 (prediction only)"},
                }
                with contextlib.suppress(Exception):
                    await self._client.publish(
                        f"homeassistant/sensor/heatctl_opt/{uid}/config",
                        json.dumps(conf), retain=True)

    async def _publish(self, subtopic: str, payload: str,
                       retain: bool = False) -> None:
        """Publish under `<base>/opt/` and nowhere else.

        The guard is not decoration. `heatctl/set/#` is a live command
        surface with no TTL behind it (DESIGN.md 2.2), so a stray publish
        from here would be indistinguishable from an operator command and
        would persist until something else overwrote it.
        """
        if subtopic.startswith("/") or ".." in subtopic:
            raise ValueError(f"refusing to publish outside opt/: {subtopic!r}")
        if self._client is None:
            return
        await self._client.publish(f"{self.base}/opt/{subtopic}", payload,
                                   retain=retain)

    async def run(self) -> None:
        interval = float(self.cfg.get("optimizer", {}).get("interval_s", 60))
        topics = list(self.room_topics) + [f"{self.base}/hp/power_estimate"]
        if self._dew_topic:
            topics.append(self._dew_topic)
        ot = self._outdoor_topic()
        if ot:
            topics.append(ot)
        while True:
            try:
                async with aiomqtt.Client(
                        hostname=self._host, port=self._port,
                        username=self._user, password=self._pass,
                        identifier="heatctl-optimizer") as client:
                    self._client = client
                    for t in topics:
                        await client.subscribe(t)
                    await self._discover()
                    log.info("optimizer connected, %d topics", len(topics))
                    loop = asyncio.create_task(self._loop(interval))
                    try:
                        async for msg in client.messages:
                            self._on_message(str(msg.topic),
                                             msg.payload.decode())
                    finally:
                        loop.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await loop
            except aiomqtt.MqttError as e:
                log.warning("broker connection lost (%s); retrying", e)
            except asyncio.CancelledError:
                raise
            finally:
                self._client = None
            await asyncio.sleep(5)

    def _on_message(self, topic: str, payload: str) -> None:
        try:
            self.readings[topic] = Reading(float(payload))
        except ValueError:
            pass   # non-numeric payloads on subscribed topics are not ours

    async def _loop(self, interval: float) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            dt, last = now - last, now
            try:
                if self.weather:
                    await self.weather.refresh()

                # The FORWARD LOAD FORECAST FIRST, and deliberately not gated
                # on the filter having inputs. It uses only the heat loss
                # coefficient, the solar geometry and the forecast - all
                # measured or surveyed - so it works with no room sensor, no
                # heat meter and no converged slab estimate. Publishing it
                # inside the filter's success path made "what does tomorrow
                # need" depend on machinery it has no relationship with, which
                # is the same conflation that kept this offline for a day.
                opt = self.cfg.get("optimizer", {})
                target = opt.get("target_air_c", 21.0)
                days = self.load_forecast(target,
                                          opt.get("delivery_ceiling_w", 5700.0))
                if days:
                    # Log on CHANGE only. The forecast refreshes twice an hour
                    # and these numbers move slowly, so logging every 60 s cycle
                    # would bury everything else - but never logging them would
                    # leave the day's plan visible only to whoever is holding an
                    # MQTT client.
                    summary = "; ".join(
                        f"{d['day']} peak {d['peak_kw']:.1f} kW, "
                        f"{d['cooling_kwh']:.0f} kWh, {d['hours_over']} h over "
                        f"ceiling, pre-charge {d['precharge_k']:.2f} K"
                        for d in days)
                    if summary != self._last_load_summary:
                        log.info("load forecast: %s", summary)
                        self._last_load_summary = summary
                    await self._publish("load_forecast", json.dumps(days))
                    # The hour-by-hour series behind those totals. Published
                    # separately rather than folded into `load_forecast` so the
                    # daily aggregates keep their shape for anything already
                    # reading them.
                    series = self.hourly_forecast(
                        target, opt.get("delivery_ceiling_w", 5700.0))
                    await self._publish("forecast_hourly", json.dumps(series))

                    # PER-ROOM SOLAR. Retained, unlike the rest of this
                    # module's output, because layer 1 consumes it: a heatctl
                    # restart would otherwise run with q_sol = 0 for every room
                    # until the next cycle, which silently understates the load
                    # in exactly the rooms this exists to describe.
                    room_now = self.room_solar_w()
                    for room, w in room_now.items():
                        await self._publish(f"room/{room}/solar_w",
                                            f"{w:.0f}", retain=True)
                    for room, pk in self.room_solar_peak().items():
                        await self._publish(f"room/{room}/solar_peak_w",
                                            f"{pk['peak_w']:.0f}", retain=True)
                    rows = self.room_solar_hourly()
                    if rows:
                        await self._publish("room_solar_hourly",
                                            json.dumps(rows))
                    # SCALARS, not just the JSON blob. A series is for a
                    # planner; a number is what an operator can put on a
                    # dashboard and watch. Publishing only the blob is how this
                    # layer stayed invisible.
                    gap = self.humidity_gap()
                    if gap is not None:
                        await self._publish("humidity_gap", f"{gap:.2f}")
                    if series:
                        nxt = series[:24]
                        await self._publish("ceiling_now",
                                            f"{series[0]['ceiling_w']:.0f}")
                        await self._publish(
                            "ceiling_min_24h",
                            f"{min(r['ceiling_w'] for r in nxt):.0f}")
                        await self._publish(
                            "deficit_24h",
                            f"{sum(r['deficit_w'] for r in nxt)/1000.0:.2f}")
                    t = days[0]
                    await self._publish("today/peak_kw", str(t["peak_kw"]))
                    await self._publish("today/cooling_kwh",
                                        str(t["cooling_kwh"]))
                    await self._publish("today/precharge_k",
                                        str(t["precharge_k"]))
                    delta = self.setpoint_delta(
                        target, opt.get("delivery_ceiling_w", 5700.0))
                    # LOG IT, not just publish it. This is the one number that
                    # actually reaches the control core, and it was publish-only
                    # - so answering "what is the optimizer asking for right
                    # now" meant hunting an MQTT client, twice. Logged on change
                    # only, alongside the forecast summary it derives from.
                    if delta != self._last_delta:
                        log.info("setpoint delta %+.2f K (target %.1f, "
                                 "horizon %.1f h, taper %.1f h)", delta,
                                 target, self.lead_h(),
                                 eigen_time_constants_h(self.bp)[1])
                        self._last_delta = delta
                    # FORECAST-AVERAGED OUTDOOR for layer 1's slab target.
                    # DESIGN_ENERGY_DEMAND.md 2 asks for this and layer 1 was
                    # shipped using the instantaneous reading instead, which is
                    # what produced a -20 kWh "deficit" on the night of
                    # 2026-08-06: the slabs were cold from the day's cooling and
                    # the target was computed against a 20 degC night as if that
                    # were the whole story. A slab responds over hours, so the
                    # question is not what it is outside now but what is coming.
                    #
                    # A PARAMETER, not a command - layer 1 decides what to do
                    # with it and falls back to its own sensors when this goes
                    # stale, exactly as it does for the pre-conditioning delta.
                    avg = self.outdoor_avg_c()
                    if avg is not None:
                        await self._publish("outdoor_avg_c", f"{avg:.2f}")
                    await self._publish("setpoint_delta", f"{delta:.2f}")
                    if len(days) > 1:
                        n = days[1]
                        await self._publish("tomorrow/peak_kw",
                                            str(n["peak_kw"]))
                        await self._publish("tomorrow/cooling_kwh",
                                            str(n["cooling_kwh"]))
                        await self._publish("tomorrow/precharge_k",
                                            str(n["precharge_k"]))
                        await self._publish("tomorrow/hours_over",
                                            str(n["hours_over"]))

                state = self.step(dt)
                if state is None:
                    await self._publish("status", "forecast_only")
                    continue
                await self._publish("status", "ok")
                await self._publish("state", json.dumps(state))
                for k, v in state.items():
                    if v is not None:
                        await self._publish(k, str(v))
                d = self.demand_forecast(target)
                if d:
                    await self._publish("demand", json.dumps(d))
            except asyncio.CancelledError:
                raise
            except Exception:
                # Layer 2 is allowed to fail, but it is not allowed to fail
                # silently or to stop: a dead estimator that keeps its last
                # value on the broker looks exactly like a healthy one.
                log.exception("estimator step failed")
                with contextlib.suppress(Exception):
                    await self._publish("status", "error")
