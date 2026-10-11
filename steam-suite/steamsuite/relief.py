"""Pressure relief valve sizing for water and steam.

Methods
-------
* Saturated / superheated steam: API 520 Part I steam equation (Napier),
  cross-checked by direct integration of isentropic nozzle flow.
* Water (liquid) that does not flash: API 520 Part I liquid equation for
  valves requiring capacity certification.
* Wet steam, and hot water that flashes as it relieves: direct integration of
  isentropic, homogeneous-equilibrium nozzle flow using IAPWS-IF97 (the
  "HDI" method described in API 520 Part I, Annex C).

Orifice letters and effective areas are from API 526. All results are
preliminary: final sizing needs the valve manufacturer's certified
coefficient and actual orifice area, and review by a qualified engineer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize_scalar

from .report import CalcReport, num, unit
from .units import P_ATM_KPA, fmt
from .water import (
    P_CRIT_KPA,
    P_TRIPLE_KPA,
    WaterPropertyError,
    WaterState,
    P_sat,
    T_sat,
    state_PT,
    state_Ps,
    state_Px,
)

IN2_TO_MM2 = 645.16
LB_TO_KG = 0.45359237
PSI_TO_KPA = 6.894757293168361

# API 526 effective orifice areas, in²
API526_ORIFICES: list[tuple[str, float]] = [
    ("D", 0.110),
    ("E", 0.196),
    ("F", 0.307),
    ("G", 0.503),
    ("H", 0.785),
    ("J", 1.287),
    ("K", 1.838),
    ("L", 2.853),
    ("M", 3.60),
    ("N", 4.34),
    ("P", 6.38),
    ("Q", 11.05),
    ("R", 16.0),
    ("T", 26.0),
]

FLUIDS = {
    "saturated_steam": "Saturated steam",
    "superheated_steam": "Superheated steam",
    "wet_steam": "Wet steam",
    "water": "Hot water (liquid)",
}

VALVE_TYPES = {
    "conventional": "Conventional spring-loaded",
    "balanced": "Balanced bellows",
    "pilot": "Pilot-operated",
}


@dataclass(frozen=True)
class OverpressureBasis:
    label: str
    percent: float
    min_kpa: float  # minimum overpressure for low set pressures
    rule: str


OVERPRESSURE_BASES: dict[str, OverpressureBasis] = {
    "single": OverpressureBasis(
        "Single valve, non-fire case (10 %)", 10.0, 20.7,
        "ASME Section VIII Div. 1 / Section XIII: 10 % or 3 psi (20.7 kPa), whichever is greater",
    ),
    "multiple": OverpressureBasis(
        "Multiple valves, non-fire case (16 %)", 16.0, 27.6,
        "ASME Section VIII Div. 1 / Section XIII: 16 % or 4 psi (27.6 kPa), whichever is greater",
    ),
    "fire": OverpressureBasis(
        "Fire case (21 %)", 21.0, 0.0,
        "ASME Section VIII Div. 1 / Section XIII and API 521: 21 % for fire exposure",
    ),
    "boiler": OverpressureBasis(
        "ASME Section I boiler safety valve (3 %)", 3.0, 13.8,
        "ASME Section I: capacity at 3 % or 2 psi (13.8 kPa) overpressure, whichever is greater",
    ),
    "custom": OverpressureBasis("Custom overpressure", 10.0, 0.0, "User-specified overpressure"),
}

DEFAULT_KD = {"vapour": 0.975, "liquid": 0.65, "two-phase": 0.85}

DISCLAIMER = (
    "This is a preliminary sizing calculation. Final valve selection must use the manufacturer's "
    "certified discharge coefficient and actual orifice area, and be checked by a qualified engineer "
    "against the code and edition that apply to your equipment."
)

REFERENCES = [
    "API Standard 520 Part I, Sizing, Selection, and Installation of Pressure-relieving Devices — Sizing and Selection.",
    "API Standard 526, Flanged Steel Pressure-relief Valves (orifice letter designations and effective areas).",
    "API Standard 521, Pressure-relieving and Depressuring Systems (relief scenarios and required rates).",
    "ASME Boiler and Pressure Vessel Code, Section I (power boilers), Section VIII Division 1 and Section XIII (overpressure protection).",
    "IAPWS R7-97, Revised Release on the IAPWS Industrial Formulation 1997 for the Thermodynamic Properties of Water and Steam.",
]


@dataclass
class ReliefInput:
    """Inputs for a relief valve sizing case (internal units)."""

    fluid: str  # key of FLUIDS
    flow_kg_h: float  # required relieving rate
    set_pressure_kpag: float
    overpressure_basis: str = "single"
    custom_overpressure_percent: float | None = None
    temperature_c: float | None = None  # superheated steam or water
    dryness: float | None = None  # wet steam
    back_pressure_kpag: float = 0.0  # total back pressure (superimposed + built-up)
    valve_type: str = "conventional"
    kd: float | None = None  # None = default for the flow regime
    kb: float | None = None  # balanced bellows only
    kw: float | None = None  # balanced bellows, liquid only
    rupture_disk: bool = False
    kc: float | None = None  # None = 0.9 with rupture disk, 1.0 without
    ksh: float | None = None  # None = estimate (superheated steam)
    p_atm_kpa: float = P_ATM_KPA
    tag: str = ""
    service: str = ""


@dataclass
class NozzleFlow:
    """Result of isentropic nozzle flow integration."""

    mass_flux: float  # kg/(s·m²)
    throat_pressure: float  # kPa(a)
    choked: bool
    throat_state: WaterState
    curve: list[tuple[float, float]] = field(default_factory=list)  # (P kPa(a), G kg/s·m²)


@dataclass
class ReliefResult:
    report: CalcReport
    required_area_mm2: float
    governing_method: str
    flow_regime: str
    relieving_pressure_kpa: float
    relieving_state: WaterState
    orifice: str | None
    orifice_area_mm2: float | None
    rated_capacity_kg_h: float | None
    valves_needed: int
    coefficients: dict[str, float]
    cross_checks: dict[str, float]
    warnings: list[str]
    nozzle: NozzleFlow | None = None


# --- nozzle flow by direct integration ------------------------------------------


def _flux(P: float, h0: float, s0: float) -> tuple[float, WaterState | None]:
    try:
        st = state_Ps(P, s0)
    except WaterPropertyError:
        return 0.0, None
    dh = h0 - st.h
    if dh <= 0:
        return 0.0, st
    return st.rho * math.sqrt(2000.0 * dh), st


def isentropic_nozzle_flow(inlet: WaterState, back_pressure: float, ignore_back_pressure: bool = False,
                           n_points: int = 160) -> NozzleFlow:
    """Maximum mass flux through an ideal nozzle by direct integration.

    Expands the fluid isentropically (homogeneous equilibrium) from the inlet
    stagnation state. At each pressure P the velocity is sqrt(2·(h0 − h)) and
    the mass flux is G = ρ·velocity. The flow is choked at the pressure where
    G is greatest; if that pressure is below the back pressure, the flow is
    not choked and G at the back pressure is used.
    """
    P0, h0, s0 = inlet.P, inlet.h, inlet.s
    p_floor = P_TRIPLE_KPA * 1.05
    p_low = p_floor if ignore_back_pressure else max(back_pressure, p_floor)
    if p_low >= P0:
        raise ValueError("Back pressure must be below the relieving pressure.")

    grid = set(np.linspace(p_low, P0, n_points)[:-1].tolist())
    grid |= set(np.geomspace(p_low, P0, n_points)[:-1].tolist())
    # the isentrope of a subcooled liquid starts to flash close to its saturation pressure
    if inlet.phase == "liquid" and inlet.P < P_CRIT_KPA:
        try:
            ps = P_sat(inlet.T)
            for f in (1.0, 0.999, 0.99, 1.001, 1.01):
                if p_low < ps * f < P0:
                    grid.add(ps * f)
        except WaterPropertyError:
            pass
    pts = sorted(grid)
    vals = [_flux(p, h0, s0)[0] for p in pts]
    i = int(np.argmax(vals))

    # refine around the best grid point
    lo = pts[max(i - 1, 0)]
    hi = pts[min(i + 1, len(pts) - 1)]
    best_p, best_g = pts[i], vals[i]
    if hi > lo:
        res = minimize_scalar(lambda p: -_flux(p, h0, s0)[0], bounds=(lo, hi), method="bounded",
                              options={"xatol": max(1e-6 * P0, 1e-5)})
        if res.success and -res.fun > best_g:
            best_p, best_g = float(res.x), float(-res.fun)

    choked = best_p > p_low * (1 + 1e-6)
    if not choked:
        best_p = p_low
        best_g = _flux(p_low, h0, s0)[0]
    throat = state_Ps(best_p, s0)
    curve = list(zip(pts, vals))
    return NozzleFlow(mass_flux=best_g, throat_pressure=best_p, choked=choked, throat_state=throat, curve=curve)


# --- API 520 helpers -------------------------------------------------------------


def napier_kn(p1_kpa: float) -> float:
    """API 520 correction factor for Napier's equation (SI units, P1 in kPa(a))."""
    if p1_kpa <= 10339.0:
        return 1.0
    return (0.02764 * p1_kpa - 1000.0) / (0.03324 * p1_kpa - 1061.0)


def viscosity_correction(q_gpm: float, sg: float, mu_cp: float, area_in2: float) -> tuple[float, float]:
    """API 520 viscosity correction factor Kv (capped at 1.0) and Reynolds number."""
    re = q_gpm * 18800.0 * sg / (mu_cp * math.sqrt(area_in2))
    kv = 1.0 / (0.9935 + 2.878 / re**0.7 + 342.75 / re**1.5)
    return min(kv, 1.0), re


def select_orifice(area_mm2: float) -> tuple[str | None, float | None, int]:
    """Smallest API 526 orifice with at least the required area.

    Returns (letter, area mm², number of valves). If even a T orifice is too
    small, returns the number of T valves needed.
    """
    for letter, a_in2 in API526_ORIFICES:
        a = a_in2 * IN2_TO_MM2
        if a >= area_mm2:
            return letter, a, 1
    t_area = API526_ORIFICES[-1][1] * IN2_TO_MM2
    n = math.ceil(area_mm2 / t_area)
    return "T", t_area, n


def _overpressure(inp: ReliefInput) -> tuple[float, float, OverpressureBasis]:
    basis = OVERPRESSURE_BASES.get(inp.overpressure_basis)
    if basis is None:
        raise ValueError(f"Unknown overpressure basis: {inp.overpressure_basis}")
    pct = basis.percent
    if inp.overpressure_basis == "custom":
        if inp.custom_overpressure_percent is None or inp.custom_overpressure_percent <= 0:
            raise ValueError("Enter the custom overpressure as a positive percentage.")
        pct = inp.custom_overpressure_percent
    dp = max(pct / 100.0 * inp.set_pressure_kpag, basis.min_kpa)
    return pct, dp, basis


# --- main entry point --------------------------------------------------------------


def size_relief_valve(inp: ReliefInput) -> ReliefResult:
    """Size a pressure relief valve and return a step-by-step report."""
    if inp.fluid not in FLUIDS:
        raise ValueError(f"Unknown fluid type: {inp.fluid}")
    if inp.valve_type not in VALVE_TYPES:
        raise ValueError(f"Unknown valve type: {inp.valve_type}")
    if not inp.flow_kg_h or inp.flow_kg_h <= 0:
        raise ValueError("The required relieving rate must be greater than zero.")
    if inp.set_pressure_kpag <= 0:
        raise ValueError("The set pressure must be above atmospheric pressure (greater than 0 gauge).")
    if inp.back_pressure_kpag < -inp.p_atm_kpa + P_TRIPLE_KPA:
        raise ValueError("The back pressure cannot be below a perfect vacuum.")
    if inp.back_pressure_kpag >= inp.set_pressure_kpag:
        raise ValueError("The back pressure must be lower than the set pressure.")

    W = inp.flow_kg_h
    warnings: list[str] = []
    rep = CalcReport(
        title="Pressure relief valve sizing" + (f" — {inp.tag}" if inp.tag else ""),
        subtitle=f"{FLUIDS[inp.fluid]} service" + (f": {inp.service}" if inp.service else ""),
        disclaimer=DISCLAIMER,
        references=list(REFERENCES),
    )

    pct, dp_op, basis = _overpressure(inp)
    P1 = inp.set_pressure_kpag + dp_op + inp.p_atm_kpa
    P2 = inp.back_pressure_kpag + inp.p_atm_kpa

    # inputs table
    rep.add_input("Fluid", FLUIDS[inp.fluid])
    rep.add_input("Required relieving rate", f"{fmt(W)} kg/h")
    rep.add_input("Set pressure", f"{fmt(inp.set_pressure_kpag)} kPa(g)")
    rep.add_input("Overpressure basis", basis.label if inp.overpressure_basis != "custom" else f"Custom ({fmt(pct)} %)")
    if inp.fluid in ("superheated_steam", "water"):
        rep.add_input("Relieving temperature", f"{fmt(inp.temperature_c)} °C")
    if inp.fluid == "wet_steam":
        rep.add_input("Dryness fraction", fmt(inp.dryness))
    rep.add_input("Total back pressure", f"{fmt(inp.back_pressure_kpag)} kPa(g)")
    rep.add_input("Valve type", VALVE_TYPES[inp.valve_type])
    rep.add_input("Rupture disk upstream", "Yes" if inp.rupture_disk else "No")
    rep.add_input("Atmospheric pressure", f"{fmt(inp.p_atm_kpa)} kPa(a)")

    # Step 1: relieving pressure
    pct_dp = pct / 100.0 * inp.set_pressure_kpag
    min_note = ""
    if basis.min_kpa > 0 and basis.min_kpa > pct_dp:
        min_note = (f" The percentage gives only {fmt(pct_dp)} kPa, so the minimum overpressure of "
                    f"{fmt(basis.min_kpa)} kPa for low set pressures applies.")
    rep.add_step(
        "Relieving pressure",
        text=("The valve must pass the required flow before the pressure rises more than the allowed "
              f"overpressure above the set pressure. Rule used: {basis.rule}.{min_note} "
              "The relieving pressure P₁ is the set pressure plus overpressure plus atmospheric pressure, "
              "as an absolute pressure."),
        equation=r"P_1 = P_{set} + \Delta P_{over} + P_{atm}",
        substitution=(rf"P_1 = {num(inp.set_pressure_kpag)} + {num(dp_op)} + {num(inp.p_atm_kpa)}"),
        result=rf"P_1 = {num(P1, 5)}{unit('kPa(a)')}",
        reference="API 520 Part I, definitions of relieving pressure and overpressure",
    )

    # Step 2: fluid state at relieving conditions
    state = _relieving_state(inp, P1)
    if inp.fluid == "water" and state.phase != "liquid":
        raise ValueError("At the relieving pressure this water is not liquid; choose a steam option instead.")
    sat_note = ""
    if P1 < P_CRIT_KPA:
        sat_note = f" At this pressure water boils at {fmt(T_sat(P1))} °C."
    rep.add_step(
        "Fluid properties at relieving conditions",
        text=f"Properties from the IAPWS-IF97 steam tables at P₁ = {fmt(P1)} kPa(a).{sat_note}",
        table=[
            ["Property", "Value"],
            ["Condition", state.describe()],
            ["Temperature", f"{fmt(state.T)} °C"],
            ["Specific enthalpy", f"{fmt(state.h)} kJ/kg"],
            ["Specific entropy", f"{fmt(state.s)} kJ/(kg·K)"],
            ["Density", f"{fmt(state.rho)} kg/m³"],
        ],
        reference="IAPWS-IF97",
    )

    # Step 3: back pressure
    bp_ratio = inp.back_pressure_kpag / inp.set_pressure_kpag
    rep.add_step(
        "Back pressure",
        text=("Back pressure is the pressure at the valve outlet (superimposed plus built-up). "
              "As an absolute pressure:"),
        equation=r"P_2 = P_{back} + P_{atm}",
        substitution=rf"P_2 = {num(inp.back_pressure_kpag)} + {num(inp.p_atm_kpa)}",
        result=(rf"P_2 = {num(P2, 5)}{unit('kPa(a)')} \quad "
                rf"\left(\tfrac{{P_{{back}}}}{{P_{{set}}}} = {num(bp_ratio * 100, 3)}\,\%\right)"),
    )
    if inp.valve_type == "conventional" and bp_ratio > 0.10:
        warnings.append(
            f"Back pressure is {fmt(bp_ratio * 100, 3)} % of set pressure. Conventional valves are normally "
            "limited to about 10 % built-up back pressure; consider a balanced bellows or pilot-operated valve."
        )
    if inp.valve_type == "balanced" and bp_ratio > 0.5:
        warnings.append(
            f"Back pressure is {fmt(bp_ratio * 100, 3)} % of set pressure, which is high even for balanced "
            "bellows valves. Check the manufacturer's limits."
        )

    if inp.rupture_disk:
        kc = inp.kc if inp.kc is not None else 0.9
    else:
        kc = inp.kc if inp.kc is not None else 1.0

    if inp.fluid in ("saturated_steam", "superheated_steam"):
        result = _size_steam(inp, rep, state, P1, P2, kc, warnings)
    elif inp.fluid == "wet_steam":
        result = _size_two_phase(inp, rep, state, P1, P2, kc, warnings, regime_hint="two-phase")
    else:  # water
        try:
            psat = P_sat(state.T)
        except WaterPropertyError:
            psat = None
        if psat is not None and psat >= P2:
            rep.add_step(
                "Check for flashing",
                text=(f"The water's saturation pressure at {fmt(state.T)} °C is {fmt(psat)} kPa(a), "
                      f"which is above the back pressure of {fmt(P2)} kPa(a). Part of the water will flash "
                      "to steam as the pressure falls through the valve, so the liquid equation would "
                      "overestimate the capacity. Two-phase direct integration is used instead."),
            )
            warnings.append(
                "The relieved water flashes to steam. Design the discharge piping for two-phase flow and "
                "check reaction forces."
            )
            result = _size_two_phase(inp, rep, state, P1, P2, kc, warnings, regime_hint="flashing")
        else:
            if psat is not None:
                rep.add_step(
                    "Check for flashing",
                    text=(f"The water's saturation pressure at {fmt(state.T)} °C is {fmt(psat)} kPa(a), "
                          f"below the back pressure of {fmt(P2)} kPa(a), so the water stays liquid through "
                          "the valve. The API 520 liquid equation applies."),
                )
            result = _size_liquid(inp, rep, state, P1, P2, kc, warnings)

    A_req, method, regime, coeffs, checks, nozzle = result

    # orifice selection
    letter, a_orf, n_valves = select_orifice(A_req)
    table = [["Orifice", "Effective area (mm²)", "Effective area (in²)", ""]]
    for L, a_in2 in API526_ORIFICES:
        mark = "◀ selected" if L == letter else ""
        table.append([L, fmt(a_in2 * IN2_TO_MM2, 4), f"{a_in2:.3f}", mark])
    if n_valves == 1:
        rated = W * a_orf / A_req
        rep.add_step(
            "Select a standard orifice",
            text=(f"Choose the smallest API 526 orifice with an effective area of at least "
                  f"{fmt(A_req)} mm². The selected orifice is {letter}. Its rated capacity at the same "
                  "conditions is the required rate scaled by the area ratio."),
            equation=r"W_{rated} = W \cdot \frac{A_{orifice}}{A_{required}}",
            substitution=rf"W_{{rated}} = {num(W, 5)} \cdot \frac{{{num(a_orf, 5)}}}{{{num(A_req, 5)}}}",
            result=rf"W_{{rated}} = {num(rated, 5)}{unit('kg/h')}",
            table=table,
            reference="API 526 effective orifice areas",
        )
    else:
        rated = None
        rep.add_step(
            "Select a standard orifice",
            text=(f"The required area of {fmt(A_req)} mm² is larger than the biggest API 526 orifice "
                  f"(T, {fmt(a_orf)} mm²). At least {n_valves} T-orifice valves are needed, or split the "
                  "relief load over several valves."),
            table=table,
        )
        warnings.append(
            f"No single standard orifice is large enough: use at least {n_valves} valves. With several valves, "
            "the multiple-valve overpressure (16 %) may apply."
        )

    warnings.append(
        "API 526 areas and API effective discharge coefficients are for preliminary sizing. Confirm with the "
        "manufacturer's certified (rated) coefficient and actual orifice area."
    )

    # summary
    rep.add_result("Required effective area", f"{fmt(A_req)} mm² ({fmt(A_req / IN2_TO_MM2)} in²)")
    if n_valves == 1:
        rep.add_result("Selected API 526 orifice", f"{letter} — {fmt(a_orf)} mm² ({fmt(a_orf / IN2_TO_MM2)} in²)")
        rep.add_result("Rated capacity of selected orifice", f"{fmt(rated)} kg/h")
    else:
        rep.add_result("Selected API 526 orifice", f"{n_valves} × T — {fmt(a_orf)} mm² each")
    rep.add_result("Relieving pressure", f"{fmt(P1)} kPa(a)")
    rep.add_result("Relieving condition", state.describe())
    rep.add_result("Flow regime", regime)
    rep.add_result("Governing method", method)

    rep.warnings = warnings
    rep.assumptions = _assumptions(inp)

    return ReliefResult(
        report=rep,
        required_area_mm2=A_req,
        governing_method=method,
        flow_regime=regime,
        relieving_pressure_kpa=P1,
        relieving_state=state,
        orifice=letter,
        orifice_area_mm2=a_orf,
        rated_capacity_kg_h=rated,
        valves_needed=n_valves,
        coefficients=coeffs,
        cross_checks=checks,
        warnings=warnings,
        nozzle=nozzle,
    )


def _relieving_state(inp: ReliefInput, P1: float) -> WaterState:
    if inp.fluid == "saturated_steam":
        if P1 >= P_CRIT_KPA:
            raise ValueError("The relieving pressure is above the critical pressure; saturated steam does not exist there.")
        return state_Px(P1, 1.0)
    if inp.fluid == "wet_steam":
        if inp.dryness is None or not 0.0 < inp.dryness < 1.0:
            raise ValueError("For wet steam, enter a dryness fraction between 0 and 1 (e.g. 0.95).")
        if P1 >= P_CRIT_KPA:
            raise ValueError("The relieving pressure is above the critical pressure; wet steam does not exist there.")
        return state_Px(P1, inp.dryness)
    if inp.temperature_c is None:
        raise ValueError("Enter the relieving temperature.")
    if inp.fluid == "superheated_steam":
        if P1 < P_CRIT_KPA:
            ts = T_sat(P1)
            if inp.temperature_c <= ts + 0.01:
                raise ValueError(
                    f"{fmt(inp.temperature_c)} °C is not superheated at the relieving pressure "
                    f"(water boils at {fmt(ts)} °C at {fmt(P1)} kPa(a)). Choose 'Saturated steam' or raise the temperature."
                )
        return state_PT(P1, inp.temperature_c)
    # water
    if P1 < P_CRIT_KPA:
        ts = T_sat(P1)
        if inp.temperature_c >= ts - 0.01:
            raise ValueError(
                f"At {fmt(inp.temperature_c)} °C the water would be boiling at the relieving pressure "
                f"(saturation temperature {fmt(ts)} °C). Choose 'Wet steam' or 'Saturated steam' instead."
            )
    return state_PT(P1, inp.temperature_c)


def _kb_for(inp: ReliefInput, warnings: list[str]) -> float:
    if inp.valve_type == "balanced":
        kb = inp.kb if inp.kb is not None else 1.0
        if inp.kb is None and inp.back_pressure_kpag > 0:
            warnings.append(
                "Balanced bellows valve: Kb was taken as 1.0. Read the back pressure correction factor Kb "
                "from the manufacturer's curve and enter it."
            )
        return kb
    return 1.0


def _size_steam(inp, rep, state, P1, P2, kc, warnings):
    W = inp.flow_kg_h
    kd = inp.kd if inp.kd is not None else DEFAULT_KD["vapour"]
    kb = _kb_for(inp, warnings)

    # direct integration (also tells us whether the flow is choked)
    use_critical = inp.valve_type == "balanced"
    nozzle = isentropic_nozzle_flow(state, P2, ignore_back_pressure=use_critical)
    crit = nozzle if use_critical else isentropic_nozzle_flow(state, P2, ignore_back_pressure=True)
    choked = crit.throat_pressure >= P2
    regime = "Critical (choked) vapour flow" if choked else "Subcritical vapour flow"
    rep.add_step(
        "Flow regime",
        text=(f"Expanding the steam isentropically from P₁, the mass flux is greatest at a throat pressure of "
              f"{fmt(crit.throat_pressure)} kPa(a) (critical pressure ratio {fmt(crit.throat_pressure / P1, 3)}). "
              + ("The back pressure is lower than this, so the flow is choked (critical): the flow rate does not "
                 "depend on the back pressure." if choked else
                 "The back pressure is higher than this, so the flow is not choked (subcritical) and the back "
                 "pressure reduces the capacity.")),
        equation=r"G = \rho \sqrt{2\,(h_1 - h)} \quad \text{along } s = s_1",
        reference="API 520 Part I, Annex C (direct integration)",
    )

    G_hdi = nozzle.mass_flux
    A_hdi = W / 3600.0 / (kd * kb * kc * G_hdi) * 1e6

    coeffs = {"Kd": kd, "Kb": kb, "Kc": kc}
    checks: dict[str, float] = {}

    # balanced bellows valves use the critical-flow equation with Kb even when subcritical
    napier_ok = (choked or inp.valve_type == "balanced") and P1 <= 22057.0
    if napier_ok:
        kn = napier_kn(P1)
        if P1 <= 10339.0:
            rep.add_step(
                "Napier correction factor KN",
                text="KN corrects Napier's equation at high pressure. It is 1.0 when P₁ ≤ 10,339 kPa(a).",
                result=r"K_N = 1.0",
                reference="API 520 Part I, steam sizing",
            )
        else:
            rep.add_step(
                "Napier correction factor KN",
                text="For 10,339 < P₁ ≤ 22,057 kPa(a):",
                equation=r"K_N = \frac{0.02764\,P_1 - 1000}{0.03324\,P_1 - 1061}",
                substitution=rf"K_N = \frac{{0.02764 \times {num(P1, 5)} - 1000}}{{0.03324 \times {num(P1, 5)} - 1061}}",
                result=rf"K_N = {num(kn, 4)}",
                reference="API 520 Part I, steam sizing",
            )
        if inp.fluid == "saturated_steam":
            ksh = 1.0
            rep.add_step("Superheat correction factor KSH",
                         text="For saturated steam there is no superheat correction.", result=r"K_{SH} = 1.0")
        elif inp.ksh is not None:
            ksh = inp.ksh
            rep.add_step("Superheat correction factor KSH",
                         text="KSH entered by the user (e.g. from the code's superheat correction table).",
                         result=rf"K_{{SH}} = {num(ksh, 4)}")
        else:
            sat = state_Px(P1, 1.0)
            g_sat = isentropic_nozzle_flow(sat, P2, ignore_back_pressure=True).mass_flux
            g_sh = crit.mass_flux
            ksh = min(g_sh / g_sat, 1.0)
            rep.add_step(
                "Superheat correction factor KSH (estimated)",
                text=("Superheated steam is less dense than saturated steam at the same pressure, so less mass "
                      "flows through the same area. KSH is estimated here as the ratio of the ideal critical mass "
                      "fluxes of the superheated and the saturated steam at P₁, both found by direct integration. "
                      "If you work to a code table of KSH, enter that value instead under the advanced options."),
                equation=r"K_{SH} \approx \frac{G^*_{superheated}}{G^*_{saturated}}",
                substitution=rf"K_{{SH}} \approx \frac{{{num(g_sh, 5)}}}{{{num(g_sat, 5)}}}",
                result=rf"K_{{SH}} = {num(ksh, 4)}",
            )
            warnings.append(
                f"KSH = {fmt(ksh, 3)} was estimated from nozzle-flow theory. If your design code tabulates KSH, "
                "enter the tabulated value."
            )
        coeffs.update({"KN": kn, "KSH": ksh})
        A_napier = 190.4 * W / (P1 * kd * kb * kc * kn * ksh)
        _coeff_step(rep, inp, kd, kb, kc, "vapour")
        rep.add_step(
            "Required area — API 520 steam equation (Napier)",
            text=("For steam in critical flow, API 520 uses Napier's empirical equation "
                  "(SI form: A in mm², W in kg/h, P₁ in kPa(a))."),
            equation=r"A = \frac{190.4\,W}{P_1\,K_d\,K_b\,K_c\,K_N\,K_{SH}}",
            substitution=(rf"A = \frac{{190.4 \times {num(W, 5)}}}{{{num(P1, 5)} \times {num(kd, 3)} \times "
                          rf"{num(kb, 3)} \times {num(kc, 3)} \times {num(kn, 4)} \times {num(ksh, 4)}}}"),
            result=rf"A = {num(A_napier, 5)}{unit('mm^2')} \;=\; {num(A_napier / IN2_TO_MM2, 4)}{unit('in^2')}",
            reference="API 520 Part I, sizing for steam relief (equivalent to W = 51.5·A·P₁·Kd·Kb·Kc·KN·KSH in US units)",
        )
        diff = (A_hdi - A_napier) / A_napier * 100.0
        rep.add_step(
            "Cross-check by direct integration",
            text=(f"As an independent check, the ideal critical mass flux from direct integration is "
                  f"G = {fmt(G_hdi)} kg/(s·m²). Using the same coefficients, this needs an area "
                  f"{fmt(abs(diff), 2)} % {'larger' if diff > 0 else 'smaller'} than Napier's equation. "
                  "Napier's equation governs because it is the code equation for steam."),
            equation=r"A = \frac{W}{K_d\,K_b\,K_c\,G}",
            substitution=(rf"A = \frac{{{num(W, 5)} / 3600}}{{{num(kd, 3)} \times {num(kb, 3)} \times "
                          rf"{num(kc, 3)} \times {num(G_hdi, 5)}}} \times 10^6"),
            result=rf"A = {num(A_hdi, 5)}{unit('mm^2')}",
        )
        checks["Direct integration (HDI)"] = A_hdi
        if abs(diff) > 10:
            warnings.append(
                f"Napier's equation and direct integration differ by {fmt(abs(diff), 2)} %. Review the inputs."
            )
        return A_napier, "API 520 steam equation (Napier)", regime, coeffs, checks, nozzle

    # Napier not applicable: use direct integration
    why = ("the flow is subcritical" if not choked else
           "the relieving pressure is above 22,057 kPa(a), the upper limit of Napier's equation")
    _coeff_step(rep, inp, kd, kb, kc, "vapour")
    rep.add_step(
        "Required area — direct integration",
        text=(f"Napier's equation is not used because {why}. The required area follows from the mass flux found "
              f"by direct integration, G = {fmt(G_hdi)} kg/(s·m²)."),
        equation=r"A = \frac{W}{K_d\,K_b\,K_c\,G}",
        substitution=(rf"A = \frac{{{num(W, 5)} / 3600}}{{{num(kd, 3)} \times {num(kb, 3)} \times "
                      rf"{num(kc, 3)} \times {num(G_hdi, 5)}}} \times 10^6"),
        result=rf"A = {num(A_hdi, 5)}{unit('mm^2')} \;=\; {num(A_hdi / IN2_TO_MM2, 4)}{unit('in^2')}",
        reference="API 520 Part I, Annex C",
    )
    return A_hdi, "Direct integration of isentropic nozzle flow (HDI)", regime, coeffs, checks, nozzle


def _size_two_phase(inp, rep, state, P1, P2, kc, warnings, regime_hint):
    W = inp.flow_kg_h
    kb = _kb_for(inp, warnings)
    use_critical = inp.valve_type == "balanced"
    nozzle = isentropic_nozzle_flow(state, P2, ignore_back_pressure=use_critical)
    throat = nozzle.throat_state

    liquid_at_throat = throat.is_liquid_like
    if regime_hint == "flashing":
        if liquid_at_throat:
            regime = ("Subcooled liquid, choked at its saturation pressure (flashes after the throat)"
                      if nozzle.choked else "Subcooled liquid (flashes downstream)")
            kd_default = DEFAULT_KD["liquid"]
            kd_why = ("The liquid is still single-phase at the throat (high subcooling), so the liquid "
                      f"discharge coefficient Kd = {DEFAULT_KD['liquid']} is used.")
        else:
            regime = "Flashing two-phase flow" + (" (choked)" if nozzle.choked else "")
            kd_default = DEFAULT_KD["two-phase"]
            kd_why = (f"The water starts to flash before the throat, so a two-phase discharge coefficient "
                      f"Kd = {DEFAULT_KD['two-phase']} is used as a preliminary value.")
    else:
        regime = "Two-phase (wet steam) flow" + (" (choked)" if nozzle.choked else "")
        kd_default = DEFAULT_KD["two-phase"]
        kd_why = (f"For two-phase flow a discharge coefficient Kd = {DEFAULT_KD['two-phase']} is commonly used "
                  "for preliminary sizing when no certified two-phase value is available.")
    kd = inp.kd if inp.kd is not None else kd_default

    rep.add_step(
        "Mass flux by direct integration",
        text=("The fluid is expanded isentropically from P₁, assuming liquid and vapour stay in equilibrium and "
              "travel at the same speed (homogeneous equilibrium model). At each pressure the mass flux is "
              "G = ρ·√(2(h₁ − h)). "
              + (f"G is greatest at a throat pressure of {fmt(nozzle.throat_pressure)} kPa(a), which is above "
                 f"the back pressure, so the flow is choked." if nozzle.choked else
                 "G keeps rising down to the back pressure, so the flow is not choked and G at the back "
                 "pressure is used.")
              + f" At the throat the fluid is {throat.describe().lower()}."),
        equation=r"G = \max_{P_2 \le P \le P_1} \; \rho(P, s_1)\,\sqrt{2\,[h_1 - h(P, s_1)]}",
        result=(rf"G = {num(nozzle.mass_flux, 5)}{unit('kg/(s·m^2)')} \quad "
                rf"\text{{at }} P_t = {num(nozzle.throat_pressure, 5)}{unit('kPa(a)')}"),
        reference="API 520 Part I, Annex C (homogeneous direct integration)",
    )
    if inp.kd is None:
        kd_text = kd_why + " Use the manufacturer's certified value if you have one."
    else:
        kd_text = "Kd entered by the user."
    _coeff_step(rep, inp, kd, kb, kc, "two-phase", kd_text=kd_text)

    A = W / 3600.0 / (kd * kb * kc * nozzle.mass_flux) * 1e6
    rep.add_step(
        "Required area",
        equation=r"A = \frac{W}{K_d\,K_b\,K_c\,G}",
        substitution=(rf"A = \frac{{{num(W, 5)} / 3600}}{{{num(kd, 3)} \times {num(kb, 3)} \times "
                      rf"{num(kc, 3)} \times {num(nozzle.mass_flux, 5)}}} \times 10^6"),
        result=rf"A = {num(A, 5)}{unit('mm^2')} \;=\; {num(A / IN2_TO_MM2, 4)}{unit('in^2')}",
    )
    coeffs = {"Kd": kd, "Kb": kb, "Kc": kc}
    return A, "Direct integration of isentropic nozzle flow (HDI)", regime, coeffs, {}, nozzle


def _size_liquid(inp, rep, state, P1, P2, kc, warnings):
    W = inp.flow_kg_h
    kd = inp.kd if inp.kd is not None else DEFAULT_KD["liquid"]
    kw = 1.0
    if inp.valve_type == "balanced":
        kw = inp.kw if inp.kw is not None else 1.0
        if inp.kw is None and inp.back_pressure_kpag > 0:
            warnings.append(
                "Balanced bellows valve in liquid service: Kw was taken as 1.0. Read Kw from the manufacturer's "
                "curve and enter it."
            )
    rho_ref = state_PT(P_ATM_KPA, 15.56).rho
    sg = state.rho / rho_ref
    Q = W / state.rho * 1000.0 / 60.0  # L/min
    dP = P1 - P2

    rep.add_step(
        "Volumetric flow and specific gravity",
        text=("The liquid equation uses volumetric flow Q in L/min and specific gravity G relative to water at "
              f"15.6 °C ({fmt(rho_ref)} kg/m³)."),
        equation=r"Q = \frac{W}{\rho} \cdot \frac{1000}{60}, \qquad G = \frac{\rho}{\rho_{ref}}",
        substitution=(rf"Q = \frac{{{num(W, 5)}}}{{{num(state.rho, 5)}}} \cdot \frac{{1000}}{{60}}, \qquad "
                      rf"G = \frac{{{num(state.rho, 5)}}}{{{num(rho_ref, 5)}}}"),
        result=rf"Q = {num(Q, 5)}{unit('L/min')}, \qquad G = {num(sg, 4)}",
    )

    A = 11.78 * Q / (kd * kw * kc) * math.sqrt(sg / dP)
    kv, re = 1.0, float("inf")
    mu_cp = (state.mu or 0.0) * 1000.0
    if mu_cp > 0:
        q_gpm = Q / 3.785411784
        for _ in range(20):
            kv_new, re = viscosity_correction(q_gpm, sg, mu_cp, A / IN2_TO_MM2)
            A_new = 11.78 * Q / (kd * kw * kc * kv_new) * math.sqrt(sg / dP)
            if abs(A_new - A) < 1e-9 * A:
                kv, A = kv_new, A_new
                break
            kv, A = kv_new, A_new
    rep.add_step(
        "Viscosity correction factor Kv",
        text=(f"Water is thin (viscosity {fmt(mu_cp)} cP), so the Reynolds number is high and Kv is close to 1. "
              "Kv is found by iteration using the required area and capped at 1.0."),
        equation=(r"Re = \frac{Q_{gpm} \cdot 18800 \cdot G}{\mu \sqrt{A_{in^2}}}, \quad "
                  r"K_v = \left(0.9935 + \frac{2.878}{Re^{0.7}} + \frac{342.75}{Re^{1.5}}\right)^{-1}"),
        result=rf"Re = {num(re, 4)}, \quad K_v = {num(kv, 4)}",
        reference="API 520 Part I, liquid sizing (viscosity correction)",
    )
    if kv < 0.98:
        warnings.append(f"Viscosity correction is significant (Kv = {fmt(kv, 3)}).")

    _coeff_step(rep, inp, kd, 1.0, kc, "liquid", kw=kw)
    rep.add_step(
        "Required area — API 520 liquid equation",
        text=("For liquids in valves requiring capacity certification (SI form: A in mm², Q in L/min, "
              "pressures in kPa)."),
        equation=r"A = \frac{11.78\,Q}{K_d\,K_w\,K_c\,K_v}\sqrt{\frac{G}{P_1 - P_2}}",
        substitution=(rf"A = \frac{{11.78 \times {num(Q, 5)}}}{{{num(kd, 3)} \times {num(kw, 3)} \times "
                      rf"{num(kc, 3)} \times {num(kv, 4)}}}\sqrt{{\frac{{{num(sg, 4)}}}{{{num(P1, 5)} - {num(P2, 5)}}}}}"),
        result=rf"A = {num(A, 5)}{unit('mm^2')} \;=\; {num(A / IN2_TO_MM2, 4)}{unit('in^2')}",
        reference="API 520 Part I, sizing for liquid relief: valves requiring capacity certification",
    )

    # cross-check with direct integration (incompressible here, so should match closely)
    nozzle = isentropic_nozzle_flow(state, P2)
    A_hdi = W / 3600.0 / (kd * kw * kc * kv * nozzle.mass_flux) * 1e6
    rep.add_step(
        "Cross-check by direct integration",
        text=(f"Direct integration gives G = {fmt(nozzle.mass_flux)} kg/(s·m²) at the back pressure, needing "
              f"A = {fmt(A_hdi)} mm² with the same coefficients. For a liquid that does not flash this is "
              "Bernoulli's equation, so the two methods should agree closely."),
    )
    coeffs = {"Kd": kd, "Kw": kw, "Kc": kc, "Kv": kv}
    return A, "API 520 liquid equation", "Liquid (no flashing)", coeffs, {"Direct integration (HDI)": A_hdi}, nozzle


def _coeff_step(rep, inp, kd, kb, kc, regime, kw=None, kd_text=None):
    rows = [["Coefficient", "Value", "Meaning"]]
    if kd_text is None:
        kd_text = ("Entered by the user." if inp.kd is not None else
                   f"API effective coefficient for preliminary sizing in {regime} service.")
    rows.append(["Kd", fmt(kd, 3), "Effective discharge coefficient. " + kd_text])
    if regime != "liquid":
        if inp.valve_type == "balanced":
            kb_text = "Back pressure correction for a balanced bellows valve (from the manufacturer's curve)."
        else:
            kb_text = ("Back pressure correction: 1.0 for conventional and pilot-operated valves "
                       "(back pressure effects are included in the flow calculation).")
        rows.append(["Kb", fmt(kb, 3), kb_text])
    if kw is not None:
        rows.append(["Kw", fmt(kw, 3), "Back pressure correction for balanced bellows valves in liquid service "
                     "(1.0 for conventional valves)."])
    rows.append(["Kc", fmt(kc, 3), "Combination factor: 0.9 with a rupture disk upstream (no certified "
                 "combination), 1.0 without."])
    rep.add_step("Correction factors", table=rows, reference="API 520 Part I")


def _assumptions(inp: ReliefInput) -> list[str]:
    items = [
        "The required relieving rate is an input here. The relief scenarios (API 521: fire, control valve "
        "failure, blocked outlet, tube rupture, ...) can work it out, and size the valve for the governing case.",
        "Inlet pressure loss, built-up back pressure and reaction force are checked when the inlet and "
        "discharge lines are given; otherwise keep the inlet loss below 3 % of set pressure (API 520 Part II) "
        "and check the discharge piping separately.",
        "Fluid properties are from IAPWS-IF97. Direct integration assumes isentropic, homogeneous-equilibrium "
        "flow through an ideal nozzle, corrected by the discharge coefficient.",
    ]
    if inp.overpressure_basis == "boiler":
        items.append("ASME Section I also limits the total pressure rise with all valves open to 6 % above the "
                     "highest set pressure; check this when several valves are installed.")
    return items
