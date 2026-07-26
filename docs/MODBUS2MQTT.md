# modbus2mqtt bridge configuration (to be completed in milestone 0)

Goal: bridge the WAGO 750-352 to MQTT so heatctl's `mqtt` io backend and
any other consumer see uniform topics.

Requirements for the bridge configuration:
- Poll input registers 12..27 (function code 4) at 1 s
- Publish RAW register values (heatctl decodes PT1000 itself, so fault
  saturation values 0x05DC/0xFED4 stay detectable). If your bridge insists
  on scaling, adjust `sensors`/fault detection accordingly - but raw is
  strongly preferred.
- Subscribe write topics for holding registers 12..19 (function code 6)
- Topic templates must match io.mqtt_io in config.yaml:
    temp:  modbus/wago/temp/<name>        (bridge -> broker)
    valve: modbus/wago/valve/<name>/set   (heatctl -> bridge)
- QoS 0 is fine (fresh beats reliable-but-old); DO NOT retain temp topics,
  retained stale values would defeat staleness detection.

Also enable the WAGO coupler's own Modbus watchdog (WBM) - it is the only
failsafe that survives a bridge crash.

Document the final bridge config file here verbatim once it works.
