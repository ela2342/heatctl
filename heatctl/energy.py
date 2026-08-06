"""Per-room slab energy: estimate, target, and the signed excess between them.

Implements §1-§3 of docs/DESIGN_ENERGY_DEMAND.md. **Pure computation, no I/O
and no authority** - `main.py` publishes what this produces and, for now, acts
on none of it. That is deliberate: a feedforward controller is confidently
wrong when its parameters are wrong, and four of seven rooms have no air
sensor to notice. Making the intermediates observable BEFORE giving them
authority is what turns "correct later" from a hope into a procedure.

WHY FEEDFORWARD AT ALL. The plant's air/slab mode is 5.62 h and its slow mode
58 h. A PID asked to control through that has to be detuned until it barely
acts; the earlier cascade sketch was rejected for exactly this. Computing the
target from physics instead moves the slow dynamics out of the loop - there is
no integrator to wind up against a process that answers in hours.

WHAT THIS IS NOT. It does not close a loop. `slab_excess_wh` is a measurement
of how far a room is from where physics says it should be; deciding what to do
about that is the caller's job.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RoomEnergy:
    """One room's slab state against its target. All fields signed."""
    name: str
    slab_c: float | None            # estimated slab temperature
    target_c: float | None          # where physics says it should sit
    excess_wh: float | None         # + = holds MORE energy than target
    valid: bool                     # is `slab_c` usable at all
    reason: str                     # why not, when it is not


def slab_target_c(setpoint_c: float, outdoor_c: float, ua_ao: float,
                  ua_sa: float, q_sol_w: float = 0.0, q_int_w: float = 0.0,
                  room_c: float | None = None, c_air_wh: float = 0.0,
                  tau_recover_h: float = 6.0) -> float:
    """Slab temperature that drives the room to setpoint.

    Two terms, and the second one is the reason this is not pure feedforward.

    **Holding term** - the steady-state balance of floor emission against room
    loss net of gains (DESIGN_ENERGY_DEMAND.md §2):

        UA_sa * (T_slab - T_room) = UA_ao * (T_room - AT) - Q_sol - Q_int

    Sign-correct in both modes with no special casing, which is why it is
    written as a balance rather than as a heating curve with a cooling variant
    bolted on. In cooling `T_set - AT` is negative so the target lands BELOW
    room temperature, and solar gain pushes it lower still. Anyone tempted to
    add `if mode == "cooling"` should check whether the arithmetic already did
    it.

    **Recovery term** - and this was MISSING from the first version, caught by
    checking it against the live plant on 2026-08-06. With Wohnzimmer 2.6 K
    above setpoint, the holding target came out at 19.84 degC while the slab
    measured 15-17 degC: colder than target, i.e. "nothing to do", while the
    room sat 2.6 K too warm. A steady-state target holds a room where it
    already is; it has no error term and cannot bring it back.

    Moving the room by `T_room - T_set` over a recovery time needs power beyond
    the steady-state balance, and its size is set by the room's heat capacity:

        Q_recover = C_air * (T_room - T_set) / tau_recover

    So this is **feedforward on the load and proportional feedback on the
    error** - and no integrator anywhere, which is the whole point. An
    integrator is what could not survive the plant's 5.62 h air/slab mode. The
    proportional gain here is not tuned; it is `C_air / tau`, derived from an
    identified capacity, with `tau_recover` the single policy choice: how fast
    we intend to correct. It should not be shorter than the fast mode, or the
    loop asks for power the building cannot absorb.

    `room_c` absent means no error term - correct behaviour for a room whose
    air temperature is unknown, which is four of seven today. The room then
    gets the holding target only, which keeps it where it is rather than
    guessing where it should go.

    `ua_sa` is a divisor and a zero is a configuration error, not a physical
    state, so it raises rather than silently returning infinity.
    """
    if ua_sa <= 0.0:
        raise ValueError(f"ua_sa must be positive, got {ua_sa}")
    if tau_recover_h <= 0.0:
        raise ValueError(f"tau_recover_h must be positive, got {tau_recover_h}")
    q_recover = 0.0
    if room_c is not None and c_air_wh > 0.0:
        q_recover = c_air_wh * (room_c - setpoint_c) / tau_recover_h
    return setpoint_c + (ua_ao * (setpoint_c - outdoor_c)
                         - q_sol_w - q_int_w - q_recover) / ua_sa


def slab_estimate_c(rl_c: float, vl_c: float | None,
                    ntu: float | None) -> float:
    """Slab temperature behind a circuit's return reading.

    A return sensor measures water that has traversed the slab, so it sits
    between supply and slab according to how long it stayed:

        RL = T_slab + (VL - T_slab) * exp(-NTU)

    Inverted here. With `ntu` unknown - which is everywhere today, since
    NTU(opening) is unmeasured (§7.3) - this falls back to `RL` itself, the
    low-flow approximation. **That approximation is biased toward VL**, i.e.
    in cooling it reads the slab COLDER than it is, so the room looks better
    supplied than it really is. Recording the direction because a bias whose
    sign nobody knows is worse than one everybody does.
    """
    if ntu is None or vl_c is None or ntu <= 0.0:
        return rl_c
    e = math.exp(-ntu)
    if e >= 1.0:                    # NTU underflow: no exchange to invert
        return rl_c
    return (rl_c - vl_c * e) / (1.0 - e)


class EnergyDemand:
    """Per-room slab excess, from config parameters and live sensors.

    Layer 1 owns this and must work with the broker dead, so every parameter
    has a config fallback. Layer 2 refines them at runtime (see `update_params`)
    using the same publish-with-expiry contract as the pre-conditioning delta -
    parameters, never commands.
    """

    def __init__(self, cfg: dict):
        c = (cfg.get("control") or {}).get("energy") or {}
        b = c.get("building") or {}
        # HOUSE TOTALS. Deliberately duplicated from optimizer/params.yaml
        # rather than read from it: layer 1 may not depend on a layer 2 file,
        # and a cross-layer import would make the control core unstartable if
        # that file were malformed. Divergence is handled at runtime instead -
        # layer 2 publishes its refined values and they take precedence while
        # fresh.
        #
        # ua_ao 267.2 is the BUILDING PERMIT CALCULATION, a prior and not a
        # measurement. params.yaml records three independent routes converging
        # near 216 instead (D-028's winter fit 216 +- 18, and an n of ~0.40
        # giving 216.5). The default here is the conservative-for-comfort end
        # of that range; the spread is real and belongs in the identification
        # ladder, not hidden behind a single number.
        self.ua_ao = float(b.get("ua_ao_w_per_k", 240.0))
        self.ua_sa = float(b.get("ua_sa_w_per_k", 490.0))
        self.c_slab_wh_per_m2 = float(b.get("c_slab_wh_per_m2_k", 63.7))
        self.q_int_w = float(b.get("q_internal_w", 350.0))
        self.c_air_wh = float(b.get("c_air_wh_per_k", 6600.0))
        # RECOVERY TIME: how fast we intend to close a room error. The single
        # policy choice in the whole scheme. Must not be shorter than the
        # plant's fast air/slab mode (5.62 h at the identified parameters) or
        # the target asks for power the building cannot absorb - which is the
        # overshoot already measured on the pre-charge trial, where a 0.39 K
        # request produced 1.2 K of undershoot overnight.
        self.tau_recover_h = float(c.get("tau_recover_h", 6.0))

        # Per-room floor area drives every per-room split: slab capacity, and
        # the share of house UA allocated to the room. Area is a poor proxy for
        # envelope exposure - a corner room loses more per m2 than an interior
        # one - so this is explicitly a first approximation, replaced per room
        # once the survey areas are entered and refined by identification.
        self.areas: dict[str, float] = {}
        # EMITTER TYPE, because area alone does not tell you whether a room has
        # thermal storage. Arbeitszimmer is 31.20 m2 on the OG with a fan coil:
        # applying `c_slab_wh_per_m2` to it invented 1987 Wh/K - 24 % of the
        # house total - in a room with no slab. Worse, `c_slab_wh` is derived
        # from the 136.40 m2 GROUND FLOOR area, which does not include that
        # room at all, so the number was wrong twice over.
        #
        # The area is still carried for the UA split: the room is real and
        # loses heat through a real envelope. Only the slab model is excluded.
        # A fan-coil room needs its own model (air capacity, no storage); until
        # it has one, `room()` refuses rather than fabricating an excess.
        self.emitters: dict[str, str] = {}
        for room in cfg.get("rooms", []):
            a = room.get("floor_area_m2")
            if a:
                self.areas[room["name"]] = float(a)
                self.emitters[room["name"]] = room.get("emitter", "slab")
        self.total_area = sum(self.areas.values())

        # Layer 2 refinements, empty until it publishes.
        self._ntu: dict[str, float] = {}
        self._q_sol: dict[str, float] = {}

    def has_slab(self, name: str) -> bool:
        """Does this room store energy in a floor slab we can aim at?"""
        return self.emitters.get(name, "slab") == "slab"

    def room_share(self, name: str) -> float:
        """Fraction of the house this room represents, by floor area."""
        if not self.total_area or name not in self.areas:
            return 0.0
        return self.areas[name] / self.total_area

    def update_params(self, ntu: dict[str, float] | None = None,
                      q_sol: dict[str, float] | None = None) -> None:
        """Accept layer 2 refinements. Parameters only - never commands."""
        if ntu:
            self._ntu.update(ntu)
        if q_sol:
            self._q_sol.update(q_sol)

    def room(self, name: str, setpoint_c: float, outdoor_c: float | None,
             rl_c: float | None, vl_c: float | None,
             rl_valid: bool = True, room_c: float | None = None) -> RoomEnergy:
        """One room's slab state. Never raises; returns an invalid result.

        Refuses rather than guesses on every missing input. A feedforward
        target computed from an absent outdoor temperature is not a degraded
        estimate, it is a fabricated one, and the caller must be able to tell
        the difference - hence `valid` and `reason` rather than a None that
        loses the cause.
        """
        share = self.room_share(name)
        if share <= 0.0:
            return RoomEnergy(name, None, None, None, False, "no floor area")
        if outdoor_c is None:
            return RoomEnergy(name, None, None, None, False, "no outdoor temp")

        target = slab_target_c(
            setpoint_c, outdoor_c,
            ua_ao=self.ua_ao * share, ua_sa=self.ua_sa * share,
            q_sol_w=self._q_sol.get(name, 0.0),
            q_int_w=self.q_int_w * share,
            room_c=room_c, c_air_wh=self.c_air_wh * share,
            tau_recover_h=self.tau_recover_h)

        if not self.has_slab(name):
            # The target still stands - it says what water this room wants -
            # but `excess` is C_slab * dT and this room has no C_slab. Refusing
            # is the honest answer; a fan-coil room needs an air-capacity model
            # it does not have yet.
            return RoomEnergy(name, None, target, None, False,
                              f"no slab ({self.emitters[name]})")
        if rl_c is None:
            return RoomEnergy(name, None, target, None, False, "no return temp")
        if not rl_valid:
            return RoomEnergy(name, None, target, None, False, "rl not valid")

        slab = slab_estimate_c(rl_c, vl_c, self._ntu.get(name))
        c_room = self.c_slab_wh_per_m2 * self.areas[name]
        return RoomEnergy(name, slab, target, c_room * (slab - target),
                          True, "ok")

    def house_excess_wh(self, rooms: list[RoomEnergy]) -> float | None:
        """Signed house total, or None if nothing was estimable.

        Sums only the valid rooms, so a partially instrumented house
        UNDERSTATES the total rather than extrapolating. Understating means
        the plant does less than it might; extrapolating from two rooms to
        seven would have it confidently do the wrong amount.
        """
        vals = [r.excess_wh for r in rooms if r.valid and r.excess_wh is not None]
        return sum(vals) if vals else None
