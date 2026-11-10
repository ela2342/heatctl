# Experiment: slab-target cascade on the valves

**Status: PREPARED, NOT RUN.** Built 2026-11-10 at the owner's request ("you'd
think a primary control loop targeting the slab temperature, and a secondary
loop that steers the slab target from room temperature would perform better
… prepare this as an experiment ready to run when I do"). Off by default:
`control.cascade.enabled: false`.

## Why

Today each room's valves are driven by a PI on **room air** (kp 25 %/K, ki
0.005, integral time 1.4 h). Room air lags the floor by hours, so that loop
sees the consequence of a valve move long after it matters, and the return
temperatures - the richest live signal about the slabs - take no part in it
(they only drive the fallback for rooms without a sensor). On 10-29/30 every
room PI sat at a limit for 48 h; when they did act (Arbeitszimmer, 11-08) the
room overshot by 1.3 K. A loop on the slab itself answers in minutes.

## What it does

```
room setpoint ──► outer loop (per room): feedforward slab target
                    + slow integral trim on (setpoint − room air)  ──► slab target
                                                                       │
circuit water mean (VL+RL)/2 ──► inner loop (per circuit): PI ──► valve demand
```

- **Inner, per circuit** (`Controller._cascade_inner`): a PI holding the
  circuit's water mean `(VL + RL)/2` on its room's slab target. The water mean
  is the quantity the targets are defined in: `slab_target_c` was built on the
  490 W/K measured room->WATER (D-051), so its "slab" is the water mean.
  Measured only while `rl_gate` says MEASURE (flowing ≥ 300 s above 27.5 %);
  FLUSH and HOLD as the return fallback does; a stagnant reading is never
  integrated. Valve opening moves the circuit mean between ~slab (no flow) and
  VL (high flow), so the inner loop has real authority while the supply is
  above the target.
- **Outer, per room** (`Controller._cascade_target`): the energy model's
  target (as the water law uses it, recovery term included) plus a trim that
  integrates `outer_ki_k_per_kh` (0.5 K per K·h) of room-air error, clamped to
  ±`outer_trim_max_k` (3 K), frozen while every circuit of the room is pinned
  in the direction the error pushes (anti-windup). Wohnzimmer uses its room
  mean (`room_temp_offset_per_k`).
- **Eligible rooms**: slab rooms with their own fresh air reading and a target
  younger than `target_max_age_s`. Everything else runs the room PI as today.
  `rooms: []` = all eligible; a list restricts it.
- **Unchanged**: the water law (balance/neediest), distribution (D-017), the
  flow floor, safety. One variable at a time.

## How to run

1. Pick the rooms. A first run on ONE room is cheaper to read: e.g.
   `rooms: [badezimmer]` (one circuit, sensor direct to the plant, setpoint
   23.0).
2. In the LIVE config (`/media/sdcard/docker-root/heatctl/config.yaml`), under
   `control.cascade`: `enabled: true`, `rooms: [...]`. Back up first.
3. Restart with the usual procedure (mode off, 0 Hz, restart, heating).
4. To stop: `enabled: false`, restart.

## What to watch

| topic | meaning |
|---|---|
| `cascade/<room>/target` | the slab target the inner loop chases |
| `cascade/<room>/trim` | the outer loop's correction, K |
| `valve_actual/<valve>` | the inner loop's output after distribution and floor |
| `temp/vl_total`, `temp/<rl>` | the circuit water mean it controls |
| `room/<room>/temp` (`temp_mean`) | the outcome |
| `override/<valve>` | safety interventions (should stay `none`) |

## Success, against the baseline

Baseline = the same room(s) on the room PI over a comparable week (outdoor
within a few K). Better if, over ≥ 3 days:
- room air RMS error vs setpoint lower;
- no valve limit cycle (period of hours, amplitude > 10 %);
- circuit water mean tracks its target within ~1 K while flowing;
- no rise in compressor hours or defrosts attributable to it.

## Abort

- a room > 1.5 K off setpoint for > 6 h in the direction the cascade drove;
- valve oscillation with a period under ~2 h;
- `override/*` firing on a cascade room;
- anything that looks like it fights the flow floor (valves pumping against
  `demand/open_pct` at 41 %).

## Known limitations

- The hourly rl_gate FLUSH re-opens held circuits at 100 % for ~5 min: heat
  into satisfied rooms. DESIGN_ESTIMATION_PLANNING 2.6 wants variance-based
  flushing; not built.
- The water mean is a lumped stand-in for the slab; layer 2's per-room filter
  now estimates slabs from the returns and could replace it (version 2 of
  this experiment, once the filter beats persistence).
- With the water law unchanged, a target above what the supply can reach
  saturates the inner loop; the outer trim then freezes (anti-windup).
- Tuning (inner kp 15 %/K, ki 0.01 → integral time 25 min; outer 0.5 K/K·h)
  is a first guess from the circuit transport time (~5 min) and the house's
  fast mode (~6 h), not identified.
