import json
import math

import pandas as pd
import streamlit as st

import ui
from steamsuite.examples import EXAMPLES
from steamsuite.flowsheet import BLOCK_TYPES, FLOW_MODES, Flowsheet
from steamsuite.units import fmt
from steamsuite.water import WaterPropertyError

u = ui.units()

# --- state ---------------------------------------------------------------------------

if "fs_data" not in st.session_state:
    st.session_state.fs_data = EXAMPLES["Industrial steam system"]().to_dict()
    st.session_state.fs_ver = 0


def set_data(data: dict) -> None:
    st.session_state.fs_data = data
    st.session_state.fs_ver += 1


data = st.session_state.fs_data
ver = st.session_state.fs_ver


@st.cache_data(show_spinner="Solving the steam system…", max_entries=50)
def solve(js: str):
    fs = Flowsheet.from_json(js)
    try:
        fs.solve()
    except (ValueError, WaterPropertyError) as exc:
        return fs, str(exc)
    return fs, None


# --- toolbar ----------------------------------------------------------------------------

st.title(":material/account_tree: Steam system simulator")
with st.container(border=True):
    c1, c2, c3, c4 = st.columns([2.2, 1, 2.2, 1], vertical_alignment="center")
    example = c1.selectbox("Start from an example", list(EXAMPLES), key="fs_example")
    if c2.button("Load", use_container_width=True, icon=":material/upload_file:",
                 help="Replace the current flowsheet with the selected example."):
        set_data(EXAMPLES[example]().to_dict())
        st.rerun()
    upload = c3.file_uploader("Open a saved flowsheet (.json)", type=["json"], key=f"fs_upload_{ver}")
    if upload is not None:
        try:
            loaded = json.loads(upload.getvalue().decode("utf-8"))
            Flowsheet.from_dict(loaded)  # validate
            set_data(loaded)
            st.rerun()
        except (ValueError, KeyError, TypeError) as exc:
            st.error(f"Could not open this file: {exc}")
    c4.download_button("Save", json.dumps(data, indent=2), file_name=f"{data.get('name', 'flowsheet')}.json",
                       mime="application/json", use_container_width=True, icon=":material/save:",
                       help="Download the flowsheet as a .json file you can open again later.")

st.subheader(data.get("name") or "Untitled flowsheet")
if data.get("description"):
    st.caption(data["description"])

fs, structure_error = (None, None)
if data.get("blocks"):
    fs, structure_error = solve(json.dumps(data, sort_keys=True))
res = fs.result if fs is not None else None
solved = res is not None and not res.errors and structure_error is None

# --- status ------------------------------------------------------------------------------

if not data.get("blocks"):
    st.info("The flowsheet is empty. Open the **Edit** tab to add equipment, or load an example.",
            icon=":material/lightbulb:")
elif structure_error:
    st.error(f"The flowsheet can't be solved yet: {structure_error}", icon=":material/error:")
elif res.errors:
    st.error("Some equipment could not be calculated:\n\n" + "\n".join(f"- {e}" for e in res.errors),
             icon=":material/error:")
else:
    bal = res.balance
    msg = (f"Solved in {res.iterations} iterations. Mass balance closes to {abs(bal['mass_error']):.1e} kg/s and "
           f"energy balance to {abs(bal['energy_error']):.1e} kW.")
    (st.success if res.converged else st.warning)(msg, icon=":material/check_circle:" if res.converged else ":material/warning:")
    for w in res.warnings:
        st.warning(w, icon=":material/warning:")

if solved:
    s = fs.summary()
    kpis = [
        ("Steam generated", s["steam_generated"], "mass_flow"),
        ("Fuel energy input", s["fuel"], "power"),
        ("Heat to process", s["process_heat"], "power"),
        ("Power generated", s["turbine_electric"], "power"),
        ("Pump power", s["pump_electric"], "power"),
        ("Water / steam supplied", s["supply_flow"], "mass_flow"),
    ]
    kpis = [k for k in kpis if abs(k[1]) > 1e-9]
    if "cycle_efficiency" in s:
        kpis.append(("Cycle efficiency", s["cycle_efficiency"] * 100, "percent"))
    for start in range(0, len(kpis), 4):
        cols = st.columns(4)
        for col, (label, val, kind) in zip(cols, kpis[start:start + 4]):
            col.metric(label, ui.show_value(val, kind, u, 4))

# a view selector (rather than tabs) so the chosen view survives re-runs after an edit
VIEWS = {
    "Diagram": ":material/schema: Diagram",
    "Streams": ":material/table: Streams",
    "Equipment": ":material/build: Equipment",
    "Edit": ":material/edit: Edit",
    "Report": ":material/description: Report",
}
view = st.segmented_control("View", list(VIEWS), format_func=VIEWS.get, key="fs_view", default="Diagram",
                            label_visibility="collapsed") or "Diagram"
st.divider()

# --- diagram --------------------------------------------------------------------------------

CAT_COLOURS = {
    "Supplies": "#dff3e4",
    "Pressure change": "#e3ebfa",
    "Heat transfer": "#fde6dc",
    "Mixing and splitting": "#eeeeee",
    "Steam system": "#fff1cc",
}


def _q(text: str) -> str:
    """Quote a Graphviz label; literal \\n sequences become line breaks."""
    return '"' + str(text).replace('"', "'") + '"'


def connections(d: dict) -> dict[str, dict]:
    """Stream name -> {'from': block, 'to': block} from the flowsheet data."""
    conns: dict[str, dict] = {}
    for b in d.get("blocks", []):
        for key in ("outlets", "inlets"):
            for v in (b.get(key) or {}).values():
                for n in (v if isinstance(v, list) else [v]):
                    if n:
                        conns.setdefault(n, {})["from" if key == "outlets" else "to"] = b["name"]
    return conns


def diagram(d: dict, fs) -> str:
    lines = [
        "digraph G {",
        'rankdir=TB; bgcolor="white"; nodesep=0.5; ranksep=0.45; pad=0.2; newrank=true;',
        'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#7a8794", margin="0.15,0.08"];',
        'edge [fontname="Helvetica", fontsize=9, color="#6b7785", fontcolor="#33404d", arrowsize=0.7];',
    ]
    for b in d.get("blocks", []):
        cls = BLOCK_TYPES.get(b["type"])
        fill = CAT_COLOURS.get(cls.CATEGORY if cls else "", "#ffffff")
        err = fs is not None and b["name"] in fs.blocks and fs.blocks[b["name"]].error
        shape = "cds" if b["type"] == "feed" else "box"
        extra = ', color="#c0392b", penwidth=2' if err else ""
        kind = cls.LABEL if cls else b["type"]
        first_word = kind.split(" ")[0].lower()
        label = b["name"] if first_word in b["name"].lower() else f"{b['name']}\\n{kind}"
        lines.append(f'{_q(b["name"])} [label={_q(label)}, '
                     f'fillcolor="{fill}", shape={shape}{extra}];')
    for name, c in connections(d).items():
        src, dst = c.get("from"), c.get("to")
        label, colour = name, "#6b7785"
        if fs is not None and solved and name in fs.streams:
            stream = fs.streams[name]
            w = stream.state
            label = (f"{name}\\n{fmt(u.m_out(stream.m), 3)} {u.mass_flow} · {fmt(u.p_out(stream.P), 3)} {u.pressure}"
                     f" · {fmt(u.t_out(w.T), 3)} {u.temperature}")
            colour = ("#c0392b" if w.is_vapour_like else "#8e44ad" if w.phase == "two-phase" else "#2471a3")
        qlabel = _q(label)
        if src is None:
            src_id = _q(f"__in_{name}")
            lines.append(f'{src_id} [label="missing supply", shape=plaintext, fontcolor="#c0392b"];')
        else:
            src_id = _q(src)
        if dst is None:
            dst_id = _q(f"__out_{name}")
            lines.append(f'{dst_id} [label="", shape=point, width=0.08, color="{colour}"];')
        else:
            dst_id = _q(dst)
        lines.append(f'{src_id} -> {dst_id} [label={qlabel}, color="{colour}"];')
    lines.append("}")
    return "\n".join(lines)


if view == "Diagram":
    if data.get("blocks"):
        st.graphviz_chart(diagram(data, fs), use_container_width=True)
        st.caption("Line colours: :red[steam] · :violet[wet steam] · :blue[water]. Streams ending in a dot leave "
                   "the system. Labels show flow, pressure and temperature.")
    else:
        st.info("Nothing to show yet.")

# --- streams -----------------------------------------------------------------------------------

if view == "Streams":
    if solved:
        rows = []
        for st_ in fs.streams.values():
            w = st_.state
            rows.append({
                "Stream": st_.name,
                "From": st_.source[0],
                "To": st_.dest[0] if st_.dest else "— leaves system —",
                f"Flow [{u.mass_flow}]": round(u.m_out(st_.m), 5),
                f"Pressure [{u.pressure}]": round(u.p_out(st_.P), 4),
                f"Temperature [{u.temperature}]": round(u.t_out(w.T), 3),
                "Condition": w.describe(u.temperature),
                f"Enthalpy [{u.enthalpy}]": round(u.h_out(st_.h), 3),
                "Dryness": round(w.x, 4) if w.x is not None else None,
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        st.markdown("##### Size a relief valve for a stream")
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        pick = c1.selectbox("Stream", list(fs.streams), key="fs_relief_stream")
        if c2.button("Open in relief valve sizing", icon=":material/valve:", use_container_width=True):
            stream = fs.streams[pick]
            w = stream.state
            pre = {"flow_kg_s": stream.m, "set_kpag": max(stream.P - u.p_atm, 1.0), "service": pick}
            if w.phase == "supercritical":
                st.error("Relief sizing for supercritical conditions isn't supported from here.")
                st.stop()
            if w.is_vapour_like:
                if w.superheat is not None and w.superheat > 0.5:
                    pre.update(fluid="superheated_steam", temperature_c=w.T)
                else:
                    pre.update(fluid="saturated_steam")
            elif w.phase == "two-phase":
                pre.update(fluid="wet_steam", dryness=min(max(w.x, 0.01), 0.99))
            else:
                pre.update(fluid="water", temperature_c=w.T)
            pre["note"] = (f"Filled in from stream '{pick}'. The set pressure is the stream's operating pressure and "
                           "the relieving rate is its normal flow: change them to the valve's set pressure and the "
                           "rate from the governing relief scenario.")
            st.session_state.relief_prefill = pre
            st.switch_page("views/relief.py")
    else:
        st.info("Stream results appear once the flowsheet solves.")

# --- equipment --------------------------------------------------------------------------------

if view == "Equipment":
    if fs is not None and fs.result is not None:
        st.caption("Open any piece of equipment to see its results and how they were calculated. Calculation "
                   "details are in SI units (kPa(a), °C, kg/s, kJ/kg, kW).")
        for b in fs.blocks.values():
            icon = ":material/error:" if b.error else (":material/warning:" if b.warnings else ":material/check_circle:")
            with st.expander(f"{b.name} — {b.LABEL}", icon=icon):
                if b.error:
                    st.error(b.error)
                for w in b.warnings:
                    st.warning(w)
                if b.results:
                    st.dataframe(pd.DataFrame([{"Result": r.label, "Value": ui.show_value(r.value, r.kind, u, 5)}
                                               for r in b.results.values()]),
                                 hide_index=True, use_container_width=True)
                if b.steps:
                    st.markdown("**How it was calculated**")
                    ui.render_steps(b.steps)
    else:
        st.info("Equipment results appear once the flowsheet solves.")

# --- edit -----------------------------------------------------------------------------------------


def to_ui(value: float, kind: str) -> float:
    return {
        "pressure": u.p_out, "pressure_diff": u.dp_out, "temperature": u.t_out, "temperature_diff": u.dt_out,
        "mass_flow": u.m_out, "power": u.q_out,
    }.get(kind, lambda v: v)(value)


def from_ui(value: float, kind: str) -> float:
    return {
        "pressure": u.p_in, "pressure_diff": u.dp_in, "temperature": u.t_in, "temperature_diff": u.dt_in,
        "mass_flow": u.m_in, "power": u.q_in,
    }.get(kind, lambda v: v)(value)


UNIT_LABEL = {
    "pressure": lambda: u.pressure, "pressure_diff": lambda: u.dp_label, "temperature": lambda: u.temperature,
    "temperature_diff": lambda: u.temperature, "mass_flow": lambda: u.mass_flow, "power": lambda: u.power,
    "percent": lambda: "%",
}


def param_widget(p, value, key: str, inlet_options: list[str]):
    label = p.label + (f" [{UNIT_LABEL[p.kind]()}]" if p.kind in UNIT_LABEL else "")
    help_ = p.help or None
    if p.kind == "choice":
        idx = p.choices.index(value) if value in p.choices else 0
        return st.radio(label, p.choices, index=idx, key=key, horizontal=True, help=help_)
    if p.kind == "inlet_choice":
        opts = [""] + [o for o in inlet_options if o]
        if value and value not in opts:
            opts.append(value)
        return st.selectbox(label, opts, index=opts.index(value) if value in opts else 0, key=key, help=help_,
                            format_func=lambda x: x or "(none)")
    kwargs = {}
    if p.kind in ("percent", "fraction"):
        if p.min_value is not None:
            kwargs["min_value"] = float(p.min_value)
        if p.max_value is not None:
            kwargs["max_value"] = float(p.max_value)
    elif p.min_value is not None and p.kind in ("mass_flow", "power", "pressure_diff", "temperature_diff"):
        kwargs["min_value"] = 0.0
    shown = float(to_ui(float(value), p.kind))
    if "min_value" in kwargs:
        shown = max(shown, kwargs["min_value"])
    if "max_value" in kwargs:
        shown = min(shown, kwargs["max_value"])
    fmt_str = "%.4f" if p.kind in ("fraction", "mass_flow", "pressure") else "%.3f"
    v = st.number_input(label, value=shown, key=key, help=help_, format=fmt_str, **kwargs)
    return from_ui(v, p.kind)


def block_form(cls, bd: dict, prefix: str) -> dict:
    """Widgets for one piece of equipment; returns the edited block data."""
    name = st.text_input("Name", value=bd.get("name", ""), key=f"{prefix}_name")
    inlets, outlets = {}, {}
    params = dict(bd.get("params") or {})
    c_in, c_out = st.columns(2)
    with c_in:
        for port in cls.INLETS:
            cur = (bd.get("inlets") or {}).get(port.key)
            if port.multiple:
                txt = st.text_input(f"{port.label} — stream names, separated by commas", value=", ".join(cur or []),
                                    key=f"{prefix}_in_{port.key}")
                inlets[port.key] = [x.strip() for x in txt.split(",") if x.strip()]
            else:
                inlets[port.key] = st.text_input(
                    f"{port.label} — stream name" + (" (optional)" if port.optional else ""), value=cur or "",
                    key=f"{prefix}_in_{port.key}").strip()
    with c_out:
        for port in cls.OUTLETS:
            cur = (bd.get("outlets") or {}).get(port.key)
            if port.with_specs:
                specs = params.get("outlet_specs") or {}
                rows = []
                for n in cur or []:
                    sp = specs.get(n) or {"mode": "Remainder", "value": 0.0}
                    val = float(sp.get("value") or 0.0)
                    rows.append({"Stream": n, "Flow mode": sp.get("mode", "Remainder"),
                                 "Value": u.m_out(val) if sp.get("mode") == "Flow" else val})
                st.markdown(f"{port.label}")
                edited = st.data_editor(
                    pd.DataFrame(rows, columns=["Stream", "Flow mode", "Value"]), num_rows="dynamic",
                    key=f"{prefix}_out_{port.key}", use_container_width=True, hide_index=True,
                    column_config={
                        "Stream": st.column_config.TextColumn("Stream", required=True),
                        "Flow mode": st.column_config.SelectboxColumn(
                            "Flow mode", options=list(FLOW_MODES), required=True, default="As required",
                            help="Flow: fixed flow · Fraction: % of the total · As required: whatever the "
                                 "connected equipment needs · Remainder: whatever is left (one outlet at most)"),
                        "Value": st.column_config.NumberColumn(
                            f"Value ({u.mass_flow} or %)", default=0.0,
                            help=f"Flow in {u.mass_flow} for 'Flow', percent for 'Fraction'; ignored otherwise."),
                    })
                names, new_specs = [], {}
                for _, r in edited.iterrows():
                    n = str(r["Stream"]).strip() if r["Stream"] is not None and str(r["Stream"]) != "nan" else ""
                    if not n:
                        continue
                    mode = r["Flow mode"] if r["Flow mode"] in FLOW_MODES else "Remainder"
                    val = r["Value"]
                    val = 0.0 if val is None or (isinstance(val, float) and math.isnan(val)) else float(val)
                    names.append(n)
                    new_specs[n] = {"mode": mode, "value": u.m_in(val) if mode == "Flow" else val}
                outlets[port.key] = names
                params["outlet_specs"] = new_specs
            elif port.multiple:
                txt = st.text_input(f"{port.label} — stream names, separated by commas", value=", ".join(cur or []),
                                    key=f"{prefix}_out_{port.key}")
                outlets[port.key] = [x.strip() for x in txt.split(",") if x.strip()]
            else:
                outlets[port.key] = st.text_input(
                    f"{port.label} — stream name" + (" (optional)" if port.optional else ""), value=cur or "",
                    key=f"{prefix}_out_{port.key}").strip()
    if cls.PARAMS:
        st.markdown("**Settings**")
    vals = dict(params)
    grid = st.columns(2)
    shown = 0
    for p in cls.PARAMS:
        if p.show_if is not None:
            ctrl, allowed = p.show_if
            if vals.get(ctrl) not in allowed:
                continue
        opts = []
        if p.kind == "inlet_choice":
            v = inlets.get(p.inlet_port)
            opts = v if isinstance(v, list) else [v]
        with grid[shown % 2]:
            vals[p.key] = param_widget(p, vals.get(p.key, p.default), f"{prefix}_p_{p.key}", opts)
        shown += 1
    return {"type": cls.TYPE, "name": name.strip(), "inlets": inlets, "outlets": outlets, "params": vals}


def check_block(new: dict, others: list[dict]) -> str | None:
    if not new["name"]:
        return "Give the equipment a name."
    if any(o["name"] == new["name"] for o in others):
        return f"There is already equipment called '{new['name']}'."
    try:
        blk = BLOCK_TYPES[new["type"]](new["name"], new["inlets"], new["outlets"], new["params"])
        blk.validate_ports()
    except ValueError as exc:
        return str(exc)
    return None


if view == "Edit":
    st.markdown("Connect equipment by **stream names**: use the same name for one unit's outlet and another unit's "
                "inlet. Outlets that aren't connected to anything leave the system. The flowsheet re-solves "
                "automatically after every change.")
    with st.expander("Flowsheet name and description"):
        nm = st.text_input("Name", value=data.get("name", ""), key=f"fs_name_{ver}")
        ds = st.text_area("Description", value=data.get("description", ""), key=f"fs_desc_{ver}")
        if st.button("Save name and description", key=f"fs_meta_{ver}"):
            set_data({**data, "name": nm, "description": ds})
            st.rerun()

    conns = connections(data)
    open_outlets = [n for n, c in conns.items() if "to" not in c]
    missing = [n for n, c in conns.items() if "from" not in c]
    if missing:
        st.warning("Inlet streams with nothing supplying them: " + ", ".join(f"`{n}`" for n in missing))

    st.markdown("#### Equipment")
    blocks = data.get("blocks", [])
    for i, bd in enumerate(blocks):
        cls = BLOCK_TYPES.get(bd["type"])
        if cls is None:
            st.error(f"Unknown equipment type '{bd['type']}' for '{bd['name']}'.")
            continue
        with st.expander(f"{bd['name']} — {cls.LABEL}"):
            st.caption(cls.DESCRIPTION)
            prefix = f"e{ver}_{i}"
            new = block_form(cls, bd, prefix)
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("Apply changes", key=f"{prefix}_apply", type="primary", icon=":material/check:"):
                err = check_block(new, [b for j, b in enumerate(blocks) if j != i])
                if err:
                    st.error(err)
                else:
                    new_blocks = list(blocks)
                    new_blocks[i] = new
                    set_data({**data, "blocks": new_blocks})
                    st.rerun()
            if b2.button("Delete", key=f"{prefix}_delete", icon=":material/delete:"):
                set_data({**data, "blocks": [b for j, b in enumerate(blocks) if j != i]})
                st.rerun()

    st.markdown("#### Add equipment")
    with st.container(border=True):
        options = {f"{c.LABEL}  ·  {c.CATEGORY}": c for c in BLOCK_TYPES.values()}
        choice = st.selectbox("Type of equipment", list(options), key=f"add_type_{ver}")
        cls = options[choice]
        st.caption(cls.DESCRIPTION)
        if open_outlets:
            st.caption("Unconnected outlet streams you can use as inlets: "
                       + ", ".join(f"`{n}`" for n in open_outlets))
        n = 1
        existing = {b["name"] for b in blocks}
        while f"{cls.LABEL} {n}" in existing:
            n += 1
        default_name = f"{cls.LABEL} {n}"
        default = {"name": default_name, "inlets": {}, "outlets": {}, "params": {}}
        for port in cls.OUTLETS:
            if port.with_specs:
                default["outlets"][port.key] = [f"{default_name} out 1"]
                default["params"]["outlet_specs"] = {f"{default_name} out 1": {"mode": "Remainder", "value": 0.0}}
            elif port.multiple:
                default["outlets"][port.key] = [f"{default_name} {port.label.lower()}"]
            elif not port.optional:
                default["outlets"][port.key] = f"{default_name} {port.label.lower()}"
        default["params"].update({p.key: p.default for p in cls.PARAMS})
        new = block_form(cls, default, f"add{ver}_{cls.TYPE}")
        if st.button("Add to flowsheet", type="primary", icon=":material/add:", key=f"add_btn_{ver}"):
            err = check_block(new, blocks)
            if err:
                st.error(err)
            else:
                set_data({**data, "blocks": blocks + [new]})
                st.rerun()

# --- report ----------------------------------------------------------------------------------------

if view == "Report":
    if solved:
        rep = fs.report()
        st.markdown("A complete record of this calculation: summary, warnings, stream table, and every equipment "
                    "calculation step by step (SI units).")
        ui.download_buttons(rep, f"steam-system-{data.get('name', 'flowsheet')}".replace(" ", "-").lower(), "fsrep")
        st.dataframe(pd.DataFrame(rep.results, columns=["Result", "Value"]), hide_index=True,
                     use_container_width=True)
    else:
        st.info("The report is available once the flowsheet solves.")
