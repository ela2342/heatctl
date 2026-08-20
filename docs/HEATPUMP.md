# Heat pump (PW58321) — Modbus register map, as it concerns heatctl

Register addresses, ranges and defaults are facts about the device and are
recorded here in full. Verified against the unit itself wherever a register is
actually used, and against working code for the thirteen whose meaning is
independently known.

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

## `outdoor_ambient` (0x8011) is NOT air temperature in daytime

**Measured 2026-07-28.** The unit's own outdoor sensor reported a peak of
**36.5 °C** at 17:00 CEST. Two independent Fine Offset weather-station sensors
agreed with each other on **25.1 °C** in the same hour. The heat pump reads up
to **+11 K high** in the afternoon.

Cause is the usual one: the sensor sits on the outdoor unit, so it picks up
solar gain on the casing and its own discharge air recirculating. Overnight the
two sources agree within ~0.7 K (heat pump slightly low), so the error is
daytime and insolation-driven, not a calibration offset.

**Consequences**

* Do **not** use it for weather compensation, degree-days, COP-vs-ambient, or
  anything else that needs real air temperature. Use
  `sensor.fineoffset_wh65b_210_t` / `wh24_210_t`.
* It is still the right signal for **the machine's own** operating point —
  defrost, capacity derating, and the manufacturer's COP tables are all
  referenced to what the unit itself experiences. Keep publishing it, and keep
  it clearly named as the unit's sensor rather than "outdoor temperature".
* Energy balances built on it will be wrong by up to 11 K in daytime.
  The overnight balance in `docs/BUILDING.local.md` is unaffected (night-time
  agreement is ~0.7 K on a 7.1 K delta, inside its stated uncertainty).

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


## Complete register map

**256 addresses over `0x0000`–`0x010C`.** Superseding the short table below,
which listed 17 rows and read as though it were the whole map - which is how
`0x008D` (the compressor restart dead zone, and the constraint that explains
most of this plant's behaviour) stayed invisible for a day.

⚠️ **Transcribed from a paginated original, so ~9 % of rows carry layout
artefacts.** Validated against 13 registers whose meaning is independently
known from working code: 12 matched, and the one that did not (`0x00C5`) is
corrected here by hand. Rows marked **?** are truncated or carry text belonging
to their neighbour, because the source splits a row across a page boundary and
the address then lands on the far side of the break. **Verify a `?` row before
writing to it.** Unmarked rows matched the anchor pattern.

| Addr | Description | |
|---|---|---|
| `0x0000` | Control Flags 1 Bit0:Power ON/OFF， 0 -OFF/ 1-ON Bit1： A41 Main Expansion Valve Model Selection ， 0-Auto/1- Manual Bit2:Manual frequency switches Bit3: Reserved Bit4: C01Constant Temperature pump selection ， 1-Non-stop/0- Stop Bit5: B01Auxiliary Expansion Valve Model Selection, 0- Auto /1- Manual Bit6: A45 Expansion Valve Initial Opening Adjustment mode ， 0-Fixed / 1-Adjustable Bit7: Reserved RW |  |
| `0x0001` | Control Flags 1 Bit0: With or Without Constant Temperature Bit1： C02 Pressure Sensor Enable/disable,1-enable,/0-disable Bit2: B62 Cooling Auxiliary Circuit enable/disable,0-enable/ 1-disable. Bit3: B76Auxiliary Expansion Valve control mode,0-EVI Superheat/1- discharge gas superheat Bit 4:Powerful mode Selection Bit5:Silent Mode Selection Bit6:P22 Heating Target Temperature Auto-Adjustment 0~1（ 0-Disable/1- enable ） Bit7:Reserved RW |  |
| `0x0002` | Control Flags 2 Reserved Bit0: Reserved Bit1:Vacation mode Bit2: Reserved Bit3: Reserved Bit4: Reserved Bit5: Reserved Bit6: Reserved Bit7: Reserved RW |  |
| `0x0003` | Number of System(Compressor) 1 RW |  |
| `0x0004` | Mode 0:DHW 1:HEATING Default: 1 Heating 2:COOLING 3:DHW+HEATING 4:DHW+ COOLING RW |  |
| `0x0005` | P09 Defrost frequency 30-120HZ RW |  |
| `0x0006` | P10 Defrost cycle 20MIN~90MIN RW |  |
| `0x0007` | P12 Defrost time 5MIN~20MIN RW |  |
| `0x0008` | A01 Main Expansion Valve Adjustment Cycle 20S~90S RW |  |
| `0x0009` | A14 Initial Opening of The Main Expansion valve in Heating Mode 00 0~240 Multiply by 2 for actual use RW |  |
| `0x000A` | A15 Initial Opening of The Main Expansion valve in Heating Mode 01 0~240 RW |  |
| `0x000B` | A16 Initial Opening of The Main Expansion valve in Heating Mode 02 0~240 RW |  |
| `0x000C` | A17 Initial Opening of The Main Expansion valve in Heating Mode 03 0~240 RW |  |
| `0x000D` | A18 Initial Opening of The Main Expansion valve in Heating Mode 04 0~240 RW |  |
| `0x000E` | A19 Initial Opening of The Main Expansion valve in Heating Mode 05 0~240 RW |  |
| `0x000F` | A20 Initial Opening of The Main Expansion valve in Heating Mode 06 0~240 RW |  |
| `0x0010` | A21 Initial Opening of The Main Expansion valve in Heating Mode 07 0~240 RW |  |
| `0x0011` | A22 Initial Opening of The Main Expansion valve in Cooling Mode 00 0~240 Multiply by 2 for actual use RW A23 Initial Opening of The Main 0~240 | **?** |
| `0x0012` | Expansion valve in Cooling Mode 01 RW |  |
| `0x0013` | A24 Initial Opening of The Main Expansion valve in Cooling Mode 02 0~240 RW |  |
| `0x0014` | A25 Initial Opening of The Main Expansion valve in Cooling Mode 03 0~240 RW |  |
| `0x0015` | A26 Initial Opening of The Main Expansion valve in Hot Water Mode 00 0~240 Multiply by 2 for actual use RW |  |
| `0x0016` | A27 Initial Opening of The Main Expansion valve in Hot Water Mode 01 0~240 RW |  |
| `0x0017` | A28 Initial Opening of The Main Expansion valve in Hot Water Mode 02 0~240 RW |  |
| `0x0018` | A29 Initial Opening of The Main Expansion valve in Hot Water Mode 03 0~240 RW |  |
| `0x0019` | A30 Main expansion valve Automatic Adjustment Lower Limit in Heating mode 00 0~240 Multiply by 2 for actual use RW |  |
| `0x001A` | A31 Main expansion valve Automatic Adjustment Lower Limit in Heating mode 01 0~240 RW |  |
| `0x001B` | A32 Main expansion valve Automatic Adjustment Lower Limit in Heating mode 02 0~240 RW |  |
| `0x001C` | A33 Main expansion valve Automatic Adjustment Lower Limit in Heating mode 03 0~240 RW |  |
| `0x001D` | A34 Main expansion valve Automatic Adjustment Lower Limit in Heating mode 04 0~240 RW |  |
| `0x001E` | A35 Main expansion valve Automatic Adjustment Lower Limit in Heating 0~240 mode 05 RW |  |
| `0x001F` | A36 Main expansion valve Automatic Adjustment Lower Limit in Heating mode 06 0~240 RW |  |
| `0x0020` | A37 Main expansion valve Automatic Adjustment Lower Limit in Heating mode 07 0~240 RW |  |
| `0x0021` | A39 Main Expansion valve defrosting opening 10~225 Multiply by 2 for actual use RW |  |
| `0x0022` | A40 Minimum opening of Main Expansion valve in Hot water Mode 25~75 Multiply by 2 for actual use RW |  |
| `0x0023` | A42 Manual step of Main Expansion valve 10~225 Multiply by 2 for actual use RW |  |
| `0x0024` | A43 Superheat Scale Factor of Main Expansion valve 1~20 RW |  |
| `0x0025` | A44 Superheat Differential coefficient of Main Expansion valve 1~180 RW |  |
| `0x0026` | B02 Manual Steps of Auxiliary Expansion valve 10~225 Multiply by 2 for actual use RW |  |
| `0x0027` | B04 Exhaust Scale Factor of Auxiliary Expansion valve 1~20 RW |  |
| `0x0028` | B05 Exhaust Differential coefficient of Auxiliary expansion valve 0~180 RW |  |
| `0x0029` | B06 Superheat scale factor of Auxiliary Expansion valve 1~20 RW |  |
| `0x002A` | B07 Superheat Differential coefficient of Auxiliary expansion valve 0~180 RW |  |
| `0x002B` | B08 Adjustment cycle of Auxiliary expansion valve 10~20 RW B19 Initial opening of Auxiliary 0~240 Multiply by 2 for actual use | **?** |
| `0x002C` | expansion valve in Heating mode 00 RW B20 Initial opening of Auxiliary expansion valve in Heating mode 01 0~240 RW B21 Initial opening of Auxiliary expansion valve in Heating mode 02 0~240 RW B22 Initial opening of Auxiliary expansion valve in Heating mode 03 0~240 RW B23 Initial opening of Auxiliary expansion valve in Heating mode 04 0~240 RW B24 Initial opening of Auxiliary expansion valve in Heating mode 05 0~240 RW B25 Initial opening of Auxiliary expansion valve in Heating mode 06 0~240 RW B26 Initial opening of Auxiliary expansion valve in Heating mode 07 0~240 RW B27 Initial opening of Auxiliary expansion valve in Hot water Mode 00 0~240 Multiply by 2 for actual use RW B28 Initial opening of Auxiliary expansion valve in Hot water Mode 01 0~240 RW B29 Initial opening of Auxiliary expansion valve in Hot water Mode 02 0~240 RW B30 Initial opening of Auxiliary expansion valve in Hot water Mode 03 0~240 RW B31 Auxiliary expansion valve Automatic Adjustment Lower Limit in Heating mode 00 0~240 Multiply by 2 for actual use RW | **?** |
| `0x0039` | B32 Auxiliary expansion valve Automatic Adjustment Lower Limit in Heating mode 01 0~240 RW B33 Auxiliary expansion valve 0~240 | **?** |
| `0x003A` | Automatic Adjustment Lower Limit in Heating mode 02 RW |  |
| `0x003B` | B34 Auxiliary expansion valve Automatic Adjustment Lower Limit in Heating mode 03 0~240 RW |  |
| `0x003C` | B35 Auxiliary expansion valve Automatic Adjustment Lower Limit in Heating mode 04 0~240 RW |  |
| `0x003D` | B36 Auxiliary expansion valve Automatic Adjustment Lower Limit in Heating mode 05 0~240 RW |  |
| `0x003E` | B37 Auxiliary expansion valve Automatic Adjustment Lower Limit in Heating mode 06 0~240 RW |  |
| `0x003F` | B38 Auxiliary expansion valve Automatic Adjustment Lower Limit in Heating mode 07 0~240 RW |  |
| `0x0040` | B39 Auxiliary Expansion Valve Defrosting Opening 0~240 Multiply by 2 for actual use RW |  |
| `0x0041` | B40 Auxiliary Expansion Valve Cooling Opening 0~240 Multiply by 2 for actual use RW |  |
| `0x0042` | C03 High-pressure protection value(Reserved) 25.0-50.0bar RW |  |
| `0x0043` | C04 High pressure recovery value(Reserved) 25.0-50.0bar RW |  |
| `0x0044` | C05 Low pressure protection value 0-20.0bar RW |  |
| `0x0045` | C06 Low pressure recovery value 0-20.0bar RW D03 Heating Mode Wind Speed 1 0~100 | **?** |
| `0x0046` | RW | **?** |
| `0x0047` | D04 Heating Mode Wind Speed 2 0~100 RW |  |
| `0x0048` | D05 Heating Mode Wind Speed 3 0~100 RW |  |
| `0x0049` | D06 Heating Mode Wind Speed 4 0~100 RW |  |
| `0x004A` | D07 Heating Mode Wind Speed 5 0~100 RW |  |
| `0x004B` | D08 Heating Mode Wind Speed 6 0~100 RW |  |
| `0x004C` | Reserved RW |  |
| `0x004D` | Reserved RW |  |
| `0x004E` | D11 Heating mode Wind Speed 1 corresponding Coil Temperature -30~30 RW |  |
| `0x004F` | D12 Heating mode Wind Speed 2 corresponding Coil Temperature -30~30 RW |  |
| `0x0050` | D13 Heating mode Wind Speed 3 corresponding Coil Temperature -30~30 RW |  |
| `0x0051` | D14 Heating mode Wind Speed 4 corresponding Coil Temperature -30~30 RW |  |
| `0x0052` | D15 Heating mode Wind Speed 5 corresponding Coil Temperature -30~30 RW |  |
| `0x0053` | D16 Heating mode Wind Speed 6 corresponding Coil Temperature -30~30 RW |  |
| `0x0054` | D17 Reserved -30~30 RW D18Reserved -30~30 | **?** |
| `0x0055` | RW | **?** |
| `0x0056` | D19 DC FAN Speed regulation cycle 10~180 Second RW |  |
| `0x0057` | D20 Fan Adjustment speed per cycle 0~100 转 RW |  |
| `0x0058` | D21 Hot water Mode Wind Speed 1 0~1000 RW |  |
| `0x0059` | D22 Hot water Mode Wind Speed 2 0~1000 RW |  |
| `0x005A` | D23 Hot water Mode Wind Speed 3 0~1000 RW |  |
| `0x005B` | D24 Hot water Mode Wind Speed 4 0~1000 RW |  |
| `0x005C` | D25 Hot water Mode Wind speed 1 corresponding coil Temperature -30~30 RW |  |
| `0x005D` | D26 Hot water Mode Wind speed 2 corresponding coil Temperature -30~30 RW |  |
| `0x005E` | D27 Hot water Mode Wind speed 3 corresponding coil Temperature -30~30 RW |  |
| `0x005F` | D28 Hot water Mode Wind speed 4 corresponding coil Temperature -30~30 RW |  |
| `0x0060` | D29 Cooling Mode DC Fan Max Speed 1 0~1000 RW |  |
| `0x0061` | D30 Cooling Mode DC Fan Max Speed 2 0~1000 RW |  |
| `0x0062` | D31 Cooling Mode DC Fan Max Speed 3 0~1000 RW |  |
| `0x0063` | D32 Cooling Mode DC Fan Max Speed 4 0~1000 RW B41 Auxiliary Expansion Valve 0~240 Multiply by 2 for actual use | **?** |
| `0x0064` | Automatic Adjustment Lower Limit in Hot Water Mode 00 RW |  |
| `0x0065` | B42 Auxiliary Expansion Valve Automatic Adjustment Lower Limit in Hot Water Mode 01 0~240 RW |  |
| `0x0066` | B43 Auxiliary Expansion Valve Automatic Adjustment Lower Limit in Hot Water Mode 02 0~240 RW |  |
| `0x0067` | B44 Auxiliary Expansion Valve Automatic Adjustment Lower Limit in Hot Water Mode 03 0~240 RW |  |
| `0x0068` | B45 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 00 50~125℃ RW |  |
| `0x0069` | B46 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 01 50~125℃ RW |  |
| `0x006A` | B47 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 02 50~125℃ RW |  |
| `0x006B` | B48 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 03 50~125℃ RW |  |
| `0x006C` | B49 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 04 50~125℃ RW |  |
| `0x006D` | B50 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 05 50~125℃ RW |  |
| `0x006E` | B51 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 06 50~125℃ RW |  |
| `0x006F` | B52 Exhaust Temperature of Enthalpy Valve Opening In Heating mode 07 50~125℃ RW |  |
| `0x0070` | B53 Exhaust Temperature of Enthalpy Valve Opening In Hot Water Mode 00 50~125℃ RW B54 Exhaust Temperature of Enthalpy 50~125℃ | **?** |
| `0x0071` | Valve Opening In Hot Water Mode 01 RW |  |
| `0x0072` | B55 Exhaust Temperature of Enthalpy Valve Opening In Hot Water Mode 02 50~125℃ RW |  |
| `0x0073` | B56 Exhaust Temperature of Enthalpy Valve Opening In Hot Water Mode 03 50~125℃ RW |  |
| `0x0074` | B57 Exhaust Temperature of Enthalpy Valve Opening In Cooling Mode 00 50~125℃ RW |  |
| `0x0075` | B58 Exhaust Temperature of Enthalpy Valve Opening In Cooling Mode 01 50~125℃ RW |  |
| `0x0076` | B59 Exhaust Temperature of Enthalpy Valve Opening In Cooling Mode 02 50~125℃ RW |  |
| `0x0077` | B60 Exhaust Temperature of Enthalpy Valve Opening In Cooling Mode 03 50~125℃ RW |  |
| `0x0078` | B61 Enthalpy valve Opening delay time 0~180S RW |  |
| `0x0079` | B63 Return difference of Exhaust to Close Enthalpy Valve 0~30 RW |  |
| `0x007A` | B64 Exhaust Temperature difference of Auxiliary Expansion valve in Heating Mode 00 0~125℃ RW |  |
| `0x007B` | B65 Exhaust Temperature difference of Auxiliary Expansion valve in Heating Mode 01 0~125℃ RW |  |
| `0x007C` | B66 Exhaust Temperature difference of Auxiliary Expansion valve in Heating Mode 02 0~125℃ RW |  |
| `0x007D` | B67 Exhaust Temperature difference of Auxiliary Expansion valve in Heating Mode 03 0~125℃ RW B68 Exhaust Temperature difference of 0~125℃ | **?** |
| `0x007E` | Auxiliary Expansion valve in Heating Mode 04 RW |  |
| `0x007F` | B69 Exhaust Temperature difference of Auxiliary Expansion valve in Heating Mode 05 0~125℃ RW |  |
| `0x0080` | B70 Exhaust Temperature difference of Auxiliary Expansion valve in Heating Mode 06 0~125℃ RW |  |
| `0x0081` | B71 Exhaust Temperature difference of Auxiliary Expansion valve in Heating Mode 07 0~125℃ RW |  |
| `0x0082` | B72 Exhaust Temperature difference of Auxiliary Expansion valve in Hot Water Mode 00 0~125℃ RW |  |
| `0x0083` | B73 Exhaust Temperature difference of Auxiliary Expansion valve in Hot Water Mode 01 0~125℃ RW |  |
| `0x0084` | B74 Exhaust Temperature difference of Auxiliary Expansion valve in Hot Water Mode 02 0~125℃ RW |  |
| `0x0085` | B75 Exhaust Temperature difference of Auxiliary Expansion valve in Hot Water Mode 03 0~125℃ RW |  |
| `0x0086` | B77 Target Superheat Correction value -30~30℃ RW |  |
| `0x0087` | B78 Target Superheat Correction value -30~30℃ RW |  |
| `0x0088` | B79Target Superheat Correction value 3 -30~30℃ RW B80 Target Superheat Correction value -30~30℃ | **?** |
| `0x0089` | 4 RW | **?** |
| `0x008A` | B81 Target Superheat Correction value -30~30℃ RW |  |
| `0x008B` | B82 Target Superheat Correction value -30~30℃ RW |  |
| `0x008C` | B83 Target Superheat Correction value -30~30℃ RW |  |
| `0x008D` | P01 Re-start Temperature difference of Heating/Cooing Mode 2℃~18℃ RW |  |
| `0x008E` | P02Re-start Temperature difference of Hot water Mode 2℃~18℃ RW |  |
| `0x008F` | P03Set Temperature of Hot Water Mode 28℃~60℃ RW |  |
| `0x0090` | P04 Set Temperature of Chilling Mode 7℃~30℃ RW |  |
| `0x0091` | P05 Set Temperature of Heating Mode 15℃~50℃ RW |  |
| `0x0092` | P08 Water Temperature Compensation -5℃~15℃ RW |  |
| `0x0093` | P11 Defrost Enter Coil Temperature -15℃~-1℃ RW |  |
| `0x0094` | P13 Defrost Exit Coil Temperature 1℃~40℃ RW |  |
| `0x0095` | P14 Defrost Ambient and Coil Temperature Difference 1 0℃~15℃ RW |  |
| `0x0096` | P15 Defrost Ambient and Coil Temperature Difference 2 0℃~15℃ RW |  |
| `0x0097` | P16 Defrost Ambient Temperature 0℃~20℃ RW A02 Target Superheat of Main -5℃~10℃ | **?** |
| `0x0098` | Expansion Valve in Heating Mode 1 RW |  |
| `0x0099` | A03 Target Superheat of Main Expansion Valve in Heating Mode 2 -5℃~10℃ RW |  |
| `0x009A` | A04 Target Superheat of Main Expansion Valve in Heating Mode 3 -5℃~10℃ RW |  |
| `0x009B` | A05 Target Superheat of Main Expansion Valve in Heating Mode 4 -5℃~10℃ RW |  |
| `0x009C` | A06 Target Superheat of Main Expansion Valve in Heating Mode 5 -5℃~10℃ RW |  |
| `0x009D` | A07 Target Superheat of Main Expansion Valve in Heating Mode 6 -5℃~10℃ RW |  |
| `0x009E` | A08 Target Superheat of Main Expansion Valve in Heating Mode 7 -5℃~10℃ RW |  |
| `0x009F` | A09 Target Superheat of Main Expansion Valve in Heating Mode 8 -5℃~10℃ RW |  |
| `0x00A0` | A10 Target Superheat of Main Expansion Valve in Cooling Mode 1 -5℃~10℃ RW |  |
| `0x00A1` | A11 Target Superheat of Main Expansion Valve in Cooling Mode 2 -5℃~10℃ RW |  |
| `0x00A2` | A12 Target Superheat of Main Expansion Valve in Cooling Mode 3 -5℃~10℃ RW |  |
| `0x00A3` | A13 Target Superheat of Main Expansion Valve in Cooling Mode 4 -5℃~10℃ RW |  |
| `0x00A4` | A38 Exhaust Temperature of Main Expansion Valve 70℃~125℃ RW |  |
| `0x00A5` | B03 Enthalpy Solenoid Valve Opening Ambient Temperature 11℃~45℃ RW |  |
| `0x00A6` | B09 Target Exhaust Temperature of Auxiliary Expansion Valve 70~120 RW B10 Exhaust Temperature of Close 40~70 | **?** |
| `0x00A7` | Auxiliary Expansion Valve RW |  |
| `0x00A8` | B11 Target Superheat of Auxiliary Expansion valve in Heating mode 1 -10~10 RW |  |
| `0x00A9` | B12 Target Superheat of Auxiliary Expansion valve in Heating mode 2 -10~10 RW |  |
| `0x00AA` | B13 Target Superheat of Auxiliary Expansion valve in Heating mode 3 -10~10 RW |  |
| `0x00AB` | B14 Target Superheat of Auxiliary Expansion valve in Heating mode 4 -10~10 RW |  |
| `0x00AC` | B15 Target Superheat of Auxiliary Expansion valve in Heating mode 5 -10~10 RW |  |
| `0x00AD` | B16 Target Superheat of Auxiliary Expansion valve in Heating mode 6 -10~10 RW |  |
| `0x00AE` | B17 Target Superheat of Auxiliary Expansion valve in Heating mode 7 -10~10 RW |  |
| `0x00AF` | B18 Target Superheat of Auxiliary Expansion valve in Heating mode 8 -10~10 RW |  |
| `0x00B0` | D01 AC Wind speed switching Environment -10~50℃ RW |  |
| `0x00B1` | D02 AC Wind speed switching Environment -10~50℃ RW |  |
| `0x00B2` | R16 Exhaust Setting TP0 50~125℃ RW |  |
| `0x00B3` | R17 Exhaust Setting TP1 50~125℃ RW |  |
| `0x00B4` | R18 Exhaust Setting TP2 50~125℃ RW |  |
| `0x00B5` | R19 Exhaust Setting TP3 50~125℃ RW R20 Exhaust Setting TP4 50~125℃ | **?** |
| `0x00B6` | RW | **?** |
| `0x00B7` | Manual frequency 15~120 RW |  |
| `0x00B8` | R00 Compressor Operating Frequency 30~120Hz 30 Hz RW |  |
| `0x00B9` | R01 Compressor Operating Frequency 30~120Hz 35 Hz RW |  |
| `0x00BA` | R02 Compressor Operating Frequency 30~120Hz 40 Hz RW |  |
| `0x00BB` | R03 Compressor Operating Frequency 30~120Hz 45 Hz RW |  |
| `0x00BC` | R04 Compressor Operating Frequency 30~120Hz 55 Hz RW |  |
| `0x00BD` | R05 Compressor Operating Frequency 30~120Hz 60 Hz RW |  |
| `0x00BE` | R06 Compressor Operating Frequency 30~120Hz 65 Hz RW |  |
| `0x00BF` | R07 Compressor Operating Frequency 30~120Hz 70 Hz RW |  |
| `0x00C0` | R08 Compressor Operating Frequency 30~120Hz 75 Hz RW |  |
| `0x00C1` | R09 Compressor Operating Frequency 30~120Hz 80 Hz RW |  |
| `0x00C2` | R10 Compressor Operating Frequency 30~120Hz 85 Hz RW |  |
| `0x00C3` | R11 Compressor Operating Frequency 30~120Hz 90 Hz RW |  |
| `0x00C4` | R12 Lower Limit of Constant Temperature operating frequency 30~120Hz 30 Hz RW R13 Upper Limit of Constant 30~120Hz 80 Hz | **?** |
| `0x00C5` | R13 Upper Limit of Constant Temperature operating frequency 30~120Hz 80 Hz |  |
| `0x00C6` | reserved RW |  |
| `0x00C7` | reserved RW |  |
| `0x00C8` | R21 Lower Limit of Frequency adjustment 01 0~125Hz 125 RW |  |
| `0x00C9` | R22 Lower Limit of Frequency Adjustment 02 0~125Hz 125 RW |  |
| `0x00CA` | R23 Lower Limit of Frequency Adjustment 03 0~125Hz 125 RW |  |
| `0x00CB` | R24 Lower Limit of Frequency Adjustment 04 0~125Hz 125 RW |  |
| `0x00CC` | R25 Upper Limit of Frequency Adjustment 01 0~125Hz 125 RW |  |
| `0x00CD` | R26 Upper Limit of Frequency Adjustment 02 0~125Hz 125 RW |  |
| `0x00CE` | R27 Upper Limit of Frequency Adjustment 03 0~125Hz 125 RW |  |
| `0x00CF` | R28 Upper Limit of Frequency Adjustment 04 0~125Hz 125 RW |  |
| `0x00D0` | Timer Allowable marker Bit Bit0： 1st Timer Allowed, 0-Not Allowed/1-Allowed Bit1： 2nd Timer Allowed Bit2： 3rd Timer Allowed Bit3： 4th Timer Allowed Bit4： 5th Timer Allowed RW |  |
| `0x00D1` | 1St Timer ON(Hour) 00~23 RW 1st Timer ON(Minutes) 00~59 | **?** |
| `0x00D2` | RW | **?** |
| `0x00D3` | 1St Timer OFF(Hour) 00~23 RW |  |
| `0x00D4` | 1St Timer OFF(Minutes) 00~59 RW |  |
| `0x00D5` | 2nd Timer ON(Hour) 00~23 RW |  |
| `0x00D6` | 2nd Timer ON(Minutes) 00~59 RW |  |
| `0x00D7` | 2nd Timer OFF(Hour) 00~23 RW |  |
| `0x00D8` | 2nd Timer OFF(Minutes) 00~59 RW |  |
| `0x00D9` | 3rd Timer ON(Hour) 00~23 RW |  |
| `0x00DA` | 3rd Timer ON(Minutes) 00~59 RW |  |
| `0x00DB` | 3rd Timer OFF (HOUR) 00~23 RW |  |
| `0x00DC` | 3rd Timer OFF(Minutes) 00~59 RW |  |
| `0x00DD` | 4th Timer ON(Hour) 00~23 RW |  |
| `0x00DE` | 4th Timer ON(Minute ） 00~59 RW |  |
| `0x00DF` | 4th Timer OFF(Hour) 00~23 RW |  |
| `0x00E0` | 4th Timer OFF(Minute) 00~59 RW 5th Timer ON(Hour) 00~23 | **?** |
| `0x00E1` | RW | **?** |
| `0x00E2` | 5th Timer ON(Minute) 00~59 RW |  |
| `0x00E3` | 5th Timer OFF(Hour) 00~23 RW |  |
| `0x00E4` | 5th Timer OFF(Minutes) 00~59 RW |  |
| `0x00E5` | Reserved RW |  |
| `0x00E6` | P17 High Temperature disinfection cycle days 0~30Days,No disinfection function when set to 0 RW |  |
| `0x00E7` | P18 High Temperature Disinfection start time 0~23 RW |  |
| `0x00E8` | P19 High Temperature Disinfection Sustaining Time 0~90min RW |  |
| `0x00E9` | P20 Set Temperature of High Temperature Disinfection 0~90℃ RW |  |
| `0x00EA` | P21 High Temperature disinfection Heat pump Set Temperature 40~60℃ RW |  |
| `0x00EB` | P23 Compensation Temperature of Heating Mode (Ambient Temperature) 0-40 RW |  |
| `0x00EC` | P24 Target Temperature Compensation factor 1~30（ 1 corresponds to the actual 0.1） RW |  |
| `0x00ED` | P26 Ambient Temperature of Start Electric Heater -20-20℃ 0 RW |  |
| `0x00EE` | R29 Frequency increase of Powerful Heating Mode -30~30Hz 5 RW |  |
| `0x00EF` | R30 Max Frequency of Silent Heating Mode 30~120Hz 70 RW R31 Frequency increase of Powerful -30~30Hz 5 | **?** |
| `0x00F0` | Cooling Mode RW |  |
| `0x00F1` | R32 Max Frequency of Silent Cooling Mode 30~120Hz 70 RW |  |
| `0x00F2` | Set Temperature of Vacation mode RW |  |
| `0x00F3` | D08 Max Wind Speed of Silent Mode in Heating or Hot Water mode 0~1000 60 RW |  |
| `0x00F4` | D09 Max Wind Speed of Silent Mode in Cooling Mode 0~1000 60 RW |  |
| `0x00F5` | Mute Timer Enable Flag RW |  |
| `0x00F6` | 1st Mute Timer ON(Hour) 00~23 RW |  |
| `0x00F7` | 1st Mute Timer ON(Minutes) 00~59 RW |  |
| `0x00F8` | 1st Mute Timer OFF (Hour) 00~23 RW |  |
| `0x00F9` | 1st Mute Timer OFF(Minutes) 00~59 RW |  |
| `0x00FA` | 2nd Mute Timer ON(Hour) 00~23 RW |  |
| `0x00FB` | 2nd Mute Timer ON(Minutes) 00~59 RW |  |
| `0x00FC` | 2nd Mute Timer OFF(Hour) 00~23 RW |  |
| `0x00FD` | 2nd Mute Timer OFF(Minutes) 00~59 RW |  |
| `0x00FE` | P27 Delay start time of Water Tank Electric Heater 0-60 RW 0x00FF R14 Frequency Compensation of Hot -50~20Hz Water Mode RW | **?** |
| `0x0100` | F1 Model Selection 1:Heating only 2:Heating + Cooling 3:heating+ DHW 4:Heating /cooling+DHW RW |  |
| `0x0101` | F2 Water pump constant Temp. Operation mode 0:Intermittent Opening 1:Always open 2:Constant Temp. Stop Working RW |  |
| `0x0102` | F3 Water Pump Thermostat Start/stop Cycle 1-120min 60 RW |  |
| `0x0103` | D1 DC FAN 1 Selection 0: Disable 1: enable RW |  |
| `0x0104` | D2 DC Fan 2 Selection 0:Disable 1:Enable RW |  |
| `0x0105` | F4 DC Pump mode 0:Disable 1:Auto 2:Manual RW |  |
| `0x0106` | F5 DC Pump Regulation cycle 10-120S RW |  |
| `0x0107` | F6 DC Pump Manual Speed 10-100% 50 RW |  |
| `0x0108` | F7 DC Pump Max Speed 10-100% 100 RW |  |
| `0x0109` | F8 DC Pump Min Speed 10-100% 40 RW |  |
| `0x010A` | F9 DC Pump Regulation speed 0-50% 10 RW |  |
| `0x010B` | F10 DC water pump inlet and outlet temperature difference setting 2-30℃ 5 RW |  |
| `0x010C` | F11 DC pump model (minimum communication frequency) 0:1000HZ 1:100HZ 0 R 0x8000 Reserved R 0x8001 Reserved R 0x8002 Machine status check Bit0： Bit1： Reserved Bit2： Bit3： Bit4： Reserved Bit5： Reserved Bit6： Reserved Bit7： Reserved R 0x8003 Mode Selection Bit0:Hot water disable/enable,0-disable/1- enable Bit1: Reserved Bit2:Heating disable/enable;0-disable/1- enable Bit3:Cooling disable/enable;0-disable/1- enable Bit4:DC Fan 1 Enable/disable;0-disable/1- enable Bit5： DC Fan 2 Disable/enable;0-disable/1- enable Bit6:Reserved Bit7:Defrost R 0x8004 Output flags1 Bit0： compressor Bit1： reserved Bit2： reserved Bit3： reserved Bit4： reserved Bit5： FAN motor Bit6： 4 way valve Bit7： reserved R 0x8005 Output flags 2 Bit0： Chassis Electric Heater Bit1： reserved Bit2： Reserved Bit3： Reserved Bit4： Reserved Bit5： Auxillary E-heater Bit6： 3 way valve Bit7： Water Tank E-Heater R 0x8006 Output flags 3 Bit0： Water pump Bit1： Crankshaft electric heater Bit2： reserved Bit3： reserved Bit4： reserved Bit5： reserved Bit6： reserved Bit7： reserved R 0x8007 Fault flags 1 Bit0: Er 14 Water Tank Temp. Sensor Failure Bit1:Er 21 Ambient Temp. Sensor failure Bit2: Er 16 External Coil Temp. Sensor failure Bit3： Reserved Bit4: Er 27 Outlet Water Temp. Sensor failure Bit 5: Er 05 High pressure failure Bit 6:Er 06 Low pressure failure Bit7： Reserved R 0x8008 Fault flags 2 Bit0： Er 03 Water Flow Failure Bit1： Reserved Bit2： Er 32 Leaving Water Temperature Overheat Protection in Heating Mode Bit3： reserved Bit4： reserved Bit5： reserved Bit6： reserved Bit7： reserved R 0x8009 Fault flags 3 Bit0： reserved Bit1： reserved Bit2： reserved Bit3： reserved Bit4： reserved Bit5： reserved Bit6： Er 18 Exhaust Temperature Failure Bit7： Reserved R 0x800A Fault flags 4 Bit0： Er 15 Inlet Water Temperature Failure Bit1： Er 12 Exhaust Temperature Overload protection Bit2： Reserved Bit3： Reserved Bit4： Reserved Bit5： Er 23 Leaving Water Temperature Over-cold Protection in Cooling Mode Er 29 Suction Gas Temperature Failure Bit7： Reserved R 0x800B Fault flags 5 Bit0： Er 69 Low Pressure Protection Bit1： Reserved Bit2： Er 33 Exceed Temperature protection of Coil Temperature Bit3： Er 42 Cooling Coil Temperature Sensor Failure Bit4： Reserved Bit5： Reserved Bit6： Reserved Bit7： Er 67 Low Pressure Sensor Failure R 0x800C Fault flags 6 Bit0： Reserved Bit1： Reserved Bit2： Reserved Bit3： Reserved Bit4： Secondary Anti- freeze Bit5： Primary Anti-freeze Bit6： Reserved Bit7： Reserved R 0x800D Fault flags Bit0： Reserved Bit1： Reserved Bit2： Reserved Bit3： Reserved Bit4： Reserved Bit5： Reserved Bit6： Er 64 DC Fan 1 Failure Bit7： Er 65 Compressor Over-current Protection R 0x800E 01 Return Water Temperature Accuracy 0.1 R 0x800F 10 Water Tank Temp. Accuracy 0.5 R 0x8010 Reserved R 0x8011 03 Outdoor Ambient Temperature Accuracy 0.5 R 0x8012 02 Leaving Water Temperature Accuracy 0.5 R 0x8013 Economizer Inlet Temperature(Reserved) Accuracy 0.5 R 0x8014 Economizer Outlet Temperature(Reserved) Accuracy 0.5 R 0x8015 05 Suction Gas Temperature Accuracy 0.5 R 0x8016 06 External Coil Temperature Accuracy 0.5 R 0x8017 Reserved R 0x8018 Reserved R 0x8019 Reserved R 0x801A 09 Cooling Coil Temperature Accuracy 0.5 R 0x801B 04 Exhaust Gas Temperature Accuracy 0.5 R 0x801C 11 Main Expansion Valve Opening R 0x801D 12 Auxiliary Expansion Valve Opening R 0x801E 16 Actual Frequency of Compressor R 0x801F Inverter Fault Low 8 bits are 0xff when the corresponding fault is reportedR 0x8020 Inverter Fault High 8 Bits R 0x8021 15 DC Bus Voltage R 0x8022 Reserved R 0x8023 Reserved R 0x8024 Target frequency R 0x8025 13 Compressor Current R 0x8026 19 Wind Speed of DC Fan 1 R 0x8027 Reserved R 0x8028 21 Pressure Conversion temperature of Low-Pressure Switch R 0x8029 Reserved R 0x802A 23 Actual speed of DC Pump |  |

### The registers that matter for the operating window

| Addr | What | Range / default | Why it matters |
|---|---|---|---|
| `0x008D` | P01 restart temperature difference, heating/cooling | **2–18 °C**, at 2 | The dead zone. **Already at its minimum** - the unit will not start until return water is 2 K past setpoint, so it always lets the house drift before running. |
| `0x00C5` | R13 upper limit of constant-temperature operating frequency | 30–120 Hz, **80** | ⚠️ **TESTED 2026-07-30: IT DOES NOT BIND.** The datasheet claim — that it caps the compressor while leaving the unit's own modulation and protections intact — was measured and refuted. Written 80 → 50, read back 50.0, the write stuck and persisted; the compressor went on running 79–80 Hz. Re-observed unchanged 2026-08-08 (register 50, compressor 79–85 Hz). **`R32` (`silent_max_freq_cooling_hz`) is the register that binds**, and only in silent mode — which is why `capacity.py` drives that one and checks silent mode explicitly. The write working is what makes this misleading: the register accepts and holds a value, it simply has no effect. See BACKLOG "R13 TEST RESULT: it does not bind. Clean negative." |
| `0x00C4` | R12 lower limit of the same | 30–120 Hz, 30 | The other end; raising it fights minimum modulation. |
| `0x00B7` | Manual frequency | 15–120 | With `0x0000` bit 2. Fixes frequency outright and takes the unit's modulation logic out of the loop - more control, less protection. |
| `0x0092` | P08 water temperature compensation | −5…15 °C | Outdoor-dependent setpoint correction. Believed disabled; confirm before adding control on top. |
| `0x010B` | F10 DC pump inlet/outlet ΔT | 2–30, set to **2** | Holds the pump at full flow instead of throttling to build spread. |

## Writable registers (RW) - the short list kept for context

⚠️ **THIS TABLE IS A SUBSET — 17 rows.** The complete map is above. This short
list is kept only because other documents reference it; it reads as though it
were the whole map, which is how `0x008D` P01 — the compressor restart dead
zone, and the constraint that explains most of this plant's behaviour — stayed
invisible for a day. **Use the complete map above.**


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

## Er03, water flow — it backs off, and eventually it sticks

Owner, 2026-08-20: *"Er03 is self clearing if the cause goes away immediately.
It backs off and eventually gets stuck in Er03. We should never depend on Er03
being self clearing."*

So the self-clears observed are not a property to design around, they are the
early part of a retry sequence with a lengthening backoff. **Every trip makes
the next one likelier to latch for good**, and a latched Er03 has needed a
physical reset. Observed self-clears — three on 2026-08-10 at ~4.5 min each,
one on 2026-08-20 at 4.5 min — say only that the cause vanished quickly, not
that the unit tolerates the event.

**What this changes about how we treat it:**

- Never write "it will probably clear" into a plan or a comment. The unit is
  spending a budget nobody can read.
- The unit shuts its own **water pump** down with the fault, so restored flow
  cannot clear it — there is no flow to detect. Waiting is not a recovery
  mechanism, it is waiting.
- It is the reason D-035 removed valve-closing as a condensation defence:
  starving the unit is not a cheap action that occasionally annoys, it is
  drawing down a reserve toward an on-site reset.
- Any procedure that stops the controller must stop the **source** first — see
  the cutover procedure in `docs/PFC200.md`.
