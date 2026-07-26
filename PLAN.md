# heatctl - development plan (to be executed with Claude Code)

## Context for the model

Two-layer architecture for floor heating/cooling driven by a WAGO 750-352
Modbus coupler, designed for 30-year maintainability and full independence
from Home Assistant.

- **Layer 1 (this repo, `heatctl/`)**: self-sufficient control core.
  Safety-critical. Minimal pinned dependencies. NEVER call HA APIs here.
- **Layer 2 (to be built, `optimizer/`)**: setpoint optimization (weather,
  PV forecast, system identification). May fail at any time. Talks to
  layer 1 ONLY via MQTT (`heatctl/set/...`); safety clamps everything.

### I/O architecture (decided, do not relitigate)
The control core is transport-agnostic via `heatctl/backends/`:
- `mqtt` (default): WAGO I/O via a modbus2mqtt bridge; room sensors
  (Shelly H&T) via MQTT anyway. Broker (mosquitto) + bridge + heatctl all
  run on the SAME dedicated machine; HA bridges into that broker.
- `modbus_direct`: fallback/insurance path, and mandatory transport for
  future fast loops (DHW station, 100 ms) - those must not go through a
  polling bridge.
Bridge-specific topic knowledge lives ONLY in `backends/mqtt_io.py`.

### Existing environment
- WAGO 750-352 @ 192.0.2.52 (mapping: config.yaml + docs/HARDWARE.md)
- HA @ 192.0.2.230 with Mosquitto and an unconfigured Modbus2MQTT add-on
- Heat pump on Modbus RTU via Waveshare RS485 gateway (192.0.2.37),
  HA modbus hub "WSDEV0001", register 0 = control flags (bit 0 = water pump).
  Currently written by HA automations - see milestone 1 warning.
- Rooms/circuits: see `rooms:` in config.yaml (Gästebad, Wohnzimmer x4,
  Kinderzimmer Natalie/Naomi, Badezimmer, Elternschlafzimmer, Arbeitszimmer;
  circuits 5 and 12 out of service).

## Milestone 0 - bring-up (manual, no code)
- [ ] Verify valve<->circuit mapping in config.yaml (8 analog outputs vs
      10 active circuits; Wohnzimmer circuits 7/8/9 valve assignment TODO)
- [ ] Configure modbus2mqtt on the dev host (or HA add-on for prototyping):
      poll input registers 12-27 (temps), write holding registers 12-19.
      Document the exact register map + topics in docs/MODBUS2MQTT.md
- [ ] Enable the coupler's Modbus watchdog in the WBM; document behavior
- [ ] Local test run: `python -m heatctl.main ./config.yaml`
- [ ] Verify HA MQTT discovery shows sensors + valves

## Milestone 1 - harden layer 1
- [ ] pytest suite: PID (step response, anti-windup, invert), Safety (frost,
      overtemp, sensor fault, stale), MqttIOBackend staleness promotion,
      backend contract test run against both backends with fakes
- [ ] Reconnect/backoff in modbus_direct (currently: crash -> restart)
- [ ] Heat-demand logic: request heat pump when sum of valve openings > X
      (replaces the HA automations "Steuerung der Wasserpumpe..."').
      WARNING: while those HA automations are active, heatctl must NOT
      write WSDEV0001 register 0 (two writers doing read-modify-write on a
      flag register = race). Migrate in one step, then disable them in HA.
- [ ] Cooling: dew-point supervision. Subscribe weather-station dew point
      via MQTT (configurable topic), fall back to static vl_min_cooling_c
      when data is missing/stale (port of the existing HA automation
      "Climate: Prevent Condensation").
- [ ] Shelly room sensors: add real topics to config, validate cascade
      (room PID) vs fallback (return PID) switchover

## Milestone 2 - DHW station (fresh water) fast loop
- [ ] Flow sensor with pulse output on a digital input (16DI terminal,
      discrete inputs FC2) - hardware addition
- [ ] Feed-forward: pump speed (0-10V, spare 750-559 channel) as a
      function of flow; temperature PID only trims
- [ ] Separate asyncio task at 100 ms using modbus_direct ONLY;
      temperatures stay at 1 s (750-463 limit)

## Milestone 3 - layer 2 (`optimizer/`, separate process/container)
- [ ] System identification from heatctl.sqlite: fit step responses per
      room/circuit (first/second-order models, scipy.optimize), report
      time constants
- [ ] Weather forecast (Open-Meteo, no API key) + PV forecast
- [ ] Heuristic v1 (no MPC): rule-based setpoint shifting, e.g. "PV surplus
      expected in <4 h and buffer < X -> postpone buffer charging"
- [ ] MPC v2 optional (cvxpy), only after v1 runs and models are validated
- [ ] Everything via `heatctl/set/setpoint/<room>` and `heatctl/set/mode`

## Milestone 4 - production
- [ ] Dedicated machine next to the coupler: mosquitto + modbus2mqtt +
      heatctl via systemd (deploy/systemd/), hardware watchdog,
      consider read-only rootfs
- [ ] HA: bridge HA-Mosquitto <-> dedicated broker; remove WAGO-related
      HA modbus config and automations
- [ ] Backup: config.yaml + sqlite; vendor dependencies (pip download)
      for long-term reproducibility
- [ ] Keep docs/HARDWARE.md current: every terminal, wire and register

## Conventions
- Python >=3.11, stdlib + pinned minimal deps, type annotations everywhere
- asyncio only, no threads, no global singletons
- Every safety rule gets a test
- Code and docs in English (open-source ready); config labels may be German
