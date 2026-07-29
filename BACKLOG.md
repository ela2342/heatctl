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

- [x] **DONE 2026-07-28 (D-025), shipped in 0.13.0.** `min_open_pct` was
      documented, configured, and NEVER ENFORCED - it would have gone
      live the moment the actuators were fitted.** Found 2026-07-28 after the
      owner closed every valve but circuit 11 and got an **instant Er03**
      (water flow, bit 0 of 0x8008).
      `demand.py` reads `min_open_pct: 40.0` and its own docstring is explicit
      about what it is for - *"a constraint on how far heatctl may throttle - a
      reason to hold valves OPEN"*, naming Er03 by name. But `open_pct()` is
      only ever used to build a status string and publish telemetry. **Nothing
      clamps the valve outputs.** Grep confirms: no reference in `main.py` or
      `distribution.py` beyond publishing it.
      **Why it has never bitten:** 8 of the 10 water-carrying circuits are open
      pipe and count as 100 %, so the mean opening cannot currently fall below
      **80 %**. The floor is unreachable. Once all actuators are fitted,
      distribution can drive every circuit to `open_threshold_pct` = **5 %**,
      far below the 40 % floor - and per the owner's experiment the unit faults
      out immediately. That is a self-inflicted plant shutdown, in the hour
      when the house most needs cooling, caused by heatctl's own output.
      **PROPOSED FIX** (small, and the same principle as D-017): after
      distribution, if the mean opening is below `min_open_pct`, scale ALL
      openings up by one common factor until the mean reaches the floor,
      clipping at 100. That preserves the relative proportions exactly - it is
      D-017's normalisation applied at the bottom end instead of the top - and
      it is the correct response anyway, because low flow is a reason to open
      valves, not to throttle further. Needs a test asserting the direction:
      too little flow must OPEN valves, never close them.
      Sequencing note: it must run BEFORE safety, so that a frost or dew-point
      override still wins. Safety closing circuits can itself starve flow, and
      that case is genuinely a source problem, not a valve problem - see the
      existing "source-side last resort when safety costs flow" item.

- [ ] **Derive the flow floor from the datasheet instead of a rule of thumb.**
      The 40 % `min_open_pct` is the owner's estimate, and the datasheet turns
      out to agree exactly - the BLP08P1V1MR32 wants **0.16-0.40 l/s**, and
      0.16/0.40 = **40 %**. Tempting, but it is only agreement if BOTH hold:
      (a) flow is linear in mean valve opening - it is not, strictly: parallel
          branches sum conductance, the valve characteristic is not linear, and
          a fixed-speed pump moves up its curve as circuits close, so flow
          falls LESS than proportionally (which errs safe);
      (b) all-valves-open actually reaches 0.40 l/s. **This is the real risk
          and it is unmeasured.** If this system's loop resistance means the
          pump tops out at 0.30 l/s, Er03 sits at 53 % of achievable flow and a
          40 % floor is too low:
            all-open 0.40 l/s -> floor 40 % (x1.25 margin: 50 %)
            all-open 0.35      -> 46 %  (57 %)
            all-open 0.30      -> 53 %  (67 %)
            all-open 0.25      -> 64 %  (80 %)
      So: keep 40 % as the interim, but the correct fix is to express the limit
      in **l/s** and measure our actual maximum. Until then treat 40 % as a
      lower bound on the floor, not a calibrated value.

- [ ] **Nothing checks the flow MAXIMUM, and D-017 pushes toward it.** The
      datasheet gives 0.40 l/s as a maximum, not just a design point, and
      D-017's whole principle is "normalise so the most-demanding circuit is
      fully open" - i.e. deliberately maximise flow. With `dc_pump_speed`
      observed at 100 % and every circuit open, nothing establishes that we
      stay under it. Probably fine, since the pump is internal to the monoblock
      and the manufacturer sized it - but that is an assumption, not a check.
      Resolve with the same flow measurement.

- [ ] **The Er03 flow switch is a free single-point flow calibration.** It trips
      at the unit's minimum, spec'd 0.16 l/s. So the valve configuration at
      which it *just* trips tells us the flow through that configuration -
      an absolute anchor for the pump-curve model we otherwise have no way to
      pin. Combine with `dc_pump_speed` and the commanded openings. Do it
      deliberately and briefly, not by accident, and only once the actuators
      are in; tripping a flow failsafe repeatedly is not free wear-wise.

- [!] **auto_mode heated the house in July, for correct reasons. 2026-07-29.**
      First time `auto_mode` (D-020) has ever flipped the plant, and it flipped
      the wrong way half an hour before sunrise. Sequence:
        * compressor OFF from ~23:00, mean 0.00 Hz through to 05:00 - the plant
          was not cooling at all. The house lost ~0.65 K to an 11-13 degC night
          through the envelope (~2.3 kW against H_total 267 W/K).
        * the water-setpoint loop walked the cooling setpoint 19 -> 25 and
          **hit `cooling_max_c` at 02:00**, then sat saturated for four hours.
          Raising a cooling setpoint cannot stop passive envelope loss; in
          cooling mode there is no actuator for "stop losing heat".
        * 05:56 the house average reached 1.10 K cold, clearing
          `mode_deadband_c: 1.0` and `mode_dwell_s: 3600` -> switched to HEATING.
        * 06:37 raised the heating setpoint 25 -> 26; supply peaked at 30.1
          degC and charged the slab, immediately before ~20 kWh of morning sun
          arrived through the east facade. Wohnzimmer reached 26.4 against a
          23.0 target. Owner had it flipped back manually at 07:39.
      **Every step was correct on the information available.** The gap is
      anticipation - the same one as the 2026-07-28 solar item, now biting in
      the opposite and more expensive direction: yesterday we merely failed to
      pre-cool, today we actively charged the slab before the load arrived.
      THREE separate fixes, in increasing order of ambition:
      (a) **Cheapest and available now: use setpoint-loop saturation as an
          early warning.** The loop hit its clamp at 02:00 - nearly four hours
          before the mode flip. A saturated compensation loop means the mode is
          probably wrong, and it is a local signal needing no forecast. At
          minimum it should be published and alarmed; arguably it should damp
          the mode switch rather than accelerate it.
      (b) **`off` was probably the right answer at 05:56, not `heating`.**
          Turning the plant off does not stop envelope loss either, but it does
          not charge the slab. Check whether `demand.py` can ever choose `off`
          as the plant mode, or only heating/cooling - and whether it should.
      (c) **Forecast-aware mode switching** (docs/DESIGN.md WP-H). A planner
          holding the east-facade solar forecast would never have started
          heating at 05:56. This is the same planner the solar item needs.
      **And the structural problem underneath, which no mode logic fixes:**
      Gaestebad wanted heat (22.3 vs 23.5) while Wohnzimmer wanted cooling
      (26.4 vs 23.0) AT THE SAME TIME, on one water temperature. Distribution
      can share energy between rooms; it cannot reverse its sign. That is an
      argument for the fan coil's independence, and eventually for a mixing
      circuit - see the latent-lever item.

- [!] **The condensation guard is BLIND to showers - measured 2026-07-28.**
      The owner showered in Gaestebad in the morning and asked whether it
      showed up. It did not, anywhere. `sensor.luftfeuchte_gastebad` stayed
      inside **46.4-50.3 % RH for the whole of 06:30-12:00**, with no spike at
      any point, and the derived `system_dew_point_reference` drifted
      *downward* 12.6 -> 12.0 across the same window. A shower in a 3.4 m2
      bathroom should drive RH to 80-95 % and the local dew point to 18-22 degC
      within minutes.
      The sensor is alive and behaving - RH falls correctly when the room warms
      (08:15-08:22), so it tracks temperature - it simply never saw the
      moisture. Most likely heavy damping in the Controme RC firmware, or the
      wall unit sits outside the plume, or extraction clears it faster than the
      ~60 s reporting interval resolves.
      **Why this matters:** `system_dew_point_reference` is the MAX over four
      rooms and it is the sole input to the cooling condensation limit. If the
      bathroom sensor cannot see a shower, the guard is blind to the largest
      and most abrupt indoor moisture source in the house - and Gaestebad is
      circuit 1, one of only two with an actuator fitted.
      It did not bite today: dew point ~12 against a supply of 14-20, so metres
      of margin. It would bite on a humid day with supply already at the limit.
      The 2.0 K margin absorbs some of this, which is an argument for deriving
      it properly rather than shrinking it.
      FIX candidates: a fast, well-placed humidity sensor in the bathroom (the
      Shelly H&T migration is the natural vehicle - pick the position for the
      plume, not for tidiness); and/or treat bathroom circuits conservatively
      on a humidity *rate* trigger or occupancy. Note no control change helps
      until a sensor can actually see the event.

- [ ] **Adapt control to circuit 11 being a FAN CONVECTOR, not floor heating**
      (owner, 2026-07-28; details in docs/HARDWARE.md). Same loop, same valve
      channel, entirely different plant. Ordered by when it starts to matter:
      (a) **Condensate drain: a TEMPORARY one is installed** (owner,
          2026-07-28), and making it permanent is under consideration. Note it
          is necessary but nowhere near sufficient for the latent lever below -
          the hydraulics are the real blocker. For the guard question: if a
          permanent drain exists,
          the `vl_undertemp` guard is not just over-conservative for that
          circuit but counter-productive - letting the coil run wet would lower
          the house dew point and buy headroom for every slab circuit. If it
          does not, the guard is essential there. **Do not exempt on
          assumption.**
      (b) `rl_gating.settle_s` must become per-circuit before an actuator is
          fitted to 11. 300 s is slab transport time; a convector responds in
          tens of seconds.
      (c) The return-temperature PID on circuit 11 is tuned for slab dynamics.
      (d) Distribution maps demand -> opening identically for every circuit; a
          convector's characteristic is different and has a second input (fan
          speed) heatctl cannot see or command.
      (e) Room model: Arbeitszimmer is single-state, not room+slab.
      **Rated 4.2 kW cooling / 4.3 kW heating** (owner, 2026-07-28). Total
      emitter capacity is therefore 7.6-9.0 kW against a heat pump good for
      ~5.7 kW, so **we are source-limited, not emitter-limited** - reversing
      the earlier conclusion.
      **And there is a real strategy in the surplus.** 4.2 kW over 31.20 m2 is
      135 W/m2; the room cannot absorb it. But a wet coil dehumidifies, the
      guard is `dew point + 2.0`, and so every 1 K of house dew point removed
      is 1 K more supply headroom for all ten slab circuits - about 1 kW of
      extra slab capacity. Holding the house 2 K below outdoor dew point costs
      only 0.36 kW latent at n=0.7, i.e. the coil at 25-34 % duty, whose
      0.67-1.09 kW sensible byproduct is roughly Arbeitszimmer's own load
      anyway. Net gain on the order of +1 kW, landed on the slab where it is
      needed. Numbers and caveats in docs/HARDWARE.md.
      **BUT NOT ON TODAY'S HYDRAULICS** (owner's correction, 2026-07-28, and
      it is right). The lever needs the coil to see ~8-11 degC water, several K
      below the slab's 14.5 limit, and all eleven circuits share one supply
      header - so there is no way to feed the coil cold without sending the
      same water to the slab. "Close the slab circuits" does not rescue it:
      only circuits 1 and 2 have actuators, the other seven are open pipe and
      cannot be closed, so cold water would reach the slab and condense inside
      it invisibly. Requires, in order: a separate low-temperature branch with
      the slab behind a 3-way mixing valve (already in docs/DESIGN.md 1.2 - the
      current H_DIRECT wiring is the interim that lacks it); all twelve
      actuators fitted; and the temporary condensate drain made permanent.
      **Also costs EER, which I had not counted:** with one source, running
      cold for the coil means making cold water for everything and mixing back
      up for the slab. Dropping leaving water 14 -> 9 degC moves EER ~2.66 ->
      ~2.25, **+18 % electrical for the same cooling** - about 0.4 kW to buy
      the 1 kW. So it is a **peak-shaving move for capacity-constrained hours
      on hydraulics we do not yet have**, not a default mode, and a bad trade
      on an ordinary day.
      Still true: per-circuit guard scoping is the enabler, and the latent path
      is the only route by which the coil's surplus reaches the rest of the
      house - sensible cooling stays stuck in Arbeitszimmer.

- [ ] **Stop treating `heatctl_outdoor_ambient` as air temperature.** Measured
      2026-07-28: the heat pump's own sensor peaked at **36.5 degC** while two
      independent Fine Offset station sensors agreed on **25.1** in the same
      hour - **+11 K**. Solar loading on the outdoor unit's casing plus its own
      discharge recirculating. Overnight the two agree within ~0.7 K, so it is
      a daytime insolation error, not an offset. Keep publishing it (it is the
      right signal for the MACHINE's operating point - defrost, derating, the
      vendor COP tables), but rename it so nobody mistakes it, and point any
      weather compensation, degree-day or COP-vs-ambient work at
      `sensor.fineoffset_wh65b_210_t`. See docs/HEATPUMP.md.

- [ ] **Two geometry take-offs the model needs, both from the Bauantrag plans.**
      docs/DESIGN.md 6.1 was rewritten 2026-07-28 against the building survey;
      these are what it still lacks.
      (a) **Per-ROOM glazing split.** We have window areas and true azimuths per
          FACADE only, and the distribution is wildly uneven - Wohnzimmer holds
          roughly 28 m2 of the house's 51 m2. Without the split, per-room solar
          gain `q_sol,room` cannot be computed at all, and that is the dominant
          summer disturbance. **Highest-value remaining geometry item.**
      (b) **Shared wall area per room PAIR**, for the new `UA_nb` coupling
          terms. Note the automated attempt FAILED and should not be repeated
          naively: extracting 8 cm face pairs from the EG plan gives 105.6 m of
          run, but room perimeters imply only ~42 m - it pairs door leaves and
          dimension ticks. Do it by hand off the plan. The total is currently
          a +/-20 % geometric estimate (~42 m run, ~100 m2, ~2,000 Wh/K), which
          happens to close the overnight mass balance (15,300 predicted vs
          15,700-18,300 measured) but is not good enough for per-pair coupling.

- [!] **Door and window contacts - they switch the model's topology, not just
      its comfort.** Owner raised it 2026-07-29 while the Arbeitszimmer door
      and a Wohnzimmer window were both open.
      **Why this is not merely telemetry.** An open door between Wohnzimmer and
      the OG Luftraum carries **~158 W/K** of buoyancy-driven exchange at a
      2 K difference - 471 m3/h, close to one air change of the whole heated
      volume per hour, through one doorway. Closed, the same door is ~3.6 W/K.
      A **factor of ~44**, and the open value is 59 % of the entire building's
      H_total. An open window likewise changes `n` from the assumed 0.7 h-1 to
      something much larger.
      Consequences if we cannot see them:
      (a) **Parameter identification is corrupted.** A window-open hour looks
          exactly like a much higher `UA_eo`; the filter fits it and carries
          the error afterwards.
      (b) **Disturbance states absorb the difference** - misattributed to
          solar, occupancy or slab exchange, which are the very things we are
          trying to estimate.
      (c) The docs/DESIGN.md 7.1 innovation-whiteness gate would correctly
          flag the filter as mis-parameterised but could not say WHY, so we
          would lose planner confidence with no diagnosis.
      Priority order for fitting: **Wohnzimmer windows first** (that room holds
      48 % of the house's glazing), then the **Arbeitszimmer/Luftraum door**
      because it switches a coupling term rather than a loss term, then
      Kind 1 / Kind 2, then the bathroom.
      Until they exist: treat both as unmeasured disturbances with wide process
      noise, and **discard any identification run during which a door or window
      state changed**.

- [ ] **The open Arbeitszimmer door is a deliberate strategy, not an accident**
      (owner, 2026-07-29) - record it so nobody "fixes" it. The Luftraum and
      the fan coil sit ABOVE Wohnzimmer, so the stack effect carries the
      house's warmest and most humid air to the coil, giving it maximum
      sensible dT and maximum latent capture, and returns cooled denser air
      downward under gravity. A free thermosiphon, and the thermodynamically
      right place for a cooling emitter: cooling from above works WITH
      buoyancy, while floor cooling works against it - which is precisely why
      the slab is capped at 25-35 W/m2. It also partly defeats the "capacity
      is not fungible between rooms" limitation, since air moves what the
      hydraulics cannot. Worth testing deliberately once the door sensor
      exists: compare Wohnzimmer cooling rate with the door open vs shut, at
      matched solar and supply conditions.

- [ ] **Pipe run between the outdoor unit and the manifold: real, but not yet
      cleanly measurable.** Owner flagged it 2026-07-29 - it is an outdoor
      monobloc, so HP leaving water is NOT manifold supply. Measured over 24 h
      (all times UTC in InfluxDB):
      * **Return side is the consistent signal: HP return runs +0.4 to +1.0 K
        warmer than manifold return, mean +0.68 K.**
      * Flow side is inconsistent: +3.2 K during a warm idle period, but
        -0.6 to +0.8 K while actually cooling, sometimes negative.
      Do NOT read the flow-side mean as a loss figure. Two confounds:
      (a) with the compressor off and low flow the two ends simply decouple,
          so the 3.2 K is stagnation, not transport loss; and
      (b) in cooling the true effect is only a few tenths, which is at or
          below the offset between the heat pump's own sensor and our PT1000 -
          the two have never been cross-calibrated.
      To measure it properly: compare the two ends during steady flow at large
      dT (heating season gives 20-30 K to surroundings), or cross-calibrate by
      logging both at zero flow and full thermal equilibrium.
      Consequence meanwhile: **use manifold VL/RL for anything about the
      house, and HP leaving/return for anything about the machine.** Never mix
      them in one energy balance.

- [ ] **Two caveats for any winter-data analysis, both from the owner.**
      (a) **The heat pump applies its own outdoor-dependent setpoint
          correction.** So the setpoint register is NOT the effective target,
          and a reconstruction that assumes it is will be wrong. Use measured
          leaving/return water as ground truth. Check the RW register block
          for the weather-compensation curve parameters.
      (b) **Entity names change at the Controme/heatctl handover.** Winter
          data uses the old HA modbus hub's names - `leaving_water_temperature`,
          `return_water_temperature`, `outdoor_ambient_temperature`. From
          2026-07 it is `heatctl_leaving_water`, `heatctl_return_water`,
          `heatctl_outdoor_ambient`. A query spanning both periods silently
          returns half the data. Same trap for room temps: winter has eight
          rooms, today three.

- [!] **heatctl will CANCEL domestic hot water once the tank is connected.**
      Found 2026-07-29 when the owner said DHW must run even in cooling mode.
      The heat pump already supports it: mode **4 = `dhw+cooling`** (and
      3 = `dhw+heating`) are in `heatpump_map.py`. But heatctl only ever
      selects 1 or 2, has no DHW concept at all, and `_sync_pump_mode` treats
      anything else as a disagreement to correct - so it will write 2 over the
      unit's 4 every cycle and kill the DHW call. It will present as "the heat
      pump won't make hot water".
      **Blocks tank commissioning.** Not a one-liner:
      (a) plant mode becomes a PAIR (space mode x DHW demand), not a scalar;
      (b) `Safety.apply` must know a DHW call legitimately puts water far above
          any cooling supply limit - today `vl_undertemp`/`vl_overtemp` reason
          about one water temperature serving the floor;
      (c) the water-setpoint loop (D-018) must not fight the DHW setpoint;
      (d) `_sync_pump_mode`'s "disagreement" test needs to accept the DHW
          variants as agreement rather than drift.
      Design it before coding it.

- [ ] **Get the Solarbayer SLS-1000 datasheet.** The buffer is an SLS-1000,
      not the Buderus Logalux P990.6 M-C the EnEV papers name (that is now the
      **fifth** as-built deviation, after floor, walls, insulation and stove -
      treat every component in those 2020/21 papers as provisional). Needed:
      actual volume, standby loss (the 3.14 kWh/d quoted throughout our docs is
      the BUDERUS figure and is probably wrong), heat-exchanger surfaces,
      stratification pocket heights, and connection positions. The pocket
      heights in particular are needed before the 5-node tank model in
      docs/DESIGN.md 6.2 means anything.
      Note the owner reports it **provides hydraulic isolation**, which bears
      directly on the mode-selection valve question below.

- [!] **The 8 kW tank element is FITTED with no control path at all.** Owner,
      2026-07-29. Needs a contactor or SSR rated for 8 kW, one of the WAGO's
      spare relay outputs, and an interlock.
      Worth doing properly rather than minimally, because this is the one heat
      source whose energy we can measure **exactly**: resistive heating is
      100 % efficient by construction, so a Shelly on its supply gives true
      kWh with none of the dT and flow uncertainty that dogs every hydronic
      measurement here. That makes it the **calibration reference for the
      whole plant** - a known 8 kW into a known 1000 L of water is the
      cleanest experiment available for separating C from H, which is exactly
      the degeneracy the summer-night fit could not break.
      Only useful once the tank is filled and connected.

- [ ] **Choose the mode-selection valve topology** - 3-way plus non-return, vs
      4-way, vs two 4-way. Owner has a motorised 3-way on hand.
      The crux: a 3-way diverter switches the FLOW path only, so the return
      must be handled too or the idle branch stays hydraulically connected.
      A non-return valve blocks *forced* backflow but **not thermosiphon**.
      And the buffer is **inside** the thermal envelope (owner, 2026-07-29 -
      the EnEV papers say otherwise and are wrong), so a parasitic loop is not
      a loss to outdoors: in COOLING the plant cools the buffer and the buffer
      re-warms off the house, spending capacity to move heat in a circle. In
      heating the same loop is comparatively benign.
      Needs pipe geometry and relative heights, which are documented nowhere.

- [ ] **Write a 3-point actuator driver for the Afriso ARM 343 mixing valve.**
      Hardware is fitted (see docs/HARDWARE.md): 230 V, two directions, 120 s
      full travel, **no end switches, no position feedback at all**.
      Four requirements, and the second is the interesting one:
      (a) Dead-reckon position by integrating energised time per direction.
      (b) **Re-reference on start rather than persisting the estimate.** A
          dead-reckoned position is precisely the kind of state the design
          forbids surviving a restart. Drive hard to one end for >120 s and
          call it zero. The Alpha 5 solves the same problem in firmware
          (D-022); this actuator cannot, so heatctl owns it.
      (c) **Relay wear budget.** Mechanical relays give ~10^5 operations; a
          naive 1 Hz controller would spend that in a day. Needs a deadband, a
          minimum pulse, and a minimum rest - structurally the same argument
          as the heat pump's flash-write budget (D-013).
      (d) Mutual interlock, in hardware if the actuator does not provide it
          and in software regardless.
      Relay modules confirmed as **2x750-517** (owner, 2026-07-29),
      potential-free changeover, AC 250 V - adequate for the ARM 343 with room
      to spare. **But add an RC snubber per contact**: these switch an
      inductive motor load, and arcing on break erodes contacts far faster
      than the datasheet's resistive-load operation count suggests, which
      makes (c) more binding rather than less. **Unblocks the mixing circuit FOR HEATING.** Correction
      2026-07-29: the mixer is on the heating side only and the cooling path
      bypasses it, so it does NOT unblock the latent lever - that needs a
      cooling-side low-temperature branch this topology does not provide.

- [!] **WINTER DATA EXISTS: InfluxDB has 2025-10-03 to 2026-02-21 at full
      instrumentation, and it changes the priority order.** Found 2026-07-29.
      `http://<ha>:8086`, db `homeassistant`, HA's own influxdb credentials,
      **retention `autogen` = `0s` = INFINITE**. Earliest datapoint overall
      2023-05-23; 210 entities in the degC measurement alone.
      The usable window is **2025-10-03 -> 2026-02-21**, which matches the
      owner's account exactly: moved in August 2025, no proper doors and
      windows until October, so earlier data is test-bench only. The Controme
      died **2026-02-21 ~16:20** - every Controme-sourced entity stops within
      17 minutes, a precisely timestamped step change in control.
      **What is in that window - far more than we have today:**
      * **8 rooms**, not 3: `raumtemperatur_{wohnzimmer,gastebad,
        elternschlafzimmer}` plus `{bad,gastebad,kinderzimmer_naomi,
        kinderzimmer_natalie,schlafzimmer_eltern}_eg_current_temperature`
      * **all 12 circuit returns** `rl_1`..`rl_12`
      * heat pump: leaving/return water, outdoor ambient, tank, and the
        refrigerant side (cooling coil, exhaust gas, external coil, suction
        gas, economizer)
      * room **setpoints** (`solltemperatur_*`) - so the control target is
        known, not inferred
      * **the utility Shelly**: `netzstrom_*` active power PER PHASE and
        total, plus energy counters, plus `compressor_current`
      Density in Jan 2026: outdoor every ~80 s, leaving water every ~2.2 min,
      circuit returns every ~3.3 min, room temps every ~11 min.
      **Why this outranks several open items:**
      (a) **Winter dT is 2-3x summer.** Our 0.1 K quantisation is a far
          smaller relative error against a 15-25 K spread than against the
          0.65 K we fought all this week.
      (b) **8 rooms makes the per-room model identifiable** - the constraint
          that docs/DESIGN.md 6.1.1 names as binding.
      (c) **The 0x8025 calibration can be done retrospectively**, on four
          months and thousands of compressor start/stop events, instead of
          waiting for one hot afternoon. The heat pump is single-phase, so
          use the PER-PHASE Shelly channel rather than the total to isolate
          it. This supersedes "watch it at full output tomorrow".
      (d) **Flow may be derivable without the meter**: calibrated electrical
          power -> datasheet COP map -> thermal output -> with measured
          leaving/return dT -> `m_dot`. Caveats: nameplate COP is not this
          unit, part-load COP differs from rated, and the house has other
          loads. Worth attempting before the meter arrives; the meter remains
          worth buying for ongoing accuracy and drift detection.
      (e) A free-decay window may exist after 2026-02-21 with control stopped.
          Check what the plant actually did between then and heatctl.

- [!] **BUY: combined heating/cooling heat meter (Waerme-/Kaeltezaehler).**
      Decided 2026-07-29. Supersedes the "measure the flow rate" item below by
      choosing the instrument; that item's reasoning still applies.
      **Placement: primary circuit at the heat pump, flow sensor in the RETURN
      leg**, temperature pair straddling leaving/return. Return leg is standard
      (cooler water, longer sensor life). Primary rather than manifold feed
      because today they are the same thing under `H_DIRECT`, but the target
      design puts a buffer and mixing valve between them - and then primary
      measures what the HEAT PUMP produced (what COP needs, and it stays clean
      when the stove joins the circuit) while the manifold feed measures what
      reached the slab.
      **A plain heat meter will NOT do.** It integrates only when flow is
      warmer than return, so in cooling it registers nothing. Needs separate
      heating and cooling registers. Note MID (MI-004) covers heating only -
      cooling registers are never legal-for-trade, which is irrelevant here.
      SPECIFICATION, in order of how easily it goes wrong:
      * **CORRECTED 2026-07-29 after a market survey. My original spec of
        "DTmin <= 1 K" was WRONG and would have disqualified every meter made.**
        `DTmin = 3 K` is universal - it is the MID *approval* range, not a
        measurement cut-off. The figure that actually matters for non-billing
        use is the separately published **response threshold**
        (`Ansprechgrenze` / `Anlauf-DT`), which runs **0.01-0.5 K** by model.
        Specify on THAT.
        The underlying worry was right and is in fact worse: **below 3 K no
        manufacturer states an error bound at all.** Applying Kamstrup's own
        sensor-pair and calculator formulae gives roughly +/-4 % at 3 K,
        +/-8 % at 1 K, +/-15 % at 0.5 K and **+/-60 % at 0.1 K**. At the bottom
        of our measured spread NO purchasable meter yields usable energy
        accuracy. That is a physics limit of the matched pair, not a product
        gap - so plan around it rather than shopping for a way out.
      * **Ultrasonic**, not vane-wheel: turndown, and no moving parts on a
        30-year horizon.
      * `qp` ~1.5 m3/h for our 0.58-1.44 range - and check **`qi`**, the low
        end, not just nominal.
      * Temperature range covering ~5-90 degC (supply reaches 11 on a design
        cooling day).
      * **Condensation-rated, IP54+.** We run AT the dew point by design.
      * M-Bus or Modbus RTU on **its own bus** - must not share the heat
        pump's line, which is under a 200 ms inter-transaction constraint and
        a single-master rule (D-013).
      **SURVEYED 2026-07-29. Two survive; recommendation is Kamstrup.**

      | | Kamstrup MULTICAL 403-T | Diehl SHARKY 775 |
      |---|---|---|
      | response threshold | **0.01 K**, "no cut-off" | 0.125 K |
      | sensor pair | **explicitly matched** | not stated |
      | temp range | 2-130 degC | 5-105 degC |
      | turndown | 1:250, qi 6 l/h | 1:250, qi 6 l/h |
      | interface | **M-Bus only** | native Modbus RTU |
      | price DE | **EUR 217.85 net, in stock** | quote only |
      | cooling duty | 403-**T** = mandatory condensation-proof variant | IP65 potted sensor |

      Choose **Kamstrup MULTICAL 403-T** despite the Diehl's native Modbus:
      * 0.01 vs 0.125 K is a 12x difference sitting exactly in our band, whose
        floor is 0.10 K.
      * Kamstrup states the pair is MATCHED; Diehl does not. At sub-1 K dT the
        pair matching IS the measurement.
      * It avoids a trap the Diehl has: SHARKY only books cooling when flow is
        below 20 degC, so a shoulder-season 21 degC supply would silently
        register as HEAT. Kamstrup lets the heat/cool switchover threshold be
        disabled (set theta_hc to 250 degC) so dT alone routes energy - correct
        for us since we are not billing.
      * The Modbus advantage is smaller than it looks: we cannot share the heat
        pump's RS485 line anyway (200 ms rule, single-master, D-013), so it is
        a second interface either way.
      REJECTED: Zenner zelsius C5-IUF (no published threshold, no Modbus,
      battery-only); Sontex Supercal 5 S (fluidic oscillator, not ultrasonic);
      Landis+Gyr UH50/T550 (legacy family, not for a new 30-year install).
      **ASK KAMSTRUP BEFORE ORDERING:** does the 0.01 K threshold hold in
      COMBINED heat/cool mode? Engelmann degrades 0.05 -> 0.5 K when combined,
      and the others may too without publishing it.

- [ ] **Filter design note from the meter survey: feed VOLUME, not ENERGY.**
      The meter's energy register inherits the dT error above - up to +/-60 %
      at 0.1 K - and presents it as a single opaque number the filter cannot
      weight. The **volume/flow output is ultrasonic and independent of dT**,
      so it stays accurate across the whole range. Take volume as the strong
      observation, compute energy from flow plus our own temperature sensors,
      and let the filter weight the temperature term by its actual
      dT-dependent variance. This is also the concrete vindication of buying
      for flow rather than for energy: flow collapses the
      `m_dot` / `UA_ws` / `NTU` identifiability tangle regardless of how poor
      the temperature difference gets.
      **Worst case is still a win:** even if the energy register is poor at low
      spread, the ultrasonic FLOW output is unaffected by dT - and flow is what
      collapses the `m_dot` / `UA_ws` / `NTU` identifiability tangle that
      currently lets the filter fit the same RL data with high-flow/low-UA or
      low-flow/high-UA. Good DTmin additionally buys trustworthy COP.

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

