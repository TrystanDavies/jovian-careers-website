# Validation

How Steam Suite's results were checked. The comparisons in sections 1 to 7 are automated tests in `tests/`,
run with `python -m pytest` (170 tests). Section 8 is a browser test of the P&ID designer.

## 1. Water and steam properties

| Check | Reference | Result |
|---|---|---|
| Specific volume, enthalpy and entropy at 6 states in regions 1 and 2 | IAPWS R7-97 verification tables (Tables 5 and 15) | Match to 1 part in 10⁸ |
| Saturation pressure at 300, 500 and 600 K | IAPWS R7-97 Table 35 | Match to 1 part in 10⁸ |
| Enthalpy over a 5 × 4 grid (5 kPa to 20 MPa, 10 to 500 °C) | CoolProp's independent IF97 implementation | Match to 1 part in 10⁶ |
| Fast path (CoolProp IF97 + Newton refinement) vs. the `iapws` package: more than 600 states from 300 random (P, h) points, 1 kPa to 16 MPa, as (P, h), (P, s) and (P, T) inputs | Same equations, independent code | Same phase; T to 10⁻⁶ K; h and s to 1 part in 10⁹; density to 10⁻⁷; viscosity, conductivity, speed of sound and c_p to 10⁻⁶ |
| Out-of-range inputs (below 0 °C, below the triple point, above 100 MPa, dryness above the critical point) | — | Rejected with a readable message |

The fast-path comparison includes transport properties on purpose: it caught a bug where one property call
overwrote another's results, which made a water pipe's pressure drop 11 % too low.

## 2. Pipe hydraulics

| Check | Basis | Result |
|---|---|---|
| Pipe bore, 2" Sch 40 | ASME B36.10M: OD 60.3 mm, wall 3.91 mm | 52.48 mm |
| Friction factor: laminar, transition and turbulent | f = 64/Re; Colebrook–White | Exact |
| Fully turbulent friction factor f_T | Crane TP-410: 0.019 for 2", 0.015 for 6" | 0.0189, 0.0149 |
| Water, 3 kg/s at 20 °C, 100 m of 2" Sch 40 | Darcy–Weisbach by hand: v = 1.389 m/s, Re = 72,700, f = 0.02247 | 41.25 kPa, same as the hand calculation to 1 part in 10⁴ |
| Static head, 10 m rise | ρgΔz | Exact to 0.1 % |
| Saturated steam, 10 t/h at 10 bar(g), 100 m of 4" with K = 5 | The same pipe divided into 400 segments | 246.59 vs 246.59 kPa (difference 0.002 %) |
| Every two-phase method (Müller-Steinhagen & Heck, Friedel, Chisholm, homogeneous) at x → 0 and x → 1 | Must equal the all-liquid and all-vapour gradients | Within 0.5 % |
| Friedel at 5 bar(a), x = 0.1, G = 300 kg/(m²·s), 80 mm bore | Correlation evaluated step by step by hand | Exact (1 part in 10¹²) |
| Chisholm across the viscous/turbulent regime change, flux varied in 2 % steps | Must have no jump | Largest step 3 % (1 % expected from G² alone) |
| Surface tension at 25, 100 and 200 °C | IAPWS R1-76 table (71.97, 58.91, 37.67 mN/m) | Within 0.006 mN/m; zero at the critical point |
| Void fraction | Homogeneous and drift flux: 0 at x → 0, 1 at x → 1; with slip, α(vertical) < α(horizontal) < α(homogeneous); downflow homogeneous | As expected |
| Rising wet-condensate line | Drift flux must give a larger static head than homogeneous | 1.5 times larger or more; zero in a level line |
| Speed of sound in wet steam | Homogeneous equilibrium √(ΔP/Δρ)_s from a finite isentropic step | Within 0.2 %; far below the dry-steam value |
| Choking length of superheated steam (2 bar, 400 °C, nearly ideal gas) in a fully rough 50 mm pipe, inlet Mach 0.25, 0.4 and 0.6 | Exact Fanno-flow solution, f·L*/D = (1 − M²)/(γM²) + (γ + 1)/(2γ)·ln[(γ + 1)M²/(2 + (γ − 1)M²)] | −0.39 %, −0.15 %, +0.07 % |
| 3" × 100 m of dry steam from 5 bar(a), at 1.0–1.07 kg/s, just below choking | Must not depend on the number of segments (before the choking-aware march, results near choking changed by a factor of two with the segment count) | Outlet pressure within 0.7 % for 20, 60 and 200 segments |
| Choked pipe | The exit must be sonic (v = c); a longer pipe chokes at the same point; a smaller flow chokes further along | All three hold |
| Flashing hot water line | Must choke on the two-phase speed of sound | Choked, with the exit pressure reported |
| Reverse flow | Mirror image: friction and acceleration reversed, static head unchanged; smooth through zero | Exact |
| Heat loss at a tiny flow | The fluid must not cool below ambient | Holds |
| Heat loss, 4" pipe at 180 °C, 50 mm insulation (k = 0.04 W/m·K), h_o = 10 W/m²·K | Conduction plus surface resistance, by hand | 60.4 W/m, exact; the pipe model's loss agrees within 5 % as the steam cools along it, and condensate forms |
| A 3" line asked to carry 10 t/h of 10 bar(g) steam over 200 m | Physically impossible (choked) | Reported as an error with the choking length, not a wrong answer |
| NPSH available | (P − P_v)/(ρg) | Exact |

## 3. Control valves

| Check | Basis | Result |
|---|---|---|
| Water, 5 kg/s at 40 °C, 10 → 6 bar(a) | IEC 60534 liquid equation by hand | Cv 10.45, exact |
| Water and steam: size the Cv, then put that Cv back in and calculate the outlet pressure | Round trip | Outlet pressure recovered to 1 part in 10⁶ |
| Superheated steam at 250 °C, 11 → 1.5 bar(a) | Choked: expansion factor Y must be 2/3 | Y = 0.6667, flagged as choked |
| Asking a valve to pass more choked flow than its Cv allows | Physically impossible | Reported as an error |
| On the P&ID: "Cv and opening" mode using the Cv the sizing mode found | Round trip through the whole flowsheet | Same outlet pressure to 1 part in 10⁶ |
| Flow from pressures (used by the pressure–flow solver), water and steam | Inverse of the sizing equations | Flow recovered to 1 part in 10⁵; constant once choked; zero at zero ΔP; negative for a reversed ΔP |

## 4. Heat exchangers

| Check | Basis | Result |
|---|---|---|
| Water–water, 2 kg/s from 90 to 50 °C heating 3 kg/s from 20 °C | Duty from enthalpies; UA from the log-mean temperature difference | Duty exact; UA 9.2435 vs 9.2494 kW/K (0.06 %, because c_p varies with temperature, which the zone method includes) |
| Rating: give the UA from the design case, find the outlet temperatures | Must reproduce the design | Hot outlet 50.0001 °C (target 50 °C) |
| Condensing heater: steam at 3 bar(g) heating 5 kg/s of water from 40 to 120 °C | ṁ_steam = Q/h_fg | Exact to 1 part in 10⁸; condensate at saturation temperature to 10⁻⁶ K |
| Cold outlet hotter than the hot inlet | Temperature cross | Reported as an error, with the largest duty the exchanger could transfer |
| Energy balance across the exchanger | Hot side loses what cold side gains | Closes to 10⁻⁶ kW |

## 5. Equipment, solver and tools

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

### Example flowsheets
There's no published answer for these, so the checks are on internal consistency:

- **Industrial steam system:** mass balance closes to 2 × 10⁻¹² kg/s and energy to 3 × 10⁻⁹ kW. Make-up
  water equals the sum of all losses. The boiler produces exactly what the HP header sends to its users. The
  deaerator outlet is saturated water, the desuperheater outlet is at its 10 °C superheat target, and process
  duties are met exactly.
- **Steam distribution:** mass balance closes exactly and energy to 3 × 10⁻¹⁰ kW, including pipe heat losses
  and pump work. The pipe pressure drop is the sum of its friction, fittings, static and acceleration parts to
  1 part in 10⁹.

### Pressure–flow solving

| Check | Basis | Result |
|---|---|---|
| Two identical pipes in parallel | Must share the flow equally | Equal to 1 part in 10⁹ |
| Two parallel pipes of different length | Equal pressure drops; the ratio of flows | Pressure drops equal to 1 part in 10⁶; each branch equals a direct pipe calculation to 1 part in 10⁸ |
| Two equal-bore pipes in fully rough flow, lengths 1 : 4 | m_A/m_B = √(L_B/L_A) = 2 | 2.00 (within 1 %) |
| Pump on its curve against a quadratic resistance | Closed-form root of H₀ − (H₀ − H_r)(Q/Q_r)² = ΔP_r(ṁ/ṁ_r)²/(ρg) | Flow to 1 part in 10⁶ |
| Pump curve against a pipe and a Cv valve | Independent root-finding (Brent) on pump head = system head | Flow to 1 part in 10⁵ |
| Steam trap discharging through a return line to a receiver | Trap back pressure = receiver pressure + the return line's pressure drop | Matches a direct pipe calculation to 1 part in 10⁶ |
| Pressure-reducing valve with too little supply pressure | Must go wide open at its rated Cv rather than fail | Fully open; its flow equals the valve equation at the solved pressures to 1 part in 10⁶ |
| A valve too small to pass the flow even fully open | Must be explained | "… choked … even fully open" |
| Closed hot-water loop with an expansion tank | The tank's flow settles at zero; the loop pressure is the tank's; the pump head matches its curve | All hold |
| Closed Rankine cycle with a flow specification | Çengel & Boles Example 10-1 | Efficiency 26.02 % (textbook 26.0 %) |
| Closed loop without anything fixing its flow; fixed make-up into a closed loop; missing and conflicting specifications | Must be explained in plain words | "the circulating flow … is not set", "Not enough specifications …", "Too many specifications …" |
| Check valve against a higher back pressure | Must close (zero flow) and reopen when the pressure allows | Closes; reopens |
| Every example flowsheet solved in both modes | Sequential and pressure–flow must agree | Flows, pressures and enthalpies within 1 part in 10⁶; equations = unknowns; mass and energy balances close |

### Other equipment and tools

| Check | Result |
|---|---|
| Valve flash fraction, flash vessel split, turbine power from isentropic efficiency, steam user flow from heat duty, splitter fractions and shortages, mixer and heater energy balances | Each matches its hand calculation |
| Pump curve: operating point lies on H = H₀ − (H₀ − H_r)(Q/Q_r)²; NPSH warning when NPSHa < NPSHr | Exact; warning given |
| Steam compressor at 100 % efficiency | Isentropic (entropy unchanged to 10⁻⁶) |
| Relief valve placed on a P&ID line vs the stand-alone relief sizing for the same conditions | Same area to 1 part in 10⁶ and the same orifice |
| Adjust with limits (Brent's method): supply pressure that gives 9 bar(g) at the end of a steam main | Target met to 1 part in 10⁷ |
| Adjust without limits (secant method): pump outlet pressure for a given power | Target met to 1 part in 10⁵ |
| Adjust with a target outside its limits | Reported as "No solution between the limits" |
| Case study of pipe pressure drop against flow | Increases with flow; original setting restored afterwards |
| Save and reload (JSON), including the drawing layout | Identical results and layout |
| Missing connections, duplicate stream names, failing equipment | Clear messages instead of crashes |

## 6. Relief valve sizing

| Check | Basis | Result |
|---|---|---|
| Saturated steam, 153,500 lb/h, set 1600 psig, 10 % overpressure | Hand calculation with the API 520 steam equation in US units: P₁ = 1774.7 psia, KN = 1.0115, A = 1.703 in² | 1.703 in², K orifice |
| SI and US forms of the steam equation | 190.4 (SI) is the exact unit conversion of 51.5 (US) | Agree to 0.2 % |
| Napier's equation vs. direct integration (isentropic nozzle flow, IF97) for saturated steam, 1 to 150 bar(g) | Theory | Within ±4 % (Napier is empirical, and KN steps at 1500 psia) |
| Liquid equation vs. Bernoulli's equation with Kd = 0.65 | A = W / (Kd·√(2ρΔP)) | Agree to 0.01 % (182.90 vs 182.89 mm²) |
| Choked steam critical pressure ratio | Expected about 0.58 for saturated steam | 0.55–0.60 |
| Superheat factor KSH | Should fall below 1 and decrease with superheat | 1 > KSH(250 °C) > KSH(400 °C) > 0.7 |
| Hot water that flashes | Must need more area than cold water at the same conditions | Yes; switches to direct integration with a two-phase warning |
| Wet steam | Mass flux must exceed dry steam's | Yes |
| Rupture disk upstream | Area ÷ 0.9 | Exact |
| Low set pressure, fire case | ASME minimum overpressure of 3 psi (20.7 kPa); 21 % for fire | Exact |
| Orifice selection | API 526 letters D to T; boundaries; multiple T valves | Exact |
| Invalid inputs | e.g. "superheated" steam below saturation, back pressure above set pressure | Rejected with a clear message |

### Relief scenarios and piping

| Check | Basis | Result |
|---|---|---|
| Fire, vertical and horizontal vessels, with and without drainage, environment factor, fire zone (7.6 m) | Q = C·F·A^0.82 and W = Q/λ by hand | Exact (1 part in 10⁹) |
| Control valve fails open, with a credit for normal outflow | The valve flow equation by hand, minus the credit; superheat after throttling | Exact; no relief needed when the upstream pressure is not above P₁ |
| Blocked outlet: pump on its curve | Q from the curve at the relieving head | Exact; not needed when the shut-off head is too low |
| Tube rupture | 2·C_d·A·G with G from the isentropic nozzle; the 10/13 rule | Exact; excluded when the rule is met |
| Thermal expansion | α_v from IAPWS-IF97 (3.9 × 10⁻⁴ K⁻¹ near 40 °C); W = α_v·Φ/c_p | Within 5 % of the tabulated α_v; W exact |
| Abnormal heat input | UA(T_h − T_sat)/λ | Exact |
| Several scenarios | The largest area governs; fire is sized at its own 21 % overpressure; the governing area equals a direct sizing | All hold |
| Inlet line | Loss = friction + fittings of a direct pipe calculation at the **rated** flow; a too-small line is flagged | Exact; flagged |
| Choked discharge to atmosphere | Exit at the speed of sound; F = ṁv_e + (P_e − P_atm)A_e; sizing repeated with the built-up back pressure | Mach 1 within 2 %; F exact; the API vapour formula 8 % higher (ideal gas vs real steam) |
| Discharge to a header | The exit reaches the header pressure; total back pressure = superimposed + built-up; no reaction force | All hold |
| Built-up back pressure limit | Follows the scenario's overpressure (10 % for a single valve, 21 % for fire) | Flagged at 10 %, not at 21 % |
| Relief valve on the drawing with scenarios from the equipment (a control valve's Cv and inlet) | Same rate as the stand-alone calculation | To 1 part in 10⁶ |

Every equation in every report (279 in the test set) was also rendered with KaTeX in strict mode to make sure
the step-by-step reports display correctly.

## 7. Comparing with HYSYS or plant data

The **Compare** tab in the workbook takes pasted reference results and shows, for every stream and
property, the reference value, the simulated value, the difference and a band (good within 1 %, 1 °C or 0.01
dryness; check within 5 %, 3 °C or 0.03; large beyond). Tests check the three layouts it reads (one value
per row; the HYSYS workbook with properties down the side and streams across the top; streams down the side
with "Property [unit]" columns), unit conversion (including gauge and US units) and the messages for text it
cannot read.

No HYSYS case has been compared yet in this repository: paste one in to check a design. HYSYS's "ASME Steam"
package uses the older IFC-67 equations, which differ from IAPWS-IF97 by up to about 0.1–0.5 %.

## 8. Web API and browser

- **API tests** (`tests/test_web_api.py`): every equipment type is in the catalogue; every example loads with a
  layout and solves; structural errors, calculation steps, charts, Adjust results, relief sizing, properties,
  case study and report downloads all return what the browser expects.
- **Browser test** (`tests/e2e/designer_e2e.mjs`, Playwright with Chromium): 48 checks on the real app:
  loading and solving examples; dragging equipment from the palette and placing it by clicking; connecting
  nozzles; making a product stream by dragging an outlet into empty space; pipe results and rendered
  equations; inserting a valve into a line; adding and sizing a relief valve; undo and redo; rotate,
  duplicate and delete; tidy layout; the workbook, units switching and case study; the cooling-water network
  in pressure–flow mode (branch flows differ and add up to the pump flow, and throttling one balancing valve
  moves flow to the others); switching the solver in the toolbar; placing a sink; relief scenarios on a PSV
  taking values from a valve on the drawing, with the governing one highlighted; pasting a HYSYS-style table
  into Compare; saving a flowsheet; the relief sizing page with scenarios, inlet line and discharge line; the
  steam table page. It also fails if the browser logs any JavaScript error.
- **API tests** also cover a pressure–flow solve with a warm start and the relief-system endpoint.

## What has not been validated

- Comparison against a commercial simulator (e.g. Aspen HYSYS or Aspen Plus) or plant data. The Compare tool
  makes that check quick for a specific case.
- Two-phase pressure drop against measurements. The correlations are typically within ±30 %; the pipe report
  shows the spread between them so a margin can be chosen.
- Relief scenarios against published worked examples (only hand calculations of the same equations).
- Relief sizing against the manufacturer's certified capacities for a specific valve model.
- KSH against the tabulated values in ASME Section I or API 520. Enter the tabulated value when your design
  code requires it.
- Control valve sizing against a manufacturer's sizing program (the valve-specific F_L, x_T and Cv must come
  from the manufacturer).
