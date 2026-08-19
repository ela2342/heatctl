"""Return-temperature validity gating.

The sensors sit ON THE RETURN PIPE AT THE MANIFOLD, not in the slab. That
detail decides the whole failure mode, so it is worth being precise about
(corrected 2026-07-27; an earlier version of this file claimed slab ambient
and reasoned from it, wrongly).

With no flow through its circuit, such a sensor stops measuring that circuit
at all and equilibrates toward the manifold cabinet's ambient - which is
dominated by the flow and return headers running past it, i.e. it drifts
toward roughly the system water temperature.

That produces LOCK-OUT, not oscillation, and lock-out is the worse of the
two because it is silent:

    target = mixed system return (`return_setpoint_source: system_return`)
    stagnant sensor -> reads ~header temperature -> ~= the target
    -> error ~= 0 -> "nothing to do" -> the circuit stays shut forever

A closed circuit therefore manufactures its own evidence that it should stay
closed. This is the same phenomenon `system_return_bias_c` was added to paper
over - "all valves closed" being a valid equilibrium - seen from the sensor
side. With a fixed target instead of system-return tracking it can fall
either way depending on header temperature, but the stagnant reading is
fiction in both cases.

It matters more than it looks: every room whose `room_temp_topic` is unset
falls through to exactly this per-circuit path, so for most of the house it
is the *only* control path there is.

The consequence for the design below: the periodic FLUSH is the load-bearing
part, not the hold. Holding alone would preserve the lock-out.

The rule implemented here: RL means something only after the valve has been
commanded meaningfully open for long enough that water has actually travelled
the loop. Otherwise the circuit is held, and re-measured periodically by
flushing. This is the minimal mitigation named in ROADMAP.md Milestone 1; the
full scheduled flush-and-remeasure design is docs/DESIGN.md section 4.

Two deliberate choices:

* **No trustworthy RL and nothing held yet is treated as lost knowledge**, so
  the caller falls back to the fail-open position, exactly as it does for a
  faulted sensor (see `safety.py`). That also makes start-up self-healing
  without a special case: the circuit opens, water moves, RL becomes real,
  and normal control takes over. There is deliberately no forced flush at
  start-up - it would mean a multi-minute full-open on every single deploy.
* **Circuits with no actuator fitted are always trustworthy.** They are open
  pipe: flow does not follow the command, so gating on the command would be
  a fiction of its own. Config marks this per valve channel.

Safety is NOT gated by any of this. `Safety.apply` reads RL for frost
protection, and a manifold-ambient reading is still a real temperature from a
real place in the building - if it is near freezing, something is wrong and
opening is right. Control proposes, safety decides, and safety keeps seeing
the raw measurement.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("heatctl.rl")

MEASURE = "measure"   # RL is trustworthy: run the controller
FLUSH = "flush"       # force the circuit open to re-measure
HOLD = "hold"         # RL is fiction: keep the last known-good command


@dataclass
class _Circuit:
    open_since: float | None = None     # when it was first commanded open
    last_trusted: float | None = None   # last time RL was usable
    held: float | None = None           # last control output while trusted
    flushing: bool = False


class RLGate:
    def __init__(self, cfg: dict):
        g = dict(cfg["control"].get("rl_gating") or {})
        self.enabled = bool(g.get("enabled", True))
        # MUST NOT SIT BELOW `distribution.open_threshold_pct`, which is 20 %
        # since D-041 - the command at which water starts to move at all. It
        # was 15 while that threshold was believed to be the 5 % electrical
        # deadband, so the gate would have trusted the return sensor on a
        # circuit passing nothing, which is the exact D-009 lock-out it exists
        # to prevent. Still a guess above that bound: how much flow RL needs to
        # mean something is not measured.
        self.min_opening = float(g.get("min_opening_pct", 25.0))
        # Valve stroke PLUS hydraulic transport through the loop: water has to
        # travel the circuit before RL means anything (docs/DESIGN.md 4.1.5).
        self.settle_s = float(g.get("settle_s", 300.0))
        self.flush_interval_s = float(g.get("flush_interval_s", 3600.0))
        self.flush_pct = float(g.get("flush_pct", 100.0))

        # Circuits whose flow does not follow our command - see module docstring.
        self.unactuated = {c["name"] for c in cfg["valves"]["channels"]
                           if not c.get("fitted", True)}
        self._c: dict[str, _Circuit] = {}

    def _circuit(self, valve: str) -> _Circuit:
        return self._c.setdefault(valve, _Circuit())

    def action(self, valve: str, now: float) -> str:
        """What to do with this circuit this cycle.

        Not a pure query: it records when RL last became trustworthy, which is
        what the flush schedule is measured from.
        """
        if not self.enabled or valve in self.unactuated:
            return MEASURE
        c = self._circuit(valve)
        if c.open_since is not None and now - c.open_since >= self.settle_s:
            if c.flushing:
                log.info("%s: flush complete, RL trustworthy again", valve)
                c.flushing = False
            c.last_trusted = now
            return MEASURE
        if c.flushing:
            return FLUSH                       # keep it open until it settles
        if c.last_trusted is None:
            # Never had a usable reading. Not a flush: the caller falls back
            # to fail-open, which opens the circuit and produces one anyway.
            return HOLD
        if now - c.last_trusted >= self.flush_interval_s:
            log.info("%s: RL unusable for %.0f s, flushing to re-measure",
                     valve, now - c.last_trusted)
            c.flushing = True
            return FLUSH
        return HOLD

    def held(self, valve: str, default: float) -> float:
        """Last control output taken while RL was trustworthy, else `default`."""
        h = self._circuit(valve).held
        return default if h is None else h

    def note_control(self, valve: str, pct: float) -> None:
        """Remember a control output computed from a trustworthy RL."""
        self._circuit(valve).held = pct

    def record_command(self, valve: str, pct: float, now: float) -> None:
        """Record what was ACTUALLY written, after safety had its say.

        Safety overrides change real flow (frost forces open, overtemp forces
        closed), so gating on the pre-safety proposal would track a command
        the plant never received.
        """
        if not self.enabled or valve in self.unactuated:
            return
        c = self._circuit(valve)
        if pct >= self.min_opening:
            if c.open_since is None:
                c.open_since = now
        else:
            c.open_since = None
