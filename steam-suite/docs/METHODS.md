# Calculation methods

Internal units throughout: pressure kPa(a), temperature °C, mass flow kg/s, enthalpy kJ/kg, entropy
kJ/(kg·K), power kW, lengths m, diameters and roughness mm. The user interface converts to and from the units
you choose.

## Properties

All water and steam properties come from **IAPWS-IF97**, with the IAPWS transport property equations for
viscosity and thermal conductivity. States can be defined by (P, T), (P, h), (P, s), (P, x) or (T, x).
Streams are stored as pressure and enthalpy, because temperature alone cannot tell wet steam from saturated
water or saturated steam.

Two implementations of the same equations are used:

- **CoolProp's IF97 backend** (C++), when installed. It is about 150 times faster.
  - IF97's backward equations give T(P, h) and T(P, s) to within a few millikelvin; a Newton refinement on the
    forward equations removes that error.
  - Whether a state is wet steam is decided from the exact saturated-water and saturated-steam values, and
    wet-steam properties are found from them by the lever rule.
- **The `iapws` Python package** as a fallback, and wherever CoolProp fails (near the critical point).

The test suite checks that both give the same results, to 1 part in 10⁹ for h and s and 10⁻⁶ K for T, at more
than 600 random states.

## Steam system simulator

### Equipment equations

| Equipment | Equations |
|---|---|
| Pump | h₂ₛ = h(P₂, s₁); h₂ = h₁ + (h₂ₛ − h₁)/η; W = ṁ(h₂ − h₁); W_elec = W/η_motor |
| Pump curve | H = H₀ − (H₀ − H_r)(Q/Q_r)²; η = η_r[2(Q/Q_r) − (Q/Q_r)²]; ΔP = ρgH |
| NPSH available | NPSHa = (P₁ − P_v(T₁))/(ρ₁g) + z_s (static head above the suction) |
| Steam compressor | as the pump, for steam |
| Turbine | h₂ₛ = h(P₂, s₁); h₂ = h₁ − η(h₁ − h₂ₛ); W = ṁ(h₁ − h₂); W_elec = W·η_gen |
| Valve / PRV / trap | h₂ = h₁ (isenthalpic), plus the flow coefficient (below) |
| Boiler | ṁ_bd = b·ṁ_fw; Q = ṁ_s·h_s + ṁ_bd·h_f − ṁ_fw·h_fw; Q_fuel = Q/η |
| Heater / cooler | Q = ṁ(h₂ − h₁), with h₂ from the outlet temperature or dryness, or h₂ = h₁ + Q/ṁ |
| Condenser | h₂ = h_f(P) (or subcooled); ṁ_cw = Q/(c_p·ΔT_cw) |
| Mixer / header | ṁ = Σṁᵢ; h = Σṁᵢhᵢ / ṁ; header outlets at the header pressure |
| Flash vessel | x = (h_in − h_f)/(h_g − h_f); flash steam = x·ṁ |
| Desuperheater | ṁ_w = ṁ_s(h_s − h_target)/(h_target − h_w) |
| Deaerator | ṁ_s + Σṁ_w = ṁ_out(1 + r); ṁ_s·h_s + Σṁ_w·h_w = ṁ_out(h_f + r·h_g) |
| Process steam user | ṁ_s = Q/(h_s − h_c); condensate return = r·ṁ_s |

### Pipe segments

- **Dimensions:** ASME B36.10M outside diameters and wall thicknesses (Sch 40, Sch 80, STD, XS) for ½" to 24",
  or a custom inside diameter.
- **Friction:** Darcy–Weisbach, ΔP_f = f·(L/D)·ρv²/2.
  - f comes from the Colebrook–White equation, solved by iteration.
  - Laminar flow (Re < 2000) uses f = 64/Re; the transition region (2000–4000) is interpolated.
- **Fittings and valves:** Crane TP-410 equivalent lengths, K = (L/D)·f_T, where f_T is the fully turbulent
  friction factor of clean commercial steel of the same bore (e.g. 0.019 for 2", 0.015 for 6"). Entrance and
  exit losses have fixed K. The total K is spread evenly along the pipe.
- **Two-phase friction:**
  - Müller-Steinhagen & Heck (default): with A and B the all-liquid and all-vapour gradients at the total mass
    flux, (dP/dz) = [A + 2(B − A)x](1 − x)^⅓ + B·x³.
  - Or homogeneous flow, with the Cicchitti mixture viscosity.
  - Static head and acceleration use the homogeneous density.
- **Integration along the pipe:** the pipe is divided into 20 segments (60 when the pressure drop exceeds a
  quarter of the inlet pressure). Each segment uses a predictor and two trapezoidal corrector passes, so the
  method is second-order: the numerical error is about 0.003 % for a 20 % pressure drop. A fixed segment count
  keeps results smooth, which Adjust needs.
  - Each segment adds the friction, fittings, static head ρgΔz and acceleration G²Δ(1/ρ) terms.
  - The enthalpy changes by the heat loss, the elevation and the kinetic energy.
- **Heat loss:** q′ = (T − T_amb) / [ln(r₂/r₁)/(2πk) + 1/(2πr₂h_o)], through the insulation and from the outer
  surface. The pipe wall and inside film are neglected.
- **Checks:**
  - Velocity: water about 3 m/s, saturated steam about 40 m/s, superheated steam about 60 m/s.
  - Erosional velocity for two-phase flow, API RP 14E: v_e = 122/√ρ m/s (C = 100).
  - Mach number above 0.3.
  - Choked flow (velocity reaching the speed of sound) is reported as an error.

### Control valves (IEC 60534-2-1, Fp = 1)

- **Water:** Cv = (Q/N₁)·√((ρ₁/ρ₀)/ΔP), with N₁ = 0.0865 (Q in m³/h, ΔP in kPa).
  - The usable pressure drop is limited to ΔP_max = F_L²(P₁ − F_F·P_v), with F_F = 0.96 − 0.28√(P_v/P_c).
  - Flashing (P₂ < P_v) and cavitation are flagged.
- **Steam:** Cv = W / (N₆·Y·√(x·P₁·ρ₁)), with N₆ = 2.73 (W in kg/h, P₁ in kPa).
  - x = ΔP/P₁ and Y = 1 − x/(3F_γ·x_T), with F_γ = γ/1.4. The isentropic exponent γ = w²ρ/P comes from the
    speed of sound (1.135 for wet steam).
  - Flow is choked when x ≥ F_γ·x_T.
- **Modes:** give the outlet pressure or pressure drop to get the Cv needed (and the opening, if the rated Cv
  is known); or give the rated Cv and the opening to get the pressure drop.
  - Opening characteristics: linear, equal percentage (rangeability 50) and quick opening.

### Heat exchangers

- **Zone analysis:** the duty is divided into 20 equal zones. In each, the hot and cold temperatures come from
  IAPWS-IF97 (pressure varies linearly along each side), and UA = Σ ΔQᵢ/ΔT_lm,i. This is correct with
  condensing, boiling or desuperheating.
- **Temperature cross:** the minimum approach is the smallest hot-to-cold temperature difference. If it is
  zero or below there is a temperature cross, which is reported with the largest feasible duty.
- **Specifications:** outlet temperature, outlet dryness, duty, UA (rating: the duty is found by Brent's method
  so that the required UA equals the given UA), or minimum approach.
- **Condensing-heater mode:** gives the cold outlet temperature and hot outlet dryness, and asks for whatever
  hot (steam) flow is needed.

### Solving

The flowsheet is solved by **successive substitution**. Each iteration has two sweeps:

1. **Backward (demands):** equipment asks upstream equipment for the flow it needs. Examples:
   - a process user asks for steam;
   - a header asks its balancing supply for the shortfall;
   - a boiler asks for feedwater (steam ÷ (1 − blowdown));
   - a deaerator asks for heating steam and make-up water, by solving its mass and energy balance;
   - a desuperheater asks for spray water;
   - a condensing heater asks for steam.
2. **Forward (states):** each piece of equipment calculates its outlets from the actual inlet flows, so mass
   and energy are always conserved exactly.

Recycle loops are broken with starting estimates from the source equipment's settings. Iteration stops when
no flow, pressure, enthalpy or demand changes by more than one part in 10⁹ over two successive iterations.
Afterwards the overall mass and energy balances are checked and reported.

**Adjust (goal seek)** varies one numeric setting of a piece of equipment until a stream property or an
equipment result meets a target. Each trial is a full flowsheet solve, warm-started from the previous one.

- With limits, it uses Brent's method between them.
- Without limits, it uses the secant method from the current value.
- With several Adjusts, they are solved in turn until all are met.

**Case study** solves the flowsheet for a list of values of one setting and records chosen stream properties
or results.

## Relief valve sizing

1. **Relieving pressure:** P₁ = P_set + ΔP_over + P_atm. ΔP_over is the chosen percentage of the set pressure,
   with the ASME minimum for low set pressures (3 psi single valve, 4 psi multiple valves, 2 psi Section I).
2. **Fluid state** at P₁ from IAPWS-IF97.
3. **Method:**
   - *Saturated or superheated steam, choked flow:* API 520 steam equation (Napier),
     A = 190.4·W / (P₁·Kd·Kb·Kc·KN·KSH), with A in mm², W in kg/h and P₁ in kPa(a).
     - KN = 1 for P₁ ≤ 10,339 kPa, otherwise (0.02764·P₁ − 1000)/(0.03324·P₁ − 1061).
     - KSH is 1 for saturated steam. For superheated steam it is either entered by the user or estimated as
       the ratio of ideal critical mass fluxes, superheated to saturated.
   - *Steam in subcritical flow, or above 22,057 kPa(a):* direct integration (below).
   - *Water that does not flash* (vapour pressure below the back pressure): API 520 liquid equation,
     A = 11.78·Q / (Kd·Kw·Kc·Kv)·√(G/(P₁ − P₂)), with Q in L/min. Kv is found by iteration from the
     Reynolds number and capped at 1.
   - *Wet steam, and water that flashes:* direct integration (below).
4. **Direct integration (HDI, API 520 Annex C):** the fluid is expanded isentropically from P₁ assuming
   homogeneous equilibrium. At each pressure P, G(P) = ρ(P, s₁)·√(2·(h₁ − h(P, s₁))).
   - The throat condition is the maximum of G between the back pressure and P₁ (choked flow), or G at the back
     pressure if G is still rising there.
   - A = W/(Kd·Kb·Kc·G).
5. **Discharge coefficients:**
   - Kd = 0.975 for vapour and 0.65 for liquid (API effective values).
   - Two-phase flow defaults to Kd = 0.85, a commonly used preliminary value. A subcooled liquid that is still
     liquid at the throat uses 0.65.
   - Kc = 0.9 with a rupture disk upstream.
   - Kb (and Kw for liquids) apply to balanced bellows valves only, from the manufacturer's curve. For
     conventional and pilot-operated valves, back pressure effects are captured by the flow calculation itself.
6. **Orifice:** the smallest API 526 letter (D to T) with at least the required effective area. Rated
   capacity = W·A_orifice/A_required.
7. **On the P&ID:** a relief valve takes the relieving fluid from the stream it protects.
   - Superheated steam is used if the stream is superheated at the relieving pressure.
   - Wet steam uses the stream's dryness, and water uses its temperature.
   - The relieving rate is either fixed or a factor times the stream flow.
8. **Warnings:**
   - back pressure above 10 % of set pressure for conventional valves;
   - set pressure at or below the operating pressure;
   - flashing discharge;
   - estimated KSH;
   - multiple valves needed;
   - confirm with certified data.

Out of scope: determining the relieving rate (API 521 scenarios), inlet pressure loss (API 520 Part II's 3 %
rule), discharge piping, and reaction forces.
