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

### Modbus watchdog registers (read live 2026-07-26)
| Addr | Meaning (per WAGO docs - LABELS UNVERIFIED) | Value found |
|------|--------------------------------------------|-------------|
| 0x1000 | watchdog time, units of 100 ms | 100 -> **10 s** |
| 0x1001 | coding mask: which function codes retrigger it | **0xFFFF = all** |
| 0x1002 | watchdog trigger (write to retrigger) | 0xFFFF |
| 0x1003 | minimum trigger time | 0 |
| 0x1004 | status / stop | 0xFFFF |
| 0x1005..0x1007 | stop / restart / config | 0 |
| 0x1028 | fieldbus-failure behaviour (guess) | 4 |

### WBM Watchdogs page, read 2026-07-26 - CURRENT STATE: DISABLED
`State Modbus Watchdog: Disabled`. **There is currently no hardware failsafe on
this coupler at all.** The register values above are only the stored config, not
an armed watchdog - do not mistake a populated 0x1000 for protection.

The page (Navigation -> Watchdog) offers:

| Field | Value found | Note |
|---|---|---|
| Connection Timeout Value (100 ms) | 600 -> 60 s | Separate *TCP connection* watchdog, not the Modbus one. heatctl polls every 1 s so it never trips; and modbus_direct reconnects if it ever does. |
| State Modbus Watchdog | **Disabled** | Read-only display |
| Watchdog Type | **Standard** / Alternative | See below - Standard is the wrong choice for us |
| Watchdog Timeout Value (100 ms) | 100 -> 10 s | Fine against a 1 s control loop: ~10 kicks per window |
| Trigger Mask F1-F16 / F17-F32 | 0xFFFF / 0xFFFF | Every function code retriggers it |

**Use "Alternative", not "Standard".** UNVERIFIED against the manual, but the
distinction appears to be: Standard is retriggered by any Modbus function
matching the trigger mask, Alternative only by an explicit write to the trigger
register (0x1002). Standard with mask 0xFFFF is why the watchdog would be
useless to us - heatctl reads every second, so reads alone would keep it alive
even if the write path were completely broken, which is a failure mode heatctl
can actually have (write_valve raising every cycle while read_state succeeds).
Alternative gives a true heartbeat instead: heatctl kicks 0x1002 only *after* a
successful valve write, so a broken write path lets the watchdog fire. That is
better than narrowing the mask, because it expresses intent rather than
approximating it.

**Enabling requires a coupler reset.** The page states Modbus Watchdog changes
"take effect after the next software or hardware reset", so arming it means a
brief outage of all I/O - schedule it, do not do it mid-heating-season blind.

### Output behaviour on timeout is NOT configurable - RESOLVED 2026-07-26
Checked every WBM page that could carry it: **Watchdog** (no such field),
**Features** (only "Autoreset on system error", "BOOTP request before static
IP", "Non-adaptive Kbus speed active" - all unchecked), **IO config** (a module
listing only). There is no fieldbus-failure / substitute-value option anywhere.

So **full-scale-on-timeout cannot be configured on this coupler.** An earlier
version of this file asserted the fallback "must be configured to drive outputs
to FULL SCALE"; that is not achievable and the claim is withdrawn. The documented
behaviour is that outputs are cleared to 0 on timeout - i.e. with NC actuators,
valves CLOSE. Still worth verifying empirically rather than trusting the manual.

**This does not actually conflict with the fail-open policy, because the two
cover different failures:**
- Software fail-open (`safety.failsafe_valve_pct: 100`) applies when heatctl is
  ALIVE but has lost knowledge - sensor fault, stale data. It can still reason,
  and an open circuit fed by a heat pump holding a sane return setpoint is safe.
- The watchdog applies when heatctl is DEAD. There, closing is the conservative
  choice: the one genuinely fast hazard is condensation, and `safety.py` already
  fails closed on `vl_undertemp` for exactly that reason. Leaving valves stuck
  wherever a dying controller last left them - possibly 100 % open with
  below-dew-point water - is strictly worse than closing them.

**Crucially, a watchdog trip does not stop circulation today**: only circuits 1
and 2 have actuators, the other eight are open pipe, so flow continues through
them regardless. That is what makes fail-closed acceptable here.

**REVISIT WHEN THE REMAINING ACTUATORS ARRIVE.** Once every circuit can close, a
watchdog trip would shut all flow and leave the heat pump deadheading against a
closed manifold - a real hazard (flow error / pressure). At that point either the
heat-demand interlock must stop the pump when the watchdog fires, or a bypass /
differential-pressure valve is needed. Do not carry today's "acceptable" verdict
forward past that hardware change.

Module count cross-check from IO config: 10 on terminalbus, 10 in I/O
configuration - consistent, and matches the terminal layout above
(16DI + 750-652 + 4x750-463 + 2x750-559 + 2x750-517 = 10).

Still to determine, and it decides whether hardware fail-open is even possible:
what the coupler does to the analog outputs on timeout. WAGO couplers typically
offer "set outputs to zero" or "retain last value", not an arbitrary substitute.
If a substitute value is not available then full-scale-on-timeout cannot be
configured, "retain last value" is the closest approximation, and the fail-open
policy remains a software-only property. Verify empirically by arming the
watchdog, stopping writes, and reading the output image at 0x0200 + word.

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
