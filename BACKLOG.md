# Backlog

**The single source of truth for open work.** If it is not here, it is not
tracked. No TODO comments in code, no "still missing" notes buried in prose —
those go stale silently and nobody greps for them.

**What happened, and why, lives in `LOGBOOK.md`.** This file drifted into being
a lab notebook: on 2026-08-21 it held 6 300 lines, of which 4 500 were dated
investigations, measurements and superseded designs wrapped around the open
work. That is a good record and a bad backlog, so the two were split. Items
below that came out of an investigation carry a `→ LOGBOOK §` pointer to the
evidence rather than repeating it.

Each item says what it is, why it matters, and what unblocks it, because an
item whose rationale has been forgotten cannot be prioritised — it just sits
here.

Markers: `[ ]` not started · `[~]` partially done or blocked externally ·
`[!]` a finding or constraint that shapes other work rather than a task ·
`[x]` **closed** — done *or* rejected, and the item says which. Closed items
are kept, not deleted: a rejected idea that is not recorded gets re-proposed,
and a completed one explains why the code looks the way it does. When a closed
item's story is long, it lives in `LOGBOOK.md` and the line here points at it.

## Now — what I would pick up next

Not a priority ranking of everything below; the eight things that are either
blocking something else, cheap, or a known defect in the safety path.

| | what | why now |
|---|---|---|
| 1 | **The capacity loop's raise path has no rate term** | A proven defect with a measured trace and a fix sketch. It is what put the supply 1.0 K under the condensation limit on 2026-08-21. |
| 2 | **A cleared safety override is never published** | Two lines of code. Until then `heatctl/override/global` is a permanent false alarm after any transient, and silent when a real override clears. |
| 3 | **Bench `pfc-modbus-server`, then swap the coupler (D)** | The swap stops Modbus crossing the network and lets the manifold wiring be finished. Going via Modbus-on-the-box keeps the coupler watchdog, so the failsafe question defers to E. |
| 4 | ~~CODESYS owns `/dev/kbus0`~~ — **done 2026-08-24** | `runtime-version=0` freed the node and returned its ~18 % of the core. Left off; WBM still works. |
| 5 | **One coupled Kalman filter for the slab estimate** | `auto_mode` is off because the estimate follows the control action. Nothing else re-enables automatic mode selection. |
| 6 | **`supply_k_per_hz` has POOR provenance by its own comment** | The entire capacity descent rate is computed from it, and 2026-08-21 put it nearer 0.04 than the configured 0.074. Wants one controlled step test. |
| 7 | **`dew_point_margin_c: 1.0` is unsized** | The only buffer in the condensation defence, and it has never been derived. D-039 says there is no safe amount of condensation. |
| 8 | **Six rooms still to migrate onto Shellys** | Retires the Controme dependency room by room, and each one improves the local dew point. |

Longer-running and deliberately not on that list: the heat meter, the DHW
station fast loop, and layer 2 gaining command authority. They are big, none of
them is blocked, and none of them is urgent.

## Milestone 1 - harden layer 1

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
- [~] Room air sensors, Shelly H&T. **Three fitted and live 2026-08-06**
      (Schlafzimmer, Kinderzimmer Naomi, Badezimmer), all mains-powered,
      reporting every 6-12 min. House goes from 3 of 7 rooms with comfort
      feedback to 6 of 7. Needed `control.room_temp_max_age_s` raised 300 ->
      900 s first, or each room would have been called stale a third of the
      time and had its integrator reset on every flip.
      - [ ] **`kind_natalie` is the only blind room left** - one more unit.
            Until then it runs on the house average, which cannot distinguish
            it from its neighbours.
      - [ ] Bridged via three HA automations onto `roomtemp/<room>` (option A).
            **This raises the layer-1 independence debt from two rooms to
            five** (`docs/HA_INTEGRATION.md` risk 2). Deliberate for today.
- [ ] **Shellys publish to the broker directly** (option B), retiring the
      three bridge automations. One-time RPC config; devices are at
      `192.168.178.64/.67/.68`, Gen3, mains-powered, so MQTT runs alongside the
      HTTP/WS the Shelly integration uses and HA keeps battery/firmware.
      Blocked on: an MQTT user, since the Mosquitto App refuses anonymous
      clients. Buys: HA out of the path for three rooms.
- [ ] **Broker on the PFC200**, then **heatctl itself on the PFC200** (owner's
      target, 2026-08-06: "the whole control on the PFC200, an MQTT there, and
      the Shellys connecting directly to this MQTT"). Today the 750-352 is a
      dumb Modbus TCP coupler and the control core runs on the HA host, so it
      depends on a general-purpose machine it does not own. The PLC200 is
      already on order (see the M-Bus line in the shopping list, which is
      likewise blocked on it). Note the steps are not equal: option B removes
      an automation someone can switch off by accident; this removes a whole
      machine from the dependency chain.

#### Opened 2026-08-06 by the energy-demand work

- [~] ~~The slab target is mode-agnostic and its CONSUMER must not be.~~
      **DONE 2026-08-06.** `actionable_wh` gates the excess by plant mode -
      cooling acts only on a surplus of stored heat, heating only on a deficit,
      `off` on nothing - and `excess_wh` stays signed beside it, because
      clamping the measurement would hide the surplus that is the thing worth
      seeing overnight. House totals published both ways: the raw sum lets a
      surplus in one room offset a need in another, which the coupling makes
      partly real; the actionable sum does not, because a surplus the plant
      cannot deliver must not cancel a need it can.
      - [ ] **`blocked_wh` is the mode-switch signal and is NOT wired to mode
            selection.** Clamping to zero without keeping the remainder would
            have thrown away the one number saying "there is a job here and
            this mode cannot do it", so it is published per room and per house.
            But on the night it landed it read ~-31 kWh for a house at
            24-25 degC: as a switch signal that means "heat, in August". The
            slab target is STEADY-STATE and the building is in a diurnal
            transient, so this leads the air by hours and overshoots badly.
            Mode stays on the measured house average (D-020) - comfort, not
            model, and chosen precisely because it does not care what month it
            is. Its real near-term value is as an OVER-DELIVERY detector: the
            slab crosses to the wrong side of the target before the air does.
            Revisit as a mode input only once the shadow has earned it.
- [ ] **The slab target is mode-agnostic and its CONSUMER must not be.**
      Caught by the shadow the night of 2026-08-06: with outdoor down to ~20
      and the slabs at ~17 from the day's cooling, `house_excess_wh` read
      **-20 kWh**. That is correct arithmetic - the slabs are far below what
      would hold 23 degC against a cool night with no gains - and a nonsensical
      instruction, because in cooling a slab colder than the holding target is
      STORED COOLTH, not a deficit to make up with heat. The plant has no
      business heating in August. Either the consumer reads the sign through
      the plant mode, or the excess is clamped on the cooling side. Exactly the
      class of error shadow mode exists to catch before it moves a valve.
- [ ] **Give the energy shadow authority.** `heatctl/energy.py` computes slab
      target, estimate and per-room excess and publishes them; nothing reads
      the result back. Unblocks on watching the numbers against the plant for
      a few days. See `docs/DESIGN_ENERGY_DEMAND.md`.
- [~] **VL/RL cross-calibration - ATTEMPTED 2026-08-08, THREE TIMES, ALL
      INVALID.** See the entry below. The short version: you cannot calibrate
      two sensors against each other inside a live system with a distributed
      heat source. It needs a REFERENCE - a calibrated probe strapped
      alongside, or the pair in a common bath. The suspicion that started this
      (a ~0.5 K offset making the condensation guard permissive) is now
      neither confirmed nor refuted, and the number it rested on turned out to
      be an artefact.
- [ ] **Per-circuit flow at the LOW end of the opening range.** `open_threshold_pct`
      and `full_open_pct` are unmeasured and default to identity. The
      rotameters pin at 3 l/min, so the top of the curve is not measurable -
      but the interesting part is where flow STARTS (Möhlenhoff `Umin` ~5 %),
      which is exactly where they read well. Wiring verification needs only a
      change, not an absolute.
- [ ] **`NTU(opening)` per circuit, passively.** Converts RL into slab
      temperature; without it the estimate is the low-flow approximation,
      biased toward VL. §7.3 costs a dedicated sweep at ~20 h and says to
      prefer passive identification - we now have weeks of VL, RL and
      commanded opening logged.
- [ ] **Per-room `UA_ao` by envelope exposure, not floor area.** Currently one
      house-level permit prior split by area, so a corner room with two glazed
      façades gets the same W/K per m² as an interior one. The survey says
      outright that treating rooms as similar "will be wrong about
      [Wohnzimmer] specifically" - it carries ~28 of the house's 51 m² of
      glazing.
- [ ] **Air-capacity model for the fan-coil room.** Arbeitszimmer has no slab,
      so it is refused a slab excess and contributes nothing to the house
      figure. It still delivers and removes energy.
- [ ] **Door and window sensors** (planned, owner 2026-08-06). Every room
      couples to its neighbours and the Arbeitszimmer boundary is a door that
      is deliberately held open for heat exchange. An open door changes plant
      TOPOLOGY, not a parameter, and nothing reads its state - so the model
      cannot know which building it is in.

#### Opened 2026-08-06 by operations

- [ ] **Reconcile the heat-pump write budget.** WP-B's gate says "< 20
      writes/day"; `config.yaml` warns at 30/hour (720/day); the capacity loop
      actually wrote R32 **364 times** yesterday. Two numbers in this project
      disagree by 36x, the observed rate sits between them, and nobody decided
      that. If D-013's flash-wear premise holds and the register is EEPROM at a
      typical 100k cycles, 364/day is under a year of endurance.
- [ ] **Short-cycling, ~22 min.** Evenly spaced zero-crossings of compressor
      frequency suggest the unit cycles roughly every 22 minutes with very
      brief stops. `freq_min_hz` 30 exceeds the night load so it must cycle -
      buffer volume, not control. Confirm it is not the frequency register
      reading 0 transiently during modulation before acting.
- [ ] **`transaction_id` mismatch errors, ~6/min** on the heat-pump link.
      `modbus_direct.py` and `heatpump.py` build separate clients so it is not
      our concurrency; most likely the RS485->TCP gateway. Unexplained.
- [ ] **Valve command has no output deadband.** hk11 flipped +-1 % at ~1 Hz for
      hours. Physically harmless against a 150 s actuator, but it spams every
      write path and bloats the archive.
- [ ] **A heatctl restart commands a compressor stop/start.** P04 goes to 30
      ("dew point unknown") and back ~30 s later, which is the exact transition
      that provoked Er03 before C01 was set. It makes every deploy a small
      plant event.


## Raised in discussion, not yet scheduled

**This section is 1 200 lines and 50 items with no internal order** — the
largest remaining grooming problem, and why the table below exists. Themes, in
the order they would most likely be worked:

| theme | what is in it |
|---|---|
| **Flow and hydraulics** | flow floor from the datasheet rather than a rule of thumb; nothing checks the flow *maximum* though D-017 pushes toward it; the Er03 switch as a free single-point flow calibration; measuring the hydronic flow rate, which gates every energy balance; dT resolution as an independent limit |
| **Buffer, DHW and the tank element** | heatctl will cancel DHW once the tank is connected; the 8 kW element is fitted with no control path; SLS-1000 datasheet; mode-selection valve topology; a 3-point driver for the Afriso ARM 343 |
| **Metering and the energy balance** | buying the combined heating/cooling meter; where to place it, since that decides which question it answers; sub-metering dwelling vs annexe; separating the DHW load; `hp_power_estimate` is not usable for COP |
| **Weather and forecast** | the site runs 3 K colder than the forecast; forecast dew point is biased the *dangerous* way for cooling; learning the bias in layer 2; per-facade solar planes |
| **Model priors and geometry** | two take-offs from the Bauantrag plans; the outdoor-unit pipe run; phase-2 priors and their two gaps; caveats for any winter-data analysis |
| **Windows, doors and occupancy** | no window-open input and no sensors; door/window contacts switch the model's *topology*; the open Arbeitszimmer door as a deliberate strategy; the condensation guard is blind to showers |
| **Actuators and distribution** | per-channel step test when fitting each actuator; actuator characterisation; tuning `distribution.eps` |
| **Mode selection** | `auto_mode` heated the house in July for correct reasons; seasonal lockout proposed and rejected; source-side last resort when safety costs flow |
| **Retirement** | the legacy Controme Mini Server, and everything still depending on it |

  - [ ] **Split this section along those themes.** Mechanical, but it needs
        judgement on a few items that belong under two of them, so it is worth
        doing deliberately rather than with a script. Until then the table is
        the index.


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
      (a) **Per-ROOM glazing split. DONE 2026-08-09** - shipped as D-034.
          The assignment was already in docs/BUILDING.local.md (owner-confirmed
          2026-07-29, arithmetically verified against the per-facade totals);
          it needed wiring, not surveying. `optimizer/solar.py per_room_w`
          computes `q_sol,room` hourly, the optimizer publishes it retained on
          `heatctl/opt/room/<name>/solar_w`, and `EnergyDemand` subtracts it
          per room. Remaining, and deliberately left visible: the north and
          west EG windows (1.8 of 14.5 m2 effective) are unassigned, so
          gaestebad and the utility room report no gain rather than zero gain.
      (b) **Shared wall area per room PAIR**, for the new `UA_nb` coupling
          terms. Note the automated attempt FAILED and should not be repeated
          naively: extracting 8 cm face pairs from the EG plan gives 105.6 m of
          run, but room perimeters imply only ~42 m - it pairs door leaves and
          dimension ticks. Do it by hand off the plan. The total is currently
          a +/-20 % geometric estimate (~42 m run, ~100 m2, ~2,000 Wh/K), which
          happens to close the overnight mass balance (15,300 predicted vs
          15,700-18,300 measured) but is not good enough for per-pair coupling.

- [!] **Door and window contacts - they switch the model's topology, not just
      its comfort.** **EnOcean chosen** (owner, 2026-07-29) - energy
      harvesting, no batteries to maintain, which fits this project's 30-year
      premise better than any wireless alternative. Three things to get right:

      **(1) THE HEARTBEAT PROBLEM - design for it or it will bite.**
      Electrodynamic EnOcean contacts harvest energy from the magnet passing a
      coil, so they transmit **only on state change**. There is no periodic
      telegram. That inverts heatctl's central safety assumption: everywhere
      else, silence means lost knowledge and we fail open (D-003). A contact
      that speaks only on change is *permanently* silent and indistinguishable
      from a dead one.
      **Rule: door/window contacts are LATCHED inputs. Absence of a message
      means "unchanged", not "unknown".** This is the only sensor class in the
      system with that semantics, so it must be explicit in code and comment or
      someone will apply the standard staleness rule and get nonsense.
      **DECIDED 2026-07-29: solar variants** (STM 330 class, e.g. Eltako
      FTKB-hg), which *do* send periodic telegrams. So a heartbeat exists,
      a dead sensor is detectable, and the latched-input special case can
      carry a real timeout after all - which keeps door/window state inside
      the same staleness discipline as everything else rather than as an
      exception to it.

      **(2) Route it via MQTT, NOT via Home Assistant.**
      `EnOcean USB 300 -> enocean-mqtt -> mosquitto -> heatctl`. heatctl already
      subscribes arbitrary MQTT topics for room sensors, so this needs no new
      transport. Going through HA would make door state inherit HA's
      availability - unacceptable for something that feeds the model and
      eventually window-open safety logic, given heatctl must keep working with
      HA dead. HA's built-in `enocean` integration is also YAML-only with
      limited EEP coverage.

      **(3) Hardware.** The owner HAS a receiver, and is considering a **WAGO
      750 EnOcean module** (~EUR 99, second-hand) instead. That is
      architecturally attractive: door/window state would arrive over the
      **same Modbus TCP path heatctl already polls** - no USB stick, no bridge
      daemon, no extra failure mode, and it inherits the coupler's watchdog and
      staleness handling. Decoding the EEP in heatctl is no harder than the
      PT1000 raw decode we already do.
      **But check two things before buying:**
      * **PROCESS IMAGE SHIFT - the dangerous one.** WAGO maps process data by
        module order within each data type. An EnOcean module presenting input
        registers, placed *before* the four 750-463s, would **shift all 16
        PT1000 registers** and silently remap every temperature sensor. This
        is precisely the failure that mis-mapped the valves in July.
        **Rule: append new modules at the END of the rail, and re-verify the
        register map against the coupler after ANY module change.**
        config.yaml hardcodes `base_register: 12` for both sensors and valves.
      * **Device capacity** - how many EnOcean sensors one module can learn.
        Unverified; check before assuming it covers every window.
      If the USB route is used instead, note `/dev/ttyUSB0` is the ConBee III,
      so address by `/dev/serial/by-id/` and never by `ttyUSBn`. `/dev/ttyUSB0` is already taken by the ConBee III, so **address
      it by `/dev/serial/by-id/` and never by ttyUSBn** - enumeration order is
      not stable across reboots and a swap would silently point the bridge at
      the Zigbee stick. 868 MHz through a slab-heavy house may want a repeater.
      Worth checking whether any EnOcean hardware already exists from the
      Controme era - its source carries an `enocean_handler.py`. Owner raised it 2026-07-29 while the Arbeitszimmer door
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

- [x] **RESOLVED 2026-07-29: pumps are 2024 models, Connect modules apply.**
      Wilo gates Connect-module support on "Modell ab 2022". The unit marking
      **`24w11/074 0969 / I`** reads as **week 11 of 2024** (owner's
      interpretation, and the format is standard), comfortably past the gate.
      The shipped Kurzanleitung being dated 2021-01 is just old stock
      documentation. Worth one confirmation when a module is first fitted: a
      `SW Version` entry should appear under `Externes Modul`.

- [ ] **DECIDED: Modbus RTU Connect modules, 2x.** Owner, 2026-07-29 - no
      pump switching is planned, so telemetry is the whole point and only
      Modbus provides it. Routes below kept for the record.
      * **Modbus RTU Connect module** (~EUR 234-251 each) - gives `flow`,
        `powerInput`, `energyConsumption`, `speed`, and setpoint write. Both
        pumps share one RS-485 segment; a new Modbus client alongside the
        coupler, no new transport class. **Preferred if the pumps qualify.**
      * **BMS module** (EUR 265) - 0-10 V in, digital in, relay out, using the
        WAGO spares we already have. Control and fault status, **zero
        telemetry**.
      * **Relay on mains** - free, but see the inrush note below, and it gives
        nothing back.
      **Do not treat the pump's `flow` as a measurement.** Wilo explicitly
      disclaims it for closed-loop use and publishes no tolerance at all - it
      is a sensorless estimate from the motor operating point. It does NOT
      substitute for the heat meter; it is a soft signal for trend and
      sanity-bounding. `powerInput`/`energyConsumption` are real electrical
      measurements and are trustworthy (1 kWh resolution, rolls at 65535).

- [x] **MOOT - no pump switching planned** (owner, 2026-07-29). Kept because
      the constraint still applies to anyone who later adds a hard-off relay.
      **The 750-517 cannot switch the pumps.** Wilo requires the
      switching relay to make **>=5 A inrush**; the 750-517 is a 2 A part. It
      remains fine for the Afriso ARM 343 (tens of mA) - the earlier note in
      HARDWARE.md said 750-517 was adequate without distinguishing the loads.
      If pumps are to be switched at all, use a contactor or an interposing
      relay rated for the inrush. Wilo's other limits: <=100 switchings/24 h,
      <=20/h, >=1 min between transitions, max 10 A slow pre-fuse, and **never
      phase-angle control**. Settings survive a mains interruption, so relay
      on/off is safe configuration-wise.

- [!] **PLC200 ordered to replace the 750-352 + HA-container combo, giving
      CODESYS for the DHW loop.** Owner, 2026-07-29. The 1606 is ordered too,
      which unblocks the ten actuators.
      **The motivation is sound.** A 100 ms DHW loop (ROADMAP Milestone 2) run
      from a container over Ethernet is fragile in exactly the way that
      matters: it depends on the host, the network and the container runtime
      all behaving, for a loop whose whole point is determinism. Running it in
      CODESYS on the same backplane as the I/O removes all three dependencies.
      That is the right call for that loop.
      **Five things to settle before it lands, in rough order of danger:**
      (a) **SINGLE-WRITER OWNERSHIP.** Two controllers will touch one I/O rail.
          Which outputs belong to CODESYS and which to heatctl must be
          explicit and enforced, not conventional. This is the same failure
          class as the HA-vs-heatctl Modbus contention we removed in July
          (D-013), and it will be harder to see because both writers will be
          "ours".
      (b) **THE COUPLER WATCHDOG DOES NOT COME ALONG.** heatctl's outermost
          safety net is the 750-352's own Modbus watchdog zeroing outputs when
          writes stop - the one failsafe that survives a heatctl crash
          entirely. A PLC200 runs its own program; that behaviour must be
          re-created in CODESYS deliberately. **Do not migrate before this is
          designed**, or the plant silently loses its last line of defence.
      (c) **Register map changes again.** A PLC200's Modbus server maps its
          process image differently from a 352 coupler. `config.yaml`
          hardcodes `base_register: 12` for both sensors and valves. Re-verify
          against the device - this is the third time this rule has come up.
      (d) **Division of labour.** Least disruptive: the PLC exposes Modbus TCP
          exactly as the 352 did, heatctl keeps its architecture unchanged,
          and CODESYS owns *only* the fast DHW loop. Most disruptive: migrate
          control into CODESYS. Decide deliberately rather than by drift.
      (e) **CODESYS is a large new dependency**, and worth naming honestly
          against this project's stated premise of boring technology and
          minimal pinned dependencies. It means two languages, two toolchains,
          two deployment paths and two sets of failure modes, maintained for
          thirty years. The DHW determinism argument justifies it *for that
          loop*; it does not automatically justify moving anything else.
      **Do not let scope drift.** The strongest version of this is: CODESYS
      owns the one loop that genuinely needs hard real-time, heatctl keeps
      everything else, and the boundary is written down before any code moves.

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

- [!] **CONFIRMED AND QUANTIFIED: the site runs 3 K colder than the forecast
      on clear calm nights — river-valley cold pooling.** Owner's anecdote,
      validated 2026-07-29 against **3,388 paired winter hours**
      (2025-11-01..2026-03-31), local station vs Open-Meteo `icon_seamless`.

      **Overall the model looks fine** — median bias −0.20 K. The bias is
      **conditional**, and the conditioning variables are exactly the textbook
      cold-pooling ones. Conditioned on MODEL variables only (what a planner
      actually has at prediction time), not measured ones:

      | condition | n | median | sd |
      |---|---|---|---|
      | all hours | 3388 | −0.20 | 1.50 |
      | cloud <25 % | 683 | −1.20 | 2.16 |
      | cloud >90 % | 2091 | −0.10 | 0.99 |
      | wind <4 km/h | 375 | −0.60 | 1.81 |
      | wind 8–15 km/h | 1609 | +0.00 | 1.04 |
      | **night + clear + calm(<4)** | **50** | **−3.00** | 1.02 |
      | night + clear + calm(<8) | 263 | −2.90 | 1.15 |
      | night + overcast + windy | 629 | −0.10 | 0.67 |

      **−3.00 K median, to the decimal, exactly the owner's anecdote.** The
      contrast against the null case (night + overcast + windy, −0.10 K,
      n=629) is a factor of 30, with both cells well sampled.

      Mechanism: clear sky drives radiative surface cooling, calm air lets the
      inversion stand, cold dense air drains into the valley and pools. ICON at
      ~2 km cannot resolve a small river valley, so it returns the regional
      value.

      **Ruled out — this is not a static offset.** The model grid cell sits
      10 m ABOVE the site, worth ~+0.07 K of lapse rate: negligible, and the
      wrong sign. And a static offset would appear in every bin; this one
      vanishes under overcast or wind.

      **Daytime bias is POSITIVE** (+0.20 median, +0.60 clear days), which is
      the signature of station radiation error, not of the valley — a Fine
      Offset shield heats in sun and reads high, worst on exactly the clear
      days where the effect is largest. Daytime data is therefore contaminated
      **on the station side**, and the correction below deliberately applies at
      night only.

      **PRECISION CAVEAT — the WU history path returns INTEGER degC.** All
      3,389 values are whole numbers, 11 distinct values across an 11 K band.
      The station side of the winter analysis is therefore quantised to 1 K.
      What that does and does not damage:
      - **Headline survives.** Rounding is symmetric and near-unbiased, so a
        median over n=50 and n=263 is not moved by it, and 1 K of quantisation
        cannot manufacture a 30-fold contrast between −3.00 and −0.10 K.
      - **Do not over-read the exact −3.00.** Medians of integers land on
        integers and half-integers preferentially; that it matches the anecdote
        to the decimal is partly an artefact of the grid. The honest claim is
        "about 3 K", which is what was anecdotally reported anyway.
      - **The sd figures are inflated**, by roughly 0.29 K in quadrature
        (uniform rounding over 1 K). True scatter on the clear-calm-night cell
        is nearer 0.98 than 1.02 K.
      - **The RMSE improvements are understated if anything** — quantisation
        noise is irreducible error the correction cannot fit, so real skill is
        slightly better than the measured 20.6 % / 65 %.
      - **A fog/saturation test on this data is NOT valid.** Comparing two
        independently-rounded integers against a 1 K threshold is meaningless;
        an earlier "84 % of clear calm night hours are saturated" figure from
        this data is withdrawn. The owner's direct visual observation of
        valley mist is better evidence than that number was.

      **Consequence for the refit:** the restored local path carries 0.1 K
      resolution. Refit on local data from now on, and use WU only to backfill
      gaps, accepting the coarser resolution where it is the only source.

- [ ] **PLAN: learn the forecast temperature bias (layer 2 / planner only).**
      Candidate model, fitted and validated 2026-07-29. Every input comes from
      the same forecast response as the temperature, so it is computable at
      prediction time:

      ```
      dT = −a · (1 − cloud_cover/100) · exp(−wind_10m / w0)   [night only]
      a ≈ 5.0–5.5 K        w0 ≈ 8 km/h        night := shortwave ≤ 0
      ```

      **Out-of-sample validation** (fit Nov+Dec+Jan n=1988, test Feb+Mar
      n=1400): RMSE 1.835 → 1.457 K, **20.6 % better overall**; on clear calm
      nights in the test set (n=133), 3.376 → 1.177 K, **65 % better**. Fitted
      parameters barely moved between the two periods (a 5.0 vs 5.5, w0 8 in
      both), so the functional form is not overfitted.

      **Where it lives: layer 2 only, never layer 1.** The safety layer must
      not depend on a forecast, let alone on a learned correction to one. This
      is a planner input, and it must be clamped (reject |dT| > 5 K) so a
      pathological refit cannot feed nonsense to the planner.

      Refinements worth trying, in rough order of expected value:
      - **time since sunset** in place of the night step function — the
        inversion builds through the night, so the bias should grow, and a step
        cannot represent that. Likely the biggest remaining gain.
      - solar elevation for a continuous night factor rather than `shortwave≤0`
      - snow cover as a separate term (strong radiative cooling, high albedo)
      - seasonal variation in `a`
      - refit periodically from the ongoing dual-path record; do NOT freeze
        these constants into code as magic numbers

      Why this matters more than a 1.5 K RMSE suggests: the bias is worst
      **precisely on the nights that size the plant** — cold, clear, calm — so
      a planner on raw forecast under-predicts overnight loss exactly when the
      margin is thinnest. It plausibly explains the 2026-07-29 05:56 incident,
      where after a clear calm night the house drifted 1.1 K below target and
      `auto_mode` flipped to heating half an hour before sunrise. A planner
      aware of the local bias would have pre-charged the slab instead of
      reacting at dawn.

- [!] **Outdoor forecast DEW POINT is biased the DANGEROUS way for cooling.**
      Same 3,388 winter hours: the site is **+0.60 K moister than the model
      overall, and +1.30 K in daytime** (n=1411, sd 1.10, max +5.80). Daytime
      is when cooling runs, so a planner using forecast dew point to estimate
      cooling headroom will systematically believe it has **more headroom than
      it really has**.

      Two consequences:
      - **Never feed forecast dew point to the condensation guard.** It already
        uses the measured indoor maximum, which is both the right quantity and
        the safe one — keep it that way (`safety.cooling_supply_limit`).
      - If the planner uses outdoor dew point for capacity planning, it needs a
        margin of at least the +1.3 K bias plus scatter, not the raw value.

      The night+clear+calm cell runs the other way (−1.30 K): the air cools
      below the model and moisture deposits out as dew or frost. That is
      physically coherent, and a mild independent confirmation that the
      cold-pooling story above is real rather than an artefact.

- [x] **Local station is BACK** (2026-07-29), under the same entity names
      (`sensor.fineoffset_wh65b_210_*`), and there is now a **second,
      independent ingest path**: the console uploads to Weather Underground,
      whose hourly history API returned the entire winter the local path missed
      (3,389 hours, zero failed days). Station ID, coordinates and API access
      live in `docs/BUILDING.local.md` — site-identifying, never in this repo.

      The two paths share one physical sensor, so this is redundancy against
      **receiver/ingest failure** — exactly what happened on 2025-11-20 — not
      against sensor failure. Worth wiring the WU pull in as routine backfill
      so the next local outage costs no training data.

- [x] **WEATHER DATA SOURCE FOUND AND TESTED 2026-07-29 — Open-Meteo, wrapping
      DWD ICON.** All three endpoints verified working for our exact
      coordinates, hourly, **no API key**:
      | endpoint | use | gives |
      |---|---|---|
      | `archive-api.open-meteo.com/v1/archive` | full history (ERA5) | `temperature_2m`, `shortwave_radiation`, **`direct_normal_irradiance`**, `diffuse_radiation`, `wind_speed_10m` |
      | `api.open-meteo.com/v1/forecast?models=icon_d2` | planner, 48 h | same + `cloud_cover`. **DWD ICON-D2, 2.2 km** - the owner was right that this is the high-precision short-term model |
      | `historical-forecast-api.open-meteo.com/v1/forecast?models=icon_seamless` | **re-analysis** | archived HIGH-RES model runs rather than ERA5 |
      **Two things this unlocks immediately:**
      * **DNI and DHI separately** - which is what makes plane-of-array
        irradiance computable per facade at the measured azimuths. GHI alone
        would not do it. This is the input the solar-corrected H re-analysis
        needs.
      * **Wind for the WHOLE window**, not just the 46 days the local station
        ran. The infiltration-vs-conduction test (does H scale with wind?)
        becomes possible after all - it failed earlier purely for lack of
        wind-speed coverage and dynamic range.
      **CAVEAT, and it matters: ERA5 and ICON disagree on DNI by 2x.** Spot
      check for 2026-01-10 13:00: GHI agrees well (198 vs 204 W/m2) but DNI is
      **180 vs 384 W/m2**. DNI is what drives directional facade gain, so this
      is not a rounding difference - it would roughly double or halve
      Wohnzimmer's computed morning load. **Prefer the historical-forecast
      (ICON) endpoint over the ERA5 archive**, and arbitrate using the Fine
      Offset **lux** series for 2025-10-05..11-20 where we have ground truth.
      **Maintainability**: free, no key, open-source and self-hostable, and the
      underlying data is DWD ICON available directly from opendata.dwd.de - so
      there is a fallback if Open-Meteo goes away. **Layer 1 must never depend
      on it**: forecast is layer-2/planner input only, and heatctl already
      keeps that separation.

- [!] **Solar gain is uncredited in the H estimate, and it is big enough to
      matter.** Raised by the owner 2026-07-29; quantified below.
      Over the analysis window (Oct 5 - Feb 21) the EnEV monthly figures give
      **1,775 kWh of solar gain = 532 W continuous = 23 % of everything the
      heat pump delivered.** And the certificate's *Ausnutzungsgrad* is
      **1.000 in Dec/Jan** - in deep winter every kilowatt-hour of it is usable
      heat, none is wasted.
      **The analysis handled direct solar correctly** by restricting to dark
      hours (18:00-07:00). **But that does not remove it - it delays it.** A
      sunny day charges an 8,691 Wh/K slab which then discharges through the
      night, so the following dark hours need less heat pump input, and the
      balance credits that to nothing. The bias understates H:

      | fraction of daytime gain persisting into dark hours | H understated by |
      |---|---|
      | 20 % | 6 W/K |
      | 35 % | 10 W/K |
      | 50 % | 15 W/K |
      | 70 % | 21 W/K |

      Against the 51 W/K gap between calculated 267 and measured 216, solar
      plausibly explains **20-40 % of it** - material, but not the whole story.
      **THE FIX, and it is a real improvement rather than a patch:** we now
      have a far better solar model than EnEV's monthly means - per-facade
      Forecast.Solar planes at the MEASURED azimuths, with per-room effective
      collector areas (docs/BUILDING.local.md). Re-run the H estimate with an
      **hourly solar term over ALL hours** instead of excluding daylight. That
      removes the bias and gains ~4x the data at the same time.
      **Caveat on the 1,775 kWh itself:** EnEV uses a standard reference
      climate, not the actual weather of that window, so it could be off by
      ±30 % either way. The Fine Offset station logged **lux** for
      2025-10-05 to 2025-11-20 (~46 of the 139 days), which converts to
      approximate irradiance and would give a real check over that third.

- [ ] **Separate the DHW load properly, and reconcile the energy totals.**
      Two follow-ups from the eta decomposition (D-028).
      (a) **Classify the >8 kW episodes properly** rather than by a single
          threshold. Nothing else in the house draws 10-23 kW, so electric DHW
          is cleanly identifiable by magnitude - a first pass puts it at
          ~1,193 kWh, ~28 % of non-heat-pump consumption, which tightens eta
          to ~0.70 and H to ~216 +/- 10 W/K. Doing it by episode shape and
          duration rather than a flat threshold would tighten it further, and
          also yields the household's DHW demand profile - which the planner
          will need anyway once the tank is connected and DHW moves onto the
          heat pump.
      (b) **RECONCILE: integrating 1-minute mean power over the window gives
          8,848 kWh; the winter analysis reported 6,491 kWh.** A 36 %
          discrepancy. Candidates: power integration vs energy-counter
          differencing, a different window, or per-phase vs total. The eta
          RATIOS are robust to this but every absolute energy figure we have
          quoted depends on it, including the seasonal COP of 3.35.
          **Settle it before quoting absolute energy anywhere.**

- [ ] **Sub-meter the dwelling separately from the annexe.** The
      Sommerkueche/Grosskueche/Garage sit **outside the thermal envelope** and
      their consumption is inside the winter grid total with no way to remove
      it. A dedicated meter exists on the Hoernchenhaus/Kobel but only from
      June 2026. Adding dwelling-only metering converts eta from a reasoned
      estimate into a measurement, and would then make a blower-door test the
      dominant remaining question rather than a secondary one.

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
- [x] **DONE — `docs/DECISIONS.md`, D-001..D-047, referenced by ID from code
      and docs.** Several decisions have now been reversed - register 0
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

## `0x00F4` reads 65512 and the silent-mode gate passes on it

Known since 2026-08-08 (`_check_ranges` docstring); restated here because
D-038 made it load-bearing rather than merely untidy.

The register is declared `0..1000` and reads raw **65512**. `silent_ok` in
`_trim_capacity` tests `fan_cap >= capacity_fan_min`, so it passes — 65512 is a
large number. The gate exists to confirm the condenser fan is not throttled
before driving a frequency ceiling, and it is currently answering that question
by accident.

**Left passing deliberately.** Making it reject the implausible value was
written and reverted the same hour on 2026-08-19: `silent_ok = False` sends
`CapacityController.step` down the BLOCKED path, and before D-038 that also
removed the compressor STOP — the only condensation enforcement left after
D-035. Tightening a gate on a register nobody can read would have disarmed a
loop that demonstrably works.

**The evidence that the fan is actually fine**, and it is not the register:
silent mode binds (measured repeatedly 2026-07-30 → 2026-08-12; the compressor
tracks R32 within a few Hz once settled), and there have been **zero Er05
high-pressure trips**, which is the failure a throttled condenser produces.

**What would settle it**

- [ ] Read `0x00F4` as **signed**: 65512 is −24. Its neighbour `0x00F0`
      (`powerful_freq_boost_cooling_hz`) *is* a signed −30..30 trim, so the
      block may be trims rather than absolute speeds and the map may be wrong
      about the type, not just the range.
- [ ] Failing that, write a known good value and read it back. A register that
      accepts and holds a value while having no effect is a shape this unit has
      form for (R13 accepts 50 and runs at 80; `docs/HEATPUMP.md`).
- [ ] Only then tighten the gate to reject out-of-range readings.

Until one of those happens, `silent_ok` is not a safety property and should not
be described as one.

## `dew_point_margin_c: 1.0` is the only buffer, and it is unsized

`target_margin_c` is 0, so the capacity loop aims *at* dew + 1.0 and tolerates
±`deadband_c` (0.25) around it. Every other mechanism keys off the same limit.
So the entire defence against D-039's cumulative, invisible damage is one
empirical constant, and `safety.py` says so plainly: *"The margin is EMPIRICAL:
it matches the margin the existing HA supervisory loop has run at without
condensation... Sizing it properly is a BACKLOG.md item."*

It has to cover, at minimum: PT1000 error at the manifold, the dew-point
sensors' own RH error (the dominant term — 3 % RH is roughly 0.5 K of dew
point), the spread of dew point *between* rooms and the unmeasured spaces
between them, and the control loop's own overshoot. That is plausibly more
than 1.0 K, and nobody has added it up.

**No urgency, and the evidence says so.** Owner, 2026-08-19: *"empirically it
seemed fine"* — and the measurement agrees. Over the nine days to 2026-08-19
the manifold supply went below the dew point for five minutes total, all on
08-10 and all explained by the stale two-room reference. Zero since it was
fixed. So 1.0 K has held in practice against everything the plant has actually
met.

This is a request to *size* it, not to pad it. The owner reverted a 1.0 → 2.0
raise on 2026-08-10 because the incident had a complete explanation without it,
and that reasoning stands: a defensive change needs its own evidence. What is
missing is the arithmetic, not the margin.

## PFC200 migration — phases C, D and E

Phases A (broker), the bridge, and B (heatctl itself) are **done**, 2026-08-19
and 2026-08-20, as are the normaliser and the journal. `docs/PFC200.md` holds
the survey and the per-container detail; the reasoning behind the ordering is
in LOGBOOK § *PFC200 750-8212 — survey and migration strategy, 2026-08-19*.

These were tracked only in that document's status table until 2026-08-21, which
is not tracking — it is a device note that happens to have a column saying
"not started".

  - [ ] **Phase C: bench the Modbus watchdog. Gates D.** Three questions, not
        one, and only the second was written down before 2026-08-24.

        **C1 — ANSWERED 2026-08-24, and it dissolved most of Phase C.** The
        stock Modbus server is an **ADI device** (`/usr/lib/dal/libmbs.so`),
        not a daemon: `modbus_config` sets parameters for something that does
        not exist until an application instantiates it. There is no `modbus`
        init script and no modbus binary on the box, and starting CODESYS3
        brought up its gateway on 11740 but never 502, with no application
        loaded.
        **But that application need not be CODESYS.** WAGO publish
        `pfc-modbus-server`, whose own setup script sets `runtime-version=0` —
        so D can have a Modbus server with the runtime off. The remaining C
        questions apply to *that* server, not to a CODESYS program, and they
        only matter if D is taken. See the item below.

        **C2 — does `alternative-watchdog` behave like Standard?** The 750-352
        uses *Standard* with a coding mask restricted to FC6+FC16 (D-004), so
        "watchdog satisfied" means *outputs are being driven* and heatctl needs
        no separate heartbeat: its per-cycle valve write **is** the heartbeat.
        Alternative resets on any telegram, which D-004 calls "exactly
        backwards" — a controller reading fine but failing to write would keep
        it fed while the outputs went stale. There is an `options` mask,
        currently 4, that may restore write-only semantics. **That is a
        hypothesis about a name.**

        **C3 — which direction does it drive the outputs on trip, and is that
        configurable here?** This inherits the open contradiction from
        2026-07-31 (LOGBOOK): the 352 zeroes its outputs and that is *not*
        configurable, verified twice on hardware, while `docs/DESIGN.md` and
        `safety.py`'s policy docstring still assert the opposite ("full scale
        — valves are fail-open by design"). With NC actuators, zero closes.
        The PFC runs its own program and **neither behaviour comes along for
        free**, so the swap is the moment to decide which is wanted and make
        the documents agree with the hardware.

        Bench it the way the 352's trip test was run on 2026-07-26: stop
        writing, prove the outputs actually move, and record which way.
  - [ ] **Phase D — the swap, with `pfc-modbus-server` on the box. NEXT.**
        Takes Modbus off the network, which is the standing risk from
        2026-08-08, and lets the manifold wiring be finished and the cabinet
        closed. The wiring is identical for D and E; only the protocol above it
        changes later.

        **Why D rather than straight to E** (owner, 2026-08-24): native KBUS
        removes the coupler watchdog, which is the only failsafe surviving a
        dead heatctl, and nothing replaces it yet. Modbus-on-the-box keeps that
        watchdog, so the swap happens now and the failsafe question travels
        with E where it belongs. That is what makes D a useful step rather than
        a detour.

        **Gating checks. NOT doable on an empty rail** — tested 2026-08-24:
        the server starts and listens, but the KBUS will not init
        (`KBUS ERROR: 3`) and every register returns exception 6, busy. So
        these move to swap day, staged: **one 750-559 first**, verify, then the
        rest. Costs four valve channels on a plant that is down anyway.
          - [x] **Does `kbusmodbusslave` implement a watchdog?** **YES**, on
                the binary's own strings: `Watchdog Init/start/stop/trigger`,
                `ModbusWatchdog Expired Task`, `Watchdog Timeout: %ums`. D
                keeps a coupler-style watchdog, which is the premise the plan
                rests on.
          - [ ] **What does it do on expiry?** No string reveals the
                direction, so this is a bench observation. Settles C3 and the
                open 2026-07-31 contradiction at the same time.
          - [ ] **Do our register offsets survive the 362 emulation?** It
                emulates a **750-362**; ours is a **352**.
                `docs/HARDWARE.md` says input regs 12–27, holding 12–27. Same
                family, probably the same rules — not good enough for the thing
                the plant stands on with the cabinet open.
          - [x] **Starts and serves 502 with the runtime off** — confirmed
                2026-08-24. Degrades correctly too: with no KBUS it answers
                *busy* rather than hanging or serving stale zeros, so heatctl
                would fail its reads and hit the stale-data failsafe.
          - [ ] **Does it survive a reboot?** WAGO's README documents a
                "toggle the runtime if the KBUS will not init" bootstrap. Find
                out before relying on it at 2 a.m.
          - [ ] Note `kbus_cycle_ms 50` in its shipped config — the planned
                100 ms DHW loop (Milestone 2) fits inside that, which is worth
                knowing beyond this phase.

        Swap day: **source off first, watched to 0 Hz** — Er03 does not
        reliably self-clear (2026-08-20). Then terminals 1–12 plus the 750-600,
        verify the process image against `docs/HARDWARE.md` before trusting it,
        repoint `HEATCTL_MODBUS_HOST`, and run the watchdog trip test —
        which also settles the open 2026-07-31 direction contradiction.
        Rollback is physical: the 352 goes back on the rail. Keep it
        configured, on the shelf, until E is done.
  - [ ] **Phase E: native KBUS backend, retiring Modbus from the control
        path.** `/dev/kbus0` and the WAGO DAL libraries are present, so a Linux
        process can reach the process image with no Modbus server and no
        CODESYS — that is what the `IOBackend` ABC exists for. Two blockers:
        ~~**CODESYS currently holds the device node**, and there are **no SDK
        headers on the device**, so this needs WAGO's SDK or a documented
        ABI.~~ **BOTH RESOLVED 2026-08-24.** The node is free with
        `runtime-version=0`. The ABI is documented: WAGO's ADI-DAL manual,
        `adi_functions.txt` and a working `kbusdemo.c` in
        `github.com/WAGO/pfc-howtos`, plus the `libpackbus` headers in the G2
        SDK. And heatctl's own container can reach the DAL - verified, see
        `docs/PFC200.md`. What is left is in the bench-work item below.

        **`jessejamescox/pfc-kbus-api` — evaluated 2026-08-22 and REJECTED as
        the I/O path, but it settled the CODESYS question.** Owner raised it.
        Two reasons it is not the route:

          * **It is an MQTT bridge.** heatctl → MQTT → kbus-api → KBUS. That
            reinstates precisely what Phase E exists to remove, and it is
            structurally `backends/mqtt_io.py`, which already exists and is
            deliberately not in use. Its payload is the AWS-IoT shadow shape
            (`state.reported` / `state.desired`) published cyclically, so it
            inherits the staleness and latency questions in
            `docs/MODBUS2MQTT.md` as well.
          * **A prebuilt 267 KB armhf binary with no source**, last pushed
            2022-08-22, three stars, MIT on the wrapper scripts only. A closed
            blob in the safety-critical I/O path is the opposite of the
            30-year promise: it cannot be rebuilt, audited or fixed.

        What it DID give us is the supported way to release the device node
        from CODESYS, recorded under the CODESYS item below, and the useful
        existence proof that a plain Linux process drives KBUS on this
        hardware with the runtime switched off.

        **What those two grounds do NOT reject is a topology**, and that
        distinction was nearly lost on 2026-08-24 — owner asked "on what
        grounds did we reject the kbus-api shape?" and the honest answer was
        that we rejected *a binary* and *a transport*, not "a process between
        heatctl and the KBUS". A sibling process on the same box over a unix
        socket is not a network hop, and Phase E exists to remove the
        **network** from the I/O path, not all IPC. Note also that the MQTT
        objection is narrower than it first looks: `docs/MODBUS2MQTT.md` says
        the bridge was abandoned because the available add-on could not publish
        raw per-register values, and explicitly that "a future bridge may do
        this properly". The durable objection to MQTT here is the broker in the
        critical path and the 100 ms DHW loop, not MQTT as such.

  - [ ] **Phase E removes the outermost failsafe, and nothing yet replaces
        it.** The hard part of E, and **deliberately deferred to when E is
        implemented** (owner, 2026-08-24) — going via D keeps the coupler
        watchdog, so this does not block the swap. Do not start E without
        answering it.

        CLAUDE.md is explicit: the coupler's Modbus watchdog "is the only
        failsafe that survives a *bridge* crash — software failsafe logic here
        is the second layer, not the only one." Remove Modbus and that
        watchdog goes with it. If heatctl wedges with the outputs at 10 V,
        nothing zeroes them: the NC actuators close on loss of **power**, not
        on a hung controller.

        Three candidates, none free:

          * **A watchdog in the DAL/KBUS layer.** Plausible and cheapest if it
            exists; needs the SDK documentation we do not have.
          * **A local KBUS supervisor** owning `/dev/kbus0`, implementing the
            watchdog, and dropping the outputs when its client stops writing.
            This is **structurally what the 750-352 already does** — heatctl's
            per-cycle write is the heartbeat today and D-004's mask makes
            "outputs are being driven" the liveness condition — so it is the
            most faithful port of the current design rather than a departure
            from it. Cost: a second process in the I/O path, which must then
            be as boring and as well-tested as the control core.
          * **Hardware**: a relay or contactor dropping output power on a
            heartbeat. The only one that survives everything, and the most
            work.

        Decide this before E is scheduled, not during it.

  - [ ] **Bench work for E, prepared 2026-08-24 — what is left.** The two
        blockers named above are both gone; what remains is real but bounded.

        **Done and verified:**
          * `/dev/kbus0` is free with `runtime-version=0`, `codesys3` stops,
            ~18 % of the core comes back.
          * heatctl's own container **can reach the DAL** — ctypes recipe in
            `docs/PFC200.md`, `adi_GetApplicationInterface()` returns a live
            pointer from stock `python:3.12-slim`. No compiler, no SDK on the
            device, no new dependency, no base-image change.
          * The ABI is documented: WAGO's ADI-DAL manual, `adi_functions.txt`
            and a working `kbusdemo.c` in `github.com/WAGO/pfc-howtos`.

        **Left:**
          * [ ] Get `dal/adi_application_interface.h` and transcribe the vtable
                into ctypes `Structure`s. Do not guess offsets - it is a
                function pointer in the I/O path.
          * [ ] Prove `Init/ScanDevices/GetDeviceList` finds a device named
                `libpackbus`. **This works with an EMPTY rail**, so it can be
                done before the swap and before any terminals exist.
          * [ ] Decide the failsafe (the item above). Still the hard one.
          * [ ] Read/write process data — needs terminals, so after the swap.
          * [ ] Check whether `SCHED_FIFO` priority 40 matters, as WAGO's demo
                does it. Untested from Python.

  - [ ] **`WAGO/pfc-modbus-server` — makes Phase D much cheaper than the
        CODESYS route, and is worth a look before committing to E-first.**
        Vendor-published Docker image serving Modbus TCP off the KBUS with the
        runtime OFF. Costs: `--privileged`, D-Bus socket, a closed 24 KB
        binary (vendor, but last pushed 2022), a **750-362** register map that
        must be checked against our 352 offsets, a documented "if the kbus
        would not init, toggle the runtime" bootstrap, and dependence on the
        physical RUN/STOP switch. Detail in `docs/PFC200.md`.
        Worth testing on the bench precisely because heatctl would need only
        an address change — if the 362 mapping matches, D becomes an
        afternoon.

## The PFC200 and its SD card are now single points of failure

What the resilience design (→ LOGBOOK § *Resilience: depend on as little as
possible, duplicate what remains*) deliberately did not answer.

**The PFC200 itself, and its SD card, became single points of failure** the
moment control moved onto them on 2026-08-20 — and an SD card is a wear-out
part on a thirty-year horizon, carrying docker-root, heatctl's SQLite and now
the journal. A spare unit, a restorable image, and a documented rebuild are the
obvious shape, and none of it exists.

  - [ ] **A restorable image and a documented rebuild.** Everything that is not
        in git lives on that card: `config.yaml`, the broker's `passwd`, certs
        and persistence, four `run-*.sh`, the four `*.env` files with
        credentials generated on the device and stored nowhere else. Losing the
        card today means reconstructing all of it from memory.
  - [ ] **Decide whether a cold spare is worth it**, and if so keep its
        firmware and configuration in step. The rollback path is still "start
        the Home Assistant App", which needs the coupler — so it disappears at
        Phase D, and this becomes the only answer.

## Battery Shellys wake every 2 h, and the freshness window assumes 15 min

Measured 2026-08-22, when Bad and Gästebad came onto the plant broker:

| room | power | `wakeup_period` | temperature msgs / 5 h | worst gap |
|---|---|---|---|---|
| Wohnzimmer | **mains** (`external.present: true`) | 600 s | ~75 | ~6 min |
| Bad | battery, 6.27 V | **7200 s** | 8 | 112 min |
| Gästebad | battery, 6.29 V | **7200 s** | 7 | 93 min |

`room_temp_max_age_s` is 900 s and the normaliser's `ttl_s` matches it, so a
battery room spends most of the day on `house_avg`. Bad was migrated anyway -
its Controme sensor was dead, so an hourly real reading strictly beats a
permanent house average - but **Gästebad was deliberately NOT repointed**: its
Controme path still publishes ~620 times a day against this device's ~7, so
switching now trades a two-minute cadence for a two-hour one.

**The interesting part is that silence means different things on the two.** A
periodic sensor going quiet is a fault. A *change-triggered* one going quiet
means the room is not moving - which is exactly when the last reading is still
valid. The two are only distinguishable by the device's own `wakeup_period`:
silence longer than that is a fault, shorter than that is information. So the
window is not arbitrary, it is a property of the device, and the device
publishes it.

  - [ ] **Decide the approach.** Three, and they are not exclusive:
        **mains-power them** (Wohnzimmer already is, and it still deep-sleeps,
        so accuracy is unaffected - `wakeup_reason.boot` is `deepsleep_wake`);
        **shorten `wakeup_period`** on the devices, at a real battery cost of
        roughly 12x the wakes; or **size the window per room**.
  - [ ] **If per-room: derive it, do not configure it.** The normaliser already
        receives `status/sys` with `wakeup_period` on every wake, so it can set
        each room's expiry from what that device says about itself - about
        1.5x its own period. Self-configuring, and it cannot drift from the
        device the way a hand-set number would. heatctl would need
        `room_temp_max_age_s` per room to match.
  - [ ] **Watch the battery.** 6.27 V and 6.29 V, both reporting 100 %, are the
        first readings. Whatever is decided above changes the discharge rate,
        so record a baseline now while the cadence is known.

## What the normaliser left open

  - [ ] **A room on the normaliser depends on a second process.** Supervised,
        same box, and its death degrades that room to house-average control
        rather than to a wrong number — but the raw topic did not have that
        dependency. The fix is letting a room name **more than one source**,
        preferring the freshest: raw and normalised together, and the raw path
        keeps working if the normaliser is gone. Needs a heatctl change
        (`room_temp_topic` becomes a list), so it is not free.
  - [ ] **The expiry does not survive the bridge to Home Assistant.** The
        bridge speaks v3.1.1, so `sensors/room/#` lands on HA's broker as
        ordinary retained values that never expire — the fossil shape, on a
        tree nothing consumes yet. `sample_ts` is published beside every value
        precisely so the age is recoverable there, and anything built on this
        tree in HA must use it. `bridge_protocol_version mqttv50` would carry
        the property across; untested, and it changes a working link for every
        bridged topic, so it wants a quiet moment and a quick revert path.
  - [ ] **Six rooms still to migrate.** Each needs its Shelly pointed at the
        plant broker, an entry in `normaliser/config.yaml`, and heatctl's
        `room_temp_topic` repointed — three steps, deliberately separable, so
        raw and normalised can be compared on a live room first.

**Wohnzimmer is the pilot** (owner): it has both an old-world source (Controme
REST via the HA bridge) and a new-world one (Shelly on the PLC broker), so
every one of these can be proven against a room that still has a working
fallback before any other room moves.

## Found while operating the plant, 2026-08-19 → 2026-08-21


### A cleared safety override is never published, so the topic keeps the alarm

Found 2026-08-20 while checking the plant after a restart:
`heatctl/override/global` read `stale_data` eight minutes after the log said
`failsafe cleared (was stale_data for 1 s)`. Verified retained (`retain=True`),
not a live republish.

`Controller.failsafe()` publishes `override/global`; `_failsafe_cleared()` only
logs. Since `ControlPlane.publish` retains by default, the last reason stands
for ever. The per-valve `override/<valve>` topics have the same shape — written
while a rule is active, never written when it stops.

**Why it is worse than cosmetic.** The topic is useless in both directions: it
shows a false alarm permanently after any transient, and when a *real* override
clears, nothing says so. Anything in Home Assistant built on it is reporting
plant safety state that has no relation to the plant. Every restart arms it,
because a restart always passes briefly through `stale_data`.

This is the same defect already recorded above for the per-room energy topics —
**absence must be published, not implied** — and it landed on a safety topic
this time.

  - [ ] `_failsafe_cleared()` publishes `override/global` = `none`; the
        per-valve loop publishes `none` for every owned valve not overridden
        this cycle. Both need a test that asserts the CLEAR is published, not
        merely that the set is.
  - [x] The stale retained value was cleared by hand on 2026-08-20 so it did
        not sit there overnight advertising a failsafe that had ended. That is
        a cleanup, not the fix.

### The CODESYS runtime is still running, and it owns `/dev/kbus0`

Measured 2026-08-20 while looking at why the single core is busy:

```
PID 2366  /usr/bin/codesys3   17.9 %CPU   64 MB RES   240 min CPU accumulated
fuser /dev/kbus0  ->  2366
```

Three separate problems in one process, and none of them was known:

1. **It is a second master on the local I/O.** It holds the KBUS device node.
   That is a hard blocker for the native KBUS backend (Phase E), not a
   performance note — heatctl cannot open a device another process owns.
2. **It costs ~18 % of the only core, permanently**, for a runtime carrying no
   program of ours. heatctl itself sits at ~48 % and mosquitto at ~10 %, so
   the box runs at roughly 77 % of one core with a 1 s control loop on it.
   Reclaiming CODESYS's share is the largest single headroom win available
   and needs no code.
3. **It is a writer nobody decided on.** Whatever it does or does not do with
   the outputs today, "I do not trust a situation of two masters writing to
   the same bus" (owner, on the heat pump) applies here by the same argument.

  - [x] **DONE 2026-08-24.** Turned off with `config_runtime -w
        runtime-version=0`, attended, plant quiescent. `/dev/kbus0` reports
        FREE, `codesys3` is gone, its ~18 % of the core is back, and **the WBM
        still answers** - nothing that matters depended on it. Left off, since
        that is also what Phase E needs.
  - [ ] **Use WAGO's own `config_runtime`, not the init script.** Owner found
        the procedure in `jessejamescox/pfc-kbus-api` (2026-08-22), and it is
        supported and reversible rather than a hack:

        ```sh
        /etc/init.d/runtime stop
        /etc/config-tools/config_runtime -w runtime-version=0      # none
        /etc/config-tools/config_runtime cfg-version=3 webserver-state=disabled
        ```

        and back again with `runtime-version=3` / `webserver-state=enabled`.
        Consistent with the 2026-08-19 survey, where `get_possible_runtimes`
        offered `0 1`. Prefer this to disabling `S98_pp_codesys3`: it is what
        the vendor's tooling is for, and it has a documented undo.
  - [x] **EXPLAINED 2026-08-24 — the survey was misled by its own tool.**
        It recorded `get_runtime_config` empty and concluded no runtime was
        running; on 2026-08-21 `codesys3` was running and holding the node.
        Both observations were accurate: **`get_runtime_config` returns empty
        even while `codesys3` is running.** Confirmed directly - starting
        CODESYS3 brought up its gateway on port 11740 while the getter still
        reported nothing. So the getter reports a *configured selection*, not
        what is live, and "no runtime selected" never meant "no runtime
        running". Check the process table, not the config tool.

### The capacity loop's raise path has no rate term, and that is what breaches the limit

Measured 2026-08-21, and this is the first end-to-end log of a cooling ramp
under the D-035/D-036 architecture. Sampled every 33 s. `limit` is
`cooling_supply_limit`; `ceil` is R32.

```
time         vl     rl  limit  ceil  freq  reason
11:40:10   19.7   22.7   20.0  50.0   0.0  margin -0.30 K low, waiting for the last move
11:41:16   19.8   22.7   20.0  48.0   0.0  margin -0.20 K - in band
11:42:22   20.1   22.8   19.1  48.0   0.0  limit DROPS 20.0 -> 19.1 (bathroom aired out)
11:42:52   20.7   23.0   19.1  48.0  28.0  compressor starts
11:43:25   21.1   23.2   19.1  58.0  50.0  margin +2.00  <- RAISE
11:45:37   20.8   23.6   19.1  68.0  63.0  margin +1.70  <- RAISE, margin now falling
11:47:49   19.8   23.5   19.1  75.0  74.0  margin +0.70  <- RAISE, still falling
11:49:28   18.9   23.3   19.0  75.0  74.0  margin -0.10  crosses under
11:53:16   18.0   22.7   19.0  56.0  56.0  margin -1.00  worst point
11:57:41   18.9   22.3   19.0  42.0  41.0  margin -0.10  recovering
11:58:14   19.0   22.3   19.0  42.0  41.0  margin  0.00  in band
12:01:29   19.3   22.4   19.0  44.0  43.0  stable, ceiling 42-44, supply on the limit
```

**Two findings, and the first one matters more than the defect.**

#### 1. The loop works. It was interrupted once for no good reason.

Left alone it caught the excursion and settled: worst case **1.0 K under the
limit for about five minutes**, then a clean landing at 42 Hz with the supply
sitting on the limit. No intervention, no oscillation, no fault. That is
D-036's architecture doing exactly what it says it does — *"the floor does not
hold the limit; the enforcer is `_trim_capacity`, acting on measured supply
every cycle"*.

An earlier ramp the same morning was cut short by an operator `mode off` at
supply 17.7 / limit 19.0-20.0, on the reading that "nothing is stopping it".
Something was: the ceiling had already moved 71 -> 61 and `writes_last_hour`
was 9. The reason string said `waiting for the last move to take effect`, which
is a loop mid-response, and it was read as a loop not responding. That
intervention destroyed the only interesting measurement of the day and produced
a proposal to reinstate D-030 — a decision the repository already records as
tried, measured and reversed.

Worth stating as a rule, because it will come up again: **`_trim_capacity` is
the designated enforcer and it acts on a 60 s settle cadence. A margin that is
negative and a loop that is stepping the ceiling down is the system working.
Before overriding it, check that the ceiling has actually moved and that
`min_hz` has been reached** — that is the point at which its authority is
genuinely exhausted, and it stops the compressor by itself there.

#### 2. The raise path spends transient headroom as if it were steady state

The breach was caused by the *raise* path, not by a failure of the lower path.
Between 11:43 and 11:48 the ceiling went **48 -> 58 -> 68 -> 75 Hz** while the
margin fell monotonically **+2.00 -> +1.70 -> +0.70**. It then took six minutes
of lowering to walk back out of an excursion it had created.

`step()` raises on the margin's **level** (`err > deadband`, at ceiling, raise
interval elapsed) and never looks at its **slope**. During a cold-start ramp
into a large demand, headroom is being consumed at ~0.3 K per 30 s and reading
it as spare capacity is simply wrong.

This is the same family as the RESUME defect fixed on 2026-08-11/12 - *"the
loop spends a margin it created itself"* - in the other branch, and the same
comment already warns about it for `_last_raise`. `raise_interval_s` was also
cut 600 -> 120 when the step became proportional, which makes it raise three
times through a transient where it used to raise once.

  - [ ] **Do not raise while the margin is falling.** The cheapest form is a
        sign test on the change in margin since the last sample; a small
        negative-slope veto would have blocked all three raises above without
        affecting steady-state behaviour at all. It must not become a
        derivative *controller* - the lowering path stays purely proportional,
        because the protective direction must never depend on an estimate of
        a rate.
  - [ ] **Consider whether a cold start should raise at all** for the first few
        minutes. `_last_raise` is seeded on first use precisely so a restart
        cannot ratchet; a compressor start from 0 Hz is the same situation and
        is not currently covered.
  - [ ] **`supply_k_per_hz: 0.074` still has POOR provenance by its own
        comment.** This log is not a clean step test either - the limit moved
        at 11:42 and again at 11:48 - but it does give a usable check: 75 -> 42
        Hz against roughly +1.3 K of supply recovery is ~0.04 K/Hz, about half
        the configured figure. If that holds up, every lowering step is
        currently about half the size the loop intends. A controlled step test
        against a stable dew point remains the fix.

### Broker file permissions — mosquitto is warning about them

Every reload prints them, so they are not a discovery, just unrecorded:

```
Warning: File /mosquitto/config/passwd owner is not root.
Warning: File /mosquitto/config/mosquitto.acl has world readable permissions.
         Future versions will refuse to load this file.
```

  - [ ] Tighten `mosquitto.conf`, `mosquitto.acl` and `passwd` to 0600 owned by
        1883, and confirm the broker still starts. Deferred rather than done
        because the image is **pinned by digest**, so "future versions" cannot
        arrive on their own — and a permissions change has already taken this
        broker down once (root-owned 0600 files, 2026-08-19). It wants a moment
        when watching it recover is convenient, not the end of a long session.
        The CA private key sitting world-readable next to them
        (`docs/PFC200.local.md`) is the more serious half of the same job.

### D-044's start-up one-shot can fire before the energy model has answered

Observed immediately after deploying D-046:

```
mode -> cooling at start-up (house -1.04 K (no energy model), 7 rooms, no dwell)
```

`_last_house_excess_wh` is `None` until the energy shadow has run once, so the
one-shot — which fires as soon as the room set is complete — can spend itself
on the fallback statistic. That is the very statistic D-046 demoted, and on
that evening the two disagreed **in sign**.

Not fatal: the dwell path prefers energy, so it self-corrects after
`mode_dwell_s`. But an hour in the wrong mode after every restart is most of
what D-044 was built to avoid.

  - [ ] Make the one-shot wait for the energy basis, bounded — arm on energy
        if it arrives within a short grace, otherwise fall back and spend it.
        Needs a start timestamp in `DemandController`. The unbounded version
        is wrong: a permanently blind model would lose the fast start-up
        decision altogether.

## Carried over from the investigation log

Fifty-five items that were still open inside the dated entries when the log was
split out on 2026-08-21. They are titles plus a pointer, deliberately: the
reasoning is long, it is already written, and copying it here is how two copies
start disagreeing. Read the log section before acting on one.

**These have NOT been individually re-validated.** Some date to 2026-07-29 and
the plant has changed a great deal since — the heat pump is configured
differently, the controller has moved machines, and several were written before
decisions that supersede them. Triaging them is itself a backlog item:

  - [ ] **Re-validate the carried items below, and close what is dead.** Cheaper
        one theme at a time than in one pass, and each closure should say why.

### Heat pump registers and the frequency ceiling

  - [ ] Silent-mode settings are now load-bearing  
        → LOGBOOK § *SILENT COOLING MODE WORKS. The window is open. 2026-07-30 12:33.*
  - [ ] If the spread problem is to be attacked through frequency, capping the  
        → LOGBOOK § *R13 TEST RESULT: it does not bind. Clean negative.*
  - [ ] Also unexplained: what *does* enforce a ceiling? The unit reached 89 Hz  
        → LOGBOOK § *R13 TEST RESULT: it does not bind. Clean negative.*
  - [ ] Write R13 = 50 and observe  
        → LOGBOOK § *Read the frequency-limit registers. R13 does not appear to bind.*
  - [ ] Only then consider rewriting the ladder's top entries  
        → LOGBOOK § *Read the frequency-limit registers. R13 does not appear to bind.*
  - [ ] P08 water temperature compensation (`0x0092`, −5…15 °C) is unexplored  
        → LOGBOOK § *THE OPERATING WINDOW IS ~0.5 K WIDE. This explains everything.*
  - [ ] Re-audit `docs/HEATPUMP.md` against the full capture  
        → LOGBOOK § *THE OPERATING WINDOW IS ~0.5 K WIDE. This explains everything.*

### Spread and flow

  - [ ] Set F10 = 2 and observe for a day  
        → LOGBOOK § *F10 (`0x010B`) IS THE LEVER — the unit is holding a 5 K spread on *
  - [ ] Also worth investigating: `powerful_mode` is currently ON  
        → LOGBOOK § *F10 (`0x010B`) IS THE LEVER — the unit is holding a 5 K spread on *
  - [ ] The setpoint→supply gap is DYNAMIC and nothing in layer 1 measures it  
        → LOGBOOK § *F10 (`0x010B`) IS THE LEVER — the unit is holding a 5 K spread on *

### Capacity loop and the write budget

  - [ ] Asymmetric minimum step on the capacity actuator  
        → LOGBOOK § *ANSWERED 2026-08-01: it tripped, and the budget is NOT the thing t*
  - [ ] The `P_el` intercept is applied unconditionally, and its constituents  
        → LOGBOOK § *ANSWERED 2026-08-01: it tripped, and the budget is NOT the thing t*
  - [ ] Make P04 retreat when the heat-pump link goes stale  
        → LOGBOOK § *2026-08-02 — P04-low + R32-modulating lost a self-limiting propert*

### Hydraulics: the manifold dT loss

  - [ ] Check whether the return run is insulated  
        → LOGBOOK § *MEASURED 2026-08-01 — 19 % of the heat pump's dT never reaches the*
  - [ ] Cheap interim check: swap or cross-calibrate the VL/RL sensor pair  
        → LOGBOOK § *2026-08-01 — measured COP is 1.69, and that number indicts the man*
  - [ ] The COP SHAPE is usable now even though the level is not  
        → LOGBOOK § *2026-08-01 — measured COP is 1.69, and that number indicts the man*
  - [ ] D-027's 200 W intercept has unsound provenance - the magnitude may be  
        → LOGBOOK § *2026-08-01 — measured COP is 1.69, and that number indicts the man*

### Pre-charging and lead time

  - [ ] A lead-time-aware delta is the missing piece  
        → LOGBOOK § *⚠️ THERE IS NO PRE-COOLING SCHEDULE. It is not time-based at all.*
  - [ ] Validating `ua_sa` would make the fast mode trustworthy  
        → LOGBOOK § *⚠️ THERE IS NO PRE-COOLING SCHEDULE. It is not time-based at all.*
  - [ ] The trim needs a slab-referenced mode for pre-charging  
        → LOGBOOK § *THE OVERNIGHT PRE-CHARGE FAILED. Measured 2026-07-30 morning.*
  - [ ] Consider whether the setpoint should ever sit where the unit will not  
        → LOGBOOK § *THE OVERNIGHT PRE-CHARGE FAILED. Measured 2026-07-30 morning.*

### WP-S, still outstanding

  - [ ] B · Stop the setpoint trim walking P04 down for capacity  
        → LOGBOOK § *WP-S implementation status — the three changes, 2026-07-31*
  - [ ] C · Compressor stop as the bottom of the spread actuator  
        → LOGBOOK § *WP-S implementation status — the three changes, 2026-07-31*

### Layer 2 gates

  - [ ] Two weeks of innovation whiteness is the next gate  
        → LOGBOOK § *Layer 2 — first cut shipped 2026-07-29 (WP-F scaffold, observe-onl*
  - [ ] Known weak inputs, in order  
        → LOGBOOK § *Layer 2 — first cut shipped 2026-07-29 (WP-F scaffold, observe-onl*
  - [ ] Before layer 2 may command anything:  
        → LOGBOOK § *Layer 2 — first cut shipped 2026-07-29 (WP-F scaffold, observe-onl*

### Modelling and per-room sensing

  - [ ] Decide whether the slab model needs to be per-CIRCUIT rather than  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] Note the diagnostic value: a circuit reading far above its neighbours  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] The 0.90 shading factor is a certificate constant, not a measurement  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] Falsify the per-room solar shape against the room sensors  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] Schlafzimmer needs external shading, and that is a building decision  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] The manifold cabinet has temperature but no HUMIDITY, so its dew point  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] The dew-point pair list is duplicated between two HA template helpers  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] Generalise the lesson: alarm on DEGRADED INPUTS, not just bad outputs  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] ONE coupled Kalman filter over the whole house — owner's design  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*
  - [ ] `valve_*_actual` is named as if it were valve feedback. It is not  
        → LOGBOOK § *2026-08-08 — VL/RL calibration: three methods, three confounds, on*

### Sensors and alarms

  - [ ] Verify the three cabinet sensors during OPERATION before trusting them  
        → LOGBOOK § *MEASURED 2026-08-01: D-009 confirmed, and `settle_s` is ~20x too s*
  - [ ] The budget alarm has no hysteresis and flaps on the threshold  
        → LOGBOOK § *MEASURED 2026-08-01: D-009 confirmed, and `settle_s` is ~20x too s*

### Sleeping sensors

  - [ ] Size `room_temp_max_age_s` against the wake period  
        → LOGBOOK § *What that leaves*
  - [ ] Publish per-room sample age  
        → LOGBOOK § *What that leaves*
  - [ ] A normaliser on the PFC  
        → LOGBOOK § *What that leaves*

### Fan coil and emitter capacity

  - [ ] The hydraulic separation is worth more than it looked  
        → LOGBOOK § *MEASURED: the fan coil is worth ~2.5 K over slab, on identical wat*
  - [ ] More coil, or coil in Wohnzimmer  
        → LOGBOOK § *MEASURED: the fan coil is worth ~2.5 K over slab, on identical wat*
  - [ ] Relay control of the coil fan is a MODULATE-DOWN lever, not a capacity  
        → LOGBOOK § *MEASURED: the fan coil is worth ~2.5 K over slab, on identical wat*

### Air change rate

  - [ ] Get a CO2 sensor and run an overnight decay  
        → LOGBOOK § *2026-08-01 — the moisture balance does NOT identify `n`. It identi*
  - [ ] Do not fit `n` from moisture again without an independent `G`  
        → LOGBOOK § *2026-08-01 — the moisture balance does NOT identify `n`. It identi*

### Network

  - [ ] Find the loop  
        → LOGBOOK § *2026-08-08 — [!] both Modbus endpoints lost at once: a switch, pro*
  - [ ] Consider whether those two devices should share a path at all  
        → LOGBOOK § *2026-08-08 — [!] both Modbus endpoints lost at once: a switch, pro*
  - [ ] The aging dumb switch is a diagnostic dead end  
        → LOGBOOK § *2026-08-08 — [!] both Modbus endpoints lost at once: a switch, pro*

### Weather inputs

  - [ ] Which bucket scaling is right is unknown  
        → LOGBOOK § *Redundancy for the outdoor temperature specifically*

### Heat meter and procurement

  - [ ] ASK THE DISTRIBUTOR: does mains supply shorten the measuring /  
        → LOGBOOK § *REVISED 2026-07-29 (owner: mains is available at the meter) — go M*
  - [ ] MEASURE FIRST — three numbers, before contacting anyone  
        → LOGBOOK § *ACTION: heat meter enquiry — ready to send (written 2026-07-29 eve*
  - [ ] THEN send this  
        → LOGBOOK § *ACTION: heat meter enquiry — ready to send (written 2026-07-29 eve*
  - [ ] Expect ≈ €600–700 net and 4–5 weeks  
        → LOGBOOK § *ACTION: heat meter enquiry — ready to send (written 2026-07-29 eve*
  - [ ] Nothing else on the list is gated on this  
        → LOGBOOK § *ACTION: heat meter enquiry — ready to send (written 2026-07-29 eve*
