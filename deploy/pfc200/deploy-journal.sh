#!/bin/sh
# Build and run the MQTT black box on the PFC200. Run FROM THE REPOSITORY ROOT:
#
#     deploy/pfc200/deploy-journal.sh
#
# Ships code, builds on the device, starts the container. It does NOT touch
# /media/sdcard/docker-root/journal/config.yaml, and it never touches
# .../journal/data - a deploy must not be able to destroy the recording it
# exists to improve.
#
# Safe to run at any time: the image carries no Modbus library and the broker
# account is read-only.
set -e
HOST=${PFC_HOST:-192.168.178.62}
D=/media/sdcard/docker-root/journal

echo "== shipping source"
tar czf - journal \
    -C deploy/pfc200 Dockerfile.journal run-journal.sh \
  | ssh "root@$HOST" "mkdir -p $D/build && tar xzf - -C $D/build"

echo "== building on the device (one ARMv7 core, be patient)"
ssh "root@$HOST" "cd $D/build && docker build -f Dockerfile.journal -t journal:local ."

echo "== (re)starting"
ssh "root@$HOST" "cp $D/build/run-journal.sh $D/run-journal.sh && sh $D/run-journal.sh"
