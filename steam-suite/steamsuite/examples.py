"""Ready-made example flowsheets."""

from __future__ import annotations

from .flowsheet import Flowsheet
from .flowsheet.blocks import (
    Boiler,
    CheckValve,
    Condenser,
    Deaerator,
    Desuperheater,
    Feed,
    FlashVessel,
    Header,
    Mixer,
    Heater,
    Pump,
    Sink,
    Splitter,
    SteamUser,
    Turbine,
    Valve,
)
from .flowsheet.advanced import Adjust, HeatExchanger, Pipe, ReliefValveUnit, Specification
from .units import P_ATM_KPA


def _place(fs: Flowsheet, positions: dict, ends: dict | None = None, labels: dict | None = None,
           mids: dict | None = None) -> Flowsheet:
    """Drawing positions: name -> (x, y[, rotation, flip]); ends: product stream -> (x, y);
    labels: stream -> (dx, dy) label offset; mids: stream -> (axis, value) middle segment position."""
    nodes = {}
    for name, p in positions.items():
        x, y, *rest = p
        nodes[name] = {"x": x, "y": y, "rot": rest[0] if rest else 0, "flip": rest[1] if len(rest) > 1 else False}
    streams: dict = {}
    for k, v in (ends or {}).items():
        streams.setdefault(k, {})["end"] = {"x": v[0], "y": v[1]}
    for k, v in (labels or {}).items():
        streams.setdefault(k, {})["label"] = {"dx": v[0], "dy": v[1]}
    for k, v in (mids or {}).items():
        streams.setdefault(k, {})["mid"] = {"axis": v[0], "v": v[1]}
    fs.layout = {"nodes": nodes, "streams": streams}
    return fs


def barg(v: float) -> float:
    """bar(g) to kPa(a)."""
    return v * 100.0 + P_ATM_KPA


def kpa(v: float) -> float:
    """kPa(a), for readability."""
    return v


def t_h(v: float) -> float:
    """t/h to kg/s."""
    return v / 3.6


def industrial_steam_system() -> Flowsheet:
    fs = Flowsheet(
        "Industrial steam system",
        "Boiler at 10.5 bar(g) feeding a 10 bar(g) header, a back-pressure turbine and a PRV with desuperheater "
        "down to a 3 bar(g) header, flash steam recovery, condensate return and a deaerator. Steam generation, "
        "PRV flow, spray water, deaerator steam and make-up water are all calculated to match the process demands.",
    )
    fs.add(Feed("Make-up water", outlets={"out": "Make-up water"},
                params={"pressure": barg(3), "temperature": 15.0, "flow_mode": "As required", "flow": 1.0}))
    fs.add(Deaerator("Deaerator", inlets={"steam": "DA steam", "water": ["Make-up water", "Condensate return"]},
                     outlets={"out": "DA outlet", "vent": "DA vent"},
                     params={"pressure": barg(0.3), "vent": 0.1, "makeup_inlet": "Make-up water"}))
    fs.add(Pump("Feed pump", inlets={"in": "DA outlet"}, outlets={"out": "Feedwater"},
                params={"outlet_pressure": barg(13), "efficiency": 70.0, "motor_efficiency": 95.0}))
    fs.add(Splitter("Feedwater split", inlets={"in": "Feedwater"}, outlets={"out": ["Boiler feed", "Spray water"]},
                    params={"outlet_specs": {"Boiler feed": {"mode": "As required", "value": 0.0},
                                             "Spray water": {"mode": "As required", "value": 0.0}}}))
    fs.add(Boiler("Boiler", inlets={"in": "Boiler feed"}, outlets={"steam": "HP steam", "blowdown": "Blowdown"},
                  params={"pressure": barg(10.5), "steam_condition": "Superheated", "temperature": 250.0,
                          "efficiency": 85.0, "blowdown": 3.0}))
    fs.add(Header("HP header (10 bar g)", inlets={"in": ["HP steam"]},
                  outlets={"out": ["Process A steam", "Turbine steam", "PRV steam"]},
                  params={"pressure": barg(10), "balancing_inlet": "HP steam",
                          "outlet_specs": {"Process A steam": {"mode": "As required", "value": 0.0},
                                           "Turbine steam": {"mode": "Flow", "value": t_h(4.0)},
                                           "PRV steam": {"mode": "As required", "value": 0.0}}}))
    fs.add(SteamUser("Process A", inlets={"in": "Process A steam"},
                     outlets={"condensate": "Process A condensate", "loss": "Process A losses"},
                     params={"spec": "Steam flow", "flow": t_h(5.0), "return_percent": 80.0}))
    fs.add(FlashVessel("Flash vessel", inlets={"in": "Process A condensate"},
                       outlets={"vapour": "Flash steam", "liquid": "Flash condensate"},
                       params={"pressure": barg(3)}))
    fs.add(Turbine("Back-pressure turbine", inlets={"in": "Turbine steam"}, outlets={"out": "Turbine exhaust"},
                   params={"outlet_pressure": barg(3), "efficiency": 65.0, "generator_efficiency": 95.0}))
    fs.add(Valve("PRV", inlets={"in": "PRV steam"}, outlets={"out": "PRV outlet"},
                 params={"outlet_pressure": barg(3)}))
    fs.add(Desuperheater("Desuperheater", inlets={"steam": "PRV outlet", "water": "Spray water"},
                         outlets={"out": "Desuperheated steam"},
                         params={"spec": "Superheat above saturation", "superheat": 10.0}))
    fs.add(Header("LP header (3 bar g)", inlets={"in": ["Turbine exhaust", "Flash steam", "Desuperheated steam"]},
                  outlets={"out": ["Process B steam", "DA steam"]},
                  params={"pressure": barg(3), "balancing_inlet": "Desuperheated steam",
                          "outlet_specs": {"Process B steam": {"mode": "As required", "value": 0.0},
                                           "DA steam": {"mode": "As required", "value": 0.0}}}))
    fs.add(SteamUser("Process B", inlets={"in": "Process B steam"},
                     outlets={"condensate": "Process B condensate", "loss": "Process B losses"},
                     params={"spec": "Heat duty", "duty": 3000.0, "return_percent": 70.0, "subcooling": 50.0}))
    fs.add(Mixer("Condensate return", inlets={"in": ["Flash condensate", "Process B condensate"]},
                 outlets={"out": "Condensate return"}))
    return _place(fs, {
        "Boiler": (140, 170), "HP header (10 bar g)": (560, 90), "Process A": (420, 260),
        "Back-pressure turbine": (620, 270), "PRV": (800, 259), "Desuperheater": (960, 264),
        "Flash vessel": (380, 450), "LP header (3 bar g)": (780, 420), "Process B": (860, 570),
        "Condensate return": (580, 680, 0, True), "Deaerator": (280, 720, 0, True), "Make-up water": (90, 560),
        "Feed pump": (440, 880), "Feedwater split": (600, 862),
    }, ends={"Blowdown": (140, 270), "Process A losses": (520, 350), "Process B losses": (960, 670),
             "DA vent": (340, 630)},
       mids={"Boiler feed": ("y", 960), "Spray water": ("x", 1080)})


def simple_rankine() -> Flowsheet:
    """Ideal simple Rankine cycle: 3 MPa / 350 °C, condenser at 75 kPa."""
    fs = Flowsheet(
        "Simple Rankine cycle",
        "Ideal Rankine cycle: steam enters the turbine at 3 MPa and 350 °C and is condensed at 75 kPa(a). "
        "The cycle is opened at the condenser outlet: the supply is saturated water at condenser pressure, "
        "and the condensate leaving the condenser has the same state. Textbook result: efficiency 26.0 %.",
    )
    fs.add(Feed("Condensate (cycle start)", outlets={"out": "1 Pump inlet"},
                params={"pressure": kpa(75), "condition": "Dryness fraction", "dryness": 0.0, "flow": 10.0}))
    fs.add(Pump("Feed pump", inlets={"in": "1 Pump inlet"}, outlets={"out": "2 Boiler inlet"},
                params={"outlet_pressure": kpa(3000), "efficiency": 100.0, "motor_efficiency": 100.0}))
    fs.add(Boiler("Boiler", inlets={"in": "2 Boiler inlet"}, outlets={"steam": "3 Turbine inlet"},
                  params={"pressure": kpa(3000), "steam_condition": "Superheated", "temperature": 350.0,
                          "efficiency": 100.0}))
    fs.add(Turbine("Turbine", inlets={"in": "3 Turbine inlet"}, outlets={"out": "4 Condenser inlet"},
                   params={"outlet_pressure": kpa(75), "efficiency": 100.0, "generator_efficiency": 100.0}))
    fs.add(Condenser("Condenser", inlets={"in": "4 Condenser inlet"}, outlets={"out": "5 Condensate"}))
    return fs


def regenerative_rankine() -> Flowsheet:
    """Ideal regenerative Rankine cycle with one open feedwater heater."""
    fs = Flowsheet(
        "Regenerative Rankine cycle",
        "Ideal regenerative Rankine cycle with one open feedwater heater: turbine inlet 15 MPa and 600 °C, "
        "extraction at 1.2 MPa, condenser at 10 kPa(a). The extraction steam needed by the heater is calculated "
        "automatically. Textbook result: 22.7 % of the steam is extracted and the efficiency is 46.3 %.",
    )
    fs.add(Feed("Condensate (cycle start)", outlets={"out": "1 Pump I inlet"},
                params={"pressure": kpa(10), "condition": "Dryness fraction", "dryness": 0.0, "flow": 10.0}))
    fs.add(Pump("Pump I", inlets={"in": "1 Pump I inlet"}, outlets={"out": "2 To heater"},
                params={"outlet_pressure": kpa(1200), "efficiency": 100.0, "motor_efficiency": 100.0}))
    fs.add(Deaerator("Open feedwater heater", inlets={"steam": "6 Extraction steam", "water": ["2 To heater"]},
                     outlets={"out": "3 Pump II inlet"}, params={"pressure": kpa(1200), "vent": 0.0}))
    fs.add(Pump("Pump II", inlets={"in": "3 Pump II inlet"}, outlets={"out": "4 Boiler inlet"},
                params={"outlet_pressure": kpa(15000), "efficiency": 100.0, "motor_efficiency": 100.0}))
    fs.add(Boiler("Boiler", inlets={"in": "4 Boiler inlet"}, outlets={"steam": "5 HP turbine inlet"},
                  params={"pressure": kpa(15000), "steam_condition": "Superheated", "temperature": 600.0,
                          "efficiency": 100.0}))
    fs.add(Turbine("HP turbine", inlets={"in": "5 HP turbine inlet"}, outlets={"out": "HP exhaust"},
                   params={"outlet_pressure": kpa(1200), "efficiency": 100.0, "generator_efficiency": 100.0}))
    fs.add(Splitter("Extraction", inlets={"in": "HP exhaust"}, outlets={"out": ["6 Extraction steam", "LP turbine inlet"]},
                    params={"outlet_specs": {"6 Extraction steam": {"mode": "As required", "value": 0.0},
                                             "LP turbine inlet": {"mode": "Remainder", "value": 0.0}}}))
    fs.add(Turbine("LP turbine", inlets={"in": "LP turbine inlet"}, outlets={"out": "7 Condenser inlet"},
                   params={"outlet_pressure": kpa(10), "efficiency": 100.0, "generator_efficiency": 100.0}))
    fs.add(Condenser("Condenser", inlets={"in": "7 Condenser inlet"}, outlets={"out": "Condensate out"}))
    return fs


def steam_distribution() -> Flowsheet:
    fs = Flowsheet(
        "Steam distribution with pipes and relief valves",
        "Steam from the boiler house travels 200 m along an insulated 4\" main to a pressure-reducing station, then "
        "60 m to a process heater that warms 8 kg/s of water from 40 to 90 °C. Condensate passes a steam trap, is "
        "lifted 5 m up a 3\" return line as a flashing two-phase flow, and is pumped from a vented receiver. "
        "An Adjust finds the boiler pressure that delivers 10 bar(g) at the end of the main; two relief valves are "
        "sized from the line conditions.",
    )
    fs.add(Feed("Boiler house", outlets={"out": "S1"},
                params={"pressure": barg(10.5), "condition": "Dryness fraction", "dryness": 1.0,
                        "flow_mode": "As required", "flow": 1.0}))
    fs.add(Pipe("L-101 Steam main", inlets={"in": "S1"}, outlets={"out": "S2"},
                params={"nps": "4", "schedule": "40", "length": 200.0,
                        "fittings": {"elbow_90_lr": 8, "gate": 2, "tee_run": 3},
                        "heat_loss": "Insulated", "ins_thickness": 50.0}))
    fs.add(Valve("PCV-101", inlets={"in": "S2"}, outlets={"out": "S3"},
                 params={"outlet_pressure": barg(4.0), "cv": 63.0, "characteristic": "Equal percentage"}))
    fs.add(Pipe("L-102 LP steam", inlets={"in": "S3"}, outlets={"out": "S4"},
                params={"nps": "4", "schedule": "40", "length": 60.0, "fittings": {"elbow_90_lr": 4, "gate": 1},
                        "heat_loss": "Insulated", "ins_thickness": 40.0}))
    fs.add(Feed("Process water", outlets={"out": "W1"},
                params={"pressure": barg(3.0), "temperature": 40.0, "flow": 8.0}))
    fs.add(HeatExchanger("E-101 Process heater", inlets={"hot_in": "S4", "cold_in": "W1"},
                         outlets={"hot_out": "S5", "cold_out": "W2"},
                         params={"spec": "Condensing heater (hot flow as required)", "cold_T": 90.0, "hot_x": 0.0,
                                 "dp_cold": 30.0}))
    fs.add(Valve("ST-101 Steam trap", inlets={"in": "S5"}, outlets={"out": "S6"},
                 params={"outlet_pressure": barg(1.0)}))
    fs.add(Pipe("L-103 Condensate return", inlets={"in": "S6"}, outlets={"out": "S7"},
                params={"nps": "3", "schedule": "40", "length": 100.0, "elevation": 5.0,
                        "fittings": {"elbow_90_std": 6, "check_swing": 1}}))
    fs.add(FlashVessel("V-101 Condensate receiver", inlets={"in": "S7"},
                       outlets={"vapour": "Flash steam to vent", "liquid": "C1"},
                       params={"pressure": barg(0.05)}))
    fs.add(Pump("P-101 Condensate pump", inlets={"in": "C1"}, outlets={"out": "C2"},
                params={"outlet_pressure": barg(3.0), "efficiency": 60.0, "npshr": 2.0, "suction_head": 3.0}))
    fs.add(ReliefValveUnit("PSV-101", params={"stream": "S3", "tag": "PSV-101", "set_pressure": barg(6.0),
                                              "rate_mode": "Stream flow × factor", "rate_factor": 1.0}))
    fs.add(ReliefValveUnit("PSV-102", params={"stream": "W2", "tag": "PSV-102", "set_pressure": barg(5.0),
                                              "rate_mode": "Fixed rate", "rate": 0.5}))
    fs.add(Adjust("ADJ-101", params={"var_block": "Boiler house", "var_param": "pressure",
                                     "target_type": "Stream property", "target_stream": "S2",
                                     "target_property": "Pressure", "target_value": barg(10.0),
                                     "lower": barg(10.0), "upper": barg(14.0)}))
    return _place(fs, {
        "ADJ-101": (130, 50), "Boiler house": (100, 160), "L-101 Steam main": (290, 160), "PCV-101": (470, 149),
        "PSV-101": (560, 60), "L-102 LP steam": (660, 160), "E-101 Process heater": (880, 230),
        "Process water": (700, 230), "PSV-102": (1010, 130), "ST-101 Steam trap": (820, 340, 0, True),
        "L-103 Condensate return": (620, 351, 0, True), "V-101 Condensate receiver": (430, 358, 0, True),
        "P-101 Condensate pump": (300, 470, 0, True),
    }, ends={"W2": (1080, 230), "Flash steam to vent": (430, 250), "C2": (150, 452)})


def rankine_closed_fwh() -> Flowsheet:
    fs = Flowsheet(
        "Rankine cycle with closed feedwater heater",
        "Turbine inlet 15 MPa and 600 °C, condenser at 10 kPa(a). Steam extracted at 1.2 MPa heats the feedwater in "
        "a closed (shell-and-tube) heater to 3 °C below the extraction saturation temperature; the drains are "
        "throttled back to the condenser. The extraction flow is found automatically.",
    )
    fs.add(Feed("Condensate (cycle start)", outlets={"out": "1"},
                params={"pressure": kpa(10), "condition": "Dryness fraction", "dryness": 0.0, "flow": 10.0}))
    fs.add(Pump("P-1 Feed pump", inlets={"in": "1"}, outlets={"out": "2"},
                params={"outlet_pressure": kpa(15000), "efficiency": 85.0, "motor_efficiency": 100.0}))
    fs.add(HeatExchanger("E-1 Feedwater heater", inlets={"hot_in": "6", "cold_in": "2"},
                         outlets={"hot_out": "7", "cold_out": "3"},
                         params={"spec": "Condensing heater (hot flow as required)", "cold_T": 184.97, "hot_x": 0.0}))
    fs.add(Boiler("B-1 Boiler", inlets={"in": "3"}, outlets={"steam": "4"},
                  params={"pressure": kpa(15000), "steam_condition": "Superheated", "temperature": 600.0,
                          "efficiency": 100.0}))
    fs.add(Turbine("T-1 HP turbine", inlets={"in": "4"}, outlets={"out": "5"},
                   params={"outlet_pressure": kpa(1200), "efficiency": 87.0, "generator_efficiency": 100.0}))
    fs.add(Splitter("Extraction", inlets={"in": "5"}, outlets={"out": ["6", "8"]},
                    params={"outlet_specs": {"6": {"mode": "As required", "value": 0.0},
                                             "8": {"mode": "Remainder", "value": 0.0}}}))
    fs.add(Turbine("T-2 LP turbine", inlets={"in": "8"}, outlets={"out": "9"},
                   params={"outlet_pressure": kpa(10), "efficiency": 87.0, "generator_efficiency": 100.0}))
    fs.add(Valve("Drain valve", inlets={"in": "7"}, outlets={"out": "10"}, params={"outlet_pressure": kpa(10)}))
    fs.add(Mixer("Hotwell", inlets={"in": ["9", "10"]}, outlets={"out": "11"}))
    fs.add(Condenser("C-1 Condenser", inlets={"in": "11"}, outlets={"out": "12"}))
    return fs


def empty() -> Flowsheet:
    return Flowsheet("New flowsheet", "")


PD = {"mode": "Pressure-driven", "value": 0.0}
TRAP = "Free pressure drop (steam trap / flow controller)"


def cooling_water_network() -> Flowsheet:
    """Pump on a curve feeding three parallel coolers; the flows split by hydraulics."""
    fs = Flowsheet(
        "Cooling-water network (pressure–flow)",
        "A cooling-water pump draws from the tower basin and feeds three process coolers in parallel, each with "
        "its own branch line and balancing valve; the water returns to the top of the tower. Solved in "
        "pressure–flow mode: the pump runs where its curve meets the system's resistance, and the flow divides "
        "between the branches until their pressure drops are equal. Try closing a balancing valve, or changing a "
        "branch length, and watch the flows redistribute.",
    )
    fs.solver_mode = "pressure_flow"
    fs.add(Feed("Tower basin", outlets={"out": "CW1"},
                params={"pressure": P_ATM_KPA, "temperature": 30.0, "flow_mode": "As required", "flow": 40.0}))
    fs.add(Pump("P-201", inlets={"in": "CW1"}, outlets={"out": "CW2"},
                params={"mode": "Pump curve", "shutoff_head": 48.0, "rated_flow": 150.0, "rated_head": 38.0,
                        "efficiency": 78.0, "npshr": 4.0, "suction_head": 2.0}))
    fs.add(Pipe("L-201 CW supply header", inlets={"in": "CW2"}, outlets={"out": "CW3"},
                params={"nps": "6", "length": 120.0, "elevation": 6.0,
                        "fittings": {"elbow_90_lr": 4, "gate": 2, "check_swing": 1}}))
    fs.add(Splitter("Supply manifold", inlets={"in": "CW3"}, outlets={"out": ["CW-A1", "CW-B1", "CW-C1"]},
                    params={"outlet_specs": {"CW-A1": PD, "CW-B1": PD, "CW-C1": PD}}))
    branches = (("A", 40.0, 800.0, 60.0), ("B", 70.0, 600.0, 80.0), ("C", 110.0, 1000.0, 100.0))
    returns = []
    for tag, length, duty, opening in branches:
        fs.add(Pipe(f"L-20{ord(tag) - 63} branch {tag}", inlets={"in": f"CW-{tag}1"}, outlets={"out": f"CW-{tag}2"},
                    params={"nps": "3", "length": length, "fittings": {"elbow_90_std": 4, "gate": 2, "tee_branch": 1}}))
        fs.add(Heater(f"E-20{ord(tag) - 64} cooler {tag}", inlets={"in": f"CW-{tag}2"}, outlets={"out": f"CW-{tag}3"},
                      params={"spec": "Heat duty", "duty": duty, "dp_mode": "Scales with flow²",
                              "pressure_drop": 50.0, "rated_flow": 12.0}))
        fs.add(Valve(f"HV-20{ord(tag) - 64}", inlets={"in": f"CW-{tag}3"}, outlets={"out": f"CW-{tag}4"},
                     params={"mode": "Cv and opening", "cv": 60.0, "opening": opening, "characteristic": "Linear"}))
        returns.append(f"CW-{tag}4")
    fs.add(Mixer("Return manifold", inlets={"in": returns}, outlets={"out": "CW4"},
                 params={"pressure_mode": "Equal pressures (junction)"}))
    fs.add(Pipe("L-205 CW return", inlets={"in": "CW4"}, outlets={"out": "CW5"},
                params={"nps": "6", "length": 150.0, "elevation": 8.0, "fittings": {"elbow_90_lr": 5, "gate": 1}}))
    fs.add(Sink("Tower distribution", inlets={"in": "CW5"}, params={"pressure": P_ATM_KPA}))
    return fs


def condensate_return_network() -> Flowsheet:
    """Three steam users with traps discharging into a common lifted return line."""
    fs = Flowsheet(
        "Condensate return with trap back pressure (pressure–flow)",
        "Three process heaters on a 7 bar(g) steam main drain through steam traps into a common condensate return "
        "that rises 5 m to a vented receiver. Solved in pressure–flow mode: the traps pass whatever condensate "
        "forms, and the back pressure at each trap is worked out backwards from the receiver, through the flashing "
        "two-phase return line. Each trap's results show its back pressure, which must stay below its inlet "
        "pressure.",
    )
    fs.solver_mode = "pressure_flow"
    fs.add(Feed("Steam main", outlets={"out": "ST1"},
                params={"pressure": barg(7), "condition": "Dryness fraction", "dryness": 1.0,
                        "flow_mode": "As required", "flow": 1.0}))
    fs.add(Splitter("Steam branches", inlets={"in": "ST1"}, outlets={"out": ["ST-A", "ST-B", "ST-C"]},
                    params={"outlet_specs": {"ST-A": PD, "ST-B": PD, "ST-C": PD}}))
    users = (("A", 900.0, 30.0), ("B", 600.0, 45.0), ("C", 1200.0, 20.0))
    drains = []
    for tag, duty, length in users:
        fs.add(SteamUser(f"Heater {tag}", inlets={"in": f"ST-{tag}"}, outlets={"condensate": f"CD-{tag}1"},
                         params={"spec": "Heat duty", "duty": duty}))
        fs.add(Valve(f"ST-10{ord(tag) - 64} trap", inlets={"in": f"CD-{tag}1"}, outlets={"out": f"CD-{tag}2"},
                     params={"mode": TRAP, "outlet_pressure": barg(1)}))
        fs.add(Pipe(f"L-30{ord(tag) - 64} drain {tag}", inlets={"in": f"CD-{tag}2"}, outlets={"out": f"CD-{tag}3"},
                    params={"nps": "2", "length": length, "fittings": {"elbow_90_std": 3, "tee_branch": 1},
                            "void_model": "Drift flux (Rouhani–Axelsson)"}))
        drains.append(f"CD-{tag}3")
    fs.add(Mixer("Return header", inlets={"in": drains}, outlets={"out": "CD1"},
                 params={"pressure_mode": "Equal pressures (junction)"}))
    fs.add(Pipe("L-304 condensate return", inlets={"in": "CD1"}, outlets={"out": "CD2"},
                params={"nps": "4", "length": 150.0, "elevation": 5.0, "fittings": {"elbow_90_lr": 6, "gate": 1},
                        "void_model": "Drift flux (Rouhani–Axelsson)"}))
    fs.add(FlashVessel("Condensate receiver", inlets={"in": "CD2"}, outlets={"vapour": "Flash to vent",
                                                                           "liquid": "Receiver outlet"},
                       params={"pressure": barg(0.1), "inlet_specs": {"CD2": "Open"}}))
    return fs


def closed_heating_loop() -> Flowsheet:
    """A closed hot-water loop: the expansion tank only sets the pressure."""
    fs = Flowsheet(
        "Closed hot-water heating loop (pressure–flow)",
        "A closed low-temperature hot-water loop: a circulating pump, a boiler heat exchanger raising the water to "
        "80 °C, and two heating circuits in parallel. The expansion tank sets the loop's pressure; its flow settles "
        "at zero. The circulating flow and the split between the circuits follow from the pump curve and the "
        "resistances, and the return temperature from the heat taken by each circuit.",
    )
    fs.solver_mode = "pressure_flow"
    fs.add(Feed("Expansion tank", outlets={"out": "X"},
                params={"pressure": barg(1.5), "temperature": 60.0,
                        "flow_mode": "Pressure reference (expansion tank)", "flow": 0.0}))
    fs.add(Mixer("Pump suction", inlets={"in": ["HW-R2", "X"]}, outlets={"out": "HW1"},
                 params={"pressure_mode": "Equal pressures (junction)"}))
    fs.add(Pump("P-401", inlets={"in": "HW1"}, outlets={"out": "HW2"},
                params={"mode": "Pump curve", "shutoff_head": 22.0, "rated_flow": 40.0, "rated_head": 16.0,
                        "efficiency": 70.0}))
    fs.add(Heater("E-401 boiler heat exchanger", inlets={"in": "HW2"}, outlets={"out": "HW3"},
                  params={"spec": "Outlet temperature", "temperature": 80.0, "dp_mode": "Scales with flow²",
                          "pressure_drop": 30.0, "rated_flow": 11.0}))
    fs.add(Pipe("L-401 flow main", inlets={"in": "HW3"}, outlets={"out": "HW4"},
                params={"nps": "4", "length": 80.0, "fittings": {"elbow_90_lr": 6, "gate": 2},
                        "heat_loss": "Insulated", "ambient": 15.0}))
    fs.add(Splitter("Flow manifold", inlets={"in": "HW4"}, outlets={"out": ["HW-A1", "HW-B1"]},
                    params={"outlet_specs": {"HW-A1": PD, "HW-B1": PD}}))
    for tag, length, duty in (("A", 60.0, -250.0), ("B", 120.0, -350.0)):
        fs.add(Pipe(f"L-40{ord(tag) - 63} circuit {tag}", inlets={"in": f"HW-{tag}1"}, outlets={"out": f"HW-{tag}2"},
                    params={"nps": "2-1/2", "length": length, "fittings": {"elbow_90_std": 8, "gate": 2}}))
        fs.add(Heater(f"Heating circuit {tag}", inlets={"in": f"HW-{tag}2"}, outlets={"out": f"HW-{tag}3"},
                      params={"spec": "Heat duty", "duty": duty, "dp_mode": "Scales with flow²",
                              "pressure_drop": 20.0, "rated_flow": 5.0}))
    fs.add(Mixer("Return manifold", inlets={"in": ["HW-A3", "HW-B3"]}, outlets={"out": "HW-R1"},
                 params={"pressure_mode": "Equal pressures (junction)"}))
    fs.add(Pipe("L-404 return main", inlets={"in": "HW-R1"}, outlets={"out": "HW-R2"},
                params={"nps": "4", "length": 80.0, "fittings": {"elbow_90_lr": 6, "gate": 2}}))
    return fs


EXAMPLES = {
    "Steam distribution with pipes and relief valves": steam_distribution,
    "Industrial steam system": industrial_steam_system,
    "Cooling-water network (pressure–flow)": cooling_water_network,
    "Condensate return with trap back pressure (pressure–flow)": condensate_return_network,
    "Closed hot-water heating loop (pressure–flow)": closed_heating_loop,
    "Rankine cycle with closed feedwater heater": rankine_closed_fwh,
    "Simple Rankine cycle (textbook)": simple_rankine,
    "Regenerative Rankine cycle (textbook)": regenerative_rankine,
    "Empty flowsheet": empty,
}
