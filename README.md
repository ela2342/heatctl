# heatctl

Self-sufficient two-layer control for hydronic floor heating and cooling
on a WAGO 750-352 Modbus coupler. Built for 30-year maintainability:
boring technology, minimal pinned dependencies, single-file hardware truth.

- **Layer 1** (`heatctl/`): control core + safety + telemetry. Keeps the
  house warm with Home Assistant, the optimizer, or the network dead.
- **Layer 2** (`optimizer/`): weather/PV-aware setpoint optimization over
  MQTT. Allowed to fail. **Observe-only today** — it runs the thermal model
  and publishes what it believes under `heatctl/opt/…`, and it structurally
  cannot send a set command (see `optimizer/estimator.py`). Setpoint
  optimization proper is gated on `ControlPlane` gaining command TTL and on
  the model earning trust against its own innovation statistics.

      venv/bin/python -m optimizer.main ./config.yaml

Beside them, and belonging to neither — **plumbing and observation**. None of
these decides anything, none can reach the plant, and heatctl works with all
three dead:

- **`normaliser/`** — room sensors sleep and their status topics are not
  retained, so a restart is blind per room for a whole wake period. It
  republishes each sample retained with an MQTT 5 expiry, so the broker holds
  the deadline (D-047).
- **`journal/`** — the black box. `mosquitto_sub` piped into a rotator, writing
  every message to the PFC's SD card with a UTC daily roll and 90-day
  retention. Exists because the 2026-08-21 capacity-loop finding only survived
  by luck.
- **`mqtt2influx/`** — the same stream into the InfluxDB that already runs on
  the Home Assistant host, for Grafana. A bounded 30-day window; the long
  history stays with the plant.

      venv/bin/python -m normaliser.main ./normaliser/config.yaml
      venv/bin/python -m journal.main            # reads records on stdin
      venv/bin/python -m mqtt2influx.main        # reads /data/options.json

## Architecture

Two machines. Everything in the dotted box runs on the PFC200 and survives the
LAN going away; only Modbus to the coupler still crosses it, and Phase D
removes that too (`docs/PFC200.md`).

    .- WAGO PFC200 750-8212 (1 ARMv7 core) --------------------.
    |                                                          |
    |  heatctl ── SQLite history      (containers, `docker ps`) |
    |     │  ▲                                                 |
    |     ▼  │            normaliser ──┐                       |
    |  mqtt-broker ◄──────────────────┬┴── journal ── SD card  |
    |     ▲   │                       │                        |
    '-----│---│-----------------------│------------------------'
          │   │ TLS 8883              │ bridge (both ways)
          │   ▼                       ▼
          │  Shelly H&T (sleep 360 s)  Home Assistant .230
          │                             ├─ mqtt2influx ─► InfluxDB ─► Grafana
          │                             ├─ rtl_433 (WH65B outdoor)
          │                             └─ Controme RC bridge (retiring)
          │ Modbus TCP
          ├─► WAGO 750-352 coupler .52   (PT1000 ×16, 0–10 V ×16)
          └─► PW58321 heat pump .37:4196 (RS485 via Waveshare)

I/O transport is pluggable (`io.backend: mqtt | modbus_direct`), so the
coupler link is replaceable and the direct path stays as insurance.

## Looking at the running plant

Three tools, and the right one depends on the question. **Do not go through the
PFC to observe the PFC** — it has one core and a 1 s control loop on it.

| Question | Tool |
|---|---|
| What is it doing *right now*? | `tools/plant-status.sh` |
| What happened at 11:47:49? | the journal on the PFC, with `grep`/`zgrep` |
| Show me a week of it | InfluxDB + Grafana on the HA host |

```sh
tools/plant-status.sh                 # heatctl's own state, ~4 s, bounded
tools/plant-status.sh inputs          # the non-retained inbound feeds, 90 s
tools/plant-status.sh raw 20 'heatctl/hp/#'
```

It talks to the broker's TLS port from the workstation using `~/plc-ca.crt` and
`~/plc-pw`; every mode passes `-W`, so it always terminates.

The journal is `/media/sdcard/docker-root/journal/data/mqtt-YYYYMMDD.log` on
the PFC, one line per message as `<epoch> <topic> <payload>`:

```sh
ssh root@<pfc>; D=/media/sdcard/docker-root/journal/data
grep  ' heatctl/capacity/reason ' $D/mqtt-20260821.log
zgrep ' heatctl/hp/silent_max_freq_cooling_hz ' $D/*.gz
date -d @1787313600            # the timestamps are epoch seconds
```

InfluxDB holds the same stream as one measurement, queryable from the HA host —
numeric payloads in `value`, everything else in `text`:

```sql
SELECT last(value) FROM mqtt WHERE topic = 'heatctl/temp/vl_total'
SELECT last(text)  FROM mqtt WHERE topic = 'heatctl/capacity/reason'
```

**A trap worth knowing before you measure anything:** a freshly connected
subscriber receives the whole **retained snapshot** first — around 800 messages
— which a long-running recorder never sees. Counting lines from a new
`mosquitto_sub` therefore makes any recorder look ~25 % short when it is losing
nothing. Compare by wall-clock window on the timestamps instead. That cost two
rounds of chasing a bug that did not exist.

## Where things live

| I need... | Go to | Rule |
|---|---|---|
| **What is still open** | `BACKLOG.md` | The **only** place open work is tracked. No TODO comments in code, no "still missing" notes buried in prose — those go stale silently and nobody greps for them. |
| **What happened, and what we believed at the time** | `LOGBOOK.md` | Investigations, incidents, measurements and superseded designs, append-only and dated. Read it before re-running an experiment or re-deriving a number. It is not a task list — nothing in it is tracked. |
| Where the system is going, and what was already done | `ROADMAP.md` | Milestones and their history. Completed items keep their rationale; open ones live in the backlog and are only named here. |
| **Why something is the way it is**, and what we believed before | `docs/DECISIONS.md` | Numbered `D-nnn`, append-only, never renumbered. Reference decisions **by ID** — `see D-012` — never "section 4.3 of DESIGN.md": section numbers move, IDs do not. |
| The whole-system target architecture | `docs/DESIGN.md` | The destination, not today. Work packages WP-A..WP-I. |
| WAGO coupler: registers, wiring, watchdog | `docs/HARDWARE.md` | Device truth. |
| Heat pump: registers, limits, access rules | `docs/HEATPUMP.md` | Device truth. Read before touching heat-pump code. |
| PFC200 750-8212: the target controller | `docs/PFC200.md` | Device truth. Survey, the watchdog question, and what it costs. |
| What Home Assistant does, and **what was turned off** | `docs/HA_INTEGRATION.md` | Includes operational state — disabled automations, commented-out config — none of which is discoverable from the running system. |
| Site addresses, credentials, vendor manuals, **building physics** | `docs/*.local.md` | Git-excluded; this repository is public. Envelope areas, U-values, thermal masses, façade azimuths and per-room geometry live in `docs/BUILDING.local.md` — they identify the site, so they never move into a tracked file. |
| How one control decision is made | the module docstring in `heatctl/<module>.py` | Rationale lives next to the code it explains. |
| Whether a rule still holds | `tests/` | Every safety rule has a test; each regression test carries its defect's story. |
| **What is actually running, and on which machine** | § Architecture above, then `docs/PFC200.md` (the three PFC containers) and `docs/HA_INTEGRATION.md` (the HA Apps) | There are two machines and six processes. Guessing from the repository layout will miss half of them. |
| **How to see what the plant is doing** | § Looking at the running plant above | `tools/plant-status.sh` for now, the journal for a past moment, InfluxDB for a trend. Includes the retained-snapshot trap. |

**Where new things go**

- An open item → `BACKLOG.md`. Nowhere else.
- What you did, measured or found out → `LOGBOOK.md`, dated, appended. If it
  leaves something to do, the *task* goes to the backlog with a pointer back.
  Keeping the two apart is deliberate: the backlog was 6 300 lines and mostly
  narrative before they were split on 2026-08-21, which made it useless as
  both.
- A decision that establishes a principle, or reverses an earlier one → a new
  `D-nnn` in `docs/DECISIONS.md`. Routine work does not belong there.
- A fact about a device → `docs/HARDWARE.md`, `docs/HEATPUMP.md` or
  `docs/PFC200.md`, never inline in the code that happens to use it.
- A new **process** → named in § Architecture here, with its operational
  detail in `docs/PFC200.md` if it runs on the PFC or `docs/HA_INTEGRATION.md`
  if it runs on Home Assistant. A component documented only in its own module
  docstring is one nobody will find.
- Rationale for *how a module works* → that module's docstring.

The failure mode this structure exists to prevent: a decision recorded only in
a commit message, an open item recorded only in a conversation, and a device
fact recorded only in the code that happens to use it.

## Quickstart (development)
    python -m venv venv && venv/bin/pip install -r requirements.txt
    venv/bin/python -m heatctl.main ./config.yaml

## Tests
    venv/bin/pip install -r requirements-dev.txt
    venv/bin/pytest

No hardware and no broker required — the coupler and the MQTT plane are faked.
Every safety rule is tested by the *direction* of its failure (fail-open on
lost knowledge, fail-closed on known-bad supply), and each regression test
names the defect it came from.

## Configuration
`config.yaml` is the single source of truth for register mapping, topology and
safety limits, and is versioned. It carries **placeholder addresses**
(`192.0.2.x`, RFC 5737) because this repository is public. Environment
variables override the file, so point it at real hardware without editing a
tracked file:

    HEATCTL_MODBUS_HOST   WAGO coupler address      (default: config.yaml)
    HEATCTL_MODBUS_PORT   default 502
    HEATCTL_MQTT_HOST     control-plane broker
    HEATCTL_MQTT_PORT     default 1883
    HEATCTL_MQTT_USERNAME broker credentials - never put these in config.yaml
    HEATCTL_MQTT_PASSWORD

For systemd use an `EnvironmentFile`; see `deploy/systemd/README.md`.

## Deployment
**Live since 2026-08-20: a container on the WAGO PFC200 750-8212**
(`deploy/pfc200/`, see `docs/PFC200.md`). Control plane on a broker on the same
box, Modbus still over the network to the 750-352 coupler. The PFC has no
Python and no pip, so it runs containerised — `deploy/systemd/` does not apply
to it.

- Previous: HA add-on, `deploy/ha-addon/`. **Stopped, not removed** — it is the
  rollback, and its config directory is still the seed for the PFC's.
- Next: swap the coupler for the PFC so the control↔I/O link stops crossing the
  network. Gated on a watchdog bench test — see `docs/PFC200.md`.

**Moving control between machines needs a procedure**, not just a stop and a
start: stop the *source* first, or the coupler watchdog closes the valves under
a running compressor and trips a latching Er03. Cutover steps in
`docs/PFC200.md`.

## Development
See `ROADMAP.md` for milestones, `BACKLOG.md` for what is open, and
`docs/DECISIONS.md` for why things are the way they are.

## License
MIT (add LICENSE before publishing).
