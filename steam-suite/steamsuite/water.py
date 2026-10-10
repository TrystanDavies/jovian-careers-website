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
    return WaterState(P=P, T=T, h=float(st.h), s=float(st.s), rho=float(st.rho), x=x,
                      phase=phase, cp=cp, mu=mu, k=k)


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
    return _build(_call(P=P / 1000.0, T=T + 273.15))


@lru_cache(maxsize=200_000)
def state_Ph(P: float, h: float) -> WaterState:
    """State from pressure [kPa(a)] and specific enthalpy [kJ/kg]."""
    _check_bounds(P)
    return _build(_call(P=P / 1000.0, h=h))


@lru_cache(maxsize=200_000)
def state_Ps(P: float, s: float) -> WaterState:
    """State from pressure [kPa(a)] and specific entropy [kJ/(kg·K)]."""
    _check_bounds(P)
    return _build(_call(P=P / 1000.0, s=s))


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
    return _build(_call(P=P / 1000.0, x=x), sat_x=x)


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
    return _build(_call(T=T + 273.15, x=x), sat_x=x)


@lru_cache(maxsize=50_000)
def T_sat(P: float) -> float:
    """Saturation (boiling) temperature [°C] at pressure P [kPa(a)]."""
    _check_bounds(P)
    if P >= P_CRIT_KPA:
        raise WaterPropertyError("Above the critical pressure there is no saturation temperature.")
    return _call(P=P / 1000.0, x=0.0).T - 273.15


@lru_cache(maxsize=50_000)
def P_sat(T: float) -> float:
    """Saturation (vapour) pressure [kPa(a)] at temperature T [°C]."""
    _check_bounds(None, T)
    if T >= T_CRIT_C:
        raise WaterPropertyError("Above the critical temperature there is no saturation pressure.")
    return _call(T=T + 273.15, x=0.0).P * 1000.0


def saturation_at_P(P: float) -> tuple[WaterState, WaterState]:
    """(saturated liquid, saturated vapour) at pressure P [kPa(a)]."""
    return state_Px(P, 0.0), state_Px(P, 1.0)


def saturation_at_T(T: float) -> tuple[WaterState, WaterState]:
    """(saturated liquid, saturated vapour) at temperature T [°C]."""
    return state_Tx(T, 0.0), state_Tx(T, 1.0)
