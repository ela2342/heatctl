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
`heatctl` should eventually own (ROADMAP.md Milestone 1 / WP-B). Nothing here is
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

## Legacy entity cleanup - DONE 2026-07-27

Three separate paths carried the same legacy Controme data into HA. Two of
them were dead or duplicated, and the resulting entity list was actively
misleading - similarly named sensors, only some of them true.

**Removed from `/config/configuration.yaml`** (backup taken, `ha core check`
passed, registry orphans purged afterwards):
- `sensor.rl_1` … `rl_12` - DS18B20 returns via the retired floor gateway, all
  `null`. Superseded by `sensor.heatctl_return_circuit_*`.
- The entire `/get/json/v1/1/outs` REST block - `sensor.ventil_1..11`, all 0
  from the same dead gateway. Superseded by `sensor.heatctl_valve_*`.
- `sensor.average_valve_opening` (min_max over those). Superseded by
  `sensor.installed_valve_demand`.

**KEPT, because live control depends on them** - the eight remaining REST
sensors, all reading real values:
- `sensor.raumtemperatur_gastebad` / `_wohnzimmer` - room temperature into the
  bridge, and thence heatctl's room PID.
- `sensor.luftfeuchte_gastebad` / `_wohnzimmer` - inputs to
  `sensor.system_dew_point_reference`, i.e. the condensation limit. heatctl
  now STOPS COOLING without it, so these are load-bearing.
- `sensor.solltemperatur_gastebad` / `_wohnzimmer` - the wall dials, which
  define the room target.
- The Elternschlafzimmer `raumtemperatur`/`luftfeuchte` pair, left dormant:
  `unavailable` today, correctly skipped by the dew-point helper, free to
  recover if that unit is ever revived.

### The third path: the Controme HomeKit bridge
Easy to miss, because it is an integration rather than YAML. The Mini Server
exposes a HomeKit bridge and `homekit_controller` imports 29 entities from it -
a `climate`, a `current_temperature` sensor, a display-units `select` and an
identify `button` per room, for seven rooms.

**Four of those rooms report a hardcoded 10 °C** (Bad, both Kinderzimmer,
Elternschlafzimmer). That is Controme's placeholder for "no sensor", not a
measurement - and HA presents it as a perfectly ordinary live value, which is
worse than `unavailable` would be. Those four rooms' `climate` and
`current_temperature` entities are now **disabled** (registry disable, not
deletion - reversible from the UI).

The remaining three (Gästebad, Wohnzimmer, Arbeitszimmer) report real values
but merely duplicate what heatctl publishes itself. Left enabled for now as a
cross-check; they go away with the Mini Server.

**Deliberately NOT deleted: the HomeKit config entry itself.** Re-adding it
needs a HomeKit pairing code, so removing it is not trivially reversible.
Disable, do not delete, until the Mini Server is actually decommissioned.

### Dashboard migration (the "Test" dashboard)
It was the only consumer of the removed sensors, so it had to move first -
otherwise the cleanup would have left a dashboard full of dead cards. Its two
grids and three thermostat cards were repointed at heatctl:
`sensor.rl_N` -> `sensor.heatctl_return_circuit_N`, `sensor.ventil_N` ->
`sensor.heatctl_valve_hkNN`, `average_valve_opening` ->
`installed_valve_demand`, and `climate.wohnzimmer_eg` / `gastebad_eg` ->
`climate.heatctl_*`. Cards with no heatctl equivalent were dropped: circuits 5
and 12 (out of service), valve channels for circuits 8-10 (no analog output
assigned), and the Elternschlafzimmer thermostat (no room sensor, so heatctl
publishes no thermostat for it). A small `heatctl` entities card was added.

Note the ordering trap that made this worth checking first:
`sensor.average_valve_opening` still appeared in a search of the LIVE pump
reconciler - but only in its `description` prose, explaining why valve-demand
gating is not used yet. Harmless. The two legacy pump automations that really
did trigger on it are off but not deleted, and can no longer be meaningfully
re-enabled; that is fine, since re-enabling them caused an outage on
2026-07-26 and `sensor.installed_valve_demand` is the modern replacement.

This whole `rest:` block dies with the Mini Server anyway, so the above is a
step toward switching that machine off, not just tidying.


## Operational state changed on 2026-07-27 — READ THIS BEFORE DEBUGGING HA

Things that were deliberately turned off or commented out on the Home Assistant
side that day. Written down because none of it is discoverable from the running
system: an automation that is off looks the same as one that never existed, and
a commented-out YAML block looks like it was never configured.

### Disabled, and NOT to be re-enabled without thought
| What | State | Why | What replaced it |
|---|---|---|---|
| `automation.heat_pump_circulation_pump_request` | **off** | It wrote register 0 bit 0, which is the unit's POWER, not the water pump (docs/HEATPUMP.md). Two masters on one RS485 bus also cannot honour the device's 200 ms minimum. | heatctl's `source_demand` reconciler holds the unit powered |
| `automation.climate_chilling_setpoint_supervisory_loop` | **off** | Same bus contention; and the setpoint now has one owner. | heatctl's water-setpoint loop (`control.water_setpoint`), whose breach branch is the direct port |
| `automation.climate_prevent_condensation_with_modbus_fallback` | **off** | Same. | heatctl's `safety.cooling_requires_dew_point` (valve side) plus the setpoint loop's breach jump (source side) |
| `modbus:` block in `/config/configuration.yaml` | **commented out** | heatctl is now sole Modbus master for the heat pump - two independent masters cannot honour the 200 ms interval and demonstrably interfered. | heatctl publishes every register over MQTT; HA consumes those entities |
| 4 HomeKit `climate` + `sensor` entities (Bad, both Kinderzimmer, Elternschlafzimmer) | **registry-disabled** | They report a hardcoded 10 degC - Controme's placeholder for "no sensor" - which HA renders as an ordinary live reading. | nothing needed; the rooms have no sensor |

Backups on the host: `/config/configuration.yaml.bak-modbus-*` (before the
modbus block was commented out) and `/config/configuration.yaml.bak-*` (before
the dead REST sensors were removed).

**The HomeKit config entry itself was deliberately NOT deleted** - re-adding it
needs a pairing code, so it is not trivially reversible. Disable, do not delete,
until the Mini Server is actually decommissioned.

### Still live and load-bearing
- `automation.heatctl_bridge_legacy_wall_unit_room_temps_to_mqtt` - room
  temperature AND dial setpoint for Gaestebad and Wohnzimmer. Without it those
  two rooms lose their air sensor and fall back to return-temperature control.
- `automation.heatctl_publish_indoor_dew_point_to_mqtt` - **safety-critical**.
  heatctl stops cooling entirely without a fresh dew point
  (`cooling_requires_dew_point`), so if this automation stops, cooling stops.
  That is the intended failure direction, but know that it is the cause.
- `sensor.system_dew_point_reference` and the two rooms' `luftfeuchte` REST
  sensors that feed it.

### Recording
InfluxDB receives everything via a **config entry**, not an `influxdb:` YAML
block - so the absence of YAML is not evidence that recording is off. That
mistake was made and corrected on 2026-07-27. Verified by querying Influx
directly: heatctl circuits, setpoints and heat pump registers all landing at
full resolution. Grafana add-on is installed alongside.
