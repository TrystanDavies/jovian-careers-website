"""Comparing results with HYSYS or plant data."""

import pytest

from steamsuite.compare import compare, parse
from steamsuite.examples import steam_distribution


@pytest.fixture(scope="module")
def solved():
    fs = steam_distribution()
    assert fs.solve().converged
    return fs


def test_one_value_per_row_with_units(solved):
    s = solved.streams["S2"]
    text = ("Stream\tProperty\tValue\tUnit\n"
            f"S2\tPressure\t{(s.P - 101.325) / 100:.4f}\tbar(g)\n"
            f"s-2\tTemperature\t{s.state.T + 0.5:.3f}\tC\n"
            f"S2\tMass flow\t{s.m * 3.6 * 1.03:.5f}\tt/h\n")
    res = compare(solved, text)
    rows = {r["property"]: r for r in res.rows}
    assert rows["Pressure"]["simulated"] == pytest.approx(rows["Pressure"]["reference"], rel=1e-4)
    assert rows["Pressure"]["band"] == "good"
    assert rows["Temperature"]["difference"] == pytest.approx(-0.5, abs=2e-3)
    assert rows["Mass flow"]["relative"] == pytest.approx(1 / 1.03 - 1, rel=1e-3)
    assert rows["Mass flow"]["band"] == "check"


def test_hysys_workbook_layout(solved):
    a, b = solved.streams["S1"], solved.streams["S3"]
    text = ("Name\tS1\tS3\tNot-a-stream\n"
            f"Vapour Fraction\t{a.state.x if a.state.x is not None else 1:.4f}\t1.0000\t1\n"
            f"Temperature [C]\t{a.state.T:.2f}\t{b.state.T + 10:.2f}\t20\n"
            f"Pressure [kPa]\t{a.P:.2f}\t{b.P:.2f}\t100\n"
            f"Mass Flow [kg/h]\t{a.m * 3600:.1f}\t{b.m * 3600:.1f}\t1\n"
            "Molar Flow [kgmole/h]\t1\t2\t3\n")
    res = compare(solved, text)
    assert len(res.rows) == 8
    assert any("Not-a-stream" in w for w in res.warnings)
    assert any("Molar Flow" in w for w in res.warnings)
    t3 = next(r for r in res.rows if r["stream"] == "S3" and r["property"] == "Temperature")
    assert t3["band"] == "large" and t3["difference"] == pytest.approx(-10.0, abs=0.01)
    assert res.summary["worst"]["stream"] == "S3"


def test_streams_down_the_side_and_us_units(solved):
    s = solved.streams["S1"]
    text = ("Stream, Pressure (psig), Temperature (F), Mass flow (lb/h)\n"
            f"S1, {(s.P - 101.325) / 6.894757:.3f}, {s.state.T * 1.8 + 32:.3f}, {s.m * 3600 / 0.45359237:.2f}\n")
    res = compare(solved, text)
    assert len(res.rows) == 3 and all(r["band"] == "good" for r in res.rows)


def test_unrecognised_text_is_explained():
    refs, warnings = parse("hello world\nnothing here")
    assert not refs and warnings
