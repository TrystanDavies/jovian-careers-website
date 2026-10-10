# Calculation methods

Internal units throughout: pressure kPa(a), temperature °C, mass flow kg/s, enthalpy kJ/kg, entropy
kJ/(kg·K), power kW. The user interface converts to and from the units you choose.

## Properties

All water and steam properties come from **IAPWS-IF97** (the `iapws` Python package). States can be defined
by (P, T), (P, h), (P, s), (P, x) or (T, x). Streams are stored as pressure and enthalpy, because temperature
alone cannot tell wet steam from saturated water or saturated steam.

## Steam system simulator

### Equipment equations

| Equipment | Equations |
|---|---|
| Pump | h₂ₛ = h(P₂, s₁); h₂ = h₁ + (h₂ₛ − h₁)/η; W = ṁ(h₂ − h₁); W_elec = W/η_motor |
| Turbine | h₂ₛ = h(P₂, s₁); h₂ = h₁ − η(h₁ − h₂ₛ); W = ṁ(h₁ − h₂); W_elec = W·η_gen |
| Valve / PRV | h₂ = h₁ (isenthalpic) |
| Boiler | ṁ_bd = b·ṁ_fw; Q = ṁ_s·h_s + ṁ_bd·h_f − ṁ_fw·h_fw; Q_fuel = Q/η |
| Heater / cooler | Q = ṁ(h₂ − h₁), with h₂ from the outlet temperature or dryness, or h₂ = h₁ + Q/ṁ |
| Condenser | h₂ = h_f(P) (or subcooled); ṁ_cw = Q/(c_p·ΔT_cw) |
| Mixer / header | ṁ = Σṁᵢ; h = Σṁᵢhᵢ / ṁ; header outlets at the header pressure |
| Flash vessel | x = (h_in − h_f)/(h_g − h_f); flash steam = x·ṁ |
| Desuperheater | ṁ_w = ṁ_s(h_s − h_target)/(h_target − h_w) |
| Deaerator | ṁ_s + Σṁ_w = ṁ_out(1 + r); ṁ_s·h_s + Σṁ_w·h_w = ṁ_out(h_f + r·h_g) |
| Process steam user | ṁ_s = Q/(h_s − h_c); condensate return = r·ṁ_s |

### Solving

The flowsheet is solved by **successive substitution**. Each iteration has two sweeps:

1. **Backward (demands):** equipment asks upstream equipment for the flow it needs. Examples: a process user
   asks for steam, a header asks its balancing supply for the shortfall, a boiler asks for feedwater
   (steam ÷ (1 − blowdown)), a deaerator asks for heating steam and make-up water (solving its mass and energy
   balance), a desuperheater asks for spray water.
2. **Forward (states):** each piece of equipment calculates its outlets from the actual inlet flows, so mass
   and energy are always conserved exactly. Demands are requests that upstream equipment meets on the next
   iteration.

Recycle loops are broken with starting estimates from the source equipment's settings. Iteration stops when
no flow, pressure, enthalpy or demand changes by more than one part in 10⁹ over two successive iterations.
Afterwards the overall mass and energy balances are checked and reported.

## Relief valve sizing

1. **Relieving pressure:** P₁ = P_set + ΔP_over + P_atm. ΔP_over is the chosen percentage of the set pressure,
   with the ASME minimum for low set pressures (3 psi single valve, 4 psi multiple valves, 2 psi Section I).
2. **Fluid state** at P₁ from IAPWS-IF97.
3. **Method:**
   - *Saturated or superheated steam, choked flow:* API 520 steam equation (Napier),
     A = 190.4·W / (P₁·Kd·Kb·Kc·KN·KSH), with A in mm², W in kg/h and P₁ in kPa(a).
     KN = 1 for P₁ ≤ 10,339 kPa, otherwise (0.02764·P₁ − 1000)/(0.03324·P₁ − 1061).
     KSH is 1 for saturated steam. For superheated steam it is either entered by the user or estimated as the
     ratio of ideal critical mass fluxes, superheated to saturated.
   - *Steam in subcritical flow, or above 22,057 kPa(a):* direct integration (below).
   - *Water that does not flash* (vapour pressure below the back pressure): API 520 liquid equation,
     A = 11.78·Q / (Kd·Kw·Kc·Kv)·√(G/(P₁ − P₂)), with Q in L/min. Kv is found by iteration from the
     Reynolds number and capped at 1.
   - *Wet steam, and water that flashes:* direct integration (below).
4. **Direct integration (HDI, API 520 Annex C):** the fluid is expanded isentropically from P₁ assuming
   homogeneous equilibrium. At each pressure P, G(P) = ρ(P, s₁)·√(2·(h₁ − h(P, s₁))). The throat condition is
   the maximum of G between the back pressure and P₁ (choked flow), or G at the back pressure if G is still
   rising there. A = W/(Kd·Kb·Kc·G).
5. **Discharge coefficients:** Kd = 0.975 for vapour and 0.65 for liquid (API effective values). For two-phase
   flow the default is 0.85, a commonly used preliminary value. A subcooled liquid that is still liquid at the
   throat uses 0.65. Kc = 0.9 with an upstream rupture disk. Kb (and Kw for liquids) apply to balanced bellows
   valves only, from the manufacturer's curve. For conventional and pilot-operated valves, back pressure
   effects are captured by the flow calculation itself.
6. **Orifice:** the smallest API 526 letter (D to T) with at least the required effective area. Rated
   capacity = W·A_orifice/A_required.
7. **Warnings:** back pressure above 10 % of set for conventional valves, flashing discharge, estimated KSH,
   multiple valves needed, and the need to confirm with certified data.

Out of scope for version 0.1: determining the relieving rate (API 521 scenarios), inlet pressure loss
(API 520 Part II's 3 % rule), discharge piping, and reaction forces.
