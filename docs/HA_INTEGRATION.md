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
| `sensor.system_dew_point_reference` | template | **Highest INDOOR dew point**, Magnus formula over each room's temperature+humidity, falling back to the outdoor station only when no indoor pair is available. Indoor is what governs slab condensation; outdoor is often higher and would forbid cooling. Yields `unknown` only when every source is gone, which is what the safety shutdown keys on. **The pair list is the load-bearing part - see below.** |
| `sensor.system_dew_point_pairs` | template | How many rooms are actually behind the reference. 6 is healthy. Added 2026-08-10 because the reference degraded to 2 rooms silently for two weeks; a dew point is plausible at any room count, so only the count shows it. 0 means it has fallen back to the OUTDOOR station, which is drier than indoors and therefore unsafe in the cooling direction. |
| `binary_sensor.heat_pump_pump_request` | template | Bit 0 of the heat pump's control-flag register, so automations can compare against the actual request bit instead of the pump's output state - avoids rewriting the same register value every tick and wearing the controller's flash. |
| `sensor.installed_valve_demand` | min_max (max) | Max of the two valve channels that actually have an actuator. Currently **unused** - kept for when the remaining actuators arrive. |

## Automations

> **STATUS 2026-08-05: every automation in this table that touches the heat
> pump is OFF and has been since 2026-07-28 23:25.** They remain in the entity
> registry rather than deleted, so they are trivially reversible, but nothing
> below writes a heat-pump register today. The only row still running is the
> wall-unit bridge (20159 state changes in the last 7 days), which touches MQTT
> and not the pump. Read the table as history plus a rebuild recipe, not as a
> description of what is currently steering the plant.
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
3. ~~**Single-writer boundary.** The heat pump's registers are written by these
   HA automations, not by heatctl. Until WP-B migrates that, heatctl must not
   write them.~~ **RESOLVED 2026-07-28, recorded 2026-08-05.** All four
   heat-pump-writing automations were turned off at 23:25 that night and have
   not run since — verified in InfluxDB: `last(state)` is `off` for each, and
   zero state changes in the following seven days against 42352 / 58780 /
   401 / 6 points in the preceding month. **heatctl is the sole writer of the
   heat pump's registers**, including `0x0000`.

   This entry stayed stale for a week and cost real advice: on 2026-08-05 the
   C01 fix for recurring Er03 was recommended "at the front panel, to avoid
   racing the HA automations" that had not existed for eight days. A doc that
   describes a retired constraint is worse than no doc, because it is trusted.

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

## Dashboard

`heatctl-overview` ("Heizung", in the sidebar). One screen, deliberately not a
dump of the ~94 entities heatctl publishes. What it shows and why:

| Section | Content | Why these |
|---|---|---|
| Badges | Heat pump fault and plant/pump mode conflict — **hidden unless active** — plus outdoor temperature and dew point | Faults must be impossible to miss but must not occupy space while everything is fine |
| Status | Mode, house deviation, **spread**, and the two decision strings verbatim | The spread is the efficiency KPI (docs/DESIGN.md 4.5). The decision strings say *why* the plant is doing what it is doing, which no gauge can |
| Ventile | Only circuits 1 and 2, labelled as the only ones with actuators | Showing twelve bars would imply twelve working valves. Ten of those commands go to outputs with nothing attached, so the number is real but the valve is not |
| Räume | The three `climate.heatctl_*` with target-temperature control | The only rooms with an air sensor. Rooms without one are absent rather than shown inert |
| Wärmepumpe | Fault, compressor, cooling setpoint (adjustable), leaving/return water, power estimate | Enough to see whether the source is working and to trim it by hand |
| Verlauf | Room temperatures 24 h; water temperatures and dew point 24 h | The two questions history actually answers: is comfort being delivered, and is the water where it should be relative to the condensation limit |

Deliberately NOT on it: the ~40 heat-pump diagnostic sensors, all twelve return
temperatures, the raw registers, valve read-backs, the flow proxy and peak
demand. They are recorded in InfluxDB and available for a graph when a question
needs them — putting them here would bury the six things that matter.

The power figure is `compressor current × 230 V` and is labelled as an
estimate. It ignores fans and pump and is not metered.

## The dew-point reference's pair list — 2026-08-10 incident

**Visible condensation on the Badezimmer floor and on the manifold pipework.**
Root cause was not the safety margin and not heatctl: the template helper's
room list had never been updated after the new room sensors went in.

```
listed since 2026-07-26     Gästebad, Wohnzimmer      (two Controme wall units)
instrumented since ~2026-08-07   Bad, Schlafzimmer, Kind Naomi   NEVER ADDED

reference read              12.0 °C
Bad's actual dew point      17.3 °C
supply running at           12.9 °C      → 4.4 K below the dew point in Bad
```

Bad is a bathroom and sat at 72 % RH against 45–55 % elsewhere, so it was 4–5 K
wetter than anything in the max() — and it was the room that condensed.

**Why nothing caught it for two weeks.** Every layer behaved correctly on the
data it was given. The helper's `max()` over a stale list is still a valid dew
point; heatctl enforced `dew + margin` faithfully; the guard tripped exactly
when it was told to. A dew point is a plausible number at any room count, so
no single reading looks wrong. This is the same failure shape as the layer-2
midnight forecast (D-034's follow-up): **a degraded input that stays inside its
plausible range.**

The margin was briefly raised 1.0 → 2.0 and **reverted the same hour** (owner):
the sensor list explains the condensation completely, so the margin was never
falsified and 1 K of supply headroom is worth ~1 kW of capacity. Do not
re-raise it as a reflex — fix the inputs.

### Rules for this helper

1. **Adding a room sensor means adding it here.** The pair only counts when
   BOTH temperature and humidity are live; a room missing one drops out
   silently.
2. **Keep `system_dew_point_pairs` in step with the reference's pair list.**
   It exists solely to make a silent drop visible.
3. **Arbeitszimmer is currently INCLUDED** (owner, 2026-08-10, "until we
   stabilize things"), reversing the 2026-07-31 exclusion. That exclusion's
   reasoning still stands — the fan coil has a condensate drain, so the room is
   designed to get wet, and including it costs real supply depression. This is
   a deliberate conservative choice for the unstable period, not a refutation.
   Revisit when the plant is demonstrably not condensing.
4. **The manifold itself condensed too, and no sensor measures its cabinet
   air.** The reference is a max over *rooms*; the manifold is in none of them.
   Nothing currently protects that surface except the room maximum happening to
   be conservative enough. See BACKLOG.
