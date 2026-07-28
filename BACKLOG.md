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
- [ ] **heatctl has no window-open input, and there are no window sensors in
      HA at all** (checked 2026-07-28: no matching entities). Observed live
      when the owner ventilated Wohnzimmer at ~07:10 with 13 degC outside
      against 26 degC inside.
      MEASURED, and it corrected the prediction that was written here first.
      The predicted failure was churn - sensor dives, demand collapses,
      circuit throttles off 100 %, setpoint trim reverses. NONE of that
      happened. Wohnzimmer peaked at 26.00 at 07:11:16 and then fell only to
      25.50 by 07:28, i.e. the window turned +0.074 K/min into -0.042 K/min
      and by 07:29 was already decelerating back toward zero as the sun
      climbed. Peak circuit demand went the OTHER way from the prediction,
      58 -> 92 straight through the window opening, hk02 stayed pinned at
      100 %, and the setpoint trim continued down to 19.0. Control never saw
      an artefact because the room stayed ~2.5 K above setpoint the whole
      time: heatctl reacts to the GAP, and ventilation only shaved the ramp.
      So the churn scenario is real but narrower than stated: it needs
      ventilation to DOMINATE, i.e. a mild day and a room near setpoint, not
      a room under heavy solar load. CAUTION on the capacity figure first
      recorded here (0.12 K/min): the baseline was contaminated and it is
      VOID. The owner pointed out that direct sun was on the WALL the sensor
      is mounted on until ~07:36, so the 25.5 plateau was partly radiant wall
      temperature, not room air. Once the sun moved off, the reading fell
      25.50 -> 24.44 in 8 minutes, **-0.13 K/min**, three times the earlier
      apparent rate. Treat -0.13 K/min as a LOWER BOUND on ventilation
      capacity at a 13 K difference, and treat the first minutes of that
      decay as partly the sensor re-equilibrating rather than the room
      cooling - watch where it flattens to get the real air temperature.
      Second, independent reason the Shelly H&T migration matters: a wall
      unit on a sunlit wall reports the wall. Whatever replaces it needs a
      PLACEMENT rule, not just a protocol.
      Cheapest fix is not a control change: a contact sensor per ventilated
      room, published like any other input, and a per-room "suspend" that
      parks the circuit rather than driving it. Note this is a SUSPEND, not
      an off - safety (frost, dew point) must keep running on that room, so
      it cannot be implemented by masking the room out of the demand set.
      Until then it is a known, benign inefficiency, not a defect.
      Related but distinct from the dew-point angle. Careful with this one -
      the house REFERENCE was 12.5 against 12.1 outdoors, so ventilating
      lowered the aggregate. But Wohnzimmer itself was DRIER than outside
      (dew point ~11.2), so its own dew point rose toward 12.1 - 11.2 to
      11.6 in the first 18 minutes. Per-room dew point is what threatens a
      per-room cold circuit, so a house-wide reference can be reassuring and
      wrong at the same time; worth checking whether the guard should track
      the worst room rather than the reference. That will not hold on a muggy day, and then
      opening a window while cooling is genuinely hazardous - the guard is
      `Safety.apply`, which sees the dew point rise and forces closed, but
      only after the fact. Worth a look when the contact sensors go in.

- [!] **Measure the hydronic flow rate - it now gates every energy balance.**
      Highest-value missing instrument, promoted 2026-07-28 after the first
      model validation. The overnight mass estimate came out at 13,700-18,600
      Wh/K, and that whole spread is driven by the ASSUMED flow (0.8-1.5 m3/h)
      feeding the delivered-cooling term, which is about a third of the
      balance. Everything downstream - slab capacity, envelope loss, COP,
      whether the plant can meet a design day - inherits that uncertainty.
      **Note flow does NOT require pipe surface area** - that only enters the
      water-to-slab conductance `UA_ws`, which is downstream and separately
      identifiable once flow is known. Three routes, none needing it:
      (a) **TRANSIT TIME - free, today, no new hardware.** Let one circuit
          stagnate, command it fully open, and time the thermal front reaching
          its own return sensor: `t = V_circuit / Q_circuit`. Needs pipe
          INTERNAL VOLUME (length x bore), both specifiable - length from area
          / spacing off the floor plan, bore from the pipe spec. Take the 50 %
          rise point; axial dispersion and slab exchange smear the front, so
          expect ~20 %. **`rl_gate.py`'s FLUSH already performs exactly this
          manoeuvre** - the data may be in the logs already.
      (b) ~~RESISTIVE CALORIMETRY~~ and (c) ~~BUFFER AS CALORIMETER~~ are both
          **BLOCKED for now** (owner, 2026-07-28): the tank is not online yet
          and the 8 kW element sits *in the tank*. Revisit both when it is
          commissioned - they are the accurate routes, and the element is a
          100 %-efficient reference needing no geometry at all.
      **Datasheet narrows it meanwhile.** The BLP08P1V1MR32 specifies water
      flow **min 0.16 / max 0.40 l/s** (0.58-1.44 m3/h). With `dc_pump_speed`
      observed at 90-100 % we are near the top: **1.2-1.44 m3/h**. Re-running
      the overnight balance on that narrower range gives a building capacity of
      **15,700-18,300 Wh/K**, tightening the earlier 13,700-18,600 and landing
      it on the as-built + partition figure. So the flow gap is now a
      refinement rather than a blocker - but see the dT item, which is not.
      **Check the manifold for built-in Durchflussmesser FIRST.** Floor-heating
      manifolds commonly carry per-circuit float topmeters (0.5-5 L/min) for
      hydraulic balancing. If ours has them, total flow is readable by eye for
      free right now - and they are the balancing instrument we will want
      anyway once more actuators are fitted.

- [ ] **Our dT resolution limits energy measurement independently of flow.**
      Worth knowing before buying a bare flow sensor. The PT1000 chain
      quantises to 0.1 K, and the overnight manifold spread was 0.10-1.01 K -
      so dT alone carries 10-100 % error at low load, and no flow figure
      however good repairs that. Consequence for procurement: a proper
      **Waermemengenzaehler** (heat meter, M-Bus or Modbus) with its own
      matched sensor pair closes flow, energy AND dT in one purchase, and is
      what COP monitoring needs regardless. A bare flow meter fixes one of the
      three.

- [ ] **Heat-meter placement decides WHICH question it answers** (owner raised
      the stove problem, 2026-07-28). A Waermemengenzaehler sees only the
      HYDRONIC share, so once the water-jacketed wood stove is online its
      direct radiant and convective output to the room is invisible to the
      meter. That is real, but it is not an argument against the meter - it is
      an argument about placement, and for the estimator:
      * **On the heat pump's own circuit** it measures the heat pump cleanly
        whatever the stove does. This is the placement for COP and for flow
        calibration - the two things we actually lack.
      * **On the manifold feed** it measures energy into the slab, correctly
        summing stove and heat pump water contributions, but cannot separate
        them.
      * The stove's DIRECT share stays unmeasured either way, which is exactly
        how docs/DESIGN.md 6.4 already models it - a pure disturbance. With a
        metered hydronic side and a validated building model, that direct share
        becomes the *residual*, i.e. observable rather than unknown. The stove
        makes the estimator more valuable, not the meter less.
      Recommend: heat pump circuit first, since it closes flow, energy, dT and
      COP together, and the stove is not yet online to confound anything.

- [ ] **`hp_power_estimate` is not usable for COP, and can be improved cheaply.**
      It is `compressor_current x 230 V` (heatctl/main.py), inherited from the
      retired HA template, and its docstring is honest that it is not metered.
      But the device also reports `dc_bus_voltage` (0x8021), reading **374 V**
      while we assume 230 - so the assumed voltage is not even the bus the
      current is measured on.
      **RESOLVE IT WITH THE UTILITY SHELLY** (owner, 2026-07-28) - this is the
      clean answer and needs no new hardware. There is a Shelly metering the
      house's grid connection, so correlate its power step against the step in
      `0x8025` each time the compressor starts, stops or changes frequency.
      The compressor is by far the largest switched load, so the regression
      slope is direct: **~230 W/A means 0x8025 is mains current** and the
      present estimate is roughly right; a slope near 374 W/A means DC link;
      anything much lower means inverter output current. The intercept also
      hands us the fan + pump + controls overhead the estimate currently omits.
      Do this before deriving COP - and it yields real measured electrical
      power for the heat pump as a by-product, which is half of COP anyway.
      Narrowing from the owner: **10 A has been observed**, which rules out the
      DC-link reading (bracketed 5-7 A at full output) but does not separate
      mains from inverter output, since 10 A may not have been at full load.
      Datasheet bound for reference: mains current maxes at 16.5 A.
      Fans (80 W), circulation pump and controls are excluded either way; the
      datasheet's own input range at the relevant duty point is 380-2600 W,
      which bounds any sanity check.

- [ ] **Phase-2 model priors are now extracted; two gaps remain.** The EnEV
      Waermeschutznachweis and the Bauantrag drawings have been mined into
      `docs/BUILDING.local.md` (git-excluded - the data identifies the site):
      envelope areas and U-values, loss coefficients, per-element thermal
      mass, room areas, the full window inventory, and the design flow/return.
      Three as-built corrections from the owner are folded in, and they all
      point the same way - **U-values survive, thermal masses do not**, so the
      certificate's annual-energy figures are usable and its dynamics are not.
      The floor slab alone is 36 % heavier than the certificate says.
      STILL MISSING, both needed before the per-room model means anything:
      (a) **Internal partition area.** 9 cm solid wood, so 1.05 W/(m2K)
          room-to-room and 20 Wh/(m2K) of shared mass, but the AREA is in no
          document we hold. Plausibly 4,000-6,000 Wh/K, i.e. comparable to all
          external walls and roof combined. Measure it off the floor plans.
      (b) **Pipe depth within the 10 cm screed.** Sets the split between mass
          above the pipes (couples to the room, fast) and below (dead weight).
          The 3-state RC model in docs/DESIGN.md 6.1 needs it.

- [ ] **Add per-facade solar forecast planes - API contract now confirmed.**
      HA's solar forecast is a client for the public **Forecast.Solar** HTTP
      API, which takes arbitrary planes, so we can query the WINDOW facades
      instead of borrowing the roof PV planes:
      `GET https://api.forecast.solar/estimate/{lat}/{lon}/{declination}/{azimuth}/{kwp}`
      - no API key; **12 requests/hour per IP**, today + tomorrow, hourly
      - `declination: 90` for a vertical wall; `kwp` is a pure linear scaler
      - **AZIMUTH TRAP: the raw API uses 0 = SOUTH (-180..180), while HA's
        config flow uses 0 = NORTH.** They differ by 180, and getting it wrong
        points every plane at its exact opposite - which yields a plausible
        curve peaking at the wrong time, not an error.
      Recipe: one plane per facade, `kwp` = that facade's effective collector
      area, so the returned watts come out directly as solar heat gain in watts
      within one per-facade calibration factor of order 1.0 - which the
      estimator should identify rather than us deriving it.
      VERIFIED against today's data (2026-07-28): the ESE facade peaks at
      **08:00** and is at 76 % of peak by 07:00, exactly matching both the
      sun-position calculation and the observed Wohnzimmer ramp. It carries
      2,181 Wh/kWp today against the SSW facade's 1,426, and the two are nearly
      complementary - ESE owns the morning, SSW the afternoon, crossover about
      12:00. Full tables in `docs/BUILDING.local.md`.
      Why the existing PV planes will not do: both are configured south
      (185/17 and 180/25), so they understate the east facade by 1.7-4.5x
      through the morning and overstate it by ~4x in the afternoon. Wrong in
      both directions at the worst times, and not fixable with one coefficient.

- [ ] **SUPERSEDED by the item above - kept for the measurement.** Reconfigure
      the HA solar forecast per facade, with the MEASURED azimuths.** The building is rotated 16.3 degrees from cardinal (measured
      off the compass rose and building grid on the Bauantrag ground-floor
      plan, see `docs/BUILDING.local.md`). Configuring a forecast with the
      drawings' nominal N/E/S/W labels puts every plane 16 degrees out, which
      is 60-70 minutes of error on when each facade's gain peaks - and peak
      timing is the whole point, since the planner has to pre-cool BEFORE the
      gain arrives. Give the service the true azimuths and 90 degree tilt, one
      plane per facade, scaled by the effective collector areas already
      tabulated. Then the east plane becomes a direct predictor for the room
      that actually has the problem.

- [ ] **Watch the 2026-07-30 heat event (36 degC, forecast dew point 9) - it
      is the first time the plant runs AT the condensation constraint all
      day.** Predicted chain: safety limit = 9 + 2 = **11 degC** supply, and
      load compensation can drive the heat pump's return-water setpoint down
      to `water_setpoint.cooling_min_c: 14.0`, which at the spreads seen so
      far lands supply at roughly 10-11 - i.e. on the limit, not below it.
      So the day is a test of two things at once, both currently UNDEPLOYED:
      D-024 supplies the extra 1 K of headroom that the old floor would have
      eaten, and D-023's release hysteresis is what stops the valves flapping
      against the limit for hours. Deploy both before it.
      What to check on the day: whether supply actually reaches ~11 or
      whether `cooling_min_c` binds first (if it binds, that bound is a
      control-layer choice and can be lowered - it is not a safety limit);
      how often the guard trips with hysteresis in place; and whether a 2.0 K
      margin still looks right at the dry end, where it is a much larger
      fraction of the available headroom than it is at dew point 15.

- [!] **The dew-point template falls back to the OUTDOOR dew point, and
      nothing bounds that any more.** Found 2026-07-28 while removing the
      12 degC floor (D-024), which had been accidentally capping the damage.
      `sensor.system_dew_point_reference` takes the max over four indoor
      temperature/humidity pairs and, if none is valid, **substitutes
      `sensor.fineoffset_wh65b_210_dew_point` - an OUTDOOR sensor.**
      Two reasons this is wrong:
      (a) It contradicts config.yaml's own warning under `dew_point_topic`,
          which says in as many words not to point this at an outdoor dew
          point. The comment only anticipated outdoor being too HIGH
          (needlessly forbidding safe cooling); the dangerous direction is
          outdoor being too LOW - a cold dry day gives a plausible, fresh,
          authoritative and badly wrong limit.
      (b) It defeats D-010. `cooling_requires_dew_point` exists so that
          "we do not know the humidity" means "stop cooling". A fallback that
          always produces a number means heatctl can never reach that state,
          so the designed safe degradation is unreachable from the plant.
      Correlated-failure risk is real, not theoretical: three of the four
      pairs are Controme room controllers reaching HA through the single
      legacy Mini Server, so one host dying invalidates three at once.
      FIX: delete the fallback and let the template go unavailable. heatctl
      then stops cooling by itself, which is the whole point of D-010. The
      template lives in HA, not in git - see docs/HA_INTEGRATION.md.
      Consider also a plausibility gate INSIDE heatctl (reject a dew point
      above room temperature, or wildly out of band), because layer 1 is not
      supposed to depend on an HA template being correct.

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

- [x] **FIXED 2026-07-28 (D-023), not yet deployed.** Release-only hysteresis,
      `safety.dew_point_release_margin_c: 0.3`. Root cause was NOT what the
      first report here claimed: every transition is explained exactly by
      `vl < limit` on two independently 0.1-K-quantised signals, and the
      16 s reopen came from the DEW POINT ticking 12.5 -> 12.4, not from
      supply noise and not from any inconsistency. Frequency was also
      overstated - 4 trips in 9.7 h, one sub-stroke, rather than chatter.
      Original report, kept because the trace is the evidence:
  **The below-dew-point cooling limit has NO hysteresis - observed on a
      fitted actuator 2026-07-28 07:32.** Raised from "worth
      doing" to the top of the list because the predicted failure happened.
      hk02 (Wohnzimmer, `fitted: true`) was commanded 100 -> 0 -> 100 -> 0 in
      **27 seconds**, against a 150 s full stroke (D-022): three commanded
      full reversals inside a fifth of one stroke time. The valve cannot have
      tracked any of it, so its actual position is now unknown - precisely
      the state the design exists to avoid.
      Trip points, against a limit of 14.5 (dew 12.5 + 2.0): forced closed at
      supply 14.4 (07:32:18), released at 14.4 (07:32:34), closed again at
      14.3 (07:32:45), released at 14.4 (07:35:22).
      NOTE the second transition: it released while supply was still BELOW
      the limit. That is not zero hysteresis, that is inconsistent, and it
      means the trip input is moving too - most likely the dew-point
      reference itself dithering, or the guard reading a different supply
      quantity than the published `supply_total`. Establish which BEFORE
      adding hysteresis, or the deadband will be tuned against the wrong
      signal.
      Earlier and milder observation of the same thing, 2026-07-27 23:19-23:23: supply fell through
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
          ANSWERED 2026-07-28 07:10:42: it is authorised and not clamped.
          It made its first trim, 20.0 -> 19.0 degC, as soon as the morning
          solar load pushed house deviation past `deviation_band_c`. It had
          simply had no reason to move before. The remaining question is
          only whether 1 K / 30 min is fast enough - see the solar item.
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

