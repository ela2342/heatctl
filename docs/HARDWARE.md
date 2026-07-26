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
| 7-8 | 2x750-559 | 8x 0-10V (0..32767)                 | holding reg. 12-19 |
| 9-10| 2x750-517 | 4 relays                            | coils 0-3 |
|     | 750-600   | bus end terminal                    | -      |

### Register spaces - read-back gotcha (verified on hardware 2026-07-26)
The coupler overlays the input and output process images in the same low
address range, so **you cannot read back what you wrote at the address you
wrote it to**:
- FC4 (read input registers) at 12..27 -> PT1000 values. As documented above.
- FC6/FC16 (write) at 12..19 -> the 750-559 analog outputs. Correct, works.
- FC3 (read holding registers) at 12..19 -> **returns the INPUT image, i.e.
  temperatures again, NOT your output values.** Reading 12/13 right after
  writing them returns ~174/175 (17.4/17.5 degC), which looks like a failed
  write but is not.
- The output process image is mirrored for reading at **0x0200 + word
  offset**: output word 12 reads back at 524 (0x020C), word 19 at 531.
  Verified by writing 16383 to HR12/13 and finding it at 524/525.
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
| 0x1003 | R/W | Watchdog **trigger** (toggle register) | - | 0 |
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
750-559 ch 1-8: Alpha 5 proportional actuators, 0-10V.
Valve->circuit mapping: TODO verify (8 outputs, 10 active circuits)!

**Only circuits 1 and 2 have an actuator fitted.** Every other circuit is
open pipe, so water circulates through them whenever the pump runs, with no
way to throttle them. Two consequences: the manifold cannot be balanced until
the remaining actuators arrive, and a "closed" state only exists for 1 and 2.

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

TODO measure per valve type (one-off, cheap, and needed before WP-C):
1. `open_threshold_pct` - ramp the output up in small steps, dwelling long
   enough at each, and find where RL first responds (loop starts flowing).
2. `full_open_pct` - where further increase stops changing RL.
3. `settling_time_s` - full 0->100 and 100->0 stroke time; take the slower.
   Size it from the RL response, not from a datasheet.
Record the measured values here, and see docs/DESIGN.md section 4 for how
they feed the controller.

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
  **interim** source; per-room Shelly H&T is the target (see PLAN.md).
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
