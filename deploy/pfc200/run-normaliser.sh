#!/bin/sh
# Start the sensor-topic normaliser on the PFC200. Idempotent.
#
# NO SINGLE-WRITER CHECK, and no SOURCE_STOPPED gate, unlike run-heatctl.sh.
# Neither applies: this container has no Modbus library and no route to the
# coupler or the heat pump, and restarting it cannot create a control gap -
# heatctl keeps running on whatever is already retained, and falls back to its
# own staleness handling if this never comes back. That asymmetry is the
# reason it is a separate container.
set -e
D=/media/sdcard/docker-root/normaliser

docker network inspect plc >/dev/null 2>&1 || docker network create plc
docker rm -f normaliser 2>/dev/null || true
docker run -d --name normaliser --restart always --network plc \
  -v "$D/config.yaml":/config/normaliser.yaml:ro \
  --env-file "$D/normaliser.env" \
  normaliser:local

echo "started:"; docker ps --filter name=normaliser --format "{{.Status}}"
