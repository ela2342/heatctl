#!/bin/sh
# Install the storage guard on the PFC and wire it in front of dockerd.
#
# RUN THIS AGAIN AFTER ANY WAGO FIRMWARE UPDATE. `/etc` lives on the active
# RAUC slot, so an update reverts both the guard and the patch to WAGO's
# dockerd init script. `plant-storage-guard.sh --check` on the device tells you
# whether the mount is currently right; `grep PLANT-STORAGE-GUARD
# /etc/init.d/dockerd` tells you whether the patch is still there.
#
# Idempotent: safe to re-run, and it will not double-patch.
#
# WHY PATCH WAGO'S SCRIPT rather than add our own init unit. The failure is a
# RACE, so anything that depends on boot ordering has to win the same race we
# already lost. Calling the guard from `do_docker_start` has no ordering
# question at all: it runs exactly when dockerd is about to start, whether that
# is at boot, by hand, or after a crash.
set -e
HOST=${PFC_HOST:-192.168.178.62}
# /etc, not /usr/local/sbin: the latter does not exist on this firmware, and
# /etc is on the active RAUC slot alongside the init script we patch.
GUARD=/etc/plant-storage-guard.sh
INIT=/etc/init.d/dockerd
MARK='PLANT-STORAGE-GUARD'

cd "$(dirname "$0")"

echo "== shipping the guard to $HOST"
scp -q plant-storage-guard.sh "root@$HOST:$GUARD"
ssh "root@$HOST" "chmod 0755 $GUARD"

echo "== patching $INIT (idempotent)"
ssh "root@$HOST" "
set -e
if grep -q '$MARK' $INIT; then
    echo '   already patched, leaving it alone'
    exit 0
fi
cp $INIT $INIT.orig-\$(date +%Y%m%d)
# Insert the guard as the FIRST thing do_docker_start does. Refusing here means
# dockerd never comes up on a tmpfs data-root.
awk '
  /^function do_docker_start\(\)/ { print; getline; print;   # the opening brace
    print \"    # --- $MARK -----------------------------------------------\";
    print \"    # Do not start on a tmpfs data-root. See $GUARD.\";
    print \"    if ! $GUARD; then\";
    print \"        echo \\\"REFUSING to start dockerd: the SD card is not mounted at\\\" >&2\";
    print \"        echo \\\"/media/sdcard, so the data-root would be an empty tmpfs and\\\" >&2\";
    print \"        echo \\\"the plant would have no controller while looking healthy.\\\" >&2\";
    print \"        exit 1\";
    print \"    fi\";
    print \"    # --- end $MARK -------------------------------------------\";
    next }
  { print }
' $INIT > $INIT.new
mv $INIT.new $INIT
chmod 0755 $INIT
echo '   patched'
"

echo "== verifying"
ssh "root@$HOST" "grep -c '$MARK' $INIT && $GUARD --check"
echo
echo "Installed. The guard has NOT been proven against a real boot yet -"
echo "only a reboot does that. See docs/PFC200.md."
