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
750-559 outputs fall to a safe state when the bridge stops writing.
