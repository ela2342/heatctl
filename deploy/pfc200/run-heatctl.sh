#!/bin/sh
# Start heatctl on the PFC200. Idempotent; re-run after a rebuild.
#
# SINGLE WRITER. Two heatctl instances writing the same coupler registers is
# the failure this project has already had once, with HA automations on the
# heat pump's register 0. The check lives in `deploy-heatctl.sh`, which runs on
# the workstation and can reach BOTH machines - the device cannot reliably
# reach the HA host, and a check that silently cannot run is worse than none.
#
# If you are running this script by hand, confirm first:
#     ssh root@192.168.178.230 'ha addons info local_heatctl | grep state'
set -e
D=/media/sdcard/docker-root/heatctl

# TZ comes from heatctl.env. The device runs UTC; without it the
# container's log timestamps are two hours off everything else we
# read, which makes cross-referencing an incident needlessly hard.
# Staleness is unaffected either way - that uses time.monotonic().

docker network inspect plc >/dev/null 2>&1 || docker network create plc
docker rm -f heatctl 2>/dev/null || true
docker run -d --name heatctl --restart always --network plc \
  -v "$D/config.yaml":/config/config.yaml:ro \
  --env-file "$D/heatctl.env" \
  heatctl:local

echo "started:"; docker ps --filter name=heatctl --format "{{.Status}}"
