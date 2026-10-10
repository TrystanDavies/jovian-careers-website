"""Ready-made example flowsheets."""

from __future__ import annotations

from .flowsheet import Flowsheet
from .flowsheet.blocks import (
    Boiler,
    Condenser,
    Deaerator,
    Desuperheater,
    Feed,
    FlashVessel,
    Header,
    Mixer,
    Pump,
    Splitter,
    SteamUser,
    Turbine,
    Valve,
)
from .units import P_ATM_KPA


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
    return fs


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


def empty() -> Flowsheet:
    return Flowsheet("New flowsheet", "")


EXAMPLES = {
    "Industrial steam system": industrial_steam_system,
    "Simple Rankine cycle (textbook)": simple_rankine,
    "Regenerative Rankine cycle (textbook)": regenerative_rankine,
    "Empty flowsheet": empty,
}
