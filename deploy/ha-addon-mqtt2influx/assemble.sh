#!/bin/sh
# Assemble the App build context, then ship it. Run FROM THE REPOSITORY ROOT:
#
#     deploy/ha-addon-mqtt2influx/assemble.sh
#     scp -r dist/ha-addon-mqtt2influx/. root@<ha>:/addons/mqtt2influx/
#     ssh root@<ha> 'ha addons rebuild local_mqtt2influx'
#
# The App cannot build straight from the repository root: the Supervisor copies
# the App directory as the build context, and `mqtt2influx/` lives above it.
set -e
OUT=dist/ha-addon-mqtt2influx
rm -rf "$OUT"; mkdir -p "$OUT"
cp -r mqtt2influx "$OUT/"
cp deploy/ha-addon-mqtt2influx/config.yaml \
   deploy/ha-addon-mqtt2influx/build.yaml \
   deploy/ha-addon-mqtt2influx/Dockerfile \
   deploy/ha-addon-mqtt2influx/run.sh \
   deploy/ha-addon-mqtt2influx/requirements.txt "$OUT/"
echo "assembled $OUT"
