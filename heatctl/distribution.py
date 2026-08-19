"""Valve distribution: maximise flow, preserve the ratios between rooms.

The objective, stated by the owner 2026-07-27, is not "avoid starving the
pump". It is:

    maximise overall flow -> minimise the leaving/return spread ->
    the water can sit closer to room temperature for the same duty ->
    better COP

Throttling a valve is therefore a *cost*, paid only to distribute energy
between rooms that need different amounts. It is never something to do for its
own sake, and the pump's minimum-flow requirement stops being a constraint we
defend and becomes a side effect of doing the right thing anyway.

So the rule is: **scale the whole set of demands so the most-demanding circuit
is fully open.** Ratios between rooms are preserved - that is the distribution
- while the absolute amount of energy delivered stays governed by the water
temperature, not by valve position.

    cmd_i = (d_i + eps) / (max(d) + eps)

The naive form, `d_i / max(d)`, has two failures that this fixes together:

  * **0/0 at equilibrium.** With every room satisfied, max(d) is 0 and the
    scale factor is undefined. Here the expression tends to eps/eps = 1 for
    every circuit, so it approaches ALL VALVES FULLY OPEN continuously - which
    is also the correct answer physically: with nothing to distribute there is
    no reason to throttle anything, and maximum flow is what we want.
  * **Noise amplification at low demand.** Demands of [0.001, 0.0005] normalise
    to [100, 50] under the naive form - the ratio is preserved but it is a
    ratio of noise. The eps term makes the discrimination fade out smoothly as
    demand falls.

**eps is a real engineering knob, not a fudge factor.** It is the demand scale
below which we stop trying to tell rooms apart. Larger eps -> flatter
distribution -> more valves open wider -> more flow and better COP, at the cost
of less per-room discrimination. Smaller eps -> sharper distribution, less
flow. It trades comfort precision against efficiency.

NOT handled here, deliberately:
  * Safety. This produces a control proposal; `Safety.apply` runs after it and
    may still close a circuit. If safety closes enough of them that flow is
    genuinely lost, the escalation is the source-side last resort, not
    reopening valves into a known-bad supply.
  * The effective range. `open_threshold_pct`/`full_open_pct` map the result
    onto the commands that actually move water - 20 to 50 % since D-041, which
    also lists what else is keyed to those two. "Normalise to fully open"
    means `full_open_pct`, not the number 100.
"""
from __future__ import annotations

import logging

log = logging.getLogger("heatctl.dist")


class Distributor:
    def __init__(self, cfg: dict):
        d = dict(cfg["control"].get("distribution") or {})
        self.enabled = bool(d.get("enabled", True))
        # Demand scale below which rooms stop being told apart. See the module
        # docstring - this is the flow/discrimination trade-off.
        self.eps = float(d.get("eps", 5.0))
        # Actuator effective range. Identity until measured.
        self.open_threshold_pct = float(d.get("open_threshold_pct", 0.0))
        self.full_open_pct = float(d.get("full_open_pct", 100.0))
        # Rate limit on the REFERENCE PEAK, in percent per cycle. The circuits
        # are coupled by normalisation - a change in the most-demanding room
        # rescales every other one - so a step in one circuit's demand would
        # otherwise re-throttle the whole house at once, against actuators that
        # take minutes to move. Limiting the peak keeps the units meaningful
        # (percent of demand) instead of rate-limiting an abstract gain.
        self.max_peak_step = float(d.get("max_peak_step_per_cycle", 2.0))
        self._peak: float | None = None

    def apply(self, demands: dict[str, float]) -> dict[str, float]:
        """Demands (0..100, as the PIDs produce them) -> commanded positions.

        cmd_i = open_threshold + (d_i + eps)/(peak + eps) * (full_open - open_threshold)
        """
        if not self.enabled or not demands:
            return dict(demands)

        target_peak = max(demands.values())
        if self._peak is None:
            self._peak = target_peak
        else:
            step = max(-self.max_peak_step,
                       min(self.max_peak_step, target_peak - self._peak))
            self._peak += step
        peak = self._peak

        span = self.full_open_pct - self.open_threshold_pct
        out = {}
        for name, d in demands.items():
            frac = min(1.0, max(0.0, (d + self.eps) / (peak + self.eps)))
            out[name] = round(self.open_threshold_pct + frac * span, 1)
        return out
