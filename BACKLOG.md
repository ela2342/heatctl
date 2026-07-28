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
- [ ] **Underfloor cooling cannot track solar gain - measured 2026-07-28.**
      First clean observation of the limit, worth keeping as a reference
      trace. Wohnzimmer has large glazing; at sunrise its air went
      **22.1 -> 25.6 degC in 44 minutes** (06:21-07:05), smooth and linear at
      ~0.1 K/min. Over the same window that room's own slab circuits went the
      OTHER way: circuit 8 20.6 -> 18.6, circuit 9 20.6 -> 19.6, circuit 10
      20.4 -> 18.9. (Those three are open pipe, so flow was constant; part of
      the fall is supply falling, so treat the magnitude as indicative, not
      as a calibrated room-temperature proxy.)
      The point is the time constants, and they are far apart: solar gain
      through glass loads the air in minutes, the slab responds over hours.
      Control did the right thing - Wohnzimmer became peak demand, hk02 went
      to 100 %, Gaestebad throttled to 6 % - and it will still lose the race,
      because by the time the slab is cold the sun has moved on.
      Implication, and it is a design one rather than a tuning one: this load
      can only be met by ANTICIPATION, i.e. pre-cooling the slab before the
      sun arrives. That is the concrete case for the layer-2 planner
      (docs/DESIGN.md, WP-H) and it needs a solar forecast, not a faster
      loop. No amount of PID tuning in layer 1 fixes it.
      Worth checking when the planner is built: whether overnight setpoints
      should be biased DOWN on rooms with big glazing ahead of a sunny
      morning, and how that trades against the condensation floor, which was
      already binding all night (supply minima 14.7-15.2 against a limit of
      14.3-14.7).

- [ ] **Per-channel step test when fitting each actuator** - confirms fitment
      AND mapping in one move, and costs one command step. Discovered by
      accident 2026-07-27 while checking whether hk11 had an actuator.
      Procedure: command channel n hard closed for ~5 min while the plant is
      running with a spread, and watch `return_circuit_n`.
        * ACTUATOR FITTED: flow stops, so the manifold-mounted return sensor
          stops seeing its circuit and drifts UP toward header/cabinet
          temperature - the stagnation signature rl_gate.py exists for. Clear
          inflection within a couple of minutes.
        * NOT FITTED (open pipe): the return keeps tracking supply with its
          usual lag, straight through both edges, no inflection. This is what
          hk11 did at 23:19:21 and 23:22:11 - the reason `fitted: false` is
          corroborated by physics and not just by the flag.
        * WRONG CHANNEL: a DIFFERENT circuit's return inflects. This is the
          only cheap check that catches the index-shift class of bug (the one
          that had the Arbeitszimmer PID driving circuit 7 until 2026-07-27),
          and it catches it before the actuator is trusted rather than after.
      Do it per channel as each actuator goes in, and flip `fitted: true` only
      once the step test passes - not when the hardware is screwed on.

- [ ] **The below-dew-point cooling limit has NO hysteresis, and it visibly
      limit-cycles.** Observed live 2026-07-27 23:19-23:23: supply fell through
      the limit (15.4 = dew 13.4 + 2.0), safety forced hk11 to 0, supply
      recovered, hk11 went back to 100 at 15.4 - closed at 15.3, reopened at
      15.4. Safety behaved exactly as designed (fail CLOSED on known-bad
      supply, D-011) and the house never moved, so this is not a defect and
      not urgent. But two things follow:
      (a) A 0.1 K band on a 150 s actuator (D-022) means a valve can be
          commanded 0 -> 100 -> 0 without ever completing travel, so its real
          position becomes unknown - the one state the whole design tries to
          avoid. Wants a deadband on the RELEASE edge (reopen at limit + h),
          not on the trip edge, which must stay immediate.
      (b) The cycle is driven by the unit undershooting: it targets 20 degC
          RETURN water, return sits at ~20.3, so it keeps driving and leaving
          water goes to ~14. Load compensation (D-018) is the right lever;
          check whether it is actually authorised to raise the cooling
          setpoint here, or whether it is sitting at a clamp.
      Also worth remembering when reading these traces: only circuits 1 and 2
      have actuators fitted, so forcing hk11 closed changes almost no real
      flow. Most of the observed recovery is the heat pump's own modulation,
      not our valve action.

- [~] **Actuator characterisation - LARGELY SETTLED from the datasheet
      (2026-07-27, D-022).** The valves are Moehlenhoff Alpha 5
      `APV 42505-00`, and the APV variant has valve-travel detection: it
      measures its own stroke and auto-adapts the active control-voltage
      range, regulating internally for maximum stroke minus over-travel. So
      the upper deadband the owner suspected is real but the DEVICE
      compensates for it - `full_open_pct: 100` is correct physically, not
      just the safe default. `open_threshold_pct: 5.0` comes from Umin
      (0-0.5 V ignored to reject cable hum), and 30 s/mm x 5.0 mm = 150 s
      full stroke confirms `rl_gating.settle_s: 300` has margin.
      REMAINING, and much smaller than the original item: confirm on the real
      plant once more actuators are fitted that the mapping behaves as the
      datasheet says - a valve commanded 5 % should just begin to move, and
      one commanded 100 % should be at its stop. Passive identification from
      logged data (docs/DESIGN.md 7.3) is sufficient; no dedicated sweep.
      Also worth knowing during build-out: a NEWLY fitted NC actuator holds
      its valve OPEN via the First-Open function until it has determined its
      closing point, regardless of what heatctl commands. Expect it; it is
      not a fault.
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

