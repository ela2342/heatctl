"""modbus_direct: availability rules, reconnect/backoff, watchdog recovery.

Everything here runs against a fake pymodbus client - no coupler needed. The
module's docstring calls three properties load-bearing (start() never raises,
read_state() never raises and stays honest about staleness, reconnection is
rate-limited and bounded); those are exactly what a future "cleanup" would
strip out, so they are tested as behaviour rather than left as comments.
"""
from __future__ import annotations

import asyncio

import pytest

from heatctl.backends import modbus_direct as md
from heatctl.backends.modbus_direct import (
    WD_MASK_1_16, WD_STATUS, WD_STATUS_ACTIVE, WD_STATUS_EXPIRED,
    WD_STATUS_INACTIVE, WD_TIME, WD_TRIGGER, ModbusDirectBackend,
)


class Response:
    def __init__(self, registers=None, error=False, exception_code=0):
        self.registers = registers or []
        self._error = error
        self.exception_code = exception_code

    def isError(self):
        return self._error

    def __repr__(self):
        return f"<Response error={self._error} code={self.exception_code}>"


class FakeCoupler:
    """Models the bits of the WAGO 750-352 that heatctl actually depends on.

    Two behaviours are modelled from observed hardware, not from the manual:
      * while the watchdog is EXPIRED, all process data (FC4/FC6) is refused
        with exception 0x04, but the 0x1000 register block stays readable -
        this is what makes recovery possible at all;
      * 0x1003 is a TOGGLE: writing the value it already holds is refused with
        exception 0x03 and clears nothing.
    """

    def __init__(self, temps=None, wd_status=WD_STATUS_INACTIVE):
        self.connected = True
        self.temps = temps if temps is not None else list(range(200, 216))
        self.regs = {WD_TIME: 100, WD_MASK_1_16: 0, WD_TRIGGER: 0,
                     WD_STATUS: wd_status}
        self.outputs: dict[int, int] = {}
        self.connect_calls = 0
        self.reads = 0

    # -- transport --
    async def connect(self):
        self.connect_calls += 1
        return self.connected

    def close(self):
        self.connected = False

    @property
    def _blocked(self):
        return self.regs[WD_STATUS] == WD_STATUS_EXPIRED

    # -- process data --
    async def read_input_registers(self, addr, count=1):
        self.reads += 1
        if self._blocked:
            return Response(error=True, exception_code=4)
        return Response(self.temps[:count])

    async def write_register(self, addr, value):
        if addr in (WD_TIME, WD_MASK_1_16, WD_TRIGGER, WD_STATUS):
            return self._write_watchdog(addr, value)
        if self._blocked:
            return Response(error=True, exception_code=4)
        self.outputs[addr] = value
        return Response()

    async def read_holding_registers(self, addr, count=1):
        if addr in self.regs:
            return Response([self.regs[addr]])
        return Response(error=True, exception_code=2)

    # -- watchdog --
    def _write_watchdog(self, addr, value):
        if addr == WD_TRIGGER:
            # Toggle register: same value = illegal data value, no effect.
            if value == self.regs[WD_TRIGGER]:
                return Response(error=True, exception_code=3)
            self.regs[WD_TRIGGER] = value
            self.regs[WD_STATUS] = WD_STATUS_ACTIVE     # clears a trip
            return Response()
        if addr == WD_MASK_1_16:
            self.regs[addr] = value
            if value:
                self.regs[WD_STATUS] = WD_STATUS_ACTIVE  # non-zero mask arms
            return Response()
        self.regs[addr] = value
        return Response()

    def expire(self):
        self.regs[WD_STATUS] = WD_STATUS_EXPIRED


@pytest.fixture
def backend(cfg, monkeypatch):
    """A backend with its client replaced by a FakeCoupler."""
    def _make(coupler=None, **modbus_overrides):
        cfg["io"]["modbus"].update(modbus_overrides)
        b = ModbusDirectBackend(cfg)
        c = coupler if coupler is not None else FakeCoupler()
        b.client = c
        b._ever_connected = True
        return b, c
    monkeypatch.delenv("HEATCTL_MODBUS_HOST", raising=False)
    monkeypatch.delenv("HEATCTL_MODBUS_PORT", raising=False)
    return _make


# ---------- REGRESSION: the 2026-07-27 outage ----------

async def test_watchdog_trigger_is_toggled_not_set_to_a_constant(backend):
    """Real defect: a constant write recovered exactly ONE trip, ever.

    0x1003 clears a trip on a CHANGE of value; re-writing the value it already
    holds is refused with exception 0x03. The original code always wrote 1, so
    it recovered the first trip (register still at its power-on 0) and no
    subsequent one. In the field that meant the coupler blocked all process
    data for ~3.5 h while heatctl looped on the stale-data failsafe.
    """
    b, c = backend()
    c.regs[WD_TRIGGER] = 1          # the state that used to be unrecoverable
    c.expire()

    await b.read_state()

    assert c.regs[WD_STATUS] != WD_STATUS_EXPIRED, "trip was not cleared"
    assert c.regs[WD_TRIGGER] == 0, "trigger must be toggled to the other value"


async def test_watchdog_recovery_survives_repeated_trips(backend):
    """One recovery proves nothing here - the first trip always worked.

    This is the shape of test that would have caught the bug: trip it twice so
    the trigger register starts each recovery from a different value.
    """
    b, c = backend()
    seen = []
    for _ in range(4):
        c.expire()
        await b.read_state()
        assert c.regs[WD_STATUS] != WD_STATUS_EXPIRED
        seen.append(c.regs[WD_TRIGGER])
    assert set(seen) == {0, 1}, f"trigger never alternated: {seen}"


async def test_watchdog_recovery_tries_both_values_if_the_read_fails(backend):
    """Without a readable current value, one of the two writes must land."""
    b, c = backend()
    c.regs[WD_TRIGGER] = 1
    c.expire()

    async def no_reads(addr, count=1):
        return Response(error=True, exception_code=4)
    c.read_holding_registers = no_reads

    await b._watchdog_kick_after_error()
    assert c.regs[WD_STATUS] != WD_STATUS_EXPIRED


async def test_expired_watchdog_surfaces_as_stale_not_as_a_crash(backend):
    """A trip must be distinguishable from a bug.

    read_state() returns the previous state WITHOUT refreshing last_read_ts,
    so the controller takes the `stale_data` path rather than `cycle_error`.
    """
    b, c = backend()
    await b.read_state()                     # one good read to seed the state
    before = b.state.last_read_ts
    assert before > 0

    c.expire()
    state = await b.read_state()             # must not raise

    assert state.last_read_ts == before, "staleness was masked by a failed read"
    assert state.is_stale(0.0)


async def test_watchdog_is_armed_when_inactive(backend):
    b, c = backend()
    assert c.regs[WD_STATUS] == WD_STATUS_INACTIVE
    await b.read_state()
    assert c.regs[WD_STATUS] == WD_STATUS_ACTIVE
    assert c.regs[WD_MASK_1_16] == 0x8020     # FC6 + FC16 only
    assert c.regs[WD_TIME] == 100             # 10.0 s in units of 100 ms


async def test_watchdog_is_not_touched_when_disabled(backend):
    b, c = backend(watchdog_enabled=False)
    await b.read_state()
    assert c.regs[WD_STATUS] == WD_STATUS_INACTIVE
    assert c.regs[WD_MASK_1_16] == 0


# ---------- REGRESSION (b), mandated by PLAN.md: reconnect / backoff ----------

async def test_start_never_raises_when_the_coupler_is_unreachable(cfg):
    """A dead coupler must not prevent the controller from starting.

    Frost protection has to run and the stale-data failsafe is the correct
    behaviour meanwhile; refusing to start would leave the house with no
    controller at all after a transient.
    """
    class Dead:
        connected = False
        def __init__(self, *a, **kw): pass
        async def connect(self): return False
        def close(self): pass

    b = ModbusDirectBackend(cfg)
    b.client = Dead()
    await b._ensure_connected()               # must not raise

    state = await b.read_state()              # must not raise either
    assert state.is_stale(0.0)


async def test_connect_failure_is_swallowed_not_propagated(backend):
    b, c = backend()
    c.connected = False

    async def boom():
        raise OSError("no route to host")
    c.connect = boom

    assert await b._ensure_connected() is False   # must not raise


async def test_backoff_grows_and_is_capped(backend):
    b, c = backend(reconnect_delay_s=1.0, reconnect_delay_max_s=8.0)
    c.connected = False

    async def fail():
        return False
    c.connect = fail

    seen = []
    for _ in range(8):
        b._next_attempt = 0.0                 # allow an immediate retry
        await b._ensure_connected()
        seen.append(b._backoff)

    assert seen[0] < seen[1] < seen[2], f"backoff did not grow: {seen}"
    assert max(seen) <= 8.0, f"backoff exceeded the cap: {seen}"


async def test_backoff_rate_limits_attempts_within_the_control_loop(backend):
    """The 1 s loop must not attempt a reconnect on every single cycle."""
    b, c = backend()
    c.connected = False
    attempts = 0

    async def fail():
        nonlocal attempts
        attempts += 1
        return False
    c.connect = fail

    for _ in range(20):                       # 20 cycles, still backing off
        await b._ensure_connected()
    assert attempts == 1, f"{attempts} connect attempts in one backoff window"


async def test_backoff_resets_after_a_successful_connect(backend):
    b, c = backend(reconnect_delay_s=1.0, reconnect_delay_max_s=30.0)
    c.connected = False

    async def fail():
        return False
    c.connect = fail
    for _ in range(3):
        b._next_attempt = 0.0
        await b._ensure_connected()
    assert b._backoff > 1.0

    c.connected = True
    assert await b._ensure_connected() is True
    assert b._backoff == 1.0


async def test_a_hanging_connect_is_bounded_by_the_timeout(backend):
    """A blocking reconnect would stall safety supervision."""
    b, c = backend(timeout_s=0.05)
    c.connected = False

    async def hang():
        await asyncio.sleep(10)
    c.connect = hang

    await asyncio.wait_for(b._ensure_connected(), timeout=2.0)


# ---------- reads, writes, decoding ----------

async def test_read_state_decodes_and_maps_channels(backend):
    b, c = backend()
    c.temps = [0] * 16
    c.temps[0] = 235                          # channel 1 -> rl_hk01
    c.temps[13] = 185                         # channel 14 -> rl_total
    c.temps[14] = 0x10000 - 55                # channel 15 -> vl_total, -5.5 C
    await b.read_state()
    assert b.state.temps["rl_hk01"] == 23.5
    assert b.state.temps["rl_total"] == 18.5
    assert b.state.temps["vl_total"] == -5.5


async def test_a_sparse_channel_list_does_not_crash_the_loop(cfg):
    """Found by this suite, 2026-07-27.

    read_state() used to request `len(channels)` registers and then index the
    reply by channel INDEX. Those agree only while config.yaml enumerates every
    channel densely. List a subset - say, only the channels that are actually
    wired - and the reply is shorter than the highest index, so the lookup
    raises IndexError. That is the worst available failure mode: not a
    degradation but a per-cycle `cycle_error`, forever, from a legal config.
    """
    cfg["sensors"]["channels"] = [{"index": 1, "name": "rl_hk01"},
                                  {"index": 15, "name": "vl_total"}]
    b = ModbusDirectBackend(cfg)
    c = FakeCoupler()
    c.temps = [0] * 16
    c.temps[0] = 220
    c.temps[14] = 300
    b.client = c

    await b.read_state()

    assert b.state.temps == {"rl_hk01": 22.0, "vl_total": 30.0}


async def test_disabled_channels_are_not_published(backend):
    b, _ = backend()
    await b.read_state()
    assert "spare" not in b.state.temps


async def test_saturated_raw_values_become_faults(backend):
    """Wire break / short circuit must not be decoded as a temperature."""
    b, c = backend()
    c.temps = [0] * 16
    c.temps[0] = 0x05DC                       # short circuit
    c.temps[1] = 0xFED4                       # wire break
    await b.read_state()
    assert b.state.faults == {"rl_hk01", "rl_hk02"}
    assert "rl_hk01" not in b.state.temps
    assert "rl_hk02" not in b.state.temps


async def test_faults_clear_when_the_sensor_recovers(backend):
    b, c = backend()
    c.temps = [0x05DC] + [200] * 15
    await b.read_state()
    assert "rl_hk01" in b.state.faults
    c.temps = [235] + [200] * 15
    await b.read_state()
    assert b.state.faults == set()
    assert b.state.temps["rl_hk01"] == 23.5


async def test_read_error_never_raises_and_keeps_the_old_state(backend):
    b, c = backend()
    await b.read_state()
    good = dict(b.state.temps)
    ts = b.state.last_read_ts

    async def fail(addr, count=1):
        raise OSError("connection reset")
    c.read_input_registers = fail

    state = await b.read_state()
    assert state.temps == good
    assert state.last_read_ts == ts           # staleness stays honest


async def test_write_valve_scales_percent_to_full_scale(backend):
    b, c = backend()
    await b.write_valve("valve_hk01", 100.0)
    assert c.outputs[12] == md.RAW_FULLSCALE
    await b.write_valve("valve_hk02", 0.0)
    assert c.outputs[13] == 0
    await b.write_valve("valve_hk03", 50.0)
    assert c.outputs[14] == pytest.approx(md.RAW_FULLSCALE // 2, abs=1)


async def test_write_valve_clamps_out_of_range_commands(backend):
    b, c = backend()
    await b.write_valve("valve_hk01", 150.0)
    assert c.outputs[12] == md.RAW_FULLSCALE
    await b.write_valve("valve_hk01", -20.0)
    assert c.outputs[12] == 0


async def test_write_valve_raises_on_failure(backend):
    """Unlike read_state, a definite write failure MUST be visible."""
    b, c = backend()
    c.expire()                                # process writes refused
    with pytest.raises(IOError):
        await b.write_valve("valve_hk01", 50.0)


async def test_write_all_valves_never_raises(backend):
    """The failsafe path must survive a bus that is refusing everything."""
    b, c = backend()
    c.expire()
    await b.write_all_valves(100.0)           # must not raise


async def test_failsafe_write_failure_is_one_line_not_eight_tracebacks(
        backend, caplog):
    """Real defect, 2026-07-27: log flooding destroyed the incident evidence.

    Eight stack traces per second at one failsafe cycle per second flushed 3.5
    hours of container log - including whatever started it - before it could
    be read.
    """
    b, c = backend()
    c.expire()
    with caplog.at_level("WARNING", logger="heatctl.io.modbus"):
        await b.write_all_valves(100.0)
    records = [r for r in caplog.records if "failsafe write" in r.getMessage()]
    assert len(records) == 1, f"{len(records)} records for one failsafe write"
    assert records[0].exc_info is None, "traceback attached to an expected error"


# ---------- configuration ----------

def test_environment_overrides_the_configured_host(cfg, monkeypatch):
    """Site values come from the environment so config.yaml can be public."""
    monkeypatch.setenv("HEATCTL_MODBUS_HOST", "198.51.100.7")
    monkeypatch.setenv("HEATCTL_MODBUS_PORT", "1502")
    b = ModbusDirectBackend(cfg)
    assert (b.host, b.port) == ("198.51.100.7", 1502)


def test_configured_host_is_used_without_an_override(cfg, monkeypatch):
    monkeypatch.delenv("HEATCTL_MODBUS_HOST", raising=False)
    monkeypatch.delenv("HEATCTL_MODBUS_PORT", raising=False)
    b = ModbusDirectBackend(cfg)
    assert (b.host, b.port) == ("192.0.2.52", 502)
