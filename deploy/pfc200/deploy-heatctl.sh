#!/bin/sh
# Build and run heatctl on the PFC200. Run FROM THE REPOSITORY ROOT:
#
#     deploy/pfc200/deploy-heatctl.sh
#
# Ships code, builds on the device, and starts the container. It does NOT
# touch /media/sdcard/docker-root/heatctl/config.yaml - same rule as the App,
# the operator's config is the source of truth for the register map and the
# safety limits and a deploy must not be able to clobber it.
set -e
HOST=${PFC_HOST:-192.168.178.62}
HA=${HA_HOST:-192.168.178.230}
D=/media/sdcard/docker-root/heatctl

# SINGLE WRITER, checked from here because this machine can reach both. Fails
# CLOSED: if the App's state cannot be determined, refuse rather than assume.
if [ "${SKIP_PEER_CHECK:-0}" != "1" ]; then
    state=$(ssh -o ConnectTimeout=5 "root@$HA" \
            'ha addons info local_heatctl --raw-json 2>/dev/null' \
            | grep -o '"state":"[a-z]*"' | head -1) || state=""
    case "$state" in
        *stopped*) : ;;
        "")  echo "REFUSING: cannot determine whether the HA App is running." >&2
             echo "Two controllers on one coupler is the failure this prevents." >&2
             exit 1 ;;
        *)   echo "REFUSING: the HA App local_heatctl is $state." >&2
             echo "Stop it first:  ssh root@$HA 'ha addons stop local_heatctl'" >&2
             exit 1 ;;
    esac
fi

# THE SOURCE MUST BE STOPPED BEFORE THE GAP. Owner, 2026-08-20, after the
# first cutover tripped Er03: when the controller stops, the coupler watchdog
# expires after 10 s and zeroes the outputs, the NC actuators close, flow
# through the heat pump collapses, and a RUNNING compressor trips its
# water-flow fault - which latches. It self-cleared in 4.5 min that time and
# has needed a physical reset before.
#
# Not automated here on purpose: stopping the source is `mode off`, and
# watching the frequency reach 0 before pulling the controller is a judgement
# a script should not fake. The full procedure is in docs/PFC200.md. This flag
# is the acknowledgement that it was followed.
if [ "${SOURCE_STOPPED:-0}" != "1" ]; then
    echo "REFUSING: set SOURCE_STOPPED=1 once the compressor is at 0 Hz." >&2
    echo "  See the cutover procedure in docs/PFC200.md - skipping it tripped" >&2
    echo "  Er03 on 2026-08-20." >&2
    exit 1
fi

echo "== shipping source"
tar czf - heatctl optimizer requirements.txt \
    -C deploy/pfc200 Dockerfile entrypoint.sh \
  | ssh "root@$HOST" "mkdir -p $D/build && tar xzf - -C $D/build"

echo "== building on the device (one ARMv7 core, be patient)"
ssh "root@$HOST" "cd $D/build && docker build -t heatctl:local ."

echo "== (re)starting"
ssh "root@$HOST" "sh $D/run-heatctl.sh"
