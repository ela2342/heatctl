"""Return-temperature validity gating.

A closed circuit's RL sensor measures slab ambient, not loop water. Feeding
that number to a return-temperature PID is not merely inaccurate, it is
actively destabilising, and in the same direction in both modes:

  heating: valve closes -> RL drifts DOWN toward slab -> "too cold, needs
           heat" -> valve opens -> real RL appears, warm -> valve closes ...
  cooling: valve closes -> RL drifts UP toward slab   -> "too warm, needs
           cooling" -> valve opens -> real RL appears, cold -> valve closes ...

So the failure mode is a self-sustaining hunt on actuators that take minutes
per stroke. This matters more than it looks: every `room_temp_topic` that is
unset falls through to exactly this per-circuit path, so for most rooms it is
the *only* control path there is.

The rule implemented here: RL means something only after the valve has been
commanded meaningfully open for long enough that water has actually travelled
the loop. Otherwise the circuit is held, and re-measured periodically by
flushing. This is the minimal mitigation named in PLAN.md Milestone 1; the
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
protection, and slab ambient is a perfectly good frost indicator - arguably a
better one than loop water. Control proposes, safety decides, and safety keeps
seeing the raw measurement.
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
        # PROVISIONAL. The Alpha 5 deadband has not been measured yet
        # (docs/HARDWARE.md), so this is a conservative guess, not a fact.
        # Replace it with the measured opening threshold once the remaining
        # actuators are fitted and characterised.
        self.min_opening = float(g.get("min_opening_pct", 15.0))
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
