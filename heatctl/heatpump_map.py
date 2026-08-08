"""PW58321 register map — device truth, transcribed from the vendor manual.

Separate from `config.yaml` on purpose: `config.yaml` is *site* truth (which
circuit is in which room), this is *device* truth and is identical for every
PW58321. Full manual and provenance: `docs/HEATPUMP.md`.

Scales come from the manual's per-register "Accuracy" annotations and were
cross-checked against the live device on 2026-07-27. **There is no uniform
factor** — return water is 0.1 and leaving water is 0.5, sitting four registers
apart. Getting one wrong yields a plausible number, which is the worst kind of
wrong.

Temperatures are SIGNED int16. Home Assistant's existing config gets this wrong
for the economizer registers, which read 65440/65436 and are displayed as
+32720/+32718 when they are actually -48.0/-50.0 °C sentinels for sensors this
unit does not have fitted.
"""
from __future__ import annotations

from dataclasses import dataclass

# Contiguous, verified on the device. See docs/HEATPUMP.md - the apparent
# "gap" at 0x002D-0x0038 was an artifact of extracting the PDF, not real.
RW_FIRST, RW_LAST = 0x0000, 0x010C      # 269 registers, configuration
RO_FIRST, RO_LAST = 0x8000, 0x802A      # 43 registers, status + telemetry

# The device SILENTLY TRUNCATES reads longer than this - it returns 120
# registers and no error. Always validate the returned length.
MAX_READ = 120

# Minimum spacing between any two transactions, per the manual.
MIN_INTERVAL_S = 0.25                    # manual says >=200 ms; margin added

MODES = {0: "dhw", 1: "heating", 2: "cooling", 3: "dhw+heating",
         4: "dhw+cooling"}
MODE_BY_NAME = {v: k for k, v in MODES.items()}


@dataclass(frozen=True)
class Reg:
    addr: int
    name: str
    scale: float = 1.0
    unit: str = ""
    signed: bool = False
    writable: bool = False
    lo: float | None = None            # documented range, for write validation
    hi: float | None = None
    device_class: str | None = None


# --- writable configuration -------------------------------------------------
# Only the registers heatctl has a reason to name. Everything else in
# 0x0000-0x010C is still readable, published raw, and watched for drift.
WRITABLE = [
    Reg(0x0000, "control_flags_0", writable=True),
    Reg(0x0004, "mode", writable=True, lo=0, hi=4),
    Reg(0x008F, "setpoint_dhw", 1.0, "°C", writable=True, lo=28, hi=60,
        device_class="temperature"),
    Reg(0x0090, "setpoint_cooling", 1.0, "°C", writable=True, lo=7, hi=30,
        device_class="temperature"),
    Reg(0x0091, "setpoint_heating", 1.0, "°C", writable=True, lo=15, hi=50,
        device_class="temperature"),
    # Added 2026-07-30. These were in the register map all along but unnamed,
    # so nothing could read them - which is how the restart dead zone stayed
    # invisible while it dictated the plant's behaviour. Naming them here makes
    # them readable as entities and writable by name, with range checks.
    Reg(0x0001, "control_flags_1", writable=True),
    Reg(0x008D, "restart_diff_c", 1.0, "K", writable=True, lo=2, hi=18,
        device_class="temperature"),
    Reg(0x0092, "water_temp_compensation", 1.0, "K", writable=True,
        lo=-5, hi=15, signed=True, device_class="temperature"),
    Reg(0x00C4, "freq_min_hz", 1.0, "Hz", writable=True, lo=30, hi=120),
    # The silent-mode frequency caps. PURPOSE-BUILT ceilings, mode-specific, and
    # the unit's own feature - so every protection it has stays in play, unlike
    # taking over the frequency directly. R32 is the cooling one.
    Reg(0x00EF, "silent_max_freq_heating_hz", 1.0, "Hz", writable=True,
        lo=30, hi=120),
    Reg(0x00F1, "silent_max_freq_cooling_hz", 1.0, "Hz", writable=True,
        lo=30, hi=120),
    # Powerful mode turns out to be a +5 Hz TRIM, not a cap release. That is why
    # clearing it on 2026-07-29 had no measurable effect, and why the claim that
    # it capped the compressor was withdrawn.
    Reg(0x00F0, "powerful_freq_boost_cooling_hz", 1.0, "Hz", writable=True,
        lo=-30, hi=30, signed=True),
    Reg(0x00F4, "silent_max_fan_cooling", 1.0, None, writable=True,
        lo=0, hi=1000),
    Reg(0x00C5, "freq_max_hz", 1.0, "Hz", writable=True, lo=30, hi=120),
    Reg(0x0101, "pump_operation_mode", writable=True, lo=0, hi=1),
    Reg(0x0102, "pump_cycle_min", 1.0, "min", writable=True, lo=1, hi=120),
    Reg(0x010B, "pump_delta_t", 1.0, "K", writable=True, lo=2, hi=30),
    # --- the DC pump control block, F4-F9 -----------------------------------
    # Mapped 2026-07-31 for VISIBILITY, not to be written. The unit runs its own
    # pump loop and D-030 counts three controllers in this plant; this block is
    # a fourth, and it was invisible. Owner: "Pump should never be at 70 %
    # according to our design principles. We want to maximize flow to minimize
    # spread." Observed at 70 % with an hp spread of 2.9 K against an F10 target
    # of 2 K - if the DeltaT loop were regulating it would speed UP, so
    # something else is in charge and we could not see what.
    #
    # `docs/HEATPUMP.md` claims F10=2 "holds the pump at full flow". That claim
    # is unverified and the evidence contradicts it. Read these before touching
    # anything: writing F6 or F8 blind is how you end up fighting a loop you
    # have not identified.
    Reg(0x0105, "pump_mode", writable=True, lo=0, hi=2),      # 0 off 1 auto 2 manual
    Reg(0x0106, "pump_regulation_cycle_s", 1.0, "s", writable=True, lo=10, hi=120),
    Reg(0x0107, "pump_manual_speed_pct", 1.0, "%", writable=True, lo=10, hi=100),
    Reg(0x0108, "pump_max_speed_pct", 1.0, "%", writable=True, lo=10, hi=100),
    Reg(0x0109, "pump_min_speed_pct", 1.0, "%", writable=True, lo=10, hi=100),
    Reg(0x010A, "pump_regulation_speed_pct", 1.0, "%", writable=True, lo=0, hi=50),
]

# --- read-only status -------------------------------------------------------
STATUS = [
    Reg(0x800E, "return_water", 0.1, "°C", signed=True, device_class="temperature"),
    Reg(0x800F, "tank_temp", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x8011, "outdoor_ambient", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x8012, "leaving_water", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x8013, "economizer_inlet", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x8014, "economizer_outlet", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x8015, "suction_gas", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x8016, "external_coil", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x801A, "cooling_coil", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x801B, "exhaust_gas", 0.5, "°C", signed=True, device_class="temperature"),
    Reg(0x801C, "main_valve_opening", 1.0, "steps"),
    Reg(0x801D, "aux_valve_opening", 1.0, "steps"),
    Reg(0x801E, "compressor_freq", 1.0, "Hz"),
    Reg(0x8021, "dc_bus_voltage", 1.0, "V", device_class="voltage"),
    Reg(0x8024, "target_freq", 1.0, "Hz"),
    Reg(0x8025, "compressor_current", 0.1, "A", device_class="current"),
    Reg(0x8026, "dc_fan_1_speed", 1.0, "rpm"),
    Reg(0x8028, "lp_switch_conv_temp", 0.5, "°C", signed=True,
        device_class="temperature"),
    Reg(0x802A, "dc_pump_speed", 1.0, "%"),
]

# --- bitfields --------------------------------------------------------------
# (address, bit) -> name. Reserved bits are omitted rather than named, so a
# bit appearing here is one the manual actually defines.
OUTPUT_BITS = {
    (0x8004, 0): "compressor",
    (0x8005, 0): "chassis_electric_heater",
    (0x8006, 0): "water_pump",
    (0x8006, 1): "crankshaft_heater",
}

MODE_STATUS_BITS = {
    (0x8003, 0): "hot_water_enabled",
    (0x8003, 3): "cooling_enabled",
}

CONTROL_BITS = {
    (0x0000, 0): "power",                    # NOT the water pump - see docs
    (0x0000, 2): "manual_frequency",
    (0x0000, 4): "pump_non_stop",            # C01
    (0x0001, 0): "constant_temperature",   # gates whether R12/R13 bind at all
    (0x0001, 4): "powerful_mode",
    (0x0001, 5): "silent_mode",
    (0x0002, 1): "vacation_mode",
}

# Fault registers 0x8007-0x800D. Every defined bit, from the manual.
FAULT_BITS = {
    (0x8007, 0): "er14_water_tank_temp",
    (0x8007, 1): "er21_ambient_temp",
    (0x8007, 2): "er16_external_coil",
    (0x8007, 4): "er27_outlet_water",
    (0x8007, 5): "er05_high_pressure",
    (0x8007, 6): "er06_low_pressure",
    (0x8008, 0): "er03_water_flow",
    (0x8008, 2): "er32_leaving_water",
    (0x8009, 6): "er18_exhaust",
    (0x800A, 0): "er15_inlet_water",
    (0x800A, 1): "er12_exhaust",
    (0x800A, 5): "er23_leaving_water",
    (0x800B, 0): "er69_low_pressure",
    (0x800B, 2): "er33_exceed",
    (0x800B, 3): "er42_cooling_coil",
    (0x800B, 7): "er67_low_pressure",
    (0x800C, 4): "secondary_antifreeze",
    (0x800C, 5): "primary_antifreeze",
    (0x800D, 6): "er64_dc_fan_1",
    (0x800D, 7): "er65_compressor",
}
FAULT_REGS = range(0x8007, 0x800E)


def decode(reg: Reg, raw: int) -> float:
    """Raw register value -> engineering units."""
    if reg.signed and raw > 0x7FFF:
        raw -= 0x10000
    v = raw * reg.scale
    return round(v, 3)


def encode(reg: Reg, value: float) -> int:
    """Engineering units -> raw register value, for writes."""
    raw = int(round(value / reg.scale))
    return raw & 0xFFFF if raw >= 0 else (raw + 0x10000) & 0xFFFF


REG_BY_ADDR: dict[int, Reg] = {r.addr: r for r in (*STATUS, *WRITABLE)}


def by_name(name: str) -> Reg:
    """Look a register up by name. Use this rather than hardcoding an address
    and a scale at the call site - the scales are per register and getting one
    wrong produces a plausible number rather than an obvious error."""
    for reg in (*STATUS, *WRITABLE):
        if reg.name == name:
            return reg
    raise KeyError(name)
