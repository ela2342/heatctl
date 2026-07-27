# Backlog

**The single source of truth for open work.** If it is not here, it is not
tracked. No TODO comments in code, no "still missing" notes buried in prose —
those go stale silently and nobody greps for them.

Grouped by the milestone in `ROADMAP.md` they belong to. Each item says what it
is, why it matters, and what unblocks it, because an item whose rationale has
been forgotten cannot be prioritised — it just sits here.

Markers: `[ ]` not started · `[~]` partially done or blocked externally ·
`[x]` here means rejected, kept so it is not re-proposed.

### Milestone 0 - bring-up (manual, no code)

- [~] Hardware: the **2x 750-559 arrived and are fitted** (2026-07-27,
      positions 9 and 10), so there are now 16 analog outputs - enough for all
      12 circuits plus spares. Still open: the 750-1606 (enough 0V terminals
      for all 12 valves) status is unconfirmed, and **only 2 actuators are
      physically on the manifold** - Gästebad (circuit 1) and Wohnzimmer
      (circuit 2). A module arriving is not an actuator being fitted; keep
      `fitted:` in config.yaml honest about the difference.
      WHEN THEY ARE FITTED, two decisions expire together and must be
      revisited in the same breath - both are safe today only because most
      circuits are unthrottleable open pipe:
      (a) the coupler watchdog's fail-closed trip, which would then shut every
      circuit and deadhead the pump into Er03;
      (b) heat-demand logic, which needs the minimum-flow figure - see the
      Milestone 1 item and docs/DESIGN.md 4.3.
      Also flip `fitted: true` per valve channel in config.yaml as each
      actuator goes on, or heatctl will keep treating that circuit as open
      pipe and skip RL validity gating for it.
- [~] NOT APPLICABLE - modbus2mqtt abandoned, see docs/MODBUS2MQTT.md. Was:
      Configure modbus2mqtt on the dev host (or HA add-on for prototyping):
      poll input registers 12-27 (temps), write holding registers 12-19.
      Document the exact register map + topics in docs/MODBUS2MQTT.md

### Milestone 1 - harden layer 1

- [ ] DEFERRED, deliberately: put the dew-point margin on a proper footing.
      `dew_point_margin_c: 2.0` is EMPIRICAL - it matches the margin the HA
      supervisory loop has run at without condensation.
      What it is NOT is a screed-gradient correction. The floor build-up is
      vapour-permeable, so condensation happens throughout the slab and
      directly on the PIPE WALL, which sits essentially at water temperature.
      Supply temperature is therefore very nearly the surface that matters and
      there is no hidden reserve standing behind it. So the margin has to
      cover measurement uncertainty and the spread of indoor dew point between
      rooms - not a thermal gradient. Sizing it means quantifying sensor error
      and inter-room dew-point spread (we currently measure humidity in two
      rooms), which is data we do not have yet. Not worth blocking on: the
      empirical value has a track record. Revisit when more rooms report
      humidity, or sooner if condensation is ever observed.
      Note condensation inside the slab is INVISIBLE - no wet patch will
      prompt anyone to intervene. That is a standing argument against relaxing
      any of this.
- [ ] Room air sensors, target: Shelly H&T per room via MQTT (none bought
      yet). This is still the long-term plan; the legacy wall-unit bridge above
      is interim plumbing with a finite life. Rooms without either source
      keep running on the return-temperature fallback.


### Raised in discussion, not yet scheduled

- [~] ~~Seasonal lockout for `auto_mode`~~ - **PROPOSED AND REJECTED**
      (owner, 2026-07-27): this site has seen below freezing in August, so an
      outdoor-temperature guard would refuse heating exactly when a freak cold
      snap needed it. The house average is the right signal precisely because
      it does not care what month it is. Kept here rather than deleted so the
      idea is not re-proposed. If a transient (an evening of ventilation) does
      cause a spurious switch, the lever is a LONGER DWELL, not a lockout -
      currently one hour, see D-020.
- [ ] **Source-side last resort when safety costs us flow.** The distribution
      design guarantees flow only for the CONTROL proposal; `Safety.apply` runs
      afterwards and may close circuits for condensation or screed overtemp. If
      it closes enough of them, flow is genuinely lost and the correct
      escalation is to stop the unit - the one place "measure of last resort"
      actually applies. Currently unimplemented: safety can starve the pump and
      nothing notices.
- [ ] **Characterise the actuator, per TYPE not per valve.** Wanted:
      `open_threshold_pct`, `settling_time_s`, and confirmation of
      `full_open_pct`. Sequence, cheapest first:
      (a) read the Alpha 5 datasheet for the voltage-to-position control range
      - the top end is a device property and this is the only reliable source
      for it (D-021);
      (b) fit `open_threshold_pct` and `settling_time_s` PASSIVELY from logged
      data (docs/DESIGN.md 7.3). No experiment, no disruption, and the
      distribution design already sweeps each circuit's full range in normal
      operation because the peak rotates between rooms;
      (c) only if something is still missing, a dedicated sweep - watching the
      HEAT PUMP's leaving/return spread rather than circuit RL, which saturates
      early (D-021). Needs heating season for thermal contrast, and expect
      cross-talk between circuits on the shared manifold.
      **Do not lower `full_open_pct` from 100 without strong evidence** - the
      error is asymmetric and too-low throws away flow (D-021).
      Blocked on: actuators being fitted (only 2 of 12 today).
- [ ] **Tune `distribution.eps`.** The flow/discrimination trade-off, currently
      a guess at 5.0. First thing to revisit once there is recorded data - see
      the evaluation checklist in docs/DESIGN.md 4.5.
- [ ] **A decision log.** Several decisions have now been reversed - register 0
      bit 0 is power not the water pump, the condensation guard scoped back to
      cooling, the source stays on rather than tracking demand, the valve
      mapping is 1:1, InfluxDB was recording all along. Those reversals live
      only in commit messages, which is the least discoverable place in a
      project whose premise is thirty years. The rationale is well recorded at
      the point of use; the *history* is not.
- [ ] **Retire the legacy Controme Mini Server.** Everything still depending on
      it is now enumerated in docs/HA_INTEGRATION.md: the two wall units' room
      temperature and dial setpoints, the humidity feeding the dew-point
      reference, and the HomeKit bridge. Shelly H&T per room is the long-term
      replacement (Milestone 1).


### Milestone 2 - DHW station (fresh water) fast loop

- [ ] Flow sensor with pulse output on a digital input (16DI terminal,
      discrete inputs FC2) - hardware addition
- [ ] Feed-forward: pump speed (0-10V, spare 750-559 channel) as a
      function of flow; temperature PID only trims
- [ ] Separate asyncio task at 100 ms using modbus_direct ONLY;
      temperatures stay at 1 s (750-463 limit)


### Milestone 3 - layer 2 (`optimizer/`, separate process/container)

- [ ] System identification from heatctl.sqlite: fit step responses per
      room/circuit (first/second-order models, scipy.optimize), report
      time constants
- [ ] Weather forecast (Open-Meteo, no API key) + PV forecast
- [ ] Heuristic v1 (no MPC): rule-based setpoint shifting, e.g. "PV surplus
      expected in <4 h and buffer < X -> postpone buffer charging"
- [ ] MPC v2 optional (cvxpy), only after v1 runs and models are validated
- [ ] Everything via `heatctl/set/setpoint/<room>` and `heatctl/set/mode`


### Milestone 4 - production

- [ ] Dedicated machine next to the coupler: mosquitto + modbus2mqtt +
      heatctl via systemd (deploy/systemd/), hardware watchdog,
      consider read-only rootfs
- [ ] HA: bridge HA-Mosquitto <-> dedicated broker; remove WAGO-related
      HA modbus config and automations
- [ ] Backup: config.yaml + sqlite; vendor dependencies (pip download)
      for long-term reproducibility
- [ ] Keep docs/HARDWARE.md current: every terminal, wire and register

