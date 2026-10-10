"""Steam Suite — entry point.

Run from the steam-suite folder with:

    streamlit run app/streamlit_app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

import ui  # noqa: E402

st.set_page_config(page_title="Steam Suite", page_icon="♨️", layout="wide")

pages = [
    st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
    st.Page("views/simulator.py", title="Steam system simulator", icon=":material/account_tree:"),
    st.Page("views/relief.py", title="Relief valve sizing", icon=":material/valve:"),
    st.Page("views/properties.py", title="Steam tables", icon=":material/table_chart:"),
]
nav = st.navigation(pages)
ui.unit_sidebar()
with st.sidebar:
    st.caption("Steam Suite 0.1 · IAPWS-IF97 properties. Results are preliminary engineering calculations; "
               "have them checked by a qualified engineer before use.")
nav.run()
