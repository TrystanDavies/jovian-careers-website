"""Pressure–flow mode: flows found from the hydraulics."""

import math

import pytest
from scipy.optimize import brentq

from steamsuite.examples import EXAMPLES, barg
from steamsuite.flowsheet import Flowsheet
from steamsuite.flowsheet.advanced import HeatExchanger, Pipe, Specification
from steamsuite.flowsheet.blocks import (
    Boiler,
    CheckValve,
    Condenser,
    Feed,
    FlashVessel,
    Heater,
    Mixer,
    Pump,
    Sink,
    Splitter,
    SteamUser,
    Turbine,
    Valve,
)
from steamsuite.hydraulics import pipe_dimensions, pipe_flow, valve_flow
from steamsuite.water import state_Ph, state_PT, state_Px

PD = {"mode": "Pressure-driven"}


def pf(name="test") -> Flowsheet:
    fs = Flowsheet(name)
    fs.solver_mode = "pressure_flow"
    return fs


def assert_balanced(res):
    assert res.converged, res.errors
    assert abs(res.balance["mass_error"]) < 1e-8
    assert abs(res.balance["energy_error"]) < 1e-5


def parallel_pipes(len_a=50.0, len_b=150.0):
    fs = pf("parallel")
    fs.add(Feed("Supply", outlets={"out": "S1"}, params={"pressure": 500.0, "temperature": 20.0,
                                                        "flow_mode": "As required"}))
    fs.add(Splitter("Tee", inlets={"in": "S1"}, outlets={"out": ["A1", "B1"]},
                    params={"outlet_specs": {"A1": PD, "B1": PD}}))
    fs.add(Pipe("A", inlets={"in": "A1"}, outlets={"out": "A2"}, params={"nps": "2", "length": len_a}))
    fs.add(Pipe("B", inlets={"in": "B1"}, outlets={"out": "B2"}, params={"nps": "2", "length": len_b}))
    fs.add(Mixer("Join", inlets={"in": ["A2", "B2"]}, outlets={"out": "S2"},
                 params={"pressure_mode": "Equal pressures (junction)"}))
    fs.add(Pipe("C", inlets={"in": "S2"}, outlets={"out": "S3"}, params={"nps": "3", "length": 30.0}))
    fs.add(Sink("Out", inlets={"in": "S3"}, params={"pressure": 200.0}))
    return fs


def test_equal_parallel_pipes_share_flow_equally():
    fs = parallel_pipes(80.0, 80.0)
    res = fs.solve()
    assert_balanced(res)
    assert fs.streams["A1"].m == pytest.approx(fs.streams["B1"].m, rel=1e-9)


def test_unequal_parallel_pipes_have_equal_pressure_drop():
    fs = parallel_pipes(50.0, 150.0)
    res = fs.solve()
    assert_balanced(res)
    a, b = fs.blocks["A"].results, fs.blocks["B"].results
    assert a["dP"].value == pytest.approx(b["dP"].value, rel=1e-6)
    ratio = fs.streams["A1"].m / fs.streams["B1"].m
    # Darcy–Weisbach: ΔP ∝ f·L·m², so m_A/m_B = √(L_B f_B / L_A f_A) ≈ √3, a little more as f falls with Re
    assert 1.70 < ratio < 1.85
    assert fs.streams["S3"].P == pytest.approx(200.0, abs=1e-6)
    # the solution satisfies each pipe exactly: recompute one directly
    st = state_Ph(500.0, fs.streams["A1"].h)
    direct = pipe_flow(fs.streams["A1"].m, 500.0, st.h, pipe_dimensions("2", "40")[0], 50.0, segments=20)
    assert fs.streams["A2"].P == pytest.approx(direct.P_out, rel=1e-8)


def test_pump_curve_meets_system_curve():
    fs = pf("pump")
    fs.add(Feed("Tank", outlets={"out": "W1"}, params={"pressure": 101.325, "temperature": 30.0,
                                                      "flow_mode": "As required"}))
    fs.add(Pump("P-1", inlets={"in": "W1"}, outlets={"out": "W2"},
                params={"mode": "Pump curve", "shutoff_head": 60.0, "rated_flow": 50.0, "rated_head": 45.0}))
    fs.add(Pipe("L-1", inlets={"in": "W2"}, outlets={"out": "W3"},
                params={"nps": "3", "length": 200.0, "elevation": 10.0}))
    fs.add(Valve("FV-1", inlets={"in": "W3"}, outlets={"out": "W4"},
                 params={"mode": "Cv and opening", "cv": 60.0, "opening": 70.0, "characteristic": "Linear"}))
    fs.add(Sink("Out", inlets={"in": "W4"}, params={"pressure": 101.325}))
    res = fs.solve()
    assert_balanced(res)
    m = fs.streams["W1"].m
    # independent check: solve pump head = system head for the flow directly
    w1 = state_PT(101.325, 30.0)
    d = pipe_dimensions("3", "40")[0]

    def mismatch(mm):
        q = mm / w1.rho * 3600
        P2 = 101.325 + w1.rho * 9.80665 * (60 - 15 * (q / 50) ** 2) / 1000
        h2 = fs.streams["W2"].h
        P3 = pipe_flow(mm, P2, h2, d, 200.0, dz=10.0, segments=20).P_out
        return valve_flow(state_Ph(P3, h2), 101.325, 42.0) - mm

    assert m == pytest.approx(brentq(mismatch, 10.0, 15.0, xtol=1e-12), rel=1e-5)


def test_trap_back_pressure_found_from_the_receiver():
    """Condensate trap with a free pressure drop: its outlet pressure is the receiver pressure plus the
    return line's pressure drop and lift."""
    fs = pf("trap")
    fs.add(Feed("Condensate", outlets={"out": "C1"}, params={"pressure": barg(5), "condition": "Dryness fraction",
                                                            "dryness": 0.0, "flow": 1.0}))
    fs.add(Valve("Trap", inlets={"in": "C1"}, outlets={"out": "C2"},
                 params={"mode": "Free pressure drop (steam trap / flow controller)", "outlet_pressure": 300.0}))
    fs.add(Pipe("Return", inlets={"in": "C2"}, outlets={"out": "C3"},
                params={"nps": "2", "length": 80.0, "elevation": 5.0}))
    fs.add(FlashVessel("Receiver", inlets={"in": "C3"}, outlets={"vapour": "V", "liquid": "L"},
                       params={"pressure": barg(0.2), "inlet_specs": {"C3": "Open"}}))
    res = fs.solve()
    assert res.converged, res.errors
    assert fs.streams["C3"].P == pytest.approx(barg(0.2), abs=1e-6)
    direct = pipe_flow(1.0, fs.streams["C2"].P, fs.streams["C2"].h, pipe_dimensions("2", "40")[0], 80.0,
                       dz=5.0, segments=fs.blocks["Return"].pf_state["segments"])
    assert direct.P_out == pytest.approx(barg(0.2), rel=1e-6)
    assert barg(0.2) < fs.streams["C2"].P < barg(5)


def test_prv_runs_wide_open_when_the_supply_is_too_low():
    def build(p_supply):
        fs = pf("prv")
        fs.add(Feed("Steam", outlets={"out": "S1"}, params={"pressure": barg(p_supply), "condition": "Dryness fraction",
                                                           "dryness": 1.0, "flow_mode": "As required"}))
        fs.add(Valve("PRV", inlets={"in": "S1"}, outlets={"out": "S2"},
                     params={"mode": "Outlet pressure", "outlet_pressure": barg(4), "cv": 80.0,
                             "characteristic": "Linear"}))
        fs.add(SteamUser("User", inlets={"in": "S2"}, outlets={"condensate": "C"}, params={"flow": 1.0}))
        return fs

    ok = build(10)
    res = ok.solve()
    assert res.converged, res.errors
    assert ok.streams["S2"].P == pytest.approx(barg(4))
    assert "fully open" not in " ".join(res.network["notes"])
    starved = build(4.5)
    res = starved.solve()
    assert res.converged, res.errors
    assert starved.streams["S2"].P < barg(4)  # cannot hold the set pressure
    assert any("PRV is fully open" in n for n in res.network["notes"])
    assert valve_flow(starved.streams["S1"].state, starved.streams["S2"].P, 80.0) == pytest.approx(1.0, rel=1e-6)


def test_valve_that_cannot_pass_the_flow_is_explained():
    fs = pf("too small")
    fs.add(Feed("Steam", outlets={"out": "S1"}, params={"pressure": barg(4.5), "condition": "Dryness fraction",
                                                       "dryness": 1.0, "flow_mode": "As required"}))
    fs.add(Valve("PRV", inlets={"in": "S1"}, outlets={"out": "S2"},
                 params={"mode": "Outlet pressure", "outlet_pressure": barg(4), "cv": 40.0}))
    fs.add(SteamUser("User", inlets={"in": "S2"}, outlets={"condensate": "C"}, params={"flow": 1.0}))
    res = fs.solve()
    assert not res.converged
    assert any("PRV" in e and "choked" in e and "even fully open" in e for e in res.errors), res.errors


def cooling_loop(tank_mode="Pressure reference (expansion tank)"):
    fs = pf("loop")
    fs.add(Feed("Expansion tank", outlets={"out": "X"}, params={"pressure": 250.0, "temperature": 40.0,
                                                              "flow_mode": tank_mode, "flow": 0.0}))
    fs.add(Mixer("Suction", inlets={"in": ["R", "X"]}, outlets={"out": "W1"},
                 params={"pressure_mode": "Equal pressures (junction)"}))
    fs.add(Pump("P-1", inlets={"in": "W1"}, outlets={"out": "W2"},
                params={"mode": "Pump curve", "shutoff_head": 40.0, "rated_flow": 60.0, "rated_head": 30.0}))
    fs.add(Heater("Cooler", inlets={"in": "W2"}, outlets={"out": "W3"},
                  params={"spec": "Outlet temperature", "temperature": 40.0, "dp_mode": "Scales with flow²",
                          "pressure_drop": 50.0, "rated_flow": 15.0}))
    fs.add(Pipe("Return", inlets={"in": "W3"}, outlets={"out": "R"}, params={"nps": "4", "length": 300.0}))
    return fs


def test_closed_loop_with_expansion_tank():
    fs = cooling_loop()
    res = fs.solve()
    assert res.converged, res.errors
    assert fs.streams["X"].m == pytest.approx(0.0, abs=1e-8)  # the tank only sets the pressure
    assert fs.streams["W1"].P == pytest.approx(250.0)
    m = fs.streams["W2"].m
    assert m > 5.0
    # the pump head equals the loop's resistance
    assert fs.blocks["P-1"].results["dP"].value == pytest.approx(
        fs.blocks["Return"].results["dP"].value + (fs.streams["W2"].P - fs.streams["W3"].P), rel=1e-6)


def test_fixed_makeup_into_a_closed_loop_is_explained():
    fs = cooling_loop(tank_mode="Fixed")
    fs.blocks["Expansion tank"].params["flow"] = 0.5
    res = fs.solve()
    assert not res.converged
    assert any("Too many specifications" in e or "not fixed" in e or "backwards" in e or "Not enough" in e
               for e in res.errors)


def test_closed_rankine_cycle_with_a_flow_specification():
    fs = pf("closed rankine")
    fs.add(Pump("Pump", inlets={"in": "1"}, outlets={"out": "2"}, params={"outlet_pressure": 3000.0,
                                                                         "efficiency": 100.0}))
    fs.add(Boiler("Boiler", inlets={"in": "2"}, outlets={"steam": "3"},
                  params={"pressure": 3000.0, "steam_condition": "Superheated", "temperature": 350.0}))
    fs.add(Turbine("Turbine", inlets={"in": "3"}, outlets={"out": "4"}, params={"outlet_pressure": 75.0,
                                                                              "efficiency": 100.0}))
    fs.add(Condenser("Condenser", inlets={"in": "4"}, outlets={"out": "1"}))
    no_spec = fs.solve()
    assert not no_spec.converged
    assert any("circulating flow" in e for e in no_spec.errors)
    fs.add(Specification("Flow", params={"stream": "3", "property": "Mass flow", "flow": 10.0}))
    res = fs.solve()
    assert res.converged, res.errors
    assert all(s.m == pytest.approx(10.0) for s in fs.streams.values())
    eff = fs.summary()["cycle_efficiency"]
    assert eff == pytest.approx(0.2602, abs=5e-4)  # Çengel & Boles Example 10-1


def test_missing_and_conflicting_specifications_are_explained():
    fs = pf("missing")
    fs.add(Feed("Supply", outlets={"out": "S1"}, params={"pressure": 500.0, "temperature": 20.0,
                                                        "flow_mode": "As required"}))
    fs.add(Pipe("L", inlets={"in": "S1"}, outlets={"out": "S2"}, params={"nps": "2", "length": 50.0}))
    res = fs.solve()  # nothing sets the flow: the line just ends
    assert any("Not enough specifications" in e and "flow" in e for e in res.errors)
    fs.blocks["Supply"].params["flow_mode"] = "Fixed"
    fs.add(Sink("Out", inlets={"in": "S2"}, params={"pressure": 200.0}))
    res = fs.solve()  # flow fixed at the supply AND pressure fixed at the sink
    assert any("Too many specifications" in e for e in res.errors)


def test_check_valve_closes_against_higher_back_pressure():
    def build(p_b):
        fs = pf("check")
        fs.add(Feed("A", outlets={"out": "A1"}, params={"pressure": 400.0, "temperature": 20.0,
                                                       "flow_mode": "As required"}))
        fs.add(Feed("B", outlets={"out": "B1"}, params={"pressure": p_b, "temperature": 20.0,
                                                       "flow_mode": "As required"}))
        fs.add(CheckValve("NRV", inlets={"in": "B1"}, outlets={"out": "B2"}, params={"cv": 40.0}))
        fs.add(Mixer("Tee", inlets={"in": ["A1", "B2"]}, outlets={"out": "M"},
                     params={"pressure_mode": "Equal pressures (junction)"}))
        fs.add(Pipe("L", inlets={"in": "M"}, outlets={"out": "M2"}, params={"nps": "2", "length": 40.0}))
        fs.add(Sink("Out", inlets={"in": "M2"}, params={"pressure": 300.0}))
        return fs

    fs = build(380.0)  # B is below the junction pressure: the check valve stays shut
    res = fs.solve()
    assert res.converged, res.errors
    assert fs.streams["B2"].m == pytest.approx(0.0, abs=1e-9)
    assert any("NRV is closed" in n for n in res.network["notes"])
    fs = build(420.0)  # B is above the junction pressure: it flows
    res = fs.solve()
    assert res.converged, res.errors
    assert fs.streams["B2"].m > 0.1


@pytest.mark.parametrize("key", list(EXAMPLES))
def test_examples_give_the_same_answer_in_both_modes(key):
    seq = EXAMPLES[key]()
    if not seq.blocks:
        return
    assert seq.solve().converged
    net = EXAMPLES[key]()
    net.solver_mode = "pressure_flow"
    res = net.solve()
    assert_balanced(res)
    assert res.network["equations"] == res.network["unknowns"]
    for name, s in net.streams.items():
        a = seq.streams[name]
        assert s.m == pytest.approx(a.m, rel=1e-6, abs=1e-8)
        assert s.P == pytest.approx(a.P, rel=1e-6)
        assert s.h == pytest.approx(a.h, rel=1e-6, abs=1e-6)


def test_solver_mode_round_trips_through_json():
    fs = parallel_pipes()
    fs2 = Flowsheet.from_json(fs.to_json())
    assert fs2.solver_mode == "pressure_flow"
