#!/bin/sh
# Recreate the heatctl plant broker. Idempotent: run it again after changing
# this file. Config, certs, data and log are bind-mounted, so nothing the
# broker keeps lives inside the container.
#
# IMAGE IS PINNED BY DIGEST, not `:latest`. This project's premise is 30-year
# maintainability, and an unpinned tag means a pull can change the broker
# under a plant that was working. Same reasoning as requirements.txt.
set -e
IMAGE=eclipse-mosquitto@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797
D=/media/sdcard/docker-root/mosquitto

docker network inspect plc >/dev/null 2>&1 || docker network create plc

docker rm -f mqtt-broker 2>/dev/null || true
docker run -d --name mqtt-broker --restart always --network plc \
  -p 8883:8883 \
  -v "$D/config":/mosquitto/config \
  -v "$D/certs":/mosquitto/certs \
  -v "$D/data":/mosquitto/data \
  -v "$D/log":/mosquitto/log \
  "$IMAGE"

# 8883 is the ONLY published port. 1883 stays inside the `plc` network for
# heatctl; 9001 was mapped to a listener that did not exist and is gone.
echo "started:"; docker ps --filter name=mqtt-broker --format "{{.Status}}  {{.Ports}}"
