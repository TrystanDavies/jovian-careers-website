import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import ui
from steamsuite.units import ENTHALPY_FACTORS, ENTROPY_FACTORS, convert_to, fmt
from steamsuite.water import (
    T_CRIT_C,
    WaterPropertyError,
    saturation_at_P,
    saturation_at_T,
    state_Ph,
    state_PT,
    state_Ps,
    state_Px,
    state_Tx,
)

u = ui.units()

st.title(":material/table_chart: Steam tables")
st.caption("Properties of water and steam from IAPWS-IF97. Enter any two known values.")

MODES = [
    "Pressure and temperature",
    "Pressure and dryness fraction",
    "Temperature and dryness fraction",
    "Pressure and enthalpy",
    "Pressure and entropy",
    "Saturation table at a pressure",
    "Saturation table at a temperature",
]
mode = st.radio("What do you know?", MODES, horizontal=True, key="prop_mode")


@st.cache_data(show_spinner=False)
def dome() -> pd.DataFrame:
    rows = []
    for T in np.concatenate([np.linspace(0.01, 360, 120), np.linspace(360, T_CRIT_C - 0.01, 30)]):
        l, v = saturation_at_T(float(T))
        rows.append((l.s, T, "Saturated water"))
        rows.append((v.s, T, "Saturated steam"))
    df = pd.DataFrame(rows, columns=["s", "T", "line"])
    liq = df[df.line == "Saturated water"].sort_values("T")
    vap = df[df.line == "Saturated steam"].sort_values("T", ascending=False)
    return pd.concat([liq, vap])


def ts_chart(points: list[tuple[str, object]]) -> alt.Chart:
    d = dome().copy()
    d["s_u"] = d["s"].map(u.s_out)
    d["T_u"] = d["T"].map(u.t_out)
    d["order"] = range(len(d))
    base = alt.Chart(d).mark_line(color="#4a6fa5").encode(
        x=alt.X("s_u:Q", title=f"Specific entropy [{u.entropy}]"),
        y=alt.Y("T_u:Q", title=f"Temperature [{u.temperature}]"),
        order="order:Q",
    )
    pts = pd.DataFrame([{"label": lbl, "s_u": u.s_out(s.s), "T_u": u.t_out(s.T)} for lbl, s in points])
    marks = alt.Chart(pts).mark_point(size=120, filled=True, color="#d9534f").encode(
        x="s_u:Q", y="T_u:Q", tooltip=["label"])
    text = alt.Chart(pts).mark_text(align="left", dx=8, dy=-8).encode(x="s_u:Q", y="T_u:Q", text="label")
    return (base + marks + text).properties(height=380)


def prop_rows(s) -> list[tuple[str, str]]:
    rows = [
        ("Condition", s.describe(u.temperature)),
        ("Pressure", f"{fmt(u.p_out(s.P), 6)} {u.pressure}  ({fmt(s.P, 6)} kPa(a))"),
        ("Temperature", f"{fmt(u.t_out(s.T), 6)} {u.temperature}"),
        ("Specific enthalpy h", f"{fmt(u.h_out(s.h), 6)} {u.enthalpy}"),
        ("Specific entropy s", f"{fmt(u.s_out(s.s), 6)} {u.entropy}"),
        ("Density ρ", f"{fmt(u.rho_out(s.rho), 6)} {u.density}"),
        ("Specific volume v", f"{fmt(1 / u.rho_out(s.rho), 6)} {'m³/kg' if u.density == 'kg/m³' else 'ft³/lb'}"),
    ]
    if s.x is not None:
        rows.append(("Dryness fraction x", fmt(s.x, 6)))
    if s.T_sat is not None:
        rows.append(("Boiling point at this pressure", f"{fmt(u.t_out(s.T_sat), 6)} {u.temperature}"))
    if s.superheat is not None:
        rows.append(("Superheat", f"{fmt(u.dt_out(s.superheat), 4)} {u.temperature}"))
    if s.subcooling is not None:
        rows.append(("Subcooling", f"{fmt(u.dt_out(s.subcooling), 4)} {u.temperature}"))
    if s.cp is not None:
        rows.append(("Specific heat cp", f"{fmt(u.s_out(s.cp), 5)} {u.entropy}"))
    if s.mu is not None:
        rows.append(("Dynamic viscosity μ", f"{fmt(s.mu * 1000, 5)} cP (mPa·s)"))
    if s.k is not None:
        rows.append(("Thermal conductivity k", f"{fmt(s.k, 5)} W/(m·K)"))
    return rows


c1, c2 = st.columns(2)
try:
    if mode == "Pressure and temperature":
        P = c1.number_input(f"Pressure [{u.pressure}]", value=u.p_out(1101.325), format="%.4f", key="pr_p")
        T = c2.number_input(f"Temperature [{u.temperature}]", value=u.t_out(250.0), format="%.3f", key="pr_t")
        state = state_PT(u.p_in(P), u.t_in(T))
    elif mode == "Pressure and dryness fraction":
        P = c1.number_input(f"Pressure [{u.pressure}]", value=u.p_out(1101.325), format="%.4f", key="pr_p2")
        x = c2.number_input("Dryness fraction (0 = water, 1 = dry steam)", 0.0, 1.0, 1.0, 0.01, key="pr_x")
        state = state_Px(u.p_in(P), x)
    elif mode == "Temperature and dryness fraction":
        T = c1.number_input(f"Temperature [{u.temperature}]", value=u.t_out(100.0), format="%.3f", key="pr_t3")
        x = c2.number_input("Dryness fraction (0 = water, 1 = dry steam)", 0.0, 1.0, 1.0, 0.01, key="pr_x3")
        state = state_Tx(u.t_in(T), x)
    elif mode == "Pressure and enthalpy":
        P = c1.number_input(f"Pressure [{u.pressure}]", value=u.p_out(1101.325), format="%.4f", key="pr_p4")
        h = c2.number_input(f"Specific enthalpy [{u.enthalpy}]", value=u.h_out(2000.0), format="%.2f", key="pr_h")
        state = state_Ph(u.p_in(P), convert_to(h, u.enthalpy, ENTHALPY_FACTORS))
    elif mode == "Pressure and entropy":
        P = c1.number_input(f"Pressure [{u.pressure}]", value=u.p_out(1101.325), format="%.4f", key="pr_p5")
        s_in = c2.number_input(f"Specific entropy [{u.entropy}]", value=u.s_out(6.5), format="%.4f", key="pr_s")
        state = state_Ps(u.p_in(P), convert_to(s_in, u.entropy, ENTROPY_FACTORS))
    else:
        state = None
        if mode == "Saturation table at a pressure":
            P = c1.number_input(f"Pressure [{u.pressure}]", value=u.p_out(1101.325), format="%.4f", key="pr_p6")
            liq, vap = saturation_at_P(u.p_in(P))
        else:
            T = c1.number_input(f"Temperature [{u.temperature}]", value=u.t_out(100.0), format="%.3f", key="pr_t7")
            liq, vap = saturation_at_T(u.t_in(T))
        st.success(f"Boiling point: **{fmt(u.t_out(liq.T), 6)} {u.temperature}** at "
                   f"**{fmt(u.p_out(liq.P), 6)} {u.pressure}** ({fmt(liq.P, 6)} kPa(a))")
        table = pd.DataFrame(
            [
                ("Specific enthalpy", f"{fmt(u.h_out(liq.h), 6)}", f"{fmt(u.h_out(vap.h), 6)}",
                 f"{fmt(u.h_out(vap.h - liq.h), 6)}", u.enthalpy),
                ("Specific entropy", f"{fmt(u.s_out(liq.s), 6)}", f"{fmt(u.s_out(vap.s), 6)}",
                 f"{fmt(u.s_out(vap.s - liq.s), 6)}", u.entropy),
                ("Density", f"{fmt(u.rho_out(liq.rho), 6)}", f"{fmt(u.rho_out(vap.rho), 6)}", "", u.density),
                ("Specific heat cp", fmt(u.s_out(liq.cp), 5), fmt(u.s_out(vap.cp), 5), "", u.entropy),
                ("Viscosity", fmt((liq.mu or 0) * 1000, 5), fmt((vap.mu or 0) * 1000, 5), "", "cP"),
            ],
            columns=["Property", "Saturated water", "Saturated steam", "Evaporation (latent)", "Unit"],
        )
        col1, col2 = st.columns([1.1, 1])
        col1.dataframe(table, hide_index=True, use_container_width=True)
        col1.caption("The latent heat of evaporation is the enthalpy difference between saturated steam and water.")
        col2.altair_chart(ts_chart([("Saturated water", liq), ("Saturated steam", vap)]), use_container_width=True)

    if state is not None:
        st.success(f"**{state.describe(u.temperature)}**")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Temperature", f"{fmt(u.t_out(state.T), 5)} {u.temperature}")
        m2.metric("Enthalpy", f"{fmt(u.h_out(state.h), 5)} {u.enthalpy}")
        m3.metric("Density", f"{fmt(u.rho_out(state.rho), 5)} {u.density}")
        m4.metric("Dryness fraction" if state.x is not None else "Entropy",
                  fmt(state.x, 4) if state.x is not None else f"{fmt(u.s_out(state.s), 5)} {u.entropy}")
        col1, col2 = st.columns([1.1, 1])
        rows = prop_rows(state)
        col1.dataframe(pd.DataFrame(rows, columns=["Property", "Value"]), hide_index=True,
                       use_container_width=True, height=35 * (len(rows) + 1) + 3)
        col2.altair_chart(ts_chart([("State", state)]), use_container_width=True)
except WaterPropertyError as exc:
    st.error(str(exc), icon=":material/error:")
