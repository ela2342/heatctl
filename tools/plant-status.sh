#!/bin/sh
# One-shot plant status from the workstation, over the PFC broker's TLS port.
#
# WHY THIS EXISTS. The obvious way to look at the plant - `docker run ...
# mosquitto_sub` on the PFC - runs a container on a machine with ONE ARMv7
# core that is already at ~77 % with the control loop on it. Watching the plant
# should not perturb it. 8883 is published on the host, the CA and the
# credentials are on the workstation, so there is no reason to go through the
# device at all.
#
#     tools/plant-status.sh              # heatctl's own state, ~4 s
#     tools/plant-status.sh inputs       # what reaches it from outside, 90 s
#     tools/plant-status.sh raw 'heatctl/hp/#'   # anything, printed verbatim
#
# BOUNDED BY CONSTRUCTION. Every mode passes -W, so it always terminates.
# Nothing here should ever be the thing left running in a terminal.
#
# heatctl's own telemetry is RETAINED (since 2026-08-08), so a few seconds is
# enough to see all of it. The INBOUND feeds are not retained and arrive every
# 60 s or on a radio frame, which is why `inputs` needs a long window - absence
# over a short one proves nothing, and reading it as a dead bridge is a mistake
# already made once.
set -e
HOST=${PFC_HOST:-192.168.178.62}
CA=${PLC_CA:-$HOME/plc-ca.crt}
PWFILE=${PLC_PW:-$HOME/plc-pw}
USER=${PLC_USER:-homeassistant}
PW=$(grep "^$USER:" "$PWFILE" | cut -d: -f2)
[ -n "$PW" ] || { echo "no password for $USER in $PWFILE" >&2; exit 1; }

sub() {  # sub <seconds> <topic>...
    secs=$1; shift
    args=""
    for t in "$@"; do args="$args -t $t"; done
    # shellcheck disable=SC2086
    mosquitto_sub -h "$HOST" -p 8883 --cafile "$CA" -u "$USER" -P "$PW" \
        -v -W "$secs" $args 2>/dev/null | sort -u
}

case "${1:-state}" in
state)
    sub "${2:-4}" \
        'heatctl/status' 'heatctl/mode' 'heatctl/override/#' \
        'heatctl/dew_point/#' 'heatctl/temp/vl_total' 'heatctl/temp/rl_total' \
        'heatctl/room/+/temp' 'heatctl/valve/+' 'heatctl/setpoint/#' \
        'heatctl/demand/#' 'heatctl/hp/target_freq' 'heatctl/hp/compressor_freq' \
        'heatctl/hp/return_water' 'heatctl/hp/setpoint_heating' \
        'heatctl/hp/setpoint_cooling' 'heatctl/hp/writes_last_hour' \
        'heatctl/energy/house_excess_wh' 'heatctl/energy/house_actionable_wh' \
        'heatctl/energy/house_blocked_wh' 'heatctl/energy/rooms_valid' \
        'heatctl/energy/outdoor_c' 'heatctl/energy/outdoor_source' \
        'sensors/room/#'
    ;;
inputs)
    # NOT RETAINED and infrequent. A short window here is worthless.
    echo "watching the inbound feeds for ${2:-90} s (they are not retained)..."
    sub "${2:-90}" 'heatctl/env/#' 'heatctl/set/#' 'roomtemp/#' 'rtl_433/#' \
        'bridge/#' 'heatctl/opt/#'
    ;;
raw)
    shift
    secs=$1; shift
    sub "$secs" "$@"
    ;;
*)
    echo "usage: $0 [state [secs] | inputs [secs] | raw <secs> <topic>...]" >&2
    exit 2
    ;;
esac
