import altair as alt
import pandas as pd
import streamlit as st

import ui
from steamsuite.relief import (
    API526_ORIFICES,
    DEFAULT_KD,
    FLUIDS,
    IN2_TO_MM2,
    OVERPRESSURE_BASES,
    VALVE_TYPES,
    ReliefInput,
    size_relief_valve,
)
from steamsuite.units import AREA_FACTORS, fmt, pressure_diff_from_kpa, pressure_diff_to_kpa
from steamsuite.water import WaterPropertyError

u = ui.units()
pg = u.p_gauge  # set and back pressures are always gauge

# values sent from the simulator ("Size a relief valve for this stream")
prefill = st.session_state.pop("relief_prefill", None)
if prefill:
    st.session_state["rv_fluid"] = FLUIDS[prefill["fluid"]]
    st.session_state[f"rv_flow_{u.mass_flow}"] = u.m_out(prefill["flow_kg_s"])
    st.session_state[f"rv_set_{pg}"] = pressure_diff_from_kpa(prefill["set_kpag"], pg)
    if prefill.get("temperature_c") is not None:
        st.session_state[f"rv_temp_{u.temperature}"] = u.t_out(prefill["temperature_c"])
    if prefill.get("dryness") is not None:
        st.session_state["rv_dry"] = prefill["dryness"]
    st.session_state["rv_service"] = prefill.get("service", "")
    st.session_state["rv_prefill_note"] = prefill["note"]

st.title(":material/valve: Relief valve sizing")
st.caption("Preliminary sizing to API 520 Part I, with API 526 standard orifices. Every step of the calculation "
           "is shown under the result.")

note = st.session_state.get("rv_prefill_note")
if note:
    st.info(note, icon=":material/info:")

left, right = st.columns([1, 1.35], gap="large")

with left:
    st.subheader("1 · What is being relieved?")
    fluid_label = st.radio("Fluid at the valve inlet", list(FLUIDS.values()), key="rv_fluid", horizontal=True)
    fluid = next(k for k, v in FLUIDS.items() if v == fluid_label)
    c1, c2 = st.columns(2)
    tag = c1.text_input("Valve tag (optional)", key="rv_tag", placeholder="e.g. PSV-101")
    service = c2.text_input("Service / scenario (optional)", key="rv_service", placeholder="e.g. boiler outlet")
    temperature = dryness = None
    if fluid == "superheated_steam":
        st.session_state.setdefault(f"rv_temp_{u.temperature}", u.t_out(300.0))
        temperature = st.number_input(f"Relieving temperature [{u.temperature}]", format="%.2f",
                                      key=f"rv_temp_{u.temperature}",
                                      help="Steam temperature at the valve inlet while relieving.")
    elif fluid == "water":
        st.session_state.setdefault(f"rv_temp_{u.temperature}", u.t_out(60.0))
        temperature = st.number_input(f"Water temperature [{u.temperature}]", format="%.2f",
                                      key=f"rv_temp_{u.temperature}",
                                      help="If the water is hot enough to flash to steam as it relieves, the "
                                           "calculation switches to two-phase flow automatically.")
    elif fluid == "wet_steam":
        st.session_state.setdefault("rv_dry", 0.95)
        dryness = st.number_input("Dryness fraction (0 = water, 1 = dry steam)", min_value=0.01, max_value=0.99,
                                  step=0.01, key="rv_dry")

    st.subheader("2 · Required relieving rate")
    st.session_state.setdefault(f"rv_flow_{u.mass_flow}", u.m_out(10000 / 3600))
    flow = st.number_input(f"Relieving rate [{u.mass_flow}]", min_value=0.0,
                           format="%.4f", key=f"rv_flow_{u.mass_flow}",
                           help="The flow the valve must pass in the governing overpressure scenario (for example "
                                "the boiler's maximum steaming rate, or the flow through a failed-open control "
                                "valve). Determine it per API 521.")

    st.subheader("3 · Pressures")
    c1, c2 = st.columns(2)
    st.session_state.setdefault(f"rv_set_{pg}", pressure_diff_from_kpa(1000.0, pg))
    set_p = c1.number_input(f"Set pressure [{pg}]", min_value=0.0,
                            format="%.3f", key=f"rv_set_{pg}",
                            help="Pressure at which the valve starts to open. Usually the equipment's maximum "
                                 "allowable working pressure (MAWP) or lower.")
    back_p = c2.number_input(f"Total back pressure [{pg}]", value=0.0, format="%.3f", key=f"rv_back_{pg}",
                             help="Pressure at the valve outlet while relieving (superimposed + built-up). "
                                  "0 for discharge straight to atmosphere.")
    op_labels = {b.label: k for k, b in OVERPRESSURE_BASES.items()}
    op_label = st.selectbox("Allowed overpressure", list(op_labels), key="rv_op",
                            help="How far above the set pressure the pressure may rise while the valve passes "
                                 "the required flow.")
    op_key = op_labels[op_label]
    custom_pct = None
    if op_key == "custom":
        custom_pct = st.number_input("Overpressure [% of set pressure]", min_value=0.1, max_value=100.0, value=10.0,
                                     key="rv_custom_op")
    else:
        st.caption(OVERPRESSURE_BASES[op_key].rule)

    st.subheader("4 · Valve")
    valve_labels = {v: k for k, v in VALVE_TYPES.items()}
    valve_label = st.radio("Valve type", list(valve_labels), horizontal=True, key="rv_valve")
    valve_type = valve_labels[valve_label]
    rupture = st.checkbox("Rupture disk installed upstream of the valve", key="rv_rd")

    kd = kb = kw = ksh = kc = None
    with st.expander("Advanced: correction factors"):
        st.caption("Leave these unchanged for preliminary sizing. The defaults are the API 520 values.")
        if st.checkbox("Use my own effective discharge coefficient Kd", key="rv_kd_on",
                       help=f"Defaults: {DEFAULT_KD['vapour']} for steam, {DEFAULT_KD['liquid']} for liquid, "
                            f"{DEFAULT_KD['two-phase']} for two-phase flow."):
            kd = st.number_input("Kd", min_value=0.1, max_value=1.0, value=0.975 if fluid != "water" else 0.65,
                                 step=0.005, format="%.3f", key="rv_kd")
        if valve_type == "balanced":
            kb = st.number_input("Back pressure correction Kb (from the manufacturer's curve)", min_value=0.05,
                                 max_value=1.0, value=1.0, step=0.01, key="rv_kb")
            if fluid == "water":
                kw = st.number_input("Liquid back pressure correction Kw (from the manufacturer's curve)",
                                     min_value=0.05, max_value=1.0, value=1.0, step=0.01, key="rv_kw")
        if fluid == "superheated_steam" and st.checkbox("Enter the superheat correction factor KSH from a code table",
                                                        key="rv_ksh_on",
                                                        help="By default KSH is estimated from nozzle-flow theory."):
            ksh = st.number_input("KSH", min_value=0.5, max_value=1.0, value=0.9, step=0.001, format="%.3f",
                                  key="rv_ksh")
        if rupture:
            kc = st.number_input("Combination factor Kc (0.9 unless a certified value is available)",
                                 min_value=0.5, max_value=1.0, value=0.9, step=0.01, key="rv_kc")

inp = ReliefInput(
    fluid=fluid,
    flow_kg_h=u.m_in(flow) * 3600.0,
    set_pressure_kpag=pressure_diff_to_kpa(set_p, pg),
    overpressure_basis=op_key,
    custom_overpressure_percent=custom_pct,
    temperature_c=u.t_in(temperature) if temperature is not None else None,
    dryness=dryness,
    back_pressure_kpag=pressure_diff_to_kpa(back_p, pg),
    valve_type=valve_type,
    kd=kd, kb=kb, kw=kw, ksh=ksh, kc=kc,
    rupture_disk=rupture,
    p_atm_kpa=u.p_atm,
    tag=tag,
    service=service,
)


@st.cache_data(show_spinner="Sizing…")
def run(inp: ReliefInput):
    return size_relief_valve(inp)


with right:
    try:
        res = run(inp)
    except (ValueError, WaterPropertyError) as exc:
        st.error(str(exc), icon=":material/error:")
        st.stop()

    def area(mm2: float) -> str:
        return f"{fmt(mm2 / AREA_FACTORS[u.area], 4)} {u.area}"

    st.subheader("Result")
    m1, m2, m3 = st.columns(3)
    m1.metric("Required effective area", area(res.required_area_mm2))
    if res.valves_needed == 1:
        m2.metric("API 526 orifice", res.orifice, help=f"Effective area {area(res.orifice_area_mm2)}")
        m3.metric("Rated capacity", f"{fmt(u.m_out(res.rated_capacity_kg_h / 3600), 4)} {u.mass_flow}",
                  help="Capacity of the selected orifice at the same relieving conditions.")
    else:
        m2.metric("API 526 orifice", f"{res.valves_needed} × T")
        m3.metric("Valves needed", res.valves_needed)
    st.markdown(
        f"**{res.relieving_state.describe(u.temperature)}** at a relieving pressure of "
        f"**{fmt(u.p_out(res.relieving_pressure_kpa, pg), 4)} {pg}** · {res.flow_regime} · "
        f"Method: {res.governing_method}"
    )
    for w in res.warnings:
        st.warning(w, icon=":material/warning:")

    tab_calc, tab_orifice, tab_flow, tab_dl = st.tabs(
        ["Calculation steps", "Orifice table", "Nozzle flow", "Download report"])
    with tab_calc:
        st.caption("The calculation is shown in SI units: kPa, kg/h and mm², as in the SI form of the API 520 "
                   "equations.")
        ui.render_report(res.report)
    with tab_orifice:
        rows = []
        for letter, a_in2 in API526_ORIFICES:
            a_mm2 = a_in2 * IN2_TO_MM2
            cap = u.m_out(inp.flow_kg_h / 3600 * a_mm2 / res.required_area_mm2)
            rows.append({"Orifice": letter, f"Effective area [{u.area}]": round(a_mm2 / AREA_FACTORS[u.area], 4),
                         f"Capacity at these conditions [{u.mass_flow}]": round(cap, 4),
                         "": "◀ selected" if letter == res.orifice else ""})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Capacities assume the same coefficients as the sizing calculation. Final selection must use the "
                   "manufacturer's actual orifice area and certified coefficient.")
    with tab_flow:
        noz = res.nozzle
        if noz is not None and noz.curve:
            df = pd.DataFrame(noz.curve, columns=["P", "G"])
            df["Pressure"] = df["P"].map(lambda p: u.p_out(p, u.p_abs))
            line = alt.Chart(df).mark_line().encode(
                x=alt.X("Pressure:Q", title=f"Pressure in the nozzle [{u.p_abs}]", scale=alt.Scale(reverse=True)),
                y=alt.Y("G:Q", title="Mass flux G [kg/(s·m²)]"),
            )
            pt = alt.Chart(pd.DataFrame([{"Pressure": u.p_out(noz.throat_pressure, u.p_abs), "G": noz.mass_flux}])).mark_point(
                size=120, filled=True, color="#d9534f").encode(x="Pressure:Q", y="G:Q")
            st.altair_chart((line + pt).properties(height=320), use_container_width=True)
            st.caption("Ideal mass flux as the fluid expands isentropically from the relieving pressure (left) "
                       "towards the back pressure (right). The red point is the throat condition used for sizing: "
                       "the maximum (choked) flux, or the flux at the back pressure if the flow is not choked.")
        else:
            st.info("No nozzle flow curve for this case.")
    with tab_dl:
        st.markdown("Download the full calculation report for checking, approval or your records. The HTML file "
                    "opens in any browser and prints cleanly.")
        ui.download_buttons(res.report, f"relief-sizing-{tag or 'valve'}", "rv")
