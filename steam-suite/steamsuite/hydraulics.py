"""Pipe and valve hydraulics for water, steam and two-phase flow.

* Pipe dimensions: ASME B36.10M nominal pipe sizes and schedules.
* Friction: Darcy–Weisbach with the Colebrook–White friction factor
  (64/Re in laminar flow, interpolated across the transition region).
* Fittings: Crane TP-410 equivalent lengths, K = (L/D)·f_T, where f_T is the
  fully turbulent friction factor of clean commercial steel of the same bore.
* Two-phase friction: Müller-Steinhagen & Heck (default), Friedel,
  Chisholm (Lockhart–Martinelli) or homogeneous flow; static head and
  acceleration from the homogeneous or a drift-flux (Rouhani–Axelsson)
  void fraction.
* Compressible flow (steam) and changing phase are handled by marching along
  the pipe in segments, updating the properties from IAPWS-IF97 at each step;
  near the speed of sound the march switches to pressure steps, which find
  the choking point exactly (homogeneous-equilibrium speed of sound for wet
  steam).
* Heat loss through insulation to ambient air.
* Control valves: IEC 60534-2-1 / ISA-75.01 flow coefficient (Cv) equations.

Internal units: kPa(a), °C, kg/s, kJ/kg, m, mm (diameters and roughness).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .water import (
    P_CRIT_KPA,
    P_TRIPLE_KPA,
    WaterPropertyError,
    WaterState,
    P_sat,
    T_sat,
    state_Ph,
    state_Ps,
    state_PT,
    state_Px,
    sat_transport,
    surface_tension,
)

G_ACC = 9.80665

# --- pipe data ---------------------------------------------------------------------

# ASME B36.10M: NPS -> (outside diameter mm, {schedule: wall thickness mm})
PIPE_SIZES: dict[str, tuple[float, dict[str, float]]] = {
    "1/2": (21.3, {"40": 2.77, "80": 3.73, "STD": 2.77, "XS": 3.73}),
    "3/4": (26.7, {"40": 2.87, "80": 3.91, "STD": 2.87, "XS": 3.91}),
    "1": (33.4, {"40": 3.38, "80": 4.55, "STD": 3.38, "XS": 4.55}),
    "1-1/4": (42.2, {"40": 3.56, "80": 4.85, "STD": 3.56, "XS": 4.85}),
    "1-1/2": (48.3, {"40": 3.68, "80": 5.08, "STD": 3.68, "XS": 5.08}),
    "2": (60.3, {"40": 3.91, "80": 5.54, "STD": 3.91, "XS": 5.54}),
    "2-1/2": (73.0, {"40": 5.16, "80": 7.01, "STD": 5.16, "XS": 7.01}),
    "3": (88.9, {"40": 5.49, "80": 7.62, "STD": 5.49, "XS": 7.62}),
    "4": (114.3, {"40": 6.02, "80": 8.56, "STD": 6.02, "XS": 8.56}),
    "5": (141.3, {"40": 6.55, "80": 9.53, "STD": 6.55, "XS": 9.53}),
    "6": (168.3, {"40": 7.11, "80": 10.97, "STD": 7.11, "XS": 10.97}),
    "8": (219.1, {"40": 8.18, "80": 12.70, "STD": 8.18, "XS": 12.70}),
    "10": (273.0, {"40": 9.27, "80": 15.09, "STD": 9.27, "XS": 12.70}),
    "12": (323.8, {"40": 10.31, "80": 17.48, "STD": 9.53, "XS": 12.70}),
    "14": (355.6, {"40": 11.13, "80": 19.05, "STD": 9.53, "XS": 12.70}),
    "16": (406.4, {"40": 12.70, "80": 21.44, "STD": 9.53, "XS": 12.70}),
    "18": (457.0, {"40": 14.27, "80": 23.83, "STD": 9.53, "XS": 12.70}),
    "20": (508.0, {"40": 15.09, "80": 26.19, "STD": 9.53, "XS": 12.70}),
    "24": (610.0, {"40": 17.48, "80": 30.96, "STD": 9.53, "XS": 12.70}),
}
SCHEDULES = ("40", "80", "STD", "XS")

# absolute roughness, mm
ROUGHNESS = {
    "Commercial steel, new": 0.045,
    "Steel, used / corroded": 0.15,
    "Stainless steel": 0.015,
    "Copper / drawn tubing": 0.0015,
    "Cast iron": 0.26,
}

# Crane TP-410: equivalent length L/D (multiplied by f_T), or a fixed K
FITTINGS: dict[str, tuple[str, str, float]] = {
    "elbow_90_std": ("90° elbow, standard", "LD", 30.0),
    "elbow_90_lr": ("90° elbow, long radius (r/D 1.5)", "LD", 14.0),
    "elbow_45": ("45° elbow", "LD", 16.0),
    "bend_180": ("180° close return bend", "LD", 50.0),
    "tee_run": ("Tee, flow through run", "LD", 20.0),
    "tee_branch": ("Tee, flow through branch", "LD", 60.0),
    "gate": ("Gate valve, fully open", "LD", 8.0),
    "globe": ("Globe valve, fully open", "LD", 340.0),
    "angle": ("Angle valve, fully open", "LD", 150.0),
    "ball": ("Ball valve, full bore", "LD", 3.0),
    "butterfly": ("Butterfly valve, fully open", "LD", 45.0),
    "plug": ("Plug valve, straight-through", "LD", 18.0),
    "check_swing": ("Swing check valve", "LD", 100.0),
    "check_lift": ("Lift check valve", "LD", 600.0),
    "entrance_sharp": ("Pipe entrance, sharp-edged", "K", 0.5),
    "entrance_rounded": ("Pipe entrance, well rounded", "K", 0.04),
    "exit": ("Pipe exit into a vessel", "K", 1.0),
}

TWO_PHASE_METHODS = ("Müller-Steinhagen & Heck", "Friedel", "Chisholm (Lockhart–Martinelli)", "Homogeneous")
VOID_MODELS = ("Homogeneous", "Drift flux (Rouhani–Axelsson)")


def pipe_dimensions(nps: str, schedule: str) -> tuple[float, float]:
    """(inside diameter mm, outside diameter mm) for a nominal pipe size."""
    if nps not in PIPE_SIZES:
        raise ValueError(f"Unknown nominal pipe size {nps!r}.")
    od, walls = PIPE_SIZES[nps]
    if schedule not in walls:
        raise ValueError(f"Schedule {schedule!r} is not available for {nps}\" pipe.")
    return od - 2.0 * walls[schedule], od


def friction_factor(re: float, rel_roughness: float) -> float:
    """Darcy friction factor.

    Laminar (Re < 2000): 64/Re. Turbulent (Re > 4000): Colebrook–White, solved
    iteratively from the Swamee–Jain estimate. In between the two are
    interpolated linearly.
    """
    if re <= 0:
        return 0.0
    if re < 2000.0:
        return 64.0 / re
    if re < 4000.0:
        f_lam = 64.0 / 2000.0
        f_turb = friction_factor(4000.0, rel_roughness)
        return f_lam + (f_turb - f_lam) * (re - 2000.0) / 2000.0
    f = 0.25 / math.log10(rel_roughness / 3.7 + 5.74 / re**0.9) ** 2
    x = 1.0 / math.sqrt(f)
    for _ in range(50):
        x_new = -2.0 * math.log10(rel_roughness / 3.7 + 2.51 * x / re)
        if abs(x_new - x) < 1e-12:
            x = x_new
            break
        x = x_new
    return 1.0 / (x * x)


def fully_turbulent_friction(d_mm: float, eps_mm: float = 0.045) -> float:
    """f_T for Crane's equivalent-length method (clean commercial steel)."""
    return (2.0 * math.log10(3.7 * d_mm / eps_mm)) ** -2


def fittings_k(fittings: dict[str, float], d_mm: float) -> tuple[float, list[tuple[str, float, float]]]:
    """Total K of a set of fittings and a breakdown [(description, count, K each)]."""
    fT = fully_turbulent_friction(d_mm)
    total = 0.0
    rows = []
    for key, count in (fittings or {}).items():
        if not count:
            continue
        if key not in FITTINGS:
            raise ValueError(f"Unknown fitting type {key!r}.")
        label, kind, val = FITTINGS[key]
        k_each = val * fT if kind == "LD" else val
        total += k_each * count
        rows.append((label, float(count), k_each))
    return total, rows


def heat_loss_per_metre(t_fluid: float, t_amb: float, od_mm: float, ins_mm: float, k_ins: float,
                        h_out: float) -> float:
    """Heat lost per metre of pipe, W/m (positive = heat leaving the fluid).

    Resistances: insulation conduction ln(r2/r1)/(2πk) plus outer surface
    coefficient 1/(2π r2 h). Pipe wall and inside film are neglected (small).
    """
    r1 = od_mm / 2000.0
    r2 = r1 + max(ins_mm, 0.0) / 1000.0
    r_total = 1.0 / (2.0 * math.pi * r2 * h_out)
    if ins_mm > 0:
        r_total += math.log(r2 / r1) / (2.0 * math.pi * k_ins)
    return (t_fluid - t_amb) / r_total


# --- pipe flow -----------------------------------------------------------------------


@dataclass
class HeatLoss:
    t_ambient: float = 20.0  # °C
    insulation_mm: float = 50.0
    k_insulation: float = 0.04  # W/(m·K)
    h_outside: float = 10.0  # W/(m²·K)
    od_mm: float = 0.0


@dataclass
class PipeResult:
    P_out: float
    h_out: float
    dp_total: float  # kPa, positive = pressure falls
    dp_friction: float
    dp_fittings: float
    dp_static: float
    dp_accel: float
    heat_loss_kw: float  # positive = heat lost
    v_in: float
    v_out: float
    v_max: float
    re_in: float
    f_in: float
    mach_max: float
    segments: int
    k_total: float
    two_phase: bool
    profile: list[tuple[float, float, float, float | None, float]] = field(default_factory=list)  # (L, P, T, x, v)
    choked: bool = False  # the flow reaches the speed of sound before the end of the pipe
    L_choke: float | None = None  # distance from the inlet where it does, m
    reverse: bool = False  # flow from outlet to inlet (approximate mirror image, for solvers)
    c_out: float | None = None  # speed of sound at the outlet, m/s


class PipeChokedError(ValueError):
    """The flow reaches the speed of sound part-way along the pipe."""

    def __init__(self, message: str, result: PipeResult):
        super().__init__(message)
        self.result = result


class _PressureCollapse(Exception):
    pass


def sound_speed(st: WaterState) -> float | None:
    """Speed of sound, m/s.

    Single phase: IAPWS-IF97. Wet steam: the homogeneous equilibrium value
    c = √((∂P/∂ρ)_s), found from a small isentropic expansion. It is far lower
    than in either phase alone (a few m/s to tens of m/s for wet condensate),
    which makes it the conservative choice for predicting choked flow."""
    if st.phase != "two-phase":
        return st.w
    P2 = max(st.P * (1.0 - 2e-4), P_TRIPLE_KPA * 1.01)
    try:
        st2 = state_Ps(P2, st.s)
    except WaterPropertyError:
        return None
    drho = st.rho - st2.rho
    if drho <= 0:
        return None
    return math.sqrt((st.P - P2) * 1000.0 / drho)


def void_fraction(st: WaterState, G: float, model: str = "Homogeneous", sin_theta: float = 0.0) -> float:
    """Vapour volume fraction α of a two-phase state flowing at mass flux G (kg/(m²·s)).

    'Homogeneous': no slip, α = (x/ρ_g)/(x/ρ_g + (1−x)/ρ_f).
    'Drift flux (Rouhani–Axelsson)': α = (x/ρ_g)/[C₀(x/ρ_g + (1−x)/ρ_f) + u_gj/G] with
    u_gj = 1.18(1−x)[gσ(ρ_f − ρ_g)]^¼/ρ_f^½ and C₀ = 1 + c(1−x), c = 0.12 for
    horizontal pipes (Steiner's form) rising to 0.2 for vertical upflow (Rouhani–Axelsson).
    Downward flow uses the homogeneous value."""
    if st.phase != "two-phase":
        return 1.0 if st.is_vapour_like else 0.0
    x = st.x
    rf, rg, _, _ = sat_transport(st.P)
    a = x / rg
    b = (1.0 - x) / rf
    if not model.startswith("Drift") or sin_theta < -0.05 or G <= 0:
        return a / (a + b)
    c0 = 1.0 + (0.12 + 0.08 * min(max(sin_theta, 0.0), 1.0)) * (1.0 - x)
    sigma = surface_tension(st.T)
    ugj = 1.18 * (1.0 - x) * (G_ACC * sigma * max(rf - rg, 0.0)) ** 0.25 / math.sqrt(rf)
    return a / (c0 * (a + b) + ugj / G)


@dataclass(frozen=True)
class _Phase:
    rho: float
    mu: float


def _props(st: WaterState) -> tuple[float, float, _Phase | None, _Phase | None]:
    """(density, viscosity, saturated liquid, saturated vapour) for friction calculations."""
    if st.phase == "two-phase":
        rf, rg, mf, mg = sat_transport(st.P)
        mu = st.x * mg + (1.0 - st.x) * mf  # Cicchitti mixture viscosity
        return st.rho, mu, _Phase(rf, mf), _Phase(rg, mg)
    mu = st.mu
    if mu is None:  # saturated state built from (P, h) at x = 0 or 1
        sat = state_Px(st.P, 1.0 if st.is_vapour_like else 0.0)
        mu = sat.mu
    return st.rho, mu, None, None


def _two_phase_friction(x: float, T: float, G: float, d: float, eps: float, liq, vap, method: str) -> float:
    """Two-phase frictional pressure gradient, Pa/m."""
    rl, rg, ml, mg = liq.rho, vap.rho, liq.mu, vap.mu
    rho_h = 1.0 / (x / rg + (1.0 - x) / rl)
    if method == "Homogeneous":
        mu_h = x * mg + (1.0 - x) * ml
        f = friction_factor(G * d / mu_h, eps / d)
        return f * G * G / (2.0 * d * rho_h)
    f_lo = friction_factor(G * d / ml, eps / d)
    f_go = friction_factor(G * d / mg, eps / d)
    a = f_lo * G * G / (2.0 * d * rl)  # all-liquid gradient
    b = f_go * G * G / (2.0 * d * rg)  # all-vapour gradient
    if method == "Friedel":
        e = (1.0 - x) ** 2 + x * x * (rl * f_go) / (rg * f_lo)
        f_ = x**0.78 * (1.0 - x) ** 0.224
        h_ = (rl / rg) ** 0.91 * (mg / ml) ** 0.19 * (1.0 - mg / ml) ** 0.7
        fr = G * G / (G_ACC * d * rho_h * rho_h)
        sigma = surface_tension(T)
        we = G * G * d / (sigma * rho_h) if sigma > 0 else math.inf
        return (e + 3.24 * f_ * h_ / (fr**0.045 * we**0.035)) * a
    if method.startswith("Chisholm"):
        gl, gg = (1.0 - x) * G, x * G
        re_l, re_g = gl * d / ml, gg * d / mg
        dpl = friction_factor(re_l, eps / d) * gl * gl / (2.0 * d * rl)  # liquid flowing alone
        dpg = friction_factor(re_g, eps / d) * gg * gg / (2.0 * d * rg)  # vapour flowing alone
        tl = min(max((re_l - 2000.0) / 2000.0, 0.0), 1.0)  # 0 viscous, 1 turbulent
        tg = min(max((re_g - 2000.0) / 2000.0, 0.0), 1.0)
        c = 5.0 * (1 - tl) * (1 - tg) + 10.0 * tl * (1 - tg) + 12.0 * (1 - tl) * tg + 20.0 * tl * tg
        return dpl + c * math.sqrt(dpl * dpg) + dpg
    # Müller-Steinhagen & Heck (default)
    lam = a + 2.0 * (b - a) * x
    return lam * (1.0 - x) ** (1.0 / 3.0) + b * x**3


def _friction(st: WaterState, G: float, d: float, eps: float, method: str, tp_factor: float = 1.0) -> tuple[float, float]:
    """(frictional pressure gradient Pa/m, density for fittings losses): the part of _gradients a march needs."""
    rho, mu, liq, vap = _props(st)
    if liq is None:
        return friction_factor(G * d / mu, eps / d) * G * G / (2.0 * d * rho), rho
    return _two_phase_friction(st.x, st.T, G, d, eps, liq, vap, method) * tp_factor, rho


def _gradients(st: WaterState, G: float, d: float, eps: float, method: str,
               tp_factor: float = 1.0) -> tuple[float, float, float, float]:
    """Frictional pressure gradient (Pa/m), density used for fittings losses,
    Reynolds number and friction factor at a state."""
    rho, mu, liq, vap = _props(st)
    if liq is None:
        re = G * d / mu
        f = friction_factor(re, eps / d)
        return f * G * G / (2.0 * d * rho), rho, re, f
    grad = _two_phase_friction(st.x, st.T, G, d, eps, liq, vap, method) * tp_factor
    re = G * d / mu
    f = friction_factor(re, eps / d) if method == "Homogeneous" else friction_factor(G * d / liq.mu, eps / d)
    return grad, rho, re, f


def two_phase_gradients(st: WaterState, G: float, d_mm: float, eps_mm: float) -> dict[str, float]:
    """Frictional pressure gradient (Pa/m) of a two-phase state by every method, for comparison."""
    if st.phase != "two-phase" or G <= 0:
        return {}
    _, _, liq, vap = _props(st)
    d, eps = d_mm / 1000.0, eps_mm / 1000.0
    return {m: _two_phase_friction(st.x, st.T, G, d, eps, liq, vap, m) for m in TWO_PHASE_METHODS}


@dataclass
class _Pipe:
    """Everything the marching routines need about one pipe calculation."""

    m: float
    G: float
    P_in: float
    h_in: float
    d: float  # m
    eps: float  # m
    length: float
    dz: float
    k_total: float
    heat: HeatLoss | None
    method: str
    void_model: str
    tp_factor: float
    h_floor: float | None = None  # ambient-temperature enthalpy: heat loss cannot cool the fluid below it

    @property
    def sin_theta(self) -> float:
        return min(max(self.dz / self.length, -1.0), 1.0) if self.length > 0 else 0.0

    def rates(self, st: WaterState) -> tuple[float, float, float, float, float]:
        """(friction gradient Pa/m, density for fittings, density for static head,
        momentum-flux specific volume, heat loss W/m) at a state."""
        G = self.G
        if G > 0:
            grad, rho_k = _friction(st, G, self.d, self.eps, self.method, self.tp_factor)
        else:
            grad, rho_k = 0.0, st.rho
        rho_s, u_mom = st.rho, 1.0 / st.rho
        if st.phase == "two-phase" and self.void_model.startswith("Drift"):
            alpha = void_fraction(st, G, self.void_model, self.sin_theta)
            rf, rg, _, _ = sat_transport(st.P)
            rho_s = alpha * rg + (1.0 - alpha) * rf
            x = st.x
            u_mom = ((x * x / (alpha * rg) if alpha > 0 else 0.0)
                     + ((1.0 - x) ** 2 / ((1.0 - alpha) * rf) if alpha < 1 else 0.0))
        q = 0.0
        if self.heat is not None:
            ht = self.heat
            q = heat_loss_per_metre(st.T, ht.t_ambient, ht.od_mm, ht.insulation_mm, ht.k_insulation, ht.h_outside)
        return grad, rho_k, rho_s, u_mom, q


@dataclass
class _Totals:
    dpf: float = 0.0
    dpk: float = 0.0
    dps: float = 0.0
    dpa: float = 0.0
    q: float = 0.0
    v_max: float = 0.0
    mach: float = 0.0
    steps: int = 0
    two_phase: bool = False
    profile: list = field(default_factory=list)


MACH_SWITCH = 0.3  # above this the march continues in pressure steps (resolves choking)


def pipe_flow(m: float, P_in: float, h_in: float, d_mm: float, length: float, eps_mm: float = 0.045,
              dz: float = 0.0, k_total: float = 0.0, heat: HeatLoss | None = None,
              method: str = "Müller-Steinhagen & Heck", segments: int | None = None,
              void_model: str = "Homogeneous", tp_factor: float = 1.0, strict: bool = True) -> PipeResult:
    """Pressure and enthalpy change along a pipe (inlet conditions known).

    The pipe is divided into segments. In each, the friction, fittings (K
    spread evenly along the pipe), static head and acceleration pressure
    changes are integrated with the trapezoidal rule (a predictor, then
    corrector passes until the end pressure settles, so the result is
    second-order accurate), and the enthalpy is updated from the energy
    balance: heat loss, elevation and kinetic energy.

    The default is 20 segments (about 0.01 % numerical error for a 20 %
    pressure drop), or 60 when the pressure drop exceeds a quarter of the
    inlet pressure. A fixed count keeps the result a smooth function of the
    inputs, which goal-seeking needs.

    Where the Mach number exceeds 0.3 the rest of the pipe is integrated in
    small pressure steps instead (the length of each step follows from the
    momentum balance, the state from the energy balance). This resolves
    choking exactly: if the flow reaches the speed of sound before the end of
    the pipe, the pipe cannot pass this flow from these inlet conditions.
    With `strict` that raises PipeChokedError; otherwise the result is
    returned with `choked=True`, the sonic state as the outlet and `L_choke`.

    A negative flow returns the mirror image of the forward result (friction
    and acceleration reversed, static head unchanged), so network solvers see
    a smooth function through zero flow.
    """
    if d_mm <= 0:
        raise ValueError("Pipe inside diameter must be greater than zero.")
    if length < 0:
        raise ValueError("Pipe length cannot be negative.")
    if m < 0:
        fwd = pipe_flow(-m, P_in, h_in, d_mm, length, eps_mm, dz, k_total, None, method, segments, void_model,
                        tp_factor, strict)
        return _mirror(fwd, P_in, h_in)
    d = d_mm / 1000.0
    area = math.pi * d * d / 4.0
    st0 = state_Ph(P_in, h_in)
    pipe = _Pipe(m=m, G=m / area, P_in=P_in, h_in=h_in, d=d, eps=eps_mm / 1000.0, length=length, dz=dz,
                 k_total=k_total, heat=heat, method=method, void_model=void_model, tp_factor=tp_factor)
    if heat is not None:
        pipe.h_floor = _ambient_enthalpy(P_in, heat.t_ambient)
    if segments is not None:
        res = _march(pipe, st0, max(int(segments), 1))
    else:
        res = _march(pipe, st0, 20)
        if not res.choked and res.dp_total > 0.25 * P_in:
            res = _march(pipe, st0, 60)
    if res.choked and strict:
        raise PipeChokedError(
            f"The flow is choked: it reaches the speed of sound {res.L_choke:.3g} m along the pipe "
            f"(pressure {res.P_out:.4g} kPa(a) there), so the pipe cannot pass this flow. Increase the pipe size "
            "or shorten the run.", res)
    return res


def _ambient_enthalpy(P: float, t_amb: float) -> float | None:
    try:
        if P < P_CRIT_KPA and abs(t_amb - T_sat(P)) < 1e-6:
            return None
        return state_PT(P, t_amb).h
    except WaterPropertyError:
        return None


def _mirror(r: PipeResult, P_in: float, h_in: float) -> PipeResult:
    dp = -(r.dp_friction + r.dp_fittings + r.dp_accel) + r.dp_static
    return PipeResult(P_out=P_in - dp, h_out=h_in, dp_total=dp, dp_friction=-r.dp_friction,
                      dp_fittings=-r.dp_fittings, dp_static=r.dp_static, dp_accel=-r.dp_accel, heat_loss_kw=0.0,
                      v_in=-r.v_in, v_out=-r.v_out, v_max=r.v_max, re_in=r.re_in, f_in=r.f_in, mach_max=r.mach_max,
                      segments=r.segments, k_total=r.k_total, two_phase=r.two_phase, profile=[], reverse=True)


def _limit_heat(pipe: _Pipe, h: float, dh_heat: float) -> float:
    """Heat loss (or gain) cannot take the fluid past ambient temperature (matters at very low flow)."""
    if pipe.h_floor is None:
        return dh_heat
    room = h - pipe.h_floor  # positive if warmer than ambient
    if dh_heat > 0:
        return min(dh_heat, max(room, 0.0))
    return max(dh_heat, min(room, 0.0))


def _march(pipe: _Pipe, st0: WaterState, n: int) -> PipeResult:
    G, m = pipe.G, pipe.m
    dl = pipe.length / n
    dzs = pipe.dz / n
    dk = pipe.k_total / n
    P, h, st = pipe.P_in, pipe.h_in, st0
    v_in = G / st0.rho
    _, _, re_in, f_in = _gradients(st0, G, pipe.d, pipe.eps, pipe.method) if G > 0 else (0, 0, 0.0, 0.0)
    c0 = sound_speed(st0)
    tot = _Totals(v_max=v_in, mach=(v_in / c0) if c0 else 0.0, two_phase=st0.phase == "two-phase",
                  profile=[(0.0, P, st0.T, st0.x, v_in)])

    def too_low(p):
        if p <= pipe.P_in * 0.02 or p <= 0.7:
            raise _PressureCollapse

    for i in range(n):
        if tot.mach > MACH_SWITCH:
            return _pressure_march(pipe, st, P, h, i * dl, tot, v_in, re_in, f_in)
        try:
            g1, r1k, r1s, u1, q1 = pipe.rates(st)
            v1 = G / st.rho
            # predictor (explicit Euler)
            P_end = P - (g1 * dl + dk * G * G / (2 * r1k)) / 1000.0 - r1s * G_ACC * dzs / 1000.0
            dh_q = _limit_heat(pipe, h, q1 * dl / 1000.0 / m) if m > 0 else 0.0
            h_end = h - dh_q - G_ACC * dzs / 1000.0
            too_low(P_end)
            st_end = state_Ph(P_end, h_end)
            # trapezoidal corrector passes, repeated until the outlet pressure settles (two are enough at
            # low Mach number; the acceleration term needs more as the velocity approaches the speed of sound)
            P_prev = None
            for k in range(12):
                if k >= 2 and abs(P_end - P_prev) <= 1e-10 * P:
                    break
                P_prev = P_end
                g2, r2k, r2s, u2, q2 = pipe.rates(st_end)
                dp_f = 0.5 * (g1 + g2) * dl / 1000.0
                dp_k = dk * G * G / (2.0 * 0.5 * (r1k + r2k)) / 1000.0
                dp_s = 0.5 * (r1s + r2s) * G_ACC * dzs / 1000.0
                dp_a = G * G * (u2 - u1) / 1000.0
                dh_q = _limit_heat(pipe, h, 0.5 * (q1 + q2) * dl / 1000.0 / m) if m > 0 else 0.0
                v2 = G / st_end.rho
                P_end = P - dp_f - dp_k - dp_s - dp_a
                h_end = h - dh_q - G_ACC * dzs / 1000.0 - (v2 * v2 - v1 * v1) / 2000.0
                too_low(P_end)
                st_end = state_Ph(P_end, h_end)
        except (_PressureCollapse, WaterPropertyError):
            return _pressure_march(pipe, st, P, h, i * dl, tot, v_in, re_in, f_in)
        v_new = G / st_end.rho
        c = sound_speed(st_end)
        mach_end = v_new / c if c else 0.0
        if mach_end > MACH_SWITCH:  # redo this segment in pressure steps
            return _pressure_march(pipe, st, P, h, i * dl, tot, v_in, re_in, f_in)
        tot.mach = max(tot.mach, mach_end)
        tot.two_phase = tot.two_phase or st_end.phase == "two-phase"
        tot.dpf += dp_f
        tot.dpk += dp_k
        tot.dps += dp_s
        tot.dpa += dp_a
        tot.q += dh_q * m
        tot.steps += 1
        P, h, st = P_end, h_end, st_end
        tot.v_max = max(tot.v_max, v_new)
        tot.profile.append(((i + 1) * dl, P, st.T, st.x, v_new))

    return _finish(pipe, tot, P, h, st, v_in, re_in, f_in)


def _finish(pipe: _Pipe, tot: _Totals, P: float, h: float, st: WaterState, v_in: float, re_in: float, f_in: float,
            choked: bool = False, L_choke: float | None = None) -> PipeResult:
    profile = tot.profile
    if len(profile) > 121:  # keep charts light
        step = (len(profile) - 1) / 120.0
        profile = [profile[round(i * step)] for i in range(121)]
        profile[-1] = tot.profile[-1]
    return PipeResult(
        P_out=P, h_out=h, dp_total=pipe.P_in - P, dp_friction=tot.dpf, dp_fittings=tot.dpk, dp_static=tot.dps,
        dp_accel=tot.dpa, heat_loss_kw=tot.q, v_in=v_in, v_out=pipe.G / st.rho, v_max=tot.v_max, re_in=re_in,
        f_in=f_in, mach_max=tot.mach, segments=tot.steps, k_total=pipe.k_total, two_phase=tot.two_phase,
        profile=profile, choked=choked, L_choke=L_choke, c_out=sound_speed(st))


def _pressure_march(pipe: _Pipe, st: WaterState, P: float, h: float, L_done: float, tot: _Totals,
                    v_in: float, re_in: float, f_in: float) -> PipeResult:
    """Continue the march in pressure steps from (P, h) at distance L_done.

    For each step to a lower pressure P₂ the state follows from the energy
    balance (h + v²/2 falls only by heat loss and elevation), and the length
    of the step from the momentum balance:
        ΔL = [ (P₁ − P₂) − G²(u₂ − u₁) ] / [ (dP/dz)_friction+fittings + ρ g sinθ ]
    ΔL shrinks to zero where the velocity reaches the speed of sound: the
    largest length reachable is the choking length.
    """
    G, m = pipe.G, pipe.m
    if G <= 0:
        raise ValueError("The pressure falls to almost nothing along the pipe with no flow: check the elevation.")
    sin_t = pipe.sin_theta
    kpm = pipe.k_total / pipe.length if pipe.length > 0 else 0.0
    L_left = pipe.length - L_done
    p_floor = max(P_TRIPLE_KPA * 1.05, 0.005 * pipe.P_in)

    def frates(state):
        grad, rho_k, rho_s, u_mom, q = pipe.rates(state)
        return grad, kpm * G * G / (2.0 * rho_k), rho_s, u_mom, q

    F1, K1, rs1, u1, q1 = frates(st)
    v1 = G / st.rho
    H = h + v1 * v1 / 2000.0  # kJ/kg

    def step(P2: float, dL_guess: float):
        """State and length of a step from the current point to pressure P2."""
        dL = max(dL_guess, 0.0)
        q2 = q1
        h2 = h
        st2 = None
        for _ in range(iterate):
            H2 = H - G_ACC * sin_t * dL / 1000.0 - (0.5 * (q1 + q2) * dL / 1000.0 / m)
            h2 = _energy_state(P2, H2, h2, G)
            st2 = state_Ph(P2, h2)
            F2, K2, rs2, u2, q2 = frates(st2)
            num_ = (P - P2) * 1000.0 - G * G * (u2 - u1)
            den = 0.5 * (F1 + F2) + 0.5 * (K1 + K2) + 0.5 * (rs1 + rs2) * G_ACC * sin_t
            if den <= 0:
                raise ValueError("The pressure rises along this pipe (downhill flow), so it cannot be integrated in "
                                 "pressure steps; use more segments.")
            dL = num_ / den
        return st2, h2, dL, (F1, F2, K1, K2, rs1, rs2, u1, u2, q1, q2)

    dL_prev = 0.0
    mach = tot.mach
    iterate = 3 if (sin_t != 0.0 or pipe.heat is not None) else 1  # dL only feeds back through elevation and heat
    for _ in range(4000):
        # pressure steps: 0.4 % near choking, up to 1.2 % where the Mach number is lower
        P2 = P * (1.0 - 0.004 * min(max((0.6 / max(mach, 1e-6)) ** 2, 1.0), 3.0))
        if P2 < p_floor:
            raise ValueError("The pressure falls to almost nothing along the pipe: the pipe is far too small for "
                             "this flow (or too long). Increase the pipe size.")
        st2, h2, dL, parts = step(P2, dL_prev)
        c2 = sound_speed(st2)
        v2 = G / st2.rho
        mach2 = v2 / c2 if c2 else 0.0
        if dL <= 0 or mach2 >= 1.0:
            # the sonic point lies inside this step: find the end pressure giving the longest step
            Pc, sc, hc, Lc, pc = _longest_step(step, P2, P, dL_prev)
            if Lc >= L_left:
                P_end, st_e, h_e, dL_e, parts_e = _step_to_length(step, Pc, P, L_left, dL_prev)
                _add_step(tot, pipe, parts_e, P, P_end, dL_e, L_done + dL_e, st_e)
                return _finish(pipe, tot, P_end, h_e, st_e, v_in, re_in, f_in)
            _add_step(tot, pipe, pc, P, Pc, Lc, L_done + Lc, sc)
            tot.mach = max(tot.mach, 1.0)
            return _finish(pipe, tot, Pc, hc, sc, v_in, re_in, f_in, choked=True, L_choke=L_done + Lc)
        if dL >= L_left:
            P_end, st_e, h_e, dL_e, parts_e = _step_to_length(step, P2, P, L_left, dL)
            _add_step(tot, pipe, parts_e, P, P_end, dL_e, L_done + dL_e, st_e)
            return _finish(pipe, tot, P_end, h_e, st_e, v_in, re_in, f_in)
        _add_step(tot, pipe, parts, P, P2, dL, L_done + dL, st2)
        tot.mach = max(tot.mach, mach2)
        mach = mach2
        L_done += dL
        L_left -= dL
        P, h, st = P2, h2, st2
        F1, K1, rs1, u1, q1 = frates(st)
        H = h + v2 * v2 / 2000.0
        dL_prev = dL
    raise ValueError("The pipe calculation did not finish (too many pressure steps).")


def _energy_state(P2: float, H2: float, h_guess: float, G: float) -> float:
    """Static enthalpy h at pressure P2 with h + v²/2 = H2 (v = G/ρ(P2, h))."""

    def resid(hh):
        v = G / state_Ph(P2, hh).rho
        return hh + v * v / 2000.0 - H2

    h_a = h_guess
    f_a = resid(h_a)
    h_b = H2 - (f_a + H2 - h_a)  # fixed-point step
    for _ in range(12):
        f_b = resid(h_b)
        if abs(f_b) < 1e-9:
            return h_b
        if f_b == f_a:
            break
        h_a, h_b, f_a = h_b, h_b - f_b * (h_b - h_a) / (f_b - f_a), f_b
    return h_b


def _longest_step(step, P_lo: float, P_hi: float, dL_guess: float):
    """Golden-section search for the end pressure in (P_lo, P_hi) that maximises the step length."""
    gr = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = P_lo, P_hi
    best = None

    def length(Pe):
        nonlocal best
        try:
            r = step(Pe, dL_guess)
        except (ValueError, WaterPropertyError):
            return -math.inf
        if best is None or r[2] > best[1][2]:
            best = (Pe, r)
        return r[2]

    c = b - gr * (b - a)
    d = a + gr * (b - a)
    fc, fd = length(c), length(d)
    for _ in range(40):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = length(c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = length(d)
        if b - a < 1e-7 * P_hi:
            break
    Pe, (st2, h2, dL, parts) = best
    return Pe, st2, h2, dL, parts


def _step_to_length(step, P_lo: float, P_hi: float, target: float, dL_guess: float):
    """End pressure of a step of exactly `target` metres (the step length rises as the end pressure falls)."""
    a, b = P_lo, P_hi  # length(a) >= target > length(b) = 0
    r = None
    for _ in range(60):
        mid = 0.5 * (a + b)
        r = step(mid, dL_guess)
        if r[2] >= target:
            a = mid
        else:
            b = mid
        if b - a < 1e-10 * P_hi:
            break
    Pe = a
    st2, h2, dL, parts = step(Pe, dL_guess)
    return Pe, st2, h2, dL, parts


def _add_step(tot: _Totals, pipe: _Pipe, parts, P1: float, P2: float, dL: float, L: float, st2: WaterState) -> None:
    F1, F2, K1, K2, rs1, rs2, u1, u2, q1, q2 = parts
    G = pipe.G
    tot.dpf += 0.5 * (F1 + F2) * dL / 1000.0
    tot.dpk += 0.5 * (K1 + K2) * dL / 1000.0
    tot.dps += 0.5 * (rs1 + rs2) * G_ACC * pipe.sin_theta * dL / 1000.0
    tot.dpa += G * G * (u2 - u1) / 1000.0
    tot.q += 0.5 * (q1 + q2) * dL / 1000.0
    tot.steps += 1
    v2 = G / st2.rho
    tot.v_max = max(tot.v_max, v2)
    tot.two_phase = tot.two_phase or st2.phase == "two-phase"
    tot.profile.append((L, P2, st2.T, st2.x, v2))


def velocity_guidance(st: WaterState, v: float) -> str | None:
    """Warning text if the velocity is above common design guidelines."""
    if st.phase == "two-phase":
        ve = 122.0 / math.sqrt(st.rho)  # API RP 14E erosional velocity, C = 100
        if v > ve:
            return (f"Velocity {v:.1f} m/s exceeds the erosional velocity for this two-phase mixture "
                    f"({ve:.1f} m/s, API RP 14E with C = 100).")
        return None
    if st.is_liquid_like or st.phase == "liquid":
        if v > 3.0:
            return f"Water velocity {v:.2f} m/s is above the usual limit of about 3 m/s (erosion, noise, water hammer)."
        return None
    limit = 40.0 if (st.superheat is None or st.superheat < 10) else 60.0
    if v > limit:
        kind = "saturated" if limit == 40.0 else "superheated"
        return f"Steam velocity {v:.1f} m/s is above the usual limit of about {limit:.0f} m/s for {kind} steam (noise, erosion)."
    return None


# --- control valves (IEC 60534-2-1, Fp = 1) ------------------------------------------------

N1 = 0.0865  # Q in m³/h, ΔP in kPa
N6 = 2.73  # W in kg/h, P in kPa, ρ in kg/m³
RHO_WATER_REF = 999.0


def characteristic(opening: float, kind: str, rangeability: float = 50.0) -> float:
    """Fraction of rated Cv at a given opening (0–1)."""
    l = min(max(opening, 0.0), 1.0)
    if kind == "Equal percentage":
        return rangeability ** (l - 1.0) if l > 0 else 0.0
    if kind == "Quick opening":
        return math.sqrt(l)
    return l


def isentropic_exponent(st: WaterState) -> float:
    if st.w and st.is_vapour_like:
        return st.w * st.w * st.rho / (st.P * 1000.0)
    return 1.135  # wet / saturated steam


@dataclass
class ValveSizing:
    cv: float
    regime: str  # 'liquid', 'vapour', 'two-phase'
    choked: bool
    flashing: bool
    cavitation: bool
    x: float | None = None
    x_eff: float | None = None
    y: float | None = None
    dp_choked: float | None = None
    notes: list[str] = field(default_factory=list)


def valve_cv_required(m: float, inlet: WaterState, P2: float, fl: float = 0.9, xt: float = 0.7) -> ValveSizing:
    """Flow coefficient Cv needed to pass m (kg/s) from inlet to P2 (kPa(a))."""
    P1 = inlet.P
    dp = P1 - P2
    if dp <= 0:
        return ValveSizing(cv=float("inf") if m > 0 else 0.0, regime="liquid", choked=False, flashing=False,
                           cavitation=False, notes=["No pressure drop across the valve."])
    W = m * 3600.0
    if inlet.is_liquid_like:
        pv = P_sat(inlet.T) if inlet.T < 373.9 else P1
        ff = 0.96 - 0.28 * math.sqrt(pv / P_CRIT_KPA)
        dp_max = fl * fl * (P1 - ff * pv)
        choked = dp >= dp_max
        dp_eff = min(dp, dp_max)
        q = W / inlet.rho  # m³/h
        cv = q / N1 * math.sqrt(inlet.rho / RHO_WATER_REF / dp_eff) if dp_eff > 0 else float("inf")
        flashing = P2 < pv
        cavitation = choked and not flashing
        notes = []
        if flashing:
            notes.append("Outlet pressure is below the vapour pressure: the water flashes in the valve.")
        elif cavitation:
            notes.append("The pressure drop exceeds the choked limit: severe cavitation is likely.")
        return ValveSizing(cv=cv, regime="liquid", choked=choked, flashing=flashing, cavitation=cavitation,
                           dp_choked=dp_max, notes=notes)
    gamma = isentropic_exponent(inlet)
    f_gamma = gamma / 1.40
    x = dp / P1
    x_ch = f_gamma * xt
    choked = x >= x_ch
    x_eff = min(x, x_ch)
    y = 1.0 - x_eff / (3.0 * x_ch)
    cv = W / (N6 * y * math.sqrt(x_eff * P1 * inlet.rho))
    regime = "two-phase" if inlet.phase == "two-phase" and inlet.x < 0.98 else "vapour"
    notes = []
    if regime == "two-phase":
        notes.append("Two-phase inlet: Cv uses the gas equation with the homogeneous mixture density (approximate).")
    if choked:
        notes.append("The flow is choked (critical): lowering the outlet pressure further does not increase flow.")
    return ValveSizing(cv=cv, regime=regime, choked=choked, flashing=False, cavitation=False, x=x, x_eff=x_eff, y=y,
                       notes=notes)


def valve_outlet_pressure(m: float, inlet: WaterState, cv: float, fl: float = 0.9, xt: float = 0.7) -> tuple[float, ValveSizing]:
    """Outlet pressure for a flow m (kg/s) through a valve with flow coefficient cv."""
    if cv <= 0:
        raise ValueError("The valve is closed (zero Cv) but there is flow through it.")
    P1 = inlet.P
    W = m * 3600.0
    if m <= 0:
        return P1, valve_cv_required(0.0, inlet, P1)
    if inlet.is_liquid_like:
        q = W / inlet.rho
        dp = inlet.rho / RHO_WATER_REF * (q / (N1 * cv)) ** 2
        pv = P_sat(inlet.T) if inlet.T < 373.9 else P1
        ff = 0.96 - 0.28 * math.sqrt(pv / P_CRIT_KPA)
        dp_max = fl * fl * (P1 - ff * pv)
        if dp > dp_max:
            raise ValueError(f"The flow exceeds the valve's choked (cavitating) capacity: it would need a pressure "
                             f"drop of {dp:.0f} kPa but at most {dp_max:.0f} kPa is usable. Increase Cv or opening.")
        P2 = P1 - dp
        return P2, valve_cv_required(m, inlet, P2, fl, xt)
    gamma = isentropic_exponent(inlet)
    x_ch = gamma / 1.40 * xt

    def flow_at(x: float) -> float:
        y = 1.0 - x / (3.0 * x_ch)
        return N6 * cv * y * math.sqrt(x * P1 * inlet.rho)

    w_max = flow_at(x_ch)
    if W > w_max * (1 + 1e-9):
        raise ValueError(f"The flow ({W:.0f} kg/h) exceeds the valve's choked capacity ({w_max:.0f} kg/h). "
                         "Increase Cv or opening.")
    lo, hi = 0.0, x_ch
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if flow_at(mid) < W:
            lo = mid
        else:
            hi = mid
    x = 0.5 * (lo + hi)
    P2 = P1 * (1.0 - x)
    return P2, valve_cv_required(m, inlet, P2, fl, xt)


def valve_flow(inlet: WaterState, P2: float, cv: float, fl: float = 0.9, xt: float = 0.7) -> float:
    """Mass flow (kg/s) through a valve with flow coefficient cv from the inlet state to P2 (kPa(a)).

    The inverse of valve_cv_required: the same IEC 60534 equations solved for
    the flow, including the choked limits. For network solvers the result is
    smooth through zero pressure drop (√ΔP is replaced by ΔP/√(|ΔP| + δ) with a
    tiny δ) and negative when P2 is above the inlet pressure (mirror image)."""
    if cv <= 0:
        return 0.0
    P1 = inlet.P
    dp = P1 - P2
    sign = 1.0 if dp >= 0 else -1.0
    dp = abs(dp)
    reg = 1e-6 * P1  # kPa
    if inlet.is_liquid_like:
        pv = P_sat(inlet.T) if inlet.T < 373.9 else P1
        ff = 0.96 - 0.28 * math.sqrt(pv / P_CRIT_KPA)
        dp_max = max(fl * fl * (P1 - ff * pv), 0.0)
        dp_eff = min(dp, dp_max)
        q = N1 * cv * dp_eff / math.sqrt((dp_eff + reg) * inlet.rho / RHO_WATER_REF)  # m³/h
        return sign * q * inlet.rho / 3600.0
    gamma = isentropic_exponent(inlet)
    x_ch = gamma / 1.40 * xt
    x = min(dp / P1, x_ch)
    y = 1.0 - x / (3.0 * x_ch)
    w = N6 * cv * y * x * math.sqrt(P1 * inlet.rho / (x + reg / P1))  # kg/h
    return sign * w / 3600.0


def npsh_available(inlet: WaterState) -> float | None:
    """Net positive suction head available at the pump inlet, m (velocity head neglected)."""
    if not inlet.is_liquid_like or inlet.T >= 373.9:
        return None
    try:
        pv = P_sat(inlet.T)
    except WaterPropertyError:
        return None
    return (inlet.P - pv) * 1000.0 / (inlet.rho * G_ACC)
