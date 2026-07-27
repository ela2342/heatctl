# Roadmap

**What this is:** where the system is going, milestone by milestone, and the
record of what has already been done and why. Completed items keep their full
rationale — that history is the point, not clutter.

**What this is NOT:** the list of things to do. That is `BACKLOG.md`, which is
the single source of truth for open work. Each milestone below names the
backlog items belonging to it rather than restating them, so nothing is
tracked in two places.

See also `docs/DECISIONS.md` for decisions that established a principle or
reversed an earlier one, referenced by stable ID (`D-nnn`).

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
- Heat pump (PW58321) on Modbus RTU via Waveshare RS485 gateway
  (192.0.2.37), HA modbus hub "WSDEV0001". **Register map: docs/HEATPUMP.md**
  (full vendor manual captured in the local-only docs/PW58321_MODBUS.local.md).
  CORRECTED 2026-07-27: this line previously said "register 0 = control flags
  (bit 0 = water pump)". Bit 0 of 0x0000 is the unit's **POWER ON/OFF**. The
  pump knob is bit 4. So the HA automations that "hold the pump request set"
  are holding the whole unit powered on, and the condensation automation that
  clears it powers the heat pump off - which is what was found on 2026-07-26.
  Note docs/DESIGN.md always had this right; the error lived only here, and was
  then propagated into the HA automation and a template helper, which made
  three sources look like corroboration when they had one origin.
  Currently written by HA automations - see milestone 1 warning.
- Rooms/circuits: see `rooms:` in config.yaml (Gästebad, Wohnzimmer x4,
  Kinderzimmer Natalie/Naomi, Badezimmer, Elternschlafzimmer, Arbeitszimmer;
  circuits 5 and 12 out of service).

## Milestone 0 - bring-up (manual, no code)


- [x] Verify valve<->circuit mapping (2026-07-27, owner): **it is 1:1 with
      the circuit number** - analog output n drives circuit n, and input n is
      that circuit's return sensor. Also resolved the Wohnzimmer 8/9/10 valve
      assignment, since 16 outputs (4x 750-559) means every circuit has one.
      This corrected a real error: config.yaml's old 8-channel table had been
      built by fitting 10 active circuits into 8 outputs, so it skipped the
      out-of-service circuits and shifted indices 5-8 - the Arbeitszimmer room
      PID was driving circuit 7's output. Harmless only because no actuator is
      fitted there. See docs/HARDWARE.md.
      The hk07/hk10 room mapping was settled separately on 2026-07-26 from the
      Controme database and is unaffected.
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


- [x] pytest suite (2026-07-27, 232 tests, ~5 s by the end of that day): PID (direction, invert,
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
      protection, and a stagnant reading is still a real temperature from a
      real place in the building.
      Worth recording WHY, because the symptom is not the intuitive one. The
      RL sensors are on the return pipes AT THE MANIFOLD, not in the slab
      (docs/HARDWARE.md). A circuit with no flow is therefore not measured at
      all: its sensor drifts toward the manifold cabinet's ambient, dominated
      by the headers running past it, i.e. toward roughly system water
      temperature. With the interim system-return target that reads as
      "error zero, nothing to do" - so the failure is silent LOCK-OUT rather
      than oscillation: a closed circuit manufactures its own evidence to stay
      closed. Which is why the periodic flush, not the hold, is the
      load-bearing part of the fix.
      Full scheduled flush-and-remeasure remains docs/DESIGN.md section 4.
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
      On a stale or missing reading heatctl STOPS COOLING
      (`cooling_requires_dew_point`, default on) rather than trusting the
      static `vl_min_cooling_c`. That value arrived undocumented in the
      initial commit and is not conservative - a 26 degC room at 60 % RH has a
      dew point of 17.6 degC, above it. It looks like a safe floor and is not
      one. This is also the only protection left in the case the HA-side
      automation cannot cover: a dew point missing *because HA died* takes its
      source-side pump shutdown with it.
      Same change fixed a rule-ORDER defect found while writing it: the
      known-bad-supply checks now run BEFORE the fail-open one. They depend on
      the supply sensor and are independent of the circuit's return sensor, so
      checking fail-open first meant one faulted return sensor forced its
      circuit open even while the supply was measurably below the dew point -
      condensation protection defeated by an unrelated sensor fault.
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
- [x] Clean up the dead legacy Controme entities in HA (2026-07-27). Removed
      12 `rl_*`, 11 `ventil_*` and the min_max over them from
      configuration.yaml (backup + `ha core check` + registry purge); kept the
      eight REST sensors live control depends on. Turned out there were THREE
      paths carrying the same legacy data, not one: the HomeKit bridge
      (`homekit_controller`, 29 entities) is easy to miss because it is an
      integration rather than YAML, and four of its seven rooms report a
      hardcoded 10 degC - Controme's placeholder for "no sensor", which HA
      presents as an ordinary live reading. Those are disabled; the config
      entry is deliberately NOT deleted, since re-adding it needs a HomeKit
      pairing code. The "Test" dashboard was the only consumer of the removed
      sensors and was migrated to heatctl's equivalents first, dropping cards
      with no equivalent rather than faking them.
      Full detail in docs/HA_INTEGRATION.md. Step toward switching the legacy
      server off, not just tidying.
- [x] Load compensation: house demand -> water setpoint (2026-07-27,
      `heatctl/setpoint.py`). Until this existed the water temperature was a
      constant that only ever moved upward, defensively, when the condensation
      guard shoved it there - nothing connected "the house is 0.6 K too warm"
      to "make water at N degC". Signal is BOTH house deviation and valve
      saturation, because water colder than needed does not make the house
      colder, it just makes the valves throttle it back: the error is
      invisible in room temperature and shows up only as COP and condensation
      risk. 1 K every 30 min (owner), integer and hysteretic, because every
      write wears the pump's flash and the slab has hours of thermal mass.
      A measured leaving-water breach bypasses the cadence - that is a safety
      event, not a trim. This also subsumes the old HA chilling-setpoint loop,
      so the setpoint has ONE owner.
      Honest limit while only two circuits are actuated: the other eight are
      open pipe and cannot throttle, so valve saturation barely reflects load
      and the loop effectively runs on house deviation alone.
- [x] Data recording verified working (2026-07-27). Home Assistant forwards to
      the InfluxDB add-on via a CONFIG ENTRY, not a `influxdb:` YAML block -
      an earlier note in this session wrongly concluded "no YAML, therefore not
      recording". Confirmed by querying Influx directly: heatctl's circuits,
      setpoints and heat pump registers are all landing at full resolution.
      heatctl's own SQLite is now a 14-day rolling buffer rather than an
      archive - the layer-1-independent fallback for when HA is the thing that
      broke. Unbounded it would have been about a GB a year.
      Everything heatctl knows is now exposed as an entity (and so recorded):
      valve command AND read-back, the demand signals, the water-setpoint
      decision, plant/pump mode agreement, and every decoded heat pump value
      including all 20 fault bits. The 312 raw registers stay on hp/raw/# but
      are deliberately NOT discovered - 312 diagnostic entities would bury
      everything useful.


- [x] Heat-demand logic (2026-07-27), replacing the HA automations
      "Steuerung der Wasserpumpe...". The design was CORRECTED mid-flight and
      the correction is the useful part - see D-016. It is a RECONCILER, not an
      on/off controller: the heat pump regulates itself, starting and stopping
      its own compressor and varying power from the leaving/return spread, so
      heatctl holds the unit powered and only powers down on an explicit `off`.
      The original design stopped the source when the house was satisfied, and
      again when flow fell low; both were wrong, and the second was circular -
      valve position is heatctl's own output.
      `source_demand.enabled` and `auto_mode` are both on, so the house average
      also picks the plant mode (D-020) and heatctl writes the pump's mode
      register (0x0004) to match. heatctl is sole Modbus master for the unit
      (D-013), and every write is transition-only because they wear its flash.

## Milestone 2 - DHW station (fresh water) fast loop


## Milestone 3 - layer 2 (`optimizer/`, separate process/container)


## Milestone 4 - production


## Conventions
- Python >=3.11, stdlib + pinned minimal deps, type annotations everywhere
- asyncio only, no threads, no global singletons
- Every safety rule gets a test
- Code and docs in English (open-source ready); config labels may be German
