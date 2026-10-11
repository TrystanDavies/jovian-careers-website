import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from steamsuite.web.server import app  # noqa: E402

client = TestClient(app)


def test_index_and_static():
    r = client.get("/")
    assert r.status_code == 200 and "Steam Suite" in r.text
    assert client.get("/static/js/main.js").status_code == 200


def test_catalog_lists_every_equipment_type():
    cat = client.get("/api/catalog").json()
    types = {b["type"] for b in cat["blocks"]}
    for t in ("feed", "pump", "valve", "turbine", "boiler", "heater", "condenser", "mixer", "splitter", "header",
              "flash", "desuperheater", "deaerator", "steam_user", "pipe", "heat_exchanger", "compressor",
              "relief_valve", "adjust"):
        assert t in types
    pipe = next(b for b in cat["blocks"] if b["type"] == "pipe")
    assert any(p["kind"] == "fittings" for p in pipe["params"])
    assert "4" in cat["pipe_sizes"] and "elbow_90_std" in cat["fittings"]


def test_examples_have_layouts_and_solve():
    examples = client.get("/api/examples").json()
    assert len(examples) >= 4
    for ex in examples:
        data = client.get(f"/api/examples/{ex['key']}").json()
        names = {b["name"] for b in data["blocks"]}
        assert set(data["layout"]["nodes"]) >= names
        if not names:
            continue
        res = client.post("/api/solve", json=data).json()
        assert res["errors"] == [], (ex["key"], res["errors"])
        assert res["converged"]
        assert res["streams"] and all(s["known"] for s in res["streams"].values())


def test_solve_reports_structure_errors():
    data = {"blocks": [{"type": "valve", "name": "V", "inlets": {"in": "nowhere"}, "outlets": {"out": "o"},
                        "params": {}}]}
    res = client.post("/api/solve", json=data).json()
    assert "nothing supplies it" in res["structure_error"]


def test_solve_returns_steps_charts_and_adjusted_values():
    data = client.get("/api/examples/Steam distribution with pipes and relief valves").json()
    res = client.post("/api/solve", json=data).json()
    assert not res["errors"]
    pipes = [b for b in res["blocks"].values() if b["type"] == "pipe"]
    assert pipes and pipes[0]["charts"] and pipes[0]["steps"]
    psvs = [b for b in res["blocks"].values() if b["type"] == "relief_valve"]
    assert psvs and any(r["key"] == "orifice" for r in psvs[0]["results"])


def test_relief_endpoint():
    r = client.post("/api/relief", json={"fluid": "saturated_steam", "flow_kg_h": 10000, "set_pressure_kpag": 1000})
    body = r.json()
    assert r.status_code == 200 and body["orifice"] == "L"
    assert body["report"]["steps"] and "<html" in body["html"]
    bad = client.post("/api/relief", json={"fluid": "saturated_steam", "flow_kg_h": 0, "set_pressure_kpag": 1000})
    assert bad.status_code == 400


def test_properties_endpoint():
    r = client.post("/api/properties", json={"mode": "PT", "P": 1000, "T": 250}).json()
    assert r["state"]["phase"] == "vapour"
    r = client.post("/api/properties", json={"mode": "satP", "P": 101.325}).json()
    assert r["liquid"]["T"] == pytest.approx(99.97, abs=0.01)
    assert client.post("/api/properties", json={"mode": "PT", "P": 1000, "T": -10}).status_code == 400
    assert len(client.get("/api/dome").json()["points"]) > 50


def test_case_study_endpoint():
    data = client.get("/api/examples/Simple Rankine cycle (textbook)").json()
    r = client.post("/api/case-study", json={
        "flowsheet": data, "block": "Boiler", "param": "temperature", "start": 300, "end": 500, "steps": 3,
        "outputs": [{"type": "Stream property", "object": "4 Condenser inlet", "property": "Dryness fraction"}]})
    rows = r.json()["rows"]
    assert len(rows) == 3 and rows[0]["outputs"][0] < rows[2]["outputs"][0]


def test_report_endpoint():
    data = client.get("/api/examples/Simple Rankine cycle (textbook)").json()
    assert "<html" in client.post("/api/report", json=data).text
    assert "# Steam system calculation" in client.post("/api/report?format=md", json=data).text


def test_pressure_flow_solve_reports_the_network_and_accepts_a_warm_start():
    doc = client.get("/api/examples/Cooling-water network (pressure–flow)").json()
    assert doc["solver_mode"] == "pressure_flow"
    r = client.post("/api/solve", json=doc).json()
    assert r["converged"], r["errors"]
    assert r["network"]["equations"] == r["network"]["unknowns"] > 0
    warm = {k: [s["m"], s["P"], s["h"]] for k, s in r["streams"].items()}
    r2 = client.post("/api/solve", json={**doc, "warm": warm}).json()
    assert r2["converged"]
    assert r2["network"]["newton_iterations"] == 0  # already the answer
    cat = client.get("/api/catalog").json()
    assert "pressure_flow" in cat["solver_modes"] and "Open" in cat["inlet_modes"]
    assert {"sink", "check_valve", "specification"} <= {b["type"] for b in cat["blocks"]}


def test_relief_system_endpoint():
    cat = client.get("/api/catalog").json()
    assert {"fire", "cv_failure", "tube_rupture", "thermal"} <= set(cat["scenarios"])
    body = {"valve": {"fluid": "saturated_steam", "flow_kg_h": 1.0, "set_pressure_kpag": 1000.0, "tag": "PSV-9"},
            "scenarios": [{"type": "fire", "wetted_area": 30.0}, {"type": "given", "flow": 1.0}],
            "inlet": {"nps": "4", "length": 1.0, "fittings": {"entrance_sharp": 1}},
            "outlet": {"nps": "6", "length": 8.0}, "outlet_to": "atmosphere"}
    r = client.post("/api/relief-system", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["orifice"] and j["governing"] and len(j["scenarios"]) == 2
    assert j["reaction"]["force_n"] > 0 and "Relief scenarios" in j["html"]
    assert client.post("/api/relief-system", json={"valve": {"fluid": "x"}}).status_code == 400
