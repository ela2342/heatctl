"""Safety layer. Runs AFTER control and may override everything.

Principle: control proposes, safety decides. Every rule here must work
without MQTT command plane, without HA, without layer 2.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("heatctl.safety")


class Safety:
    def __init__(self, cfg: dict):
        s = cfg["safety"]
        self.setpoint_min = s["setpoint_min_c"]
        self.setpoint_max = s["setpoint_max_c"]
        self.vl_max_heating = s["vl_max_heating_c"]
        self.frost_c = s["frost_protect_c"]
        self.stale_timeout = s["stale_data_timeout_s"]
        self.failsafe_pct = s["failsafe_valve_pct"]

        # Dew-point supervision. THERE IS NO STATIC FALLBACK, and there is no
        # flag to re-enable one. The condensation limit is the indoor dew point
        # plus a margin; without a dew point we do not know it, so we do not
        # cool. A number invented to stand in for it is not a floor, it is a
        # guess wearing a floor's clothes - `vl_min_cooling_c: 16.0` was BELOW
        # the live limit on 2026-07-31 (16.5-16.8), so losing the dew point
        # made the constraint LOOSER. Removed 2026-07-31 on the owner's
        # instruction, along with `cooling_requires_dew_point`, which existed
        # only to choose between stopping and trusting that guess.
        self.dew_margin = s.get("dew_point_margin_c", 1.0)
        self.dew_max_age = s.get("dew_point_max_age_s", 900)
        # ASYMMETRIC hysteresis on the condensation guard. Trip immediately,
        # release only `release_margin` above the limit. See apply().
        self.dew_release_margin = s.get("dew_point_release_margin_c", 0.3)
        # How long supply must sit below the dew point CONTINUOUSLY before the
        # valve backstop fires. 0 restores the pre-2026-08-01 instant trip.
        # See the long note in apply() - this is what turns the guard from a
        # noise amplifier into the last stage of a cascade.
        self.undertemp_dwell_s = float(s.get("undertemp_dwell_s", 180.0))
        self._undertemp_since: float | None = None
        self._cooling_tripped = False
        self._dew: float | None = None
        self._dew_ts = 0.0
        self._dew_logged: float | None = None

    def clamp_setpoint(self, sp: float) -> float:
        return max(self.setpoint_min, min(self.setpoint_max, sp))

    def set_dew_point(self, dp: float | None, now: float | None = None) -> None:
        """Feed the latest measured dew point. None simply means no update."""
        if dp is None:
            return
        self._dew = dp
        self._dew_ts = time.monotonic() if now is None else now

    def dew_point_known(self, now: float | None = None) -> bool:
        """Is there a dew-point reading fresh enough to act on?"""
        now = time.monotonic() if now is None else now
        return self._dew is not None and now - self._dew_ts <= self.dew_max_age

    def cooling_supply_limit(self, now: float | None = None) -> float:
        """Lowest supply temperature cooling may run at, right now.

        With a fresh dew point this is exactly `dew point + margin`. There is
        deliberately no lower floor on it (D-024, removed 2026-07-28): a floor
        low enough to permit useful cooling is not a safe floor anyway - a
        12 degC indoor dew point is an ordinary 22 degC at 53 % RH - and one
        high enough to be genuinely safe blocks cooling outright, which is the
        static limit this mechanism replaced. The reading is defended by being
        the MAXIMUM across every instrumented room and by the staleness check,
        not by clamping its output.

        The margin is EMPIRICAL: it matches the margin the existing HA
        supervisory loop has run at without condensation. It is a margin on
        the right quantity, though - the floor build-up is vapour-permeable,
        so condensation is not confined to the visible floor surface. Moist
        air reaches into the slab and condenses throughout it, including
        directly on the pipe wall, which sits essentially at water
        temperature. Supply temperature is therefore very nearly the surface
        that matters, with no hidden reserve behind a screed gradient. What
        the margin has to cover is measurement error and the spread of indoor
        dew point between rooms. Sizing it properly is a BACKLOG.md item.

        Worth knowing when tempted to relax any of this: condensation inside
        the slab is invisible. There is no wet patch to prompt anyone to
        intervene.

        Deviation from docs/DESIGN.md 3.5, which specifies
        `max(static, dew_point + margin)`: taking the max makes live data
        useless in the dry direction - it can only ever tighten the static
        guess, never relax it. Measured 2026-07-27: an 11.4 degC dew point
        would still have been clamped to 16.0, holding circuits shut with 4.6
        K of headroom to spare.

        **Returns None when the dew point is unknown**, and callers must treat
        that as "do not cool" rather than substituting anything. There is no
        static fallback: the limit depends on indoor humidity, so a fixed
        number cannot express it, and the one that used to live here (16.0) sat
        BELOW the live limit on a normal summer afternoon - losing the dew
        point relaxed the constraint instead of tightening it.
        """
        now = time.monotonic() if now is None else now
        if not self.dew_point_known(now):
            if self._dew_logged is not None:
                log.warning("dew point stale or absent - no cooling limit can "
                            "be computed, so cooling stops")
                self._dew_logged = None
            return None
        limit = self._dew + self.dew_margin
        if self._dew_logged is None or abs(self._dew - self._dew_logged) >= 0.5:
            log.info("cooling supply limit %.1f degC (dew point %.1f + %.1f)",
                     limit, self._dew, self.dew_margin)
            self._dew_logged = self._dew
        return limit

    def apply(self, mode: str, state, circuit_sensor: str,
              proposed_pct: float,
              now: float | None = None) -> tuple[float, str | None]:
        """Returns (valve position, reason). reason != None => override active.

        Failure policy - two deliberately different directions:

        * FAIL OPEN when we have lost *knowledge* (sensor fault, stale data, a
          crashed controller). The heat pump's own controller holds a return
          water setpoint, so an open circuit with no supervision still gets
          water at a sane temperature. All that is lost is efficient
          distribution and per-room control - not safety. Driven by
          `safety.failsafe_valve_pct`.
        * FAIL CLOSED when the supply temperature is *known* to be dangerous:
          screed overtemp in heating, below-dew-point in cooling. Here opening
          is the actively harmful choice, and "the heat pump holds a setpoint"
          no longer applies because the measurement says it is not. These
          stay at 0 % on purpose - do not "make everything fail open".
        * FAIL CLOSED IN COOLING when the dew point is unknown, if
          a dew point. Condensation is the one limit we
          cannot bound without a measurement, and the damage is wet floors
          rather than a warm screed the slab mass absorbs. See
          cooling_supply_limit() for why a static number is not a safe
          substitute.

        ORDER MATTERS, and not in the obvious way. The known-bad-supply rules
        are checked BEFORE the fail-open one, because they depend on the
        SUPPLY sensor and are independent of this circuit's return sensor.
        Checking fail-open first (as this did until 2026-07-27) meant a single
        faulted return sensor forced its circuit open even while the supply
        was measurably dangerous - condensation protection defeated by an
        unrelated sensor fault. Frost still outranks everything, because a
        burst pipe is unrecoverable and it needs a valid return reading.

        Note the hardware limit: per the legacy system's records the actuators
        are NC (normally closed), so a loss of signal or power closes them
        regardless of what we command. Fail-open therefore covers software and
        bridge failure (with the coupler's Modbus watchdog fallback set to full
        scale), not power loss. True fail-open would need NO actuators.
        """
        rl = state.temps.get(circuit_sensor)
        vl = state.temps.get("vl_total")
        rl_valid = circuit_sensor not in state.faults and rl is not None

        # Frost protection beats everything - needs a valid return reading.
        if rl_valid and rl < self.frost_c:
            return 100.0, "frost_protect"

        # Known-dangerous supply. Independent of this circuit's sensor, so
        # checked before the fail-open rule below - see the note above.
        if mode == "heating" and vl is not None and vl > self.vl_max_heating:
            return 0.0, "vl_overtemp"    # screed protection

        _now = time.monotonic() if now is None else now
        if mode == "cooling":
            # Condensation guard, deliberately scoped to cooling (owner's
            # call, 2026-07-27). An earlier draft made it mode-independent, on
            # the theory that heatctl's mode and the pump's could diverge. They
            # can - but heatctl now READS the pump's own mode register, so the
            # honest fix is to detect a disagreement and alarm, not to run a
            # condensation guard in heating where a lukewarm start-up supply
            # plus humid air would block the house warming up.
            # NO VALVE ACTION ON AN UNKNOWN DEW POINT. Removed 2026-08-01.
            #
            # This used to `return 0.0, "dew_point_unknown"`, closing every
            # owned valve until the first dew-point message arrived over MQTT.
            # Measured that day: 33 s of a fully shut manifold on EVERY
            # restart, four restarts, and Er03 - which latches and needs a
            # person at the unit - three times.
            #
            # Two things make that the wrong actuator, not merely badly tuned:
            #   * It inverts D-003. Lost knowledge fails OPEN everywhere else,
            #     and this failed CLOSED into a fault only a human can clear.
            #   * "Nobody has told me the dew point" is not a measured danger
            #     to the screed. It is a reason not to MAKE cold water, which
            #     is a source-side action. Shutting valves cannot stop the
            #     compressor; it can only starve the pump.
            #
            # The refusal now lives where it belongs: main.py commands the
            # compressor OFF while the dew point is unknown. Valve position is
            # left exactly as control proposed.
            if not self.dew_point_known(now):
                self._undertemp_since = None
                self._cooling_tripped = False
                return proposed_pct, None
            if vl is not None:
                # THE GUARD TRIPS AT THE DEW POINT, not at the control target
                # (owner, 2026-07-31: "Trip at 0, target 1K"). These are two
                # different jobs and stacking them cost a whole margin:
                #   control target = dew + dew_point_margin_c   (how badly we
                #                    know the dew point)
                #   guard trip     = dew                        (the physical
                #                    boundary, a genuine last resort)
                # Previously the guard tripped at the target, so the controller
                # could not aim there without sitting on the trip threshold -
                # which is what `capacity.target_margin_c` was really buying.
                limit = self._dew
                # ASYMMETRIC BY DESIGN. Trip the instant supply goes below the
                # limit; release only once it is `release_margin` clear of it.
                #
                # Measured 2026-07-28 07:32 (D-023). A strict `vl < limit`
                # compares two INDEPENDENTLY quantised 0.1 K signals, and the
                # better the plant is controlled the more time supply spends
                # sitting exactly on the limit - load compensation drives it
                # there on purpose. One LSB tick in EITHER signal then flips
                # every owned valve. That morning the trip came from supply
                # (14.5 -> 14.4) and the release 16 s later came from the DEW
                # POINT (12.5 -> 12.4, limit 14.5 -> 14.4) with supply
                # unchanged, so instrumenting only the supply side would have
                # missed half of it. 16 s against a 150 s actuator stroke
                # means the valve never reached either commanded position and
                # its true opening became unknown.
                #
                # The asymmetry is the safety-relevant part: closing is the
                # protective direction and must stay instantaneous, so the
                # margin may only ever DELAY REOPENING. Do not "simplify" this
                # into a symmetric band - that would defer the trip.
                below = (vl < limit or (self._cooling_tripped
                                        and vl < limit + self.dew_release_margin))
                # DWELL BEFORE TRIPPING. Added 2026-08-01, owner's call.
                #
                # The instant trip above was firing on ONE 0.1 K quantisation
                # tick in either signal (D-023 records a trip from supply and a
                # release 16 s later from the dew point moving instead), and
                # every firing starved the pump into a latched Er03. Against a
                # 150 s actuator stroke the valve never even reached the
                # commanded position, so the "protection" was noise in and a
                # plant outage out.
                #
                # Owner, 2026-08-01: *"it's not like a minute or three below
                # dew point causes immediate harm, if it is a rare event."*
                # Condensation is a rate process; three minutes deposits
                # nothing that matters.
                #
                # The dwell is not an arbitrary delay - it is what makes this a
                # CASCADE. The capacity loop cuts frequency within a cycle and
                # stops the compressor at its floor, so if supply is still
                # under the dew point after the dwell, the source-side
                # protection has demonstrably failed and this backstop should
                # fire. That is the case worth keeping: on 2026-08-01 the heat
                # pump was unreachable for 8 minutes with supply 0.1 K off the
                # dew point, and nothing else could have stopped it.
                #
                # Set `undertemp_dwell_s: 0` to restore the instant trip.
                if below:
                    if self._undertemp_since is None:
                        self._undertemp_since = _now
                    if _now - self._undertemp_since >= self.undertemp_dwell_s:
                        self._cooling_tripped = True
                        return 0.0, "vl_undertemp"
                    return proposed_pct, None
                self._undertemp_since = None
            self._cooling_tripped = False
        else:
            # Mode left cooling; the latch must not survive into the next
            # cooling period (restart == safe state, and so does a mode flip).
            # The dwell timer is part of that latch and must reset with it, or
            # a mode flip would carry accumulated below-limit time into a fresh
            # cooling period and trip on the first cycle.
            self._cooling_tripped = False
            self._undertemp_since = None

        # Lost knowledge of this circuit -> fail open (see policy above).
        if not rl_valid:
            return self.failsafe_pct, f"sensor_fault:{circuit_sensor}"

        return proposed_pct, None
