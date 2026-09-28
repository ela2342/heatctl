# Estimation and planning — the control overhaul

**Status: AGREED, being implemented.** Written 2026-09-28 with the owner.
Supersedes DESIGN.md §7.1 (decoupled filters) and §8 (heuristic planner, then
MPC), and the setpoint half of §2.2. Builds on DESIGN_ENERGY_DEMAND.md, whose
§1–§3 run today in `heatctl/energy.py`; its §4 (valves distributed by energy
deficit) is implemented here as part of the overhaul.

The principles are in `docs/DECISIONS.md`, argued there and referenced here
by ID: **D-048** (mode is a season, charge is a control), **D-049** (what the
layer split is for, and the plan interface), **D-050** (one coupled filter).
This file is the design, not the argument.

---

## 0. Why now

Two incidents in three days, opposite in sign and identical in shape:

| | mode | what happened | stored energy at the time |
|---|---|---|---|
| 2026-09-25 | heating | the trim walked P05 20 → 25 while the house was cold; the house reached 27 °C | `house_blocked_wh` **+66 757** |
| 2026-09-28 | cooling | three days later, P04 at its 15 °C floor, one warm room (Arbeitszimmer) holding peak demand at 100; Badezimmer 2.9 K under setpoint | `house_blocked_wh` **−85 899** |

About 150 kWh was moved through the slab in three days and it overshot both
ways. In each case the mode was right when it was chosen. What was missing:

1. **Nothing bounded the charge.** The trim's back-off requires the most
   demanding valve to be nearly idle; one room held it open.
2. **Nothing looked ahead.** Layer 1 reacts to air temperature, which lags the
   slab by hours; the slow mode is ~55 h.

`auto_mode` does not answer either (owner, 2026-09-25: *"it will just lead
to cycling"*) — see D-048.

---

## 1. Architecture

```
               forecast (Open-Meteo), all sensors
                              │
  Layer 2  ┌──────────────────▼──────────────────┐   separate process,
  optimizer│ estimator: one coupled KF (§2)      │   may die at any time
           │ planner:   72 h QP, hourly (§3)     │
           └──────────────────┬──────────────────┘
                              │ heatctl/set/plan   — elements with expiry (§4)
                              │ heatctl/opt/state  — estimates + innovations
  Layer 1  ┌──────────────────▼──────────────────┐   1 s loop, safety last
  heatctl  │ slab-target tracking (§5)           │
           │   valves  ← per-room slab deficit   │
           │   P04/P05 ← house slab deficit      │
           │ constraints: dew point, compressor  │
           │   ceiling, frost, screed, flow floor│
           │ fallback when the plan is stale:    │
           │   own slab targets + charging gate  │
           └─────────────────────────────────────┘
```

Timescales decide the split (D-030): seconds to minutes in layer 1, hours to
days in layer 2. Failure domains make it necessary (D-049): the forecast
needs the internet, a filter can diverge, a planner can emit nonsense, and a
matrix exponential in heatctl's single event loop would stall the 1 s cycle.

---

## 2. The estimator

One linear Kalman filter over the whole house, 60 s steps, the existing
pure-Python `optimizer/kalman.py` (Joseph form, native missing measurements,
Van Loan ZOH). Linear time-varying: matrices switch with valve openings and
plant mode.

### 2.1 States

| block | states | n |
|---|---|---|
| room air | `T_air,r` for each of 7 rooms | 7 |
| slab | `T_slab,r` for the 6 slab rooms (Arbeitszimmer is a fan coil, D-046) | 6 |
| disturbances | forecast outdoor bias `b_out`; solar gain factor `k_sol` | 2 |
| augmented parameters | released **one at a time** (§2.5) | 0–4 |

15–19 states. The slow mode (~55 h) and fast mode (~6 h) are **properties of
this model**, computed by `eigen_time_constants_h()` generalised to the full
matrix — never quoted (D-031).

Wohnzimmer's four circuits spread 2.86 K under sun. One slab node per room is
the starting point; splitting Wohnzimmer is a later question for the
innovations to answer, not a guess to build in.

### 2.2 Dynamics

Per room, extending `optimizer/model.py`:

```
C_air,r  dT_air,r  = UA_ao,r (T_out − T_air,r) + UA_sa,r (T_slab,r − T_air,r)
                   + Σ_n UA_nb,rn (T_air,n − T_air,r)
                   + f_sol k_sol q_sol,r + q_int,r
C_slab,r dT_slab,r = Q_r − UA_sa,r (T_slab,r − T_air,r) − UA_sg,r (T_slab,r − T_ground)
                   + (1 − f_sol) k_sol q_sol,r
```

* `T_out` is the station reading when fresh, else forecast + `b_out`.
* `q_sol,r` per room from `optimizer/solar.py`, as today.
* `UA_nb,rn` from shared interior wall areas × partition U (DESIGN §6.1).
  **Prerequisite, owner task:** the wall areas by hand, because automated
  take-off from the plans failed.
* Per-room UA and capacities split from the house values by floor area and
  exposure, as `energy.py` already does; `params.yaml` holds them with sigma
  and provenance (D-032).

### 2.3 Heat input — without a heat meter

```
Q_r = Σ_circuits  ṁ_i c_p (VL − RL_i)          only while rl_gate says MEASURE
ṁ_i = flow_scale · f(opening_i)                 valve map, D-041
```

This replaces "compressor current × flat COP 3.35", which is wrong on both
counts: the measured COP is 1.69, and the current path is **mode-blind** — in
cooling it books compressor power into the slab as heat (the bug in
`optimizer/estimator.py heat_input_w`, fixed in phase 1). With `ṁ·ΔT` the sign
is physical in both modes.

`flow_scale` is not identifiable without a meter: it is confounded with
`UA_sa` through NTU. **So it stays fixed at its prior** and `UA_sa` is
identified relative to it. The consequence is an energy-scale error, which in
closed loop is an actuator-gain error, which hourly replanning against
measured slab temperatures corrects (§5.3).

### 2.4 Measurements

| sensor | equation | when | R |
|---|---|---|---|
| room air (Shelly, WH32) | `z = T_air,r` | on each sample | noise² + q²/12, q = report step (0.5 K today) |
| silent battery Shelly | `|T_air,r − last| < q` | between samples | as a bounded pseudo-measurement |
| circuit return | `RL_i = a_i T_slab,r + (1 − a_i) VL` | rl_gate MEASURE | PT1000 0.1 K |
| `vl_total`, `rl_total`, HP return/leaving water | inputs and consistency checks | always | 0.1 K / 0.5 K |
| outdoor station | `z = T_out` (identifies `b_out`) | on sample | station spec |

The **return equation is the big gain**: it is the first direct measurement of
the slab. `a_i = 1 − exp(−NTU_i)` is learned per circuit and opening band
(BACKLOG `NTU(opening)`); until learned it starts from the D-042 regime table.
When a circuit is idle there is no update and the model carries its slab —
that is the reason to have a model.

**Event-triggered sensors.** A battery Shelly reports on a 0.5 K change or
every 7200 s. Its silence is information: the room has not moved 0.5 K.
Treating silence as "nothing known" biases the fit toward fast dynamics
(BACKLOG). The owner will improve resolution and cadence; that changes `q`
and nothing structural.

### 2.5 Parameters and identification

Augmented states with random-walk noise derived from their expected drift
(D-032, WP-R(c)), released one at a time, each only after the previous one's
innovations are white:

1. `UA_sa` — at night first (`f_sol` and `UA_sa` are confounded in daylight,
   WP-R(b)); the free-decay experiment (BACKLOG Now #4) gives it excitation.
2. `UA_ao` — prior 216 ± 18 W/K (D-028).
3. `f_sol`.
4. `flow_scale` — **only once the heat meter exists** (§6).

"Bad control data identifies the controller" (WP-R(d)): identification runs
on periods where the actuation was not itself a function of the estimate.

### 2.6 Flushing as a measurement decision

The Controme system this project replaced flushed each circuit periodically
so its return reading would not go stale; `rl_gate` does the same today on a
fixed 3600 s (`flush_interval_s`). With a filter, staleness is a number:
each slab state's variance. **A circuit is flushed when its slab variance
exceeds a threshold**, not on a timer — rooms the model predicts well are
left alone, rooms it is unsure of are sampled. The fixed timer stays as the
fallback when layer 2 is stale.

The **coast state** (§3.2) observes every slab for free: source stopped,
valves parked open (D-025/`off_valve_pct`), pump running. The water
equilibrates with the slabs and every return is valid. It is also the most
common correct state in the shoulder season.

### 2.7 Outputs and validation

Published under `heatctl/opt/state/...`: per-room `T_slab`, `T_air`, their
sigmas, energy vs target, innovation mean / sd / lag-1 per sensor.

**Gate before anything consumes it** (WP-F, unchanged in spirit): per-room
innovations unbiased and white for two weeks; slab estimates agree with
returns whenever a circuit flows; replay over the archive (§7) first.
Innovations are published **per room** even from one coupled filter, so a bad
room is visible on its own — the part of DESIGN §7.1's argument that survives.

---

## 3. The planner

### 3.1 Formulation

Every hour, over 72 hourly steps:

* **Decision** `u_k`: heat rate into the slabs, W. Positive heats, negative
  cools. Box limits from the forecast: heating capacity at forecast outdoor
  temperature; cooling capacity bounded by the condensation limit at the
  **measured** dew point held flat (never the forecast dew point — it is
  biased the dangerous way, BACKLOG).
* **Prediction**: the model is linear, so predicted room temperatures are
  `T = T_free + G u`, `G` the step-response matrix of the current linearised
  model, `T_free` the response to forecast weather with `u = 0`.
* **Objective**:
  - comfort: quadratic penalty outside each room's band `[sp − 0.5, sp + 1.0]`
    (band edges are config policy);
  - energy: `Σ |u_k| / COP(T_out,k)`;
  - **sign change**: a heavy penalty on `u` changing sign, plus a minimum
    block length of 24 h for either sign. This is where "no cycling" is
    built, not bolted on (D-048);
  - terminal: slab energy at step 72 vs the steady-state target for the
    forecast's last day — covers the tail of the 55 h mode the horizon cannot.
* **Solver**: a box-constrained QP in 72 variables, projected gradient, pure
  Python. No cvxpy, no numpy — the runtime set stays pymodbus + PyYAML +
  aiomqtt.

72 h is ~1.3 slow-mode time constants; forecast error past 48 h is handled by
replanning every hour, not by trusting day three.

### 3.2 From heat rate to mode: heat, cool, or coast

The plan's `u` is signed, and three regimes fall out of it:

| plan over the next ≥24 h | mode recommendation |
|---|---|
| net heat needed | `heating` |
| net cooling needed | `cooling` |
| `u ≈ 0` holds the band | **coast** — `off`, valves open, pump running |

Coast is not a failure to decide. With up to 60 kWh/day of solar gain and a
55 h mass, it is the usual correct answer in spring and autumn.

**Mode changes stay manual at first** (owner, 2026-09-28): the planner
publishes a recommendation and the owner switches. Automatic switching is a
later step, allowed only when the plan wants the other sign for ≥24 h.

### 3.3 Outputs

`heatctl/opt/plan/...`: the 72 h trajectories (u, predicted room and slab
temperatures, bands) for Grafana, and the mode recommendation. In shadow
mode (phase 4) that is all; from phase 5 the executable part also goes to
`heatctl/set/plan` (§4).

---

## 4. The interface: `heatctl/set/plan`

Replaces the one scalar (`opt/setpoint_delta`), which cannot express "coast
until 03:00, then charge" (BACKLOG).

A JSON document of hourly elements:

```json
{"generated": 1790575200,
 "elements": [
   {"start": 1790575200, "expires": 1790582400,
    "slab_target_c": {"wohnzimmer": 23.4, "badezimmer": 24.1, ...},
    "house_heat_w": -1200,
    "mode_recommendation": "cooling"},
   ...]}
```

* Layer 1 executes **the element covering now**, and only while
  `now < expires`. Each element expires on its own, so a dead optimizer
  degrades one hour at a time to the fallback (§5.2) — never to an old plan.
* **Not retained, and retained copies are ignored** (DESIGN §2.2's rule,
  unchanged): a retained plan would look fresh on every reconnect.
* Everything is clamped by layer 1: slab targets to the condensation floor
  (D-046) and the screed limit; the water setpoint by the existing trim bounds
  and cadence. Safety reads none of it (principle 5).
* `mode_recommendation` is published, never applied, until the owner enables
  automatic switching.

---

## 5. Layer 1: tracking slab targets

### 5.1 The setpoint variable is slab temperature

```
room air setpoint ──►  slab target per room  ──►  valves + water setpoint
   (the objective)      (plan, or layer 1's own     (layer 1 tracks it)
                         algebra when stale)
```

* **Valves**: distributed by each room's slab energy deficit against its
  target — DESIGN_ENERGY_DEMAND §4. The room PID stops being the primary valve
  driver; it stays for Arbeitszimmer (no slab) and as the fallback when no
  slab estimate is usable. D-017's normalisation (most-demanding circuit fully
  open) is kept, applied to the deficits.
* **Water setpoint**: follows the house's total slab deficit and, when a plan
  is fresh, its `house_heat_w`, inside the existing 1 K / 30 min trim and the
  flash-write budget (D-013, D-018).
* **Constraints are unchanged and still win**: supply vs dew point, the
  compressor ceiling, frost, screed overtemperature, the flow floor, safety
  last.

### 5.2 The fallback, with layer 2 dead

The same loops with a worse target: `energy.slab_target_c` (holding term from
outdoor, solar and setpoint; slow recovery term from room air) instead of the
plan's. The slab signal is the gated returns **smoothed over hours** — the
slab cannot move faster than that, and the raw return moves with the water
within minutes, which is the trap behind the 78-minute `auto_mode`
oscillation of 2026-08-19 (LOGBOOK).

### 5.3 The charging gate — phase 0, and permanent

The part that stops the oscillation now, before any of the above exists:

> **While the smoothed house slab energy is past target in the current mode's
> charging direction and the house air is not asking for more, the trim steps
> the water setpoint toward neutral on its normal cadence, whatever the valves
> say.**

* It changes the back-off branch only: today that branch requires the most
  demanding valve at ≤`idle_pct`, and one warm room defeats it (both
  incidents). The charging branch is untouched — it already requires the air
  to want more.
* Air over-shoot past the band also triggers it, so it works with the energy
  model blind.
* It never switches the mode. It only moves the setpoint toward neutral, so
  it cannot drive the plant into the other season.
* "Air not asking for more" is what stops it fighting an August pre-charge:
  a cold slab under a warm house keeps cooling.
* Smoothing: first-order, 1 h (`gate_smoothing_s`) — 20× the water loop's
  1–3 min, 6× below the ~6 h fast mode, so it rejects the return's reaction to
  the actuator but not slab motion.
* Band: `overcharge_slab_k`, 1 K of whole slab — the water setpoint's own
  resolution; a finer band asks the trim to resolve what its actuator cannot.

When a plan is fresh, the plan's targets replace `energy.slab_target_c` in the
same gate; the gate stays as layer 1's own guarantee.

---

## 6. When the heat meter arrives

A MULTICAL 403 (or equivalent) on the **total supply line** adds one
measurement: total flow and total heat. Nothing structural changes:

1. `flow_scale` becomes measured (`params.yaml` kind `measured`, D-032) — and
   with it `UA_sa` separates from flow.
2. The manifold supply/return offset (manifold ΔT ≈ 0.807 × the unit's)
   becomes calibratable in the live plant, which has failed three ways
   without a reference (LOGBOOK).
3. Energy figures become absolute rather than relative.
4. With an electricity meter as well, measured COP replaces the table.

**Decide before buying:** placement (total supply, or it answers a different
question — BACKLOG) and the communication module, which decides whether data
reaches the broker without new hardware on the PFC. The replay harness
simulates the meter from day one so the code path is tested before it
exists.

---

## 7. Phases, each with a gate

| # | what | gate |
|---|---|---|
| 0 | charging gate in the trim (§5.3); sustained-deviation alarm | unit tests incl. both incidents replayed, mutation-verified; deployed |
| 1 | fix `heat_input_w` mode-blindness; wall areas (owner); HA read on `roomtemp/#` | — |
| 2 | replay harness over the InfluxDB archive; coupled filter v2 against it; then deployed observe-only | per-room innovations white 2 weeks; slab vs flowing returns agree |
| 3 | identification: free decay for `UA_sa`, then parameters one at a time | each parameter improves innovations, quantified |
| 4 | planner in shadow; 24/48/72 h predictions scored against outcome | prediction skill stated per horizon, ~2 weeks |
| 5 | `set/plan` with per-element expiry; valves on slab deficit; trim becomes fallback | a week of closed loop, zero out-of-clamp rejections not understood |
| 6 | automatic mode switching (owner decision) | — |

Where layer 2 runs: in its own low-priority container on the PFC, with its
CPU measured; the HA host is the fallback if it does not fit.
