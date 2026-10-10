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

from scipy.optimize import brentq

from ..report import CalcReport, Step
from ..units import fmt
from ..water import P_CRIT_KPA, WaterPropertyError, state_Px, state_PT
from .core import BLOCK_TYPES, STREAM_PROPERTIES, Block, SolveContext, Stream


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
        self.layout: dict = {}  # drawing positions: {"nodes": {name: {x, y, rot, flip}}, "streams": {...}}
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

    def solve(self, max_iterations: int = 300, tolerance: float = 1e-9, warm: bool = False) -> SolveResult:
        """Solve the flowsheet, including any Adjust (goal-seek) operations.

        warm=True starts from the previous solution (faster when only a setting changed)."""
        adjusts = [b for b in self.blocks.values() if b.TYPE == "adjust"]
        if not adjusts:
            return self._solve_once(max_iterations, tolerance, warm, final=True)

        first = self._solve_once(max_iterations, tolerance, warm, final=False)
        messages: dict[str, tuple[str, str]] = {}  # adjust name -> ("error"|"ok", text)
        info: dict[str, dict] = {}
        if not first.errors:
            active = []
            for a in adjusts:
                problem = self._check_adjust(a)
                if problem:
                    messages[a.name] = ("error", problem)
                else:
                    active.append(a)
            rounds = 1 if len(active) <= 1 else 8
            for _ in range(rounds):
                all_met = True
                for a in active:
                    if messages.get(a.name, ("ok",))[0] == "error":
                        continue
                    try:
                        info[a.name] = self._run_adjust(a, max_iterations, tolerance)
                    except (ValueError, WaterPropertyError, ZeroDivisionError, RuntimeError) as exc:
                        messages[a.name] = ("error", str(exc))
                for a in active:
                    if a.name in info and messages.get(a.name, ("ok",))[0] != "error":
                        if abs(self._adjust_error(a)) > a.p("tolerance") * max(abs(a.p("target_value")), 1e-6) * 10:
                            all_met = False
                if all_met:
                    break
        result = self._solve_once(max_iterations, tolerance, warm=True, final=True)
        for a in adjusts:
            a.begin()
            kind, text = messages.get(a.name, ("ok", ""))
            if kind == "error":
                a.error = text
                result.errors.append(f"{a.name}: {text}")
                continue
            if a.name in info:
                d = info[a.name]
                blk = self.blocks[a.p("var_block")]
                pdef = next(pp for pp in blk.PARAMS if pp.key == a.p("var_param"))
                a.result("value", f"Adjusted: {blk.name} — {pdef.label}", blk.params[a.p("var_param")], pdef.kind)
                a.result("achieved", "Target value reached", self.measure_target(a), a.target_kind(self.blocks))
                a.result("evaluations", "Flowsheet solutions needed", d["evaluations"], "number")
                a.step("Goal seek",
                       text=(f"{blk.name} — {pdef.label} was varied until the target was met "
                             f"({d['method']}, {d['evaluations']} flowsheet solutions)."),
                       result=(rf"\text{{setting}} = {fmt(blk.params[a.p('var_param')], 6, sep=False)}, \quad "
                               rf"\text{{target}} = {fmt(self.measure_target(a), 6, sep=False)}"))
        result.converged = result.converged and not result.errors
        self.result = result
        return result

    def _check_adjust(self, a: Block) -> str | None:
        vb = self.blocks.get(a.p("var_block"))
        if vb is None:
            return "Choose the equipment to adjust."
        pdef = next((pp for pp in vb.PARAMS if pp.key == a.p("var_param")), None)
        if pdef is None or not isinstance(vb.params.get(pdef.key), (int, float)) or pdef.kind in ("choice", "text"):
            return "Choose a numeric setting to adjust."
        try:
            self.measure_target(a)
        except (KeyError, ValueError, TypeError) as exc:
            return f"Choose a valid target ({exc})."
        return None

    def measure(self, kind: str, obj: str, prop: str) -> float:
        """Value of a stream property or an equipment result (internal units)."""
        if kind == "Stream property":
            s = self.streams.get(obj)
            if s is None or not s.known:
                raise KeyError(f"stream '{obj}' not found")
            return float(STREAM_PROPERTIES[prop][1](s))
        b = self.blocks.get(obj)
        if b is None:
            raise KeyError(f"equipment '{obj}' not found")
        r = b.results.get(prop)
        if r is None or isinstance(r.value, str):
            raise KeyError(f"'{obj}' has no numeric result '{prop}'")
        return float(r.value)

    def measure_target(self, a: Block) -> float:
        if a.p("target_type") == "Stream property":
            return self.measure("Stream property", a.p("target_stream"), a.p("target_property"))
        return self.measure("Equipment result", a.p("target_block"), a.p("target_result"))

    def _adjust_error(self, a: Block) -> float:
        return self.measure_target(a) - float(a.p("target_value"))

    def _run_adjust(self, a: Block, max_iterations: int, tolerance: float) -> dict:
        blk = self.blocks[a.p("var_block")]
        key = a.p("var_param")
        target = float(a.p("target_value"))
        tol = float(a.p("tolerance")) * max(abs(target), 1e-6)
        count = {"n": 0}

        def g(v: float) -> float:
            blk.params[key] = float(v)
            count["n"] += 1
            r = self._solve_once(max_iterations, tolerance, warm=True, final=False)
            if r.errors:
                raise ValueError(f"with the setting at {fmt(v, 5)} the flowsheet fails: {r.errors[0]}")
            return self._adjust_error(a)

        lo, hi = float(a.p("lower")), float(a.p("upper"))
        if hi > lo:
            g_lo, g_hi = g(lo), g(hi)
            if g_lo == 0:
                root = lo
            elif g_hi == 0:
                root = hi
            elif g_lo * g_hi > 0:
                raise ValueError(f"No solution between the limits: the target varies from "
                                 f"{fmt(g_lo + target, 5)} to {fmt(g_hi + target, 5)}, but {fmt(target, 5)} is wanted. "
                                 "Widen the limits.")
            else:
                root = brentq(g, lo, hi, xtol=1e-12 * max(abs(lo), abs(hi), 1.0), rtol=1e-12, maxiter=100)
            method = "Brent's method between the limits"
        else:
            x0 = float(blk.params[key])
            x1 = x0 * 1.02 if x0 != 0 else 1.0
            f0, f1 = g(x0), g(x1)
            root = x1
            for _ in range(60):
                if abs(f1) <= tol:
                    break
                if f1 == f0:
                    raise ValueError("The target does not change when the setting changes; choose another setting.")
                x2 = x1 - f1 * (x1 - x0) / (f1 - f0)
                x0, f0 = x1, f1
                x1, f1 = x2, g(x2)
                root = x1
            else:
                raise ValueError("The goal seek did not converge. Give lower and upper limits for the setting.")
            method = "secant method from the current value"
        blk.params[key] = float(root)
        if abs(g(root)) > max(tol, 1e-9 * max(abs(target), 1.0)) * 10:
            raise ValueError("The goal seek could not meet the target to the requested tolerance.")
        return {"evaluations": count["n"], "method": method}

    def case_study(self, block: str, param: str, values: list[float], outputs: list[dict]) -> list[dict]:
        """Vary one setting over a list of values and record outputs.

        outputs: [{"type": "Stream property"|"Equipment result", "object": name, "property": key}]
        """
        blk = self.blocks.get(block)
        if blk is None or param not in blk.params:
            raise ValueError("Choose the equipment and the setting to vary.")
        original = blk.params[param]
        rows = []
        try:
            for v in values:
                blk.params[param] = float(v)
                try:
                    res = self.solve(warm=True)
                except ValueError as exc:
                    rows.append({"value": v, "ok": False, "error": str(exc), "outputs": [None] * len(outputs)})
                    continue
                ok = not res.errors
                vals = []
                for o in outputs:
                    try:
                        vals.append(self.measure(o["type"], o["object"], o["property"]) if ok else None)
                    except (KeyError, ValueError):
                        vals.append(None)
                rows.append({"value": v, "ok": ok, "error": res.errors[0] if res.errors else None, "outputs": vals})
        finally:
            blk.params[param] = original
            try:
                self.solve(warm=True)
            except ValueError:
                pass
        return rows

    def _solve_once(self, max_iterations: int, tolerance: float, warm: bool, final: bool) -> SolveResult:
        if not self.blocks:
            raise ValueError("The flowsheet is empty. Add some equipment first.")
        for b in self.blocks.values():
            b.validate_ports()
        previous = self._snapshot() if warm and self.streams else {}
        self._build_streams()
        for n, vals in previous.items():
            s = self.streams.get(n)
            if s is not None and None not in vals[:3]:
                s.m, s.P, s.h, s.demand = vals
        ctx = SolveContext(self.streams, blocks=self.blocks)
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

        if final:
            # final pass: lets equipment add end-of-solve warnings and run final-only calculations
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
            "layout": self.layout,
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
        fs.layout = dict(data.get("layout") or {})
        return fs

    @classmethod
    def from_json(cls, text: str) -> "Flowsheet":
        return cls.from_dict(json.loads(text))
