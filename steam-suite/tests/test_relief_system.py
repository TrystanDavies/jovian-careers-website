"""API 521 scenarios, inlet loss, built-up back pressure and reaction force."""

import math

import pytest

from steamsuite.examples import barg, steam_distribution
from steamsuite.flowsheet.advanced import ReliefValveUnit
from steamsuite.hydraulics import fittings_k, pipe_dimensions, pipe_flow, sound_speed, valve_flow
from steamsuite.relief import ReliefInput, isentropic_nozzle_flow, select_orifice, size_relief_valve
from steamsuite.relief_system import LineSpec, size_relief_system
from steamsuite.scenarios import run_scenario
from steamsuite.water import T_sat, state_Ph, state_PT, state_Px

SET = 1000.0  # kPa(g)
P1 = SET * 1.10 + 101.325
P1_FIRE = SET * 1.21 + 101.325


def latent(P):
    return state_Px(P, 1.0).h - state_Px(P, 0.0).h


def test_fire_case_vertical_vessel_hand_calculation():
    r = run_scenario({"type": "fire", "orientation": "Vertical", "diameter": 2.0, "length": 4.0, "level": 1.5,
                      "elevation": 0.0}, P1_FIRE)
    A = math.pi * 2.0 * 1.5 + math.pi * 2.0**2 / 4.0
    Q = 43.2 * 1.0 * A**0.82
    assert r.rate_kg_h == pytest.approx(Q / latent(P1_FIRE) * 3600.0, rel=1e-9)
    assert r.fluid == "saturated_steam" and r.overpressure_basis == "fire"


def test_fire_case_horizontal_vessel_and_fire_zone():
    # half full: wetted area is half the shell plus half of each end
    r = run_scenario({"type": "fire", "orientation": "Horizontal", "diameter": 2.0, "length": 6.0, "level": 1.0,
                      "drainage": "No"}, P1_FIRE)
    A = math.pi * 2.0 * 6.0 / 2.0 + math.pi * 2.0**2 / 4.0
    assert r.rate_kg_h == pytest.approx(70.9 * A**0.82 / latent(P1_FIRE) * 3600.0, rel=1e-9)
    # a vertical vessel standing 7 m above grade: only 0.6 m of its wetted wall is in the fire zone
    high = run_scenario({"type": "fire", "diameter": 2.0, "length": 4.0, "level": 2.0, "elevation": 7.0}, P1_FIRE)
    A = math.pi * 2.0 * 0.6 + math.pi
    assert high.rate_kg_h == pytest.approx(43.2 * A**0.82 / latent(P1_FIRE) * 3600.0, rel=1e-6)
    env = run_scenario({"type": "fire", "wetted_area": 20.0, "environment": "Fire-proof insulation: enter F",
                        "f_factor": 0.3}, P1_FIRE)
    assert env.rate_kg_h == pytest.approx(43.2 * 0.3 * 20.0**0.82 / latent(P1_FIRE) * 3600.0, rel=1e-9)


def test_control_valve_failure_uses_the_valve_equations():
    spec = {"type": "cv_failure", "upstream_pressure": barg(16), "condition": "Saturated steam", "cv": 40.0,
            "bypass_open": "Yes", "bypass_cv": 10.0, "credit": 0.5}
    r = run_scenario(spec, P1)
    up = state_Px(barg(16), 1.0)
    assert r.rate_kg_h == pytest.approx(valve_flow(up, P1, 50.0) * 3600.0 - 1800.0, rel=1e-9)
    down = state_Ph(P1, up.h)  # throttled: superheated a little
    assert r.fluid == "superheated_steam" and r.temperature_c == pytest.approx(down.T)
    low = run_scenario({**spec, "upstream_pressure": P1 - 10}, P1)
    assert not low.applies and low.rate_kg_h == 0.0


def test_blocked_outlet_pump_on_its_curve():
    spec = {"type": "blocked_outlet", "source": "Pump (curve)", "suction_pressure": 201.325,
            "suction_temperature": 105.0, "shutoff_head": 150.0, "rated_flow": 20.0, "rated_head": 120.0}
    r = run_scenario(spec, P1)
    st = state_PT(201.325, 105.0)
    H = (P1 - 201.325) * 1000 / (st.rho * 9.80665)
    q = 20.0 * math.sqrt((150.0 - H) / 30.0)
    assert r.rate_kg_h == pytest.approx(q * st.rho, rel=1e-9) and r.fluid == "water"
    weak = run_scenario({**spec, "shutoff_head": 50.0}, P1)
    assert not weak.applies


def test_tube_rupture_two_orifices_and_the_10_13_rule():
    spec = {"type": "tube_rupture", "hp_design": 3000.0, "lp_design": 1000.0, "upstream_pressure": barg(25),
            "condition": "Water", "temperature": 150.0, "tube_id": 15.75, "cd": 0.7}
    r = run_scenario(spec, P1)
    G = isentropic_nozzle_flow(state_PT(barg(25), 150.0), P1).mass_flux
    assert r.rate_kg_h == pytest.approx(2 * 0.7 * math.pi * 0.01575**2 / 4 * G * 3600.0, rel=1e-9)
    assert r.applies
    excluded = run_scenario({**spec, "lp_design": 2400.0}, P1)  # 2400 ≥ 10/13 × 3000 = 2308
    assert not excluded.applies


def test_thermal_expansion_from_iapws_expansion_coefficient():
    r = run_scenario({"type": "thermal", "heat_input": 50.0, "temperature": 40.0}, P1)
    st = state_PT(P1, 40.0)
    alpha = -(state_PT(P1, 40.01).rho - state_PT(P1, 39.99).rho) / 0.02 / st.rho
    assert alpha == pytest.approx(3.9e-4, rel=0.05)  # water near 40 °C
    assert r.rate_kg_h == pytest.approx(alpha * 50.0 / st.cp * 3600.0, rel=1e-4)


def test_abnormal_heat_input():
    r = run_scenario({"type": "heat_input", "ua": 30.0, "heating_temperature": 220.0}, P1)
    assert r.rate_kg_h == pytest.approx(30.0 * (220.0 - T_sat(P1)) / latent(P1) * 3600.0, rel=1e-9)


def test_largest_area_governs_and_each_scenario_uses_its_own_overpressure():
    base = ReliefInput(fluid="saturated_steam", flow_kg_h=1.0, set_pressure_kpag=SET)
    scen = [{"type": "given", "flow": 1.0},  # 3600 kg/h saturated steam at 10 % overpressure
            {"type": "fire", "wetted_area": 60.0}]  # about 2000 kg/h at 21 % overpressure
    res = size_relief_system(base, scen)
    gov = res.governing
    assert gov.scenario.key == "given"
    fire = next(z for z in res.sizings if z.scenario.key == "fire")
    assert fire.relief.relieving_pressure_kpa == pytest.approx(P1_FIRE)
    direct = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=3600.0, set_pressure_kpag=SET))
    assert gov.relief.required_area_mm2 == pytest.approx(direct.required_area_mm2, rel=1e-9)
    assert res.orifice == select_orifice(direct.required_area_mm2)[0]
    big_fire = size_relief_system(base, [scen[0], {"type": "fire", "wetted_area": 400.0}])
    assert big_fire.governing.scenario.key == "fire"


def test_inlet_loss_is_the_non_recoverable_pressure_drop_at_rated_flow():
    base = ReliefInput(fluid="saturated_steam", flow_kg_h=10000.0, set_pressure_kpag=SET)
    line = LineSpec("4", "40", length=2.0, fittings={"entrance_sharp": 1, "elbow_90_lr": 1})
    res = size_relief_system(base, inlet=line)
    gov = res.governing
    d = pipe_dimensions("4", "40")[0]
    k, _ = fittings_k(line.fittings, d)
    r = pipe_flow(gov.rated_kg_h / 3600.0, P1, state_Px(P1, 1.0).h, d, 2.0, 0.045, 0.0, k)
    assert gov.inlet.percent == pytest.approx((r.dp_friction + r.dp_fittings) / SET * 100.0, rel=1e-9)
    assert gov.rated_kg_h > 10000.0  # rated capacity, not the required rate
    small = size_relief_system(base, inlet=LineSpec("3", "40", length=5.0, fittings={"entrance_sharp": 1}))
    assert not small.governing.inlet.ok and any("3 %" in w for w in small.warnings)


def test_choked_discharge_line_and_reaction_force():
    base = ReliefInput(fluid="saturated_steam", flow_kg_h=10000.0, set_pressure_kpag=SET)
    res = size_relief_system(base, outlet=LineSpec("4", "40", length=10.0, fittings={"elbow_90_lr": 1}))
    dis = res.governing.discharge
    assert dis.choked_exit and dis.P_exit > 101.325
    assert dis.v_exit == pytest.approx(sound_speed(dis.exit_state), rel=0.02)  # Mach 1 at the exit
    m = dis.flow_kg_h / 3600.0
    F = m * dis.v_exit + (dis.P_exit - 101.325) * 1000.0 * dis.area_m2
    assert res.reaction.force_n == pytest.approx(F, rel=1e-12)
    assert res.reaction.api_force_n == pytest.approx(F, rel=0.15)  # ideal-gas formula, same order
    # the sizing was repeated with the built-up back pressure
    assert res.governing.back_pressure_kpag == pytest.approx(dis.built_up, rel=1e-6, abs=0.5)


def test_unchoked_discharge_reaches_the_destination_pressure():
    base = ReliefInput(fluid="saturated_steam", flow_kg_h=10000.0, set_pressure_kpag=SET)
    res = size_relief_system(base, outlet=LineSpec("8", "40", length=10.0), outlet_to="header",
                             superimposed_kpag=50.0)
    dis = res.governing.discharge
    assert not dis.choked_exit
    assert dis.P_exit == pytest.approx(151.325, rel=1e-6)
    assert res.governing.back_pressure_kpag == pytest.approx(50.0 + dis.built_up, rel=1e-6)
    assert res.reaction is None  # closed discharge to a header


def test_built_up_back_pressure_limit_follows_the_overpressure():
    line = LineSpec("4", "40", length=10.0, fittings={"elbow_90_lr": 1})
    single = size_relief_system(ReliefInput(fluid="saturated_steam", flow_kg_h=7000.0, set_pressure_kpag=SET),
                                outlet=line)
    pct = single.governing.discharge.built_up / SET * 100.0
    assert 10.0 < pct < 21.0, pct  # between the two limits for this test to mean something
    assert any("built-up back pressure" in w and "10.0 %" in w for w in single.warnings)
    fire = size_relief_system(ReliefInput(fluid="saturated_steam", flow_kg_h=7000.0, set_pressure_kpag=SET,
                                          overpressure_basis="fire"), outlet=line)
    assert not any("built-up back pressure is" in w for w in fire.warnings)


def test_psv_on_the_drawing_with_scenarios_from_the_equipment():
    fs = steam_distribution()
    psv = fs.blocks["PSV-101"]
    pcv = next(n for n, b in fs.blocks.items() if b.TYPE == "valve" and b.p("cv") > 0)
    psv.params.update({"rate_mode": "Scenarios (API 521)",
                       "scenarios": [{"type": "cv_failure", "valve": pcv},
                                     {"type": "fire", "wetted_area": 15.0}],
                       "inlet_line": "Pipe", "inlet_nps": "3",
                       "outlet_line": "Pipe to atmosphere", "outlet_nps": "6", "outlet_length": 8.0})
    res = fs.solve()
    assert res.converged, res.errors
    r = psv.results
    assert r["governing"].value.startswith("Control valve fails open")
    up = fs.streams[fs.blocks[pcv].inlets["in"]]
    expected = valve_flow(up.state, r["P1"].value, fs.blocks[pcv].p("cv"), 0.9, 0.7)
    assert r["rate"].value == pytest.approx(expected, rel=1e-6)
    for key in ("inlet_loss", "built_up", "reaction"):
        assert key in r
    assert any(s.title == "Relief scenarios" for s in psv.steps)
