"""Unit conversions.

Everything inside the library uses one fixed set of units so calculations
never mix them up:

    pressure      kPa (absolute)
    temperature   °C
    mass flow     kg/s
    enthalpy      kJ/kg
    entropy       kJ/(kg·K)
    power / duty  kW
    density       kg/m³
    area          mm²

The user interface converts to and from whatever units the user picks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

P_ATM_KPA = 101.325  # standard atmosphere

# --- pressure ---------------------------------------------------------------

PRESSURE_FACTORS = {  # kPa per unit
    "kPa": 1.0,
    "bar": 100.0,
    "MPa": 1000.0,
    "psi": 6.894757293168361,
}

PRESSURE_UNITS = ["bar(g)", "bar(a)", "kPa(g)", "kPa(a)", "MPa(g)", "MPa(a)", "psig", "psia"]


def _split_pressure_unit(unit: str) -> tuple[str, bool]:
    """Return (base unit, is_gauge) for a unit such as 'bar(g)' or 'psia'."""
    if unit in ("psig", "psia"):
        return "psi", unit == "psig"
    if unit.endswith("(g)"):
        return unit[:-3], True
    if unit.endswith("(a)"):
        return unit[:-3], False
    if unit in PRESSURE_FACTORS:
        return unit, False
    raise ValueError(f"Unknown pressure unit: {unit}")


def pressure_to_kpa_abs(value: float, unit: str, p_atm: float = P_ATM_KPA) -> float:
    base, gauge = _split_pressure_unit(unit)
    kpa = value * PRESSURE_FACTORS[base]
    return kpa + p_atm if gauge else kpa


def pressure_from_kpa_abs(value: float, unit: str, p_atm: float = P_ATM_KPA) -> float:
    base, gauge = _split_pressure_unit(unit)
    kpa = value - p_atm if gauge else value
    return kpa / PRESSURE_FACTORS[base]


def pressure_diff_to_kpa(value: float, unit: str) -> float:
    base, _ = _split_pressure_unit(unit)
    return value * PRESSURE_FACTORS[base]


def pressure_diff_from_kpa(value: float, unit: str) -> float:
    base, _ = _split_pressure_unit(unit)
    return value / PRESSURE_FACTORS[base]


def pressure_diff_label(unit: str) -> str:
    base, _ = _split_pressure_unit(unit)
    return base


def gauge_variant(unit: str) -> str:
    base, _ = _split_pressure_unit(unit)
    return "psig" if base == "psi" else f"{base}(g)"


def abs_variant(unit: str) -> str:
    base, _ = _split_pressure_unit(unit)
    return "psia" if base == "psi" else f"{base}(a)"


# --- temperature ------------------------------------------------------------

TEMPERATURE_UNITS = ["°C", "°F", "K"]


def temperature_to_c(value: float, unit: str) -> float:
    if unit == "°C":
        return value
    if unit == "°F":
        return (value - 32.0) * 5.0 / 9.0
    if unit == "K":
        return value - 273.15
    raise ValueError(f"Unknown temperature unit: {unit}")


def temperature_from_c(value: float, unit: str) -> float:
    if unit == "°C":
        return value
    if unit == "°F":
        return value * 9.0 / 5.0 + 32.0
    if unit == "K":
        return value + 273.15
    raise ValueError(f"Unknown temperature unit: {unit}")


def temperature_diff_to_c(value: float, unit: str) -> float:
    return value * 5.0 / 9.0 if unit == "°F" else value


def temperature_diff_from_c(value: float, unit: str) -> float:
    return value * 9.0 / 5.0 if unit == "°F" else value


def temperature_diff_label(unit: str) -> str:
    return {"°C": "°C", "°F": "°F", "K": "K"}[unit]


# --- simple multiplicative units -------------------------------------------

MASS_FLOW_FACTORS = {  # kg/s per unit
    "t/h": 1000.0 / 3600.0,
    "kg/h": 1.0 / 3600.0,
    "kg/s": 1.0,
    "lb/h": 0.45359237 / 3600.0,
}
POWER_FACTORS = {  # kW per unit
    "kW": 1.0,
    "MW": 1000.0,
    "hp": 0.745699872,
    "Btu/h": 0.00029307107,
}
ENTHALPY_FACTORS = {"kJ/kg": 1.0, "Btu/lb": 2.326}
ENTROPY_FACTORS = {"kJ/(kg·K)": 1.0, "Btu/(lb·°F)": 4.1868}
DENSITY_FACTORS = {"kg/m³": 1.0, "lb/ft³": 16.018463}
AREA_FACTORS = {"mm²": 1.0, "cm²": 100.0, "in²": 645.16}
VOLUME_FACTORS = {"m³/kg": 1.0, "ft³/lb": 0.062427961}


def convert_to(value: float, unit: str, factors: dict[str, float]) -> float:
    """Convert from `unit` to the internal unit."""
    return value * factors[unit]


def convert_from(value: float, unit: str, factors: dict[str, float]) -> float:
    """Convert from the internal unit to `unit`."""
    return value / factors[unit]


# --- unit system used by the user interface ---------------------------------


@dataclass
class UnitSystem:
    """The units the user has chosen for input and display."""

    pressure: str = "bar(g)"
    temperature: str = "°C"
    mass_flow: str = "t/h"
    power: str = "kW"
    enthalpy: str = "kJ/kg"
    entropy: str = "kJ/(kg·K)"
    density: str = "kg/m³"
    area: str = "mm²"
    p_atm: float = P_ATM_KPA

    # pressure (absolute internally)
    def p_in(self, v: float, unit: str | None = None) -> float:
        return pressure_to_kpa_abs(v, unit or self.pressure, self.p_atm)

    def p_out(self, v: float, unit: str | None = None) -> float:
        return pressure_from_kpa_abs(v, unit or self.pressure, self.p_atm)

    def dp_in(self, v: float) -> float:
        return pressure_diff_to_kpa(v, self.pressure)

    def dp_out(self, v: float) -> float:
        return pressure_diff_from_kpa(v, self.pressure)

    @property
    def dp_label(self) -> str:
        return pressure_diff_label(self.pressure)

    @property
    def p_gauge(self) -> str:
        return gauge_variant(self.pressure)

    @property
    def p_abs(self) -> str:
        return abs_variant(self.pressure)

    # temperature
    def t_in(self, v: float) -> float:
        return temperature_to_c(v, self.temperature)

    def t_out(self, v: float) -> float:
        return temperature_from_c(v, self.temperature)

    def dt_in(self, v: float) -> float:
        return temperature_diff_to_c(v, self.temperature)

    def dt_out(self, v: float) -> float:
        return temperature_diff_from_c(v, self.temperature)

    # others
    def m_in(self, v: float) -> float:
        return convert_to(v, self.mass_flow, MASS_FLOW_FACTORS)

    def m_out(self, v: float) -> float:
        return convert_from(v, self.mass_flow, MASS_FLOW_FACTORS)

    def q_in(self, v: float) -> float:
        return convert_to(v, self.power, POWER_FACTORS)

    def q_out(self, v: float) -> float:
        return convert_from(v, self.power, POWER_FACTORS)

    def h_out(self, v: float) -> float:
        return convert_from(v, self.enthalpy, ENTHALPY_FACTORS)

    def s_out(self, v: float) -> float:
        return convert_from(v, self.entropy, ENTROPY_FACTORS)

    def rho_out(self, v: float) -> float:
        return convert_from(v, self.density, DENSITY_FACTORS)

    def a_out(self, v: float) -> float:
        return convert_from(v, self.area, AREA_FACTORS)


UNIT_PRESETS = {
    "Metric (bar g, °C, t/h)": UnitSystem(),
    "SI (kPa a, °C, kg/s)": UnitSystem(pressure="kPa(a)", mass_flow="kg/s"),
    "US customary (psig, °F, lb/h)": UnitSystem(
        pressure="psig",
        temperature="°F",
        mass_flow="lb/h",
        power="hp",
        enthalpy="Btu/lb",
        entropy="Btu/(lb·°F)",
        density="lb/ft³",
        area="in²",
    ),
}


# --- number formatting --------------------------------------------------------


def fmt(value: float | None, sig: int = 4, sep: bool = True) -> str:
    """Format a number to roughly `sig` significant figures, without
    scientific notation for everyday magnitudes."""
    if value is None:
        return "—"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "—"
    if value == 0:
        return "0"
    mag = math.floor(math.log10(abs(value)))
    if mag >= 9 or mag <= -5:
        return f"{value:.{sig - 1}e}"
    decimals = max(0, sig - 1 - mag)
    text = f"{value:,.{decimals}f}" if sep else f"{value:.{decimals}f}"
    return text
