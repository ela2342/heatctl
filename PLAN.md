# heatctl - development plan (to be executed with Claude Code)

## Context for the model

Two-layer architecture for floor heating/cooling driven by a WAGO 750-352
Modbus coupler, designed for 30-year maintainability and full independence
from Home Assistant.

The whole-system target design (buffer tank, wood stove, DHW, operating
modes, physical model + estimation, planner) lives in `docs/DESIGN.md`;
its work packages WP-A..WP-I extend the milestones below.

- **Layer 1 (this repo, `heatctl/`)**: self-sufficient control core.
  Safety-critical. Minimal pinned dependencies. NEVER call HA APIs here.
- **Layer 2 (to be built, `optimizer/`)**: setpoint optimization (weather,
  PV forecast, system identification). May fail at any time. Talks to
  layer 1 ONLY via MQTT (`heatctl/set/...`); safety clamps everything.

### I/O architecture (decided, do not relitigate)
The control core is transport-agnostic via `heatctl/backends/`:
- `modbus_direct` (**ACTIVE, changed 2026-07-26**): direct Modbus TCP to the
  WAGO. Also the mandatory transport for future fast loops (DHW station,
  100 ms) - those must not go through a polling bridge.
- `mqtt`: WAGO I/O via a modbus2mqtt bridge. Kept in the tree but NOT in use.
  Bridge-specific topic knowledge lives ONLY in `backends/mqtt_io.py`.

Why the change: the available HA modbus2mqtt add-on publishes one aggregated
JSON document per device and cannot emit raw per-register values on flat
topics, so it cannot meet the contract in `docs/MODBUS2MQTT.md` - see that
file for the full investigation before reconsidering. This is the
"insurance policy" in the original design paying out. Note heatctl's own
control plane already publishes every sensor and valve to MQTT with HA
discovery (`ControlPlane`), so dropping the bridge costs no HA visibility.
Room sensors still arrive via MQTT regardless of this choice.

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
      10 active circuits; Wohnzimmer circuits 7/8/9 valve assignment TODO).
      Also resolve the hk07/hk10 conflict against the legacy Controme
      mapping - see the cross-check table in docs/HARDWARE.md
- [ ] Hardware still missing: a 750-1606 (enough 0V terminals for all 12
      valves) and 2x 750-559 (drive all valves, plus spares). Currently
      only 2 valves are wired: Gästebad (hk01) and Wohnzimmer (hk02)
- [~] NOT APPLICABLE - modbus2mqtt abandoned, see docs/MODBUS2MQTT.md. Was:
      Configure modbus2mqtt on the dev host (or HA add-on for prototyping):
      poll input registers 12-27 (temps), write holding registers 12-19.
      Document the exact register map + topics in docs/MODBUS2MQTT.md
- [x] Enable the coupler's Modbus watchdog. Was DISABLED as of
      2026-07-26, so there is no hardware failsafe at all right now. Steps:
      (a) DONE 2026-07-26 from the manual: use Type **Standard** with coding
      mask 0x8020 in 0x1001 (FC6 + FC16). Standard evaluates the mask; it is
      *Alternative* that resets on any telegram. An earlier note here advised
      Alternative - that was backwards. With a write-only mask heatctl's normal
      per-cycle valve write IS the heartbeat, so no extra trigger write needed;
      (b) DONE 2026-07-26: no output-behaviour option exists anywhere in the
      WBM, so full-scale-on-timeout is NOT configurable. Outputs clear to 0 on
      timeout, i.e. valves close. Accepted: when heatctl is dead, closing is the
      conservative choice against condensation, and 8 of 10 circuits are open
      pipe so circulation continues anyway. MUST be revisited once every circuit
      has an actuator - then a trip would deadhead the heat pump;
      (c) NO coupler reset needed via registers: write 0x1000 (time), then a
      non-zero mask to 0x1001 arms it live; 0x1008 (0x55AA/0xAA55) stops it.
      Fully reversible, no I/O outage. Do not write 0x100B (makes it remanent)
      until settled;
      (d) implement in modbus_direct: arm on start, and CRUCIALLY handle the
      trip - after a time-out the coupler answers every request with exception
      0x0004 and blocks process-data writes until a non-zero value is written
      to trigger register 0x1003. Without that, one transient trip disables
      control permanently. Detect status 0x1006 == 2 and re-arm;
      (e) DONE 2026-07-26: armed, tripped and recovered on live hardware -
      heatctl arms on start, the trip blocks process data while leaving the
      watchdog registers readable, and heatctl clears it and resumes within one
      cycle. Only remaining unknown is physical output zeroing during the trip,
      which cannot be read back while process data is blocked.
      See docs/HARDWARE.md for the register values and page contents.
- [x] Local test run: `python -m heatctl.main ./config.yaml` (2026-07-26 -
      full run() loop against the real coupler and HA's Mosquitto; outputs
      parked closed afterwards)
- [x] Verify HA MQTT discovery shows sensors + valves (2026-07-26 - 28
      entities: 12 temperatures, 8 valve positions, plus `select.heatctl_mode`
      and 7 `number.heatctl_setpoint_*` controls so HA can actually command
      mode and setpoints instead of only displaying. Entities correctly go
      `unavailable` when heatctl stops.)
      NOTE: MQTT credentials come from `HEATCTL_MQTT_USERNAME` /
      `HEATCTL_MQTT_PASSWORD` in the environment, never from config.yaml -
      that file is committed. Currently reusing HA's own `homeassistant`
      broker account; a dedicated credential would be tidier (see
      deploy/systemd/README.md).

## Milestone 1 - harden layer 1
- [ ] pytest suite: PID (step response, anti-windup, invert), Safety (frost,
      overtemp, sensor fault, stale), MqttIOBackend staleness promotion,
      backend contract test run against both backends with fakes.
      Two regression tests this suite MUST include, both from real defects:
      (a) starting in `mode: cooling` from config must invert the PIDs -
      `Controller.__init__` applied the mode to the setpoints but not to
      `pid.invert`, so config-configured cooling ran in the heating
      direction (fixed 2026-07-26, found by hardware test, not by reading);
      (b) modbus_direct reconnect/backoff behaviour, see below.
- [ ] Valve output read-back verification: heatctl treats
      `IOState.valves_pct` as the last *commanded* value and never reads the
      coupler back, so it cannot notice that the WAGO Modbus watchdog has
      fired and forced the outputs to their safe state. Read-back lives at
      `0x0200 + word` (see docs/HARDWARE.md) - one extra FC3 read per cycle.
- [x] Reconnect/backoff in modbus_direct (2026-07-26, promoted to
      prerequisite when modbus_direct became the active backend):
      `start()` no longer raises when the coupler is unreachable (the control
      loop must come up so safety runs; stale-data failsafe covers the gap),
      `read_state()` returns the previous state without refreshing
      `last_read_ts` so staleness is reported honestly instead of surfacing
      as a bogus "cycle_error", reconnects are rate-limited with exponential
      backoff (`reconnect_delay_s` .. `reconnect_delay_max_s`) and each
      attempt is bounded by `timeout_s` so the 1 s loop never stalls.
      `write_valve()` still raises, per the IOBackend contract.
      STILL MISSING: unit tests for this - see the pytest item above.
- [ ] RL validity gating (present defect, do before WP-C): `Controller.step`
      feeds the per-circuit return PID from `state.temps[sensor]` with no
      check on valve position, but a closed circuit's RL sensor reads slab
      ambient, not loop state. Since every `room_temp_topic` is still empty,
      this fallback is currently the ONLY live control path, so the whole
      controller acts on invalid RL whenever a valve is closed. Minimal fix:
      don't trust RL below an opening threshold - hold last valid value or
      fall back to the curve default. Full flush-and-remeasure scheme is
      docs/DESIGN.md section 4.
- [ ] Heat-demand logic: request heat pump when sum of valve openings > X
      (replaces the HA automations "Steuerung der Wasserpumpe..."').
      WARNING: while those HA automations are active, heatctl must NOT
      write WSDEV0001 register 0 (two writers doing read-modify-write on a
      flag register = race). Migrate in one step, then disable them in HA.
- [x] Cooling: source-side response to a supply-below-dew-point breach.
      DECIDED 2026-07-26 (owner's call): raising P04 is sufficient - the heat
      pump reacts to setpoint changes quickly, and a few minutes of supply
      below dew point is not critical given the screed's mass. So NO
      circulation-stop interlock and no shared inhibit flag. The HA loop jumps
      P04 to dew point + 6 on breach rather than creeping 1 K/min, and that is
      the whole mechanism. Do not add a stop-the-pump path without revisiting
      this decision.
- [ ] Cooling: dew-point supervision. Subscribe weather-station dew point
      via MQTT (configurable topic), fall back to static vl_min_cooling_c
      when data is missing/stale (port of the existing HA automation
      "Climate: Prevent Condensation").
- [x] Room air sensors, interim (2026-07-26): all three available sources are
      live - Arbeitszimmer subscribes to its sensor's own MQTT topic directly,
      Gaestebad and Wohnzimmer are bridged from HA including their dial
      setpoints. See docs/HA_INTEGRATION.md. Was: publish the two legacy wall
      units (Gästebad, Wohnzimmer - see docs/HARDWARE.md)
      to MQTT and set their `room_temp_topic` in config; validate cascade
      (room PID) vs fallback (return PID) switchover. Making them independent
      of the legacy server means serving the HTTP routes they already call,
      which is also how their display/interval settings get configured - see
      the local notes outside this repository for the details. Only some units
      survived the overvoltage event, so this covers 2 rooms, not the house.
- [ ] Room air sensors, target: Shelly H&T per room via MQTT (none bought
      yet). This is still the long-term plan; the legacy wall-unit bridge above
      is interim plumbing with a finite life. Rooms without either source
      keep running on the return-temperature fallback.

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
