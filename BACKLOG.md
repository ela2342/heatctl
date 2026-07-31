# Backlog

**The single source of truth for open work.** If it is not here, it is not
tracked. No TODO comments in code, no "still missing" notes buried in prose —
those go stale silently and nobody greps for them.

Grouped by the milestone in `ROADMAP.md` they belong to. Each item says what it
is, why it matters, and what unblocks it, because an item whose rationale has
been forgotten cannot be prioritised — it just sits here.

Markers: `[ ]` not started · `[~]` partially done or blocked externally ·
`[x]` here means rejected, kept so it is not re-proposed.

### SHOPPING LIST — sourced and priced 2026-07-29 (≈ €3,142 gross)

**Not needed:** Möhlenhoff actuators (all on hand) · sensor pockets (fitted) ·
750-series modules (owner sourcing second-hand).

| # | Item | Part / spec | Qty | € gross | Supplier |
|---|---|---|---|---|---|
| 1 | Heat meter | **MULTICAL 403, qp 3.5, DN25 (G1¼B/R1), type `6`, supply `7`** | 1 | **~600-700 net, QUOTE** | energie-zaehler.com |
| 1b | Comms module | **Kamstrup Modbus RTU `HC-003-67`** (in the quote above) | 1 | incl. | same |
| 2 | ~~M-Bus master~~ | ~~solvimus MBUS-GE20M~~ **WITHDRAWN — see below** | — | ~~474~~ | — |
| 3 | Pump modules | **Wilo Connect RS485 `4268524`** | 2 | 597 | SHK wholesaler (list) |
| 4 | PT1000 probes | **2-wire**, Ø6 mm, 2 m silicone, class B | 10 | 130 | heizlando.de |
| 5 | Window contacts | **Eltako FTK** (solar, batteryless) | 8 | 568 | voelkner.de |
| 5 | EnOcean receiver | **USB 300** (not the WAGO module — see below) | 1 | 36 | unitronic / berrybase |
| 6 | Element control | **my-PV AC•THOR 9s** | 1 | 829 | geizhals (51 offers) |
| 7 | Element meter | Shelly Pro 3EM | 1 | 76 | eBay merchants |
| 8 | USB-RS485 | **Delock 62501**, 3 kV isolated, DIN rail | 1 | 112 | reichelt.de |
| 8 | Bus cable | Lapp UNITRONIC BUS LD 2×2×0.22, 20 m | 1 | 32 | — |

### CORRECTION — the M-Bus master line was badly over-specified

**Reject the solvimus MBUS-GE20M at €474.** It is a 20-load M-Bus → Modbus
TCP gateway, specified to read **one** heat meter. Owner caught it. The line
is withdrawn and the shopping-list total drops from ≈ €3,142 to **≈ €2,668**
before whichever replacement below is chosen.

| Option | Cost | Needs | Verdict |
|---|---|---|---|
| solvimus MBUS-GE20M | €474 | nothing | **reject** — 20 loads for 1 meter |
| **WAGO 753-649** used | **~€80–150** | **PLC200 + CODESYS** | **preferred once the PLC lands** |
| WAGO 753-649 new | €323 | same | only if no used unit appears |
| USB M-Bus master (TSS721) | **~€15–40** | Python M-Bus in heatctl | **unblocks today** |
| Kamstrup Modbus RTU module | ~€200 | **mains-powered meter** | see the trap below |

**WAGO 753-649 is the "nice 750 module" — with one hard condition.** It is the
M-Bus master for the 750/753 system, **40 slaves per module**, and WAGO ships
M-Bus libraries including one specifically for heat meters
(`M-Bus Wärmezähler`) with no restriction on meter make.

⚠️ **It does NOT work on the 750-352 alone.** WAGO's own guide requires
WAGO-I/O-PRO-CAA, i.e. a controller — the coupler cannot run the M-Bus stack.
On the bare coupler it degrades to a byte-wise mailbox in the process image,
which is the exact reason the 750-642 EnOcean module was rejected. **The
PLC200 already on order is what makes this module the right answer**, and it
is worthless before then. 40 slaves also leaves room for water and electricity
meters later, which the one-meter alternatives do not.

**The €30 answer that works today:** a TSS721-based USB M-Bus master on the
Linux host, with heatctl speaking M-Bus directly. M-Bus is a polled
request/response protocol, so unlike EnOcean there is no lost-telegram hazard
in a mailbox — you control when you ask. For a single meter this is entirely
adequate and carries no dependency on the PLC200 timeline.

⚠️ **Trap in the Modbus-RTU alternative.** Kamstrup does make a plug-and-play
Modbus RTU (RS-485) module for the 403, auto-detected, and it could share the
RS-485 run with the two Wilo pumps — but **it is powered from the meter's
230 VAC or 24 VAC supply, so it will not work with a battery meter.** Choosing
it means a mains-powered 403 plus 230 V at the meter position. That is a
wiring job and a different meter type code, and it is why this route is not
the recommendation despite looking tidy on paper.

⚠️ **Check what the €289 meter quote actually includes.** The communication
module is a digit in the 403 type code, so the price moves with it. Confirm
the quote is for the M-Bus variant before ordering, and re-confirm the
`403-T…6…` requirement (type 6 for the θhc heat/cool threshold) at the same
time.

**Recommendation:** buy the €30 USB M-Bus master now so the heat meter is not
gated on the PLC200, and watch kleinanzeigen for a 753-649 under ~€150 as the
permanent home once CODESYS is running. Do not buy the solvimus.

### REVISED 2026-07-29 (owner: mains is available at the meter) — go Modbus RTU

Mains at the meter position removes the only real objection, and the deciding
argument then is **not cost**:

> **heatctl already depends on pymodbus.** Modbus RTU over serial is the same
> library, the same idioms and the same failure handling as the existing
> `backends/modbus_direct.py`. Every M-Bus route instead means either a new
> Python M-Bus implementation to maintain for thirty years, or CODESYS work on
> the PLC200 plus a hard dependency on it. For a project whose stated premise
> is boring technology and a minimal pinned dependency set, adding a second
> metering protocol to read one meter is the expensive choice even when the
> hardware is cheaper.

**Decision: MULTICAL 403 with 230 VAC supply + Kamstrup Modbus RTU module,
on the same RS-485 run as the two Wilo Connect modules.**

Dropped entirely: solvimus MBUS-GE20M (€474), WAGO 753-649, USB M-Bus master.
Added: Modbus module ~€200. The Delock 62501 (3 kV isolated, DIN) already on
the list is the master, and it now carries three devices instead of two.

**Ordering specifics, confirmed from the type-code table:**

| Field | Value | Note |
|---|---|---|
| Supply | **digit `7`** — 230 VAC. **SETTLED 2026-07-29.** | The owner's 24 V is **DC**, and the type code offers only "230 VAC Supply 7" and "24 V**AC** Supply 8" — there is no 24 VDC variant, so digit `8` is out. No cost: the meter sits ~1 m from the panel, whose 230 V is present anyway to feed the 24 V PSU. Connection is **two-wire, no protective earth** per the datasheet — tell the electrician, it is not the usual three-core. |
| Modbus module | **`HC-003-67`**, ordered separately | The type-code Modules field lists only M-Bus (`20`/`21`) and wireless M-Bus (`30`) — **there is no Modbus digit**. The module is a plug-and-play accessory, auto-detected by the meter. |
| Meter type | **`6`** (non-MID) | Unchanged and still binding: θhc heat/cool changeover is "nur möglich mit Zählertyp 6". |
| Size | **qp 3.5, DN25 (G1¼B / R1)** | **CORRECTED** — see the DN25 correction below. |

Datasheet also confirms the 403 is explicitly a "heat meter, cooling meter or
**combined heat/cooling meter**" on the ultrasonic principle — the
bidirectional capability the plant needs.

**The meter sits within ~1 m of the controls**, which simplifies three things:

- **Mains is free.** A 1 m run from the panel means the 230 VAC supply costs
  no wiring work, so the supply requirement stops being an argument against
  the Modbus route entirely.
- **Termination and isolation stop mattering on the meter leg.** At 1 m and
  9600–19200 baud, RS-485 reflections are irrelevant. They still matter on the
  run out to the pumps, which is where the Delock's 3 kV isolation earns its
  place — motors and drives, not the meter.
- **A dedicated adapter becomes an option worth considering.** Consequence 1
  above (one bus as a single failure domain for pumps *and* meter) can simply
  be bought off for a second €112 adapter, giving the meter its own bus with
  no baud/parity negotiation against the Wilo modules. Not required — but if
  the pumps and the meter turn out to disagree on a comfortable baud rate,
  this is the cheap escape rather than a compromise setting.

**Consequences to design around:**

1. **One RS-485 run is now a single failure domain for both pumps and the heat
   meter.** Acceptable, and worth stating explicitly rather than discovering:
   this is layer-2 and telemetry data. The safety path stays on the WAGO node
   over Ethernet and is unaffected by anything on this bus.
2. **Daisy-chain, not star**, terminated at both ends. All three devices being
   in the plant room makes this easy — do not be tempted into a star because
   the cable runs are short.
3. **Baud rate and parity must agree across meter and pumps.** Kamstrup does
   300–115200 and addresses 1–247, with the **default address equal to the
   last three digits of the meter's customer number** — set it deliberately
   rather than inheriting that.
4. **Registers appear at two addresses**, as IEEE float and as 32-bit signed
   integer, 32-bit values spanning two registers. Pick one convention, write
   it into `docs/HARDWARE.md`, and do not mix them.
5. Battery and mains supplies are **interchangeable at any time**, so this is
   not a one-way door if the mains supply is ever inconvenient.

- [ ] **ASK THE DISTRIBUTOR: does mains supply shorten the measuring /
      integration interval versus battery?** Could not be confirmed from the
      datasheet — the text extraction was too mangled to trust and the figure
      was not found. It matters more than it looks: `Q_heat` freshness is the
      binding input on the layer-2 slab estimate (see `optimizer/params.yaml`,
      `heat_input`), so a meter that integrates over minutes is worth much
      less to the filter than one that updates every few seconds. Do not
      assume mains helps here just because it enables Modbus.

### CORRECTION 2026-07-29 — take qp 3.5 / DN25, not qp 1.5 / DN15

Owner: "Certainly DN25? Pump outlet to manifold input is all DN25." Correct,
and **the earlier DN15 recommendation was wrong for a reason worth recording:
I optimised a specification that never binds.**

The original argument rejected larger sensors because `qi` (minimum flow)
rises with `qp` — qp 2.5 giving qi 25 l/h against DN15's 15 l/h was called
"the wrong trade for an instrument". That is only a trade if the plant ever
operates near `qi`. **It does not, by two orders of magnitude.** At the heat
pump's minimum modulation of 1.0–1.1 kW and a 5 K spread, flow is
≈ **190 l/h**; even at an implausible 10 K spread it is 95 l/h. Against a
qi of 35 l/h there is no contest. I never checked the number I was protecting.

Flow-sensor options, from the type-code table:

| qp | Connection | Pipe | Length | Δp at our 1.24 m³/h | Code |
|---|---|---|---|---|---|
| 1.5 | R¾ | DN15/20 | 130 mm | **≈ 0.17 bar** | A0 |
| 2.5 | G1B (R¾) | DN20 | 190 mm | ≈ 0.06 bar | B0 |
| **3.5** | **G1¼B (R1)** | **DN25** | **260 mm** | **≈ 0.03 bar** | **D0** |
| 6.0 | G1¼B (R1) | DN25 | 260 mm | ≈ 0.01 bar | F0 |

(Δp scales as flow², from a nominal 0.25 bar at qp.)

**Three reasons DN25 wins, in order of weight:**

1. **Pressure drop, and it fights the control strategy directly.** qp 1.5 costs
   ≈ 0.17 bar at our measured 1.24 m³/h, against ≈ 0.03 bar for qp 3.5 —
   about **14 kPa saved**, a substantial fraction of the circulator's
   available head at this flow. This plant exists to *maximise* flow and
   minimise spread for COP (D-017). Fitting a restriction that eats a quarter
   of the pump head to gain resolution we cannot use is exactly backwards.
2. **No reducers.** DN25→DN15→DN25 puts two disturbances immediately either
   side of an ultrasonic transit-time sensor, which is the one place a flow
   profile most needs to be undisturbed. Matching the pipework removes the
   problem rather than managing it.
3. **Accuracy is not the trade it appears to be.** MID class 2 is
   ±(2 + 0.02·qp/q) %. At 1.24 m³/h that is **2.06 % for qp 3.5 against
   2.02 % for qp 1.5** — four hundredths of a percent, swamped by the ±10 %
   systematic already carried on the flow estimate this meter replaces.

⚠️ **Check the installation length before ordering: 260 mm** for qp 3.5,
against 130 mm for qp 1.5. That is the real constraint now, not the diameter.
Confirm the straight run between pump outlet and manifold input takes it,
*plus* the inlet/outlet straight lengths the sensor needs.

**Revised meter spec:** MULTICAL 403, **qp 3.5, G1¼B (R1) / DN25**, meter type
`6`, supply digit `7` (230 VAC), sensor pair Pt500 pockets, Modbus module
`HC-003-67` separately.

### ACTION: heat meter enquiry — ready to send (written 2026-07-29 evening)

- [ ] **MEASURE FIRST — three numbers, before contacting anyone.** Each one can
      invalidate the order, and all three are quicker to take than to correct
      after a 4–5 week lead time.

      1. **Pocket bore diameter and immersion depth**, both pockets. The
         fitted pockets decide the sensor part, and the stocked configurations
         ship Ø5.0 mm *direct-immersion* sensors that do not belong in a
         pocket at all. A sensor that is too short sits in an air gap and
         reads the pocket rather than the water — slow, plausible, and exactly
         the corruption that would poison the heat figure the layer-2 slab
         estimate depends on.
      2. **Straight run between pump outlet and manifold input**: needs
         **260 mm** for the qp 3.5 body *plus* the sensor's own inlet and
         outlet straight lengths. If it does not fit, the fallback is qp 2.5
         DN20 at 130 mm with reducers — worse, but not fatal.
      3. **Cable distance from each pocket to the calculator position**, to
         choose between the 1.5 m and 3.0 m sensor leads.

- [ ] **THEN send this.** energie-zaehler.com, **+49 9854 9799 820**,
      `info@energie-zaehler.com` — they stock combined heat/cooling 403s, so
      the configuration is familiar to them and they advertise Fachberatung.
      Alternates: zaehleronlineshop.de (has the DN25 mains body and sells a
      Modbus + 230 V combination, so they clearly configure), then
      stark-elektronik.de.

      > Angebot erbeten: **Kamstrup MULTICAL 403**, Konfiguration:
      >
      > - **Wärme-/Kältezähler, Zählertyp 6** (nicht MID — die
      >   θhc-Umschaltschwelle wird benötigt und ist laut Kamstrup
      >   "nur möglich mit Zählertyp 6")
      > - Durchflusssensor **qp 3,5 m³/h, G1¼B (R1) / DN25, Baulänge 260 mm**
      > - **Netzteil 230 V AC** (Versorgungscode 7), zweiadrig ohne
      >   Schutzleiter
      > - **Fühlerpaar für Tauchhülsen** (NICHT Direkteintauch) — Bohrung
      >   ⌀ ___ mm, Einbaulänge ___ mm; Kabellänge ___ m
      > - **Modbus-RTU-Modul HC-003-67** (RS-485)
      >
      > Bitte Lieferzeit, Tauchhülsen-Kompatibilität und den vollständigen
      > Typenschlüssel zur Gegenprüfung angeben.

      **Ask for the full type code back** and check it before paying: the
      three fields that have already gone wrong once each are meter type
      (`6`), supply (`7`), and the sensor pair (pocket, not direct).

- [ ] **Expect ≈ €600–700 net and 4–5 weeks.** Not the €289 quoted earlier —
      that was a stocked qp 1.5 DN15 wM-Bus unit, the right meter type in the
      wrong size with the wrong comms. Budget impact is about +€350 on the
      shopping list.

- [ ] **Nothing else on the list is gated on this.** The meter improves the
      layer-2 slab estimate; it does not block the 750-1606 work (2 → 12
      controllable circuits), which remains the best outcome-per-euro item.

### ORDERING REALITY CHECK 2026-07-29 — our configuration is not a stocked item

Searched the German vendors. **Nothing on a shelf matches the spec**, and the
€289 figure quoted earlier was for a different meter:

| What is actually stocked | Config | Price | Problem |
|---|---|---|---|
| energie-zaehler.com, €299 | qp 1.5 **DN15**, **wM-Bus**, heat/**cooling** ✓ | €299 | **this is where the €289 came from** — wrong size, wrong comms |
| zaehleronlineshop.de | qp 3.5 **DN25** ✓, 260 mm ✓, **230 V** ✓, no module | €479.85 gross / €403 net | **heat ONLY** — no cooling |
| zaehleronlineshop.de | qp 2.5 DN20, **230 V + Modbus RTU** ✓ | €498.99 gross | **heat ONLY**, and DN20 |

The pattern is consistent: vendors stock either the **heat/cooling** variant in
the small wireless configuration, or the **DN25 mains** variant as heat-only.
Our combination — qp 3.5 DN25 + heat/cooling type `6` + 230 VAC + Modbus RTU —
is **configure-to-order**, which also explains the 4–5 week lead times seen on
the non-stocked items.

**Budget correction: expect ≈ €600–700 net for the meter, not €289.** The
DN25 mains heat-only body alone is €403 net; heat/cooling and the Modbus
module are additions on top. The shopping-list total needs revising upward by
roughly €350 once a real quote lands.

**Preferred vendor: energie-zaehler.com.** They already stock combined
heat/cooling 403s, so the configuration is familiar to them, and they
advertise Fachberatung rather than being a pure catalogue shop.
Tel **+49 9854 9799 820**, `info@energie-zaehler.com`.
Second source: zaehleronlineshop.de (has the DN25 mains body and sells the
Modbus + 230 V combination, so they clearly configure). Third:
stark-elektronik.de.

⚠️ **Resolve before ordering — the temperature sensors.** The stocked DN25
listing ships **Ø5.0 mm direct-immersion** sensors on 1.5 m leads. This site
already has **pockets fitted** (recorded under "not needed" in the shopping
list), so the order must specify a **pocket sensor pair** instead, and the
pocket bore and immersion depth must be measured first. Ordering direct
sensors against fitted pockets means either they do not fit or they sit in
an air gap and read the pocket rather than the water — a slow, plausible,
hard-to-diagnose error of the exact kind that would corrupt the heat figure
the layer-2 slab estimate depends on.

⚠️ Also confirm **1.5 m vs 3.0 m sensor leads** reach from the pockets to the
calculator position, and that 260 mm of straight run plus the sensor's own
inlet/outlet straight lengths exist between pump outlet and manifold input.

### Corrections to my own specification

1. **`403-T` is a PREFIX, not a suffix.** The type code is
   `403-□ □□ □ □□ □□ □ □□`, and **T is the first digit** = Pt500 + cooling /
   heat-cooling. Saying "403-T" to a distributor is ambiguous — you need the
   whole string.
2. **Order meter type digit `6` (non-MID), and not just to save money.** Per
   Kamstrup's own word list the heat/cool changeover threshold **θhc is "nur
   möglich mit Zählertyp 6"**. Buy the MID version (type 3) and you lose the
   parameter that makes a combined meter behave sensibly in a bidirectional
   plant. Target: **`403-T…6…`**.
3. ~~**Take qp 1.5 in DN15, not DN20.**~~ **WITHDRAWN 2026-07-29** —
   the pipework is DN25 throughout and the `qi` argument this rested on
   never binds. See the DN25 correction above.
4. **PT1000 must be 2-wire.** The **750-463 is 2-wire only** on all four
   channels (the 2-/3-/4-wire part is the 750-461). 3- or 4-wire heads are
   wasted money. On Pt1000 the 2-wire error over 2 m is **~0.08 K** — it would
   be ~0.8 K on Pt100, which is where the technique's bad reputation comes from.
   ⚠️ **Check pocket bore before ordering: Ø6 mm probes need Ø6 mm+ pockets.**
5. **Wilo `4268524`, not `4263625`.** Not a pricing inconsistency — 4263625 is
   the outgoing **Modbus-only** part (one retailer quotes 191 working days, a
   discontinued-line signature); 4268524 is the current **dual-protocol**
   RS485/BACnet part, market availability 2026-07-01.
6. **EnOcean: Eltako `FTK`, and mind the family names.** FTK = solar,
   batteryless, **transmits status every ~20 min** — that is the heartbeat the
   design needs. **`FTKE` is the electrodynamic one to avoid**; `TF-FKB` is
   Eltako's proprietary Tipp-Funk, also avoid. `FTKB` (solar + backup battery)
   is worth the premium for deep or north-facing reveals.
   ⚠️ **Charge them in daylight for hours before fitting** or they look dead.
7. **Do NOT buy the WAGO 750-642 EnOcean module.** €440–541 against €36 for a
   USB stick, and it exposes only **3 data bytes plus a status byte** in the
   process image — a byte-wise mailbox. Reassembling and de-duplicating
   telegrams over polled Modbus TCP makes **a missed poll a lost telegram**,
   which is exactly wrong for a latched input with a 20-minute heartbeat. Put
   the USB 300 on the Linux host where the decode and the timeout logic live
   next to the rest of heatctl.

- [x] **VERIFIED 2026-07-29: no legacy HA automation writes to the plant.**
      Single-writer is intact; nothing needed disabling. Checked because
      `docs/HA_INTEGRATION.md` records that a lot of control logic still lives
      in Home Assistant, which made a second writer plausible.

      | automation | state | last fired |
      |---|---|---|
      | Climate: Prevent Condensation (Modbus fallback) | off | 27 Jul 13:55 |
      | Climate: Chilling Setpoint Supervisory Loop | off | 27 Jul 13:58 |
      | Heat pump: circulation pump request | off | 27 Jul 13:55 |
      | Steuerung der Wasserpumpe (einschalten) | off | 28 Jun |
      | Steuerung der Wasserpumpe (ausschalten) | off | 26 Jul |

      All five were disabled in the **same second** — 2026-07-28 23:25:42 —
      which is a deliberate cutover, not drift.

      Still enabled, and correctly so, because they are INPUTS rather than
      writers: `heatctl: bridge legacy wall units to MQTT (temperature +
      setpoint)` and `heatctl: publish indoor dew point to MQTT`. The first is
      the one that overwrites room setpoints every minute (see the pre-charge
      entry below); the second feeds the condensation guard, so disabling it
      would leave safety on its static fallback and stop cooling entirely.

      Worth re-checking after any HA restore from backup — a snapshot taken
      before 2026-07-28 23:25 would bring all five back enabled.

- [!] **`safety.setpoint_min_c: 15.0` is not a guard.** Owner flagged it
      2026-07-29. The comment above it says "layer 2 may only set setpoints
      WITHIN these bounds", which is exactly the scenario where the number has
      to be tight — and 15 °C is not.

      **In cooling a 15 °C room setpoint does not express a target, it expresses
      "run forever".** The plant cannot deliver a 15 °C room, so the setpoint is
      permanently unreachable: valves stay open, the water setpoint walks down
      to the condensation floor and stays there, and nothing ever signals that
      the goal was impossible. That is precisely the failure a clamp against a
      malfunctioning layer 2 exists to prevent.

      Same class of defect as the old `dew_floor_offset_c: 4.0` — a limit that
      reads like a safety bound and does not bind.

      **This needs per-mode bounds, and the numbers are the owner's call, not
      mine.** The physics only says the cooling floor must sit at or above what
      the plant can actually reach (~20 °C on this house); the heating floor is
      a policy question, because a winter vacation setback may legitimately
      want 16 while a normal heating minimum would be 18. A single symmetric
      pair cannot express that, and picking one number at midnight to make
      tonight work is how the last two bad constants got in.
      NOTE `safety.frost_protect_c` is separate and unaffected — pipe
      protection does not depend on this clamp.

- [!] **Room setpoints are NOT an available layer-2 lever while the Controme
      wall units own them.** Measured 2026-07-29 23:11: published 22.0 to
      `heatctl/set/setpoint/{gaestebad,wohnzimmer,arbeitszimmer}`, and **49
      seconds later the HA bridge automation republished 23.5 / 23.0** — it
      pushes the wall-unit dial value every minute regardless of change. This is
      already documented in a comment in `setpoint.py` ("the wall-unit bridge
      republishes the dial value every minute whether or not it moved"); I read
      it earlier the same evening and failed to connect it.

      Consequence for pre-charging: **the designed interface for aiming below
      comfort target is unavailable.** Options, in order of preference:
      1. **Give layer 2 its own offset**, applied by layer 1 on top of whatever
         the dial says, so the bridge and the optimizer stop fighting over one
         value. Needs the expiry discussed in DESIGN.md §2.2.
      2. Disable the bridge automation while pre-charging — works tonight,
         reversible, but leaves the dial and the plant disagreeing.
      3. Drive P04 (the water setpoint) directly and accept that the trim will
         raise it again once the rooms reach target, which is exactly the
         behaviour pre-charging needs to override.
      Option 3 is why this cannot be solved by writing a register: the trim
      correctly backs off when the house is satisfied, and "satisfied" is the
      wrong criterion the night before a 37 °C day.


### TIME CONSTANTS: the real eigenvalues are 55 h and 3.4 h, not 5.2 and 8.4

Computed 2026-07-30. **This corrects a figure quoted repeatedly through the day.**
`BuildingParams.time_constants_h()` returns PER-NODE constants — C over the sum of
that node's conductances — and its own docstring says they are "not the system
eigenvalues". They were nevertheless used all day as though they were.

| | slow mode | fast mode |
|---|---|---|
| true coupled eigenvalues | **55.2 h** | **3.4 h** |
| per-node figures quoted instead | (8.4 h "slab") | (5.2 h "air") |

**The slow mode, ~55 h, is the whole building drifting against outdoor.** It is
almost insensitive to the badly-known parameter: 52.8–58.9 h across a sixfold
range of `ua_sa`. So it is trustworthy, and it means the house integrates outdoor
conditions over **two and a half days**, not hours.

**The fast mode, ~3.4 h, is air and slab equilibrating with each other.** It is
directly proportional to `ua_sa` and therefore soft: 6.2 h at 500 W/K, 1.2 h at
3000.

**The consequence matters more than the correction.** The fast mode is how quickly
a charged slab discharges into the room. At 3.4 h, a slab charged at 07:00 has
transferred most of that charge by early afternoon — roughly two time constants
before the peak. **So overnight pre-charging helps the MORNING, not the afternoon
peak.** The energy arithmetic (22.3 kWh of excess, 15.3 kWh/K of capacity) is
correct but says nothing about *when* the stored coolth is released, and the
eigenvalue says: earlier than we need it. Charging closer to the peak would be
better, but the plant is already saturated by then. That tension is real and was
not visible from the per-node numbers.

### Provenance, per parameter — what is measured and what is guessed

| quantity | value | basis |
|---|---|---|
| `ua_ao` heat loss | 267 W/K | **MEASURED**, corroborated twice (winter data, and the summer H estimate) |
| `c_slab` | 8691 Wh/K | **COMPUTED** from as-built layers, 63.7 Wh/(m²K) × 136.40 m² |
| `c_air` | 6600 Wh/K | **DERIVED** as predicted total minus slab; the total is corroborated by measurement (15,700–18,300 against 15,300 predicted) |
| `ua_sg` slab→ground | 29 W/K | **COMPUTED** from as-built |
| **`ua_sa` slab→air** | **1000 W/K** | **GUESSED.** EN 1264's 10.8 W/(m²K) over 136.40 m², de-rated by a third. params.yaml has said "POOR - estimated, learn this one" since it was written |
| slow mode 55 h | — | computed; robust to the guess |
| **fast mode 3.4 h** | — | computed; **inherits the guess entirely** |

**Nothing has been identified from operating data.** The Kalman filter exists to
learn `ua_sa` from the innovation, and its acceptance gate — two weeks of
whiteness — has never been started. So every dynamic claim made today rests on a
survey plus one guessed conductance.

### The control time constants, for completeness

| | |
|---|---|
| water setpoint trim | 1 K per **30 min** (D-018), and reset by every restart |
| capacity controller raise | **10 min**; lowering immediate |
| Möhlenhoff actuator stroke | **150 s** |
| fan coil response | **seconds** — the one fast actuator |
| heat pump config poll | 300 s |
| forecast refresh | 30 min |
| optimizer cycle | 60 s |

### ⚠️ THERE IS NO PRE-COOLING SCHEDULE. It is not time-based at all.

Asked directly "when does pre-cooling start", the honest answer is that it does
not start — **the delta is recomputed every 60 s from the excess still ahead and
applied continuously.** There is no lead time, no ramp, and no notion of "begin
8 h before the peak".

It currently *works* overnight by accident: during the peak the delta asks for
temperatures the saturated plant cannot deliver, so it does nothing; overnight,
when spare capacity exists, it bites. Right behaviour, wrong reason — and it would
misbehave on a mild night before a hot day, where the plant could overshoot the
target with nothing to stop it but the absolute clamp.

- [ ] **A lead-time-aware delta is the missing piece.** It should ramp the offset
      in ahead of a forecast peak on the timescale the building actually
      responds — and per the eigenvalues above, that is the 3.4 h air/slab mode
      for delivery, not the 8 h figure used in the reasoning so far. The correct
      lead time is therefore SHORTER than assumed, which is the opposite of what
      was expected.
- [ ] Validating `ua_sa` would make the fast mode trustworthy. It is the single
      parameter that governs when stored energy arrives, and it is the one guess
      in the set.


### MEASURED: the fan coil is worth ~2.5 K over slab, on identical water

Prompted by the owner noticing Arbeitszimmer was comfortable, 2026-07-30 ~15:45,
at the day's peak with outdoor around 37–40 °C.

| room | emitter | now | target | over |
|---|---|---|---|---|
| Arbeitszimmer | **fan coil only, no slab** | 24.4 | 23.0 | **+1.4** |
| Wohnzimmer | slab | 26.9 | 23.0 | **+3.9** |
| Gästebad | slab | 24.8 | 23.5 | +1.3 |

**And Arbeitszimmer has the WORSE solar exposure** — upstairs, 31.2 m², east and
south glazing — so on fabric grounds it should be the hottest room in the house.
It is the coolest of the three relative to a comparable target.

**Circuit evidence, same supply water to both:**

| | valve | return | circuit ΔT |
|---|---|---|---|
| hk11 (coil) | **100 %** | **22.8** | **5.5 K** |
| hk01–hk10 (slab) | 100 % | 19.2–20.3 | ~2 K |

The coil is already flat out and extracting nearly three times the temperature
drop per unit flow that a slab circuit manages, on the same 17.3 °C supply.

**Why, and it is the design's own argument confirmed by measurement:** the coil
is 4.2 kW over 31.2 m² = **135 W/m² against the slab's 25–35**. DESIGN.md §6.1
already states the mechanism — cooling from above works *with* buoyancy while
floor cooling works against it, "which is exactly why the slab is limited to
25–35 W/m²". This is the first quantified check of that claim on this plant, and
it holds with room to spare.

⚠️ **A lever I expected to find is not there.** Arbeitszimmer being comfortable
suggested its room PID was throttling hk11, leaving spare coil capacity that the
Luftraum thermosiphon could push at Wohnzimmer. It is not: **hk11 is already at
100 %.** The coil is delivering everything slab-safe water allows, and lowering
Arbeitszimmer's setpoint would do nothing.

**What this actually argues for**, given the coil is the strongest emitter in the
house by a factor of four and is already saturated:

- [ ] **The hydraulic separation is worth more than it looked.** It is currently
      justified by the latent lever (dehumidify to raise the slab's limit). This
      measurement adds a second, larger justification: the coil could take water
      several K colder than the slab tolerates, and at 135 W/m² that capacity is
      immediately useful rather than a by-product. Feeding the coil cold and
      mixing up for the slab is the single largest capacity change available to
      this plant.
- [ ] **More coil, or coil in Wohnzimmer.** Wohnzimmer carries 28 m² of the
      house's 51 m² of glazing and is cooled by the weakest emitter available.
      That is backwards, and it is the room that failed today.
**ANSWERED (owner, 2026-07-30): the coil fan is three 230 V speed taps,
currently hardwired to HIGH.** So there is no unused airflow — the coil is
genuinely maxed on both of its actuators, valve at 100 % and fan at top speed.
Nothing more is available from it without colder water, which confirms the
hydraulic separation as the only real lever and closes the question above.

- [ ] **Relay control of the coil fan is a MODULATE-DOWN lever, not a capacity
      one.** Hardwired to high means it runs at full speed whenever there is flow
      — including overnight and when Arbeitszimmer needs nothing. Putting the
      three taps on relays buys noise, fan energy, and a second finer actuator on
      the strongest emitter for the times it is not needed. It buys no extra
      capacity, because high is already high.

      Three constraints if this is built:
      * **The three taps must be mutually exclusive** — energising two speed
        windings at once is a fault, not a compromise. The 750-517 gives two
        changeover contacts per module, so the interlock belongs in the wiring
        rather than only in software.
      * **Relay wear is the budget** (HARDWARE.md: mechanical relays, ~10⁵
        operations). Speed should follow a demand *level* and change rarely, not
        track a continuous controller.
      * **The coil responds in seconds against the actuators' 150 s**, so a
        cascade must treat the two timescales separately — the fan is the fast
        actuator in this plant and everything else is slow.


### PEAK INDOOR PREDICTION 2026-07-30 15:45 — the peak is now, ~26.9 °C

Closed-loop simulation, anchored on measured room air and slab, with the plant
holding the supply at the condensation floor so delivered cooling grows as the
slab warms.

| room | now | target | over |
|---|---|---|---|
| Gästebad | 24.8 | 23.5 | +1.3 |
| **Wohnzimmer** | **26.9** | 23.0 | **+3.9** |
| Arbeitszimmer | 24.4 | 23.0 | +1.4 |
| house mean | 25.4 | — | — |

**Predicted: the peak is NOW.** The simulation never rises above the current
temperature — it declines monotonically from here:

| local | house mean | Wohnzimmer (est) | Q_cool |
|---|---|---|---|
| 16:00 | 25.25 | 26.79 | 3.51 kW |
| 18:00 | 25.14 | 26.68 | 4.62 kW |
| 20:00 | 24.83 | 26.37 | 4.86 kW |
| 22:00 | 23.92 | 25.45 | 4.54 kW |
| 00:00 | 23.20 | 24.73 | 4.11 kW |

Two effects turn it over despite outdoor still at 37 °C: **solar is already
falling** (5.25 → 3.10 kW between 16:00 and 18:00, since east peaked in the
morning and south around noon), and **delivered cooling is rising** (3.5 →
4.9 kW) because the plant holds supply at the floor, so a warmer slab means a
bigger spread means more extraction. It is self-limiting.

**THIS CORRECTS MY OWN ESTIMATE OF AN HOUR EARLIER.** At 14:20 I extrapolated the
observed 0.24 K/h drift linearly to 20:00 and predicted a peak of −4.5 to −5 K.
That was wrong in method: the drift is not linear, because both the load and the
delivery move. A linear extrapolation of a self-limiting process overstates it.
The closed-loop simulation is the right tool and it says +3.9 K, now.

⚠️ **Wohnzimmer is estimated, not modelled.** Its +1.53 K offset from the house
mean is MEASURED and held constant through the run. The 2-state model is
whole-house by construction (DESIGN.md §6.1.1 — the per-room form needs the
Shelly sensors), so it cannot resolve the room that carries 28 m² of the house's
51 m² of glazing. The offset will in fact shrink as the sun moves west, since west
glazing is only 5 m² — so 26.9 is more likely a slight over-estimate than under.

### Afternoon status 2026-07-30 ~14:20 — the plant is at its physical optimum

| | |
|---|---|
| outdoor (HP sensor, reads high in sun) | 40.0 °C |
| compressor / ceiling | **59 Hz at a 60 Hz ceiling** — the ceiling IS the constraint |
| spread | 2.9 K |
| manifold supply vs limit | 17.3 vs 16.4 — **+0.9 K, on the controller's 1.0 target** |
| setpoint | 20, and the floor is 20 — saturated |
| valves | 100 % |
| house | **−3.54 K** and warming |

**Delivered cooling: 0.344 kg/s × 4180 × 2.9 K = 4.2 kW.** Predicted load for this
hour: **8.9 kW**. So the plant is moving less than half the load, which is why the
house is losing ground — and it is doing so with the supply pinned at the
condensation floor, the valves wide open and the frequency ceiling at the point
where raising it further would eat the margin. **There is nothing left in the
control system.**

**THE LOAD MODEL IS TRACKING, which is the encouraging part.** Predicted deficit
8.9 − 4.2 = 4.7 kW against 15.3 kWh/K of capacity gives **0.31 K/h** of expected
drift. Observed: −3.30 K at 13:00 to −3.54 K at 14:20, i.e. **0.24 K/h**. Within
the model's stated uncertainty, on a day it had never seen. That is the first
independent check of the layer-2 load calculation against reality and it holds.

**Expected trajectory:** the house keeps warming until the load falls below
~4.2 kW, which the forecast puts around 20:00 (3.86 kW). Peak indoor deviation
therefore lands early evening at roughly −4.5 to −5 K, then recovers overnight.

**The capacity controller has converged**, which is the right behaviour: 59 Hz
against a 60 Hz ceiling with 0.9 K of margin sits inside its 0.4 K deadband, so it
holds rather than hunting. It found the maximum spread this dew point allows,
which is what it was built to do.

**The remaining lever today is not in the plant.** Solar is ~5 kW of the 8.9 kW
load; external shading on the east and south glazing is worth more than the
entire cooling system. Everything else waits on lowering the indoor dew point,
which needs the hydraulic separation that is not built.

### SILENT COOLING MODE WORKS. The window is open. 2026-07-30 12:33.

Owner's call, and the right one. Three writes, in this order:

| addr | register | 	from → to |
|---|---|---|
| `0x00F4` | D09 max fan speed, silent cooling | **60 → 1000** |
| `0x00F1` | R32 max frequency, silent cooling | 70 → **45** |
| `0x0001` bit 5 | silent mode | off → **on** (9 → 41, bits 0 and 3 preserved) |

**ORDER MATTERS AND NEARLY WENT WRONG.** The owner asked to measure both the fan
speed and the register value rather than trusting the default. Measured:
normal-mode fan at 79–80 Hz runs **788–805 RPM**, and D09's silent cap was **60**
— same 0–1000 scale, so **7.5 % of normal, effectively stopped**. Enabling silent
mode without raising D09 first would have collapsed condenser heat rejection on a
38 °C day, spiking condensing pressure and very likely tripping a high-pressure
fault. The fan cap must be lifted BEFORE the mode bit, never after.

**Result, measured:**

| | uncapped | R32 = 45 |
|---|---|---|
| compressor | 79–80 Hz | **44–45 Hz** — capped exactly |
| leaving/return spread | 4.5 K | **1.4–2.5 K** |
| condenser fan | 788–805 RPM | **675–793 RPM** — unthrottled |
| manifold supply vs limit | 15.3 vs 16.0 — **breach** | **18.8 vs 16.0 — 2.8 K margin** |
| valves | forced shut | **hk01 modulating at 67 %** |

**R32 binds where R13 did not.** Same nominal purpose, different register, and
only the measurement distinguishes them — which is why the negative R13 result
was worth having rather than assuming.

**The window is open.** Floor = 16.0 + 2.3 = 19, setpoint 19, and the compressor
runs because 19 is under the return−2 ceiling. That is the first feasible
operating point of the day.

**Worth following up, not urgent:** manifold supply reads 18.8 while the machine
side shows a 2.3 K spread against a setpoint of 19 — so the manifold is much
warmer than the heat pump's leaving water, meaning real mixing or pickup between
the two. The condensation floor is computed from the MACHINE spread, so it is
over-conservative for protecting the manifold, which is what actually feeds the
slab. Quantifying that gap would buy back usable setpoint range.

- [ ] Silent-mode settings are now load-bearing. If the unit is ever factory
      reset or its panel used to toggle silent mode, D09 returns to 60 and the
      next cooling run throttles the condenser fan to 7.5 %. Worth an alarm on
      `hp/silent_max_fan_cooling` dropping below ~400.


### Options for reducing compressor output, ranked

Read out of the full register map 2026-07-30, after R13 tested negative.

**Incidental finding that settles an earlier question:**
`0x00F0` **R31 "Frequency increase of Powerful Cooling Mode" = ±30 Hz range,
default +5.** Powerful mode is a **+5 Hz trim**, not a cap release. That is why
clearing it had no measurable effect, and it independently confirms the
withdrawal of that claim — there was never a large effect to observe.

**A — silent cooling mode. RECOMMENDED.**

| addr | register | range | default |
|---|---|---|---|
| `0x0001` bit 5 | silent mode | — | off |
| `0x00F1` | **R32 Max Frequency of Silent Cooling Mode** | 30–120 Hz | **70** |
| `0x00F4` | D09 Max Wind Speed of Silent Mode in Cooling | 0–1000 | 60 |

Purpose-built, mode-specific, and the unit's own feature — so every protection
and every piece of modulation logic stays in play. Two writes, both trivially
reversible, and unlike R13 this register's *name* says it caps frequency in
cooling specifically.

Arithmetic: at R32 = 45 Hz against the 80 Hz observed, output roughly halves, so
the 4.5 K spread should fall to about 2.5 K. The floor becomes 16.0 + 2.5 = 18.5
against a 19.6 running ceiling — **the window opens for the first time today.**
That is the whole point; peak capacity is traded for a window that exists.

**B — R25–R28 upper limits of frequency adjustment** (`0x00CC`–`0x00CF`,
0–125 Hz, all at 125). ⚠️ **Ambiguous, do not touch first:** R21–R24, the
*lower* limits, are ALSO 125, which is a degenerate range and suggests 125 is a
"disabled" sentinel rather than an active ceiling. Worth understanding, not
worth guessing at.

**C — the frequency ladder R00–R11** (`0x00B8`–`0x00C3`, defaults ending 75, 80,
85, 90). Rewrites the unit's own staging table rather than a limit it consults,
so anything keyed to those steps moves too. More invasive; keep as a fallback.

**D — manual frequency** (`0x00B7`, 15–120, plus `0x0000` bit 2). Takes the
unit's modulation out of the loop entirely: maximum control, minimum protection,
and heatctl would then owe the plant a capacity controller it does not have.
Last resort.

**Why any of this matters**, restated because it is the crux: at a 15.0 °C dew
point and a 4.5 K spread the minimum safe setpoint is 20.5 while the maximum
runnable one is 19.6. No setpoint satisfies both, so the plant cannot cool
safely at all. Spread is the only variable in reach, and frequency is what sets
spread.


### R13 TEST RESULT: it does not bind. Clean negative.

Written 2026-07-30 11:03, observed 11:22–11:25.

| | |
|---|---|
| `0x00C5` R13 written | 80 → **50** |
| R13 read back after the config poll | **50.0** — the write stuck and persisted |
| compressor while running | **79–80 Hz** |

**R13 is set to 50 and the compressor runs at 79–80 Hz. It does not cap the
compressor**, at least not in cooling, despite `0x0001` bit 0
(constant temperature) being ON. The register named "Upper Limit of Constant
Temperature operating frequency" bounds some narrower function than the
frequency the unit actually climbs to.

⚠️ **Do not read anything into 79–80 versus the 85–89 seen earlier today.** The
operating point also changed (setpoint 19 and P08 zeroed, against a much larger
morning error), so attributing the difference to R13 would be exactly the
phase-confounding mistake already made once with `powerful_mode`. The only sound
conclusion from this test is the negative one: 50 is not enforced.

**Remaining candidate: the frequency ladder**, `0x00B8`–`0x00C3` = R00–R11
"Compressor Operating Frequency 1…12", defaults 30, 35, 40, 45, 55, 60, 65, 70,
75, 80, **85, 90**. This is the table the unit appears to actually step through.

- [ ] **If the spread problem is to be attacked through frequency, capping the
      ladder's upper entries is what remains.** It is more invasive than R13:
      it rewrites the unit's own staging table rather than a limit it consults,
      so any protection logic keyed to those steps changes with it. Worth doing
      deliberately, with the defaults recorded first so it is reversible:
      `0x00C2` = 85, `0x00C3` = 90, `0x00C1` = 80, `0x00C0` = 75.
- [ ] Also unexplained: what *does* enforce a ceiling? The unit reached 89 Hz
      this morning and 80 Hz now, and neither matches R13. Until that is known,
      any frequency intervention is guesswork.

**P08 zeroed at the same time**, confirmed reading 0.0. The +1 K
outdoor-dependent correction that had been shifting the effective target
underneath every setpoint is gone, so what heatctl commands is now what the unit
aims at.


### Read the frequency-limit registers. R13 does not appear to bind.

Named `0x0001`, `0x008D`, `0x0092`, `0x00C4`, `0x00C5` in the register map so they
could be read at all — they had been in the device the whole time, unnamed and
therefore invisible. Measured 2026-07-30:

| register | value | documented |
|---|---|---|
| `0x00C5` R13 upper limit, constant-temp operating freq | **80 Hz** | default 80 |
| `0x00C4` R12 lower limit | **30 Hz** | default 30 |
| `0x008D` P01 restart temperature difference | **2 K** | min 2 — at the floor |
| `0x0001` bit 0 constant temperature | **ON** | — |
| `0x0092` P08 water temperature compensation | **+1 K** | −5…15 |

**The contradiction: constant-temperature mode is ON and R13 is 80, yet the
compressor was measured at 85 and 89 Hz this morning.** R13 therefore does not
cap what its name suggests, at least not in cooling.

**The likely explanation is the frequency LADDER, not the limit pair.**
`0x00B8`–`0x00C3` hold R00–R11 "Compressor Operating Frequency 1…12" with
defaults 30, 35, 40, 45, 55, 60, 65, 70, 75, 80, **85, 90**. The observed 85 Hz is
exactly R10 and 89 is within a hair of R11. So the unit steps that ladder and
reaches its top two entries, which sit *above* R13 — meaning R12/R13 bound some
narrower "constant temperature operation" function rather than the ladder the
unit actually climbs.

**This is inference, not documented behaviour, and should be tested in the
cheapest order:**

- [ ] **Write R13 = 50 and observe.** One register, documented purpose,
      trivially reversible. If the compressor caps at 50, the question is
      answered and the spread problem has a one-register fix. If it still
      reaches 85, R13 provably does not bind and the ladder is the lever.
- [ ] Only then consider rewriting the ladder's top entries
      (`0x00C2`, `0x00C3`, and downward as needed). That changes the unit's own
      staging table, so it is the more invasive option and should not be first.

⚠️ **P08 is NOT zero — it is +1 K.** Believed disabled; it is not. So there is an
outdoor-dependent correction shifting the effective target by a kelvin
underneath every setpoint heatctl writes, which also means the setpoint we
command is not exactly what the unit aims at. Small, but it is a second writer
on the quantity this whole exercise is about, and it was invisible until the
register was named. Decide deliberately whether to zero it.


### THE OPERATING WINDOW IS ~0.5 K WIDE. This explains everything.

Found 2026-07-30 in `docs/PW58321_MODBUS.local.md`, which holds the **complete**
244-address RW capture. `docs/HEATPUMP.md` documents 17 rows and reads as though
that were the whole map — that presentation is the documentation defect, not the
capture.

```
0x008D  P01 Re-start Temperature difference of Heating/Cooling Mode  2 °C~18 °C  RW
0x008E  P02 Re-start Temperature difference of Hot water Mode        2 °C~18 °C  RW
0x0092  P08 Water Temperature Compensation                         -5 °C~15 °C  RW
```

**The dead zone is `0x008D`, and its documented minimum is 2 °C — it is already
at the floor.** Dropping it to 1 K is not available. That lever does not exist.

**What that means, and it is the structural diagnosis of this plant.** Two
constraints squeeze the cooling setpoint from opposite sides:

| | bound | now |
|---|---|---|
| condensation | setpoint ≥ limit + spread | 15.4 + 3.2 = **18.6** |
| restart dead zone | setpoint ≤ return − 2 | 21.5 − 2 = **19.5** |

**A window about 0.5 K wide.** Above it the compressor will not start; below it
the supply condenses. Every failure of the last twenty-four hours is this window
closing:

- **overnight idle (00:06–06:50):** setpoint bounced to 20 by a breach, return
  water settled at 20, and 20 is not ≤ 20 − 2. The unit could not start at all.
- **09:14 → 3 K overshoot:** a 0.1 K breach jumped the setpoint to 21, putting it
  above the window again. Same trap.
- **the "restart differential" observed at 21:00 the previous evening** — return
  21.6 against setpoint 20, idle — was exactly this, 1.6 K short of the 2 K
  the register requires.

**The unit therefore cannot hold a setpoint; it can only chase one, and it
always lets the house drift ~2 K warm before it will start.** That is not a
control defect and no tuning fixes it.

**The only lever that widens the window is SPREAD**, because spread is what eats
it from below. Every kelvin of spread removed is a kelvin of window. F10 = 2
holds the pump at full flow, which is the part already won; the rest of the
spread is compressor frequency, and frequency is driven by the error, so a
larger error means a wider spread means a narrower window. That is a positive
feedback into the failure.

- [ ] **P08 water temperature compensation (`0x0092`, −5…15 °C) is unexplored**
      and is the outdoor-dependent setpoint correction the owner mentioned. On a
      day like this it could shift the setpoint with outdoor temperature without
      heatctl writing anything, which is worth understanding before adding more
      control on top of it.
- [ ] **Re-audit `docs/HEATPUMP.md` against the full capture.** 17 rows of 244
      presented as a map is how the dead zone stayed invisible for a day.


- [!] **WITHDRAWN: clearing `powerful_mode` was not shown to cap the compressor.**
      Claimed 2026-07-29 evening on the strength of a coincidence, and the
      evidence does not survive the next morning.

      **The disproof:** `powerful_mode` is still off, and at 06:50 on 2026-07-30
      the compressor ramped to 85 Hz anyway.

      **How the wrong conclusion was reached, because the shape of the mistake
      is worth keeping.** The flag was cleared at 21:39. Between 21:43 and 21:49
      the compressor sat at a steady 39-40 Hz with a 2.0-2.5 K spread, and that
      was read as the effect. But 20 minutes earlier, with the flag still ON, it
      had run 16 → 49 → 89 Hz. The difference was not the flag: at 21:17 the
      unit was in a **pull-down** after the setpoint dropped 20 → 19, and by
      21:43 it had reached target and was **modulating at steady state**. Two
      phases of the unit's own control cycle, mistaken for a before/after.

      **Consequence for everything downstream:** frequency is driven by the
      error, not by that flag, and the spread follows frequency. So the
      2.0-2.5 K spread measured that evening was a steady-state figure and is
      NOT what the plant sees during a pull-down - the measured value the next
      morning was **3.2 K**. Every calculation that assumed 2.2 K understated
      the setpoint-to-supply gap, which is part of why repeated pushes to 16,
      17 and 18 all breached.

      **What still stands:** the F10 = 2 change is separately demonstrated - the
      pump held 100 % against the 90/80/70/60/50 throttling seen on two baseline
      cycles, which is a direct before/after on a quantity the flag cannot
      touch.

      Re-test `powerful_mode` properly if it matters: hold the setpoint constant
      and well below return water so the unit stays in pull-down, then toggle
      the flag. Comparing across phases of its own control cycle proves nothing.


### THE OVERNIGHT PRE-CHARGE FAILED. Measured 2026-07-30 morning.

Owner: "almost no cooling overnight". Correct. Compressor history:

| local | compressor |
|---|---|
| 00:00–00:06 | 39 → 31 → **0 Hz** |
| 00:06 – 06:50 | **off**, apart from one ~1 min blip at 03:44 (16 Hz) |
| 06:50 | restarts, ramps to 85 Hz |

**6 h 44 min idle on the night before a 38 °C day.** Slab evidence: return
circuits read 19.6–21.8 now against 18.9–22.1 at 21:00 the previous evening —
**essentially unchanged. Zero slab charge stored.**

**Compound cause, and only part of it is a control defect.**

1. **The condensation limit genuinely capped it.** At a ~13.8 °C dew point the
   limit was 14.8–14.9, and the measured setpoint-to-supply gap was ~3.2 K, so
   the coldest sustainable setpoint was ~18 — and 18 breached by 0.1 K at
   23:55. Attempts at 16, 17 and 18 were all correctly bounced to 20 by the
   guard. There was very little room, and pretending otherwise would be wrong.
2. **Once at 20, the unit would not run at all.** Return water settles at the
   setpoint, and a return at 20 against a setpoint of 20 is below the machine's
   own restart differential — the same behaviour already recorded the previous
   evening as "heat pump idle does not mean no demand". So the plant sat idle
   rather than trickling.
3. **The trim had no signal to lower it, and this is the real defect.** Free
   drift cooled the AIR to target, so `wants_more` was false and the capacity
   branch never fired. The trim watches air temperature; the thing that needed
   charging was the slab. **A controller that cannot see the slab cannot
   pre-charge it**, and no amount of tuning fixes that.
4. Compounding it: every deploy re-seeds the 30 min settling timer, and there
   were six deploys that evening. The trim had almost no authority anyway.

**What this proves about the design, not just the night.** Reactive control on
air temperature is structurally incapable of storing energy, because "the air is
comfortable" and "the mass is charged" are different states and only one of them
is measured. The layer-2 offset would have carried the intent; what it needs to
act ON is a slab estimate, which is the filter's job and is still waiting on a
heat meter.

- [ ] **The trim needs a slab-referenced mode for pre-charging**, not just an
      air-referenced one. Until then pre-charge is a manual act.
- [ ] **Consider whether the setpoint should ever sit where the unit will not
      run.** A setpoint equal to the return water is a no-op that looks like
      control; something should notice and say so.


### The setpoint correction tomorrow's forecast implies (computed 2026-07-29 ~24:00)

The optimizer produces the **energy** requirement (22.3 kWh, 1.46 K equivalent)
and stops there. It does not convert that into a water setpoint. Done by hand
with the same 2-state model, from air 24.2 / slab 21.0 over the 7 h to dawn:

| Q_cool | air | slab | air kWh | slab kWh | **stored** |
|---|---|---|---|---|---|
| 0 W | 21.44 | **21.59** | +18.2 | **−5.1** | **+13.1** |
| 1000 W | 21.21 | 20.98 | +19.7 | +0.1 | +19.9 |
| 2000 W | 20.98 | 20.38 | +21.2 | +5.4 | +26.6 |
| 3000 W | 20.75 | 19.77 | +22.7 | +10.7 | +33.4 |
| 5000 W | 20.30 | 18.56 | +25.8 | +21.2 | +46.9 |

**The trap: free drift alone stores only 13.1 kWh of the 22.3 needed, because
it cools the AIR and WARMS the slab.** The air node (6.6 kWh/K, 5.2 h) drops
2.8 K unaided, falls below the slab, and the slab then feeds heat *into* it —
21.0 → 21.59 — cancelling 5.1 kWh of the air's 18.2 kWh gain. Reading air
temperature alone says the pre-charge is free. It is not: **only active cooling
charges the slab, and the slab is 8.7 of the 15.3 kWh/K.**

This is also why last night's drift, which the mode flip reacted to, looked like
success and was not: the air had cooled, the slab had not.

**Required: ~1.5 kW sustained, i.e. hold the setpoint at the condensation floor
all night.** Floor right now is 17 °C (limit 14.9 + measured spread 2.2), and it
falls as the indoor dew point falls. Currently commanded 18.

⚠️ **The reactive trim will undo this around 02:00–03:00.** Its efficiency
branch backs off once the house is satisfied and the valves go idle — and by the
model the air reaches comfort target then, with four hours of useful slab
charging still available. "Satisfied" is the wrong criterion the night before a
37 °C day, and no reactive rule can know that.

**In setpoint terms that is the whole gap: hold ~18 °C versus the ~21–22 °C the
trim will choose.** Three to four kelvin, worth roughly 17 kWh of slab charge.
That is precisely what the layer-2 offset would carry, and tonight it needs a
human to hold the number.


### PREDICTED LOAD for 2026-07-30 (the 37 degC day) — computed 2026-07-29

First real use of the layer-2 model: Open-Meteo forecast + per-facade solar +
measured building physics, hourly, house held at 24 degC.

| local | T_out | fabric | solar | NET |
|---|---|---|---|---|
| 09:00 | 24.4 | +0.11 | +4.90 | +4.95 |
| 12:00 | 33.0 | +2.40 | +6.54 | +8.88 |
| 15:00 | 37.2 | +3.53 | +5.47 | **+8.95** |
| 16:00 | 37.9 | +3.71 | +5.26 | +8.92 |
| 19:00 | 36.2 | +3.26 | +2.43 | +5.63 |

**Daily cooling load 94.1 kWh, peak 8.95 kW, nine hours above the source limit.**

**CORRECTED — the fan coil was omitted from the first version (owner caught
it).** Capacities per docs/HARDWARE.md:

| | kW |
|---|---|
| Slab, 136.40 m2 at 25–35 W/m2 | 3.4 – 4.8 |
| **Fan coil** | **4.2** |
| Total emitter | 7.6 – 9.0 |
| **Heat pump at ~11 degC supply** | **5.7 ← binding** |

The first version compared against the slab alone and concluded the plant was
emitter-limited. It is not — it is **source-limited**, which is what
HARDWARE.md already says. The difference is material:

| ceiling used | excess to store | pre-charge needed |
|---|---|---|
| slab only, 4.8 kW (wrong) | 31.4 kWh | 2.05 K |
| **source, 5.7 kW (right)** | **22.3 kWh** | **1.46 K** |

**The coil removes 9.1 kWh of tomorrow's deficit** — not by adding capacity
beyond the source, but by letting the plant actually *reach* the heat pump's
5.7 kW instead of being stuck at the slab's 4.8.

⚠️ **The coil's 4.2 kW rating assumes water far colder than the slab can take.**
On the current single-header hydraulics it sees the same slab-safe supply
(~16 degC), so its real sensible output tomorrow is well below 4.2 kW and is
NOT quantified here. Treat 5.7 kW as the ceiling because the source binds
first, not because the coil is delivering its rating.

⚠️ **The latent lever is unavailable on current hydraulics** (D-, owner's
correction 2026-07-28): dehumidifying needs the coil at 8–11 degC while the
slab needs ≥14.5, and all eleven circuits share one header with only two
actuators fitted. So the dew point cannot be attacked tomorrow — it will rise
through the day as it did today, tightening the slab limit exactly when the
load peaks.

**Three conclusions, in order of leverage.**

1. **Solar is 61 % of the peak** — 5.47 kW against 3.53 kW of fabric gain at
   15:00. External shading on the east and south glazing is worth up to ~3.8 kW,
   **which is more than the whole plant can deliver.** Nothing in the control
   system comes close. This is the answer.
2. **Pre-cool overnight: 22.3 kWh, i.e. ~1.46 K of whole-building drawdown**
   (capacity 15.3 kWh/K). Overnight load is negative from 22:00 to 07:00, giving
   **16.3 kWh free** — about 1.07 K — so the plant only has to find the last
   ~6 kWh at the lowest setpoint the dew point allows.
3. **24 degC will not hold through the afternoon.** Nine hours above the source
   limit is a capacity fact, not a control problem. The goal is a small, late
   excursion.

**This reframes the 05:56 mode flip.** The overnight cooling that made the house
1.10 K "too cold" is ~16 kWh of stored cooling — most of tomorrow's required
pre-charge. auto_mode saw an asset, called it a fault, and would have spent
energy destroying it.

### F10 (`0x010B`) IS THE LEVER — the unit is holding a 5 K spread on purpose

Owner's question, 2026-07-29: "Can we adjust the target spread? I'd rather have
a 2 K spread at low compressor setting than cycling." **Yes — and the measured
behaviour says it matters more than expected.**

`0x010B` = F10 DC pump inlet/outlet ΔT setting, range **2–30, currently 5**,
writable. It modulates the **circulation pump** to hold that spread.

**It is actively throttling flow to build spread.** Measured 19:43–19:52:

| time | pump | compressor | spread |
|---|---|---|---|
| 19:43 | 90 % | →85 Hz | — |
| 19:44 | 80 % | 85 Hz | **5.7–5.8 K** |
| 19:49 | 70 % | 79→40 Hz | 5.0→4.1 |
| 19:50 | 60 % | 40 Hz | 2.6–3.2 |
| 19:51 | **50 %** | 39 Hz | 2.4–3.0 |
| 19:52 | 100 % | 0 Hz (stopped) | — |

As the compressor winds down the unit **cuts the pump to 50 %** to keep ΔT near
its 5 K target. Flow therefore falls to roughly 0.2 l/s, close to the unit's
own 0.16 l/s minimum.

**Three reasons this is the wrong policy for this plant:**

1. **It directly contradicts D-017.** heatctl's entire distribution strategy is
   "maximise flow, minimise spread" for COP and even emitter temperatures. The
   heat pump is doing the opposite one layer upstream, and winning.
2. **It consumes the condensation budget.** P04 targets RETURN water, so
   leaving water sits a full spread below the setpoint. At ΔT 5.7 K that is
   5.7 K of headroom spent on the unit's own ΔT policy — and condensation is
   governed by the leaving water. This is the dominant reason the limit bound
   all afternoon.
3. **5 K is a radiator-era default.** Underfloor emitters want low ΔT and high
   flow. Nothing in this plant benefits from a wide spread.

**Expected effect of F10 = 2:** spread roughly halves, so leaving water rises
~3.5 K for the same setpoint, and the pump stops being throttled at low
compressor speed. That converts almost directly into usable setpoint range —
the plant could then run *colder* water and deliver *more* cooling without
breaching, which is the opposite of today's outcome.

**Risk assessment: low.**
- Fully reversible, one register, documented range 2–30.
- Higher flow stays inside the unit's 0.16–0.40 l/s window (100 % ≈ 0.40).
- Lower ΔT across the plate exchanger is if anything *better* for compressor
  duty and COP; it is standard practice for underfloor systems.
- One flash write, against a 30/hour budget.

⚠️ **What this does NOT fix.** Minimum modulation is 1.0–1.1 kW, so when the
load is below that the unit must still cycle — see docs/HEATPUMP.md, which
records that the *overnight* cycling was min-modulation-limited and not a
control fault. Today's afternoon behaviour is a different problem: not too
little load, but the unit rushing to 85 Hz and then holding a wide spread.
Do not conflate the two.

#### F10 test — baseline and method (write applied 2026-07-29 21:01)

`heat pump 0x010B: 5 -> 2 (mqtt)` at 21:01:12, read back from the device as
2.0 at 21:01:17. One flash write.

**Baseline, F10 = 5** (two independent cycles, both before the change):

| | cycle A 19:43–19:52 | cycle B 20:18–20:27 |
|---|---|---|
| pump speed | 90→80→70→60→**50 %** | 90→80→70→60→**50 %** |
| compressor | 85 → 39 Hz | ramp-down |
| peak spread | **5.7–5.8 K** | — |
| cycle period | ~34 min, ~21 min off | ~34 min |

Whole-day baseline, F10 = 5: **14 condensation breaches**, house deviation
degraded −0.32 → −1.25 K, valves at 100 % throughout, dew point 12.1 → 14.1.

**What to compare on the next hot day**, in order of what actually matters:

1. **Peak spread.** Should fall from ~5.8 K toward ~2 K. This is the direct
   effect and the one that must be seen before believing any of the rest.
2. **Leaving water against the condensation limit.** The point of the exercise:
   a smaller spread should lift leaving water for the same setpoint, so
   breaches should become rare. Near-zero breaches is success.
3. **Pump throttling.** Should stop stepping down to 50 % as the compressor
   winds down; the unit should hold flow instead of trading it for spread.
4. **Compressor cycle count and minimum sustained frequency.** The hope is
   longer, gentler runs. ⚠️ But see the min-modulation caveat — below the
   1.0–1.1 kW floor the unit must cycle whatever F10 says, so judge this
   metric ONLY on a day with real load, never overnight.
5. **House deviation.** The outcome that matters, but the slowest and noisiest
   — do not read it before the four above.

⚠️ **Do not change `powerful_mode` until this test has had a full hot day.**
Changing both makes neither attributable, and the unit ramping to 85 Hz on
every cycle is a separate hypothesis with its own separate test.

⚠️ **Evening and overnight data will NOT settle this.** The load after ~20:00
is at or below minimum modulation, which is exactly the regime where the unit
cycles regardless. A quiet night proves nothing either way.


#### F10 = 2 RESULT (2026-07-29 21:17–21:22) — half the hypothesis confirmed

Forced a test by writing the cooling setpoint 20 → 19 at 21:16:56, because the
compressor had been idle for 50 minutes with return water 1.6 K **above** its
setpoint and the house 1.17 K too warm.

**Finding 1 — the setpoint was what held the machine off.** The compressor
started **22 seconds** after the write. So the unit has a restart differential
it was not meeting at 21.6 vs 20.0, and the plant can sit idle with real demand
simply because the setpoint is too close to the return water. Worth knowing
independently of F10: **"heat pump idle" does not mean "no demand"**.

**Finding 2 — F10 = 2 works, on the pump.** The pump held **100 % throughout**,
against the 90→80→70→60→50 % throttling seen on both baseline cycles. The unit
no longer trades flow for spread. That is a real win for distribution (D-017)
even though it is not the win that was being chased.

**Finding 3 — and it does NOT cap the spread.** Spread still reached
**4.7–4.9 K** against 5.7–5.8 baseline: about 1 K, not the ~3.5 K hoped for.
Because with the pump already at maximum, ΔT = Q/(ṁ·c) and ṁ is pinned — so the
spread is set by **compressor output alone**, and the compressor ramped to
**89 Hz**.

Confirmed by the guard firing on cue: at 21:21:59 leaving water 16.0 against a
16.4 limit, setpoint jumped 19 → 20. The new constraint memory recorded
`blocked ≤ 19 @ 16.4` and will not re-attempt 19 until the limit falls — its
first live exercise, behaving correctly.

**Conclusion: the binding lever is compressor frequency, not the pump.**
`powerful_mode` (`0x0001` bit 4, currently **ON**) is promoted from speculation
to the evidenced hypothesis: the unit ramps to 85–89 Hz on every single cycle,
and at maximum flow that frequency *is* the spread. F10 has removed the pump
from the equation, so a `powerful_mode` test is now cleanly attributable
against this as the new baseline.

⚠️ **Expect a real trade.** Lower frequency means less capacity per unit time.
That is likely net positive while the plant is condensation-limited rather than
capacity-limited — which is what today's data says — but it is a genuine
trade-off and not a free win. Test it on a day with real load, and watch house
deviation, not just spread.

**Keep F10 = 2 regardless.** Holding flow at 100 % is right for this plant
independently of what happens to the spread.


- [ ] **Set F10 = 2 and observe for a day**, comparing: peak spread, leaving
      water against the condensation limit, number of setpoint breaches, and
      compressor cycle count. If breaches fall to near zero the constraint
      memory added in D-029 will rarely engage, which is the desired outcome —
      it exists to handle a constraint we would rather not hit at all.
- [ ] Also worth investigating: **`powerful_mode` is currently ON**
      (`0x0001` bit 4). The unit ramps to 85 Hz on every cycle. If that flag
      raises the frequency ceiling, clearing it would give longer, gentler runs
      and a naturally smaller spread. Undocumented in the manual extract we
      have, so test it deliberately and separately from F10 — changing both at
      once makes neither attributable.

- [ ] **The setpoint→supply gap is DYNAMIC and nothing in layer 1 measures it.**
      Recorded 2026-07-29 after an attempt to exploit it was withdrawn the same
      day.

      P04 targets **return** water; condensation is about the water reaching
      the slab. The gap between them is the leaving/return spread, which varies
      with **flow, load and compressor modulation** — it is not a constant, and
      `dew_floor_offset_c` must never be tuned as though it were.

      **How the withdrawn attempt went wrong, because the failure mode is
      subtle and will recur.** 14 samples from the day's breaches gave a mean
      offset of −3.21 K with sd 0.25 — convincingly tight. It was an artefact
      of **selection**: every sample was taken *at a breach*, and a breach
      occurs precisely when the leaving water is low relative to the setpoint.
      That is the large-spread tail, sampled at one operating point (pump
      100 %, all valves open, peak load) — not the distribution. A tight sd on
      a conditioned sample says the *condition* was consistent, not that the
      quantity is.

      Tightening the floor on that estimate would have made the plant less
      capable at low load, where the spread is genuinely small and colder water
      is safe, while adding no safety: the measured-leaving-water branch
      already covers the real limit, on the right quantity.

      **The proper fix** is to measure the spread live — heatctl already reads
      both P04 and the leaving water (0x8012) every cycle — and let the floor
      track it. That would make the clamp bind honestly instead of being
      decorative. It is safe to attempt because the clamp is a backstop: a bad
      estimate degrades to today's behaviour, not to condensation.
      **Sample it across the whole operating envelope, not at breaches**, or it
      will reproduce exactly the bias above.

### DEFECT 2026-07-29 — the water-setpoint trim limit-cycles against the condensation limit

**14 complete oscillations between 12:24 and 20:19**, in a perfectly regular
pattern, while the house lost ground all afternoon.

```
12:24  19 -> 18   house -0.32 K, valves 100%  "not enough capacity"
12:31  18 -> 19   leaving water 14.5 below limit 14.7  "jumping"
13:01  19 -> 18   house -0.36 K
13:07  18 -> 19   leaving water 14.5 below limit 14.8
...
20:14  20 -> 19   house -1.25 K
20:19  19 -> 20   leaving water 16.0 below limit 16.4
```

House deviation degraded **monotonically through every one of them**:
−0.32 → −0.36 → −0.43 → −0.50 → −0.58 → −0.62 → −0.76 → −0.87 → −0.98 →
−1.11 → −1.17 → −1.22 → −1.25 K.

**Mechanism.** Two controllers with no knowledge of each other:
- the capacity trim sees "house warm + valves at 100 %" and steps the water
  setpoint **down** 1 K (D-018 rate limit: one step per 30 min);
- ~6 minutes later the leaving water crosses the condensation limit and the
  trim's own guard steps it straight back **up**;
- 30 minutes later, the timer expires and it tries the identical step again.

Period ≈ 36 min, of which **~30 min is spent 1 K warmer than the plant could
actually sustain**. The trim re-attempts a step it has just been told is
infeasible, on a timer, without recording *why* it failed.

**Fix: constraint memory, not a slower timer.** When the condensation limit
rejects setpoint S at dew point D, S is infeasible *for that dew point* — and
retrying it 30 minutes later with D unchanged (or risen, as it did all day)
cannot succeed. Retry must be triggered by **the constraint moving**, not by
the clock: re-attempt when the dew point falls, or when the measured leaving
water shows headroom against the current limit. This is ordinary anti-windup;
the trim is integrating against a saturated actuator and forgetting the
saturation between attempts.

⚠️ Do **not** "fix" this by widening the trim's own guard band or slowing the
retry. Both would hide the oscillation while leaving the plant sitting even
further from the achievable setpoint — the loss is already in the 30-minute
wait, and lengthening it makes the loss larger, not smaller.

### The day was CONDENSATION-limited, not capacity-limited

The more important finding, and it is a plant property rather than a bug.

**Indoor dew point rose +2.0 K through the day**: 12.1 (09:01) → 12.6 (11:15)
→ 13.1 (13:28) → 13.6 (15:49) → 14.1 (17:52). The cooling supply limit tracked
it exactly: 14.1 → 16.1 °C.

So the floor's usable supply temperature **rose by 2 K over the course of the
day, while the cooling load was peaking**. The heat pump was never the
constraint — valves sat at 100 %, the compressor had headroom, and every
setpoint reduction was rejected by the dew point rather than by the machine.

This is structural: **radiant floor cooling cannot dehumidify.** It is required
to stay above the dew point, so latent load accumulates all day and tightens
the very constraint that limits sensible cooling. The consequence is that the
plant is weakest exactly when it is needed most, and no control change fixes
it. The levers are dehumidification, ventilation with drier air (unavailable at
31 °C outdoor), or accepting the shortfall.

### What worked

- **Zero valve overrides all day** — no `vl_undertemp`, no failsafe, no sensor
  faults. The D-023 release hysteresis has now run a full hot day with no
  chatter, and the soft setpoint trim absorbed the constraint before the hard
  valve guard ever had to fire. That is the intended layering.
- **Distribution and the flow floor** held every owned circuit at 100 % under
  peak demand without hunting.
- Overnight the trim correctly *relaxed* 22 → 25 °C with valves at 0 %, rather
  than over-chilling into an empty demand.

### This is the case for the layer-2 planner

The plant entered the hot day with an uncharged slab and spent the whole day
behind. The dew point was **12.1 °C at 09:00 and 14.1 °C by 18:00** — meaning
the cheapest, coldest, least condensation-constrained hours were **overnight
and early morning, before anyone needed cooling**.

A planner that pre-cooled the slab overnight against the forecast would convert
the morning's 2 K of extra dew-point headroom into stored cooling capacity for
the afternoon, when that headroom no longer exists. That is precisely the
storage-and-retrieval problem in DESIGN.md §8, and today is the measurement
that justifies it: **the constraint is not the machine, it is when the
constraint binds.**

### Layer 2 — first cut shipped 2026-07-29 (WP-F scaffold, observe-only)

- [x] **`optimizer/` exists and runs.** Own process, MQTT only, allowed to
      fail. `venv/bin/python -m optimizer.main ./config.yaml`.
      46 tests, no new runtime dependencies (pure-Python linear algebra and
      `urllib`, deliberately — the dependency set is part of the 30-year
      promise).

- [x] **It structurally cannot steer the plant.** Every publish goes through
      `_publish()`, which prefixes `heatctl/opt/` and raises on any attempt to
      escape the namespace; `heatctl/set/#` is unreachable from layer 2 and a
      test holds it. This is not staging discipline — DESIGN.md §2.2 records
      that `ControlPlane` applies commands immediately with **no receive
      timestamp and no expiry sweep**, so a layer 2 that hung after sending a
      setpoint would leave the house steered by its last thought indefinitely.

- [x] **Whole-house 2-state model, not the per-room 3-state one.** DESIGN.md
      §6.1.1 is explicit that the 3-state form needs the per-room Shelly H&T
      sensors and is otherwise unidentifiable; today only two rooms have any
      air measurement. Modelled time constants: **air 5.2 h, slab 8.4 h.**

- [x] **Per-facade solar, at the measured true azimuths.** Replaces a lumped
      aperture. Beam and diffuse are separated (projecting GHI onto a vertical
      window with a cosine is meaningless under overcast), solar position is
      computed hourly, and the survey's flat 0.9 non-perpendicular factor is
      deliberately NOT applied on top — solar.py computes the real incidence.
      Effective aperture **16.10 m²**, i.e. the earlier lumped 8 m² guess was
      out by a factor of two.

      Live check, a clear summer day: east peaks 08:00 UTC at 4.2 kW, south
      12:00 at 3.5 kW, west 16:00 at 1.1 kW. **60.4 kWh/day through the
      glazing, 6.37 kW peak**, against a 3.31 kW steady-state demand to hold
      21 °C at the coldest hour ahead. Solar gain is roughly twice the design
      heating load — the owner's instinct that solar dominates is confirmed
      with a wide margin.

- [ ] **Two weeks of innovation whiteness is the next gate** (WP-F). The
      filter records innovations and publishes mean/sd/lag-1 for exactly this.
      Expect the daytime residual to be the first thing to move, because
      `f_sol` (the air/floor split of solar gain) is a guess.

- [ ] **Known weak inputs, in order.** Each is a named parameter with its
      confidence in `optimizer/params.yaml` rather than a buried constant:
      1. **`Q_heat`** — no heat meter, so delivered heat is a calibrated
         current fit times a flat seasonal COP. DESIGN.md §6.1.1 calls flow
         "a model prerequisite, not an accounting nicety". The MULTICAL 403 on
         the shopping list retires this. Slab process noise is set high to say
         so.
      2. **`ua_sa`** (slab→air, 1000 W/K) — estimated, not surveyed.
      3. **`f_sol`** (0.30) — a guess.
      4. **house air = mean of two rooms** — a biased estimate of a
         seven-room house, knowingly used as one.

- [ ] **Before layer 2 may command anything:** command TTL + expiry sweep in
      `ControlPlane` (DESIGN.md §2.2), then WP-H's planner. Do not shortcut
      the order — the existing two set topics are already TTL-less, and adding
      more without it makes them strictly less safe.

### Milestone 0 - bring-up (manual, no code)

- [~] Hardware: the **2x 750-559 arrived and are fitted** (2026-07-27,
      positions 9 and 10), so there are now 16 analog outputs - enough for all
      12 circuits plus spares.
      **UPDATE 2026-07-29: the actuators are NOT the blocker - they exist.**
      All the Möhlenhoff Alpha 5 survived the surge event and are on hand;
      only 2 are physically on the manifold (Gästebad circuit 1, Wohnzimmer
      circuit 2). **The blocker is 0 V terminals**: the 750-559 does not
      provide enough, so fitting all 12 needs the **750-1606** potential
      distribution module - or a jury-rigged common 0 V rail.
      That makes this a **cheap blocker in front of a large win**: one module,
      or an afternoon with a terminal block, converts 2 controllable circuits
      into 12 and takes the house from 2 rooms under real control to 7. It is
      probably the highest ratio of outcome to cost anywhere on this list.
      If jury-rigging: the 0 V rail must be a *proper* common reference, not a
      daisy chain through actuator terminals - voltage drop along a shared
      return shifts every actuator's effective command, and the error grows
      with the number of units and their position in the chain. That failure
      would look exactly like a mis-calibrated actuator, which is a debugging
      hole we do not need.
      A module arriving is not an actuator being fitted; keep `fitted:` in
      config.yaml honest about the difference.
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

## ua_sa identified, and the lead time it implies (2026-07-30)

`ua_sa` was a **guess of 1000 W/K that sat above a directly measurable upper
bound** for as long as nobody measured it. Identified from operating data at
16:53 (plant in steady operation, manifold dT 2.10 K at 1.24 m3/h = 3020 W,
room mean 25.37 against water mean 19.20):

    UA(room -> water) = 3020 / 6.17 = 490 W/K

No flow split is needed for that figure, which is why it is the one adopted:
the 2-state model has no coil node, so every watt leaving the rooms into water
passes through `ua_sa` by construction. Stripping the coil out by assuming it
takes a proportional share of flow puts the slab alone at 256-355 W/K, but that
rests on a flow split nobody has measured.

**Consequence: the fast coupled mode is 6.35 h, not the 3.4 h recorded earlier
today.** That REVERSES the conclusion recorded alongside it. The note saying
"the correct lead time is therefore SHORTER than assumed, which is the opposite
of what was expected" was itself wrong - it was arithmetic on a guessed
parameter. With a 6.3 h fast mode an overnight charge does survive to the
afternoon peak, so overnight pre-charging is vindicated after all.

Two errors in a row here, in opposite directions, both from quoting a number
without asking what it rested on: first per-node time constants quoted as system
eigenvalues, then correct eigenvalues computed from a parameter that was never
measured. `optimizer/model.eigen_time_constants_h` now exists so the modes are
never hand-derived again, and `tests/test_optimizer_leadtime.py` pins both.

Caveats on the 490, none of which move it by more than about 20 %: the assumed
flow carries +-10 % systematic (COP-map-derived, no heat meter - the MULTICAL
403 retires this), the room mean covers 3 of 7 rooms, water mean stands in for
the slab node temperature, and the plant was not strictly at steady state.
Re-identify once the heat meter is in.

### The lead time is now derived, not scheduled

The delta was applied flat: recomputed every 60 s from the excess still ahead,
with no notion of WHEN that excess arrives. A hot spell twenty hours out
demanded exactly as much pre-cooling as one two hours out. It only behaved
overnight by luck - the plant is saturated during the peak and so ignores the
delta then.

First attempt weighted each hour by `exp(-dt / tau_fast)` - the survival of an
impulse of charge. **That is the wrong actuator model and was caught on
validating it against tonight**, before it ran unattended. The controller does
not inject a lump of coolth and walk away; it holds a depressed setpoint and
replenishes continuously. Held charge does not decay, only abandoned charge
does. The impulse form gave weights of 0.07-0.24 through the night against a
15:00 peak - about 0.05 K of pre-cooling - and only ramped up mid-morning, by
which time the rising load has eaten the plant's spare capacity. Overnight is
the ONLY time this house has spare capacity, so that is worse than the flat sum
it replaced.

Corrected to a **lead horizon**: full weight within `2 * tau_fast` (12.7 h),
tapering with `tau_fast` beyond. Both from the identified parameters, neither
hand-picked. Against a 15:00 peak the weight is 1.00 from 06:00, 0.95 at 02:00,
0.51 at 22:00 and 0.27 at 18:00 the previous evening - the delta ramps in
through the evening and is at full strength for the whole night. What this buys
over a flat sum is a horizon at all: excess two days out no longer demands
pre-cooling tonight.

Both wrong forms are pinned by mutation-verified tests (flat weights, and the
impulse decay) in `tests/test_optimizer_leadtime.py`.

### Found while testing: solar, not air temperature, breaks the budget

At 38 degC outdoor with no sun the house needs **4.0 kW against a 5.7 kW
plant** - it fits. It is the ~3 kW of glazing gain that pushes it over. Worth
holding onto when reasoning about hot days: the air temperature in the forecast
is not the thing to watch.

### Open: opaque-envelope solar is not modelled at all

`solar.py` computes per-facade gain through GLAZING only. `ua_ao` is driven by
air temperature, so there is no sol-air term - the roof and sunlit walls are
treated as if they were shaded. Rough size at solar noon (alpha 0.6, h_o 25):

    roof   UA 24.0 W/K, sol-air +17.2 K  ->  413 W
    wall S UA  7.7 W/K, sol-air +10.8 K  ->   83 W
    wall W UA  9.5 W/K, sol-air +12.0 K  ->  114 W
                                    total ~610 W

About 12 % of the peak load, systematically biasing the peak prediction LOW,
and concentrated in the afternoon (the W wall peaks late). The roof is the bulk
of it and is nearly massless (41.8 kg/m2 timber), so it arrives at the air node
with little lag. Two things cut it: the flat-roof PV shades part of the roof,
and at night the same roof radiates to the sky for about -94 W of free cooling
that is equally unmodelled. `alpha` for the trapezoidal sheet is unknown and is
the dominant uncertainty - worth a look at the actual roof colour before
implementing.

## No cooling overnight: Arbeitszimmer sets the limit, and a wrong fix for it (2026-07-31)

**Symptom.** Compressor ran briefly 23:00-01:00 then sat at 0 Hz until past
09:00 - through exactly the hours the optimizer was asking for pre-cooling
(-0.46 to -0.50 K) and the only hours with spare capacity and the best COP.
Wohnzimmer's 0.7 K overnight fall was passive loss to a 19.7 degC night.

**Mechanism.** The plant was stuck 0.6 K below its own restart threshold:

    water setpoint   21.0   (saturated at its floor)
    return water     22.4
    restart dead zone 2.0 -> needs return >= 23.0

heatctl reported this itself: `water_setpoint_saturated = on`, and
`water_setpoint_decision = "house -3.63 K and valves at 100% - not enough
capacity (already at the limit)"`.

**A WRONG DIAGNOSIS WAS SHIPPED AND REVERTED. Read this part before touching
the dew point reference.** The HA helper takes a max() over four
temperature/humidity pairs. The fourth, `fineoffset_wh32_245`, was assumed from
its name to be the outdoor weather station and removed - "restoring documented
intent". The reference fell 17.1 -> 15.7, the limit fell with it, and the
compressor started, which looked like a clean confirmation. It was not.

**The compressor start was a coincidence, and the timestamps prove it:**

    09:47:13   compressor 0 -> 14 -> 50 Hz       <- started on its OWN
    10:07:38   limit 18.2 -> 16.7                <- the change lands
    10:07:43   setpoint 21.0 -> 20.0             <- the only real effect
    10:12:05   supply bottoms at 18.7
    10:13:38   limit back to 18.1                <- revert

The machine restarted twenty minutes BEFORE the change, when return water
crossed the 2 K dead zone as the day warmed - which had been predicted in this
very session at 09:05 ("should restart around 10:00") and then not connected to
the evidence an hour later. Exposure was six minutes; supply bottomed at 18.7
against a true limit of 18.2 and an actual dew point of 17.1, so it never went
below the true limit and no condensation risk was realised.

WH32-245 is the **Arbeitszimmer** sensor. `config.yaml` uses that exact topic as
the room's `room_temp_topic`. Hourly means from the same night settle it:

    WH32-245   26.4 26.4 25.8 25.3 25.3 25.4 25.5 25.7   <- does not swing
    WH65B-210  22.1 18.9 17.4 17.3 19.5 20.9 22.4 24.2   <- genuinely outdoor

A sensor that does not follow the diurnal swing is indoors. And it did not need
deriving from data at all: `config.yaml` REGISTERS that topic as
Arbeitszimmer's `room_temp_topic`, and `docs/BUILDING.local.md` carries a
floor-by-floor room table. Both were in the repository the whole time.

With the wrong version live the plant drove supply toward a limit 1.4 K too low
and the capacity controller was actively raising frequency to push it further;
measured margin at revert was 0.70 K against a 1.0 K target.

**The lesson is not "check sensor names".** The wrong version produced exactly
the effect that had been predicted for it - dewref down, compressor starts - and
that agreement was taken as confirmation. It confirmed nothing: the prediction
followed from removing ANY high-reading member of a max(), whatever it measured.
The identity of the sensor was never tested, only its effect. The check that
settled it - does this sensor track the outdoor diurnal swing - costs one
history query - and was not even necessary, because the repository already
recorded the answer.

**Both errors that day had one cause: inferring a fact from a name while ground
truth sat unread.** "Elternschlafzimmer" was asserted to be upstairs because
bedrooms usually are; BUILDING.local.md says EG. "fineoffset_wh32_245" was
assumed outdoor because Fine Offset make weather stations; config.yaml
registers it to Arbeitszimmer. The owner's question about the first is what
surfaced the second. **When ground truth exists - floor plans, the register
map, config.yaml, an entity registry - read it. A name is a hypothesis.**

**THE ROOT CAUSE WAS OCCUPANCY, AND IT WAS NOT DISCOVERABLE FROM THE DATA.**
Owner, 2026-07-31: somebody slept in Arbeitszimmer that night and switched the
fan coil's fan off. That is the whole explanation, and the numbers agree - a
sleeping adult emits roughly 40 g/h of moisture, so eight hours in that ~81 m3
room is ~320 g into ~97 kg of air, about 3 g/kg of humidity ratio. AZ at 17.1
degC dew point sits near 12.2 g/kg against the ground floor's ~10.2. Occupancy
alone accounts for the entire 2.6 K gap. With the fan off there was neither
circulation to disperse the moisture nor a cold coil surface to condense it back
out.

So Arbeitszimmer's dew point was a TRANSIENT, not a property of the room, and
the earlier text here claiming it "legitimately carries the highest dew point
because warm moist air collects via the Luftraum" was a plausible-sounding
story fitted to one night's data. The Luftraum coupling is real (BUILDING.local
.md) but it is not what happened here.

**The systemic finding, which is the part worth keeping.** One person sleeping
in one room with one fan switched off raised that room's dew point ~2.6 K, which
raised the condensation floor for the ENTIRE plant, which held the water
setpoint above the compressor's restart dead zone, which stopped cooling for the
whole house on the night before a 33 degC day:

    person + fan off -> AZ dew 17.1 -> floor 17.1 + dew_floor_offset_c 4.0
    = 21.1 -> setpoint ~21 -> restart needs return >= 23.0 -> return sat at
    22.4 -> plant idle 01:00-09:47

The dew point reference is a `max()`, so by design the most humid room governs
everywhere. That is correct for condensation safety and has a nasty consequence:
**any single room can veto cooling for the house, and nothing currently notices
which room is doing it or why.** The plant published `water_setpoint_saturated =
on` all night and no-one could tell from that which room was binding.

**Open: put the fan coil's fan under control.** DEFERRED - needs a cable pulled
(owner, 2026-07-31), so not a same-day job. The coil has three 230 V speed
inputs and is currently hardwired, and there are spare 750-517 relay outputs on
the WAGO. Running the fan when its own room is the binding constraint both
disperses the moisture and condenses it out on the coil, which is the only
actuator in the house that can lower a room's dew point. Today the room that
limits the plant is something heatctl can be blocked by but cannot act on.
Prerequisites and cautions:
  - The cable run. Not started.
  - Interlock: never run the fan with the coil below the room dew point unless
    the condensate path is known good - check whether this unit has a tray and
    a drain at all before commanding anything.
  - Single-writer rule applies to the relay outputs as it does everywhere else.

**DONE 2026-07-31: publish WHICH room sets the limit.** The reference is a
max() and heatctl only ever saw the scalar, so it said how cold the water may
be but never because of whom. Added `sensor.system_dew_point_source` (HA
template helper, entry `01KYVPHCT3F5JNCP6DX3943WHC`) returning the argmax room
name, republished to `heatctl/env/dew_point_source` by its own automation.

Two deliberate choices. The publisher is a SEPARATE automation from the dew
point one rather than a second action inside it: that one is on the safety path
and a diagnostic addition must not be able to take it down. And the pair list,
the Magnus constants and the validity filter are duplicated verbatim from the
reference - **if they ever drift apart this will name the wrong room, which is
worse than naming none.** Change both together.

Verified at first read: source `Arbeitszimmer`, reference 17.2, Arbeitszimmer's
own computed dew point 17.18. Gaestebad 14.00, Wohnzimmer 15.35,
Elternschlafzimmer no data - a 3.2 K spread across the house, still unclear
hours after the occupancy ended because the fan is still off.


### Also found, not yet fixed: the Wohnzimmer wall unit is sunlit

From 06:32 it read 25.44 -> 29.06 in 87 minutes - **2.5 K/h against the ~0.2 K/h
the thermal load can actually produce** - with a clean dip at 07:32-07:45 and a
resumed climb, which is a cloud crossing the sun. Air in a 6600 Wh/K space
cannot do that. It is direct beam on the unit via the ESE facade at 106.3 deg,
the largest glazed elevation at 21.54 m2, which `optimizer/params.yaml` already
documents as catching sun early.

So Wohnzimmer's room PID chases a sensor reading roughly +3.5 K of sunshine for
a few hours each morning. Needs shading or relocation; until then, consider
falling back to return-temperature control for that room during the affected
hours. Gaestebad is unaffected and believable.

## WP-S · Setpoint authority: one owner per actuator (planned 2026-07-31)

Implements D-030. **Not an afternoon.** Staged so every stage ships something
that stands on its own and can be stopped after, because the plant runs a
house and a half-migrated controller is worse than either end state.

### What we actually need — two questions, one answer each

Everything below follows from separating two questions that are currently both
answered in several places at once:

    "How cold MAY the water be?"     -> a CONSTRAINT. Safety-critical, fast,
                                        measured, layer 1, evaluated ONCE.
    "How cold SHOULD the water be?"  -> an OBJECTIVE. Slow, model-based,
                                        forecast-driven, layer 2, one writer.

The objective, written down once so constants can be derived from it instead of
chosen (D-030 rule 3):

    minimise    room comfort error
    subject to  T_supply >= T_dew + margin          (hard, condensation)
                device limits (write budget, restart hysteresis, freq range)
    preferring  the warmest water that still meets demand   (COP)
    penalising  P04 moves                                   (flash wear)

Move suppression is a PHYSICAL constraint here, not a tuning knob - which is
what makes this closer to MPC-with-move-penalty than to PID, and why
`docs/DESIGN.md` 8 already names linear MPC as planner v2. Layer 2 holds the
identified model, the estimator and the forecast; layer 1 holds the envelope.

### Stage 0 — DONE 2026-07-31: demote the coarse floor to a fallback

This stage was planned around a premise that turned out to be false. The plan
said `_spread_est` decays toward optimism while the compressor is off, so the
constant had to stay until the estimator was fixed. **It does not** —
`main.py:705` passes `None` when frequency is 0 and `observe_spread` returns
before decaying, so the estimate already holds. The premise was taken from the
decay term without reading the caller, which is the same mistake as the WH32
identification earlier the same day.

The constant was guarding against nothing; it simply assumes 3 K of spread
against a plant now producing ~2.2 K. `max()` removed,
`dew_floor_offset_c` is now reached only when no spread has ever been measured
or the limit is absent. Recovers ~0.8 K of floor at the live numbers (derived
20.4 vs constant 21.2). `tests/test_setpoint_floor.py` pins both directions and
is mutation-verified against restoring the `max()`; the old
`test_the_dynamic_floor_can_only_tighten_the_static_one`, which pinned the
defect as a requirement, is replaced.

### Stage 1 — evaluate the constraint once

Compute `supply_limit` and `P04_min` in one place per cycle and pass them to
both the setpoint and capacity controllers, which currently each derive their
own view of the same limit.

  - Pure refactor. **Gate: no behavioural change** - pin current outputs with
    tests first, then move the code, then prove the tests still pass.
  - Publish `P04_min` and the name of the binding term as telemetry. Today
    nothing says whether the floor, the guard or the demand is in charge; the
    dew point argmax work of the same day proved how expensive that blindness
    is.

### Stage 2 — layer 2 emits the P04 request

Optimizer publishes a water-setpoint request on `heatctl/set/...` with a TTL.
Layer 1 clamps it to `>= P04_min`, applies its own rate limit, and ignores it
when stale.

  - **The independence rule is the gate**: pull the optimizer's plug and the
    house must still be safe and warm. Test with layer 2 killed, with layer 2
    publishing garbage, and with layer 2 publishing a value below `P04_min`.
  - Layer 2 gets the comfort/COP/forecast trade-off because that is where the
    model is. Layer 1 never gains a model.

### Stage 3 — demote the trim, delete the referees

With one objective and one owner there is nothing left to arbitrate.

  - Trim becomes the layer-2-is-dead fallback, unchanged in behaviour. A
    one-step-per-30-min rule is good degraded behaviour; it was only wrong as
    the primary.
  - Remove the reversal guard, the constraint memory and `breach_jump_c` **only
    where the structure makes them unreachable**, and keep every regression test
    (D-029's limit cycle, the 08:20 reversal, the start-up ratchet). A test that
    survives the deletion of its guard is the proof the structure fixed it; one
    that fails means the guard was load-bearing and the structure is not ready.

### Stage 4 — re-derive what remains

Every surviving constant gets a device limit, a measurement, or a derivation
from identified dynamics, and says which. Known targets: `raise_interval_s: 600`
is ~5x slower than its own 1-3 min process and should come from the write budget
and the process time constant; `step_hz: 5.0` is ~0.37 K of supply movement at
the measured ~0.074 K/Hz and wants to be smaller; `interval_s: 1800` and
`step_c: 1.0` want deriving from the 6.35 h fast mode rather than taste.

### Out of scope

The floor-circuit cascade (`docs/DESIGN.md` 4) is separately designed and is not
touched here. This work package is only about who decides the water temperature.
