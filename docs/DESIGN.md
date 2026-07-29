# heatctl target design — whole-system control

Status: DRAFT for review. This document defines the target control design
for the full hydronic system (three heat sources, stratified buffer, DHW,
floor heating/cooling), the physical model and estimator behind it, and an
ordered implementation/validation roadmap. It is written so that each
numbered work package can be handed to an implementing agent with no
further context than this file, `ROADMAP.md`, `config.yaml` and
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
| Heat pump (PW58321 controller) = **Blaupunkt BLP08P1V1MR32** — **full register map: `docs/HEATPUMP.md`** | 8.4 kW heat / 6.0 kW cool, 3.6 kW_el max, R32, 1~230 V | Modbus RTU 9600 8N1, addr 1, via Waveshare RS485 gateway 192.0.2.37 | Modes: DHW / Heating / Cooling / DHW+Heating / DHW+Cooling. Setpoints P03 (DHW 28–60), P04 (cooling 7–30), P05 (heating 15–50). Power = reg 0x0000 bit 0. Telemetry incl. return/leaving water, tank, ambient, compressor Hz + current + DC bus V (→ electrical power estimate), pump speed, fault flags (flow, pressure, anti-freeze). **Writes wear the controller's flash — write registers only on change, never periodically.** ≥200 ms between transactions, ≤120 regs/read. |
| Wood stove **Lohberger Varioline AC 105** (series "AquaTherm Combi"; the Baubeschreibung's "La Nordica Termorosa XXL" is a stale 2021 planning entry) | **14 kW total = 10.5 kW water + 3.5 kW room-direct** at nominal; **8.0 = 7.0 + 1.0** at part load. Efficiency 76 %. *Not 18 kW — that figure was wrong.* Split is switched by grate height (Füll-/Flachfeuerung) and the Kessel-/Kochbetrieb flap, not continuously variable. | **Pump is NOT integral** — it is in the optional "Installationspaket" mounted on the rear, and Lohberger publishes **no pump model, flow rate or curve**. Return-temperature raising required: ≥55 °C at the return stub, ideal 60 °C. Water content **25 L**. Buffer store mandatory. | **External air duct IS fitted** (owner). The EN 16510 type B/BE "raumluftabhängig" classification is a **backdraught-safety** class, not a statement about where the air comes from: the path is not fully *sealed*, so a pressure differential — a kitchen extractor is the classic case — can pull flue gas into the room, which is why forced ventilation needs an interlock. **For the energy model, assume external combustion air: `n` is not materially raised by firing, and the residual leakage error is small** (owner's assessment, and it matches the physics — a duct-fed firebox draws its air from outside in normal operation). The certification matters for SAFETY interlocks, not for the thermal balance. Batch-fired: ~3.7 kg charge → ~60 min burn, classified intermittent; no published output-vs-time curve. **No electrical interface at all** — no bus, no status contact, only a mechanical pump thermostat (~55 °C). Sits in the living room → its room-direct share is a large local disturbance. Manually fired: not schedulable, only detectable. |
| Electric element in buffer | 8 kW_el | TBD (contactor via WAGO DO? — open question §10) | COP 1; only sensible with PV surplus or as backup. |

### 1.2 Storage and distribution
| Component | Sensors/actuators | Notes |
|---|---|---|
| Buffer tank 1000 L, stratified | 5 temperature sensors (top→bottom), 8 kW element | Supports layered charging. Top zone serves DHW, mid/bottom serves floor heating and HP charging. |
| Floor heating manifold | Per-circuit RL sensors + proportional valves (WAGO 750-352; see `config.yaml`) | Feed: pump + 3-way mixing valve from buffer. 10 active circuits, 7 rooms. |
| FWS (DHW) | Pump + plate HX drawing from buffer top | On-demand; fast loop (100 ms) planned — ROADMAP.md Milestone 2; needs flow sensor. |
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

Extends the existing two-layer design (ROADMAP.md) by making the layering
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
- FWS: fast loop per ROADMAP.md Milestone 2 — feed-forward pump speed from
  flow, PID trims outlet temp; scald clamp is a safety rule.
- Legionella: weekly boost of top zone (HP disinfection function exists on
  the PW58321 — P17–P21 — but running it via our own schedule keeps one
  owner for the logic).

### 3.5 Cooling safety (design gap to close, port of existing HA logic)
- Chilled-water floor cooling requires dew-point supervision.
  **IMPLEMENTED 2026-07-27, and deliberately NOT as first specified here.**
  Two changes, both from measurement:

  1. `VL_cool_min = dew_point + margin`, **not**
     `max(config.vl_min_cooling_c, dew_point + margin)`. Taking the max makes
     live data useless in the dry direction — it can only tighten the static
     guess, never relax it. Measured: an 11.4 °C indoor dew point was being
     clamped to 16.0 °C, holding circuits shut with 4.6 K of headroom spare.
  2. **INDOOR dew point, not the weather station.** Outdoor is frequently
     higher and would forbid cooling that is perfectly safe indoors. Source is
     the highest indoor dew point across rooms reporting humidity, with
     outdoor only as a last-resort fallback.

  On a stale or missing reading heatctl now **stops cooling**
  (`cooling_requires_dew_point`, default on) rather than falling back to the
  static clamp. The static `vl_min_cooling_c` arrived undocumented in the
  initial commit and is **not** conservative — a 26 °C room at 60 % RH has a
  dew point of 17.6 °C, above it. It looks like a safe floor and is not one.
  This also covers the case the HA-side automation cannot: if the dew point
  is missing *because Home Assistant died*, its source-side pump shutdown
  died with it, and the valve side is the only protection left.

  The margin is empirical — it matches the HA loop that has run without
  condensation. Note it is a margin on the *right* quantity, though:
  **the floor build-up is vapour-permeable, so condensation is not confined
  to the visible floor surface. Moist air reaches into the slab and condenses
  throughout it, including directly on the pipe wall** — and the pipe wall
  sits essentially at the water temperature. So supply water temperature is
  very nearly the surface that matters, not a proxy for it standing off behind
  a screed gradient. There is no hidden reserve to lean on.

  Two consequences worth stating plainly:
  - The margin covers measurement uncertainty and the spatial spread of indoor
    dew point between rooms. It does not need to cover a screed gradient,
    because there effectively is not one at the relevant surface.
  - Condensation inside the slab is invisible. Nobody will notice a wet patch
    and intervene, which is a further argument for stopping cooling outright
    when the dew point is unknown rather than trusting a static guess.
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

- **Interim inner-loop target (implemented 2026-07-26):** until per-room air
  sensors exist, `control.return_setpoint_source: system_return` makes each
  circuit's target the *mixed system return* (`rl_total`) rather than an
  absolute number, so the loop balances distribution instead of trying to set
  an absolute temperature it cannot reach. The heat pump owns absolute water
  temperature through its own return setpoint. This is a stepping stone to the
  `RL_curve` below, not a replacement: it has no notion of weather or of how
  much heat a room actually needs, and `all valves closed` is a valid
  equilibrium (hence `system_return_bias_c`). Measured the day it landed: a
  fixed 20 degC target commanded 0 % on every circuit with rooms at 22-23 degC,
  while system-return tracking correctly singled out the one genuinely warm
  circuit.
- `RL_curve(AT_avg)`: linear in the *forecast-averaged* outdoor
  temperature (window configurable, default 0–5 h ahead) between two
  configurable points, e.g. (AT +20 → RL 22) and (AT −20 → RL 40).
  Physical basis: steady state requires floor emission ∝ (RL − T_room) to
  match room loss ∝ (T_room − AT), i.e. `RL − T_room = m·(T_room − AT)`
  — the curve is just this line with a default slope; layer 2 can learn m
  per room from logged data (§7.3) and override via `rl_target`.
- Observability rule: the RL sensors are on the return pipes **at the
  manifold**, so a circuit with no flow is not measured at all — its sensor
  drifts toward the manifold cabinet's ambient, which is dominated by the
  flow/return headers and therefore sits near the system water temperature.
  (Corrected 2026-07-27; this section previously said "slab ambient" and the
  code reasoned from that, wrongly.)

  The consequence is **lock-out, not oscillation**, and lock-out is worse
  because it is silent: with the interim `system_return` target, a stagnant
  sensor reads ≈ the header temperature ≈ the target, so the error is ≈ 0 and
  the controller concludes there is nothing to do. A closed circuit
  manufactures its own evidence to stay closed. This is the sensor-side view
  of the same "all valves closed is a valid equilibrium" problem that
  `system_return_bias_c` was added to paper over.

  So periodically flush closed loops (interval scheduled by AT, order of
  1–5 h) and re-measure during a fixed open window before trusting RL again.
  The flush is the load-bearing part: holding the last good command alone
  would preserve the lock-out forever. (A slab temp sensor per zone would
  remove the need — §10.)

  **RESOLVED 2026-07-27** in `heatctl/rl_gate.py` (ROADMAP.md Milestone 1). RL
  counts only after the valve has been commanded past `min_opening_pct` for
  `settle_s` — valve stroke *plus* hydraulic transport, per §4.1.5. Otherwise
  the circuit holds its last known-good command and is re-opened every
  `flush_interval_s` for one honest reading. Never-measured is treated as lost
  knowledge, so the caller falls back to fail-open; that also makes start-up
  self-healing without a special case, and avoids a multi-minute full-open on
  every deploy. Circuits marked `fitted: false` in config.yaml are always
  trusted — they are open pipe, so flow does not follow the command and
  gating them would be a fiction of its own.

  This was a live defect, not merely a WP-C gap: with every `room_temp_topic`
  empty at the time, *all* control ran through this fallback path.
- Fallbacks (each is the same controller with a input frozen, not a
  different mode): no room sensor → outer loop frozen at curve default
  (heat only if AT forecast says the room needs it); no RL sensor → outer
  loop drives the valve directly with conservative gain; no AT → last
  known / static curve point.
- Hydraulic fairness: per-circuit `max_cap` (config) plays the role of a
  balancing valve; §7.4 defines how to measure the caps. Pump/heat demand
  = f(Σ openings) with on/off delays (exists as HA automation today;
  becomes heatctl's, Milestone 1) — see §4.3.

### 4.3 Source demand and minimum flow

**CORRECTED 2026-07-27 (owner)**, replacing an earlier design built on a wrong
model of the plant. What that design got wrong, and why, is recorded as D-016 -
the reasoning is worth keeping even though the text is not.

**The unit regulates itself.** It starts and stops its own compressor and
varies its power from the spread between leaving and return water. **Powering
the unit down is a measure of last resort, not a control action.**

The steady state of this plant is: pump running, compressor doing as much as it
needs, and **every valve open to a degree that distributes the supplied energy
to the rooms according to their need**. Note the precision — not "all valves
wide open", and not valves cycling shut, but open to *proportions*. The water
temperature decides how much energy there is; the valves decide how it is
shared out. This is why the *maximum* circuit opening is the right signal for
the water-setpoint loop: it is the most-demanding room reporting whether the
water it is being given is hot or cold enough.

So the control hierarchy is:

1. **Water temperature** (`control.water_setpoint`, §4.4) — the primary
   modulation lever, driven by house demand.
2. **Valve positions** — per-room trim around that, bounded below by the flow
   floor.
3. **The unit's own compressor control** — the fine modulation, which is not
   ours to do.

Two consequences, and they are what invalidated the earlier design:

- **"Satisfied" is not a reason to stop.** The unit idles its own compressor
  and costs almost nothing; power-cycling a heat pump is expensive and slow.
- **Low flow is a reason to OPEN VALVES, not to stop the source.**
  `min_open_pct` constrains how far heatctl may throttle. Treating it as a
  shutdown trigger was also circular: valve position is heatctl's own output,
  so the plant would have been switched off in response to heatctl's own
  decision.

And one principle from that earlier design that survives it intact, because it
is about the *input* rather than the mechanism:

- **Compute demand from ROOM deviation, never from valve position.** Valves
  also close for safety reasons — dew point, screed overtemp — which say
  nothing about whether the house wants heat. Gating on valve openings would
  read a condensation closure as "no demand", stop the source, and prevent the
  supply from ever recovering: the same shape of latch-up as the condensation
  bug that took cooling out of service on 2026-07-26.

`source_demand` is therefore a *reconciler* — it holds the unit powered and
only powers down on an explicit `off` — not a controller.

Keeping flow up is **§4.4's** job, not this one's: normalising the demand set
so the most-demanding circuit is fully open maximises flow as a matter of
course, which is why the pump's minimum stopped needing a defensive mechanism
at all.

### 4.4 Valve distribution — maximise flow, minimise spread

**The objective** (owner, 2026-07-27), and it is an efficiency objective, not
a protective one:

> maximise overall flow → minimise the leaving/return spread → the water can
> sit closer to room temperature for the same duty → better COP

Throttling a valve is a **cost**. It is paid only to distribute energy between
rooms that need different amounts, never for its own sake. The pump's
minimum-flow requirement therefore stops being a constraint we defend and
becomes a side effect of doing the right thing anyway.

**The rule.** Scale the whole set of demands so the most-demanding circuit is
fully open. Ratios between rooms — the distribution — are preserved; the
absolute energy delivered stays governed by water temperature (§4.5), not by
valve position.

```
cmd_i = open_threshold + (d_i + ε)/(peak + ε) · (full_open − open_threshold)
```

The naive `d_i / max(d)` fails twice, and ε fixes both together:

| | Naive | With ε |
|---|---|---|
| Every room satisfied, `max(d)=0` | 0/0, undefined | → ε/ε = 1 for every circuit, i.e. **all valves fully open**, reached continuously |
| Demands `[0.001, 0.0005]` | `[100, 50]` — a ratio of noise | discrimination fades out smoothly as demand falls |

All-valves-open at equilibrium is not a degenerate case being papered over: it
is the physically correct answer. With nothing to distribute there is no reason
to throttle anything, and maximum flow is exactly what we want.

**ε is an engineering knob, not a fudge factor.** It is the demand scale below
which we stop trying to tell rooms apart. Larger ε → flatter distribution →
more flow and better COP, at the cost of per-room discrimination. Smaller ε →
sharper distribution, less flow. It trades comfort precision against
efficiency, and it is the first thing to tune once there is data.

**Consequences that are easy to miss:**

1. **The commanded maximum is pinned at 100 % by construction.** So valve
   position can no longer tell the water-setpoint loop whether there is enough
   capacity — it would read "saturated" forever and drive the water colder
   without limit. That loop must read the **pre-normalisation peak demand**.
   These were the same quantity before normalisation and are not now.
2. **The circuits are coupled.** Every command depends on the maximum across
   all of them, so a change in the most-demanding room rescales everyone. The
   reference peak is therefore slew-limited (`max_peak_step_per_cycle`), or one
   room's transient would re-throttle the whole house against actuators that
   take minutes to move.
3. **`off` must bypass normalisation.** An all-zero demand set correctly
   normalises to all-valves-open, which is right at thermal equilibrium and
   exactly wrong when the plant is meant to be off.
4. **Safety runs after.** This is a control proposal. If safety closes enough
   circuits that flow is genuinely lost, the escalation is the source-side last
   resort — not reopening valves into a known-bad supply.

**Deadband, both ends.** §4.1.2 already requires `open_threshold_pct` and
`full_open_pct` per valve. The upper one matters especially here: "normalise so
the peak circuit is fully open" only means what it says once `full_open_pct` is
a *measured* number. Both are unmeasured today — two actuators, no flow meters,
and eight circuits that cannot throttle at all — so they default to an identity
mapping and the measurement is a prerequisite (§7.3).

### 4.5 How to tell whether any of this is working

Recorded continuously so the question can be answered later rather than
guessed at. Everything below is an HA entity and therefore in InfluxDB at full
resolution.

| Signal | Topic / entity | What it tells you |
|---|---|---|
| Leaving/return spread | `hp/spread` | **The primary KPI.** Small spread = high flow = the design working. A large spread while the compressor runs means flow is inadequate. |
| Pre-normalisation peak demand | `demand/peak` | Is there enough capacity? Pinned near 100 % → water too mild. Sitting near 0 → water too aggressive. |
| Commanded vs actual valve | `valve/*` and `valve_actual/*` | Divergence means something other than heatctl moved the outputs. |
| Flow proxy | `demand/open_pct` | Mean opening across circuits, unactuated counted as 100 %. |
| Water setpoint + decision | `hp/setpoint_*`, `water_sp/reason` | Is the setpoint loop settling, or hunting? |
| Compressor frequency, current, power estimate | `hp/compressor_freq`, `hp/compressor_current`, `hp/power_estimate` | Duty and rough electrical input. The estimate is current × 230 V — it ignores fans and pump and is **not** metered. |
| House deviation, per-room setpoint/temperature | `demand/deviation`, `setpoint:*`, `room:*` | Is comfort actually being delivered? |
| Outdoor ambient | `hp/outdoor_ambient` | Normalise everything else against weather. |
| All six fault registers | `hp/fault/*`, `hp/fault_any` | Er03 in particular, since flow is what this design manipulates. |
| Settled flag per circuit | `settled:*` (SQLite) | Excludes samples taken while an actuator was still travelling — those are poison for identification (§4.1.4). |

**What to check, when we decide to check:**

1. **Spread while the compressor runs.** Should be small and stable. If it
   grows as rooms diverge, distribution is throttling too hard — raise ε.
2. **Does `demand/peak` spend its time pinned at 100 %?** Then the water is too
   mild and the setpoint loop is not being aggressive enough, or its bounds are
   wrong. Persistently near 0 is the opposite.
3. **Does the water setpoint settle or oscillate?** Hunting means the 30 min
   cadence or the 1 K step is wrong for this slab's time constant.
4. **Distribution of commanded positions.** If every circuit sits at 100 %
   permanently, ε is too large and there is no distribution happening at all.
   If most sit near zero, ε is too small.
5. **Compressor cycle length.** Short cycling wastes energy and wears the unit.
   Compare against the ~10 min on / ~9 min off observed on 2026-07-27, before
   any of this existed.
6. **Energy per degree-day.** `hp/power_estimate` integrated, against
   `hp/outdoor_ambient` and the room deviations. This is the only number that
   actually answers "is it more efficient", and it needs weeks, not hours.
7. **Er03 occurrences.** Was 25 in 10 days before this work, all attributed to
   flukes/low system pressure rather than valve position. If that count rises
   after the actuators are fitted, distribution is starving the pump.

Note (6) cannot be answered until there are comparable periods, and none of
this is meaningful until more than two circuits can actually throttle.

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

### 6.1 Room model — REVISED 2026-07-28 against measured plant + building data

Assumes the planned **per-room air sensors** (Shelly H&T) are in place. Without
them four of seven rooms have no air measurement at all and the 3-state form is
not identifiable — see "Observability" below, which is the real constraint on
model order, more than any physics question.

States per room: `T_air`, `T_env`, `T_slab`.

```
C_air  dT_air/dt  = UA_ae·(T_env−T_air) + UA_sa·(T_slab−T_air)
                    + Σ_n UA_nb,n·(T_air,n − T_air)          ← NEW: neighbours
                    + ṁ_adv·c·(T_air,n − T_air)              ← NEW: open air paths
                    + f_sol·q_sol,room                       ← NEW: split, see below
                    + q_int + q_stove_dir(living room)
C_env  dT_env/dt  = UA_ae·(T_air−T_env) + UA_eo·(AT−T_env)
C_slab dT_slab/dt = UA_ws·(T_wm−T_slab) − UA_sa·(T_slab−T_air)
                    − UA_sg·(T_slab − T_ground)              ← NEW: ground
                    + (1−f_sol)·q_sol,room                   ← NEW: solar to the floor
```

Four corrections to the original formulation, each forced by measurement:

**(a) Rooms are coupled to each other, and it was missing entirely.** Internal
partitions are 9 cm solid wood: **U ≈ 1.05 W/(m²K)**, roughly **six times** the
external wall's 0.18. Rooms exchange heat with each other far more readily than
with outdoors, so omitting this pushes a large real flux into whatever
disturbance state sits nearest. Add `UA_nb,n = 1.05 × A_shared`.

Separately, **Wohnzimmer and Arbeitszimmer share an open air path** — the OG
`Luftraum` over the living room, plus a door the owner leaves open. That is
advective, not conductive, and **it is far larger than any wall term.**

**CORRECTION 2026-07-29: `ṁ_adv` is a SWITCHED INPUT, not a parameter to
identify.** An earlier draft of this section had the filter track it as a slowly
varying coefficient. That is wrong, and the magnitudes show why. Standard
buoyancy-driven two-way doorway exchange,
`V̇ = ⅓·C_d·W·H^1.5·√(g·ΔT/T̄)`, for a 0.9 × 2.0 m opening:

| ΔT | exchange flow | heat | effective UA |
|---|---|---|---|
| 0.5 K | 236 m³/h | 39 W | 79 W/K |
| 1.0 K | 333 m³/h | 112 W | 112 W/K |
| **2.0 K** | **471 m³/h** | **316 W** | **158 W/K** |
| 5.0 K | 745 m³/h | 1248 W | 250 W/K |

Against a **closed** door at ~3.6 W/K, that is a **factor of ~44**. And 158 W/K
is **59 % of the entire building's H_total (267 W/K)** — one doorway, moving
nearly a full air change of the heated volume per hour. A state this large
cannot be a parameter: opening a door changes the plant's topology, and a
filter that models it as drift will corrupt every parameter it touches.

Note also `UA_eff ∝ √ΔT`, so it is nonlinear, and it is **directional**: warm
air crosses high, cool air returns low.

**Strategically this door is worth keeping open** (owner, 2026-07-29). The
`Luftraum` and the fan coil are *above* Wohnzimmer, so the stack effect delivers
the house's warmest, most humid air straight to the coil — maximum sensible ΔT
and maximum latent capture — and returns cooled, denser air downward by gravity.
That is a free thermosiphon, and it is the thermodynamically correct place for a
cooling emitter: cooling from above works *with* buoyancy, whereas floor cooling
works against it, which is exactly why the slab is limited to 25–35 W/m². It
also partly defeats the "capacity is not fungible between rooms" limitation
elsewhere in this document — air does what the hydraulics cannot.

Same treatment for **infiltration**: `n` is not a constant 0.7 h⁻¹, it is
0.7 plus whatever an open window is doing. Also a switched input.

**Neither switch is observable today** — see BACKLOG for door/window contacts.
Until they exist, both `ṁ_adv` and the window term must be treated as
unmeasured disturbances with wide process noise, and any parameter
identification run must be discarded if a door or window state changed during
it. Fitting through an open-window hour yields a much higher `UA_eo` that the
filter will then carry forever.

**Decoupling is preserved**: neighbour temperature enters as a *measured input*,
exactly like VL — not as a shared state. §7.1's one-filter-per-room structure
survives intact, which is the whole reason it was chosen.

**(b) The slab had no ground path.** Add `UA_sg·(T_slab − T_ground)`. With 12 cm
PU under the screed this is ≈ **29 W/K** over 136.40 m², which against a slab of
8,691 Wh/K is a **~300 h** time constant — far too slow to matter for control,
but a persistent seasonal sink that would otherwise be absorbed into a
disturbance estimate and quietly bias it. `T_ground` is a slow state (or a
seasonal function): at 0.5–1 m depth it lags air by 1–2 months. **In cooling it
helps**, which is exactly when we are capacity-constrained.

**(c) Solar had the wrong driver AND the wrong node.**

*Driver.* The original used own-PV production as `I_sol`. Both PV planes face
south (185°/17°, 180°/25°) while the building is rotated **16.3° off cardinal**,
so its façades are ESE/SSW/WNW/NNE. Measured 2026-07-28: PV understates the east
façade by **1.7–4.5×** through the morning and overstates it ~4× in the
afternoon — wrong in both directions at the worst times, and not fixable with a
single coefficient. Replace with **one Forecast.Solar plane per façade** at the
measured azimuths, `declination 90`, `kwp` = that façade's effective collector
area (API contract in `docs/BUILDING.local.md`). Then
`q_sol,room = Σ_façade A_eff,room,façade · I_façade`.

**Still missing: the per-ROOM glazing split.** We have it per façade only, and
it is very unevenly distributed — Wohnzimmer holds ~28 m² of the house's 51 m².
Read it off the plans; this is the single highest-value remaining geometry item.

*Node.* Shortwave through glazing lands mostly on the **floor**, not on the
envelope. Putting it all into `T_env` gets the timing wrong, and we have direct
evidence: on 2026-07-28 the air rose 3.5 K in 44 minutes while that room's slab
circuits went *down*. A `T_env`-only injection predicts a far slower air
response than observed. Hence the `f_sol` split — a fast convective/radiant
fraction to `T_air`, the remainder charging `T_slab`. `f_sol` is a per-room
parameter for the filter to identify; expect it small (0.2–0.4).

**(d) Not every room has a slab.** Arbeitszimmer is served by a **fan convector**
(4.2 kW cooling / 4.3 kW heating), and is upstairs — outside the 136.40 m²
ground slab entirely. It is a **2-state room**: drop `T_slab`, and its emitter
term is a fast `Q_coil(valve, fan)` rather than `UA_ws·(T_wm−T_slab)`.
A fan coil also *dehumidifies* when its surface is below dew point, so for that
room alone the model has a latent channel the slab rooms do not.

### 6.1.1 Observability — the binding constraint

| | |
|---|---|
| States, target | 6 slab rooms × 3 + 1 coil room × 2 = **20**, plus disturbances |
| Air measurements | 3 today → **7 assumed** after Shelly H&T |
| Circuit RL | 10, **at the manifold**, valid only while flowing (D-009) |
| System | VL, RL total |

With per-room air sensors the 3-state form is identifiable. **Without them it is
not**, and the four unsensored rooms should collapse to 1–2 states rather than
run three states off one intermittent, position-biased measurement.

**The deepest dependency is flow.** `T_wm` and `NTU(opening)` both need it, and
that pair carries nearly all the slab information. Until flow is measured the
slab estimate rests on an assumed pump curve — see BACKLOG. This is why the flow
meter is a model prerequisite, not an accounting nicety.

### 6.1.2 Parameters now known from the building survey

From `docs/BUILDING.local.md` (EnEV certificate + Bauantrag drawings, with the
owner's as-built corrections). **U-values survived the corrections; thermal
masses did not** — so the certificate is usable for the R network and must not
be trusted for the C network.

| Parameter | Value | Confidence |
|---|---|---|
| `C_slab`, whole floor | **8,691 Wh/K** (63.7 Wh/(m²K) × 136.40 m²) | good — from as-built layers |
| `UA_sg` (slab → ground) | ≈ 29 W/K | good |
| `UA_eo` total (fabric + bridges) | 148.83 W/K | fair — 18 % is a Bbl 2 default |
| Ventilation | 118.40 W/K at n = 0.7 h⁻¹ | **poor — assumed, never measured** |
| Partition `U` | 1.05 W/(m²K) | good |
| Partition capacity | 20.0 Wh/(m²K) | good |
| Internal partition run, EG | **≈ 42 m → ~100 m² → ~2,000 Wh/K** | **weak, see note** |
| Whole-building C | ~15,300 Wh/K predicted vs **15,700–18,300 measured** | consistent |

**Note on the partition area.** Vector extraction from the Bauantrag EG plan
finds 8 cm face pairs totalling 105.6 m of run, but room perimeters imply only
~42 m — the extractor is pairing non-wall lines 8 cm apart (door leaves,
dimension ticks). The 42 m figure above is the geometric estimate
(Σ 4.15·√A − external perimeter, halved) and carries **±20 %**. A manual
take-off would settle it; per-pair `A_shared` for the coupling terms needs one
anyway.

Per-room floor areas for distributing `C_slab` and `q_int`: Wohnen/Essen 42.11,
Kind 1 16.33, Kind 2 15.61, Schlafen 11.08, Bad 8.94, Diele 9.33, HWR 8.98,
WC/Du 3.43 m² (EG, on the slab); Arbeit/Gäste 31.20 m² (OG, no slab).

### 6.2 Buffer: 5-node stratified tank

**The stratified model is only valid while the tank is externally charged.**
The SLS-1000 layers properly when charged through its external circuit, but the
**8 kW immersion element creates convective turbulence that destroys the
layers** (owner, 2026-07-29). So element operation is a **switched input** that
invalidates the stratification assumption — the same class of discrete
regime change as an open door or window (§6.1), and it must be handled the same
way: switch the tank to a **lumped/mixed** representation while the element runs
and for a settling period afterwards, rather than letting the 5-node model fit
a profile that is not there.

Energy is still conserved through mixing, so total tank energy content remains
meaningful once settled; what is lost is the *distribution* of that energy
between nodes, which is precisely what the 5-node model exists to track.
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
  0x8025). **The unit is a Blaupunkt BLP08P1V1MR32** (docs/HEATPUMP.md):
  single-phase 220–240 V, max 3.6 kW / 16.5 A, cooling 6.0 kW EER 2.99 at
  A35/W18 and 5.5 kW EER 2.09 at A35/W7, modulating down to ~1.0 kW.
  **What 0x8025 measures is still unresolved** — mains, inverter output, or DC
  link — and the present `× 230 V` estimate is not usable for COP until it is.
  Calibrate against the **utility Shelly**: regress its power step against the
  0x8025 step on every compressor start/stop/frequency change. Slope ~230 W/A
  means mains; ~374 W/A means DC link. The intercept also recovers the fan
  (80 W), pump and controls the estimate currently omits.
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
| Room `UA_eo` (loss) | **available now**: per-element U×A in docs/BUILDING.local.md | Night decay: heating off, fit exponential of T_air (gives UA/C pairs) | regression on winter logs |
| `C_air`, `C_env` | air volume ×1.2 kJ/m³K; interior mass estimate | same decay fit (two time constants) | KF parameter augmentation, one at a time |
| `C_slab`, `UA_sa` | **available now**: 8,691 Wh/K total, split by room floor area; ~6–11 W/m²K emission | step test: full-open heat pulse 2–4 h, observe T_air/RL trajectories | slope of RL vs room curves (m per room) |
| `UA_ws`, NTU(opening) | pipe length & spacing from floor plan | per-circuit: sweep opening at constant VL, record steady RL | slow drift tracking |
| `a_sol` | window area × g-value × orientation factor | clear-day, heating-off morning: regress T_air rise vs PV proxy | seasonal regression |
| Buffer `V_i`, `UA_loss` | tank drawing, insulation spec | standby test: 24 h no charge/discharge, fit losses + `k_mix` | continuous |
| HP COP map | datasheet | one charge run per AT bin, log (P_el, Q_th) | continuous regression |
| Hydraulic shares / max_cap | loop lengths | full-open test: all circuits open at fixed VL, compare per-loop RL rise rates; set caps to equalize | repeat seasonally |

#### Passive identification — prefer it to a dedicated experiment

A dedicated sweep is expensive (≈10 min per step, so ~20 h for twelve
circuits), needs thermal contrast that a well-tuned plant does not naturally
have, and disrupts control while it runs. Much of this ladder can instead be
fitted from data heatctl already records at 1/min into InfluxDB — commanded
position, per-circuit RL, VL, RL_total, the heat pump's leaving/return spread,
compressor state, and a per-circuit `settled` flag.

Two things make this work better than it sounds:

- **The distribution design sweeps the range by itself.** §4.4 drives the
  most-demanding circuit to fully open and the rest to the ε trickle, and
  *which* circuit is the peak rotates as rooms' needs change. So normal
  operation visits both ends of every circuit's range continuously, without
  anyone asking it to.
- **`settled` makes the data usable.** Samples taken while an actuator is
  still travelling are poison (§4.1.4): flow is unknown, so RL means nothing.
  Excluding them turns a noisy log into a usable dataset.

What this can plausibly yield without any experiment: `open_threshold_pct`
(RL departs from manifold ambient), `settling_time_s` (RL response time after a
commanded step), NTU(opening) over the visited range, and the hydraulic shares
via the mixing relation at the return header —
`RL_total = Σ(ṁ_i·RL_i)/Σ(ṁ_i)`, which is a flow-share estimator that needs no
flow meter.

What it cannot yield: `full_open_pct`, for the reason in D-021 — RL saturates
before the valve stops moving, so no amount of passive data distinguishes "the
valve is fully open" from "flow is high enough that RL no longer cares". Take
that from the datasheet, or leave it at 100, which is the safe error (D-021).

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

Planner v1 (heuristic, no MPC — matches ROADMAP.md Milestone 3):
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

Extends ROADMAP.md; Milestones 0–2 there stay unchanged and come first.
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
