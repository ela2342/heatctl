# heatctl as HA add-on (prototype only)

Copy this directory plus heatctl/, config.yaml, requirements.txt to
/addons/heatctl/ on the HA host, install via Add-on Store -> Local add-ons.

For prototyping, point mqtt.host at the HA Mosquitto and io.backend at
"modbus_direct" (simplest) or configure the Modbus2MQTT add-on topics.

The target architecture is the SAME code as a systemd service on a
dedicated machine - see deploy/systemd/README.md.
