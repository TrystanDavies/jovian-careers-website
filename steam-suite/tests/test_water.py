import pytest

from steamsuite.water import (
    WaterPropertyError,
    P_sat,
    T_sat,
    state_Ph,
    state_PT,
    state_Ps,
    state_Px,
    state_Tx,
)

# Verification values from IAPWS R7-97 (Tables 5, 15 and 35)
REGION1 = [  # T [K], P [MPa], v [m3/kg], h [kJ/kg], s [kJ/kg K]
    (300, 3, 0.100215168e-2, 0.115331273e3, 0.392294792),
    (300, 80, 0.971180894e-3, 0.184142828e3, 0.368563852),
    (500, 3, 0.120241800e-2, 0.975542239e3, 0.258041912e1),
]
REGION2 = [
    (300, 0.0035, 0.394913866e2, 0.254991145e4, 0.852238967e1),
    (700, 0.0035, 0.923015898e2, 0.333568375e4, 0.101749996e2),
    (700, 30, 0.542946619e-2, 0.263149474e4, 0.517540298e1),
]
SATURATION = [(300, 0.353658941e-2), (500, 0.263889776e1), (600, 0.123443146e2)]  # T [K], Psat [MPa]


@pytest.mark.parametrize("T, P, v, h, s", REGION1 + REGION2)
def test_iapws_if97_verification_values(T, P, v, h, s):
    st = state_PT(P * 1000.0, T - 273.15)
    assert st.v == pytest.approx(v, rel=1e-8)
    assert st.h == pytest.approx(h, rel=1e-8)
    assert st.s == pytest.approx(s, rel=1e-8)


@pytest.mark.parametrize("T, Ps", SATURATION)
def test_saturation_pressure(T, Ps):
    assert P_sat(T - 273.15) == pytest.approx(Ps * 1000.0, rel=1e-8)
    assert T_sat(Ps * 1000.0) == pytest.approx(T - 273.15, abs=1e-6)


def test_ph_and_ps_round_trip():
    st = state_PT(1000.0, 300.0)
    assert state_Ph(1000.0, st.h).T == pytest.approx(300.0, abs=1e-6)
    assert state_Ps(1000.0, st.s).T == pytest.approx(300.0, abs=1e-6)


def test_wet_steam_quality():
    liq, vap = state_Px(1000.0, 0.0), state_Px(1000.0, 1.0)
    h = liq.h + 0.25 * (vap.h - liq.h)
    st = state_Ph(1000.0, h)
    assert st.phase == "two-phase"
    assert st.x == pytest.approx(0.25, abs=1e-8)


def test_phase_descriptions():
    assert state_PT(101.325, 20.0).describe().startswith("Subcooled water")
    assert state_Px(500.0, 0.0).describe() == "Saturated water (at boiling point)"
    assert state_Px(500.0, 1.0).describe() == "Dry saturated steam"
    assert state_Px(500.0, 0.9).describe() == "Wet steam (dryness 0.900)"
    assert state_PT(1000.0, 250.0).describe().startswith("Superheated steam")
    assert state_PT(25000.0, 600.0).describe() == "Supercritical fluid"
    assert state_Tx(100.0, 1.0).P == pytest.approx(101.418, abs=1e-3)


@pytest.mark.parametrize("call", [
    lambda: state_PT(100.0, -5.0),
    lambda: state_PT(0.1, 20.0),
    lambda: state_PT(200000.0, 20.0),
    lambda: state_Px(25000.0, 0.5),
    lambda: state_Px(500.0, 1.5),
])
def test_out_of_range_inputs_raise_readable_errors(call):
    with pytest.raises(WaterPropertyError):
        call()


def test_matches_coolprop_if97():
    CP = pytest.importorskip("CoolProp.CoolProp")
    for P in (5.0, 101.325, 1000.0, 5000.0, 20000.0):
        for T in (10.0, 150.0, 300.0, 500.0):
            st = state_PT(P, T)
            h_cp = CP.PropsSI("H", "P", P * 1000.0, "T", T + 273.15, "IF97::Water") / 1000.0
            assert st.h == pytest.approx(h_cp, rel=1e-6)


def test_fast_backend_matches_iapws_package():
    """CoolProp's IF97 (fast) and the iapws package agree away from the critical region."""
    pytest.importorskip("CoolProp")
    import random

    from steamsuite import water

    random.seed(7)
    pts = [(random.uniform(1.0, 16000.0), random.uniform(60.0, 3500.0)) for _ in range(300)]

    def run(backend):
        water.set_backend(backend)
        out = []
        for P, h in pts:
            try:
                st = state_Ph(P, h)
                out.append((st, state_Ps(P, st.s), state_PT(P, st.T) if st.x is None else None))
            except WaterPropertyError:
                out.append(None)
        return out

    try:
        fast, ref = run("coolprop"), run("iapws")
    finally:
        water.set_backend("coolprop")
    compared = 0
    for a, b in zip(fast, ref):
        assert (a is None) == (b is None)
        if a is None:
            continue
        for x, y in zip(a, b):
            if x is None:
                continue
            compared += 1
            assert x.phase == y.phase
            assert x.T == pytest.approx(y.T, abs=1e-6)
            assert x.h == pytest.approx(y.h, rel=1e-9, abs=1e-9)
            assert x.s == pytest.approx(y.s, rel=1e-9, abs=1e-9)
            assert x.rho == pytest.approx(y.rho, rel=1e-7)
            for prop in ("mu", "k", "w", "cp"):  # transport and derived properties
                a_, b_ = getattr(x, prop), getattr(y, prop)
                assert (a_ is None) == (b_ is None), prop
                if a_ is not None:
                    assert a_ == pytest.approx(b_, rel=1e-6), prop
    assert compared > 600
