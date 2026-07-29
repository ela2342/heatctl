"""Whole-house 2-state thermal model (layer 2).

**Why 2 states and not the 3-state per-room model in docs/DESIGN.md 6.1.**
That model assumes the planned per-room Shelly H&T sensors. They are not
installed. DESIGN.md 6.1.1 is explicit that without them the 3-state form is
not identifiable and unsensored rooms "should collapse to 1-2 states rather
than run three states off one intermittent, position-biased measurement" -
and today only two rooms have any air measurement at all, both of them via
the surviving Controme wall units.

So this is the honest reduction, not a shortcut: one air node for the
dwelling, one slab node, driven by measured outdoor temperature and forecast
solar. It is a stepping stone with a known end date. When the Shelly sensors
and the flow meter arrive, this file is superseded by the per-room form
rather than extended into it.

    C_air  dT_air/dt  = UA_ao(AT - T_air) + UA_sa(T_slab - T_air)
                        + f_sol*q_sol + q_int
    C_slab dT_slab/dt = Q_heat - UA_sa(T_slab - T_air)
                        - UA_sg(T_slab - T_ground) + (1 - f_sol)*q_sol

**The known weak point is Q_heat.** Without a heat meter it comes from an
assumed pump curve and the VL/RL spread, which DESIGN.md 6.1.1 calls the
model's deepest dependency: "the flow meter is a model prerequisite, not an
accounting nicety". Q_heat is therefore carried as an input with a large
process-noise allowance rather than trusted, and the filter's innovation
statistics are the instrument that tells us how bad the assumption is.

All internal arithmetic is SI - J/K and seconds - while params.yaml is in the
Wh/K the building survey quotes. The conversion happens once, here.
"""
from __future__ import annotations

from dataclasses import dataclass

from .kalman import Matrix, expm

WH_PER_J = 1.0 / 3600.0
J_PER_WH = 3600.0

# Input vector order. Named so the callers cannot silently transpose two of
# them - a swapped q_int and q_sol still runs and still looks plausible.
U_OUTDOOR = 0
U_SOLAR = 1
U_INTERNAL = 2
U_HEAT = 3
U_GROUND = 4
N_INPUTS = 5


@dataclass(frozen=True)
class BuildingParams:
    """Thermal parameters. See optimizer/params.yaml for provenance."""
    ua_ao: float        # W/K, air -> outdoor (fabric + ventilation)
    ua_sa: float        # W/K, slab -> air
    ua_sg: float        # W/K, slab -> ground
    c_air_wh: float     # Wh/K, everything that is not the slab
    c_slab_wh: float    # Wh/K, the floor slab
    f_sol: float        # fraction of solar gain landing on air, not floor

    @property
    def c_air(self) -> float:
        return self.c_air_wh * J_PER_WH

    @property
    def c_slab(self) -> float:
        return self.c_slab_wh * J_PER_WH

    def time_constants_h(self) -> tuple[float, float]:
        """Rough per-node time constants, for sanity-checking a config.

        Not the system eigenvalues - these ignore the coupling term's effect
        on the modes - but enough to catch a parameter entered in the wrong
        unit, which is the failure this is here to make obvious.
        """
        return ((self.c_air / (self.ua_ao + self.ua_sa)) / 3600.0,
                (self.c_slab / (self.ua_sa + self.ua_sg)) / 3600.0)


def continuous(p: BuildingParams) -> tuple[Matrix, Matrix]:
    """Continuous-time (A, B) for dx/dt = A x + B u."""
    a = [[-(p.ua_ao + p.ua_sa) / p.c_air, p.ua_sa / p.c_air],
         [p.ua_sa / p.c_slab, -(p.ua_sa + p.ua_sg) / p.c_slab]]
    b = [[0.0] * N_INPUTS, [0.0] * N_INPUTS]
    b[0][U_OUTDOOR] = p.ua_ao / p.c_air
    b[0][U_SOLAR] = p.f_sol / p.c_air
    b[0][U_INTERNAL] = 1.0 / p.c_air
    b[1][U_SOLAR] = (1.0 - p.f_sol) / p.c_slab
    b[1][U_HEAT] = 1.0 / p.c_slab
    b[1][U_GROUND] = p.ua_sg / p.c_slab
    return a, b


def discretise(p: BuildingParams, dt_s: float) -> tuple[Matrix, Matrix]:
    """Exact zero-order-hold discretisation over `dt_s`, by Van Loan.

    Builds the block matrix [[A, B], [0, 0]]*dt, exponentiates it, and reads
    F and G off the top row. This avoids inverting A, which matters because A
    becomes singular in the limit of a perfectly insulated building - a case
    that is physically silly but numerically reachable while someone is
    experimenting with parameters, and it should not raise.
    """
    a, b = continuous(p)
    n, m = len(a), N_INPUTS
    block = [[0.0] * (n + m) for _ in range(n + m)]
    for i in range(n):
        for j in range(n):
            block[i][j] = a[i][j] * dt_s
        for j in range(m):
            block[i][n + j] = b[i][j] * dt_s
    e = expm(block)
    f = [[e[i][j] for j in range(n)] for i in range(n)]
    g = [[e[i][n + j] for j in range(m)] for i in range(n)]
    return f, g


def steady_state_air(p: BuildingParams, outdoor: float, ground: float,
                     q_heat: float, q_sol: float = 0.0,
                     q_int: float = 0.0) -> float:
    """Equilibrium air temperature for a constant input set.

    Used for the heat-demand estimate and for testing: at steady state the
    slab drops out and the whole building is a single resistance, so this is
    also the sanity check that ua_ao really is the H the winter data measured.
    """
    a, b = continuous(p)
    # Solve A x = -B u for x.
    u = [0.0] * N_INPUTS
    u[U_OUTDOOR], u[U_GROUND] = outdoor, ground
    u[U_HEAT], u[U_SOLAR], u[U_INTERNAL] = q_heat, q_sol, q_int
    rhs = [-sum(b[i][k] * u[k] for k in range(N_INPUTS)) for i in range(2)]
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    if abs(det) < 1e-18:
        raise ValueError("degenerate model: no unique steady state")
    return (rhs[0] * a[1][1] - a[0][1] * rhs[1]) / det


def heat_demand_w(p: BuildingParams, target_air: float, outdoor: float,
                  ground: float, q_sol: float = 0.0,
                  q_int: float = 0.0) -> float:
    """Steady-state heat input needed to hold `target_air`. Never negative.

    Clamped at zero because this is a heating-demand figure: when gains alone
    overshoot the target the answer is "none", and the negative number the
    algebra produces is a cooling demand, which is a different question with
    a different safety envelope (condensation) and must not be conflated.
    """
    a, b = continuous(p)
    # With T_air pinned, the slab equation gives T_slab, and the air equation
    # then gives the required Q. Doing it in this order avoids assuming the
    # heat enters the air node, which it does not - it enters the slab.
    u_sol_slab = (1.0 - p.f_sol) * q_sol
    # 0 = ua_sa(T_slab - T_air) ... solved jointly with the air balance:
    loss_air = p.ua_ao * (target_air - outdoor) - p.f_sol * q_sol - q_int
    # loss_air must arrive from the slab: ua_sa(T_slab - T_air) = loss_air
    t_slab = target_air + loss_air / p.ua_sa
    q = p.ua_sg * (t_slab - ground) + loss_air - u_sol_slab
    del a, b
    return max(0.0, q)
