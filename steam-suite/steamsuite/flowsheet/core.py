"""Building blocks of the flowsheet: parameters, ports, streams and the
equipment base class."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, ClassVar

from ..report import Step
from ..water import WaterState, state_Ph

# internal units: kPa(a), °C, kg/s, kJ/kg, kW


@dataclass(frozen=True)
class Param:
    """An equipment setting shown in the user interface.

    kind decides how the value is shown and converted for display:
      numbers: 'pressure' (absolute kPa), 'pressure_diff' (kPa), 'temperature' (°C),
      'temperature_diff' (°C), 'mass_flow' (kg/s), 'power' (kW), 'percent',
      'fraction' (0–1), 'number', 'length' (m), 'diameter' (mm), 'roughness' (mm),
      'head' (m), 'volume_flow' (m³/h), 'ua' (kW/K), 'htc' (W/m²K), 'conductivity' (W/mK)
      other: 'choice', 'text', 'inlet_choice' (one of the block's inlet streams),
      'stream_choice' / 'block_choice' (any stream / equipment in the flowsheet),
      'param_choice' / 'result_choice' (a setting / result of the equipment chosen in
      the setting named by depends_on), 'fittings' ({fitting: count}),
      'target_value' (number whose unit follows the chosen target property),
      'scenarios' (list of relief scenarios)
    """

    key: str
    label: str
    kind: str
    default: Any = None
    help: str = ""
    choices: tuple[str, ...] = ()
    show_if: tuple[str, tuple[str, ...]] | None = None
    min_value: float | None = None
    max_value: float | None = None
    inlet_port: str | None = None  # for kind 'inlet_choice'
    group: str = ""  # heading the setting is shown under
    depends_on: str | None = None  # for 'param_choice' / 'result_choice': the block-choice setting it refers to


@dataclass(frozen=True)
class Port:
    key: str
    label: str
    multiple: bool = False
    optional: bool = False
    help: str = ""
    with_specs: bool = False  # outlet flow specifications (splitter, header)
    open_option: bool = False  # inlet can be 'Open' (arrives at the vessel pressure) in pressure–flow mode


FLOW_MODES = ("Flow", "Fraction", "As required", "Remainder", "Pressure-driven")
INLET_MODES = ("Throttled", "Open")


@dataclass
class Result:
    label: str
    value: Any
    kind: str  # same kinds as Param, plus 'text', 'enthalpy', 'number'


class Stream:
    """A connection between two pieces of equipment carrying water or steam."""

    def __init__(self, name: str):
        self.name = name
        self.m: float | None = None  # kg/s
        self.P: float | None = None  # kPa(a)
        self.h: float | None = None  # kJ/kg
        self.demand: float | None = None  # kg/s requested by the consumer
        self.source: tuple[str, str] | None = None  # (block name, port)
        self.dest: tuple[str, str] | None = None
        self.estimate: dict | None = None
        self.locked = False  # pressure–flow mode: m and P come from the network solution

    @property
    def known(self) -> bool:
        return self.m is not None and self.P is not None and self.h is not None

    def set(self, m: float, P: float, h: float) -> None:
        if self.locked:  # flow and pressure were fixed by the pressure–flow solution
            self.h = float(h)
            return
        self.m, self.P, self.h = float(m), float(P), float(h)

    @property
    def state(self) -> WaterState:
        return state_Ph(round(self.P, 9), round(self.h, 9))

    def __repr__(self) -> str:
        return f"Stream({self.name!r}, m={self.m}, P={self.P}, h={self.h}, demand={self.demand})"


class SolveContext:
    """Gives equipment access to its streams (and the other equipment) during a solve."""

    def __init__(self, streams: dict[str, Stream], final: bool = False, blocks: dict | None = None,
                 pressure_flow: bool = False):
        self.streams = streams
        self.final = final
        self.blocks = blocks or {}
        self.pressure_flow = pressure_flow  # flows and pressures come from the network solution


# stream properties that Adjust and case studies can target: name -> (kind, getter)
def _dryness(s: "Stream") -> float:
    st = s.state
    if st.x is not None:
        return st.x
    return 1.0 if st.is_vapour_like else 0.0


STREAM_PROPERTIES: dict[str, tuple[str, Any]] = {
    "Temperature": ("temperature", lambda s: s.state.T),
    "Pressure": ("pressure", lambda s: s.P),
    "Mass flow": ("mass_flow", lambda s: s.m),
    "Dryness fraction": ("fraction", _dryness),
    "Superheat": ("temperature_diff", lambda s: s.state.superheat or 0.0),
    "Specific enthalpy": ("enthalpy", lambda s: s.h),
    "Density": ("density", lambda s: s.state.rho),
}


class Block:
    """Base class for equipment.

    Subclasses implement:
      * ``calculate`` — compute outlet streams from inlet streams (forward pass),
      * ``update_demands`` — request flows from upstream (backward pass),
      * ``initial_guess`` — a starting estimate for an outlet stream when a
        recycle loop must be broken.
    Mass is always conserved using the actual inlet flows; demands are requests
    that upstream equipment satisfies on the next iteration.
    """

    TYPE: ClassVar[str] = ""
    LABEL: ClassVar[str] = ""
    CATEGORY: ClassVar[str] = ""
    DESCRIPTION: ClassVar[str] = ""
    INLETS: ClassVar[list[Port]] = []
    OUTLETS: ClassVar[list[Port]] = []
    PARAMS: ClassVar[list[Param]] = []

    def __init__(self, name: str, inlets: dict | None = None, outlets: dict | None = None,
                 params: dict | None = None):
        self.name = name
        self.inlets: dict[str, Any] = dict(inlets or {})
        self.outlets: dict[str, Any] = dict(outlets or {})
        self.params: dict[str, Any] = {p.key: copy.deepcopy(p.default) for p in self.PARAMS}
        if params:
            unknown = set(params) - set(self.params) - {"outlet_specs", "inlet_specs"}
            if unknown:
                raise ValueError(f"{self.LABEL} '{name}': unknown setting(s) {sorted(unknown)}")
            self.params.update(copy.deepcopy(params))
        if any(p.with_specs for p in self.OUTLETS):
            self.params.setdefault("outlet_specs", {})
        if any(p.open_option for p in self.INLETS):
            self.params.setdefault("inlet_specs", {})
        self.pf_state: dict[str, Any] = {}  # pressure–flow active sets (kept between passes)
        self.results: dict[str, Result] = {}
        self.steps: list[Step] = []
        self.warnings: list[str] = []
        self.error: str | None = None
        self.heat_in = 0.0  # kW added to the fluid as heat
        self.work_in = 0.0  # kW added to the fluid as shaft work (or as potential/kinetic energy)
        self.charts: dict[str, dict] = {}  # name -> {"x": label, "y": label, "series": {name: [(x, y)]}}
        self._ctx: SolveContext | None = None

    # --- connections --------------------------------------------------------

    def port_streams(self, ports: list[Port], mapping: dict[str, Any]) -> list[tuple[str, str]]:
        out = []
        for port in ports:
            val = mapping.get(port.key)
            if val is None or val == "" or val == []:
                continue
            names = val if isinstance(val, list) else [val]
            out += [(port.key, n) for n in names if n]
        return out

    def inlet_streams(self) -> list[tuple[str, str]]:
        return self.port_streams(self.INLETS, self.inlets)

    def outlet_streams(self) -> list[tuple[str, str]]:
        return self.port_streams(self.OUTLETS, self.outlets)

    def validate_ports(self) -> None:
        for port in self.INLETS:
            if not port.optional and not self.inlets.get(port.key):
                raise ValueError(f"{self.LABEL} '{self.name}': connect the '{port.label}' inlet.")
        for port in self.OUTLETS:
            if not port.optional and not self.outlets.get(port.key):
                raise ValueError(f"{self.LABEL} '{self.name}': name the '{port.label}' outlet stream.")

    def s_in(self, port: str) -> Stream | None:
        name = self.inlets.get(port)
        return self._ctx.streams[name] if name else None

    def s_out(self, port: str) -> Stream | None:
        name = self.outlets.get(port)
        return self._ctx.streams[name] if name else None

    def s_ins(self, port: str) -> list[Stream]:
        names = self.inlets.get(port) or []
        names = names if isinstance(names, list) else [names]
        return [self._ctx.streams[n] for n in names]

    def s_outs(self, port: str) -> list[Stream]:
        names = self.outlets.get(port) or []
        names = names if isinstance(names, list) else [names]
        return [self._ctx.streams[n] for n in names]

    # --- solving -------------------------------------------------------------

    def bind(self, ctx: SolveContext) -> None:
        self._ctx = ctx

    def begin(self) -> None:
        self.results = {}
        self.steps = []
        self.warnings = []
        self.error = None
        self.heat_in = 0.0
        self.work_in = 0.0
        self.charts = {}

    def calculate(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def update_demands(self) -> None:
        """Default: no flow requests."""

    def hydraulics(self, net) -> None:
        """Add this equipment's pressure–flow equations to the network (see network.py)."""
        raise NotImplementedError(f"{self.LABEL} cannot be used in pressure–flow mode yet.")

    def diagnose(self, net, x) -> str | None:
        """Pressure–flow mode: explain why this equipment may make the equations unsolvable at x."""
        return None

    def check_active_set(self, net, x) -> bool:
        """Pressure–flow mode: switch between alternative equation sets (e.g. a PRV that runs wide open).
        Return True if the set changed."""
        return False

    @property
    def pf(self) -> bool:
        """True during the energy pass of a pressure–flow solve (flows and pressures are imposed)."""
        return bool(self._ctx is not None and self._ctx.pressure_flow)

    def inlet_open(self, stream_name: str) -> bool:
        return (self.params.get("inlet_specs") or {}).get(stream_name) == "Open"

    def initial_guess(self, port: str) -> tuple[float, float, float] | None:
        """(P, h, m) starting estimate for an outlet, or None."""
        return None

    def ready(self) -> bool:
        return all(self._ctx.streams[n].known for _, n in self.inlet_streams())

    # --- helpers for subclasses ---------------------------------------------

    def p(self, key: str) -> Any:
        return self.params[key]

    def result(self, key: str, label: str, value: Any, kind: str) -> None:
        if not isinstance(value, str):
            value = float(value)
        self.results[key] = Result(label, value, kind)

    def step(self, title: str, **kwargs) -> None:
        self.steps.append(Step(title=title, **kwargs))

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    def pass_demand_through(self, inlet_port: str = "in", outlet_port: str = "out", factor: float = 1.0) -> None:
        out = self.s_out(outlet_port)
        inp = self.s_in(inlet_port)
        if out is not None and inp is not None and out.demand is not None:
            inp.demand = out.demand * factor

    # --- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return copy.deepcopy({
            "type": self.TYPE,
            "name": self.name,
            "inlets": self.inlets,
            "outlets": self.outlets,
            "params": self.params,
        })


BLOCK_TYPES: dict[str, type[Block]] = {}


def register(cls: type[Block]) -> type[Block]:
    BLOCK_TYPES[cls.TYPE] = cls
    return cls


def allocate_outlets(block: Block, m_total: float, outlets: list[Stream]) -> dict[str, float]:
    """Split a total flow over outlets according to their flow specifications.

    Each outlet has a mode: 'Flow' (fixed kg/s), 'Fraction' (% of total),
    'As required' (whatever the downstream equipment requests) or 'Remainder'
    (whatever is left; at most one outlet). If the flows do not add up,
    the outlets are scaled to conserve mass and a warning is raised.
    """
    specs = block.params.get("outlet_specs") or {}
    flows: dict[str, float] = {}
    remainder: str | None = None
    for s in outlets:
        spec = specs.get(s.name) or {"mode": "Remainder", "value": 0.0}
        mode = spec.get("mode", "Remainder")
        val = float(spec.get("value") or 0.0)
        if mode == "Flow":
            flows[s.name] = max(val, 0.0)
        elif mode == "Fraction":
            flows[s.name] = max(val, 0.0) / 100.0 * m_total
        elif mode in ("As required", "Pressure-driven"):
            flows[s.name] = max(s.demand or 0.0, 0.0)
        elif mode == "Remainder":
            if remainder is not None:
                raise ValueError(f"{block.LABEL} '{block.name}': only one outlet can be set to 'Remainder'.")
            remainder = s.name
        else:
            raise ValueError(f"{block.LABEL} '{block.name}': unknown flow mode '{mode}'.")
    assigned = sum(flows.values())
    tol = 1e-6 * max(1.0, m_total)
    if remainder is not None:
        rest = m_total - assigned
        if rest < -tol:
            block.warn(
                f"Not enough flow: the outlets need {assigned:.4g} kg/s but only {m_total:.4g} kg/s arrives. "
                "Outlet flows were reduced in proportion."
            )
            scale = m_total / assigned if assigned > 0 else 0.0
            flows = {k: v * scale for k, v in flows.items()}
            rest = 0.0
        flows[remainder] = max(rest, 0.0)
    elif abs(assigned - m_total) > tol:
        if assigned > m_total:
            block.warn(
                f"Not enough flow: the outlets need {assigned:.4g} kg/s but only {m_total:.4g} kg/s arrives. "
                "Outlet flows were reduced in proportion."
            )
        else:
            block.warn(
                f"Surplus flow: {m_total:.4g} kg/s arrives but the outlets only take {assigned:.4g} kg/s. "
                "Outlet flows were increased in proportion. Add a 'Remainder' outlet (e.g. a vent) to send the "
                "surplus somewhere."
            )
        scale = m_total / assigned if assigned > 0 else 0.0
        if assigned > 0:
            flows = {k: v * scale for k, v in flows.items()}
        else:
            share = m_total / len(outlets) if outlets else 0.0
            flows = {s.name: share for s in outlets}
    return flows


def requested_outflow(block: Block, outlets: list[Stream], m_total_guess: float) -> float | None:
    """Total flow the outlets want, used to request flow from upstream.

    Returns None when an outlet is specified as a fraction (the total cannot be
    requested in that case)."""
    specs = block.params.get("outlet_specs") or {}
    total = 0.0
    for s in outlets:
        spec = specs.get(s.name) or {"mode": "Remainder", "value": 0.0}
        mode = spec.get("mode", "Remainder")
        if mode == "Flow":
            total += max(float(spec.get("value") or 0.0), 0.0)
        elif mode in ("As required", "Pressure-driven", "Remainder"):
            total += max(s.demand or 0.0, 0.0)
        elif mode == "Fraction":
            return None
    return total
