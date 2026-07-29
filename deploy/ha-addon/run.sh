#!/usr/bin/with-contenv bashio
# Translate App options into heatctl's environment overrides and start it.
#
# Deliberately explicit `if` blocks rather than `cmd && export ...` one-liners:
# under `set -e` a false bashio::config.has_value would make the statement's
# exit status non-zero and kill the script.
set -euo pipefail

CONFIG_DIR=/config
CONFIG_FILE="$(bashio::config 'config_file')"
if bashio::var.is_empty "${CONFIG_FILE}"; then
    CONFIG_FILE="config.yaml"
fi
TARGET="${CONFIG_DIR}/${CONFIG_FILE}"

# First start: seed an editable copy of the shipped template. Never overwrite an
# existing file - that config is the single source of truth for the register map
# and safety limits, and clobbering it on restart would be catastrophic.
if [ ! -f "${TARGET}" ]; then
    bashio::log.warning "No ${TARGET} yet - seeding from the shipped template."
    bashio::log.warning "It contains PLACEHOLDER addresses and an unverified valve map."
    bashio::log.warning "Review it (rooms, registers, safety limits) before trusting this."
    mkdir -p "$(dirname "${TARGET}")"
    cp /app/config.dist.yaml "${TARGET}"
fi

# --- site values: App options win over the config file ---
if bashio::config.has_value 'heatpump_host'; then
    export HEATCTL_HP_HOST="$(bashio::config 'heatpump_host')"
fi
if bashio::config.has_value 'heatpump_port'; then
    export HEATCTL_HP_PORT="$(bashio::config 'heatpump_port')"
fi
if bashio::config.has_value 'modbus_host'; then
    export HEATCTL_MODBUS_HOST="$(bashio::config 'modbus_host')"
fi
if bashio::config.has_value 'modbus_port'; then
    export HEATCTL_MODBUS_PORT="$(bashio::config 'modbus_port')"
fi
if bashio::config.has_value 'log_level'; then
    export HEATCTL_LOG_LEVEL="$(bashio::config 'log_level')"
fi

# MQTT: an explicit host wins; otherwise use whatever broker the Supervisor
# knows about, so the normal case needs no credentials typed in anywhere.
if bashio::config.has_value 'mqtt_host'; then
    export HEATCTL_MQTT_HOST="$(bashio::config 'mqtt_host')"
    if bashio::config.has_value 'mqtt_port'; then
        export HEATCTL_MQTT_PORT="$(bashio::config 'mqtt_port')"
    fi
    if bashio::config.has_value 'mqtt_username'; then
        export HEATCTL_MQTT_USERNAME="$(bashio::config 'mqtt_username')"
    fi
    if bashio::config.has_value 'mqtt_password'; then
        export HEATCTL_MQTT_PASSWORD="$(bashio::config 'mqtt_password')"
    fi
    bashio::log.info "MQTT: using configured broker ${HEATCTL_MQTT_HOST}"
elif bashio::services.available 'mqtt'; then
    export HEATCTL_MQTT_HOST="$(bashio::services 'mqtt' 'host')"
    export HEATCTL_MQTT_PORT="$(bashio::services 'mqtt' 'port')"
    export HEATCTL_MQTT_USERNAME="$(bashio::services 'mqtt' 'username')"
    export HEATCTL_MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"
    bashio::log.info "MQTT: using the Supervisor's broker at ${HEATCTL_MQTT_HOST}:${HEATCTL_MQTT_PORT}"
else
    bashio::log.warning "MQTT: no broker configured and none offered by the Supervisor."
    bashio::log.warning "The control loop and all safety rules still run; only telemetry,"
    bashio::log.warning "HA entities and remote setpoints are unavailable. This is by design."
fi

if bashio::config.has_value 'modbus_host'; then
    bashio::log.info "Modbus: ${HEATCTL_MODBUS_HOST}:${HEATCTL_MODBUS_PORT:-502}"
else
    bashio::log.warning "Modbus: no modbus_host set, falling back to config.yaml -"
    bashio::log.warning "which ships a PLACEHOLDER address, so this will not reach hardware."
fi

# --- layer 2, optional and allowed to fail ---------------------------------
# Started as a SEPARATE process, backgrounded, and never with `exec`. That is
# the architecture, not convenience: layer 2 may crash, hang or be killed
# without the control core noticing, which is only true if they are not the
# same process. It is also why nothing below waits on it or checks its exit.
#
# It needs coordinates for solar position and the forecast; without them it
# logs a warning and runs without either, so an unset option is not an error.
if bashio::config.has_value 'latitude'; then
    export HEATCTL_LATITUDE="$(bashio::config 'latitude')"
fi
if bashio::config.has_value 'longitude'; then
    export HEATCTL_LONGITUDE="$(bashio::config 'longitude')"
fi
if bashio::config.true 'optimizer_enabled'; then
    if bashio::config.has_value 'latitude'; then
        bashio::log.info "Starting the optimizer (layer 2, observe-only)"
        cd /app
        python3 -m optimizer.main "${TARGET}" /app/optimizer/params.yaml &
    else
        bashio::log.warning "optimizer_enabled but no latitude/longitude set -"
        bashio::log.warning "it cannot compute solar position or fetch a forecast."
    fi
fi

bashio::log.info "Starting heatctl with ${TARGET}"
cd /app
exec python3 -m heatctl.main "${TARGET}"
