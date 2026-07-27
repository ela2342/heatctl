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
See `PLAN.md` (structured for Claude Code) and `docs/HARDWARE.md`.

## License
MIT (add LICENSE before publishing).
