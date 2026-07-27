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
| 11-12| 2x750-5xx| 4 relays (2DO each)                 | coils 0-3 |
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

Measurement needed per valve TYPE - not per valve. The physics is a property
of the Alpha 5, not of circuit 7, and a per-circuit sweep costs ~10 min per
step (stroke plus hydraulic transport), so twelve circuits is ~20 h of
disrupted control. Two or three done properly is enough.
Tracked in `BACKLOG.md`; prerequisite for the distribution design (D-017).

**`open_threshold_pct` - ramp up, find where RL first responds.** Sound: at
zero flow the sensor sits at manifold ambient, so the first real flow moves it
sharply toward VL. Large, unambiguous signal.

**`full_open_pct` - do NOT infer this from "RL stops changing" (D-021).**
That is what an earlier version of this file said and it is systematically
wrong. RL is not a flow measurement, it is a heat-exchange measurement:

    RL ~= T_slab + (VL - T_slab) * exp(-NTU),   NTU = UA / (m_dot * cp)

As flow rises, NTU falls, exp(-NTU) -> 1, and RL asymptotes to VL. So
dRL/d(opening) -> 0 at high openings for purely hydraulic reasons - the valve
is still moving, RL has simply stopped reporting it. The procedure would find
the knee at perhaps 60 % and record that as full open, which **throws away
flow** - precisely what docs/DESIGN.md 4.4 exists to maximise. Prefer, in
order: the vendor datasheet's control range; passive identification from
logged data (docs/DESIGN.md 7.3); a sweep watching the HEAT PUMP's
leaving/return spread and DC pump speed, which keep responding after circuit
RL has saturated.

**`settling_time_s` - full 0->100 and 100->0 stroke; take the slower.** Size it
from the RL response, not a datasheet, because it must include hydraulic
transport through the loop, not just the actuator.

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
