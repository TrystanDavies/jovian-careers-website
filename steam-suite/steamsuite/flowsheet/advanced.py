"""Piping, two-stream heat exchangers, relief valves and logical operations."""

from __future__ import annotations

import math

from .. import exchanger as hx
from ..hydraulics import (
    PIPE_SIZES,
    ROUGHNESS,
    SCHEDULES,
    TWO_PHASE_METHODS,
    VOID_MODELS,
    HeatLoss,
    PipeChokedError,
    fittings_k,
    fully_turbulent_friction,
    pipe_dimensions,
    pipe_flow,
    two_phase_gradients,
    velocity_guidance,
    void_fraction,
)
from ..relief import FLUIDS, OVERPRESSURE_BASES, VALVE_TYPES, ReliefInput, _overpressure, size_relief_valve
from ..report import num, tex_text, unit
from ..units import P_ATM_KPA, fmt
from ..water import P_CRIT_KPA, T_sat, WaterPropertyError, state_Ph, state_PT, state_Px
from .blocks import _dp_equations, _outlet_after_dp, dp_params, flow_dp
from .core import STREAM_PROPERTIES, Block, Param, Port, register

G_ACC = 9.80665


def _kj(v: float) -> str:
    return f"{num(v, 5)}{unit('kJ/kg')}"


# --- pipe segment -----------------------------------------------------------------------

TWO_PHASE_TEXT = {
    "Müller-Steinhagen & Heck": (
        "The all-liquid and all-vapour friction gradients A and B are found at the total mass flux and combined "
        "by the dryness fraction x.",
        r"\left(\frac{dP}{dz}\right)_f = \left[A + 2(B - A)x\right](1 - x)^{1/3} + B x^3",
        "Müller-Steinhagen & Heck (1986)"),
    "Friedel": (
        "The all-liquid gradient is multiplied by Friedel's two-phase multiplier, which depends on the density and "
        "viscosity ratios, the Froude and Weber numbers (surface tension from IAPWS R1-76). Friction factors from "
        "Colebrook. Valid for horizontal and upward flow.",
        r"\left(\frac{dP}{dz}\right)_f = \Phi_{lo}^2\left(\frac{dP}{dz}\right)_{lo}, \quad "
        r"\Phi_{lo}^2 = E + \frac{3.24\,F\,H}{Fr^{0.045}\,We^{0.035}}",
        "Friedel (1979)"),
    "Chisholm (Lockhart–Martinelli)": (
        "Gradients for the liquid and the vapour each flowing alone in the pipe are combined with Chisholm's C "
        "(20 if both phases are turbulent, 12 or 10 if one is laminar, 5 if both are; blended smoothly between).",
        r"\left(\frac{dP}{dz}\right)_f = \left(\frac{dP}{dz}\right)_l + C\sqrt{\left(\frac{dP}{dz}\right)_l"
        r"\left(\frac{dP}{dz}\right)_g} + \left(\frac{dP}{dz}\right)_g",
        "Lockhart & Martinelli (1949); Chisholm (1967)"),
    "Homogeneous": (
        "Liquid and vapour are treated as one fluid with the mixture density and the Cicchitti mixture viscosity.",
        r"\rho_h = \left(\frac{x}{\rho_g} + \frac{1 - x}{\rho_f}\right)^{-1}, \quad \mu_h = x\mu_g + (1 - x)\mu_f",
        "Homogeneous equilibrium model"),
}


@register
class Pipe(Block):
    TYPE = "pipe"
    LABEL = "Pipe segment"
    CATEGORY = "Piping"
    DESCRIPTION = ("Pressure drop and heat loss along a run of pipe, from its size, length, elevation change, "
                   "fittings and insulation. Works for water, steam and two-phase flow.")
    INLETS = [Port("in", "Inlet")]
    OUTLETS = [Port("out", "Outlet")]
    PARAMS = [
        Param("size_mode", "Pipe size given by", "choice", "Nominal size", choices=("Nominal size", "Inside diameter"),
              group="Pipe"),
        Param("nps", "Nominal pipe size (inch)", "choice", "4", choices=tuple(PIPE_SIZES),
              show_if=("size_mode", ("Nominal size",)), group="Pipe"),
        Param("schedule", "Schedule", "choice", "40", choices=SCHEDULES, show_if=("size_mode", ("Nominal size",)),
              group="Pipe"),
        Param("diameter", "Inside diameter", "diameter", 102.3, min_value=1.0,
              show_if=("size_mode", ("Inside diameter",)), group="Pipe"),
        Param("length", "Length", "length", 50.0, min_value=0.0, group="Pipe"),
        Param("elevation", "Elevation change (outlet above inlet)", "length", 0.0, group="Pipe"),
        Param("material", "Material", "choice", "Commercial steel, new", choices=tuple(ROUGHNESS) + ("Custom",),
              group="Pipe"),
        Param("roughness", "Absolute roughness", "roughness", 0.045, min_value=0.0,
              show_if=("material", ("Custom",)), group="Pipe"),
        Param("fittings", "Fittings", "fittings", {}, group="Fittings and valves",
              help="Number of each fitting in this run of pipe (Crane TP-410 resistance coefficients)."),
        Param("extra_k", "Additional resistance coefficient K", "number", 0.0, min_value=0.0,
              group="Fittings and valves", help="Any other losses, e.g. a strainer or flow meter."),
        Param("heat_loss", "Heat loss", "choice", "None (adiabatic)",
              choices=("None (adiabatic)", "Insulated", "Bare pipe"), group="Heat loss"),
        Param("ambient", "Ambient temperature", "temperature", 20.0,
              show_if=("heat_loss", ("Insulated", "Bare pipe")), group="Heat loss"),
        Param("ins_thickness", "Insulation thickness", "diameter", 50.0, min_value=0.0,
              show_if=("heat_loss", ("Insulated",)), group="Heat loss"),
        Param("ins_k", "Insulation conductivity", "conductivity", 0.04, min_value=0.001,
              show_if=("heat_loss", ("Insulated",)), group="Heat loss",
              help="Mineral wool about 0.04, calcium silicate about 0.06 W/(m·K)."),
        Param("h_out", "Outside surface coefficient", "htc", 10.0, min_value=0.1,
              show_if=("heat_loss", ("Insulated", "Bare pipe")), group="Heat loss",
              help="Convection plus radiation from the outer surface; about 10 W/(m²·K) indoors."),
        Param("method", "Two-phase friction method", "choice", TWO_PHASE_METHODS[0], choices=TWO_PHASE_METHODS,
              group="Two-phase flow",
              help="Müller-Steinhagen & Heck is the default and generally the most reliable for steam–water. "
                   "The Results tab compares all methods."),
        Param("void_model", "Void fraction (static head and acceleration)", "choice", VOID_MODELS[0],
              choices=VOID_MODELS, group="Two-phase flow",
              help="Drift flux accounts for steam slipping past the water, which raises the static head in "
                   "rising wet lines (e.g. lifted condensate). New pipes use drift flux."),
        Param("tp_factor", "Design factor on two-phase friction", "number", 1.0, min_value=0.1, max_value=5.0,
              group="Two-phase flow",
              help="Multiplies the two-phase friction gradient, e.g. 1.3 to allow for the correlations' "
                   "typical ±30 % uncertainty. Single-phase flow is not affected."),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._memo: dict = {}

    def _sin_theta(self) -> float:
        L = float(self.p("length"))
        return min(max(float(self.p("elevation")) / L, -1.0), 1.0) if L > 0 else 0.0

    def dims(self) -> tuple[float, float]:
        if self.p("size_mode") == "Nominal size":
            return pipe_dimensions(self.p("nps"), self.p("schedule"))
        d = float(self.p("diameter"))
        return d, d * 1.1

    def roughness(self) -> float:
        mat = self.p("material")
        return float(self.p("roughness")) if mat == "Custom" else ROUGHNESS[mat]

    def describe_size(self) -> str:
        if self.p("size_mode") == "Nominal size":
            return f'{self.p("nps")}" Sch {self.p("schedule")}, {fmt(self.p("length"), 3)} m'
        return f'ID {fmt(self.p("diameter"), 3)} mm, {fmt(self.p("length"), 3)} m'

    def _run(self, m, P, h, segments=None, strict=True):
        d, od = self.dims()
        eps = self.roughness()
        k_fit, rows = fittings_k(self.p("fittings"), d)
        k_total = k_fit + float(self.p("extra_k") or 0.0)
        heat = None
        if self.p("heat_loss") != "None (adiabatic)":
            heat = HeatLoss(t_ambient=self.p("ambient"),
                            insulation_mm=self.p("ins_thickness") if self.p("heat_loss") == "Insulated" else 0.0,
                            k_insulation=self.p("ins_k"), h_outside=self.p("h_out"), od_mm=od)
        key = (round(m, 12), round(P, 9), round(h, 9), segments, strict,
               repr(sorted(self.params.items(), key=lambda kv: kv[0])))
        res = self._memo.get(key)
        if res is None:
            try:
                res = pipe_flow(m, P, h, d, float(self.p("length")), eps, float(self.p("elevation")), k_total, heat,
                                self.p("method"), segments=segments, void_model=self.p("void_model"),
                                tp_factor=float(self.p("tp_factor")), strict=strict)
            except (ValueError, WaterPropertyError) as exc:  # remember failures too: solvers retry the same inputs
                res = exc
            if len(self._memo) > 64:
                self._memo.clear()
            self._memo[key] = res
        if isinstance(res, Exception):
            raise res.with_traceback(None)
        return res, d, od, eps, k_total, rows

    def _pf_segments(self) -> int:
        return int(self.pf_state.get("segments", 20))

    def hydraulics(self, net):
        sin, out = self.s_in("in"), self.s_out("out")
        net.same_flow(sin, out, "same flow in and out")
        # a fixed number of segments keeps the pressure drop a smooth function of the flow
        segs = 20
        if sin.known:
            try:
                r = self._run(sin.m, sin.P, sin.h)[0]
                segs = 60 if r.dp_total > 0.25 * sin.P else 20
                dp_scale = max(abs(r.dp_total), 1e-3 * sin.P, 1e-3)
            except (ValueError, WaterPropertyError):
                dp_scale = net.P_ref
        else:
            dp_scale = net.P_ref
        self.pf_state["segments"] = segs
        h_in = sin.h

        length = float(self.p("length"))

        def outlet(m, P1, h_in=h_in, segs=segs):
            r = self._run(m, P1, h_in, segments=segs, strict=False)[0]
            if r.choked and r.L_choke:
                # beyond choking there is no solution; continue the curve downwards smoothly so that the
                # solver is steered back to flows the pipe can pass (a choked answer is reported later)
                return r.P_out - (P1 - r.P_out) * (length - r.L_choke) / r.L_choke
            return r.P_out

        d = self.dims()[0] / 1000.0
        st = sin.state if sin.known else None
        v_nom = 2.0 if st is None or st.is_liquid_like else (10.0 if st.phase == "two-phase" else 25.0)
        m_nom = (st.rho if st is not None else 1000.0) * v_nom * math.pi * d * d / 4.0
        net.element(sin, out, outlet, f"pipe pressure drop ({self.describe_size()})", scale=dp_scale,
                    m_nominal=m_nom)

    def diagnose(self, net, x) -> str | None:
        sin = self.s_in("in")
        m, P1 = x[net.im(sin)], x[net.ip(sin)]
        try:
            r = self._run(m, P1, sin.h, segments=self._pf_segments(), strict=False)[0]
        except (ValueError, WaterPropertyError):
            return None
        if r.choked:
            return (f"the flow is choked: {fmt(m * 3600, 4)} kg/h reaches the speed of sound {fmt(r.L_choke, 3)} m "
                    f"along this {fmt(self.p('length'), 3)} m pipe, so it cannot pass the flow needed downstream. "
                    "Increase the pipe size.")
        return None

    def calculate(self):
        sin, out = self.s_in("in"), self.s_out("out")
        st1 = sin.state
        try:
            res, d, od, eps, k_total, rows = self._run(sin.m, sin.P, sin.h,
                                                        segments=self._pf_segments() if self.pf else None)
        except PipeChokedError as exc:
            r = exc.result
            raise ValueError(
                f"The flow is choked: at {fmt(sin.m * 3600, 4)} kg/h the velocity reaches the speed of sound "
                f"{fmt(r.L_choke, 3)} m along this {fmt(self.p('length'), 3)} m pipe, so the pipe cannot pass this "
                "flow from these inlet conditions. Increase the pipe size or shorten the run.") from exc
        out.set(sin.m, res.P_out, res.h_out)
        st2 = out.state
        self.heat_in = -res.heat_loss_kw
        # elevation and velocity changes are mechanical energy; count them so the energy balance closes
        dh_mech = -(sin.h - res.h_out) * sin.m - self.heat_in if sin.m > 0 else 0.0
        self.work_in = dh_mech
        area = math.pi * (d / 1000.0) ** 2 / 4.0

        self.result("dP", "Pressure drop", res.dp_total, "pressure_diff")
        self.result("P_out", "Outlet pressure", res.P_out, "pressure")
        self.result("T_out", "Outlet temperature", st2.T, "temperature")
        self.result("condition", "Outlet condition", st2.describe(), "text")
        self.result("v_in", "Velocity at inlet", res.v_in, "velocity")
        self.result("v_out", "Velocity at outlet", res.v_out, "velocity")
        self.result("dp_f", "Friction pressure drop", res.dp_friction, "pressure_diff")
        self.result("dp_k", "Fittings pressure drop", res.dp_fittings, "pressure_diff")
        self.result("dp_s", "Static head (elevation) pressure drop", res.dp_static, "pressure_diff")
        self.result("dp_a", "Acceleration pressure drop", res.dp_accel, "pressure_diff")
        self.result("dp_per_100m", "Pressure drop per 100 m", res.dp_total / max(self.p("length"), 1e-9) * 100.0
                    if self.p("length") > 0 else 0.0, "pressure_diff")
        self.result("re", "Reynolds number (inlet)", res.re_in, "number")
        self.result("f", "Friction factor (inlet)", res.f_in, "number")
        self.result("id", "Inside diameter", d, "diameter")
        if res.mach_max > 0:
            self.result("mach", "Maximum Mach number", res.mach_max, "number")
        if self.p("heat_loss") != "None (adiabatic)":
            self.result("q_loss", "Heat lost", res.heat_loss_kw, "power")
            if st1.is_vapour_like and st2.phase == "two-phase":
                self.result("condensate", "Condensate formed", (1.0 - st2.x) * sin.m, "mass_flow")
        self.result("segments", "Calculation segments", res.segments, "number")

        for st, v in ((st1, res.v_in), (st2, res.v_out)):
            msg = velocity_guidance(st, v)
            if msg:
                self.warn(msg)
        if res.mach_max > 0.3:
            self.warn(f"Mach number reaches {fmt(res.mach_max, 2)}: expect noise and a large pressure drop. "
                      "Mach 0.3 is a common upper limit for steam lines.")
        if st1.is_vapour_like and st2.phase == "two-phase":
            self.warn(f"Heat loss condenses {fmt((1.0 - st2.x) * sin.m * 3600.0, 3)} kg/h of steam in this line: "
                      "provide drain points with steam traps.")
        elif st1.is_liquid_like and st2.phase == "two-phase":
            self.warn("The water flashes to steam in this pipe as the pressure falls.")
        wet = [st for st in (st1, st2) if st.phase == "two-phase" and 0.02 < st.x < 0.98]
        g_flux = sin.m / (math.pi * (d / 1000.0) ** 2 / 4.0) if d > 0 else 0.0
        compare = []  # (end, {method: gradient})
        for label, st in (("inlet", st1), ("outlet", st2)):
            grads = two_phase_gradients(st, g_flux, d, eps)
            if grads:
                compare.append((label, st, grads))
        spread = None
        if compare:
            vals = [v for _, _, g in compare for v in g.values()]
            rel = [max(g.values()) / min(g.values()) - 1.0 for _, _, g in compare if min(g.values()) > 0]
            spread = max(rel) * 100.0 if rel else None
            if spread is not None:
                self.result("tp_spread", "Spread of two-phase friction methods", spread, "percent")
        if wet:
            self.warn("Two-phase flow: friction correlations are typically accurate to about ±30 %"
                      + (f"; here the methods differ by up to {fmt(spread, 2)} % (see 'Two-phase methods compared')."
                         if spread is not None else "."))

        rows_fit = [["Fitting", "Number", "K each", "K total"]]
        rows_fit += [[lbl, fmt(cnt, 3), fmt(k, 3), fmt(k * cnt, 3)] for lbl, cnt, k in rows]
        if self.p("extra_k"):
            rows_fit.append(["Additional resistance", "1", fmt(self.p("extra_k"), 3), fmt(self.p("extra_k"), 3)])
        rows_fit.append(["Total", "", "", fmt(k_total, 4)])

        g = sin.m / area if area > 0 else 0.0
        self.step("Pipe and flow area",
                  text=(f"{self.describe_size()}. Inside diameter {fmt(d)} mm, roughness {fmt(eps)} mm."),
                  equation=r"A = \frac{\pi D^2}{4}, \qquad G = \frac{\dot m}{A}, \qquad v = \frac{G}{\rho}",
                  result=(rf"A = {num(area * 1e4, 4)}{unit('cm^2')}, \quad G = {num(g, 4)}{unit('kg/(m^2·s)')}, "
                          rf"\quad v_{{in}} = {num(res.v_in, 4)}{unit('m/s')}"))
        if sin.m > 0:
            self.step("Friction factor (inlet conditions)",
                      text=("Reynolds number from the inlet viscosity; Darcy friction factor from the Colebrook–White "
                            "equation (64/Re if laminar)."),
                      equation=(r"Re = \frac{G D}{\mu}, \qquad \frac{1}{\sqrt f} = -2\log_{10}\left("
                                r"\frac{\varepsilon/D}{3.7} + \frac{2.51}{Re\sqrt f}\right)"),
                      result=rf"Re = {num(res.re_in, 4)}, \quad f = {num(res.f_in, 4)}",
                      reference="Colebrook (1939); Darcy–Weisbach")
        if st1.phase == "two-phase" or res.two_phase:
            text, eq, ref = TWO_PHASE_TEXT.get(self.p("method"), TWO_PHASE_TEXT[TWO_PHASE_METHODS[0]])
            if float(self.p("tp_factor")) != 1.0:
                text += f" The result is multiplied by the design factor {fmt(self.p('tp_factor'), 3)}."
            self.step("Two-phase friction", text=f"Method: {self.p('method')}. " + text, equation=eq, reference=ref)
            if self.p("void_model").startswith("Drift"):
                st_tp = next((st for st in (st1, st2) if st.phase == "two-phase"), None)
                alpha = void_fraction(st_tp, g_flux, self.p("void_model"), self._sin_theta()) if st_tp else None
                self.step("Void fraction (static head and acceleration)",
                          text=("Steam moves faster than the water (slip), so the water occupies more of the pipe than "
                                "the no-slip (homogeneous) value. The drift-flux model gives the vapour volume "
                                "fraction α; the static head uses ρ_m = αρ_g + (1 − α)ρ_f. C₀ = 1 + 0.12(1 − x) "
                                "for horizontal pipes (Steiner), rising to 1 + 0.2(1 − x) for vertical upflow "
                                "(Rouhani–Axelsson); downward flow uses the homogeneous value."),
                          equation=(r"\alpha = \frac{x/\rho_g}{C_0\left(\frac{x}{\rho_g} + \frac{1-x}{\rho_f}\right)"
                                    r" + \frac{1.18(1-x)\left[g\sigma(\rho_f - \rho_g)\right]^{1/4}}{G\,\rho_f^{1/2}}}"),
                          result=(rf"\alpha = {num(alpha, 4)}" + tex_text(" (where the flow first becomes two-phase)")
                                  if alpha is not None else None),
                          reference="Rouhani & Axelsson (1970); Steiner (1993), VDI Heat Atlas")
            if compare:
                header = ["Method"] + [f"Friction gradient at {lbl} (kPa per 100 m)" for lbl, _, _ in compare]
                table = [header]
                for meth in TWO_PHASE_METHODS:
                    table.append([meth + (" (used)" if meth == self.p("method") else "")]
                                 + [fmt(g[meth] / 10.0, 4) for _, _, g in compare])
                self.step("Two-phase methods compared",
                          text=("Frictional pressure gradient by each correlation at the same conditions "
                                f"(dryness {', '.join(fmt(st.x, 3) for _, st, _ in compare)}). The spread between "
                                "them indicates the uncertainty of the two-phase pressure drop"
                                + (f": {fmt(spread, 2)} % here." if spread is not None else ".")),
                          table=table,
                          reference="Müller-Steinhagen & Heck (1986); Friedel (1979); Chisholm (1967)")
        self.step("Fittings",
                  text=("Resistance coefficients from Crane TP-410: K = (L/D)·f_T, where f_T = "
                        f"{fmt(fully_turbulent_friction(d), 3)} is the fully turbulent friction factor of clean steel "
                        "pipe of this bore. The fittings' losses are spread along the pipe."),
                  equation=r"\Delta P_K = \sum K \cdot \frac{\rho v^2}{2}",
                  result=rf"\sum K = {num(k_total, 4)}, \quad \Delta P_K = {num(res.dp_fittings, 4)}{unit('kPa')}",
                  table=rows_fit if len(rows_fit) > 2 else None,
                  reference="Crane Technical Paper 410")
        self.step("Pressure drop along the pipe",
                  text=(f"The pipe is calculated in {res.segments} step(s). In each, properties are updated from "
                        "IAPWS-IF97 and the friction, fittings, static head and acceleration terms are added. "
                        "Energy balance per step: heat loss, elevation and kinetic energy change the enthalpy. "
                        "Where the Mach number exceeds 0.6 the march continues in small pressure steps, so that "
                        "choking (velocity reaching the speed of sound) is found exactly"
                        + (" (for wet steam the homogeneous-equilibrium speed of sound is used, which is "
                           "conservative)." if res.two_phase else ".")),
                  equation=(r"\Delta P = \underbrace{\sum f\frac{\Delta L}{D}\frac{\rho v^2}{2}}_{friction}"
                            r" + \Delta P_K + \underbrace{\sum \rho g \Delta z}_{static} + "
                            r"\underbrace{G^2\left(\frac{1}{\rho_{out}} - \frac{1}{\rho_{in}}\right)}_{acceleration}"),
                  substitution=(rf"\Delta P = {num(res.dp_friction, 4)} + {num(res.dp_fittings, 4)} + "
                                rf"{num(res.dp_static, 4)} + {num(res.dp_accel, 4)}"),
                  result=(rf"\Delta P = {num(res.dp_total, 5)}{unit('kPa')}, \quad P_{{out}} = {num(res.P_out, 5)}"
                          rf"{unit('kPa(a)')}"),
                  reference="Darcy–Weisbach")
        if self.p("heat_loss") != "None (adiabatic)":
            self.step("Heat loss",
                      text=("Heat flows through the insulation and from the outer surface to the surroundings "
                            "(pipe wall and inside film resistances are neglected)."),
                      equation=(r"q' = \frac{T - T_{amb}}{\dfrac{\ln(r_2/r_1)}{2\pi k} + \dfrac{1}{2\pi r_2 h_o}}"),
                      result=rf"Q_{{loss}} = {num(res.heat_loss_kw, 4)}{unit('kW')} \;(" + tex_text(
                          f"outlet {st2.describe()}") + ")")
        self.charts["Profile along the pipe"] = {
            "x": "Distance along pipe (m)",
            "y": "Pressure (kPa a)",
            "y_kind": "pressure",
            "x_kind": "length",
            "series": {"Pressure": [(L, P) for L, P, _, _, _ in res.profile]},
        }
        self.charts["Temperature along the pipe"] = {
            "x": "Distance along pipe (m)",
            "y": "Temperature (°C)",
            "y_kind": "temperature",
            "x_kind": "length",
            "series": {"Temperature": [(L, T) for L, _, T, _, _ in res.profile]},
        }

    def update_demands(self):
        self.pass_demand_through()

    def initial_guess(self, port):
        sin = self.s_in("in")
        if sin.known:
            return sin.P, sin.h, sin.m
        return None


# --- two-stream heat exchanger ---------------------------------------------------------------

HX_SPECS = (
    "Cold outlet temperature",
    "Hot outlet temperature",
    "Heat duty",
    "Hot outlet dryness fraction",
    "Cold outlet dryness fraction",
    "UA (rating)",
    "Minimum approach",
    "Condensing heater (hot flow as required)",
)


@register
class HeatExchanger(Block):
    TYPE = "heat_exchanger"
    LABEL = "Heat exchanger"
    CATEGORY = "Heat transfer"
    DESCRIPTION = ("Transfers heat between a hot and a cold stream (shell-and-tube or plate). Specify an outlet "
                   "condition, the duty, or the UA for rating. Analysed in zones, so condensing and boiling are "
                   "handled correctly; checks for temperature crosses.")
    INLETS = [Port("hot_in", "Hot side inlet"), Port("cold_in", "Cold side inlet")]
    OUTLETS = [Port("hot_out", "Hot side outlet"), Port("cold_out", "Cold side outlet")]
    PARAMS = [
        Param("spec", "Specify", "choice", HX_SPECS[0], choices=HX_SPECS),
        Param("cold_T", "Cold outlet temperature", "temperature", 80.0,
              show_if=("spec", ("Cold outlet temperature", "Condensing heater (hot flow as required)"))),
        Param("hot_T", "Hot outlet temperature", "temperature", 60.0, show_if=("spec", ("Hot outlet temperature",))),
        Param("duty", "Heat duty", "power", 1000.0, min_value=0.0, show_if=("spec", ("Heat duty",))),
        Param("hot_x", "Hot outlet dryness fraction", "fraction", 0.0, min_value=0.0, max_value=1.0,
              show_if=("spec", ("Hot outlet dryness fraction", "Condensing heater (hot flow as required)")),
              help="0 = fully condensed to saturated water."),
        Param("cold_x", "Cold outlet dryness fraction", "fraction", 1.0, min_value=0.0, max_value=1.0,
              show_if=("spec", ("Cold outlet dryness fraction",))),
        Param("ua", "UA (overall coefficient × area)", "ua", 20.0, min_value=0.0, show_if=("spec", ("UA (rating)",))),
        Param("approach", "Minimum approach temperature", "temperature_diff", 5.0, min_value=0.01,
              show_if=("spec", ("Minimum approach",))),
        Param("arrangement", "Flow arrangement", "choice", "Counter-current", choices=("Counter-current", "Co-current")),
        Param("dp_hot", "Hot side pressure drop", "pressure_diff", 0.0, min_value=0.0, group="Pressure drops"),
        Param("dp_cold", "Cold side pressure drop", "pressure_diff", 0.0, min_value=0.0, group="Pressure drops"),
        *dp_params("hot_", "Hot side pressure drop", "Pressure drops"),
        *dp_params("cold_", "Cold side pressure drop", "Pressure drops"),
    ]

    N_ZONES = 20

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._memo: dict = {}

    def _sides(self):
        hi, ci = self.s_in("hot_in"), self.s_in("cold_in")
        hot = hx.Side(hi.m, hi.P, hi.h, _outlet_after_dp(self, hi, self.s_out("hot_out"), "hot_", "dp_hot"))
        cold = hx.Side(ci.m, ci.P, ci.h, _outlet_after_dp(self, ci, self.s_out("cold_out"), "cold_", "dp_cold"))
        if hot.P_out <= 0 or cold.P_out <= 0:
            raise ValueError("A pressure drop is larger than the inlet pressure.")
        return hot, cold

    def _duty(self, hot, cold) -> float:
        spec = self.p("spec")
        counter = self.p("arrangement") == "Counter-current"
        if spec == "Heat duty":
            return float(self.p("duty"))
        if spec == "Hot outlet temperature":
            return hot.m * (hot.h_in - state_PT(hot.P_out, self.p("hot_T")).h)
        if spec == "Hot outlet dryness fraction":
            return hot.m * (hot.h_in - state_Px(hot.P_out, self.p("hot_x")).h)
        if spec == "Cold outlet temperature":
            return cold.m * (state_PT(cold.P_out, self.p("cold_T")).h - cold.h_in)
        if spec == "Cold outlet dryness fraction":
            return cold.m * (state_Px(cold.P_out, self.p("cold_x")).h - cold.h_in)
        if spec == "Condensing heater (hot flow as required)":
            q = cold.m * (state_PT(cold.P_out, self.p("cold_T")).h - cold.h_in)
            dh_hot = hot.h_in - state_Px(hot.P_out, self.p("hot_x")).h
            return min(q, hot.m * dh_hot) if dh_hot > 0 else 0.0
        key = (spec, hot.m, hot.P_in, hot.h_in, hot.P_out, cold.m, cold.P_in, cold.h_in, cold.P_out,
               self.p("ua"), self.p("approach"), counter)
        if key in self._memo:
            return self._memo[key]
        if spec == "UA (rating)":
            q = hx.duty_for_ua(hot, cold, float(self.p("ua")), counter, n=12)
        else:
            q = hx.duty_for_approach(hot, cold, float(self.p("approach")), counter, n=12)
        if len(self._memo) > 64:
            self._memo.clear()
        self._memo[key] = q
        return q

    def update_demands(self):
        for a, b in (("hot_out", "hot_in"), ("cold_out", "cold_in")):
            out, inp = self.s_out(a), self.s_in(b)
            if out.demand is not None:
                inp.demand = out.demand
        if self.p("spec") == "Condensing heater (hot flow as required)":
            hi, ci = self.s_in("hot_in"), self.s_in("cold_in")
            if not (hi.known and ci.known):
                return
            try:
                hot, cold = self._sides()
                q = cold.m * (state_PT(cold.P_out, self.p("cold_T")).h - cold.h_in)
                dh = hot.h_in - state_Px(hot.P_out, self.p("hot_x")).h
            except (ValueError, WaterPropertyError):
                return
            if dh > 0:
                hi.demand = max(q, 0.0) / dh

    def calculate(self):
        hot, cold = self._sides()
        counter = self.p("arrangement") == "Counter-current"
        q = self._duty(hot, cold)
        if q < -1e-9:
            raise ValueError("The specification needs heat to flow from the cold side to the hot side. Check which "
                             "stream is connected to the hot side, or the outlet temperature.")
        q = max(q, 0.0)
        h_ho = hot.h_in - (q / hot.m if hot.m > 0 else 0.0)
        h_co = cold.h_in + (q / cold.m if cold.m > 0 else 0.0)
        feasible = True
        try:
            state_Ph(hot.P_out, h_ho)
            state_Ph(cold.P_out, h_co)
            if q > 0 and hot.m > 0 and cold.m > 0:
                feasible = hx.profile(hot, cold, q, counter, self.N_ZONES).min_approach > 0
        except WaterPropertyError:
            feasible = False
        if not feasible:
            q_max = hx.max_duty(hot, cold, counter, self.N_ZONES)
            raise ValueError(f"Temperature cross: a duty of {fmt(q)} kW would need the hot stream to become colder than "
                             f"the cold stream. The most this exchanger arrangement can transfer is {fmt(q_max)} kW "
                             "(with an infinitely large exchanger). Change the outlet specification.")
        self.s_out("hot_out").set(hot.m, hot.P_out, h_ho)
        self.s_out("cold_out").set(cold.m, cold.P_out, h_co)
        st_hi, st_ci = self.s_in("hot_in").state, self.s_in("cold_in").state
        st_ho, st_co = self.s_out("hot_out").state, self.s_out("cold_out").state
        self.result("duty", "Heat duty", q, "power")
        self.result("T_hot_out", "Hot outlet temperature", st_ho.T, "temperature")
        self.result("T_cold_out", "Cold outlet temperature", st_co.T, "temperature")
        self.result("hot_cond", "Hot outlet condition", st_ho.describe(), "text")
        self.result("cold_cond", "Cold outlet condition", st_co.describe(), "text")
        if self.p("spec") == "Condensing heater (hot flow as required)":
            self.result("hot_flow", "Hot (heating) flow", hot.m, "mass_flow")

        if q <= 0 or hot.m <= 0 or cold.m <= 0:
            self.step("Energy balance", text="No heat is transferred.")
            return
        prof = hx.profile(hot, cold, q, counter, self.N_ZONES)
        if prof.min_approach <= 0:
            raise ValueError(f"Temperature cross: with a duty of {fmt(q)} kW the hot stream would have to be colder "
                             f"than the cold stream (minimum approach {fmt(prof.min_approach, 3)} °C). Reduce the duty "
                             "or change the outlet specification.")
        self.result("approach", "Minimum approach temperature", prof.min_approach, "temperature_diff")
        self.result("ua", "UA required", prof.ua, "ua")
        self.result("lmtd", "Effective mean temperature difference (Q/UA)", q / prof.ua if prof.ua > 0 else 0.0,
                    "temperature_diff")
        if prof.min_approach < 3.0:
            self.warn(f"The minimum approach is only {fmt(prof.min_approach, 2)} °C: the exchanger would be very large.")
        self.step("Energy balance",
                  text=(f"Specification: {self.p('spec').lower()}. Hot side: {st_hi.describe().lower()} → "
                        f"{st_ho.describe().lower()}. Cold side: {st_ci.describe().lower()} → {st_co.describe().lower()}."),
                  equation=r"Q = \dot m_h (h_{h,in} - h_{h,out}) = \dot m_c (h_{c,out} - h_{c,in})",
                  substitution=(rf"Q = {num(hot.m, 5)} \times ({num(hot.h_in, 6)} - {num(h_ho, 6)}) = "
                                rf"{num(cold.m, 5)} \times ({num(h_co, 6)} - {num(cold.h_in, 6)})"),
                  result=rf"Q = {num(q, 5)}{unit('kW')}")
        self.step("Zone analysis and UA",
                  text=(f"The duty is split into {self.N_ZONES} equal zones ({self.p('arrangement').lower()} flow). "
                        "Temperatures at each zone boundary come from IAPWS-IF97, so phase change is followed "
                        "correctly, and the UA of each zone uses its own log-mean temperature difference."),
                  equation=(r"UA = \sum_i \frac{\Delta Q_i}{\Delta T_{lm,i}}, \qquad \Delta T_{lm} = "
                            r"\frac{\Delta T_a - \Delta T_b}{\ln(\Delta T_a / \Delta T_b)}"),
                  result=(rf"UA = {num(prof.ua, 4)}{unit('kW/K')}, \quad \Delta T_{{min}} = {num(prof.min_approach, 4)}"
                          rf"{unit('°C')}"),
                  reference="Weighted (zone) LMTD method")
        self.charts["Temperature profile (T–Q diagram)"] = {
            "x": "Heat transferred from the cold end (kW)",
            "y": "Temperature (°C)",
            "x_kind": "power",
            "y_kind": "temperature",
            "series": {"Hot side": [(qq, th) for qq, th, _ in prof.points],
                       "Cold side": [(qq, tc) for qq, _, tc in prof.points]},
        }

    def initial_guess(self, port):
        src = {"hot_out": "hot_in", "cold_out": "cold_in"}[port]
        s = self.s_in(src)
        dp = self.p("dp_hot") if port == "hot_out" else self.p("dp_cold")
        if s.known:
            return s.P - dp, s.h, s.m
        return None

    def hydraulics(self, net):
        hi, ho, ci, co = self.s_in("hot_in"), self.s_out("hot_out"), self.s_in("cold_in"), self.s_out("cold_out")
        _dp_equations(self, net, hi, ho, "hot_", "dp_hot", "hot side: ")
        _dp_equations(self, net, ci, co, "cold_", "dp_cold", "cold side: ")
        if self.p("spec") == "Condensing heater (hot flow as required)":
            P_ho = ho.P if ho.known else hi.P - self.p("dp_hot")
            P_co = co.P if co.known else ci.P - self.p("dp_cold")
            dh_hot = hi.h - state_Px(P_ho, self.p("hot_x")).h
            dh_cold = state_PT(P_co, self.p("cold_T")).h - ci.h
            if dh_hot <= 0:
                raise ValueError("The hot (heating) side cannot give up heat to reach its outlet condition.")
            net.linear_flows({hi: dh_hot, ci: -dh_cold}, 0.0, "energy balance: heating flow for the cold outlet "
                                                              "temperature")


# --- relief valve on the drawing -----------------------------------------------------------------


@register
class ReliefValveUnit(Block):
    TYPE = "relief_valve"
    LABEL = "Pressure relief valve (PSV)"
    CATEGORY = "Safety"
    DESCRIPTION = ("Sizes a pressure relief valve to API 520 from the conditions of the stream it protects. "
                   "It does not take part in the heat and mass balance (it is closed in normal operation).")
    INLETS = []
    OUTLETS = []
    PARAMS = [
        Param("stream", "Protected stream (gives the relieving fluid)", "stream_choice", ""),
        Param("tag", "Valve tag", "text", "PSV-001"),
        Param("set_pressure", "Set pressure", "pressure", 1201.325),
        Param("overpressure", "Allowed overpressure", "choice", OVERPRESSURE_BASES["single"].label,
              choices=tuple(b.label for b in OVERPRESSURE_BASES.values())),
        Param("custom_op", "Custom overpressure", "percent", 10.0, min_value=0.1,
              show_if=("overpressure", (OVERPRESSURE_BASES["custom"].label,))),
        Param("rate_mode", "Relieving rate", "choice", "Stream flow × factor", choices=("Stream flow × factor", "Fixed rate")),
        Param("rate_factor", "Factor on the stream flow", "number", 1.0, min_value=0.0,
              show_if=("rate_mode", ("Stream flow × factor",))),
        Param("rate", "Relieving rate", "mass_flow", 1.0, min_value=0.0, show_if=("rate_mode", ("Fixed rate",))),
        Param("valve_type", "Valve type", "choice", VALVE_TYPES["conventional"], choices=tuple(VALVE_TYPES.values())),
        Param("back_pressure", "Total back pressure (gauge)", "pressure_diff", 0.0),
        Param("rupture_disk", "Rupture disk upstream", "choice", "No", choices=("No", "Yes")),
        Param("kb", "Back pressure factor Kb (from the manufacturer)", "number", 1.0, min_value=0.05, max_value=1.0,
              show_if=("valve_type", (VALVE_TYPES["balanced"],))),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.relief = None

    def hydraulics(self, net):
        """Closed in normal operation: no flow equations."""

    def calculate(self):
        if not self._ctx.final:
            return
        name = self.p("stream")
        if not name:
            raise ValueError("Choose the stream this relief valve protects.")
        s = self._ctx.streams.get(name)
        if s is None or not s.known:
            raise ValueError(f"Stream '{name}' does not exist or has not been calculated.")
        st = s.state
        set_g = self.p("set_pressure") - P_ATM_KPA
        if self.p("set_pressure") <= s.P:
            self.warn(f"The set pressure is not above the operating pressure of '{name}' "
                      f"({fmt(s.P - P_ATM_KPA)} kPa(g)): the valve would be open in normal operation.")
        basis = next(k for k, b in OVERPRESSURE_BASES.items() if b.label == self.p("overpressure"))
        _, dp_op, _ = _overpressure(ReliefInput(fluid="saturated_steam", flow_kg_h=1.0, set_pressure_kpag=set_g,
                                                overpressure_basis=basis,
                                                custom_overpressure_percent=self.p("custom_op")))
        P1_est = set_g + dp_op + P_ATM_KPA
        kwargs = {}
        if st.phase == "two-phase":
            fluid, kwargs["dryness"] = "wet_steam", st.x
        elif st.is_vapour_like and st.phase != "supercritical":
            if st.superheat is not None and P1_est < P_CRIT_KPA and st.T > T_sat(P1_est) + 1.0:
                fluid, kwargs["temperature_c"] = "superheated_steam", st.T
            else:
                fluid = "saturated_steam"
        elif st.is_liquid_like:
            fluid, kwargs["temperature_c"] = "water", st.T
        else:
            raise ValueError("Relief sizing is not available for supercritical conditions.")
        rate = s.m * self.p("rate_factor") if self.p("rate_mode") == "Stream flow × factor" else self.p("rate")
        if rate <= 0:
            raise ValueError("The relieving rate is zero.")
        vt = next(k for k, v in VALVE_TYPES.items() if v == self.p("valve_type"))
        inp = ReliefInput(fluid=fluid, flow_kg_h=rate * 3600.0, set_pressure_kpag=set_g, overpressure_basis=basis,
                          custom_overpressure_percent=self.p("custom_op"), back_pressure_kpag=self.p("back_pressure"),
                          valve_type=vt, kb=self.p("kb") if vt == "balanced" else None,
                          rupture_disk=self.p("rupture_disk") == "Yes", tag=self.p("tag"),
                          service=f"protects stream '{name}'", **kwargs)
        res = size_relief_valve(inp)
        self.relief = res
        self.result("orifice", "API 526 orifice",
                    res.orifice if res.valves_needed == 1 else f"{res.valves_needed} × {res.orifice}", "text")
        self.result("area", "Required effective area", res.required_area_mm2, "area")
        if res.rated_capacity_kg_h:
            self.result("rated", "Rated capacity of selected orifice", res.rated_capacity_kg_h / 3600.0, "mass_flow")
        self.result("rate", "Required relieving rate", rate, "mass_flow")
        self.result("P1", "Relieving pressure", res.relieving_pressure_kpa, "pressure")
        self.result("fluid", "Relieving fluid", f"{FLUIDS[fluid]}: {res.relieving_state.describe()}", "text")
        self.result("regime", "Flow regime", res.flow_regime, "text")
        self.result("method", "Method", res.governing_method, "text")
        for w in res.warnings:
            if not w.startswith("API 526 areas"):
                self.warn(w)
        self.steps = list(res.report.steps)


# --- adjust (goal seek) -----------------------------------------------------------------------------


@register
class Adjust(Block):
    TYPE = "adjust"
    LABEL = "Adjust (goal seek)"
    CATEGORY = "Logical"
    DESCRIPTION = ("Changes one setting of a piece of equipment until a stream property or an equipment result "
                   "reaches a target — like a controller in steady state (e.g. find the pump pressure that delivers "
                   "a required pressure at the end of a pipe).")
    INLETS = []
    OUTLETS = []
    PARAMS = [
        Param("var_block", "Equipment to adjust", "block_choice", ""),
        Param("var_param", "Setting to adjust", "param_choice", "", depends_on="var_block"),
        Param("target_type", "Target is a", "choice", "Stream property", choices=("Stream property", "Equipment result")),
        Param("target_stream", "Target stream", "stream_choice", "", show_if=("target_type", ("Stream property",))),
        Param("target_property", "Property", "choice", "Temperature", choices=tuple(STREAM_PROPERTIES),
              show_if=("target_type", ("Stream property",))),
        Param("target_block", "Target equipment", "block_choice", "", show_if=("target_type", ("Equipment result",))),
        Param("target_result", "Result", "result_choice", "", depends_on="target_block",
              show_if=("target_type", ("Equipment result",))),
        Param("target_value", "Target value", "target_value", 0.0),
        Param("lower", "Lowest allowed value of the setting", "adjust_bound", 0.0, group="Limits"),
        Param("upper", "Highest allowed value of the setting", "adjust_bound", 0.0, group="Limits",
              help="Give both limits to search between them; leave both 0 to search near the current value."),
        Param("tolerance", "Tolerance (relative)", "number", 1e-6, min_value=1e-12, group="Limits"),
    ]

    def calculate(self):
        """The search is done by the flowsheet solver; nothing to do in a pass."""

    def hydraulics(self, net):
        """Works on whole solutions, not on the network equations."""

    def target_kind(self, blocks) -> str:
        if self.p("target_type") == "Stream property":
            return STREAM_PROPERTIES.get(self.p("target_property"), ("number",))[0]
        b = blocks.get(self.p("target_block"))
        r = b.results.get(self.p("target_result")) if b else None
        return r.kind if r else "number"


# --- specification (pressure–flow mode) ----------------------------------------------------------


@register
class Specification(Block):
    TYPE = "specification"
    LABEL = "Flow / pressure specification"
    CATEGORY = "Logical"
    DESCRIPTION = ("Fixes the flow or the pressure of any stream in pressure–flow mode, like a flow or pressure "
                   "controller holding its set point. The equipment's other settings must leave that value free.")
    INLETS = []
    OUTLETS = []
    PARAMS = [
        Param("stream", "Stream", "stream_choice", ""),
        Param("property", "Fix its", "choice", "Mass flow", choices=("Mass flow", "Pressure")),
        Param("flow", "Flow", "mass_flow", 1.0, show_if=("property", ("Mass flow",))),
        Param("pressure", "Pressure", "pressure", 301.325, show_if=("property", ("Pressure",))),
    ]

    def _stream(self):
        name = self.p("stream")
        if not name:
            raise ValueError("Choose the stream to specify.")
        s = self._ctx.streams.get(name)
        if s is None:
            raise ValueError(f"Stream '{name}' does not exist.")
        return s

    def hydraulics(self, net):
        s = self._stream()
        if self.p("property") == "Mass flow":
            net.flow(s, self.p("flow"), f"specified flow of '{s.name}'")
        else:
            net.pressure(s, self.p("pressure"), f"specified pressure of '{s.name}'")

    def calculate(self):
        s = self._stream()
        if not s.known:
            return
        flow = self.p("property") == "Mass flow"
        target = self.p("flow") if flow else self.p("pressure")
        actual = s.m if flow else s.P
        kind = "mass_flow" if flow else "pressure"
        self.result("target", "Specified value", target, kind)
        self.result("actual", "Value in the solution", actual, kind)
        if not self.pf:
            self.warn("Specifications act only in pressure–flow mode (switch the solver in the toolbar).")
