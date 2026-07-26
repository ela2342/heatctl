# Home Assistant side of the system

**Why this file exists:** a meaningful amount of control logic currently lives in
Home Assistant automations and helpers, which are **not** in this repository and
therefore not versioned, reviewed or backed up with it. That is a real risk for a
project whose whole premise is 30-year maintainability. This file is the
inventory so the HA side can be rebuilt if it is ever lost, and so nobody
searching the repo for "what controls the pump" concludes wrongly that nothing
does. Addresses follow the repo convention: placeholders, real values in local
notes.

Migration direction: everything here is either interim plumbing or logic that
`heatctl` should eventually own (PLAN.md Milestone 1 / WP-B). Nothing here is
meant to be permanent.

## Entities heatctl publishes (MQTT discovery, automatic)
12 temperature sensors, 8 valve-position sensors, and one `climate.heatctl_<room>`
per room **that has a room temperature source**. Rooms without one get no
thermostat on purpose: their room setpoint is inert because they run the
return-temperature fallback. Mode on every thermostat is the single global plant
mode, not per-room. These need no HA-side configuration at all.

## Helpers (created via the HA config-flow API, not YAML)
| Helper | Type | Purpose |
|---|---|---|
| `sensor.system_dew_point_reference` | template | **Highest INDOOR dew point**, Magnus formula over each room's temperature+humidity, falling back to the outdoor station only when no indoor pair is available. Indoor is what governs slab condensation; outdoor is often higher and would forbid cooling. Yields `unknown` only when every source is gone, which is what the safety shutdown keys on. |
| `binary_sensor.heat_pump_pump_request` | template | Bit 0 of the heat pump's control-flag register, so automations can compare against the actual request bit instead of the pump's output state - avoids rewriting the same register value every tick and wearing the controller's flash. |
| `sensor.installed_valve_demand` | min_max (max) | Max of the two valve channels that actually have an actuator. Currently **unused** - kept for when the remaining actuators arrive. |

## Automations
| Automation | What it does | Notes |
|---|---|---|
| `Climate: Prevent Condensation (With Modbus Fallback)` | Clears the heat pump's pump-request bit when dew-point knowledge is lost; restores it, raising the setpoint **first**, when it returns. | Rewritten to be **state-based** and re-evaluated on HA start and every 5 min. The original was edge-triggered and latched cooling off indefinitely after a sensor dropout - a real incident on 2026-07-26. |
| `Climate: Chilling Setpoint Supervisory Loop` | Trims the heat pump's chilling setpoint to keep **supply** water a margin above the dew point; hard-jumps it on an actual breach. | Gated on the pump having run 1 min so it reads circulating rather than stagnant water. Remember the setpoint targets **return** water, so supply is never directly commanded - the clamp is a heuristic, the feedback is the mechanism. |
| `Heat pump: circulation pump request` | Holds the pump-request bit set, as a state-based reconciler that writes only on a real transition. | Replaces two legacy edge-triggered automations that keyed off a signal derived from the retired floor gateway and so sat near zero, killing circulation minutes after every recovery. Valve-demand gating deliberately **not** used yet. |
| `heatctl: bridge legacy wall units to MQTT` | Republishes the two surviving wall units' temperature and dial setpoint onto MQTT for heatctl. | INTERIM. The dial is authoritative for those rooms, so HA cannot override it. Arbeitszimmer bypasses this entirely - its sensor already publishes a bare numeric value on its own topic. |
| `Steuerung der Wasserpumpe ... (einschalten)` / `(ausschalten)` | **Turned OFF**, superseded by the reconciler above. | Left in place rather than deleted so the change is trivially reversible. |

## Hand-edited YAML
`/config/configuration.yaml` holds ~40 `rest:` sensors polling the legacy
server's JSON API, plus the heat pump's whole modbus register map and its
flag-decoding template sensors. Two setpoint sensors were added there on
2026-07-26 (`controme_sp_wohnzimmer`, `controme_sp_gaestebad`) with a timestamped
backup alongside and a passing `ha core check`. Prefer the config-flow API over
editing this file; when it is unavoidable, back up and validate first.

## Known risks
1. **Not versioned.** Everything above lives only in the running HA instance.
2. **Layer-1 independence is compromised for two rooms.** Gästebad and Wohnzimmer
   get their room temperature through HA, so heatctl's room control for them
   depends on HA being up - exactly what layer 1 is meant not to need. Safe
   degradation: a room temperature older than 5 min is treated as absent and the
   return-temperature loop takes over.
3. **Single-writer boundary.** The heat pump's registers are written by these HA
   automations, not by heatctl. Until WP-B migrates that, heatctl must not write
   them.

## Pending cleanup: most of the legacy REST entities are dead
Of the ~40 `rest:` sensors in `/config/configuration.yaml`, the majority read
`null`/0 permanently because they are fed by the retired floor gateway. They are
also now *superseded*, because heatctl publishes the real thing from the WAGO.
Leaving them makes the entity list actively misleading - two sets of
similarly-named sensors, only one of them true.

**Safe to remove (dead and superseded):**
- `sensor.rl_1` … `sensor.rl_12` - DS18B20 returns via the dead gateway, all
  `null`. Superseded by `sensor.heatctl_return_circuit_*`.
- `sensor.ventil_1..4, 6..10` - valve openings from the dead gateway's `outs`
  API, all 0. Superseded by `sensor.heatctl_valve_*`.
- `sensor.average_valve_opening` - min_max over those dead valve sensors.
  Superseded by `sensor.installed_valve_demand`. **Check first that nothing
  still references it**: it was the trigger for the two legacy pump automations,
  which are turned off but not deleted.

**MUST KEEP - removing these breaks live control:**
- `sensor.raumtemperatur_gastebad` / `_wohnzimmer` - the room temperatures the
  bridge publishes to heatctl.
- `sensor.luftfeuchte_gastebad` / `_wohnzimmer` - inputs to
  `sensor.system_dew_point_reference`, i.e. the condensation limit.
- `sensor.solltemperatur_gastebad` / `_wohnzimmer` - the wall-unit dial
  setpoints.

**Leave dormant rather than delete:** the Elternschlafzimmer
`raumtemperatur`/`luftfeuchte` pair. Currently `unavailable` because that wall
unit is offline, and correctly skipped by the dew-point helper - but it comes
back for free if the unit is ever revived.

Note the whole `rest:` block dies with the legacy server anyway, so this cleanup
is a step toward switching that machine off, not just tidying. Do it with a
backup and `ha core check`, as before; YAML platform entities disappear on
reload without needing registry surgery.
