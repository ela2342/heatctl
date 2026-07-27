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
correct through the whole build-out with no special cases - today the average
sits near 79 % because seven of nine circuits are open pipe, so no stall is
possible, and the figure falls naturally as actuators are fitted.

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
        # Shadow by default: compute and publish, let nothing act on it. The
        # heat pump has another writer until WP-B, and this logic has to be
        # watched against the plant before it owns anything.
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

        # Engage the source once the house is at least this far off target.
        self.engage_deviation_c = float(d.get("engage_deviation_c", 0.3))
        # Pump minimum flow, as mean opening across all circuits. 40 % is the
        # owner's measured figure - below it the system runs into trouble and
        # eventually the pump's own Er03 water-flow failsafe.
        self.min_open_pct = float(d.get("min_open_pct", 40.0))
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

        self._source_on = False
        self._since = 0.0            # when source_request last changed
        self._mode_candidate: str | None = None
        self._candidate_since = 0.0

    # ---------- flow ----------

    def open_pct(self, valves_pct: dict[str, float]) -> float | None:
        """Mean opening across all water-carrying circuits, 0..100.

        Unactuated circuits count as 100: they are open pipe. This is a flow
        PROXY, not a measurement - there is no flow meter. It is the same
        quantity the owner's 40 % rule of thumb refers to.
        """
        vals = []
        for name in self.circuit_valves:
            if name in self.unactuated:
                vals.append(100.0)
            elif name in valves_pct:
                vals.append(valves_pct[name])
        return sum(vals) / len(vals) if vals else None

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

    def _pick_mode(self, current: str, dev: float | None, now: float) -> str:
        """Mode from the house average, with a deadband and a dwell time."""
        if not self.auto_mode or dev is None:
            return current
        if dev > self.mode_deadband_c:
            want = "heating"
        elif dev < -self.mode_deadband_c:
            want = "cooling"
        else:
            self._mode_candidate = None
            return current
        if want == current:
            self._mode_candidate = None
            return current
        # Require the condition to persist. Switching the whole plant on a
        # transient average is expensive and slow to undo.
        if self._mode_candidate != want:
            self._mode_candidate = want
            self._candidate_since = now
            return current
        if now - self._candidate_since < self.mode_dwell_s:
            return current
        log.info("mode -> %s (house average %+.2f K for %.0f s)",
                 want, dev, now - self._candidate_since)
        self._mode_candidate = None
        return want

    def step(self, mode: str, setpoints: dict[str, float],
             room_temps: dict[str, float], valves_pct: dict[str, float],
             now: float) -> Demand:
        dev, n = self.mean_deviation(setpoints, room_temps)
        open_pct = self.open_pct(valves_pct)
        mode = self._pick_mode(mode, dev, now)

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
