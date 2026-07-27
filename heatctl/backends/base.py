"""I/O backend abstraction.

The control core never talks to hardware directly. It sees exactly this
interface, so the transport (direct Modbus TCP vs. an MQTT bridge such as
modbus2mqtt) is swappable via config without touching control logic.

Contract:
  - read_state() returns an IOState with temperatures in degC and a set of
    failed sensors. It must raise or mark staleness honestly - never serve
    silently outdated values.
  - write_valve(name, pct) accepts 0..100 and is fire-and-forget from the
    caller's perspective, but must raise on definite failure so the caller
    can trigger failsafe handling.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class IOState:
    """Last known input state. temps in degC, valves_pct is the last setpoint.

    Note the asymmetry between the two valve fields, it is the point of
    having both: `valves_pct` is what heatctl last *commanded*, while
    `valves_readback_pct` is what the coupler says its outputs are actually
    at. They diverge when something other than heatctl moved the outputs -
    the Modbus watchdog forcing its safe state being the case that matters.
    A backend that cannot read its outputs back simply leaves these empty.
    """
    temps: dict[str, float] = field(default_factory=dict)
    temps_raw: dict[str, int] = field(default_factory=dict)
    faults: set[str] = field(default_factory=set)
    valves_pct: dict[str, float] = field(default_factory=dict)
    valves_readback_pct: dict[str, float] = field(default_factory=dict)
    valve_mismatch: set[str] = field(default_factory=set)
    last_read_ts: float = 0.0

    def is_stale(self, timeout_s: float) -> bool:
        return (time.monotonic() - self.last_read_ts) > timeout_s


def decode_pt1000(raw: int) -> float:
    """750-463 process value: degC * 10, two's complement."""
    if raw > 0x7FFF:
        raw -= 0x10000
    return raw / 10.0


class IOBackend(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def read_state(self) -> IOState: ...

    @abstractmethod
    async def write_valve(self, name: str, pct: float) -> None: ...

    @abstractmethod
    async def write_all_valves(self, pct: float,
                               names: list[str] | None = None) -> None:
        """Failsafe write. `names` limits it to the channels the caller owns;
        None means every declared channel."""
        ...


def make_backend(cfg: dict) -> IOBackend:
    kind = cfg["io"]["backend"]
    if kind == "modbus_direct":
        from .modbus_direct import ModbusDirectBackend
        return ModbusDirectBackend(cfg)
    if kind == "mqtt":
        from .mqtt_io import MqttIOBackend
        return MqttIOBackend(cfg)
    raise ValueError(f"unknown io backend: {kind}")
