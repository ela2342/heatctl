# Decision log

**What belongs here:** a decision that establishes a principle, or that
*reverses* an earlier one. Not routine work — that is in `ROADMAP.md`.

**Why it exists:** rationale is recorded well at the point of use (module
docstrings, `config.yaml` comments), which serves someone reading that code.
It does not serve someone asking *"why did this change, and what did we believe
before?"* Before this file, every reversal lived only in a commit message —
the least discoverable place in a project whose premise is thirty years.

**How to reference one:** by ID. `see D-012`, never "section 4.3 of DESIGN.md".
IDs are stable; section numbers move. Append new entries at the bottom, never
renumber, never delete — a decision that was wrong gets a *superseding* entry,
so the reasoning that led there stays visible.

**Format:** what was decided, what it supersedes, why, and what it costs. The
"why" matters more than the "what" — the what is in the code.

---

## D-001 · Two layers, and layer 1 never calls Home Assistant
Layer 1 (`heatctl/`) is the safety-critical control core; layer 2 (the future
optimizer) may fail at any time and talks to layer 1 only over MQTT, clamped by
`Safety`. **Why:** the house must stay warm with HA, the optimizer, or the
network entirely dead. **Cost:** anything HA provides (room temperature, dew
point) must degrade safely rather than be depended on.

## D-002 · `modbus_direct` is the active I/O backend; modbus2mqtt abandoned
**Why:** the available HA add-on publishes one aggregated JSON document per
device and cannot emit raw per-register values on flat topics
(`docs/MODBUS2MQTT.md`). Direct Modbus is also the mandatory transport for the
planned 100 ms DHW loop. **Cost:** none realised — heatctl's own control plane
already gives HA full visibility. The `mqtt` backend stays in the tree because
the abstraction is what made this swap cheap.

## D-003 · Valves fail OPEN on lost knowledge, CLOSED on known-bad supply
Sensor fault, stale data, crashed controller → open. Screed overtemp or
below-dew-point supply → closed. **Why:** the heat pump holds its own return
setpoint, so an unsupervised open circuit still gets sane water; only
distribution is lost. But a *measured* bad supply makes opening the actively
harmful choice. **Cost:** the two directions must never be collapsed into one
rule. See `heatctl/safety.py`.

## D-004 · Coupler watchdog: type Standard, mask `0x8020` (FC6+FC16)
**Why:** Standard evaluates the coding mask, so restricting it to the write
function codes means "watchdog satisfied" implies *outputs are being driven*,
not merely that something is polling. heatctl's per-cycle valve write is
therefore the heartbeat and needs no separate kick. An earlier note advised
*Alternative*, which resets on any telegram — exactly backwards.

## D-005 · The per-circuit target tracks the mixed system return
`return_setpoint_source: system_return`. **Why:** a fixed absolute target is
near-useless in cooling — the slab return sits below any plausible number even
with warm rooms (measured: returns 18.5–19.2 °C against a 20.0 target commanded
0 % everywhere). Tracking the system return makes the inner loop a *balancing*
controller, which is heatctl's actual job while per-room sensors are missing.
**Superseded in part by D-018**, which added the missing outer loop.

## D-006 · The wall-unit dial defines the room target; `betriebsart` is ignored
**Why:** a target is a target. 20 °C means "hold this room at 20"; whether we
approach it by heating or cooling is decided one level up. **Supersedes** a
brief change that stripped setpoints out of the bridge on the theory that a
heating target "inverts its meaning" in cooling. It does not. **Cost:** one
number cannot express both a heating and a cooling bound — acceptable while
mode is a deliberate seasonal choice.

## D-007 · Cooling condensation response is source-side, not circulation-stop
Raise the chilling setpoint; do not stop circulation. **Why:** the pump reacts
quickly to setpoint changes and a few minutes of supply below dew point is not
critical given the screed's mass. **Cost:** valve-side protection alone is
partial while most circuits are unactuated open pipe.

---

## D-008 · The watchdog trigger `0x1003` is a TOGGLE
Recovery must write the *other* value, not a constant. **Why:** the register
clears a trip on a **change** of value and refuses a same-value write with
exception `0x03`. **Supersedes** the original implementation, which wrote a
constant `1` — that recovered exactly once, the first trip, when the register
still held its power-on `0`. Overnight into 2026-07-27 the coupler tripped a
second time and stayed blocked ~3.5 h. **Lesson:** one successful recovery test
proves nothing here; test twice.

## D-009 · The RL sensors are at the MANIFOLD, so stagnant readings cause lock-out
A circuit with no flow is not measured at all — its sensor drifts toward the
manifold cabinet's ambient, near the header temperature. **Supersedes** the
claim (in code and DESIGN.md) that it reads "slab ambient". The consequence is
the opposite of what that implied: with the system-return target, a stagnant
sensor reads ≈ the target, error ≈ 0, and the circuit talks itself into staying
shut — silent **lock-out**, not oscillation. Handled by `heatctl/rl_gate.py`,
where the periodic *flush* is the load-bearing part, not the hold.

## D-010 · No fresh dew point means no cooling
**Why:** the static `vl_min_cooling_c` is not conservative — a 26 °C room at
60 % RH has a dew point of 17.6 °C, above the 16.0 it permits. It looks like a
safe floor and is not one. Also covers the case the HA automation cannot: if
the dew point is missing *because HA died*, its source-side shutdown died with
it. **Cost:** cooling now depends on one HA automation publishing dew point —
recorded in `docs/HA_INTEGRATION.md` as safety-critical.

## D-011 · Known-bad-supply checks run BEFORE the fail-open check
**Why:** they depend on the *supply* sensor and are independent of a circuit's
return sensor. Checking fail-open first meant one faulted return sensor forced
its circuit open while the supply was measurably below the dew point —
condensation protection defeated by an unrelated fault. Frost still outranks
everything.

## D-012 · Register `0x0000` bit 0 is the unit's POWER, not the water pump
**Supersedes** an assumption inherited from the roadmap, which the HA automation
and a template helper were both built to match — three sources, one unverified
origin. The pump knob is bit 4. **Consequences:** the automation that "held the
pump request set" was holding the whole unit powered on; the condensation
automation that cleared it was *powering the heat pump off*. See
`docs/HEATPUMP.md`.

## D-013 · heatctl is the sole Modbus master for the heat pump
**Why:** the unit documents a ≥200 ms minimum between transactions, and two
independent masters cannot honour that on each other's behalf — they
demonstrably interfered. **Cost:** HA's `modbus:` block for this unit is
commented out and HA now consumes heatctl's MQTT entities instead. Every write
wears the unit's flash, so writes happen only on a real transition.

## D-014 · Analog output *n* drives circuit *n* — the mapping is 1:1
**Supersedes** an 8-channel table built by fitting 10 active circuits into 8
outputs, which skipped the out-of-service circuits and shifted indices 5–8. The
Arbeitszimmer room PID was therefore driving circuit 7's output. Harmless only
because no actuator is fitted there. **Lesson:** a mapping built by "fitting
things in" rather than measured will silently point a live controller at the
wrong device.

## D-015 · The condensation guard is scoped to COOLING only
**Supersedes** a draft that made it mode-independent, on the theory that
heatctl's mode and the pump's could diverge. They can — but heatctl now *reads*
the pump's mode register, so detecting the disagreement is the honest fix. A
mode-independent guard would let a lukewarm start-up supply plus humid air
block the house heating.

## D-016 · The unit self-regulates; powering it down is a last resort
Steady state is: pump running, compressor doing as much as it needs, and **every
valve open to a degree proportional to its room's need**. **Supersedes** the
original demand design, which stopped the source when the house was satisfied
*and* when flow got low. Both wrong: "satisfied" is the unit's own business, and
low flow is a reason to open valves. The latter was also circular — valve
position is heatctl's own output, so it switched the plant off in response to
its own decision.

## D-017 · Distribution normalises so the most-demanding circuit is fully open
`cmd_i = (d_i + ε)/(peak + ε)`. **Why:** the objective is efficiency — maximise
flow → minimise the leaving/return spread → the water sits closer to room
temperature → better COP. Throttling is a *cost*, paid only to distribute. ε
resolves both the 0/0 at equilibrium (→ all valves open, which is also the
physically right answer) and noise amplification at low demand. **ε is an
engineering knob**, trading flow against per-room discrimination. **Cost:** the
commanded maximum is pinned at 100 % by construction, so the setpoint loop must
read *pre-normalisation* demand; and the circuits are now coupled, hence the
slew-limited reference peak.

## D-018 · Water temperature is the primary modulation lever (1 K / 30 min)
Load compensation from house demand *and* valve saturation. **Why:** water
colder than needed does not make the house colder — the valves throttle it back
— so the error is invisible in room temperature and shows up only as COP and
condensation risk. Slow and integer because every write wears flash and the slab
has hours of thermal mass. A measured leaving-water breach bypasses the cadence,
because that is a safety event, not a trim. **Subsumes** the HA chilling-setpoint
loop, giving the setpoint exactly one owner.

## D-019 · InfluxDB (via HA) is the archive; heatctl's SQLite is a 14-day buffer
**Why:** HA forwards to InfluxDB through a **config entry**, not an `influxdb:`
YAML block — so the absence of YAML is not evidence that recording is off. That
mistake was made and corrected the same day; verified by querying Influx
directly. heatctl's own file is the layer-1-independent fallback for when HA is
the thing that broke, so it only has to cover a gap. Unbounded it would have
been about a GB a year.

## D-020 · `auto_mode` is on: the house average picks heating vs cooling
Deliberately sluggish — the average must sit more than 1 K past the band for a
full hour. **Why:** switching the whole plant is expensive and slow to undo, and
only three of seven rooms have an air sensor. **No seasonal lockout** (owner, same day): an
outdoor-temperature guard was proposed and rejected — this site has seen below
freezing in August, so a lockout would refuse heating exactly when a freak cold
snap needed it. The house average is the right signal precisely *because* it
does not care what month it is. The deadband and the hour of dwell are the
guard against a transient (an evening of ventilation), and lengthening the
dwell is the lever if that proves insufficient.

## D-021 · `full_open_pct` defaults to 100, and may only be lowered on strong evidence
The error is **asymmetric**. Set too high (100 when the true full open is 85),
the peak circuit is commanded 100 and the valve simply sits at its mechanical
stop — harmless. Set too low (85 when the truth is 100), the plant never fully
opens and **throws away flow**, which is exactly what D-017 exists to maximise.
**Why it matters now:** the obvious measurement — ramp the opening until RL
stops changing — is systematically biased *low*, because RL asymptotes to VL as
flow rises (`RL ≈ T_slab + (VL−T_slab)·exp(−NTU)`), so it stops responding for
hydraulic reasons while the valve is still travelling. A badly measured value is
therefore worse than no measurement. **Consequence:** the identity default is
the safe one; prefer the datasheet or passive identification (§7.3) over a
thermal sweep, and treat any measured value that lowers this as suspect until
corroborated.

## D-022 · The actuator self-calibrates, so the identity mapping is correct — not merely safe
The valves are Möhlenhoff Alpha 5 **`APV 42505-00`**, and the APV prefix means
`Ventilwegerkennung`: the drive measures its own valve travel and *auto-adapts
the active control-voltage range*, determines its closing point automatically,
and regulates internally for maximum stroke **minus over-travel**. **Why it
matters:** the upper deadband is real — the characteristic curve names an
"Over-elevation range" — but the device already compensates for it, so
`full_open_pct = 100` is right for a physical reason rather than as the safe
default D-021 settled for. **Supersedes** the plan to measure it. The one
genuine lower deadband is `Umin`: 0 – 0.5 V is ignored to reject hum on long
cables, i.e. **5 %**, now `distribution.open_threshold_pct`. **Also settled:**
30 s/mm × 5.0 mm = 150 s full stroke, so `rl_gating.settle_s: 300` has margin.
**Second finding, and the one with teeth:** the `-00` is not decoration, it is
the control-characteristic field of the order code — `00` = 0–10 V direct,
`01` = 2–10 V, `02` = **10–0 V inverted**, and the NC/NO bit sits in the
`42505` digits. Our whole output mapping rests on that field, so the type key
is now written out in `docs/HARDWARE.md`: anyone sourcing a replacement must
match the code, not the model name. **Cost:** none — this replaced an
experiment that would have cost hours of disrupted control and, done the
obvious way, would have been biased low anyway.

## D-023 · The condensation guard gets hysteresis on RELEASE only
`Safety.apply` compared supply against `dew_point + margin` with a strict
`<` and no hysteresis. Both operands are quantised to 0.1 K and dither
independently, and load compensation (D-018) deliberately drives supply down
onto the limit — so the plant parks exactly where one LSB tick in *either*
signal flips every owned valve. **Measured 2026-07-28 07:32:** trip at supply
14.5→14.4, reopen 16 s later from the **dew point** moving 12.5→12.4 with
supply unchanged, trip again at 14.3. hk02 is a fitted actuator with a 150 s
stroke (D-022), so 100→0→100→0 in 27 s left its true position unknown — the
one state the design exists to prevent. **Fix:** trip at `vl < limit`, release
only at `vl >= limit + dew_point_release_margin_c` (0.3 K). **The asymmetry is
the whole point** — closing is protective and must stay instantaneous, so the
margin may only ever delay reopening; a symmetric band would defer the trip and
be worse than no hysteresis. **Frequency, for honesty:** 4 trips in 9.7 h, one
of them sub-stroke. This was not chronic chatter, and the first report of it as
such overstated the case. It will get worse as actuators are fitted and as the
trim tracks the constraint harder. **Also learned:** instrumenting only the
supply side would have missed this — the reopen came from the humidity input.

## D-024 · No lower floor on the cooling supply limit — bound the reading, not the result
`safety.vl_min_cooling_floor_c: 12.0` clamped the computed limit to
`max(dew + margin, 12.0)`. **Removed 2026-07-28** at the owner's call.
**Why it was wrong:** it cannot do the job its own comment claimed. A floor low
enough to permit useful cooling is not a safe floor — a 12 °C indoor dew point
is an ordinary 22 °C at 53 % RH, so if it ever *did* bind it would be
authorising condensation, not preventing it. A floor high enough to be
genuinely safe (≈17–18 °C) blocks cooling outright, which is precisely the
static `vl_min_cooling_c: 16.0` this whole mechanism replaced (D-010). The two
requirements are mutually exclusive, so the construct was never going to work.
**Evidence it was inert:** across ten days of recorded data the reference dew
point ranged 11.2–15.1 °C, giving a limit of 13.2–17.1 °C. It never came within
1.2 K of the floor. **Owner's site knowledge closes it from both ends
(2026-07-28):** this house has seen dew points of **20 °C**, against which a
12 °C floor is not merely useless but actively misleading — and the forecast
for 2026-07-30 is **36 °C with a dew point of 9 °C**, where the floor would
have thrown away 1 K of supply headroom on the hottest day of the year. A
constant cannot straddle an 11 K spread in the quantity it is standing in for.
That is the general lesson: a fixed number substituting for a measured one
fails at *both* ends of the measurement's range, not one. **Provenance, for honesty:** I introduced it in `d457314`,
the same commit whose docstring criticises the *other* undocumented magic
number for arriving without derivation. It had none either.
**The principle worth keeping:** if a reading needs defending against, defend
the **reading** — plausibility bounds, cross-room agreement, staleness — never
clamp the result computed from it. Clamping the output only moves a wrong
number somewhere harder to see. The dew point is already the **maximum** across
every instrumented room and already has a staleness check; that is the right
shape. **Exposed by this removal:** see BACKLOG — the HA template falls back to
the *outdoor* dew point when no indoor pair is valid, and the floor was
accidentally the only thing bounding that path.

## D-025 · Too little flow opens valves; it never throttles and never stops the source
The plant has a hard minimum water flow enforced by the unit's own flow switch
(0.16 l/s on the BLP08P1V1MR32) — below it the heat pump throws **Er03 and
stops**. Confirmed on the plant 2026-07-28: the owner shut every valve but one
and tripped it instantly. `min_open_pct` had been configured and documented
since Milestone 1 but **never enforced** — `open_pct()` fed a status string and
nothing else. It was unreachable only because 8 of 10 circuits are open pipe and
count as 100 %, pinning the mean at ≥ 80 %; **fitting the remaining actuators
would have made heatctl able to fault its own plant**, since distribution can
drive every circuit to `open_threshold_pct` (5 %). **Decision:** enforce it in
`Demand.enforce_flow_floor`, by scaling all openings up by one common factor
until the mean clears the floor — D-017's normalisation applied at the bottom
end rather than the top, so the distribution decided upstream survives intact.
**Two orderings are load-bearing.** It runs *after* distribution, because it
needs the final openings; and *before* safety, because safety must still be able
to force a circuit shut for frost or below-dew-point supply. Reversing that
would hold a circuit open into dangerous water to protect the pump — trading an
invisible wet slab for a recoverable fault code, which is the wrong trade.
**Direction is the invariant, not the mechanism:** low flow is a reason to OPEN
valves and never to close them or to stop the source (D-016). A throttling
version would deadhead the pump faster than no protection at all, so the tests
assert the direction rather than that something changed. **Exempt in `off`** —
no flow is wanted and the source is not running. **Note the floor itself is
still an estimate**; 40 % coincides with the datasheet's 0.16/0.40 ratio, but
only under assumptions nobody has measured. See BACKLOG.

## D-026 · Transport policy: Zigbee is observation-only, never control or safety
**Owner's call, 2026-07-29: "no Zigbee on the critical path, that turned out to
be toy technology."** Recorded as a standing constraint, not a preference.
**The rule:** anything heatctl *acts on* — sensor inputs to control or safety,
and every actuator — must arrive over **wired I/O (WAGO/Modbus)** or **IP+MQTT**.
Zigbee may carry observation only: convenience metering, indication, things
whose loss degrades nothing. **Why it matters beyond taste:** heatctl's failure
model assumes it can tell *lost knowledge* from *bad news* (D-003), and a mesh
that silently drops or delays messages corrupts exactly that distinction — a
stale reading and a slow one look identical.
**Consequences already in force:** door/window contacts go **EnOcean**
(energy-harvesting, no batteries — fits the 30-year premise), and **solar**
variants specifically, so a periodic heartbeat exists and a dead sensor is
detectable. The grid meters are **Shelly Pro 3EM** (`SPEM-003CEBEU` at
192.168.178.16, `SPEM-003CEBEU63` at 192.168.178.31) — **IP, not Zigbee**, so
they are admissible, and they speak MQTT natively, meaning heatctl can read
them without HA in the path. The existing Zigbee smart plugs stay where they
are: observation. **Related:** [[D-003]] fail-open on lost knowledge, [[D-013]]
single-writer on shared buses.

## D-027 · `0x8025` is AC mains current — calibrated, not assumed
Settled 2026-07-29 by regression against the utility meter over **129 days** of
winter data (2025-10-05 → 2026-02-21), not by the single hot-afternoon test
previously planned. **Result: `P_el = 198·I + 200 W`, R² = 0.994 over 0–12 A.**
**Three independent proofs it is mains current, not DC link or inverter output:**
the Shelly's phase-A RMS current tracks the register **0.92 A per reported A**
(a DC-link current has no reason to); `V_bus × I` would give **3366 W** at 9 A
where **2011 W** was measured; and 198 / 220.9 V measured mains = **PF 0.90**,
normal for a single-phase inverter drive, consistent with the nameplate's
3600 W / 16.5 A = 218 W/A. **The intercept switches with UNIT POWER, not with
the compressor** — event-based fits return ≈0 W because fan and pump are
already running when the compressor starts. So it is applied whenever the unit
is energised. **Why the old `I × 230` was worse than it looked:** 16 % too
steep on slope, but omitting the 200 W partly cancelled it — net only +2…4 % at
the 9–10 A where the machine lives, and **14 % LOW at 3 A**. A *shape* error,
worst at part load, which is exactly where an optimizer needs it right.
**Also established:** the heat pump is on **phase A alone** (B and C carry
literally none of it, R² 0.000 and 0.059), so per-phase beats the 3-phase total
by 8 points of R².

## D-028 · Winter data confirms the building model at two timescales
Same analysis. **Flow: 0.345 l/s = 1.24 m³/h** (±10 % systematic, from the COP
map), consistent with the manufacturer's 0.16–0.40 l/s band at its 80th
percentile — and with our datasheet-plus-pump-speed estimate of 1.2–1.44 m³/h.
**H = 245 W/K** as fitted (plausible 215–275) against our calculated
**267 W/K**. **With η resolved to ≈ 0.70 this becomes H = 216 ± 18 W/K**
(198–234), the ± being η ±5, COP map ±13 and statistical ±12, combined in
quadrature. Taking the calculated fabric term (148.83 W/K) as given, that
implies a ventilation rate of **n ≈ 0.40 h⁻¹** rather than the assumed 0.70.
**Do not revise `n` on this**: the fabric term itself carries an 18 % thermal-
bridge *default*, so the discrepancy may sit in either term, and only a
blower-door test separates them. What can be said is that **0.70 h⁻¹ now looks
high**. **C is scale-dependent, and that is the finding**,
not a defect — the 1R1C fit's capacity rises monotonically with averaging
window, which is the signature of distributed storage:
* **3–6 h (dark): 8,900–10,300 Wh/K** vs our calculated **slab alone 8,691** —
  genuine, independent corroboration of the as-built slab correction (D-022).
* **12 h: 18,256 ± 1,533 Wh/K**; **24 h: 24,593 ± 2,575**.

**CORRECTION, same day.** A first version of this entry said the 12 h figure
matched the summer-night estimate of 15,700–18,300 "essentially exactly" and
called it two independent methods agreeing. **That overstated it, twice:**
(a) **the summer-night estimate was never independent of `H`** — it assumed the
*calculated* 267 W/K. Redone with the measured flow (1.24 m³/h) and the
η-corrected H = 216, the same 6 h balance yields **≈ 14,200 Wh/K**; and
(b) **the timescales do not correspond** — a 6 h balance should be compared
against the winter **6 h** fit of 8,900–9,644 Wh/K, which it does not match.
The estimators also differ in kind (single energy balance vs 1R1C regression).
**What stands:** C rises monotonically with averaging window — the signature of
distributed storage — and the 3–6 h figures bracket the calculated slab.
**What does not:** any claim of exact agreement between the two seasons.
Reconciling them properly is open work. **The two-time-constant fit
remains unidentifiable** — the longest dark free decay is 11.1 h over 1.2 K, and
every two-exponential attempt ran to a search boundary with absurd parameters.
**New dominant uncertainty in H: `η`**, the fraction of household electricity
becoming room heat. Consumption was 6,491 kWh in 4.6 months ≈ **1,940 W
continuous** — comparable to the heat pump's own thermal output — and free
fitting gives η = 0.22 ± 0.19, i.e. nothing. It moves H from 196 (η=0.5) to 246
(η=1.0). **This now outranks the ventilation-rate question**: n ≈ 0.57 h⁻¹ is
merely *hinted*, and is within uncertainty, so do not revise it on this evidence.

**PARTLY RESOLVED the same day, from owner knowledge plus the grid signal.**
η is not one number — it is a *mixture*, and the components are separable:

| load | η | why |
|---|---|---|
| **Electric DHW** — currently made with electricity, **10–23 kW spikes** | **≈ 0.1–0.3** | the energy leaves down the drain; only pipe and standby losses stay |
| Garage / Großküche / Sommerküche (the Hörnchenhaus-Kobel meter) | **0** | **outside the envelope** |
| Well pump | ≈ 0, and **negligible in winter** — only runs frost-free | outside |
| Ordinary indoor load | ≈ 0.9 | lights, fridge, electronics — all of it becomes room heat |

**The DHW load is identifiable from the grid signal by magnitude alone**, which
is what makes this tractable: nothing else in a house draws 10–20 kW. Over the
window, >8 kW episodes occupy 3.5 % of the time and carry ~1,474 kWh gross;
subtracting the 2,385 W baseline running underneath them leaves **≈ 1,193 kWh
of heater proper**, roughly **28 %** of all non-heat-pump consumption.

Blending on that basis gives **η ≈ 0.70 → H ≈ 216 W/K**, and it is
insensitive: DHW anywhere from 20 % to 35 % of load moves H only 222 → 212 W/K.
So **the estimate tightens from "unfittable" to ±10 W/K** on this reasoning
alone, before any sub-metering.

**Caveat, unresolved:** integrating 1-minute mean power over the window gives
**8,848 kWh** against the analysis's **6,491 kWh** — a 36 % discrepancy, method
not yet reconciled (power integration vs energy counters, or a differing
window). The *ratios* above are robust to it; the absolute kWh are not. Settle
this before quoting any absolute energy figure.



## D-029

**The water-setpoint trim remembers which setpoints the condensation guard
rejected, and retries on the constraint moving rather than on a timer.**

*2026-07-29.* Measured that afternoon: **14 setpoint oscillations between
12:24 and 20:19**, perfectly regular, while the house deviation degraded
monotonically from −0.32 K to −1.25 K.

The mechanism was two controllers with no knowledge of each other. The
capacity branch saw "house warm, valves at 100 %" and stepped the setpoint
down 1 K; roughly six minutes later the leaving water crossed the condensation
limit and the breach branch stepped it straight back up; thirty minutes after
that the D-018 rate limiter expired and the identical step was attempted
again. The plant therefore sat **~30 of every 36 minutes a full kelvin warmer
than it could actually sustain**, on the hottest day of the year.

This is textbook integrator windup against a saturated actuator, with the
saturation forgotten between attempts. The fix is to remember it: a setpoint
rejected at a given supply limit is infeasible *for that limit*, so no amount
of waiting can make it succeed — only the constraint moving can. Retry is
gated on the limit falling by `constraint_retry_margin_c` (0.5 K, half a trim
step), never on elapsed time.

Three details that are load-bearing:

- **Remember the LEAST aggressive failure.** If 19 °C breaches, 18 certainly
  would too, so remembering 19 blocks both; remembering 18 would leave 19 to
  be rediscovered one wasted cycle at a time.
- **Block only setpoints at or below the rejected one.** Blocking everything
  would strand the plant at whatever setpoint it happened to hold.
- **Fail toward trying when the limit is unknown.** The measured-breach branch
  is the real protection, so a wasted attempt costs one step, whereas wrongly
  blocking strands the plant somewhere it could have improved on.

**Rejected: widening the trim's guard band, or slowing the retry.** Both hide
the oscillation while leaving the plant further from the achievable setpoint —
the loss already lives in the thirty-minute wait, so lengthening it makes the
loss larger, not smaller.

The blocked state is now reported rather than silent (`water_sp/blocked`, plus
an edge-triggered warning). "The plant cannot meet demand and knows why" was
previously the quietest state in the system, which is how this ran unnoticed
for a full afternoon. Supersedes nothing; refines D-018.

Note the deeper finding this exposed, which is a plant property and not a
control bug: the day was **condensation-limited, not capacity-limited**.
Indoor dew point rose 2.0 K through the day and the supply limit tracked it
exactly, so the floor's usable supply temperature rose while the load peaked.
Radiant floor cooling cannot dehumidify — it must stay above the dew point —
so latent load accumulates and tightens the very constraint limiting sensible
cooling. Constraint memory stops the plant wasting capacity it has; it cannot
create capacity the dew point forbids.
