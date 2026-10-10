import math

import pytest

from steamsuite.relief import (
    API526_ORIFICES,
    IN2_TO_MM2,
    ReliefInput,
    napier_kn,
    select_orifice,
    size_relief_valve,
)
from steamsuite.water import state_Px

PSI = 6.894757293168361
LB = 0.45359237


def test_steam_hand_calculation_us_units():
    """Saturated steam, 153,500 lb/h, set 1600 psig, 10 % overpressure.

    Hand calculation in US units with the API 520 steam equation:
    P1 = 1600 + 160 + 14.7 = 1774.7 psia
    KN = (0.1906·1774.7 − 1000)/(0.2292·1774.7 − 1061) = 1.0115
    A  = 153500 / (51.5 · 1774.7 · 0.975 · 1.0115) = 1.703 in²  → K orifice
    """
    p1 = 1774.7
    kn_us = (0.1906 * p1 - 1000) / (0.2292 * p1 - 1061)
    a_us = 153500 / (51.5 * p1 * 0.975 * kn_us)
    assert a_us == pytest.approx(1.703, abs=0.001)

    r = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=153500 * LB,
                                      set_pressure_kpag=1600 * PSI, p_atm_kpa=14.7 * PSI))
    assert r.required_area_mm2 / IN2_TO_MM2 == pytest.approx(a_us, rel=2e-3)
    assert r.coefficients["KN"] == pytest.approx(kn_us, rel=1e-3)
    assert r.orifice == "K"
    assert r.governing_method.startswith("API 520 steam")


def test_napier_kn_values():
    assert napier_kn(10339.0) == 1.0
    # the API 520 KN formula itself steps slightly at 1500 psia (0.9957)
    assert napier_kn(10340.0) == pytest.approx(0.9957, abs=0.001)
    assert napier_kn(1774.7 * PSI) == pytest.approx((0.1906 * 1774.7 - 1000) / (0.2292 * 1774.7 - 1061), rel=1e-3)


@pytest.mark.parametrize("set_barg", [1, 2, 10, 40, 100, 150])
def test_direct_integration_agrees_with_napier_for_saturated_steam(set_barg):
    """Napier's equation is empirical; theory and Napier agree within about ±3 %."""
    r = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=10000, set_pressure_kpag=set_barg * 100))
    hdi = r.cross_checks["Direct integration (HDI)"]
    assert hdi == pytest.approx(r.required_area_mm2, rel=0.04)


def test_liquid_equation_is_bernoulli_with_kd():
    W = 20000.0  # kg/h
    r = size_relief_valve(ReliefInput(fluid="water", flow_kg_h=W, set_pressure_kpag=1000, temperature_c=40))
    rho = r.relieving_state.rho
    dp = (r.relieving_pressure_kpa - 101.325) * 1000.0
    a_bernoulli = W / 3600 / (0.65 * math.sqrt(2 * rho * dp)) * 1e6
    assert r.flow_regime == "Liquid (no flashing)"
    assert r.required_area_mm2 == pytest.approx(a_bernoulli, rel=2e-3)
    assert r.cross_checks["Direct integration (HDI)"] == pytest.approx(r.required_area_mm2, rel=2e-3)


def test_hot_water_that_flashes_uses_direct_integration():
    cold = size_relief_valve(ReliefInput(fluid="water", flow_kg_h=20000, set_pressure_kpag=1000, temperature_c=40))
    hot = size_relief_valve(ReliefInput(fluid="water", flow_kg_h=20000, set_pressure_kpag=1000, temperature_c=170))
    assert "HDI" in hot.governing_method
    assert hot.required_area_mm2 > cold.required_area_mm2
    assert any("flashes" in w for w in hot.warnings)


def test_superheat_correction_reduces_capacity():
    sat = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=5000, set_pressure_kpag=1000))
    sh1 = size_relief_valve(ReliefInput(fluid="superheated_steam", flow_kg_h=5000, set_pressure_kpag=1000,
                                        temperature_c=250))
    sh2 = size_relief_valve(ReliefInput(fluid="superheated_steam", flow_kg_h=5000, set_pressure_kpag=1000,
                                        temperature_c=400))
    assert 1.0 > sh1.coefficients["KSH"] > sh2.coefficients["KSH"] > 0.7
    assert sat.required_area_mm2 < sh1.required_area_mm2 < sh2.required_area_mm2


def test_user_ksh_is_used():
    r = size_relief_valve(ReliefInput(fluid="superheated_steam", flow_kg_h=5000, set_pressure_kpag=1000,
                                      temperature_c=300, ksh=0.9))
    assert r.coefficients["KSH"] == 0.9


def test_minimum_overpressure_for_low_set_pressure():
    r = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=500, set_pressure_kpag=50))
    assert r.relieving_pressure_kpa == pytest.approx(50 + 20.7 + 101.325)


def test_fire_case_overpressure():
    r = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=500, set_pressure_kpag=1000,
                                      overpressure_basis="fire"))
    assert r.relieving_pressure_kpa == pytest.approx(1210 + 101.325)


def test_orifice_selection_boundaries():
    e_area = 0.196 * IN2_TO_MM2
    assert select_orifice(e_area)[0] == "E"
    assert select_orifice(e_area * 1.0001)[0] == "F"
    letter, area, n = select_orifice(26.0 * IN2_TO_MM2 * 2.5)
    assert (letter, n) == ("T", 3)
    assert [o[0] for o in API526_ORIFICES] == list("DEFGHJKLMNPQRT")


def test_subcritical_flow_needs_more_area_than_critical():
    crit = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=5000, set_pressure_kpag=1000))
    sub = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=5000, set_pressure_kpag=1000,
                                        back_pressure_kpag=900, valve_type="pilot"))
    assert sub.flow_regime == "Subcritical vapour flow"
    assert sub.required_area_mm2 > crit.required_area_mm2
    assert not any("Conventional valves" in w for w in sub.warnings)


def test_conventional_valve_back_pressure_warning():
    r = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=5000, set_pressure_kpag=1000,
                                      back_pressure_kpag=200))
    assert any("Conventional valves" in w for w in r.warnings)


def test_rupture_disk_combination_factor():
    a = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=5000, set_pressure_kpag=1000))
    b = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=5000, set_pressure_kpag=1000,
                                      rupture_disk=True))
    assert b.required_area_mm2 == pytest.approx(a.required_area_mm2 / 0.9)


def test_wet_steam_mass_flux_above_dry_steam():
    dry = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=5000, set_pressure_kpag=1000))
    wet = size_relief_valve(ReliefInput(fluid="wet_steam", flow_kg_h=5000, set_pressure_kpag=1000, dryness=0.8))
    g_dry = 5000 / 3600 / (0.975 * dry.cross_checks["Direct integration (HDI)"] * 1e-6)
    assert wet.nozzle.mass_flux > g_dry


@pytest.mark.parametrize("kwargs, message", [
    (dict(fluid="superheated_steam", temperature_c=150), "not superheated"),
    (dict(fluid="water", temperature_c=200), "boiling"),
    (dict(fluid="saturated_steam", back_pressure_kpag=1200), "back pressure"),
    (dict(fluid="wet_steam", dryness=1.2), "dryness"),
])
def test_invalid_inputs_give_clear_errors(kwargs, message):
    base = dict(flow_kg_h=5000, set_pressure_kpag=1000)
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        size_relief_valve(ReliefInput(**base))


def test_report_contains_every_step():
    r = size_relief_valve(ReliefInput(fluid="superheated_steam", flow_kg_h=5000, set_pressure_kpag=1000,
                                      temperature_c=300, tag="PSV-101"))
    md = r.report.to_markdown()
    html = r.report.to_html()
    for text in ("Relieving pressure", "Napier", "K_{SH}", "Select a standard orifice", "API Standard 520"):
        assert text in md
    assert "katex" in html and "PSV-101" in html
    assert len(r.report.steps) >= 7


def test_nozzle_flux_matches_incompressible_bernoulli_for_cold_water():
    from steamsuite.relief import isentropic_nozzle_flow
    from steamsuite.water import state_PT
    st = state_PT(1000.0, 20.0)
    noz = isentropic_nozzle_flow(st, 101.325)
    assert not noz.choked
    assert noz.mass_flux == pytest.approx(math.sqrt(2 * st.rho * (1000.0 - 101.325) * 1000), rel=2e-3)


def test_choked_steam_critical_pressure_ratio():
    from steamsuite.relief import isentropic_nozzle_flow
    noz = isentropic_nozzle_flow(state_Px(1000.0, 1.0), 101.325)
    assert noz.choked
    assert 0.55 < noz.throat_pressure / 1000.0 < 0.60
