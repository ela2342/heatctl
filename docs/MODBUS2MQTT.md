# modbus2mqtt bridge configuration (ABANDONED - see "Status" below)

**Decision taken 2026-07-26: `io.backend` is now `modbus_direct`.** This
document is kept as the record of why, and as the spec any future bridge
would have to satisfy. Reconnect/backoff in `modbus_direct` was implemented
in the same change (ROADMAP.md Milestone 1). Nothing below is a pending task.

Goal: bridge the WAGO 750-352 to MQTT so heatctl's `mqtt` io backend and
any other consumer see uniform topics.

Requirements for the bridge configuration:
- Poll input registers 12..27 (function code 4) at 1 s
- Publish RAW register values (heatctl decodes PT1000 itself, so fault
  saturation values 0x05DC/0xFED4 stay detectable). If your bridge insists
  on scaling, adjust `sensors`/fault detection accordingly - but raw is
  strongly preferred.
- Subscribe write topics for holding registers 12..19 (function code 6)
- Topic templates must match io.mqtt_io in config.yaml:
    temp:  modbus/wago/temp/<name>        (bridge -> broker)
    valve: modbus/wago/valve/<name>/set   (heatctl -> bridge)
- QoS 0 is fine (fresh beats reliable-but-old); DO NOT retain temp topics,
  retained stale values would defeat staleness detection.

Also enable the WAGO coupler's own Modbus watchdog (WBM) - it is the only
failsafe that survives a bridge crash.

Document the final bridge config file here verbatim once it works.

## Status (2026-07-26): blocked - this add-on cannot meet the contract above

Investigated the HA add-on `37e92509_modbus2mqtt` ("Modbus <=> MQTT",
upstream https://github.com/modbus2mqtt/server, v0.32.1). Conclusion: **it
cannot publish raw per-register values on flat per-name topics, no matter
how it is configured.** Its data model is architecturally incompatible
with the contract this doc requires. Details below so nobody re-derives
this from scratch.

### How the add-on stores config
`options: {}` / `schema: []` in the HA supervisor entry is real - it takes
no HA-level YAML options at all. It is a full Angular SPA + Express REST
backend behind ingress (port 3000), backed by its own internal state (not
a HA-editable file, not under `/addon_configs/`). Everything is done
through the web UI, or its REST API (unauthenticated on the container's
internal address, found by inspecting the shipped JS bundle - not
officially documented, treat as fragile/version-specific):
`/api/bus[ses]`, `/api/slave[s]`, `/api/configuration`, `/api/converters`,
`/api/specifications`, `/api/modbus/write/entity`. Global config
(`/api/configuration`) showed `mqttbasetopic: "modbus2mqtt"`,
`mqttusehassio: true` (it gets the Mosquitto connection from Supervisor
service discovery, not from stored credentials).

**Pre-existing state found, untouched by this work:** one bus already
defined, `busId 0`, `connectionData: {host: 192.0.2.37, port: 4196}`
- that host is the heat pump's Waveshare RS485 gateway (see
`docs/HARDWARE.md`), on a non-standard port, with **zero slaves** (so it
polls nothing right now). Origin unknown/unexplained. Left exactly as
found - do not add slaves to it or repurpose it; the heat pump register
single-writer rule applies regardless of which tool would be writing.

### The blocking architecture mismatch
Inspected the add-on's Angular bundle (`main-*.js` + lazy chunks) to find
its MQTT topic-building class. Confirmed behavior, independent of any UI
setting:
- **State (read) topic is one aggregate JSON document per Modbus "slave"
  (device)**, always at `<mqttbasetopic>/<rootTopic>/state/` (trailing
  slash included), built as `JSON.stringify({...one key per entity...})`.
  There is no per-entity/per-register state topic and no bare-scalar
  payload option - every value, however many entities a slave has, is
  delivered as one JSON blob on one topic.
- Command (write) topics *are* per-entity: `<mqttbasetopic>/<rootTopic>/
  <mqttname>/set/`. This alone would almost line up with
  `modbus/wago/valve/<name>/set` (modulo the trailing slash and the
  `mqttbasetopic` prefix) - but it's moot given the read side is broken.
- Available value converters (`/api/converters`): `number, select, text,
  binary, value` - none of them change topic granularity; "raw" is at
  best a converter choice, not a fix for the one-topic-per-device problem.

Consequence: heatctl's `mqtt` IO backend (`heatctl/backends/mqtt_io.py`)
subscribes `modbus/wago/temp/+` and does `int(float(payload))` per
message - i.e. it requires exactly the flat/bare-scalar shape this add-on
structurally cannot produce. This is not a settings problem; do not spend
more time trying to configure it into compliance.

### Two points that make the decision easier (added after review)
- **The bridge's main benefit is already covered elsewhere.** A reason to
  want WAGO-over-MQTT is "so HA and other consumers can see the I/O" - but
  heatctl's *control plane* already does that itself, independently of the
  IO backend: `ControlPlane.telemetry()` publishes `heatctl/temp/<name>` and
  `heatctl/valve/<name>` every cycle, and `_publish_discovery()` registers
  every sensor channel and valve as an HA MQTT-discovery sensor. So dropping
  the bridge costs no HA visibility. The bridge's remaining unique value is
  only "a consumer other than heatctl could drive the WAGO", which is not a
  goal - the single-writer rule says the opposite.
- **The WAGO Modbus watchdog stays mandatory.** This doc and
  `backends/mqtt_io.py` justify it as "the only failsafe that survives a
  *bridge* crash", which could be misread as "no bridge, no watchdog needed".
  Wrong: with `modbus_direct` it is what drives the outputs to a safe state
  when *heatctl itself* dies, hangs, or loses the network. It is the one
  failsafe that needs no software at all (DESIGN.md layer 0). Still a
  Milestone 0 item, unchanged.

### Consequence if `modbus_direct` becomes the primary path
`Reconnect/backoff in modbus_direct` (ROADMAP.md Milestone 1) is currently
listed as hardening; it becomes a **prerequisite**. Today
`ModbusDirectBackend.read_state()` raises on a failed read and there is no
reconnect logic, so the documented behavior is "crash -> restart". In
production `deploy/systemd/heatctl.service` has `Restart=always` /
`RestartSec=5`, so that degrades to a 5 s outage loop rather than a dead
controller - survivable, but it means every transient network blip restarts
the process and resets PID integrators. In *development* there is no
supervisor at all, so a blip just ends the run. Fix the reconnect path
before relying on this backend for anything unattended.

### Recommendation
- **Primary: use `io.backend: modbus_direct`.** This was already called
  out in `heatctl/backends/mqtt_io.py`'s own docstring and in CLAUDE.md as
  "the insurance policy against the bridge project going unmaintained" -
  this investigation is exactly that scenario materializing. `pymodbus`
  is already pinned in `requirements.txt` and `modbus_direct.py` is a
  working implementation; it talks to the WAGO directly and sidesteps
  this add-on entirely.
- If MQTT bridging to the shared broker is still wanted for other
  reasons, either (a) write a small standalone adapter that subscribes to
  this add-on's `modbus2mqtt/<rootTopic>/state/` JSON topics and
  republishes individual raw values onto `modbus/wago/temp/<name>` (extra
  always-on component, extra failure mode - evaluate whether that's worth
  it vs. modbus_direct), or (b) replace this specific add-on with a
  simpler bridge that natively does flat raw topics.

### What was verified (read-only, no writes anywhere)
- WAGO 750-352 at 192.0.2.52:502 is reachable and answering FC4 reads.
  Confirmed independently twice: once via the Controme Pi's `pymodbus`
  (python2.7), once directly from the heatctl host's own venv
  (`pymodbus>=3.6` per `requirements.txt`). Input registers 12-27 all
  decoded to plausible PT1000 return/supply temperatures (~17.5-22 C,
  no-heating-season baseline, July) with no channel showing the
  `0x05DC`/`0xFED4` fault-saturation values. All 16 channels are live.
- The MQTT broker itself (Supervisor's `core_mosquitto`, reachable as
  `192.0.2.230:1883`, credentials from HA's own `mqtt` config entry)
  is reachable and authenticates fine - verified with a scratch pub/sub
  round trip on a throwaway topic, not any production topic. The broker
  side is entirely ready; the gap is only the add-on described above.
- Valve write topics and WAGO holding registers: **not touched**, per the
  hard safety constraint - moot in any case since there's no working read
  path to pair them with yet.
- WAGO Modbus watchdog (WBM at https://192.0.2.52
 **not attempted** - browser/HTTPS admin task, needs the user.

### Bottom line
Not "configured, needs verification" - genuinely blocked upstream of any
config choice. Nothing was written to the WAGO, the heat pump gateway, HA
`configuration.yaml`, or the Controme Pi. Decide between `modbus_direct`
and an adapter/different bridge before revisiting this file.
