#!/usr/bin/env bash
# Deploy heatctl to the HA App, fail-fast and verified at every step.
#
# WHY THIS EXISTS. On 2026-07-31 a deploy was run as a loose chain of commands.
# The code `scp` failed with one line of output, the chain continued, the CONFIG
# was uploaded successfully, and the App rebuilt with **new config against old
# code**. A key removed from both crashed the controller on startup:
#
#     KeyError: 'vl_min_cooling_c'
#
# heatctl was down for 30 minutes. It failed safe - the coupler watchdog zeroed
# the outputs and the NC valves closed - but the house got no cooling on a warm
# afternoon, and nothing announced it.
#
# The lesson is not "be careful with scp". It is that a deploy which is a
# sequence of independent commands has no failure semantics at all: any step can
# fail and the rest proceed. So this script is `set -e`, verifies what it
# uploaded actually arrived, and does not consider the job done until the App is
# running and its log is free of tracebacks.
#
#   ./deploy/ha-addon/deploy.sh [user@ha-host]
set -euo pipefail

HOST="${1:-root@homeassistant.andreas.org}"
SLUG=local_heatctl
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SUP=(ssh "$HOST" curl -s -H '"Authorization: Bearer $SUPERVISOR_TOKEN"')

say() { printf '\n=== %s\n' "$*"; }

say "tests"
"$ROOT/venv/bin/python" -m pytest -q >/dev/null

say "assemble"
"$ROOT/deploy/ha-addon/assemble.sh" >/dev/null

say "upload code"
scp -q -r "$ROOT/dist/ha-addon/." "$HOST:/addons/heatctl/"

# VERIFY IT LANDED. `scp` has failed mid-transfer here before, and a partial
# upload is indistinguishable from a good one until the App refuses to start.
say "verify upload"
want_sum=$(cd "$ROOT/dist/ha-addon" && find . -name '*.py' -type f -exec md5sum {} + | sort -k2 | md5sum | cut -d' ' -f1)
have_sum=$(ssh "$HOST" "cd /addons/heatctl && find . -name '*.py' -type f -exec md5sum {} + | sort -k2 | md5sum | cut -d' ' -f1")
if [ "$want_sum" != "$have_sum" ]; then
    echo "UPLOAD MISMATCH: local $want_sum != remote $have_sum" >&2
    echo "The App has NOT been rebuilt. Re-run." >&2
    exit 1
fi
echo "python sources match ($want_sum)"

# Config is NOT shipped by a deploy (run.sh seeds it once and never overwrites).
# Report drift so a code change that needs a config change cannot go unnoticed -
# which is exactly the pair that caused the outage above.
say "config drift"
"$ROOT/deploy/ha-addon/check-live-config.sh" "$HOST" || {
    echo
    echo "^^ Repo and running config differ. If this deploy's CODE requires a"
    echo "   config change, apply it BEFORE rebuilding, or the App starts with"
    echo "   new code against old config (or the reverse) - which is exactly"
    echo "   the 2026-07-31 17:03 outage." >&2
    # NOT an interactive prompt. A `read` here hung the very first real run of
    # this script for ten minutes with the new code on disk and the old image
    # still serving - a deploy tool that can block forever is worse than the
    # hand-chaining it replaced. Drift is REPORTED and the deploy proceeds;
    # set DEPLOY_STRICT=1 to make it fatal instead.
    if [ "${DEPLOY_STRICT:-0}" = "1" ]; then
        echo "DEPLOY_STRICT=1 - refusing to continue." >&2
        exit 1
    fi
    echo "   (continuing; set DEPLOY_STRICT=1 to make drift fatal)"
}

say "rebuild"
ssh "$HOST" 'curl -s -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/addons/'"$SLUG"'/rebuild' >/dev/null

say "wait for start"
for i in $(seq 1 60); do
    sleep 5
    state=$(ssh "$HOST" 'curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/addons/'"$SLUG"'/info' | tr ',' '\n' | grep '"state"' | head -1 || true)
    case "$state" in *started*) break;; esac
    [ "$i" = 60 ] && { echo "App did not reach 'started'" >&2; exit 1; }
done
# A rebuild can leave it stopped rather than started; start it explicitly.
ssh "$HOST" 'curl -s -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/addons/'"$SLUG"'/start' >/dev/null 2>&1 || true
sleep 15

say "verify it is actually running"
log=$(ssh "$HOST" 'curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/addons/'"$SLUG"'/logs' | tail -40)
if grep -qE 'Traceback|KeyError|ModuleNotFound' <<<"$log"; then
    echo "$log" | tail -20 >&2
    echo >&2
    echo "STARTED BUT CRASHING. The plant is running on the coupler watchdog." >&2
    exit 1
fi
grep -E 'cooling supply limit|control plane connected|modbus connected' <<<"$log" | tail -3
say "deployed OK"
