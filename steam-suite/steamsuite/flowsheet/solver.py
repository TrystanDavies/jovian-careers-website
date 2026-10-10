"""The flowsheet: equipment connected by streams, and the solver.

Solving method
--------------
Each iteration does two sweeps over the equipment:

1. A backward sweep, in which equipment requests flows from upstream
   ("demands"): e.g. a process steam user asks its header for steam, the
   header asks its balancing supply for the shortfall, a boiler asks for
   feedwater, a deaerator asks for heating steam and make-up water.
2. A forward sweep, in which every piece of equipment calculates its outlet
   streams from its inlet streams, conserving mass and energy exactly.

Recycle loops are broken with starting estimates. Iterations continue until no
stream flow, pressure, enthalpy or demand changes (successive substitution).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..report import CalcReport, Step
from ..units import fmt
from ..water import P_CRIT_KPA, WaterPropertyError, state_Px, state_PT
from .core import BLOCK_TYPES, Block, SolveContext, Stream


@dataclass
class SolveResult:
    converged: bool
    iterations: int
    max_change: float
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    balance: dict[str, float] = field(default_factory=dict)


class Flowsheet:
    def __init__(self, name: str = "Untitled flowsheet", description: str = ""):
        self.name = name
        self.description = description
        self.blocks: dict[str, Block] = {}
        self.streams: dict[str, Stream] = {}
        self.estimates: dict[str, dict] = {}
        self.result: SolveResult | None = None

    # --- building ------------------------------------------------------------

    def add(self, block: Block) -> Block:
        if not block.name or not block.name.strip():
            raise ValueError("Every piece of equipment needs a name.")
        if block.name in self.blocks:
            raise ValueError(f"There is already equipment called '{block.name}'.")
        self.blocks[block.name] = block
        return block

    def remove(self, name: str) -> None:
        self.blocks.pop(name, None)

    def _build_streams(self) -> None:
        streams: dict[str, Stream] = {}
        for b in self.blocks.values():
            for port, n in b.outlet_streams():
                s = streams.setdefault(n, Stream(n))
                if s.source is not None:
                    raise ValueError(f"Stream '{n}' is an outlet of both '{s.source[0]}' and '{b.name}'. "
                                     "Give one of them a different name.")
                s.source = (b.name, port)
        for b in self.blocks.values():
            for port, n in b.inlet_streams():
                s = streams.setdefault(n, Stream(n))
                if s.dest is not None:
                    raise ValueError(f"Stream '{n}' flows into both '{s.dest[0]}' and '{b.name}'. "
                                     "Use a splitter or header to divide a stream.")
                s.dest = (b.name, port)
        for s in streams.values():
            if s.source is None:
                raise ValueError(f"Stream '{s.name}' flows into '{s.dest[0]}' but nothing supplies it. "
                                 "Connect it to an outlet of other equipment or add a water/steam supply.")
            if s.source[0] == (s.dest[0] if s.dest else None):
                raise ValueError(f"Stream '{s.name}' leaves and enters the same equipment.")
        self.streams = streams

    def _order(self) -> list[Block]:
        """Calculation order: upstream first; loops are broken where most inlets are known."""
        remaining = list(self.blocks.values())
        done: set[str] = set()
        order: list[Block] = []

        def sources(b: Block) -> list[str]:
            return [self.streams[n].source[0] for _, n in b.inlet_streams()]

        while remaining:
            progress = False
            for b in list(remaining):
                if all(src in done for src in sources(b)):
                    order.append(b)
                    done.add(b.name)
                    remaining.remove(b)
                    progress = True
            if not progress:
                best = max(remaining, key=lambda b: (sum(src in done for src in sources(b)) / max(len(sources(b)), 1),
                                                     -remaining.index(b)))
                order.append(best)
                done.add(best.name)
                remaining.remove(best)
        return order

    def _guess(self, s: Stream) -> None:
        est = self.estimates.get(s.name)
        if est:
            P = est["P"]
            h = est.get("h")
            if h is None:
                h = state_Px(P, est["x"]).h if "x" in est else state_PT(P, est["T"]).h
            s.set(est.get("m", 0.0), P, h)
            return
        src = self.blocks[s.source[0]]
        guess = None
        try:
            guess = src.initial_guess(s.source[1])
        except (ValueError, WaterPropertyError, ZeroDivisionError):
            guess = None
        if guess is None:
            P = None
            for key in ("pressure", "outlet_pressure"):
                if key in src.params and src.params[key]:
                    P = float(src.params[key])
                    break
            P = P or 101.325
            h = state_Px(min(P, P_CRIT_KPA - 1.0), 0.0).h
            guess = (P, h, s.demand or 0.0)
        P, h, m = guess
        s.set(m if m is not None else 0.0, P, h)

    # --- solving --------------------------------------------------------------

    def solve(self, max_iterations: int = 300, tolerance: float = 1e-9) -> SolveResult:
        if not self.blocks:
            raise ValueError("The flowsheet is empty. Add some equipment first.")
        for b in self.blocks.values():
            b.validate_ports()
        self._build_streams()
        ctx = SolveContext(self.streams)
        for b in self.blocks.values():
            b.bind(ctx)
        order = self._order()

        converged = False
        change = float("inf")
        it = 0
        stable = 0
        for it in range(1, max_iterations + 1):
            snap = self._snapshot()
            for b in reversed(order):
                try:
                    b.update_demands()
                except (ValueError, WaterPropertyError, ZeroDivisionError):
                    pass
            for b in order:
                b.begin()
                for _, n in b.inlet_streams():
                    if not self.streams[n].known:
                        self._guess(self.streams[n])
                try:
                    b.calculate()
                except (ValueError, WaterPropertyError, ZeroDivisionError) as exc:
                    b.error = str(exc)
            change = self._change(snap)
            errors = any(b.error for b in self.blocks.values())
            stable = stable + 1 if change < tolerance and not errors else 0
            if it >= 3 and stable >= 2:
                converged = True
                break

        # final pass: lets equipment add end-of-solve warnings
        ctx.final = True
        for b in order:
            b.begin()
            try:
                b.calculate()
            except (ValueError, WaterPropertyError, ZeroDivisionError) as exc:
                b.error = str(exc)

        errors = [f"{b.name}: {b.error}" for b in self.blocks.values() if b.error]
        warnings = [f"{b.name}: {w}" for b in self.blocks.values() for w in b.warnings]
        if not converged and not errors:
            warnings.insert(0, f"The calculation did not fully converge after {it} iterations "
                               f"(largest relative change {change:.2g}). Results may be inaccurate.")
        self.result = SolveResult(converged=converged and not errors, iterations=it, max_change=change,
                                  errors=errors, warnings=warnings, balance=self.balance() if not errors else {})
        return self.result

    def _snapshot(self) -> dict[str, tuple]:
        return {n: (s.m, s.P, s.h, s.demand) for n, s in self.streams.items()}

    def _change(self, snap: dict[str, tuple]) -> float:
        worst = 0.0
        for n, s in self.streams.items():
            old = snap.get(n)
            if old is None:
                return float("inf")
            for new_v, old_v, scale in ((s.m, old[0], 0.01), (s.P, old[1], 1.0), (s.h, old[2], 10.0),
                                        (s.demand, old[3], 0.01)):
                if new_v is None and old_v is None:
                    continue
                if new_v is None or old_v is None:
                    return float("inf")
                worst = max(worst, abs(new_v - old_v) / (abs(new_v) + scale))
        return worst

    # --- results ---------------------------------------------------------------

    def feeds(self) -> list[Stream]:
        return [s for s in self.streams.values() if self.blocks[s.source[0]].TYPE == "feed"]

    def products(self) -> list[Stream]:
        return [s for s in self.streams.values() if s.dest is None]

    def balance(self) -> dict[str, float]:
        """Overall mass and energy balance (kg/s and kW)."""
        feeds, products = self.feeds(), self.products()
        m_in = sum(s.m for s in feeds)
        m_out = sum(s.m for s in products)
        h_in = sum(s.m * s.h for s in feeds)
        h_out = sum(s.m * s.h for s in products)
        q = sum(b.heat_in for b in self.blocks.values())
        w = sum(b.work_in for b in self.blocks.values())
        return {
            "mass_in": m_in,
            "mass_out": m_out,
            "mass_error": m_in - m_out,
            "enthalpy_in": h_in,
            "enthalpy_out": h_out,
            "heat_in": q,
            "work_in": w,
            "energy_error": h_in + q + w - h_out,
        }

    def summary(self) -> dict[str, float]:
        """Key figures for the whole system (kW and kg/s)."""
        def total(btype: str, key: str) -> float:
            return sum(b.results[key].value for b in self.blocks.values()
                       if b.TYPE == btype and key in b.results)

        out = {
            "steam_generated": total("boiler", "steam"),
            "boiler_duty": total("boiler", "duty"),
            "fuel": total("boiler", "fuel"),
            "turbine_power": total("turbine", "power"),
            "turbine_electric": total("turbine", "electric"),
            "pump_power": total("pump", "power"),
            "pump_electric": total("pump", "electric"),
            "process_heat": total("steam_user", "duty"),
            "heat_rejected": total("condenser", "duty"),
            "supply_flow": sum(s.m for s in self.feeds()),
        }
        out["net_power"] = out["turbine_power"] - out["pump_power"]
        out["net_electric"] = out["turbine_electric"] - out["pump_electric"]
        # cycle efficiency only means something for a pure power cycle (no process heat)
        if out["boiler_duty"] > 0 and out["turbine_power"] > 0 and out["process_heat"] == 0:
            out["cycle_efficiency"] = out["net_power"] / out["boiler_duty"]
        return out

    def report(self) -> CalcReport:
        rep = CalcReport(
            title=f"Steam system calculation — {self.name}",
            subtitle=self.description,
            disclaimer=("Steady-state heat and mass balance using IAPWS-IF97 properties. Check results with a "
                        "qualified engineer before using them for design."),
            references=["IAPWS R7-97, Revised Release on the IAPWS Industrial Formulation 1997 for the "
                        "Thermodynamic Properties of Water and Steam."],
        )
        res = self.result
        if res is not None:
            rep.add_result("Converged", f"Yes ({res.iterations} iterations)" if res.converged else "No")
            rep.warnings = list(res.errors) + list(res.warnings)
        if res is not None and not res.errors:
            s = self.summary()
            labels = [("steam_generated", "Steam generated", "kg/s"), ("fuel", "Fuel energy input", "kW"),
                      ("boiler_duty", "Boiler heat duty", "kW"), ("process_heat", "Heat to process", "kW"),
                      ("turbine_electric", "Turbine electrical output", "kW"), ("pump_electric", "Pump electrical input", "kW"),
                      ("heat_rejected", "Heat rejected in condensers", "kW"), ("supply_flow", "Water/steam supplied", "kg/s")]
            for key, label, u in labels:
                if abs(s.get(key, 0.0)) > 0:
                    rep.add_result(label, f"{fmt(s[key])} {u}")
            if "cycle_efficiency" in s:
                rep.add_result("Cycle efficiency (net shaft work / boiler heat)", f"{fmt(s['cycle_efficiency'] * 100, 4)} %")
            bal = res.balance
            rep.add_result("Mass balance error", f"{bal['mass_error']:.2e} kg/s")
            rep.add_result("Energy balance error", f"{bal['energy_error']:.2e} kW")

            rows = [["Stream", "From → To", "Flow (kg/s)", "P (kPa a)", "T (°C)", "h (kJ/kg)", "Condition"]]
            for st in self.streams.values():
                w = st.state
                rows.append([st.name, f"{st.source[0]} → {st.dest[0] if st.dest else '(leaves system)'}",
                             fmt(st.m, 5), fmt(st.P, 5), fmt(w.T, 4), fmt(st.h, 5), w.describe()])
            rep.steps.append(Step(title="Stream table", table=rows))
            for b in self.blocks.values():
                rows = [["Result", "Value"]]
                for r in b.results.values():
                    rows.append([r.label, r.value if isinstance(r.value, str) else fmt(r.value, 5)])
                rep.steps.append(Step(title=f"{b.name} ({b.LABEL})", text=b.DESCRIPTION, table=rows))
                for st in b.steps:
                    rep.steps.append(Step(title=f"{b.name} — {st.title}", text=st.text, equation=st.equation,
                                          substitution=st.substitution, result=st.result, table=st.table))
        rep.assumptions = [
            "Steady state; no heat losses from pipes or vessels unless modelled explicitly.",
            "Pressure drops are zero unless entered.",
            "Results are in SI units: kPa(a), °C, kg/s, kJ/kg, kW.",
        ]
        return rep

    # --- serialisation -------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "format": "steam-suite-flowsheet",
            "version": 1,
            "name": self.name,
            "description": self.description,
            "blocks": [b.to_dict() for b in self.blocks.values()],
            "estimates": self.estimates,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "Flowsheet":
        fs = cls(data.get("name", "Untitled flowsheet"), data.get("description", ""))
        for bd in data.get("blocks", []):
            btype = bd.get("type")
            if btype not in BLOCK_TYPES:
                raise ValueError(f"Unknown equipment type '{btype}'.")
            fs.add(BLOCK_TYPES[btype](bd["name"], bd.get("inlets"), bd.get("outlets"), bd.get("params")))
        fs.estimates = dict(data.get("estimates", {}))
        return fs

    @classmethod
    def from_json(cls, text: str) -> "Flowsheet":
        return cls.from_dict(json.loads(text))
