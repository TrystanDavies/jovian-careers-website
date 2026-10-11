"""Relieving-rate scenarios for water and steam systems (API 521).

Each scenario works out how much the relief valve must pass, and what it
relieves (steam, wet steam or water and its condition at the relieving
pressure), with the calculation shown step by step. The relief valve is
then sized for every scenario that applies; the scenario needing the
largest orifice area governs.

Scenarios
---------
* External fire on a vessel containing water (API 521 heat input, wetted area)
* Control valve or pressure-reducing valve failing open (plus its bypass)
* Blocked outlet (pump against its curve, or a supply through an open valve)
* Heat exchanger tube rupture (two orifices of the tube bore, 10/13 rule)
* Thermal (hydraulic) expansion of blocked-in water
* Loss of cooling to a condenser
* Abnormal heat input (heating medium on a blocked-in boiling side)
* Boiler maximum continuous rating (ASME Section I)
* A rate given by the user
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .flowsheet.core import Param
from .hydraulics import G_ACC, valve_flow
from .relief import isentropic_nozzle_flow
from .report import Step, num, tex_text, unit
from .units import fmt
from .water import P_CRIT_KPA, WaterPropertyError, WaterState, T_sat, state_Ph, state_PT, state_Px

FIRE_ZONE_M = 7.6  # API 521: wetted area counts up to 7.6 m (25 ft) above grade

ENVIRONMENT_FACTORS = {
    "Bare vessel (F = 1.0)": 1.0,
    "Water application / deluge (F = 1.0)": 1.0,
    "Depressuring and emptying facilities (F = 1.0)": 1.0,
    "Earth-covered storage above grade (F = 0.03)": 0.03,
    "Below-grade storage (F = 0)": 0.0,
    "Fire-proof insulation: enter F": None,
}


@dataclass
class ScenarioResult:
    key: str
    title: str
    rate_kg_h: float
    fluid: str  # relief.FLUIDS key
    temperature_c: float | None = None
    dryness: float | None = None
    overpressure_basis: str | None = None  # None = use the valve's own basis
    steps: list[Step] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    applies: bool = True  # False when the scenario does not need relief (e.g. 10/13 rule)
    note: str = ""

    def describe_fluid(self) -> str:
        if self.fluid == "superheated_steam":
            return f"superheated steam at {fmt(self.temperature_c)} °C"
        if self.fluid == "wet_steam":
            return f"wet steam (dryness {fmt(self.dryness, 3)})"
        if self.fluid == "water":
            return f"water at {fmt(self.temperature_c)} °C"
        return "saturated steam"


def fluid_from_state(st: WaterState, P1: float) -> dict:
    """The relief sizing fluid (and its temperature or dryness) for a state at the relieving pressure."""
    if st.phase == "two-phase":
        return {"fluid": "wet_steam", "dryness": min(max(st.x, 1e-4), 0.9999)}
    if st.is_vapour_like:
        if P1 < P_CRIT_KPA and st.T > T_sat(P1) + 0.5:
            return {"fluid": "superheated_steam", "temperature_c": st.T}
        return {"fluid": "saturated_steam"}
    if P1 < P_CRIT_KPA and st.T >= T_sat(P1) - 0.02:  # saturated water: flashes in the valve
        return {"fluid": "wet_steam", "dryness": 1e-4}
    return {"fluid": "water", "temperature_c": st.T}


def condition_inputs(st: WaterState) -> dict:
    """Scenario condition settings that reproduce a state (for filling inputs from the drawing)."""
    if st.phase == "two-phase":
        return {"condition": "Wet steam", "dryness": st.x}
    if st.phase == "saturated vapour":
        return {"condition": "Saturated steam"}
    if st.phase == "saturated liquid":
        return {"condition": "Saturated water"}
    if st.is_vapour_like:
        return {"condition": "Superheated steam", "temperature": st.T}
    return {"condition": "Water", "temperature": st.T}


def _state_from_inputs(P: float, condition: str, T: float | None, x: float | None) -> WaterState:
    if condition == "Saturated steam":
        return state_Px(P, 1.0)
    if condition == "Wet steam":
        return state_Px(P, float(x))
    if condition == "Saturated water":
        return state_Px(P, 0.0)
    return state_PT(P, float(T))


def _latent(P1: float, warnings: list[str]) -> float:
    if P1 >= 0.98 * P_CRIT_KPA:
        raise ValueError("The relieving pressure is at or above the critical pressure: there is no latent heat, so "
                         "the vapour generation rate cannot be found this way. Use a dynamic (transient) analysis.")
    hf, hg = state_Px(P1, 0.0).h, state_Px(P1, 1.0).h
    if P1 > 0.8 * P_CRIT_KPA:
        warnings.append("Near the critical pressure the latent heat is small and the vapour generation rate "
                        "becomes very sensitive; consider a transient analysis.")
    return hg - hf


# --- input definitions (shared by the web forms) ---------------------------------------------

CONDITIONS = ("Saturated steam", "Superheated steam", "Wet steam", "Saturated water", "Water")


def _cond_params(prefix: str = "", label: str = "Upstream") -> list[Param]:
    k = f"{prefix}condition"
    return [
        Param(k, f"{label} condition", "choice", "Saturated steam", choices=CONDITIONS),
        Param(f"{prefix}temperature", f"{label} temperature", "temperature", 200.0,
              show_if=(k, ("Superheated steam", "Water"))),
        Param(f"{prefix}dryness", f"{label} dryness fraction", "fraction", 0.9, min_value=0.0, max_value=1.0,
              show_if=(k, ("Wet steam",))),
    ]


@dataclass(frozen=True)
class ScenarioType:
    key: str
    label: str
    description: str
    params: list[Param]
    calc: Callable[[dict, float], ScenarioResult]
    block_param: str | None = None  # a 'block_choice' that can fill the inputs from the drawing
    block_types: tuple[str, ...] = ()


def _p(inputs: dict, key: str, default=None):
    v = inputs.get(key, default)
    return default if v is None else v


# --- scenario calculations -------------------------------------------------------------------


def fire(inputs: dict, P1: float) -> ScenarioResult:
    warnings: list[str] = []
    steps: list[Step] = []
    orient = _p(inputs, "orientation", "Vertical")
    D, L = float(_p(inputs, "diameter", 2.0)), float(_p(inputs, "length", 4.0))
    level, elev = float(_p(inputs, "level", 1.5)), float(_p(inputs, "elevation", 0.0))
    a_given = float(_p(inputs, "wetted_area", 0.0))
    if a_given > 0:
        A = a_given
        steps.append(Step("Wetted area", text="Wetted area entered directly.",
                          result=rf"A_{{ws}} = {num(A, 4)}{unit('m^2')}"))
    else:
        if D <= 0 or L <= 0:
            raise ValueError("Enter the vessel diameter and length (or the wetted area).")
        h = max(min(level, FIRE_ZONE_M - elev, D if orient == "Horizontal" else L), 0.0)
        if orient == "Vertical":
            A = math.pi * D * h + (math.pi * D * D / 4.0 if elev < FIRE_ZONE_M and h > 0 else 0.0)
            eq = r"A_{ws} = \pi D h + \frac{\pi D^2}{4}"
            sub = rf"A_{{ws}} = \pi \times {num(D, 4)} \times {num(h, 4)} + \frac{{\pi \times {num(D, 4)}^2}}{{4}}"
        else:
            theta = 2.0 * math.acos(max(min(1.0 - 2.0 * h / D, 1.0), -1.0))
            A = theta * D * L / 2.0 + 2.0 * (D * D / 8.0) * (theta - math.sin(theta))
            eq = r"\theta = 2\cos^{-1}\left(1 - \frac{2h}{D}\right), \quad A_{ws} = \frac{\theta D L}{2} + 2\cdot\frac{D^2}{8}(\theta - \sin\theta)"
            sub = rf"\theta = {num(theta, 4)}" + tex_text(" rad")
        steps.append(Step(
            "Wetted area",
            text=(f"{orient} vessel, {fmt(D)} m diameter × {fmt(L)} m, liquid {fmt(level)} m deep, bottom "
                  f"{fmt(elev)} m above grade. Only the surface wetted by the liquid and within "
                  f"{FIRE_ZONE_M} m of grade (the height of a pool fire) counts: wetted height h = {fmt(h)} m. "
                  "Heads are treated as flat (slightly conservative for dished heads)."),
            equation=eq, substitution=sub, result=rf"A_{{ws}} = {num(A, 4)}{unit('m^2')}",
            reference="API 521, wetted surface and fire zone"))
    env = _p(inputs, "environment", "Bare vessel (F = 1.0)")
    F = ENVIRONMENT_FACTORS.get(env)
    if F is None:
        F = float(_p(inputs, "f_factor", 1.0))
    drained = _p(inputs, "drainage", "Yes") == "Yes"
    C = 43.2 if drained else 70.9
    Q = C * F * A**0.82
    steps.append(Step(
        "Heat input from the fire",
        text=("With adequate drainage and prompt fire-fighting C = 43.2 (43,200 W), otherwise C = 70.9. "
              f"Environment factor F = {fmt(F, 3)} ({env})."),
        equation=r"Q = C \cdot F \cdot A_{ws}^{0.82}",
        substitution=rf"Q = {num(C, 3)} \times {num(F, 3)} \times {num(A, 4)}^{{0.82}}",
        result=rf"Q = {num(Q, 5)}{unit('kW')}",
        reference="API 521, heat absorption equations for liquid-filled vessels"))
    lam = _latent(P1, warnings)
    W = Q / lam * 3600.0
    steps.append(Step(
        "Steam generated",
        text=(f"The heat boils the water at the relieving pressure ({fmt(P1)} kPa(a), {fmt(T_sat(P1))} °C). "
              "Sensible heating of the water is ignored (conservative)."),
        equation=r"W = \frac{Q}{\lambda}, \qquad \lambda = h_g - h_f",
        substitution=rf"W = \frac{{{num(Q, 5)}}}{{{num(lam, 5)}}} \times 3600",
        result=rf"W = {num(W, 5)}{unit('kg/h')}" + tex_text(" of saturated steam")))
    if F == 0:
        warnings.append("Environment factor 0: below-grade storage is not exposed to fire.")
    return ScenarioResult("fire", "External fire", W, "saturated_steam", overpressure_basis="fire", steps=steps,
                          warnings=warnings, applies=W > 0)


def _valve_upstream(inputs: dict) -> WaterState:
    return _state_from_inputs(float(_p(inputs, "upstream_pressure", 1101.325)), _p(inputs, "condition",
                              "Saturated steam"), _p(inputs, "temperature"), _p(inputs, "dryness"))


def valve_failure(inputs: dict, P1: float, title: str = "Control valve fails open", key: str = "cv_failure",
                  credit: bool = True) -> ScenarioResult:
    warnings: list[str] = []
    up = _valve_upstream(inputs)
    if up.P <= P1:
        return ScenarioResult(key, title, 0.0, "saturated_steam", applies=False,
                              note="The upstream pressure is not above the relieving pressure: no relief needed.",
                              steps=[Step(title, text=(f"The upstream pressure ({fmt(up.P)} kPa(a)) cannot raise the "
                                                       f"protected system above its relieving pressure "
                                                       f"({fmt(P1)} kPa(a)), so this case needs no relief."))])
    cv = float(_p(inputs, "cv", 0.0))
    cv_bp = float(_p(inputs, "bypass_cv", 0.0)) if _p(inputs, "bypass_open", "No") == "Yes" else 0.0
    if cv <= 0:
        raise ValueError("Enter the valve's rated (fully open) Cv.")
    fl, xt = float(_p(inputs, "fl", 0.9)), float(_p(inputs, "xt", 0.7))
    m = valve_flow(up, P1, cv + cv_bp, fl, xt)
    W = m * 3600.0
    steps = [Step(
        "Flow through the fully open valve",
        text=(f"Upstream: {up.describe().lower()} at {fmt(up.P)} kPa(a) (the highest pressure it can see). "
              f"Downstream at the relieving pressure {fmt(P1)} kPa(a). Valve fully open, Cv = {fmt(cv, 4)}"
              + (f" plus the bypass, Cv = {fmt(cv_bp, 4)}" if cv_bp else " (bypass closed in normal operation)")
              + ". The IEC 60534 equations, including choked flow, give the flow."),
        equation=r"W = f(C_v,\ P_{up},\ P_1)" + tex_text(" (IEC 60534-2-1 solved for the flow)"),
        result=rf"W = {num(W, 5)}{unit('kg/h')}",
        reference="API 521, control valve failure")]
    credit_kg_h = float(_p(inputs, "credit", 0.0)) * 3600.0 if credit else 0.0
    if credit_kg_h > 0:
        W_net = max(W - credit_kg_h, 0.0)
        steps.append(Step("Credit for normal outflow",
                          text=("Flow that continues to leave the protected system through outlets that stay open "
                                "may be deducted (API 521), if they are sure to remain open."),
                          equation=r"W_{relief} = W - W_{out}",
                          substitution=rf"W_{{relief}} = {num(W, 5)} - {num(credit_kg_h, 5)}",
                          result=rf"W_{{relief}} = {num(W_net, 5)}{unit('kg/h')}"))
        W = W_net
    down = state_Ph(P1, up.h)
    fl_kw = fluid_from_state(down, P1)
    steps.append(Step("Relieving fluid",
                      text=(f"Throttled through the valve at constant enthalpy to {fmt(P1)} kPa(a), the fluid is "
                            f"{down.describe().lower()}.")))
    return ScenarioResult(key, title, W, **fl_kw, steps=steps, warnings=warnings, applies=W > 0)


def blocked_outlet(inputs: dict, P1: float) -> ScenarioResult:
    source = _p(inputs, "source", "Pump (curve)")
    if source == "Supply through a fully open valve":
        return valve_failure(inputs, P1, "Blocked outlet", "blocked_outlet", credit=False)
    if source == "Given flow":
        st = _state_from_inputs(P1, _p(inputs, "condition", "Saturated steam"), _p(inputs, "temperature"),
                                _p(inputs, "dryness"))
        W = float(_p(inputs, "flow", 0.0)) * 3600.0
        return ScenarioResult("blocked_outlet", "Blocked outlet", W, **fluid_from_state(st, P1),
                              steps=[Step("Blocked outlet", text="Maximum inflow entered by the user.",
                                          result=rf"W = {num(W, 5)}{unit('kg/h')}")], applies=W > 0)
    Ps = float(_p(inputs, "suction_pressure", 201.325))
    T = float(_p(inputs, "suction_temperature", 105.0))
    h0, qr, hr = float(_p(inputs, "shutoff_head", 150.0)), float(_p(inputs, "rated_flow", 20.0)), \
        float(_p(inputs, "rated_head", 120.0))
    st = state_PT(Ps, T)
    if not st.is_liquid_like:
        raise ValueError("The pump suction must be water (below boiling at the suction pressure).")
    head_needed = (P1 - Ps) * 1000.0 / (st.rho * G_ACC)
    steps = [Step("Head at the relieving pressure",
                  text=(f"With the outlet blocked, the pump pushes the protected system up to the relieving "
                        f"pressure. Suction {fmt(Ps)} kPa(a), water at {fmt(T)} °C (ρ = {fmt(st.rho)} kg/m³)."),
                  equation=r"H = \frac{P_1 - P_s}{\rho g}",
                  substitution=rf"H = \frac{{({num(P1, 5)} - {num(Ps, 5)}) \times 1000}}{{{num(st.rho, 5)} \times 9.807}}",
                  result=rf"H = {num(head_needed, 4)}{unit('m')}")]
    if head_needed >= h0 or qr <= 0:
        steps.append(Step("Pump flow", text=(f"The pump's shut-off head ({fmt(h0)} m) cannot reach the relieving "
                                             "pressure, so a blocked outlet does not overpressure the system.")))
        return ScenarioResult("blocked_outlet", "Blocked outlet", 0.0, "water", temperature_c=T, steps=steps,
                              applies=False, note="The pump cannot reach the relieving pressure.")
    q = qr * math.sqrt((h0 - head_needed) / (h0 - hr)) if h0 > hr else 0.0
    W = q * st.rho
    steps.append(Step("Pump flow at that head",
                      text="From the pump curve, a parabola through the shut-off head and the rated point.",
                      equation=r"Q = Q_r\sqrt{\frac{H_0 - H}{H_0 - H_r}}, \qquad W = \rho Q",
                      substitution=rf"Q = {num(qr, 4)}\sqrt{{\frac{{{num(h0, 4)} - {num(head_needed, 4)}}}{{{num(h0, 4)} - {num(hr, 4)}}}}}",
                      result=rf"Q = {num(q, 4)}{unit('m^3/h')}, \quad W = {num(W, 5)}{unit('kg/h')}"))
    return ScenarioResult("blocked_outlet", "Blocked outlet (pump)", W, **fluid_from_state(state_PT(P1, T), P1),
                          steps=steps, applies=W > 0)


def tube_rupture(inputs: dict, P1: float) -> ScenarioResult:
    warnings: list[str] = []
    steps: list[Step] = []
    hp_design = float(_p(inputs, "hp_design", 2000.0))
    lp_design = float(_p(inputs, "lp_design", 1000.0))
    ratio = lp_design / hp_design if hp_design > 0 else 1.0
    rule_ok = lp_design >= 10.0 / 13.0 * hp_design
    steps.append(Step(
        "10/13 rule",
        text=("A tube rupture need not be a relief case if the low-pressure side's test pressure (1.3 × its design "
              "pressure) is at least the high-pressure side's design pressure, i.e. P_LP ≥ (10/13)·P_HP. "
              + (f"Here {fmt(lp_design)} ≥ {fmt(10 / 13 * hp_design)} kPa(g): the case can be excluded."
                 if rule_ok else
                 f"Here {fmt(lp_design)} < {fmt(10 / 13 * hp_design)} kPa(g): the rupture must be relieved.")),
        equation=r"P_{LP,design} \ge \tfrac{10}{13}\,P_{HP,design}",
        result=rf"\frac{{P_{{LP}}}}{{P_{{HP}}}} = {num(ratio, 4)}" + tex_text(" (10/13 = 0.769)"),
        reference="API 521, heat exchanger tube rupture"))
    up = _state_from_inputs(float(_p(inputs, "upstream_pressure", 2101.325)), _p(inputs, "condition", "Water"),
                            _p(inputs, "temperature", 150.0), _p(inputs, "dryness"))
    d = float(_p(inputs, "tube_id", 15.75)) / 1000.0
    cd = float(_p(inputs, "cd", 0.7))
    if up.P <= P1:
        return ScenarioResult("tube_rupture", "Tube rupture", 0.0, "water", temperature_c=up.T, steps=steps,
                              applies=False, note="The high-pressure side is not above the relieving pressure.")
    noz = isentropic_nozzle_flow(up, P1)
    A = math.pi * d * d / 4.0
    W = 2.0 * cd * A * noz.mass_flux * 3600.0
    steps.append(Step(
        "Flow through the broken tube",
        text=(f"A clean break of one tube: fluid enters through both open ends, each an orifice of the tube bore "
              f"({fmt(d * 1000)} mm). High-pressure side: {up.describe().lower()} at {fmt(up.P)} kPa(a) "
              f"({_p(inputs, 'hp_basis', 'maximum operating pressure')}). The mass flux G comes from isentropic "
              f"homogeneous expansion to the relieving pressure ({'choked' if noz.choked else 'not choked'}, throat "
              f"{fmt(noz.throat_pressure)} kPa(a)), with a discharge coefficient Cd = {fmt(cd, 3)}."),
        equation=r"W = 2\,C_d\,\frac{\pi d^2}{4}\,G",
        substitution=rf"W = 2 \times {num(cd, 3)} \times {num(A * 1e6, 4)}\times 10^{{-6}} \times {num(noz.mass_flux, 5)} \times 3600",
        result=rf"W = {num(W, 5)}{unit('kg/h')}",
        reference="API 521, tube rupture flow through two orifices"))
    down = state_Ph(P1, up.h)
    if up.is_vapour_like or up.phase == "two-phase":
        warnings.append("Steam entering a liquid-full low-pressure side first pushes out liquid at about the same "
                        "volumetric rate, and can cause pressure peaks a steady calculation does not show. API 521 "
                        "recommends a dynamic analysis when the low-pressure side is liquid-full.")
    if not rule_ok:
        pass
    return ScenarioResult("tube_rupture", "Tube rupture", W, **fluid_from_state(down, P1), steps=steps,
                          warnings=warnings, applies=not rule_ok,
                          note="Excluded by the 10/13 rule." if rule_ok else "")


def thermal_expansion(inputs: dict, P1: float) -> ScenarioResult:
    Q = float(_p(inputs, "heat_input", 10.0))  # kW
    T = float(_p(inputs, "temperature", 60.0))
    st = state_PT(P1, T)
    if not st.is_liquid_like:
        raise ValueError("Thermal expansion relief is for blocked-in liquid: the water would boil at this "
                         "temperature and the relieving pressure.")
    dT = 0.5
    r_hi, r_lo = state_PT(P1, T + dT).rho, state_PT(P1, T - dT).rho
    alpha = -(r_hi - r_lo) / (2 * dT) / st.rho
    W = alpha * Q / st.cp * 3600.0
    qv = W / st.rho * 1000.0 / 60.0  # L/min
    steps = [Step(
        "Expansion of the blocked-in water",
        text=(f"Heat input {fmt(Q)} kW into water at {fmt(T)} °C and {fmt(P1)} kPa(a). The cubic expansion "
              "coefficient α_v and the specific heat come from IAPWS-IF97."),
        equation=r"\alpha_v = -\frac{1}{\rho}\frac{\partial \rho}{\partial T}, \qquad W = \frac{\alpha_v\,\Phi}{c_p}",
        substitution=rf"W = \frac{{{num(alpha, 4)} \times {num(Q, 4)}}}{{{num(st.cp, 4)}}} \times 3600",
        result=rf"W = {num(W, 4)}{unit('kg/h')} \;({num(qv, 3)}{unit('L/min')})",
        reference="API 521, hydraulic (thermal) expansion")]
    return ScenarioResult("thermal", "Thermal expansion", W, "water", temperature_c=T, steps=steps,
                          warnings=["Thermal relief valves are usually a nominal size (e.g. ¾ in × 1 in); the rate "
                                    "is tiny and the valve need not be sized for it."], applies=W > 0)


def loss_of_cooling(inputs: dict, P1: float) -> ScenarioResult:
    up = _state_from_inputs(P1, _p(inputs, "condition", "Saturated steam"), _p(inputs, "temperature"),
                            _p(inputs, "dryness"))
    W = float(_p(inputs, "flow", 1.0)) * 3600.0
    steps = [Step("Steam no longer condensed",
                  text=("With no cooling water the condenser stops condensing: all the steam flowing in must be "
                        "relieved (no credit is taken for the shell's heat losses)."),
                  equation=r"W = \dot m_{steam,in}", result=rf"W = {num(W, 5)}{unit('kg/h')}",
                  reference="API 521, loss of cooling")]
    return ScenarioResult("loss_of_cooling", "Loss of cooling", W, **fluid_from_state(up, P1), steps=steps,
                          applies=W > 0)


def heat_input(inputs: dict, P1: float) -> ScenarioResult:
    warnings: list[str] = []
    ua = float(_p(inputs, "ua", 20.0))
    Th = float(_p(inputs, "heating_temperature", 180.0))
    ts = T_sat(P1)
    lam = _latent(P1, warnings)
    dT = Th - ts
    if dT <= 0:
        return ScenarioResult("heat_input", "Abnormal heat input", 0.0, "saturated_steam", applies=False,
                              note="The heating medium is not hotter than the boiling point at the relieving pressure.",
                              steps=[Step("Heat input", text=(f"The heating medium ({fmt(Th)} °C) is not hotter than "
                                                              f"the boiling point at the relieving pressure "
                                                              f"({fmt(ts)} °C): nothing boils.")) ])
    Q = ua * dT
    W = Q / lam * 3600.0
    steps = [Step(
        "Vapour generated in the blocked-in side",
        text=(f"The heating medium at {fmt(Th)} °C keeps transferring heat to the blocked-in water, which boils at "
              f"{fmt(ts)} °C at the relieving pressure. UA = {fmt(ua)} kW/K (clean exchanger, conservative)."),
        equation=r"Q = UA\,(T_h - T_{sat}(P_1)), \qquad W = \frac{Q}{\lambda}",
        substitution=rf"Q = {num(ua, 4)} \times ({num(Th, 4)} - {num(ts, 4)}), \quad W = \frac{{{num(Q, 5)}}}{{{num(lam, 5)}}} \times 3600",
        result=rf"W = {num(W, 5)}{unit('kg/h')}", reference="API 521, abnormal heat input")]
    return ScenarioResult("heat_input", "Abnormal heat input", W, "saturated_steam", steps=steps, warnings=warnings,
                          applies=W > 0)


def boiler_mcr(inputs: dict, P1: float) -> ScenarioResult:
    W = float(_p(inputs, "flow", 1.0)) * 3600.0
    st = _state_from_inputs(P1, _p(inputs, "condition", "Saturated steam"), _p(inputs, "temperature"), None)
    steps = [Step("Boiler maximum continuous rating",
                  text=("ASME Section I: the safety valves together must discharge all the steam the boiler can "
                        "generate (its maximum continuous rating) at no more than 3 % (or 2 psi) overpressure."),
                  equation=r"W = W_{MCR}", result=rf"W = {num(W, 5)}{unit('kg/h')}",
                  reference="ASME Boiler and Pressure Vessel Code, Section I")]
    return ScenarioResult("boiler_mcr", "Boiler (ASME I)", W, **fluid_from_state(st, P1), overpressure_basis="boiler",
                          steps=steps, applies=W > 0)


def given_rate(inputs: dict, P1: float) -> ScenarioResult:
    st = _state_from_inputs(P1, _p(inputs, "condition", "Saturated steam"), _p(inputs, "temperature"),
                            _p(inputs, "dryness"))
    W = float(_p(inputs, "flow", 1.0)) * 3600.0
    return ScenarioResult("given", _p(inputs, "name", "") or "Given rate", W, **fluid_from_state(st, P1),
                          steps=[Step("Relieving rate", text="Rate entered by the user.",
                                      result=rf"W = {num(W, 5)}{unit('kg/h')}")], applies=W > 0)


_VALVE_PARAMS = [
    Param("upstream_pressure", "Highest upstream pressure", "pressure", 1101.325),
    *_cond_params(),
    Param("cv", "Valve Cv, fully open", "number", 50.0, min_value=0.0),
    Param("bypass_open", "Bypass open in normal operation", "choice", "No", choices=("No", "Yes")),
    Param("bypass_cv", "Bypass Cv", "number", 0.0, min_value=0.0, show_if=("bypass_open", ("Yes",))),
    Param("fl", "FL", "number", 0.9, min_value=0.3, max_value=1.0),
    Param("xt", "xT", "number", 0.7, min_value=0.1, max_value=1.0),
]

SCENARIO_TYPES: dict[str, ScenarioType] = {
    t.key: t for t in (
        ScenarioType("fire", "External fire", "A pool fire heats a vessel containing water; the steam generated "
                     "is relieved (21 % overpressure).", [
                         Param("orientation", "Vessel", "choice", "Vertical", choices=("Vertical", "Horizontal")),
                         Param("diameter", "Diameter", "length", 2.0, min_value=0.0),
                         Param("length", "Length (or height)", "length", 4.0, min_value=0.0),
                         Param("level", "Liquid level above the bottom", "length", 1.5, min_value=0.0),
                         Param("elevation", "Vessel bottom above grade", "length", 0.0, min_value=0.0),
                         Param("wetted_area", "Wetted area (0 = calculate)", "surface_area", 0.0, min_value=0.0),
                         Param("environment", "Environment factor", "choice", "Bare vessel (F = 1.0)",
                               choices=tuple(ENVIRONMENT_FACTORS)),
                         Param("f_factor", "Environment factor F", "number", 0.3, min_value=0.0, max_value=1.0,
                               show_if=("environment", ("Fire-proof insulation: enter F",))),
                         Param("drainage", "Adequate drainage and fire-fighting", "choice", "Yes",
                               choices=("Yes", "No")),
                     ], fire),
        ScenarioType("cv_failure", "Control valve fails open", "An upstream control valve or PRV fails wide open "
                     "(its bypass in its normal position).", [
                         Param("valve", "Valve on the drawing (fills in the values below)", "block_choice", ""),
                         *_VALVE_PARAMS,
                         Param("credit", "Credit for normal outflow", "mass_flow", 0.0, min_value=0.0),
                     ], valve_failure, block_param="valve", block_types=("valve",)),
        ScenarioType("blocked_outlet", "Blocked outlet", "The outlet is closed while the supply keeps running.", [
                         Param("source", "Supply", "choice", "Pump (curve)",
                               choices=("Pump (curve)", "Supply through a fully open valve", "Given flow")),
                         Param("pump", "Pump on the drawing (fills in the curve)", "block_choice", "",
                               show_if=("source", ("Pump (curve)",))),
                         Param("suction_pressure", "Suction pressure", "pressure", 201.325,
                               show_if=("source", ("Pump (curve)",))),
                         Param("suction_temperature", "Water temperature", "temperature", 105.0,
                               show_if=("source", ("Pump (curve)",))),
                         Param("shutoff_head", "Shut-off head", "head", 150.0, show_if=("source", ("Pump (curve)",))),
                         Param("rated_flow", "Rated flow", "volume_flow", 20.0, show_if=("source", ("Pump (curve)",))),
                         Param("rated_head", "Head at rated flow", "head", 120.0,
                               show_if=("source", ("Pump (curve)",))),
                         Param("flow", "Maximum inflow", "mass_flow", 1.0, show_if=("source", ("Given flow",))),
                     ] + [Param(p.key, p.label, p.kind, p.default, p.help, p.choices,
                                p.show_if or ("source", ("Supply through a fully open valve",)), p.min_value,
                                p.max_value) for p in _VALVE_PARAMS], blocked_outlet,
                     block_param="pump", block_types=("pump",)),
        ScenarioType("tube_rupture", "Tube rupture", "A tube breaks in a heat exchanger and the high-pressure fluid "
                     "flows into the low-pressure side.", [
                         Param("hp_design", "High-pressure side design pressure", "pressure_diff", 2000.0),
                         Param("lp_design", "Low-pressure side design pressure", "pressure_diff", 1000.0),
                         Param("upstream_pressure", "High-pressure side pressure", "pressure", 2101.325),
                         Param("hp_basis", "That pressure is the", "choice", "maximum operating pressure",
                               choices=("maximum operating pressure", "design pressure")),
                         *_cond_params(label="High-pressure fluid"),
                         Param("tube_id", "Tube inside diameter", "diameter", 15.75, min_value=1.0),
                         Param("cd", "Discharge coefficient Cd", "number", 0.7, min_value=0.3, max_value=1.0,
                               help="About 0.6–0.7 for a sharp-edged break; API 521 leaves it to the engineer."),
                     ], tube_rupture),
        ScenarioType("thermal", "Thermal expansion", "Water trapped between closed valves is heated (sun, tracing, "
                     "an exchanger) and expands.", [
                         Param("heat_input", "Heat input", "power", 10.0, min_value=0.0),
                         Param("temperature", "Water temperature", "temperature", 60.0),
                     ], thermal_expansion),
        ScenarioType("loss_of_cooling", "Loss of cooling", "Cooling water to a condenser fails; the steam coming in "
                     "is no longer condensed.", [
                         Param("condenser", "Condenser on the drawing (fills in the flow)", "block_choice", ""),
                         Param("flow", "Steam flow into the condenser", "mass_flow", 1.0, min_value=0.0),
                         *_cond_params(label="Steam"),
                     ], loss_of_cooling, block_param="condenser", block_types=("condenser",)),
        ScenarioType("heat_input", "Abnormal heat input", "A heating medium keeps heating a blocked-in water side, "
                     "which boils.", [
                         Param("exchanger", "Heat exchanger on the drawing (fills in UA and temperature)",
                               "block_choice", ""),
                         Param("ua", "UA of the exchanger (clean)", "ua", 20.0, min_value=0.0),
                         Param("heating_temperature", "Heating medium temperature", "temperature", 180.0),
                     ], heat_input, block_param="exchanger", block_types=("heat_exchanger",)),
        ScenarioType("boiler_mcr", "Boiler maximum rating", "ASME Section I: relieve the boiler's maximum continuous "
                     "rating (3 % overpressure).", [
                         Param("boiler", "Boiler on the drawing (fills in the flow)", "block_choice", ""),
                         Param("flow", "Maximum continuous rating", "mass_flow", 5.0, min_value=0.0),
                         Param("condition", "Steam condition", "choice", "Saturated steam",
                               choices=("Saturated steam", "Superheated steam")),
                         Param("temperature", "Steam temperature", "temperature", 250.0,
                               show_if=("condition", ("Superheated steam",))),
                     ], boiler_mcr, block_param="boiler", block_types=("boiler",)),
        ScenarioType("given", "Given rate", "A relieving rate you have worked out elsewhere.", [
                         Param("name", "Scenario name", "text", ""),
                         Param("flow", "Relieving rate", "mass_flow", 1.0, min_value=0.0),
                         *_cond_params(label="Relieving fluid"),
                     ], given_rate),
    )
}


def run_scenario(spec: dict, P1: float) -> ScenarioResult:
    """Calculate one scenario from its settings ({'type': key, ...inputs})."""
    st = SCENARIO_TYPES.get(spec.get("type", ""))
    if st is None:
        raise ValueError(f"Unknown relief scenario '{spec.get('type')}'.")
    defaults = {p.key: p.default for p in st.params}
    inputs = {**defaults, **{k: v for k, v in spec.items() if v is not None}}
    try:
        res = st.calc(inputs, P1)
    except WaterPropertyError as exc:
        raise ValueError(f"{st.label}: {exc}") from exc
    if spec.get("name") and st.key != "given":
        res.title = f"{res.title} — {spec['name']}"
    return res

