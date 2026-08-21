#!/bin/sh
# Start the MQTT black box on the PFC200. Idempotent.
#
# No SOURCE_STOPPED and no peer check, same as the normaliser: this container
# has no Modbus library, a read-only broker account (`journal`, `topic read #`,
# no write rule at all), and no route to the plant. Restarting it loses at most
# the buffered second of recording.
#
# THE PIPELINE. `mosquitto_sub` does the MQTT work in C and emits the record
# format directly; `journal.main` only decides which day-file each record goes
# in, rolls at UTC midnight, gzips and prunes. Measured 2026-08-21: the
# all-Python version lost about 40 % (mosquitto logged "Outgoing messages are
# being dropped for client journal"); this pipeline recorded 2376 against 2366
# seen by an independent subscriber over the same wall-clock window.
#
#   %U  epoch seconds with sub-second precision, at RECEIPT
#   %t  topic
#   %p  payload
#
# `journal.main` parses that leading timestamp, so changing the format here
# without changing `looks_like_record` there turns every record into a
# continuation line. A test asserts the two agree.
#
# DEPRIORITISED, NOT CAPPED, and that distinction was learned the hard way. The
# box has one ARMv7 core with no idle time and a 1 s control loop on it, so the
# first version used `--cpus 0.10` as a hard ceiling - and it silently dropped
# two thirds of the traffic. `--cpu-shares 128` is a WEIGHT: it binds only when
# something else wants the core, and then heatctl at the default 1024 wins 8:1.
# Idle capacity stays available to the recorder instead of being forbidden to
# it. A black box that drops messages under exactly the load worth
# investigating is worse than none.
#
# NO PYTHONUNBUFFERED. It was set here to make the start-up line appear, and it
# applies to STDIN too - roughly one read() syscall per message through the
# pipe. The recorder now line-buffers its own stderr and reads stdin through
# its own 256 KB buffer, so the log is readable without putting the environment
# in the hot path.
set -e
D=/media/sdcard/docker-root/journal
RETAIN_DAYS=${JOURNAL_RETAIN_DAYS:-90}

docker network inspect plc >/dev/null 2>&1 || docker network create plc
mkdir -p "$D/data"
docker rm -f journal 2>/dev/null || true
docker run -d --name journal --restart always --network plc \
  --cpu-shares 128 \
  -e JOURNAL_RETAIN_DAYS="$RETAIN_DAYS" \
  -e JOURNAL_DIR=/data \
  -v "$D/data":/data \
  --env-file "$D/journal.env" \
  --entrypoint /bin/sh \
  journal:local -c '
    exec mosquitto_sub -h "$JOURNAL_MQTT_HOST" -p "$JOURNAL_MQTT_PORT" \
        -u "$JOURNAL_MQTT_USERNAME" -P "$JOURNAL_MQTT_PASSWORD" \
        -i journal -t "#" -q 0 -F "%U %t %p" \
      | python3 -m journal.main'

echo "started:"; docker ps --filter name=journal --format "{{.Status}}"
