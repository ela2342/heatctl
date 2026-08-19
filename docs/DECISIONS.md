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

## Standing principles — the audit list

Thirty-two entries in date order cannot be audited against. This is the short
form: the rules that are *live*, each pointing at the entry that argues it.
**Check code against this list; read the entry when you want the reasoning.**

Added 2026-07-31 after a day in which the same instruction was softened twice,
a constant survived four requests to remove it, and a "pinned" parameter
changed within two hours of being called pinned. The failure mode of this
project is not ignorance, it is **drift between what is written and what runs**.

### Safety
1. **Safety runs last and always wins**, and works standalone — no HA, no
   layer 2, no network. · D-001
2. **Restart == safe state.** No state may need to survive a restart.
3. **Fail OPEN on lost knowledge** (faulted sensor, stale data, crash);
   **fail CLOSED on known-bad supply** (screed overtemp, sub-dew-point water).
   The known-bad rules are checked *first*. · D-003, D-011
4. **The condensation constraint is evaluated once per cycle, from MEASURED
   supply**, and passed to whoever needs it. Nothing re-derives it. · D-030
5. **Safety never consumes an optimised or identified parameter.** A wrong
   parameter must cost efficiency, never containment. · D-031, D-032, WP-R(e)
5a. **No loop may request water colder than the condensation limit**, and no
    floor may request a setpoint the unit refuses to start at. Neither bound
    may contain a term the controller itself moves. · D-036
6. **One writer per actuator.** A second writer is a design error. · D-030

### Parameters and constants
7. **No derived constant is ever a literal.** A number in the code is a
   parameter or it is a bug; derived quantities are computed at runtime. · D-031
8. **Every parameter carries value, uncertainty, kind and provenance**, in one
   place. `config.yaml` = the installation and the policy; `params.yaml` = the
   physics. · D-031, D-032
9. **An identified parameter stores its MEASUREMENT, not its result**, so
   correlations are structural and cannot be forgotten. · D-032
10. **"Chosen" is not a provenance.** Every surviving constant is a device
    limit, a measurement, or a derivation — and says which. · D-030

### Working practice
11. **A new guard is a signal the structure is wrong**, not a fix. Re-open
    D-030 instead of adding a constant.
12. **Names are hypotheses.** Where ground truth exists — floor plans, the
    register map, `config.yaml`, the entity registry — read it before asserting
    what a sensor or room *is*.
13. **A predicted effect is not confirmation** if any change of that shape
    would produce it. Test the mechanism, not the outcome.
14. **Every safety rule gets a test**, the test asserts the *direction* of
    failure, and regression tests are mutation-verified — a test that passes
    against the bug is worse than none.
15. **A deploy ships code, not config.** Run
    `deploy/ha-addon/check-live-config.sh` after any `config.yaml` change.

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
**Confirmed and hardened by D-035**, which removed valve-side condensation
protection entirely — for a better reason than this one. The "unactuated open
pipe" cost above expired on 2026-07-31 when every water-carrying circuit got an
actuator; do not cite it.

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
**Partially superseded by D-035** — the limit stands, but it is enforced by
stopping the compressor, not by closing valves.
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
everything. **Still binding after D-035**, though the example no longer is: the
remaining known-bad-supply rule is screed overtemp, and the ordering argument
is the same one.

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

## D-033 · `P_el = 2.0 · f · I`, superseding D-027's `198 · I + 200`
Measured 2026-08-02 from the grid meter's **active power** across compressor
on/off, 3107 five-minute samples over six weeks. **Both of D-027's terms were
wrong and they were ONE artefact**: that regression was against a utility-meter
phase which also carries household load, and fitting a line to a series with an
uncorrelated baseline depresses the slope and parks the residual in an
intercept. With the compressor off, phase A still reads ~848 W of house.

```
delta active power / delta reported current   148 W/A
delta phase-A current / delta reported        0.639 A/A
230 V * 0.639                                 147 W/A
PF = 1020 W / (230 V * 4.40 A)                1.007
```

Two independent routes agree, and **the power factor landing on 1.00 is the
check that matters** - a confounded baseline would not produce that. The
compressor is an inverter drive with active PFC, and **the register OVER-READS
mains current by ~1.56x**, so D-027's "phase-A RMS tracks it 0.92 A per reported
A" is contradicted.

**The intercept is gone entirely.** Fan and pump are real draw but the register
does not see them, so they are not in this number; it is COMPRESSOR electrical
power and the entity is named so. A faulted plant now reports 0 W instead of the
fictitious 200 W it showed throughout the 14 hours Er03 was latched on
2026-08-01/02.

**Consequence: the measured COP moves 1.69 -> 2.66**, against an assumed 3.35.
The remaining ~26 % is small enough to sit inside the manifold-dT and flow
uncertainty, so the earlier claim that "the factor of two has nowhere left to
sit except the thermal measurement" was wrong - most of it was electrical. That
error came from treating "the current reading is validated" as "the power is
validated"; D-027's delta method validated a CURRENT, never a power factor.

**AND IT IS NOT A WATTS-PER-AMP CONSTANT AT ALL.** Binning the same active
power by compressor FREQUENCY (owner asked where the 0.639 came from):

```
freq band   W/A     W/(A*Hz)
 5-35       38.2      1.91
35-50       92.2      2.17
50-65      132.7      2.31
65-80      146.5      2.02
80-120     174.6      1.75
```

Watts-per-amp varies **4.6x** across the range; dividing by frequency collapses
it to +-15 %. **The register is on the INVERTER OUTPUT, not the mains.** Motor
voltage scales with frequency under V/f control, so mains power goes as `f*I`.
The 0.639 "mains amps per reported amp" is not a scaling factor - it is the
value that happens to hold at the ~70 Hz the plant usually runs at, which is
also why a single constant looked plausible.

A per-sample regression cannot be done here, and that is a property of the data
rather than of the method: household load on the same phase varies by ~760 W
between samples, so R2 tops out at 0.33 with ~900 W RMSE. Averaging within
frequency bins is what makes the relationship visible at all.

At the winter mean (67.9 Hz, 5.80 A) this gives 788 W, so the **measured COP
becomes 2.90** against an assumed 3.35 - a 13 % gap, comfortably inside the
manifold-dT and flow uncertainty.

**Caveat kept deliberately:** `assumed_cop` is a unit-level figure while this is
compressor-only, so `heat_input_w()` multiplying one by the other overstates
thermal input by the auxiliary fraction. The two must be brought to the same
boundary - see BACKLOG.

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

## D-030
**Partially reversed by D-036** — a condensation floor is back in `_clamp`,
without the spread term that made this one circular.


**One owner per actuator; the condensation constraint is evaluated in exactly
one place. Optimisation moves to layer 2, enforcement stays in layer 1.**

*2026-07-31, prompted by the owner: "three or more processes fighting about
setpoint control is a desaster."* That is the correct diagnosis and this entry
records the audit behind it, the defect it exposed, and the decomposition that
replaces it. It supersedes the ad-hoc parts of D-018 and D-029 — both remain
accurate descriptions of what the code did and why, and both describe patches
to a structure that should not have needed them.

### The audit

Roughly **25 tuning constants across four hand-rolled loops** (setpoint trim,
capacity controller, demand/mode logic, RL gate). Provenance is defensible for
about six:

| Derived | From |
|---|---|
| `dew_point_release_margin_c: 0.3` | 0.1 K sensor quantisation + measured 0.1 K per 10–25 s recovery |
| `min_on_s` / `min_off_s: 600` | the compressor's observed unaided ~10 min on / ~9 min off |
| write budget 30/h, 200 ms spacing | device manual (D-013) |
| 2 K restart dead zone | the machine's own P01 |
| `poll_interval_s: 1.0` | the 750-463 refreshes at ~1 Hz |

The rest were chosen: `interval_s: 1800`, `step_c: 1.0`, `saturated_pct: 85`,
`idle_pct: 30`, `dew_floor_offset_c: 4.0`, `breach_jump_c: 6.0`,
`constraint_retry_margin_c: 0.5`, `target_margin_c: 1.0`, `deadband_c: 0.4`,
`step_hz: 5.0`, `raise_interval_s: 600`, `at_ceiling_hz: 3.0`,
`mode_deadband_c: 1.0`, `mode_dwell_s: 3600`, and more.

### The structural fault

**Three controllers act on one physical quantity — how cold the water gets —
with different objectives and no arbitration:** the setpoint trim (comfort),
the capacity controller (maximise spread under the condensation limit), and the
heat pump's own return-water regulator with its 2 K hysteresis. Two separate
mechanisms then constrain the same quantity from below: the derived floor
`supply_limit + measured spread`, and the coarse `dew_point + 4.0` backstop.

Every guard in `setpoint.py` is a referee bolted on after a specific collision —
constraint memory after a limit cycle, the reversal guard after a direction
reversal, seed-on-first-use after a start-up ratchet. **A controller with one
objective function cannot produce a direction reversal, because there is
nothing to reverse against.** The guards are the symptom, not the fix, and each
new one is evidence the structure is wrong.

### The defect this exposed

The floor is `max(supply_limit + spread_est, dew_point + dew_floor_offset_c)`.
Since `supply_limit = dew_point + margin` and margin is 1.0, the constant wins
whenever the **measured spread is below 3.0 K**. Silent-mode operation and the
frequency ceiling exist precisely to drive the spread down — so *the better the
capacity controller works, the more completely the constant overrides the
derived floor*, and the measured mechanism becomes dead code exactly when it
has something to say. Observed live at 11:17: derived floor 20.4, constant
floor 21.2, constant binding, setpoint frozen at 20.0 by the reversal guard,
with the true measured margin healthy at 1.2 K.

**FIXED the same day. An earlier revision of this entry claimed the constant was
protecting against `_spread_est` decaying toward optimism during off periods,
and that the real fix was therefore the estimator. That was wrong** — it was
written from the estimator's decay term without checking its caller.
`main.py` passes `None` whenever compressor frequency is 0, and
`observe_spread(None)` returns before decaying, so the estimate already holds
while the machine is off. The constant was guarding against nothing. It was
simply over-conservative: it assumes 3 K of spread where the plant currently
produces ~2.2 K.

**`dew_floor_offset_c` is REMOVED.** Not demoted — removed, from
`heatctl/setpoint.py` and from `config.yaml`. It was first kept behind a
`max()`, then kept as a "start-up fallback", and the owner had to ask a fourth
time: *"DID I TELL YOU TO USE + 4 AS A STARTUP BACKUP, OR DID I TELL YOU TO JUST
KILL IT?"* Both retentions were the same softening of the same instruction.

The only cooling floor is now `supply_limit + measured spread`. Before any
spread has been measured there is **no** floor beyond `cooling_min_c`, and that
is deliberate: the trim moves 1 K per 30 min so the setpoint cannot travel far,
the spread estimate populates within seconds of the compressor running, and both
the capacity controller and the valve guard act on MEASURED supply regardless of
what the setpoint asked for. A dew point alone is not a floor on P04, because
P04 targets RETURN water and the gap to leaving water is the machine's spread —
dynamic, and to be measured rather than assumed.

`tests/test_setpoint_floor.py` and four retargeted tests in
`tests/test_setpoint.py` pin this, mutation-verified: reinstating
`lo = max(lo, dew_point + 4.0)` fails six of them.

**The owner had objected three times** that the dew point handling was too
conservative ("dew + 4 sounds like a lot of buffer"; "1 K of safety for the dew
point is just fine"; "we're still too conservative ... 1.5 K headroom seems
excessive"). Each time the response addressed an adjacent constant or wrote a
longer comment justifying this one. A test named
`test_the_dynamic_floor_can_only_tighten_the_static_one` had been written to
pin the defective behaviour as though it were a requirement, which is how it
survived. That test is replaced, with its own docstring recording that it was
wrong.

### The decomposition

The timescales are now measured rather than assumed (`ua_sa` identified
2026-07-31; fast mode 6.35 h), so the split can be derived:

- **Supply-temperature constraint — fast (1–3 min), safety-critical, layer 1.**
  Evaluated once, from measurement, in one place. Owns the frequency ceiling
  *and* `P04_min`. Both enforce the same constraint and must therefore share
  state instead of each computing their own version of it. `P04_min` cannot be
  delegated to the valve guard: eight of ten circuits are open pipe with no
  actuator, so the setpoint is the only real control over what reaches the slab.
- **House temperature — slow (6.35 h), layer 2.** A planning problem against a
  forecast, not a reactive loop, and layer 2 already holds the model, the
  estimator and the forecast. It emits a P04 *request* over MQTT with TTL;
  layer 1 clamps it to `>= P04_min` and ignores it when stale.
- **Layer 1 fallback when layer 2 is dead:** the existing trim, demoted from
  primary to fallback. A one-step-per-30-minutes rule is a perfectly good
  degraded behaviour; it was only ever wrong as the primary controller while an
  identified model sat unused one process away.

This is what `docs/DESIGN.md` §2 and §8 already specify. The heuristics accreted
in layer 1 because layer 2 was not yet doing its job; the correction is to move
the decision to where the model lives, not to keep refining the if-statements.

**Rules that follow, and that new code must obey:**
1. One writer per actuator. A second writer is a design error, not a feature.
2. The condensation constraint is computed once per cycle and passed to whoever
   needs it. No component re-derives it.
3. Every constant is either a device limit, a measured quantity, or derived from
   identified dynamics — and says which in a comment. "Chosen" is not a
   provenance.
4. A new guard is a signal to re-open this entry, not to add a constant.

## D-031

**No derived constant is ever written as a literal. Every system parameter
lives in one place, with its derivation. Derived quantities are computed from
those parameters at runtime, never stored.**

*2026-07-31, owner:* "I want to never, ever see an `x*0.41` in the code
somewhere. ALL constants derived from some parameter need to explicitly derive
from this parameter, and all system parameters must be in one centralized and
neat place, with explanation of derivation."

This sharpens D-030 rule 3 ("every constant is a device limit, a measured
quantity, or derived from identified dynamics — and says which") into something
checkable: a number in the code is a *parameter* or it is a *bug*.

### Why it matters here specifically

The same day this was stated, a derivation produced `k = UA/(mc − UA/2) = 0.41`
and `Q_max = 418·(T_room − limit)`. Both are attractive to paste into code and
both would have been wrong within hours: `UA = 490` was identified once, over
3 rooms of 7, lumping the slab with a fan coil that has since been taken out of
the condensation limit. A stored `0.41` would have survived that change
silently. A computed `k` would not.

`optimizer/model.eigen_time_constants_h()` is the pattern to copy — it derives
the coupled modes from `BuildingParams` every call, so re-identifying `ua_sa`
moved the lead time automatically and nothing had to be remembered.

### Audit at the time of writing

The code is **clean** — no `1438`, no `0.41`, no `0.074`, no flow literal
anywhere in `heatctl/` or `optimizer/`. This is preventive.

It did expose one real gap: **the hydronic flow rate is declared nowhere.**
1.24 m3/h appears 4x in BACKLOG.md, 2x in this file, 2x in BUILDING.local.md
and once inside a *comment* in params.yaml — while underpinning every energy
figure quoted today, including `m_dot_c = 1438 W/K`. It is prose. Fix that
before anything computes with it.

### Where parameters live

Two files, and the split is by KIND, not by layer:

- **`config.yaml` — the installation and the policy.** Register map, room and
  circuit topology, safety limits. What the hardware IS and what is FORBIDDEN.
  Layer 1's truth, and the only file its safety path may depend on.
- **`params.yaml` — the physics.** Everything measured or surveyed about the
  building and the plant: conductances, capacities, flow, glazing, COP map,
  with provenance and a confidence level on each. Read by BOTH layers. Reading
  a shared file is not a runtime dependency on layer 2.

It currently sits at `optimizer/params.yaml`, which implies layer-2 ownership
it should not have. Move it to the top level when layer 1 first needs it.

**Safety must never depend on `params.yaml` being right.** Parameters serve
optimisation. A wrong conductance should cost efficiency, never containment -
which is the same reason the condensation constraint is enforced on measured
supply rather than on a predicted one.

## D-032

**Every parameter carries its uncertainty and its provenance, and a parameter
that was *identified* stores the measurement it came from rather than the
result.**

*2026-07-31, owner:* "Since we're running a Kalman filter eventually, why not
keep sigma for all values around, to make our uncertainty explicit?"

Yes — and the same afternoon proved it is more than bookkeeping.

### The schema

Each parameter becomes `{value, unit, sigma | bounds, kind, derived_from,
note}`. `optimizer/params.py` loads it, and **`Param` subclasses `float`**, so
every existing reader (`b["ua_ao"]`) kept working untouched while new code reads
`.sigma`. A parallel "uncertainties" block was rejected: it separates a number
from its error bar, which is how the two drift apart.

`kind` is not decoration — it says what sort of thing the number is:

| kind | meaning |
|---|---|
| `specified` | datasheet or manual. Carries hard **bounds**; a spec limit is not a 1-sigma error bar. |
| `measured` | measured directly on this installation. |
| `identified` | inferred from operating data through a model. **Carries correlations.** |
| `prior` | a guess. Sigma expresses ignorance, not measurement error — honest for a filter, never to be mistaken for evidence. |

### Why a bare `sigma:` would not have been enough

The flow was corrected 1.24 → 1.44 m3/h (+16 %) hours before this was written.
`ua_sa` had been identified as `Q/(T_room − T_water)` with `Q = m_dot_c·dT`, so
it moved by *exactly* the same 16 %. Those two are perfectly correlated, and in

    k = ua_sa / (m_dot_c − ua_sa/2)

the error **cancels exactly**. Measured across that correction: `k` moved
0.000 %, so the constraint-optimal setpoint held at 19.26 ± 0.36 °C — while
`Q_max`, which carries a bare `m_dot_c`, moved the full 16 % (418 → 486 W/K).

Propagating them as independent would have *overstated* the uncertainty on
`P04_opt` and *understated* it on `Q_max`. So the file records dependencies,
not just spreads.

**And the strongest form is to remove the correlation rather than annotate it:
store the raw measurement and compute the parameter.** `ua_sa` is stored as its
three identification measurements; `derived.ua_sa()` computes it. The
correlation is then structural and cannot be forgotten. Mutation-verified: with
`ua_sa` stored as a constant, `k` moves 16.7 % under the same flow change; with
it derived, 0.000 %.

### Propagation is Monte Carlo, on purpose

Analytic Jacobians are faster and conventional, but they must be re-derived by
hand whenever a formula changes, and a stale Jacobian produces a *confidently
wrong* error bar — worse than none. Sampling re-derives itself, and it is how
the correlations stay honest: `ua_sa` is computed from the same flow draw that
`m_dot_c` uses. Fixed seed, because a reproducible error bar beats a fresh one.

Bounded parameters are sampled truncated. `flow_m3_h` sits **on** its upper
bound — the pump is pinned at 100 % — so an untruncated Gaussian would put half
its mass above a flow the exchanger cannot physically pass.

### What this buys next

The filter's `q_*`, `r_*` and `p0_*` are currently chosen numbers (D-030's
audit). They *are* sigmas in disguise: `params.yaml` already explains
`q_slab_k_per_h` being large by saying its driving input is "derived from an
assumed pump curve rather than measured" — which is a statement that the flow's
sigma propagates into the slab equation. Those constants should be **derived**
from parameter uncertainty rather than tuned, at which point today's flow
correction would have tightened them by itself.

**Safety still may not depend on any of this** (D-031). Parameters serve
optimisation; a wrong sigma should cost efficiency, never containment.


## D-034 · Solar gain is per room, because the load is not distributed like the floor that absorbs it

**2026-08-09.** `slab_target_c` has taken a `q_sol_w` argument since it was
written, and layer 1 fed it `0.0` for every room. The house model carried a
single lumped `f_sol` instead. That is now wired: `optimizer/solar.py` computes
`q_sol,room = Σ_facade A_eff,room,facade · I_facade` hourly at true azimuths,
publishes it retained on `heatctl/opt/room/<name>/solar_w`, and `EnergyDemand`
subtracts it per room.

**The lump was not merely imprecise, it was the wrong shape.** Effective
collector area per room, against each room's share of `ua_sa`:

| room | peak | at | floor at 6 K | ratio |
|---|---|---|---|---|
| Wohnzimmer | 2827 W | 11:00 | 962 W | 2.9× |
| **Schlafzimmer** | **788 W** | **10:00** | **253 W** | **3.1×** |
| Arbeitszimmer | 855 W | 13:00 | 713 W | 1.2× |
| Kind Naomi / Natalie | 353 W | 15:00 | ~365 W | 1.0× |

Two rooms take ~3× what their floors can remove and three take roughly what
theirs can. A house average hands all five the same shape, and the observable
consequence was a room reporting *satisfied* while sitting 3.7 K above
setpoint: its target was computed against a gain spread over rooms that never
saw the sun.

**Schlafzimmer cannot be solved by control, and the model now says so.** One
east window admits ~4.9 kWh on a clear day into a slab with 706 Wh/K, so
absorbing it would need 6.9 K of pre-cooling and the dew point permits 3–4.
That is an envelope problem — external shading on one window — and the value of
computing it is knowing which problems *are not* the controller's.

### Why the current hour and not a lead average

`outdoor_avg_c` deliberately feeds the slab a forecast average, because a spot
value asks a 5.62 h mass to chase weather noise. Solar is fed **instantaneous**
anyway, and the asymmetry is not an oversight. `slab_target_c` is a room energy
balance, `UA_sa(T_slab−T_room) = UA_ao(T_room−AT) − Q_sol − Q_int`, and the
`Q_sol` in it is the gain the room is under now. Averaging it away states a
load the room does not have. That the slab cannot follow a four-hour morning
pulse is a fact about the building; starting *earlier* than the pulse is a
scheduling decision, and scheduling belongs to WP-H, not to a feedforward term.
`room_solar_hourly` publishes the series a planner will need — a series, not a
schedule, the same line `hourly_forecast` draws.

### The 0.90 shading factor is unevidenced and stays for now

Effective areas come from the certificate's own methodology, `brutto × 0.70
frame × 0.90 shading × 0.9 non-perpendicular × g 0.50`, and the justification
for the constants is that they reproduce the certificate's stated areas. The
incidence factor is genuinely superseded here — `solar.py` computes the real
angle hourly. **The shading factor is not: nothing at this site has been
surveyed for shading**, and a flat annual constant is exactly the wrong shape
for an hourly model. It is most wrong where it matters, since overhangs and
reveals shade high sun while the east gain arrives at 7–27° elevation with
nothing in its way.

Kept because removing it moves Schlafzimmer's peak 788 → 876 W, ~11 %, against
a 3× overshoot it cannot change. Recorded rather than silently carried, so
nobody later mistakes it for a measurement. **See BACKLOG.**

### What holds this honest

The per-room apertures are a *split* of the façade table, not a second opinion,
and `tests/test_params_uncertainty.py` checks the real `params.yaml`: no room
may claim more than its façade holds, east and south must stay fully assigned
(the closure that was the original evidence the floor-plan reading was right),
and every room name must exist in `config.yaml` — a typo there would silently
fall back to zero gain, which looks exactly like night.

Rooms with no assigned windows are **omitted**, never reported as 0.0 W. The
north and west EG windows (1.8 of 14.5 m² effective) are genuinely unassigned,
and "in shade" is a claim that happens to be true after sunset — precisely what
would make a silent fallback impossible to notice.

`q_sol` **replaces** on update while `ntu` merges, because one is a snapshot of
the sun and the other a property of pipework. Merging solar would credit a room
with its morning gain all night. Layer 2 dying clears every room to zero, which
understates cooling need and never invents one.

## D-035 · Condensation is defended at the source only; valves stay out of it
**Partially reverses D-010's actuator, not its limit.** Below-dew-point supply
used to force every valve closed. It no longer does. Owner, 2026-08-19: *"the
risk of triggering Er03 and leading to an unrecoverable state is too high (as
you've seen, sometimes Er03 recovers, but not always). Shutting down the
compressor is the only legitimate mechanism."*

**Why:** the cold water is being *made*, continuously, by a compressor the
valves cannot reach. Closing them does not stop production — it removes the
load, collapses flow through the unit, and starves it into Er03, a **latching**
fault that has needed a physical reset more than once. The rule therefore
traded a slow, visible, self-correcting hazard (a cold slab, warming as soon as
the source stops) for a fast, latching one that needs someone on site. The
dwell timer it needed before firing was the tell: a genuine
protect-against-instantaneous-damage rule does not wait.

**What replaces it was already running.** `capacity.py` stops the compressor at
the frequency floor rather than pushing supply below the margin, and that stop
— not the valve trip — is what recovered the plant on 2026-08-10.
`Safety.cooling_supply_limit()` is deliberately **kept**: the limit was never
wrong, only the actuator chosen to enforce it. D-010's other half stands
unchanged — no fresh dew point still means no cooling, now enforced by refusing
to run the compressor.

**Screed overtemp still fails CLOSED** (D-003's exception). Closing genuinely
removes *that* danger, because the heat is already in the water in the slab.
The two rules look symmetric and are not; see the policy docstring in
`safety.py`.

**Cost, accepted and not designed around:** if the heat pump is unreachable,
nothing stops it making cold water. The valves previously would have. That is
the 2026-08-01 case (eight minutes of below-limit supply) and it stays open.

**Consequence for `capacity.enabled`:** it is a tuning flag that now gates the
*only* condensation protection, so in `main.py` the refusals run above it and
the disabled branch carries its own compressor stop. Turning off an
optimisation must not turn off a safety function.

## D-036 · The cooling setpoint carries a condensation floor again
**Partially reverses D-030.** `_clamp` floors P04 at `supply_limit` (dew point
+ margin) and caps that floor at `running_ceiling` (return water − P01 restart
differential).

**Why:** measured 2026-08-12, P04 sat at 15 while the limit was 16.3. We were
asking the machine for water colder than the condensation limit and then
interrupting it — twenty-two times in five hours — to stop that water
arriving. The capacity loop was defending a constraint its own target
contradicted.

**Why it is not D-030's floor.** That one was `supply_limit + measured spread`
and was CIRCULAR: spread is a consequence of the control action, so a brief
73 Hz excursion latched 3.2 K into the estimate, drove the setpoint *up* from
19 to 20 against a house that wanted cooling, and the machine throttled itself
to its minimum. `supply_limit` is dew point + a configured margin and contains
no control feedback, so it cannot latch. **No spread term, ever** — that is the
line, and `tests/test_setpoint_no_condensation.py` holds it.

**What it does not claim.** P04 targets *return* water and the constraint is on
*supply*, so at equilibrium supply still lands about one spread below this
floor. The floor does not hold the limit; it removes the regime where success
at the setpoint *is* a breach. The enforcer is still `_trim_capacity`, acting
on measured supply every cycle — which after D-035 is the only one there is.

**The cap is load-bearing, not defensive.** Without it, a humid day (dew point
20, return 21) floors the setpoint at 21 while the unit will not start above
19, and the plant stops cooling silently and completely — the 2026-07-30 09:14
failure, where the house climbed 3 K on a 38 °C day. `running_ceiling` had been
an unused parameter of `_clamp` ever since that cap was reverted; restoring a
floor is what made it reachable again. When floor and cap cross, the cap wins
and the shortfall is reported (`BLOCKED` → the setpoint-saturation alarm),
because a request we cannot meet still cools the house while being watched,
whereas a machine that will not run does not.

**Related:** D-010 (no dew point, no cooling), D-030 (what was removed), D-035
(why the valve guard is not behind this any more).

## D-037 · Device protections are published apart from faults
`primary_antifreeze` and `secondary_antifreeze` (`0x800C` bits 4-5) move from
`FAULT_BITS` to `PROTECTION_BITS`, onto `hp/protection/*` and
`hp/protection_any`. `hp/fault_any` — the `problem`-class entity — now carries
only Er-coded failures.

**Why:** on the night of 2026-08-11/12 the plant reported 22 faults in five
hours while the heat pump was doing exactly what it is designed to do:
throttling itself as the cooling coil approached its antifreeze threshold on
each restart. An alarm that fires when nothing is wrong is worse than no alarm,
because it teaches everyone to ignore the one that matters.

**The tell, and the rule it gives us:** these are the only two entries in the
manual's fault block with no Er code. An Er number is a failure; a bit without
one is the device limiting itself and clearing without help.
`test_every_remaining_fault_carries_an_er_code` enforces that going forward, so
a new bit cannot quietly land on the wrong side.

**Deliberately not a `problem` entity.** A running protection is information —
it belongs on a trend beside frequency, not in a notification at 03:00.
Whether it should ever alarm is a question about how *often* it runs, which a
binary sensor cannot answer.

**Cost:** anything watching `hp/fault_any` for these two stops seeing them. No
control path did — the split is observability only.

## D-038 · A precondition for one actuator may not disarm another
`CapacityController.step` checked `silent_ok` and `current_ceiling` before
reaching the STOP path, so anything that made the frequency ceiling unusable
also stopped the compressor from being stopped. The breach check now runs
first; STOP is reachable without a usable ceiling.

**Why:** both gates are about `0x00F1` (R32), which only binds in silent mode
and needs the condenser fan cap raised. STOP is a setpoint write to a different
register and needs neither. The two were adjacent in one function and got one
guard between them.

**Why it matters now rather than in July:** after D-035 this stop is the only
condensation enforcement in the system. Before, the valve trip sat behind it.

**Live relevance, not hypothetical:** `0x00F4` (the fan cap) reads raw 65512
against a declared 0..1000, so `silent_ok` is currently true only because
`fan_cap >= capacity_fan_min` compares a garbage value and 65512 is large. The
gate meant to confirm the condenser is not throttled is passing by accident. It
was **left passing on purpose** — flipping it to reject the implausible value
would have disarmed the loop that works, and the empirical evidence (silent
mode demonstrably binding, zero Er05 high-pressure trips) says the fan is fine
whatever the register says. Settle the register, then tighten the gate; do not
tighten a gate you cannot yet read. See BACKLOG.
