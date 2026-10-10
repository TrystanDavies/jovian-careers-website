# Validation

How Steam Suite's results were checked. All of these comparisons are automated tests in `tests/`, so they
run every time `python -m pytest` is run (69 tests).

## 1. Water and steam properties

| Check | Reference | Result |
|---|---|---|
| Specific volume, enthalpy and entropy at 6 states in regions 1 and 2 | IAPWS R7-97 verification tables (Tables 5 and 15) | Match to 1 part in 10⁸ |
| Saturation pressure at 300, 500 and 600 K | IAPWS R7-97 Table 35 | Match to 1 part in 10⁸ |
| Enthalpy over a 5 × 4 grid (5 kPa to 20 MPa, 10 to 500 °C) | CoolProp's independent IF97 implementation | Match to 1 part in 10⁶ |
| Out-of-range inputs (below 0 °C, below the triple point, above 100 MPa, dryness above the critical point) | — | Rejected with a readable message |

## 2. Steam system simulator

### Ideal simple Rankine cycle
Çengel & Boles, *Thermodynamics: An Engineering Approach*, Example 10-1: 3 MPa and 350 °C at the turbine
inlet, condenser at 75 kPa.

| Quantity | Textbook | Steam Suite |
|---|---|---|
| h₁, pump inlet (kJ/kg) | 384.44 | 384.37 |
| h₂, boiler inlet (kJ/kg) | 387.47 | 387.40 |
| h₃, turbine inlet (kJ/kg) | 3116.1 | 3116.06 |
| h₄, turbine exhaust (kJ/kg) | 2403.0 | 2403.03 |
| Exhaust dryness x₄ | 0.8861 | 0.8861 |
| Thermal efficiency | 26.0 % | 26.02 % |

### Ideal regenerative Rankine cycle with an open feedwater heater
Çengel & Boles, Example 10-5: 15 MPa and 600 °C, extraction at 1.2 MPa, condenser at 10 kPa. The extraction
flow is not entered: the simulator finds it from the heater's energy balance.

| Quantity | Textbook | Steam Suite |
|---|---|---|
| Fraction of steam extracted, y | 0.2270 | 0.2271 |
| Heater outlet h₃ (kJ/kg) | 798.33 | 798.50 |
| Extraction steam h₆ (kJ/kg) | 2860.2 | 2858.9 |
| LP turbine exhaust h₇ (kJ/kg) | 2115.3 | 2115.3 |
| Thermal efficiency | 46.3 % | 46.32 % |

The small differences come from the textbook's steam tables (based on IAPWS-95) versus IAPWS-IF97. They are
within the stated uncertainty of IF97.

### Industrial steam system (example flowsheet)
There's no published answer for this one, so the checks are on internal consistency:

- Overall mass balance closes to 2 × 10⁻¹² kg/s, and energy balance to 3 × 10⁻⁹ kW.
- Make-up water equals the sum of all losses (blowdown, unreturned condensate and deaerator vent).
- The boiler produces exactly what the HP header sends to its users.
- The deaerator outlet is saturated water at its pressure, and the desuperheater outlet is at the target
  superheat of 10 °C.
- Process heat duties are met exactly.

Each equipment type also has its own test: valve flash fraction, flash vessel mass and energy split, turbine
power from isentropic efficiency, steam user flow from heat duty, splitter fractions and remainders, mixer
energy balance, and heater duty.

## 3. Relief valve sizing

| Check | Basis | Result |
|---|---|---|
| Saturated steam, 153,500 lb/h, set 1600 psig, 10 % overpressure | Hand calculation with the API 520 steam equation in US units: P₁ = 1774.7 psia, KN = 1.0115, A = 1.703 in² | 1.703 in², K orifice |
| SI and US forms of the steam equation | 190.4 (SI) is the exact unit conversion of 51.5 (US) | Agree to 0.2 % |
| Napier's equation vs. direct integration (isentropic nozzle flow, IF97) for saturated steam, 1 to 150 bar(g) | Theory | Within ±3.2 % (Napier is empirical) |
| Liquid equation vs. Bernoulli's equation with Kd = 0.65 | A = W / (Kd·√(2ρΔP)) | Agree to 0.01 % (182.90 vs 182.89 mm²) |
| Choked steam critical pressure ratio | Expected about 0.58 for saturated steam | 0.55–0.60 |
| Superheat factor KSH | Should fall below 1 and decrease with superheat | 1 > KSH(250 °C) > KSH(400 °C) > 0.7 |
| Hot water that flashes | Must need more area than cold water at the same conditions | Yes; switches to direct integration with a two-phase warning |
| Rupture disk upstream | Area ÷ 0.9 | Exact |
| Low set pressure | ASME minimum overpressure of 3 psi (20.7 kPa) applied | Exact |
| Orifice selection | API 526 letters D to T; boundaries; multiple T valves | Exact |
| Invalid inputs | e.g. "superheated" steam below saturation, back pressure above set pressure | Rejected with a clear message |

Every equation in every report (279 in the test set) was also rendered with KaTeX in strict mode to make sure
the step-by-step reports display correctly.

## What has not been validated

- Comparison against a commercial simulator (e.g. Aspen HYSYS or Aspen Plus) or plant data.
- Relief sizing against the manufacturer's certified capacities for a specific valve model.
- KSH against the tabulated values in ASME Section I or API 520. Enter the tabulated value when your design
  code requires it.
