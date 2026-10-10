import pytest

from steamsuite.units import (
    UnitSystem,
    fmt,
    gauge_variant,
    pressure_from_kpa_abs,
    pressure_to_kpa_abs,
    temperature_from_c,
    temperature_to_c,
)


@pytest.mark.parametrize("value, unit, expected", [
    (10.0, "bar(g)", 1101.325),
    (10.0, "bar(a)", 1000.0),
    (100.0, "psig", 100 * 6.894757293168361 + 101.325),
    (1.0, "MPa(a)", 1000.0),
    (0.0, "kPa(g)", 101.325),
])
def test_pressure_conversion_round_trip(value, unit, expected):
    kpa = pressure_to_kpa_abs(value, unit)
    assert kpa == pytest.approx(expected)
    assert pressure_from_kpa_abs(kpa, unit) == pytest.approx(value)


def test_temperature_conversion():
    assert temperature_to_c(212.0, "°F") == pytest.approx(100.0)
    assert temperature_from_c(0.0, "K") == pytest.approx(273.15)


def test_gauge_variant():
    assert gauge_variant("bar(a)") == "bar(g)"
    assert gauge_variant("psia") == "psig"


def test_unit_system_mass_flow():
    u = UnitSystem(mass_flow="t/h")
    assert u.m_in(3.6) == pytest.approx(1.0)
    assert u.m_out(1.0) == pytest.approx(3.6)


def test_fmt():
    assert fmt(1234.5678) == "1,235"
    assert fmt(0.012345) == "0.01235"
    assert fmt(None) == "—"
