"""Two-stream heat exchanger analysis by zones.

Water and steam change phase, so the heat capacity is not constant and a
single log-mean temperature difference (LMTD) is not accurate. Instead the
duty is divided into equal steps. At each step the hot and cold temperatures
are found from IAPWS-IF97 (pressure varies linearly along each side), and

    UA = Σ ΔQ_i / LMTD_i

(the "weighted" method). The smallest hot-to-cold temperature difference is
the minimum approach; zero or negative means a temperature cross.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.optimize import brentq

from .water import WaterPropertyError, state_Ph, state_PT


@dataclass
class Side:
    m: float  # kg/s
    P_in: float  # kPa(a)
    h_in: float  # kJ/kg
    P_out: float  # kPa(a)


@dataclass
class Profile:
    duty: float
    min_approach: float
    ua: float
    points: list[tuple[float, float, float]] = field(default_factory=list)  # (Q from cold end, T_hot, T_cold)
    pinch_at: float = 0.0  # Q at the minimum approach


def _lmtd(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    if abs(a - b) < 1e-9 * max(a, b):
        return a
    return (a - b) / math.log(a / b)


def profile(hot: Side, cold: Side, q: float, counter: bool = True, n: int = 20) -> Profile:
    """Temperature profile, minimum approach and required UA for a duty q (kW)."""
    if q < 0:
        raise ValueError("Heat duty cannot be negative (the hot side must give heat to the cold side).")
    pts = []
    h_co = cold.h_in + (q / cold.m if cold.m > 0 else 0.0)
    for k in range(n + 1):
        f = k / n  # fraction of duty transferred, measured from the hot inlet end
        P_h = hot.P_in + (hot.P_out - hot.P_in) * f
        h_h = hot.h_in - (q * f / hot.m if hot.m > 0 else 0.0)
        if counter:
            P_c = cold.P_out + (cold.P_in - cold.P_out) * f
            h_c = h_co - (q * f / cold.m if cold.m > 0 else 0.0)
            q_from_cold_end = q * (1 - f)
        else:
            P_c = cold.P_in + (cold.P_out - cold.P_in) * f
            h_c = cold.h_in + (q * f / cold.m if cold.m > 0 else 0.0)
            q_from_cold_end = q * f
        T_h = state_Ph(P_h, h_h).T
        T_c = state_Ph(P_c, h_c).T
        pts.append((q_from_cold_end, T_h, T_c))
    dts = [th - tc for _, th, tc in pts]
    i_min = min(range(len(dts)), key=lambda i: dts[i])
    ua = 0.0
    if q > 0:
        for i in range(n):
            lm = _lmtd(dts[i], dts[i + 1])
            ua = float("inf") if lm <= 0 else ua + (q / n) / lm
    pinch_q = pts[i_min][0]
    pts.sort(key=lambda p: p[0])
    return Profile(duty=q, min_approach=dts[i_min], ua=ua, points=pts, pinch_at=pinch_q)


def max_duty(hot: Side, cold: Side, counter: bool = True, n: int = 20) -> float:
    """Largest duty before the temperatures cross (minimum approach = 0)."""
    if hot.m <= 0 or cold.m <= 0:
        return 0.0
    t_hi = state_Ph(hot.P_in, hot.h_in).T
    t_ci = state_Ph(cold.P_in, cold.h_in).T
    if t_hi <= t_ci:
        return 0.0
    try:
        q_hot = hot.m * (hot.h_in - state_PT(hot.P_out, max(t_ci, 0.01)).h)
    except WaterPropertyError:
        q_hot = hot.m * hot.h_in
    try:
        q_cold = cold.m * (state_PT(cold.P_out, t_hi).h - cold.h_in)
    except WaterPropertyError:
        q_cold = q_hot
    hi = max(min(q_hot, q_cold), 0.0)
    if hi <= 0:
        return 0.0

    def approach(q):
        try:
            return profile(hot, cold, q, counter, n).min_approach
        except WaterPropertyError:
            return -1.0

    if approach(hi) > 0:
        return hi
    return brentq(approach, 0.0, hi, xtol=1e-9 * hi, rtol=1e-10, maxiter=200)


def duty_for_ua(hot: Side, cold: Side, ua: float, counter: bool = True, n: int = 16) -> float:
    """Duty at which the required UA equals the given UA (rating)."""
    if ua <= 0:
        return 0.0
    qmax = max_duty(hot, cold, counter, n)
    if qmax <= 0:
        return 0.0
    hi = qmax * (1 - 1e-7)
    ua_hi = profile(hot, cold, hi, counter, n).ua
    if ua_hi <= ua:  # even the largest feasible duty needs less area than given
        return hi
    return brentq(lambda q: profile(hot, cold, q, counter, n).ua - ua, 0.0, hi, xtol=1e-9 * qmax, rtol=1e-10,
                  maxiter=200)


def duty_for_approach(hot: Side, cold: Side, approach: float, counter: bool = True, n: int = 20) -> float:
    """Duty at which the minimum approach equals the given temperature difference."""
    qmax = max_duty(hot, cold, counter, n)
    if qmax <= 0:
        return 0.0
    if profile(hot, cold, 1e-9 * qmax + 1e-12, counter, n).min_approach < approach:
        raise ValueError("Even with no heat transfer the temperature difference is below the specified approach.")
    return brentq(lambda q: profile(hot, cold, q, counter, n).min_approach - approach, 0.0, qmax,
                  xtol=1e-9 * qmax, rtol=1e-10, maxiter=200)
