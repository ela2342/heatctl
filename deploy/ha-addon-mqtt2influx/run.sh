#!/usr/bin/with-contenv bashio
# The App reads /data/options.json itself (see mqtt2influx/main.py for why),
# so this only fills in what the SUPERVISOR knows and the options file cannot:
# the broker's address and credentials.
#
# All four, not just the host. The first version exported MQTT_HOST alone and
# the App connected anonymously - HA's mosquitto refuses that, so it sat in a
# reconnect loop reporting "Not authorized" with a perfectly good broker.
set -e

if bashio::services.available "mqtt" && [ -z "$(bashio::config 'mqtt_host')" ]; then
    export MQTT_HOST="$(bashio::services mqtt 'host')"
    export MQTT_PORT="$(bashio::services mqtt 'port')"
    export MQTT_USERNAME="$(bashio::services mqtt 'username')"
    export MQTT_PASSWORD="$(bashio::services mqtt 'password')"
    bashio::log.info "Using the Supervisor's broker at ${MQTT_HOST}:${MQTT_PORT} as ${MQTT_USERNAME}"
fi

exec python3 -m mqtt2influx.main
