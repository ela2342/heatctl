# heatctl target design — whole-system control

Status: DRAFT for review. This document defines the target control design
for the full hydronic system (three heat sources, stratified buffer, DHW,
floor heating/cooling), the physical model and estimator behind it, and an
ordered implementation/validation roadmap. It is written so that each
numbered work package can be handed to an implementing agent with no
further context than this file, `PLAN.md`, `config.yaml` and
`docs/HARDWARE.md`.

Notation: VL = Vorlauf (supply), RL = Rücklauf (return), AT = outdoor
temperature, HP = heat pump, WWB = buffer tank (Warmwasserpuffer),
FWS = fresh-water station (DHW plate HX), °C everywhere, kW thermal
unless marked kW_el.

Items marked `ASSUMPTION:` reflect the system description as of
2026-07-26 and must be confirmed as the hydraulic build-out proceeds.

---

## 1. Plant inventory

### 1.1 Heat sources
| Source | Rating | Interface | Notes |
|---|---|---|---|
| Heat pump (PW58321 controller, "Easylife" series) | (nameplate TBD) | Modbus RTU 9600 8N1, addr 1, via Waveshare RS485 gateway 192.0.2.37 | Modes: DHW / Heating / Cooling / DHW+Heating / DHW+Cooling. Setpoints P03 (DHW 28–60), P04 (cooling 7–30), P05 (heating 15–50). Power = reg 0x0000 bit 0. Telemetry incl. return/leaving water, tank, ambient, compressor Hz + current + DC bus V (→ electrical power estimate), pump speed, fault flags (flow, pressure, anti-freeze). **Writes wear the controller's flash — write registers only on change, never periodically.** ≥200 ms between transactions, ≤120 regs/read. |
| Wood stove Lohberger AC105 | 18 kW total, split water/room-direct/cooking | Own pump + return-raising mixing valve (boiler anti-condensation) | Sits in the living room → its room-direct share is a large local disturbance. Water side charges the buffer. Manually fired: not schedulable, only detectable. |
| Electric element in buffer | 8 kW_el | TBD (contactor via WAGO DO? — open question §10) | COP 1; only sensible with PV surplus or as backup. |

### 1.2 Storage and distribution
| Component | Sensors/actuators | Notes |
|---|---|---|
| Buffer tank 1000 L, stratified | 5 temperature sensors (top→bottom), 8 kW element | Supports layered charging. Top zone serves DHW, mid/bottom serves floor heating and HP charging. |
| Floor heating manifold | Per-circuit RL sensors + proportional valves (WAGO 750-352; see `config.yaml`) | Feed: pump + 3-way mixing valve from buffer. 10 active circuits, 7 rooms. |
| FWS (DHW) | Pump + plate HX drawing from buffer top | On-demand; fast loop (100 ms) planned — PLAN.md Milestone 2; needs flow sensor. |
| HP return mixer | Mixing valve on HP return | ASSUMPTION: conditions the HP water-side return temperature (protect envelope / stabilize operation). Confirm intended function. |
| Mode selection valves | Multi-way valves | Switch HP between (a) charging buffer with hot water and (b) cooling the floor directly (bypassing buffer). |
| Solar PV | Existing small system; production visible in HA | No battery. PV surplus is the trigger for the 8 kW element and for load shifting. |

### 1.3 Environment sensors
- FineOffset WH65B weather station in HA: outdoor temp, humidity →
  dew point (`sensor.fineoffset_wh65b_210_dew_point`), solar-relevant data.
- PV production: usable as a free irradiance proxy for solar-gain
  estimation (large living-room windows → substantial gains).
- Room air: 2x surviving legacy wall units (interim), Shelly H&T (target);
  rooms without either run on the return-temperature fallback.

---

## 2. Control architecture: three layers

Extends the existing two-layer design (PLAN.md) by making the layering
explicit across the whole plant, not just the floor circuits.

```
Layer 0  Hardware failsafes.  WAGO Modbus watchdog (fallback must drive
         the analog outputs to FULL SCALE - valves are fail-open by design,
         see docs/HARDWARE.md and heatctl/safety.py); HP internal protections
         (flow, pressure, anti-freeze, overtemp); stove thermal-discharge
         safety and return-raising valve (self-acting); FWS scald limit.
         Work without any software.

Layer 1  heatctl (this repo).  Safety-critical, self-sufficient, boring.
         - Floor circuit control (cascade, §4)
         - Plant sequencing: operating-mode state machine (§3), pump and
           valve interlocks, HP start/stop + setpoint writes, e-heater
           enable, DHW fast loop.
         - Safety supervision last, always: clamps, dew point, screed
           limit, stale-data failsafe, single-writer ownership.
         Must keep the house safe and warm with layer 2, HA, and the
         network dead.

Layer 2  optimizer/ (separate process; may fail at any time).
         - State estimation: Kalman filters over the physical model (§6–7)
         - Forecasting: weather (Open-Meteo), PV, DHW usage pattern
         - Planning: which source, which storage, when (§8)
         - Talks to layer 1 ONLY via MQTT `heatctl/set/...`; every command
           is clamped by layer-1 safety and expires (TTL) so a dead
           optimizer degrades to the layer-1 defaults.
```

### 2.1 Single-writer ownership (hard rule)
Every actuator and writable register has exactly one writer:

| Resource | Writer | Migration note |
|---|---|---|
| WAGO valve outputs, pumps on WAGO | heatctl | already the plan |
| HP Modbus registers (power, mode, P03/P04/P05) | heatctl (once Milestone HP lands) | until then HA automations own reg 0 — heatctl must not write it (read-modify-write race). Migrate in one step, then disable the HA automations. |
| Mode-selection / mixer valves | heatctl | wiring TBD §10 |
| 8 kW element contactor | heatctl | commanded *value* may come from layer 2, clamped |

Layer 2 never touches hardware. HA never touches hardware (post-migration);
HA is UI + sensor source only.

### 2.2 MQTT contract (layer 2 → layer 1), additions
Existing: `heatctl/set/setpoint/<room>`, `heatctl/set/mode`.
New (all values clamped by safety, all with TTL — on expiry heatctl
reverts to its built-in defaults):

```
heatctl/set/plant_mode            requested operating mode (§3); heatctl may refuse
heatctl/set/buffer_target/<zone>  target temp for buffer top/mid zone
heatctl/set/vl_target             floor supply temp target (else curve default)
heatctl/set/rl_target/<room>      per-room return-temp target override
heatctl/set/eheater_power         0/half/full request for the 8 kW element
heatctl/status/...                heatctl publishes full plant state, mode,
                                  and *why* (active constraint) for each output
```

**Set topics must never be retained, and heatctl must ignore retained
messages on `heatctl/set/#`.** A retained set message is redelivered on every
broker reconnect, so it would look perpetually fresh and silently defeat the
TTL above — a dead optimizer would keep steering the plant forever. This is
the same failure mode as retained temperature topics defeating staleness
detection (see `docs/MODBUS2MQTT.md`); same rule, different direction.

Implementation note: `ControlPlane` in `heatctl/mqtt_plane.py` currently
applies commands immediately with no receive timestamp and no expiry sweep,
so TTL does not exist yet. Adding the new set topics above requires adding
both (per-command receive time + periodic expiry back to layer-1 defaults)
in the same change — otherwise the new topics are strictly less safe than the
two that exist today.

---

## 3. Operating modes and sequencing (layer 1)

### 3.1 Mode inventory
A plant mode is a consistent set of valve routings + source assignments.
ASSUMPTION on routings; verify against the final hydraulic scheme.

| Mode | HP | Buffer | Floor | DHW | Notes |
|---|---|---|---|---|---|
| `H_BUFFER` (winter default) | Heating → charges buffer (mid/bottom layers) | discharging to floor + DHW | fed from buffer via mixer | FWS from top | Stove, when lit, also charges buffer. |
| `H_DIRECT` (fallback/simple) | Heating → manifold directly (today's wiring) | bypassed / absent | fed by HP | — | Current interim state; keep supported forever as the degraded mode. |
| `C_DIRECT` (summer) | Cooling → floor directly, buffer bypassed | DHW zone only | chilled water, dew-point-limited | FWS from top; HP charges top on demand (mode DHW+Cooling) | |
| `DHW_BOOST` | DHW priority (HP mode 0 or 3/4) | top layer charge | unchanged | priority | Entered on low buffer-top temp; time-boxed. |
| `STOVE` (overlay, not exclusive) | HP inhibited or reduced | charged by stove | fed from buffer | from top | Detected, not commanded (§3.3). |
| `OFF/FROST` | off | — | frost protection only | — | |

Design rule: modes are few, explicit, and *statically verified*: each mode
lists required valve positions and which pumps run; heatctl refuses a mode
whose preconditions (valve end positions, sensor availability) are not
met, and publishes the refusal reason.

### 3.2 Transition rules
- Mode changes are rate-limited (min dwell, e.g. 15 min) and sequenced:
  stop source → wait pump run-down → move valves → verify → start source.
  No source ever runs against closed paths (HP flow-error protection is
  layer 0, not the plan).
- Heating↔cooling season switch: manual or layer-2 initiated, but always
  through `OFF` with a configurable lockout (hours), never direct.
- HP writes: on-change only (flash wear), sequence-numbered, and verified
  by read-back on the next poll cycle.

### 3.3 Stove detection and reaction (no stove telemetry assumed)
The stove is manually fired; control can only *detect* it:
- Detection: buffer layer temps rising with HP off and element off, and/or
  stove-loop VL sensor if one exists (§10), and/or living-room air rising
  fast above target.
- Reaction (layer 1, immediate):
  1. Inhibit/reduce HP (it would fight a free source).
  2. Living room floor circuits: widen the upper room-air tolerance band
     (e.g. from +0.5 K to +4 K) instead of closing valves — the slab keeps
     being conditioned by return-temp control, so the room does not crash
     when the stove burns down. Same mechanism serves solar-gain days
     (large windows): tie band widening to the estimated disturbance
     input, not to the stove specifically.
  3. DHW/e-heater deferred (buffer is being charged for free).

### 3.4 DHW
- Guarantee: buffer top zone ≥ configurable minimum (e.g. 47 °C) during
  comfort hours; `DHW_BOOST` entered below hysteresis.
- FWS: fast loop per PLAN.md Milestone 2 — feed-forward pump speed from
  flow, PID trims outlet temp; scald clamp is a safety rule.
- Legionella: weekly boost of top zone (HP disinfection function exists on
  the PW58321 — P17–P21 — but running it via our own schedule keeps one
  owner for the logic).

### 3.5 Cooling safety (design gap to close, port of existing HA logic)
- Chilled-water floor cooling requires dew-point supervision:
  `VL_cool_min = max(config.vl_min_cooling_c, dew_point + margin)` with
  the weather-station dew point via MQTT; stale data → fall back to the
  static clamp, and if configured, stop cooling (current HA behavior:
  stop + notify).
- The HP chilling setpoint (P04) follows the same rule; heatctl owns it
  post-migration.

---

## 4. Floor circuit control (layer 1) — cascade

Replaces the current either/or (room PID *or* return PID) with a cascade;
the inner loop always drives the valve.

```
outer loop (slow, per room, ~1 min):
    e_room = T_room_target − T_room
    RL_target = RL_curve(AT_avg) + k_room · e_room       # k_room ≈ 2–4 K/K
    band logic:
        e_room >  band_hi  → valve full open (skip inner loop)
        e_room < −band_lo  → valve closed   (skip inner loop)
        else               → inner loop active

inner loop (per circuit, ~1–3 min):
    e_rl = RL_target − RL_measured
    opening += kp_rl · e_rl · f(opening)   # gain scheduled by opening,
    clamp slew, clamp [min_stroke, max_cap], close below ~5 %
```

- `RL_curve(AT_avg)`: linear in the *forecast-averaged* outdoor
  temperature (window configurable, default 0–5 h ahead) between two
  configurable points, e.g. (AT +20 → RL 22) and (AT −20 → RL 40).
  Physical basis: steady state requires floor emission ∝ (RL − T_room) to
  match room loss ∝ (T_room − AT), i.e. `RL − T_room = m·(T_room − AT)`
  — the curve is just this line with a default slope; layer 2 can learn m
  per room from logged data (§7.3) and override via `rl_target`.
- Observability rule: a closed circuit's RL sensor reads slab ambient, not
  loop state. Periodically flush closed loops (interval scheduled by AT,
  order of 1–5 h) and re-measure during a fixed open window before
  trusting RL again. Without this, RL-based control acts on stale
  fiction. (A slab temp sensor per zone would remove the need — §10.)

  **This is already a live defect, not only a WP-C feature.**
  `Controller.step` in `heatctl/main.py` feeds `state.temps[sensor]` into the
  per-circuit return PID unconditionally, with no gating on valve position.
  And because every room currently has an empty `room_temp_topic`,
  `ControlPlane.room_temp` always returns `None`, so *all* control today runs
  through exactly that fallback path — i.e. the whole controller is presently
  acting on RL readings that are invalid whenever a valve is closed. A
  minimal mitigation (don't trust RL below some opening threshold; hold the
  last valid value or fall back to the curve default instead) is worth doing
  before WP-C, since the two wired PoC circuits will hit this immediately.
  See PLAN.md Milestone 1.
- Fallbacks (each is the same controller with a input frozen, not a
  different mode): no room sensor → outer loop frozen at curve default
  (heat only if AT forecast says the room needs it); no RL sensor → outer
  loop drives the valve directly with conservative gain; no AT → last
  known / static curve point.
- Hydraulic fairness: per-circuit `max_cap` (config) plays the role of a
  balancing valve; §7.4 defines how to measure the caps. Pump/heat demand
  = f(Σ openings) with on/off delays (exists as HA automation today;
  becomes heatctl's, Milestone 1).

### 4.1 Actuator dynamics — slow, deadbanded, no feedback
The Alpha 5 actuators have a **lower deadband** (they do not begin to open at
just any value above zero) and a **multi-minute stroke**, with no position
feedback (see `docs/HARDWARE.md`). The commanded value is a request; for
minutes after any change, true position is unknown. Five consequences, all
mandatory for WP-C:

1. **The inner loop must be absolute, not incremental** — this settles
   §10.9. An incremental law accumulates into a `opening` variable that is a
   *fiction*: it cannot be reconciled with a plant whose real position lags
   by minutes and is deadbanded at the bottom, and after a restart there is
   nothing truthful to re-seed it from (the register read-back is the last
   *command*, not the position, and the watchdog may have overwritten it with
   the failsafe value). Use absolute PI on `e_rl` with anti-windup and apply
   the gain scheduling `f(opening)` to the *output*. This also keeps the
   "restart == safe state" invariant intact with no rewording.
2. **Deadband compensation, from measured values.** Config per valve:
   `open_threshold_pct`, `full_open_pct`. Map controller demand 0–100 % onto
   `[open_threshold, full_open]`, and treat "closed" as a genuine 0, not as
   a small percentage. §4's earlier "close below ~5 %" is a guess and must be
   replaced by the measured threshold. Measurement procedure lives in
   `docs/HARDWARE.md`.
3. **Rate-limit control writes, but never safety writes.** Do not recompute
   and rewrite valve demand every 1 s loop: commanding faster than the
   actuator settles means reacting to a plant that has not yet responded,
   which winds the integrator up and oscillates. Update control-driven demand
   at most once per `settling_time_s` (and slew-limit the step). **Safety
   overrides must bypass this limiter entirely** — frost/overtemp/dew-point
   reactions still apply immediately. So the fast cycle stays fast for
   reading and safety; only the control path is throttled. Keeping
   `loop_interval_s: 1.0` is therefore correct and should not be slowed down
   to match the valve.
4. **Data taken while unsettled is poison for identification.** Log the
   commanded value plus a `settled` flag (`time_since_last_change >
   settling_time_s`) and exclude unsettled samples from every §7.3 fit —
   especially the NTU(opening) sweep, whose per-step dwell must exceed
   `settling_time_s` or it measures nothing. For the estimator (§7.1): during
   settling, flow is unknown, so treat RL as a **missing measurement** and
   skip the update step — the filters already handle that natively.
5. **The flush window (§4 observability rule) must be sized as
   `settling_time_s` + hydraulic transport time through the loop**, not just
   the valve stroke. Water still has to travel the circuit before RL means
   anything.

Note the useful side effect: rate limiting directly serves WP-C's own gate
("valve travel not higher" than the old controller).

### 4.2 Safety timing consequence (affects §3.5 and `safety.py`)
If valves need minutes to move, then **valve position is a slow lever and
cannot be the primary protection for any fast limit.** `Safety.apply` today
reacts to supply overtemp and dew-point violation by commanding 0 %, which
now means "and then wait minutes." For screed protection the slab's thermal
mass makes that tolerable. For condensation in cooling the exposure is real
but bounded: **decided 2026-07-26 that a few minutes below dew point is
acceptable** — the heat pump reacts to setpoint changes quickly and the screed's
mass rules out a fast surface excursion. So the response is to raise the
setpoint hard, not to stop circulation, and no inhibit-flag machinery is
needed.
**The heat pump's setpoint (P04) targets RETURN water, not supply.** Supply is
therefore never directly commanded — it is whatever the machine produces while
dragging return down to target, so the gap between them is the load-dependent
ΔT across the loop, not a fixed offset. Two consequences, both learned the hard
way on 2026-07-26:
- **No constant clamp on P04 can guarantee supply stays above dew point.** Only
  feedback on *measured* supply can. A clamp is a heuristic backstop; do not
  document it as a guarantee.
- **A low supply reading is not evidence of the pump undershooting.** With P04
  at 7 and supply at 10, the machine was running flat out and *failing* to
  reach 7 — the opposite reading of the same data.
Measured that day while restoring cooling: supply reached 14.3 °C against a
14.9 °C indoor dew point — an actual breach, because the setpoint had been
wound down to a value that is safe as a *return* target but not as a supply one.

Therefore: for cooling/dew-point violations the **source-side interlock is
primary** (stop the chiller / raise P04) and valve closure is secondary
backup — which matches the existing HA behavior noted in §3.5 ("stop + notify")
and is another reason WP-B (HP write ownership) gates real cooling operation.
Same logic applies to the global failsafe: `failsafe_valve_pct` and the WAGO
watchdog fallback both take minutes to take physical effect, so neither is a
fast protection — they are the last, slow line.

This section supersedes the "room PID with per-circuit fallback is the
whole strategy" wording in CLAUDE.md once implemented.

---

## 5. Why a model + estimator at all

The planning questions ("charge buffer now or at noon?", "preheat slab
with PV surplus?", "is the stove lit and how hard?") all reduce to:
*how much energy is stored where, and how fast does each store leak or
deliver?* Point sensors answer neither directly:
- 5 buffer sensors ≠ energy content without a stratification model,
- room air temp ≠ slab energy (the slab lags hours),
- stove heat input is unmeasured entirely.

So layer 2 maintains a physical state estimate (Kalman filter) over a
deliberately simple model. The model is **never** in the safety path;
layer 1 works on raw sensors alone.

---

## 6. Physical model (layer 2)

Keep every sub-model linear (or linearized) and low-order; identifiability
beats fidelity.

### 6.1 Room + slab: 3-state RC model per room
States: `T_air`, `T_env` (envelope/mass node), `T_slab`.

```
C_air  dT_air/dt = UA_ae·(T_env−T_air) + UA_sa·(T_slab−T_air)
                   + q_int + q_stove_dir(living room)
C_env  dT_env/dt = UA_ae·(T_air−T_env) + UA_eo·(AT−T_env) + a_sol·I_sol
C_slab dT_slab/dt = UA_ws·(T_wm−T_slab) − UA_sa·(T_slab−T_air)
```

- `T_wm` = mean loop water temp ≈ (VL+RL)/2 while flowing; RL itself is a
  measurement of the slab heat exchange: `RL ≈ T_slab + (VL−T_slab)·exp(−NTU)`
  per circuit; valve opening → flow → NTU (nonlinear but slowly varying;
  treat NTU(opening) as a lookup identified in §7.4).
- `I_sol`: solar irradiance proxy = own PV production (normalized), plus
  forecast for prediction; `a_sol` per room (large for the living room).
- `q_int`: lumped internal gains (people/appliances), small constant +
  estimated disturbance.
- `q_stove_dir`: stove direct radiation into the living room — estimated
  as a disturbance state (§7.2).

### 6.2 Buffer: 5-node stratified tank
One state per sensor zone `T_i` (i=1 top … 5 bottom), volumes `V_i` from
tank geometry:

```
ρc V_i dT_i/dt =  ṁ_charge·c·(T_in−T_i)[into its layer]
                + ṁ_discharge·c·(T_{i+1}−T_i)  (plug-flow between nodes)
                + k_mix·(T_{i−1}−T_i) + k_mix·(T_{i+1}−T_i)   (mixing/conduction)
                − UA_loss,i·(T_i − T_ambient)
                + P_el·η [element node]        + Q_stove [stove coil node]
```

Flows `ṁ` from pump states (and pump speed telemetry where available);
charge inlet layer depends on the active mode (layered charging).
Buffer energy content and "usable DHW/heating energy" are then linear
functions of the state — the planner's main quantities.

### 6.3 Heat pump: static map + telemetry
No dynamic model needed (its own controller handles dynamics). Model:
- `P_el ≈ g(f_comp, U_bus, I_comp)` from Modbus telemetry (0x801E, 0x8021,
  0x8025) — calibrate g once against an external meter if available.
- `Q_th = ṁ·c·(T_leaving − T_return)` from 0x8012/0x800E + pump speed.
- `COP(AT, T_leaving)` map: start from datasheet, refine by regression on
  logged (P_el, Q_th) pairs. The planner uses COP to price HP heat against
  the 8 kW element (COP 1) and stove (free but manual).

### 6.4 Stove: pure disturbance
`Q_stove` (water side) and `q_stove_dir` (room side) are estimated
disturbance states with slow random-walk dynamics — the filter infers them
from buffer/room residuals. If a stove-loop VL/RL sensor pair gets wired
(§10), `Q_stove` becomes measured and the estimate collapses to it.

---

## 7. Estimation and identification

### 7.1 Filter structure: decoupled, not monolithic
One Kalman filter per room (3 states + disturbance), one for the buffer
(5 states + Q_stove), all linear time-varying (matrices switch with pump/
valve/mode status). No giant coupled EKF — decoupled filters are
debuggable, individually validatable, and failure-isolated. Couplings
(VL temp, flows) enter as measured inputs, not shared states.

Practical choices:
- Discretize at 60 s. Process noise: small on temps, larger on
  disturbance states. Measurement noise from sensor spec (PT1000 ~0.1 K,
  air sensors ~0.3 K).
- Handle missing measurements natively (skip update step) — this is the
  normal case (RL invalid while valve closed, room sensor offline).
- **Validation gate**: publish innovation statistics per filter; a filter
  whose innovations are biased/non-white is mis-parameterized and its
  estimates must not be used by the planner (planner falls back to
  sensor-only heuristics).

### 7.2 What the filter buys concretely
- Slab energy state per room → preheat planning ("store 3 kWh in the
  bathroom floor before the PV peak ends").
- Buffer usable-energy split (DHW zone vs heating zone) → charge planning.
- Stove detection = `Q_stove` estimate crossing a threshold (better than
  ad-hoc temperature triggers, and gives magnitude).
- Solar gain now vs forecast → the band-widening reaction in §3.3.

### 7.3 Parameter identification ladder (per parameter: initial value → experiment → refinement)

| Parameter | Initial value from drawings | Dedicated experiment | Online refinement |
|---|---|---|---|
| Room `UA_eo` (loss) | U-values × areas from building drawings | Night decay: heating off, fit exponential of T_air (gives UA/C pairs) | regression on winter logs |
| `C_air`, `C_env` | air volume ×1.2 kJ/m³K; interior mass estimate | same decay fit (two time constants) | KF parameter augmentation, one at a time |
| `C_slab`, `UA_sa` | screed volume × ~2.0 MJ/m³K; ~6–11 W/m²K floor emission × area | step test: full-open heat pulse 2–4 h, observe T_air/RL trajectories | slope of RL vs room curves (m per room) |
| `UA_ws`, NTU(opening) | pipe length & spacing from floor plan | per-circuit: sweep opening at constant VL, record steady RL | slow drift tracking |
| `a_sol` | window area × g-value × orientation factor | clear-day, heating-off morning: regress T_air rise vs PV proxy | seasonal regression |
| Buffer `V_i`, `UA_loss` | tank drawing, insulation spec | standby test: 24 h no charge/discharge, fit losses + `k_mix` | continuous |
| HP COP map | datasheet | one charge run per AT bin, log (P_el, Q_th) | continuous regression |
| Hydraulic shares / max_cap | loop lengths | full-open test: all circuits open at fixed VL, compare per-loop RL rise rates; set caps to equalize | repeat seasonally |

Rule for the implementing agent: never fit more than two parameters from
one experiment; prefer experiments that isolate (valves closed elsewhere,
night-time, constant inputs). Every fitted value goes into
`optimizer/params.yaml` with date, experiment id, and confidence — never
hard-coded.

### 7.4 Data plumbing
`heatctl.sqlite` (already planned) is the single source: every cycle logs
sensors, outputs, mode, and active constraints. Layer 2 reads it read-only.
Add: HP telemetry poll (read-only Modbus is safe alongside HA today),
PV production, weather actuals. Retention: keep raw forever (it is tiny);
this is the 30-year system-identification asset.

---

## 8. Planning (layer 2) — energy storage and retrieval

State everything in kWh with temperature-window constraints:

| Store | Capacity (approx) | Charge via | Discharge via | Constraint window |
|---|---|---|---|---|
| Buffer heating zone | ~1000 L × ΔT·1.16 kWh/K → e.g. 35 kWh @ ΔT30 | HP (COP 3–5), stove (free), element (COP 1) | floor mixer | must stay above floor-VL need; below HP max |
| Buffer DHW zone (top) | ~10–15 kWh | HP DHW mode, stove, element | FWS | ≥ 47 °C comfort, ≤ 60 °C |
| Slab thermal mass (all rooms) | ~1–2 kWh/K per room, several K usable | floor circuits | passive to rooms | room comfort band ± tolerance, screed ≤ 45 °C VL |
| (no battery) | — | — | — | PV surplus is use-it-or-lose-it |

Planner v1 (heuristic, no MPC — matches PLAN.md Milestone 3):
ordered rules evaluated every 10–15 min, e.g.:
1. Comfort floors first: DHW zone below min → schedule `DHW_BOOST` at the
   best COP slot within the allowed delay.
2. PV surplus now and buffer/slab headroom → raise HP setpoint one step or
   enable element (element only if HP is maxed or COP < threshold... i.e.
   element is the *last* PV sink).
3. Stove detected → suppress HP, re-target its planned energy to later.
4. Cold snap in forecast → pre-charge buffer + preheat slabs during the
   warmest/PV-richest hours (COP and PV both favor daytime).
Each rule outputs at most a setpoint/mode *request* over MQTT with TTL.

Planner v2 (optional, only after v1 + validated models): linear MPC over
24–48 h, decision variables = HP power per slot, element power, mode
schedule; objective = grid import cost (or kWh) + comfort penalty;
constraints from §6 linear models. cvxpy, cold-startable, and still only
allowed to emit the same clamped MQTT requests.

---

## 9. Implementation roadmap (work packages with validation gates)

Extends PLAN.md; Milestones 0–2 there stay unchanged and come first.
Each WP lists: deliverable → validation gate (must pass before the next
WP builds on it). An implementing agent should do exactly one WP per
branch/PR.

**WP-A HP integration (read-only)** — `heatctl/backends/hp_pw58321.py`:
poll telemetry set into state DB + MQTT status. No writes.
*Gate:* 48 h of clean telemetry; poll spacing ≥200 ms verified; zero
writes on the bus (verify with HA logs); values plausible vs HP display.

**WP-B HP write ownership migration** — implement heat-demand logic +
power/mode/setpoint writes with on-change-only policy and read-back
verify; disable the two HA pump automations and the HA side of the
condensation automation in the same change.
*Gate:* one week of operation; register write count < 20/day; behavior
matches the old automations (pump on above valve-opening threshold, dew
point clamp active); race test: confirm HA no longer writes reg 0.

**WP-C Cascade room control** — restructure `main.py` control step per §4
(outer/inner loops, bands, flushing, fallbacks) and §4.1 (absolute inner
loop, deadband compensation, rate/slew limiting with a safety bypass,
`settled` flagging); config schema for curve points, k_room, bands, caps,
flush intervals, and per-valve `open_threshold_pct` / `full_open_pct` /
`settling_time_s`.
*Prerequisite:* the §4.1 actuator values measured per `docs/HARDWARE.md`.
*Gate:* unit tests for every branch (bands, fallbacks, flush timer,
deadband mapping, rate limiter **including that safety overrides bypass it**);
2-week A/B on the two wired rooms vs old controller: comfort (time in
±0.5 K) not worse, valve travel not higher; every safety test still green.

**WP-D Plant mode state machine** — §3 modes, transitions, interlocks,
stove overlay, DHW guarantee. Initially only `H_DIRECT`/`OFF` are
reachable (matching real hydraulics today); other modes land behind
config flags as the hardware arrives.
*Gate:* state machine model-checked by tests (no transition bypasses
sequencing; refusal paths covered); dry-run mode logs intended actions
for a week and they are reviewed as sensible.

**WP-E Telemetry/logging completion** — sqlite schema covering §7.4
(sensors, outputs, mode, constraints, HP, PV, weather actuals).
*Gate:* one month of gap-free data; disk growth within budget;
a notebook reproduces basic plots from it.

**WP-F optimizer/ scaffold + buffer & room filters** — decoupled KFs per
§7.1 with parameters from drawings (§7.3 initial column), publishing
estimates + innovation stats to MQTT (status only, no set commands yet).
*Gate:* innovation whiteness/bias within bounds for ≥2 weeks on ≥2 rooms
and the buffer; estimated buffer energy consistent with charge/discharge
events to ±15 %.

**WP-G Identification experiments** — implement the §7.3 experiment
runner as supervised scripts (operator-triggered, layer 1 enforces safety
during runs), results into `optimizer/params.yaml`.
*Gate:* each experiment yields parameters with stated confidence; KF
innovations improve (quantified) after parameter update.

**WP-H Planner v1 (heuristics)** — §8 rules → MQTT requests with TTL.
*Gate:* two comparison weeks: measured grid import per heating-degree-day
vs pre-planner baseline; no comfort violations; layer 1 rejected zero
out-of-clamp commands (or the rejections are understood).

**WP-I Planner v2 (MPC)** — optional, only if v1's ceiling is measured
and the models are validated.
*Gate:* backtest on logged data beats v1 in simulation before touching
the house.

Cross-cutting definition of done for every WP: type-annotated, tested,
no new pinned deps without justification, docs updated (this file +
HARDWARE.md), degraded-mode behavior stated explicitly.

---

## 10. Open questions / hardware gaps (answer before the affected WP)

1. Wiring/ownership of the new actuators: buffer element contactor, mode
   multi-way valves, floor mixing valve, FWS pump, HP return mixer — which
   land on WAGO terminals (need DO/AO inventory, likely more 750-x
   modules) vs elsewhere? (blocks WP-D beyond dry-run)
2. Buffer's 5 sensors: wired to WAGO (which terminals) or elsewhere?
   (blocks WP-F buffer filter)
3. Stove loop instrumentation: is a VL/RL pair + pump status feasible?
   Cheap and collapses the largest unmeasured disturbance (§6.4).
4. HP return mixer: confirm intended function and control authority.
5. Nameplate data: HP thermal rating + datasheet COP table; buffer
   geometry/insulation; screed thickness per room; window areas/g-values
   (for §7.3 initial values — building drawings to be digested into
   `optimizer/params.yaml`).
6. Heat metering: even one clamp-on ultrasonic heat meter (or VL/RL+flow
   on the HP loop) would anchor COP and buffer models absolutely —
   worth the investment?
7. Slab temperature sensors (1 per key zone, in-screed or surface):
   optional, but would remove the flushing/observability workaround for
   those zones (§4) and sharpen the slab-storage estimate.
8. Tariff: fixed price or dynamic? (changes planner objective only, §8.)
9. ~~Incremental inner loop vs. the restart invariant.~~ **RESOLVED
   2026-07-26 — use an absolute inner loop.** The actuator constraint decides
   it: the valves are deadbanded and take minutes to stroke, with no position
   feedback, so an incremental law's accumulated `opening` cannot be
   reconciled with reality and has nothing truthful to re-seed from after a
   restart. Absolute PI on `e_rl` + anti-windup, gain scheduling applied to
   the output. See §4.1 item 1; the restart invariant stands unchanged.
   Remaining sub-question (measurement, not design): the actual
   `open_threshold_pct` / `full_open_pct` / `settling_time_s` values —
   procedure in `docs/HARDWARE.md`, must be measured before WP-C.
