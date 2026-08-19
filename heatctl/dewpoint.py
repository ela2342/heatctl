"""Dew point from air temperature and relative humidity.

Pure arithmetic, no I/O, so the one number the whole condensation defence rests
on can be tested directly.

**Why this exists as heatctl code at all.** Until 2026-08 the dew point was
computed by a Home Assistant template helper and republished onto
`heatctl/env/dew_point`. That worked, and it put the *only* computation in the
safety path on a machine heatctl is explicitly designed to survive without
(D-001) - and after D-035 the condensation limit has exactly one enforcer, so
the input to it should not depend on HA being up. It also lived in three
hand-maintained copies of the same room list, which is how the 2026-08-10
incident happened: the reference was still listing two rooms after five were
instrumented, read 12.0 while Bad's dew point was 17.3, and the first symptom
was water on the floor.

Once every room's humidity arrives on a topic heatctl already subscribes to,
computing it here removes both problems at once.

**Magnus-Tetens**, the same coefficients the HA helper used, so the changeover
is not also a change of number:

    gamma = ln(RH/100) + a*T/(b+T)
    Td    = b*gamma / (a - gamma)          a = 17.625, b = 243.04 degC

Accurate to about 0.1 K over 0..60 degC, which is well inside the 1.0 K
`safety.dew_point_margin_c` and far inside the RH sensors' own error - 3 % RH
is roughly 0.5 K of dew point, and that is the dominant term (see BACKLOG on
sizing the margin).
"""
from __future__ import annotations

import math

A = 17.625
B = 243.04

# Rejection bounds. These are not tuning: they are the range in which the
# formula and the sensors both mean something. Outside it the reading is not a
# dew point that happens to be extreme, it is a fault - a disconnected RH
# channel reads 0 %, a shorted one reads 100 %, and log(0) is undefined.
RH_MIN_PCT = 1.0
RH_MAX_PCT = 100.0
TEMP_MIN_C = -40.0
TEMP_MAX_C = 60.0


def dew_point_c(temp_c: float | None, rh_pct: float | None) -> float | None:
    """Dew point in degC, or None if the inputs cannot support one.

    None means "no knowledge", and every caller must treat it as such rather
    than as a low dew point - in cooling, a missing dew point stops the
    compressor (D-010), it does not license colder water.
    """
    if temp_c is None or rh_pct is None:
        return None
    if not (TEMP_MIN_C <= temp_c <= TEMP_MAX_C):
        return None
    if not (RH_MIN_PCT <= rh_pct <= RH_MAX_PCT):
        return None
    gamma = math.log(rh_pct / 100.0) + (A * temp_c) / (B + temp_c)
    return B * gamma / (A - gamma)


def house_dew_point(pairs: dict[str, tuple[float | None, float | None]],
                    ) -> tuple[float | None, str | None, int]:
    """The HIGHEST dew point across rooms, which room set it, and how many
    rooms contributed.

    The maximum, not the mean: one supply temperature serves every circuit, so
    the wettest room is the one that decides what is safe. Averaging would
    protect the average room and condense in the worst one.

    The COUNT is returned because it is the only thing that makes a silent
    failure visible. A dew point is a plausible number whatever the room count,
    so the value alone can never show that rooms have dropped out - which is
    exactly how 2026-08-10 went unnoticed. Publish it and watch it.
    """
    best: float | None = None
    room: str | None = None
    n = 0
    for name in sorted(pairs):
        t, rh = pairs[name]
        d = dew_point_c(t, rh)
        if d is None:
            continue
        n += 1
        if best is None or d > best:
            best, room = d, name
    return best, room, n
