# Hardware documentation (as of July 2026)

## Node: WAGO 750-352, 192.0.2.52 (static DHCP lease)
DIP switches all ON (=255 = DHCP mode).
WBM: https://192.0.2.52.
MANDATORY for mqtt backend: enable the coupler's Modbus watchdog so
outputs fall to a safe state when writes stop.

## Terminal layout (left to right)
| Pos | Terminal  | Function                            | Modbus |
|-----|-----------|-------------------------------------|--------|
| 1   | 16DI      | 16 digital inputs (free)            | discrete inputs 0-15 |
| 2   | 750-652   | RS485 (unused)                      | IR/HR 0-11 |
| 3-6 | 4x750-463 | 16x PT1000, degC*10, 2's complement | input reg. 12-27 |
| 7-10| 4x750-559 | **16x 0-10V (0..32767)**            | holding reg. 12-27 |
| 11-12| **2x750-517**| 4 relay outputs (2 changeover each), potential-free | coils 0-3 |
|     | 750-600   | bus end terminal                    | -      |

**Changed 2026-07-27: two more 750-559 fitted** (positions 9 and 10), so
there are now 16 analog outputs, not 8. Verified against the coupler:
AO index n -> holding register 11+n -> `M{7+(n-1)//4}Ch{(n-1)%4+1}`, read
back at `0x0200 + 11 + n`. The INPUT image is unchanged - 16 PT1000 still
at input registers 12-27, since the added modules are outputs.

Which analog output drives which circuit remains **unverified except
channels 1 and 2**. config.yaml keeps indices 1-8 at their existing names
on purpose: renumbering them would silently move which physical valve
heatctl drives, and 1 and 2 are the only confirmed ones.

### Register spaces - read-back gotcha (verified on hardware 2026-07-26)
The coupler overlays the input and output process images in the same low
address range, so **you cannot read back what you wrote at the address you
wrote it to**:
- FC4 (read input registers) at 12..27 -> PT1000 values. As documented above.
- FC6/FC16 (write) at 12..27 -> the 750-559 analog outputs. Correct, works.
  (12..19 before the second pair of modules was fitted on 2026-07-27.)
- FC3 (read holding registers) at 12..27 -> **returns the INPUT image, i.e.
  temperatures again, NOT your output values.** Reading 12/13 right after
  writing them returns ~174/175 (17.4/17.5 degC), which looks like a failed
  write but is not.
- The output process image is mirrored for reading at **0x0200 + word
  offset**: output word 12 reads back at 524 (0x020C), word 27 at 539.
  Verified by writing 16383 to HR12/13 and finding it at 524/525, and again
  across the full 16-output image on 2026-07-27.
- **0x1000+ IS valid** - the watchdog configuration block lives there. An
  earlier note in this file claimed otherwise; that was wrong, and only looked
  that way because a 32-register block read spanned past the end of the block
  and returned illegal-data-address for the whole request. Read these one or
  two registers at a time.

### Modbus watchdog - from the manual (750-352 Handbuch v1.2.0, sections 9.6 / 11.2.5)
Authoritative, replacing three earlier guesses in this file that were wrong.
Manual: /mnt/c/Users/Ela/Downloads/750-352.pdf (pp. 112-113, 171-177).

| Addr | Access | Meaning | Default | Read live 2026-07-26 |
|------|--------|---------|---------|----------------------|
| 0x1000 | R/W | Watchdog time, x100 ms | 0x0064 = 10 s | 100 = 10 s |
| 0x1001 | R/W | Coding mask, FC **1..16** | 0xFFFF | 0xFFFF |
| 0x1002 | R/W | Coding mask, FC **17..32** | 0xFFFF | 0xFFFF |
| 0x1003 | R/W | Watchdog **trigger** (toggle register - see below) | - | 0 |
| 0x1004 | R | **Minimum trigger time** | - | 0xFFFF |
| 0x1005 | R/W | Stop watchdog (write 0xAAAA then 0x5555) | - | 0 |
| 0x1006 | R | **Status**: 0 = not active, 1 = active, 2 = expired | 0x0000 | **0 -> not active** |
| 0x1007 | R/W | Restart watchdog (write 0x1) | 0x0001 | 0 |
| 0x1008 | R/W | Simple stop (write 0x55AA or 0xAA55) | 0x0000 | - |
| 0x1009 | R/W | Close MODBUS socket on time-out (0/1) | - | - |
| 0x100A | R/W | **Alternative watchdog** enable | 0x0000 | - |
| 0x100B | W | Make 0x1000/0x1001/0x1002 remanent (0x55AA/0xAA55) | - | - |
| 0x1028 | R/W | **Boot configuration** (NOT fieldbus-failure behaviour) | - | 4 |

**Outputs ARE set to zero on time-out.** Confirmed twice: WBM table for Watchdog
Timeout Value - "Nach Ablauf dieser Zeit ohne empfangenes MODBUS-Telegramm,
werden die physikalischen Ausgaenge auf '0' gesetzt" - and the 0x100A
description. With NC actuators that means valves close. Not configurable; see
the fail-open discussion below.

**Use Watchdog Type "Standard", NOT "Alternative".** An earlier note here
advised the opposite; that was exactly backwards. Per the WBM table:
- *Standard*: the coding mask decides which telegrams reset the timer.
- *Alternative*: **any** MODBUS/TCP telegram resets it.
So Alternative is the useless one for us - heatctl's once-per-second reads would
keep it alive with a dead write path. Standard with a mask restricted to the
write function codes gives the property we want.

**Mask to use: 0x8020 in 0x1001** = FC6 (bit 5, write single register) + FC16
(bit 15, write multiple). Then only actual output writes retrigger the watchdog,
so "watchdog satisfied" means "outputs are being driven" - and heatctl needs no
separate heartbeat, because its per-cycle valve write IS the heartbeat.

**Arming needs no coupler reset.** The WBM says its changes apply after a reset,
but that is about its EEPROM copy. Over Modbus: set 0x1000, then write a non-zero
mask to 0x1001 - that write arms it, live. Stop again with 0x1008 (0x55AA or
0xAA55). So arming and testing is fully reversible without an I/O outage, and the
"schedule a reset" caveat noted earlier does not apply to the register route.
Do NOT write 0x100B while experimenting - that makes the settings remanent.

### Verified end-to-end on hardware 2026-07-26
Armed and tripped deliberately with heatctl running as the HA App:

| Observation | Result |
|---|---|
| heatctl arms it on start | `coupler watchdog armed: 10.0 s, mask 0x8020 (FC6+FC16)`, status 0x1006 -> 1 |
| Stop heatctl -> trip | status 1 -> **2** after ~10 s |
| During the trip | process-data reads **blocked** (FC4 -> exception 0x04, Slave Device Failure), while **0x1006 stays readable** |
| heatctl restarted | detected exception 4, wrote the trigger, took the `stale_data` failsafe for that one cycle, and was back to `watchdog active` **1 s later** |

Two things this settles:
- The recovery design is sound *because* watchdog registers stay accessible
  while process data is blocked. That was an assumption; it is now observed.
- The failure surfaces as `stale_data`, not `cycle_error` - i.e. the
  read_state-never-raises rule keeps a watchdog trip semantically distinct from
  a bug, exactly as intended.

NOT verified, and not verifiable this way: that the outputs were physically
zeroed during the trip. Process-data reads are blocked precisely while it
matters, so the manual's statement is the only evidence. Confirm by watching an
actual valve if it ever matters.

### "Toggle register" is literal - verified the hard way 2026-07-27
0x1003 clears a trip on a **change** of value, not on a non-zero write. Writing
back the value it already holds is refused with **exception 0x03 (illegal data
value)** and clears nothing:

```
status=2 trigger=1  write 0x1003=1 -> exception 0x03,  status stays 2, process data BLOCKED
status=2 trigger=1  write 0x1003=0 -> ok,              status 2 -> 1,  process data restored
```

**Field failure this caused.** heatctl's first implementation wrote a constant
1. That recovered exactly once - the first trip, when the register still held
its power-on 0 - and never again. Overnight into 2026-07-27 the coupler tripped
a second time and stayed blocked for ~3.5 h: every read and write answered with
exception 0x04, valves held closed by the coupler's own safe state, heatctl
looping on `stale_data` with no way back without manual intervention. Note that
yesterday's end-to-end verification below passed *because* it was the first
trip. **One successful recovery test proves nothing here - test twice.**

Re-verified 2026-07-27 with the toggling implementation, two consecutive trips:

| Trip | trigger before | after recovery | Result |
|---|---|---|---|
| 1 | 0 | 1 | status 2 -> 1, process data restored |
| 2 | 1 | 0 | status 2 -> 1, process data restored (the case that used to be fatal) |

**heatctl MUST handle the trip, or one time-out disables control permanently.**
After a time-out the coupler answers *all* subsequent MODBUS/TCP requests with
exception 0x0004 (Slave Device Failure), and process-data writes stay blocked
until the watchdog error is cleared by writing a non-zero value to the trigger
register 0x1003 (or 0x1007). Without that recovery step, a single transient trip
leaves modbus_direct failing every read and write forever - staleness failsafe
looping, no way back without manual intervention. Any implementation must detect
status 0x1006 == 2 (or exception 4) and re-arm.

Consequence for anyone verifying valve output: read FC3 at `0x0200 + 12 + n`,
never at `12 + n`. Worth knowing that a read-back check is also the only way
to notice that the coupler's Modbus watchdog has fired and overwritten the
outputs with its safe state - heatctl does not currently do this (it treats
`IOState.valves_pct` as the last *commanded* value).

## Sensor assignment (750-463, channel n = input register 11+n)

### Where these sensors physically are - READ THIS BEFORE USING RL IN CONTROL
The per-circuit RL sensors are clamped to the **return pipes at the
manifold**. They are NOT in the slab and not distributed through the floor.

That placement decides what a reading means when its circuit is not flowing:
the sensor stops measuring the circuit entirely and equilibrates toward the
**manifold cabinet's ambient**, which is dominated by the flow and return
headers running past it - so it drifts toward roughly the system water
temperature, not toward slab or room temperature.

Consequence, and it is not the intuitive one: this causes **lock-out, not
oscillation**. With the interim `system_return` target (each circuit aims at
the mixed system return), a stagnant sensor reads ≈ header temperature ≈ the
target, so the error is ≈ 0 and the controller concludes there is nothing to
do. A closed circuit manufactures its own evidence to stay closed, silently
and indefinitely. This is the sensor-side view of the "all valves closed is a
valid equilibrium" problem that `system_return_bias_c` papers over.

Handled by `heatctl/rl_gate.py`: RL is only trusted after the circuit has been
commanded open long enough for water to have travelled it, and a held-closed
circuit is flushed periodically to take one honest reading. The flush is the
load-bearing part - holding alone preserves the lock-out.

(Recorded 2026-07-27 after the code and docs had asserted "a closed circuit's
RL sensor reads slab ambient" and reasoned from it. That was wrong.)

| Ch | Sensor    | Location                                   |
|----|-----------|--------------------------------------------|
| 1  | rl_hk01   | return, circuit 1 - Gästebad               |
| 2  | rl_hk02   | return, circuit 2 - Wohnzimmer             |
| 3  | rl_hk03   | return, circuit 3 - Kinderzimmer Natalie   |
| 4  | rl_hk04   | return, circuit 4 - Kinderzimmer Naomi     |
| 5  | rl_hk05   | circuit 5 - Bad Handtuchhalter (reserve, not installed) |
| 6  | rl_hk06   | return, circuit 6 - Badezimmer             |
| 7  | rl_hk07   | return, circuit 7 - Elternschlafzimmer      |
| 8-10| rl_hk08-10| return, circuits 8-10 - Wohnzimmer        |
| 11 | rl_hk11   | return, circuit 11 - Arbeitszimmer (recent addition) |
| 12 | rl_hk12   | circuit 12 - out of service                |
| 13 | vl_total  | supply total                               |
| 14 | rl_total  | return total                               |
| 15-16 | reserve | spare (PT1000 fitted)                     |
All 16 channels have PT1000 fitted (avoids wire-break faults on the
series-connected measuring circuits). Fault saturation values:
0x05DC (wire break / overtemp), 0xFED4 (short / undertemp).

## Actuators
4x 750-559, 16 channels of 0-10 V: Alpha 5 proportional actuators.

**Valve->circuit mapping RESOLVED 2026-07-27 (owner): it is 1:1 with the
circuit number.** Analog output n drives circuit n, and input n is that same
circuit's return sensor - "Input 1, output 1: Gästebad. Etc." So the sensor
table above and the output channels share one numbering, and outputs 13-16 are
genuine spares because there is no circuit 13-16.

This retired the long-standing TODO here ("8 outputs, 10 active circuits") and
corrected a real error in `config.yaml`. That file's 8-channel table had been
built around fitting 10 active circuits into 8 outputs, so it skipped the
out-of-service circuits and shifted everything after index 4:

| AO index | config used to call it | actually drives |
|---|---|---|
| 5 | `valve_hk06` | circuit 5, Bad Handtuchhalter (reserve) |
| 6 | `valve_hk07` | circuit 6, Badezimmer |
| 7 | `valve_hk11` | circuit 7, Elternschlafzimmer |
| 8 | `valve_spare` | circuit 8, Wohnzimmer |

Consequence while that was live: the Arbeitszimmer room PID - which has a real
room sensor and commands real percentages - was driving circuit 7's output.
Harmless in practice only because no actuator is fitted on any of those
channels. Worth remembering as the shape of the risk: a plausible-looking
mapping built by "fitting things in" rather than measured, silently pointing a
live controller at the wrong valve.

**Only circuits 1 and 2 have an actuator fitted** (still true as of
2026-07-27 - the two extra 750-559 *modules* arrived that day, which is not the
same as actuators being on the manifold). Every other circuit is open pipe, so
water circulates through them whenever the pump runs, with no way to throttle
them. Two consequences: the manifold cannot be balanced until the remaining
actuators arrive, and a "closed" state only exists for 1 and 2.

`config.yaml` tracks this per channel with `fitted:`, which is load-bearing in
two places - `heatctl/rl_gate.py` (an unactuated circuit always flows, so its
return sensor is always valid) and the demand controller's flow proxy (which
counts an unactuated circuit as 100 % open). Flip each to `true` as the
actuator goes on, not when the module arrives.

**These are NC (normally closed) actuators** - recorded as `stellantrieb: NC`
for every output in the legacy system's database. So loss of signal or power
CLOSES them. The project's fail-open policy (`safety.failsafe_valve_pct: 100`,
see heatctl/safety.py) therefore covers software and bridge failure only; a
genuine power loss still closes every valve. True hardware fail-open would
need NO actuators. Consequently, **the coupler's Modbus watchdog fallback must
be configured to drive the 750-559 outputs to FULL SCALE (10 V), not zero** -
the WBM default of "outputs off" is the wrong direction for this design.

### Actuator dynamics (control-relevant - do not ignore)
These are slow, open-loop actuators with **no position feedback**. The
commanded analog value is a *request*, not a measurement:
- **Lower deadband**: the valve does NOT begin to open at just any value
  above zero. There is a threshold below which the actuator is still fully
  closed, so commanded % != actual opening in the lower range.
- **Multi-minute stroke**: it can take several minutes from changing the
  analog output until the valve has actually reached the commanded position.
- Consequence: for minutes after any change, actual position is unknown and
  somewhere between the old and new value. Any RL reading taken during that
  window reflects neither.

**Model: Möhlenhoff Alpha 5 `APV 42505-00`** (owner, 2026-07-27). Datasheet
facts, which largely settle the deadband question:

| Property | Value |
|---|---|
| Control signal | **0 – 10 V**, direct acting |
| Supply | 24 V **DC** |
| Stroke | 5.0 mm |
| Closing force | 100 N |
| Direction | NC (spring closes when de-energised) |
| Mean running time (`Mittlere Stellzeit`) | **30 s/mm → 150 s full stroke** |
| `Ventilwegerkennung` (valve travel detection) | **yes** |

**Read the type key before assuming anything about a replacement.** Every
field above is encoded in the order code, and three of them are things heatctl
would get silently wrong if a differently-coded actuator were fitted:

    APV  4 2 5 05 - 00  [N00-1S]
    │    │ │ │       └─ control characteristic
    │    │ │ └───────── stroke: 4 = 4.0 mm, 5 = 5.0 mm
    │    │ └─────────── 0 = 24 V AC NC, 1 = 24 V AC NO,
    │    │              2 = 24 V DC NC, 3 = 24 V DC NO
    │    └───────────── Alpha 5 OEM proportional family
    └────────────────── APR = without valve travel detection
                        APV = WITH valve travel detection
                        (APP = pulse-proportional, APO = with feedback)

    control characteristic:  00 = 0 – 10 V      01 = 2 – 10 V
                             02 = 10 – 0 V      10 = 0 – 10 V (NO types)

    trailing N00-1S = base version / colour / 1 m pluggable lead.
    Shops truncate the code at various points; "APV 42505-00" and
    "APV 42505-00N00-1S" are the same actuator.

So our `-00` **is** the guarantee that the signal is 0–10 V direct-acting.
A `-01` (2 – 10 V) would make `open_threshold_pct` 20, not 5, and a `-02`
(10 – 0 V) is fully inverted — 0 % command would mean fully open. Likewise
`42505` vs `43505` is the NC/NO bit. Verified against the full variant table
in the Möhlenhoff *Technisches Datenblatt, OEM Antrieb 5: Proportional*
(document `100727AA-24`); local capture in `docs/ALPHA5.local.md`.

**The actuator linearises itself, which is why the identity mapping is right.**
Per the datasheet, an APV variant *"ermittelt der Antrieb den Ventilweg und
passt automatisch den aktiven Steuerspannungsbereich an"* — it measures the
actual valve travel and auto-adapts the active control-voltage range. It also
determines the valve closing point fully automatically on first power-up,
stores it across power interruptions, and re-checks it during operation.
Internally it regulates for *"Maximalhub abzüglich Überhub"* — maximum stroke
**minus over-travel** — so the over-elevation range visible on the
characteristic curve is compensated inside the device, not by us.

Consequence: `full_open_pct = 100` is correct for a physical reason, not merely
the safe default (D-021, D-022). Do not go looking for an upper deadband to
subtract; the drive has already subtracted it.

**The one real lower deadband is `Umin`.** *"Im Bereich von 0 bis 0,5 V
(Modell-abhängig) bleibt der Antrieb im Ruhezustand, um Brummspannungen durch
lange Leitungslängen zu ignorieren."* 0.5 V of 10 V is **5 %**, so commands
below that do nothing at all — hence `open_threshold_pct: 5.0`.

**`Totzeit` is a dead TIME, not a dead band.** The datasheet says the drive
opens *"nach Ablauf der Totzeit"* — after a delay, then moves evenly. It feeds
`settling_time_s`, not the voltage mapping. With 150 s of stroke plus that
delay plus hydraulic transport, the configured `rl_gating.settle_s: 300` has
comfortable margin.

**Commissioning note.** *"Im Auslieferungszustand halten NC- und NO-Antriebe
das Ventil geöffnet"* — via the First-Open function a new NC actuator holds its
valve **open** until the closing point has been determined after first power-up.
So a freshly fitted actuator is open regardless of what heatctl commands, until
it has self-calibrated. Expect that during build-out rather than treating it as
a fault.

**Preconditions for any thermal method.** It needs contrast between VL and the
slab - if VL is near slab temperature there is no signal at all, which is
exactly the state a well-tuned system sits in. Heating season is far easier
than cooling, where aggressive water collides with the condensation limit.
And with twelve circuits on one manifold there is cross-talk: opening one
changes differential pressure and therefore flow in all the others.

Record measured values here, and see docs/DESIGN.md section 4 for how they
feed the controller.

## Other devices in the system
- Heat pump: Modbus RTU via Waveshare RS485 gateway 192.0.2.37,
  HA hub "WSDEV0001". Register 0 = control flags (bit 0 = water pump).
  Currently written by HA automations - single-writer rule applies!
- Weather station FineOffset WH65B (dew point for cooling mode)
- Home Assistant: 192.0.2.230 (own Mosquitto; bridge to dedicated broker)

## Legacy system being replaced (why this project exists)
The previous vendor control system is still physically present and partly
alive. What matters for *this* hardware map:
- Its valve/sensor gateway was **destroyed in an overvoltage event**, which is
  what took the old control system down and started this rebuild.
- **Its return-line sensors were DS18B20 1-wire**, hanging off that gateway's
  1-wire bus, and all read null since it died. They are **not** reused - this
  project replaces them with PT1000 on the 750-463 terminals listed above.
  Do not expect to find 1-wire anywhere in heatctl.
- **Two of its room-controller wall units survive** and have been switched to
  WiFi. They are currently the only working room-air temperature source in the
  house, covering Gästebad and Wohnzimmer only (the others were lost in the
  same event). Mains-powered, so no battery/sleep constraints. They are an
  **interim** source; per-room Shelly H&T is the target (see ROADMAP.md).
- The old server also still exposes a read-only JSON API that Home Assistant
  polls today via hand-written `rest:` sensors in its `configuration.yaml`.
  Those are the entities heatctl's own MQTT discovery eventually replaces.

Addresses and device identifiers for the surviving legacy units are kept in
local notes outside this repository, not here.

## Cross-check: the old system's circuit->room map (RESOLVED - authoritative)
The old system ran this house for years, so its database is the best
evidence of how the manifold is actually wired. Its gateway-output -> room
mapping is:

| Controme output | Room |
|-----------------|------|
| 1 | Gästebad |
| 2, 8, 9, 10 | Wohnzimmer |
| 3 | Kinderzimmer Natalie |
| 4 | Kinderzimmer Naomi |
| 6 | Bad |
| 7 | Schlafzimmer Eltern |
| 15 | orphaned (no room) |
| - | Arbeitszimmer has **no** output (and is the only room on floor OG) |

**This table is authoritative and `config.yaml` has been corrected to match
it (2026-07-26).** An earlier version of `config.yaml`, written from
recollection, had circuits **7 and 10 transposed** (7 as Wohnzimmer, 10 as
Elternschlafzimmer). The Controme mapping is correct given the actual room
layout. Circuits 1, 2, 3, 4, 6 agreed already, as did 5 and 12 being unused.

Circuit 11 (Arbeitszimmer, upstairs) is a **recent addition**, made after the
Controme system was in service - which is exactly why Controme has no output
for that room. It is not a discrepancy.

Note this did not affect bring-up: the only two valves physically wired so
far are circuits 1 (Gästebad) and 2 (Wohnzimmer), both of which were already
mapped correctly.

Still open: which 750-559 analog channel drives which circuit. That is a
separate question from circuit->room and remains unverified for all channels
except 1 and 2 - resolve at the manifold during Milestone 0.

## Circuit 11 (Arbeitszimmer) is a FORCED-AIR CONVECTOR, not floor heating

Owner, 2026-07-28. Every other active circuit feeds the ground-floor slab;
circuit 11 feeds a fan convector in the upstairs Arbeitszimmer. It is the same
water loop and the same valve channel, so heatctl drives it identically — but
almost nothing else about it is the same, and several defaults are wrong for it.

**Consistent with the building data:** the EnEV floor-to-ground area is
136.40 m², the ground floor only. The upstairs was never part of the heated
slab, so this is not a change to the slab model — it is an *additional* emitter
the model did not have.

| | Slab circuits | Circuit 11 (convector) |
|---|---|---|
| Response time | hours | tens of seconds |
| Thermal mass | huge (69 % of the building) | negligible |
| Output per unit | ~25–35 W/m² of floor | high, and fan-speed dependent |
| Condensate | must never form | **forms by design** |

**What this invalidates**

1. **`rl_gating.settle_s: 300`** was sized for water to traverse a slab loop.
   A convector responds in tens of seconds. Circuit 11 is `fitted: false` today
   so the gate is inert, but this must be per-circuit before an actuator goes on.
2. **The return-temperature PID** driving circuit 11 is tuned for slab dynamics.
   Wrong plant, and it will be sluggish at best.
3. **Distribution normalisation** maps demand → opening identically for all
   circuits. A convector's output-vs-opening curve is nothing like a slab's,
   and it has a second control input (fan speed) heatctl cannot see.
4. **The 3-state room+slab model** (DESIGN.md §6.1) does not apply — Arbeitszimmer
   is essentially a single-state room.

**The condensation guard question — needs an answer before the next hot spell.**
A fan coil below dew point condenses; that is how it dehumidifies, and a proper
one has a condensate tray and drain. Two cases:

* **Drain fitted** → the guard is over-conservative for circuit 11. Worse, it is
  counter-productive: letting that coil run wet would *lower* the house dew
  point and buy headroom for every slab circuit. Consider exempting circuit 11
  from `vl_undertemp` — but only that circuit, and only with the drain confirmed.
* **No drain** → the guard is essential and the circuit needs at least the same
  limit, arguably a tighter one, since there is no slab mass to buffer a mistake.

**Do not exempt it on assumption.** Confirm the drain physically first.

**Rated capacity: 4.2 kW cooling / 4.3 kW heating** (owner, 2026-07-28).

### Capacity: the source is now the binding constraint, not the emitters

| | kW |
|---|---|
| Slab, 136.40 m² at 25–35 W/m² | 3.4 – 4.8 |
| Fan coil | 4.2 |
| **Total emitter** | **7.6 – 9.0** |
| Heat pump at ~11 °C supply | **5.7 ← binding** |

This reverses the earlier conclusion that we were emitter-limited. We are not;
we are source-limited. Supply headroom (D-024) still matters, but for a
different reason — to let the heat pump reach its own capacity, not to squeeze
more out of the floor.

**The coil is enormously oversized for its own room:** 4.2 kW over 31.20 m² is
**135 W/m²**, against 25–35 W/m² for the slab. Arbeitszimmer cannot absorb
anything like that. That surplus is the interesting part.

### The latent lever — spend coil capacity to buy slab capacity

A wet coil removes moisture. The condensation guard is `dew point + 2.0 K`, so
**every 1 K of house dew point removed is 1 K of extra supply headroom for all
ten slab circuits** — worth roughly 1 kW of extra slab capacity at a textbook
7 W/(m²K).

What it costs, at the EnEV-assumed n = 0.7 h⁻¹ (348 m³/h = 418 kg/h of outdoor
air):

| Hold the house below outdoor dew point by | Latent load |
|---|---|
| 1 K | 0.18 kW |
| 2 K | 0.36 kW |
| 3 K | 0.56 kW |

At a wet-coil SHR of 0.65–0.75, meeting the 2 K case needs the coil at only
**25–34 % duty**, which dumps **0.67–1.09 kW of sensible** into Arbeitszimmer.

**And that sensible byproduct is approximately Arbeitszimmer's own cooling
load** on a hot day (31 m², east and south glazing, upstairs). So the
dehumidification comes out very nearly free: net gain on the order of **+1 kW
of usable capacity**, delivered where it is actually needed — the slab serves
the whole ground floor.

### CORRECTION (2026-07-28, owner) — not available on the current hydraulics

The paragraphs above describe a real effect but skipped the hydraulics, and the
owner caught it. **The lever needs the coil to see water several K COLDER than
the slab can safely take** — roughly 8–11 °C to get the coil surface under a
12.5 °C dew point, against a slab limit of 14.5 °C. Today all eleven circuits
hang off one common supply header, so there is no way to give the coil cold
water without sending the same water to the slab.

And the fallback of "close the slab circuits while running cold" **does not
work either**: only circuits 1 and 2 have actuators. The other seven active
circuits are open pipe and cannot be closed at all, so cold water would flow
straight into the slab and condense inside it — invisibly, which is the failure
mode this whole guard exists to prevent.

**What it would actually require**, in order:

1. **A separate low-temperature branch for the coil** — heat pump feeding the
   coil directly, with the slab manifold behind a 3-way mixing valve raising its
   supply back above dew point. DESIGN.md §1.2 already specifies exactly this
   ("Feed: pump + 3-way mixing valve from buffer"); today's `H_DIRECT` wiring
   (§3.1) is the interim that lacks it. So this is not new plumbing to invent,
   it is plumbing already in the target design.
2. All twelve actuators fitted, so the slab can genuinely be isolated.
3. The condensate drain made permanent (currently temporary).

**A cost I had not accounted for.** With a single source, running cold enough
for the coil means the heat pump makes cold water for *everything*, mixed back
up for the slab. That costs EER across the whole output, not just the coil's
share — interpolating the datasheet, dropping leaving water 14 → 9 °C moves EER
from ~2.66 to ~2.25, i.e. **+18 % electrical input for the same cooling**.

So the honest conclusion is narrower than the section above implies: this is a
**peak-shaving move for capacity-constrained hours**, on hydraulics we do not
yet have — not a default operating mode. On an ordinary day it is a bad trade.
The +1 kW is real; so is the ~0.4 kW of extra compressor power to get it.

**The current guard blocks exactly this.** `vl_undertemp` forces the valve shut
below `dew point + 2`, which is precisely the operating point the lever
requires. Scoping the guard per circuit is therefore not a refinement; it is
what makes the strategy possible at all.

**Everything above is conditional on the condensate drain**, still unconfirmed.
It is now the highest-value open question on the plant. Other assumptions worth
naming: SHR 0.65–0.75 is generic and depends on entering water temperature;
7 W/(m²K) for floor cooling is a textbook figure we have never measured; and
n = 0.7 h⁻¹ is EnEV's assumption, not a blower-door result.

**Still not fungible between rooms** for *sensible* cooling — the coil does
nothing directly for Wohnzimmer. The latent path is the only route by which its
surplus reaches the rest of the house, which is why it is worth the trouble.

## Mixing valve: Afriso ARM 343, 3-point, 230 V, 120 s

Owner, 2026-07-29. The slab-circuit mixing valve actuator is **fitted**. It is
**3-point (three-wire)**: two 230 V inputs, one per direction, **120 s** for
full travel, and **no end switches** — no position feedback of any kind.

Sensor pockets (Tauchhülsen) for the stove and buffer are **already fitted**,
so that item is closed.

### What 3-point + no feedback forces on the design

**1. Position must be dead-reckoned from run time.** There is nothing to read.
heatctl would integrate energised time per direction to estimate position.

**2. That collides with the "no state survives a restart" invariant** — a
dead-reckoned position is exactly such state. **Resolution: re-reference, don't
remember.** On start, drive hard to one end for >120 s and call that zero. Same
principle as everywhere else in this codebase: restart == safe state, reached
by *action* rather than by trusting a stored value. Note the Alpha 5 actuators
solve the identical problem in firmware (D-022) — this one cannot, so heatctl
must do it.

**3. Relay wear is a real budget.** Mechanical relays last on the order of 10⁵
switching operations. A naive per-cycle controller at 1 Hz would consume that
in about a day. Needs a deadband, a minimum pulse (below which the actuator
does not move meaningfully anyway), and a minimum rest between pulses — the
same shape of reasoning as the heat pump's flash-write budget (D-013).

**4. Mutual interlock is mandatory.** Both directions energised at once is a
short across the actuator. Do it in hardware if the actuator does not already
interlock internally, and in software regardless.

**5. It is not a fast element.** 120 s full travel sits between the Alpha 5's
150 s and the fan coil's seconds. Any cascade must treat it as slow.

### Relay modules: 750-517 — adequate, with one caveat

Confirmed by the owner 2026-07-29: the relay modules are **2× 750-517**,
potential-free changeover contacts, AC 250 V rated. Driving the ARM 343 needs
two of the four channels and is well inside the contact rating — a 3-point
valve actuator of this class draws single-digit watts, so tens of mA at 230 V.

**The caveat is wear, not rating.** These are *mechanical* relays switching an
*inductive* AC load (a motor). Inductive switching arcs on break, which erodes
contacts considerably faster than the datasheet's resistive-load operation
count suggests. So the relay-wear budget already required for the ARM 343
driver — deadband, minimum pulse, minimum rest — is **more** binding than the
bare 10⁵-operation figure implies, and an **RC snubber across each contact** is
worth fitting. Cheap now, tedious once the panel is closed.

### Power injection: 750-602 and 750-612 both on hand

The owner holds both against the internal-bus / field-potential budget, which
covers the concern either way. Worth keeping the two problems distinct, because
they are different failure modes and only one is about module count:

* **Internal system bus (5 V, regenerated from 24 V)** — the coupler feeds a
  finite current down the internal bus. Adding modules eventually exceeds it,
  and the symptom is not a clean failure but modules dropping out or reading
  nonsense at the far end of the rail.
* **Field-side potential** — the 24 V supplying the I/O itself, and segmenting
  it so one group's fault does not take out another.

Before adding the 750-463 modules the buffer and stove sensors need, sum the
modules' internal-bus current draw against the 750-352's budget. WAGO's own
configurator does this arithmetic; do not eyeball it. **Which of the two
modules is the right answer depends on which limit you actually hit** — verify
each part's role in its datasheet rather than assuming from the number.

## Plant inventory as built — owner, 2026-07-29

Recorded here because none of it is discoverable from the running system.

| Item | Detail | Status |
|---|---|---|
| **Mixing valve** | **Afriso ARM 343**, 3-point, 230 V per direction, **120 s** full travel, **no end switches** | fitted — see the section above |
| **Circulation pumps ×2** | **Wilo Stratos PICO plus 25/0.5-6 (DACH)**, art. **4244375**, unit marking `24w11/074 0969 / I`. One on distribution, one on the heat exchanger — **identical parts** | fitted, **no control interface yet** |
| **Buffer tank** | **Solarbayer SLS-1000** (owner, 2026-07-29 — *not* the Buderus Logalux P990.6 M-C in the EnEV papers). Stratified, 5 pockets, and **provides hydraulic isolation**. **INSIDE the thermal envelope** — the EnEV papers say "außerhalb der therm. Hülle, Keller" and are **wrong** (owner, 2026-07-29) | **in place, not yet filled or connected** |
| **Electric element** | **8 kW in the tank** | **fitted, NO control path** — needs contactor/SSR + a DO channel + interlock |
| **Sensor pockets** | stove VL/RL and buffer stratification | **fitted** |
| **Mode-selection valve** | a motorised 3-way is on hand; final topology undecided | **open question — see below** |
| Floor actuators | Möhlenhoff Alpha 5 APV 42505-00 | 2 of 12 fitted |
| Heat pump | Blaupunkt BLP08P1V1MR32 (PW58321 controller) | fitted, on Modbus |
| Stove | Lohberger Varioline AC 105, external air duct fitted | fitted |

### The mixer is on the HEATING side only

**Important, and it corrects an earlier note in this file.** The current
hydraulic design routes only the **heating** circuit through the ARM 343; the
**cooling** path bypasses it. Consequences:

* The mixer does **not**, as plumbed, enable the "latent lever" (running the
  fan coil below dew point while the slab stays above it). That idea needs a
  low-temperature branch **in cooling**, which this topology does not provide.
  An earlier entry claiming the mixing circuit unblocks it was wrong.
* In cooling the slab therefore receives whatever the heat pump produces,
  which is exactly why the condensation guard has to act on the source
  temperature and why D-024's headroom matters so much.
* If the latent lever is ever wanted, it needs a *cooling-side* mixing or
  injection arrangement, not this one.

### Open: mode-selection valve topology

Requirement (docs/DESIGN.md §1.2): switch the heat pump between charging the
buffer and feeding the floor circuit directly, and do it for both heating and
cooling. The owner has a motorised 3-way valve and asks whether that plus a
non-return valve suffices, or whether 4-way, or two 4-way, is needed.

The consideration that decides it: a 3-way diverter switches the **flow** path
only. The **return** then has to be handled too, or the idle branch stays
hydraulically connected. A non-return valve blocks *forced* backflow but does
**not** block **thermosiphon**. The buffer is **inside** the envelope, so a
parasitic loop is not a loss to outdoors — in cooling it is worse: the plant
cools the buffer, the buffer re-warms off the house, and capacity is spent
moving heat in a circle. Two-valve or 4-way isolation
removes that failure mode by construction rather than by relying on
pressure relationships holding in every operating state.

Not decided here — it depends on pipe geometry and relative heights that are
not documented. Flagged so the reasoning is on record when it is decided.

## DHW is required *during cooling* — and heatctl would currently cancel it

Owner, 2026-07-29: the buffer will serve domestic hot water **even while the
plant is cooling**.

The heat pump supports this natively — `MODES` in `heatpump_map.py` already
lists **4 = `dhw+cooling`** (and 3 = `dhw+heating`). The hardware is not the
problem.

**heatctl is.** It only ever selects `heating` (1) or `cooling` (2), has no DHW
concept anywhere, and `_sync_pump_mode` in `main.py` treats any other value as
a disagreement to be corrected. So the moment the tank is connected and the
unit enters mode 4 to make hot water, heatctl will write 2 over it and **cancel
the DHW call**, every cycle. This is not a latent inefficiency; it is an active
fight between the controller and the appliance, and it will look like "the heat
pump won't heat water".

Fixing it is not a one-line change: the plant mode becomes a *pair* (space
mode × DHW demand) rather than a scalar, `Safety.apply` needs to know that a
DHW call legitimately raises water temperature far above any cooling limit, and
the water-setpoint loop must not fight the DHW setpoint. Design before coding.

**Standby loss caveat:** the 3.14 kWh/d figure quoted elsewhere in these
documents is the **Buderus** value from the EnEV papers. The SLS-1000's real
figure needs pulling from Solarbayer's datasheet, along with its actual volume,
heat-exchanger surfaces and pocket heights.

## Wilo Stratos PICO plus 25/0.5-6 (art. 4244375) — control and telemetry

Researched 2026-07-29 from Wilo's own EBA, Kurzanleitung and Modbus datapoint
list. Two identical pumps: distribution and heat exchanger.

**The bare pump has no machine interface at all** — only the mains plug. No
0–10 V, no PWM, no SSM contact, no bus. Everything needs a plug-in module in
the Wilo-Connectivity Interface slot.

### Flow IS readable — and is NOT a heat-meter substitute

Wilo's Modbus datapoint list exposes, as input registers (FC 04), for this pump
family: `flow` (m³/h), `powerInput` (W), `energyConsumption` (kWh), `pressure`,
`speed`, `operationTime`. So the temptation is obvious. Resist it for flow:

> *"Bei berechneten Werten sollte der aktuelle Wert **nicht für geschlossene
> externe Regelkreise verwendet werden, da die Genauigkeit und Verfügbarkeit
> nicht in allen Betriebspunkten gewährleistet werden kann.**"*

It is a sensorless estimate from the motor's electrical operating point against
a stored curve, and Wilo publishes **no tolerance band at all** — only that
disclaimer, plus the pump's own display prefixing `<` or `>` at operating points
where it knows the value is unreliable. **This does not replace the heat meter.**
It is useful as a soft signal: trend, "is there flow at all", cross-checking a
real sensor, bounding a Kalman estimate.

`powerInput` and `energyConsumption` are the pump's own *electrical*
measurements and carry no such disclaimer — considerably more trustworthy. Note
`energyConsumption` has **1 kWh resolution and rolls over at 65535**.

### Model-year gate — RESOLVED: these are 2024 units

Both Connect-module manuals require **"Modell ab 2022"**. The Kurzanleitung
shipped with these pumps is **Ed.01/2021-01**. Article 4244375 spans both
generations, so the article number does not settle it.

**Resolved 2026-07-29:** the unit marking `24w11/074 0969 / I` reads as **week
11 of 2024**, comfortably past the gate. The 2021-dated Kurzanleitung is simply
old stock documentation and not evidence of the pump's age. Worth one
confirmation when the first module is fitted — a `SW Version` entry should then
appear under `Externes Modul`.

### Module options (Wilo list prices, excl. VAT)

| Module | Art. | Price | Gives |
|---|---|---|---|
| Connect **Modbus RTU** | 4263625 / 4268524 *(see note)* | €234–251 | full telemetry + setpoint write (HR 1 `dutyPointRel`) |
| Connect **BMS** | 4257834 | €265 | 0–10 V in, digital in, changeover relay out — **no telemetry** |
| Smart Connect **BT** | 4239241 | €103 | Bluetooth app only |

*Note: Wilo's DE and AT catalogues present 4263625 and 4268524 inconsistently —
possibly the same product, possibly Modbus-only vs dual-protocol. Confirm.*

Modbus limitations for this pump: only **HR 1** is writable (setpoint). The
control mode (Δp-v/Δp-c/n-const) **cannot** be switched over the bus. Remote
on/off via HR 40 is **unconfirmed** — the pump is absent from that register's
support column.

**IF-Modules do not fit.** Those are for Stratos/MAXO/GIGA and use a different
slot. Common confusion, worth stating.

### Mains switching limits — and a correction about the 750-517

Wilo permits relay switching, within limits: **≤100 per 24 h, ≤20 per hour,
≥1 minute between transitions**, and:

> *"Der **Einschaltstrom der Pumpe ist < 5 A**. Wird die Pumpe über ein Relais
> geschaltet, ist sicherzustellen, dass das Relais in der Lage ist einen
> Einschaltstrom von mindestens 5 A zu schalten."*

**This corrects an earlier note in this file.** The 750-517 is fine for the
ARM 343 mixing valve (tens of mA) but is **NOT adequate for switching these
pumps** — it would need to make 5 A of inrush. Use a contactor or an
appropriately rated interposing relay, not the 750-517 directly.

Also mandated: max 10 A slow pre-fuse, and **never phase-angle control**.

Settings **survive a mains interruption**, which makes relay on/off safe from a
configuration standpoint.

### Bluetooth: reverse-engineered, but do not build on it

Third parties have mapped the BLE GATT protocol thoroughly. It is nonetheless
the wrong choice here: undocumented proprietary protocol, no open-source
implementation to inherit, firmware updates can break it silently, and **the
pump displays a fresh 4-digit PIN on its LCD for each connection** — fatal for
unattended operation unless a static-PIN mode works, which is unverified. The
raw card-edge serial tap carries **mains potential**. Both are the opposite of
this project's premise.

## PT1000 channel budget — 2× 750-463 needed

Counted 2026-07-29 with the owner. Currently 16 channels, 12 enabled, **4
spare**. Planned consumers:

| Purpose | Channels |
|---|---|
| Buffer stratification (5-node model, DESIGN §6.2) | 5 |
| Stove VL/RL | 2 |
| Mixed flow after the ARM 343 — needed to regulate mixer temperature at all | 1 |
| DHW station flow + return — for pump-speed regulation | 2 |
| **Total** | **10** |

Shortfall 6, so **two more 750-463** (4 channels each), leaving 2 channels of
headroom. **Append them at the END of the rail** — WAGO maps process data by
module order within each data type, so inserting analog inputs before the
existing four would shift all sixteen PT1000 registers and silently remap every
temperature sensor. `config.yaml` hardcodes `base_register: 12`.

Note the mixer and DHW sensors are not optional extras: **you cannot regulate a
mixing valve without measuring what comes out of it**, and the ARM 343 has no
position feedback, so the mixed-flow temperature is the *only* signal closing
that loop.

