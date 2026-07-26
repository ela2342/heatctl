# heatctl as a Home Assistant App (add-on)

This is the **prototype** deployment. The target architecture runs the same code
as a systemd service on a dedicated machine next to the coupler - see
`../systemd/README.md`. Read the limitations at the bottom before relying on it.

## Build and install

The App's Docker build context is its own directory, so it needs `heatctl/` and
`requirements.txt` inside it. It also cannot live at the repository root,
because HA requires the manifest to be named `config.yaml` and heatctl's own
configuration already claims that name. So the App is assembled on demand
rather than duplicated in git:

    ./assemble.sh                       # -> dist/ha-addon/
    scp -r dist/ha-addon root@<ha-host>:/addons/heatctl

Then in HA: **Settings → Apps → Add-on Store → ⋮ → Check for updates**, and
install heatctl from *Local add-ons*. Re-run `assemble.sh` and re-copy after
changing the source, then Rebuild.

## Configuration, in two places

**App options** (Configuration tab) carry only site-specific values:

| Option | Notes |
|---|---|
| `config_file` | Name of heatctl's config inside the App config dir |
| `log_level` | Overrides `logging.level` |
| `modbus_host` / `modbus_port` | The WAGO coupler. Normally **must** be set |
| `mqtt_*` | Leave empty to use the broker HA already knows about |

Options win over the config file, via heatctl's `HEATCTL_*` environment
overrides. Credentials therefore never live in a tracked file.

**heatctl's own `config.yaml`** holds everything else - register maps, room and
circuit topology, PID gains, safety limits - because it is far too large and too
structural for an options schema. It lives in this App's config directory:

    /addon_configs/<slug>_heatctl/config.yaml      (on the HA host)
    /config/config.yaml                            (inside the container)

It is seeded from the shipped template on first start and **never overwritten**
afterwards, so it survives rebuilds and updates. Edit it with File editor or
over Samba, then restart the App.

## What it does and does not talk to

- **MQTT**: `services: mqtt:want` asks the Supervisor for broker details, so the
  usual case needs no credentials entered. `want` (not `need`) is deliberate:
  the control plane is optional, and the control loop plus every safety rule
  keeps running with the broker dead. You lose telemetry, HA entities and
  remote setpoints - nothing more.
- **Home Assistant APIs**: never. `hassio_api`, `homeassistant_api` and
  `auth_api` are pinned to `false` in the manifest so the layering rule from
  `CLAUDE.md` is enforced by the platform, not just by convention.
- **State**: the SQLite history goes to `/data`, the App's persistent volume, so
  it survives restarts and updates. Nothing heatctl needs has to survive a
  restart - restart means safe state.

## Limitations of running as an App

Honest list, because these are the reasons the target is a dedicated machine:

- **The Supervisor can stop or update this App at any time**, and HA OS updates
  reboot the host. A heating controller that disappears during a host update is
  exactly what the WAGO's own Modbus watchdog exists to cover - so that watchdog
  is *not optional* here. Its output fallback must drive the analog outputs to
  full scale, because valves are fail-open by design; see
  `../../docs/HARDWARE.md`.
- **No hardware watchdog**, and no control over host reboot ordering.
- **Shared fate with HA.** The whole point of layer 1 is to keep the house warm
  when Home Assistant is dead; running inside HA's Supervisor gives that up.
  Fine for bring-up and for validating control logic, wrong for winter.
- **The 100 ms DHW fast loop (Milestone 2) does not belong here** - it needs
  predictable scheduling next to the hardware.
