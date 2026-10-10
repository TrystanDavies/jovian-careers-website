import json

import pytest

from steamsuite.examples import (
    barg,
    industrial_steam_system,
    regenerative_rankine,
    simple_rankine,
)
from steamsuite.flowsheet import Flowsheet
from steamsuite.flowsheet.blocks import (
    Feed,
    FlashVessel,
    Heater,
    Mixer,
    Splitter,
    SteamUser,
    Turbine,
    Valve,
)
from steamsuite.water import state_Px


def test_simple_rankine_matches_textbook():
    """Çengel & Boles, Thermodynamics, Example 10-1 (ideal simple Rankine cycle).

    h1 = 384.44, h2 = 387.47, h3 = 3116.1, h4 = 2403.0 kJ/kg, x4 = 0.8861, efficiency 26.0 %.
    """
    fs = simple_rankine()
    res = fs.solve()
    assert res.converged
    s = fs.streams
    assert s["1 Pump inlet"].h == pytest.approx(384.44, abs=0.2)
    assert s["2 Boiler inlet"].h == pytest.approx(387.47, abs=0.2)
    assert s["3 Turbine inlet"].h == pytest.approx(3116.1, abs=0.3)
    assert s["4 Condenser inlet"].h == pytest.approx(2403.0, abs=0.5)
    assert s["4 Condenser inlet"].state.x == pytest.approx(0.8861, abs=5e-4)
    assert fs.summary()["cycle_efficiency"] == pytest.approx(0.260, abs=0.001)


def test_regenerative_rankine_matches_textbook():
    """Çengel & Boles, Example 10-5 (ideal regenerative cycle, one open feedwater heater).

    Extraction fraction y = 0.2270, efficiency 46.3 %.
    """
    fs = regenerative_rankine()
    res = fs.solve()
    assert res.converged
    m_boiler = fs.streams["5 HP turbine inlet"].m
    y = fs.streams["6 Extraction steam"].m / m_boiler
    assert y == pytest.approx(0.2270, abs=5e-4)
    assert fs.summary()["cycle_efficiency"] == pytest.approx(0.463, abs=0.001)
    # heater outlet is saturated water at 1.2 MPa
    assert fs.streams["3 Pump II inlet"].h == pytest.approx(state_Px(1200.0, 0.0).h, abs=0.01)


def test_industrial_system_balances_and_meets_targets():
    fs = industrial_steam_system()
    res = fs.solve()
    assert res.converged, res.errors
    assert not res.errors
    bal = res.balance
    assert abs(bal["mass_error"]) < 1e-9
    assert abs(bal["energy_error"]) < 1e-6
    s = fs.streams
    # deaerator produces saturated water at 0.3 bar(g)
    assert s["DA outlet"].h == pytest.approx(state_Px(barg(0.3), 0.0).h, abs=1e-3)
    # desuperheater hits 10 °C superheat
    assert s["Desuperheated steam"].state.superheat == pytest.approx(10.0, abs=1e-3)
    # process demands are met
    assert s["Process A steam"].m == pytest.approx(5.0 / 3.6, rel=1e-9)
    assert fs.blocks["Process B"].results["duty"].value == pytest.approx(3000.0, rel=1e-6)
    # the boiler makes exactly what the HP header sends out
    hp_out = s["Process A steam"].m + s["Turbine steam"].m + s["PRV steam"].m
    assert s["HP steam"].m == pytest.approx(hp_out, rel=1e-9)
    # make-up water replaces every loss
    losses = sum(s[n].m for n in ("Blowdown", "Process A losses", "Process B losses", "DA vent"))
    assert s["Make-up water"].m == pytest.approx(losses, rel=1e-8)


def test_json_round_trip_gives_identical_results():
    fs = industrial_steam_system()
    fs.solve()
    fs2 = Flowsheet.from_json(fs.to_json())
    fs2.solve()
    for name, st in fs.streams.items():
        assert fs2.streams[name].m == pytest.approx(st.m, rel=1e-9)
        assert fs2.streams[name].h == pytest.approx(st.h, rel=1e-9)
    json.loads(fs.to_json())


def test_report_includes_streams_and_equipment():
    fs = industrial_steam_system()
    fs.solve()
    md = fs.report().to_markdown()
    assert "Stream table" in md and "Deaerator" in md and "Mass balance error" in md


def _single(block, feed_params, extra=()):
    fs = Flowsheet("test")
    fs.add(Feed("Supply", outlets={"out": "in"}, params=feed_params))
    fs.add(block)
    for b in extra:
        fs.add(b)
    res = fs.solve()
    return fs, res


def test_valve_flashing_condensate_fraction():
    hf10, hf2, hg2 = state_Px(1101.325, 0.0).h, state_Px(301.325, 0.0).h, state_Px(301.325, 1.0).h
    fs, res = _single(Valve("Trap", inlets={"in": "in"}, outlets={"out": "out"}, params={"outlet_pressure": 301.325}),
                      {"pressure": 1101.325, "condition": "Dryness fraction", "dryness": 0.0, "flow": 1.0})
    assert res.converged
    expected = (hf10 - hf2) / (hg2 - hf2)
    assert fs.streams["out"].state.x == pytest.approx(expected, rel=1e-6)
    assert fs.blocks["Trap"].results["flash"].value == pytest.approx(expected * 100, rel=1e-6)


def test_flash_vessel_splits_mass():
    fs, res = _single(FlashVessel("FV", inlets={"in": "in"}, outlets={"vapour": "v", "liquid": "l"},
                                  params={"pressure": 201.325}),
                      {"pressure": 1101.325, "condition": "Dryness fraction", "dryness": 0.0, "flow": 2.0})
    v, l = fs.streams["v"], fs.streams["l"]
    assert v.m + l.m == pytest.approx(2.0)
    assert v.m * v.h + l.m * l.h == pytest.approx(2.0 * state_Px(1101.325, 0.0).h)


def test_turbine_efficiency_and_power():
    fs, res = _single(Turbine("T", inlets={"in": "in"}, outlets={"out": "out"},
                              params={"outlet_pressure": 401.325, "efficiency": 70.0, "generator_efficiency": 100.0}),
                      {"pressure": 4101.325, "temperature": 400.0, "flow": 1.0})
    st_in = fs.streams["in"]
    from steamsuite.water import state_Ps
    h2s = state_Ps(401.325, st_in.state.s).h
    W = fs.blocks["T"].results["power"].value
    assert W == pytest.approx(0.70 * (st_in.h - h2s), rel=1e-9)


def test_steam_user_with_heat_duty_requests_right_flow():
    fs = Flowsheet("test")
    fs.add(Feed("Steam", outlets={"out": "s"},
                params={"pressure": 501.325, "condition": "Dryness fraction", "dryness": 1.0, "flow_mode": "As required"}))
    fs.add(SteamUser("User", inlets={"in": "s"}, outlets={"condensate": "c"}, params={"spec": "Heat duty", "duty": 2000.0}))
    res = fs.solve()
    assert res.converged
    hfg = state_Px(501.325, 1.0).h - state_Px(501.325, 0.0).h
    assert fs.streams["s"].m == pytest.approx(2000.0 / hfg, rel=1e-8)


def test_splitter_fractions_and_remainder():
    fs = Flowsheet("test")
    fs.add(Feed("Supply", outlets={"out": "in"}, params={"pressure": 301.325, "temperature": 50.0, "flow": 10.0}))
    fs.add(Splitter("S", inlets={"in": "in"}, outlets={"out": ["a", "b", "c"]},
                    params={"outlet_specs": {"a": {"mode": "Fraction", "value": 25.0},
                                             "b": {"mode": "Flow", "value": 3.0},
                                             "c": {"mode": "Remainder"}}}))
    fs.solve()
    assert fs.streams["a"].m == pytest.approx(2.5)
    assert fs.streams["b"].m == pytest.approx(3.0)
    assert fs.streams["c"].m == pytest.approx(4.5)


def test_splitter_shortage_is_reported_and_mass_conserved():
    fs = Flowsheet("test")
    fs.add(Feed("Supply", outlets={"out": "in"}, params={"pressure": 301.325, "temperature": 50.0, "flow": 2.0}))
    fs.add(Splitter("S", inlets={"in": "in"}, outlets={"out": ["a", "b"]},
                    params={"outlet_specs": {"a": {"mode": "Flow", "value": 2.0}, "b": {"mode": "Flow", "value": 2.0}}}))
    res = fs.solve()
    assert fs.streams["a"].m + fs.streams["b"].m == pytest.approx(2.0)
    assert any("Not enough flow" in w for w in res.warnings)


def test_heater_duty_spec():
    fs, res = _single(Heater("H", inlets={"in": "in"}, outlets={"out": "out"},
                             params={"spec": "Heat duty", "duty": 418.0}),
                      {"pressure": 301.325, "temperature": 20.0, "flow": 1.0})
    assert fs.streams["out"].h - fs.streams["in"].h == pytest.approx(418.0)
    assert fs.streams["out"].state.T == pytest.approx(119.9, abs=0.5)


def test_mixer_energy_balance():
    fs = Flowsheet("test")
    fs.add(Feed("Hot", outlets={"out": "h"}, params={"pressure": 301.325, "temperature": 90.0, "flow": 1.0}))
    fs.add(Feed("Cold", outlets={"out": "c"}, params={"pressure": 301.325, "temperature": 10.0, "flow": 1.0}))
    fs.add(Mixer("M", inlets={"in": ["h", "c"]}, outlets={"out": "o"}))
    fs.solve()
    o = fs.streams["o"]
    assert o.m == pytest.approx(2.0)
    assert o.h == pytest.approx((fs.streams["h"].h + fs.streams["c"].h) / 2)
    assert o.state.T == pytest.approx(50.0, abs=0.3)


def test_unconnected_inlet_gives_clear_error():
    fs = Flowsheet("test")
    fs.add(Valve("V", inlets={"in": "missing"}, outlets={"out": "o"}))
    with pytest.raises(ValueError, match="nothing supplies it"):
        fs.solve()


def test_duplicate_outlet_name_gives_clear_error():
    fs = Flowsheet("test")
    fs.add(Feed("A", outlets={"out": "x"}))
    fs.add(Feed("B", outlets={"out": "x"}))
    with pytest.raises(ValueError, match="outlet of both"):
        fs.solve()


def test_equipment_error_is_reported_not_raised():
    fs, res = _single(Valve("V", inlets={"in": "in"}, outlets={"out": "out"}, params={"outlet_pressure": 2000.0}),
                      {"pressure": 301.325, "temperature": 20.0, "flow": 1.0})
    assert not res.converged
    assert any("above the inlet pressure" in e for e in res.errors)
