# Logbook

**What happened, measured, and what we believed at the time.** Investigations,
incidents, experiments and their results, in the order they were written. Split
out of `BACKLOG.md` on 2026-08-21, where 4 500 lines of this had accumulated
around the ~1 700 lines of actual open work and made both hard to use.

Read this when you want to know **why a number is what it is**, whether
something has already been tried, or what a plant excursion looked like from
the inside. Nothing here is a task list.

Three rules, so it stays useful:

- **Append, do not revise.** An entry is what was believed on its date. When it
  turns out to be wrong, write a new entry saying so and strike the old
  heading - several already read `~~like this~~ — WRONG, <date>`. Silently
  correcting a log destroys the record of how the mistake was made, and this
  project has learned more from those than from the successes.
- **No open work lives here.** Anything actionable belongs in `BACKLOG.md`,
  which is the only place it is tracked. Checkbox markers were demoted to plain
  bullets during the split for exactly that reason: a `- [ ]` in here would be
  a task nobody is watching. The 55 that were still open moved to the backlog.
- **Principles graduate.** When an entry establishes a rule rather than a fact,
  it becomes a `D-nnn` in `docs/DECISIONS.md`, and this keeps the evidence
  behind it.

Device facts belong in `docs/HARDWARE.md`, `docs/HEATPUMP.md` and
`docs/PFC200.md`; where a measurement below has hardened into device truth,
those files carry the fact and this carries how it was obtained.

Roughly chronological, 2026-07-29 onward — the order entries were written.

---

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

- **ASK THE DISTRIBUTOR: does mains supply shorten the measuring /
      integration interval versus battery?** Could not be confirmed from the
      datasheet — the text extraction was too mangled to trust and the figure
      was not found. It matters more than it looks: `Q_heat` freshness is the
      binding input on the layer-2 slab estimate (see `optimizer/params.yaml`,
      `heat_input`), so a meter that integrates over minutes is worth much
      less to the filter than one that updates every few seconds. Do not
      assume mains helps here just because it enables Modbus.

### 2026-08-01 — the flow floor is COMMAND-SIDE and cannot see a stuck valve

Sharpens the case for a real flow measurement above, with evidence.

`Demand.enforce_flow_floor` reasons entirely about percentages heatctl asked
for. It has no measurement, so it cannot distinguish "commanded 100 % and
flowing" from "commanded 100 % and spring-closed". On the night of 2026-07-31
all ten actuators sat shut on an undersized 24 V supply (see the new section in
`docs/HARDWARE.md`) while the proxy would have computed a comfortable 100 %
open and actual flow was **zero**.

Worse, neither setting of the `fitted` flag models that state:

- `fitted: false` treats the circuit as permanently open pipe worth 100 %
- `fitted: true` trusts the commanded percentage

Both therefore over-report flow when an actuator is fitted but not moving.

**So Er03 — the heat pump's own flow switch — is currently the only real
protection against zero-flow operation.** That is a hardware interlock doing
safety work that the controller believes it is doing, which is exactly the kind
of quiet delegation worth writing down. Until a flow sensor exists, do not
strengthen any claim about `min_open_pct` beyond "it stops heatctl throttling
itself into a fault", and never treat it as evidence that flow exists.

### 2026-08-01 — actuator travel times vary widely; D-017 assumes they do not

Owner, fitting the last eight: *"it seems not all of the valves react at the
same speed... the rest varies wildly too"*, singling out circuit 9. The
datasheet nominal is 150 s full stroke.

`distribution.py` normalises the whole demand set (D-017) on the assumption
that a commanded percentage maps to a comparable opening across circuits. That
holds in steady state — the APV variants self-calibrate their travel — but not
during transients, where circuits with different travel times reach different
actual openings from the same normalised command. With a 1 s control loop and
150 s+ strokes, the plant spends a lot of time in that transient.

Unblocked by nothing; needs measurement. The per-channel sweep
(`tools/commission_valves.py`) already records enough to estimate per-circuit
response times as a by-product.

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

- **MEASURE FIRST — three numbers, before contacting anyone.** Each one can
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

- **THEN send this.** energie-zaehler.com, **+49 9854 9799 820**,
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

- **Expect ≈ €600–700 net and 4–5 weeks.** Not the €289 quoted earlier —
      that was a stocked qp 1.5 DN15 wM-Bus unit, the right meter type in the
      wrong size with the wrong comms. Budget impact is about +€350 on the
      shopping list.

- **Nothing else on the list is gated on this.** The meter improves the
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

- **A lead-time-aware delta is the missing piece.** It should ramp the offset
      in ahead of a forecast peak on the timescale the building actually
      responds — the FAST coupled mode, not the slow one, so the correct lead
      time is SHORTER than the 8 h originally assumed.
      **Do not quote the number here.** It is `eigen_time_constants_h(bp)[1]`
      and it moves with `ua_sa`: this entry said 3.4 h, `estimator.py` said 8 h,
      and the code derived 5.62 h at the same time (2026-08-01). Three prose
      copies of one derived quantity, all disagreeing — the exact failure
      D-031/D-032 exist to prevent. `estimator.setpoint_delta` already does this
      correctly, taking `2 × τ_fast` as its lead horizon from the function.
- Validating `ua_sa` would make the fast mode trustworthy. It is the single
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

- **The hydraulic separation is worth more than it looked.** It is currently
      justified by the latent lever (dehumidify to raise the slab's limit). This
      measurement adds a second, larger justification: the coil could take water
      several K colder than the slab tolerates, and at 135 W/m² that capacity is
      immediately useful rather than a by-product. Feeding the coil cold and
      mixing up for the slab is the single largest capacity change available to
      this plant.
- **More coil, or coil in Wohnzimmer.** Wohnzimmer carries 28 m² of the
      house's 51 m² of glazing and is cooled by the weakest emitter available.
      That is backwards, and it is the room that failed today.
**ANSWERED (owner, 2026-07-30): the coil fan is three 230 V speed taps,
currently hardwired to HIGH.** So there is no unused airflow — the coil is
genuinely maxed on both of its actuators, valve at 100 % and fan at top speed.
Nothing more is available from it without colder water, which confirms the
hydraulic separation as the only real lever and closes the question above.

- **Relay control of the coil fan is a MODULATE-DOWN lever, not a capacity
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

- Silent-mode settings are now load-bearing. If the unit is ever factory
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

- **If the spread problem is to be attacked through frequency, capping the
      ladder's upper entries is what remains.** It is more invasive than R13:
      it rewrites the unit's own staging table rather than a limit it consults,
      so any protection logic keyed to those steps changes with it. Worth doing
      deliberately, with the defaults recorded first so it is reversible:
      `0x00C2` = 85, `0x00C3` = 90, `0x00C1` = 80, `0x00C0` = 75.
- Also unexplained: what *does* enforce a ceiling? The unit reached 89 Hz
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

- **Write R13 = 50 and observe.** One register, documented purpose,
      trivially reversible. If the compressor caps at 50, the question is
      answered and the spread problem has a one-register fix. If it still
      reaches 85, R13 provably does not bind and the ladder is the lever.
- Only then consider rewriting the ladder's top entries
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

- **P08 water temperature compensation (`0x0092`, −5…15 °C) is unexplored**
      and is the outdoor-dependent setpoint correction the owner mentioned. On a
      day like this it could shift the setpoint with outdoor temperature without
      heatctl writing anything, which is worth understanding before adding more
      control on top of it.
- **Re-audit `docs/HEATPUMP.md` against the full capture.** 17 rows of 244
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

- **The trim needs a slab-referenced mode for pre-charging**, not just an
      air-referenced one. Until then pre-charge is a manual act.
- **Consider whether the setpoint should ever sit where the unit will not
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


- **Set F10 = 2 and observe for a day**, comparing: peak spread, leaving
      water against the condensation limit, number of setpoint breaches, and
      compressor cycle count. If breaches fall to near zero the constraint
      memory added in D-029 will rarely engage, which is the desired outcome —
      it exists to handle a constraint we would rather not hit at all.
- Also worth investigating: **`powerful_mode` is currently ON**
      (`0x0001` bit 4). The unit ramps to 85 Hz on every cycle. If that flag
      raises the frequency ceiling, clearing it would give longer, gentler runs
      and a naturally smaller spread. Undocumented in the manual extract we
      have, so test it deliberately and separately from F10 — changing both at
      once makes neither attributable.

- **The setpoint→supply gap is DYNAMIC and nothing in layer 1 measures it.**
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

- **Two weeks of innovation whiteness is the next gate** (WP-F). The
      filter records innovations and publishes mean/sd/lag-1 for exactly this.
      Expect the daytime residual to be the first thing to move, because
      `f_sol` (the air/floor split of solar gain) is a guess.

- **Known weak inputs, in order.** Each is a named parameter with its
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

- **Before layer 2 may command anything:** command TTL + expiry sweep in
      `ControlPlane` (DESIGN.md §2.2), then WP-H's planner. Do not shortcut
      the order — the existing two set topics are already TTL-less, and adding
      more without it makes them strictly less safe.

### Milestone 0 - bring-up (manual, no code)

- Hardware: the **2x 750-559 arrived and are fitted** (2026-07-27,
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
- NOT APPLICABLE - modbus2mqtt abandoned, see docs/MODBUS2MQTT.md. Was:
      Configure modbus2mqtt on the dev host (or HA add-on for prototyping):
      poll input registers 12-27 (temps), write holding registers 12-19.
      Document the exact register map + topics in docs/MODBUS2MQTT.md

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

### THE DESIGN, as settled with the owner 2026-07-31

Three loops, one actuator each, no negotiation between them:

| Loop | Actuator | Controls | Timescale | Layer |
|---|---|---|---|---|
| Valves | per-circuit opening | room / circuit temperature | minutes | 1 |
| **Spread** | frequency ceiling R32, **down to OFF** | manifold supply vs limit | 1-3 min | 1 |
| Setpoint | P04 | house demand only | 6.35 h | 2, clamped by 1 |

It all follows from `supply = return - spread` and `return -> P04`, so
`supply ~ P04 - spread`, against the constraint `supply >= dew + margin`. Two
variables, one constraint: P04 serves demand, spread serves the constraint.

**The assignment is forced by the timescales, not chosen.** Condensation is a
minutes-scale hazard (a shower, an opened window); spread responds in 1-3 min
while P04 is rate-limited to a step per 30 min by flash wear. Serving a fast
hazard with the slow actuator is exactly why the current code needs
`breach_jump_c` - the slow actuator cannot catch up, so it has to leap.

It also breaks the circularity that every guard in `setpoint.py` exists to
referee: today the setpoint floor is `limit + spread_estimate`, but spread is
what the capacity controller is *manipulating*, so each loop moves the other's
target.

#### OFF IS THE BOTTOM OF THE SPREAD ACTUATOR'S RANGE (owner, 2026-07-31)

An earlier draft of this plan said that when the spread loop saturates at the
machine's minimum frequency, P04 must be raised - `P04_min = dew + margin +
spread_min`. **The owner rejected that: "DO NOT TOUCH THE SETPOINT AS A LAST
RESORT. The conclusion here is to turn off the compressor entirely."** Correct,
for four reasons:

  1. P04 is the slow actuator; the hazard is fast.
  2. It re-couples condensation to the setpoint actuator, undoing the whole
     separation.
  3. Raising P04 only *gradually* stops the machine pulling return down. It
     keeps running and keeps making cold water meanwhile, and eight of ten
     circuits cannot close.
  4. The spread loop's authority is one continuous axis - full frequency, down
     to minimum, down to **off**. Reaching for a different actuator at the end
     of that range is what manufactured the "operating window" corner where the
     floor exceeds the ceiling and no setpoint satisfies both. With OFF as the
     bottom of the range that corner does not exist.

**A setpoint floor survives, but as EFFICIENCY, not safety, and therefore in
layer 2.** Without one, an over-aggressive P04 is not unsafe - it is cyclic:
cool until supply hits the limit, stop, drift up, restart on the 2 K dead zone.
The house still gets cooling, in bursts. Choosing P04 to keep the plant in
continuous operation is worth doing because cycling is inefficient, but if
layer 2 gets it wrong layer 1 degrades to cycling. Suboptimal, never unsafe.
`safety.py` gets no setpoint floor at all.

Details that need care when building this:
  - **The circulation pump KEEPS RUNNING when the compressor stops for
    condensation.** That is the recovery mechanism - circulating warms the loop
    back above dew point. Stopping both leaves cold water in the slab with no
    way out.
  - Asymmetric as everywhere else: stop immediately, restart only after
    `min_off_s` and the machine's own dead zone.
  - **Reconcile with the existing HA automation** that stops *circulation* on
    dew-point knowledge loss (and raises P04 before circulation resumes on
    recovery). "Dew point unknown" and "constraint unsatisfiable at minimum
    spread" are different conditions wanting different responses; they need
    reconciling, not layering.
  - Measure `spread_min` across flow and load before relying on it. One
    afternoon's figure is not a device constant.
  - **Known coupling, stated rather than discovered later:** closing valves
    reduces flow, and less flow means more spread at the same power - so the
    valve loop is a disturbance source for the spread loop. Weak today because
    eight of ten circuits are open pipe; it will not stay weak once the
    remaining actuators are fitted. The spread loop measures supply directly so
    it sees and corrects the disturbance, but if the two loops ever run at
    similar speeds they will interact.

### ⚠️ SUPERSEDED — the constraint-optimal setpoint solved the wrong problem

**Kept because the error is instructive, not because the result is usable.**
Owner, 2026-07-31: *"Are we talking about the same thing to fix? I am still at
'maximize flow, maximize spread, limited only by demand and dew point'."* That
framing is correct and the derivation below is not.

**The false assumption: that return water reaches P04.** It only does if the
machine can get there. Once the capacity loop caps frequency to protect supply,
it cannot - return floats *above* P04, set by how fast the rooms give up heat.
So below the point where P04 stops binding, Q does not fall away at
`m_dot_c` per K as claimed. **It plateaus.** The "sharp asymmetric peak" and the
"erring low costs 2.4x erring high" conclusion are both wrong on the low side.

**The correct statement fixes SUPPLY, not return:**

    Q = m_dot_c * s = UA * (T_room - supply - s/2)
    =>  Q = m_dot_c*UA/(m_dot_c + UA/2) * (T_room - supply)
          = 478 * (T_room - supply)      [m_dot_c 1503 at 90 % pump, UA 568]

**P04 does not appear.** Delivered cooling is set by the room temperature and
how low supply dares go - nothing else. Note `(m_dot_c + UA/2)` where the old
derivation had `(m_dot_c - UA/2)`; that sign is the whole difference between
fixing return and fixing supply.

**What follows, and it is much simpler than what it replaces:**
  - **Flow: maximum, always.** Not coordinated with the unit's pump loop -
    that loop is removed.
  - **Spread: whatever the compressor gives** with supply driven to
    `dew + margin`. The capacity loop already does exactly this and is the only
    capacity control needed.
  - **P04 is not a capacity lever.** It needs only to be low enough never to
    bind. Its real jobs are the restart dead zone and backing off once demand
    is satisfied.
  - **Demand and dew point are the only limits.**

There is no optimum to compute and no `P04_opt` telemetry to publish. The
machinery that was about to be built would have searched for a number that does
not need finding.

The superseded derivation follows.

### (superseded) The constraint-optimal setpoint — derived 2026-07-31

Prompted by the owner: *"instead of increasing the spread, the set point walks
down. This is broken."* It was, and working out why produced the first
statement of what layer 2 should actually COMPUTE rather than merely own.

At steady state, with `T_water_mean = P04 - s/2`:

    Q = m_dot_c * s                          (heat into the water)
    Q = UA * (T_room - T_water_mean)         (heat out of the rooms)
    =>  s = UA (T_room - P04) / (m_dot_c - UA/2)   =  k (T_room - P04)

With the identified `UA = 490` and `m_dot_c = 1438`, **k = 0.41**, so
`supply = 1.41*P04 - 0.41*T_room`. Applying `supply >= limit`:

    P04_opt = (limit + k*T_room) / (1 + k)
    Q_max   = m_dot_c * k/(1+k) * (T_room - limit)  =  **418 * (T_room - limit)**

Checked against the plant at 14:48: limit 16.5, T_room ~26 gives P04_opt 19.3
and Q_max 3975 W, against 4026 W measured. Agreement to 1 %.

**The peak is sharp and ASYMMETRIC**, which is the practical result:

    below P04_opt:  constraint binds, s = P04 - limit,  dQ/dP04 = +1438 W/K
    above P04_opt:  room side binds,  s = k(T_room-P04), dQ/dP04 =  -590 W/K

**Erring 1 K low costs 2.4x what erring 1 K high costs.** So when uncertain,
P04 should err HIGH - the exact opposite of the current trim's bias, which
lowers P04 whenever the house is warm and the valves are open. At 14:48 it sat
at 19.0 against an optimum of 19.3, i.e. ~430 W surrendered, and it got there by
stepping down past the peak at 13:27.

**CORRECTION TO A FIGURE REPEATED ALL DAY.** "Every 1 K off the dew point is
worth ~1.4 kW" appears several times above and in the 2026-07-31 entries. It is
wrong. `m_dot_c = 1438 W/K` converts a MEASURED spread into power, which is
correct; it does not value a kelvin of the limit, because the rooms can only
surrender heat at `UA * dT`. The right figure is **Q_max = 418 W per kelvin of
(T_room - limit)** - so removing Arbeitszimmer's 2 K was worth ~840 W, not
2.8 kW. Still the largest single lever found today, but a third of what was
claimed.

**Two regimes, and the design needs both:**
  - **Saturated** (house wants everything it can get): P04 has ONE right value,
    `P04_opt` above. House demand contributes nothing to it - it only says
    "everything". The value comes from the limit and the room temperature.
  - **Satisfied**: P04 should be as HIGH as still meets demand, for COP. This
    is the mild-weather regime and the trim's descent logic is fine there.

**Where this derivation is soft, and what to do about it:**
  - **Steady state.** The plant rarely is. Dew point moves, sun comes and goes,
    rooms drift. The optimum is therefore a slowly-moving target, which suits a
    coarse, rare P04 and a fast frequency ceiling absorbing the rest.
  - **UA = 490 was identified once**, at one operating point, over 3 of 7 rooms,
    and it lumped the slab with the fan coil. With Arbeitszimmer now outside the
    condensation limit, the slab-only UA is the relevant one and is smaller.
    Re-identify.
  - **`T_room` is a lumped house node** while `limit` comes from ONE room's dew
    point. Mixing a house average with a single-room constraint is defensible
    but should be stated, not hidden.
  - **`m_dot_c` assumes fixed flow.** True today only because eight of ten
    circuits cannot close. It stops being true as actuators are fitted, and
    then the valve loop moves `m_dot_c` under this equation.
  - **P04 is quantised to 1 K** (int16 degC register) and the optimum fell at
    19.3, between two settable values. The plant can never sit exactly at the
    peak; the frequency ceiling must absorb the residual. That is what the fast
    loop is for, but it means the setpoint loop should be coarse and rare BY
    DESIGN rather than by flash-budget accident.

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

## The heat pump write budget warns instead of gating (2026-07-31)

Owner's call: *"make this an error state we can see, but DO NOT DROP WRITES...
Being unable to correct plant deviations can hurt us more than a soft limit
like flash writes."*

`write_budget_per_hour: 30` was a gate. Past it, `write_register` refused,
logged, and returned False - so heatctl silently stopped being able to actuate
the heat pump, and the only trace was a log line nobody was reading. The
asymmetry was backwards: flash wear is a soft cost accumulating over years,
while an uncorrectable plant deviation is a hard cost happening now (a cold
house, or cold water reaching the slab).

Now:
  - Over `write_budget_per_hour` -> **user-visible alarm, write proceeds.**
    Publishes `hp/write_budget_exceeded` and `hp/writes_last_hour`, discovered
    into HA as a `problem`-class binary sensor plus a diagnostic count.
  - Over `write_hard_limit_per_hour` (default 10x = 300) -> refuses, logs
    CRITICAL, publishes `hp/write_hard_limit_hit`. At that rate no legitimate
    control is happening.
  - The alarm clears when the rolling-hour rate falls back, because a latched
    alarm that never clears is one nobody trusts.

No-op writes are still dropped before the bus - that one is free, it costs a
packet and saves a flash cycle.

**Two tests had to be retargeted, and both had passed against the old
requirement**: `test_the_flash_budget_stops_a_runaway_loop` asserted the gate at
5 writes, and now asserts all 20 get through with the alarm raised; a new
`test_the_hard_limit_does_stop_a_runaway_loop` covers the gate that remains.
Full coverage in `tests/test_heatpump_write_budget.py`, mutation-verified
against restoring the soft gate.

**Watch for:** the alarm firing in normal operation. The budget is 30/h and
legitimate control changes are meant to be rare (a mode change, a setpoint
trim). If it trips without a runaway, the budget is wrong for how the plant
actually runs and should be re-derived rather than silently raised - the write
rate is now observable, so that is answerable from data.

### ANSWERED 2026-08-01: it tripped, and the budget is NOT the thing that is wrong

The alarm fired at 13:13 in ordinary operation, exactly as anticipated above.
Answering it from data, as that paragraph asks:

**Every write was `0x00F1`.** 24 of 24 in the log window - the capacity loop,
nothing else. Observed ceiling sequence, one move per minute or two:

```
41 -> 39 -> 36 -> 32 -> 30 -> 32 -> 39 -> 44 -> 47 -> 49 -> 44 -> 42 -> 40
```

A full sweep to the 30 Hz floor, back up to 49, and down again. A limit cycle,
not a runaway.

**Mechanism: the deadband is on the INPUT, not the OUTPUT.** `deadband_c` is
0.25 K of *margin*; there is no minimum step on the *actuator*. A margin error
of 0.3 K - barely outside the deadband - computes as
`loop_gain * err / supply_k_per_hz = 0.5 * 0.3 / 0.074 ~= 2 Hz`, and that 2 Hz
goes to flash. With `lower_settle_s` 60 and `raise_interval_s` 120 the ceiling
is 60 lowers + 30 raises per hour, so the budget can be exhausted by noise
alone whenever the plant cannot settle.

It could not settle because it was pinned against the condensation limit all
day - cooling into open windows while the incoming air raised the dew point, so
the constraint moved as fast as the loop chased it.

**Note the gain is one we do not trust:** `supply_k_per_hz: 0.074` is recorded
elsewhere as having poor provenance. So these 2 Hz corrections are computed
from an untrusted constant, which makes chasing them doubly pointless.

**So do NOT re-derive the budget upward.** That would hide a real limit cycle
behind a bigger number, which is the failure mode the paragraph above warns
against. The loop is what needs fixing.

- **Asymmetric minimum step on the capacity actuator.**
      * **Lowering: unchanged.** It is the safety direction, its first move is
        deliberately never delayed, and a genuine breach produces a large step
        anyway - a minimum-step rule would not block it.
      * **Raising: require a minimum step** (~4-5 Hz) before writing. Raises are
        discretionary; suppressing 2 Hz nibbles costs only a little unused
        headroom.
      Roughly half the observed moves are raises, so this should take ~30/h to
      ~15-20/h without touching the safety path.
      **The test must assert the DIRECTION asymmetry**, not merely that a
      threshold exists - applying it to both directions is the easy mistake and
      would delay a condensation response, which is strictly worse than the
      flash wear it saves.

- **The `P_el` intercept is applied unconditionally, and its constituents
      can be off.** Owner, 2026-08-01: *"Where are 200W power estimate coming
      from with the compressor turned off?"*

      D-027 is not wrong and this does not reopen it. `P_el = 198*I + 200 W`
      (R2 0.994 over 129 days) and the 200 W is fan + circulation pump +
      electronics, which switch with UNIT POWER rather than with the
      compressor - event-based fits return an intercept near zero precisely
      because those are already running when the compressor starts. Checked at
      16:35 the same day and it was CORRECT: unit on, `water_pump` on,
      `dc_pump_speed` 100 %, compressor 0 A, estimate 200 W. Real load.

      **The gap is the word "unconditionally".** `main.py` adds the intercept
      whenever that code runs, i.e. whenever the unit is energised - but there
      are states where the auxiliaries are NOT running. Measured at 14:20 that
      day, after the capacity loop stopped the compressor and Er03 latched,
      `binary_sensor.heatctl_water_pump` read **off**. Compressor stopped, pump
      stopped, and the estimate still reported 200 W when the true draw was
      electronics only.

      **Why the calibration did not catch it:** D-027 fitted 129 days of WINTER
      data, where the unit is rarely sitting powered-but-idle for hours. A
      summer day on a condensation-limited plant is exactly that regime - on
      2026-08-01 the plant was faulted or idle for several hours, so roughly
      1.2 kWh was attributed to a machine doing nothing.

      This is energy accounting, not control - but the optimizer's COP and
      consumption figures rest on it, and the error is one-sided (always over).

      Fix is cheap because the inputs are already read and published: gate the
      intercept on `water_pump` (`0x8006` bit 0) and `dc_pump_speed` instead of
      on "this code is running". Splitting the 200 W into its pump and
      electronics parts needs a measurement - the pump is a DC circulator whose
      draw scales with speed, so `dc_pump_speed` should scale that share rather
      than switch it.

### 2026-08-02 — P04-low + R32-modulating lost a self-limiting property

Owner, 2026-08-02, describing what the control had become: *"So we now clamp P04
to a low value, use the max frequency for regulation, and just turn off the
compressor by setting P04 to 30 if needed?"* That is an accurate description,
and it EMERGED rather than being designed - worth recording as an architecture,
because it now has a failure mode nobody chose.

| lever | role | why |
|---|---|---|
| R32 frequency ceiling | the modulating regulator | fast, continuous, no wear |
| P04 setpoint | coarse permission | flash wear, 30-min cadence, 2 K dead zone |
| P04 = 30 | off | the unit has no off command |

The allocation is defensible: the condensation constraint needs a FAST actuator
and R32 is one, while P04 is a poor one on every count. Note P04 is not
"clamped" low - the trim WALKS it down under demand and bottoms out at
`cooling_min_c: 14` on hot days, and the 2026-08-02 dead-zone fix now also
lowers it on resume. Low is a consequence, not a setting.

**WHAT WAS LOST.** With P04 near its floor the unit permanently asks for maximum
output, and R32 is the only restraint. A higher P04 used to be self-limiting -
the machine stopped wanting more once return reached setpoint. That property is
gone.

It matters because the restraint is reachable only over the RS485 gateway, which
dropped TWICE in two days (2026-08-01 13:53 and 18:04). In that window heatctl
keeps running, valves stay under control, and the compressor pulls toward a
14 degC return with nothing able to stop it. The remaining defences moved
further out at the same time:

  * the condensation valve guard now waits `undertemp_dwell_s` (180 s), where it
    used to be instant;
  * the coupler watchdog only helps if heatctl dies ENTIRELY, not if just the
    heat-pump link does.

- **Make P04 retreat when the heat-pump link goes stale.** If the status
      block has not been read for some multiple of the poll interval, walk P04
      back toward a survivable value while the link still works, so a
      subsequent loss leaves the plant asking for something safe rather than for
      everything. This restores the self-limiting property WITHOUT giving up the
      fast actuator, which is the part worth keeping.
      Note the ordering trap: the retreat must be written BEFORE the link is
      fully gone, so it has to trigger on staleness, not on failure.

### MEASURED 2026-08-01 — 19 % of the heat pump's dT never reaches the manifold

Owner asked whether the ~0.7 K loss between heat pump and manifold explains the
COP shortfall. It does not, but it is real and it is asymmetric in a way that
matters. Five days, 10-minute means, cooling:

```
                                    all samples   cooling hard (n=253)
HP dT (return - leaving)              +1.747 K        +2.896 K
manifold dT (rl_total - vl_total)     +1.616 K        +2.338 K
supply-side gain  HP -> manifold      -0.489 K        +0.031 K
return-side gain  manifold -> HP      +0.620 K        +0.527 K

manifold dT / HP dT = 0.807 while cooling
```

**The loss sits entirely on the RETURN run.** While cooling, the supply side is
clean (+0.03 K) and the return gains +0.53 K. That asymmetry is backwards for a
pure thermal loss: the supply pipe carries the COLDEST water and should gain
MORE from cabinet air, not less. So this is either an uninsulated return run or
a calibration offset between the two sensor sets.

**During idle, BOTH manifold sensors read ~0.5 K below the heat pump's pair**
(-0.489 and -0.620). A thermal loss cannot make the supply read colder
downstream, so at least part of this is a systematic offset between the WAGO
PT1000s and the unit's internal sensors.

**Consequences.**
- **System COP and machine COP differ by ~19 %.** The COP figure above uses the
  HP's own dT, which is correct for the MACHINE. Anything sizing what reaches
  the slab must use the manifold dT and is 19 % smaller.
- It does NOT explain the factor of two. Using manifold dT instead would move
  the COP from 1.69 to ~1.37 - the wrong direction.
- It is a second, independent reason to distrust absolute dT figures, alongside
  the COP result. Two sensor pairs that should agree closely do not.

- **Check whether the return run is insulated**, and cross-calibrate the two
      sensor sets at a settled no-flow point. The idle offset (~0.5 K on both
      manifold sensors) is measurable in minutes and separates calibration from
      pipe loss - which the operating data alone cannot.

### 2026-08-01 — measured COP is 1.69, and that number indicts the manifold dT

`assumed_cop: 3.35 +- 1.0` is a prior and `params.yaml` calls it "THE MODEL'S
WEAKEST INPUT". It looked like the cheapest win available: every input needed to
MEASURE it is already in the archive, so this should have been arithmetic rather
than identification.

**METHOD.** Hourly, 2025-10..2026-02, compressor-running hours only:

    P_el = 198*I + 200 W          D-027, R2 0.994 over 129 days, I = 0x8025
    flow = 1.44 * pump_pct/100    params.yaml + derived.flow_from_pump
    Q    = rho*cp*flow*(VL - RL)  rho 998, cp 4183 (specified)
    COP  = sum(Q) / sum(P_el)     ENERGY-weighted, not a mean of ratios

Filters: compressor frequency >= 5 Hz, current >= 0.5 A, pump >= 5 %, VL-RL >
0.05 K, and VL/RL > 0.05 (the unit reports 0 when off, which is not 0 degC).
835 usable hours.

Energy weighting is the right estimator here and the algebra was checked: in an
hour at 50 % duty, `Q` and `P` dilute consistently, because the 200 W standby
floor and the zero compressor current cancel correctly. Cycling is NOT the
explanation for what follows.

**RESULT: COP = 1.69.** Against an assumed 3.35 - a factor of two.

```
VL band    n    COP     Q W    P W   dT K    Toa        Toa band   n   COP
 0-26     45   1.35    1423   1051   1.35    5.0        -20-0    165  1.20
26-30    312   1.67    2026   1216   2.10    6.1          0-4    164  1.27
30-34    322   1.86    2596   1394   2.66    5.9          4-8    147  1.79
34-38    111   1.50    2300   1537   2.67    4.9         8-12    258  2.18
38-60     45   1.46    2615   1787   3.15    3.9        12-30     87  1.77
```

**The SHAPE is right and the LEVEL is not.** COP rises with outdoor temperature
exactly as it must (1.20 below 0 degC to 2.18 at 8-12), so the data are not
noise - but 1.69 at VL ~30 degC and +6 degC outdoor is not a plausible level for
this machine.

**What it is NOT.** Flow cannot close the gap: reaching 3.35 needs 2.85 m3/h at
100 % pump against a specified maximum of 1.44. Cycling cannot, per the
estimator argument above.

**What it probably IS: the manifold dT reads about 2 K low.** At 1.35 kW
electrical and COP ~3.1 the required dT is ~4.9 K; we measure 2.41 K mean. A 2 K
systematic offset between two independently calibrated sensors is ordinary,
especially with `leaving_water` quantised at 0.5 K against `return_water` at
0.1 K (heatpump_map records the differing scales as a known trap).

**WHY THIS MATTERS BEYOND THE COP, and it is the important part.** `ua_sa` is
identified from `ua_sa_identification.manifold_dt_k = 2.1 +- 0.14 K` - the SAME
measurement, and the five-month mean of 2.41 K is consistent with it. If that dT
is systematically low then `ua_sa` is low, `q_max` is low, and the
condensation-limited delivery ceiling is UNDERSTATED. Every figure quoted from
`derived.q_max()` (2.8-3.4 kW on a humid day) inherits the same suspicion, and
that ceiling is what the hourly forecast is meant to be rebuilt on.

So this is not a heat-pump efficiency question. It is a question about whether
the plant's single most reused measurement is biased.

- [!] **Get an independent heat measurement (the MULTICAL 403 already named in
      params.yaml).** It resolves the COP level, the dT offset and `ua_sa` in
      one instrument, and until then anything derived from manifold dT carries
      an unquantified systematic. Do NOT "fix" `assumed_cop` to 1.69 - that
      would bake a suspected sensor bias into the model as physics.
- **Cheap interim check: swap or cross-calibrate the VL/RL sensor pair.**
      Running them briefly at the same point (no flow, thermally settled) shows
      the offset directly and costs nothing but time.
- **The COP SHAPE is usable now even though the level is not.** COP(Toa, VL)
      = k * f(Toa, VL) with f measured above and k unknown (~2). If the level is
      pinned later, the shape does not need re-deriving.

**THE ELECTRICAL SIDE IS VALIDATED, so the discrepancy is thermal.** Owner,
2026-08-01: phase A carries more than the heat pump, so its ABSOLUTE level is
not a proxy for heat-pump power - but the DELTA when the compressor starts is,
and that is what established the unit's own current register as 230 V mains
current (D-027, 0.92 A per reported A). `P_el = 198*I + 200` can therefore be
used directly and is not the thing in doubt.

Attempting to re-derive that step ratio here found almost no transitions to
measure: **2084 five-minute samples across 15 days of January contain
essentially no compressor start/stop events.** That is itself worth recording -
in winter this machine MODULATES continuously rather than cycling, which is why
the anti-short-cycle reasoning that dominates summer operation has no
counterpart in the winter data.

With the electrical half sound and flow bounded by the pump's specification,
the factor of two has nowhere left to sit except the thermal measurement.

- **D-027's 200 W intercept has unsound provenance - the magnitude may be
      right by luck.** Owner, 2026-08-01: *"I think even is the compressor
      current, it does not measure pump current. That 200W offset is a mistake."*
      D-027 explains the intercept as "fan + circulation pump + electronics",
      but it comes from a regression against the utility meter, and phase A
      carries household load. Measured over 6 weeks at 5-minute resolution:
      with the compressor OFF and the pump running, phase A already sits at a
      MEDIAN 3.08 A (~709 W) with sd 3.28 A. Any intercept fitted against that
      series absorbs household baseline, so the regression cannot attribute
      200 W to the unit's auxiliaries.
      The magnitude is not absurd on physical grounds - a fan plus a DC
      circulator at ~57 % plausibly draws 70-190 W - so this is a PROVENANCE
      defect rather than a demonstrated error, which is exactly the class
      D-031/D-032 exist to catch.
      **The decisive test could not be run: the pump never stops** (6 samples
      out of 2062 - it is in "always open" mode), so the pump-only step on
      phase A is unmeasurable from the archive. It needs a clamp meter on the
      unit, or a deliberate period with the pump commanded off.
      Effect on the COP above: dropping the intercept moves 1.69 -> 1.99, so it
      does NOT resolve the factor of two either way.

### 2026-08-01 — the moisture balance does NOT identify `n`. It identifies `G/n`.

Attempted because `n` (air change rate) is the worst parameter in the set -
`docs/DESIGN.md` calls it *"poor - assumed, never measured"* at 0.7 h-1, and
D-028 could only infer ~0.40 without separating it from the fabric term's 18 %
thermal-bridge default, concluding *"only a blower-door test separates them"*.
Moisture looked like the way round that: it does not interact with the fabric
at all, so a moisture-derived `n` would un-confound the thermal fit.

**METHOD.** Single-zone moisture balance on the indoor air:

    dW/dt = n*(W_out - W) + G/(rho*V)

Over a fixed step the exact solution is `W[k+1] = W_ss + (W[k]-W_ss)*exp(-n*dt)`,
which rearranges to

    dW = a*(W_out - W) + b,     a = 1 - exp(-n*dt),  b = a*G/(n*rho*V)

**linear in (a, b)** - so this is ordinary least squares with real standard
errors, not a numerical optimiser with a convergence story. `n` and `G` come
back out by inverting the two definitions.

Data: the InfluxDB archive 2025-10..2026-02, hourly (see the memory note for
access). Indoor `W` from each room's RH and air temperature via Magnus, then
averaged over the rooms with >=2 reporting. Outdoor `W` from the Open-Meteo
ERA5 archive rather than the local station, because the local outdoor humidity
sensor covers only 28 % of hours and sits stuck at a constant for one four-month
stretch. Air mass from the surveyed heated volume.

**RESULT 1 - THE DYNAMIC FIT FAILS, AND IT IS NOT A CODING ERROR.**

```
subset                        N     n /h   tau h     R2
all hours                  2857    0.042   23.86   0.026
|dW_out/dt| > 0.3           186    0.047   21.15   0.040
night 00-05 UTC             521    0.083   12.00   0.049
```

`n` of 0.04-0.08 h-1 is a time constant of 12-24 HOURS for a house that should
sit near 1.5-5 h. R2 never exceeds 0.05. Restricting to the hours that should
carry the most information - fast outdoor changes, or nights when moisture
generation is quietest - moves it a factor of two and no further.

**Diagnosis.** The estimate FALLS as the step grows (0.041 at 1 h, 0.016 at 6 h),
which is the signature of attenuation rather than noise. The cause is that
**the house sits near moisture steady state**: `G` continuously replenishes what
ventilation removes, so `dW ~= 0` for most hours and the balance carries almost
no dynamic information. What variance `dW` does have is dominated by `G` itself
- showers, cooking, occupancy - which is unmeasured, time-varying, and
uncorrelated with the regressor. Hourly averaging smooths what little transient
remains, and `W` appearing on both sides adds errors-in-variables on top.

**A large mean gradient is not the same as informative dynamics.** That was the
mistake going in: the +1.4 g/kg indoor-outdoor gap was read as "well
conditioned", when it is exactly the steady state that makes `n` unidentifiable.

**RESULT 2 - THE STEADY STATE IS WELL DETERMINED, AND CONSTRAINS THE PAIR.**

    <W_in - W_out> = 1.442 +- 0.018 g/kg   (sd 0.99, n = 3002)
    => G = n * 0.861 kg/h

```
   n /h   G kg/day   plausibility for a household of this size (8-15 kg/day)
   0.30       6.2    low
   0.40       8.3    plausible
   0.50      10.3    plausible
   0.70      14.5    plausible, upper end
   1.00      20.7    implausible
```

So the data bound the PAIR, not either alone. Taking 8-12 kg/day as the
defensible range gives **n ~ 0.39-0.58 h-1** - consistent with D-028's ~0.40 and
sitting below the assumed 0.70, but note this is inference from a PRIOR on
moisture production, not a measurement. It must not be written into params.yaml
as though it were identified.

**WHAT WOULD ACTUALLY CLOSE IT: a CO2 decay test.** CO2 is the standard tracer
for air change rate precisely because it avoids everything that broke this:
occupants stop generating it when they leave, so the decay is a clean
first-order relaxation with a known zero input, and one overnight decay in a
closed room gives `n` directly. It is far cheaper than the blower door D-028
asked for, and it measures the OPERATIONAL air change rate rather than envelope
tightness at 50 Pa - which is the quantity the model actually wants.

- **Get a CO2 sensor and run an overnight decay.** Needs no permanent
      install. With `n` measured, `G` follows from the steady-state relation
      above at no extra cost, and D-028's fabric/ventilation ambiguity resolves
      as a side effect.
- **Do not fit `n` from moisture again without an independent `G`.** The
      failure above is structural, not a tuning problem; a better optimiser on
      the same data returns the same wrong answer with tighter error bars.

### MEASURED 2026-08-01: D-009 confirmed, and `settle_s` is ~20x too short

First INDEPENDENT evidence for the return-sensor gating rule. D-009 was decided
on a physical argument plus one incident; this is five months of pre-heatctl
history (2025-10..2026-02, hourly, from the InfluxDB archive - see the memory
note for how to reach it) agreeing with it.

Method: classify each hour as flowing (manifold flow-return spread > 0.5 K and
supply > 5 K above cabinet air) or stagnant (spread < 0.15 K and supply within
2 K of cabinet), then compare each circuit return against the cabinet air
sensor that existed in that era (`rl_12`, which is manifold ambient and NOT a
circuit - owner).

```
circuit   |rl - ambient| FLOWING   |rl - ambient| STAGNANT
rl_1            8.85 K                   1.13 K
rl_2            9.70                     1.20
rl_3            4.60                     1.03
rl_4            4.69                     1.01
rl_5            5.37                     0.95
rl_6            6.13                     1.33
rl_7            5.45                     1.03
rl_8            9.25                     1.21
rl_9            7.98                     1.14
rl_10           9.50                     1.14
```

**Every circuit collapses to within ~1 K of cabinet air when flow stops.** The
mechanism is exactly what D-009 asserts, on all ten circuits, measured.

**CAVEAT THAT LIMITS THE SETTLING RESULT - the historic sensors are not the
present ones** (owner, 2026-08-01). The circuit returns above are Controme
DS18B20 probes on the 1-wire bus that died with the Floor Gateway; today's are
WAGO PT1000s the owner fitted, and the owner notes those are INSULATED. So:

  * The PHYSICS transfers - a stagnant circuit's water reaches cabinet
    temperature, and that is a property of the plant, not of the instrument.
  * The TIME CONSTANT does not. The 2-3 hour recovery is a property of those
    probes and their mounting. The present sensors could be faster or slower,
    and their insulation makes slower plausible.
  * **ABSOLUTE accuracy runs the OTHER way** (owner, 2026-08-01): DS18B20 is
    digital and factory-calibrated, with no analog chain to drift, while the
    PT1000s pass through wiring and the 750-463's ADC. So the HISTORIC values
    are the more trustworthy in absolute terms, and it is the PRESENT chain
    that wants calibrating. That bears directly on the ~0.5 K offsets measured
    between the manifold pair and the heat pump's own sensors, and on
    `ua_sa_identification` - whose manifold dT was taken on the PT1000 chain,
    not on the DS18B20s.

So "settle_s is 20x too short" is an indictment supported by the old sensors and
NOT yet confirmed on the new ones. Re-measure on the current hardware before
choosing a number - which is a further argument for replacing the timer with the
`|rl - ambient|` test, since that criterion does not depend on the sensor's time
constant at all.

**The recovery is what indicts `rl_gating.settle_s: 300`.** Fraction of the
eventual reading achieved after flow restarts:

```
 h    rl_1  rl_2  rl_3  rl_4  rl_5  rl_6  rl_7  rl_8  rl_9 rl_10  median
 0    0.57  0.61 -0.01  0.03  0.24  0.46 -0.02  0.59  0.42  0.63   0.44
 1    0.81  0.95  0.52  0.48  0.67  0.73  0.39  0.82  0.78  0.86   0.76
 2    0.96  0.92  0.84  0.70  0.84  0.84  0.64  0.92  0.91  0.95   0.88
 3    0.99  1.00  1.01  0.83  0.93  0.91  0.86  0.97  0.96  0.99   0.96
```

90 % takes **2-3 hours**; `settle_s` is 300 s. At five minutes the PID is fed a
value roughly half cabinet temperature. The bias direction is "closer to room
temperature than the truth", which makes circuits OVER-open in both modes -
safe for flow, wasteful, and it corrupts room control.

**Mechanism, owner 2026-08-01: the sensors are insulated.** So a large part of
this is the SENSOR's own first-order lag, not water failing to arrive. That
does not change the 20x error, but it changes the remedy: the reading is a
lagged truth rather than noise, so it is characterisable and could be
compensated rather than merely waited out.

- **WITHDRAWN 2026-08-19 (D-042): replace the `settle_s` timer with a
      direct `|rl - ambient|` test.** The proposal inverts a valid implication.
      "No flow, so the sensor drifts to ambient" does not give "reads ambient,
      so no flow" - the owner has seen a *flowing* return match cabinet air by
      chance, and a stagnant one takes far longer than a control cycle to get
      there. Both errors are real and the permissive one is the dangerous one:
      a circuit that stopped minutes ago still reads "flowing", so the test
      would trust exactly the stagnant sensor the gate exists to distrust.
      This is standing principle 13 - a predicted effect is not confirmation.
      The rest of the item stood on a true observation and is kept:
      **the circuits differ by ~2.5x** (at h=1: rl_7 0.39 vs rl_2 0.95, and
      3/4/7 show nothing at all in the first hour). One global constant is
      either far too short for the slow circuits or wasteful for the fast ones.
      **Do NOT hard-code per-circuit values from the table above** - the owner
      has since swapped valves around, so the per-circuit IDENTITIES do not
      transfer. Only the distribution does.

- **Verify the three cabinet sensors during OPERATION before trusting them.**
      Checked 2026-08-01 while the plant was idle: 22.60 / 22.00 / 22.00 against
      circuits at 20.8-21.5. Consistent, but the whole manifold spanned 1.8 K at
      the time, so any three sensors would have looked agreeable. The
      discriminating test is a running plant, where circuits must pull AWAY from
      cabinet air and these three must not. Input 12 also read 0.6 K above the
      other two - placement or offset, unresolved.

- [!] **heatctl cannot tell that a command it issued did not take effect.**
      Observed 2026-08-01 16:26, and it is a whole missing feedback path rather
      than a bug in one loop.

      ```
      16:26:00  compressor RESUME at 20 degC: margin +4.30 K recovered - restarting
      ```

      heatctl wrote P04 = 20 and logged a restart. The compressor did not start:
      `er03_water_flow` was latched, frequency stayed 0, and the water pump
      stayed off. **The controller believed the plant was running for as long as
      nobody looked at the fault entity.**

      The gap is that every heat-pump command is OPEN LOOP. `cooling_is_off()`
      reports what heatctl last WROTE to P04, not what the machine is doing -
      the same category error as reading the coupler's output mirror and calling
      it a valve position (see the PSU section in docs/HARDWARE.md). The unit
      publishes everything needed to close the loop: compressor status is
      `0x8004` bit 0, frequency is a register we already read every cycle.

      Why it matters beyond the one event:

      * **Er03 LATCHES.** It needs a person at the unit, so this divergence does
        not self-heal - it persists until someone notices. On 2026-08-01 the
        controller sat in "resumed" for over two hours.
      * **The capacity loop keeps working a dead actuator.** It computes margins
        and steps a frequency ceiling for a compressor that cannot run, spending
        flash writes against a budget that was already tripping that day.
      * **A future planner would size the day against capacity that does not
        exist.** WP-H hands out setpoint requests assuming the source can
        deliver; nothing tells it the source is faulted.

      Fix: after commanding a state change, verify it within a bounded time and
      alarm if it did not happen. "Commanded RESUME, compressor still at 0 Hz
      after N s" is the operator-visible fact, and it should also stop the
      capacity loop re-commanding into a latched fault rather than burning
      writes. Note the alarm must be on the DIVERGENCE, not on the fault - the
      fault is already published; what is missing is that heatctl's own model
      disagrees with the plant.

      Cheap partial: while `hp/fault_any` is set, do not spend writes on the
      frequency ceiling. That does not close the loop but removes the worst
      consequence.

- **The budget alarm has no hysteresis and flaps on the threshold.**
      Observed the same afternoon: EXCEEDED at 13:37 (30/h), "back within
      budget" at 13:41 (29/h), and it will keep crossing while the rate sits on
      the limit. Raise-and-clear at the same number turns a real signal into a
      stream nobody reads - the same "cries wolf" failure `deploy.sh` documents
      for its own start-up check. Clear at a distinctly lower rate than it
      raises (or require the lower rate to hold for a few minutes). Cheap, and
      it should land with the loop fix above rather than instead of it: the
      flapping is a symptom of the rate parking exactly on the budget, which
      the minimum-step change is what actually cures.

- [!] **Two documents assert a coupler watchdog behaviour the hardware does not
      have.** Raised 2026-07-31 while explaining the safety chain, and recorded
      here because it was nearly lost in conversation.
      `docs/DESIGN.md` Layer 0 says the WAGO Modbus watchdog fallback "must
      drive the analog outputs to FULL SCALE - valves are fail-open by design",
      and the `safety.py` policy docstring reasons from the same premise
      ("with the coupler's Modbus watchdog fallback set to full scale").
      `docs/HARDWARE.md` records the opposite as **verified twice on hardware**:
      the 750-352 sets physical outputs to ZERO on timeout and it is *not
      configurable*. With NC actuators that CLOSES valves.
      So the outermost failsafe fails in the opposite direction to heatctl's own
      fail-open policy. That is defensible for a genuinely dead controller - and
      may well be the right behaviour - but **two documents and a code comment
      currently assert something untrue**, which is how a future change gets
      reasoned into existence on a false premise. Decide which behaviour is
      wanted, then make the documents agree with the hardware.
      Note this interacts with the 750-8212 swap: a PFC200 runs its own program
      and neither behaviour comes along for free.

- [!] **Two telemetry sensors publish one quantity, and one of them is dead.**
      2026-07-31. `sensor.heatctl_water_sp_spread_est` reads `unknown` while
      `sensor.heatctl_spread_estimate_floor_input` reads the live value (2.20 at
      the time). The floor consumes the latter. Harmless today, but it cost time
      during the D-030 diagnosis and is exactly the sort of thing that misleads
      at 03:00 - one of them should go, and the survivor should be the one the
      control path actually reads. Fold into WP-S Stage 1, which is already
      about publishing the constraint properly.

- [x] **Elternschlafzimmer removed from both dew point templates, 2026-07-31.**
      Owner: *"broken in the same way all other rooms are - I am not sure why it
      appears as special."* Correct, and it corrects me: I had called restoring
      that sensor "the cheapest real improvement available" and described the
      room as upstairs. Both wrong. It is EG, and there is **no sensor there at
      all** - Controme reports a hardcoded 10 degC placeholder for it exactly as
      it does for Bad and both Kinderzimmer (docs/HA_INTEGRATION.md), so the
      pair could never contribute a dew point.
      Removed from `sensor.system_dew_point_reference` and
      `sensor.system_dew_point_source` in step, because listing a pair that can
      never report implies coverage the house does not have - which is worse
      than showing three rooms honestly.
      **Real dew point coverage is 3 of 7 rooms: Gaestebad, Wohnzimmer,
      Arbeitszimmer.** The Shelly H&T rollout is the only thing that changes
      that; there is no cheap intermediate step, and claiming otherwise was the
      error here.

- [x] **Removed the legacy `Climate: Prevent Condensation (With Modbus Fallback)`
      HA automation, 2026-07-31.** Owner: *"before it confuses us even more."*
      It had become actively misleading on three counts:
      1. **It was inert.** Its actions targeted `modbus.write_register` on hub
         `WSDEV0001`, `climate.set_temperature_of_chilling_mode` and
         `sensor.control_flags_0` - and that hub is commented out in
         `configuration.yaml` (line 73), so all three were `unavailable`. The
         automation was also `off`. Doubly dead, but it read like a safety net.
      2. **It was built on the misconception `docs/HEATPUMP.md` exists to
         correct.** Its description calls register 0 bit 0 "the pump-request
         bit" and claims clearing it "stops cooling circulation". That bit is
         the unit's **POWER**. When it did work it was switching the whole heat
         pump off.
      3. **It was a second writer to the heat pump**, by direct Modbus,
         bypassing heatctl entirely - the exact single-writer violation
         CLAUDE.md and config.yaml both warn about, and a read-modify-write
         race on register 0 at that.
      Its function is already covered properly: `safety.py` closes owned valves
      on `dew_point_unknown` in cooling, and `dew_point_max_age_s` ages the
      value out. `automations.yaml` backed up on the HA host as
      `automations.yaml.bak-legacy-chiller-20260731` before the delete.

- [x] **DONE: all four remaining legacy chiller automations deleted**, along
      with 80 orphaned entities and 475 lines of dead `configuration.yaml`
      (the commented-out WSDEV0001 modbus block and the template block that
      decoded its registers). `automations.yaml` and `configuration.yaml` were
      backed up on the HA host first, as `*.bak-legacy-chiller-20260731` and
      `*.bak-cleanup-20260731`.
      The energy chain was NOT deleted - `Heat Pump Power` was rewired onto
      `sensor.heatctl_hp_power_estimate` keeping its `unique_id`, so
      `sensor.heat_pump_energy` and both utility meters carried their history
      across intact (74.968 kWh verified after the restart). Original list,
      found while removing the one above: All are `off` and all target the same
      commented-out `WSDEV0001` hub, so all are inert:
      * `Climate: Chilling Setpoint Supervisory Loop` (`1782601857263`) -
        **worth noting given D-030**: this is a fourth process that once
        controlled the water setpoint. It is disabled, but it is precisely the
        kind of hidden competing writer that discussion was about.
      * `Heat pump: circulation pump request` (`1785095167030`) - named in
        `docs/HEATPUMP.md` as the automation written to match the wrong bit-0
        meaning.
      * `Steuerung der Wasserpumpe in der Waermepumpe (einschalten)` and
        `(ausschalten)` (`1760279804931`/`...932`).
      Removing them is cleanup with no functional effect, but it was not asked
      for and deleting HA config is not trivially reversible, so it is recorded
      rather than done. The backup above covers all five.

- [!] **THE HOUSE HAS NO DEHUMIDIFICATION PATH IN COOLING MODE, AND THAT IS A
      RATCHET.** Measured 2026-07-31, and it explains why a milder day felt
      worse than a hot one.
      Arbeitszimmer humidity rose all morning with the fan coil running and the
      windows shut: 57.2 % at 08:00 to 60.0 % at 14:00 at a near-constant
      25.3-25.7 degC, taking its dew point 16.2 -> 17.4.
      **The fan coil cannot dehumidify.** Its surface sits at supply
      temperature - 19.2 degC at the time - while the room dew point was 17.4.
      A coil 1.8 K ABOVE dew point condenses nothing, and it can never be below
      it, because `dew_point_margin_c` exists precisely to keep supply above
      dew point. The constraint that protects the slab also disables the only
      component that could lower the dew point.
      So: the slab cannot dehumidify (above dew point by design), the coil
      cannot (same limit), and there is no dedicated unit. Outdoor dew point was
      19.2, so every air exchange adds moisture with nothing removing it.
      Indoor absolute humidity ratchets upward, the condensation limit follows,
      and cooling capacity is progressively strangled. **No software change
      fixes this** - it is a plant capability that does not exist.
      **Immediate answer: a standalone dehumidifier in Arbeitszimmer.** That
      room sets the limit for the whole house, so every 1 K off its dew point is
      ~1.4 kW of cooling unlocked in every room. Cheapest and fastest fix
      available.
      **Why the obvious alternative does not work today:** running the fan coil
      deliberately below dew point is exactly what fan coils are built for, and
      would need only a condensate tray and drain (unverified on this unit -
      check before assuming). But the coil shares one manifold supply
      temperature with all ten slab circuits, and its valve controls flow, not
      temperature. There is no way to give the coil cold water and the slab warm
      water until the buffer and mixing arrangement in docs/DESIGN.md exist.
      **This is a strong argument for that work package**, and it should be
      recorded as a requirement on it: hydraulic separation of the fan coil from
      the slab circuits buys the house a dehumidifier it already owns.

- [x] **Arbeitszimmer removed from the dew point limit - it has no slab and its
      coil drains, 2026-07-31.** Owner: *"I still have the temporary hose for
      condensation installed at the fan coil. We can take out this sensor from
      the dew point calculation without harm - condensate will land in a
      bucket."*
      The limit exists to keep water below the dew point out of the SCREED,
      where condensation is invisible and unrecoverable. Arbeitszimmer has no
      floor heating - it is served by the fan coil on circuit 11 - and that coil
      drains to a bucket. Condensation there is collected, not damage.
      Including it cost the whole house about **2 K of supply depression, ~2.8
      kW**, to protect a surface designed to get wet. It was the binding room
      all day: reference 17.4 while the actual slab rooms sat at 14.0
      (Gaestebad) and 15.4 (Wohnzimmer).
      **The rule this establishes: only rooms with a slab circuit belong in the
      condensation max().** If the coil's condensate drain is ever removed, put
      Arbeitszimmer back.
      Note the sequencing lesson - the previous entry on this page correctly
      refused to remove WH32 when it was mistaken for an outdoor station, and it
      is now removed for an entirely different and valid reason. Same edit,
      opposite justification; the justification is what mattered.

- [i] **A dropout of the binding room lowers the reference - and that is not a
      defect to fix.** Owner, 2026-07-31: *"There's nothing to fix about the max
      of a sensor that goes missing. We just don't know any better at this
      point."* Correct, and it retires the "options worth weighing" below, which
      were cleverness dressed as safety: holding a last-known value or
      synthesising a fallback adds no information, it only makes the guess look
      more confident.
      The missing-sensor case is a small subset of a much larger permanent
      blindness. **Coverage is 2 rooms of 7** (Gaestebad, Wohnzimmer). Bad, both
      Kinderzimmer, Schlafzimmer and Diele have no humidity measurement at all -
      and `Bad` is a bathroom, which is why "the condensation guard is BLIND to
      showers" is already an entry on this page. `dew_point_margin_c` at 1.0 K is
      what covers that whole class, and **sensors, not logic, are what shrink
      it** - the Shelly H&T rollout.
      Kept below as an explanation, because someone will one day see the limit
      move after a restart and need to know why. The right response was
      observability, and that is already done: `sensor.system_dew_point_source`
      names the binding room, so a change in it is visible.

  (original text, retained for the mechanism:)
  **A dropout of the BINDING room RELAXES the condensation limit.**
      Noticed 2026-07-31: `fineoffset_wh32_245` (Arbeitszimmer) went
      `unavailable` at 11:26 - battery, most likely, since its battery sensor
      went with it while the other rtl_433 devices stayed up - and the dew point
      reference immediately fell 17.4 -> 15.4 because the max() lost its highest
      member. The limit dropped 2 K with it.
      **That is the wrong direction on a sensor failure.** It happened to be
      harmless here (that room should not have been in the calculation at all),
      but the general case is not: lose the humid room's sensor and the plant
      becomes MORE aggressive exactly when it has less information.
      The `max()` has no notion of "a source I expected is missing". Options
      worth weighing: hold the last known value for that room until it ages out,
      fall back to the outdoor dew point when any expected pair is missing, or
      publish a distinct "degraded coverage" state that heatctl treats as a
      reason to add margin rather than remove it. Do this before the Shelly
      rollout multiplies the number of sources that can drop.

- [!] **AN HA RESTART CAN TRANSIENTLY RELAX THE CONDENSATION LIMIT.** Corrected
      entry - the first version of this said `fineoffset_wh32_245` was "dead
      since 11:26, battery the likely cause". **Wrong on both counts.** Its
      battery reads 100 %, and it recovered by itself 21 minutes later. The
      battery entity going unavailable alongside the others was simply all of
      that device's entities dropping together, which I read as evidence when it
      was a consequence.
      What actually happened (owner spotted the correlation): WH32 went
      unavailable at 13:26 local, **a few minutes after an HA core restart**, and
      returned at 13:47. Both `rtl_433` add-ons were `started` with watchdogs
      throughout and the other two devices never visibly dropped - but they are
      outdoor stations transmitting every ~16 s, so a restart-induced gap in
      them would be invisible. WH32 is indoors on the OG with a weaker path.
      Restart artefact and radio dropout cannot be separated from the evidence
      available; the SDR chain itself is healthy.
      **The operational point stands regardless of cause, and it is the one that
      matters:** MQTT-discovered entities are `unavailable` after an HA restart
      until their device next transmits. Combined with the entry above - a
      dropout of the binding room RELAXES the limit - **restarting Home
      Assistant can silently lower the plant's condensation limit for as long as
      it takes the slowest room sensor to report.** Here that was 21 minutes.
      Fix the max()'s handling of missing expected sources and this goes away
      too.

- [!] **A DEPLOY SHIPS CODE, NOT CONFIG - and that silently cost half a day.**
      2026-07-31. `run.sh` seeds the App's `config.yaml` on first start only and
      never overwrites it, deliberately: it is the operator's source of truth for
      the register map and safety limits. The consequence is that editing
      `config.yaml` in the repository does **not** change the running plant.
      Found when the capacity controller's own log lines still read
      `target 1.0` and 5 Hz steps after the change to 0.6 / 2 Hz had been
      committed, deployed, and reported as live. The App was running a config
      file from 13:14 the previous day. Three separate deploys had "succeeded".
      Mitigation shipped: `deploy/ha-addon/check-live-config.sh` prints the
      behavioural diff between repo and running config. It reports rather than
      reconciles - divergence is often legitimate (`mode`, host addresses,
      operator tuning) and deciding which side is right is a human job.
      **The memory note claiming "the App's live config is deliberately
      overwritten on every deploy" was wrong and has been corrected.** It is the
      opposite.
      Remaining known-legitimate divergence: repo ships `mode: heating` as the
      fresh-install default, live runs `mode: cooling` for the season.

- [!] **Merge `control.mode` and `control.demand.auto_mode` into one parameter,
      defaulting to `auto`.** Owner, 2026-07-31.
      Today they are two settings expressing one decision: `mode` takes
      `heating | cooling | off` (`main.py:202`) and `auto_mode` is a separate
      boolean that lets the house average pick `mode` instead. Two knobs for one
      question is how you get a plant in cooling with `auto_mode` half-forgotten
      in the other direction, and it is also why the repo ships `mode: heating`
      as a fresh-install default that is simply wrong for half the year.
      Target: `mode: heating | cooling | off | auto`, default `auto`.
      **Dependency the implementer must not skip:** merging the config surface
      does not make `auto` safe. `auto_mode` was switched off on 2026-07-29
      because it heated the house in July - correct logic, wrong conclusion,
      because it guesses the season from indoor temperature and only three of
      seven rooms have an air sensor. The recorded condition for re-enabling is
      *"only once layer 2's forecast can gate it"*, which lands with WP-S Stage
      2. So: merge the surface whenever, but `auto` must consult the forecast
      before it is allowed to be the default in a live plant.

## WP-R · Online parameter identification as a Rao-Blackwellised filter

Owner's observation, 2026-07-31: *"Did we just re-invent a Rao-Blackwell
filter?"* Not quite - but both halves are in the tree and only one wire is
missing, so this records the join and, more importantly, the caveats.

### What already exists

  - **Samples over parameters** - `derived.propagate()` draws `flow`, the
    `ua_sa` identification measurements, `f_sol`, respecting bounds (D-032).
  - **An exact Kalman filter over states** - `kalman.py`, 2-state.
  - **A likelihood signal** - the filter's own innovation.

That is exactly the Rao-Blackwell decomposition: sample the awkward part
(parameters), handle the conditionally linear-Gaussian part (states)
analytically, and marginalise the analytic part out. What is missing is that
**the sampling is offline and static** - it propagates uncertainty into derived
constants once, and the filter then runs on a single point estimate. The
particles never see the innovation, so they never learn.

### The join

One Kalman filter per parameter particle; weight each particle by the
likelihood of its innovation; resample. Online identification of `ua_sa`,
`f_sol` and `q_internal_w` then arrives as a by-product rather than as separate
machinery - which is what `docs/DESIGN.md` 7.3's identification ladder asks for.

Cost is not the obstacle: a 2x2 filter is a handful of multiplies and even 100
particles at a 60 s cadence is nothing. We already run 4000 offline samples per
derived quantity, which is more work than the online version needs.

### CAVEATS - none of these is optional, and each needs an answer

**(a) Particle degeneracy on static parameters. THE failure mode.** Parameters
do not evolve, so weights collapse onto one particle and the filter stops
learning while *looking* converged. It fails silently, which is the worst
property a thing can have here. Options, none free:
  - artificial parameter jitter - simple, but inflates the posterior and the
    jitter magnitude is another invented constant (D-030 applies to it)
  - Liu & West kernel smoothing - shrinks toward the mean while adding noise,
    preserving posterior mean and variance
  - resample-move (Gilks & Berzuini) - an MCMC step after resampling; correct
    and expensive
  - Storvik / sufficient-statistic filters - exact where the structure is
    conjugate
  **Detect it regardless of the fix chosen: publish effective sample size**
  `ESS = 1 / sum(w^2)` and alarm on it. Same lesson as the dew point argmax -
  a quantity nobody can see is a quantity that fails unnoticed for eight hours.

**(b) `f_sol` and `ua_sa` are hard to separate.** Both raise daytime air
temperature. DESIGN.md 6.1.1 already warns that unsensored rooms make the
3-state form unidentifiable; the same logic applies to telling these two apart
from one air measurement.
  **The natural experiment is night.** With no sun, `f_sol` has no effect, so
  night data identifies `ua_sa` alone; day data then identifies `f_sol` given
  it. Sun angle helps further - per-facade gain varies by hour and orientation
  while `ua_sa` does not, which is one more argument for the per-facade solar
  model already being in `solar.py`. Sequential identification, exploiting a
  free experiment that runs every day.

**(c) The parameters are not actually static, and that is the ANSWER to (a).**
`ua_sa` depends on flow (which starts modulating the moment the DC pump does)
and on which circuits are open; `f_sol` moves with shading, furniture and
season. Treating them as static is itself an approximation. So the jitter that
fixes degeneracy is not arbitrary - **it can be derived from the expected drift
rate**, which converts an invented constant into a measured one (D-031). Do it
that way round.

**(d) Bad control data identifies the controller, not the building.** While the
loops fight each other (D-030), the excitation is correlated with the
controller's own pathologies. This is the real reason WP-R comes after WP-S,
not merely a preference about ordering.

**(e) SAFETY MUST NEVER CONSUME AN IDENTIFIED PARAMETER.** An online estimate
feeding a safety limit is a mechanism for the filter to talk itself into a
breach - it would only need to become confident and wrong, which is precisely
what (a) produces. Parameters serve optimisation. The condensation constraint
stays on measured supply (D-031, D-032).

### Validation gates

  1. `ESS` published and alarmed before any parameter is believed.
  2. Night-only identification of `ua_sa` first - the cleanest separation - and
     it must agree with the 2026-07-31 manual identification within the stated
     sigma, or one of the two is wrong and that is the finding.
  3. Only then `f_sol`, conditioned on the identified `ua_sa`.
  4. No safety path reads any of it, checked by test.

- [!] **The static cooling fallback is LESS conservative than the live limit.**
      Found 2026-07-31 while measuring the loop's excursion for `target_margin_c`.
      `safety.vl_min_cooling_c` is 16.0, while the dew-derived limit that
      afternoon ran 16.5-16.8. The 5-minute statistics show the limit dipping to
      exactly 16.0 several times - each one a window after an App restart,
      before the first `heatctl/env/dew_point` message arrives.
      **So losing the dew point makes the constraint LOOSER, not tighter.** That
      is the wrong direction on a knowledge loss, and the same class of fault as
      the dew point `max()` relaxing when its highest member drops out.
      It is bounded - `dew_point_unknown` closes owned valves once the value has
      genuinely aged out (`dew_point_max_age_s`, 900 s), so this is only the gap
      between start-up and the first message, and the republish runs every
      120 s. But the gap exists and it is on the permissive side.
      Options: seed the limit pessimistically at start-up rather than from the
      static value; raise `vl_min_cooling_c` to something that is genuinely a
      floor rather than a mid-range guess; or refuse to cool at all until a
      dew point has been seen once. The third is the most honest and costs a
      couple of minutes of cooling after a restart.

      **UPDATE 2026-08-01 - the permissive gap above is GONE, and what replaced
      it is worse.** The static fallback this entry worries about was removed on
      2026-07-31, so there is no longer a loose limit at start-up. Instead
      `Safety.apply` hits `return 0.0, "dew_point_unknown"` and **closes every
      owned valve** until the first dew-point message arrives. Measured on the
      15:33 restart, the first run with safety overrides actually logged:

      ```
      15:33:28  SAFETY OVERRIDE dew_point_unknown on 10 circuit(s): [all ten]
      15:34:01  safety override dew_point_unknown cleared (was active for 33 s)
      ```

      **33 seconds of a fully shut manifold on every restart.** With the pump
      turning that is a flow collapse, which is Er03 - and Er03 **latches** and
      needs a human at the unit. heatctl was restarted four times that day and
      Er03 appeared three times; this is the most likely link for at least the
      morning occurrences, better than any of the theories entertained at the
      time.

      Two things make it a design fault rather than a tuning question:

      * **It inverts D-003.** Lost knowledge is supposed to fail OPEN. This
        fails CLOSED on lost knowledge, and unlike every other fail-closed path
        the consequence is not recoverable without a person.
      * **The valves are the wrong actuator for it.** "I have not been told the
        dew point" is not a measured danger to the screed; it is an argument for
        not MAKING cold water. That is a source-side action. Closing valves
        cannot stop the compressor and can only starve the pump.

      So the entry's own third option is right - refuse to cool until a dew
      point has been seen once - but it must be implemented source-side, and
      valve position must be left alone.

      Found only because safety overrides were finally logged the same day; the
      behaviour had been invisible in both the log and HA.

- [!] **DECIDED: collapse the two cooling margins into one.** Owner,
      2026-07-31: *"I am fine with collapsing all of that to one single number.
      The 'limit' has 1K of headroom."* Correct - and working out how exposed
      what `target_margin_c` was actually buying, which is not what the entry
      below assumed.
      **The guard trips AT the limit.** `safety.py` closes owned valves when
      `supply < cooling_supply_limit`. So if the controller also targets the
      limit, its normal operating point sits exactly on the guard's trip
      threshold and every quantisation tick trips valves. `target_margin_c` has
      been buying separation from the GUARD, not covering loop noise.
      Collapsing therefore has to move the guard down with it:

          now   guard trips at dew + 1.0   controller targets dew + 1.6
          one   guard trips at dew + 0.0   controller targets dew + 1.0

      The 1 K then becomes what it was always meant to be - the control margin,
      sized to how badly the dew point is known - and the guard becomes a
      genuine last resort at the physical boundary instead of a second budget
      stacked on the first. Excursions dip to dew + 0.8, still clear, and
      spurious trips stop.
      Worth **~290 W** at the 2026-07-31 operating point, on top of everything
      else recovered that day.
      **Not implemented** - it touches the safety path and was decided as the
      owner was leaving. Do it deliberately, with the guard change and the
      margin change in the same commit, or there is a window where the
      controller targets a limit the guard still trips on.

- [i] **(superseded by the entry above)** `target_margin_c` derived from drift.
      Measured 2026-07-31 over an hour of converged operation: supply holds to
      about +-0.1 K within 5-minute buckets (mostly the 0.1 K quantisation),
      while the LIMIT moves +-0.2 K underneath it as the dew point drifts.
      Aiming at margin 0 would therefore sit below the limit roughly half the
      time - not because the loop is sloppy, but because its target moves.
      The evidence supports about **0.4** rather than the current 0.6: the
      limit's own drift plus a quantisation tick. Owner asked the right
      question ("wouldn't a margin of 0 be on target?"); the answer is no, and
      the reason is measurable rather than a matter of taste.

- [!] **30-MINUTE OUTAGE, 2026-07-31 17:03-17:33, caused by a deploy with no
      failure semantics.** Recorded because the cause is procedural and will
      recur otherwise.
      `vl_min_cooling_c` was removed from BOTH `safety.py` and `config.yaml`.
      The deploy ran as a loose chain of commands: the code `scp` failed with a
      single line (`scp: Connection closed`), **everything after it ran anyway**
      - the config upload succeeded and the App rebuilt. Result: new config
      against old code, and the controller died on startup with
      `KeyError: 'vl_min_cooling_c'`.
      It failed SAFE - the coupler watchdog zeroed the outputs and the NC valves
      closed, which is the designed behaviour for a dead controller - but the
      house got no cooling for half an hour on a warm afternoon and **nothing
      announced it**. It was found only because the next status query returned
      `unavailable` for everything.
      **The lesson is not "be careful with scp".** A deploy that is a sequence
      of independent commands has no failure semantics at all: any step may fail
      and the rest proceed. Two of today's incidents share that shape - this
      one, and the capacity tuning that was reported as live for hours while the
      App ran yesterday's config.
      Fixed: `deploy/ha-addon/deploy.sh` is `set -euo pipefail`, **verifies by
      checksum that the upload actually arrived**, reports config drift and
      makes you acknowledge it, waits for `started`, and greps the log for a
      traceback before declaring success. Use it instead of hand-chaining.
      **DONE 2026-07-31: liveness now watched, two ways.**
        * `automation.heatctl_alert_when_the_control_loop_stops` - fires when
          `sensor.heatctl_supply_total` has been `unavailable` for 2 minutes,
          and again on recovery. heatctl publishes an MQTT last-will on
          `heatctl/status` which every discovered entity carries as its
          `availability_topic`, so a crash, a hang or a lost broker connection
          all surface. The 2-minute delay is deliberate: deploys take 30-90 s
          and an alert that cries wolf on every deploy gets muted, which would
          reproduce the failure it exists to catch. Notifies the phone AND
          raises a persistent notification, so it is still visible if the phone
          was not.
        * Supervisor App **watchdog enabled** (`watchdog: true`), so a
          transient crash restarts itself rather than only being reported.
      This is a prerequisite for WP-S change C, not a nicety: that compressor
      stop lives in the pump's flash and survives heatctl crashing, so a dead
      controller would leave the plant stopped indefinitely.

      (original text) **Nothing watches whether heatctl is alive.** The App has
      `watchdog: false` and there is no alert on the control loop stopping. A
      30-minute silent outage should not be possible to discover by accident.
      Simplest fix: an HA automation on `binary_sensor.heatctl_*` going
      unavailable, or the Supervisor's own App watchdog. Do this before the
      next structural change.

## WP-S implementation status — the three changes, 2026-07-31

Written down because they were discussed at length, agreed in principle, and
then existed only in conversation. The owner's framing: *"maximize flow,
maximize spread, limited only by demand and dew point."*

- [x] **A · Pin the pump at maximum flow. DONE 2026-07-31 18:56.**
      `pump_manual_speed_pct` (F6, 0x0107) 30 -> 100, THEN `pump_mode` (F4,
      0x0105) 1 -> 2. That order matters: F6 was at 30 %, so switching to
      manual first would have dropped flow to 30 % in the gap.
      Result: pump 70 % -> 100 % at unchanged spread (2.6 K) and unchanged
      compressor frequency (47 Hz), so m_dot_c went ~1169 -> ~1670 W/K and
      delivered heat ~3.0 -> ~4.3 kW. No faults.

      **Manual mode rather than pinning F8 (min speed) to 100** - the owner's
      call, and the reasoning is worth keeping. F8 = 100 would corner the DeltaT
      regulator so it has no room to move; F4 = manual turns it OFF. The
      difference matters twice over: a cornered regulator is still running and
      still wanting to throttle, and it is silently restored the moment anyone
      changes F8 for an unrelated reason - a service visit, a settings restore,
      someone chasing a flow problem. That is precisely the
      implicit-by-constraint design D-030 exists to reject.
      A concern about manual mode running the pump when the unit would rather
      stop it turned out to be unfounded: **F2 (`0x0101`
      `pump_operation_mode`) = 1, "Always open"**, governs WHETHER the pump
      runs and is a different register. F4 only governs how fast.
      (superseded plan follows)
      **A · Pin the pump at maximum flow.** NOT DONE. The unit runs its own
      DeltaT loop (F4 = AUTO, F10 = 2 K) which throttles flow when we throttle
      the compressor, cancelling the throttling - observed at 70 % while
      Arbeitszimmer was nowhere near setpoint, recovering to 90 % once the
      ceiling rose again.
      Mechanism: set **F8 `pump_min_speed_pct` = 100** so min = max = 100 and
      the loop has no room. One register write, reversible, keeps AUTO mode and
      its protections. **Do NOT switch to manual (F4 = 2) without setting F6
      first** - `pump_manual_speed_pct` is 30 %, so manual would drop flow, not
      pin it.
      Write it through `heatctl/hp/set/pump_min_speed_pct`, which already has
      range checking, the write budget and single-writer ownership. Not through
      an ad-hoc script.
      Note F8 currently reads **10 %**, not the 40 % default - which is also why
      the `flow = flow_max * speed/100` model is less well-founded than it
      looked (that derivation leaned on 0.58/1.44 = 40.3 % matching the
      default). The MULTICAL 403 settles it.

- **B · Stop the setpoint trim walking P04 down for capacity.** NOT DONE.
      Today: house warm + valves open -> step P04 down. That does not add
      cooling, because output is set by the frequency ceiling - and it is what
      walked past the useful point at 13:27, costing ~430 W.
      Target rule: **P04 lowers only when P04 is actually the binding
      constraint** - the machine reaching setpoint and stopping while demand is
      unmet. Otherwise leave it. Its remaining job is to rise when the house is
      satisfied (COP).
      **Ordering constraint:** B keeps the `limit + measured spread` floor on
      P04 until C exists. That floor is currently the only thing stopping a low
      P04 pulling supply below the dew point once the ceiling saturates.

- **C · Compressor stop as the bottom of the spread actuator. DESIGN
      SETTLED 2026-07-31, not yet implemented.**

      **Mechanism (owner's): write the setpoint OR "OFF" to P04.** There is no
      writable cooling-disable on this machine - `0x8003`'s cooling enable bit
      is READ-ONLY and `0x0004` Mode has no off value - and `0x0000` bit 0
      (unit power) would stop the internal DC pump, which is the only
      circulation the plant has until the buffer tank lands. Raising P04 above
      the return temperature stops the compressor on the machine's OWN logic
      while the unit stays powered, so the pump keeps turning at the 100 % it
      was pinned to.

      **This is NOT the setpoint-as-last-resort that was rejected earlier.** The
      distinction, and it is the whole point:
        - rejected: nudging P04 as a capacity modulator (19 -> 20 to back off a
          bit) - partial, slow, and it makes P04 carry the condensation
          constraint;
        - this: driving P04 to a value that unambiguously means OFF. Not a
          modulation, a stop - expressed through the only lever that does not
          also kill the pump.

      **Encoding: P04 = 30 (its maximum).** Not `return + margin`, which is a
      computed value racing a moving return and would silently restart if
      return drifted up. 30 is above any cooling return, needs no computation,
      is the top of P04's documented 7-30 range, and reads as "off" to anyone
      looking at the register.

      **P04 IS A TRANSPORT, NOT THE SETPOINT.** Owner: *"we do not mess with the
      setpoint in a way that is visible to anyone."* The logical setpoint and
      the register value are different things:
        - `setpoint.py` reads the current setpoint to compute its next move. If
          it ever reads back 30, the trim, the constraint memory and the
          reversal guard all reason from a number that is not a setpoint. All
          setpoint logic must operate on the LOGICAL value.
        - On restart heatctl reads P04 from the device. Reading 30 must be
          recognised as the OFF sentinel, not adopted as a setpoint. Safe
          because nobody would ever command 30 in cooling.
        - Telemetry publishes `setpoint` and the on/off state SEPARATELY.
          Never publish 30 as "the setpoint".

      **Caveat that shapes the sequencing:** unlike a valve command, this stop
      is written to the device's flash and SURVIVES A HEATCTL CRASH. Nothing
      restores it. For condensation that is the safe direction - a dead
      controller leaves the plant not cooling - but it is the same shape as the
      2026-07-31 17:03 outage: the house sits uncooled until a human notices.
      **Do the liveness alert before C goes live, not after.**

      Cost: two flash writes per stop/start cycle, bounded by `min_off_s`
      (600 s) to at most ~6/hour, well inside the budget.

      Implementation order, each stage observable before the next is
      authoritative:
        1. The abstraction: logical setpoint + `compressor_enabled`, register
           value derived, telemetry split, restart sentinel handling. OFF
           reachable by hand only.
        2. Wire the decision into `capacity.py` as the bottom of its range,
           with hysteresis and `min_off_s`.
        3. Only then delete the P04 floor - the payoff, and what breaks the
           `spread_est` -> floor -> setpoint circularity.

      **ALL THREE STAGES SHIPPED 2026-07-31 evening.** Stage 3 removed more
      than the floor, because the floor was not the only condensation logic
      living on the setpoint:
        * the `limit + measured spread` floor (circular - see the 18:00 entry);
        * the **breach branch**, which jumped the setpoint UPWARD on a measured
          breach. That is what caused the 2026-07-30 09:14 incident: a 0.1 K
          breach jumped the setpoint 18 -> 21, parked return water inside the
          restart dead zone, stopped the compressor and let the house climb 3 K
          on a 38 degC day;
        * the **constraint memory** (D-029), whose only writer was that branch -
          dead code that still looked live.
      A breach is now answered where it happens: the capacity loop cuts
      frequency immediately (its first lowering move is never delayed), stops
      the compressor at the frequency floor, and the valve guard trips behind
      that. Three responses, none of them the setpoint.
      Seventeen tests and one whole file guarded the removed mechanisms and
      went with them, replaced by `tests/test_setpoint_no_condensation.py` -
      five tests asserting the new invariant, mutation-verified against
      restoring the floor.

      (superseded outline follows)
      **C · Compressor stop as the bottom of the spread actuator.** In WP-S
      above. When the ceiling saturates at minimum frequency and supply is
      still too cold, stop the compressor and **keep the pump running** - that
      is how the loop warms back up. Only after C can P04's floor be removed.
      Needs the experiment: which register actually stops it (R32 to zero, the
      power bit, or the mode register) and what each costs in flash.

- [!] **Renaming an MQTT-discovered entity does not change its entity_id.** HA
      keys on `unique_id`, so the discovery `name` change made on 2026-07-31 to
      tidy `sensor.heatctl_hp_writes_in_the_last_hour` into
      `..._hp_writes_last_hour` was a **no-op** - the original id persists and
      the commit that "fixed" it changed nothing. To actually rename, either
      change the `unique_id` (creating a new entity and orphaning the old) or
      rename in the entity registry. Worth knowing before anyone tidies another
      one and believes it worked.

- [!] **THE P04 FLOOR IS CIRCULAR, AND IT CAUGHT US LIVE, 2026-07-31 18:00.**
      Owner: *"The current margin is gigantic, spread should go up."* It could
      not, and the reason is the clearest demonstration of D-030 yet.

          spread_est = 3.20     decaying MAX, latched from a brief excursion
          limit      = 16.5
          P04 floor  = 16.5 + 3.20 = 19.7  ->  setpoint forced UP to 20.0

      The sequence, all within twenty minutes:
        1. The capacity controller pushed the ceiling 62 -> 73 Hz. Correct.
        2. The compressor briefly produced a 3.2 K spread.
        3. `_spread_est` is a decaying maximum, so it LATCHED 3.2 and relaxes
           only slowly (0.995 per sample).
        4. The P04 floor is `limit + spread_est` -> 19.7 -> the setpoint was
           forced UP from 19 to 20.
        5. Higher setpoint -> the machine throttled itself to 35 Hz (its
           minimum) -> spread collapsed to 2.3.
        6. The estimate still held 3.2, so the floor stayed high and the plant
           stayed throttled, margin stuck at 0.8 K.

      **The controller sabotaged itself through its own success.** The floor is
      computed from MEASURED SPREAD, but spread is a *consequence* of the
      control action, not an independent constraint - feedback through the
      wrong path. Making the capacity controller more aggressive made this
      worse, not better, because bigger excursions latch a higher floor.

      No fault was involved: `heat_pump_active_faults = none`. The frequency
      drop was the unit's own modulation easing off as return approached its
      raised setpoint - not a protection trip.

      **This is the argument for change C.** Once the compressor can be stopped
      as the bottom of the spread actuator, the P04 floor is deleted entirely
      and this loop cannot form. Until then, note that a decaying-max estimate
      feeding a floor is strictly worse than a slower controller: consider
      whether the estimate should sample only at steady state, or be dropped
      from the floor in favour of a fixed worst case, as an interim.

      Also worth an alarm: **`silent_max_fan_cooling` reads 65512**, which is
      -24 as a signed int16, and has done constantly. Not the cause here, but a
      garbage value in a register that caps the condenser fan in silent mode
      deserves investigation before anyone pushes frequency harder.

- [!] **750-8212 ARRIVED 2026-07-31. Phase 0 is two hours of bench work and it
      gates everything.** The 2026-07-29 entry above records that the PLC was
      ordered and the five things to settle; this records the plan for the unit
      now physically here.

      **The gating question: does the PFC200's Modbus server offer an
      equivalent output-zeroing watchdog?** heatctl's outermost safety net is
      the 750-352's coupler watchdog at `0x1000+`, armed with mask `0x8020` so
      only FC6/FC16 output writes retrigger it - which means heatctl needs no
      separate heartbeat, its per-cycle valve write IS the heartbeat. Verified
      on hardware 2026-07-26. It is the only failsafe that survives heatctl
      crashing outright, and on 2026-07-31 it did exactly that during a
      30-minute outage.
      A PFC200 is not a coupler; its Modbus server presents a process image
      under its own program's control. If the answer is yes, the swap is a day.
      If no, the watchdog must be built in CODESYS and the whole toolchain is on
      the critical path for what was meant to be a drop-in - at which point
      point (e) of the 2026-07-29 entry applies in full.

      **Phase 0, bench, no plant downtime, ~2 h:**
        1. Power it standalone, find it, get into the WBM, check firmware.
        2. The watchdog question above.
        3. Process-image layout. `config.yaml` hardcodes `base_register: 12`
           for both sensors and valves; a PLC maps its image differently from a
           352. This is the THIRD time the register map has moved.
        4. Internal-bus 5 V budget against the existing module rail - the
           8212's budget differs from the 352's, and the symptom of exceeding
           it is not a clean failure but modules at the far end reading
           nonsense. Use WAGO's configurator, do not eyeball it.

      **Phase 1, the swap, ~1 day, only if Phase 0 clears:** back up the 352's
      watchdog and IP config, swap (same backplane, modules carry over), IP to
      the coupler's address, re-verify every register against known live sensor
      values, re-arm the watchdog and **re-run the deliberate trip test** from
      2026-07-26, then run heatctl against it and diff the readings.

      **Window: 08-01 / 08-02.** Forecast 27.3 and 26.2 degC with 0 hours over
      the delivery ceiling, against 31.3 on 08-03 and 36.0 on 08-04. Losing
      plant I/O for a few hours costs almost nothing on those two days and a
      lot afterwards. Do not let it slip to 08-03.

- [!] **The setpoint trim should be a PI, like the capacity loop.** Owner,
      2026-07-31: *"I'd probably want that to be a PI, but for now I accept it
      as an immediate solution."*
      Shipped instead: a regime-dependent CADENCE (`saturated_interval_s: 120`
      while the house is under-served, `interval_s: 1800` when only trimming
      for comfort). That fixes the immediate problem - with the condensation
      floor gone, P04 became the binding constraint and the walk from 19 to 16
      would have taken 90 minutes purely on the clock - but it is still a fixed
      1 K step at two speeds, which is a coarse stand-in for proportional
      action.
      The same argument as `capacity.py`: a step controller with a deadband and
      an interval is a bang-bang with hysteresis; its steady state is a limit
      cycle rather than convergence. A PI on the house deviation would size the
      move to the error.
      Two things make it harder here than in the capacity loop, and are the
      reason it is not done yet:
        * **P04 is quantised to 1 K** (int16 degC register), so the output is
          integer and a PI must accumulate below the quantum rather than
          rounding each cycle to zero;
        * **the process is the HOUSE** (5.6 h fast mode), not the water loop, so
          the integral term needs an anti-windup that survives hours - and the
          plant saturates often, which is exactly when naive integrators wind
          up.
      Do it after the capacity PI, and reuse `heatctl/pid.py` rather than
      hand-rolling a second one.

- [!] **CASCADE ERROR, 2026-07-31 20:52-21:02: the outer loop was made as fast
      as the inner one and outran it.** Recorded because it is the sharpest
      lesson of the day and it very nearly cost a slab.

      With the condensation floor removed, P04 became free to fall - correct.
      But `saturated_interval_s` had just been set to **120 s**, which is the
      same speed as the capacity loop's own settle times (60 s lowering,
      120 s raising). The trim walked P04 **19 -> 14 in ten minutes**, the
      machine chased it, and the frequency ceiling could not cut fast enough to
      hold supply up:

          20:59   supply 15.6   limit 16.2   MARGIN -0.6   dew 15.2
                  -> 0.4 K from actual condensation

      **In a cascade the outer loop must be several times SLOWER than the
      inner.** That is not a tuning preference, it is what makes the inner loop
      able to reject the outer loop's moves as disturbances. Setting them equal
      turns a cascade into two controllers racing. `saturated_interval_s` is now
      **900 s**, about 7x the inner loop's interval.

      **What worked, and is why nothing was damaged:** the capacity loop cut the
      ceiling 73 -> 52 continuously, and the valve guard tripped and closed the
      owned circuits. Supply bottomed at 15.6 against a 15.2 dew point - no
      condensation. The layering held even while one layer was mistuned.

      **What to take from it:**
        * The floor removal was right; the cadence change shipped alongside it
          was not, and shipping two changes to the same axis in one evening is
          how you cannot tell which one bit.
        * Any future PI on the setpoint (owner's stated preference) inherits
          this constraint: its bandwidth must sit well below the capacity
          loop's, or it reproduces this exactly and faster.
        * Eight of ten circuits still cannot close, so the valve guard is a
          partial protection. It was the capacity loop that did the real work.

### 2026-08-02 — [!] pre-charge lead horizon widened to 24 h, ON TRIAL

Owner asked to "try hooking up the prediction to the precharge", noting *"no one
will be bothered by a lack of comfort for a day or two"*. **The prediction was
already hooked up** — estimator publishes `opt/setpoint_delta`, `mqtt_plane`
subscribes with a staleness contract, `main.py` applies `active = dial + delta`
and clamps it. It was live and acting: −0.20 K at 22:00.

What it could not do was act *overnight for the next afternoon*, and that is the
one job it exists for.

| | |
|---|---|
| horizon (was) | `2 * tau_fast` = **11.2 h** |
| tomorrow's 15:00 peak, from 22:00 | 17 h out → weight **0.36** |
| forecast ask for that day | 0.43 K pre-charge, 7 h over ceiling |
| delta actually produced | **−0.20 K** |

Nothing was malfunctioning. The horizon simply did not reach, exactly as
designed.

**THE TWO ARGUMENTS, NEITHER DECIDABLE FROM THE PARAMETERS.**

  * *Short (11.2 h, shipped):* the delta is recomputed every minute, so it needs
    only enough lead to FILL the mass — `tau_fast`. Asking earlier spends
    comfort and standing loss on charge a later cycle could put in just as well.
  * *Long (24 h, now running):* the charging opportunity and the demand are one
    diurnal cycle apart. This house has spare capacity at night and none in the
    afternoon. Waiting until the peak is inside an 11.2 h horizon means starting
    ~09:00, when the load is already rising and the capacity is going away.

The short argument assumes the later cycle will still *have* capacity. Nothing
here measures that, which is the actual gap. So the horizon became an explicit
`optimizer.lead_horizon_h` rather than an implied constant; default unchanged,
config.yaml sets 24.0, revert by removing the key.

**Note the near-miss.** The first attempt at this changed the default and
falsified `test_imminent_excess_outweighs_identical_excess_a_day_away`, a
mutation-verified test. Reading it showed the shipped reasoning was stronger
than assumed — it is *not* the impulse-survival error, it is a feedback-cadence
argument. A test disagreeing with a change is evidence about the change.

**What would settle it:** whether morning spare capacity exists is measurable —
`ceiling_w` minus forecast load, hour by hour, is already computed in
`hourly_forecast()`. If the 06:00–10:00 hours reliably show slack, the short
horizon is right and this should revert. If they are already tight on hot days,
the long one is right and the horizon should be *derived* from the last hour
with slack rather than set to 24. That derivation is the real fix; 24 h is a
trial standing in for it.

**Watch:** overnight room temperature undershoot vs. `dial + delta`, and whether
tomorrow's afternoon still saturates. Discomfort tolerance was explicitly given
for a day or two — it does not extend past that.

### 2026-08-04 — [!] Er03 latched 11 h; the flow floor guards only half the loop

**Current state at time of writing: Er03 latched since 03:39:54, water pump
off, compressor 0 A, no cooling on a day forecast 6.8 kW peak and 3 h over
ceiling.** Needs a unit reset, which heatctl must not do itself (register
0x0000 is the HA automations' to write — single-writer rule, CLAUDE.md).

**Timeline.** Cleared 08-02 10:58 and stayed clear through 40 h of heavy
cooling. Returned 08-03 23:56, then 08-04 03:10, 03:23, 03:39 — three retries
in half an hour, each clearing in ~3 min, the last one latching for good.
`pump_non_stop` went off at 08:37, after the latch, so it is not the cause.

**Both clusters are at night, at low load.** That is the pattern, and it points
at the thing the flow floor does not cover:

| lever | who owns it | at low load |
|---|---|---|
| valve opening | heatctl (`min_open_pct`, flow floor) | held at 55 % mean |
| **circulation pump speed** | **the unit / HA automations** | **50 % → 40 % → 0** |

The flow floor did its job — measured at the latch, five circuits at 100 % and
five at 10 %, mean exactly 55.0 %. Flow still failed, because **flow is the
product of valve opening and pump speed, and heatctl owns only one factor.**

Note also that 55 % *mean* is not 55 % *flow*: five circuits open and five
nearly shut is hydraulically nothing like ten at 55 %, and a proportional
actuator at 10 % passes far less than a tenth. The mean is the wrong statistic
for a constraint that is about total flow. `circuit_opening_flow_proxy` already
reports 55 % on that distribution, so the proxy inherits the same flaw.

**What to do, in order:**
  1. Establish whether the flow switch is genuinely tripping or is itself
     faulty/fouled — every conclusion here assumes the sensor is honest, and
     nothing has verified that. The rotameters would settle it in minutes.
  2. Make the flow floor a floor on the *minimum* circuit, not the mean, or on
     a proxy that models valve authority rather than averaging position.
  3. Decide who guarantees pump speed at low load. `pump_non_stop` (0x0000
     bit 4) is the obvious lever and heatctl may not touch that register —
     so this is an HA-side change, or a case for renegotiating the
     single-writer boundary (see the 2026-08-02 P04 entry, same theme:
     heatctl's authority stops short of the thing that actually protects it).
  4. Until then Er03 recurrence is expected on any low-load night, and
     recovery needs a human. That is the real cost.

**Process note.** This was reported to the owner as "no faults" while it had
been latched ten hours. The fault entity was never queried; absence of error
lines in a 12-second log window was read as health. The log window was 12
seconds because of the pymodbus flood fixed in the same session — a defect in
observability turned into a defect in the report.

### 2026-08-05 — Er03: the pump CYCLES when the compressor is idle

Owner recalled setting pump non-stop and min speed to 100 and wondered whether
the 08-04 reset lost it. Checked against 14 days of InfluxDB history — **the
settings are intact, and they were never the ones that matter.**

| register | set | now | transitions in 14 d |
|---|---|---|---|
| F4 `pump_mode` (0x0105) | 1 auto → **2 manual**, 07-31 18:56:53 | 2 | none since |
| F6 `pump_manual_speed_pct` (0x0107) | 30 → **100**, 07-31 18:56:30 | 100 | none since |
| **C01 `pump_non_stop` (0x0000 bit 4)** | — | **off** | **none, ever** — 101 points, all off since 07-27 |
| F9 `pump_regulation_speed_pct` | — | 10 | none |
| F8 `pump_min_speed_pct` | — | 10 | none |

So the 07-31 intervention took and survived the reset. Manual 100 % governs
**how fast the pump runs while it runs** — it says nothing about *whether* it
runs. C01 is the knob for that, and it has been off the whole time.

**The mechanism, corrected.** Earlier this was read as the pump "winding down"
50 → 40 → 0. It is not modulating: in manual mode it runs at 100 or not at all,
and `pump_cycle_min` is 30. Those figures are 2 h bucket MEANS of a pump
cycling on and off — 50 % means on half the time. **Er03 fires when a
compressor start lands in a pump-off window.**

That also explains the clean night of 08-04→05: the compressor never stopped,
so the pump never cycled, so there was no off-window to start into.

**The fix is C01, and it should be set AT THE UNIT'S FRONT PANEL**, not over
Modbus. C01 shares register 0x0000 with bit 0, which the HA automations write;
a read-modify-write from anywhere else races them, and bit 0 is unit power.
Setting it at the panel avoids the register entirely.

**Untested hypothesis, flagged by the owner:** using 0x0000 bit 0 to clear a
latched fault. Bit 0 = power is documented, but *toggling it to reset a latch*
has never been tried. The successful clears were physical resets, which may be
a mains interruption; a control-bit power-off may be a standby that preserves
the latch. Do not build auto-recovery on this until it has been tested with
someone present. Until then, prevention (C01) is the whole strategy.

### 2026-08-05 — C01 pump_non_stop set; the Er03 fix is now on trial

Written from heatctl over MQTT (`heatctl/hp/set/bit/pump_non_stop`), which
routes to `set_control_bit` — read-modify-write against a register actually
read, no-op writes refused for flash wear.

```
0x0000   65 -> 81      (0x41 -> 0x51)
         bit 4 pump_non_stop  0 -> 1
         bit 0 power          1 -> 1   preserved
         bit 6 A45 EV mode    1 -> 1   preserved
```

Read back **from the unit's registers**, not a command echo.

This was possible only because the single-writer constraint turned out to have
been void since 2026-07-28 (see that entry). The previous recommendation — walk
to the front panel — was an artefact of a stale doc.

**F6 manual speed stays at 100 %,** and the earlier suggestion to reduce it was
wrong. Two levers move spread in opposite directions: compressor frequency
raises it (more Q at fixed flow), pump speed lowers it (more flow at fixed Q).
The binding constraint is manifold SUPPLY staying above dew point + margin, and
supply is the cold end, so low spread is margin. Throttling the pump spends
exactly the headroom `capacity.py` exists to use.

**The test is the first low-load compressor stop.** Prediction: `water_pump`
stays `on` and `dc_pump_speed` stays at 100 while `compressor_current` goes to
0. Before C01, the pump cycled on `pump_cycle_min` = 30, and an Er03 fired when
a compressor start landed in an off-window. Verify in InfluxDB, not the add-on
log — see below.

**Deliberately NOT deployed alongside this:** the committed fix for the
duplicated pymodbus errors. Deploying restarts heatctl, and a restart commands
P04 to 30 and back ~30 s later, i.e. a compressor stop/start — the exact
transition under test. Doing both at once would make an Er03 unattributable and
would spend the owner's absence on a cosmetic fix. C01 should make that restart
safe; that is a reason to deploy *after* it is proven, not before.

**Consequence worth noting:** the add-on log is currently unusable again, this
time from the duplicated transaction-id errors (~12/min), which is why the C01
write itself could not be found in it. Verification came from MQTT and
InfluxDB. The transaction-id errors themselves — ~6/min on the heat-pump link,
two separate pymodbus clients so not our concurrency, most likely the RS485→TCP
gateway — remain unexplained and are their own open item.

### 2026-08-06 — Looked closer at the cycling and the dew-point dips

Owner: *"I see the compressor cycling instead of reducing frequency. It also
seems like we were below dew point repeatedly during the night."* Both real.
Nothing changed on the plant; this is the investigation.

**My first framing overstated it.** Comparing hourly VL *minima* against the
hourly *mean* limit made brief dips look like whole bad hours. Measured against
the limit in force at each sample, over 20 h:

| | excursions | total |
|---|---|---|
| below the ACTUAL dew point | 12 | **3 min**, longest 1.5 min |
| inside the 1 K margin only | 210 | 370 min (31 % of the time) |

So condensation exposure is small — and consistent with the owner's own earlier
ruling that a minute or three below dew point is not harmful if rare. What is
not small is living inside the margin a third of the time; the margin is meant
to be headroom, not the operating point.

**R32 IS binding — I was wrong to say otherwise.** That claim came from the same
aggregation error (hourly mean ceiling vs hourly max frequency, while the
capacity loop moves the ceiling within the hour). At matched timestamps: 116 of
659 samples above the ceiling then in force, median excess 8 Hz, worst +17 Hz —
and the excursions cluster in restart windows.

**Mechanism.** `freq_min_hz` = 30 exceeds the night load, so the unit has no
lower gear and MUST cycle. On restart the return-vs-P04 error is maximal by
construction (P01 dead zone 2 K), it ramps to ~50 Hz, supply plunges, the
capacity loop slams the ceiling to 30–32, the compressor descends, supply
recovers. The loop works; it is simply reacting after the plunge rather than
preventing it. The valve guard never engages because `undertemp_dwell_s` is
180 s and the longest excursion is 90 s — as designed.

**Silent mode is not the problem.** `silent_mode` on, `heat_pump_mode` cooling,
modes agree — all unchanged since 08-02 16:31, so the 08-04 power cycle did not
reset them.

**F10 is NOT the reactivation dead zone.** `0x010B` F10 is the DC pump's
inlet/outlet ΔT *target* (2–30, default 5, set to 2). The reactivation dead
zone is P01 `restart_diff_c` at `0x008D`. **Both currently read 2.0**, which is
exactly how they get conflated.

F10 is also **inert right now**: F4 `pump_mode` = 2 (manual) at 100 %, so the
pump does not regulate to F10 at all. That retires the open puzzle in
`heatpump_map.py` — the pump observed at 70 % with 2.9 K spread against an F10
target of 2 K, "something else is in charge and we could not see what". It was
in auto then; since 07-31 18:56 it has been manual. The doc claim that "F10=2
holds the pump at full flow" remains unverified and is now unverifiable while
manual mode holds full flow by itself.

**Caveat that could change all of it:** `sensor_provenance` records the manifold
pair reading ~0.5 K below the heat pump's own sensors at idle. Most of the
"inside margin" time is between −0.3 and −0.7 K. **A 0.5 K calibration offset on
`supply_total` would erase most of these excursions.** Cross-calibrating the
VL/RL pair at settled no-flow is already on this list; it is now a prerequisite
for acting on any of the above, not a nice-to-have.

**Candidate fix, NOT implemented:** lower R32 to minimum at RESUME and let the
capacity loop earn it back, so restarts are gentle instead of reactive. Cannot
stop the cycling — that is a capacity mismatch and needs buffer volume, not
control.

### 2026-08-06 — Room sensing: three Shelly H&T G3 wired, and the target that isn't this

Three Shelly H&T G3 units, all mains-powered (`ext_power` on, battery 0 %,
so the 7200 s `sleep_period` two of them carry is moot), reporting every
6-12 minutes:

| device | area | heatctl room |
|---|---|---|
| Raumcontroller Elternachlafzimmer | schlafzimmer | `schlafzimmer` |
| Raumcontroller Naomi | kinderzimmer | `kind_naomi` |
| Raumcontroller Bad | bad | `badezimmer` |

That takes the house from 3 of 7 rooms with comfort feedback to 6 of 7.
**`kind_natalie` is now the only blind room** and still runs on the house
average.

**The staleness window had to move first.** At 6-12 min reporting against a
300 s window, each room would have been called stale about a third of the time,
and every flip switches the control path AND resets that room's integrator - so
the rooms would never settle. `control.room_temp_max_age_s` now defaults to
900 s, safe against a 5.62 h air/slab mode. Without that, wiring the sensors up
would have looked like bad tuning.

**Shipped today: option A, the HA bridge.** Three automations republish each
temperature onto `roomtemp/<room>`, matching the existing Controme pattern.
Retained, so heatctl gets a value the instant it reconnects rather than running
the return-temperature fallback for up to 12 minutes; the cost is that a
retained value can look fresh for up to one staleness window after a restart.

**This raises the layer-1 independence debt from two rooms to five.**
`docs/HA_INTEGRATION.md` risk 2 already records it. Accepted deliberately for
today.

#### The target (owner, 2026-08-06)

> the whole control on the PFC200, an MQTT there, and the Shellys connecting
> directly to this MQTT, making the whole setup as HA independent as possible

Three steps, and each stands on its own:

1. **Shellys publish to the broker directly** (option B). One-time RPC config
   on each device - they are at `192.168.178.64`, `.67`, `.68`, mains-powered,
   Gen3, so MQTT can run alongside the HTTP/WS the Shelly integration uses. HA
   keeps battery and firmware entities; heatctl subscribes to the device topic,
   the way it already does for Arbeitszimmer's rtl_433 sensor. Needs an MQTT
   user, since the Mosquitto App rejects anonymous clients. **Removes HA from
   the path for three rooms.**
2. **A broker on the PFC200.** Then the Shellys and heatctl share a broker that
   does not depend on the HA machine being up at all.
3. **heatctl itself on the PFC200.** This is the step that changes the
   hardware story: today the WAGO 750-352 is a dumb Modbus TCP coupler and the
   control runs on the HA host, so the control core depends on a general-purpose
   machine it does not own. A PFC200 runs the control on the same hardware that
   owns the I/O.

Worth noting what each step buys, because they are not equal: step 1 removes an
automation that can be turned off by accident; step 3 removes an entire machine
from the dependency chain. Step 3 also interacts with the 30-year-maintainability
promise in both directions - fewer moving parts, but a specific PLC to keep
alive.

### 2026-08-08 — [!] both Modbus endpoints lost at once: a switch, probably a loop

~13:18 to ~13:45 the WAGO coupler (`192.168.178.52:502`) AND the heat-pump
RS485→TCP gateway (`192.168.178.37:4196`) were both unreachable from the HA
host — ping and port. The HA host itself stayed fine, which is what made this
diagnosable: not two device faults, one shared path.

Owner reset an aging TP-Link **dumb** switch in the chain and the links
returned. The upstream MikroTik was reporting **excessive broadcast traffic,
consistent with a loop**. A broadcast storm saturating that segment explains
both devices vanishing together while everything else kept working, and it will
recur until the loop is found. The dumb switch offers no diagnostics, so there
is nothing to read from it directly.

**heatctl behaved correctly, and "correctly" still meant no cooling:**

```
13:18:47  coupler watchdog trigger write FAILED
13:18:47  FAILSAFE: stale_data
13:21:36  failsafe write to 100% failed for 10/10 valves: modbus not connected
```

The coupler watchdog expired on its own, zeroed the outputs, and the NC
actuators CLOSED. heatctl kept trying to write the failsafe position and could
not. That is the layering working as designed — the coupler's own watchdog is
the only thing that survives loss of the controller — but the outcome is a
plant with every circuit shut and no supervision of the heat pump, which had
Er03 latched throughout.

**What this exposes, beyond the switch:**

1. **The I/O path and the heat-pump path share a failure domain.** They are
   different protocols to different devices, but one segment. Losing it loses
   both the ability to read the plant and the ability to command the source.
2. **Availability, not safety.** Nothing unsafe happened and nothing could
   have: valves closed, the source was already locked out. But cooling stopped
   for the rest of the day, and the day after was forecast 8 h over ceiling.
3. **This is an argument for the PFC200 target** beyond HA independence. With
   control running on the hardware that owns the I/O, the control↔I/O link stops
   crossing the network at all — a switch fault can then cost telemetry and
   layer 2, but not the control loop itself. Worth weighing when sequencing
   that work.

**Open:**
  - Find the loop. Managed ports with storm control, or STP, on whatever
        the coupler and gateway hang off.
  - Consider whether those two devices should share a path at all.
  - The aging dumb switch is a diagnostic dead end; replacing it with
        something manageable would at least make the next occurrence legible.

### 2026-08-08 — VL/RL calibration: three methods, three confounds, one real finding

The plant was idle after a 33 h Er03 outage, so the long-wanted calibration
window looked free. It was not. Recorded in full because the negative result is
what stops the next attempt costing another evening.

| attempt | condition | why it was invalid |
|---|---|---|
| 1 | no flow, 27 h settled | **separate water columns.** The header sensors read water that sat in pipe runs through 24-26 degC rooms; the circuit sensors read water that sat in the 22 degC slab. Nothing mixes them without a pump, so the difference measured LOCATION. |
| 2 | full flow, compressor off, 8 min | **still a thermal transient.** Water was warming from the cooling that had just stopped; sensor differences were lag, not offset. |
| 3 | full flow, compressor off, 17 min | **the building is a heat source.** "Compressor off" is not "no heat input" - circulating water picks up slab heat continuously, so `rl_total > vl_total` by however much it collected. |

Attempt 1 produced `vl_total - rl_total = +0.775 K` and I reported it as a
calibration offset with consequences for the condensation guard. **Both were
wrong.** At full flow the same two sensors sit within 0.25 K of the pack; the
+0.775 was two different water columns. Owner's challenge - "all other sensors
show a measurement in the same range, but these two are both way off?" - was
what exposed it, and the follow-up that all probes are the same batch, same
cable length, and both header sensors sit at the manifold killed the two
systematic explanations offered (2-wire lead resistance, differing ambient).

**Attempt 3 refutes itself, visibly.** `vl_total - rl_total` GREW from -0.405
to -0.858 K over the 17 minutes. Equilibrating water would show the pickup
shrinking as it approaches slab temperature. It grew, because afternoon solar
gain was increasing the heat the slab hands to the water. There is no quiet
moment to calibrate in.

**What this means:** the -0.4 to -0.9 K observed is entirely consistent with
ZERO sensor offset plus real slab pickup. The method cannot separate the two.
Calibration needs a reference instrument, full stop. Every attempt to be clever
about it has failed for a different reason, which is itself the signal.

#### The finding that survives: Wohnzimmer's slab is not one temperature

Measured during attempt 3, full flow, all circuits open:

```
return_circuit_9     24.35   +2.90 K   Wohnzimmer
return_circuit_8     22.56   +1.11 K   Wohnzimmer
return_circuit_10    21.63           Wohnzimmer
return_circuit_2     21.49           Wohnzimmer
the other seven      20.76 - 21.70
```

Owner identified the cause immediately: **that is where the sun is on the floor
right now.** The two outliers are adjacent circuits in the same room, so this is
a spatially coherent solar signature, not two faulty sensors - hk09 held +2.90 K
with a stddev of 0.05 over 25 samples.

**Wohnzimmer's four circuits span 2.86 K.** `energy.py` models each room as ONE
slab at ONE temperature, and for this room that abstraction is wrong by more
than most effects being chased elsewhere. It is the building survey's warning -
"any per-room solar model that treats rooms as similar will be wrong about this
one specifically" - appearing directly in return temperatures.

  - Decide whether the slab model needs to be per-CIRCUIT rather than
        per-room, at least for rooms with several circuits and high glazing.
        Per-room is cheaper and right for the four single-circuit rooms.
  - Note the diagnostic value: a circuit reading far above its neighbours
        at equal commanded opening is either solar or no flow, and the two are
        distinguishable by whether the pattern is spatially coherent and
        follows the sun. That is a better stagnation test than the
        cabinet-air comparison, which is emitter-dependent (see 2026-08-06).

- **The 0.90 shading factor is a certificate constant, not a measurement.**
      Raised by the owner 2026-08-09 with one word — "What shading." — and the
      honest answer is that nothing at this site has ever been surveyed for it.
      It enters every effective collector area via `brutto × 0.70 frame × 0.90
      shading × 0.9 non-perpendicular × g 0.50`, and the only justification on
      record is that the product reproduces the certificate's own stated areas.
      The incidence factor is genuinely superseded (solar.py computes the real
      angle hourly); the shading one is still a flat annual constant applied to
      an hourly model.
      **It is most wrong where the gain is.** Overhangs, reveals and balconies
      shade HIGH sun. The east gain arrives at 7–27° elevation between 07:00 and
      10:00, when nothing built into a facade blocks it — so 0.90 probably
      *understates* the morning peak, and any real obstruction there would be
      horizon, neighbours or vegetation, none of which is documented.
      Not urgent: removing it entirely moves Schlafzimmer 788 → 876 W against a
      floor that removes 253 W, so the 3× overshoot stands either way. Worth
      doing as a per-window survey when someone is at the house with the plans,
      at which point it should become a per-window number in `solar.rooms`
      rather than a factor smeared across the whole building.

- **Falsify the per-room solar shape against the room sensors.** D-034
      predicts distinct peak times on a clear day — Schlafzimmer 10:00,
      Wohnzimmer 11:00, Arbeitszimmer 13:00, the two south children's rooms
      15:00 — and three of those rooms now have a Shelly H&T. This is the check
      the per-facade model could not support: a house average has no per-room
      shape to be wrong about. A room whose measured rise leads or lags its
      predicted peak by more than an hour means its window assignment or its
      azimuth is wrong, not that the gain is mis-sized.
      Do it on a clear day with the plant in a steady mode, or the control
      response confounds the disturbance.

- **Schlafzimmer needs external shading, and that is a building decision
      rather than a control one.** One east window admits ~4.9 kWh on a clear
      day into a slab holding 706 Wh/K: absorbing it needs 6.9 K of pre-cooling
      and the dew point permits 3–4. No setpoint, distribution weighting or
      pre-charge schedule closes that gap — the room will run above setpoint on
      sunny mornings until the gain is rejected outside the glass. Worth
      pricing against the alternative, which is accepting the excursion.
      Wohnzimmer is 2.9× over on the same arithmetic but spreads its load
      across four circuits and an open-plan ground floor, which is why it
      presents as less severe despite collecting more per m2.

- **The manifold cabinet has temperature but no HUMIDITY, so its dew point
      is unknowable — and the manifold condensed.** Observed 2026-08-10
      alongside the Bad floor.
      **CORRECTION, same day:** the first version of this entry said "nothing
      measures the manifold cabinet's air". That was wrong — there are three
      sensors, `manifold_cabinet_air_12/15/16`, reading 19.6-20.2 °C. The gap
      is humidity, not temperature, and it is the humidity that a dew point
      needs. Written from memory instead of from the entity list, which is the
      same mistake this file keeps recording.
      The limit is a max over ROOM dew points and the manifold is in none of
      those rooms, while carrying the coldest water in the house (VL, before
      any slab has warmed it). It is protected only by the room maximum
      happening to be conservative enough, which is luck rather than design.
      One humidity sensor in the cabinet, added to the reference's pair list,
      closes it — the temperature side is already there. Until then treat
      manifold condensation as an unmonitored failure mode.

- **The dew-point pair list is duplicated between two HA template helpers**
      (`system_dew_point_reference` and `system_dew_point_pairs`, 2026-08-10).
      The count is only trustworthy while the two lists agree, and nothing
      enforces that — a room added to one and not the other gives a count that
      certifies a reference it does not describe.
      Proper fix is to compute the dew point in heatctl from the room humidity
      topics it already subscribes to, which also removes HA from a safety
      path (docs/HA_INTEGRATION.md records that as a known risk). That is the
      real target; the twin helpers are the stopgap.

- **Generalise the lesson: alarm on DEGRADED INPUTS, not just bad outputs.**
      Three defects this month share one shape — an input that quietly stopped
      describing reality while staying inside its plausible range:
      the layer-2 forecast reading midnight instead of now (`q_solar_w` = 0.0
      for weeks), the dew-point reference running on 2 of 6 rooms, and the
      energy shadow's `ua_sa` disagreeing with the identified value by 16 %.
      None of them looked broken. Each needed a *count* or a *provenance* to be
      visible: `energy/solar_rooms`, `system_dew_point_pairs`,
      `energy/outdoor_source`. Publish the provenance of every input that feeds
      a safety limit or a control target, and make the count the thing that is
      watched.

- **ONE coupled Kalman filter over the whole house — owner's design
      direction, 2026-08-10, to revisit properly.** Recorded verbatim because
      it contradicts a rule the code currently follows:

      > "a large Kalman filter with all the state variables for all rooms,
      > modeling all transmissions between inside and outside, as well as
      > between the rooms. I have the sensor for Natalie there, could mount it
      > if that is what it takes."

      **What it contradicts.** DESIGN.md 7.1 specifies the opposite —
      "decoupled, not monolithic… one Kalman filter per room… **No giant
      coupled EKF** — decoupled filters are debuggable, individually
      validatable, and failure-isolated. Couplings (VL temp, flows) enter as
      **measured inputs, not shared states**."

      **Why the owner's version has a real argument.** That last clause is the
      weak point. Inter-room coupling in this house is not a small correction:
      measured 2026-08-09 the rooms spanned 21.4-26.0 degC, a 4.6 K spread, and
      Wohnzimmer/Arbeitszimmer are joined by an open Luftraum that is the whole
      reason the coil room stratifies. Treating a neighbour's temperature as a
      *measured input* is exact only where that neighbour is actually measured;
      for an unsensored room it is an estimate being fed into another filter as
      if it were data, which is the coupling smuggled back in without its
      covariance. A joint filter carries the cross-covariance honestly.
      It also makes `UA_nb` identifiable at all: with per-room filters, heat
      arriving through a party wall is indistinguishable from a wrong `UA_ao`.

      **The decoupled argument is not thereby refuted** — a monolithic filter
      IS harder to validate, and 7.1's innovation-whiteness gate is much
      weaker when one bad room can bias twenty states. That gate is the thing
      to design for, not to discard. Note also that 7.1 is an axiom of the
      same kind as the layer-1/layer-2 split: asserted in the initial commit,
      never traced to a measurement or an incident. Do not treat either side
      as settled doctrine.

      **What it needs, in dependency order:**
      1. **Mount the Natalie sensor** — the owner has it in hand. That takes
         air measurements to 7 of 7 rooms, and DESIGN.md 6.1.1 is explicit
         that "with per-room air sensors the 3-state form is identifiable.
         Without them it is not." This is the cheap unblocking step and it is
         worth doing regardless of which filter architecture wins.
      2. **Shared wall area per room PAIR** for the `UA_nb` terms — the
         existing item (b) above. Note its warning: the automated extraction
         FAILED (105.6 m of face pairs against ~42 m implied by room
         perimeters, because it pairs door leaves and dimension ticks). Do it
         by hand off the plan.
      3. **Decide the observability budget before writing code.** 6 slab rooms
         x 3 states + 1 coil room x 2 = 20 states plus disturbances, against 7
         air measurements and 10 intermittent circuit returns. A coupled filter
         does not create information; it only stops wasting it. Rooms that stay
         unidentifiable should collapse to fewer states rather than run three
         off one measurement.
      4. **Keep it in layer 2.** Whatever the filter shape, the control path
         must not depend on it - `slab_estimate_c` stays algebraic in layer 1
         and the filter's output arrives as parameters, the same contract the
         per-room solar term now uses (D-034).

- **`valve_*_actual` is named as if it were valve feedback. It is not.**
      Owner, 2026-08-10: *"Where do SOLL vs IST for the valves come from? We
      have no feedback on them."* Correct, and the naming is why the question
      had to be asked.
      `IOState.valves_readback_pct` is the coupler's **analog output register
      read back over Modbus** — the 0-10 V leaving the node. The Möhlenhoff
      Alpha 5 are thermal actuators with no position sensor of any kind, so
      valve position is not merely unmeasured but unmeasurable (D-023:
      commanded 100 -> 0 -> 100 -> 0 in 27 s, position untrackable).
      The comparison is still worth having — `backends/base.py` says exactly
      what for: it detects the **coupler watchdog forcing its safe state**, a
      failed write, or a second master on the bus. All three are real and none
      is about the actuator.
      **Evidence it is not mechanical**, measured 2026-08-10: 8 of 10 circuits
      matched exactly and the two that differed by 1 % were both commanded to
      10 %. Actuator lag would show worst on the *largest* steps; hk07 went to
      100 % and matched exactly. It is rounding in the percent/raw conversion.
      Rename `_actual` to something like `_output_readback` so the entity
      cannot be read as a position. Renaming touches dashboards, InfluxDB
      history and anything already graphing it, so follow the impact-analysis
      workflow rather than doing it casually. Until then the Kreise view of
      `heatctl-detail` carries the explanation on the card.
      **The only observable of whether a valve actually opened is the
      circuit's return temperature** (D-009), which is why that column now sits
      beside the register in the same table.
      **Follow-up, same day: the readback VALUE is near-worthless; the derived
      MISMATCH is the part worth keeping — and only the worthless half is
      instrumented.** `valve_*_actual` has ten discovered HA entities and
      InfluxDB history; `valve_mismatch` is published to MQTT with no HA
      discovery at all, so it is no entity, has no history and appears on no
      dashboard. Publish the exception, not the value: add discovery for a
      single mismatch count/flag, and consider dropping the ten per-circuit
      readback entities. The ten graphs have already been removed from
      `heatctl-detail`; the register stays as one column in the table.

## Nine-day review, 2026-08-10 → 2026-08-19

Taken from InfluxDB (the App's own log keeps 100 lines, see below). Local
times; Influx is UTC.

### The manifold has been clean since the incident — the finding that matters

`heatctl_supply_total` (the PT1000 the safety code and the capacity loop both
read) against `cooling_supply_limit - 1.0` (i.e. the bare dew point), counted
only while the compressor ran:

| day | run min | below limit | **below dew point** | worst |
|---|---|---|---|---|
| 08-09 | 600 | 245 | 0 | — |
| 08-10 | 640 | 235 | **5** | **3.08 K** |
| 08-11 … 08-18 | 65–330 | 5–150 | **0** | — |

Five minutes on 08-10, 3.08 K under, and nothing since. That is the visible
condensation, and the dew-reference fix that morning closed it.

**Do not read the "below limit" column as a breach.** `target_margin_c` is 0,
so the capacity loop deliberately regulates *at* the limit; sitting a little
under it for a third of the runtime is what a zero-margin proportional loop
does, and the limit already carries `dew_point_margin_c: 1.0`.

**Correction worth keeping.** Running the same query against
`heatctl_leaving_water` instead says 10–90 min/day below dew point, up to
1.87 K. That series is the *heat pump's own* register at 0.5 K resolution,
upstream of the manifold; it dips on every restart while the water that
reaches the slab does not. Two supply sensors, two different answers, and only
one of them condenses anything. I reported the alarming number first and had
to withdraw it.

### Er03 has not recurred

Three `er03_water_flow` faults, all on 2026-08-10 between 10:20 and 10:34
local, each ~4.5 min and self-clearing. None in the nine days since. That
window is the valve trip firing, which is what D-035 removed.

### 22 compressor cycles in five hours, on the unit's own antifreeze protection

Night of 08-11/12, 02:12–07:15 local: `primary_antifreeze` (`0x800C` bit 5)
raised and cleared 22 times, on a ~19 min period. One cycle, raw:

```
01:50:08  heatctl writes P04 = 15   (RESUME)
01:50:19  compressor 14 Hz -> 50 Hz within 60 s
01:51:44  leaving water 17.5 -> 15.5 in three minutes
01:57:45  unit modulates down to 30 Hz on its own
01:58:41  heatctl writes P04 = 30   (STOP), frequency 0 the same second
01:58:47  primary_antifreeze ON
02:03:51  primary_antifreeze OFF
02:08:38  heatctl writes P04 = 15   (RESUME) — and round again
02:09:51  cooling coil 10.5 -> 1.0 degC in 45 s
```

Two things this says.

**The coil reaches 1–3 °C on every start.** The unit ramps to 50 Hz in a
minute regardless of load; at night the floor cannot absorb that, so the
evaporating pressure collapses and its antifreeze protection sees it. Note
`Er 23 Leaving Water Over-cold Protection in Cooling Mode` (`0x800A` bit 5) did
*not* trip — this is the coil, not the water.

**STOP/RESUME is a bang-bang actuator and we are using it as the fine one.**
`min_off_s` is 600 s and the resume hysteresis is `target_margin_c +
deadband_c`, so the shortest achievable cycle is roughly what we saw. Against a
load below the compressor's minimum modulation there is no duty it can hold —
it can only cycle. With the valve backstop gone (D-035) this loop is the *only*
condensation actuator, so its coarseness is now load-bearing.

The exit is not a faster loop. `setpoint.py:_clamp` already argues, in the
comment block D-030 left behind, that **the setpoint is the only real control
over what reaches the slab** — and it currently commands P04 = 15 while the
limit is 16.3, i.e. we ask for water colder than the condensation limit and
then interrupt the machine to stop it arriving. Raising P04 to at or just above
the limit would let the unit's own thermostat modulate instead of being yanked
off, at the cost of the capacity the low setpoint was buying. **Not changed:
this is a design question, and the plant is not currently condensing.**

`primary_antifreeze` is also, note, the only entry in `FAULT_BITS` with no `Er`
code — the manual lists it under "Fault flags 6" but it reads as a protection
state. heatctl surfaces it as `binary_sensor.heatctl_heat_pump_fault`, so the
plant looked faulted 22 times for doing its job. Worth deciding whether the two
antifreeze bits belong in a separate `protections` series.

### Smaller things found while looking

- **`0x00F4 silent_max_fan_cooling` reads raw 65512** (= −24 signed) against a
  declared 0..1000, warned on every start. Either the map is wrong or the
  register holds junk; it is the fan cap the silent-mode work depends on (see
  `_trim_capacity`'s `silent_ok` check), so it is worth resolving.
- **The App log is useless for review.** `ha addons logs` returns 100 lines and
  the once-per-minute `flow floor: valves raised to 55% mean (still, since N s)`
  line consumes all of them — nine days of history had to come from InfluxDB. A
  "still" line that repeats unchanged every 60 s should log on the edge and
  then at a decreasing rate, like the setpoint-saturation alarm already does.
- **Untidy shutdown.** Stopping the container produces a stack of
  `RuntimeError: Event loop is closed` tracebacks from `main.py:439`
  (`plane_task.cancel()` after the loop is gone) and two more from
  `mqtt_plane.py:204`. Cosmetic — the failsafe path is unaffected — but it
  makes a real crash on shutdown indistinguishable from a clean stop.
- **Dew-point pair count ranged 4–6** over the ten days (mean 5.5), so the
  reference does still narrow occasionally. Not the 2-of-6 of the incident.
- **Two P04 writes in 600 ms at startup** (`None -> 30`, then `25 -> 30`).
  Both are flash cycles for one decision (D-013).

## Cooling-path audit against D-039, 2026-08-19

Prompted by having twice in one day proposed mechanisms that traded the
condensation constraint for comfort without noticing. Checking every place the
trade could be made.

**Clean:**

- `capacity.py` STOP/RESUME. Resumes only at `target_margin_c + deadband_c`
  above the limit (0.25 K), stops on any breach, and since D-038 the stop is
  reachable without a usable frequency ceiling.
- The setpoint floor. Uncapped since D-039; it may now ask for a setpoint the
  unit will not start at, which is the point.
- `_trim_capacity`'s no-dew-point refusal, and its fallback stop when
  `capacity.enabled` is false. Both run above the optimisation gate.
- Distribution and the valves. They cannot make water colder, so they cannot
  breach the constraint — which is the whole of D-035.

**One finding.**

## PFC200 750-8212 — survey and migration strategy, 2026-08-19

The unit that arrived 2026-07-31 is online at `192.168.178.62` with Docker and
a Mosquitto on a 119 GB SD card. Device facts: `docs/PFC200.md`; access and
credentials: `docs/PFC200.local.md` (git-excluded).

### The gating question is answered, and the answer is "not cleanly"

The 2026-07-31 entry made everything conditional on whether the PFC200's Modbus
server offers an equivalent output-zeroing watchdog. It does offer a watchdog,
configurable without CODESYS via `/etc/config-tools/modbus_config`, with a
timeout and an **options mask**. But the only one on offer is called
**`alternative`**, and D-004 chose *Standard* on the 750-352 precisely to avoid
Alternative's behaviour: Standard evaluates the coding mask, so `0x8020`
(FC6+FC16) makes a satisfied watchdog mean *outputs are being driven*, which is
why heatctl needs no heartbeat — its per-cycle valve write **is** the heartbeat.

Whether the `options` mask restores Standard semantics is **unknown**. It is a
hypothesis about a name. Until it is bench-tested, assume the worst case: a
heatctl that reads fine and fails to write keeps the watchdog fed while the
outputs go stale, and the outermost safety net is gone.

Two further facts change the shape of the work:

- **Nothing listens on 502 today.** The Modbus server lives in the PLC runtime
  and no runtime is selected. `/home/codesys/` exists but is inert.
- **There is no Python on the device.** heatctl runs containerised here or not
  at all, which puts dockerd and an SD card in the critical path.

### Proposed order, and the argument for it

**Do not swap the coupler first.** That is the intuitive order and it is the
wrong one. Swapping first replaces a *proven* failsafe (verified on hardware
2026-07-26, and it did its job during the 2026-07-31 outage and the 2026-08-08
switch incident) with an unverified one, while gaining nothing yet — the
control would still run on the HA host, still across the network. All the risk,
none of the benefit.

Sequence by reversibility instead.

**Phase A — DONE 2026-08-19.** Broker, no plant risk. The broker cannot
carry heatctl as configured: `homeassistant` is read-only and `shelly` is
confined to `sensors/shellies/#`, so nothing can publish `heatctl/#` and HA
cannot send `heatctl/set/#`. Needs a `heatctl` account with write on its own
tree, HA write-limited to `set/`, `persistence true` so retained state survives
a container restart, 9001 closed or configured, and the CA key moved off the
broker.

**Phase B — DONE 2026-08-20.** heatctl on the PFC200, 750-352 kept.
Tripped Er03 on the cutover by leaving the plant unmanaged ~90 s; the
procedure that prevents it is in `docs/PFC200.md` and enforced by
`deploy-heatctl.sh`. Status table in that file.
 Container on the
PFC, `io.backend: modbus_direct` still pointing at `192.168.178.52:502`,
control plane on the PFC's own broker. **No plant downtime and rollback in
seconds** — stop the container, start the HA add-on. What it buys is
knowledge: whether one ARMv7 core runs the 1 s loop with margin, whether
Docker-on-SD is acceptable, whether the broker holds. All of that is learned
while the proven coupler watchdog still guards the outputs.

> **Single-writer rule.** The HA add-on must be *stopped*, not merely idle. Two
> heatctl instances writing the same valves is the failure this project has
> already had once with HA automations on register 0.

**Phase C — NEXT, and it gates D.** Bench the watchdog. On the bench, no
plant involvement. Select a runtime so 502 listens. Then the only question that
matters: **does a read-only Modbus client keep `alternative-watchdog` fed?**
Connect, poll inputs, never write, and see whether the outputs zero. If they do
not, the watchdog is the wrong kind and heatctl needs an explicit heartbeat
write — a code change, not a config one, and one that weakens D-004's guarantee
because a heartbeat can succeed while the real valve write fails. Also settle
the process image layout (`base_register: 12` is hardcoded and this is the
third time the map has moved) and the 5 V internal bus budget, with WAGO's
configurator rather than by eye.

**Phase D — blocked on C.** Swap the coupler. Only if C clears. Same backplane, modules carry
over, IP to the coupler's address, re-verify every register against known live
sensor values, re-arm the watchdog and **re-run the deliberate trip test** from
2026-07-26. After this heatctl talks to `127.0.0.1:502` and the control↔I/O
link stops crossing the network at all — the 2026-08-08 lesson, banked.

**Phase E — later: a native KBUS backend.** `/dev/kbus0` and the WAGO DAL
libraries are on the device, so a third `IOBackend` beside `modbus_direct` and
`mqtt_io` can drive the process image with no Modbus, no runtime and no
CODESYS. No SDK headers are present, so this needs WAGO's SDK or a documented
ABI. It is the better destination, not the first step.

### Timing

Phase D is the only one that costs plant availability, and it wants a **mild
shoulder day** — neither a heatwave nor a cold snap. Roughly now to October.
The 2026-07-31 entry picked its window on forecast and then let it slip; the
same reasoning applies, so pick a day with low load in both directions and do
not let it drift into a hot spell.

Phases A and B are season-independent. B is worth doing soon precisely because
it is reversible: the sooner heatctl has run a few weeks on this hardware, the
less the coupler swap is carrying.

### Shellys direct to this broker — independent, but not free

One is already there: `shellyhtg3-9070695AA90C`, topic base
`sensors/shellies/wohnzimmer`. Two measured problems before more rooms move off
the HA bridge (details in `docs/PFC200.md`):

- The device **deep-sleeps on a 600 s cycle** despite being mains powered.
- **Only `online` is retained**, not the readings — so a subscriber that
  connects mid-sleep has no temperature until the next wake, and heatctl would
  fall back to house-average control silently.

The HA-bridged rooms paper over exactly this with a `/2` heartbeat automation.
Removing HA from the path removes that helper too, which is the honest cost.
Also: the payload is JSON (`{"tC":23.7}`), and `room_temp_topic` currently
expects a bare float for the rtl_433 room — so a JSON-extracting topic form is
needed regardless.

## Resilience: depend on as little as possible, duplicate what remains

Owner, 2026-08-19, setting the design goal for the PFC200 era. Recorded here
because it is the frame the migration decisions get judged against, not a work
item on its own — the individual pieces below are.

The principle has two halves and they pull in opposite directions, which is
why it is worth stating: **remove dependencies where you can, and where you
cannot, have two of them.** A single dependency that cannot be removed is
where redundancy is worth its cost.

### Redundant paths from the sensors to the controller

- **The PFC200 has two Ethernet ports and supports spanning tree.** Connect
  them to two network segments, each carrying WLAN access points whose
  coverage overlaps, and a room sensor has two radio-and-wire paths to the
  controller. STP handles the loop this deliberately creates — which is worth
  noting against 2026-08-08, when an *accidental* loop on a dumb switch took
  out the coupler and the heat-pump gateway together for half an hour. The
  same topology that failed by accident works when it is managed.
- Today the control↔I/O path and the heat-pump path share one segment and one
  unmanaged switch. That is the single point of failure the 08-08 entry
  identified and nothing has changed it yet.

### Redundant radio for the 433 MHz sensors

- **Decouple rtl_433 from Home Assistant** and let it publish to the broker
  directly. Today the outdoor temperature and Arbeitszimmer reach heatctl only
  if the HA host is up, for no reason other than where the decoder happens to
  run.
- **Several rtl-sdr frontends**, on the redundant segments above, so a dead
  dongle or a bad antenna position costs nothing. Duplicate decodes of the
  same transmission are a deduplication problem, which is a much better
  problem than a missing one.

### Redundancy for the outdoor temperature specifically

`UA_ao * (T_set - AT)` makes this the largest single term in the slab target,
so it earns more than one source. In descending order of trust:

1. Our own WH65B/WH24 at id 210 — **one physical station**, reported by
   rtl_433 under two model names, so it is one source and not two.

   Proved on the rain gauge, at the owner's prompting, because agreeing
   temperatures prove nothing (any two thermometers in one garden agree). A
   *cumulative* counter is the discriminating measurement, and the two totals
   look nothing alike: WH65B 2857.25, WH24 3374.7. They are the same count at
   two bucket scalings — 0.254 mm (0.01 in) and 0.3 mm:

       2857.25 / 0.254 = 11249.0 tips
       3374.7  / 0.300 = 11249.0 tips        ratio 1.181101 vs 1.181102

   Identical to six decimal places. One rain gauge, two unit conventions. The
   UV field differs for the same reason (2.0 vs 1.0), and the 32 s gap in
   `utc` is the two decoders matching different packets from the same station.

   **Do not count this pair as redundancy.** It is one sensor counted twice,
   which is worse than one sensor, because it looks like two.

   - **Which bucket scaling is right is unknown.** One of the two rain
         figures is wrong by 18 %. Nothing uses rain today, so this is filed
         rather than fixed - but if rain ever feeds anything, settle it against
         the station's actual model before trusting either number.
2. **A neighbour's WH24**, per the owner. **Not confirmed from this side:** the
   only Fineoffset ids visible in HA are 210 (ours) and 245 (Arbeitszimmer),
   and the rtl_433 add-on's retained log window shows no second id. Since 210
   is our own station decoded twice, a genuine second source must carry a
   different id — identify it before counting on it, and give it a name in
   `config.yaml` so nobody later mistakes it for ours.
3. **The heat pump's own ambient register.** Crude — mounted on the unit, so
   it reads high from compressor exhaust and evening sun, measured 1.8–2.1 K
   over through the afternoon with a 45.6 °C excursion on 2026-08-04. Good
   enough for a rough heat-demand estimate and nothing finer. Already wired as
   the fallback; the value of writing it down here is that it is the *third*
   line, not the second.

**Decided 2026-08-19: the WH65B does not move to the PFC broker.** It stays on
the HA-side rtl_433 path for now, precisely as this contingency. So the bridge
keeps a permanent inbound leg rather than a transitional one.

## Retained sensor data and staleness detection — they are one question

Owner, 2026-08-19: *"could we just configure that? But if so, how would we
detect stale data?"* The second half is why the first half is not free.

heatctl times staleness from **arrival** (`room_temp_ts[room] =
time.monotonic()`, checked against `room_temp_max_age_s`). A retained message
is delivered on subscribe with no indication of when it was produced, so a
three-hour-old reading arrives looking zero seconds old. Retain therefore
*defeats* the only staleness mechanism heatctl has. That is not an argument
against retain — it is an argument that retain needs a second signal beside it.

There are three, and they compose differently depending on one decision.

### ~~The decision everything hangs on: does the Shelly keep sleeping?~~ — SETTLED 2026-08-20, and not the way I hoped

**Sleep cannot be disabled, and the reason is physical.** Owner: an always-on
CPU self-heats and distorts the temperature measurement. So this is not a
firmware limitation to be argued with — the device is only accurate *because*
the CPU is off between samples. "Just keep it awake" is permanently closed, and
anyone who proposes it later should be pointed here.

That kills the branch this section was built around. What I wrote — *"stopping
the deep sleep is not a nicety, it is what makes retain safe"* — was the right
analysis of the wrong option. `online` is false roughly 357 seconds in every
360 by design, so it can never gate freshness. It survives only as a **wake
event marker**: `online` going true says fresh data arrives in the next second
or two.

The payload-timestamp route below is closed too, independently: the clock is
unset immediately after wake (`"unixtime":null`), which is exactly the window a
first-message-after-reconnect would depend on.

### What that leaves

**Room temperature is an inherently sampled signal, ~6 min between samples**,
and no protocol work changes that. Observed connects were exactly 360 s apart
though the device reports `wakeup_period: 600` — resolve which governs before
sizing anything, because everything below is sized against it.

  - **Size `room_temp_max_age_s` against the wake period.** It is 900 s,
        chosen for sensors reporting every minute. Against a 360 s wake that
        tolerates one miss; against 600 s, barely any. With seven sleeping
        rooms the chance that *some* room is stale stops being negligible, and
        the failure is silent — the room drops to house-average control with
        nothing said.
  - **Publish per-room sample age**, so a room going quiet is visible
        rather than inferred. Absence must be published, not implied.
  - **A normaliser on the PFC** is the option I would pursue: subscribe
        `sensors/shellies/+/status/#`, republish to a heatctl-native topic
        **retained**, with an **MQTT 5 message-expiry** of ~3 wake periods so
        mosquitto itself drops the value when it goes stale. That fixes retain,
        staleness and the JSON-vs-bare-float difference in one place, using a
        clock we control instead of the sensor's — and needs no heatctl change
        at all. Cost: a new moving part in the sensor path, which cuts against
        "depend on as little as possible", mitigated only by it sharing a box
        and therefore a failure domain with heatctl.

**Consequences elsewhere, so they are not rediscovered:**

- **Every restart is blind for up to a wake period, per room**, because
  readings are not retained. That also blocks D-044's start-up one-shot, which
  needs a complete room set — and on the PFC that is every deploy.
- **The dew point inherits all of it** (D-045). Humidity comes from the same
  sleeping devices, so the local computation is sampled too and may have zero
  contributing rooms after a restart. Keep HA's helper as the `max()` partner
  considerably longer than planned: its state machine holds last-known values,
  so it degrades differently rather than identically.
- **It sharpens the redundancy argument.** A sleeping device that wakes to find
  no access point loses the whole cycle. Overlapping AP coverage turns a
  six-minute hole into a non-event, which matters more here than for a
  mains-powered always-connected sensor.
- **Mounting matters.** The measurement is valid because the CPU is off; do not
  place these where air exchange is poor or near a heat source.

### ~~Second mechanism: the payload already carries a timestamp~~ — CLOSED 2026-08-20

**The clock is unset right after wake.** Measured on the wire: `"time":null,
"unixtime":null, "last_sync_ts":null` in the first `sys` status of a wake
cycle. So the timestamp is missing in precisely the window a sleeping device's
first message occupies, which is every message that matters. The reasoning
below stands as the general argument for measurement time over arrival time —
it is why the normaliser stamps on the broker instead — but this device cannot
supply it.

`sensors/shellies/<room>/status/temperature:0` is `{"id":0,"tC":23.7}` — no
time. But `sensors/shellies/<room>/events/rpc` carries
`NotifyStatus`/`NotifyFullStatus` with `params.ts` (unix seconds). Subscribing
there instead gives **measurement time rather than arrival time**, which works
for retained messages and for sleeping devices alike.

Costs, all real:

- heatctl uses `time.monotonic()` for staleness and the payload is wall clock.
  Mixing the two needs care, not a cast.
- It introduces a **clock dependency** on both ends. A device that lost NTP can
  report 1970 (looks infinitely stale — safe) or a future time (looks
  infinitely fresh — **unsafe**).
- So it needs a sanity bound, and the bound must fail toward *stale*: reject
  timestamps in the future or implausibly old, and treat a rejected timestamp
  as no reading at all. D-003's "fail open on lost knowledge", applied to the
  room path.

### ~~Third: heatctl should treat `online false` as no reading~~ — INVERTED 2026-08-20

Written for a device that stays connected, where `online false` means the
device is gone. On a sleeping device it is the **normal** state — false roughly
357 s in every 360 — so this rule would discard every reading heatctl has.
Exactly backwards, and worth leaving visible: it is the shape of mistake this
whole section now exists to prevent.

What survives is the inverse. `online` going **true** is a wake event, i.e. a
reliable "fresh data in the next second or two", which is a useful thing to log
and to measure the real wake period with. It is not a freshness gate.

The general point underneath was right and is unaffected: a room with a dead
sensor should not keep its last value for the full `room_temp_max_age_s`. It
just needs a signal that means what `online` was assumed to mean.

### Recommendation, revised 2026-08-20 — BUILT the same day, see D-047

Both cheap answers were gone — the device cannot stay awake (physics) and
cannot timestamp its own wake message (unset clock) — so the normaliser was
built instead. `normaliser/main.py`, its own container on the PFC, live since
2026-08-20 with Wohnzimmer as the pilot.

1. ~~Resolve the wake period first~~ — **360 s**, measured, not reported. The
   first two intervals it published were 360 and 358, against the
   `wakeup_period: 600` the device claims. Anything sized against 600 was
   sized against the wrong number.
2. ~~Size `room_temp_max_age_s` against that~~ — 900 s **kept, now on
   evidence** rather than inheritance: at a 360 s cadence it tolerates exactly
   one missed wake (720 s) and not two (1080 s). `ttl_s` in the normaliser is
   held equal to it, and a test asserts the two do not drift apart.
3. ~~Build the normaliser~~ — done. Retained, MQTT 5 message-expiry, bare
   floats. heatctl needed no change: mosquitto delivers an expiring retained
   message to a v3.1.1 subscriber perfectly well, verified on 2.1.2.
4. **Publish per-room sample age** — half done. `sensors/room/<room>/sample_ts`
   exists for rooms on the normaliser, which is one room. The other six arrive
   over the HA bridge and rtl_433 and have no age published anywhere. Still
   open, and the general answer is heatctl publishing its own view of arrival
   age for every room, since only heatctl knows what it actually believes.

### ~~Elternschlafzimmer has lost its return temperature~~ — WRONG, 2026-08-20

**There was no sensor fault.** `rl_hk07` reads fine and always did. Two bugs
made it look like one: the caller collapsed "no reading" and "not trusted", so
a sensor the rl_gate was withholding reported as `no return temp`; and the
gate was withholding it because the valve had moved and `settle_s` had not
elapsed. Owner spotted the implausibility immediately — *"rl_hk07 being absent
is weird, it's one of the sensors on the 750 Modbus."* Both fixed; the reason
string now says `rl not valid`, which is the truth.

Kept rather than deleted because the *reasoning* is the lesson: a diagnosis
that sends you to the hardware should be doubted when the hardware is the
part least likely to be wrong.

### Per-room energy topics went stale instead of going unknown — fixed

The publisher skipped a topic when its value was `None`, which leaves the last
value standing. So Elternschlafzimmer displayed a confident `excess_wh 8996`
next to `valid 0`, computed against a target that had since moved, while the
house total had already dropped the room. Now publishes `unknown`.

Same family as the retained rtl_433 fossils found the same evening, and worth
naming as a pattern: **absence must be published, not implied.** A value that
is merely not refreshed is indistinguishable from a current one.

## Where we are, 2026-08-20 morning — handover

Supersedes the ~01:00 handover, which the morning invalidated.

### Plant state

**Running on the PFC200 since 2026-08-20 09:38.** The HA App is stopped, not
removed — it is the rollback. Control plane is on the on-box broker; Modbus
still crosses the network to the coupler until Phase D.

**Heating, quiescent, deliberately.** Owner's call from looking outside rather
than at the forecast: overcast, solar about zero, top around 24 °C, so nothing
needs moving. Water setpoint (P05) set to 24, roughly where the slab sits, so
the unit tops it up if it drifts and otherwise does nothing. The trim is left
enabled and will walk 24 down toward `heating_min_c` 20 over a couple of
hours — that walk *is* the plant concluding it has nothing to do, not
something to override.

**`auto_mode` is OFF** and mode is set by hand. See the oscillation below.
Reading the logs: automatic changeover logs as `heatctl.demand mode -> …`, a
manual command as plain `heatctl mode -> …`.

No faults or protections. No condensation exposure in heating.

### The oscillation, and why auto_mode is off

The plant self-excited overnight — four mode flips on a ~78 min period,
amplitude reaching +4.13 K of slab, each flip inverting the valve allocation
for the 10–15 min the water took to change over, and swinging supply
16 ⇄ 26 °C through an 8691 Wh/K slab for no benefit.

**Cause:** `slab_estimate_c` falls back to the raw return temperature wherever
`ntu` is unmeasured, which is everywhere — verified live, slab 22.90 against
rl 22.9 on every room. So the "stored energy" D-046 picks the mode from is
return-water temperature, which follows *supply* within minutes. Heat → return
rises → "cool"; cool → return falls → "heat". The dwell does not damp it, it
sets the period.

This is the circularity D-030 was withdrawn for, rebuilt in the mode selector.
Widening the deadband does not help: the amplitude scales with the supply
excursion the flip itself causes.

**The clamp half of D-046 is untouched and still correct** — it fixes the
target side, and Schlafzimmer's unclamped 7.59 °C target made this worse.

### Next, in the order I would take them

1. **The coupled Kalman filter.** This is now the blocking item, not an
   aspiration: we have no slab temperature, only return water, and return
   water is a function of the last control action. Every energy-based decision
   inherits that. Owner: *"sounds like we need that big Kalman filter for
   proper energy estimation."* Re-enable `auto_mode` when a slab estimate
   exists that the actuator does not move.
2. **The outdoor station's 10.5 h silence** (2026-08-19 19:34 → 06:02 UTC).
   Recovered by itself; battery check. A retained 2022 fossil was masking it
   until the fossils were cleared.
3. **D-044's start-up one-shot can fire before the energy model answers**,
   spending itself on the fallback statistic. Dormant while `auto_mode` is
   off, so no urgency. Needs a *bounded* grace, not an unbounded wait.
4. **Elternschlafzimmer's 19.0 is unreachable in summer.** The clamp stops it
   corrupting totals; it does not make the room reachable. Envelope problem —
   4.9 kWh/day of solar into a slab that sheds ~253 W. D-006's cost, twice
   over.
5. **What the plant should do overnight in shoulder season.** There may be a
   missing state between "cool" and "off": circulate, do not run the source.
   `off` is not it — D-044 made it sticky against auto_mode.
6. **Remaining rooms onto Shellys**, one at a time, Wohnzimmer having proved
   the path. Blocked on the deep-sleep question: mains powered yet sleeping
   600 s, only `online` retained, clock unset right after wake — so neither
   retained readings nor payload timestamps are available for staleness.
7. ~~**heatctl onto the PFC200** (Phase B).~~ **Done 2026-08-20.** Next in that
   thread is **Phase C, the watchdog bench test**, which gates the coupler
   swap — and the swap is what finally takes the control↔I/O link off the
   network. Watch first: whether one ARMv7 core holds the 1 s loop under load,
   and how Docker-on-SD wears.
8. **The load forecast's stale 24 °C house target.** It predates per-room
   setpoints and sits ~2 K above where the rooms actually are, so today's
   41 kWh understates by ~12 kWh. Parked by the owner until it feeds a
   prediction filter — nothing acts on it today.

### Traps worth not relearning

- **`mosquitto_pub` exits 0 on ACL denial.** Four false successes in one day.
  Verify by reading back what landed, never by exit status.
- **Absence must be published, not implied.** Three instances in one day —
  retained rtl_433 fossils, per-room energy topics, house energy topics. A
  value that is merely not refreshed is indistinguishable from a current one.
- **A green test proves nothing until its mutation is red.** Four tests in one
  day passed against the very bugs they were written for, usually by asserting
  on a path that never ran — a fixture missing `enabled`, or `floor_area_m2`.
- **A deploy ships code, not config — and the mirror image is real.** Shipping
  config without code left the old `float(payload)` running against JSON.
- **Anything a controller moves cannot measure that controller.** Spread
  (D-030) and now the slab estimate. Ask what the actuator touches before
  building a decision on a signal.

## 2026-08-24 — the KBUS route opens up, and two of my conclusions were wrong

A day of investigation prompted by owner deciding to go for the swap and
wanting the bench work prepared. No spare terminals, so the question was how
much of Phase E is provable with an empty rail. Answer: almost all of it.

### Phase C1, and the conclusion I got wrong twice in one morning

`modbus_config get tcp enabled` returns **true** on port **502**, and nothing
has ever listened there. Starting CODESYS3 (`config_runtime -w
runtime-version=1`) brought up port **11740** — its gateway — but not 502, with
`get_codesys_application_info -j` returning `{}`. No `modbus` daemon, no init
script, no binary. What exists is `/usr/lib/dal/libmbs.so`.

So the Modbus server is an **ADI device an application instantiates**, and
`modbus_config` configures something that does not exist until one does. From
that I concluded Phase D needs a CODESYS program — a second toolchain in the
plant's I/O path, for thirty years.

**Wrong within the hour.** WAGO publish `github.com/WAGO/pfc-modbus-server`: a
Docker image wrapping a `kbusmodbusslave` daemon that serves Modbus TCP
straight off the KBUS, and whose own `setup_environment.sh` sets
`runtime-version=0`. It runs with CODESYS **off**. The evidence I had was
sound; the inference from "no listener without CODESYS" to "therefore requires
CODESYS" was not — I had ruled out a daemon on this box without asking whether
the vendor shipped one elsewhere.

Its costs are real and recorded in `docs/PFC200.md`: `--privileged`, the D-Bus
socket, a closed 24 KB vendor binary last pushed 2022, a **750-362** register
map against our 352, a "toggle the runtime if the KBUS will not init"
bootstrap, and dependence on the physical RUN/STOP switch.

### The runtime getter lies, which explains a four-day-old contradiction

The 2026-08-19 survey recorded `get_runtime_config` empty and concluded no
runtime was running. On 2026-08-21 `codesys3` was running and holding
`/dev/kbus0`. Both were accurate: **the getter returns empty even while
codesys3 runs** — watched directly today, with 11740 open and the getter still
silent. It reports a configured selection, not what is live. Check the process
table.

### `runtime-version=0` frees the bus, verified

`fuser /dev/kbus0` → FREE, `codesys3` gone, **~18 % of the single core back**,
and the WBM still answers on 443 — nothing that matters depended on it. Left
off, since that is what Phase E wants anyway. Note this box offers only `0 1`
(None / CODESYS3); the `pfc-kbus-api` script's `runtime-version=3` is
e!Runtime and would have failed here.

### Is `/dev/kbus0` proprietary? (owner asked)

Split answer. The **driver** is char major 246, **built into a GPL kernel**
(6.6.94-rt56-w05.08.02), so its source is obtainable — the device interface is
knowable rather than reverse-engineered. The **protocol above it** looks
closed: `libpackbus.so` is 146 KB against `libdal`'s 18 KB and exports
`GetCnfFromRail` and `GFD_GetModuleIdentNumber`, so terminal enumeration and
process-image layout are in userspace, over a driver that is a transport
(`SPI_Open`, `SCPU_gpio_open`, "Failed ioctl to SPI device" — an SPI-attached
Infineon KBUS master). `/dev/ttyKbus` is a red herring: a symlink to
`/dev/ttyO5`, a plain UART.

Mitigating that: WAGO publish `libpackbus`'s **headers** in the G2 SDK
(`libpackbus.tgz` → `usr/include/{libpackbus,rail-info,kbus-tcm,scpu-*}.h`),
and our rail is fixed and already documented in `docs/HARDWARE.md`. The general
enumeration case may simply not be needed.

### The ABI is documented after all

`libdal.so` exports exactly one symbol, `adi_GetApplicationInterface`, and is a
thin loader over `liblibloader`. Everything else is a **vtable**, so `nm` shows
nothing useful — which is why this looked like a blocker. But
`github.com/WAGO/pfc-howtos` carries the ADI-DAL manual as a PDF,
`adi_functions.txt`, and a working `kbusdemo.c`. The sequence is
`Init → ScanDevices → GetDeviceList` (find `DeviceName == "libpackbus"`)
`→ OpenDevice → SetApplicationState(RUNNING)`, then per cycle
`CallDeviceSpecificFunction("libpackbus_Push")` and Read/Write of the process
image. WAGO's demo runs that loop at `SCHED_FIFO` priority 40.

### heatctl's own container can drive it — the result that matters

Nobody had asked whether a Debian container can load PTXdist-built vendor
libraries. It can:

```
preloaded libffi.so.8, libglib-2.0.so.0, liblibloader.so.0
loaded libdal
adi_GetApplicationInterface() -> 0xb6564154
/dev/kbus0 present: True
```

from stock `python:3.12-slim`, with `--device /dev/kbus0`, `/usr/lib` at
`/hostlib` and `/usr/lib/dal` at its own path. No compiler, no SDK on the
device, no new dependency, no base-image change.

**The first attempt failed instructively.** Setting `LD_LIBRARY_PATH=/hostlib`
made the container's own Python bind to the host's glibc:
`/hostlib/libc.so.6: version GLIBC_2.38 not found (required by
libpython3.12.so)`. Host is **2.35**, container **2.41**, and only that
direction works — an old library on a new glibc, never the reverse. So preload
the host's dependencies by absolute path with `RTLD_GLOBAL`, satisfying
`libdal`'s `DT_NEEDED` from inside the namespace, and leave the search path
alone.

### What this leaves

The vtable still has to be transcribed into ctypes from the real header — a
wrong offset is memory corruption behind a function pointer in the I/O path,
not an exception. `ScanDevices` finding `libpackbus` works on an **empty rail**
and can therefore be proven before the swap. Reading and writing process data
needs terminals. And the failsafe — what zeroes the outputs when heatctl
wedges, once the Modbus watchdog is gone — is untouched and remains the only
part of E that is not mechanical.

### Same day, later — testing `pfc-modbus-server`, and a claim of mine that failed

Pulled `wagoautomation/pfc-modbus-server` (55 MB, four years old) and ran it
against the bare PFC, runtime off.

**It starts and listens on 502.** It also cannot initialise an empty rail:
`!!!! KBUS ERROR: 3`, repeating, and it does not hold `/dev/kbus0`. Every
register read — holding, input, process image, `0x1000` — returns Modbus
**exception 6, slave device busy**. Notably *not* exception 2, which would have
told us a register does not exist.

**So the claim I had written hours earlier — that both gating checks are
answerable on an empty rail — is false.** The emulated register map cannot be
probed without terminals. Corrected in `docs/PFC200.md`, and the checks moved
onto swap day, staged: one 750-559 first, verify against it, then the rest.
Four valve channels for the duration, on a plant that is down anyway, and the
352 an arm's length away.

Two things did come out of it without hardware.

**The watchdog exists**, from the binary's own strings: `Watchdog Init`,
`Watchdog start` / `stop` / `trigger`, `ModbusWatchdog Expired Task`, `MODBUS
Watchdog expired`, `Watchdog Timeout: %ums`. That is the premise the whole
D-first plan rests on, so it is a relief to have it on evidence rather than
hope. **What it does on expiry is still unknown** — nothing in the strings
suggests a direction, so that is a bench observation.

**Its failure mode is the right one.** With no KBUS it answers *busy* rather
than hanging or serving stale zeros, so `modbus_direct` would fail its reads
and heatctl would fall into the stale-data failsafe. Same shape as the
intermittent 750-352 faults of 2026-08-22, which heatctl already handles.

Shipped config, worth recording:

```
modbus_port 502    max_tcp_connections 5    operation_mode 0 (async)
modbus_delay_ms 0  kbus_priority 60         kbus_cycle_ms 50
```

**`kbus_cycle_ms 50`** matters beyond this phase: the 100 ms DHW fast loop in
Milestone 2 has to fit inside the I/O cycle, and 50 ms does.

## 2026-08-24 evening — the coupler swap, and a controller that vanished

Owner replaced the 750-352 with the PFC200 in one go rather than staging it.
My staged suggestion — move one 750-559, verify, then the rest — was naive
about the physical reality: the terminals are a bus stack, so pulling one from
position 7–10 means splitting the rail and re-terminating anyway. More
connector handling, not less.

Compressor off first and watched to zero, per the Er03 rule: `compressor_freq
0.0`, `compressor_current 0.0` — not merely commanded off — and `spread -0.1`,
so the loop had settled. Pump left running.

### The controller disappeared, and everything looked fine

After the swap and reboot, `docker ps` showed nothing but the container I had
just created. heatctl, the broker, the normaliser and the journal were gone.

`/media/sdcard/docker-root` was a **244 MB tmpfs**, not the 119 GB card. The
card had mounted at boot (`EXT4-fs (mmcblk0p1): recovery complete`, 16.3 s) and
then vanished from the bus with **no I/O error logged** — the signature of a
clean physical removal rather than a failure. It had been knocked out of its
slot while the unit was handled.

Reseated and rebooted, and it still did not come back — but for a different
reason, which is the one worth remembering:

```
/dev/mmcblk0p1 on /media/bf594745-2a89-4f55-bf1d-0d9c5a571e85 type ext4
```

**WAGO's hotplug automounter claimed it and mounted it by UUID**, not at the
`/etc/fstab` entry for `/media/sdcard`. Docker's `data-root` points at
`/media/sdcard/docker-root`, found the tmpfs fallback there, and started with
an empty root. Nothing errored. `docker ps` was simply empty and the plant had
no controller.

Everything survived — configs, the `*.env` files carrying broker credentials
generated on the device and stored nowhere else, and all four journal files
including a live 253 MB one. Recovery was stop dockerd, unmount the tmpfs,
unmount the UUID path, `mount /media/sdcard`, start dockerd; all four
containers came back on their restart policy.

This is the *"the PFC and its SD card are single points of failure"* backlog
item arriving for real, and it landed on the half I had flagged as
unrecoverable. It is also the worst shape of failure: **healthy-looking, and
the plant simply has no controller.**

### Then the swap turned out to be fine

The 750-362 emulation reproduces the 352's register map exactly. The server
enumerates the rail at start and logs it, so this is read rather than inferred:
four 750-463 at bit offset 192/256/320/384 → **input registers 12–27**, four
750-559 at the same offsets on the output side → **holding 12–27**. Precisely
what `docs/HARDWARE.md` records. heatctl needed nothing but
`HEATCTL_MODBUS_HOST=modbus-server`.

A trap on the way: **`docker restart` does not re-read `--env-file`.** Env is
baked in at `docker run`, so the first attempt cheerfully kept dialling the
dead `192.168.178.52`. Recreating via `run-heatctl.sh` fixed it.

heatctl now reads all twelve circuits and the three manifold ambients,
22.8–23.5 °C, with no Modbus errors.

**The watchdog is live**, which was the entire premise of going D-first:
`coupler watchdog armed: 10.0 s, mask 0x8020`, registers holding 100 and
32800, and 13 629 `Watchdog trigger` lines server-side. It accepts our
Standard-style write-only mask and heatctl's per-cycle valve write feeds it
exactly as on the 352.

Three caveats, all recorded in BACKLOG: `WD_STATUS 0x1006` always reads 0 so
heatctl re-arms every cycle; holding registers **alias to the input image** on
read, which kills `valve_readback`; and the expiry *direction* still cannot be
observed and needs a physical test.

### And production found a bug I shipped two days ago

`override/global` still read `stale_data` after the swap, with no failsafe
since start-up. `run()` calls `_publish_no_overrides()` immediately after
*scheduling* the MQTT connect, so it fires before the plane is connected and
the publish is dropped.

The test passed because it called the method directly against a fake that
always records. It asserted that the method publishes — not that the effect
survives start-up ordering. The lesson is narrower than "test more": a test
that exercises a method in isolation cannot see a defect that lives in *when*
it is called.

Fix recorded: make `override/global` level-triggered like the per-valve topics.
That reverses a choice I made deliberately on churn grounds two days ago, and
the churn argument was wrong — retained state must not depend on a single
publish landing.

## 2026-08-25 / 26 — a cold night the plant sat out, and the mean that let it

**2026-08-25, 07:00.** Outdoor **7.9 degC**, down from 15-17. The house had lost
about 1 K overnight, three of seven rooms were below setpoint, and the energy
model wanted **33.9 kWh**. The compressor had not started once — zero samples
above 0 Hz in the journal for the whole night.

Not a fault. `water_sp/reason: house -0.87 K` — the trim runs on the *mean*
room deviation, and the mean said warm. Elternschlafzimmer, sitting 4.3 K above
a 19.0 setpoint it has never reached, was on its own holding that mean
negative and masking Gästebad, Badezimmer and Kinderzimmer Natalie, all
genuinely under.

Kinderzimmer Natalie had also dropped **2.8 K** against about 1 K everywhere
else, which looked like an open window rather than a control problem.

**2026-08-26, 07:36.** Outdoor back to **15.6**. Every room risen; Natalie
21.3 -> **25.3**, confirming the window. Actionable demand collapsed 33.9 kWh
-> 2.5, and the trim now reports *"water is more aggressive than needed
(already at the limit)"* — it wants to go down and cannot.

So the house rode out the cold night on its own thermal mass and not heating
was, in outcome, correct. Worth recording honestly: the concern I raised on the
25th was real in mechanism and overtaken by weather in practice. The structural
fault — one scalar deciding for seven rooms that disagree in sign — is
unchanged, and it did not bite this time.

Owner changed Elternschlafzimmer 19.0 -> 22.0 the same morning: *"it does not
make sense to hunt an unreachable value."* Measured effect on the mean,
immediately: `-2.43 -> -2.03`, exactly the predicted 3.0 K / 7 rooms. It
removes the worst distortion; it does not remove the averaging.

## 2026-08-26 — trying to identify `ua_sa` from three quiet days, and failing

Owner questioned the eigenvalue provenance; the fast mode inherits `ua_sa`
entirely and `ua_sa` is a guess, so I proposed reading it out of the journal
rather than running an experiment. The compressor had not started in three
days, which looked like a free-decay identification we had got for nothing.

It is not, and the reason is worth recording so nobody repeats the analysis.

**Window:** 2026-08-25 21:00 → 08:00 CEST, owner's choice — no solar, windows
shut, and clear of Natalie's open window (that was the night of the 24th→25th;
she was warm and rising through this one). Compressor confirmed at 0 Hz for all
4167 samples.

**The slab–air gradient does not decay. It sits at about −1 K all night:**

```
room               0.0h   2.2h   4.4h   6.6h   8.8h  11.0h
kind_naomi        -1.10  -1.30  -1.10  -1.00  -0.90  -1.10
arbeitszimmer     -1.40  -1.20  -1.20  -1.10  -1.10  -1.00
kind_natalie      -2.30  -2.20  -2.10  -2.00  -1.80  -1.50   (2 kids)
schlafzimmer      -0.80  -1.30  -1.60  -1.50  -1.40  -1.30   (2 adults)
```

Negative means the slab is COLDER than the room — the slab is a sink, not a
source, which is the summer situation. And the slab itself moved **0.2 K in
eleven hours**: two quantisation steps at the PT1000's 0.1 K resolution.
Outdoor fell only 2.7 K.

**So the limiting factor is not the confounds we were guarding against — it is
that there was no excitation.** "Compressor off for three days" does not mean
free decay; it means the house finished decaying before the window began. A
time constant cannot be fitted to a signal that does not move.

**The data itself is good, and the disturbances the owner named are visible in
it.** Natalie's room carries the largest gradient in the house and Schlafzimmer's
doubles in the first two hours — people going to bed, ~150 W into 11 m².
Wohnzimmer *rose* 0.8 K overnight against falling outdoor, the day's heat still
leaving that large slab. That is a usable internal-gain signal; it is simply
not the parameter we were after.

**Also learned, the hard way:** running the extraction on the PFC drove load
average to 6.4 on a single core carrying a 1 s control loop. `zcat | grep | awk`
over 45 MB of archive is not a thing to do on the plant controller, `nice` or
not. Pull the files and analyse on the workstation — the transfer costs the box
far less than the decompression.

## 2026-08-27 — cooling under a dew point that moved, and a setpoint that did not

Owner asked for cooling urgently. The house had gained **2–4 K across all seven
rooms in roughly an hour** with outdoor at 15.6 degC — Natalie 23.6 → 27.6,
Wohnzimmer 24.6 → 26.7, Gästebad 23.4 → 25.8. Conduction cannot do that against
a 10 K negative outdoor gradient; it is solar through glazing, and it is the
concrete version of the argument for external shading.

`heatctl/set/mode cooling`, retained. Mode took within one cycle, `mode_agrees
1`, compressor 0 → 49 → 69 → 66 Hz.

**The capacity loop found the limit and held it.** Supply 23.6 → 17.6 in about
twelve minutes; `cooling_supply_limit` 17.4; margin **+0.15 K, "in band"**.
Return 21.5, spread 3.9 K. This is the same loop that overshot on 2026-08-21,
behaving correctly on the descent — worth recording, because the raise-path
defect is real and it would be easy to read this loop as broken in general. It
is not. On the way down it did exactly the right thing.

**The dew point is the binding constraint, and the bathroom sets it.** House
dew point went 12.9 → 16.4 during the session, source `badezimmer` (it had been
`gaestebad`). Every 1 K of house dew point is 1 K of supply depression the plant
may not use, so bathroom ventilation is directly cooling capacity. Three rooms
contribute humidity; the migration to per-room Shellys is what widens that.

**What the constraint exposed:** the heat pump's `setpoint_cooling` was 15.0
while the limit was 17.4, and `setpoint.py` has no path that can raise it. This
morning 15.0 was legal (dew point 12.9, floor ~14.0); the floor rose under it.
The clamp is only ever applied to values the trim *proposes*, never to the value
already in the register, and the branch that could raise a cooling setpoint runs
only when the house is `satisfied and idle` — which in a heat wave it is not.
The reversal guard correctly returns `BLOCKED` rather than writing, so nothing
moves. Full trace and fix sketch in BACKLOG, 2026-08-27.

Not dangerous today, because the capacity loop is regulating supply by
frequency. But D-036 put a condensation floor on the setpoint precisely so it
would not be the only layer, and right now it is.

**And a tooling defect that nearly produced a false diagnosis.** Six minutes of
scanning showed nothing on `roomtemp/#` or `rtl_433/#`, which reads as four dead
room feeds. The `homeassistant` account simply has no read permission on those
topics — verified against the ACL deployed on the PFC. Mosquitto grants the
SUBACK and drops the messages at delivery, so "denied" and "silent" are
indistinguishable from the subscriber's side. `tools/plant-status.sh inputs`
subscribes to six patterns and can see three. CLAUDE.md sends a fresh session to
that command.

The rule this belongs to is already in memory as *my connectivity is not plant
state*; this is a sharper form of it. **Not seeing a message is not evidence
that it was not sent** — the broker may simply not be showing it to me.

## 2026-08-28 — the watchdog answered by accident, and an Er03 on the way back

Three things in one window, all with the compressor stopped.

**The `lower_settle_s` change works.** 60 -> 180 s took `writes_last_hour` from
**31 to 9** and cleared `write_budget_exceeded`. Supply held at 16.7–16.9
against a 16.8 limit at 33–37 Hz. The loop still lives on the constraint — that
is what `target_margin_c: 0.0` asks for — but it is no longer walking down
through it one write a minute.

**The watchdog is not there.** Deploying the arming fix needed the compressor
off, so the window was open anyway; heatctl was stopped for **30 s**, three
times the 10 s timeout, and on restart read process data immediately with no
exception 0x04 and no trigger toggle. A 750-352 refuses everything after expiry
until 0x1003 is toggled — that is the 2026-07-27 failure that blocked the plant
for 3.5 h. Third independent negative, after 0x1006 never reporting ACTIVE and
0x1000 accepting writes while supposedly running.

Worth being precise: this proves `pfc-modbus-server` does not implement the
*expiry* behaviour. It does not prove the outputs stayed alive during those
30 s. But a watchdog that does not block I/O is not the failsafe the design was
leaning on, so the distinction no longer changes anything.

The arming fix itself behaves as designed: one `arm written` line, one
`COUPLER WATCHDOG UNCONFIRMED` warning 60 s later, and the container log went
from **~90 lines/minute to 0**.

**And I tripped Er03 restoring cooling.** Not by the documented mechanism — the
compressor was at 0 Hz and unpowered through the whole gap, and the
SOURCE_STOPPED procedure was followed. The fault appeared on the *resume*: mode
went to cooling, the flow floor engaged in the same second and raised the valves
to 41 % mean, and the water-flow fault tripped about a minute later. It cleared
itself in ~4 min, as it did on 2026-08-20.

The likely cause is that the source is commanded on while the manifold is still
stroking — ~150 s — so the pump spends the first minutes pushing against a
partly closed circuit. That is inference; what is not yet established is where
`mode off` parks the valves, which decides how far they had to travel. One log
line settles it, and it should be settled before anyone designs a fix, because
the attractive fix (leave the valves OPEN during `off`) removes the hazard
entirely rather than timing around it.

Second time Er03 has self-cleared without a physical reset. Recorded, not
relied on.
