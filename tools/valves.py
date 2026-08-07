#!/usr/bin/env python3
"""Position circuit valves by hand, for commissioning and flow measurement.

Sends `heatctl/set/valve/<name>` and lets heatctl do the writing. It is NOT a
second Modbus master: heatctl stays the only thing talking to the coupler, so
the coupler's own watchdog keeps being fed by the normal 1 Hz write and safety
still runs after every command.

That last point is the reason this exists rather than a direct-to-Modbus
script. Stopping heatctl to drive the outputs yourself does not give you an
idle plant - the watchdog zeroes the outputs ~10 s later and the NC actuators
CLOSE, which is the opposite of what a flow measurement wants. And nothing
would be watching the dew point while you worked.

    tools/valves.py open                 all owned circuits to 100 %
    tools/valves.py close                all to 0 %
    tools/valves.py auto                 hand every circuit back to control
    tools/valves.py set hk03 45          one circuit to 45 %
    tools/valves.py set hk03 auto        hand one circuit back
    tools/valves.py only hk03            hk03 open, every other circuit shut
    tools/valves.py show                 what heatctl is commanding now

`only` is the per-circuit flow measurement: one circuit open against a known
pump speed, the rest shut. Mind the minimum-flow requirement - the unit trips
Er03 below it - so do not leave a single small circuit open with the compressor
running.

Overrides live in heatctl's memory and are cleared by a restart, deliberately.
There is no persistent "manual mode" to forget about.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

HOST = "192.168.178.230"          # HA host; the broker and heatctl both run here
BASE = "heatctl"
CIRCUITS = ["hk01", "hk02", "hk03", "hk04", "hk06",
            "hk07", "hk08", "hk09", "hk10", "hk11"]


def _remote(script: str) -> str:
    """Run a snippet on the HA host, where the broker credentials live.

    The credentials stay on that machine and never reach a transcript or this
    file - the same rule the InfluxDB queries follow.
    """
    creds = (
        'M=$(grep -h \'"domain": *"mqtt"\' /config/.storage/core.config_entries); '
        'U=$(echo "$M" | grep -o \'"username": *"[^"]*"\' | head -1 | cut -d\'"\' -f4); '
        'P=$(echo "$M" | grep -o \'"password": *"[^"]*"\' | head -1 | cut -d\'"\' -f4); '
    )
    out = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
         f"root@{HOST}", creds + script],
        capture_output=True, text=True, timeout=120)
    if out.returncode:
        sys.exit(f"remote command failed: {out.stderr.strip()}")
    return out.stdout


def send(name: str, value: str) -> None:
    _remote(f'mosquitto_pub -h core-mosquitto -u "$U" -P "$P" '
            f'-t "{BASE}/set/valve/{name}" -m "{value}"')


def show() -> None:
    out = _remote(
        'timeout 20 mosquitto_sub -h core-mosquitto -u "$U" -P "$P" '
        f'-t "{BASE}/valve/+" -t "{BASE}/valve_override" '
        f'-t "{BASE}/demand/open_pct" -v -W 15 2>/dev/null | sort -u')
    print(out.strip() or "(nothing published in the window)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("open");  sub.add_parser("close")
    sub.add_parser("auto");  sub.add_parser("show")
    p_set = sub.add_parser("set"); p_set.add_argument("circuit"); p_set.add_argument("value")
    p_only = sub.add_parser("only"); p_only.add_argument("circuit")
    a = ap.parse_args()

    def full(c: str) -> str:
        c = c if c.startswith("valve_") else f"valve_{c}"
        if c.replace("valve_", "") not in CIRCUITS:
            sys.exit(f"unknown circuit {c!r}; known: {' '.join(CIRCUITS)}")
        return c

    if a.cmd == "show":
        show(); return
    if a.cmd in ("open", "close", "auto"):
        v = {"open": "100", "close": "0", "auto": "auto"}[a.cmd]
        for c in CIRCUITS:
            send(f"valve_{c}", v)
        print(f"{a.cmd}: sent to {len(CIRCUITS)} circuits")
    elif a.cmd == "set":
        send(full(a.circuit), a.value)
        print(f"{a.circuit} -> {a.value}")
    elif a.cmd == "only":
        keep = full(a.circuit)
        for c in CIRCUITS:
            send(f"valve_{c}", "100" if f"valve_{c}" == keep else "0")
        print(f"only {a.circuit} open; {len(CIRCUITS)-1} circuits shut")
    print("safety still applies - a circuit can still be forced shut on frost "
          "or a supply below the dew point.")


if __name__ == "__main__":
    main()
