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

## Deployment
- Prototype: HA add-on, see `deploy/ha-addon/README.md`
- Target: systemd on a dedicated machine, see `deploy/systemd/README.md`

## Development
See `PLAN.md` (structured for Claude Code) and `docs/HARDWARE.md`.

## License
MIT (add LICENSE before publishing).
