"""Layer 2 entry point.

    venv/bin/python -m optimizer.main ./config.yaml [./optimizer/params.yaml]

Runs as its OWN process, separate from `heatctl.main`. That separation is the
architecture, not a packaging convenience: layer 2 is allowed to fail
(CLAUDE.md), and "allowed to fail" only means anything if its failure cannot
take the control core down with it. Crash this and the house stays warm.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import yaml

from .estimator import Estimator

log = logging.getLogger("optimizer")

DEFAULT_PARAMS = os.path.join(os.path.dirname(__file__), "params.yaml")


def load(config_path: str, params_path: str) -> tuple[dict, dict]:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    with open(params_path) as f:
        params = yaml.safe_load(f)
    # Credentials come from the environment, never the file - same rule as
    # layer 1, and the same reason: config.yaml is in the repository.
    m = cfg.setdefault("mqtt", {})
    m["username"] = os.environ.get("HEATCTL_MQTT_USERNAME", m.get("username"))
    m["password"] = os.environ.get("HEATCTL_MQTT_PASSWORD", m.get("password"))
    # Coordinates are site-identifying and stay out of both files.
    w = params.setdefault("weather", {})
    for key, env in (("latitude", "HEATCTL_LATITUDE"),
                     ("longitude", "HEATCTL_LONGITUDE")):
        if os.environ.get(env):
            w[key] = float(os.environ[env])
    return cfg, params


async def amain(config_path: str, params_path: str) -> None:
    cfg, params = load(config_path, params_path)
    est = Estimator(cfg, params)
    ta, ts = est.bp.time_constants_h()
    log.info("model time constants: air %.1f h, slab %.1f h", ta, ts)
    if est.weather is None:
        log.warning("no coordinates configured - running without forecast; "
                    "set HEATCTL_LATITUDE / HEATCTL_LONGITUDE")
    await est.run()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    cfg = sys.argv[1] if len(sys.argv) > 1 else "/etc/heatctl/config.yaml"
    params = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PARAMS
    try:
        asyncio.run(amain(cfg, params))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
