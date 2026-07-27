"""PW58321 client.

Weighted towards the things that damage hardware or silently corrupt data:
flash-wearing writes, the device's silent truncation of over-long reads, and
per-register scaling that yields plausible-looking wrong numbers.
"""
from __future__ import annotations

import asyncio

import pytest

from heatctl import heatpump_map as hm
from heatctl.heatpump import HeatPump


class Resp:
    def __init__(self, registers=None, error=False):
        self.registers = registers or []
        self._e = error

    def isError(self):
        return self._e


class FakePump:
    """Models the device behaviours that bite: truncation and write costs."""

    def __init__(self, regs=None, truncate_at=hm.MAX_READ):
        self.connected = True
        self.regs = regs if regs is not None else {}
        self.truncate_at = truncate_at
        self.writes: list[tuple[int, int]] = []
        self.reads: list[tuple[int, int]] = []

    async def connect(self):
        return True

    def close(self):
        self.connected = False

    async def read_holding_registers(self, addr, count=1, device_id=1):
        self.reads.append((addr, count))
        n = min(count, self.truncate_at)          # SILENT truncation
        return Resp([self.regs.get(addr + i, 0) for i in range(n)])

    async def write_register(self, addr, value, device_id=1):
        self.writes.append((addr, value))
        self.regs[addr] = value
        return Resp()


class FakePlane:
    base = "heatctl"

    def __init__(self):
        self.published: list[tuple[str, str]] = []
        self.discovered: list[tuple[str, str]] = []

    async def publish(self, suffix, payload, retain=False):
        self.published.append((suffix, str(payload)))

    async def discover(self, component, uid, conf):
        self.discovered.append((component, uid))

    def topic(self, suffix):
        for s, p in reversed(self.published):
            if s == suffix:
                return p
        return None


@pytest.fixture
def hp(cfg):
    def _make(regs=None, **over):
        cfg["heatpump"] = {"enabled": True, "host": "192.0.2.37", "port": 4196,
                           "unit": 1, "allow_writes": True,
                           "write_budget_per_hour": 30, **over}
        plane = FakePlane()
        h = HeatPump(cfg, plane)
        h.client = FakePump(regs)
        return h, h.client, plane
    return _make


# ---------- decoding ----------

def test_temperatures_are_signed():
    """The economizer registers read 65440/65436 on this unit - sentinels for
    sensors that are not fitted. Home Assistant's config decodes them unsigned
    and displays +32720 °C. Ours must not."""
    reg = next(r for r in hm.STATUS if r.name == "economizer_inlet")
    assert hm.decode(reg, 65440) == -48.0
    assert hm.decode(reg, 65436) == -50.0


def test_scaling_is_per_register_not_uniform():
    """Return water is 0.1 and leaving water is 0.5, four registers apart.
    A uniform factor gives a plausible number, which is the worst kind of
    wrong. Values cross-checked against the live device 2026-07-27."""
    ret = next(r for r in hm.STATUS if r.name == "return_water")
    leave = next(r for r in hm.STATUS if r.name == "leaving_water")
    assert hm.decode(ret, 203) == 20.3
    assert hm.decode(leave, 40) == 20.0


def test_encode_round_trips():
    reg = next(r for r in hm.WRITABLE if r.name == "setpoint_cooling")
    assert hm.encode(reg, 19) == 19
    assert hm.decode(reg, hm.encode(reg, 19)) == 19


def test_mode_names_match_the_manual():
    assert hm.MODES[2] == "cooling"
    assert hm.MODE_BY_NAME["heating"] == 1


def test_register_0_bit_0_is_named_power_not_pump():
    """The correction this whole exercise turned on."""
    assert hm.CONTROL_BITS[(0x0000, 0)] == "power"
    assert hm.CONTROL_BITS[(0x0000, 4)] == "pump_non_stop"
    assert hm.OUTPUT_BITS[(0x8006, 0)] == "water_pump"


# ---------- reads ----------

async def test_a_short_read_is_discarded_not_used(hp):
    """The device returns 120 registers for a 121-register request and no
    error. Using the reply would misalign every field after the cut while the
    values still look plausible, so it must be refused outright."""
    h, c, _ = hp()
    c.truncate_at = 10
    assert await h._read_span(0x8000, 0x802A) is None


async def test_a_long_span_is_split_into_legal_chunks(hp):
    h, c, _ = hp()
    out = await h._read_span(hm.RW_FIRST, hm.RW_LAST)     # 269 registers
    assert out is not None and len(out) == 269
    assert all(n <= hm.MAX_READ for _, n in c.reads), c.reads
    assert len(c.reads) == 3


async def test_every_transaction_is_spaced(hp, monkeypatch):
    """Reads and writes share the device's 200 ms budget."""
    h, c, _ = hp()
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)
    monkeypatch.setattr("heatctl.heatpump.asyncio.sleep", fake_sleep)

    await h._read_span(0x8000, 0x802A)
    await h._read_span(0x8000, 0x802A)
    assert any(s > 0 for s in slept), "no inter-transaction gap enforced"


# ---------- writes: the flash-wear rules ----------

async def test_a_write_that_changes_nothing_never_reaches_the_bus(hp):
    """Every write flashes the memory chip, so a no-op is not free - it is the
    single easiest way to destroy this controller with a reconcile loop."""
    h, c, _ = hp()
    h.config[0x0090] = 19
    assert await h.write_register(0x0090, 19, "test") is False
    assert c.writes == []


async def test_a_real_change_is_written(hp):
    h, c, _ = hp()
    h.config[0x0090] = 19
    assert await h.write_register(0x0090, 20, "test") is True
    assert c.writes == [(0x0090, 20)]


async def test_writes_are_refused_when_disabled(hp):
    h, c, _ = hp(allow_writes=False)
    h.config[0x0090] = 19
    assert await h.write_register(0x0090, 25, "test") is False
    assert c.writes == []


async def test_the_flash_budget_stops_a_runaway_loop(hp, caplog):
    """If something starts oscillating, the budget must fail loudly rather
    than quietly grinding the flash away."""
    h, c, _ = hp(write_budget_per_hour=5)
    for i in range(20):
        h.config[0x0090] = 0          # force every write to be a real change
        await h.write_register(0x0090, 19, "runaway")
    assert len(c.writes) == 5
    assert any("flash-wear budget" in r.getMessage() for r in caplog.records)


async def test_named_writes_validate_the_documented_range(hp):
    """P04 chilling is documented 7-30 °C."""
    h, c, _ = hp()
    h.config[0x0090] = 19
    assert await h.write_named("setpoint_cooling", 45, "test") is False
    assert await h.write_named("setpoint_cooling", 3, "test") is False
    assert c.writes == []
    assert await h.write_named("setpoint_cooling", 22, "test") is True


async def test_an_unknown_register_name_is_refused(hp):
    h, c, _ = hp()
    assert await h.write_named("nonsense", 1, "test") is False
    assert c.writes == []


async def test_mode_is_written_by_name(hp):
    h, c, _ = hp()
    h.config[0x0004] = 1
    assert await h.set_mode("cooling", "test") is True
    assert c.writes == [(0x0004, 2)]


async def test_an_unknown_mode_is_refused(hp):
    h, c, _ = hp()
    h.config[0x0004] = 1
    assert await h.set_mode("banana", "test") is False
    assert c.writes == []


# ---------- power: read-modify-write on a register we do not own ----------

async def test_power_refuses_to_guess_the_other_bits(hp, caplog):
    """0x0000 carries six other documented settings. Writing it without a
    current read would invent them - which is exactly the race that made the
    HA automation dangerous."""
    h, c, _ = hp()
    assert h.config.get(0x0000) is None
    assert await h.set_power(True, "test") is False
    assert c.writes == []
    assert any("never read it" in r.getMessage() for r in caplog.records)


async def test_power_preserves_the_other_bits(hp):
    h, c, _ = hp()
    h.config[0x0000] = 0b01000001          # 65: power on + bit6, as measured
    assert await h.set_power(False, "test") is True
    assert c.writes == [(0x0000, 0b01000000)]


async def test_power_on_sets_only_bit_zero(hp):
    h, c, _ = hp()
    h.config[0x0000] = 0b01000000
    assert await h.set_power(True, "test") is True
    assert c.writes == [(0x0000, 0b01000001)]


# ---------- publishing ----------

async def test_every_register_is_published_raw(hp):
    """'Everything accessible over MQTT' - not just the curated subset."""
    h, c, plane = hp({0x8000 + i: i for i in range(43)})
    regs = await h._read_span(hm.RO_FIRST, hm.RO_LAST)
    await h._publish_block(regs)
    assert plane.topic("hp/raw/0x8012") == "18"
    assert len([s for s, _ in plane.published if s.startswith("hp/raw/")]) == 43


async def test_faults_are_decoded_and_summarised(hp):
    h, _, plane = hp()
    h.status = {0x8008: 0b0000_0001}          # Er03 water flow
    await h._publish_decoded()
    assert plane.topic("hp/fault/er03_water_flow") == "1"
    assert plane.topic("hp/fault_any") == "1"
    assert plane.topic("hp/faults") == "er03_water_flow"


async def test_no_faults_reports_cleanly(hp):
    h, _, plane = hp()
    h.status = {a: 0 for a in hm.FAULT_REGS}
    await h._publish_decoded()
    assert plane.topic("hp/fault_any") == "0"
    assert plane.topic("hp/faults") == "none"


async def test_the_commanded_mode_is_published_by_name(hp):
    h, _, plane = hp()
    h.config = {0x0004: 2}
    await h._publish_decoded()
    assert plane.topic("hp/mode_name") == "cooling"


# ---------- config drift ----------

def test_the_first_read_is_not_reported_as_drift(hp):
    """Otherwise every restart would claim someone touched the panel."""
    h, _, _ = hp()
    assert h._diff_config({0x0090: 19}) == []


def test_a_changed_setting_is_detected(hp):
    """Settings can be changed at the unit's own control panel."""
    h, _, _ = hp()
    h.config = {0x0090: 19, 0x0091: 25}
    h._config_seen = True
    assert h._diff_config({0x0090: 22, 0x0091: 25}) == [(0x0090, 19, 22)]


# ---------- disabled ----------

async def test_a_disabled_client_does_nothing(cfg):
    cfg["heatpump"] = {"enabled": False}
    h = HeatPump(cfg, FakePlane())
    await asyncio.wait_for(h.run(), timeout=1.0)   # returns immediately
