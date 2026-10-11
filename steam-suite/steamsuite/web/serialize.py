"""Convert library objects to JSON-friendly dictionaries for the web API."""

from __future__ import annotations

import math
from dataclasses import asdict

from ..flowsheet import BLOCK_TYPES, FLOW_MODES, STREAM_PROPERTIES, Flowsheet
from ..flowsheet.core import INLET_MODES
from ..flowsheet.solver import SOLVER_MODES
from ..hydraulics import FITTINGS, PIPE_SIZES, ROUGHNESS, SCHEDULES, TWO_PHASE_METHODS
from ..relief import API526_ORIFICES, FLUIDS, OVERPRESSURE_BASES, VALVE_TYPES, ReliefResult
from ..report import CalcReport, Step
from ..water import BACKEND, WaterState


def clean(v):
    """Replace NaN/inf (not valid JSON) with None, recursively."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def catalog() -> dict:
    blocks = []
    for cls in BLOCK_TYPES.values():
        blocks.append({
            "type": cls.TYPE,
            "label": cls.LABEL,
            "category": cls.CATEGORY,
            "description": cls.DESCRIPTION,
            "inlets": [asdict(p) for p in cls.INLETS],
            "outlets": [asdict(p) for p in cls.OUTLETS],
            "params": [param_dict(p) for p in cls.PARAMS],
        })
    return clean({
        "blocks": blocks,
        "flow_modes": list(FLOW_MODES),
        "inlet_modes": list(INLET_MODES),
        "solver_modes": SOLVER_MODES,
        "two_phase_methods": list(TWO_PHASE_METHODS),
        "stream_properties": {k: v[0] for k, v in STREAM_PROPERTIES.items()},
        "fittings": {k: v[0] for k, v in FITTINGS.items()},
        "pipe_sizes": {k: {"od": v[0], "walls": v[1]} for k, v in PIPE_SIZES.items()},
        "schedules": list(SCHEDULES),
        "roughness": ROUGHNESS,
        "relief": {
            "fluids": FLUIDS,
            "valve_types": VALVE_TYPES,
            "overpressure": {k: {"label": b.label, "percent": b.percent, "rule": b.rule}
                             for k, b in OVERPRESSURE_BASES.items()},
        },
        "orifices": [list(o) for o in API526_ORIFICES],
        "scenarios": scenario_catalog(),
        "property_backend": BACKEND,
    })


def param_dict(p) -> dict:
    return {
        "key": p.key, "label": p.label, "kind": p.kind, "default": p.default, "help": p.help,
        "choices": list(p.choices), "show_if": [p.show_if[0], list(p.show_if[1])] if p.show_if else None,
        "min": p.min_value, "max": p.max_value, "inlet_port": p.inlet_port, "group": p.group,
        "depends_on": p.depends_on,
    }


def scenario_catalog() -> dict:
    from ..scenarios import SCENARIO_TYPES
    return {k: {"label": t.label, "description": t.description, "params": [param_dict(p) for p in t.params],
                "block_param": t.block_param, "block_types": list(t.block_types)}
            for k, t in SCENARIO_TYPES.items()}


def state_dict(st: WaterState) -> dict:
    return clean({
        "P": st.P, "T": st.T, "h": st.h, "s": st.s, "rho": st.rho, "x": st.x, "phase": st.phase,
        "describe": st.describe(), "T_sat": st.T_sat, "superheat": st.superheat, "subcooling": st.subcooling,
        "cp": st.cp, "mu": st.mu, "k": st.k, "w": st.w,
    })


def step_dict(s: Step) -> dict:
    return {"title": s.title, "text": s.text, "equation": s.equation, "substitution": s.substitution,
            "result": s.result, "reference": s.reference, "table": s.table}


def report_dict(rep: CalcReport) -> dict:
    return {
        "title": rep.title, "subtitle": rep.subtitle, "inputs": rep.inputs, "results": rep.results,
        "warnings": rep.warnings, "assumptions": rep.assumptions, "references": rep.references,
        "disclaimer": rep.disclaimer, "steps": [step_dict(s) for s in rep.steps],
    }


def solve_payload(fs: Flowsheet, structure_error: str | None = None) -> dict:
    res = fs.result
    out: dict = {"structure_error": structure_error, "streams": {}, "blocks": {}}
    if res is None:
        out.update({"converged": False, "errors": [structure_error] if structure_error else [], "warnings": []})
        return clean(out)
    out.update({
        "converged": res.converged,
        "iterations": res.iterations,
        "errors": res.errors,
        "warnings": res.warnings,
        "balance": res.balance,
        "summary": fs.summary() if not res.errors else {},
        "solver_mode": fs.solver_mode,
        "network": res.network,
    })
    for name, s in fs.streams.items():
        entry = {"source": list(s.source) if s.source else None, "dest": list(s.dest) if s.dest else None,
                 "m": s.m, "known": s.known}
        if s.known:
            try:
                entry.update(state_dict(s.state))
            except ValueError:
                entry["known"] = False
        out["streams"][name] = entry
    adjusted = {}
    for name, b in fs.blocks.items():
        out["blocks"][name] = {
            "type": b.TYPE,
            "error": b.error,
            "warnings": b.warnings,
            "results": [{"key": k, "label": r.label, "value": r.value, "kind": r.kind} for k, r in b.results.items()],
            "steps": [step_dict(s) for s in b.steps],
            "charts": b.charts,
        }
        if b.TYPE == "adjust" and "value" in b.results:
            adjusted.setdefault(b.params["var_block"], {})[b.params["var_param"]] = b.results["value"].value
    out["adjusted"] = adjusted
    return clean(out)


def relief_payload(res: ReliefResult) -> dict:
    return clean({
        "required_area_mm2": res.required_area_mm2,
        "governing_method": res.governing_method,
        "flow_regime": res.flow_regime,
        "relieving_pressure_kpa": res.relieving_pressure_kpa,
        "relieving_state": state_dict(res.relieving_state),
        "orifice": res.orifice,
        "orifice_area_mm2": res.orifice_area_mm2,
        "rated_capacity_kg_h": res.rated_capacity_kg_h,
        "valves_needed": res.valves_needed,
        "coefficients": res.coefficients,
        "cross_checks": res.cross_checks,
        "warnings": res.warnings,
        "nozzle": {"throat_pressure": res.nozzle.throat_pressure, "mass_flux": res.nozzle.mass_flux,
                   "choked": res.nozzle.choked, "curve": res.nozzle.curve} if res.nozzle else None,
        "report": report_dict(res.report),
    })


def relief_system_payload(res) -> dict:
    """JSON for a relief valve sized for several scenarios with its piping."""
    rows = []
    for z in res.sizings:
        sc = z.scenario
        row = {"title": sc.title, "type": sc.key, "applies": sc.applies, "rate_kg_h": sc.rate_kg_h,
               "fluid": sc.fluid, "fluid_text": sc.describe_fluid(), "error": z.error, "note": sc.note,
               "governs": z is res.governing, "steps": [step_dict(s) for s in sc.steps]}
        if z.relief is not None:
            row.update({"area_mm2": z.relief.required_area_mm2, "relieving_pressure_kpa": z.relief.relieving_pressure_kpa,
                        "rated_kg_h": z.rated_kg_h, "back_pressure_kpag": z.back_pressure_kpag,
                        "method": z.relief.governing_method, "regime": z.relief.flow_regime})
        if z.inlet is not None:
            row["inlet"] = {"percent": z.inlet.percent, "ok": z.inlet.ok, "dp": z.inlet.dp_nonrecoverable,
                            "velocity": z.inlet.velocity}
        if z.discharge is not None:
            d = z.discharge
            row["discharge"] = {"built_up": d.built_up, "P_outlet": d.P_outlet, "P_exit": d.P_exit,
                                "v_exit": d.v_exit, "choked": d.choked_exit}
        rows.append(row)
    gov = res.governing
    out = {
        "scenarios": rows,
        "orifice": res.orifice,
        "orifice_area_mm2": res.orifice_area_mm2,
        "valves_needed": res.valves_needed,
        "governing": gov.scenario.title if gov else None,
        "warnings": res.warnings,
        "reaction": {"force_n": res.reaction.force_n, "api_force_n": res.reaction.api_force_n} if res.reaction else None,
        "report": report_dict(res.report),
    }
    if gov is not None and gov.relief is not None:
        out["relief"] = relief_payload(gov.relief)
    return clean(out)
