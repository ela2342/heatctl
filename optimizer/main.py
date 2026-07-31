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
from .params import load_params
from .model import eigen_time_constants_h

log = logging.getLogger("optimizer")

DEFAULT_PARAMS = os.path.join(os.path.dirname(__file__), "params.yaml")


def load(config_path: str, params_path: str) -> tuple[dict, dict]:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    params = load_params(params_path)
    # Credentials come from the environment, never the file - same rule as
    # layer 1, and the same reason: config.yaml is in the repository.
    # Same environment overrides layer 1 honours, and for the same reason:
    # config.yaml ships placeholder addresses, and credentials must not be
    # committed. Missing HOST/PORT here was a real bug - the optimizer sat in a
    # reconnect loop against the placeholder while layer 1 talked to the
    # Supervisor's broker perfectly happily two processes away.
    m = cfg.setdefault("mqtt", {})
    for key, env in (("host", "HEATCTL_MQTT_HOST"),
                     ("port", "HEATCTL_MQTT_PORT"),
                     ("username", "HEATCTL_MQTT_USERNAME"),
                     ("password", "HEATCTL_MQTT_PASSWORD")):
        if os.environ.get(env):
            m[key] = os.environ[env]
    m["port"] = int(m.get("port") or 1883)
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
    slow, fast = eigen_time_constants_h(est.bp)
    # The COUPLED modes, not the per-node figures this used to print. The fast
    # one is the pre-conditioning lead time and is worth seeing at every start.
    log.info("model modes: slow %.1f h, fast %.2f h (pre-conditioning lead time)",
             slow, fast)
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
