"""Pressure–flow network: every stream's mass flow and pressure solved together.

In pressure–flow mode each piece of equipment contributes equations that
relate the flows and pressures of its streams (see ``Block.hydraulics``):
same flow in and out, a mass balance, a fixed pressure, a pressure drop that
depends on the flow (pipes, pump curves, exchangers), a flow that depends on
the pressures (control valves), or an energy balance that is linear in the
flows once the enthalpies are known. Enthalpies are held fixed while these
equations are solved and updated afterwards by the ordinary forward pass, in
an outer loop (see ``Flowsheet._solve_pf``).

The equations are solved by Newton's method with a line search. Before
solving, a structural check (maximum matching between equations and
unknowns) finds missing or conflicting specifications and explains them in
plain language; a rank check catches the cases a structural check cannot,
such as a closed loop with nothing to fix its circulating flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_bipartite_matching

from ..water import WaterPropertyError

FAILURES = (ValueError, WaterPropertyError, ZeroDivisionError, OverflowError, ArithmeticError)


class NetworkError(ValueError):
    """The pressure–flow equations are badly posed or could not be solved."""


@dataclass
class Equation:
    why: str  # plain-language description, used in messages
    block: str
    vars: list[int]  # unknowns the equation depends on
    kind: str  # 'linear' or 'func'
    scale: float = 1.0  # residual is divided by this
    coeffs: dict[int, float] = field(default_factory=dict)  # linear: Σ c·x − rhs
    rhs: float = 0.0
    func: Callable[[np.ndarray], float] | None = None  # func: residual from the full vector
    analytic: dict[int, float] = field(default_factory=dict)  # known constant partial derivatives (func)
    mass: bool = False  # a pure mass-conservation equation (may be dropped in a closed loop)
    absolute_pressure: bool = False  # fixes a pressure level
    surrogate: tuple | None = None  # how to build a simple quadratic stand-in (for a starting point)

    def residual(self, x: np.ndarray) -> float:
        if self.kind == "linear":
            return sum(c * x[j] for j, c in self.coeffs.items()) - self.rhs
        return self.func(x)


class Network:
    """The unknowns (flow and pressure of every stream) and the equations equipment adds."""

    def __init__(self, streams: dict, m_ref: float = 1.0, P_ref: float = 100.0):
        self.streams = streams
        self.names = list(streams)
        self.index = {n: i for i, n in enumerate(self.names)}
        self.n = len(self.names)
        self.equations: list[Equation] = []
        self.m_ref = m_ref
        self.P_ref = P_ref
        self.block = ""  # name of the block currently adding equations
        self.notes: list[str] = []
        self.last_x: np.ndarray | None = None  # last iterate (for diagnosing a failure)

    # --- unknowns ------------------------------------------------------------------

    def im(self, s) -> int:
        return self.index[s if isinstance(s, str) else s.name]

    def ip(self, s) -> int:
        return self.n + self.index[s if isinstance(s, str) else s.name]

    def describe_var(self, j: int) -> str:
        name = self.names[j % self.n]
        s = self.streams[name]
        where = f"from {s.source[0]}" + (f" to {s.dest[0]}" if s.dest else ", leaving the system")
        return f"the {'flow' if j < self.n else 'pressure'} of stream '{name}' ({where})"

    # --- equation builders (used by Block.hydraulics) -------------------------------

    def _add(self, eq: Equation) -> None:
        eq.block = self.block
        self.equations.append(eq)

    def flow(self, s, value: float, why: str) -> None:
        j = self.im(s)
        self._add(Equation(why, "", [j], "linear", self.m_ref, {j: 1.0}, float(value)))

    def flow_ratio(self, s, ref, ratio: float, why: str) -> None:
        a, b = self.im(s), self.im(ref)
        self._add(Equation(why, "", [a, b], "linear", self.m_ref, {a: 1.0, b: -float(ratio)}, 0.0))

    def same_flow(self, a, b, why: str) -> None:
        i, j = self.im(a), self.im(b)
        self._add(Equation(why, "", [i, j], "linear", self.m_ref, {i: 1.0, j: -1.0}, 0.0, mass=True))

    def mass_balance(self, ins: list, outs: list, why: str) -> None:
        coeffs: dict[int, float] = {}
        for s in ins:
            coeffs[self.im(s)] = coeffs.get(self.im(s), 0.0) + 1.0
        for s in outs:
            coeffs[self.im(s)] = coeffs.get(self.im(s), 0.0) - 1.0
        self._add(Equation(why, "", list(coeffs), "linear", self.m_ref, coeffs, 0.0, mass=True))

    def linear_flows(self, coeffs: dict, rhs: float, why: str) -> None:
        """Σ c·m = rhs, e.g. an energy balance with the enthalpies held fixed."""
        cj = {self.im(s): float(c) for s, c in coeffs.items()}
        scale = max([abs(c) for c in cj.values()] + [abs(rhs) / max(self.m_ref, 1e-9), 1e-9]) * self.m_ref
        self._add(Equation(why, "", list(cj), "linear", scale, cj, float(rhs)))

    def pressure(self, s, value: float, why: str) -> None:
        j = self.ip(s)
        self._add(Equation(why, "", [j], "linear", self.P_ref, {j: 1.0}, float(value), absolute_pressure=True))

    def same_pressure(self, a, b, why: str) -> None:
        i, j = self.ip(a), self.ip(b)
        self._add(Equation(why, "", [i, j], "linear", self.P_ref, {i: 1.0, j: -1.0}, 0.0))

    def pressure_diff(self, a, b, dp: float, why: str, scale: float | None = None) -> None:
        """P_a − P_b = dp."""
        i, j = self.ip(a), self.ip(b)
        self._add(Equation(why, "", [i, j], "linear", scale or max(abs(dp), 1e-3 * self.P_ref, 1e-3),
                           {i: 1.0, j: -1.0}, float(dp)))

    def element(self, a, b, outlet_pressure: Callable[[float, float], float], why: str, flow_stream=None,
                scale: float | None = None, m_nominal: float | None = None) -> None:
        """P_b = f(m, P_a): pipes, pump curves, pressure drops that grow with flow.

        m_nominal is a typical flow for this element, used only to build a starting point."""
        im = self.im(flow_stream if flow_stream is not None else a)
        ia, ib = self.ip(a), self.ip(b)

        def func(x, im=im, ia=ia, ib=ib):
            return x[ib] - outlet_pressure(x[im], x[ia])

        self._add(Equation(why, "", [im, ia, ib], "func", scale or self.P_ref, func=func, analytic={ib: 1.0},
                           surrogate=("element", outlet_pressure, m_nominal)))

    def flow_from_pressures(self, a, b, flow: Callable[[float, float], float], why: str, flow_stream=None,
                            scale: float | None = None) -> None:
        """m = g(P_a, P_b): valves (smooth through choking)."""
        im = self.im(flow_stream if flow_stream is not None else a)
        ia, ib = self.ip(a), self.ip(b)

        def func(x, im=im, ia=ia, ib=ib):
            return x[im] - flow(x[ia], x[ib])

        self._add(Equation(why, "", [im, ia, ib], "func", scale or self.m_ref, func=func, analytic={im: 1.0},
                           surrogate=("valve", flow, None)))

    def starting_point(self, x0: np.ndarray) -> np.ndarray:
        """Solve a stand-in network in which every pipe, pump curve and valve is replaced by
        ΔP = ΔP₀ + R·m|m| (R and ΔP₀ fitted to the real element at a typical flow).

        It needs no property calls, is easy to solve from any start, and puts the real Newton iteration
        close to the answer (starting from zero flow, the real Jacobian is nearly singular)."""
        sub = Network(self.streams, self.m_ref, self.P_ref)
        sub.equations = []
        for eq in self.equations:
            if eq.kind == "linear" or eq.surrogate is None:
                sub.equations.append(eq)
                continue
            im, ia, ib = eq.vars
            kind, fn, m_nom = eq.surrogate
            Pa = float(x0[ia])
            try:
                if kind == "element":
                    m1 = max(abs(float(x0[im])), m_nom or 0.0, 1e-3 * self.m_ref)
                    dp0 = Pa - fn(0.0, Pa)
                    for _ in range(30):
                        try:
                            dpm = Pa - fn(m1, Pa) - dp0
                            break
                        except FAILURES:
                            m1 *= 0.5
                    else:
                        raise ValueError("no flow could be evaluated")
                else:
                    dp1 = max(abs(Pa - float(x0[ib])), 0.2 * Pa)
                    m1 = fn(Pa, Pa - dp1)
                    dp0, dpm = 0.0, dp1
                R = max(dpm, 1e-9 * self.P_ref) / max(m1 * m1, 1e-18)
            except FAILURES:
                sub.equations.append(eq)
                continue

            def func(x, im=im, ia=ia, ib=ib, dp0=dp0, R=R):
                m = x[im]
                return x[ia] - x[ib] - dp0 - R * m * abs(m)

            sub.equations.append(Equation(eq.why, eq.block, [im, ia, ib], "func", max(abs(dp0) + R * m1 * m1, 1e-3),
                                          func=func, analytic={ia: 1.0, ib: -1.0}))
        x = np.array(x0, dtype=float)
        # flows that start at zero make the quadratic terms flat: start them at a typical value
        for j in range(self.n):
            if abs(x[j]) < 1e-9 * self.m_ref:
                x[j] = 0.1 * self.m_ref
        try:
            x, _, _ = sub.solve(x, max_iter=80, tol=1e-6, check_rank=False)
        except NetworkError:
            return np.array(x0, dtype=float)
        return x

    # --- structure ------------------------------------------------------------------

    def structure(self) -> list[str]:
        """Plain-language problems with the specification (empty if the equations are well posed)."""
        neq, nvar = len(self.equations), 2 * self.n
        problems: list[str] = []
        rows, cols = [], []
        for i, eq in enumerate(self.equations):
            for j in set(eq.vars):
                rows.append(i)
                cols.append(j)
        if neq == 0:
            return ["No pressure–flow equations: add equipment."]
        graph = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(neq, nvar))
        match_row = maximum_bipartite_matching(graph, perm_type="column")  # row -> column or -1
        matched_cols = {int(c) for c in match_row if c >= 0}
        col_to_row = {int(c): r for r, c in enumerate(match_row) if c >= 0}
        var_eqs: dict[int, list[int]] = {}
        for i, eq in enumerate(self.equations):
            for j in set(eq.vars):
                var_eqs.setdefault(j, []).append(i)

        missing = [j for j in range(nvar) if j not in matched_cols]
        for j in missing[:4]:
            hint = (" For example, give a Sink at the end of the line a pressure, set a vessel inlet to 'Open', "
                    "or set a valve to a fixed outlet pressure." if j >= self.n else
                    " For example, fix a supply's flow, give a splitter outlet a fixed flow, or add a "
                    "Specification for this stream.")
            problems.append(f"Not enough specifications: nothing sets {self.describe_var(j)}.{hint}")
        if len(missing) > 4:
            problems.append(f"... and {len(missing) - 4} more unknowns are not set.")

        extra = [i for i, c in enumerate(match_row) if c < 0]
        reported: set[int] = set()
        for i in extra[:3]:
            # equations reachable by alternating paths from the extra equation over-determine the same unknowns
            group, frontier, seen = [i], [i], {i}
            while frontier and len(group) < 6:
                nxt = []
                for e in frontier:
                    for j in set(self.equations[e].vars):
                        r = col_to_row.get(j)
                        if r is not None and r not in seen:
                            seen.add(r)
                            group.append(r)
                            nxt.append(r)
                frontier = nxt
            if i in reported:
                continue
            reported.update(group)
            whys = "; ".join(dict.fromkeys(f"{self.equations[e].block}: {self.equations[e].why}"
                                           for e in group[:5]))
            problems.append("Too many specifications: these fix the same flows or pressures: " + whys
                            + ". Free one of them, e.g. set a supply's flow to 'As required', set a valve to "
                              "'Free pressure drop', or remove a Sink's pressure.")
        return problems

    # --- solving --------------------------------------------------------------------

    def residuals(self, x: np.ndarray) -> np.ndarray:
        return np.array([eq.residual(x) / eq.scale for eq in self.equations])

    def jacobian(self, x: np.ndarray, F: np.ndarray, var_scale: np.ndarray) -> np.ndarray:
        """d(scaled residual)/d(scaled unknown); finite differences only where needed."""
        J = np.zeros((len(self.equations), 2 * self.n))
        for i, eq in enumerate(self.equations):
            if eq.kind == "linear":
                for j, c in eq.coeffs.items():
                    J[i, j] += c / eq.scale * var_scale[j]
                continue
            base = F[i] * eq.scale
            for j in dict.fromkeys(eq.vars):
                if j in eq.analytic:
                    J[i, j] += eq.analytic[j] / eq.scale * var_scale[j]
                    continue
                h = max(abs(x[j]) * 1e-7, var_scale[j] * 1e-8)
                xp = x.copy()
                xp[j] += h
                try:
                    r1 = eq.func(xp)
                except FAILURES:
                    xp[j] = x[j] - h
                    r1 = eq.func(xp)
                    h = -h
                J[i, j] += (r1 - base) / h / eq.scale * var_scale[j]
        return J

    def rank_problem(self, J: np.ndarray) -> str | None:
        """Explain a (numerically) singular Jacobian by the unknowns it cannot fix."""
        if J.size == 0 or J.shape[0] != J.shape[1]:
            return None
        try:
            _, sv, vt = np.linalg.svd(J)
        except np.linalg.LinAlgError:
            return None
        if sv[0] <= 0 or sv[-1] / sv[0] > 1e-11:
            return None
        null = np.abs(vt[-1])
        top = [int(j) for j in np.argsort(-null)[:4] if null[j] > 0.2 * null.max()]
        kinds = {"flow" if j < self.n else "pressure" for j in top}
        names = ", ".join(dict.fromkeys(f"'{self.names[j % self.n]}'" for j in top))
        if kinds == {"flow"}:
            return (f"The flows of streams {names} are not fixed by the equations: a closed loop needs something to "
                    "set its circulating flow (a pump curve with resistances, or a Specification), and a branch "
                    "with no pressure difference across it carries no definite flow.")
        if kinds == {"pressure"}:
            return (f"The pressures of streams {names} are not fixed: either nothing sets the pressure level there "
                    "(add a pressure reference, such as a supply set to 'Pressure reference (expansion tank)'), or a "
                    "valve or pipe upstream is choked and cannot pass the flow needed downstream.")
        return (f"The flows and pressures of streams {names} cannot both be found: for example a choked valve or "
                "pipe passes the same flow whatever the downstream pressure. Fix the downstream pressure.")

    def signature(self) -> tuple:
        """Identifies the equation structure (a Jacobian can be reused while it is unchanged)."""
        return tuple((eq.block, eq.why, tuple(eq.vars)) for eq in self.equations)

    def solve(self, x0: np.ndarray, max_iter: int = 60, tol: float = 1e-8, check_rank: bool = True,
              J0: np.ndarray | None = None) -> tuple[np.ndarray, int, np.ndarray | None]:
        """Newton's method with an Armijo line search.

        The Jacobian is found by finite differences once and then kept up to date with Broyden's update,
        so later iterations (and later solves, via J0) need no extra pipe calculations. If a step fails
        with an updated Jacobian, a fresh one is computed; if that fails too, Levenberg–Marquardt steps
        are used. Returns (solution, iterations, Jacobian)."""
        x = np.array(x0, dtype=float)
        n = self.n
        var_scale = np.concatenate([np.full(n, max(self.m_ref, 1e-6)), np.full(n, max(self.P_ref, 1.0))])
        try:
            F = self.residuals(x)
        except FAILURES as exc:
            raise NetworkError(f"The starting point could not be evaluated: {exc}") from exc
        J = None if J0 is None or J0.shape != (len(F), 2 * n) else J0.copy()
        fresh = False
        checked = not check_rank
        lam = 0.0
        it = 0
        while it < max_iter:
            self.last_x = x
            if F.size == 0 or float(np.max(np.abs(F))) < tol:
                return x, it, J
            if J is None:
                J = self.jacobian(x, F, var_scale)
                fresh = True
                if not checked:
                    checked = True
                    problem = self.rank_problem(J)
                    if problem:
                        raise NetworkError(problem)
            it += 1
            try:
                if lam > 0:
                    dz = np.linalg.solve(J.T @ J + lam * np.eye(J.shape[1]), -J.T @ F)
                else:
                    dz = np.linalg.solve(J, -F)
            except np.linalg.LinAlgError:
                dz = np.linalg.lstsq(J, -F, rcond=None)[0]
            dx = dz * var_scale
            # keep pressures positive: no more than a fall to 20 % of the current value in one step
            alpha = 1.0
            for j in range(n, 2 * n):
                if dx[j] < 0 and x[j] + dx[j] < 0.2 * x[j]:
                    alpha = min(alpha, 0.8 * x[j] / -dx[j])
            f0 = 0.5 * float(F @ F)
            accepted = False
            while alpha > 1e-6:
                xt = x + alpha * dx
                try:
                    Ft = self.residuals(xt)
                    if not np.all(np.isfinite(Ft)):
                        raise ValueError("non-finite residual")
                except FAILURES:
                    alpha *= 0.5
                    continue
                if 0.5 * float(Ft @ Ft) <= (1.0 - 1e-4 * alpha) * f0 or float(np.max(np.abs(Ft))) < tol:
                    accepted = True
                    break
                alpha *= 0.5
            if accepted:
                slow = float(np.max(np.abs(Ft))) > 0.25 * float(np.max(np.abs(F)))
                step = alpha * dz
                denom = float(step @ step)
                if slow and not fresh:
                    J = None  # an old or updated Jacobian is converging slowly: recompute it
                elif denom > 0:  # Broyden's ("good") update, in scaled variables
                    J = J + np.outer((Ft - F) - J @ step, step) / denom
                    fresh = False
                x, F = xt, Ft
                lam = lam / 10.0 if lam > 1e-6 else 0.0
                continue
            if not fresh:  # the updated Jacobian may be poor: start again from a fresh one
                J = None
                continue
            if lam == 0.0:
                lam = 1e-3
            elif lam < 1e6:
                lam *= 10.0
            else:
                problem = self.rank_problem(J) if check_rank else None
                raise NetworkError(problem or "The pressure–flow equations could not be solved from this "
                                              "starting point. Check the specifications, or solve once in "
                                              "sequential mode first.")
        if float(np.max(np.abs(F))) < tol:
            return x, it, J
        worst = int(np.argmax(np.abs(F)))
        raise NetworkError(f"The pressure–flow solution did not converge (worst equation: "
                           f"{self.equations[worst].block}: {self.equations[worst].why}).")


def components(blocks: dict, streams: dict) -> list[tuple[set[str], set[str], bool]]:
    """Connected parts of the flowsheet: (block names, stream names, grounded).

    A part is grounded if it can exchange mass with the outside: it contains a
    supply, a sink or a stream leaving the system."""
    parent = {b: b for b in blocks}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for s in streams.values():
        if s.dest is not None:
            ra, rb = find(s.source[0]), find(s.dest[0])
            if ra != rb:
                parent[ra] = rb
    groups: dict[str, tuple[set, set]] = {}
    for b in blocks:
        groups.setdefault(find(b), (set(), set()))[0].add(b)
    for n, s in streams.items():
        groups[find(s.source[0])][1].add(n)
    out = []
    for blks, strs in groups.values():
        if not strs:
            continue
        grounded = (any(blocks[b].TYPE in ("feed", "sink") for b in blks)
                    or any(streams[n].dest is None for n in strs))
        out.append((blks, strs, grounded))
    return out


def loop_description(blks: set[str], streams: dict, names: set[str]) -> str:
    path = []
    for n in sorted(names):
        s = streams[n]
        if s.source[0] not in path:
            path.append(s.source[0])
    return " → ".join(path[:6]) + (" → …" if len(path) > 6 else "")


def scaled(values: list[float], floor: float) -> float:
    vals = [abs(v) for v in values if v is not None and math.isfinite(v)]
    return max(vals + [floor])
