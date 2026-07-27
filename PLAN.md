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
- [x] pytest suite (2026-07-27, 88 tests, ~2 s): PID (direction, invert,
      anti-windup, clamping), Safety (every rule, asserted by *direction* -
      fail-open vs fail-closed), Controller (mode wiring, both control paths,
      staleness, telemetry, system-return tracking), modbus_direct against a
      fake coupler (availability rules, backoff, watchdog recovery, decoding),
      and config.yaml self-consistency. Run: `pip install -r
      requirements-dev.txt && pytest`.
      Both mandated regressions are in and were **mutation-verified** - each
      was re-broken and the suite confirmed to fail:
      (a) starting in `mode: cooling` from config must invert the PIDs -
      `Controller.__init__` applied the mode to the setpoints but not to
      `pid.invert`, so config-configured cooling ran in the heating
      direction (fixed 2026-07-26, found by hardware test, not by reading);
      (b) modbus_direct reconnect/backoff behaviour, see below.
      Plus three more from real defects: the watchdog trigger toggle
      (2026-07-27 outage), failsafe log throttling, and staleness honesty on
      a failed read.
      Still uncovered, deliberately: MqttIOBackend staleness promotion and a
      shared backend contract test across both backends - `mqtt_io` is not in
      use (docs/MODBUS2MQTT.md) and testing it now would pin down an
      interface nobody exercises. Do it if that backend is ever revived.
- [x] Writing the suite immediately found a latent defect (2026-07-27):
      `read_state()` requested `len(channels)` registers but indexed the reply
      by channel *index*, so any config.yaml listing a subset of channels
      crashed the loop with IndexError every cycle - a `cycle_error`, not a
      graceful degradation. Now reads up to the highest index.
- [x] Valve output read-back verification (2026-07-27): one extra FC3 read
      per cycle at `0x0200 + word` fills `IOState.valves_readback_pct` and
      `valve_mismatch`, published on `heatctl/valve_mismatch/<name>` when they
      disagree. This is observability, not correction - the per-cycle write
      already heals a forced output within a second, which is precisely the
      problem: a watchdog trip zeroes the outputs and then self-heals leaving
      no trace at all. Auto-disables (one log line) if the mirror is not
      readable, and a failure there can never break `read_state`.
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
- [x] RL validity gating (2026-07-27, `heatctl/rl_gate.py`). RL counts only
      after the valve has been commanded past `min_opening_pct` for
      `settle_s` (stroke PLUS transport time). Otherwise the circuit holds its
      last known-good command, and is re-opened every `flush_interval_s` to
      take one honest reading. Never measured is treated as lost knowledge, so
      the caller falls back to fail-open - which also makes start-up
      self-healing with no special case and no forced full-open on every
      deploy. Circuits with `fitted: false` are always trusted: open pipe
      flows regardless of what we command, so gating them would be a fiction
      of its own. Safety is deliberately NOT gated - it reads RL for frost
      protection, and slab ambient is a fine frost indicator.
      Worth recording WHY, because the symptom is not obvious: the error is
      not merely inaccuracy. A closed circuit's RL drifts toward slab ambient,
      which reads as "more demand" in BOTH modes, so the loop opens, sees the
      real RL, closes, and repeats - a self-sustaining hunt on actuators that
      take minutes per stroke.
      Full scheduled flush-and-remeasure remains docs/DESIGN.md section 4.
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
- [x] Cooling: dew-point supervision (2026-07-27). `mqtt.dew_point_topic`
      feeds `Safety.set_dew_point`; the cooling limit becomes
      `dew point + dew_point_margin_c`, floored by `vl_min_cooling_floor_c`
      to bound a stuck-low humidity sensor, and falls back to the static
      `vl_min_cooling_c` when the reading is older than
      `dew_point_max_age_s`. The fallback is deliberately NOT the max of the
      two: the point is accuracy in both directions. Live on the plant the day
      it landed - a 13.3 degC dew point gave a 15.3 degC limit where the
      static value had been holding circuits shut at 16.0 for no reason.
      INDOOR dew point, not the weather station: outdoor is frequently higher
      and would forbid cooling that is perfectly safe indoors. Source is HA's
      `sensor.system_dew_point_reference` republished by an automation
      (docs/HA_INTEGRATION.md). The HA-side pump-request shutdown stays where
      it is - that is source-side, this is valve-side.
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
- [ ] Clean up the dead legacy REST entities in HA. Most of the ~40 read
      null/0 permanently (fed by the retired floor gateway) AND are superseded
      by heatctl's own published sensors, so the entity list is now actively
      misleading. docs/HA_INTEGRATION.md lists exactly which are safe to remove,
      which MUST be kept because live control depends on them (the two rooms'
      temperature, humidity and dial setpoint), and which to leave dormant.
      Check nothing still references sensor.average_valve_opening first - the
      two legacy pump automations are off but not deleted. Step toward switching
      the legacy server off, not just tidying.
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
