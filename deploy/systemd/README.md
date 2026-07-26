# Dedicated machine deployment (target architecture)

All of the critical path runs on ONE dedicated machine next to the coupler:

    mosquitto (broker)  <-- HA bridges into this, not the other way round
    modbus2mqtt         <-- WAGO <-> MQTT bridge (systemd service, no HA add-on)
    heatctl             <-- this project

Install sketch:
    apt install mosquitto
    # modbus2mqtt: install per its docs, run as systemd service,
    #   configure register map, see ../../docs/MODBUS2MQTT.md
    python -m venv /opt/heatctl/venv
    /opt/heatctl/venv/bin/pip install -r requirements.txt
    cp heatctl.service /etc/systemd/system/ && systemctl enable --now heatctl

MANDATORY: enable the Modbus watchdog on the WAGO coupler (WBM) so the
750-559 outputs fall to a safe state when heatctl stops writing. (This is
also the only thing that notices heatctl dying or hanging - it is not just
about the MQTT bridge, which is no longer used.)

## MQTT credentials
`config.yaml` is committed, so it must never hold the broker password. The
control plane reads `HEATCTL_MQTT_USERNAME` / `HEATCTL_MQTT_PASSWORD` from the
environment when the config fields are empty. For systemd:

    # /etc/heatctl/mqtt.env   (chmod 600, root-owned)
    HEATCTL_MQTT_USERNAME=heatctl
    HEATCTL_MQTT_PASSWORD=...

then add to the unit's [Service] section:

    EnvironmentFile=/etc/heatctl/mqtt.env

On the target machine mosquitto is local, so an anonymous localhost listener
may make credentials unnecessary - then leave both unset.

Today heatctl borrows Home Assistant's own `homeassistant` broker account,
which works but means an HA credential rotation silently breaks heatctl.
Prefer a dedicated login (Mosquitto add-on option `logins:`, which needs an
add-on restart, or a dedicated HA user).
