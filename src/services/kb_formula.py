"""Safe Excel-style formula evaluator for knowledge motives and behaviours (ADR-032).

No ``eval``/``exec``: a hand-written tokenizer + recursive-descent parser builds a tiny AST that is
evaluated over the parameter catalogue. Only numbers, catalogue names, arithmetic, comparisons and a
fixed function whitelist are accepted.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

MAX_FORMULA_LENGTH = 1000
MAX_DEPTH = 40

# code -> metadata. `sample` feeds the editor preview; units drive the mismatch check.
PARAMETER_CATALOGUE: dict[str, dict[str, Any]] = {
    "billed_km": {"name": "Billed distance", "description": "Kilometres charged to the passenger", "unit": "km",
                  "source": "trips", "owner": "Data", "latency": "real-time", "sample": 10.0},
    "gps_km": {"name": "GPS distance", "description": "Kilometres actually driven according to GPS", "unit": "km",
               "source": "telemetry", "owner": "Data", "latency": "real-time", "sample": 8.5},
    "fare_vnd": {"name": "Fare", "description": "Fare amount of the trip", "unit": "vnd",
                 "source": "trips", "owner": "Data", "latency": "real-time", "sample": 120000},
    "surge_multiplier": {"name": "Surge multiplier", "description": "Dynamic pricing multiplier on the trip",
                         "unit": "ratio", "source": "pricing", "owner": "Marketplace", "latency": "real-time", "sample": 1.2},
    "subsidy_vnd": {"name": "Subsidy", "description": "Subsidy paid out on the trip", "unit": "vnd",
                    "source": "incentives", "owner": "Marketplace", "latency": "daily", "sample": 15000},
    "trips_today": {"name": "Trips today", "description": "Completed trips of the driver today before this trip",
                    "unit": "count", "source": "trips", "owner": "Data", "latency": "real-time", "sample": 7},
    "milestone_trips": {"name": "Milestone trips", "description": "Trip count that unlocks the milestone bonus",
                        "unit": "count", "source": "incentives", "owner": "Marketplace", "latency": "daily", "sample": 10},
    "milestone_bonus_vnd": {"name": "Milestone bonus", "description": "Bonus paid when the milestone is reached",
                            "unit": "vnd", "source": "incentives", "owner": "Marketplace", "latency": "daily", "sample": 50000},
    "trip_cost_vnd": {"name": "Cost to create a trip", "description": "Estimated driver cost of producing one trip",
                      "unit": "vnd", "source": "estimate", "owner": "Fraud platform", "latency": "daily", "sample": 12000},
    "trip_duration_min": {"name": "Trip duration", "description": "Minutes between pickup start and trip end",
                          "unit": "minutes", "source": "trips", "owner": "Data", "latency": "real-time", "sample": 18},
    "stationary_duration_s": {"name": "Stationary time", "description": "Seconds the vehicle stayed almost still during the trip",
                              "unit": "seconds", "source": "feature_sets", "owner": "Fraud platform", "latency": "real-time", "sample": 240},
    "davi": {"name": "DAVI", "description": "Distance-adjusted velocity index of the trip", "unit": "ratio",
             "source": "feature_sets", "owner": "Fraud platform", "latency": "real-time", "sample": -0.4},
    "distance_to_pickup_m": {"name": "Distance to pickup", "description": "Metres between the vehicle and the pickup point at trip start",
                             "unit": "metres", "source": "feature_sets", "owner": "Fraud platform", "latency": "real-time", "sample": 900},
}

# "policy" parameters are policy constants (not read from a case); trials assume their sample value.
for _meta in PARAMETER_CATALOGUE.values():
    _meta["kind"] = "policy" if _meta["source"] in ("incentives", "estimate", "pricing") else "case"

FUNCTIONS = {"IF", "AND", "OR", "NOT", "MIN", "MAX", "ABS", "ROUND", "SUM"}
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|<>|[-+*/^(),<>=]))")


class FormulaError(Exception):
    def __init__(self, code: str, message: str, position: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.position = position

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "position": self.position}


@dataclass(frozen=True)
class Num:
    value: float | int
    pos: int


@dataclass(frozen=True)
class Name:
    name: str
    pos: int


@dataclass(frozen=True)
class Unary:
    op: str
    operand: Any
    pos: int


@dataclass(frozen=True)
class Bin:
    op: str
    left: Any
    right: Any
    pos: int


@dataclass(frozen=True)
class Call:
    fn: str
    args: tuple
    pos: int


def _tokenize(src: str, offset: int) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    i = 0
    n = len(src)
    while i < n:
        if src[i:].strip() == "":
            break
        m = _TOKEN.match(src, i)
        if not m:
            pos = i + len(src[i:]) - len(src[i:].lstrip())
            raise FormulaError("syntax", f"Unexpected character '{src[pos]}'", pos + offset)
        num, ident, op = m.groups()
        start = m.start(m.lastindex)  # type: ignore[arg-type]
        if num is not None:
            out.append(("num", num, start + offset))
        elif ident is not None:
            out.append(("id", ident, start + offset))
        else:
            out.append(("op", op, start + offset))
        i = m.end()
    out.append(("end", "", n + offset))
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str, int]]):
        self.t = tokens
        self.i = 0
        self.depth = 0

    def peek(self) -> tuple[str, str, int]:
        return self.t[self.i]

    def take(self) -> tuple[str, str, int]:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, op: str) -> None:
        kind, val, pos = self.take()
        if kind != "op" or val != op:
            raise FormulaError("syntax", f"Expected '{op}'", pos)

    def enter(self, pos: int) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("too_complex", "Formula is nested too deeply", pos)

    def parse(self):
        node = self.comparison()
        kind, val, pos = self.peek()
        if kind != "end":
            raise FormulaError("syntax", f"Unexpected '{val}'", pos)
        return node

    def comparison(self):
        node = self.additive()
        while self.peek()[0] == "op" and self.peek()[1] in ("<", ">", "<=", ">=", "=", "<>"):
            _, op, pos = self.take()
            node = Bin(op, node, self.additive(), pos)
        return node

    def additive(self):
        node = self.term()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            _, op, pos = self.take()
            node = Bin(op, node, self.term(), pos)
        return node

    def term(self):
        node = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            _, op, pos = self.take()
            node = Bin(op, node, self.unary(), pos)
        return node

    def unary(self):
        kind, val, pos = self.peek()
        if kind == "op" and val in ("+", "-"):
            self.take()
            self.enter(pos)
            try:
                return Unary(val, self.unary(), pos)
            finally:
                self.depth -= 1
        return self.power()

    def power(self):
        node = self.atom()
        if self.peek()[0] == "op" and self.peek()[1] == "^":
            _, _, pos = self.take()
            self.enter(pos)
            try:
                return Bin("^", node, self.unary(), pos)
            finally:
                self.depth -= 1
        return node

    def atom(self):
        kind, val, pos = self.take()
        if kind == "num":
            return Num(float(val) if "." in val else int(val), pos)
        if kind == "id":
            if self.peek()[0] == "op" and self.peek()[1] == "(":
                fn = val.upper()
                if fn not in FUNCTIONS:
                    raise FormulaError("unknown_function", f"Unknown function '{val}'", pos)
                self.take()
                self.enter(pos)
                args = []
                if not (self.peek()[0] == "op" and self.peek()[1] == ")"):
                    args.append(self.comparison())
                    while self.peek()[0] == "op" and self.peek()[1] == ",":
                        self.take()
                        args.append(self.comparison())
                self.expect(")")
                self.depth -= 1
                _check_arity(fn, len(args), pos)
                return Call(fn, tuple(args), pos)
            return Name(val, pos)
        if kind == "op" and val == "(":
            self.enter(pos)
            node = self.comparison()
            self.expect(")")
            self.depth -= 1
            return node
        if kind == "end":
            raise FormulaError("syntax", "Unexpected end of formula", pos)
        raise FormulaError("syntax", f"Unexpected '{val}'", pos)


def _check_arity(fn: str, n: int, pos: int) -> None:
    ok = {"IF": n == 3, "NOT": n == 1, "ABS": n == 1, "ROUND": n in (1, 2), "AND": n >= 1, "OR": n >= 1,
          "MIN": n >= 1, "MAX": n >= 1, "SUM": n >= 1}[fn]
    if not ok:
        raise FormulaError("syntax", f"Wrong number of arguments for {fn}", pos)


def parse(src: str):
    """Parse a formula such as ``=IF(a+1>=b, c-d, 0)`` (leading ``=`` optional)."""
    if not isinstance(src, str) or not src.strip():
        raise FormulaError("syntax", "Formula is empty", 0)
    if len(src) > MAX_FORMULA_LENGTH:
        raise FormulaError("too_complex", f"Formula longer than {MAX_FORMULA_LENGTH} characters", 0)
    offset = 0
    body = src
    if src.lstrip().startswith("="):
        offset = src.index("=") + 1
        body = src[offset:]
    try:
        return _Parser(_tokenize(body, offset)).parse()
    except RecursionError as exc:  # pragma: no cover - depth guard fires first
        raise FormulaError("too_complex", "Formula is too complex", 0) from exc


def _num(v: Any, pos: int) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return v  # type: ignore[return-value]
    raise FormulaError("type", "Expected a number", pos)


def evaluate(node: Any, params: dict[str, Any]) -> Any:
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Name):
        if node.name not in PARAMETER_CATALOGUE:
            raise FormulaError("unknown_param", f"Unknown parameter '{node.name}'", node.pos)
        v = params.get(node.name)
        if v is None:
            raise FormulaError("missing_value", f"No value for parameter '{node.name}'", node.pos)
        return _num(v, node.pos)
    if isinstance(node, Unary):
        v = _num(evaluate(node.operand, params), node.pos)
        return -v if node.op == "-" else v
    if isinstance(node, Bin):
        a = evaluate(node.left, params)
        b = evaluate(node.right, params)
        op = node.op
        if op in ("<", ">", "<=", ">=", "=", "<>"):
            a, b = _num(a, node.pos), _num(b, node.pos)
            return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b,
                    "=": math.isclose(a, b), "<>": not math.isclose(a, b)}[op]
        a, b = _num(a, node.pos), _num(b, node.pos)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise FormulaError("div_zero", "Division by zero", node.pos)
            return a / b
        if op == "^":
            try:
                r = a**b
            except (OverflowError, ZeroDivisionError) as exc:
                raise FormulaError("div_zero" if isinstance(exc, ZeroDivisionError) else "overflow", str(exc), node.pos) from exc
            if isinstance(r, complex) or abs(r) > 1e18:
                raise FormulaError("overflow", "Result out of range", node.pos)
            return r
    if isinstance(node, Call):
        fn = node.fn
        if fn == "IF":  # lazily evaluate the taken branch only
            return evaluate(node.args[1] if evaluate(node.args[0], params) else node.args[2], params)
        vals = [evaluate(a, params) for a in node.args]
        if fn == "AND":
            return all(bool(v) for v in vals)
        if fn == "OR":
            return any(bool(v) for v in vals)
        if fn == "NOT":
            return not bool(vals[0])
        nums = [_num(v, node.pos) for v in vals]
        if fn == "MIN":
            return min(nums)
        if fn == "MAX":
            return max(nums)
        if fn == "SUM":
            return sum(nums)
        if fn == "ABS":
            return abs(nums[0])
        if fn == "ROUND":
            return round(nums[0], int(nums[1]) if len(nums) > 1 else 0)
    raise FormulaError("syntax", "Unsupported expression", getattr(node, "pos", 0))


def _walk(node: Any):
    yield node
    if isinstance(node, Unary):
        yield from _walk(node.operand)
    elif isinstance(node, Bin):
        yield from _walk(node.left)
        yield from _walk(node.right)
    elif isinstance(node, Call):
        for a in node.args:
            yield from _walk(a)


def _const_zero(node: Any) -> bool:
    if any(isinstance(n, (Name, Call)) for n in _walk(node)):
        return False
    try:
        return evaluate(node, {}) == 0
    except FormulaError:
        return False


def _unit(node: Any, errors: list[FormulaError]) -> str | None:
    """Infer a unit; None = wildcard (literal or unknown). Records mismatches."""
    if isinstance(node, Num):
        return None
    if isinstance(node, Name):
        meta = PARAMETER_CATALOGUE.get(node.name)
        return meta["unit"] if meta else None
    if isinstance(node, Unary):
        return _unit(node.operand, errors)
    if isinstance(node, Call):
        units = [_unit(a, errors) for a in (node.args[1:] if node.fn == "IF" else node.args)]
        if node.fn == "IF":
            _unit(node.args[0], errors)
        if node.fn in ("AND", "OR", "NOT"):
            return None
        known = {u for u in units if u}
        if len(known) > 1 and node.fn in ("IF", "MIN", "MAX", "SUM"):
            errors.append(FormulaError("unit_mismatch", f"Mixed units in {node.fn}: {', '.join(sorted(known))}", node.pos))
        return next(iter(known)) if known else None
    if isinstance(node, Bin):
        lu, ru = _unit(node.left, errors), _unit(node.right, errors)
        if node.op in ("+", "-") or node.op in ("<", ">", "<=", ">=", "=", "<>"):
            if lu and ru and lu != ru:
                errors.append(FormulaError("unit_mismatch", f"Cannot combine {lu} with {ru}", node.pos))
            return None if node.op not in ("+", "-") else (lu or ru)
        if node.op == "*":
            if lu is None or lu == "ratio":
                return ru
            if ru is None or ru == "ratio":
                return lu
            return None
        if node.op == "/":
            if ru is None or ru == "ratio":
                return lu
            return "ratio" if lu == ru else None
        return None
    return None


def validate_formula(src: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Editor validation: syntax, unknown parameters, units, constant division by zero, sample run."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        tree = parse(src)
    except FormulaError as e:
        return {"ok": False, "errors": [e.as_dict()], "warnings": [], "used_params": [], "sample": None}
    names = [n for n in _walk(tree) if isinstance(n, Name)]
    for n in names:
        if n.name not in PARAMETER_CATALOGUE:
            errors.append(FormulaError("unknown_param", f"Unknown parameter '{n.name}'", n.pos).as_dict())
    for n in _walk(tree):
        if isinstance(n, Bin) and n.op == "/" and _const_zero(n.right):
            errors.append(FormulaError("div_zero", "Division by zero", n.pos).as_dict())
    unit_errors: list[FormulaError] = []
    if not errors:
        _unit(tree, unit_errors)
        errors.extend(e.as_dict() for e in unit_errors)
    sample = None
    if not errors:
        values = params if params is not None else {k: v["sample"] for k, v in PARAMETER_CATALOGUE.items()}
        try:
            sample = evaluate(tree, values)
        except FormulaError as e:
            warnings.append(e.as_dict())
    used = sorted({n.name for n in names})
    return {"ok": not errors, "errors": errors, "warnings": warnings, "used_params": used, "sample": sample}


def evaluate_formula(src: str, params: dict[str, Any]) -> Any:
    return evaluate(parse(src), params)
