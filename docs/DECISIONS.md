# Decision log

**What belongs here:** a decision that establishes a principle, or that
*reverses* an earlier one. Not routine work — that is in `PLAN.md`.

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
**Supersedes** an assumption inherited from `PLAN.md`, which the HA automation
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
