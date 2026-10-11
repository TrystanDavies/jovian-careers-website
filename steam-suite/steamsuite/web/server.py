"""Steam Suite web application: a JSON API plus the browser-based P&ID designer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..examples import EXAMPLES
from ..flowsheet import Flowsheet
from ..flowsheet.layout import auto_layout, ensure_layout
from ..relief import ReliefInput, size_relief_valve
from ..water import (
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
from . import serialize

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Steam Suite", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _flowsheet(data: dict) -> Flowsheet:
    try:
        return Flowsheet.from_dict(data)
    except (ValueError, KeyError, TypeError) as exc:
        raise _bad(exc) from exc


def _warm(fs: Flowsheet, data: dict) -> None:
    """Pressure–flow mode can start from the previous solution the browser sends ({stream: [m, P, h]})."""
    warm = data.get("warm")
    if not isinstance(warm, dict):
        return
    out = {}
    for name, vals in warm.items():
        try:
            m, P, h = (float(v) for v in vals)
        except (TypeError, ValueError):
            continue
        if P > 0:
            out[name] = (m, P, h)
    fs.warm_start = out


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/catalog")
def get_catalog() -> dict:
    return serialize.catalog()


@app.get("/api/examples")
def list_examples() -> list[dict]:
    out = []
    for key, fn in EXAMPLES.items():
        fs = fn()
        out.append({"key": key, "name": fs.name, "description": fs.description})
    return out


@app.get("/api/examples/{key}")
def get_example(key: str) -> dict:
    if key not in EXAMPLES:
        raise HTTPException(status_code=404, detail="No such example.")
    return serialize.clean(ensure_layout(EXAMPLES[key]().to_dict()))


@app.post("/api/layout")
def layout(data: dict = Body(...)) -> dict:
    return serialize.clean(auto_layout(data))


@app.post("/api/solve")
def solve(data: dict = Body(...)) -> dict:
    fs = _flowsheet(data)
    if not fs.blocks:
        return {"structure_error": None, "converged": True, "errors": [], "warnings": [], "streams": {}, "blocks": {},
                "balance": {}, "summary": {}, "adjusted": {}, "empty": True}
    _warm(fs, data)
    try:
        fs.solve()
    except (ValueError, WaterPropertyError) as exc:
        return serialize.solve_payload(fs, str(exc))
    return serialize.solve_payload(fs)


@app.post("/api/report")
def report(data: dict = Body(...), format: str = "html") -> Any:
    fs = _flowsheet(data)
    try:
        fs.solve()
    except (ValueError, WaterPropertyError) as exc:
        raise _bad(exc) from exc
    rep = fs.report()
    if format == "md":
        return PlainTextResponse(rep.to_markdown(), media_type="text/markdown")
    return HTMLResponse(rep.to_html())


@app.post("/api/case-study")
def case_study(data: dict = Body(...)) -> dict:
    fs = _flowsheet(data.get("flowsheet") or {})
    try:
        start, end, steps = float(data["start"]), float(data["end"]), int(data["steps"])
        if steps < 2 or steps > 200:
            raise ValueError("Use between 2 and 200 steps.")
        values = list(np.linspace(start, end, steps))
        fs.solve()
        rows = fs.case_study(data["block"], data["param"], values, data.get("outputs") or [])
    except (KeyError, ValueError, WaterPropertyError) as exc:
        raise _bad(exc) from exc
    return serialize.clean({"rows": rows})


@app.post("/api/relief-system")
def relief_system(data: dict = Body(...)) -> dict:
    """{valve: ReliefInput fields, scenarios: [...], inlet: LineSpec | null, outlet: LineSpec | null,
    outlet_to: 'atmosphere' | 'header', superimposed_kpag}"""
    from ..relief_system import LineSpec, size_relief_system
    try:
        base = ReliefInput(**(data.get("valve") or {}))
        inlet = LineSpec(**data["inlet"]) if data.get("inlet") else None
        outlet = LineSpec(**data["outlet"]) if data.get("outlet") else None
        res = size_relief_system(base, data.get("scenarios") or None, inlet, outlet,
                                 data.get("outlet_to") or "atmosphere", float(data.get("superimposed_kpag") or 0.0))
    except (TypeError, ValueError, KeyError, WaterPropertyError) as exc:
        raise _bad(exc) from exc
    payload = serialize.relief_system_payload(res)
    payload["html"] = res.report.to_html()
    payload["markdown"] = res.report.to_markdown()
    return payload


@app.post("/api/relief")
def relief(data: dict = Body(...)) -> dict:
    try:
        res = size_relief_valve(ReliefInput(**data))
    except (TypeError, ValueError, WaterPropertyError) as exc:
        raise _bad(exc) from exc
    payload = serialize.relief_payload(res)
    payload["html"] = res.report.to_html()
    payload["markdown"] = res.report.to_markdown()
    return payload


@app.post("/api/properties")
def properties(data: dict = Body(...)) -> dict:
    mode = data.get("mode")
    try:
        if mode == "PT":
            return {"state": serialize.state_dict(state_PT(float(data["P"]), float(data["T"])))}
        if mode == "Px":
            return {"state": serialize.state_dict(state_Px(float(data["P"]), float(data["x"])))}
        if mode == "Tx":
            return {"state": serialize.state_dict(state_Tx(float(data["T"]), float(data["x"])))}
        if mode == "Ph":
            return {"state": serialize.state_dict(state_Ph(float(data["P"]), float(data["h"])))}
        if mode == "Ps":
            return {"state": serialize.state_dict(state_Ps(float(data["P"]), float(data["s"])))}
        if mode == "satP":
            liq, vap = saturation_at_P(float(data["P"]))
            return {"liquid": serialize.state_dict(liq), "vapour": serialize.state_dict(vap)}
        if mode == "satT":
            liq, vap = saturation_at_T(float(data["T"]))
            return {"liquid": serialize.state_dict(liq), "vapour": serialize.state_dict(vap)}
    except (KeyError, ValueError, WaterPropertyError) as exc:
        raise _bad(exc) from exc
    raise HTTPException(status_code=400, detail=f"Unknown mode {mode!r}.")


_DOME: list | None = None


@app.get("/api/dome")
def dome() -> dict:
    """Saturation line points for T–s and P–h charts."""
    global _DOME
    if _DOME is None:
        temps = list(np.linspace(0.01, 360.0, 90)) + list(np.linspace(360.0, T_CRIT_C - 0.001, 30))
        rows = []
        for T in temps:
            liq, vap = saturation_at_T(float(T))
            rows.append({"T": T, "P": liq.P, "s_f": liq.s, "s_g": vap.s, "h_f": liq.h, "h_g": vap.h})
        _DOME = rows
    return {"points": _DOME}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}
