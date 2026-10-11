"""A relief valve with its scenarios and piping (API 520 Part II, API 521).

Builds on ``relief.size_relief_valve`` (one valve, one relieving rate):

* every relief scenario is sized in its own fluid and overpressure, and the
  one needing the largest orifice area governs;
* the inlet line's non-recoverable pressure loss at the valve's rated
  capacity is checked against 3 % of the set pressure;
* the back pressure built up by flow in the discharge line is found by
  working back from the outlet (a choked exit is found exactly), and the
  sizing is repeated with it until the orifice no longer changes;
* the reaction force at an open discharge is the exit momentum plus the
  exit pressure thrust, F = ṁ·v_e + (P_e − P_atm)·A_e, cross-checked with
  API 520 Part II's formula for vapour.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

from scipy.optimize import brentq

from .hydraulics import (
    ROUGHNESS,
    PipeChokedError,
    _energy_state,
    fittings_k,
    isentropic_exponent,
    pipe_dimensions,
    pipe_flow,
    sound_speed,
)
from .relief import (
    API526_ORIFICES,
    FLUIDS,
    IN2_TO_MM2,
    OVERPRESSURE_BASES,
    VALVE_TYPES,
    ReliefInput,
    ReliefResult,
    _overpressure,
    select_orifice,
    size_relief_valve,
)
from .report import CalcReport, Step, num, tex_text, unit
from .scenarios import ScenarioResult, run_scenario
from .units import fmt
from .water import WaterPropertyError, WaterState, state_Ph

MW_WATER = 18.015
R_UNIVERSAL = 8314.462618  # J/(kmol·K)


@dataclass
class LineSpec:
    """A run of pipe at the valve inlet or outlet."""

    nps: str = "3"
    schedule: str = "40"
    id_mm: float = 0.0  # a custom inside diameter overrides the nominal size when > 0
    length: float = 1.0
    fittings: dict = field(default_factory=dict)
    elevation: float = 0.0  # outlet above inlet, m
    roughness_mm: float = ROUGHNESS["Commercial steel, new"]

    def bore(self) -> tuple[float, float]:
        if self.id_mm and self.id_mm > 0:
            return float(self.id_mm), float(self.id_mm) * 1.1
        return pipe_dimensions(self.nps, self.schedule)

    def describe(self) -> str:
        d, _ = self.bore()
        size = f'{self.nps}" Sch {self.schedule}' if not self.id_mm else f"ID {fmt(d, 3)} mm"
        return f"{size}, {fmt(self.length, 3)} m" + (f", rising {fmt(self.elevation, 3)} m" if self.elevation else "")


@dataclass
class InletCheck:
    flow_kg_h: float
    dp_nonrecoverable: float
    dp_static: float
    dp_accel: float
    percent: float
    ok: bool
    velocity: float
    steps: list[Step]


@dataclass
class DischargeResult:
    flow_kg_h: float
    P_outlet: float  # kPa(a) at the valve outlet flange
    built_up: float  # kPa
    choked_exit: bool
    P_exit: float  # kPa(a) static pressure at the pipe exit
    v_exit: float
    exit_state: WaterState
    area_m2: float
    steps: list[Step]


@dataclass
class ReactionForce:
    force_n: float
    api_force_n: float | None
    steps: list[Step]


@dataclass
class ScenarioSizing:
    scenario: ScenarioResult
    relief: ReliefResult | None
    rated_kg_h: float | None = None  # what the selected orifice passes in this scenario (per valve)
    back_pressure_kpag: float = 0.0
    inlet: InletCheck | None = None
    discharge: DischargeResult | None = None
    error: str | None = None


@dataclass
class SystemResult:
    sizings: list[ScenarioSizing]
    governing: ScenarioSizing | None
    orifice: str | None
    orifice_area_mm2: float | None
    valves_needed: int
    reaction: ReactionForce | None
    report: CalcReport
    warnings: list[str]

    @property
    def applicable(self) -> list[ScenarioSizing]:
        return [z for z in self.sizings if z.relief is not None]


# --- inlet line ---------------------------------------------------------------------------


def inlet_check(m_kg_h: float, relieving: WaterState, line: LineSpec, set_kpag: float) -> InletCheck:
    """Pressure loss from the protected equipment to the valve inlet at the valve's rated flow."""
    d, _ = line.bore()
    k, rows = fittings_k(line.fittings, d)
    m = m_kg_h / 3600.0
    try:
        r = pipe_flow(m, relieving.P, relieving.h, d, line.length, line.roughness_mm, line.elevation, k)
    except PipeChokedError as exc:
        raise ValueError(f"The inlet line chokes at the valve's rated capacity ({fmt(m_kg_h)} kg/h): it is far too "
                         f"small. {exc}") from exc
    nonrec = r.dp_friction + r.dp_fittings
    pct = nonrec / set_kpag * 100.0
    ok = pct <= 3.0
    table = [["Fitting", "Number", "K each"]] + [[lbl, fmt(c, 3), fmt(ke, 3)] for lbl, c, ke in rows]
    steps = [Step(
        "Inlet pressure loss (3 % rule)",
        text=(f"Inlet line {line.describe()}, at the valve's rated capacity of {fmt(m_kg_h)} kg/h (not the required "
              f"rate), starting at the relieving pressure {fmt(relieving.P)} kPa(a). Only the non-recoverable "
              "losses (friction, entrance and fittings) count against the 3 % limit; the static head and "
              f"acceleration terms are shown separately ({fmt(r.dp_static, 3)} and {fmt(r.dp_accel, 3)} kPa). "
              + ("Within the limit." if ok else
                 "Above 3 %: the valve may chatter. Enlarge or shorten the inlet line, or justify the design by an "
                 "engineering analysis (API 520 Part II).")),
        equation=r"\frac{\Delta P_{friction} + \Delta P_{fittings}}{P_{set}} \le 3\,\%",
        substitution=rf"\frac{{{num(r.dp_friction, 4)} + {num(r.dp_fittings, 4)}}}{{{num(set_kpag, 5)}}}",
        result=rf"{num(pct, 3)}\,\%" + tex_text(" ✓" if ok else " ✗ (above 3 %)"),
        table=table if len(table) > 1 else None,
        reference="API 520 Part II, inlet piping pressure loss")]
    return InletCheck(m_kg_h, nonrec, r.dp_static, r.dp_accel, pct, ok, r.v_in, steps)


# --- discharge line --------------------------------------------------------------------------


def discharge_line(m_kg_h: float, h0: float, line: LineSpec, P_dest: float, P_max: float) -> DischargeResult:
    """Built-up back pressure: the valve outlet pressure that drives the flow through the discharge line.

    The march starts at the valve outlet from the relieving fluid's stagnation enthalpy (the static
    enthalpy there is lower by the kinetic energy). If even the lowest outlet pressure that avoids
    choking inside the pipe leaves an exit pressure above the destination, the exit is choked
    (sonic) and that is the answer; otherwise the outlet pressure is found that brings the exit to
    the destination pressure."""
    d, _ = line.bore()
    k, _ = fittings_k(line.fittings, d)
    m = m_kg_h / 3600.0
    area = math.pi * (d / 1000.0) ** 2 / 4.0
    G = m / area

    def march(Po: float):
        try:
            h = _energy_state(Po, h0, h0, G)
            return pipe_flow(m, Po, h, d, line.length, line.roughness_mm, line.elevation, k, strict=False)
        except (ValueError, WaterPropertyError, ZeroDivisionError):
            return None

    def passes(Po: float) -> bool:
        r = march(Po)
        return r is not None and not r.choked

    lo, hi = P_dest * (1.0 + 1e-9), P_max
    if not passes(hi):
        raise ValueError(f"The discharge line ({line.describe()}) cannot pass {fmt(m_kg_h)} kg/h even with the full "
                         "relieving pressure at the valve outlet: it is far too small.")
    if passes(lo):
        Po_min = lo
    else:
        a, b = lo, hi  # a chokes, b passes
        for _ in range(60):
            mid = 0.5 * (a + b)
            if passes(mid):
                b = mid
            else:
                a = mid
            if b - a < 1e-5 * b:
                break
        Po_min = b
    r_min = march(Po_min)
    choked_exit = Po_min > lo and r_min.P_out >= P_dest
    if choked_exit:
        Po, r = Po_min, r_min
    else:
        Po = brentq(lambda p: march(p).P_out - P_dest, Po_min, hi, xtol=1e-9 * hi, rtol=1e-10)
        r = march(Po)
    st_e = state_Ph(r.P_out, r.h_out)
    c = sound_speed(st_e)
    steps = [Step(
        "Built-up back pressure in the discharge line",
        text=(f"Discharge line {line.describe()}, total K = {fmt(k, 3)}, carrying the valve's rated flow of "
              f"{fmt(m_kg_h)} kg/h to {fmt(P_dest)} kPa(a). The pressure at the valve outlet is found that pushes "
              "this flow through the line: "
              + (f"the flow chokes at the pipe exit (velocity {fmt(r.v_out)} m/s = the speed of sound), so the exit "
                 f"pressure ({fmt(r.P_out)} kPa(a)) stays above the destination pressure."
                 if choked_exit else
                 f"the exit reaches the destination pressure at {fmt(r.v_out)} m/s (Mach "
                 f"{fmt(r.v_out / c, 2) if c else '–'}).")),
        equation=r"P_{outlet} - P_{dest} = \Delta P_{friction} + \Delta P_K + \Delta P_{static} + \Delta P_{acc}"
                 + (r"\;+\; (P_{exit} - P_{dest})_{choked}" if choked_exit else ""),
        result=(rf"P_{{outlet}} = {num(Po, 5)}{unit('kPa(a)')}, \quad \Delta P_{{built-up}} = {num(Po - P_dest, 4)}"
                rf"{unit('kPa')}"),
        reference="API 520 Part II, discharge piping")]
    return DischargeResult(m_kg_h, Po, Po - P_dest, choked_exit, r.P_out, r.v_out, st_e, area, steps)


def reaction_force(dis: DischargeResult, relieving: WaterState, p_atm: float) -> ReactionForce:
    """Steady reaction force at an open discharge to atmosphere."""
    m = dis.flow_kg_h / 3600.0
    F = m * dis.v_exit + (dis.P_exit - p_atm) * 1000.0 * dis.area_m2
    steps = [Step(
        "Reaction force at the open discharge",
        text=("A momentum balance on the discharge: the jet's momentum plus the thrust of the exit pressure "
              f"above atmospheric, over the exit area {fmt(dis.area_m2 * 1e4, 4)} cm². Exit conditions come from "
              "the discharge line calculation (IAPWS-IF97)."),
        equation=r"F = \dot m\,v_e + (P_e - P_{atm})\,A_e",
        substitution=(rf"F = {num(m, 4)} \times {num(dis.v_exit, 4)} + ({num(dis.P_exit, 5)} - {num(p_atm, 5)})"
                      rf"\times 1000 \times {num(dis.area_m2, 4)}"),
        result=rf"F = {num(F, 5)}{unit('N')} = {num(F / 1000.0, 4)}{unit('kN')}",
        reference="API 520 Part II, reaction forces (open discharge)")]
    F_api = None
    if relieving.is_vapour_like:
        k = isentropic_exponent(relieving)
        T0 = relieving.T + 273.15
        F_api = m * math.sqrt(2.0 * k * R_UNIVERSAL * T0 / ((k + 1.0) * MW_WATER)) + \
            (dis.P_exit - p_atm) * 1000.0 * dis.area_m2
        diff = (F_api - F) / F * 100.0 if F else 0.0
        steps.append(Step(
            "Cross-check: API 520 Part II formula for vapour",
            text=("API's formula treats the steam as an ideal gas leaving at the speed of sound, from the relieving "
                  f"temperature (k = {fmt(k, 3)}, M = 18.015). It differs from the momentum balance by "
                  f"{fmt(diff, 2)} %: it is conservative when the exit is not choked, and real-steam effects "
                  "(condensation lowers the speed of sound) account for the rest. Design for the larger of the two. "
                  "(In US units it reads F = (W/366)·√(kT/((k+1)M)) + A·P.)"),
            equation=r"F = \dot m\sqrt{\frac{2kR_uT_1}{(k+1)M}} + (P_e - P_{atm})A_e",
            result=rf"F = {num(F_api, 5)}{unit('N')}"))
    steps.append(Step("Dynamic load",
                      text=("This is the steady force. When the valve pops open the load is applied suddenly; "
                            "design the pipe supports for up to twice this value (dynamic load factor up to 2) "
                            "unless a dynamic analysis shows otherwise.")))
    return ReactionForce(F, F_api, steps)


# --- the whole system --------------------------------------------------------------------------


def _relieving_pressure(base: ReliefInput, basis: str) -> float:
    probe = dataclasses.replace(base, overpressure_basis=basis)
    _, dp, _ = _overpressure(probe)
    return base.set_pressure_kpag + dp + base.p_atm_kpa


def size_relief_system(base: ReliefInput, scenarios: list[dict] | None = None, inlet: LineSpec | None = None,
                       outlet: LineSpec | None = None, outlet_to: str = "atmosphere",
                       superimposed_kpag: float = 0.0) -> SystemResult:
    """Size a relief valve for several scenarios, with inlet and discharge piping checks.

    base: the valve (set pressure, type, overpressure basis, coefficients). Its fluid and flow are used
    when no scenarios are given. With a discharge line, the back pressure is the superimposed pressure
    at the line's end plus the built-up back pressure; without one, base.back_pressure_kpag is used."""
    warnings: list[str] = []
    p_atm = base.p_atm_kpa
    results: list[ScenarioResult] = []
    if scenarios:
        for spec in scenarios:
            if spec.get("enabled", True) is False:
                continue
            from .scenarios import SCENARIO_TYPES  # local: keeps imports one-way
            st = SCENARIO_TYPES.get(spec.get("type", ""))
            basis = "fire" if st is not None and st.key == "fire" else (
                "boiler" if st is not None and st.key == "boiler_mcr" else base.overpressure_basis)
            P1 = _relieving_pressure(base, basis)
            res = run_scenario(spec, P1)
            res.overpressure_basis = res.overpressure_basis or base.overpressure_basis
            results.append(res)
    else:
        results.append(ScenarioResult("given", "Required rate", base.flow_kg_h, base.fluid, base.temperature_c,
                                      base.dryness, base.overpressure_basis))
    sizings = [ScenarioSizing(r, None) for r in results]
    active = [z for z in sizings if z.scenario.applies and z.scenario.rate_kg_h > 0]
    for z in sizings:
        if z not in active:
            z.error = z.scenario.note or "No relief needed in this scenario."
    rep = CalcReport(title="Relief valve and scenarios" + (f" — {base.tag}" if base.tag else ""),
                     subtitle=base.service or "", disclaimer=None)
    if not active:
        rep.add_step("Scenarios", text="None of the scenarios needs relief.")
        return SystemResult(sizings, None, None, None, 0, None, rep, ["No scenario needs relief."])

    to_header = outlet is not None and outlet_to == "header"
    P_dest = (superimposed_kpag if to_header else 0.0) + p_atm
    bp = {id(z): (superimposed_kpag if to_header else 0.0) if outlet is not None else base.back_pressure_kpag
          for z in active}
    letter = a_orf = None
    n_valves = 1
    for _ in range(6):
        for z in active:
            sc = z.scenario
            inp = dataclasses.replace(base, fluid=sc.fluid, flow_kg_h=sc.rate_kg_h, temperature_c=sc.temperature_c,
                                      dryness=sc.dryness, overpressure_basis=sc.overpressure_basis,
                                      back_pressure_kpag=bp[id(z)])
            try:
                z.relief = size_relief_valve(inp)
                z.error = None
            except ValueError as exc:
                z.relief, z.error = None, str(exc)
            z.back_pressure_kpag = bp[id(z)]
        sized = [z for z in active if z.relief is not None]
        if not sized:
            break
        gov = max(sized, key=lambda z: z.relief.required_area_mm2)
        new_letter, a_orf, n_valves = select_orifice(gov.relief.required_area_mm2)
        changed = new_letter != letter
        letter = new_letter
        for z in sized:
            z.rated_kg_h = z.scenario.rate_kg_h * (a_orf * n_valves) / z.relief.required_area_mm2 / n_valves
        if outlet is None:
            break
        moved = False
        for z in sized:
            try:
                z.discharge = discharge_line(z.rated_kg_h, z.relief.relieving_state.h, outlet, P_dest,
                                             z.relief.relieving_pressure_kpa)
            except ValueError as exc:
                z.error = str(exc)
                z.discharge = None
                continue
            new_bp = P_dest - p_atm + z.discharge.built_up
            if abs(new_bp - bp[id(z)]) > max(0.2, 0.002 * base.set_pressure_kpag):
                moved = True
            bp[id(z)] = new_bp
        if not changed and not moved:
            break
    sized = [z for z in active if z.relief is not None]
    if not sized:
        rep.warnings = [z.error for z in active if z.error]
        return SystemResult(sizings, None, None, None, 0, None, rep, rep.warnings)
    gov = max(sized, key=lambda z: z.relief.required_area_mm2)

    for z in sized:
        if inlet is not None:
            try:
                z.inlet = inlet_check(z.rated_kg_h, z.relief.relieving_state, inlet, base.set_pressure_kpag)
            except ValueError as exc:
                z.error = str(exc)
                warnings.append(f"{z.scenario.title}: {exc}")
        if outlet is not None and z.discharge is None and z.error:
            warnings.append(f"{z.scenario.title}: {z.error}")
        if z.discharge is not None:
            basis = OVERPRESSURE_BASES.get(z.scenario.overpressure_basis or base.overpressure_basis)
            limit = (base.custom_overpressure_percent if z.scenario.overpressure_basis == "custom" and
                     base.custom_overpressure_percent else basis.percent if basis else 10.0)
            pct = z.discharge.built_up / base.set_pressure_kpag * 100.0
            if base.valve_type == "conventional" and pct > limit:
                warnings.append(f"{z.scenario.title}: built-up back pressure is {fmt(pct, 3)} % of set pressure, above "
                                f"the {fmt(limit, 3)} % allowable overpressure for a conventional valve. Enlarge the "
                                "discharge line, or use a balanced bellows or pilot-operated valve.")
            total = z.back_pressure_kpag / base.set_pressure_kpag * 100.0
            if base.valve_type == "balanced" and total > 50.0:
                warnings.append(f"{z.scenario.title}: total back pressure is {fmt(total, 3)} % of set pressure, "
                                "above the usual 50 % limit for balanced bellows valves.")
        if z.inlet is not None and not z.inlet.ok:
            warnings.append(f"{z.scenario.title}: inlet pressure loss is {fmt(z.inlet.percent, 3)} % of set "
                            "pressure, above 3 % (API 520 Part II).")
    if base.valve_type == "pilot" and outlet is not None:
        warnings.append("Pilot-operated valve: check the back pressure against the manufacturer's limits.")

    reaction = None
    if outlet is not None and not to_header:
        worst = max((z for z in sized if z.discharge is not None), key=lambda z: z.discharge.flow_kg_h
                    * z.discharge.v_exit, default=None)
        if worst is not None:
            reaction = reaction_force(worst.discharge, worst.relief.relieving_state, p_atm)

    # report
    rows = [["Scenario", "Relieving fluid", "Rate (kg/h)", "P₁ (kPa a)", "Area needed (mm²)",
             "Rated flow (kg/h)"]]
    if inlet is not None:
        rows[0].append("Inlet loss (% of set)")
    if outlet is not None:
        rows[0].append("Built-up back pressure (kPa)")
    for z in sizings:
        sc = z.scenario
        if z.relief is None:
            rows.append([sc.title, "—", fmt(sc.rate_kg_h), "—", z.error or "not applicable", "—"]
                        + (["—"] if inlet is not None else []) + (["—"] if outlet is not None else []))
            continue
        row = [sc.title + (" (governs)" if z is gov else ""), sc.describe_fluid(), fmt(sc.rate_kg_h),
               fmt(z.relief.relieving_pressure_kpa), fmt(z.relief.required_area_mm2), fmt(z.rated_kg_h)]
        if inlet is not None:
            row.append(fmt(z.inlet.percent, 3) if z.inlet else "—")
        if outlet is not None:
            row.append(fmt(z.discharge.built_up, 4) if z.discharge else "—")
        rows.append(row)
    rep.add_step("Relief scenarios",
                 text=("Each scenario is sized in its own fluid and overpressure. The one needing the largest "
                       f"orifice area governs: {gov.scenario.title}. Selected orifice "
                       + (f"{letter}" if n_valves == 1 else f"{n_valves} × {letter}")
                       + f" ({fmt(a_orf)} mm² each). The rated flow is what that orifice passes in each scenario; "
                         "the piping is checked at the rated flow."),
                 table=rows, reference="API 521; API 520 Parts I and II")
    for z in sized:
        for s in z.scenario.steps:
            rep.steps.append(Step(f"{z.scenario.title} — {s.title}", s.text, s.equation, s.substitution, s.result,
                                  s.reference, s.table))
    for s in gov.relief.report.steps:
        rep.steps.append(Step(f"Sizing ({gov.scenario.title}) — {s.title}", s.text, s.equation, s.substitution,
                              s.result, s.reference, s.table))
    if gov.inlet is not None:
        rep.steps.extend(gov.inlet.steps)
    if gov.discharge is not None:
        rep.steps.extend(gov.discharge.steps)
    if reaction is not None:
        rep.steps.extend(reaction.steps)
    for z in sized:
        warnings.extend(f"{z.scenario.title}: {w}" for w in z.scenario.warnings)
        warnings.extend(w for w in z.relief.warnings if not w.startswith("API 526 areas"))
    rep.warnings = list(dict.fromkeys(warnings))
    rep.add_result("Governing scenario", gov.scenario.title)
    rep.add_result("Selected API 526 orifice", letter if n_valves == 1 else f"{n_valves} × {letter}")
    if gov.inlet is not None:
        rep.add_result("Inlet pressure loss", f"{fmt(gov.inlet.percent, 3)} % of set pressure")
    if gov.discharge is not None:
        rep.add_result("Built-up back pressure", f"{fmt(gov.discharge.built_up)} kPa")
    if reaction is not None:
        rep.add_result("Reaction force (steady)", f"{fmt(reaction.force_n / 1000.0, 4)} kN")
    return SystemResult(sizings, gov, letter, a_orf, n_valves, reaction, rep, rep.warnings)
