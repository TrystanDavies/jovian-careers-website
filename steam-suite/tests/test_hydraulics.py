import math

import pytest

from steamsuite.hydraulics import (
    HeatLoss,
    fittings_k,
    friction_factor,
    fully_turbulent_friction,
    heat_loss_per_metre,
    npsh_available,
    pipe_dimensions,
    pipe_flow,
    valve_cv_required,
    valve_outlet_pressure,
)
from steamsuite.water import state_Ph, state_PT, state_Px


def test_pipe_dimensions_b36_10():
    d, od = pipe_dimensions("2", "40")
    assert od == 60.3 and d == pytest.approx(52.48)
    d, od = pipe_dimensions("10", "XS")
    assert d == pytest.approx(273.0 - 2 * 12.70)
    with pytest.raises(ValueError):
        pipe_dimensions("7", "40")


def test_friction_factor_regimes():
    assert friction_factor(1000, 1e-4) == pytest.approx(0.064)
    # Colebrook value for Re = 1e5, eps/D = 1e-4 (Moody chart ~ 0.0185)
    f = friction_factor(1e5, 1e-4)
    assert 1 / math.sqrt(f) == pytest.approx(-2 * math.log10(1e-4 / 3.7 + 2.51 / (1e5 * math.sqrt(f))), rel=1e-10)
    assert f == pytest.approx(0.0185, abs=0.0003)
    # transition region is continuous
    assert friction_factor(1999.9, 1e-4) == pytest.approx(friction_factor(2000.1, 1e-4), rel=1e-3)


def test_crane_fully_turbulent_friction_factors():
    """Crane TP-410 tabulates f_T = 0.019 for 2-inch and 0.015 for 6-inch Schedule 40 steel."""
    assert fully_turbulent_friction(pipe_dimensions("2", "40")[0]) == pytest.approx(0.019, abs=0.0005)
    assert fully_turbulent_friction(pipe_dimensions("6", "40")[0]) == pytest.approx(0.015, abs=0.0005)


def test_fittings_k():
    d = pipe_dimensions("2", "40")[0]
    k, rows = fittings_k({"elbow_90_std": 4, "gate": 2, "exit": 1}, d)
    fT = fully_turbulent_friction(d)
    assert k == pytest.approx(4 * 30 * fT + 2 * 8 * fT + 1.0)
    assert len(rows) == 3


def test_water_pipe_matches_darcy_weisbach_hand_calculation():
    st = state_PT(500.0, 20.0)
    d = pipe_dimensions("2", "40")[0]
    r = pipe_flow(3.0, 500.0, st.h, d, 100.0)
    area = math.pi * (d / 1000) ** 2 / 4
    v = 3.0 / st.rho / area
    re = st.rho * v * (d / 1000) / st.mu
    f = friction_factor(re, 0.045 / d)
    dp = f * 100 / (d / 1000) * st.rho * v * v / 2 / 1000
    assert r.dp_total == pytest.approx(dp, rel=1e-4)
    assert r.v_in == pytest.approx(v, rel=1e-9)


def test_static_head():
    st = state_PT(500.0, 20.0)
    r = pipe_flow(1.0, 500.0, st.h, 52.48, 0.0, dz=10.0)
    assert r.dp_total == pytest.approx(st.rho * 9.80665 * 10 / 1000, rel=1e-3)


def test_steam_pipe_converges_with_segments():
    st = state_Px(1101.325, 1.0)
    d = pipe_dimensions("4", "40")[0]
    fine = pipe_flow(10000 / 3600, 1101.325, st.h, d, 100, k_total=5, segments=400)
    auto = pipe_flow(10000 / 3600, 1101.325, st.h, d, 100, k_total=5)
    assert auto.dp_total == pytest.approx(fine.dp_total, rel=0.005)
    assert auto.v_out > auto.v_in  # steam expands as pressure falls


def test_choked_or_hopeless_pipe_raises():
    st = state_Px(1101.325, 1.0)
    with pytest.raises(ValueError):
        pipe_flow(10000 / 3600, 1101.325, st.h, pipe_dimensions("3", "40")[0], 200)


def test_two_phase_msh_limits():
    from steamsuite.hydraulics import _gradients
    G, d, eps = 500.0, 0.0779, 4.5e-5
    liq, vap = state_Px(500, 0.0), state_Px(500, 1.0)
    assert _gradients(state_Px(500, 1e-9), G, d, eps, "Müller-Steinhagen & Heck")[0] == pytest.approx(
        _gradients(liq, G, d, eps, "x")[0], rel=1e-3)
    assert _gradients(state_Px(500, 1 - 1e-12), G, d, eps, "Müller-Steinhagen & Heck")[0] == pytest.approx(
        _gradients(vap, G, d, eps, "x")[0], rel=1e-3)


def test_heat_loss_insulated_pipe():
    # 4-inch pipe at 180 °C, 50 mm mineral wool, 20 °C air: about 50–60 W/m
    q = heat_loss_per_metre(180.0, 20.0, 114.3, 50.0, 0.04, 10.0)
    r1, r2 = 0.05715, 0.10715
    expected = 160 / (math.log(r2 / r1) / (2 * math.pi * 0.04) + 1 / (2 * math.pi * r2 * 10))
    assert q == pytest.approx(expected)
    assert 40 < q < 70
    st = state_Px(1101.325, 1.0)
    r = pipe_flow(1.0, 1101.325, st.h, 102.26, 100, heat=HeatLoss(od_mm=114.3))
    assert r.heat_loss_kw == pytest.approx(q * 100 / 1000, rel=0.05)
    assert state_Ph(r.P_out, r.h_out).phase == "two-phase"  # some steam condenses


def test_valve_cv_liquid_and_round_trip():
    w = state_PT(1000.0, 40.0)
    sizing = valve_cv_required(5.0, w, 600.0)
    q = 5.0 * 3600 / w.rho
    assert sizing.cv == pytest.approx(q / 0.0865 * math.sqrt(w.rho / 999.0 / 400.0))
    P2, _ = valve_outlet_pressure(5.0, w, sizing.cv)
    assert P2 == pytest.approx(600.0, rel=1e-9)


def test_valve_cv_steam_round_trip_and_choking():
    st = state_PT(1101.325, 250.0)
    sub = valve_cv_required(1.0, st, 901.325)
    assert not sub.choked
    P2, _ = valve_outlet_pressure(1.0, st, sub.cv)
    assert P2 == pytest.approx(901.325, rel=1e-6)
    crit = valve_cv_required(1.0, st, 150.0)
    assert crit.choked and crit.y == pytest.approx(2 / 3)
    with pytest.raises(ValueError, match="choked"):
        valve_outlet_pressure(1.0, st, crit.cv * 0.5)


def test_npsh_available():
    st = state_PT(150.0, 60.0)
    from steamsuite.water import P_sat
    assert npsh_available(st) == pytest.approx((150.0 - P_sat(60.0)) * 1000 / (st.rho * 9.80665))
