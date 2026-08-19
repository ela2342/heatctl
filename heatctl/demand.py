"""House demand, plant mode, and source engagement.

Owner's design decision, 2026-07-27 (docs/DESIGN.md 4.3): deciding whether to
run the source and guaranteeing the pump has flow are ONE problem, not two
interlocks that can disagree.

    aggregate per-room deviation  ->  signed house demand
    too cold on average -> heating,  too warm on average -> cooling
    engage the source only when that demand is large enough that the resulting
    valve openings keep flow above the pump's minimum; below that, run nothing

Three things here are deliberate and easy to get wrong:

**Demand comes from ROOM deviation, never from valve position.** Valves also
close for safety reasons - dew point, screed overtemp - which say nothing about
whether the house wants heat. Gating the source on valve openings would read a
condensation closure as "no demand", stop the source, and prevent the supply
from ever recovering. That is the same latch-up that took cooling out of
service on 2026-07-26; do not reintroduce it by "simplifying" the input.

**Flow is averaged over ALL circuits, counting unactuated ones as fully open.**
That is the physically meaningful number: a circuit with no actuator is open
pipe and passes water regardless of what we command. It also makes the rule
correct through the whole build-out with no special cases.

Which circuits are actuated is in `config.yaml` (`fitted`), and what a
commanded percentage is worth in litres is in `docs/FLOW_CHARACTERISATION.md`.
Neither belongs in this docstring.

**The source stays on; valves apportion.** Corrected 2026-07-27 (owner).
Powering the unit down is a last resort, not a control action: the heat pump
starts and stops its own compressor and modulates its power from the
leaving/return spread.

The steady state of this plant is: pump running, compressor doing as much as it
needs, and **every valve open to a degree that distributes the supplied energy
to the rooms according to their need**. Not "all valves wide open", and not
valves cycling shut - open to *proportions*. The water temperature sets how
much energy there is; the valves decide how it is shared. So heatctl modulates
the total by WATER TEMPERATURE (setpoint.py) and shares it out with the
valves.

That makes `min_open_pct` a constraint on how far heatctl may throttle - a
reason to hold valves OPEN - and never a reason to stop the source. Stopping on
low flow would also have been circular, since the valves are heatctl's own
output: it would have been switching the plant off in response to its own
decision.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("heatctl.demand")


@dataclass
class Demand:
    """What the plant should be doing this cycle."""
    mode: str                      # heating | cooling | off
    source_request: bool           # should the circulation pump run
    park_valves_open: bool         # source idle -> hold flow available
    mean_deviation_c: float | None  # + = too cold, - = too warm
    rooms_used: int
    open_pct: float | None         # flow proxy: mean opening over all circuits
    reason: str                    # why the source is / is not engaged


class DemandController:
    def __init__(self, cfg: dict, can_command_source_mode: bool = False):
        d = dict(cfg["control"].get("source_demand") or {})
        # `enabled` gates ACTING on source_request (holding the unit
        # powered). Off means compute and publish only, which is how this was
        # first run against the plant before it owned anything.
        # TWO independent switches, deliberately:
        #   enabled   - act on source_request, i.e. run or stop the plant
        #   auto_mode - pick WHICH mode (heating vs cooling) from the house
        # Conflating them would mean you cannot have heatctl choose the season
        # without also handing it the on/off decision.
        self.enabled = bool(d.get("enabled", False))
        self.auto_mode = bool(d.get("auto_mode", False))

        # Whether heatctl can make the HEAT PUMP follow its plant mode - i.e.
        # write register 0x0004. Passed in rather than assumed, because
        # switching heatctl's own mode while the pump stays put is worse than
        # not switching at all: the valve loop would drive the wrong direction
        # with the wrong water.
        self.can_command_source_mode = bool(can_command_source_mode)
        if self.auto_mode and not self.can_command_source_mode:
            log.error("source_demand.auto_mode requested, but heatctl cannot "
                      "command the heat pump's mode - needs heatpump.enabled "
                      "and heatpump.allow_writes. Refusing; mode stays manual.")
            self.auto_mode = False

        # Plant-level mode hysteresis. Rooms keep a single target each
        # (owner's decision); this deadband is NOT a per-room one. Without it
        # the plant flaps between heating and cooling around the average.
        self.mode_deadband_c = float(d.get("mode_deadband_c", 1.0))
        self.mode_dwell_s = float(d.get("mode_dwell_s", 3600.0))
        # ENERGY BASIS for the mode decision, in kelvin of whole slab. See
        # `_pick_mode`. Kelvin rather than Wh because Wh is unreadable and does
        # not survive a change of floor area.
        self.mode_deadband_slab_k = float(d.get("mode_deadband_slab_k", 0.5))

        # Engage the source once the house is at least this far off target.
        self.engage_deviation_c = float(d.get("engage_deviation_c", 0.3))
        # Pump minimum flow, as mean opening across all circuits. 40 % is the
        # owner's measured figure - below it the system runs into trouble and
        # eventually the pump's own Er03 water-flow failsafe.
        self.min_open_pct = float(d.get("min_open_pct", 40.0))
        # THE COMMAND AT WHICH A CIRCUIT IS ALREADY PASSING ALL THE WATER IT
        # WILL PASS. Read from the distribution block because it is the same
        # physical fact, and the floor is meaningless without it: this loop
        # credits opening as if it bought flow, so crediting anything above
        # saturation is fictitious flow, in the one calculation whose whole job
        # is to stay clear of Er03. See D-041.
        self.flow_full_open_pct = float(
            (cfg["control"].get("distribution") or {}).get("full_open_pct", 100.0))
        # Anti-short-cycle. The compressor already cycles ~10 min on / ~9 min
        # off unaided; this must not make that worse.
        self.min_on_s = float(d.get("min_on_s", 600.0))
        self.min_off_s = float(d.get("min_off_s", 600.0))

        # Circuits whose flow does not follow our command: open pipe, always
        # fully open for flow purposes.
        self.unactuated = {c["name"] for c in cfg["valves"]["channels"]
                           if not c.get("fitted", True)}
        # Only channels actually assigned to a circuit carry water.
        self.circuit_valves = [circ["valve"] for room in cfg["rooms"]
                               for circ in room["circuits"] if circ.get("valve")]
        # How many rooms can contribute to the house average at all. Gates the
        # start-up one-shot in `_pick_mode`; a room with no topic never reports
        # and must not hold the decision hostage.
        self.expected_rooms = sum(1 for room in cfg["rooms"]
                                  if room.get("room_temp_topic"))

        self._source_on = False
        self._since = 0.0            # when source_request last changed
        self._mode_candidate: str | None = None
        self._candidate_since = 0.0
        # One-shot: the first auto_mode decision after a start skips the dwell.
        # See `_pick_mode`. Not persisted - restart == safe state, and here
        # that means re-deriving the mode from measurement rather than
        # inheriting a config guess.
        self._mode_decided = False

    # ---------- flow ----------

    def open_pct(self, valves_pct: dict[str, float]) -> float | None:
        """Mean opening across all water-carrying circuits, 0..100.

        Unactuated circuits count as `flow_full_open_pct`, not 100: they are
        open pipe, which passes the same water a saturated actuated circuit
        does. Crediting them 100 on a scale where 50 is already full flow would
        make the proxy read high exactly where it is used to prevent Er03.
        This is a flow PROXY, not a measurement - there is no flow meter.
        """
        vals = []
        for name in self.circuit_valves:
            if name in self.unactuated:
                vals.append(self.flow_full_open_pct)
            elif name in valves_pct:
                vals.append(valves_pct[name])
        return sum(vals) / len(vals) if vals else None

    def enforce_flow_floor(self, commanded: dict[str, float]
                           ) -> tuple[dict[str, float], float | None]:
        """Raise valve openings until the flow proxy clears `min_open_pct`.

        Returns (adjusted, raised_to) where `raised_to` is None if nothing was
        needed - so the caller can report that this fired without recomputing.

        WHY THIS EXISTS. The heat pump has a hard minimum water flow (0.16 l/s
        for the BLP08P1V1MR32) enforced by its own flow switch: below it the
        unit throws **Er03 and stops**. The owner shut every valve but circuit
        11 on 2026-07-28 and tripped it instantly. Without this, heatctl can
        do the same to itself - distribution is free to drive every circuit
        down to `distribution.open_threshold_pct` (5 %), far under the floor,
        and the plant would fault out in the hour the house most needs it.

        It has never been reachable so far only because 8 of the 10
        water-carrying circuits are open pipe and count as 100 %, pinning the
        mean at >= 80 %. **It becomes reachable the moment the remaining
        actuators are fitted**, which is why this is here before they are.

        DIRECTION IS THE WHOLE POINT: too little flow is a reason to OPEN
        valves, never to close them. A version of this that throttled instead
        would be strictly worse than having nothing, so `test_demand.py`
        asserts the direction rather than merely asserting that something
        changed.

        Openings are scaled by ONE COMMON FACTOR, so relative proportions are
        preserved - this is D-017's normalisation applied at the bottom end
        instead of the top. Circuits that hit 100 % are clipped and their
        shortfall is redistributed across the rest, which is the only place
        proportionality genuinely cannot be kept.

        Unactuated circuits are left alone: they are open pipe, so commanding
        them changes no flow. Only actuated circuits can help.
        """
        if not self.circuit_valves:
            return commanded, None
        actuated = [v for v in self.circuit_valves
                    if v not in self.unactuated and v in commanded]
        n_total = len([v for v in self.circuit_valves
                       if v in self.unactuated or v in commanded])
        if not actuated or not n_total:
            return commanded, None

        n_unact = len([v for v in self.circuit_valves if v in self.unactuated])
        # Sum of actuated openings needed for the mean to reach the floor.
        need = (self.min_open_pct * n_total
                - self.flow_full_open_pct * n_unact)
        have = sum(commanded[v] for v in actuated)
        if need <= have:
            return commanded, None

        out = dict(commanded)
        if need >= self.flow_full_open_pct * len(actuated):
            # Even wide open cannot make the floor. Open everything and let
            # the source-side handle it - see BACKLOG. Still the right
            # direction, and the most flow we can offer.
            for v in actuated:
                out[v] = self.flow_full_open_pct
            log.warning("flow floor %.0f%% unreachable: all %d actuated "
                        "circuits forced open", self.min_open_pct, len(actuated))
            return out, self.open_pct(out)

        free = list(actuated)
        while free:
            have_free = sum(out[v] for v in free)
            if have_free <= 0.0:
                # Nothing to scale - distribute the requirement evenly.
                for v in free:
                    out[v] = need / len(free)
                break
            k = need / have_free
            clipped = [v for v in free
                       if out[v] * k > self.flow_full_open_pct]
            if not clipped:
                for v in free:
                    out[v] = out[v] * k
                break
            for v in clipped:
                out[v] = self.flow_full_open_pct
                need -= self.flow_full_open_pct
                free.remove(v)
        return out, self.open_pct(out)

    # ---------- demand ----------

    def mean_deviation(self, setpoints: dict[str, float],
                       room_temps: dict[str, float]) -> tuple[float | None, int]:
        """Signed house demand: positive = too cold, negative = too warm.

        Only rooms with a fresh air temperature contribute. Today that is
        three of seven, which is a real limitation on how well this represents
        "the house" - noted rather than hidden.
        """
        devs = [setpoints[r] - t for r, t in room_temps.items() if r in setpoints]
        if not devs:
            return None, 0
        return sum(devs) / len(devs), len(devs)

    def _mode_wanted(self, dev: float | None, excess_wh: float | None,
                     capacity_wh: float | None) -> tuple[str | None, str]:
        """Which mode the house wants, and on what basis.

        **ENERGY FIRST (D-046).** Mean temperature deviation is the wrong
        statistic for this decision, and the reason is arithmetic: kelvins do
        not add across rooms and watt-hours do. An unweighted mean lets one
        small room outvote the rest of the house, and on 2026-08-19 it did -
        Elternschlafzimmer alone contributed -4.6 K of a -6.5 K total, so the
        plant cooled three rooms that wanted warming.

        The slab excess is additive and physical: room size, solar gain and
        thermal mass all carry their true weight with no weighting scheme to
        argue about. Measured the same evening, the two bases DISAGREED IN
        SIGN - mean deviation said cool, the energy balance said the house was
        10 kWh short, i.e. heat.

        Expressed in kelvin of whole slab so the deadband is readable.

        Falls back to the deviation when the energy model cannot answer -
        every room unestimable, a missing outdoor temperature. That is a real
        state (`energy_shadow_blind`), and losing mode selection entirely
        would be worse than using the cruder statistic.
        """
        if excess_wh is not None and capacity_wh:
            slab_k = excess_wh / capacity_wh
            if slab_k > self.mode_deadband_slab_k:
                return "cooling", f"slab {slab_k:+.2f} K"
            if slab_k < -self.mode_deadband_slab_k:
                return "heating", f"slab {slab_k:+.2f} K"
            return None, f"slab {slab_k:+.2f} K in band"
        if dev is None:
            return None, "no basis"
        if dev > self.mode_deadband_c:
            return "heating", f"house {dev:+.2f} K (no energy model)"
        if dev < -self.mode_deadband_c:
            return "cooling", f"house {dev:+.2f} K (no energy model)"
        return None, f"house {dev:+.2f} K in band (no energy model)"

    def _pick_mode(self, current: str, dev: float | None, now: float,
                   rooms_used: int = 0, excess_wh: float | None = None,
                   capacity_wh: float | None = None) -> str:
        """Mode from the house average, with a deadband and a dwell time.

        **The dwell does not apply to the first decision after a start**
        (owner, 2026-08-19: "auto mode should fire on startup, not wait for an
        hour for correction"). The dwell protects a mode the plant is already
        running from a transient average. At start-up there is no such mode -
        `current` is whatever `control.mode` happens to say, a seed rather than
        a decision - so an hour of dwell buys nothing and costs an hour of
        running the wrong way. Measured 2026-08-19: a rebuild at 18:51 came up
        heating with the house 1.6 K too warm and would have idled until 19:52.

        ARMED ONLY ON A COMPLETE ROOM SET. `rooms_used` must cover every room
        with a `room_temp_topic`, because room temperatures arrive over the
        first seconds and a partial average is not the house: Elternschlafzimmer
        alone reads -5.8 K against its 19.0 target and would flip the plant on
        its own. If a sensor is dead the one-shot never arms and the dwell
        applies as before - the safe degradation, and a visible one, since the
        normal path logs its own decision.
        """
        if not self.auto_mode or dev is None:
            return current
        if current == "off":
            # OFF IS NOT A SEASON, it is an operator stopping the plant, and
            # auto_mode does not get to overrule it. The dwell path could
            # already do this after an hour; the start-up one-shot would have
            # done it within seconds of every restart, which is what made the
            # hole obvious. Caught by
            # `test_mode_off_is_the_one_thing_that_stops_the_source`.
            return current
        # Every configured room has reported, so the average means something.
        complete = self.expected_rooms > 0 and rooms_used >= self.expected_rooms
        want, basis = self._mode_wanted(dev, excess_wh, capacity_wh)
        if want is None:
            self._mode_candidate = None
            # A full reading inside the band IS a decision: the seed mode is
            # fine. Spend the one-shot, so a later drift out of band is
            # treated as the in-operation transient it is.
            self._mode_decided = self._mode_decided or complete
            return current
        if want == current:
            self._mode_candidate = None
            self._mode_decided = self._mode_decided or complete
            return current
        if not self._mode_decided and complete:
            self._mode_decided = True
            self._mode_candidate = None
            log.warning("mode -> %s at start-up (%s, %d rooms, no dwell - the "
                        "mode it replaces was a config default, not a "
                        "decision)", want, basis, rooms_used)
            return want
        # Require the condition to persist. Switching the whole plant on a
        # transient average is expensive and slow to undo.
        if self._mode_candidate != want:
            self._mode_candidate = want
            self._candidate_since = now
            return current
        if now - self._candidate_since < self.mode_dwell_s:
            return current
        log.info("mode -> %s (%s for %.0f s)",
                 want, basis, now - self._candidate_since)
        self._mode_candidate = None
        return want

    def step(self, mode: str, setpoints: dict[str, float],
             room_temps: dict[str, float], valves_pct: dict[str, float],
             now: float, excess_wh: float | None = None,
             capacity_wh: float | None = None) -> Demand:
        dev, n = self.mean_deviation(setpoints, room_temps)
        open_pct = self.open_pct(valves_pct)
        mode = self._pick_mode(mode, dev, now, rooms_used=n,
                               excess_wh=excess_wh,
                               capacity_wh=capacity_wh)

        want, reason = self._want_source(mode, dev, open_pct)

        # Minimum on/off times, applied last so they can only ever damp the
        # decision, never invent one.
        if want != self._source_on:
            elapsed = now - self._since
            hold = self.min_on_s if self._source_on else self.min_off_s
            if self._since and elapsed < hold:
                want, reason = self._source_on, f"{reason} (held {hold - elapsed:.0f}s)"
        if want != self._source_on:
            log.info("source %s: %s", "ON" if want else "OFF", reason)
            self._source_on = want
            self._since = now

        return Demand(mode=mode, source_request=self._source_on,
                      park_valves_open=not self._source_on,
                      mean_deviation_c=dev, rooms_used=n,
                      open_pct=open_pct, reason=reason)

    def _want_source(self, mode: str, dev: float | None,
                     open_pct: float | None) -> tuple[bool, str]:
        """Should the unit be powered at all.

        CORRECTED 2026-07-27 (owner). Powering the unit down is a measure of
        LAST RESORT, not a control action. The heat pump regulates itself: it
        starts and stops its own compressor and varies its power from the
        spread between leaving and return water. Steady state for this plant
        is pump running, compressor doing as much as it needs, and **every
        valve open to a degree proportional to its room's need** - not all
        valves wide open, and not valves cycling shut.

        So heatctl modulates by WATER TEMPERATURE (setpoint.py) and uses the
        valves for per-room trim around that. It does not switch the source on
        and off to track demand.

        The previous version of this method got that backwards twice: it
        stopped the source when the house was satisfied, and stopped it again
        when the mean valve opening fell below the pump's flow minimum. Both
        are wrong.
          * "Satisfied" is the unit's own business - it will idle its
            compressor and cost almost nothing, whereas power cycling a heat
            pump is expensive and slow.
          * Low flow is a reason to OPEN VALVES, not to stop the source. The
            floor is a constraint on how far heatctl may throttle, not a
            shutdown trigger. Stopping on low flow was also circular: the
            valves are heatctl's own output, so it would have been switching
            the plant off in response to its own decision.
        """
        if mode == "off":
            return False, "mode_off"
        if dev is None:
            return True, "no_room_data"
        if open_pct is not None:
            return True, f"running, flow {open_pct:.0f}%"
        return True, "running"
