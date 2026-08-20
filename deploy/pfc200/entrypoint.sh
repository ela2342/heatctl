#!/bin/sh
# Mirrors deploy/ha-addon/run.sh's process contract, which is architecture and
# not convenience.
set -e
CONFIG=${HEATCTL_CONFIG:-/config/config.yaml}

python3 -c "import pymodbus, yaml, aiomqtt; print(
    'deps:', pymodbus.__version__, yaml.__version__, aiomqtt.__version__)" || true

# --- layer 2, optional and allowed to fail ---------------------------------
# BACKGROUNDED AND NEVER `exec`. Layer 2 may crash, hang or be killed without
# the control core noticing, which is only true while they are separate
# processes. Nothing below waits on it or checks its exit.
if [ "${HEATCTL_OPTIMIZER:-1}" = "1" ] && [ -n "${HEATCTL_LATITUDE:-}" ]; then
    echo "Starting the optimizer (layer 2, observe-only)"
    python3 -m optimizer.main "$CONFIG" /app/optimizer/params.yaml &
fi

# Layer 1 as PID 1: if the control core dies the container dies and the
# restart policy notices. Anything else hides a crash behind a live container.
echo "Starting heatctl with $CONFIG"
exec python3 -m heatctl.main "$CONFIG"
