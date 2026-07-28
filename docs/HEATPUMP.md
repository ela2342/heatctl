# Heat pump (PW58321) — Modbus register map, as it concerns heatctl

Authoritative source is the vendor manual, "MODBUS Protocol-(PW58321) Without
Cascade control, With PV Compatible", English edition 2022-10-24, Easylife
Series, 28 pages. It is **captured in full** — see the local-only
`docs/PW58321_MODBUS.local.md` for the complete verbatim text plus provenance.
That capture is deliberately not committed: this repository is public and the
manual is a vendor document. Register addresses and semantics are facts and are
summarised here; prose is not reproduced.

Read the local capture before acting on anything ambiguous below.

## The unit itself — Blaupunkt BLP08P1V1MR32

`PW58321` names the **controller / Modbus protocol**; the machine is a
**Blaupunkt BLP08P1V1MR32** inverter monoblock (owner, 2026-07-28, datasheet
`BLP08P1V1MR32.pdf`). Rebranded OEM hardware, so expect the register map to be
shared across several badges.

| | |
|---|---|
| Type | Monoblock air-to-water, inverter, R32 |
| Supply | **220–240 V / 50 Hz, single phase** |
| **Max. power input** | **3.6 kW** |
| **Max. current** | **16.5 A** |
| Compressor | Twin Rotary, inverter, ×1 |
| Fan | ×1, 2500 m³/h, 80 W |
| Water heat exchanger | Plate type, **Δp 30 kPa**, **G1"** |
| **Water flow, min / max** | **0.16 / 0.40 l/s** = **0.58 / 1.44 m³/h** |
| Noise | 53 dB |

### Rated duty points

| Condition | Capacity | COP/EER | Modulation | Input |
|---|---|---|---|---|
| Heating 30/35 | 8.4 kW | 4.26 | 1.6 – 8.4 kW | 370 – 2000 W |
| Heating 40/45 (or /55) | 7.8 kW | 2.99 | 1.5 – 7.8 kW | 490 – 2600 W |
| **Cooling A35 / W18** | **6.0 kW** | **2.99** | **1.1 – 6.0 kW** | 380 – 2000 W |
| **Cooling A35 / W7** | **5.5 kW** | **2.09** | **1.0 – 5.5 kW** | 500 – 2600 W |

Heating COP at W35: 1.52 (−25 °C air) · 2.99 (−7) · 3.40 (0) · 4.26 (7) ·
4.68 (21). At W45 subtract roughly 0.7; at W55 roughly 1.3.

### Three things this settles

**1. The flow range is specified, and it narrows our energy balances.** The unit
*requires* 0.16–0.40 l/s. With `dc_pump_speed` observed at 90–100 %, we are
near the top of that: **1.2–1.44 m³/h**. That was previously a guess spanning
0.8–1.5. See BACKLOG — it tightens the measured building capacity to
15,700–18,300 Wh/K, which lands squarely on the as-built figures and further
away from the EnEV certificate's.

**2. It explains the overnight cycling.** Minimum cooling output is
**1.0–1.1 kW**. The overnight delivery we back-computed was ~0.9 kW average —
*below the unit's minimum modulation*. So it could not throttle down to match
the load and cycled on/off instead, which is exactly what the logs show: mean
compressor frequency ~16 Hz made up of brief bursts to ~89 Hz. **Not a control
fault and not something heatctl can fix** — the load was simply below the
machine's floor. Worth remembering before anyone tries to tune the cycling out.

**3. The heat pump is not the constraint on a design cooling day.** At ~11 °C
supply it interpolates to roughly **5.7 kW** cooling. The floor can only
dissipate an estimated 3.4–4.8 kW before surface temperature or the dew point
binds. So capacity is limited by the *emitter*, not the source — which is why
supply headroom (D-024) matters more than anything we could do to the unit.

### Still unresolved: what `0x8025` actually measures

`hp_power_estimate` computes `compressor_current × 230 V`. The datasheet makes
230 V at least the right voltage class (the unit is single-phase 220–240), but
does not say whether `0x8025` is mains current, inverter output current, or DC
link current. The device separately reports `dc_bus_voltage` ≈ 374 V.

**There is now a free, decisive test.** Mains current maxes at **16.5 A**. Watch
the peak value of `0x8025` when the unit runs flat out — on the 2026-07-30 heat
event, say:

* peak approaching **16 A** → it is mains current, and `× 230 V` is roughly
  right (bar power factor)
* peak around **9–10 A** → inverter output current
* peak around **5–7 A** → DC link current, and the correct multiplier is
  `dc_bus_voltage`, making our present estimate low by ~60 %

Observed 6.5 A at 89 Hz is consistent with either mains or DC link, so the
question is open until we see it at full output. Do not derive COP until then.

## Transport
RS485, 9600 8N1, **unit address fixed at 1**, standard Modbus RTU. Reached over
the LAN through a Waveshare RS485→TCP gateway (address in the local site
notes). Note this is a **second, separate** Modbus device from the WAGO
coupler — the first time layer 1 would talk to two.

Two constraints from the manual that shape any implementation:

1. **Minimum access interval 200 ms.** Do not poll this at the valve loop's
   1 s cadence without thinking, and never faster.
2. **Every write wears flash.** The manual is explicit that the unit flashes
   its memory chip on receiving 06H/10H, and warns against too many writes. So
   **write only on a real transition, never per cycle.** The existing HA
   automation already does this deliberately; a heatctl replacement must keep
   the property, and it is the reason a naive "reconcile every second" loop
   would be actively damaging.

## The correction this document exists for

**`0x0000` bit 0 is the unit's POWER ON/OFF — it is NOT the water pump.**

`ROADMAP.md` asserted "register 0 = control flags (bit 0 = water pump)", the HA
automation `Heat pump: circulation pump request` was written to match, and the
`binary_sensor.heat_pump_pump_request` helper decodes that same bit. Three
sources, one unverified origin, and it was wrong.

What follows from that:
- The HA automation that "holds the pump request set" is holding the **whole
  unit powered on**.
- The condensation automation that "clears the pump-request bit" **powers the
  heat pump off**. That is what happened on 2026-07-26 when cooling was found
  completely dead — compressor and circulation both, which fits power-off far
  better than it fits a stopped pump.
- Toggling it is therefore a **unit power cycle**, not parking a pump.
  Anti-short-cycle limits matter more than they would for a pump, and the
  flash-wear rule above applies to every one of those transitions.
- The pump has its own controls (below), so heatctl does not have to power the
  unit off to influence circulation.

## Writable registers (RW)

| Addr | Name | Values / range | Relevance |
|---|---|---|---|
| `0x0000` | Control Flags 0 | bit0 **Power ON/OFF** (0 off / 1 on); bit1 A41 main expansion valve mode; bit2 manual frequency switch; bit4 **C01 constant-temperature pump selection** (1 non-stop / 0 stop); bit5 B01 aux expansion valve mode; bit6 A45 expansion-valve initial-opening mode; bits 3,7 reserved | bit0 is what HA writes today. bit4 is the actual pump knob. |
| `0x0001` | Control Flags 1 | bit0 with/without constant temperature; bit1 C02 pressure sensor; bit2 B62 cooling auxiliary circuit; bit3 B76 aux expansion valve control mode; bit4 powerful mode; bit5 silent mode; bit6 P22 heating target auto-adjust | not used |
| `0x0002` | Control Flags 2 | bit1 vacation mode; rest reserved | not used |
| `0x0003` | Number of systems (compressors) | 1 | informational |
| `0x0004` | **Mode** | **0 DHW / 1 HEATING / 2 COOLING / 3 DHW+HEATING / 4 DHW+COOLING** (default 1) | **This answers "how is heating/cooling selected": a plain register write.** Not a bit, and not unknown. |
| `0x008F` | P03 hot-water setpoint | 28–60 °C | DHW, future WP |
| `0x0090` | P04 chilling setpoint | 7–30 °C | the cooling setpoint the HA supervisory loop trims |
| `0x0091` | P05 heating setpoint | 15–50 °C | heating counterpart |
| `0x0101` | F2 water pump constant-temp operation mode | 0 intermittent / 1 always open | circulation behaviour |
| `0x0102` | F3 water pump thermostat start/stop cycle | 1–120 min (default 60) | circulation behaviour |
| `0x010B` | F10 DC pump inlet/outlet ΔT setting | 2–30 (default 5) | pump modulation |
| — | F9 DC pump regulation speed | 0–50 % (default 10) | pump modulation |

**Remember P04 and P05 target the RETURN water temperature**, not the leaving
water — that is why the cooling supervisory loop has to work by feedback on
measured supply rather than by clamping a setpoint. See
`docs/HA_INTEGRATION.md`.

## Read-only registers (R) that matter

| Addr | Name | Note |
|---|---|---|
| `0x8003` | Mode Selection (status) | bit0 hot water enabled; bit3 decoded in HA as `binary_sensor.cooling_enabled`. This is the unit **reporting** its mode — not a command. Do not confuse with `0x0004`. |
| `0x8006` | Output flags 3 | bit0 **Water pump** — the pump's actual output state; bit1 crankshaft heater |
| `0x8011` | Outdoor ambient temperature | accuracy 0.5 |
| `0x8012` | Leaving water temperature | accuracy 0.5 — the measurement the condensation loop feeds back on |

## Consequences for the open work

- **Mode switching is not blocked.** `0x0004` is writable and documented.
  `DemandController.can_command_source_mode` can become true once heatctl talks
  to this device — but note that flipping plant mode means writing flash, so it
  belongs behind the same long dwell the mode selection already has.
- **The demand design needs revisiting in light of bit 0 being power.**
  "Stop the source when flow is too low" was written meaning "park the pump".
  Doing it via `0x0000` bit 0 powers the unit down instead. Whether that is
  what we want, or whether bit 4 / F2 / F3 are the right levers, is an open
  design question — see ROADMAP.md.
- **The read-modify-write race is worse than documented.** The HA automation
  reads `0x0000` (polled at 10 s), ORs in `0x01`, and writes the whole register
  back — which blindly restores up to 10 s of staleness across bits 1–6,
  including the expansion-valve and pump-selection modes. Single-writer is not
  a tidiness rule here.

## Complete register inventory — verified on the device 2026-07-27

Probed read-only as sole master, with Home Assistant's modbus hub temporarily
disabled (two masters demonstrably interfere; see below).

| Region | Registers | Access | Contents |
|---|---|---|---|
| `0x0000`–`0x010C` | 269, **contiguous** | RW | control flags, mode, defrost, and the full A/B/C/D/F/P parameter set |
| `0x8000`–`0x802A` | 43, contiguous | R | **all** status and telemetry |
| beyond `0x010C` | — | — | reads succeed and return 0. **Readable does not mean documented** — do not infer a register exists because it answers. |

**Correction to an earlier version of this file.** It claimed three regions
separated by undocumented gaps at `0x002D`–`0x0038`, and warned against
spanning them. Both were wrong. That "gap" is an artifact of extracting the PDF
with `pypdf`, which dropped the address cells for a run of table rows; the
manual documents B20–B31 there (auxiliary expansion-valve openings, range
0–240). The device confirms it — those registers read `[75, 100, 100, 100, 100,
80, 80, 50, 50, 100, 100, 15]`, exactly the shape of a valve-opening table, and
a block read straight across the supposed gap succeeds. **Do not derive the
register map from the text extraction; the extraction is lossy.** Use the PDF,
and verify against the device.

### The 120-register limit is enforced by SILENT TRUNCATION
Asking for 121 or 125 registers does not raise an exception — the device
returns exactly 120 and says nothing. A client that assumes it got what it
asked for will index past the end or, worse, misalign every field after the
cut. **Always request ≤120 and always validate the returned length.**

### The status region is one read
`0x8000`–`0x802A`, 43 registers, one transaction. Verified live:

    0x8006 output flags 3 = 0x0001   -> bit0 water pump running
    0x8008 fault flags 2  = 0x0000   -> bit0 Er03 clear
    0x800E return water   = 203      -> 20.3 degC  (accuracy 0.1)
    0x8012 leaving water  = 40       -> 20.0 degC  (accuracy 0.5)

Note the **per-register scaling** — `0x800E` is 0.1 and `0x8012` is 0.5. The
manual annotates each one; there is no uniform factor, and getting it wrong
gives a plausible-looking answer. This block also carries six fault-flag
registers `0x8007`–`0x800D`, so every fault the unit can report arrives in the
same read as the measurements that explain it.

### The commanded mode is visible, and HA never showed it
`0x0004` read back **2 = COOLING**, matching the plant. Home Assistant models
no register in `0x0000`–`0x010C` except through the two climate entities'
target registers, so the *commanded* mode has been invisible until now —
`sensor.mode` is `0x8003`, the unit reporting status. Live setpoints read
P03 DHW 28, P04 chilling 19, P05 heating 25.

`0x0000` read back **65** = `0b01000001`: bit0 Power ON, bit6 A45 valve mode.
Confirms bit 0 is power, as the manual says.

## Access design rules (owner's direction, 2026-07-27)

| Constraint | Consequence |
|---|---|
| ≥200 ms between transactions | Cost is **per transaction**, so minimise round trips, not registers. Reading 57 registers costs what reading 5 costs. Read WIDE. |
| ≤120 registers per read | Binding for the RW region (269 registers). Enforced by silent truncation — see above. |
| Every 06H/10H write wears flash | Write only on a real transition. A reconcile-every-cycle loop damages hardware. |

**Read plan:**

| When | Read | Regs | Why |
|---|---|---|---|
| every poll | `0x8000`–`0x802A` | 43 | complete telemetry + all fault flags, one transaction |
| every poll | `0x0000`–`0x0038` | 57 | control flags, mode, defrost — same cost as reading the five we need |
| on demand | `0x008F`–`0x0091` | 3 | the setpoints, when about to write one |
| once at start | `0x0000`–`0x010C` in 3 reads | 120+120+29 | full parameter snapshot, for reference and for diffing against commissioning values |

Two transactions per poll is ~400 ms of bus time, so **the heat-pump client must
be its own slow task, decoupled from the 1 s valve loop** — 2–5 s is sane. Do
not fold these reads into `Controller.step`.

### Open problem: two masters on one bus
Home Assistant's modbus hub already polls this unit. If heatctl also polls it,
there are two independent masters behind one RS485 gateway, and neither can
honour the 200 ms interval on behalf of the other. The gateway serialises the
TCP side, but interleaved transactions can still violate the device's minimum
spacing.

So the single-writer rule (docs/DESIGN.md 2.1) understates the problem: for this
device, **reads contend too**. The migration has to pick one:
- heatctl becomes sole master, HA's modbus hub for this unit is removed, and
  heatctl republishes the telemetry over MQTT — the clean answer, and the one
  that matches the layering: HA is a consumer, not a driver; or
- HA stays sole master and heatctl asks it for actions — rejected, layer 1 must
  not depend on HA; or
- both poll and we accept out-of-spec spacing — not acceptable for a device
  whose response to a flow fault is to stop the compressor.

Worth measuring, as part of that work, whether HA's present polling already
violates the 200 ms rule.
