# heatctl

Self-sufficient two-layer control for hydronic floor heating and cooling
on a WAGO 750-352 Modbus coupler. Built for 30-year maintainability:
boring technology, minimal pinned dependencies, single-file hardware truth.

- **Layer 1** (`heatctl/`): control core + safety + telemetry. Keeps the
  house warm with Home Assistant, the optimizer, or the network dead.
- **Layer 2** (`optimizer/`, planned): weather/PV-aware setpoint
  optimization over MQTT. Allowed to fail.

## Architecture

    Shelly H&T ----MQTT----+
    modbus2mqtt <--Modbus--> WAGO 750-352 (PT1000 x16, 0-10V x8, relays)
         |                   ^
        MQTT                 | (modbus_direct fallback / fast DHW loop)
         v                   |
      mosquitto <-------- heatctl (this) ----> SQLite history
         ^
         +---- Home Assistant (bridge; visualization + setpoints only)

I/O transport is pluggable (`io.backend: mqtt | modbus_direct`), so the
bridge is replaceable and the direct path stays as insurance.

## Where things live

| I need... | Go to | Rule |
|---|---|---|
| **What is still open** | `BACKLOG.md` | The **only** place open work is tracked. No TODO comments in code, no "still missing" notes buried in prose — those go stale silently and nobody greps for them. |
| Where the system is going, and what was already done | `ROADMAP.md` | Milestones and their history. Completed items keep their rationale; open ones live in the backlog and are only named here. |
| **Why something is the way it is**, and what we believed before | `docs/DECISIONS.md` | Numbered `D-nnn`, append-only, never renumbered. Reference decisions **by ID** — `see D-012` — never "section 4.3 of DESIGN.md": section numbers move, IDs do not. |
| The whole-system target architecture | `docs/DESIGN.md` | The destination, not today. Work packages WP-A..WP-I. |
| WAGO coupler: registers, wiring, watchdog | `docs/HARDWARE.md` | Device truth. |
| Heat pump: registers, limits, access rules | `docs/HEATPUMP.md` | Device truth. Read before touching heat-pump code. |
| What Home Assistant does, and **what was turned off** | `docs/HA_INTEGRATION.md` | Includes operational state — disabled automations, commented-out config — none of which is discoverable from the running system. |
| Site addresses, credentials, vendor manuals, **building physics** | `docs/*.local.md` | Git-excluded; this repository is public. Envelope areas, U-values, thermal masses, façade azimuths and per-room geometry live in `docs/BUILDING.local.md` — they identify the site, so they never move into a tracked file. |
| How one control decision is made | the module docstring in `heatctl/<module>.py` | Rationale lives next to the code it explains. |
| Whether a rule still holds | `tests/` | Every safety rule has a test; each regression test carries its defect's story. |

**Where new things go**

- An open item → `BACKLOG.md`. Nowhere else.
- A decision that establishes a principle, or reverses an earlier one → a new
  `D-nnn` in `docs/DECISIONS.md`. Routine work does not belong there.
- A fact about a device → `docs/HARDWARE.md` or `docs/HEATPUMP.md`, never
  inline in the code that happens to use it.
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
- Prototype: HA add-on, see `deploy/ha-addon/README.md`
- Target: systemd on a dedicated machine, see `deploy/systemd/README.md`

## Development
See `ROADMAP.md` for milestones, `BACKLOG.md` for what is open, and
`docs/DECISIONS.md` for why things are the way they are.

## License
MIT (add LICENSE before publishing).
