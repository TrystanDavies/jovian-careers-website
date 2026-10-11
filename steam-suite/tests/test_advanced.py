import math

import pytest

from steamsuite.examples import barg
from steamsuite.flowsheet import Flowsheet
from steamsuite.flowsheet.advanced import Adjust, HeatExchanger, Pipe, ReliefValveUnit
from steamsuite.flowsheet.blocks import Compressor, Feed, Pump, Valve
from steamsuite.relief import ReliefInput, size_relief_valve
from steamsuite.water import T_sat, state_Px, state_PT


def steam_line():
    fs = Flowsheet("steam line")
    fs.add(Feed("Supply", outlets={"out": "S1"},
                params={"pressure": barg(10), "condition": "Dryness fraction", "dryness": 1.0, "flow": 10 / 3.6}))
    fs.add(Pipe("Main", inlets={"in": "S1"}, outlets={"out": "S2"},
                params={"nps": "6", "length": 150.0, "fittings": {"elbow_90_lr": 6, "gate": 2}}))
    fs.add(Valve("PCV", inlets={"in": "S2"}, outlets={"out": "S3"}, params={"outlet_pressure": barg(4), "cv": 120}))
    return fs


def test_pipe_block_in_flowsheet_balances():
    fs = steam_line()
    fs.blocks["Main"].params.update({"heat_loss": "Insulated", "elevation": 5.0})
    res = fs.solve()
    assert res.converged, res.errors
    assert abs(res.balance["energy_error"]) < 1e-6
    main = fs.blocks["Main"].results
    assert main["dP"].value == pytest.approx(fs.streams["S1"].P - fs.streams["S2"].P)
    assert main["dP"].value == pytest.approx(
        main["dp_f"].value + main["dp_k"].value + main["dp_s"].value + main["dp_a"].value, rel=1e-9)
    assert main["q_loss"].value > 0
    assert "Profile along the pipe" in fs.blocks["Main"].charts


def test_valve_reports_cv_and_opening():
    fs = steam_line()
    fs.solve()
    v = fs.blocks["PCV"].results
    assert 0 < v["cv"].value < 120
    assert 0 < v["opening"].value < 100


def test_valve_cv_mode_gives_back_the_pressure():
    fs = steam_line()
    fs.solve()
    cv = fs.blocks["PCV"].results["cv"].value
    p3 = fs.streams["S3"].P
    fs.blocks["PCV"].params.update({"mode": "Cv and opening", "cv": cv, "opening": 100.0, "characteristic": "Linear"})
    fs.solve()
    assert fs.streams["S3"].P == pytest.approx(p3, rel=1e-6)


def test_relief_valve_block_matches_direct_sizing():
    fs = steam_line()
    fs.add(ReliefValveUnit("PSV", params={"stream": "S3", "set_pressure": barg(6), "rate_factor": 1.0}))
    res = fs.solve()
    assert res.converged, res.errors
    psv = fs.blocks["PSV"].results
    st = fs.streams["S3"].state
    # the stream (≈166 °C) is not superheated at the relieving pressure (6 bar g + 10 %), so: saturated steam
    assert st.T < T_sat(600.0 + 60.0 + 101.325)
    direct = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=10000.0, set_pressure_kpag=600.0))
    assert psv["area"].value == pytest.approx(direct.required_area_mm2, rel=1e-6)
    assert psv["orifice"].value == direct.orifice
    assert len(fs.blocks["PSV"].steps) >= 6


def test_adjust_with_limits_meets_target():
    fs = steam_line()
    fs.add(Adjust("ADJ", params={"var_block": "Supply", "var_param": "pressure", "target_type": "Stream property",
                                 "target_stream": "S2", "target_property": "Pressure", "target_value": barg(9.0),
                                 "lower": barg(9.0), "upper": barg(15.0)}))
    res = fs.solve()
    assert res.converged, res.errors
    assert fs.streams["S2"].P == pytest.approx(barg(9.0), rel=1e-7)
    assert fs.blocks["ADJ"].results["evaluations"].value >= 3


def test_adjust_secant_without_limits():
    fs = Flowsheet("pump")
    fs.add(Feed("W", outlets={"out": "a"}, params={"pressure": 200.0, "temperature": 40.0, "flow": 5.0}))
    fs.add(Pump("P", inlets={"in": "a"}, outlets={"out": "b"}, params={"outlet_pressure": 800.0}))
    fs.add(Adjust("ADJ", params={"var_block": "P", "var_param": "outlet_pressure", "target_type": "Equipment result",
                                 "target_block": "P", "target_result": "power", "target_value": 5.0}))
    res = fs.solve()
    assert res.converged, res.errors
    assert fs.blocks["P"].results["power"].value == pytest.approx(5.0, rel=1e-5)


def test_adjust_reports_impossible_target():
    fs = steam_line()
    fs.add(Adjust("ADJ", params={"var_block": "Supply", "var_param": "pressure", "target_type": "Stream property",
                                 "target_stream": "S2", "target_property": "Pressure", "target_value": barg(30.0),
                                 "lower": barg(9.0), "upper": barg(15.0)}))
    res = fs.solve()
    assert any("No solution between the limits" in e for e in res.errors)


def hx_flowsheet(spec, **params):
    fs = Flowsheet("hx")
    fs.add(Feed("Hot", outlets={"out": "H1"}, params={"pressure": 300.0, "temperature": 90.0, "flow": 2.0}))
    fs.add(Feed("Cold", outlets={"out": "C1"}, params={"pressure": 300.0, "temperature": 20.0, "flow": 3.0}))
    p = {"spec": spec}
    p.update(params)
    fs.add(HeatExchanger("HX", inlets={"hot_in": "H1", "cold_in": "C1"}, outlets={"hot_out": "H2", "cold_out": "C2"},
                         params=p))
    return fs


def test_heat_exchanger_water_water_matches_lmtd():
    fs = hx_flowsheet("Hot outlet temperature", hot_T=50.0)
    res = fs.solve()
    assert res.converged, res.errors
    r = fs.blocks["HX"].results
    q = 2.0 * (state_PT(300, 90).h - state_PT(300, 50).h)
    assert r["duty"].value == pytest.approx(q)
    tco = fs.streams["C2"].state.T
    lmtd = ((90 - tco) - (50 - 20)) / math.log((90 - tco) / (50 - 20))
    assert r["ua"].value == pytest.approx(q / lmtd, rel=2e-3)  # small difference: cp varies with temperature
    assert abs(res.balance["energy_error"]) < 1e-6


def test_heat_exchanger_ua_rating_inverts_design():
    design = hx_flowsheet("Hot outlet temperature", hot_T=50.0)
    design.solve()
    ua = design.blocks["HX"].results["ua"].value
    rating = hx_flowsheet("UA (rating)", ua=ua)
    rating.solve()
    assert rating.streams["H2"].state.T == pytest.approx(50.0, abs=0.05)


def test_heat_exchanger_temperature_cross_is_an_error():
    fs = hx_flowsheet("Cold outlet temperature", cold_T=95.0)
    res = fs.solve()
    assert any("Temperature cross" in e for e in res.errors)


def test_condensing_heater_finds_steam_flow():
    fs = Flowsheet("heater")
    fs.add(Feed("Steam", outlets={"out": "H1"}, params={"pressure": barg(3), "condition": "Dryness fraction",
                                                       "dryness": 1.0, "flow_mode": "As required"}))
    fs.add(Feed("Water", outlets={"out": "C1"}, params={"pressure": barg(5), "temperature": 40.0, "flow": 5.0}))
    fs.add(HeatExchanger("HX", inlets={"hot_in": "H1", "cold_in": "C1"}, outlets={"hot_out": "H2", "cold_out": "C2"},
                         params={"spec": "Condensing heater (hot flow as required)", "cold_T": 120.0}))
    res = fs.solve()
    assert res.converged, res.errors
    q = 5.0 * (state_PT(barg(5), 120.0).h - state_PT(barg(5), 40.0).h)
    hfg = state_Px(barg(3), 1.0).h - state_Px(barg(3), 0.0).h
    assert fs.streams["H1"].m == pytest.approx(q / hfg, rel=1e-8)
    assert fs.streams["H2"].state.T == pytest.approx(T_sat(barg(3)), abs=1e-6)


def test_pump_curve_operating_point():
    fs = Flowsheet("pump")
    fs.add(Feed("W", outlets={"out": "a"}, params={"pressure": 200.0, "temperature": 60.0, "flow": 5.0}))
    fs.add(Pump("P", inlets={"in": "a"}, outlets={"out": "b"},
                params={"mode": "Pump curve", "shutoff_head": 150.0, "rated_flow": 20.0, "rated_head": 120.0,
                        "npshr": 30.0}))
    res = fs.solve()
    r = fs.blocks["P"].results
    q = r["flow_vol"].value
    assert r["head"].value == pytest.approx(150 - 30 * (q / 20) ** 2, rel=1e-6)
    assert any("NPSH" in w for w in res.warnings)


def test_compressor():
    fs = Flowsheet("mvr")
    fs.add(Feed("V", outlets={"out": "a"}, params={"pressure": 101.325, "condition": "Dryness fraction",
                                                  "dryness": 1.0, "flow": 1.0}))
    fs.add(Compressor("K", inlets={"in": "a"}, outlets={"out": "b"}, params={"outlet_pressure": 200.0,
                                                                           "efficiency": 100.0}))
    fs.solve()
    assert fs.streams["b"].state.s == pytest.approx(fs.streams["a"].state.s, abs=1e-6)
    assert fs.streams["b"].state.phase == "vapour"


def test_case_study_and_layout_round_trip():
    fs = steam_line()
    fs.layout = {"nodes": {"Main": {"x": 100, "y": 50}}}
    rows = fs.case_study("Supply", "flow", [1.0, 2.0, 3.0],
                         [{"type": "Equipment result", "object": "Main", "property": "dP"}])
    dps = [r["outputs"][0] for r in rows]
    assert dps[0] < dps[1] < dps[2]
    assert fs.blocks["Supply"].params["flow"] == pytest.approx(10 / 3.6)
    fs2 = Flowsheet.from_json(fs.to_json())
    assert fs2.layout == fs.layout


def test_pipe_block_compares_two_phase_methods_and_reports_choking():
    fs = Flowsheet("wet line")
    fs.add(Feed("Wet", outlets={"out": "W1"}, params={"pressure": 300.0, "condition": "Dryness fraction",
                                                     "dryness": 0.1, "flow": 0.5}))
    fs.add(Pipe("Riser", inlets={"in": "W1"}, outlets={"out": "W2"},
                params={"nps": "3", "length": 20.0, "elevation": 5.0, "void_model": "Drift flux (Rouhani–Axelsson)",
                        "tp_factor": 1.3}))
    res = fs.solve()
    assert res.converged, res.errors
    blk = fs.blocks["Riser"]
    titles = [s.title for s in blk.steps]
    assert "Two-phase methods compared" in titles and "Void fraction (static head and acceleration)" in titles
    assert blk.results["tp_spread"].value > 0
    # a far too small pipe: a clear choking message, not a numerical failure
    blk.params.update({"nps": "1", "length": 100.0})
    res = fs.solve()
    assert any("choked" in e and "speed of sound" in e for e in res.errors)
