#!/usr/bin/env python3
"""Characterise one circuit's opening→flow curve using its return temperature.

WHY NOT THE ROTAMETERS. They top out at 2.5 l/min and every open circuit pins
them, so the useful part of the curve — where a circuit stops responding to
more command — is exactly the part they cannot see. Owner's idea, 2026-08-08:
**the fan coil on hk11 is its own flow meter.** With the fan on manual high the
air side is roughly constant, so the heat it removes is roughly fixed, and

    dT = Q / (m_dot * c)

makes the supply→return difference a monotonic proxy for flow with no ceiling.
Low flow, warm return. High flow, return approaches supply.

NOT A CALIBRATED FLOW. Q is not exactly constant — the coil's surface
temperature moves with water temperature, which moves with flow — so dT is
monotonic in flow but not proportional to 1/flow. That is enough for the two
questions worth answering: where does the circuit START responding, and where
does it STOP responding to more command.

Safety: this drives ONE circuit; the rest stay where they are, so total flow
stays high and there is no Er03 exposure. heatctl remains the only Modbus
master and safety still runs after every command — an override cannot hold a
circuit open into a supply below the dew point.

    tools/sweep_circuit.py hk11
    tools/sweep_circuit.py hk11 --steps 100,80,60,50,40,30,25,20,15 --settle 300

Leaves the circuit on `auto` when it finishes, including on Ctrl-C — a sweep
that dies half way must not leave a circuit pinned at 15 %.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

HOST = "192.168.178.230"
DEFAULT_STEPS = "100,80,70,60,50,40,35,30,25,20,15"


def _remote(script: str, timeout: int = 120) -> str:
    out = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
         f"root@{HOST}", script],
        capture_output=True, text=True, timeout=timeout)
    if out.returncode:
        sys.exit(f"remote failed: {out.stderr.strip()}")
    return out.stdout


def set_valve(circuit: str, value) -> None:
    creds = ('M=$(grep -h \'"domain": *"mqtt"\' /config/.storage/core.config_entries); '
             'U=$(echo "$M" | grep -o \'"username": *"[^"]*"\' | head -1 | cut -d\'"\' -f4); '
             'P=$(echo "$M" | grep -o \'"password": *"[^"]*"\' | head -1 | cut -d\'"\' -f4); ')
    _remote(creds + f'mosquitto_pub -h core-mosquitto -u "$U" -P "$P" '
                    f'-t "heatctl/set/valve/valve_{circuit}" -m "{value}"')


def sample(circuit: str, window_s: int) -> dict:
    """Mean supply and this circuit's return over the last `window_s`."""
    n = circuit.replace("hk", "").lstrip("0")
    creds = ('L=$(grep -h \'"domain": *"influxdb"\' /config/.storage/core.config_entries); '
             'U=$(echo "$L" | grep -o \'"username":"[^"]*"\' | cut -d\'"\' -f4); '
             'P=$(echo "$L" | grep -o \'"password":"[^"]*"\' | cut -d\'"\' -f4); ')
    q = (f'SELECT mean(value) FROM "°C" WHERE entity_id =~ '
         f'/^heatctl_(supply_total|return_circuit_{n})$/ '
         f'AND time > now() - {window_s}s GROUP BY entity_id')
    out = _remote(creds + f'curl -sG "http://a0d7b954-influxdb:8086/query" -u "$U:$P" '
                          f'--data-urlencode "db=homeassistant" '
                          f'--data-urlencode "q={q}"')
    res = {}
    for r in json.loads(out).get("results", []):
        for s in (r.get("series") or []):
            res[s["tags"]["entity_id"]] = s["values"][0][1]
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("circuit")
    ap.add_argument("--steps", default=DEFAULT_STEPS)
    ap.add_argument("--settle", type=int, default=300,
                    help="seconds per step; the actuator alone needs 150 s")
    a = ap.parse_args()
    steps = [int(x) for x in a.steps.split(",")]
    n = a.circuit.replace("hk", "").lstrip("0")

    print(f"sweeping {a.circuit}: {steps}")
    print(f"{a.settle} s per step -> {len(steps)*a.settle/60:.0f} min total\n")
    print(f"{'open %':>7}{'supply':>9}{'return':>9}{'dT':>8}   flow proxy")
    print("-" * 52)
    rows = []
    try:
        for pct in steps:
            set_valve(a.circuit, pct)
            time.sleep(a.settle)
            s = sample(a.circuit, 120)
            vl = s.get("heatctl_supply_total")
            rl = s.get(f"heatctl_return_circuit_{n}")
            if vl is None or rl is None:
                print(f"{pct:7d}   no data"); continue
            dt = rl - vl
            rows.append((pct, vl, rl, dt))
            # Bigger dT = less flow. Shown relative to the smallest dT seen so
            # far, which is the highest-flow point, so the column reads as
            # "fraction of best flow" without pretending to be l/min.
            best = min(r[3] for r in rows if r[3] > 0.05) if any(
                r[3] > 0.05 for r in rows) else None
            proxy = f"{best/dt:5.2f}" if best and dt > 0.05 else "  -  "
            print(f"{pct:7d}{vl:9.2f}{rl:9.2f}{dt:8.2f}   {proxy}")
    finally:
        set_valve(a.circuit, "auto")
        print(f"\n{a.circuit} handed back to control (auto).")


if __name__ == "__main__":
    main()
