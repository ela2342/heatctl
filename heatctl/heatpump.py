"""PW58321 heat pump client — full register access over MQTT.

heatctl becomes the SOLE Modbus master for this device. That is not a
preference: the unit documents a minimum 200 ms interval between transactions,
and two independent masters cannot honour it on each other's behalf. Home
Assistant's modbus hub for this unit must stay disabled; HA gets everything
through the MQTT topics published here instead.

What is exposed:

  - **Every register, raw.** `hp/raw/0xADDR` for all 269 configuration
    registers and all 43 status registers. No curation, nothing hidden behind
    a decode table that might be incomplete.
  - **Decoded values** for the registers we have confirmed names and scales
    for (heatctl/heatpump_map.py), including all 20 documented fault bits.
  - **Writes**, on `hp/set/<name>` and `hp/set/raw/0xADDR`.

Three properties that are not negotiable, each for a hardware reason:

**Writes wear flash, but wear is not the worst failure.** The manual states the
unit flashes its memory chip on every 06H/10H and warns against doing it often,
so a write that would not change the stored value is dropped before it reaches
the bus - that one is free, it costs a packet and saves a flash cycle.

The RATE limit is deliberately not a gate (owner, 2026-07-31). Exceeding
`write_budget_per_hour` raises a user-visible alarm and **the write still
happens**; only `write_hard_limit_per_hour`, ten times higher, actually refuses.
Flash wear is a soft cost accumulating over years, while a plant deviation
heatctl cannot correct is a hard cost happening now - a cold house, or cold
water in the slab. Dropping writes silently traded the second for the first, in
the wrong direction, somewhere nobody would look. A "reconcile every cycle" loop
would still destroy this device, which is what the hard limit is for.

**All bus access is serialised behind one lock with a minimum gap.** Reads and
writes share the 200 ms budget; nothing here may issue a transaction without
going through `_txn`.

**Over-long reads are silently truncated.** Asking for 121 registers returns
120 and no error, so every read validates the returned length. Without that a
short reply misaligns every field after the cut and the values still look
plausible.

Configuration drift is watched deliberately: the full RW space is re-read on a
slow cycle and diffed, because settings can be changed at the unit's own
control panel and we want to know when someone has.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time

from pymodbus.client import AsyncModbusTcpClient

from . import heatpump_map as hm

log = logging.getLogger("heatctl.hp")


class HeatPump:
    def __init__(self, cfg: dict, plane):
        h = dict(cfg.get("heatpump") or {})
        self.enabled = bool(h.get("enabled", False))
        # Environment wins over the file for site values, as elsewhere, so the
        # committed config.yaml keeps an RFC 5737 placeholder.
        self.host = os.environ.get("HEATCTL_HP_HOST") or h.get("host", "192.0.2.37")
        self.port = int(os.environ.get("HEATCTL_HP_PORT") or h.get("port", 4196))
        self.unit = int(h.get("unit", 1))
        self.timeout = float(h.get("timeout_s", 5.0))
        self.poll_s = float(h.get("poll_interval_s", 5.0))
        self.config_poll_s = float(h.get("config_poll_interval_s", 300.0))
        self.allow_writes = bool(h.get("allow_writes", False))
        # Flash-wear budget. Deliberately small: legitimate control changes are
        # rare events (a mode change, a setpoint trim), not a stream.
        #
        # **THIS IS A WARNING THRESHOLD, NOT A GATE** (owner, 2026-07-31).
        # Exceeding it raises a user-visible error and keeps writing. Flash
        # wear is a soft, cumulative cost measured in years; being unable to
        # correct a plant deviation is a hard cost measured in a cold house or
        # a wet slab. Silently dropping writes traded the second for the first,
        # in the wrong direction and invisibly.
        self.write_budget_per_hour = int(h.get("write_budget_per_hour", 30))
        # The actual gate, an order of magnitude up. At this rate nothing
        # legitimate is happening - it is a control loop that has lost its
        # mind - and refusing is the lesser harm.
        self.write_hard_limit_per_hour = int(
            h.get("write_hard_limit_per_hour", 10 * self.write_budget_per_hour))
        self._budget_alarm = False

        self.plane = plane
        self.client: AsyncModbusTcpClient | None = None
        # Last raw value warned about per register, so an implausible reading
        # is reported once and not once per poll. See _check_ranges.
        self._range_warned: dict[int, int] = {}
        self._lock = asyncio.Lock()
        self._last_txn = 0.0
        self._writes: list[float] = []       # timestamps, for the budget
        self.status: dict[int, int] = {}     # addr -> raw
        self.config: dict[int, int] = {}
        self._config_seen = False
        self._discovered = False

    # ---------- transport ----------

    async def _txn(self, fn, *a, **kw):
        """Every bus transaction goes through here. Serialised, spaced, bounded.

        The gap is enforced across reads AND writes because the device's limit
        is per transaction, not per kind.
        """
        async with self._lock:
            gap = hm.MIN_INTERVAL_S - (time.monotonic() - self._last_txn)
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                r = await fn(*a, **kw)
            finally:
                self._last_txn = time.monotonic()
            return r

    async def _connect(self) -> bool:
        if self.client is not None and self.client.connected:
            return True
        self.client = AsyncModbusTcpClient(
            self.host, port=self.port, timeout=self.timeout)
        try:
            await asyncio.wait_for(self.client.connect(), timeout=self.timeout)
        except Exception as e:
            log.warning("heat pump unreachable at %s:%s (%s)",
                        self.host, self.port, e)
            return False
        return bool(self.client.connected)

    async def _read_span(self, lo: int, hi: int) -> dict[int, int] | None:
        """Read [lo, hi] inclusive in <=MAX_READ chunks. None on any failure."""
        out: dict[int, int] = {}
        a = lo
        while a <= hi:
            n = min(hm.MAX_READ, hi - a + 1)
            r = await self._txn(self.client.read_holding_registers,
                                a, count=n, device_id=self.unit)
            if r.isError():
                log.warning("read 0x%04X x%d failed: %s", a, n, r)
                return None
            if len(r.registers) != n:
                # Silent truncation - see module docstring. Refuse the data
                # rather than misalign every field after the cut.
                log.error("SHORT READ at 0x%04X: asked %d, got %d - discarding",
                          a, n, len(r.registers))
                return None
            out.update({a + i: v for i, v in enumerate(r.registers)})
            a += n
        return out

    # ---------- writes ----------

    def writes_last_hour(self) -> int:
        now = time.monotonic()
        self._writes = [t for t in self._writes if now - t < 3600]
        return len(self._writes)

    async def _check_budget(self, addr: int) -> bool:
        """Report on the write rate. Returns False ONLY at the hard limit.

        Two thresholds, and the difference is the whole point:

        - `write_budget_per_hour` is a **warning**. Over it, this raises a
          user-visible alarm and returns True anyway, so the write proceeds.
          A controller that cannot actuate is a worse failure than a
          controller that wears a flash cell, and the wear is cumulative over
          years while the deviation is happening now.
        - `write_hard_limit_per_hour` is the **gate**, 10x higher. At that rate
          no legitimate control is occurring - it is a loop that has lost its
          mind - and continuing would be destructive without being useful.

        The alarm publishes rather than only logging, because the failure this
        exists to catch is a runaway loop, and a runaway loop at 03:00 that
        only writes to a log file is a failure nobody sees until the device
        stops accepting writes permanently.
        """
        n = self.writes_last_hour()
        over = n >= self.write_budget_per_hour
        if over != self._budget_alarm:
            self._budget_alarm = over
            if over:
                log.error("HEAT PUMP WRITE BUDGET EXCEEDED: %d writes in the "
                          "last hour against a budget of %d. Writes CONTINUE "
                          "up to the hard limit of %d - find the loop.",
                          n, self.write_budget_per_hour,
                          self.write_hard_limit_per_hour)
            else:
                log.warning("heat pump write rate back within budget (%d/h)", n)
            with contextlib.suppress(Exception):
                await self.plane.publish("hp/write_budget_exceeded",
                                         "1" if over else "0")
        with contextlib.suppress(Exception):
            await self.plane.publish("hp/writes_last_hour", str(n))
        if n >= self.write_hard_limit_per_hour:
            log.critical("write to 0x%04X REFUSED: %d writes in the last hour "
                         "is past the hard limit of %d. Something is looping.",
                         addr, n, self.write_hard_limit_per_hour)
            with contextlib.suppress(Exception):
                await self.plane.publish("hp/write_hard_limit_hit", "1")
            return False
        return True

    async def write_register(self, addr: int, raw: int, why: str) -> bool:
        """Write one register. Returns True if the device was actually written.

        No-ops are dropped BEFORE the bus, because the cost we are avoiding is
        a flash cycle, not a packet.
        """
        if not self.allow_writes:
            log.warning("write to 0x%04X refused: heatpump.allow_writes is off",
                        addr)
            return False
        current = self.config.get(addr)
        if current == raw:
            log.debug("write to 0x%04X skipped, already %d", addr, raw)
            return False
        if not await self._check_budget(addr):
            return False
        if not await self._connect():
            return False
        r = await self._txn(self.client.write_register,
                            addr, raw, device_id=self.unit)
        if r.isError():
            log.error("write 0x%04X = %d failed: %s", addr, raw, r)
            return False
        self._writes.append(time.monotonic())
        log.warning("heat pump 0x%04X: %s -> %d (%s)", addr, current, raw, why)
        self.config[addr] = raw
        return True

    # ---------- P04 as a transport: the setpoint, or OFF -------------------
    #
    # This machine has no writable "disable cooling". `0x8003`'s cooling-enable
    # bit is READ-ONLY, `0x0004` Mode has no off value, and `0x0000` bit 0 is
    # unit power - which stops the internal DC pump, the only circulation the
    # plant has until the buffer tank lands. Stopping the compressor while
    # water keeps moving therefore has exactly one lever: put P04 above the
    # return temperature and let the machine stop on its own logic.
    #
    # **P04 is a transport, not the setpoint** (owner, 2026-07-31: "we do not
    # mess with the setpoint in a way that is visible to anyone"). It carries
    # either the setpoint or OFF. Nothing outside this pair of methods should
    # ever see the sentinel - `setpoint.py` reasons from the current setpoint
    # to compute its next move, and a 30 read back as "the setpoint" would
    # poison the trim, the constraint memory and the reversal guard alike.
    COOLING_OFF_C = 30.0

    def cooling_setpoint(self) -> float | None:
        """The LOGICAL cooling setpoint. None means OFF is currently written.

        30 is safe as a sentinel: it is the top of P04's documented 7-30 range
        and is above any conceivable cooling return temperature, so nobody
        would ever command it as a real setpoint.
        """
        raw = self.config.get(0x0090)
        if raw is None:
            return None
        value = float(raw)
        return None if value >= self.COOLING_OFF_C else value

    def cooling_is_off(self) -> bool:
        raw = self.config.get(0x0090)
        return raw is not None and float(raw) >= self.COOLING_OFF_C

    async def set_cooling(self, setpoint: float | None, why: str) -> bool:
        """Write the setpoint, or None for OFF.

        OFF is not a modulation - it is a stop, expressed through the only
        lever that does not also kill the pump. Do not use this to back the
        machine off "a bit"; that is what the frequency ceiling is for.
        """
        if setpoint is None:
            return await self.write_named("setpoint_cooling",
                                          self.COOLING_OFF_C, f"OFF: {why}")
        if setpoint >= self.COOLING_OFF_C:
            log.error("refusing setpoint %.1f - that is the OFF sentinel, and "
                      "a real setpoint must never collide with it", setpoint)
            return False
        return await self.write_named("setpoint_cooling", setpoint, why)

    async def write_named(self, name: str, value: float, why: str) -> bool:
        reg = next((r for r in hm.WRITABLE if r.name == name), None)
        if reg is None:
            log.warning("no writable register named %r", name)
            return False
        if reg.lo is not None and not (reg.lo <= value <= reg.hi):
            log.error("%s = %s is outside the documented range %s..%s - refused",
                      name, value, reg.lo, reg.hi)
            return False
        return await self.write_register(reg.addr, hm.encode(reg, value), why)

    async def set_mode(self, mode: str, why: str = "heatctl") -> bool:
        """mode is one of heatpump_map.MODES values."""
        code = hm.MODE_BY_NAME.get(mode)
        if code is None:
            log.warning("unknown heat pump mode %r", mode)
            return False
        return await self.write_named("mode", code, why)

    # heatctl plant mode -> the pump's own mode register (0x0004).
    # "off" has no pump-mode equivalent: not running is a power/demand
    # decision, not a mode. So an off plant leaves the mode alone.
    PLANT_TO_PUMP_MODE = {"heating": "heating", "cooling": "cooling"}

    def mode_disagrees(self, plant_mode: str) -> str | None:
        """The pump's mode if it differs from what the plant thinks. Else None.

        heatctl's mode decides which way the valve PIDs run; the pump's mode
        decides what temperature the water is. If they diverge, the valve loop
        drives the wrong direction with the wrong water - and the condensation
        guard, which is scoped to the plant's cooling mode, would be off while
        chilled water circulated. Detecting that is why this exists.
        """
        want = self.PLANT_TO_PUMP_MODE.get(plant_mode)
        if want is None:
            return None
        actual = self.config.get(0x0004)
        if actual is None:
            return None                      # never read it; say nothing
        name = hm.MODES.get(actual, str(actual))
        return None if name == want else name

    async def sync_mode(self, plant_mode: str) -> bool:
        """Make the pump's mode follow the plant's. No-op when already right.

        Refuses until the config block has actually been read: writing 0x0004
        from an unknown current value would be a blind write, and every write
        costs a flash cycle.
        """
        want = self.PLANT_TO_PUMP_MODE.get(plant_mode)
        if want is None or not self._config_seen:
            return False
        if self.mode_disagrees(plant_mode) is None:
            return False
        return await self.set_mode(want, f"plant mode is {plant_mode}")

    async def set_control_bit(self, name: str, on: bool,
                              why: str = "heatctl") -> bool:
        """Set one named bit in a shared control register.

        Generalises `set_power` below, and exists for the same reason: these
        registers pack several unrelated settings, so the only safe write is
        read-modify-write against a value we have ACTUALLY READ. Register
        0x0001 alone carries seven settings, of which heatctl exposes two - so
        anyone reconstructing it from the two visible bits would silently
        rewrite the other five to whatever they guessed.

        Refuses if the register has never been read, rather than assuming
        zeros. Also refuses to write when nothing would change, because every
        write wears the unit's flash (docs/HEATPUMP.md).
        """
        entry = next(((addr, bit) for (addr, bit), n
                      in hm.CONTROL_BITS.items() if n == name), None)
        if entry is None:
            log.warning("no control bit named %r", name)
            return False
        addr, bit = entry
        cur = self.config.get(addr)
        if cur is None:
            log.error("refusing to touch 0x%04X: never read it, so a "
                      "read-modify-write would invent its other bits", addr)
            return False
        raw = (cur | (1 << bit)) if on else (cur & ~(1 << bit))
        if raw == cur:
            log.info("%s already %s - no write", name, "on" if on else "off")
            return True
        return await self.write_register(
            addr, raw, f"{name} {'on' if on else 'off'}: {why}")

    async def set_power(self, on: bool, why: str = "heatctl") -> bool:
        """Register 0 bit 0 is the unit's POWER, not the water pump.

        Read-modify-write on a register whose other bits we do not own, so it
        uses the most recent full read rather than a stale cached guess - and
        refuses outright if we have never read it.
        """
        cur = self.config.get(0x0000)
        if cur is None:
            log.error("refusing to touch 0x0000: never read it, so a "
                      "read-modify-write would invent the other 15 bits")
            return False
        raw = (cur | 0x01) if on else (cur & ~0x01)
        return await self.write_register(0x0000, raw, f"power {'on' if on else 'off'}: {why}")

    # ---------- publishing ----------

    async def _publish_block(self, regs: dict[int, int]) -> None:
        for addr, raw in regs.items():
            await self.plane.publish(f"hp/raw/0x{addr:04X}", raw)

    async def _publish_decoded(self) -> None:
        all_regs = {**self.config, **self.status}
        for reg in (*hm.WRITABLE, *hm.STATUS):
            raw = all_regs.get(reg.addr)
            if raw is not None:
                await self.plane.publish(f"hp/{reg.name}", hm.decode(reg, raw))

        for (addr, bit), name in {**hm.OUTPUT_BITS, **hm.MODE_STATUS_BITS,
                                  **hm.CONTROL_BITS}.items():
            raw = all_regs.get(addr)
            if raw is not None:
                await self.plane.publish(f"hp/{name}", "1" if raw >> bit & 1 else "0")

        mode = self.config.get(0x0004)
        if mode is not None:
            await self.plane.publish("hp/mode_name", hm.MODES.get(mode, str(mode)))

        # FAULTS AND PROTECTIONS ARE PUBLISHED APART (D-037). A fault wants a
        # human; a protection is the unit throttling itself and clearing on its
        # own. Rolling both into `fault_any` made the alarm mean nothing.
        active = [name for (addr, bit), name in hm.FAULT_BITS.items()
                  if (self.status.get(addr, 0) >> bit) & 1]
        for name in set(hm.FAULT_BITS.values()):
            await self.plane.publish(f"hp/fault/{name}",
                                     "1" if name in active else "0")
        await self.plane.publish("hp/fault_any", "1" if active else "0")
        await self.plane.publish("hp/faults", ",".join(sorted(active)) or "none")

        limiting = [name for (addr, bit), name in hm.PROTECTION_BITS.items()
                    if (self.status.get(addr, 0) >> bit) & 1]
        for name in set(hm.PROTECTION_BITS.values()):
            await self.plane.publish(f"hp/protection/{name}",
                                     "1" if name in limiting else "0")
        await self.plane.publish("hp/protection_any", "1" if limiting else "0")
        await self.plane.publish("hp/protections",
                                 ",".join(sorted(limiting)) or "none")

    # ---------- plausibility ----------

    def _check_ranges(self, block: dict[int, int]) -> None:
        """Warn when a register reads outside the range its own map declares.

        `Reg.lo`/`Reg.hi` were carried for WRITE validation only, so nothing
        ever checked what the device sends back. That cost real time on
        2026-08-08: `silent_max_fan_cooling` (declared 0-1000) reads 65512, and
        the capacity loop's precondition `fan_cap >= fan_cap_min` accepts it
        because 65512 > 400. The gate meant to confirm the condenser is not
        throttled has been passing on a value the map itself calls impossible,
        and it surfaced only during an unrelated conversation about silent mode.

        NOT SPAM. One line per register per DISTINCT value: an implausible
        reading is almost always a constant (a decode error, or a sentinel the
        map does not know), so this fires once and stays quiet until the value
        actually changes. A per-cycle warning on a 5 s poll would bury the log
        exactly the way the pymodbus frame dumps did.
        """
        for addr, raw in block.items():
            reg = hm.REG_BY_ADDR.get(addr)
            if reg is None or reg.lo is None or reg.hi is None:
                continue
            val = hm.decode(reg, raw)
            if reg.lo <= val <= reg.hi:
                self._range_warned.pop(addr, None)
                continue
            if self._range_warned.get(addr) == raw:
                continue
            self._range_warned[addr] = raw
            log.warning("register out of its documented range: 0x%04X %s = %s "
                        "(raw %d), declared %s..%s - decode or map may be wrong",
                        addr, reg.name, val, raw, reg.lo, reg.hi)

    # ---------- drift detection ----------

    def _diff_config(self, new: dict[int, int]) -> list[tuple[int, int, int]]:
        if not self._config_seen:
            return []
        return [(a, self.config[a], v) for a, v in new.items()
                if a in self.config and self.config[a] != v]

    # ---------- main loop ----------

    async def run(self) -> None:
        if not self.enabled:
            log.info("heat pump client disabled (heatpump.enabled)")
            return
        last_config = 0.0
        while True:
            try:
                if not await self._connect():
                    await asyncio.sleep(10)
                    continue

                status = await self._read_span(hm.RO_FIRST, hm.RO_LAST)
                if status:
                    self.status = status
                    await self._publish_block(status)

                now = time.monotonic()
                if now - last_config >= self.config_poll_s or not self._config_seen:
                    cfg = await self._read_span(hm.RW_FIRST, hm.RW_LAST)
                    if cfg:
                        for addr, old, new in self._diff_config(cfg):
                            # Someone changed a setting at the unit's own panel
                            # (or we did). Either way it is worth knowing.
                            log.warning("heat pump config changed outside "
                                        "heatctl: 0x%04X %d -> %d", addr, old, new)
                            await self.plane.publish(
                                "hp/config_changed", f"0x{addr:04X}:{old}->{new}")
                        self._check_ranges(cfg)
                        self.config = cfg
                        self._config_seen = True
                        await self._publish_block(cfg)
                        last_config = now
                else:
                    # Control block only - cheap, and mode/power can move.
                    ctrl = await self._read_span(hm.RW_FIRST, 0x0038)
                    if ctrl:
                        self._check_ranges(ctrl)
                        self.config.update(ctrl)
                        await self._publish_block(ctrl)

                # PUBLISH THE WRITE RATE EVERY CYCLE, not only when a write is
                # attempted. `_check_budget` runs inside write_register, so on a
                # quiet plant these entities would sit at `unknown` indefinitely
                # and the alarm would be indistinguishable from a dead sensor.
                # An alarm that only exists once something has gone wrong is not
                # an alarm. Publishing 0 continuously is what makes a later 1
                # mean something.
                await self._publish_write_rate()

                if self.status or self.config:
                    await self._publish_decoded()
                    if not self._discovered:
                        await self._publish_discovery()
                        self._discovered = True
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("heat pump cycle failed")
            await asyncio.sleep(self.poll_s)

    async def _publish_write_rate(self) -> None:
        """Heartbeat the write-rate telemetry so silence means healthy."""
        n = self.writes_last_hour()
        with contextlib.suppress(Exception):
            await self.plane.publish("hp/writes_last_hour", str(n))
            await self.plane.publish(
                "hp/write_budget_exceeded",
                "1" if n >= self.write_budget_per_hour else "0")

    async def _publish_discovery(self) -> None:
        """HA entities for the decoded subset.

        Raw registers are deliberately NOT discovered - 312 diagnostic entities
        would bury everything useful. They stay available on hp/raw/# for
        anyone who wants them.
        """
        # Every entity is prefixed "HP" so the heat pump's registers group
        # together and cannot collide with heatctl's own. Without it register
        # 0x0004 becomes `sensor.heatctl_mode`, sitting next to
        # `select.heatctl_mode` (the plant mode) meaning something different.
        for reg in (*hm.STATUS, *hm.WRITABLE):
            conf = {"name": "HP " + reg.name.replace("_", " "),
                    "state_topic": f"{self.plane.base}/hp/{reg.name}",
                    "state_class": "measurement"}
            if reg.unit:
                conf["unit_of_measurement"] = reg.unit
            if reg.device_class:
                conf["device_class"] = reg.device_class
            await self.plane.discover("sensor", f"hp_{reg.name}", conf)

        for name in (*hm.OUTPUT_BITS.values(), *hm.MODE_STATUS_BITS.values(),
                     *hm.CONTROL_BITS.values()):
            await self.plane.discover("binary_sensor", f"hp_{name}", {
                "name": "HP " + name.replace("_", " "),
                "state_topic": f"{self.plane.base}/hp/{name}",
                "payload_on": "1", "payload_off": "0",
            })

        await self.plane.discover("binary_sensor", "hp_fault_any", {
            "name": "Heat pump fault",
            "state_topic": f"{self.plane.base}/hp/fault_any",
            "payload_on": "1", "payload_off": "0",
            "device_class": "problem",
        })
        await self.plane.discover("sensor", "hp_faults", {
            "name": "Heat pump active faults",
            "state_topic": f"{self.plane.base}/hp/faults",
            "entity_category": "diagnostic",
        })
        # NOT `device_class: problem`. A running protection is information, not
        # an alarm - it says the unit is holding itself back, which is worth
        # seeing on a graph next to frequency and worth nobody's attention at
        # 03:00. Whether it should ever alarm is a question about how OFTEN it
        # runs, and that is a job for a trend, not a binary sensor.
        await self.plane.discover("binary_sensor", "hp_protection_any", {
            "name": "Heat pump protection active",
            "state_topic": f"{self.plane.base}/hp/protection_any",
            "payload_on": "1", "payload_off": "0",
            "entity_category": "diagnostic",
        })
        await self.plane.discover("sensor", "hp_protections", {
            "name": "Heat pump active protections",
            "state_topic": f"{self.plane.base}/hp/protections",
            "entity_category": "diagnostic",
        })
        await self.plane.discover("sensor", "hp_mode_name", {
            "name": "Heat pump mode",
            "state_topic": f"{self.plane.base}/hp/mode_name",
        })
        # WRITE RATE. Discovered as a `problem` so it surfaces as an actual
        # alarm rather than a number nobody reads. The budget no longer gates
        # writes (owner, 2026-07-31: an uncorrectable plant deviation beats
        # flash wear), so this indicator IS the protection - if it is not
        # visible, the runaway loop it exists to catch has nothing stopping it
        # short of the hard limit.
        await self.plane.discover("binary_sensor", "hp_write_budget_exceeded", {
            "name": "HP write budget exceeded",
            "state_topic": f"{self.plane.base}/hp/write_budget_exceeded",
            "payload_on": "1", "payload_off": "0",
            "device_class": "problem",
        })
        await self.plane.discover("sensor", "hp_writes_last_hour", {
            # Name kept in lockstep with the object id and the MQTT topic
            # (`hp/writes_last_hour`): HA derives the entity_id from the NAME,
            # so "HP writes in the last hour" would yield
            # sensor.heatctl_hp_writes_in_the_last_hour and a diagnosis at
            # 03:00 would be hunting three different spellings of one quantity.
            "name": "HP writes last hour",
            "state_topic": f"{self.plane.base}/hp/writes_last_hour",
            "state_class": "measurement",
            "entity_category": "diagnostic",
        })

        # --- CONTROLS ---
        # Exposed because their state lives in the DEVICE's flash, so an HA
        # control maps to something durable. Contrast heatctl's own behaviour
        # flags (auto_mode, the demand controller's enables): those live in
        # config.yaml, and heatctl deliberately keeps no state across a
        # restart, so an HA toggle for them would silently revert and lie.
        for reg in hm.WRITABLE:
            if reg.lo is None or reg.unit != "°C":
                continue
            await self.plane.discover("number", f"hp_set_{reg.name}", {
                "name": "HP " + reg.name.replace("_", " "),
                "state_topic": f"{self.plane.base}/hp/{reg.name}",
                "command_topic": f"{self.plane.base}/hp/set/{reg.name}",
                "min": reg.lo, "max": reg.hi, "step": 1,
                "unit_of_measurement": reg.unit,
                "mode": "box",
            })
        await self.plane.discover("switch", "hp_power", {
            "name": "HP power",
            "state_topic": f"{self.plane.base}/hp/power",
            "command_topic": f"{self.plane.base}/hp/set/power",
            "payload_on": "1", "payload_off": "0",
        })
