#!/usr/bin/env bash
# Diff the repository's config.yaml against the one the App is actually running.
#
# WHY THIS EXISTS. `run.sh` seeds /config/config.yaml on FIRST START ONLY and
# never overwrites it, deliberately: that file is the operator's source of truth
# for the register map and safety limits, and clobbering it on restart would be
# catastrophic. The consequence is that **editing config.yaml in this repo does
# not change the running plant**. A deploy ships new CODE; it does not ship new
# CONFIG.
#
# On 2026-07-31 that cost half a day: capacity tuning was committed, deployed,
# reported as live, and was not - the App ran a config file from the previous
# afternoon while the logs showed the old constants and nobody read them.
#
# Divergence is legitimate and expected (mode, host addresses, anything the
# operator has tuned in place). SILENT divergence is the problem. So this
# reports rather than reconciles - deciding which side is right is a human job.
#
#   ./deploy/ha-addon/check-live-config.sh [user@ha-host]
set -euo pipefail

HOST="${1:-root@homeassistant.andreas.org}"
LIVE=/addon_configs/local_heatctl/config.yaml
REPO="$(cd "$(dirname "$0")/../.." && pwd)/config.yaml"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if ! scp -q "${HOST}:${LIVE}" "$TMP"; then
    echo "could not fetch ${LIVE} from ${HOST}" >&2
    exit 2
fi

echo "repo: $REPO"
echo "live: ${HOST}:${LIVE}  (mtime $(ssh "$HOST" "date -r ${LIVE} '+%Y-%m-%d %H:%M'" 2>/dev/null || echo unknown))"
echo

# Only BEHAVIOUR matters here. Strip comment lines, blank lines, AND trailing
# comments - the last one because otherwise a reworded inline note reads as a
# difference, and a checker that cries wolf is a checker nobody runs. Values
# always precede the '#', so nothing real is hidden by this.
strip() { sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//' "$1" \
          | grep -vE '^[[:space:]]*#|^[[:space:]]*$'; }

if diff -u <(strip "$TMP") <(strip "$REPO") > "$TMP.diff"; then
    echo "IN SYNC - no behavioural differences."
    exit 0
fi

echo "BEHAVIOURAL DIFFERENCES  ('-' = live / running, '+' = repo)"
echo "-----------------------------------------------------------------"
tail -n +4 "$TMP.diff"
echo "-----------------------------------------------------------------"
echo
echo "Each '+' line is in the repository and NOT running. Each '-' line is"
echo "running and not in the repository. Decide per line which is right, then"
echo "copy deliberately - do NOT overwrite the live file wholesale, it carries"
echo "operator edits (D-030 and the 2026-07-31 entry in BACKLOG.md)."
exit 1
