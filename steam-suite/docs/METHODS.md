# Calculation methods

Internal units throughout: pressure kPa(a), temperature °C, mass flow kg/s, enthalpy kJ/kg, entropy
kJ/(kg·K), power kW, lengths m, diameters and roughness mm. The user interface converts to and from the units
you choose.

## Properties

All water and steam properties come from **IAPWS-IF97**, with the IAPWS transport property equations for
viscosity and thermal conductivity, and IAPWS R1-76 for surface tension,
σ = 235.8·τ^1.256·(1 − 0.625τ) mN/m with τ = 1 − T/647.096 K. States can be defined by (P, T), (P, h), (P, s), (P, x) or (T, x).
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
- **Two-phase friction:** four methods, chosen per pipe. With A and B the all-liquid and all-vapour gradients
  at the total mass flux G:
  - *Müller-Steinhagen & Heck* (default): (dP/dz) = [A + 2(B − A)x](1 − x)^⅓ + B·x³.
  - *Friedel (1979)*: Φ²_lo = E + 3.24·F·H / (Fr^0.045·We^0.035), with E = (1 − x)² + x²(ρ_l f_go)/(ρ_g f_lo),
    F = x^0.78(1 − x)^0.224, H = (ρ_l/ρ_g)^0.91(μ_g/μ_l)^0.19(1 − μ_g/μ_l)^0.7, and Fr and We from the
    homogeneous density and the IAPWS surface tension. Valid for horizontal flow and vertical upflow.
  - *Chisholm (Lockhart–Martinelli)*: (dP/dz) = (dP/dz)_l + C·√((dP/dz)_l(dP/dz)_g) + (dP/dz)_g, the expanded
    form, which has the exact all-liquid and all-vapour limits. C = 5, 10, 12 or 20 for viscous or turbulent
    liquid and vapour, blended smoothly over Re 2000–4000 so the pressure drop has no steps.
  - *Homogeneous*: single-phase friction at the homogeneous density and the Cicchitti mixture viscosity.
  - The friction factors in all of them come from Colebrook–White.
  - A **design factor** (default 1.0) multiplies the two-phase friction. The pipe's calculation report shows
    the gradient by every method at the inlet and outlet, and the spread between them. Two-phase correlations
    typically scatter by ±30 % against data, so the spread is a guide to how much margin to allow.
- **Void fraction** (for static head and acceleration):
  - *Homogeneous* (no slip): α = (x/ρ_g) / (x/ρ_g + (1 − x)/ρ_l).
  - *Drift flux (Rouhani–Axelsson)*: α = (x/ρ_g) / [C₀(x/ρ_g + (1 − x)/ρ_l) + u_gj/G], with
    u_gj = 1.18(1 − x)[gσ(ρ_l − ρ_g)]^¼/ρ_l^½ and C₀ = 1 + c(1 − x). c = 0.12 for horizontal pipes (Steiner's
    form), rising to 0.2 for vertical upflow. Downward flow uses the homogeneous value.
  - Slip makes the vapour move faster than the liquid, so the liquid holds up: a rising wet-condensate line
    has a larger static head with drift flux. New pipes use drift flux; saved files keep homogeneous unless
    changed.
- **Integration along the pipe:**
  - The pipe is divided into 20 segments (60 when the pressure drop exceeds a quarter of the inlet pressure).
    Each segment uses a predictor and trapezoidal corrector passes repeated until the end pressure settles,
    so the method is second-order. A fixed segment count keeps results smooth, which Adjust and the
    pressure–flow solver need.
  - Each segment adds the friction, fittings, static head ρgΔz and acceleration G²Δ(1/ρ) terms.
  - The enthalpy changes by the heat loss, the elevation and the kinetic energy. The heat loss cannot cool
    the fluid below ambient.
- **Choked flow:** once the Mach number passes 0.3 the rest of the pipe is integrated in small pressure steps
  instead of length steps. For each step to a lower pressure P₂:
  - the state comes from the energy balance, h + v²/2 = constant (less heat loss and elevation);
  - the length of the step comes from the momentum balance,
    ΔL = [(P₁ − P₂) − G²(1/ρ₂ − 1/ρ₁)] / [(dP/dz)_friction+fittings + ρg·sinθ].
  - ΔL falls to zero where the velocity reaches the speed of sound, so the longest reachable length is the
    choking length. If that is shorter than the pipe, the pipe cannot pass the flow from these inlet
    conditions: the result is reported as an error, with the choking length and the sonic exit state.
  - Speed of sound: IAPWS-IF97 for single phase. For wet steam, the homogeneous-equilibrium value
    c = √((∂P/∂ρ)_s), from a small isentropic expansion. It is far lower than in either phase alone, which
    makes it the conservative choice.
  - Tested against the exact Fanno-flow solution for an ideal gas (agreement within 0.4 %).
- **Reverse flow:** a negative flow gives the mirror image of the forward result (friction and acceleration
  reversed, static head unchanged), so the pressure–flow solver sees a smooth function through zero flow.
- **Heat loss:** q′ = (T − T_amb) / [ln(r₂/r₁)/(2πk) + 1/(2πr₂h_o)], through the insulation and from the outer
  surface. The pipe wall and inside film are neglected.
- **Checks:**
  - Velocity: water about 3 m/s, saturated steam about 40 m/s, superheated steam about 60 m/s.
  - Erosional velocity for two-phase flow, API RP 14E: v_e = 122/√ρ m/s (C = 100).
  - Mach number above 0.3.

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
  - *Free pressure drop (steam trap / flow controller)*: the valve passes whatever flow arrives, and in
    pressure–flow mode its outlet pressure is set by what is downstream (the trap's back pressure).
- **Flow from pressures:** the pressure–flow solver needs the inverse, ṁ = f(Cv, inlet state, P₂). Cv is
  linear in ṁ at a fixed P₂, so the same equations are solved for the flow, including the choked limits. Near
  zero pressure drop √ΔP is replaced by ΔP/√(|ΔP| + δ) with a tiny δ, and the flow is negative when P₂ is above
  the inlet pressure, so the function is smooth for Newton's method.

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

### Solving: sequential mode (default)

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

In this mode flows come from specifications and demands. A pipe's pressure drop is calculated from its flow,
but it does not change the flow, so parallel branches do not share the flow by their resistance.

### Solving: pressure–flow mode

Chosen in the toolbar (or `fs.solver_mode = "pressure_flow"`). **Every stream's mass flow and pressure are
unknowns, solved together**, so the flow divides between parallel branches until their pressure drops are
equal, a pump runs where its curve meets the system curve, and a trap's back pressure is found from the
return line. Enthalpies are held fixed during each solve and updated in an outer loop.

**Equations.** Each piece of equipment contributes as many equations as it has outlets (plus one per
Specification):

| Equipment | Pressure–flow equations |
|---|---|
| Supply | Fixed: ṁ and P. As required: P only. Pressure reference (expansion tank): P only, flow free (it settles at zero in a closed loop) |
| Product / sink | Pressure: P = set. Flow: ṁ = set. A loose product stream adds nothing |
| Specification | fixes one stream's flow or pressure (replaces many Adjusts) |
| Pipe | ṁ_out = ṁ_in; P_out = P_in − ΔP_march(ṁ, P_in, h_in), the full pipe calculation with a fixed segment count |
| Valve | ṁ_out = ṁ_in, and one of: P_out = set (regulating; wide open at its rated Cv if the inlet pressure falls too low); ΔP = set; ṁ = f(Cv·opening, P_in, P_out); free pressure drop (from downstream) |
| Check valve | open: ṁ = f(Cv, P_in − ΔP_crack, P_out), the valve flow equation after the cracking pressure; closed (when the flow would reverse): ṁ = 0 |
| Pump | ṁ_out = ṁ_in; P_out = set, P_out − P_in = set, or P_out − P_in = ρgH(Q) from the curve |
| Compressor, turbine | ṁ_out = ṁ_in; P_out = set |
| Heater, condenser, exchanger sides | ṁ_out = ṁ_in; ΔP = set, or ΔP = ΔP_r·(ṁ\|ṁ\|/ṁ_r²)·(ρ_r/ρ) ("scales with flow²"). Condensing heater: ṁ_h·Δh_h = ṁ_c·Δh_c |
| Boiler | P_steam = P_bd = set; ṁ_steam = (1 − b)ṁ_fw; ṁ_bd = b·ṁ_fw |
| Mixer | mass balance, and all inlets at the outlet pressure (junction), or outlet at the lowest inlet pressure, or set |
| Splitter, header | mass balance; outlets at the inlet (or header) pressure; outlet flow specifications, with "Pressure-driven" outlets left to the hydraulics |
| Flash vessel | P = set; ṁ_vapour = x·ṁ_in |
| Deaerator | P = set; ṁ_s·h_s + Σṁ_w·h_w = ṁ_out(h_f + r·h_g); vent = r·ṁ_out; mass balance |
| Desuperheater | ṁ_w(h_t − h_w) = ṁ_s(h_s − h_t); P_out = P_steam |
| Process steam user | ṁ(h_s − h_c) = Q; condensate return = r·ṁ |
| Vessel inlets (boiler, header, flash vessel, deaerator) | "Open" inlets add P_inlet = P_vessel, so the upstream line's back pressure (or a pump's flow into a drum) is found; "Throttled" inlets assume a valve or trap drops the pressure |

With h frozen, the energy balances are linear in the flows, so they are exact at convergence.

**Closed loops.** The flowsheet is split into connected parts. A part with no supply, sink or product
stream is a closed loop: one of its mass balances is redundant and is dropped (and checked afterwards), and
it needs a pressure reference (an expansion tank supply, or a set pressure) and something that fixes its
circulating flow (a pump curve against the loop's resistance, or a flow specification).

**Checking the specifications.** Before solving:

- A *structural check* matches equations to unknowns (maximum bipartite matching). Unmatched unknowns and
  surplus equations are explained in plain words, e.g. "nothing sets the pressure of S5 (between L-102 and
  E-101): add a sink with a pressure, set the supply to As required, or …".
- A *rank check* (singular values of the scaled Jacobian) catches what the structure cannot: a closed loop
  with nothing to fix its flow, a choked valve that is the only thing setting a pressure, or a branch with
  no flow. The unknowns in the null space name the problem.

**Newton's method.**

1. Starting point: the sequential solution (errors allowed), or the previous answer (warm start). If that is
   far off, a stand-in network is solved first in which every pipe, pump curve and valve is replaced by
   ΔP = ΔP₀ + R·ṁ|ṁ| fitted to the real element. It needs no property calls and lands Newton close to the
   answer.
2. Variables are scaled (flows by a typical flow, pressures by 100 kPa) and each equation by its natural size.
3. The Jacobian is found by finite differences, then kept up to date with Broyden's update; it is recomputed
   when convergence slows, and reused by the next solve if the equations have not changed.
4. Each step has an Armijo line search, cannot cut a pressure below 20 % of its value, and is halved when an
   evaluation fails (e.g. a pipe chokes). If steps still fail, Levenberg–Marquardt steps are used.
5. Converged when every scaled residual is below 10⁻⁸.

**Switching equipment states** (checked after each solve, with the solve repeated if anything changes):

- a pressure-reducing valve that cannot hold its set pressure goes wide open at its rated Cv;
- a check valve that would need reverse flow closes, and reopens when the pressure difference allows;
- a "lowest inlet" mixer's limiting inlet is re-chosen.

**Outer loop.** With flows and pressures locked at the network solution, the equipment calculations run
forward to update every enthalpy (and the results), and the network is solved again until the enthalpies
stop changing (10⁻⁸ relative). A final pass produces the reports, and the mass and energy balances are
checked. If any flow would run backwards, the solve reports where.

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
   - The relieving rate is fixed, a factor times the stream flow, or worked out from API 521 scenarios
     (below).
8. **Warnings:**
   - back pressure above 10 % of set pressure for conventional valves;
   - set pressure at or below the operating pressure;
   - flashing discharge;
   - estimated KSH;
   - multiple valves needed;
   - confirm with certified data.

### Relieving rate from scenarios (API 521)

Each scenario works out the relieving rate and what is relieved (steam, wet steam or water, and its condition
at the relieving pressure). **Every enabled scenario is sized in its own fluid and overpressure basis**: fire
uses the fire case (21 %), a boiler uses ASME Section I (3 %), the others the valve's chosen basis. **The
scenario needing the largest orifice area governs.**

| Scenario | Rate |
|---|---|
| External fire (vessel containing water) | Wetted area A_ws: the wetted surface within 7.6 m of grade (vertical or horizontal vessel, flat heads; or entered). Q = C·F·A_ws^0.82 kW, with C = 43.2 with adequate drainage and fire-fighting, otherwise 70.9, and F the environment factor (1.0 bare, 0.03 earth-covered, 0 below grade, or entered). W = Q/λ at P₁ (saturated steam; sensible heating ignored) |
| Control valve fails open | The valve's flow equation (IEC 60534) at full opening from the highest upstream pressure to P₁, plus its bypass if open in normal operation, less any credit for normal outflow |
| Blocked outlet | A pump against its curve: H = (P₁ − P_s)/ρg, Q = Q_r√((H₀ − H)/(H₀ − H_r)); or a supply through a fully open valve; or a given flow |
| Tube rupture | Two orifices of the tube bore (both ends of a clean break): W = 2·C_d·(πd²/4)·G, with G from isentropic homogeneous expansion of the high-pressure fluid to P₁. Excluded when the low-pressure side's design pressure is at least 10/13 of the high-pressure side's |
| Thermal expansion of blocked-in water | W = α_v·Φ/c_p, with α_v = −(1/ρ)(∂ρ/∂T) from IAPWS-IF97 |
| Loss of cooling (condenser) | All the steam flowing in |
| Abnormal heat input | Q = UA·(T_h − T_sat(P₁)); W = Q/λ |
| Boiler maximum continuous rating | W = W_MCR (ASME Section I) |
| Given rate | As entered |

On the P&ID a scenario can name equipment on the drawing, and its values are then taken from the solved
flowsheet: a control valve's rated Cv and inlet state, a pump's curve and suction, a condenser's steam
flow, an exchanger's UA and heating temperature, or a boiler's steam flow.

### Inlet pressure loss (API 520 Part II, 3 % rule)

The inlet line from the protected equipment to the valve is calculated with the full pipe method (above) at
the valve's **rated** capacity (what the selected orifice actually passes, not the required rate), starting
at the relieving pressure. Only the non-recoverable losses (friction, entrance and fittings) count against
3 % of the set pressure (gauge); static head and acceleration are reported separately. Every scenario is
checked.

### Built-up back pressure (discharge line)

- The discharge line carries the rated flow from the valve outlet to the atmosphere or a header (the
  header's pressure is the superimposed back pressure).
- The march starts from the relieving fluid's stagnation enthalpy: at the valve outlet the static enthalpy is
  lower by the kinetic energy.
- The lowest valve-outlet pressure at which the line does not choke internally is found by bisection.
  - If the exit pressure there is still above the destination pressure, the exit is choked (sonic) and that
    is the answer.
  - Otherwise the outlet pressure that brings the exit to the destination pressure is found by Brent's method.
- The total back pressure (superimposed + built-up) changes the sizing, so sizing and discharge
  calculation are repeated until neither the orifice nor the back pressure changes.
- Limits: for a conventional valve the built-up back pressure should not exceed the scenario's allowable
  overpressure (10, 16 or 21 % of set); for a balanced bellows valve the total back pressure should not
  exceed about 50 % (with Kb from the manufacturer); for a pilot-operated valve, the manufacturer's limit.

### Reaction force (open discharge)

- Momentum balance at the exit: F = ṁ·v_e + (P_e − P_atm)·A_e, from the exit state of the discharge-line
  calculation.
- Cross-check for vapour, API 520 Part II's formula: F = ṁ·√(2kR_uT₁/((k + 1)M)) + (P_e − P_atm)·A_e (in SI
  units). It treats the steam as an ideal gas leaving at the speed of sound from the relieving temperature.
  The larger of the two is reported.
- This is the steady force. The load is applied suddenly when the valve opens: design supports for up to
  twice the value (dynamic load factor up to 2) unless a dynamic analysis shows otherwise.

Out of scope: closed relief-header networks (several valves discharging into a shared header at once), and
transient (pop-open) loads beyond the dynamic load factor.
