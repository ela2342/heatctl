# Circuit flow characterisation — measured data

Manifold rotameters, read by eye, **±0.3 l/min** by the owner's own estimate.
Scale 0–2.5 l/min; anything at 2.5 is **pinned, i.e. ≥2.5 and unknown above**.
Pump at 100 % (manual, F4=2/F6=100) throughout. Compressor running unless noted.

## The thing that makes this hard

**Flows are coupled through pressure.** The pump is fixed-speed, so head follows
the system curve: throttling some circuits raises Δp across the manifold and
*increases* flow through the others. Measured directly —

| hk01 command | rest of manifold | flow |
|---|---|---|
| 20 % | 7 circuits at 100 % | 0.2 l/min |
| 20 % | 5 circuits at 100 % | **0.5 l/min** |

Same valve, same command, 2.5× the flow.

**There is therefore no per-circuit opening→flow curve.** A circuit's flow is a
function of the entire command set. `open_threshold_pct` / `full_open_pct` as
per-valve constants cannot represent this: a threshold measured with seven
circuits open is wrong when three are. Every row below records the **full
command set**, and only comparisons *within* a row are safe — there the
pressure confound is common to all circuits.

A pressure-independent characteristic would need constant Δp across the
circuit: a variable pump holding constant head, or a Δp measurement to
normalise against. We have neither.

## What is settled

- **Actuator→circuit wiring confirmed for hk01, hk02, hk03** (2026-08-08).
  Commanding each individually moved meters 1/2/3 respectively and nothing
  else. This is the WP-C prerequisite that the 2026-07-27 commissioning sweep
  left all-INCONCLUSIVE. The remaining seven get confirmed as a side effect of
  the passes below.
- **Flow starts somewhere between 15 % and 20 %** on hk01–03, at the operating
  point of pass 1. Zero is an unambiguous reading, so the lower bound is solid.
- The Möhlenhoff datasheet's **5 %** is the *electrical* dead band (0–0.5 V
  ignored), not the hydraulic one, which is at least three times higher. It
  was the configured `open_threshold_pct` until D-041 replaced it with 20.

## What is NOT settled

- **Anything above the meter's 2.5 l/min ceiling.** A pinned meter is an
  instrument limit and says nothing about whether flow keeps rising. Claims of
  "saturation at 40–50 %" and "low valve authority" were made from pinned
  readings on 2026-08-08 and are **withdrawn**.
- **Whether any circuit flattens.** hk03 read 1.7 at 30 % and 1.9 at 60 %, but
  that difference is inside the ±0.3 reading precision.

## Passes

### Pass 0 — 2026-08-08, three circuits, rest at 100 %

Command set: `hk01/02/03` as shown, `hk04 06 07 08 09 10 11` = 100 %.

| command | hk01 | hk02 | hk03 |
|---|---|---|---|
| 5 % | 0 | — | — |
| 10 % | — | 0 | — |
| 15 % | — | — | 0 |
| 20 / 25 / 30 % | 0.2 | 1.2 | 1.7 |
| 40 / 50 / 60 % | ≥2.5 | ≥2.5 | 1.9 |

Note the three columns are at *different* commands per row-group; this pass
swept the three together rather than at matched openings.

### Pass 1 — group A at 20 %

Command set: `hk01 02 03 04 06` = 20 %, `hk07 08 09 10 11` = 100 %.

| circuit | flow |
|---|---|
| hk01 | 0.5 |
| hk02 | 0.8 |
| hk03 | 0.5 |
| hk04 | **0** |
| hk06 | **0** |

**hk04 and hk06 pass nothing where their neighbours pass 0.5–0.8** under
identical conditions. That comparison is valid — same row, same pressure — and
is the first hard evidence that circuits differ materially in resistance or
threshold.

### Pass 2 — group A at 25 %

Command set: `hk01 02 03 04 06` = 25 %, `hk07 08 09 10 11` = 100 %.

| circuit | flow | at 20 % (pass 1) |
|---|---|---|
| hk01 | 1.9 | 0.5 |
| hk02 | 1.7 | 0.8 |
| hk03 | 1.4 | 0.5 |
| hk04 | 1.4 | 0 |
| hk06 | **0.8** | 0 |

**hk06 passes 0.8 where hk01 passes 1.9** at identical command and pressure —
Badezimmer was being starved whenever the plant throttled, and no control logic
fixes that. This is what prompted the balancing below.

---

## THE MANIFOLD WAS BALANCED — 2026-08-08

**All ten circuits set to 2.0 l/min** at 100 % valve opening, using the
rotameters' own throttles, within the instruments' precision (±0.3).

**Everything above this line describes a different plant.** The passes were
taken on an unbalanced manifold and their numbers do not carry forward. They
are kept for the reasoning, not the values.

### Why equal flow and not proportional to floor area

Proposed area-proportional targets (Gästebad 3.43 m² → 0.5 l/min, Kind Natalie
16.33 m² → 2.4) and the owner rejected it, correctly, on two grounds:

1. **It would break the assumption it was meant to serve.** Equal flow makes
   "100 % open" mean the same thing on every circuit, which is exactly what
   `distribution.py` assumes. Different per-circuit maxima would break that
   again.
2. **It bakes a weak proxy into brass.** Floor area is already known to be a
   poor stand-in for load — Wohnzimmer's glazing, the 2.9 K solar spread across
   its own four circuits, per-room envelope exposure nobody has numbers for.
   Committing one such guess to a physical setting, where changing it means a
   trip to the manifold, is worse than leaving a controller with real
   temperature feedback to allocate. Loop lengths are unknown, so the
   proportionality could not be checked either.

Uniform hydraulic authority is the neutral substrate; load differences belong
in the control layer, which can see them and change its mind.

### Consequences to watch

- **Total flow is now ~20 l/min (1.2 m³/h)**, inside the unit's documented
  0.58–1.44 and well above the ~9.6 l/min Er03 floor. Before balancing it was
  higher — seven circuits pinned at ≥2.5 each — so **total flow has dropped**,
  which widens spread for the same heat and pushes supply toward the
  condensation limit. Expect the capacity loop to sit at a lower frequency.
- **The thresholds must be re-measured.** They will have moved, and for the
  first time the answer should be roughly COMMON across circuits rather than
  per-circuit — which is what makes it worth putting in `config.yaml`.
- **`min_open_pct` (55 %) needs re-deriving** against the balanced manifold.

### Post-balancing: the actuator's top half does nothing

All ten circuits commanded together, balanced manifold, pump 100 %:

| command | meters | source side |
|---|---|---|
| 100 % | 2.0 | compressor 77–85 Hz |
| 75 % | **2.0 — unmoved** | |
| 50 % | **1.9** — inside ±0.3, no measurable change | 62–63 Hz, supply 13.0 |

**The actuator has no measurable authority above ~50 %.** After balancing, the
rotameter throttles are the dominant restriction, so anything from 50 % to
100 % is the same plant state.

Caveat on mechanism, not on the result: commanding all ten together is not a
clean isolation — more restriction everywhere makes the pump climb its curve,
so Δp rises and partly compensates. That prevents separating "the actuator is
not restricting" from "Δp made up for it". It does **not** affect the practical
answer, which is what distribution needs: *commanding 75 % instead of 100 %
does not change what the plant delivers.*

**Consequence for `distribution.py`.** It mapped its entire output across
`open_threshold_pct`=5 → `full_open_pct`=100 (20 → 50 since D-041). With flow starting near 15–20 %
and saturating by ~50 %, roughly **two thirds of the commanded range is inert** —
dead at the bottom, saturated at the top. This is the first measurement that
should actually reach `config.yaml`, because it was taken on the balanced
manifold and the balance makes it common to all circuits.

  - [x] **Done 2026-08-19 on the owner's calibration, not on a sweep (D-041).**
        *"Just assume 2-5 V gives 0-100 % opening, which with our balancing
        translates into 0-2 l/min flow."* So `open_threshold_pct: 20`,
        `full_open_pct: 50`, linear between, 0 → 2.0 l/min per circuit.
        `min_open_pct: 55 → 41`, which is `20·(mean−20)/30 = 14.0 l/min`
        against an Er03 floor near 9.6. `rl_gating.min_opening_pct: 15 → 25`,
        because 15 sat below the threshold where water moves at all.

## Still open

  - [ ] **A differential sweep.** Everything above was measured with all ten
        circuits commanded together, and `distribution.py` never produces
        that — D-017 normalises to a spread, which is the configuration where
        pressure coupling is strongest (throttling nine raises Δp across the
        tenth). So the 20 % threshold and the 50 % saturation point are
        established for uniform commands and assumed for the differential
        case that actually runs.

        The pass: hold nine circuits at a low fixed command, sweep the tenth
        5/10/15/20/25/30/40/50/60/80/100 reading its rotameter, then repeat on
        one other circuit to check the answer is common. ~20 readings.
        Deferred by the owner on time grounds, 2026-08-19.

  - [ ] **Whether linearity between 20 % and 50 % holds.** Assumed, not
        measured. It is what makes mean opening proportional to total flow,
        which is what makes `min_open_pct` a derived number rather than a
        guess — so it is load-bearing for D-041's arithmetic.
