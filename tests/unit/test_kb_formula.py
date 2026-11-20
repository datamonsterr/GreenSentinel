import pytest

from src.services.kb_formula import (
    PARAMETER_CATALOGUE,
    FormulaError,
    evaluate,
    parse,
    validate_formula,
)

P = {"trips_today": 9, "milestone_trips": 10, "milestone_bonus_vnd": 50000, "trip_cost_vnd": 12000,
     "gps_km": 1.0, "billed_km": 10.0, "fare_vnd": 100000, "surge_multiplier": 1.5}


def ev(src, params=None):
    return evaluate(parse(src), P if params is None else params)


def test_arithmetic_precedence_and_unary():
    assert ev("=1+2*3") == 7
    assert ev("=(1+2)*3") == 9
    assert ev("=-2+5") == 3
    assert ev("=2^3") == 8


def test_example_from_prd():
    f = "=IF(trips_today+1>=milestone_trips, milestone_bonus_vnd - trip_cost_vnd, 0)"
    assert ev(f) == 38000
    assert ev(f, {**P, "trips_today": 2}) == 0


def test_comparison_logic_functions():
    assert ev("=AND(gps_km/billed_km<0.3, fare_vnd>0)") is True
    assert ev("=OR(1=2, 3<>3)") is False
    assert ev("=NOT(1>2)") is True
    assert ev("=MAX(1,5,3)+MIN(4,2)+ABS(-1)+ROUND(2.567,1)") == 5 + 2 + 1 + 2.6


def test_no_python_execution():
    for bad in ["=__import__('os').system('x')", "=().__class__", "=open('f')", "=a.b", "=1;2", "=[1]"]:
        with pytest.raises(FormulaError):
            parse(bad)


def test_unknown_function_and_param():
    with pytest.raises(FormulaError) as e:
        parse("=EVAL(1)")
    assert e.value.code == "unknown_function"
    r = validate_formula("=nope+1")
    assert not r["ok"] and r["errors"][0]["code"] == "unknown_param"
    assert r["errors"][0]["position"] == 1


def test_syntax_error_has_position():
    r = validate_formula("=1+*2")
    assert not r["ok"] and r["errors"][0]["code"] == "syntax"
    r = validate_formula("=(1+2")
    assert not r["ok"]


def test_division_by_zero():
    r = validate_formula("=fare_vnd/0")
    assert not r["ok"] and r["errors"][0]["code"] == "div_zero"
    with pytest.raises(FormulaError) as e:
        ev("=fare_vnd/(trips_today-9)")
    assert e.value.code == "div_zero"


def test_unit_mismatch():
    r = validate_formula("=fare_vnd+gps_km")
    assert not r["ok"] and r["errors"][0]["code"] == "unit_mismatch"
    assert validate_formula("=fare_vnd+milestone_bonus_vnd")["ok"]
    assert validate_formula("=fare_vnd*surge_multiplier+1000")["ok"]


def test_validate_reports_used_params_and_sample():
    r = validate_formula("=gps_km/billed_km")
    assert r["ok"] and set(r["used_params"]) == {"gps_km", "billed_km"}
    assert r["sample"] is not None


def test_missing_value_in_evaluate_is_error():
    with pytest.raises(FormulaError) as e:
        ev("=gps_km", {})
    assert e.value.code == "missing_value"


def test_catalogue_shape():
    assert {"trips_today", "gps_km", "fare_vnd", "surge_multiplier"} <= set(PARAMETER_CATALOGUE)
    for v in PARAMETER_CATALOGUE.values():
        assert {"name", "description", "unit", "source", "owner", "latency"} <= set(v)


def test_length_and_depth_limits():
    with pytest.raises(FormulaError):
        parse("=" + "(" * 100 + "1" + ")" * 100)
    with pytest.raises(FormulaError):
        parse("=" + "1+" * 2000 + "1")
