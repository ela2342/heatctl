#!/bin/sh
# WAGO's KBUS Modbus server, for Phase D. Idempotent.
#
# WHAT THIS IS FOR. After the coupler swap the 750 terminals sit on the PFC's
# own KBUS, and this serves them over Modbus TCP so `modbus_direct` keeps
# working with nothing but an address change. It is the bridge that lets the
# swap happen before the native KBUS backend (Phase E) exists - and, crucially,
# it keeps a coupler-style watchdog, so the failsafe question defers to E
# instead of blocking the move. See docs/PFC200.md.
#
# NOT ON THE HOST NETWORK, and 502 is deliberately NOT published. heatctl
# reaches it by container name on the `plc` network, exactly as it reaches
# `mqtt-broker`, so the plant's I/O never appears on the LAN. That is the whole
# point of the swap; publishing 502 would hand it straight back.
#
# PINNED BY DIGEST. The image was last pushed in 2022 and `:latest` on a
# four-year-old tag is an invitation for it to change under a running plant -
# the same reasoning as run-broker.sh and requirements.txt.
#
# PRIVILEGED, and that is WAGO's requirement, not a shortcut: it drives
# /dev/kbus0 and needs the D-Bus system socket to arbitrate with whatever else
# might claim the bus. Worth stating plainly because it is a closed 24 KB
# binary running privileged in the plant's I/O path - accepted for Phase D as
# the price of deferring the failsafe question, and retired by Phase E.
#
# THE CODESYS RUNTIME MUST BE OFF (`config_runtime -w runtime-version=0`),
# or it holds /dev/kbus0 and this cannot init. Checked below rather than
# assumed.
set -e
IMAGE=wagoautomation/pfc-modbus-server@sha256:8454bb8008b24f882945936c718293dc83f4e623c9f1c45551a0c71638a1f263

# FAIL CLOSED on the precondition. Without this the container starts, logs
# "KBUS ERROR: 3" for ever, and answers every register with "slave device
# busy" - which heatctl correctly reads as an I/O fault, so the plant sits in
# the stale-data failsafe while the cause scrolls past in another container's
# log.
if fuser /dev/kbus0 >/dev/null 2>&1; then
    echo "REFUSING: /dev/kbus0 is held by PID $(fuser /dev/kbus0 2>&1)." >&2
    echo "  Turn the PLC runtime off first:" >&2
    echo "    /etc/config-tools/config_runtime -w runtime-version=0" >&2
    exit 1
fi

docker network inspect plc >/dev/null 2>&1 || docker network create plc
docker rm -f modbus-server 2>/dev/null || true
docker run -d --name modbus-server --restart always --network plc \
  --init --privileged \
  -v /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket \
  "$IMAGE"

echo "started:"; docker ps --filter name=modbus-server --format "{{.Status}}"
echo
echo "Now verify, because a bad start looks like a good one:"
echo "  docker logs modbus-server        # must NOT repeat 'KBUS ERROR'"
echo "  docker logs heatctl | grep -i 'coupler watchdog'"
echo "     ^ absence means heatctl silently has NO watchdog - see"
echo "       _watchdog_maintain in backends/modbus_direct.py, which returns"
echo "       quietly when the status register is unreadable."
