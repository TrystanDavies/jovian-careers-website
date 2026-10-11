"""Two-phase friction methods, void fraction, speed of sound and choked pipe flow."""

import math

import pytest

from steamsuite.hydraulics import (
    TWO_PHASE_METHODS,
    PipeChokedError,
    _gradients,
    friction_factor,
    pipe_dimensions,
    pipe_flow,
    sound_speed,
    two_phase_gradients,
    valve_cv_required,
    valve_flow,
    void_fraction,
)
from steamsuite.water import state_Ph, state_PT, state_Px, surface_tension

G_ACC = 9.80665


@pytest.mark.parametrize("T, sigma_mN", [(25.0, 71.97), (100.0, 58.91), (200.0, 37.67)])
def test_surface_tension_iapws_r1_76_table(T, sigma_mN):
    assert surface_tension(T) * 1000.0 == pytest.approx(sigma_mN, abs=0.006)


def test_surface_tension_vanishes_at_critical_point():
    assert surface_tension(373.946) == pytest.approx(0.0, abs=1e-6)
    assert surface_tension(380.0) == 0.0


@pytest.mark.parametrize("method", TWO_PHASE_METHODS)
def test_every_method_reaches_the_single_phase_limits(method):
    """As x → 0 the gradient tends to the all-liquid value, as x → 1 to the all-vapour value."""
    from steamsuite.hydraulics import _two_phase_friction
    G, d, eps = 500.0, 0.0779, 4.5e-5
    liq, vap = state_Px(500, 0.0), state_Px(500, 1.0)
    one_phase_liq = _gradients(liq, G, d, eps, method)[0]
    one_phase_vap = _gradients(vap, G, d, eps, method)[0]
    near_0 = _two_phase_friction(1e-10, liq.T, G, d, eps, liq, vap, method)
    near_1 = _two_phase_friction(1.0 - 1e-13, liq.T, G, d, eps, liq, vap, method)
    assert near_0 == pytest.approx(one_phase_liq, rel=5e-3)
    assert near_1 == pytest.approx(one_phase_vap, rel=5e-3)
    # and the two-phase gradient lies between sensible bounds in the middle
    mid = _two_phase_friction(0.5, liq.T, G, d, eps, liq, vap, method)
    assert one_phase_liq < mid < 3 * one_phase_vap


def test_friedel_hand_calculation():
    """Friedel (1979) evaluated step by step at 5 bar(a), x = 0.1, G = 300 kg/(m²·s), 80 mm bore."""
    P, x, G, d, eps = 500.0, 0.1, 300.0, 0.080, 4.5e-5
    st = state_Px(P, x)
    liq, vap = state_Px(P, 0.0), state_Px(P, 1.0)
    rl, rg, ml, mg = liq.rho, vap.rho, liq.mu, vap.mu
    f_lo = friction_factor(G * d / ml, eps / d)
    f_go = friction_factor(G * d / mg, eps / d)
    dp_lo = f_lo * G**2 / (2 * d * rl)
    E = (1 - x) ** 2 + x**2 * rl * f_go / (rg * f_lo)
    F = x**0.78 * (1 - x) ** 0.224
    H = (rl / rg) ** 0.91 * (mg / ml) ** 0.19 * (1 - mg / ml) ** 0.7
    rho_h = 1 / (x / rg + (1 - x) / rl)
    Fr = G**2 / (G_ACC * d * rho_h**2)
    We = G**2 * d / (surface_tension(st.T) * rho_h)
    phi2 = E + 3.24 * F * H / (Fr**0.045 * We**0.035)
    assert _gradients(st, G, d, eps, "Friedel")[0] == pytest.approx(phi2 * dp_lo, rel=1e-12)
    assert 5 < phi2 < 200  # sanity: a two-phase multiplier well above 1


def test_chisholm_has_no_jump_between_flow_regimes():
    """C is blended between 5, 10, 12 and 20, so the gradient is continuous as the flux changes."""
    st = state_Px(150.0, 0.05)
    d, eps = 0.0525, 4.5e-5
    gs = [5.0 * 1.005**i for i in range(1200)]  # 5 to about 2000 kg/(m²·s), covering every regime
    vals = [_gradients(st, G, d, eps, "Chisholm (Lockhart–Martinelli)")[0] for G in gs]
    jumps = [abs(b / a - 1.0) for a, b in zip(vals, vals[1:])]
    assert max(jumps) < 0.03  # smooth growth: about 1 % per step from G², up to 2 % in the transition region


def test_methods_compared_and_design_factor():
    st = state_Px(300.0, 0.2)
    grads = two_phase_gradients(st, 400.0, 77.9, 0.045)
    assert set(grads) == set(TWO_PHASE_METHODS)
    assert all(v > 0 for v in grads.values())
    base = _gradients(st, 400.0, 0.0779, 4.5e-5, TWO_PHASE_METHODS[0])[0]
    assert _gradients(st, 400.0, 0.0779, 4.5e-5, TWO_PHASE_METHODS[0], 1.3)[0] == pytest.approx(1.3 * base)
    assert two_phase_gradients(state_PT(300.0, 50.0), 400.0, 77.9, 0.045) == {}


def test_void_fraction_limits_and_slip():
    G = 300.0
    for model in ("Homogeneous", "Drift flux (Rouhani–Axelsson)"):
        assert void_fraction(state_Px(200, 1e-9), G, model) == pytest.approx(0.0, abs=1e-6)
        assert void_fraction(state_Px(200, 1 - 1e-12), G, model) == pytest.approx(1.0, abs=1e-6)
    st = state_Px(200, 0.05)
    hom = void_fraction(st, G, "Homogeneous")
    horiz = void_fraction(st, G, "Drift flux (Rouhani–Axelsson)", 0.0)
    vert = void_fraction(st, G, "Drift flux (Rouhani–Axelsson)", 1.0)
    assert vert < horiz < hom  # slip: the water holds up more of the pipe than without slip
    assert void_fraction(st, G, "Drift flux (Rouhani–Axelsson)", -1.0) == pytest.approx(hom)  # downflow


def test_drift_flux_raises_static_head_in_a_rising_wet_line():
    st = state_Px(200.0, 0.05)
    d = pipe_dimensions("3", "40")[0]
    hom = pipe_flow(1.0, 200.0, st.h, d, 10.0, dz=10.0)
    dfm = pipe_flow(1.0, 200.0, st.h, d, 10.0, dz=10.0, void_model="Drift flux (Rouhani–Axelsson)")
    assert dfm.dp_static > 1.5 * hom.dp_static
    flat = pipe_flow(1.0, 200.0, st.h, d, 10.0, void_model="Drift flux (Rouhani–Axelsson)")
    assert flat.dp_static == 0.0


def test_sound_speed():
    vap = state_PT(1000.0, 250.0)
    assert sound_speed(vap) == vap.w
    wet = state_Px(500.0, 0.5)
    c = sound_speed(wet)
    # homogeneous equilibrium: far below the speed of sound in either phase
    assert 20.0 < c < state_Px(500.0, 1.0).w
    # c² = (∂P/∂ρ)_s, checked with a central difference
    from steamsuite.water import state_Ps
    dP = 0.5
    rho_hi, rho_lo = state_Ps(500.0 + dP, wet.s).rho, state_Ps(500.0 - dP, wet.s).rho
    assert c == pytest.approx(math.sqrt(2 * dP * 1000.0 / (rho_hi - rho_lo)), rel=2e-3)


def test_near_choking_steam_line_converges_with_segments():
    """3" × 100 m of dry steam from 5 bar(a): the result no longer depends on the segment count."""
    d = pipe_dimensions("3", "40")[0]
    st = state_Px(500.0, 1.0)
    for m in (1.0, 1.05, 1.07):
        outs = [pipe_flow(m, 500.0, st.h, d, 100.0, segments=n).P_out for n in (20, 60, 200)]
        assert max(outs) / min(outs) - 1.0 < 0.005


def test_choked_pipe_gives_sonic_state_and_choking_length():
    d = pipe_dimensions("3", "40")[0]
    st = state_Px(500.0, 1.0)
    with pytest.raises(PipeChokedError) as info:
        pipe_flow(1.2, 500.0, st.h, d, 100.0)
    r = info.value.result
    assert r.choked and 0 < r.L_choke < 100.0
    assert r.v_out == pytest.approx(r.c_out, rel=0.02)  # Mach 1 at the choke point
    assert isinstance(info.value, ValueError)
    longer = pipe_flow(1.2, 500.0, st.h, d, 100.0, strict=False)
    assert longer.choked and longer.L_choke == pytest.approx(r.L_choke)
    # less flow chokes further along
    assert pipe_flow(1.1, 500.0, st.h, d, 100.0, strict=False).L_choke > r.L_choke


def test_flashing_water_line_chokes_conservatively():
    w = state_PT(300.0, 130.0)  # boils at 270 kPa(a)
    r = pipe_flow(10.0, 300.0, w.h, pipe_dimensions("2", "40")[0], 50.0, strict=False)
    assert r.choked and r.P_out < 300.0


def test_reverse_flow_is_the_mirror_image():
    st = state_PT(500.0, 20.0)
    d = pipe_dimensions("2", "40")[0]
    fwd = pipe_flow(2.0, 500.0, st.h, d, 50.0, dz=3.0)
    rev = pipe_flow(-2.0, 500.0, st.h, d, 50.0, dz=3.0)
    assert rev.reverse
    assert rev.dp_total == pytest.approx(-(fwd.dp_friction + fwd.dp_fittings + fwd.dp_accel) + fwd.dp_static)
    # continuous through zero flow: only the static head remains
    tiny = [pipe_flow(m, 500.0, st.h, d, 50.0, dz=3.0).dp_total for m in (-1e-6, 0.0, 1e-6)]
    assert max(tiny) - min(tiny) < 1e-4


def test_heat_loss_cannot_cool_below_ambient_at_tiny_flow():
    from steamsuite.hydraulics import HeatLoss
    st = state_PT(500.0, 90.0)
    r = pipe_flow(1e-5, 500.0, st.h, 52.48, 100.0, heat=HeatLoss(od_mm=60.3, insulation_mm=0.0))
    assert state_Ph(r.P_out, r.h_out).T >= 20.0 - 1e-6


def test_valve_flow_is_the_inverse_of_the_sizing_equations():
    w = state_PT(1000.0, 40.0)
    cv = valve_cv_required(5.0, w, 600.0).cv
    assert valve_flow(w, 600.0, cv) == pytest.approx(5.0, rel=1e-5)
    st = state_PT(1101.325, 250.0)
    cv = valve_cv_required(1.0, st, 901.325).cv
    assert valve_flow(st, 901.325, cv) == pytest.approx(1.0, rel=1e-5)
    # choked: flow no longer rises as the outlet pressure falls
    assert valve_flow(st, 150.0, cv) == pytest.approx(valve_flow(st, 50.0, cv), rel=1e-9)
    assert valve_flow(st, 1101.325, cv) == 0.0
    assert valve_flow(st, 1102.0, cv) < 0.0  # reversed pressure difference
