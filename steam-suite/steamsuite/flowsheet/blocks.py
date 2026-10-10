"""Equipment models.

All equipment uses steady-state mass and energy balances with IAPWS-IF97
properties. Internal units: kPa(a), °C, kg/s, kJ/kg, kW.
"""

from __future__ import annotations

import math

from ..report import num, tex_text, unit
from ..units import P_ATM_KPA, fmt
from ..water import (
    P_CRIT_KPA,
    T_sat,
    state_Ph,
    state_PT,
    state_Ps,
    state_Px,
)
from ..hydraulics import characteristic, npsh_available, valve_cv_required, valve_outlet_pressure
from .core import Block, Param, Port, allocate_outlets, register, requested_outflow

TOL_P = 1e-6  # kPa
CP_WATER = 4.186  # kJ/(kg·K), cooling water


def _sat_h(P: float) -> tuple[float, float]:
    """(h_f, h_g) at pressure P."""
    return state_Px(P, 0.0).h, state_Px(P, 1.0).h


def _kj(v: float) -> str:
    return f"{num(v, 5)}{unit('kJ/kg')}"


# --- sources --------------------------------------------------------------------


@register
class Feed(Block):
    TYPE = "feed"
    LABEL = "Water / steam supply"
    CATEGORY = "Supplies"
    DESCRIPTION = ("Water or steam entering the system, for example make-up water or imported steam. "
                   "Set the flow to 'As required' to supply whatever the connected equipment needs.")
    INLETS = []
    OUTLETS = [Port("out", "Outlet")]
    PARAMS = [
        Param("pressure", "Pressure", "pressure", 301.325),
        Param("condition", "Condition given by", "choice", "Temperature", choices=("Temperature", "Dryness fraction")),
        Param("temperature", "Temperature", "temperature", 20.0, show_if=("condition", ("Temperature",))),
        Param("dryness", "Dryness fraction", "fraction", 1.0, help="0 = saturated water, 1 = dry saturated steam",
              show_if=("condition", ("Dryness fraction",)), min_value=0.0, max_value=1.0),
        Param("flow_mode", "Flow", "choice", "Fixed", choices=("Fixed", "As required"),
              help="'As required' supplies whatever the connected equipment asks for (e.g. make-up water)."),
        Param("flow", "Flow rate (fixed, or a starting estimate)", "mass_flow", 1.0, min_value=0.0),
    ]

    def _state(self):
        if self.p("condition") == "Dryness fraction":
            return state_Px(self.p("pressure"), self.p("dryness"))
        return state_PT(self.p("pressure"), self.p("temperature"))

    def calculate(self):
        st = self._state()
        out = self.s_out("out")
        if self.p("flow_mode") == "Fixed":
            m = self.p("flow")
        else:
            m = out.demand if out.demand is not None else self.p("flow")
            if out.demand is None and self._ctx.final:
                self.warn("Flow is 'As required' but nothing downstream requests a flow; "
                          "the starting estimate was used.")
        out.set(m, st.P, st.h)
        self.result("flow", "Flow supplied", m, "mass_flow")
        self.result("temperature", "Temperature", st.T, "temperature")
        self.result("condition", "Condition", st.describe(), "text")
        self.step("Supply conditions",
                  text=(f"{st.describe()} at {fmt(st.P)} kPa(a) and {fmt(st.T)} °C. "
                        + ("Flow fixed by the user." if self.p("flow_mode") == "Fixed"
                           else "Flow set by what the downstream equipment requires.")),
                  result=rf"h = {_kj(st.h)}, \quad \dot m = {num(m, 5)}{unit('kg/s')}")

    def initial_guess(self, port):
        st = self._state()
        out = self.s_out("out")
        m = self.p("flow") if self.p("flow_mode") == "Fixed" else (out.demand or self.p("flow"))
        return st.P, st.h, m


# --- pressure changers ------------------------------------------------------------


@register
class Pump(Block):
    TYPE = "pump"
    LABEL = "Pump"
    CATEGORY = "Pressure change"
    DESCRIPTION = ("Raises the pressure of water, e.g. a boiler feed pump. Specify the outlet pressure, the "
                   "pressure rise, or a pump curve. Checks the suction head (NPSH).")
    INLETS = [Port("in", "Suction")]
    OUTLETS = [Port("out", "Discharge")]
    PARAMS = [
        Param("mode", "Specify", "choice", "Outlet pressure",
              choices=("Outlet pressure", "Pressure rise", "Pump curve")),
        Param("outlet_pressure", "Outlet pressure", "pressure", 1301.325, show_if=("mode", ("Outlet pressure",))),
        Param("pressure_rise", "Pressure rise", "pressure_diff", 1000.0, min_value=0.0,
              show_if=("mode", ("Pressure rise",))),
        Param("shutoff_head", "Shut-off head (zero flow)", "head", 150.0, min_value=0.0,
              show_if=("mode", ("Pump curve",)), group="Pump curve"),
        Param("rated_flow", "Rated flow (best efficiency point)", "volume_flow", 20.0, min_value=0.0,
              show_if=("mode", ("Pump curve",)), group="Pump curve"),
        Param("rated_head", "Head at rated flow", "head", 120.0, min_value=0.0,
              show_if=("mode", ("Pump curve",)), group="Pump curve"),
        Param("efficiency", "Pump efficiency (at rated flow for a curve)", "percent", 75.0, min_value=1.0,
              max_value=100.0, help="Isentropic (hydraulic) efficiency."),
        Param("motor_efficiency", "Motor efficiency", "percent", 95.0, min_value=1.0, max_value=100.0),
        Param("npshr", "NPSH required (0 = don't check)", "head", 0.0, min_value=0.0, group="Suction",
              help="From the pump data sheet. Compared with the NPSH available at the suction."),
        Param("suction_head", "Static head of liquid above the pump suction", "head", 0.0, group="Suction",
              help="Height of the liquid level in the suction vessel above the pump inlet, less suction line "
                   "losses. Added to the NPSH available."),
    ]

    def _outlet_pressure(self, sin, st1):
        mode = self.p("mode")
        if mode == "Pressure rise":
            return sin.P + self.p("pressure_rise"), self.p("efficiency") / 100.0, None
        if mode == "Pump curve":
            q = sin.m / st1.rho * 3600.0
            h0, qr, hr = self.p("shutoff_head"), self.p("rated_flow"), self.p("rated_head")
            if qr <= 0:
                raise ValueError("Enter a rated flow greater than zero for the pump curve.")
            r = q / qr
            head = h0 - (h0 - hr) * r * r
            if head <= 0:
                raise ValueError(f"The flow ({fmt(q)} m³/h) is beyond the end of the pump curve (head falls to zero).")
            eta = max(self.p("efficiency") / 100.0 * (2 * r - r * r), 0.05) if q > 0 else self.p("efficiency") / 100.0
            return sin.P + st1.rho * 9.80665 * head / 1000.0, eta, (q, head, r)
        return self.p("outlet_pressure"), self.p("efficiency") / 100.0, None

    def calculate(self):
        sin, out = self.s_in("in"), self.s_out("out")
        st1 = sin.state
        P2, eta, curve = self._outlet_pressure(sin, st1)
        if P2 < sin.P - TOL_P:
            raise ValueError(f"Outlet pressure ({fmt(P2)} kPa(a)) is below the inlet pressure ({fmt(sin.P)} kPa(a)).")
        if st1.phase in ("vapour", "saturated vapour") or (st1.phase == "two-phase" and st1.x > 1e-4):
            self.warn("The pump inlet contains steam. Pumps need subcooled water to avoid cavitation.")
        eta_m = self.p("motor_efficiency") / 100.0
        h2s = state_Ps(P2, st1.s).h
        h2 = st1.h + (h2s - st1.h) / eta
        W = sin.m * (h2 - st1.h)
        out.set(sin.m, P2, h2)
        st2 = out.state
        self.work_in = W
        head = (P2 - sin.P) * 1000.0 / (st1.rho * 9.80665)
        q = sin.m / st1.rho * 3600.0
        self.result("power", "Shaft power", W, "power")
        self.result("electric", "Electrical power", W / eta_m, "power")
        self.result("dP", "Pressure rise", P2 - sin.P, "pressure_diff")
        self.result("head", "Differential head", head, "head")
        self.result("flow_vol", "Volumetric flow", q, "volume_flow")
        self.result("eff", "Pump efficiency", eta * 100.0, "percent")
        self.result("dT", "Temperature rise", st2.T - st1.T, "temperature_diff")
        npsha = npsh_available(st1)
        if npsha is not None:
            npsha += self.p("suction_head")
            self.result("npsha", "NPSH available", npsha, "head")
            npshr = self.p("npshr")
            if npshr > 0 and npsha < npshr + 0.5:
                self.warn(f"NPSH available ({fmt(npsha, 3)} m) is less than NPSH required plus a 0.5 m margin "
                          f"({fmt(npshr + 0.5, 3)} m): the pump may cavitate. Raise the suction pressure or subcool "
                          "the water.")
        if curve is not None:
            qv, hv, r = curve
            self.step("Operating point on the pump curve",
                      text=("The curve is a parabola through the shut-off head and the rated point. The efficiency "
                            "falls away from the rated (best-efficiency) flow."),
                      equation=(r"H = H_0 - (H_0 - H_r)\left(\frac{Q}{Q_r}\right)^2, \qquad "
                                r"\eta = \eta_r\left[2\frac{Q}{Q_r} - \left(\frac{Q}{Q_r}\right)^2\right]"),
                      substitution=(rf"H = {num(self.p('shutoff_head'), 4)} - ({num(self.p('shutoff_head'), 4)} - "
                                    rf"{num(self.p('rated_head'), 4)})\left(\frac{{{num(qv, 4)}}}{{{num(self.p('rated_flow'), 4)}}}\right)^2"),
                      result=rf"H = {num(hv, 4)}{unit('m')}, \quad \eta = {num(eta * 100, 3)}\,\%, \quad "
                             rf"\Delta P = \rho g H = {num(P2 - sin.P, 4)}{unit('kPa')}")
        self.step("Isentropic compression",
                  text="The ideal (isentropic) outlet enthalpy is found at the outlet pressure and the inlet entropy.",
                  equation=r"h_{2s} = h(P_2,\ s_1)",
                  result=rf"h_{{2s}} = h({num(P2, 5)}{unit('kPa')},\ {num(st1.s, 5)}) = {_kj(h2s)}")
        self.step("Actual outlet enthalpy",
                  equation=r"h_2 = h_1 + \frac{h_{2s} - h_1}{\eta}",
                  substitution=rf"h_2 = {num(st1.h, 6)} + \frac{{{num(h2s, 6)} - {num(st1.h, 6)}}}{{{num(eta, 3)}}}",
                  result=rf"h_2 = {_kj(h2)} \quad (T_2 = {num(st2.T, 4)}{unit('°C')})")
        self.step("Power",
                  equation=r"W = \dot m\,(h_2 - h_1), \qquad W_{elec} = W / \eta_{motor}",
                  substitution=rf"W = {num(sin.m, 5)} \times ({num(h2, 6)} - {num(st1.h, 6)})",
                  result=rf"W = {num(W, 5)}{unit('kW')}, \quad W_{{elec}} = {num(W / eta_m, 5)}{unit('kW')}")
        if npsha is not None:
            self.step("Net positive suction head available",
                      text=("Suction pressure above the vapour pressure, expressed as a head of water, plus the static "
                            "head of liquid above the suction (velocity head neglected)."),
                      equation=r"NPSH_a = \frac{P_1 - P_v(T_1)}{\rho_1 g} + z_s",
                      result=rf"NPSH_a = {num(npsha, 4)}{unit('m')}")

    def update_demands(self):
        self.pass_demand_through()

    def initial_guess(self, port):
        sin = self.s_in("in")
        if sin.known:
            try:
                P2, _, _ = self._outlet_pressure(sin, sin.state)
            except ValueError:
                P2 = sin.P
            return P2, sin.h, sin.m
        if self.p("mode") == "Outlet pressure":
            return self.p("outlet_pressure"), state_Px(101.325, 0.0).h, 0.0
        return None


@register
class Compressor(Block):
    TYPE = "compressor"
    LABEL = "Steam compressor"
    CATEGORY = "Pressure change"
    DESCRIPTION = "Compresses steam to a higher pressure, e.g. mechanical vapour recompression (MVR)."
    INLETS = [Port("in", "Suction")]
    OUTLETS = [Port("out", "Discharge")]
    PARAMS = [
        Param("outlet_pressure", "Outlet pressure", "pressure", 401.325),
        Param("efficiency", "Isentropic efficiency", "percent", 75.0, min_value=1.0, max_value=100.0),
        Param("motor_efficiency", "Motor / drive efficiency", "percent", 95.0, min_value=1.0, max_value=100.0),
    ]

    def calculate(self):
        sin, out = self.s_in("in"), self.s_out("out")
        st1 = sin.state
        P2 = self.p("outlet_pressure")
        if P2 <= sin.P + TOL_P:
            raise ValueError(f"Outlet pressure ({fmt(P2)} kPa(a)) must be above the inlet pressure ({fmt(sin.P)} kPa(a)).")
        if st1.is_liquid_like or (st1.phase == "two-phase" and st1.x < 0.98):
            self.warn("The compressor inlet contains water droplets. Compressors need dry steam.")
        eta = self.p("efficiency") / 100.0
        eta_m = self.p("motor_efficiency") / 100.0
        h2s = state_Ps(P2, st1.s).h
        h2 = st1.h + (h2s - st1.h) / eta
        out.set(sin.m, P2, h2)
        st2 = out.state
        W = sin.m * (h2 - st1.h)
        self.work_in = W
        self.result("power", "Shaft power", W, "power")
        self.result("electric", "Electrical power", W / eta_m, "power")
        self.result("ratio", "Pressure ratio", P2 / sin.P, "number")
        self.result("T_out", "Discharge temperature", st2.T, "temperature")
        self.result("condition", "Discharge condition", st2.describe(), "text")
        self.step("Isentropic compression",
                  equation=r"h_{2s} = h(P_2,\ s_1), \qquad h_2 = h_1 + \frac{h_{2s} - h_1}{\eta}",
                  substitution=rf"h_2 = {num(st1.h, 6)} + \frac{{{num(h2s, 6)} - {num(st1.h, 6)}}}{{{num(eta, 3)}}}",
                  result=rf"h_2 = {_kj(h2)}, \quad T_2 = {num(st2.T, 4)}{unit('°C')}")
        self.step("Power",
                  equation=r"W = \dot m\,(h_2 - h_1)",
                  substitution=rf"W = {num(sin.m, 5)} \times ({num(h2, 6)} - {num(st1.h, 6)})",
                  result=rf"W = {num(W, 5)}{unit('kW')}")

    def update_demands(self):
        self.pass_demand_through()

    def initial_guess(self, port):
        sin = self.s_in("in")
        P2 = self.p("outlet_pressure")
        if sin.known:
            return P2, sin.h, sin.m
        return P2, state_Px(min(P2, P_CRIT_KPA - 1), 1.0).h, 0.0


def _inverse_characteristic(fraction: float, kind: str, rangeability: float = 50.0) -> float:
    """Opening (0–1) that gives a fraction of the rated Cv."""
    f = min(max(fraction, 0.0), 1.0)
    if kind == "Equal percentage":
        return 1.0 + math.log(f) / math.log(rangeability) if f > 1.0 / rangeability else 0.0
    if kind == "Quick opening":
        return f * f
    return f


@register
class Valve(Block):
    TYPE = "valve"
    LABEL = "Valve / control valve"
    CATEGORY = "Pressure change"
    DESCRIPTION = ("Reduces pressure at constant enthalpy: a pressure-reducing valve (PRV), control valve or steam "
                   "trap. Specify the outlet pressure or pressure drop (the Cv needed is calculated), or the valve's "
                   "Cv and opening (the pressure drop is calculated).")
    INLETS = [Port("in", "Inlet")]
    OUTLETS = [Port("out", "Outlet")]
    PARAMS = [
        Param("mode", "Specify", "choice", "Outlet pressure",
              choices=("Outlet pressure", "Pressure drop", "Cv and opening")),
        Param("outlet_pressure", "Outlet pressure", "pressure", 201.325, show_if=("mode", ("Outlet pressure",))),
        Param("pressure_drop", "Pressure drop", "pressure_diff", 100.0, min_value=0.0,
              show_if=("mode", ("Pressure drop",))),
        Param("cv", "Rated Cv (fully open; 0 = not known)", "number", 0.0, min_value=0.0, group="Valve data",
              help="US flow coefficient: US gallons per minute of water at 1 psi pressure drop."),
        Param("opening", "Opening", "percent", 100.0, min_value=0.0, max_value=100.0,
              show_if=("mode", ("Cv and opening",)), group="Valve data"),
        Param("characteristic", "Characteristic", "choice", "Equal percentage",
              choices=("Linear", "Equal percentage", "Quick opening"), group="Valve data"),
        Param("fl", "Liquid pressure recovery factor FL", "number", 0.9, min_value=0.3, max_value=1.0,
              group="Valve data"),
        Param("xt", "Pressure differential ratio factor xT", "number", 0.7, min_value=0.1, max_value=1.0,
              group="Valve data"),
    ]

    def _outlet(self, sin, st1):
        mode = self.p("mode")
        if mode == "Pressure drop":
            return sin.P - self.p("pressure_drop"), None
        if mode == "Cv and opening":
            cv_rated = self.p("cv")
            if cv_rated <= 0:
                raise ValueError("Enter the valve's rated Cv to calculate the pressure drop.")
            cv = cv_rated * characteristic(self.p("opening") / 100.0, self.p("characteristic"))
            P2, sizing = valve_outlet_pressure(sin.m, st1, cv, self.p("fl"), self.p("xt"))
            return P2, (cv, sizing)
        return self.p("outlet_pressure"), None

    def calculate(self):
        sin, out = self.s_in("in"), self.s_out("out")
        st1 = sin.state
        P2, cv_mode = self._outlet(sin, st1)
        if P2 <= 0:
            raise ValueError("The pressure drop is larger than the inlet pressure.")
        if P2 > sin.P + TOL_P:
            raise ValueError(f"Outlet pressure ({fmt(P2)} kPa(a)) is above the inlet pressure ({fmt(sin.P)} kPa(a)).")
        out.set(sin.m, P2, sin.h)
        st2 = out.state
        self.result("dP", "Pressure drop", sin.P - P2, "pressure_diff")
        self.result("T_out", "Outlet temperature", st2.T, "temperature")
        self.result("condition", "Outlet condition", st2.describe(), "text")
        if st1.is_liquid_like and st2.phase == "two-phase":
            self.result("flash", "Flash steam fraction", st2.x * 100.0, "percent")
        self.step("Throttling at constant enthalpy",
                  text=("No heat or work is exchanged, so the enthalpy does not change. "
                        f"Inlet: {st1.describe().lower()}; outlet: {st2.describe().lower()}."),
                  equation=r"h_2 = h_1",
                  result=rf"h_2 = {_kj(st2.h)}, \quad T_2 = T({num(P2, 5)}{unit('kPa')},\ h_2) = {num(st2.T, 4)}{unit('°C')}")

        # flow coefficient
        if sin.m <= 0 or sin.P - P2 <= 1e-9:
            return
        if cv_mode is not None:
            cv, sizing = cv_mode
            self.result("cv", "Cv in use (rated × characteristic)", cv, "number")
        else:
            sizing = valve_cv_required(sin.m, st1, P2, self.p("fl"), self.p("xt"))
            cv = sizing.cv
            self.result("cv", "Cv required", cv, "number")
            if self.p("cv") > 0:
                frac = cv / self.p("cv")
                if frac > 1.0:
                    self.warn(f"The valve is too small: it needs Cv {fmt(cv, 3)} but its rated Cv is {fmt(self.p('cv'), 3)}.")
                else:
                    opening = _inverse_characteristic(frac, self.p("characteristic")) * 100.0
                    self.result("opening", "Opening required", opening, "percent")
                    if opening > 90:
                        self.warn(f"The valve would be {fmt(opening, 3)} % open: little control margin left.")
                    elif opening < 10:
                        self.warn(f"The valve would be only {fmt(opening, 3)} % open: it is oversized for this duty.")
        self.result("choked", "Choked flow", "Yes" if sizing.choked else "No", "text")
        for note in sizing.notes:
            self.warn(note)
        W = sin.m * 3600.0
        if sizing.regime == "liquid":
            q = W / st1.rho
            self.step("Flow coefficient (liquid, IEC 60534-2-1)",
                      text=("Q in m³/h, ΔP in kPa, N1 = 0.0865. The usable pressure drop is limited by choking: "
                            f"ΔP_max = FL²(P1 − FF·Pv) = {fmt(sizing.dp_choked)} kPa."),
                      equation=r"C_v = \frac{Q}{N_1}\sqrt{\frac{\rho_1/\rho_0}{\Delta P}}",
                      substitution=(rf"C_v = \frac{{{num(q, 5)}}}{{0.0865}}\sqrt{{\frac{{{num(st1.rho, 5)}/999}}"
                                    rf"{{{num(min(sin.P - P2, sizing.dp_choked), 5)}}}}}"),
                      result=rf"C_v = {num(cv, 4)}",
                      reference="IEC 60534-2-1 / ISA-75.01.01")
        else:
            self.step("Flow coefficient (steam, IEC 60534-2-1)",
                      text=("W in kg/h, P1 in kPa(a), ρ1 in kg/m³, N6 = 2.73. x is the pressure drop ratio "
                            "(limited to Fγ·xT when choked) and Y the expansion factor."),
                      equation=r"C_v = \frac{W}{N_6\,Y\sqrt{x\,P_1\,\rho_1}}, \qquad Y = 1 - \frac{x}{3F_\gamma x_T}",
                      substitution=(rf"C_v = \frac{{{num(W, 5)}}}{{2.73 \times {num(sizing.y, 4)} \sqrt{{"
                                    rf"{num(sizing.x_eff, 4)} \times {num(sin.P, 5)} \times {num(st1.rho, 4)}}}}}"),
                      result=rf"C_v = {num(cv, 4)}",
                      reference="IEC 60534-2-1 / ISA-75.01.01")

    def update_demands(self):
        self.pass_demand_through()

    def initial_guess(self, port):
        sin = self.s_in("in")
        if sin.known:
            try:
                P2, _ = self._outlet(sin, sin.state)
            except ValueError:
                P2 = sin.P * 0.9
            return P2, sin.h, sin.m
        if self.p("mode") == "Outlet pressure":
            P2 = self.p("outlet_pressure")
            return P2, state_Px(min(P2, P_CRIT_KPA - 1), 1.0).h, 0.0
        return None


@register
class Turbine(Block):
    TYPE = "turbine"
    LABEL = "Steam turbine"
    CATEGORY = "Pressure change"
    DESCRIPTION = "Expands steam to a lower pressure to produce shaft power (back-pressure or condensing turbine)."
    INLETS = [Port("in", "Steam inlet")]
    OUTLETS = [Port("out", "Exhaust")]
    PARAMS = [
        Param("outlet_pressure", "Exhaust pressure", "pressure", 401.325),
        Param("efficiency", "Isentropic efficiency", "percent", 75.0, min_value=1.0, max_value=100.0),
        Param("generator_efficiency", "Mechanical × generator efficiency", "percent", 96.0, min_value=1.0,
              max_value=100.0),
    ]

    def calculate(self):
        sin, out = self.s_in("in"), self.s_out("out")
        st1 = sin.state
        P2 = self.p("outlet_pressure")
        if P2 >= sin.P - TOL_P:
            raise ValueError(f"Exhaust pressure ({fmt(P2)} kPa(a)) must be below the inlet pressure ({fmt(sin.P)} kPa(a)).")
        if st1.is_liquid_like or st1.phase == "two-phase":
            self.warn("The turbine inlet is not dry steam.")
        eta = self.p("efficiency") / 100.0
        eta_g = self.p("generator_efficiency") / 100.0
        h2s = state_Ps(P2, st1.s).h
        h2 = st1.h - eta * (st1.h - h2s)
        out.set(sin.m, P2, h2)
        st2 = out.state
        W = sin.m * (st1.h - h2)
        self.work_in = -W
        self.result("power", "Shaft power", W, "power")
        self.result("electric", "Electrical power", W * eta_g, "power")
        self.result("T_out", "Exhaust temperature", st2.T, "temperature")
        self.result("condition", "Exhaust condition", st2.describe(), "text")
        if st2.x is not None and st2.x < 0.88:
            self.warn(f"Exhaust moisture is {fmt((1 - st2.x) * 100, 3)} %. Above about 12 % moisture, blade erosion "
                      "becomes a concern.")
        self.step("Isentropic expansion",
                  text="The ideal (isentropic) exhaust enthalpy is found at the exhaust pressure and the inlet entropy.",
                  equation=r"h_{2s} = h(P_2,\ s_1)",
                  result=rf"h_{{2s}} = h({num(P2, 5)}{unit('kPa')},\ {num(st1.s, 5)}) = {_kj(h2s)}")
        self.step("Actual exhaust enthalpy",
                  equation=r"h_2 = h_1 - \eta\,(h_1 - h_{2s})",
                  substitution=rf"h_2 = {num(st1.h, 6)} - {num(eta, 3)} \times ({num(st1.h, 6)} - {num(h2s, 6)})",
                  result=rf"h_2 = {_kj(h2)} \quad {tex_text('(' + st2.describe() + ')')}")
        self.step("Power",
                  equation=r"W = \dot m\,(h_1 - h_2), \qquad W_{elec} = W\,\eta_{gen}",
                  substitution=rf"W = {num(sin.m, 5)} \times ({num(st1.h, 6)} - {num(h2, 6)})",
                  result=rf"W = {num(W, 5)}{unit('kW')}, \quad W_{{elec}} = {num(W * eta_g, 5)}{unit('kW')}")

    def update_demands(self):
        self.pass_demand_through()

    def initial_guess(self, port):
        sin = self.s_in("in")
        P2 = self.p("outlet_pressure")
        if sin.known and P2 < sin.P:
            h2s = state_Ps(P2, sin.state.s).h
            return P2, sin.h - self.p("efficiency") / 100.0 * (sin.h - h2s), sin.m
        return P2, state_Px(min(P2, P_CRIT_KPA - 1), 1.0).h, 0.0


# --- heat transfer ------------------------------------------------------------------


@register
class Boiler(Block):
    TYPE = "boiler"
    LABEL = "Boiler"
    CATEGORY = "Heat transfer"
    DESCRIPTION = ("Turns feedwater into saturated or superheated steam. Reports heat duty and fuel input, "
                   "with optional continuous blowdown.")
    INLETS = [Port("in", "Feedwater")]
    OUTLETS = [Port("steam", "Steam"), Port("blowdown", "Blowdown", optional=True)]
    PARAMS = [
        Param("pressure", "Steam pressure", "pressure", 1101.325),
        Param("steam_condition", "Steam condition", "choice", "Saturated", choices=("Saturated", "Superheated")),
        Param("temperature", "Steam temperature", "temperature", 250.0, show_if=("steam_condition", ("Superheated",))),
        Param("efficiency", "Boiler efficiency (fuel to steam)", "percent", 85.0, min_value=1.0, max_value=100.0),
        Param("blowdown", "Blowdown (% of feedwater)", "percent", 0.0, min_value=0.0, max_value=50.0),
    ]

    def _steam_state(self):
        P = self.p("pressure")
        if self.p("steam_condition") == "Superheated":
            T = self.p("temperature")
            if P < P_CRIT_KPA and T <= T_sat(P) + 1e-6:
                raise ValueError(f"Steam temperature {fmt(T)} °C is not above the boiling point "
                                 f"({fmt(T_sat(P))} °C) at the boiler pressure.")
            return state_PT(P, T)
        if P >= P_CRIT_KPA:
            raise ValueError("Above the critical pressure, choose 'Superheated' and give a temperature.")
        return state_Px(P, 1.0)

    def calculate(self):
        fw = self.s_in("in")
        P = self.p("pressure")
        if fw.P < P - 1e-3:
            self.warn(f"Feedwater pressure ({fmt(fw.P)} kPa(a)) is below the boiler pressure ({fmt(P)} kPa(a)). "
                      "Add or check the feed pump.")
        bd = self.p("blowdown") / 100.0
        bd_out = self.s_out("blowdown")
        if bd > 0 and bd_out is None:
            raise ValueError("Blowdown is set above zero: connect a blowdown outlet stream.")
        st_s = self._steam_state()
        h_bd = state_Px(P, 0.0).h if P < P_CRIT_KPA else st_s.h
        m_fw = fw.m
        m_bd = bd * m_fw
        m_s = m_fw - m_bd
        Q = m_s * st_s.h + m_bd * h_bd - m_fw * fw.h
        eta = self.p("efficiency") / 100.0
        self.s_out("steam").set(m_s, P, st_s.h)
        if bd_out is not None:
            bd_out.set(m_bd, P, h_bd)
        self.heat_in = Q
        self.result("steam", "Steam generated", m_s, "mass_flow")
        self.result("duty", "Heat to water/steam", Q, "power")
        self.result("fuel", "Fuel energy input", Q / eta, "power")
        self.result("T_steam", "Steam temperature", st_s.T, "temperature")
        if bd_out is not None:
            self.result("blowdown", "Blowdown flow", m_bd, "mass_flow")
        self.step("Steam conditions",
                  text=f"{st_s.describe()} at {fmt(P)} kPa(a).",
                  result=rf"h_{{steam}} = {_kj(st_s.h)}")
        if bd > 0:
            self.step("Blowdown",
                      text="Blowdown leaves as saturated water at boiler pressure.",
                      equation=r"\dot m_{bd} = b\,\dot m_{fw}, \qquad \dot m_{steam} = \dot m_{fw} - \dot m_{bd}",
                      substitution=rf"\dot m_{{bd}} = {num(bd, 4)} \times {num(m_fw, 5)}",
                      result=rf"\dot m_{{bd}} = {num(m_bd, 5)}{unit('kg/s')}, \quad h_{{bd}} = {_kj(h_bd)}")
        self.step("Heat duty and fuel",
                  equation=(r"Q = \dot m_{steam} h_{steam} + \dot m_{bd} h_{bd} - \dot m_{fw} h_{fw}, \qquad "
                            r"Q_{fuel} = Q / \eta"),
                  substitution=(rf"Q = {num(m_s, 5)} \times {num(st_s.h, 6)} + {num(m_bd, 4)} \times {num(h_bd, 5)}"
                                rf" - {num(m_fw, 5)} \times {num(fw.h, 5)}"),
                  result=rf"Q = {num(Q, 5)}{unit('kW')}, \quad Q_{{fuel}} = {num(Q / eta, 5)}{unit('kW')}")

    def update_demands(self):
        steam, fw = self.s_out("steam"), self.s_in("in")
        bd = self.p("blowdown") / 100.0
        if steam.demand is not None and bd < 1:
            fw.demand = steam.demand / (1.0 - bd)

    def initial_guess(self, port):
        P = self.p("pressure")
        if port == "steam":
            steam = self.s_out("steam")
            return P, self._steam_state().h, steam.demand or 0.0
        return P, state_Px(min(P, P_CRIT_KPA - 1), 0.0).h, 0.0


@register
class Heater(Block):
    TYPE = "heater"
    LABEL = "Heater / cooler"
    CATEGORY = "Heat transfer"
    DESCRIPTION = ("Adds or removes heat on one side of a heat exchanger. Specify the outlet temperature, the "
                   "outlet dryness fraction, or the heat duty.")
    INLETS = [Port("in", "Inlet")]
    OUTLETS = [Port("out", "Outlet")]
    PARAMS = [
        Param("spec", "Specify", "choice", "Outlet temperature",
              choices=("Outlet temperature", "Outlet dryness fraction", "Heat duty")),
        Param("temperature", "Outlet temperature", "temperature", 100.0, show_if=("spec", ("Outlet temperature",))),
        Param("dryness", "Outlet dryness fraction", "fraction", 0.0, show_if=("spec", ("Outlet dryness fraction",)),
              min_value=0.0, max_value=1.0),
        Param("duty", "Heat duty (+ heating, − cooling)", "power", 1000.0, show_if=("spec", ("Heat duty",))),
        Param("pressure_drop", "Pressure drop", "pressure_diff", 0.0, min_value=0.0),
    ]

    def calculate(self):
        sin, out = self.s_in("in"), self.s_out("out")
        P2 = sin.P - self.p("pressure_drop")
        if P2 <= 0:
            raise ValueError("The pressure drop is larger than the inlet pressure.")
        spec = self.p("spec")
        if spec == "Outlet temperature":
            h2 = state_PT(P2, self.p("temperature")).h
            Q = sin.m * (h2 - sin.h)
        elif spec == "Outlet dryness fraction":
            h2 = state_Px(P2, self.p("dryness")).h
            Q = sin.m * (h2 - sin.h)
        else:
            Q = self.p("duty")
            if sin.m > 1e-12:
                h2 = sin.h + Q / sin.m
            else:
                h2 = sin.h
                if abs(Q) > 0:
                    self.warn("No flow: the heat duty cannot be applied.")
                Q = 0.0
        out.set(sin.m, P2, h2)
        st1, st2 = sin.state, out.state
        self.heat_in = Q
        self.result("duty", "Heat duty (+ heating, − cooling)", Q, "power")
        self.result("T_out", "Outlet temperature", st2.T, "temperature")
        self.result("condition", "Outlet condition", st2.describe(), "text")
        if spec == "Heat duty":
            self.step("Energy balance",
                      equation=r"h_2 = h_1 + Q / \dot m",
                      substitution=rf"h_2 = {num(st1.h, 6)} + {num(Q, 5)} / {num(sin.m, 5)}",
                      result=rf"h_2 = {_kj(h2)} \quad {tex_text('(' + st2.describe() + ')')}")
        else:
            self.step("Energy balance",
                      text=f"Outlet: {st2.describe().lower()} at {fmt(P2)} kPa(a).",
                      equation=r"Q = \dot m\,(h_2 - h_1)",
                      substitution=rf"Q = {num(sin.m, 5)} \times ({num(h2, 6)} - {num(st1.h, 6)})",
                      result=rf"Q = {num(Q, 5)}{unit('kW')}")

    def update_demands(self):
        self.pass_demand_through()


@register
class Condenser(Block):
    TYPE = "condenser"
    LABEL = "Condenser"
    CATEGORY = "Heat transfer"
    DESCRIPTION = "Condenses steam to water, rejecting heat to cooling water."
    INLETS = [Port("in", "Steam inlet")]
    OUTLETS = [Port("out", "Condensate")]
    PARAMS = [
        Param("subcooling", "Condensate subcooling", "temperature_diff", 0.0, min_value=0.0),
        Param("pressure_drop", "Pressure drop", "pressure_diff", 0.0, min_value=0.0),
        Param("cw_rise", "Cooling water temperature rise", "temperature_diff", 10.0, min_value=0.1),
    ]

    def calculate(self):
        sin, out = self.s_in("in"), self.s_out("out")
        P2 = sin.P - self.p("pressure_drop")
        if P2 <= 0:
            raise ValueError("The pressure drop is larger than the inlet pressure.")
        sub = self.p("subcooling")
        h2 = state_PT(P2, T_sat(P2) - sub).h if sub > 0 else state_Px(P2, 0.0).h
        Q = sin.m * (h2 - sin.h)
        out.set(sin.m, P2, h2)
        st2 = out.state
        cw = -Q / (CP_WATER * self.p("cw_rise"))
        self.heat_in = Q
        self.result("duty", "Heat rejected", -Q, "power")
        self.result("T_out", "Condensate temperature", st2.T, "temperature")
        self.result("cw", "Cooling water flow", cw, "mass_flow")
        self.step("Heat rejected",
                  text=f"The condensate leaves as {st2.describe().lower()} at {fmt(P2)} kPa(a).",
                  equation=r"Q = \dot m\,(h_1 - h_2), \qquad \dot m_{cw} = \frac{Q}{c_p\,\Delta T_{cw}}",
                  substitution=(rf"Q = {num(sin.m, 5)} \times ({num(sin.h, 6)} - {num(h2, 6)}), \quad "
                                rf"\dot m_{{cw}} = \frac{{Q}}{{{CP_WATER} \times {num(self.p('cw_rise'), 3)}}}"),
                  result=rf"Q = {num(-Q, 5)}{unit('kW')}, \quad \dot m_{{cw}} = {num(cw, 5)}{unit('kg/s')}")

    def update_demands(self):
        self.pass_demand_through()


# --- mixing and splitting ------------------------------------------------------------


@register
class Mixer(Block):
    TYPE = "mixer"
    LABEL = "Mixer"
    CATEGORY = "Mixing and splitting"
    DESCRIPTION = "Combines several streams into one (e.g. condensate returns)."
    INLETS = [Port("in", "Inlets", multiple=True)]
    OUTLETS = [Port("out", "Outlet")]
    PARAMS = [
        Param("pressure_mode", "Outlet pressure", "choice", "Lowest inlet pressure",
              choices=("Lowest inlet pressure", "Specified")),
        Param("pressure", "Outlet pressure", "pressure", P_ATM_KPA, show_if=("pressure_mode", ("Specified",))),
    ]

    def calculate(self):
        ins, out = self.s_ins("in"), self.s_out("out")
        m = sum(s.m for s in ins)
        H = sum(s.m * s.h for s in ins)
        h = H / m if m > 1e-12 else sum(s.h for s in ins) / len(ins)
        p_min = min(s.P for s in ins)
        if self.p("pressure_mode") == "Specified":
            P = self.p("pressure")
            if P > p_min + TOL_P:
                self.warn(f"Specified outlet pressure is above the lowest inlet pressure ({fmt(p_min)} kPa(a)); "
                          "that inlet could not flow in.")
        else:
            P = p_min
        out.set(m, P, h)
        st = out.state
        self.result("flow", "Total flow", m, "mass_flow")
        self.result("T_out", "Outlet temperature", st.T, "temperature")
        self.result("condition", "Outlet condition", st.describe(), "text")
        self.step("Mass and energy balance",
                  equation=r"\dot m = \sum \dot m_i, \qquad h = \frac{\sum \dot m_i h_i}{\dot m}",
                  substitution=rf"h = \frac{{{num(H, 6)}}}{{{num(m, 5)}}}",
                  result=rf"\dot m = {num(m, 5)}{unit('kg/s')}, \quad h = {_kj(h)} \quad {tex_text('(' + st.describe() + ')')}")


@register
class Splitter(Block):
    TYPE = "splitter"
    LABEL = "Splitter"
    CATEGORY = "Mixing and splitting"
    DESCRIPTION = ("Divides one stream into several with the same conditions. Each outlet is a fixed flow, "
                   "a percentage, 'as required' by downstream equipment, or the remainder.")
    INLETS = [Port("in", "Inlet")]
    OUTLETS = [Port("out", "Outlets", multiple=True, with_specs=True)]
    PARAMS = []

    def calculate(self):
        sin = self.s_in("in")
        outs = self.s_outs("out")
        flows = allocate_outlets(self, sin.m, outs)
        for s in outs:
            s.set(flows[s.name], sin.P, sin.h)
            self.result(f"flow:{s.name}", f"Flow to {s.name}", flows[s.name], "mass_flow")
        rows = [["Outlet", "Specification", "Flow (kg/s)"]]
        specs = self.params.get("outlet_specs") or {}
        for s in outs:
            spec = specs.get(s.name) or {"mode": "Remainder"}
            mode = spec.get("mode", "Remainder")
            desc = {"Flow": f"Fixed {fmt(spec.get('value'))} kg/s", "Fraction": f"{fmt(spec.get('value'))} %",
                    "As required": "As required downstream", "Remainder": "Remainder"}.get(mode, mode)
            rows.append([s.name, desc, fmt(flows[s.name], 5)])
        self.step("Flow split", text="All outlets have the same pressure and enthalpy as the inlet.", table=rows)

    def update_demands(self):
        sin = self.s_in("in")
        outs = self.s_outs("out")
        specs = self.params.get("outlet_specs") or {}
        for s in outs:
            mode = (specs.get(s.name) or {}).get("mode", "Remainder")
            if mode == "Fraction" or (mode == "Remainder" and s.demand is None):
                return
        req = requested_outflow(self, outs, sin.m or 0.0)
        if req is not None:
            sin.demand = req

    def initial_guess(self, port):
        sin = self.s_in("in")
        return (sin.P, sin.h, 0.0) if sin.known else None


@register
class Header(Block):
    TYPE = "header"
    LABEL = "Steam header"
    CATEGORY = "Mixing and splitting"
    DESCRIPTION = ("A steam main at a set pressure that collects steam from supplies and distributes it to users. "
                   "Pick a balancing supply (e.g. the boiler or a PRV) that makes up whatever the users need.")
    INLETS = [Port("in", "Steam supplies", multiple=True)]
    OUTLETS = [Port("out", "Steam users", multiple=True, with_specs=True)]
    PARAMS = [
        Param("pressure", "Header pressure", "pressure", 1101.325),
        Param("balancing_inlet", "Balancing supply", "inlet_choice", "", inlet_port="in",
              help="This supply makes up the difference between what the users need and what the other "
                   "supplies provide."),
    ]

    def calculate(self):
        ins = self.s_ins("in")
        outs = self.s_outs("out")
        P = self.p("pressure")
        for s in ins:
            if s.P < P - 1e-3:
                self.warn(f"Supply '{s.name}' ({fmt(s.P)} kPa(a)) is below the header pressure and could not flow in.")
        m = sum(s.m for s in ins)
        H = sum(s.m * s.h for s in ins)
        h = H / m if m > 1e-12 else sum(s.h for s in ins) / len(ins)
        flows = allocate_outlets(self, m, outs)
        for s in outs:
            s.set(flows[s.name], P, h)
        st = state_Ph(P, h)
        self.result("flow", "Total flow", m, "mass_flow")
        self.result("T", "Header temperature", st.T, "temperature")
        self.result("condition", "Steam condition", st.describe(), "text")
        bal = self.p("balancing_inlet")
        if bal:
            bs = self._ctx.streams.get(bal)
            if bs is not None:
                self.result("balancing", f"Balancing supply ({bal})", bs.m, "mass_flow")
        rows = [["Stream", "Direction", "Flow (kg/s)", "h (kJ/kg)"]]
        rows += [[s.name, "in" + (" (balancing)" if s.name == bal else ""), fmt(s.m, 5), fmt(s.h, 5)] for s in ins]
        rows += [[s.name, "out", fmt(flows[s.name], 5), fmt(h, 5)] for s in outs]
        self.step("Header balance",
                  text=(f"Supplies mix at the header pressure of {fmt(P)} kPa(a) (any supply at higher pressure is "
                        f"throttled at constant enthalpy). Header steam: {st.describe().lower()}."),
                  equation=r"h = \frac{\sum \dot m_{in} h_{in}}{\sum \dot m_{in}}",
                  substitution=rf"h = \frac{{{num(H, 6)}}}{{{num(m, 5)}}}",
                  result=rf"h = {_kj(h)}, \quad T = {num(st.T, 4)}{unit('°C')}",
                  table=rows)

    def update_demands(self):
        bal = self.p("balancing_inlet")
        if not bal:
            return
        ins = self.s_ins("in")
        bs = next((s for s in ins if s.name == bal), None)
        if bs is None:
            return
        outs = self.s_outs("out")
        req = requested_outflow(self, outs, 0.0)
        if req is None:
            return
        others = sum(s.m or 0.0 for s in ins if s is not bs)
        bs.demand = max(req - others, 0.0)

    def initial_guess(self, port):
        P = self.p("pressure")
        return P, state_Px(min(P, P_CRIT_KPA - 1), 1.0).h, 0.0


# --- steam system equipment ---------------------------------------------------------------


@register
class FlashVessel(Block):
    TYPE = "flash"
    LABEL = "Flash vessel"
    CATEGORY = "Steam system"
    DESCRIPTION = ("Drops hot condensate (or blowdown) to a lower pressure and separates the flash steam from "
                   "the remaining water.")
    INLETS = [Port("in", "Inlet")]
    OUTLETS = [Port("vapour", "Flash steam"), Port("liquid", "Water")]
    PARAMS = [Param("pressure", "Vessel pressure", "pressure", 201.325)]

    def calculate(self):
        sin = self.s_in("in")
        P = self.p("pressure")
        if P > sin.P + TOL_P:
            raise ValueError(f"Vessel pressure ({fmt(P)} kPa(a)) is above the inlet pressure ({fmt(sin.P)} kPa(a)).")
        st = state_Ph(P, sin.h)
        hf, hg = _sat_h(P)
        if st.phase == "two-phase":
            x = st.x
            hv, hl = hg, hf
        elif st.is_vapour_like:
            x, hv, hl = 1.0, st.h, hf
        else:
            x, hv, hl = 0.0, hg, st.h
        mv, ml = x * sin.m, (1 - x) * sin.m
        self.s_out("vapour").set(mv, P, hv)
        self.s_out("liquid").set(ml, P, hl)
        self.result("flash", "Flash steam", mv, "mass_flow")
        self.result("fraction", "Flash fraction", x * 100.0, "percent")
        self.result("T", "Vessel temperature", st.T, "temperature")
        self.step("Flash fraction",
                  text=("The inlet is throttled to the vessel pressure at constant enthalpy. The fraction that flashes "
                        "to steam follows from the saturated water and steam enthalpies at the vessel pressure."),
                  equation=r"x = \frac{h_{in} - h_f}{h_g - h_f}",
                  substitution=rf"x = \frac{{{num(sin.h, 6)} - {num(hf, 6)}}}{{{num(hg, 6)} - {num(hf, 6)}}}",
                  result=(rf"x = {num(x, 4)} \;\Rightarrow\; \dot m_{{flash}} = {num(mv, 5)}{unit('kg/s')}"
                          if st.phase == "two-phase" else
                          rf"x = {num(x, 1)} \quad " + tex_text(f"({st.describe()}: {'no flashing' if x == 0 else 'all vapour'})")))

    def initial_guess(self, port):
        P = self.p("pressure")
        hf, hg = _sat_h(min(P, P_CRIT_KPA - 1))
        return (P, hg, 0.0) if port == "vapour" else (P, hf, 0.0)


@register
class Desuperheater(Block):
    TYPE = "desuperheater"
    LABEL = "Desuperheater"
    CATEGORY = "Steam system"
    DESCRIPTION = ("Sprays water into superheated steam to bring it close to saturation. Calculates the spray "
                   "water needed; connect the water inlet to a supply or splitter set to 'As required'.")
    INLETS = [Port("steam", "Steam"), Port("water", "Spray water")]
    OUTLETS = [Port("out", "Outlet")]
    PARAMS = [
        Param("spec", "Target", "choice", "Superheat above saturation",
              choices=("Superheat above saturation", "Outlet temperature")),
        Param("superheat", "Superheat above saturation", "temperature_diff", 5.0, min_value=0.0,
              show_if=("spec", ("Superheat above saturation",))),
        Param("temperature", "Outlet temperature", "temperature", 200.0, show_if=("spec", ("Outlet temperature",))),
    ]

    def _target_h(self, P: float) -> tuple[float, float]:
        ts = T_sat(P)
        if self.p("spec") == "Outlet temperature":
            T = self.p("temperature")
            if T < ts - 1e-6:
                raise ValueError(f"Target temperature {fmt(T)} °C is below saturation ({fmt(ts)} °C).")
        else:
            T = ts + max(self.p("superheat"), 0.0)
        if T <= ts + 1e-6:
            return state_Px(P, 1.0).h, ts
        return state_PT(P, T).h, T

    def _required(self, steam, water, demand):
        """(steam flow, water flow) needed to hit the target."""
        P = steam.P
        ht, _ = self._target_h(P)
        hs, hw = steam.h, water.h
        if hw >= ht:
            raise ValueError("The spray water is hotter than the target outlet condition.")
        if hs <= ht:
            return (demand if demand is not None else steam.m), 0.0
        if demand is not None:
            mw = demand * (hs - ht) / (hs - hw)
            return demand - mw, mw
        return steam.m, steam.m * (hs - ht) / (ht - hw)

    def update_demands(self):
        steam, water, out = self.s_in("steam"), self.s_in("water"), self.s_out("out")
        if not (steam.known and water.known):
            return
        try:
            ms, mw = self._required(steam, water, out.demand)
        except ValueError:
            return
        if out.demand is not None:
            steam.demand = ms
        water.demand = mw

    def calculate(self):
        steam, water, out = self.s_in("steam"), self.s_in("water"), self.s_out("out")
        P = steam.P
        ht, Tt = self._target_h(P)
        if water.P < P - 1e-3:
            self.warn("Spray water pressure is below the steam pressure; it could not be injected.")
        ms_req, mw_req = self._required(steam, water, out.demand)
        m = steam.m + water.m
        h = (steam.m * steam.h + water.m * water.h) / m if m > 1e-12 else steam.h
        out.set(m, P, h)
        st = out.state
        if steam.h <= ht:
            self.warn("The steam is already at or below the target condition; no spray water is needed.")
        self.result("spray", "Spray water", water.m, "mass_flow")
        self.result("T_out", "Outlet temperature", st.T, "temperature")
        self.result("condition", "Outlet condition", st.describe(), "text")
        self.step("Spray water required",
                  text=(f"Target: {fmt(Tt)} °C at {fmt(P)} kPa(a) (h_target = {fmt(ht, 5)} kJ/kg). An energy balance "
                        "on the mixing gives the water needed per kg of steam."),
                  equation=r"\dot m_w = \dot m_s\,\frac{h_s - h_{target}}{h_{target} - h_w}",
                  substitution=rf"\dot m_w = {num(steam.m, 5)} \times \frac{{{num(steam.h, 6)} - {num(ht, 6)}}}{{{num(ht, 6)} - {num(water.h, 6)}}}",
                  result=rf"\dot m_w = {num(steam.m * max(steam.h - ht, 0) / (ht - water.h), 5)}{unit('kg/s')}")
        self.step("Outlet",
                  equation=r"h_{out} = \frac{\dot m_s h_s + \dot m_w h_w}{\dot m_s + \dot m_w}",
                  result=rf"h_{{out}} = {_kj(h)}, \quad T_{{out}} = {num(st.T, 4)}{unit('°C')} \quad {tex_text('(' + st.describe() + ')')}")
        if self._ctx.final and abs(water.m - mw_req) > 1e-4 * max(1.0, mw_req):
            self.warn(f"Spray water supplied ({fmt(water.m)} kg/s) differs from the amount needed "
                      f"({fmt(mw_req)} kg/s). Set the water supply to 'As required'.")

    def initial_guess(self, port):
        steam = self.s_in("steam")
        if steam.known:
            return steam.P, self._target_h(steam.P)[0], steam.m
        return None


@register
class Deaerator(Block):
    TYPE = "deaerator"
    LABEL = "Deaerator / open feedwater heater"
    CATEGORY = "Steam system"
    DESCRIPTION = ("Mixes water inlets with heating steam to produce saturated water at the deaerator pressure. "
                   "Calculates the heating steam needed, and the make-up water if a make-up inlet is chosen.")
    INLETS = [Port("steam", "Heating steam"), Port("water", "Water inlets", multiple=True)]
    OUTLETS = [Port("out", "Deaerated water"), Port("vent", "Vent", optional=True)]
    PARAMS = [
        Param("pressure", "Operating pressure", "pressure", 131.325),
        Param("vent", "Vent rate (% of outlet flow)", "percent", 0.0, min_value=0.0, max_value=10.0,
              help="Steam vented with the non-condensable gases. Typically about 0.1 %."),
        Param("makeup_inlet", "Make-up water inlet", "inlet_choice", "", inlet_port="water",
              help="This inlet supplies whatever water is needed to meet the feedwater demand. "
                   "Leave blank if all water inlets are fixed."),
    ]

    def _balance(self):
        P = self.p("pressure")
        hf, hg = _sat_h(P)
        return P, hf, hg, self.p("vent") / 100.0

    def update_demands(self):
        steam = self.s_in("steam")
        waters = self.s_ins("water")
        out = self.s_out("out")
        if not steam.known or not all(w.known for w in waters):
            return
        P, hf, hg, r = self._balance()
        hs = steam.h
        mk_name = self.p("makeup_inlet")
        mk = next((w for w in waters if w.name == mk_name), None)
        D = out.demand
        if mk is not None and D is not None:
            others = [w for w in waters if w is not mk]
            M_o = sum(w.m for w in others)
            H_o = sum(w.m * w.h for w in others)
            denom = hs - mk.h
            if abs(denom) < 1e-9:
                return
            ms = (D * (hf + r * hg) - (D * (1 + r) - M_o) * mk.h - H_o) / denom
            ms = max(ms, 0.0)
            mb = D * (1 + r) - M_o - ms
            steam.demand = ms
            mk.demand = max(mb, 0.0)
        else:
            M_w = sum(w.m for w in waters)
            H_w = sum(w.m * w.h for w in waters)
            a = (hf + r * hg) / (1 + r)
            if abs(hs - a) < 1e-9:
                return
            steam.demand = max((M_w * a - H_w) / (hs - a), 0.0)

    def calculate(self):
        steam = self.s_in("steam")
        waters = self.s_ins("water")
        out, vent = self.s_out("out"), self.s_out("vent")
        P, hf, hg, r = self._balance()
        if r > 0 and vent is None:
            raise ValueError("The vent rate is above zero: connect a vent outlet stream (or set the vent rate to 0).")
        for s in [steam] + waters:
            if s.P < P - 1e-3:
                self.warn(f"Inlet '{s.name}' ({fmt(s.P)} kPa(a)) is below the deaerator pressure and could not flow in.")
        M_in = steam.m + sum(w.m for w in waters)
        H_in = steam.m * steam.h + sum(w.m * w.h for w in waters)
        m_out = M_in / (1 + r)
        m_v = r * m_out
        h_out = (H_in - m_v * hg) / m_out if m_out > 1e-12 else hf
        out.set(m_out, P, h_out)
        if vent is not None:
            vent.set(m_v, P, hg)
        st = out.state
        mk_name = self.p("makeup_inlet")
        self.result("steam", "Heating steam", steam.m, "mass_flow")
        if mk_name:
            mk = self._ctx.streams.get(mk_name)
            if mk is not None:
                self.result("makeup", f"Make-up water ({mk_name})", mk.m, "mass_flow")
        self.result("out", "Feedwater flow", m_out, "mass_flow")
        if vent is not None:
            self.result("vent", "Vent flow", m_v, "mass_flow")
        self.result("T_out", "Outlet temperature", st.T, "temperature")
        rows = [["Stream", "Role", "Flow (kg/s)", "h (kJ/kg)"]]
        rows.append([steam.name, "heating steam", fmt(steam.m, 5), fmt(steam.h, 5)])
        rows += [[w.name, "water" + (" (make-up)" if w.name == mk_name else ""), fmt(w.m, 5), fmt(w.h, 5)] for w in waters]
        self.step("Mass and energy balance",
                  text=(f"The outlet is saturated water at {fmt(P)} kPa(a) (T = {fmt(T_sat(P))} °C, h_f = {fmt(hf, 5)} "
                        f"kJ/kg). The vent is saturated steam (h_g = {fmt(hg, 5)} kJ/kg) at {fmt(r * 100, 3)} % of "
                        "the outlet flow. The heating steam (and make-up water, if chosen) are found from"),
                  equation=(r"\dot m_s + \sum \dot m_w = \dot m_{out}(1 + r), \qquad "
                            r"\dot m_s h_s + \sum \dot m_w h_w = \dot m_{out}(h_f + r\,h_g)"),
                  result=(rf"\dot m_s = {num(steam.m, 5)}{unit('kg/s')}, \quad \dot m_{{out}} = {num(m_out, 5)}"
                          rf"{unit('kg/s')}, \quad T_{{out}} = {num(st.T, 4)}{unit('°C')}"),
                  table=rows)
        if self._ctx.final:
            if h_out > hf + 0.5:
                self.warn("The water inlets are hotter than saturation at the deaerator pressure: "
                          "no heating steam is needed and some water flashes. Raise the deaerator pressure or vent the flash steam.")
            elif h_out < hf - 0.5:
                self.warn("Not enough heating steam reaches the deaerator: the outlet is below saturation. "
                          "Set the steam supply to 'As required' (e.g. a header's balancing supply or an 'As required' "
                          "splitter outlet).")

    def initial_guess(self, port):
        P, hf, hg, _ = self._balance()
        if port == "vent":
            return P, hg, 0.0
        out = self.s_out("out")
        return P, hf, out.demand or 0.0


@register
class SteamUser(Block):
    TYPE = "steam_user"
    LABEL = "Process steam user"
    CATEGORY = "Steam system"
    DESCRIPTION = ("A process that uses steam for heating and returns condensate. Specify the steam flow or the "
                   "heat duty, and how much condensate is returned.")
    INLETS = [Port("in", "Steam")]
    OUTLETS = [Port("condensate", "Condensate return"), Port("loss", "Condensate not returned", optional=True)]
    PARAMS = [
        Param("spec", "Specify", "choice", "Steam flow", choices=("Steam flow", "Heat duty")),
        Param("flow", "Steam flow", "mass_flow", 1.0, min_value=0.0, show_if=("spec", ("Steam flow",))),
        Param("duty", "Heat duty", "power", 1000.0, min_value=0.0, show_if=("spec", ("Heat duty",))),
        Param("return_percent", "Condensate returned", "percent", 100.0, min_value=0.0, max_value=100.0),
        Param("subcooling", "Condensate subcooling", "temperature_diff", 0.0, min_value=0.0),
    ]

    def _h_cond(self, P: float) -> float:
        sub = self.p("subcooling")
        if sub > 0:
            return state_PT(P, T_sat(P) - sub).h
        return state_Px(P, 0.0).h

    def update_demands(self):
        steam = self.s_in("in")
        if self.p("spec") == "Steam flow":
            steam.demand = self.p("flow")
        elif steam.known:
            dh = steam.h - self._h_cond(steam.P)
            if dh > 1e-6:
                steam.demand = self.p("duty") / dh
        else:
            steam.demand = self.p("duty") / 2100.0  # rough latent heat for a first estimate

    def calculate(self):
        steam = self.s_in("in")
        cond, loss = self.s_out("condensate"), self.s_out("loss")
        P = steam.P
        if P >= P_CRIT_KPA:
            raise ValueError("Steam above the critical pressure cannot be condensed in a process user.")
        hc = self._h_cond(P)
        ret = self.p("return_percent") / 100.0
        if ret < 1.0 and loss is None:
            raise ValueError("Some condensate is not returned: connect the 'Condensate not returned' outlet, "
                             "or set the return to 100 %.")
        st = steam.state
        if st.is_liquid_like:
            self.warn("The inlet is water, not steam.")
        Q = steam.m * (steam.h - hc)
        cond.set(steam.m * ret, P, hc)
        if loss is not None:
            loss.set(steam.m * (1 - ret), P, hc)
        self.heat_in = -Q
        self.result("steam", "Steam used", steam.m, "mass_flow")
        self.result("duty", "Heat delivered to process", Q, "power")
        self.result("returned", "Condensate returned", steam.m * ret, "mass_flow")
        self.result("T_cond", "Condensate temperature", state_Ph(P, hc).T, "temperature")
        if self.p("spec") == "Heat duty":
            self.step("Steam needed",
                      text=(f"The steam condenses at {fmt(P)} kPa(a) and leaves as condensate (h_c = {fmt(hc, 5)} kJ/kg)."),
                      equation=r"\dot m_s = \frac{Q}{h_s - h_c}",
                      substitution=rf"\dot m_s = \frac{{{num(self.p('duty'), 5)}}}{{{num(steam.h, 6)} - {num(hc, 6)}}}",
                      result=rf"\dot m_s = {num(self.p('duty') / (steam.h - hc), 5)}{unit('kg/s')}")
        else:
            self.step("Heat delivered",
                      text=(f"The steam condenses at {fmt(P)} kPa(a) and leaves as condensate (h_c = {fmt(hc, 5)} kJ/kg)."),
                      equation=r"Q = \dot m_s\,(h_s - h_c)",
                      substitution=rf"Q = {num(steam.m, 5)} \times ({num(steam.h, 6)} - {num(hc, 6)})",
                      result=rf"Q = {num(Q, 5)}{unit('kW')}")
        if ret < 1.0:
            self.step("Condensate return",
                      equation=r"\dot m_{return} = r\,\dot m_s",
                      substitution=rf"\dot m_{{return}} = {num(ret, 4)} \times {num(steam.m, 5)}",
                      result=rf"\dot m_{{return}} = {num(steam.m * ret, 5)}{unit('kg/s')}")
