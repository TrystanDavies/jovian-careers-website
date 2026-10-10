# Steam Suite

A **P&ID designer and steady-state simulator for water and steam systems**, in the spirit of Aspen HYSYS but
focused on water and steam. Draw the plant by dragging equipment onto a P&ID and connecting nozzles; the
simulator calculates the heat and mass balance and the pipe pressure drops as you draw. It also sizes control
valves and relief valves. Every result can be opened to show the equations used, with the numbers substituted.

![P&ID designer with a steam distribution system](docs/images/designer-pipe.png)

## What it does

| Area | Capabilities |
|---|---|
| **P&ID drawing** | Drag-and-drop palette of ISA-style symbols; connect nozzles by dragging; orthogonal pipe routing you can adjust; move, rotate, flip, copy/paste, duplicate, delete; undo/redo; pan and zoom; automatic tidy layout; stream data tags on every line (draggable); lines coloured by phase (steam, wet steam, water); export the drawing as SVG |
| **Heat and mass balance** | Solves automatically after every change. Handles recycle loops and "as required" flows (a deaerator works out its heating steam and make-up water, a header asks its balancing supply for the shortfall, a condensing heater finds its steam flow). Overall mass and energy balance checks |
| **Pressure drop** | Pipe segments: ASME B36.10M sizes and schedules, length, elevation change, roughness, Crane TP-410 fittings and valves, insulation heat loss. Water, steam (compressible) and two-phase flow (Müller-Steinhagen & Heck or homogeneous). Velocity, Mach number and erosional velocity checks; condensate formed by heat loss; flashing |
| **Valves and pumps** | Control valves: Cv required and opening (IEC 60534), or the pressure drop from a given Cv and opening; choked flow, flashing and cavitation checks. Pumps: outlet pressure, pressure rise or a pump curve; NPSH available vs required |
| **Heat exchangers** | Two-stream exchanger analysed in zones (correct for condensing and boiling); specify an outlet temperature, dryness, duty, UA (rating) or minimum approach; condensing-heater mode; temperature–duty (T–Q) diagram; temperature-cross detection |
| **Relief valves** | Place a PSV on any line: it is sized to API 520 from that line's conditions, with an API 526 orifice. A stand-alone relief sizing page covers saturated, superheated and wet steam, and hot water including flashing |
| **HYSYS-style tools** | Adjust (goal seek: vary one setting to hit a target); Case study (vary a setting over a range, table, charts and CSV); workbook of streams, equipment, piping and relief valves; downloadable calculation reports (HTML/Markdown) |
| **Properties** | IAPWS-IF97 steam tables page with a temperature–entropy chart |

Units: metric (bar g, °C, t/h), metric absolute, SI (kPa a, kg/s) or US customary (psig, °F, lb/h).

### Equipment

Water/steam supply · Pump · Steam compressor · Valve / control valve · Steam turbine · Boiler · Heater/cooler ·
Heat exchanger · Condenser · Pipe segment · Mixer · Splitter · Steam header · Flash vessel · Desuperheater ·
Deaerator / open feedwater heater · Process steam user · Pressure relief valve (PSV) · Adjust (goal seek)

> **Important:** these are preliminary engineering calculations. Results used for design, and especially for
> pressure relief, must be checked by a qualified engineer against the codes and editions that apply to your
> equipment, using manufacturers' certified data.

## Getting started

```bash
cd steam-suite
python -m pip install -r requirements.txt
python -m steamsuite.web
```

Your browser opens at http://localhost:8000 with an example loaded. Then:

1. **Draw**: drag equipment from the palette on the left onto the drawing (or click an item, then click the
   drawing).
2. **Connect**: hover over a unit to see its nozzles. Drag from an outlet (filled dot) to an inlet (open dot).
   Drag an outlet into empty space for a stream leaving the system; drag an inlet into empty space to create a
   water/steam supply.
3. **Set up**: click a unit or line and fill in its settings on the right. Right-click a line to insert a pipe
   segment, valve, heater or relief valve.
4. **Read the results**: the drawing, the workbook (bottom) and each unit's **Results** and **Calculation** tabs
   update after every change. Press **?** in the top bar for all shortcuts.
5. **Save** the flowsheet (.json), **Export drawing** (.svg) and download a **Report**.

Keyboard: `Del` delete · `R` rotate · `F` flip · `Ctrl+D` duplicate · `Ctrl+C`/`Ctrl+V` copy/paste ·
`Ctrl+Z`/`Ctrl+Y` undo/redo · mouse wheel zoom · right/middle-drag pan · `0` fit to window.

Your work is saved in the browser automatically, and restored when you come back.

## Screenshots

| Heat exchanger T–Q diagram | Relief valve on the P&ID, sized from its line |
|---|---|
| ![Heat exchanger results](docs/images/designer-heat-exchanger.png) | ![Relief valve calculation](docs/images/designer-relief-valve.png) |

![Industrial steam system](docs/images/designer-industrial.png)

| Relief valve sizing | Steam tables |
|---|---|
| ![Relief valve sizing](docs/images/relief-sizing.png) | ![Steam tables](docs/images/steam-tables.png) |

## Examples included

- **Steam distribution with pipes and relief valves**: boiler house, 200 m insulated steam main, PRV station,
  process heater, steam trap, flashing two-phase condensate return lifted 5 m, receiver and pump. Two relief
  valves, and an Adjust that finds the boiler pressure needed for 10 bar(g) at the end of the main.
- **Industrial steam system**: boiler, two headers, back-pressure turbine, PRV and desuperheater, flash steam
  recovery, condensate return, deaerator.
- **Rankine cycle with closed feedwater heater**.
- **Simple and regenerative Rankine cycles**, which match textbook results.

## Using the library from Python

```python
from steamsuite.examples import steam_distribution

fs = steam_distribution()
fs.solve()
print(fs.blocks["L-101 Steam main"].results["dP"].value, "kPa")   # pipe pressure drop
print(fs.blocks["PSV-101"].results["orifice"].value)               # API 526 orifice
print(fs.report().to_markdown())                                   # full calculation report
```

```python
from steamsuite.relief import ReliefInput, size_relief_valve

res = size_relief_valve(ReliefInput(fluid="saturated_steam", flow_kg_h=10_000, set_pressure_kpag=1_000))
print(res.orifice, round(res.required_area_mm2))   # L 1626
```

The web app talks to the same library through a small JSON API (`/api/solve`, `/api/relief`,
`/api/properties`, `/api/case-study`, ...). See `steamsuite/web/server.py`.

## Project layout

```
steam-suite/
├── steamsuite/
│   ├── water.py          IAPWS-IF97 properties (CoolProp fast path, iapws fallback)
│   ├── hydraulics.py     pipe friction, fittings, two-phase flow, heat loss, control valves
│   ├── exchanger.py      zone analysis of two-stream heat exchangers
│   ├── relief.py         relief valve sizing (API 520 / 526)
│   ├── report.py         step-by-step calculation reports
│   ├── examples.py       example flowsheets
│   ├── flowsheet/        equipment models, solver, Adjust, case studies, auto-layout
│   └── web/              FastAPI server and the browser app (plain JavaScript and SVG, no build step)
├── tests/                pytest suite, plus tests/e2e/designer_e2e.mjs (browser test)
└── docs/                 METHODS.md (equations), VALIDATION.md (checks), screenshots
```

## Tests

```bash
python -m pytest                                   # 106 tests: properties, hydraulics, equipment, solver, API
python -m steamsuite.web --no-browser &            # then, with Playwright installed:
node tests/e2e/designer_e2e.mjs                    # 32 browser checks: drawing, connecting, editing, undo, ...
```

See [docs/VALIDATION.md](docs/VALIDATION.md) for what each check compares against.

## Limitations

- Steady state only (no dynamics, start-up or control loops).
- Water and steam only (no dissolved gases, glycols or other fluids).
- Flows are set by specifications and "as required" demands, not by a pressure–flow network solve. Parallel
  pipe branches don't share flow by hydraulics automatically; use Adjust to match pressures where needed.
- Relief sizing needs the relieving rate as an input (no scenario analysis per API 521). Inlet pressure-loss
  (3 %) checks, discharge piping and reaction forces are not included.
- Two-phase pressure-drop correlations are typically accurate to about ±30 %.
