"""The per-room model, filter and replay (optimizer/house.py,
optimizer/replay_rooms.py): DESIGN_ESTIMATION_PLANNING phase 2, filter v2.

Each test is a property a plausible defect breaks: a coupling that makes or
destroys heat, a fan-coil room whose heat lands in a slab it does not have,
a sign lost between supply and return, a harness that feeds the model the
wrong slot.
"""
from __future__ import annotations

import gzip
import json
import math

import pytest

from optimizer.house import (HouseFilter, HouseModel, Room, build_couplings,
                             build_rooms, circuit_flow_kg_s, circuit_heat_w)
from optimizer.model import BuildingParams, discretise
from optimizer.params import Param
from optimizer.replay_rooms import run, score

WH = 3600.0


def _room(name, slab=True, ua_ao=50.0, ua_sa=100.0, c_air=1000.0,
          c_slab=1500.0, area=10.0, topic=None):
    return Room(name=name, area_m2=area, slab=slab, ua_ao=ua_ao,
                ua_sa=ua_sa if slab else 0.0, ua_sg=5.0 if slab else 0.0,
                c_air=c_air * WH, c_slab=c_slab * WH if slab else 0.0,
                q_int=0.0, temp_topic=topic)


def test_one_room_is_the_whole_house_model():
    """With one room and no coupling the per-room model must BE model.py's
    2-state model. If the matrices differ, one of them has a term in the
    wrong place, and the replay baselines are no longer comparable."""
    bp = BuildingParams(ua_ao=267.2, ua_sa=568.0, ua_sg=29.0, c_air_wh=6600.0,
                        c_slab_wh=8691.0, f_sol=0.3)
    r = Room("h", 100.0, True, 267.2, 568.0, 29.0, 6600.0 * WH, 8691.0 * WH,
             0.0, None)
    m = HouseModel([r], 0.3)
    F, G = m.discretise(600.0)
    F0, G0 = discretise(bp, 600.0)
    for i in range(2):
        for j in range(2):
            assert F[i][j] == pytest.approx(F0[i][j], rel=1e-9)
    # model.py inputs: outdoor, solar, internal, heat, ground.
    from optimizer.model import U_GROUND, U_HEAT, U_OUTDOOR, U_SOLAR
    for mine, theirs in ((m.U_OUT, U_OUTDOOR), (m.U_GROUND, U_GROUND),
                         (m.u_sol["h"], U_SOLAR), (m.u_heat["h"], U_HEAT)):
        for i in range(2):
            assert G[i][mine] == pytest.approx(G0[i][theirs], rel=1e-9)


def test_coupling_moves_heat_and_never_makes_it():
    """Two sealed rooms (no envelope, no slab, no ground) exchanging through
    a wall: total heat content is constant and the warm room cools. A
    one-sided coupling term - added to one room's balance and not the
    other's - would make or destroy heat here."""
    a = _room("a", slab=False, ua_ao=0.0, c_air=1000.0)
    b = _room("b", slab=False, ua_ao=0.0, c_air=3000.0)
    m = HouseModel([a, b], 0.3, {("a", "b"): 40.0})
    x = [25.0, 19.0, 0.0]
    u = [0.0] * m.m
    for _ in range(600):
        x = m.step(x, u, 60.0)
    assert 1000.0 * x[0] + 3000.0 * x[1] == pytest.approx(1000 * 25 + 3000 * 19)
    assert 19.0 < x[1] < x[0] < 25.0


def test_a_fan_coil_heats_air_and_a_floor_heats_the_slab():
    """Arbeitszimmer has no slab (D-046). Its circuit's heat must reach its
    air in the first minute; a slab room's must reach its slab first."""
    fan = _room("fan", slab=False)
    floor = _room("floor")
    m = HouseModel([fan, floor], 0.3)
    assert m.n == 4                      # two airs, one slab, b_out
    u = [0.0] * m.m
    u[m.U_OUT] = u[m.U_GROUND] = 20.0     # no loss, so only the input acts
    u[m.u_heat["fan"]] = u[m.u_heat["floor"]] = 1000.0
    x = m.step([20.0, 20.0, 20.0, 0.0], u, 60.0)
    assert x[m.air["fan"]] > 20.01
    assert x[m.slab["floor"]] > 20.005
    assert x[m.air["floor"]] - 20.0 < (x[m.slab["floor"]] - 20.0) / 10


def test_circuit_heat_has_the_sign_of_the_water():
    """Q = m c_p (VL - RL): positive heating, NEGATIVE cooling, zero when the
    valve is below the 20 % where water starts to move (D-041), and no more
    flow past 50 % than at 50 %."""
    assert circuit_heat_w(50.0, 30.0, 27.0) == pytest.approx(
        2.0 / 60.0 * 4186.0 * 3.0)
    assert circuit_heat_w(50.0, 16.0, 19.0) < 0.0
    assert circuit_heat_w(19.0, 30.0, 27.0) == 0.0
    assert circuit_flow_kg_s(100.0) == circuit_flow_kg_s(50.0)
    assert circuit_flow_kg_s(35.0) == pytest.approx(circuit_flow_kg_s(50.0) / 2)


def test_couplings_are_wall_ceiling_and_open_paths_summed_per_pair():
    p = {"couplings": {
        "partition_u_w_per_m2k": Param(1.05), "wall_height_m": Param(2.4),
        "ceiling_u_w_per_m2k": Param(1.0),
        "walls": {"a-b": Param(5.0)}, "ceilings": {"b-a": Param(10.0)},
        "open": {"a-c": Param(100.0)}}}
    c = build_couplings(p)
    assert c[("a", "b")] == pytest.approx(1.05 * 2.4 * 5.0 + 10.0)
    assert c[("a", "c")] == 100.0
    m = HouseModel([_room("a"), _room("b")], 0.3, c)
    assert m.couplings == {("a", "b"): c[("a", "b")]}    # c is not a room


def test_the_real_params_split_back_to_the_house_totals():
    """The per-room split must not invent or lose envelope: the rooms and
    the hall together carry the house UA_ao, and the slab rooms the house
    slab-to-air conductance."""
    import yaml
    from optimizer import derived
    from optimizer.params import load_params
    p = load_params("optimizer/params.yaml")
    with open("config.yaml") as f:
        rooms = build_rooms(yaml.safe_load(f), p)
    assert sum(r.ua_ao for r in rooms) == pytest.approx(float(p["building"]["ua_ao"]))
    assert sum(r.ua_sa for r in rooms) == pytest.approx(derived.ua_sa(p).value)
    names = {r.name for r in rooms}
    for a, b in build_couplings(p):
        assert a in names and b in names, (a, b)


def test_a_steady_unmodelled_gain_lands_in_b_out():
    """The house the filter watches has 500 W more gain than its model
    knows of. Without `b_out` every prediction drifts cold; with it the
    filter must attribute the gap to the bias state, at H * b_out = 500 W."""
    r = _room("r", topic="t")
    m = HouseModel([r], 0.3)
    truth = HouseModel([r], 0.3)
    u = [0.0] * m.m
    u[m.U_OUT], u[m.U_GROUND] = 5.0, 10.0
    u_true = list(u)
    u_true[truth.u_heat["r"]] = 500.0
    x = [20.0, 20.0, 0.0]
    f = HouseFilter(m, [20.0, 20.0], 0.5, 1.0, 0.05, 0.1, 3.0, 0.3)
    for _ in range(72 * 60):
        x = truth.step(x, u_true, 60.0)
        f.predict(u, 60.0)
        f.update_air("r", x[0], 0.05)
    assert f.x[m.b_out] * r.ua_ao == pytest.approx(500.0, rel=0.15)


# ---------- the harness ----------

BASE = "heatctl"
T0 = 1_790_000_000 - (1_790_000_000 % 3600)
CFG = {"mqtt": {"host": "127.0.0.1", "base_topic": BASE},
       "rooms": [
           {"name": "a", "floor_area_m2": 20.0, "room_temp_topic": "room/a",
            "circuits": [{"sensor": "rl_a", "valve": "valve_a"}]},
           {"name": "b", "floor_area_m2": 10.0, "room_temp_topic": "room/b",
            "circuits": [{"sensor": "rl_b", "valve": "valve_b"}]}]}


def _params():
    return {"building": {"ua_ao": 120.0, "ua_sa": 300.0, "ua_sg": 20.0,
                         "c_air_wh": 3000.0, "c_slab_wh": 4000.0,
                         "slab_area_m2": 30.0, "f_sol": 0.3, "t_ground": 10.0,
                         "q_internal_w": 200.0},
            "couplings": {"partition_u_w_per_m2k": 1.05, "wall_height_m": 2.4,
                          "walls": {"a-b": 4.0}},
            "filter": {"q_air_k_per_h": 0.05, "q_slab_k_per_h": 0.1,
                       "r_air_k": 0.1, "p0_air_k": 0.1, "p0_slab_k": 0.3,
                       "p0_b_out_k": 0.01, "q_b_out_k_per_h": 0.0001}}


def _journal(tmp_path, hours=30):
    """Two coupled rooms simulated by the model under test. Room a heats
    from 00:00-06:00 and COOLS 12:00-16:00, b never, so a lost sign or a
    swapped heat slot is visibly wrong."""
    p = _params()
    rooms = build_rooms(CFG, p)
    m = HouseModel(rooms, 0.3, build_couplings(p))
    x = [21.0, 21.0, 21.0, 21.0, 0.0]
    lines = []
    for k in range(hours * 60):
        t = T0 + k * 60
        hod = (k / 60.0) % 24
        outdoor = 8.0 - 4.0 * math.cos(2 * math.pi * (hod - 3) / 24)
        sun = max(0.0, 800 * math.sin(math.pi * (hod - 7) / 10)) if 7 <= hod <= 17 else 0.0
        vl, valve_a = 21.0, 20.0
        if hod < 6:
            vl, valve_a = 30.0, 50.0
        elif 12 <= hod < 16:
            vl, valve_a = 16.0, 50.0
        rl_a = vl - 0.4 * (vl - x[m.slab["a"]])
        rl_b = x[m.slab["b"]]
        for topic, v in ((f"{BASE}/opt/state", json.dumps({"outdoor": outdoor})),
                         (f"{BASE}/temp/vl_total", vl), (f"{BASE}/temp/rl_a", rl_a),
                         (f"{BASE}/temp/rl_b", rl_b),
                         (f"{BASE}/valve_actual/valve_a", valve_a),
                         (f"{BASE}/valve_actual/valve_b", 0.0),
                         (f"{BASE}/opt/room/a/solar_w", sun),
                         ("room/a", round(x[0], 2)), ("room/b", round(x[1], 2))):
            lines.append(f"{t + 1}.0 {topic} {v}")
        u = [0.0] * m.m
        u[m.U_OUT], u[m.U_GROUND], u[m.U_ONE] = outdoor, 10.0, 1.0
        u[m.u_sol["a"]] = sun
        u[m.u_heat["a"]] = circuit_heat_w(valve_a, vl, rl_a)
        x = m.step(x, u, 60.0)
    path = tmp_path / "mqtt-20261016.log.gz"
    with gzip.open(path, "wt") as f:
        f.write("\n".join(lines) + "\n")
    return str(path)


def test_the_true_model_predicts_its_own_two_rooms(tmp_path):
    """The harness baseline, as for replay.py: replayed with its own
    parameters the per-room model must predict each room near exactly.
    A heat input in the wrong room's slot, a sign lost, or journal time not
    reaching the input staleness checks all break it."""
    rp = run(CFG, _params(), [_journal(tmp_path)])
    s = score(rp, horizons=(3, 6), warmup_h=4.0)
    for room in ("a", "b", "house"):
        for h in (3, 6):
            assert s[room][h]["rmse"] < 0.05, (room, h, s[room][h])
