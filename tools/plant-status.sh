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

sub() {  # sub <seconds> <topic>...   sorted+deduped, for a state snapshot
    raw_sub "$@" | sort -u
}

raw_sub() {  # raw_sub <seconds> <topic>...   STREAMED, in arrival order
    secs=$1; shift
    args=""
    for t in "$@"; do args="$args -t $t"; done
    # shellcheck disable=SC2086
    mosquitto_sub -h "$HOST" -p 8883 --cafile "$CA" -u "$USER" -P "$PW" \
        -v -W "$secs" $args 2>/dev/null
}

case "${1:-state}" in
state)
    sub "${2:-4}" \
        'heatctl/status' 'heatctl/mode' 'heatctl/override/#' \
        'heatctl/dew_point/#' 'heatctl/temp/vl_total' 'heatctl/temp/rl_total' \
        'heatctl/room/+/temp' 'heatctl/room/+/source' \
        'heatctl/valve/+' 'heatctl/setpoint/#' \
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
rooms)
    # THE VIEW THAT WOULD HAVE CAUGHT 2026-08-22. Badezimmer read 29.3 degC all
    # day from a sensor that had published twice in eleven hours; heatctl knew
    # (`source` was `house_avg`, the only room that day) and said so on a topic
    # this script did not ask for. A number with no provenance beside it is
    # what got quoted in a status report.
    tmp=$(mktemp); sub "${2:-4}" 'heatctl/room/+/temp' 'heatctl/room/+/source' \
        'heatctl/setpoint/#' 'sensors/room/+/sample_ts' > "$tmp"
    now=$(date +%s)
    printf "%-16s %7s %7s  %-10s %s\n" room now set source "sample age"
    for r in $(awk -F/ '/heatctl\/room\//{print $3}' "$tmp" | sort -u); do
        g() { awk -v k="$1" '$1==k{print $2}' "$tmp" | tail -1; }
        ts=$(g "sensors/room/$r/sample_ts")
        age="-"
        [ -n "$ts" ] && age="$(( (now - ${ts%.*}) ))s"
        printf "%-16s %7s %7s  %-10s %s\n" "$r" \
            "$(g "heatctl/room/$r/temp")" "$(g "heatctl/setpoint/$r")" \
            "$(g "heatctl/room/$r/source")" "$age"
    done
    rm -f "$tmp"
    echo
    echo "source=house_avg means the room's own reading aged out and control"
    echo "is using the house mean. 'sample age' is only available for rooms"
    echo "that go through the normaliser; the rest have no age published yet."
    ;;
raw)
    # STREAMED, not sorted: `raw` is for WATCHING something change, and
    # `sort -u` both destroys the ordering and buffers everything until the
    # window closes - so an outer `timeout` shorter than the window throws the
    # whole capture away. That happened on 2026-08-22 and the empty file was
    # nearly read as "nothing is publishing".
    shift
    secs=$1; shift
    raw_sub "$secs" "$@"
    ;;
*)
    echo "usage: $0 [state [secs] | rooms [secs] | inputs [secs] |" >&2
    echo "          raw <secs> <topic>...]" >&2
    exit 2
    ;;
esac
