"""Checks against independent references: analytical solutions and published tables.

(The textbook Rankine cycles, the API 520 steam example and the IAPWS tables are in the other test
files.) Published worked examples are only used where their inputs and answers could be confirmed."""

import math

import pytest

from steamsuite.flowsheet import Flowsheet
from steamsuite.flowsheet.advanced import Pipe
from steamsuite.flowsheet.blocks import Feed, Heater, Mixer, Pump, Sink, Splitter
from steamsuite.hydraulics import fully_turbulent_friction, isentropic_exponent, pipe_flow
from steamsuite.water import state_PT


def test_choking_length_matches_fanno_flow():
    """Adiabatic flow with friction of a nearly ideal gas (superheated steam at 2 bar, 400 °C) in a rough
    pipe: the length at which the flow chokes, from inlet Mach number M, is (Darcy f)
        f·L*/D = (1 − M²)/(γM²) + (γ + 1)/(2γ)·ln[(γ + 1)M² / (2 + (γ − 1)M²)]."""
    st = state_PT(200.0, 400.0)
    gamma = isentropic_exponent(st)
    d, eps = 50.0, 1.0  # mm: ε/D = 0.02, fully rough, so f is constant along the pipe
    f = fully_turbulent_friction(d, eps)
    for M in (0.25, 0.4, 0.6):
        m = st.rho * M * st.w * math.pi * (d / 1000.0) ** 2 / 4.0
        fanno = (1 - M * M) / (gamma * M * M) + (gamma + 1) / (2 * gamma) * math.log(
            (gamma + 1) * M * M / (2 + (gamma - 1) * M * M))
        L_star = fanno * (d / 1000.0) / f
        r = pipe_flow(m, 200.0, st.h, d, 3.0 * L_star, eps_mm=eps, strict=False)
        assert r.choked
        assert r.L_choke == pytest.approx(L_star, rel=0.01)


def test_pump_curve_against_a_quadratic_resistance_has_a_closed_form_answer():
    """H₀ − (H₀ − H_r)(Q/Q_r)² = ΔP_r (m/m_r)² / (ρg): solved exactly for the flow."""
    fs = Flowsheet("pump and resistance")
    fs.solver_mode = "pressure_flow"
    fs.add(Feed("Tank", outlets={"out": "W1"}, params={"pressure": 101.325, "temperature": 20.0,
                                                      "flow_mode": "As required"}))
    fs.add(Pump("P", inlets={"in": "W1"}, outlets={"out": "W2"},
                params={"mode": "Pump curve", "shutoff_head": 50.0, "rated_flow": 30.0, "rated_head": 40.0}))
    fs.add(Heater("R", inlets={"in": "W2"}, outlets={"out": "W3"},
                  params={"spec": "Heat duty", "duty": 0.0, "dp_mode": "Scales with flow²", "pressure_drop": 200.0,
                          "rated_flow": 8.0}))
    fs.add(Sink("Out", inlets={"in": "W3"}, params={"pressure": 101.325}))
    res = fs.solve()
    assert res.converged, res.errors
    rho = state_PT(101.325, 20.0).rho
    rg = rho * 9.80665 / 1000.0
    a = rg * 10.0 * (3600.0 / (rho * 30.0)) ** 2
    m = math.sqrt(rg * 50.0 / (200.0 / 64.0 + a))
    assert fs.streams["W1"].m == pytest.approx(m, rel=1e-6)


def test_parallel_rough_pipes_split_by_the_square_root_of_their_lengths():
    """Two equal-bore pipes in fully rough flow with the same pressure drop: m_A/m_B = √(L_B/L_A)."""
    fs = Flowsheet("parallel")
    fs.solver_mode = "pressure_flow"
    fs.add(Feed("In", outlets={"out": "S1"}, params={"pressure": 600.0, "temperature": 20.0,
                                                    "flow_mode": "As required"}))
    fs.add(Splitter("Tee", inlets={"in": "S1"}, outlets={"out": ["A1", "B1"]},
                    params={"outlet_specs": {"A1": {"mode": "Pressure-driven"}, "B1": {"mode": "Pressure-driven"}}}))
    rough = {"nps": "2", "material": "Custom", "roughness": 2.0}
    fs.add(Pipe("A", inlets={"in": "A1"}, outlets={"out": "A2"}, params={**rough, "length": 40.0}))
    fs.add(Pipe("B", inlets={"in": "B1"}, outlets={"out": "B2"}, params={**rough, "length": 160.0}))
    fs.add(Mixer("Join", inlets={"in": ["A2", "B2"]}, outlets={"out": "S2"},
                 params={"pressure_mode": "Equal pressures (junction)"}))
    fs.add(Sink("Out", inlets={"in": "S2"}, params={"pressure": 300.0}))
    res = fs.solve()
    assert res.converged, res.errors
    # √4 = 2, within the small Reynolds-number effect left in Colebrook at these flows
    assert fs.streams["A1"].m / fs.streams["B1"].m == pytest.approx(2.0, rel=0.01)
