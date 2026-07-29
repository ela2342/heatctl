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

**Writes wear flash.** The manual states the unit flashes its memory chip on
every 06H/10H and warns against doing it often. So a write that would not
change the stored value is dropped before it reaches the bus, and a budget
caps writes per hour. A "reconcile every cycle" loop would destroy this device,
not merely waste bandwidth.

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
        self.write_budget_per_hour = int(h.get("write_budget_per_hour", 30))

        self.plane = plane
        self.client: AsyncModbusTcpClient | None = None
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

    def _budget_ok(self) -> bool:
        now = time.monotonic()
        self._writes = [t for t in self._writes if now - t < 3600]
        return len(self._writes) < self.write_budget_per_hour

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
        if not self._budget_ok():
            log.error("write to 0x%04X REFUSED: %d writes in the last hour "
                      "exceeds the flash-wear budget. Something is looping.",
                      addr, len(self._writes))
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

        active = [name for (addr, bit), name in hm.FAULT_BITS.items()
                  if (self.status.get(addr, 0) >> bit) & 1]
        for name in set(hm.FAULT_BITS.values()):
            await self.plane.publish(f"hp/fault/{name}",
                                     "1" if name in active else "0")
        await self.plane.publish("hp/fault_any", "1" if active else "0")
        await self.plane.publish("hp/faults", ",".join(sorted(active)) or "none")

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
                        self.config = cfg
                        self._config_seen = True
                        await self._publish_block(cfg)
                        last_config = now
                else:
                    # Control block only - cheap, and mode/power can move.
                    ctrl = await self._read_span(hm.RW_FIRST, 0x0038)
                    if ctrl:
                        self.config.update(ctrl)
                        await self._publish_block(ctrl)

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
        await self.plane.discover("sensor", "hp_mode_name", {
            "name": "Heat pump mode",
            "state_topic": f"{self.plane.base}/hp/mode_name",
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
