"""Per-room coupled thermal model and filter (DESIGN_ESTIMATION_PLANNING
section 2, D-050): the "coupled filter v2" of phase 2.

WHY IT REPLACES THE 2-STATE MODEL. `model.py` lumps the house into one air
and one slab node, because in July only two rooms had an air sensor. All
seven have one now, and layer 1 already reasons per room (`energy.py`), so a
whole-house layer 2 can only ever answer with averages. This is the per-room
form `model.py` says supersedes it.

    C_air,r  dT_air,r  = UA_ao,r (T_out - T_air,r) + UA_sa,r (T_slab,r - T_air,r)
                       + sum_n UA_rn (T_air,n - T_air,r)
                       + f_sol q_sol,r + q_int,r      [+ Q_r for a fan coil]
    C_slab,r dT_slab,r = Q_r - UA_sa,r (T_slab,r - T_air,r)
                       - UA_sg,r (T_slab,r - T_ground) + (1 - f_sol) q_sol,r

One air node per room, one slab node per SLAB room: Arbeitszimmer is a fan
coil (D-046), so its circuit heats its air directly and it has no slab.

WHAT IS STILL A STAND-IN, stated so nobody mistakes it for identified:
- Per-room UA and capacities are the house values split by floor area, as
  `energy.py` already does. Area is a poor proxy for exposure.
- `UA_rn`, the coupling between rooms, is a hand take-off from the plans
  (params.yaml `couplings`): partition run x height x U, the upper floor over
  the rooms below it, and two OPEN paths - hall to Wohnzimmer, and the void
  between Wohnzimmer and Arbeitszimmer - whose exchange is buoyant, grows
  with sqrt(dT), and is linearised here. The door states are unobserved.
- The hall (`zones.diele`) is an air node with no circuit and no sensor:
  every bedroom opens onto it and it is open to Wohnzimmer.
- Unknown heat: either ONE house-wide `b_out` (outdoor bias, the default)
  or one unknown gain PER SENSED ROOM (`gains="rooms"`), watts into that
  room's air. The second says where the model's missing heat is; with
  returns pinning the slabs, `b_out` spread ~1.8 kW by envelope area into
  rooms that did not have it (LOGBOOK 2026-11-05).
- The return equation (section 2.4) is in the filter (`update_return`);
  WHEN a return may be used, and with which `a`, is the caller's choice -
  see optimizer/replay_rooms.py.

THE HEAT INPUT IS PER CIRCUIT, FROM WATER: `Q = m_dot c_p (VL - RL)`, with
the flow from the valve opening through D-041's calibration (0 at 20 %,
2.0 l/min at 50 %, linear between). The sign is physical in both modes, and
compressor power times an assumed COP drops out. The flow scale itself is
not identifiable without a meter and stays at its prior (section 2.3).

All internal arithmetic is SI, J/K and seconds, as in `model.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import derived
from .kalman import Matrix, Vector, expm, madd, matmul, transpose
from .model import J_PER_WH

CP_WATER = 4186.0          # J/(kg K)
RHO_WATER = 1000.0         # kg/m3, at floor-heating temperatures to 1 %


@dataclass
class Room:
    name: str
    area_m2: float
    slab: bool
    ua_ao: float
    ua_sa: float
    ua_sg: float
    c_air: float           # J/K
    c_slab: float          # J/K, 0 for a fan-coil room
    q_int: float           # W
    temp_topic: str | None
    circuits: list[tuple[str, str]] = field(default_factory=list)
    ua_edge: float = 0.0   # slab -> outdoor air, W/K (the slab's perimeter)


def build_rooms(cfg: dict, params: dict) -> list[Room]:
    """Split the house parameters over the configured rooms.

    Envelope, air capacity and internal gains go by share of the total room
    area. The slab terms go by SLAB: capacity and ground loss per m2 of the
    as-built slab (`slab_area_m2`, whose capacity `c_slab_wh` is), and the
    slab-to-air conductance over the heated slab rooms only, because it was
    identified through the circuits and the circuits are under those rooms.
    Slab outside any room (hall, stairs) is not modelled: it has no circuit
    and no sensor.
    """
    b = params["building"]
    # INTERNAL GAINS. With an occupancy schedule (`occupancy`), the flat
    # q_internal_w is replaced by a smaller base load (appliances, standby)
    # spread by area, and the people arrive per room through the schedule
    # (`occupancy_w`) - 2026-11-08: four occupants sat exactly where the model
    # was short at night, which a flat figure by floor area cannot express.
    occ = params.get("occupancy") or {}
    q_base = float(occ["base_w"]) if "base_w" in occ else float(b["q_internal_w"])
    # ENVELOPE-SIDE FACTOR. The air along a big glazed envelope is colder than
    # the sensor in the room: Wohnzimmer measured 2.4-2.7 K below the interior
    # at ~20 K indoor-outdoor (owner, 11-05 and 11-08), i.e. ~13 % of the
    # difference. Loss through the envelope is driven by that colder air, so
    # the room's effective ua_ao is (1 - k). Not renormalised: this is a
    # correction to the room, not a redistribution of the house total.
    side = {n: float(v) for n, v in (params.get("envelope_side_k") or {}).items()}
    # SLAB EDGE. The certificate's thermal-bridge surcharge (0.10 W/m2K over
    # every element) gives the floor 13.6 W/K, and physically that is the
    # slab's perimeter losing to outdoor air under the walls. It is part of the
    # measured ua_ao; carried on the air node it was in the wrong place - the
    # returns read ~0.1-0.2 K below the modelled slabs on 7 of 9 circuits. Here
    # it moves to the slabs, by heated area, and leaves the air node: the
    # whole-house total is unchanged, only where the loss happens moves.
    ua_edge_total = float(b.get("ua_slab_edge", 0.0) or 0.0)
    # The floor's ground path is carried as ua_sg; take its share out of the
    # measured ua_ao so it is not counted twice (derived.ua_ao_air).
    ua_ao_air = derived.ua_ao_air(params)
    ua_sa = (derived.ua_sa_model(params).value if "ua_sa_identification" in b
             else float(b["ua_sa"]))
    rooms_cfg = [r for r in cfg.get("rooms", []) if r.get("floor_area_m2")]
    total = sum(float(r["floor_area_m2"]) for r in rooms_cfg)
    # HEATED floor, which is not always the floor (owner, 2026-11-08: about
    # 10 m2 of Wohnzimmer around the chimney and under the stair has no
    # pipes). The slab node is the heated part: its capacity, its share of the
    # identified slab-to-air conductance, its ground loss.
    heated = {n: float(v) for n, v in (params.get("heated_area_m2") or {}).items()}

    def heated_of(r: dict) -> float:
        return heated.get(r["name"], float(r["floor_area_m2"]))

    slab_rooms = sum(heated_of(r) for r in rooms_cfg
                     if r.get("emitter", "slab") == "slab")
    slab_area = float(b.get("slab_area_m2", slab_rooms) or slab_rooms)
    # Zones: air the model needs that layer 1 does not control. They take
    # their share of the envelope and the internal gains like any room.
    zcfg = params.get("zones") or {}
    zones = {n: float(z["floor_area_m2"]) for n, z in zcfg.items()}
    total += sum(zones.values())
    # A zone may carry a heated floor and circuits of its own (2026-11-08,
    # owner: the Diele is heated by circuit 2, which config.yaml lists under
    # Wohnzimmer because layer 1 runs it on Wohnzimmer's temperature). A
    # circuit claimed by a zone is the zone's here, whatever room config puts
    # it under: this file models where the heat GOES, config says who
    # COMMANDS it.
    zone_heated = {n: float(z.get("heated_area_m2", 0.0) or 0.0)
                   for n, z in zcfg.items()}
    zone_circuits = {n: [tuple(c) for c in (z.get("circuits") or [])]
                     for n, z in zcfg.items()}
    claimed = {c[1] for cs in zone_circuits.values() for c in cs}
    slab_rooms += sum(zone_heated.values())
    # ENVELOPE by its own take-off when there is one (params `envelope_share`,
    # renormalised over the rooms present), else by floor area. The children's
    # rooms showed why area is wrong: no roof, so their area share charged
    # them losses they do not have, which the filter then reported as heat.
    env = {n: float(v) for n, v in (params.get("envelope_share") or {}).items()}
    names = [r["name"] for r in rooms_cfg] + list(zones)
    env_total = sum(env.get(n, 0.0) for n in names)
    use_env = bool(env) and all(n in env for n in names) and env_total > 0

    def env_share(n: str, area: float) -> float:
        return env[n] / env_total if use_env else area / total

    edge_area = sum(heated_of(r) for r in rooms_cfg
                    if r.get("emitter", "slab") == "slab") + sum(zone_heated.values())

    def edge_of(ha: float) -> float:
        return ua_edge_total * ha / edge_area if edge_area else 0.0

    out = []
    for r in rooms_cfg:
        a = float(r["floor_area_m2"])
        slab = r.get("emitter", "slab") == "slab"
        share = a / total
        out.append(Room(
            name=r["name"], area_m2=a, slab=slab,
            ua_ao=ua_ao_air * env_share(r["name"], a)
            * (1.0 - side.get(r["name"], 0.0))
            - (edge_of(heated_of(r)) if slab else 0.0),
            ua_edge=edge_of(heated_of(r)) if slab else 0.0,
            ua_sa=ua_sa * heated_of(r) / slab_rooms if slab else 0.0,
            ua_sg=float(b["ua_sg"]) * heated_of(r) / slab_area if slab else 0.0,
            c_air=float(b["c_air_wh"]) * share * J_PER_WH,
            c_slab=float(b["c_slab_wh"]) * heated_of(r) / slab_area * J_PER_WH
            if slab else 0.0,
            q_int=q_base * share,
            temp_topic=r.get("room_temp_topic"),
            circuits=[(c["sensor"], c["valve"]) for c in r.get("circuits", [])
                      if c.get("sensor") and c.get("valve")
                      and c["valve"] not in claimed]))
    for n, a in zones.items():
        share = a / total
        ha = zone_heated[n]
        out.append(Room(
            name=n, area_m2=a, slab=ha > 0.0,
            ua_ao=ua_ao_air * env_share(n, a)
            * (1.0 - side.get(n, 0.0)) - edge_of(ha),
            ua_edge=edge_of(ha),
            ua_sa=ua_sa * ha / slab_rooms if ha else 0.0,
            ua_sg=float(b["ua_sg"]) * ha / slab_area if ha else 0.0,
            c_air=float(b["c_air_wh"]) * share * J_PER_WH,
            c_slab=float(b["c_slab_wh"]) * ha / slab_area * J_PER_WH if ha else 0.0,
            q_int=q_base * share, temp_topic=None,
            circuits=zone_circuits[n]))
    return out


def build_couplings(params: dict) -> dict[tuple[str, str], float]:
    """Room-pair conductances, W/K, from params.yaml `couplings`."""
    c = params.get("couplings") or {}
    if not c:
        return {}
    u_wall = float(c["partition_u_w_per_m2k"])
    h = float(c["wall_height_m"])
    u_ceil = float(c.get("ceiling_u_w_per_m2k", 0.0))
    out: dict[tuple[str, str], float] = {}

    def add(key: str, w: float) -> None:
        a, _, b = key.partition("-")
        k = tuple(sorted((a, b)))
        out[k] = out.get(k, 0.0) + w

    for key, run in (c.get("walls") or {}).items():
        add(key, u_wall * h * float(run))
    for key, area in (c.get("ceilings") or {}).items():
        add(key, u_ceil * float(area))
    for key, ua in (c.get("open") or {}).items():
        add(key, float(ua))
    return out


def occupancy_w(params: dict, room: str, hour: float, weekend: bool) -> float:
    """Sensible heat from people in `room` at local `hour`, W.

    `occupancy.schedule.<room>` is a list of [days, from_h, to_h, persons,
    state]; days is all|weekday|weekend, the span may wrap midnight, state is
    asleep|awake. A PRIOR from the owner's account, to be corrected by the
    owner and checked against the per-room gains the filter reports."""
    occ = params.get("occupancy") or {}
    w = {"asleep": float(occ.get("w_asleep", 70.0)),
         "awake": float(occ.get("w_awake", 90.0))}
    total = 0.0
    for days, h0, h1, persons, state in (occ.get("schedule") or {}).get(room, []):
        if days == "weekday" and weekend or days == "weekend" and not weekend:
            continue
        h0, h1 = float(h0), float(h1)
        inside = h0 <= hour < h1 if h0 < h1 else (hour >= h0 or hour < h1)
        if inside:
            total += float(persons) * w[state]
    return total


def circuit_flow_kg_s(opening_pct: float, open_pct: float = 20.0,
                      full_pct: float = 50.0, full_l_min: float = 2.0) -> float:
    """Mass flow through one circuit from its valve read-back (D-041)."""
    frac = min(1.0, max(0.0, (opening_pct - open_pct) / (full_pct - open_pct)))
    return frac * full_l_min / 60.0 * RHO_WATER / 1000.0


def circuit_heat_w(opening_pct: float, vl_c: float, rl_c: float) -> float:
    """Heat delivered into the floor by one circuit, W. Negative = cooling."""
    return circuit_flow_kg_s(opening_pct) * CP_WATER * (vl_c - rl_c)


class HouseModel:
    """The linear model: state, input layout, and its discretisation.

    State: every room's air, then the slab rooms' slabs, then either
    `b_out` or one unknown gain per sensed room (`gain`).
    Input: [T_out, T_ground, 1, q_sol per room..., Q per room...]; the
    constant 1 carries the internal gains, so they are part of the model
    rather than something each caller has to remember to add.
    """

    U_OUT, U_GROUND, U_ONE = 0, 1, 2

    def __init__(self, rooms: list[Room], f_sol: float,
                 couplings: dict[tuple[str, str], float] | None = None,
                 gains: str = "house") -> None:
        if gains not in ("house", "rooms"):
            raise ValueError(f"gains must be house|rooms, got {gains!r}")
        self.rooms = rooms
        self.f_sol = float(f_sol)
        # Pairs naming a room this model does not have are dropped, so a
        # synthetic config with fewer rooms still builds.
        names = {r.name for r in rooms}
        self.couplings = {k: v for k, v in (couplings or {}).items()
                          if k[0] in names and k[1] in names}
        nr = len(rooms)
        self.air = {r.name: i for i, r in enumerate(rooms)}
        self.slab: dict[str, int] = {}
        for r in rooms:
            if r.slab:
                self.slab[r.name] = nr + len(self.slab)
        # b_out, the outdoor bias (section 2.1): effective outdoor is
        # forecast + b_out, for every room's envelope. A random walk, so a
        # STEADY energy gap - wrong UA, unmodelled gains, a biased forecast -
        # lands here instead of dragging every prediction one way. Its size
        # is therefore a measurement of that gap, H * b_out watts.
        #
        # Per-room gains instead: a random walk in W into each SENSED room's
        # air. Unsensed zones (the hall) get none - nothing could observe it.
        first = nr + len(self.slab)
        self.gain: dict[str, int] = {}
        if gains == "house":
            self.b_out: int | None = first
            self.n = first + 1
        else:
            self.b_out = None
            for r in rooms:
                if r.temp_topic:
                    self.gain[r.name] = first + len(self.gain)
            self.n = first + len(self.gain)
        self.u_sol = {r.name: 3 + i for i, r in enumerate(rooms)}
        self.u_heat = {r.name: 3 + nr + i for i, r in enumerate(rooms)}
        # People, W into the room's air, from `occupancy_w`. Zero when there
        # is no schedule, so the model is unchanged without one.
        self.u_occ = {r.name: 3 + 2 * nr + i for i, r in enumerate(rooms)}
        self.m = 3 + 3 * nr
        self._cache: dict[float, tuple[Matrix, Matrix]] = {}

    def coupling(self, a: Room, b: Room) -> float:
        return self.couplings.get(tuple(sorted((a.name, b.name))), 0.0)

    def continuous(self) -> tuple[Matrix, Matrix]:
        n, m = self.n, self.m
        A = [[0.0] * n for _ in range(n)]
        B = [[0.0] * m for _ in range(n)]
        for r in self.rooms:
            i = self.air[r.name]
            A[i][i] -= r.ua_ao / r.c_air
            B[i][self.U_OUT] += r.ua_ao / r.c_air
            if self.b_out is not None:
                A[i][self.b_out] += r.ua_ao / r.c_air
            if r.name in self.gain:
                A[i][self.gain[r.name]] += 1.0 / r.c_air
            B[i][self.U_ONE] += r.q_int / r.c_air
            B[i][self.u_occ[r.name]] += 1.0 / r.c_air
            for o in self.rooms:
                if o is not r:
                    k = self.coupling(r, o)
                    A[i][i] -= k / r.c_air
                    A[i][self.air[o.name]] += k / r.c_air
            if r.slab:
                s = self.slab[r.name]
                A[i][i] -= r.ua_sa / r.c_air
                A[i][s] += r.ua_sa / r.c_air
                A[s][s] -= (r.ua_sa + r.ua_sg + r.ua_edge) / r.c_slab
                B[s][self.U_OUT] += r.ua_edge / r.c_slab
                A[s][i] += r.ua_sa / r.c_slab
                B[s][self.U_GROUND] += r.ua_sg / r.c_slab
                B[i][self.u_sol[r.name]] += self.f_sol / r.c_air
                B[s][self.u_sol[r.name]] += (1.0 - self.f_sol) / r.c_slab
                B[s][self.u_heat[r.name]] += 1.0 / r.c_slab
            else:
                # No slab: the sun and the fan coil both land in the air.
                B[i][self.u_sol[r.name]] += 1.0 / r.c_air
                B[i][self.u_heat[r.name]] += 1.0 / r.c_air
        return A, B

    def discretise(self, dt_s: float) -> tuple[Matrix, Matrix]:
        """Exact ZOH by Van Loan, as `model.discretise`; cached per step,
        because the matrices do not change with the inputs."""
        key = round(dt_s, 3)
        if key not in self._cache:
            A, B = self.continuous()
            n, m = self.n, self.m
            blk = [[0.0] * (n + m) for _ in range(n + m)]
            for i in range(n):
                for j in range(n):
                    blk[i][j] = A[i][j] * dt_s
                for j in range(m):
                    blk[i][n + j] = B[i][j] * dt_s
            e = expm(blk)
            self._cache[key] = ([row[:n] for row in e[:n]],
                                [row[n:] for row in e[:n]])
            if len(self._cache) > 32:
                self._cache.pop(next(iter(self._cache)))
        return self._cache[key]

    def step(self, x: Vector, u: Vector, dt_s: float) -> Vector:
        F, G = self.discretise(dt_s)
        return [sum(F[i][j] * x[j] for j in range(self.n))
                + sum(G[i][k] * u[k] for k in range(self.m) if u[k])
                for i in range(self.n)]


class HouseFilter:
    """Linear KF over `HouseModel`, with scalar room-air updates.

    Measurements arrive one room at a time and at different rates (a Shelly
    reports on a 0.5 K change or every two hours), so each is folded in on
    its own as a scalar update: no matrix inverse, and a room that is silent
    is simply predicted. Innovations are kept PER ROOM, so one bad room is
    visible on its own (section 2.7).
    """

    def __init__(self, model: HouseModel, x0: Vector, p0_air_k: float,
                 p0_slab_k: float, q_air_k_per_h: float,
                 q_slab_k_per_h: float, p0_b_out_k: float = 3.0,
                 q_b_out_k_per_h: float = 0.3, p0_gain_w: float = 300.0,
                 q_gain_w_per_h: float = 60.0) -> None:
        """`x0` gives the air and slab states; disturbances start at 0."""
        self.model = model
        self.x = list(x0) + [0.0] * (model.n - len(x0))
        nr = len(model.rooms)
        p0 = [p0_air_k if i < nr else p0_slab_k for i in range(model.n)]
        q = [q_air_k_per_h if i < nr else q_slab_k_per_h for i in range(model.n)]
        if model.b_out is not None:
            p0[model.b_out], q[model.b_out] = p0_b_out_k, q_b_out_k_per_h
        for i in model.gain.values():
            p0[i], q[i] = p0_gain_w, q_gain_w_per_h
        self.P = [[0.0] * model.n for _ in range(model.n)]
        for i in range(model.n):
            self.P[i][i] = p0[i] ** 2
        self.q = [v * v for v in q]
        self.innovations: dict[str, list[float]] = {r.name: [] for r in model.rooms}
        self.return_innovations: dict[str, list[float]] = {}

    def predict(self, u: Vector, dt_s: float) -> None:
        F, _ = self.model.discretise(dt_s)
        self.x = self.model.step(self.x, u, dt_s)
        P = matmul(matmul(F, self.P), transpose(F))
        h = dt_s / 3600.0
        for i in range(self.model.n):
            P[i][i] += self.q[i] * h
        self.P = P

    def update_air(self, room: str, z: float, r_k: float) -> float:
        """Fold in one room's air reading; returns the innovation."""
        y = self._update(self.model.air[room], 1.0, 0.0, z, r_k)
        v = self.innovations[room]
        v.append(y)
        del v[:-5000]
        return y

    def update_return(self, circuit: str, room: str, z: float, vl: float,
                      a: float, r_k: float) -> float:
        """Fold in one circuit's return temperature (section 2.4).

        `RL = a T_slab + (1 - a) VL`: water that has crossed the slab sits
        between the supply and the slab, `a = 1 - exp(-NTU)`. The first
        direct measurement of a slab in this model. Only valid while the
        circuit flows (D-009); the caller decides that."""
        y = self._update(self.model.slab[room], a, (1.0 - a) * vl, z, r_k)
        v = self.return_innovations.setdefault(circuit, [])
        v.append(y)
        del v[:-5000]
        return y

    def _update(self, i: int, h: float, offset: float, z: float,
                r_k: float) -> float:
        """Scalar update, z = h x_i + offset + v. Returns the innovation."""
        n = self.model.n
        y = z - (h * self.x[i] + offset)
        s = h * h * self.P[i][i] + r_k * r_k
        k = [h * self.P[j][i] / s for j in range(n)]
        self.x = [self.x[j] + k[j] * y for j in range(n)]
        # Joseph form, as kalman.KalmanFilter: (I-KH) P (I-KH)' + K R K'.
        ikh = [[(1.0 if a == b else 0.0) - (k[a] * h if b == i else 0.0)
                for b in range(n)] for a in range(n)]
        P = matmul(matmul(ikh, self.P), transpose(ikh))
        rr = r_k * r_k
        self.P = madd(P, [[k[a] * k[b] * rr for b in range(n)] for a in range(n)])
        return y
