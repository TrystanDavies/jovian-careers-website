import streamlit as st

st.title("♨️ Steam Suite")
st.markdown(
    "Engineering tools for **water and steam systems**: model a steam system, size its pressure relief "
    "valves, and look up steam properties. Every calculation is shown step by step, with the equations, "
    "the numbers substituted, and the references used."
)

c1, c2, c3 = st.columns(3)
with c1.container(border=True):
    st.markdown("#### :material/account_tree: Steam system simulator")
    st.markdown(
        "Build a system from boilers, headers, turbines, pressure-reducing valves, desuperheaters, flash "
        "vessels, deaerators, pumps and process users. The simulator balances mass and energy, and works out "
        "steam generation, make-up water and power."
    )
    st.page_link("views/simulator.py", label="Open the simulator", icon=":material/arrow_forward:")
with c2.container(border=True):
    st.markdown("#### :material/valve: Relief valve sizing")
    st.markdown(
        "Size pressure relief valves for saturated, superheated and wet steam, and for hot water (including "
        "water that flashes). Uses API 520 methods and selects an API 526 orifice, with a printable report."
    )
    st.page_link("views/relief.py", label="Size a relief valve", icon=":material/arrow_forward:")
with c3.container(border=True):
    st.markdown("#### :material/table_chart: Steam tables")
    st.markdown(
        "Look up the properties of water and steam from any two known values (pressure, temperature, dryness, "
        "enthalpy or entropy), with the state shown on a temperature–entropy chart."
    )
    st.page_link("views/properties.py", label="Open steam tables", icon=":material/arrow_forward:")

st.markdown("### Getting started")
st.markdown(
    "1. Choose your units in the sidebar (bar g / °C / t/h by default).\n"
    "2. Open the **simulator** and load the *Industrial steam system* example to see a complete plant, or "
    "start from an empty flowsheet.\n"
    "3. Pick any stream and send it to **relief valve sizing** to size a valve for it.\n"
    "4. Download the calculation report (HTML or Markdown) for review or your records."
)

with st.expander("What's behind the calculations"):
    st.markdown(
        "- **Properties:** IAPWS-IF97, the international standard for industrial steam calculations "
        "(0–800 °C up to 100 MPa).\n"
        "- **Simulator:** steady-state mass and energy balances for each piece of equipment. Recycle loops and "
        "'as required' flows are solved iteratively until everything balances.\n"
        "- **Relief sizing:** API 520 Part I steam and liquid equations, and direct integration of isentropic "
        "nozzle flow for wet steam and flashing water. API 526 orifice letters.\n"
        "- **Checked against** the IAPWS-IF97 verification values, textbook Rankine cycle examples, and hand "
        "calculations with the API 520 equations (see `docs/VALIDATION.md`)."
    )
st.warning(
    "These are preliminary engineering calculations. Results used for design, and especially for pressure "
    "relief, must be checked by a qualified engineer against the codes that apply to your equipment.",
    icon=":material/engineering:",
)
