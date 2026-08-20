#!/bin/sh
# Build and run the sensor-topic normaliser on the PFC200. Run FROM THE
# REPOSITORY ROOT:
#
#     deploy/pfc200/deploy-normaliser.sh
#
# Ships code, builds on the device, starts the container. It does NOT touch
# /media/sdcard/docker-root/normaliser/config.yaml - a deploy ships code, never
# config, the same rule heatctl deploys follow.
#
# Safe to run at any time. It cannot interrupt control: the image carries no
# Modbus library, and heatctl reads what is already retained on the broker
# while this restarts.
set -e
HOST=${PFC_HOST:-192.168.178.62}
D=/media/sdcard/docker-root/normaliser

echo "== shipping source"
tar czf - normaliser \
    -C deploy/pfc200 Dockerfile.normaliser run-normaliser.sh \
  | ssh "root@$HOST" "mkdir -p $D/build && tar xzf - -C $D/build"

echo "== building on the device (one ARMv7 core, be patient)"
ssh "root@$HOST" "cd $D/build && docker build -f Dockerfile.normaliser -t normaliser:local ."

echo "== (re)starting"
ssh "root@$HOST" "cp $D/build/run-normaliser.sh $D/run-normaliser.sh && sh $D/run-normaliser.sh"
