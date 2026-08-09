# Energy-demand control — proposal against DESIGN.md §4 and §7

**Status: PROPOSAL, not implemented.** Written 2026-08-06. Supersedes the
cascade sketch in §4 (outer room PID biasing an inner RL PID), which was
rejected for ignoring the plant's time constants — it would have needed heavy
detuning to survive the 5.62 h air↔slab mode, i.e. loop tuning spent fighting
physics we already have a model for.

The change in kind: **compute a slab target from physics and act on the energy
difference**, instead of integrating a room-temperature error. Feedforward has
no bandwidth to tune, so the slow modes stop being a control problem.

---

## 1. Slab state from RL — with the flow dependence made explicit

A circuit's return temperature is a *flow-dependent* proxy for slab
temperature, not a direct one. For the loop as a heat exchanger:

```
RL = T_slab + (VL − T_slab) · exp(−NTU)          NTU = UA_ws / (m_dot · c)
```

Three regimes, and conflating them is the source of the existing trouble:

| flow | RL reads | today |
|---|---|---|
| zero | **cabinet air** — the circuit is not measured at all | D-009; `rl_gate` exists for this |
| low, non-zero | **→ T_slab** (long residence, water equilibrates) | the useful regime |
| high | **→ VL** (short residence, little exchange) | carries little slab information |

**"RL ≈ cabinet air" is NOT a general stagnation test — it is emitter-
dependent.** A flowing circuit returns at `VL + ΔT`, so the signature is only
diagnostic when the emitter's expected ΔT is small compared to
`cabinet_air − VL`. Worked example from 2026-08-06, where that gap was
20.3 − 14.9 = 5.4 K:

| emitter | expected ΔT | verdict |
|---|---|---|
| floor loop | 1–3 K → returns 16–18 °C, clearly below cabinet | **discriminates** |
| fan coil (hk11) | ~5 K → returns ≈ 20 °C, same as cabinet | **cannot discriminate** |

Concluding hk11 was stagnant from that reading was wrong; the owner observed
flow directly. Any validity gate built on this signature must therefore know
each circuit's emitter type and its expected ΔT, or it will declare working
high-ΔT circuits invalid. That is an argument for the flow-based validity term
above rather than a temperature heuristic — and it is a constraint `rl_gate`
does not currently encode.

So the estimator is an inversion, not a reading:

```
T_slab = (RL − VL · e^(−NTU)) / (1 − e^(−NTU))
```

`NTU(opening)` is already on the §7.3 identification ladder ("per-circuit:
sweep opening at constant VL, record steady RL"). Until it is measured, the
low-flow approximation `T_slab ≈ RL` is usable in the low-flow regime only, and
the zero-flow case must still be excluded — which is what `rl_gate` does by
hand today and what §7.1's filters do natively by skipping the update.

**This is why `rl_gate` can eventually be retired rather than ported:** its job
becomes a validity term in the estimator, expressed in flow, instead of a timer.

## 2. Target slab temperature — feedforward from physics

Steady state requires floor emission to match room loss net of gains:

```
UA_sa · (T_slab − T_room)  =  UA_ao · (T_room − AT) − Q_sol − Q_int
```

Solved for the target, with the room's own setpoint as `T_room`:

```
T_slab_target = T_set + [ UA_ao · (T_set − AT_avg) − Q_sol − Q_int ] / UA_sa
```

Sign-correct in both modes without special-casing: in cooling `T_set − AT` is
negative, so the target sits *below* room temperature, and solar gain pushes it
lower still.

This is §4's `RL_curve` written with the gains included rather than folded into
a slope. `m = UA_ao / UA_sa ≈ 267.2 / 490 ≈ 0.55` house-wide from the current
parameters — but **`UA_ao` is a permit-calculation prior, not a measurement**
(recorded when `ua_ao`'s `kind` was corrected from `measured` to `prior`), and
it is house-level. Per-room `m` is the §7.3 refinement.

`AT_avg` should be the forecast-averaged outdoor temperature, not the
instantaneous one — the slab responds over hours, so feeding it a spot value
asks it to chase weather noise.

## 3. Per-room energy deficit

```
E_deficit,i = C_slab,i · (T_slab,i − T_slab_target,i)        [Wh]
```

`C_slab` is 8691 Wh/K total, split by floor area (§7.3 lists this split as
available now from the building survey). Positive deficit in cooling means the
slab holds more energy than it should, i.e. this room wants cooling.

Summing gives the house figure the plant should actually be sized against:

```
E_house = Σ E_deficit,i             [Wh]
P_required = E_house / t_horizon    [W]
```

`t_horizon` is a policy choice, not a physical constant — how fast we intend to
correct. It should be at least the fast mode (5.62 h) or the loop asks for
power the building cannot absorb.

## 4. Distribution — the change that matters most

**The current rule couples every circuit to the neediest one.** Normalising so
the peak circuit is fully open means a room far from satisfied drags everyone
else down: measured 2026-08-06, Wohnzimmer at demand 95 put the five satisfied
circuits at ~10 % before the flow floor lifted them to 24 %. Those circuits were
throttled not because they were satisfied in absolute terms but because
*another room was needier*.

That is the coupling to remove. Throttling is a cost (§4.4): it reduces total
flow, which raises spread, which pushes supply toward the condensation limit,
which forces the capacity loop to cut compressor frequency. Measured
2026-08-08 — throttling five circuits took the compressor from 77–85 Hz down to
62 Hz and supply from ~15 to 13.0 °C.

**CORRECTION 2026-08-08: that argument was one-sided.** An earlier version of
this section concluded "throttling a satisfied room therefore reduces the
energy available to the unsatisfied one." It ignores the other half, which the
owner pointed out and which was then measured: **the pump is fixed-speed, so
head follows the system curve.** Throttling raises Δp across the manifold and
pushes MORE flow through the circuits that stay open. Directly measured — hk01
at 20 % passed 0.2 l/min with seven circuits open and 0.5 l/min with five. Same
valve, same command, 2.5× the flow.

So throttling both **reduces** total flow and **redistributes** what remains
toward the circuits that need it. Which effect dominates depends on the pump
curve against the system curve, and **nobody here has measured that.** The
argument for absolute-deficit distribution does not rest on it: the case is
that a satisfied room should not be throttled *because another room is needier*
— which is a statement about control coupling, not about hydraulics. Do not
re-derive the one-sided version.

Proposed rule — absolute, not relative:

```
opening_i = clamp( E_deficit,i / E_band , min_open , 100 )
```

- deficit well above the band → **fully open**
- deficit near zero → proportional close, the band sized to the actuator so it
  does not chatter against a 150 s stroke
- deficit at or below zero → **minimum**, because delivering more is
  overcooling, which is the only legitimate reason to throttle

When the house is broadly short of energy — today's case — this opens
everything, which is both the physically correct answer (§4.4) and the one that
maximises what the source can deliver. Discrimination appears only near
equilibrium, where it is actually about distribution.

`eps` is untouched: it guards `0/0` in the existing normalisation and is not a
policy lever.

## 5. Source side — demand should drive the ceiling, not P04

`P_required` from §3 is a power. The plant's *modulating* actuator is the R32
frequency ceiling; P04 is coarse permission on a 30-minute cadence with a 2 K
dead zone (recorded 2026-08-02 — that allocation emerged rather than being
designed). So the demand figure should reach R32.

This replaces the `1 K / 30 min` water-setpoint trim, which is an arbitrary
stopgap aimed at the lever that no longer regulates.

Consequence worth stating: today the capacity loop raises frequency until supply
reaches the condensation limit, i.e. it always ends up riding the constraint.
With a power target it stops at what the house needs and only rides the limit
when demand exceeds what the limit permits. That leaves condensation margin
unspent on days that do not need it, and should reduce the restart plunges
measured on 2026-08-05/06.

## 6. What this retires

| today | becomes |
|---|---|
| `rl_gate` timers | a flow-based validity term in the estimator (§1) |
| `system_return_bias_c` | unnecessary — the target is absolute, from physics |
| room PID **or** return PID | both used: room setpoint sets the target, RL measures the state |
| `1 K / 30 min` P04 trim | `P_required` → R32 |
| peak-normalised distribution | absolute deficit per room (§4) |

## 7. Dependencies, honestly

Blocking, in rough order of how much they bite:

1. **`NTU(opening)` per circuit** (§1) — needs the opening sweep, which needs
   actuators verified to move. Until then §1 is limited to the low-flow
   approximation.
2. **Per-room `UA_ao`** — currently one house-level prior from the permit
   calculation. A single house-wide `m` will mis-target rooms with different
   exposure.
3. **VL/RL cross-calibration** — the manifold pair reads ~0.5 K below the heat
   pump's sensors. §1 differences VL and RL, so a bias between them propagates
   straight into `T_slab`.
4. **`C_slab` per-room split** — available from the survey, not yet extracted.
5. **Layer boundary.** The §2–§5 algebra is simple and stateless enough for
   layer 1: no filter, no network, degrades to sensible behaviour when inputs
   are missing. The *refinement* of `m`, `NTU`, `C_slab` and per-room `UA` is
   §7 Kalman work and belongs in layer 2, arriving as parameters. This split
   must be decided before implementation, not during it.

## 7a. Per-room assumptions that are known to be wrong

Entered 2026-08-06 with the floor areas from the building survey. Recording
them here because each is a silent error class, not a rough edge.

**Rooms are treated as thermally independent and NONE of them are** (owner,
2026-08-06). This was first written as "two of them are not", naming the
Luftraum between Arbeitszimmer and Wohnzimmer. That understated it: every room
couples to its neighbours through interior walls, and the Arbeitszimmer
boundary in particular is a **door that can be held open** for exactly this
heat exchange.

Rough scale, because it decides how much the per-room model is worth: an
interior wall of ~15 m² at U ≈ 1–2 W/(m²K) is 15–30 W/K per room pair, against
a Wohnzimmer envelope share of ~78 W/K. Non-negligible with doors closed. An
open doorway is convectively far larger and simply dominates — the two rooms
become one zone.

**Three consequences, and they point the same way:**

1. **Per-room distribution has limited authority.** Energy delivered to one
   room leaks to its neighbours at a rate comparable to its own envelope loss.
   Holding room A at 21 while B sits at 25 is not achievable by valve position
   when the two are coupled that strongly, whatever the deficits say.
2. **The house total is the robust quantity.** Inter-room flows are internal
   and cancel in the sum, so `house_excess_wh` is unaffected by coupling even
   though every per-room term is wrong. That is an argument for driving the
   SOURCE from the house figure and treating distribution as a second-order
   correction — which is also where the 2026-08-06 flat-distribution result
   landed from the flow side.
3. **The door is an actuator we do not model.** Its state changes the plant's
   topology, not just a parameter. Nothing reads it, so the model cannot know
   which building it is in. A door sensor would be worth more here than another
   temperature sensor.

The symptom of ignoring all this is a persistent innovation bias on the coupled
rooms rather than an obvious failure — which is why it is written down now
instead of being discovered as a puzzle later.

**A room is not one slab temperature — measured, not feared.** On 2026-08-08,
at full flow with every circuit commanded 100 % open, Wohnzimmer's four
circuits returned 21.49 / 21.63 / 22.56 / 24.35 °C — a **2.86 K spread inside
one room**. The two warmest are adjacent and were in direct sun on the floor,
so this is a spatially coherent solar signature rather than sensor error
(hk09 held +2.90 K with a stddev of 0.05 over 25 samples).

§3 computes one `E_deficit` per room from one slab temperature. For the four
single-circuit rooms that is exact. For Wohnzimmer it is an average over a
range wider than most of the corrections this document argues about, and the
error is not random — it tracks the sun, so it is largest exactly when cooling
demand is highest. Deciding whether the model goes per-CIRCUIT for
multi-circuit rooms is open; per-room stays right for the rest.

**Floor area is a poor proxy for envelope exposure.** UA is split by area, so a
corner room with two glazed façades gets the same W/K per m² as an interior
one. Wohnzimmer alone carries ~28 m² of the house's 51 m² of glazing on two
façades that see sun from dawn to mid-afternoon; the survey says explicitly
that "any per-room solar model that treats rooms as similar will be wrong about
this one specifically." Per-room UA is the §7.3 refinement that fixes it.

**Emitter type is not implied by floor area.** Arbeitszimmer is 31.20 m² with a
fan coil, no slab, on a floor that the 136.40 m² slab figure does not cover.
It now carries `emitter: fan_coil`, keeps its UA share, and is refused a slab
excess rather than being credited with 1987 Wh/K of storage it does not have.
A fan-coil room needs an air-capacity model; it does not have one yet.

## 8. What this does not solve

- **Cycling.** `freq_min_hz` = 30 exceeds the night load; the unit must cycle
  and no target changes that. Buffer volume is the answer, not control.
- **Dehumidification — REVISED 2026-08-06, the first version was too strong.**
  It said: with no hydraulic separation the fan coil is fed water the
  condensation guard holds above the house dew point, so it cannot condense on
  house air, and lower dew point needs ventilation or a standalone
  dehumidifier.

  That argument assumed ONE house dew point. The house is stratified: measured
  the same day, Arbeitszimmer sat at 16.5 while the ground floor was 13.4–13.6,
  nearly 3 K apart. The fan coil is at the top of the Luftraum, which is
  precisely where warm moist air collects — so supply at 14.9 °C *is* below the
  dew point of the air actually reaching it, and it does condense, into a
  drain.

  So the coil is a dehumidifier for the house, working on stratification rather
  than on mixed air, and an open door is what feeds it. What remains unknown is
  the RATE: whether moisture migrates upward fast enough to pull the ground
  floor's dew point down, and therefore whether this relaxes the condensation
  limit on the slab circuits. That is directly testable — run the coil hard and
  watch whether the ground-floor dew point follows — and it has not been done.
  The earlier claim that this path is structurally closed was wrong.
- **Sensorless rooms.** Four of seven rooms have no air temperature, so `T_set`
  is known but the *check* on whether the target was right is missing. The
  feedforward still works — that is the point of feedforward — but nothing
  detects a wrong `m`. Shelly H&T remains the fix.
