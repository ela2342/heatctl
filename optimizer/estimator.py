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
        self.bp = BuildingParams(
            ua_ao=b["ua_ao"], ua_sa=b["ua_sa"], ua_sg=b["ua_sg"],
            c_air_wh=b["c_air_wh"], c_slab_wh=b["c_slab_wh"],
            f_sol=b["f_sol"])
        self.t_ground = b["t_ground"]
        self.q_int = b["q_internal_w"]

        hi = params["heat_input"]
        self.cop = hi["assumed_cop"]
        self.standby_w = hi["standby_w"]

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
        self.max_age_s = float(cfg.get("safety", {})
                               .get("stale_data_timeout_s", 300))
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
        try:
            when = dt.datetime.fromisoformat(p.time)
        except ValueError:
            return 0.0
        if when.tzinfo is None:
            # Open-Meteo is asked for timezone=UTC and returns naive stamps.
            # Attaching UTC explicitly rather than letting solar_position
            # assume it: that function rejects naive datetimes precisely so a
            # local-time stamp cannot silently shift the sun by hours.
            when = when.replace(tzinfo=dt.timezone.utc)
        return self.solar.gain_w(when, p.dni, p.dhi, p.shortwave)

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
        which, with an 8 h slab time constant, has to be in place the night
        before or not at all.
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

        **Excess beyond a lead horizon of two fast time constants is tapered
        away**, which is what gives the delta a lead time at all. See the
        comment on the sum below for why it is a horizon and not a decay - the
        obvious exp(-dt/tau) form is wrong for an actuator that holds a
        setpoint rather than injecting a lump of charge.
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
        # So: full weight inside a lead horizon, tapering beyond it. The horizon
        # is 2*tau - two fast time constants ahead of the excess is where
        # holding the setpoint down starts to pay - and the taper beyond it
        # falls off with tau. Both come from the identified parameters; neither
        # is hand-picked. What this buys over a flat sum is a horizon at all:
        # excess two days out no longer demands pre-cooling tonight.
        _, tau_h = eigen_time_constants_h(self.bp)
        lead_h = 2.0 * tau_h
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

    async def _publish(self, subtopic: str, payload: str) -> None:
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
        await self._client.publish(f"{self.base}/opt/{subtopic}", payload)

    async def run(self) -> None:
        interval = float(self.cfg.get("optimizer", {}).get("interval_s", 60))
        topics = list(self.room_topics) + [f"{self.base}/hp/power_estimate"]
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
                                 "lead time %.1f h)", delta, target,
                                 eigen_time_constants_h(self.bp)[1])
                        self._last_delta = delta
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
