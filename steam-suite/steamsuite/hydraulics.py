"""Pipe and valve hydraulics for water, steam and two-phase flow.

* Pipe dimensions: ASME B36.10M nominal pipe sizes and schedules.
* Friction: Darcy–Weisbach with the Colebrook–White friction factor
  (64/Re in laminar flow, interpolated across the transition region).
* Fittings: Crane TP-410 equivalent lengths, K = (L/D)·f_T, where f_T is the
  fully turbulent friction factor of clean commercial steel of the same bore.
* Two-phase flow: homogeneous model or the Müller-Steinhagen & Heck
  correlation for friction; homogeneous density for static head and
  acceleration.
* Compressible flow (steam) and changing phase are handled by marching along
  the pipe in segments, updating the properties from IAPWS-IF97 at each step.
* Heat loss through insulation to ambient air.
* Control valves: IEC 60534-2-1 / ISA-75.01 flow coefficient (Cv) equations.

Internal units: kPa(a), °C, kg/s, kJ/kg, m, mm (diameters and roughness).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .water import P_CRIT_KPA, WaterPropertyError, WaterState, P_sat, state_Ph, state_Px

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

TWO_PHASE_METHODS = ("Müller-Steinhagen & Heck", "Homogeneous")


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


def _props(st: WaterState) -> tuple[float, float, float | None, float | None]:
    """(density, viscosity, liquid/vapour split info) for friction calculations."""
    if st.phase == "two-phase":
        liq, vap = state_Px(st.P, 0.0), state_Px(st.P, 1.0)
        mu = st.x * vap.mu + (1.0 - st.x) * liq.mu  # Cicchitti mixture viscosity
        return st.rho, mu, liq, vap
    mu = st.mu
    if mu is None:  # saturated state built from (P, h) at x = 0 or 1
        sat = state_Px(st.P, 1.0 if st.is_vapour_like else 0.0)
        mu = sat.mu
    return st.rho, mu, None, None


def _gradients(st: WaterState, G: float, d: float, eps: float, method: str) -> tuple[float, float, float, float]:
    """Frictional pressure gradient (Pa/m), density used for K and static head,
    Reynolds number and friction factor at a state."""
    rho, mu, liq, vap = _props(st)
    if liq is None:
        re = G * d / mu
        f = friction_factor(re, eps / d)
        return f * G * G / (2.0 * d * rho), rho, re, f
    x = st.x
    re_lo = G * d / liq.mu
    re_go = G * d / vap.mu
    f_lo = friction_factor(re_lo, eps / d)
    f_go = friction_factor(re_go, eps / d)
    if method == "Homogeneous":
        re = G * d / mu
        f = friction_factor(re, eps / d)
        return f * G * G / (2.0 * d * rho), rho, re, f
    a = f_lo * G * G / (2.0 * d * liq.rho)  # all-liquid gradient
    b = f_go * G * G / (2.0 * d * vap.rho)  # all-vapour gradient
    lam = a + 2.0 * (b - a) * x
    grad = lam * (1.0 - x) ** (1.0 / 3.0) + b * x**3
    re = G * d / mu
    return grad, rho, re, f_lo


def pipe_flow(m: float, P_in: float, h_in: float, d_mm: float, length: float, eps_mm: float = 0.045,
              dz: float = 0.0, k_total: float = 0.0, heat: HeatLoss | None = None,
              method: str = "Müller-Steinhagen & Heck", segments: int | None = None) -> PipeResult:
    """Pressure and enthalpy change along a pipe (inlet conditions known).

    The pipe is divided into segments. In each, the friction, fittings (K
    spread evenly along the pipe), static head and acceleration pressure
    changes are integrated with the trapezoidal rule (a predictor and two
    corrector passes, so the result is second-order accurate), and the
    enthalpy is updated from the energy balance: heat loss, elevation and
    kinetic energy.

    The default is 20 segments (about 0.01 % numerical error for a 20 %
    pressure drop), or 60 when the pressure drop exceeds a quarter of the
    inlet pressure. A fixed count keeps the result a smooth function of the
    inputs, which goal-seeking needs.
    """
    if d_mm <= 0:
        raise ValueError("Pipe inside diameter must be greater than zero.")
    if length < 0:
        raise ValueError("Pipe length cannot be negative.")
    d = d_mm / 1000.0
    eps = eps_mm / 1000.0
    area = math.pi * d * d / 4.0
    G = max(m, 0.0) / area
    st0 = state_Ph(P_in, h_in)
    if segments is not None:
        return _march(m, G, P_in, h_in, d, eps, length, dz, k_total, heat, method, segments, st0)
    try:
        res = _march(m, G, P_in, h_in, d, eps, length, dz, k_total, heat, method, 20, st0)
    except (ValueError, WaterPropertyError):
        return _march(m, G, P_in, h_in, d, eps, length, dz, k_total, heat, method, 60, st0)
    if res.dp_total > 0.25 * P_in:
        return _march(m, G, P_in, h_in, d, eps, length, dz, k_total, heat, method, 60, st0)
    return res


def _march(m, G, P_in, h_in, d, eps, length, dz, k_total, heat, method, n, st0) -> PipeResult:
    dl = length / n
    dzs = dz / n
    dk = k_total / n
    P, h = P_in, h_in
    st = st0
    v_in = G / st0.rho
    _, _, re_in, f_in = _gradients(st0, G, d, eps, method) if G > 0 else (0, 0, 0.0, 0.0)
    dpf = dpk = dps = dpa = q_tot = 0.0
    v_max = v_in
    mach = (v_in / st0.w) if st0.w else 0.0
    profile = [(0.0, P, st0.T, st0.x, v_in)]
    two_phase = st0.phase == "two-phase"

    def rates(state):
        if G > 0:
            grad, rho_k, _, _ = _gradients(state, G, d, eps, method)
        else:
            grad, rho_k = 0.0, state.rho
        q = heat_loss_per_metre(state.T, heat.t_ambient, heat.od_mm, heat.insulation_mm, heat.k_insulation,
                                heat.h_outside) if heat is not None else 0.0
        return grad, rho_k, q

    def too_low(p):
        if p <= P_in * 0.02 or p <= 0.7:
            raise ValueError("The pressure falls to almost nothing along the pipe: the pipe is far too small for "
                             "this flow (or too long). Increase the pipe size.")

    for i in range(n):
        g1, r1, q1 = rates(st)
        v1 = G / st.rho
        # predictor (explicit Euler, including acceleration with the start density)
        P_end = P - (g1 * dl + dk * G * G / (2 * r1)) / 1000.0 - r1 * G_ACC * dzs / 1000.0
        h_end = h - (q1 * dl / 1000.0 / m if m > 0 else 0.0) - G_ACC * dzs / 1000.0
        too_low(P_end)
        st_end = state_Ph(P_end, h_end)
        # two trapezoidal corrector passes
        for _ in range(2):
            g2, r2, q2 = rates(st_end)
            rho_avg = 0.5 * (r1 + r2)
            dp_f = 0.5 * (g1 + g2) * dl / 1000.0
            dp_k = dk * G * G / (2.0 * rho_avg) / 1000.0
            dp_s = rho_avg * G_ACC * dzs / 1000.0
            dp_a = G * G * (1.0 / st_end.rho - 1.0 / st.rho) / 1000.0
            q_seg = 0.5 * (q1 + q2) * dl / 1000.0
            v2 = G / st_end.rho
            P_end = P - dp_f - dp_k - dp_s - dp_a
            h_end = (h - (q_seg / m if m > 0 else 0.0) - G_ACC * dzs / 1000.0
                     - (v2 * v2 - v1 * v1) / 2000.0)
            too_low(P_end)
            st_end = state_Ph(P_end, h_end)
        v_new = G / st_end.rho
        if st_end.w:
            mach = max(mach, v_new / st_end.w)
            if v_new >= st_end.w:
                raise ValueError("The flow is choked: the steam velocity reaches the speed of sound in the pipe. "
                                 "Increase the pipe size.")
        two_phase = two_phase or st_end.phase == "two-phase"
        dpf += dp_f
        dpk += dp_k
        dps += dp_s
        dpa += dp_a
        q_tot += q_seg
        P, h, st = P_end, h_end, st_end
        v_max = max(v_max, v_new)
        profile.append(((i + 1) * dl, P, st.T, st.x, v_new))

    return PipeResult(
        P_out=P, h_out=h, dp_total=P_in - P, dp_friction=dpf, dp_fittings=dpk, dp_static=dps, dp_accel=dpa,
        heat_loss_kw=q_tot, v_in=v_in, v_out=G / st.rho, v_max=v_max, re_in=re_in, f_in=f_in, mach_max=mach,
        segments=n, k_total=k_total, two_phase=two_phase, profile=profile,
    )


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


def npsh_available(inlet: WaterState) -> float | None:
    """Net positive suction head available at the pump inlet, m (velocity head neglected)."""
    if not inlet.is_liquid_like or inlet.T >= 373.9:
        return None
    try:
        pv = P_sat(inlet.T)
    except WaterPropertyError:
        return None
    return (inlet.P - pv) * 1000.0 / (inlet.rho * G_ACC)
