"""Shared user-interface helpers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from steamsuite.report import CalcReport, Step
from steamsuite.units import (
    AREA_FACTORS,
    DENSITY_FACTORS,
    ENTHALPY_FACTORS,
    ENTROPY_FACTORS,
    MASS_FLOW_FACTORS,
    P_ATM_KPA,
    POWER_FACTORS,
    PRESSURE_UNITS,
    TEMPERATURE_UNITS,
    UNIT_PRESETS,
    UnitSystem,
    fmt,
)

CUSTOM = "Custom"


def unit_sidebar() -> None:
    """Unit settings in the sidebar, shared by every page."""
    with st.sidebar:
        st.markdown("### Units")
        preset = st.selectbox("Unit system", list(UNIT_PRESETS) + [CUSTOM], key="unit_preset",
                              help="Units used for input and display. Calculation reports are always in SI units.")
        if preset == CUSTOM:
            base = UnitSystem()
            u = UnitSystem(
                pressure=st.selectbox("Pressure", PRESSURE_UNITS, index=PRESSURE_UNITS.index(base.pressure), key="u_p"),
                temperature=st.selectbox("Temperature", TEMPERATURE_UNITS, key="u_t"),
                mass_flow=st.selectbox("Mass flow", list(MASS_FLOW_FACTORS), key="u_m"),
                power=st.selectbox("Power / heat", list(POWER_FACTORS), key="u_q"),
                enthalpy=st.selectbox("Enthalpy", list(ENTHALPY_FACTORS), key="u_h"),
                entropy=st.selectbox("Entropy", list(ENTROPY_FACTORS), key="u_s"),
                density=st.selectbox("Density", list(DENSITY_FACTORS), key="u_rho"),
                area=st.selectbox("Area", list(AREA_FACTORS), key="u_a"),
            )
        else:
            p = UNIT_PRESETS[preset]
            u = UnitSystem(**{k: getattr(p, k) for k in p.__dataclass_fields__})
        with st.expander("Atmospheric pressure"):
            u.p_atm = st.number_input("Atmospheric pressure [kPa(a)]", min_value=50.0, max_value=110.0,
                                      value=P_ATM_KPA, step=0.1, key="u_patm",
                                      help="Used to convert between gauge and absolute pressure. Lower it for sites at altitude.")
        st.session_state["units"] = u


def units() -> UnitSystem:
    return st.session_state.get("units") or UnitSystem()


def render_steps(steps: list[Step], start: int = 1) -> None:
    for i, s in enumerate(steps, start):
        with st.container(border=True):
            st.markdown(f"**Step {i}: {s.title}**")
            if s.text:
                st.markdown(s.text)
            for eq in (s.equation, s.substitution, s.result):
                if eq:
                    st.latex(eq)
            if s.table:
                st.dataframe(pd.DataFrame(s.table[1:], columns=s.table[0]), hide_index=True,
                             use_container_width=True)
            if s.reference:
                st.caption(f"Reference: {s.reference}")


def render_report(rep: CalcReport, show_inputs: bool = True) -> None:
    if rep.disclaimer:
        st.info(rep.disclaimer, icon=":material/info:")
    if show_inputs and rep.inputs:
        with st.expander("Inputs used", expanded=False):
            st.dataframe(pd.DataFrame(rep.inputs, columns=["Input", "Value"]), hide_index=True,
                         use_container_width=True)
    render_steps(rep.steps)
    if rep.assumptions:
        st.markdown("**Assumptions and limitations**")
        st.markdown("\n".join(f"- {a}" for a in rep.assumptions))
    if rep.references:
        st.markdown("**References**")
        st.markdown("\n".join(f"{i}. {r}" for i, r in enumerate(rep.references, 1)))


def download_buttons(rep: CalcReport, basename: str, key: str) -> None:
    c1, c2 = st.columns(2)
    c1.download_button("Download report (HTML, printable)", rep.to_html(), file_name=f"{basename}.html",
                       mime="text/html", key=f"{key}_html", use_container_width=True, icon=":material/download:")
    c2.download_button("Download report (Markdown)", rep.to_markdown(), file_name=f"{basename}.md",
                       mime="text/markdown", key=f"{key}_md", use_container_width=True, icon=":material/description:")


def show_value(value: float | None, kind: str, u: UnitSystem, sig: int = 4) -> str:
    """Format an internal value for display in the user's units."""
    if value is None:
        return "—"
    if kind == "pressure":
        return f"{fmt(u.p_out(value), sig)} {u.pressure}"
    if kind == "pressure_diff":
        return f"{fmt(u.dp_out(value), sig)} {u.dp_label}"
    if kind == "temperature":
        return f"{fmt(u.t_out(value), sig)} {u.temperature}"
    if kind == "temperature_diff":
        return f"{fmt(u.dt_out(value), sig)} {u.temperature}"
    if kind == "mass_flow":
        return f"{fmt(u.m_out(value), sig)} {u.mass_flow}"
    if kind == "power":
        return f"{fmt(u.q_out(value), sig)} {u.power}"
    if kind == "percent":
        return f"{fmt(value, sig)} %"
    if kind == "enthalpy":
        return f"{fmt(u.h_out(value), sig)} {u.enthalpy}"
    if kind == "text":
        return str(value)
    return fmt(value, sig)
