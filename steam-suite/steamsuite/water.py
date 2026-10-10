"""Water and steam properties (IAPWS-IF97).

Thin wrapper around the `iapws` package that

* uses the library's internal units (kPa absolute, °C, kJ/kg, ...),
* classifies the phase in plain language, and
* turns out-of-range inputs into readable error messages.

IAPWS-IF97 is the international standard for industrial steam calculations,
valid from 0 °C to 800 °C up to 100 MPa, and up to 2000 °C below 50 MPa.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from functools import lru_cache

from iapws import IAPWS97

P_CRIT_KPA = 22064.0
T_CRIT_C = 373.946
P_TRIPLE_KPA = 0.611657
T_MIN_C = 0.0
T_MAX_C = 800.0
T_MAX_HIGH_C = 2000.0  # region 5, only up to 50 MPa
P_MAX_KPA = 100000.0
P_MAX_HIGH_T_KPA = 50000.0


class WaterPropertyError(ValueError):
    """Raised when a water/steam state cannot be calculated."""


@dataclass(frozen=True)
class WaterState:
    """A thermodynamic state of water or steam (internal units)."""

    P: float  # kPa(a)
    T: float  # °C
    h: float  # kJ/kg
    s: float  # kJ/(kg·K)
    rho: float  # kg/m³
    x: float | None  # dryness fraction (vapour mass fraction); None if single phase
    phase: str  # 'liquid', 'saturated liquid', 'two-phase', 'saturated vapour', 'vapour', 'supercritical'
    cp: float | None = None  # kJ/(kg·K)
    mu: float | None = None  # Pa·s
    k: float | None = None  # W/(m·K)
    w: float | None = None  # speed of sound, m/s (single phase only)

    @property
    def v(self) -> float:
        return 1.0 / self.rho

    @property
    def T_sat(self) -> float | None:
        return T_sat(self.P) if self.P < P_CRIT_KPA else None

    @property
    def superheat(self) -> float | None:
        ts = self.T_sat
        if ts is None or self.phase != "vapour":
            return None
        return self.T - ts

    @property
    def subcooling(self) -> float | None:
        ts = self.T_sat
        if ts is None or self.phase != "liquid":
            return None
        return ts - self.T

    @property
    def is_vapour_like(self) -> bool:
        return self.phase in ("vapour", "saturated vapour", "supercritical")

    @property
    def is_liquid_like(self) -> bool:
        return self.phase in ("liquid", "saturated liquid")

    def describe(self, temp_unit: str = "°C") -> str:
        """Plain-language description, e.g. 'Superheated steam (52.3 °C superheat)'.

        `temp_unit` ('°C', '°F' or 'K') sets the unit of the superheat or subcooling."""
        scale = 1.8 if temp_unit == "°F" else 1.0
        if self.phase == "liquid":
            if self.P >= P_CRIT_KPA:
                return "Compressed water (above critical pressure)"
            sc = self.subcooling
            if sc is not None and sc < 0.05:
                return "Saturated water (at boiling point)"
            return f"Subcooled water ({sc * scale:.1f} {temp_unit} below boiling)" if sc is not None else "Water"
        if self.phase == "saturated liquid":
            return "Saturated water (at boiling point)"
        if self.phase == "two-phase":
            digits = 3 if 0.01 <= self.x <= 0.99 else 4
            return f"Wet steam (dryness {self.x:.{digits}f})"
        if self.phase == "saturated vapour":
            return "Dry saturated steam"
        if self.phase == "vapour":
            sh = self.superheat
            if sh is not None and sh < 0.05:
                return "Dry saturated steam"
            return f"Superheated steam ({sh * scale:.1f} {temp_unit} superheat)" if sh is not None else "Steam"
        if self.phase == "supercritical":
            return "Supercritical fluid"
        return self.phase


def _classify(st: IAPWS97, P: float, T: float) -> tuple[str, float | None]:
    region = getattr(st, "region", None)
    x_raw = getattr(st, "x", None)
    if P >= P_CRIT_KPA:
        return ("supercritical" if T >= T_CRIT_C else "liquid"), None
    if region == 4:
        x = min(max(float(x_raw), 0.0), 1.0)
        if x <= 1e-7:
            return "saturated liquid", 0.0
        if x >= 1.0 - 1e-7:
            return "saturated vapour", 1.0
        return "two-phase", x
    ts = T_sat(P)
    if region == 1:
        return "liquid", None
    if region in (2, 5):
        return "vapour", None
    # region 3 below the critical pressure: decide by temperature
    return ("liquid" if T < ts else "vapour"), None


def _check_bounds(P: float | None = None, T: float | None = None) -> None:
    if P is not None:
        if not math.isfinite(P) or P <= 0:
            raise WaterPropertyError(f"Pressure must be positive (got {P:g} kPa absolute).")
        if P < P_TRIPLE_KPA:
            raise WaterPropertyError(
                f"Pressure {P:.4g} kPa(a) is below the triple point of water ({P_TRIPLE_KPA} kPa(a))."
            )
        if P > P_MAX_KPA:
            raise WaterPropertyError(
                f"Pressure {P:,.0f} kPa(a) is above the IAPWS-IF97 limit of 100 MPa."
            )
    if T is not None:
        if not math.isfinite(T):
            raise WaterPropertyError("Temperature is not a number.")
        if T < T_MIN_C:
            raise WaterPropertyError(f"Temperature {T:.2f} °C is below 0 °C (ice is not modelled).")
        if T > T_MAX_HIGH_C:
            raise WaterPropertyError(f"Temperature {T:.0f} °C is above the IAPWS-IF97 limit of 2000 °C.")
        if T > T_MAX_C and P is not None and P > P_MAX_HIGH_T_KPA:
            raise WaterPropertyError(
                "Above 800 °C, IAPWS-IF97 is only valid up to 50 MPa."
            )


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _build(st: IAPWS97, sat_x: float | None = None) -> WaterState:
    """Build a WaterState. `sat_x` is given when the state was defined on the
    saturation line (by dryness fraction)."""
    P = st.P * 1000.0
    T = st.T - 273.15
    if sat_x is not None:
        x = float(sat_x)
        phase = "saturated liquid" if x == 0.0 else "saturated vapour" if x == 1.0 else "two-phase"
    else:
        phase, x = _classify(st, P, T)
    two_phase = phase == "two-phase"
    cp = None if two_phase else _float_or_none(getattr(st, "cp", None))
    mu = None if two_phase else _float_or_none(getattr(st, "mu", None))
    k = None if two_phase else _float_or_none(getattr(st, "k", None))
    w = None if two_phase else _float_or_none(getattr(st, "w", None))
    return WaterState(P=P, T=T, h=float(st.h), s=float(st.s), rho=float(st.rho), x=x,
                      phase=phase, cp=cp, mu=mu, k=k, w=w)


def _call(**kwargs) -> IAPWS97:
    try:
        st = IAPWS97(**kwargs)
    except NotImplementedError as exc:
        raise WaterPropertyError(
            "These conditions are outside the range of the IAPWS-IF97 steam tables "
            "(0–800 °C up to 100 MPa; up to 2000 °C below 50 MPa)."
        ) from exc
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise WaterPropertyError(f"Steam table calculation failed: {exc}") from exc
    if not getattr(st, "status", 1) or getattr(st, "h", None) is None:
        raise WaterPropertyError("Steam table calculation did not converge for these conditions.")
    return st


# --- fast backend (CoolProp's IF97 implementation) -------------------------------------
#
# CoolProp implements the same IAPWS-IF97 equations (and the IAPWS transport
# property equations) in C++, about 150 times faster than the pure-Python
# `iapws` package. Results agree to machine precision (see tests). If CoolProp
# is not installed, or fails for a state (it does near the critical point),
# the `iapws` package is used.

try:  # pragma: no cover - import guard
    import CoolProp as _CP
    from CoolProp.CoolProp import AbstractState as _AbstractState

    _HAVE_COOLPROP = True
except ImportError:  # pragma: no cover
    _HAVE_COOLPROP = False

_local = threading.local()
BACKEND = "CoolProp (IAPWS-IF97)" if _HAVE_COOLPROP else "iapws (IAPWS-IF97)"
_use_coolprop = _HAVE_COOLPROP


def set_backend(name: str) -> None:
    """'coolprop' or 'iapws' (mainly for testing that both agree)."""
    global _use_coolprop
    _use_coolprop = name == "coolprop" and _HAVE_COOLPROP
    for fn in (state_PT, state_Ph, state_Ps, state_Px, state_Tx, T_sat, P_sat, _sat_props):
        fn.cache_clear()


def _abstract_state():
    st = getattr(_local, "state", None)
    if st is None:
        st = _local.state = _AbstractState("IF97", "Water")
    return st


def _opt(fn) -> float | None:
    try:
        v = fn()
    except (ValueError, IndexError, RuntimeError):
        return None
    return v if math.isfinite(v) else None


def _read(AS) -> dict:
    """Read every property we need from the AbstractState at once (later calls reuse it)."""
    cp_ = _opt(AS.cpmass)
    return {
        "P": AS.p() / 1000.0, "T": AS.T() - 273.15, "h": AS.hmass() / 1000.0, "s": AS.smass() / 1000.0,
        "rho": AS.rhomass(), "q": AS.Q(), "cp": cp_ / 1000.0 if cp_ is not None else None,
        "mu": _opt(AS.viscosity), "k": _opt(AS.conductivity), "w": _opt(AS.speed_sound),
    }


def _from_coolprop(pair: str, a: float, b: float, sat_x: float | None = None) -> WaterState:
    """a, b in library units; raises ValueError if CoolProp cannot do it."""
    AS = _abstract_state()
    if pair in ("Ph", "Ps"):
        if pair == "Ph":
            AS.update(_CP.HmassP_INPUTS, b * 1000.0, a * 1000.0)
        else:
            AS.update(_CP.PSmass_INPUTS, a * 1000.0, b * 1000.0)
        t_guess = AS.T()
        if a < P_CRIT_KPA:
            # decide the phase with the exact saturation values (CoolProp's own
            # two-phase (P, h) and (P, s) results are slightly inconsistent)
            ts, hf, hg, sf, sg, rf, rg = _sat_props(a)
            lo, hi = (hf, hg) if pair == "Ph" else (sf, sg)
            x = (b - lo) / (hi - lo)
            if 0.0 <= x <= 1.0:
                return _two_phase_state(a, ts, x, hf, hg, sf, sg, rf, rg)
            if (x < 0) != (t_guess - 273.15 < ts):  # backward equation landed on the wrong side
                t_guess = ts + 273.15 + (-1e-7 if x < 0 else 1e-7)
        AS.update(_CP.PT_INPUTS, a * 1000.0, t_guess)
        _refine(AS, pair, a, b)
        v = _read(AS)
        v["q"] = -1.0
    else:
        if pair == "PT":
            AS.update(_CP.PT_INPUTS, a * 1000.0, b + 273.15)
        elif pair == "Px":
            AS.update(_CP.PQ_INPUTS, a * 1000.0, b)
        elif pair == "Tx":
            AS.update(_CP.QT_INPUTS, b, a + 273.15)
        else:  # pragma: no cover
            raise ValueError(pair)
        v = _read(AS)
    P, T, h, s_, rho, q = v["P"], v["T"], v["h"], v["s"], v["rho"], v["q"]
    if not all(math.isfinite(val) for val in (P, T, h, s_, rho)):
        raise ValueError("non-finite result")
    if sat_x is not None:
        x = float(sat_x)
        phase = "saturated liquid" if x == 0.0 else "saturated vapour" if x == 1.0 else "two-phase"
    elif P >= P_CRIT_KPA:
        phase, x = ("supercritical" if T >= T_CRIT_C else "liquid"), None
    elif 0.0 <= q <= 1.0:
        if q <= 1e-7:
            phase, x = "saturated liquid", 0.0
        elif q >= 1.0 - 1e-7:
            phase, x = "saturated vapour", 1.0
        else:
            phase, x = "two-phase", float(q)
    else:
        phase, x = ("liquid" if T < T_sat(P) else "vapour"), None
    if phase == "two-phase":
        return WaterState(P=P, T=T, h=h, s=s_, rho=rho, x=x, phase=phase)
    return WaterState(P=P, T=T, h=h, s=s_, rho=rho, x=x, phase=phase, cp=v["cp"], mu=v["mu"], k=v["k"], w=v["w"])


@lru_cache(maxsize=50_000)
def _sat_props(P: float) -> tuple[float, float, float, float, float, float, float]:
    """(T_sat °C, h_f, h_g, s_f, s_g, ρ_f, ρ_g) at P [kPa(a)] from CoolProp."""
    AS = _abstract_state()
    AS.update(_CP.PQ_INPUTS, P * 1000.0, 0.0)
    ts, hf, sf, rf = AS.T() - 273.15, AS.hmass() / 1000.0, AS.smass() / 1000.0, AS.rhomass()
    AS.update(_CP.PQ_INPUTS, P * 1000.0, 1.0)
    return ts, hf, AS.hmass() / 1000.0, sf, AS.smass() / 1000.0, rf, AS.rhomass()


def _two_phase_state(P, ts, x, hf, hg, sf, sg, rf, rg) -> WaterState:
    if x <= 1e-7:
        phase, x = "saturated liquid", 0.0
    elif x >= 1.0 - 1e-7:
        phase, x = "saturated vapour", 1.0
    else:
        phase = "two-phase"
    v = 1.0 / rf + x * (1.0 / rg - 1.0 / rf)
    st = WaterState(P=P, T=ts, h=hf + x * (hg - hf), s=sf + x * (sg - sf), rho=1.0 / v, x=x, phase=phase)
    if phase != "two-phase":  # transport properties of the saturated phase
        sat = state_Px(P, x)
        st = WaterState(P=P, T=ts, h=st.h, s=st.s, rho=st.rho, x=x, phase=phase, cp=sat.cp, mu=sat.mu, k=sat.k,
                        w=sat.w)
    return st


def _refine(AS, pair: str, P: float, target: float) -> None:
    """Make a single-phase (P, h) or (P, s) state exactly consistent.

    IF97's backward equations give T(P, h) and T(P, s) to within a few
    millikelvin. A few Newton steps on the forward equation h(P, T) (or
    s(P, T)) remove that error, as the `iapws` package also does."""
    p_pa = P * 1000.0
    tgt = target * 1000.0
    T = AS.T()  # caller has just set a (P, T) state
    for _ in range(25):
        AS.update(_CP.PT_INPUTS, p_pa, T)
        val = AS.hmass() if pair == "Ph" else AS.smass()
        err = tgt - val
        if abs(err) <= 1e-11 * max(abs(tgt), 1.0):
            return
        slope = AS.cpmass() if pair == "Ph" else AS.cpmass() / T
        T += err / slope
    AS.update(_CP.PT_INPUTS, p_pa, T)
    val = AS.hmass() if pair == "Ph" else AS.smass()
    if abs(tgt - val) > 1e-7 * max(abs(tgt), 1.0):
        raise ValueError("refinement did not converge")


def _state(pair: str, a: float, b: float, sat_x: float | None = None, **iapws_kwargs) -> WaterState:
    if _use_coolprop:
        try:
            return _from_coolprop(pair, a, b, sat_x)
        except (ValueError, IndexError, RuntimeError):
            pass
    return _build(_call(**iapws_kwargs), sat_x=sat_x)


# --- constructors -------------------------------------------------------------


@lru_cache(maxsize=100_000)
def state_PT(P: float, T: float) -> WaterState:
    """State from pressure [kPa(a)] and temperature [°C]."""
    _check_bounds(P, T)
    if P < P_CRIT_KPA:
        ts = T_sat(P)
        if abs(T - ts) < 1e-9:
            raise WaterPropertyError(
                f"At {P:.4g} kPa(a) water boils at exactly {ts:.3f} °C, so pressure and temperature "
                "alone do not fix the state. Give the dryness fraction instead."
            )
    return _state("PT", P, T, P=P / 1000.0, T=T + 273.15)


@lru_cache(maxsize=200_000)
def state_Ph(P: float, h: float) -> WaterState:
    """State from pressure [kPa(a)] and specific enthalpy [kJ/kg]."""
    _check_bounds(P)
    return _state("Ph", P, h, P=P / 1000.0, h=h)


@lru_cache(maxsize=200_000)
def state_Ps(P: float, s: float) -> WaterState:
    """State from pressure [kPa(a)] and specific entropy [kJ/(kg·K)]."""
    _check_bounds(P)
    return _state("Ps", P, s, P=P / 1000.0, s=s)


@lru_cache(maxsize=50_000)
def state_Px(P: float, x: float) -> WaterState:
    """Saturated state from pressure [kPa(a)] and dryness fraction (0 = saturated water, 1 = dry steam)."""
    _check_bounds(P)
    if P >= P_CRIT_KPA:
        raise WaterPropertyError(
            f"There is no boiling above the critical pressure ({P_CRIT_KPA:,.0f} kPa(a)), "
            "so a dryness fraction cannot be used. Give a temperature instead."
        )
    if not 0.0 <= x <= 1.0:
        raise WaterPropertyError("Dryness fraction must be between 0 (saturated water) and 1 (dry steam).")
    return _state("Px", P, x, sat_x=x, P=P / 1000.0, x=x)


@lru_cache(maxsize=50_000)
def state_Tx(T: float, x: float) -> WaterState:
    """Saturated state from temperature [°C] and dryness fraction."""
    _check_bounds(None, T)
    if T >= T_CRIT_C:
        raise WaterPropertyError(
            f"There is no boiling above the critical temperature ({T_CRIT_C} °C)."
        )
    if not 0.0 <= x <= 1.0:
        raise WaterPropertyError("Dryness fraction must be between 0 (saturated water) and 1 (dry steam).")
    return _state("Tx", T, x, sat_x=x, T=T + 273.15, x=x)


@lru_cache(maxsize=50_000)
def T_sat(P: float) -> float:
    """Saturation (boiling) temperature [°C] at pressure P [kPa(a)]."""
    _check_bounds(P)
    if P >= P_CRIT_KPA:
        raise WaterPropertyError("Above the critical pressure there is no saturation temperature.")
    if _use_coolprop:
        try:
            AS = _abstract_state()
            AS.update(_CP.PQ_INPUTS, P * 1000.0, 0.0)
            return AS.T() - 273.15
        except (ValueError, IndexError, RuntimeError):
            pass
    return _call(P=P / 1000.0, x=0.0).T - 273.15


@lru_cache(maxsize=50_000)
def P_sat(T: float) -> float:
    """Saturation (vapour) pressure [kPa(a)] at temperature T [°C]."""
    _check_bounds(None, T)
    if T >= T_CRIT_C:
        raise WaterPropertyError("Above the critical temperature there is no saturation pressure.")
    if _use_coolprop:
        try:
            AS = _abstract_state()
            AS.update(_CP.QT_INPUTS, 0.0, T + 273.15)
            return AS.p() / 1000.0
        except (ValueError, IndexError, RuntimeError):
            pass
    return _call(T=T + 273.15, x=0.0).P * 1000.0


def saturation_at_P(P: float) -> tuple[WaterState, WaterState]:
    """(saturated liquid, saturated vapour) at pressure P [kPa(a)]."""
    return state_Px(P, 0.0), state_Px(P, 1.0)


def saturation_at_T(T: float) -> tuple[WaterState, WaterState]:
    """(saturated liquid, saturated vapour) at temperature T [°C]."""
    return state_Tx(T, 0.0), state_Tx(T, 1.0)
