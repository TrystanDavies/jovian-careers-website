"""Compare a solved flowsheet with reference results (Aspen HYSYS, another simulator, or plant data).

Paste a table copied from a spreadsheet or from the HYSYS workbook. Two layouts are understood:

* one value per row:          Stream | Property | Value | Unit
* a table of streams:          properties down the side and streams across the top (the HYSYS workbook
                               layout), or streams down the side and properties across the top.

Units may be given in a Unit column or in brackets after the property name, e.g. "Temperature [C]",
"Pressure (kPa)", "Mass Flow [kg/h]". Columns are separated by tabs (as copied from a spreadsheet),
commas, semicolons or two or more spaces. Stream names are matched ignoring case, spaces, dashes and
underscores.

Differences are reported against the reference, with tolerance bands. Note that HYSYS's "ASME Steam"
property package uses the older IFC-67 steam tables, which differ from IAPWS-IF97 by up to about 0.1–0.5 %,
and that HYSYS reports enthalpy from a different reference state, so enthalpies are compared only if they
were exported on a steam-table basis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .flowsheet.core import STREAM_PROPERTIES
from .units import P_ATM_KPA

PROPERTY_ALIASES = {
    "Temperature": ("temperature", "temp", "t"),
    "Pressure": ("pressure", "press", "p"),
    "Mass flow": ("mass flow", "mass flowrate", "mass flow rate", "massflow", "flow", "mass rate", "w"),
    "Dryness fraction": ("vapour fraction", "vapor fraction", "vapour frac", "vapor frac", "quality", "dryness",
                         "dryness fraction", "steam quality", "x"),
    "Specific enthalpy": ("mass enthalpy", "specific enthalpy", "enthalpy", "h"),
    "Density": ("mass density", "density", "rho"),
}
NAME_HEADERS = ("name", "stream", "streams", "stream name", "tag")

# unit -> (property kind, factor, offset) converting to internal units: x_internal = x·factor + offset
UNITS = {
    "temperature": {"c": (1.0, 0.0), "°c": (1.0, 0.0), "degc": (1.0, 0.0), "k": (1.0, -273.15),
                    "f": (5.0 / 9.0, -32.0 * 5.0 / 9.0), "°f": (5.0 / 9.0, -32.0 * 5.0 / 9.0),
                    "degf": (5.0 / 9.0, -32.0 * 5.0 / 9.0)},
    "pressure": {"kpa": (1.0, 0.0), "kpaa": (1.0, 0.0), "kpa(a)": (1.0, 0.0), "kpag": (1.0, P_ATM_KPA),
                 "kpa(g)": (1.0, P_ATM_KPA), "bar": (100.0, 0.0), "bara": (100.0, 0.0), "bar(a)": (100.0, 0.0),
                 "barg": (100.0, P_ATM_KPA), "bar(g)": (100.0, P_ATM_KPA), "mpa": (1000.0, 0.0),
                 "mpaa": (1000.0, 0.0), "mpag": (1000.0, P_ATM_KPA), "psia": (6.894757, 0.0),
                 "psig": (6.894757, P_ATM_KPA), "psi": (6.894757, 0.0), "pa": (0.001, 0.0),
                 "kg/cm2": (98.0665, 0.0), "kg/cm2g": (98.0665, P_ATM_KPA)},
    "mass_flow": {"kg/s": (1.0, 0.0), "kg/h": (1.0 / 3600.0, 0.0), "kg/hr": (1.0 / 3600.0, 0.0),
                  "t/h": (1000.0 / 3600.0, 0.0), "tonne/h": (1000.0 / 3600.0, 0.0), "te/h": (1000.0 / 3600.0, 0.0),
                  "lb/h": (0.45359237 / 3600.0, 0.0), "lb/hr": (0.45359237 / 3600.0, 0.0),
                  "lb/s": (0.45359237, 0.0), "kg/min": (1.0 / 60.0, 0.0)},
    "fraction": {"": (1.0, 0.0), "-": (1.0, 0.0), "%": (0.01, 0.0), "fraction": (1.0, 0.0)},
    "enthalpy": {"kj/kg": (1.0, 0.0), "j/kg": (0.001, 0.0), "btu/lb": (2.326, 0.0)},
    "density": {"kg/m3": (1.0, 0.0), "kg/m³": (1.0, 0.0), "lb/ft3": (16.018463, 0.0)},
}
DEFAULT_UNIT = {"temperature": "c", "pressure": "kpa", "mass_flow": "kg/h", "fraction": "", "enthalpy": "kj/kg",
                "density": "kg/m3"}
# |difference| bands: (good, check) — beyond 'check' is a large difference
BANDS = {"temperature": (1.0, 3.0), "fraction": (0.01, 0.03)}  # absolute (°C, dryness)
REL_BANDS = (0.01, 0.05)  # relative, for the other properties


@dataclass
class Reference:
    stream: str
    prop: str
    value: float  # internal units
    source_text: str


@dataclass
class Comparison:
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-–—.]+", "", str(name)).lower()


def _split(line: str) -> list[str]:
    if "\t" in line:
        cells = line.split("\t")
    elif ";" in line:
        cells = line.split(";")
    elif "," in line and not re.search(r"\d,\d{1,2}(\D|$)", line):
        cells = line.split(",")
    else:
        cells = re.split(r"\s{2,}", line.strip())
    return [c.strip().strip('"') for c in cells]


def _property(label: str) -> tuple[str | None, str | None]:
    """(property name, unit text) from a label like 'Temperature [C]'."""
    m = re.match(r"^\s*(.*?)\s*[\[(]\s*([^\])]*)\s*[\])]\s*$", label)
    name, unit = (m.group(1), m.group(2)) if m else (label, None)
    key = name.strip().lower()
    for prop, aliases in PROPERTY_ALIASES.items():
        if key in aliases:
            return prop, unit
    return None, unit


def _number(text: str) -> float | None:
    t = text.strip().replace(" ", "").replace(" ", "")
    if t in ("", "-", "—", "<empty>", "empty", "n/a", "na", "***", "---"):
        return None
    if re.fullmatch(r"-?\d+,\d+", t):  # decimal comma
        t = t.replace(",", ".")
    t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _convert(prop: str, value: float, unit: str | None) -> float:
    kind = STREAM_PROPERTIES[prop][0]
    if kind == "enthalpy":
        kind = "enthalpy"
    table = UNITS.get(kind, {})
    u = (unit or DEFAULT_UNIT.get(kind, "")).strip().lower().replace(" ", "")
    if u not in table:
        raise ValueError(f"Unknown unit '{unit}' for {prop.lower()}.")
    factor, offset = table[u]
    return value * factor + offset


def parse(text: str) -> tuple[list[Reference], list[str]]:
    """Reference values from pasted text, and any problems found."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    warnings: list[str] = []
    refs: list[Reference] = []
    if not lines:
        return refs, ["Nothing to compare: paste a table of reference results."]
    rows = [_split(ln) for ln in lines]
    header = rows[0]

    # layout 1: Stream | Property | Value | Unit
    def long_row(cells):
        if len(cells) < 3:
            return None
        prop, unit = _property(cells[1])
        val = _number(cells[2])
        if prop is None or val is None:
            return None
        return cells[0], prop, val, (cells[3] if len(cells) > 3 and cells[3] else unit)

    body = rows[1:] if long_row(rows[0]) is None else rows
    long = [long_row(c) for c in body]
    if body and sum(r is not None for r in long) >= max(1, len(body) // 2):
        for cells, r in zip(body, long):
            if r is None:
                warnings.append(f"Skipped line: {' | '.join(cells)}")
                continue
            name, prop, val, unit = r
            try:
                refs.append(Reference(name, prop, _convert(prop, val, unit), f"{val:g} {unit or ''}".strip()))
            except ValueError as exc:
                warnings.append(f"{name}: {exc}")
        return refs, warnings

    # layout 2: properties down the side, streams across the top (HYSYS workbook)
    side_props = [_property(c[0]) for c in rows[1:]]
    if sum(p is not None for p, _ in side_props) >= 1 and len(header) > 1:
        streams = header[1:]
        for cells, (prop, unit) in zip(rows[1:], side_props):
            if prop is None:
                if cells and cells[0].strip().lower() not in NAME_HEADERS:
                    warnings.append(f"Unrecognised property '{cells[0]}' was skipped.")
                continue
            for name, cell in zip(streams, cells[1:]):
                val = _number(cell)
                if val is None or not name:
                    continue
                try:
                    refs.append(Reference(name, prop, _convert(prop, val, unit), f"{cell} {unit or ''}".strip()))
                except ValueError as exc:
                    warnings.append(f"{name}: {exc}")
        if refs:
            return refs, warnings

    # layout 3: streams down the side, properties across the top
    top = [_property(c) for c in header[1:]]
    if any(p is not None for p, _ in top):
        for cells in rows[1:]:
            name = cells[0]
            for (prop, unit), cell in zip(top, cells[1:]):
                val = _number(cell)
                if prop is None or val is None:
                    continue
                try:
                    refs.append(Reference(name, prop, _convert(prop, val, unit), f"{cell} {unit or ''}".strip()))
                except ValueError as exc:
                    warnings.append(f"{name}: {exc}")
        for (prop, _), cell in zip(top, header[1:]):
            if prop is None:
                warnings.append(f"Unrecognised column '{cell}' was skipped.")
        return refs, warnings
    return [], ["The table was not recognised. Use columns Stream, Property, Value, Unit, or paste the HYSYS "
                "workbook with the property names (with units in brackets) down the left."]


def compare(fs, text: str) -> Comparison:
    """Compare a solved flowsheet with pasted reference values."""
    refs, warnings = parse(text)
    out = Comparison(warnings=list(warnings))
    by_norm = {_norm(n): n for n in fs.streams}
    missing: list[str] = []
    counts = {"good": 0, "check": 0, "large": 0}
    worst = None
    for r in refs:
        name = by_norm.get(_norm(r.stream))
        if name is None:
            if r.stream not in missing:
                missing.append(r.stream)
            continue
        s = fs.streams[name]
        if not s.known:
            continue
        kind, getter = STREAM_PROPERTIES[r.prop]
        sim = float(getter(s))
        diff = sim - r.value
        rel = diff / r.value if r.value else None
        if kind in BANDS:
            good, check = BANDS[kind]
            mag = abs(diff)
        else:
            good, check = REL_BANDS
            mag = abs(rel) if rel is not None else abs(diff)
        band = "good" if mag <= good else "check" if mag <= check else "large"
        counts[band] += 1
        row = {"stream": name, "property": r.prop, "kind": kind, "reference": r.value, "simulated": sim,
               "difference": diff, "relative": rel, "band": band, "source": r.source_text}
        out.rows.append(row)
        score = mag / check
        if worst is None or score > worst[0]:
            worst = (score, row)
    if missing:
        out.warnings.append("No stream called " + ", ".join(f"'{m}'" for m in missing[:8])
                            + (" ..." if len(missing) > 8 else "") + " in this flowsheet.")
    if any(r["property"] == "Specific enthalpy" for r in out.rows):
        out.warnings.append("Enthalpies only compare if the reference uses the steam-table reference state "
                            "(HYSYS normally does not).")
    out.summary = {"compared": len(out.rows), **counts,
                   "worst": worst[1] if worst else None,
                   "note": "IAPWS-IF97 and the older IFC-67 tables (HYSYS 'ASME Steam') differ by up to about "
                           "0.1–0.5 %; differences within the 'good' band are normal."}
    return out
