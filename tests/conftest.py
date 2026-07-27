"""Shared fixtures and fakes.

Tests use a small SYNTHETIC config, not the real `config.yaml`. Two reasons:
the real file is site truth and changes whenever wiring changes, so binding
tests to it would make every rewiring look like a test failure; and a test
should state the topology it depends on. `test_config.py` separately checks
that the real file is loadable and internally consistent - that is a different
question from whether the control logic is correct.
"""
from __future__ import annotations

import copy

import pytest

from heatctl.backends.base import IOBackend, IOState

# Two rooms, deliberately different shapes:
#   gaestebad  - one circuit, HAS a room temperature source
#   wohnzimmer - two circuits sharing one room PID, no room sensor
# That covers the room-PID path, the per-circuit fallback path, and the
# "one room output applied to several circuits" rule in one config.
BASE_CFG: dict = {
    "io": {
        "backend": "modbus_direct",
        "modbus": {
            "host": "192.0.2.52", "port": 502, "timeout_s": 0.05,
            "reconnect_delay_s": 1.0, "reconnect_delay_max_s": 30.0,
            "watchdog_enabled": True, "watchdog_timeout_s": 10.0,
            "watchdog_mask": 0x8020,
        },
    },
    "mqtt": {
        "host": "192.0.2.230", "port": 1883, "username": "", "password": "",
        "base_topic": "heatctl", "ha_discovery": False,
    },
    "sensors": {
        "base_register": 12,
        "channels": [
            {"index": 1, "name": "rl_hk01"},
            {"index": 2, "name": "rl_hk02"},
            {"index": 3, "name": "rl_hk03"},
            {"index": 14, "name": "rl_total"},
            {"index": 15, "name": "vl_total"},
            {"index": 16, "name": "spare", "enabled": False},
        ],
    },
    "valves": {
        "base_register": 12,
        "channels": [
            {"index": 1, "name": "valve_hk01"},
            {"index": 2, "name": "valve_hk02"},
            {"index": 3, "name": "valve_hk03"},
        ],
    },
    "rooms": [
        {"name": "gaestebad", "room_temp_topic": "roomtemp/gaestebad",
         "circuits": [{"sensor": "rl_hk01", "valve": "valve_hk01"}]},
        {"name": "wohnzimmer",
         "circuits": [{"sensor": "rl_hk02", "valve": "valve_hk02"},
                      {"sensor": "rl_hk03", "valve": "valve_hk03"}]},
    ],
    "control": {
        "mode": "heating",
        "loop_interval_s": 1.0,
        "default_setpoint_heating_c": 21.0,
        "default_setpoint_cooling_c": 23.0,
        "return_temp_setpoint_heating_c": 22.0,
        "return_temp_setpoint_cooling_c": 20.0,
        "return_setpoint_source": "fixed",
        "system_return_sensor": "rl_total",
        "system_return_bias_c": 0.0,
        "pid_room": {"kp": 25.0, "ki": 0.005, "kd": 0.0,
                     "out_min": 0.0, "out_max": 100.0},
        "pid_return": {"kp": 8.0, "ki": 0.02, "kd": 0.0,
                       "out_min": 0.0, "out_max": 100.0},
    },
    "safety": {
        "setpoint_min_c": 15.0,
        "setpoint_max_c": 28.0,
        "vl_max_heating_c": 45.0,
        "vl_min_cooling_c": 16.0,
        "dew_point_margin_c": 2.0,
        "dew_point_max_age_s": 900,
        "vl_min_cooling_floor_c": 12.0,
        "frost_protect_c": 6.0,
        "sensor_fault_raw": [0x05DC, 0xFED4],
        "stale_data_timeout_s": 15,
        "failsafe_valve_pct": 100,
    },
    "logging": {"level": "info", "state_db": "", "log_every_n_cycles": 60},
}


@pytest.fixture
def cfg(tmp_path):
    """A fresh deep copy per test, with the state DB pointed at tmp_path."""
    c = copy.deepcopy(BASE_CFG)
    c["logging"]["state_db"] = str(tmp_path / "state.sqlite")
    return c


class FakeBackend(IOBackend):
    """In-memory IOBackend. Records writes, can be told to fail."""

    def __init__(self, temps: dict[str, float] | None = None,
                 faults: set[str] | None = None):
        self.state = IOState()
        self.state.temps = dict(temps or {})
        self.state.faults = set(faults or ())
        self.state.last_read_ts = 1.0
        self.writes: list[tuple[str, float]] = []
        self.all_valve_writes: list[float] = []
        self.started = False
        self.stopped = False
        self.fail_writes = False

    def touch(self, now: float) -> None:
        """Mark the state as read at `now` (monotonic), for staleness tests."""
        self.state.last_read_ts = now

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def read_state(self) -> IOState:
        return self.state

    async def write_valve(self, name: str, pct: float) -> None:
        if self.fail_writes:
            raise IOError(f"fake write failure for {name}")
        self.writes.append((name, pct))
        self.state.valves_pct[name] = pct

    async def write_all_valves(self, pct: float) -> None:
        self.all_valve_writes.append(pct)
        for ch in ("valve_hk01", "valve_hk02", "valve_hk03"):
            self.state.valves_pct[ch] = pct

    # -- convenience for assertions --
    @property
    def last_write(self) -> dict[str, float]:
        """Last commanded position per valve."""
        out: dict[str, float] = {}
        for name, pct in self.writes:
            out[name] = pct
        return out


class FakePlane:
    """Stands in for ControlPlane: records publishes, serves room temps.

    The real one is failure-tolerant by design, so the controller must work
    against a plane that never connects - which is exactly what this is.
    """

    def __init__(self, room_temps: dict[str, float] | None = None,
                 dew_point: float | None = None):
        self.room_temps = dict(room_temps or {})
        self.dew = dew_point
        self.published: list[tuple[str, str, bool]] = []

    def room_temp(self, room: str, max_age_s: float = 300) -> float | None:
        return self.room_temps.get(room)

    def dew_point(self, max_age_s: float = 900) -> float | None:
        return self.dew

    async def publish(self, suffix: str, payload, retain: bool = False) -> None:
        self.published.append((suffix, str(payload), retain))

    async def run(self) -> None:  # pragma: no cover - never started in tests
        pass

    async def stop(self) -> None:  # pragma: no cover
        pass

    def topic(self, suffix: str) -> str | None:
        """Most recent payload published on `suffix`, or None."""
        for s, payload, _ in reversed(self.published):
            if s == suffix:
                return payload
        return None


@pytest.fixture
def controller(cfg):
    """A Controller wired to fakes, with no hardware and no broker.

    The backend is swapped after construction rather than injected: keeping
    `make_backend(cfg)` as the single construction path means the production
    wiring stays exercised and there is no test-only branch in main.py.
    """
    from heatctl.main import Controller

    def _make(temps=None, faults=None, room_temps=None, dew_point=None,
              **overrides):
        c = copy.deepcopy(cfg)
        for section, values in overrides.items():
            c[section].update(values)
        ctl = Controller(c)
        ctl.io = FakeBackend(temps, faults)
        ctl.plane = FakePlane(room_temps, dew_point)
        return ctl

    return _make
