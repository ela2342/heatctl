"""Parameter loading with explicit uncertainty (D-032).

Every system parameter carries what it is worth knowing about it: a value, how
well it is known, where it came from, and what it was derived from. That last
field is the one most schemes omit and the one that matters most - see the
correlation note below.

**`Param` subclasses `float`**, deliberately. Existing code reads
`params["building"]["ua_ao"]` and gets a number; nothing had to change to adopt
this. New code reads `.sigma`, `.kind`, `.bounds`, `.derived_from` off the same
object. A parallel "uncertainties" block would have separated a number from its
error bar, which is how they drift apart.

`kind` says how much to trust it, and they are not interchangeable:

  specified   from a datasheet or manual. Usually carries hard BOUNDS rather
              than a sigma - a spec limit is not a 1-sigma error bar, and a
              Gaussian would put probability mass outside a physical maximum.
  measured    measured directly, on this installation.
  identified  inferred from operating data through a model. **These carry
              correlations** - see below.
  prior       a guess. Sigma expresses ignorance, not measurement error. Honest
              and useful for a filter, but must never be mistaken for evidence.

**Why `derived_from` exists.** On 2026-07-31 the flow was corrected 1.24 ->
1.44 m3/h, +16 %. `ua_sa` had been identified as `Q/(T_air - T_water)` with
`Q = m_dot_c * dT`, so it moved by exactly the same 16 %. In
`k = ua_sa / (m_dot_c - ua_sa/2)` that error cancels **exactly**, leaving the
constraint-optimal setpoint invariant (19.27 -> 19.26) while `Q_max`, which
carries a bare `m_dot_c`, scaled linearly with it (418 -> 485 W/K). Propagating
the two as independent would have overstated the uncertainty on one and
understated it on the other. A bare `sigma:` field cannot express that; a
dependency can.

The strongest form of this is not to annotate the correlation but to remove it:
store the RAW MEASUREMENT and compute the parameter (see `derived.py`). Then the
correlation is structural and cannot be forgotten. `ua_sa` is stored that way.
"""
from __future__ import annotations

from typing import Any

import yaml


class Param(float):
    """A number that remembers how well it is known and where it came from."""

    sigma: float | None
    unit: str | None
    kind: str
    bounds: tuple[float, float] | None
    derived_from: tuple[str, ...]
    note: str | None

    def __new__(cls, value: float, **kw: Any) -> "Param":
        self = super().__new__(cls, value)
        self.sigma = kw.get("sigma")
        self.unit = kw.get("unit")
        self.kind = kw.get("kind", "prior")
        b = kw.get("bounds")
        self.bounds = (float(b[0]), float(b[1])) if b else None
        self.derived_from = tuple(kw.get("derived_from") or ())
        self.note = kw.get("note")
        return self

    @property
    def relative_sigma(self) -> float | None:
        if self.sigma is None or self == 0.0:
            return None
        return abs(self.sigma / float(self))

    def __repr__(self) -> str:
        s = f"{float(self):g}"
        if self.sigma is not None:
            s += f"+-{self.sigma:g}"
        if self.unit:
            s += f" {self.unit}"
        return f"Param({s}, {self.kind})"


KINDS = {"specified", "measured", "identified", "prior"}


def _convert(node: Any, path: str = "") -> Any:
    """Recursively turn `{value: ...}` mappings into Params.

    Plain scalars are left alone, so migration can be partial and a file that
    has not been converted yet still loads. That is deliberate: a schema change
    that forces a big-bang rewrite of a safety-adjacent file is a schema change
    that gets rushed.
    """
    if isinstance(node, dict):
        if "value" in node and isinstance(node["value"], (int, float)):
            kind = node.get("kind", "prior")
            if kind not in KINDS:
                raise ValueError(f"{path}: unknown kind {kind!r}, expected one "
                                 f"of {sorted(KINDS)}")
            if node.get("sigma") is not None and node["sigma"] < 0:
                raise ValueError(f"{path}: negative sigma")
            b = node.get("bounds")
            if b is not None:
                if len(b) != 2 or b[0] > b[1]:
                    raise ValueError(f"{path}: bounds must be [lo, hi]")
                if not b[0] <= node["value"] <= b[1]:
                    raise ValueError(
                        f"{path}: value {node['value']} outside bounds {b}")
            return Param(node["value"], **{k: v for k, v in node.items()
                                           if k != "value"})
        return {k: _convert(v, f"{path}.{k}" if path else str(k))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_convert(v, f"{path}[{i}]") for i, v in enumerate(node)]
    return node


def load_params(path: str) -> dict:
    with open(path) as f:
        return _convert(yaml.safe_load(f))
