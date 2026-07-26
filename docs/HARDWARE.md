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

## Sensor assignment (750-463, channel n = input register 11+n)
| Ch | Sensor    | Location                                   |
|----|-----------|--------------------------------------------|
| 1  | rl_hk01   | return, circuit 1 - Gästebad               |
| 2  | rl_hk02   | return, circuit 2 - Wohnzimmer             |
| 3  | rl_hk03   | return, circuit 3 - Kinderzimmer Natalie   |
| 4  | rl_hk04   | return, circuit 4 - Kinderzimmer Naomi     |
| 5  | rl_hk05   | circuit 5 - Bad Handtuchhalter (reserve, not installed) |
| 6  | rl_hk06   | return, circuit 6 - Badezimmer             |
| 7-9| rl_hk07-09| return, circuits 7-9 - Wohnzimmer          |
| 10 | rl_hk10   | return, circuit 10 - Elternschlafzimmer    |
| 11 | rl_hk11   | return, circuit 11 - Arbeitszimmer         |
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

## Other devices in the system
- Heat pump: Modbus RTU via Waveshare RS485 gateway 192.0.2.37,
  HA hub "WSDEV0001". Register 0 = control flags (bit 0 = water pump).
  Currently written by HA automations - single-writer rule applies!
- Weather station FineOffset WH65B (dew point for cooling mode)
- Home Assistant: 192.0.2.230 (own Mosquitto; bridge to dedicated broker)
