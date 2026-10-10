"""Building blocks of the flowsheet: parameters, ports, streams and the
equipment base class."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..report import Step
from ..water import WaterState, state_Ph

# internal units: kPa(a), °C, kg/s, kJ/kg, kW


@dataclass(frozen=True)
class Param:
    """An equipment setting shown in the user interface.

    kind decides how the value is converted for display:
      'pressure' (absolute kPa), 'pressure_diff' (kPa), 'temperature' (°C),
      'temperature_diff' (°C), 'mass_flow' (kg/s), 'power' (kW), 'percent',
      'fraction' (0–1), 'choice', 'inlet_choice' (one of the block's inlet streams)
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


@dataclass(frozen=True)
class Port:
    key: str
    label: str
    multiple: bool = False
    optional: bool = False
    help: str = ""
    with_specs: bool = False  # outlet flow specifications (splitter, header)


FLOW_MODES = ("Flow", "Fraction", "As required", "Remainder")


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

    @property
    def known(self) -> bool:
        return self.m is not None and self.P is not None and self.h is not None

    def set(self, m: float, P: float, h: float) -> None:
        self.m, self.P, self.h = float(m), float(P), float(h)

    @property
    def state(self) -> WaterState:
        return state_Ph(round(self.P, 9), round(self.h, 9))

    def __repr__(self) -> str:
        return f"Stream({self.name!r}, m={self.m}, P={self.P}, h={self.h}, demand={self.demand})"


class SolveContext:
    """Gives equipment access to its streams during a solve."""

    def __init__(self, streams: dict[str, Stream], final: bool = False):
        self.streams = streams
        self.final = final


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
        self.params: dict[str, Any] = {p.key: p.default for p in self.PARAMS}
        if params:
            unknown = set(params) - set(self.params) - {"outlet_specs"}
            if unknown:
                raise ValueError(f"{self.LABEL} '{name}': unknown setting(s) {sorted(unknown)}")
            self.params.update(params)
        if any(p.with_specs for p in self.OUTLETS):
            self.params.setdefault("outlet_specs", {})
        self.results: dict[str, Result] = {}
        self.steps: list[Step] = []
        self.warnings: list[str] = []
        self.error: str | None = None
        self.heat_in = 0.0  # kW added to the fluid as heat
        self.work_in = 0.0  # kW added to the fluid as shaft work
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

    def calculate(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def update_demands(self) -> None:
        """Default: no flow requests."""

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
        return {
            "type": self.TYPE,
            "name": self.name,
            "inlets": self.inlets,
            "outlets": self.outlets,
            "params": self.params,
        }


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
        elif mode == "As required":
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
        elif mode == "As required":
            total += max(s.demand or 0.0, 0.0)
        elif mode == "Remainder":
            total += max(s.demand or 0.0, 0.0)
        elif mode == "Fraction":
            return None
    return total
