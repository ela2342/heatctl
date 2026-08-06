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

That is the coupling to remove. Throttling is a cost (§4.4) and it buys nothing
here: it reduces total flow, which raises spread, which pushes supply toward the
condensation limit, which forces the capacity loop to cut compressor frequency.
**Throttling a satisfied room therefore reduces the energy available to the
unsatisfied one.**

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

## 8. What this does not solve

- **Cycling.** `freq_min_hz` = 30 exceeds the night load; the unit must cycle
  and no target changes that. Buffer volume is the answer, not control.
- **Dehumidification.** With no hydraulic separation the fan coil is fed water
  the condensation guard holds above the house dew point, so it cannot condense
  on house air. Lower dew point needs ventilation or a standalone dehumidifier.
- **Sensorless rooms.** Four of seven rooms have no air temperature, so `T_set`
  is known but the *check* on whether the target was right is missing. The
  feedforward still works — that is the point of feedforward — but nothing
  detects a wrong `m`. Shelly H&T remains the fix.
