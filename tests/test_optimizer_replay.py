"""The replay harness (optimizer/replay.py): DESIGN_ESTIMATION_PLANNING phase 2.

A synthetic house is simulated with the model itself and written out as a
journal. Replayed with the same parameters, the open-loop prediction must be
near exact. That proves the harness feeds the estimator what the journal
said, on journal time, with the inputs in the right slots. Each property
below is one that a plausible harness bug breaks.
"""
from __future__ import annotations

import gzip
import json
import math

import pytest

from optimizer.model import (N_INPUTS, U_GROUND, U_HEAT, U_INTERNAL,
                             U_OUTDOOR, U_SOLAR, BuildingParams, discretise)
from optimizer.params import Param
from optimizer.replay import apply_overrides, run, score

ROOM = "sensors/room/a/temperature_c"
T0 = 1_790_000_000 - (1_790_000_000 % 3600)      # on the hour
COP = 3.35


def _params(ua_ao: float = 267.2) -> dict:
    return {
        "building": {"ua_ao": ua_ao, "ua_sa": 568.0, "ua_sg": 29.0,
                     "c_air_wh": 6600.0, "c_slab_wh": 8691.0, "f_sol": 0.3,
                     "t_ground": 10.0, "q_internal_w": 350.0},
        "filter": {"q_air_k_per_h": 0.15, "q_slab_k_per_h": 0.4,
                   "r_air_k": 0.1, "p0_air_k": 0.1, "p0_slab_k": 0.1},
        "heat_input": {"assumed_cop": COP, "standby_w": 250.0},
        "weather": {"latitude": None, "longitude": None}}


CFG = {"mqtt": {"host": "127.0.0.1", "base_topic": "heatctl"},
       "rooms": [{"name": "a", "room_temp_topic": ROOM}],
       "safety": {"stale_data_timeout_s": 300}}


def _house(hours: int, gap: tuple[int, int] | None = None) -> list[str]:
    """Journal lines for a house simulated by the model it will be scored on.

    The day swings outdoor 4-14 degC with a midday sun. The compressor heats
    from 00:00-06:00 and COOLS from 12:00-16:00 at the same electrical power,
    so a harness or estimator that loses the sign of the heat input is
    visibly wrong, not subtly wrong.
    """
    b = _params()["building"]
    bp = BuildingParams(ua_ao=b["ua_ao"], ua_sa=b["ua_sa"], ua_sg=b["ua_sg"],
                        c_air_wh=b["c_air_wh"], c_slab_wh=b["c_slab_wh"],
                        f_sol=b["f_sol"])
    F, G = discretise(bp, 60.0)
    x = [22.0, 22.0]
    lines = []
    for m in range(hours * 60):
        t = T0 + m * 60
        hod = (m / 60.0) % 24.0
        outdoor = 9.0 - 5.0 * math.cos(2 * math.pi * (hod - 3.0) / 24.0)
        solar = max(0.0, 3000.0 * math.sin(math.pi * (hod - 7.0) / 10.0)) \
            if 7.0 <= hod <= 17.0 else 0.0
        if hod < 6.0:
            mode, power = "heating", 900.0
        elif 12.0 <= hod < 16.0:
            mode, power = "cooling", 900.0
        else:
            mode, power = ("heating" if hod < 12.0 else "cooling"), 0.0
        sign = 1.0 if mode == "heating" else -1.0
        skip = gap is not None and gap[0] * 60 <= m < gap[1] * 60
        lines.append(f"{t + 1}.5 {ROOM} {x[0]:.3f}")
        if not skip:
            lines.append(f"{t + 2}.0 heatctl/opt/state " + json.dumps(
                {"outdoor": outdoor, "q_solar_w": solar}))
        lines.append(f"{t + 3}.0 heatctl/hp/power_estimate {power}")
        lines.append(f"{t + 3}.5 heatctl/hp/mode_name {mode}")
        u = [0.0] * N_INPUTS
        u[U_OUTDOOR], u[U_SOLAR], u[U_INTERNAL] = outdoor, solar, 350.0
        u[U_HEAT] = sign * power * COP if power >= 250.0 else 0.0
        u[U_GROUND] = 10.0
        x = [sum(F[i][j] * x[j] for j in range(2))
             + sum(G[i][j] * u[j] for j in range(N_INPUTS)) for i in range(2)]
    return lines


def _journal(tmp_path, lines: list[str]) -> str:
    p = tmp_path / "mqtt-20261016.log.gz"
    with gzip.open(p, "wt") as f:
        f.write("garbage line\n")
        f.write("\n".join(lines) + "\n")
        f.write("17900 truncat")
    return str(p)


HOURS = 24


@pytest.fixture(scope="module")
def truth(tmp_path_factory):
    """The house replayed with its own parameters, shared: a replay costs a
    matrix exponential per minute, and three tests need the same one."""
    d = tmp_path_factory.mktemp("journal")
    path = _journal(d, _house(HOURS))
    return path, run(CFG, _params(), [path])


def test_the_true_model_predicts_its_own_house(truth):
    """The harness's baseline property. If this fails, the harness - not the
    model - is wrong: inputs in the wrong slot, journal time not reaching
    the staleness checks, or the heat input's sign lost on the way in.
    Mutation-verified: making `heat_input_w` mode-blind again takes the
    6 h error from ~0 to well over a kelvin."""
    _, rp = truth
    assert len(rp.rows) > (HOURS - 1) * 60
    s = score(rp.rows, rp.est.bp, horizons=(3, 6), warmup_h=6.0)
    for h in (3, 6):
        assert s[h]["n"] >= 10
        assert s[h]["rmse"] < 0.05, s[h]
        assert s[h]["skill"] > 0.9, s[h]


def test_a_wrong_parameter_scores_worse(truth):
    """The point of the harness is to rank parameter sets. One off by a
    fifth must score measurably worse than the truth on the same data,
    or `--set` experiments are meaningless."""
    path, good = truth
    bad = run(CFG, _params(ua_ao=267.2 * 1.25), [path])
    sg = score(good.rows, good.est.bp, horizons=(6,), warmup_h=6.0)[6]
    sb = score(bad.rows, bad.est.bp, horizons=(6,), warmup_h=6.0)[6]
    assert sb["rmse"] > 5 * sg["rmse"]
    assert sb["rmse"] > 0.1


def test_a_start_that_runs_into_a_gap_is_dropped_not_bridged(truth, tmp_path):
    """With the optimizer down there is no outdoor figure, `step()` skips,
    and the replay has a hole. Propagating across it would silently score
    the model on inputs nobody recorded. Starts that need the hole are
    dropped, and the ones that do not are still scored."""
    _, full = truth
    holed = run(CFG, _params(), [_journal(tmp_path, _house(HOURS, gap=(12, 14)))])
    sf = score(full.rows, full.est.bp, horizons=(3,), warmup_h=6.0)[3]
    sh = score(holed.rows, holed.est.bp, horizons=(3,), warmup_h=6.0)[3]
    # Five starts need the hole: 10:00-14:00, each with a 3 h horizon that
    # touches 12:15-14:00. A harness that bridges keeps one of them and
    # scores it at ~0.05 K on inputs it made up.
    assert sh["n"] == sf["n"] - 5
    assert sh["rmse"] < 0.02


def test_overrides_are_marked_and_typos_rejected():
    """A misspelt `--set` must not quietly run the baseline and report it as
    the experiment."""
    p = _params()
    apply_overrides(p, ["building.ua_ao=216"])
    assert float(p["building"]["ua_ao"]) == 216.0
    assert isinstance(p["building"]["ua_ao"], Param)
    assert p["building"]["ua_ao"].note == "replay override"
    with pytest.raises(KeyError):
        apply_overrides(p, ["building.ua_oa=216"])
    with pytest.raises(ValueError):
        apply_overrides(p, ["building.ua_ao"])


def test_time_skipped_without_inputs_is_still_predicted_across(monkeypatch):
    """Until 2026-10-19 `Estimator.step` dropped the caller's dt whenever it
    skipped for want of an outdoor figure, so after an outage the filter
    predicted 60 s across a gap of hours. Found by the gap test above,
    which failed (0.08 K after the hole) before the fix."""
    import optimizer.estimator as est_mod
    from optimizer.estimator import Estimator, Reading
    seen: list[float] = []
    real = est_mod.discretise

    def spy(bp, dt_s):
        seen.append(dt_s)
        return real(bp, dt_s)

    monkeypatch.setattr(est_mod, "discretise", spy)
    est = Estimator(CFG, _params())
    now = [1000.0]
    est.clock = lambda: now[0]
    outdoor: list[float | None] = [8.0]
    est.outdoor_c = lambda: outdoor[0]
    est.readings[ROOM] = Reading(22.0, now[0])
    assert est.step(60.0) is not None
    outdoor[0] = None
    for _ in range(10):
        assert est.step(60.0) is None
    outdoor[0] = 8.0
    assert est.step(60.0) is not None
    assert seen == [60.0, 660.0]
