#!/bin/sh
# Make sure Docker's data-root is the SD CARD before dockerd is allowed to run.
#
# WHY THIS EXISTS. `/media` is a tmpfs (see /etc/fstab), and Docker's data-root
# is `/media/sdcard/docker-root`. If the card is not mounted at
# `/media/sdcard`, that path still exists - on the tmpfs - and dockerd starts
# happily on an empty root with no images and no containers. Nothing reports an
# error. `docker ps` is simply empty and the plant has no controller.
#
# It is not hypothetical and it is not rare. WAGO's hotplug automounter claims
# `/dev/mmcblk0p1` by UUID at `/media/<uuid>`, which wins the race against the
# fstab entry for `/media/sdcard`. Seen twice: once after a card reinsertion
# (2026-08-24) and once after a power outage, where it cost THREE DAYS of the
# plant running with no controller at all while every check looked healthy.
#
# So this script does two things, and the second matters more than the first:
#
#   1. SELF-HEAL. If the card is mounted in the wrong place, move it. If it is
#      not mounted at all, mount it, waiting for the device to enumerate.
#   2. FAIL LOUDLY. If it cannot get the real card onto `/media/sdcard`, it
#      exits non-zero so dockerd REFUSES TO START. An empty plant that says so
#      is strictly better than an empty plant that looks fine - the whole cost
#      of this failure was that it was silent.
#
# Exit 0 = data-root is on the card and safe to use. Non-zero = do not start.
#
# Kept in the repository because `/etc` lives on the active RAUC slot and a
# firmware update reverts it. Reinstall with `install-storage-guard.sh` after
# any WAGO firmware update, and re-check with `--check`.

DEV=/dev/mmcblk0p1
MNT=/media/sdcard
ROOT=$MNT/docker-root
WAIT_S=30

say() { echo "plant-storage-guard: $*" >&2; logger -t plant-storage-guard "$*" 2>/dev/null; }

# THE CARD CAN BE MOUNTED IN MORE THAN ONE PLACE AT ONCE, so neither of these
# may stop at the first hit. Observed after the 2026-09-10 reboot: the card was
# at /media/sdcard AND bind-mounted at /media/sdcard/docker-root, which an
# earlier "first match wins" version of this read as the wrong mountpoint and
# would have tried to "heal" a perfectly healthy system.
#
# Is MNT backed by DEV? Asked directly, ignoring anything else DEV may also be
# mounted on.
mounted_correctly() {
    awk -v d="$DEV" -v m="$MNT" '$1==d && $2==m {ok=1} END {exit !ok}' /proc/mounts
}

# A mountpoint of DEV that is NOT MNT and NOT underneath it - i.e. a stray the
# automounter took. Mounts under MNT are fine and must not be reported: they
# only exist because MNT itself is mounted.
stray() {
    awk -v d="$DEV" -v m="$MNT" '
        $1==d && $2!=m && index($2, m "/")!=1 {print $2; exit}' /proc/mounts
}

if [ "$1" = "--check" ]; then
    if mounted_correctly && [ -d "$ROOT/containers" ]; then
        echo "OK: $DEV on $MNT, docker-root present"; exit 0
    fi
    echo "BAD: $MNT is not backed by $DEV (stray mount: '$(stray)')"; exit 1
fi

# 1. Wait for the card to enumerate. At boot dockerd can win the race against
#    the MMC subsystem, and a missing device is not the same as a broken one.
i=0
while [ ! -b "$DEV" ] && [ "$i" -lt "$WAIT_S" ]; do
    [ "$i" = 0 ] && say "waiting for $DEV to appear..."
    i=$((i + 1)); sleep 1
done
if [ ! -b "$DEV" ]; then
    say "FATAL: $DEV never appeared after ${WAIT_S}s. Is the card seated?"
    exit 1
fi

# 2. Move it if the automounter took it somewhere else. Only when MNT is not
#    already correct - a stray mount alongside a good one is untidy, not
#    broken, and unmounting things we do not have to is its own risk.
cur=$(stray)
if [ -n "$cur" ] && ! mounted_correctly; then
    say "$DEV is mounted at $cur, not $MNT - the automounter won the race"
    # REFUSE rather than force. Something holding files open on the stray
    # mountpoint means this is not the boot-race case, and a lazy unmount here
    # would leave two views of one filesystem - far worse than not starting.
    if fuser -m "$cur" >/dev/null 2>&1; then
        say "FATAL: $cur is in use; not unmounting. Investigate by hand."
        exit 1
    fi
    umount "$cur" || { say "FATAL: could not unmount $cur"; exit 1; }
    say "unmounted $cur"
fi

# 3. Mount it where it belongs. Prefer the fstab entry so the recorded options
#    (noatime, and whatever a later firmware adds) are honoured - but do NOT
#    depend on it. A RAUC firmware update rewrites /etc, and the whole point of
#    this script is to survive the boot where something else has changed.
if ! mounted_correctly; then
    mkdir -p "$MNT"
    if mount "$MNT" 2>/dev/null; then
        say "mounted $DEV at $MNT (per fstab)"
    elif mount -o noatime "$DEV" "$MNT"; then
        say "mounted $DEV at $MNT DIRECTLY - there is no usable fstab entry"
        say "  ^ the plant is up, but fix /etc/fstab: this fallback is a"
        say "    backstop, not the intended configuration."
    else
        say "FATAL: could not mount $DEV at $MNT by either route"
        exit 1
    fi
fi

# 4. Verify, and do not take the mount's word for it. A freshly formatted or
#    wrong card would mount fine and still be empty, which is the exact
#    condition we are here to prevent.
if ! mounted_correctly; then
    say "FATAL: $MNT is still not backed by $DEV - refusing to start dockerd"
    exit 1
fi
if [ ! -d "$ROOT/containers" ]; then
    say "FATAL: $ROOT/containers is missing. The card is mounted but does not"
    say "       carry the plant's docker root. NOT starting dockerd on it -"
    say "       doing so would create an empty one and look healthy."
    exit 1
fi

say "OK: $DEV on $MNT, docker-root present"
exit 0
