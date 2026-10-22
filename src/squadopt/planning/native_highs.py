"""Native window solver boundary and exact integer model translation.

The exporter is the reviewed #1147 translation, promoted without importing the laboratory.
The host loads only its CP-SAT side. The platform runs ``native_solve`` in a separate
interpreter: OR-Tools and highspy ship incompatible libraries with the same Linux SONAME.
Only a proved optimum with a checked integer witness crosses back into the planner.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from ortools.sat.python import cp_model

INT64_MIN: Final = -(2**63)
INT64_MAX: Final = 2**63 - 1
EXACT_LIMIT: Final = 2**53
NATIVE_VERSION: Final = "1.15.1"
Expr = tuple[dict[int, int], int]
HANDLED_KINDS: Final = (
    "linear",
    "bool_or",
    "bool_and",
    "at_most_one",
    "exactly_one",
    "lin_max",
    "element",
)
REFUSED_KINDS: Final = (
    "bool_xor",
    "int_div",
    "int_mod",
    "int_prod",
    "all_diff",
    "table",
    "automaton",
    "inverse",
    "reservoir",
    "interval",
    "no_overlap",
    "no_overlap_2d",
    "cumulative",
    "circuit",
    "routes",
    "dummy_constraint",
)


class ExportRefused(ValueError):
    """The native format cannot represent this model exactly; use CP-SAT."""


def user_objective(proto: Any) -> tuple[dict[int, int | float], int | float, bool]:
    """The objective as the caller stated it: coefficients, constant, and whether maximised."""

    if proto.has_floating_point_objective():
        raise ExportRefused("The model has a floating-point objective.")
    if not proto.has_objective():
        return {}, 0, False
    objective = proto.objective
    if len(objective.domain) > 0:
        raise ExportRefused("The objective carries a domain.")
    scaling = float(objective.scaling_factor) or 1.0
    terms: dict[int, int] = {}
    for var, coeff in zip(objective.vars, objective.coeffs, strict=True):
        if var < 0:
            raise ExportRefused("The objective names a negated variable reference.")
        terms[int(var)] = terms.get(int(var), 0) + int(coeff)
    offset = float(objective.offset)
    if scaling in (1.0, -1.0):
        sign = int(scaling)
        integral = offset.is_integer()
        return (
            {var: sign * coeff for var, coeff in terms.items() if coeff != 0},
            sign * int(offset) if integral else sign * offset,
            scaling < 0,
        )
    return (
        {var: scaling * coeff for var, coeff in terms.items() if coeff != 0},
        scaling * offset,
        scaling < 0,
    )


@dataclass(frozen=True)
class Column:
    name: str
    lower: int
    upper: int


@dataclass(frozen=True)
class Row:
    name: str
    terms: Mapping[int, int]
    lower: int | None
    upper: int | None


@dataclass(frozen=True)
class Auxiliary:
    """A column the exporter added, and how a CP-SAT assignment decides its value."""

    column: int
    kind: str
    constraint: int
    position: int


@dataclass
class Milp:
    """An all-integer MILP whose first ``variables`` columns are the CP-SAT variables."""

    name: str
    columns: list[Column]
    rows: list[Row]
    objective: dict[int, int | float]
    objective_offset: int | float
    maximize: bool
    variables: int
    auxiliaries: list[Auxiliary] = field(default_factory=list)
    kinds: dict[str, int] = field(default_factory=dict)


def constraint_kind(constraint: Any) -> str:
    """The constraint's kind, by the field it sets."""

    for kind in (*HANDLED_KINDS, *REFUSED_KINDS):
        if getattr(constraint, f"has_{kind}")():
            return kind
    raise ExportRefused("A constraint sets no kind this exporter knows.")


def _add(left: Expr, right: Expr, factor: int = 1) -> Expr:
    terms = dict(left[0])
    for var, coeff in right[0].items():
        terms[var] = terms.get(var, 0) + factor * coeff
    return {var: coeff for var, coeff in terms.items() if coeff != 0}, left[1] + factor * right[1]


def _exact(value: int, what: str) -> int:
    if abs(value) >= EXACT_LIMIT:
        raise ExportRefused(f"{what} is {value}, beyond what a double holds exactly.")
    return value


class _Exporter:
    def __init__(self, proto: Any, name: str) -> None:
        self.proto = proto
        self.columns: list[Column] = []
        self.rows: list[Row] = []
        self.auxiliaries: list[Auxiliary] = []
        self.kinds: dict[str, int] = {}
        self.name = name

    def bounds_of(self, var: int) -> tuple[int, int]:
        column = self.columns[var]
        return column.lower, column.upper

    def range_of(self, expr: Expr) -> tuple[int, int]:
        low = high = expr[1]
        for var, coeff in expr[0].items():
            lower, upper = self.bounds_of(var)
            low += coeff * (lower if coeff > 0 else upper)
            high += coeff * (upper if coeff > 0 else lower)
        return low, high

    def literal(self, literal: int) -> Expr:
        var = literal if literal >= 0 else -literal - 1
        if self.bounds_of(var)[0] < 0 or self.bounds_of(var)[1] > 1:
            raise ExportRefused(f"Literal {literal} names variable {var}, which is not Boolean.")
        return ({var: 1}, 0) if literal >= 0 else ({var: -1}, 1)

    def linear_expr(self, message: Any) -> Expr:
        terms: dict[int, int] = {}
        for var, coeff in zip(message.vars, message.coeffs, strict=True):
            if var < 0:
                raise ExportRefused("A linear term names a negated variable reference.")
            terms[int(var)] = terms.get(int(var), 0) + int(coeff)
        offset = int(getattr(message, "offset", 0))
        return {var: coeff for var, coeff in terms.items() if coeff != 0}, offset

    def row(
        self, name: str, terms: Mapping[int, int], lower: int | None, upper: int | None
    ) -> None:
        if lower is None and upper is None:
            return
        for coeff in terms.values():
            _exact(coeff, f"A coefficient of row {name}")
        for bound in (lower, upper):
            if bound is not None:
                _exact(bound, f"A bound of row {name}")
        self.rows.append(Row(name, dict(terms), lower, upper))

    def auxiliary(self, kind: str, constraint: int, position: int) -> int:
        column = len(self.columns)
        self.columns.append(Column(f"a{len(self.auxiliaries)}", 0, 1))
        self.auxiliaries.append(Auxiliary(column, kind, constraint, position))
        return column

    def bounded(
        self,
        name: str,
        expr: Expr,
        lower: int | None,
        upper: int | None,
        enforcement: Sequence[int],
    ) -> None:
        """``lower <= expr <= upper``, holding only when every enforcement literal is true."""

        terms, constant = expr
        if not enforcement:
            self.row(
                name,
                terms,
                None if lower is None else lower - constant,
                None if upper is None else upper - constant,
            )
            return
        literals: Expr = ({}, 0)
        for literal in enforcement:
            literals = _add(literals, self.literal(literal))
        count = len(enforcement)
        low, high = self.range_of(expr)
        if upper is not None and upper < high:
            big = high - upper
            row_terms, row_constant = _add(expr, literals, big)
            self.row(f"{name}_up", row_terms, None, upper + big * count - row_constant)
        if lower is not None and lower > low:
            big = lower - low
            row_terms, row_constant = _add(expr, literals, -big)
            self.row(f"{name}_lo", row_terms, lower - big * count - row_constant, None)

    def count(self, kind: str) -> None:
        self.kinds[kind] = self.kinds.get(kind, 0) + 1

    def constraint(self, index: int, constraint: Any) -> None:
        kind = constraint_kind(constraint)
        enforcement = [int(literal) for literal in constraint.enforcement_literal]
        self.count(f"{kind} (enforced)" if enforcement else kind)
        name = f"c{index}"
        if kind == "linear":
            domain = [int(value) for value in constraint.linear.domain]
            if len(domain) != 2:
                raise ExportRefused(f"Linear constraint {index} has a domain with holes.")
            lower = None if domain[0] <= INT64_MIN else domain[0]
            upper = None if domain[1] >= INT64_MAX else domain[1]
            self.bounded(name, self.linear_expr(constraint.linear), lower, upper, enforcement)
        elif kind in ("bool_or", "at_most_one", "exactly_one"):
            literals = getattr(constraint, kind).literals
            total: Expr = ({}, 0)
            for literal in literals:
                total = _add(total, self.literal(int(literal)))
            lower = 1 if kind in ("bool_or", "exactly_one") else None
            upper = 1 if kind in ("at_most_one", "exactly_one") else None
            self.bounded(name, total, lower, upper, enforcement)
        elif kind == "bool_and":
            for position, literal in enumerate(constraint.bool_and.literals):
                self.bounded(f"{name}_{position}", self.literal(int(literal)), 1, None, enforcement)
        elif enforcement:
            raise ExportRefused(f"Constraint {index} is an enforced {kind}.")
        elif kind == "lin_max":
            self.lin_max(index, constraint.lin_max)
        elif kind == "element":
            self.element(index, constraint.element)
        else:
            raise ExportRefused(f"Constraint {index} is a {kind} constraint, which is not handled.")

    def lin_max(self, index: int, message: Any) -> None:
        target = self.linear_expr(message.target)
        exprs = [self.linear_expr(expr) for expr in message.exprs]
        name = f"c{index}"
        if not exprs:
            raise ExportRefused(f"Maximum constraint {index} has no expressions.")
        if len(exprs) == 1:
            terms, constant = _add(target, exprs[0], -1)
            self.row(f"{name}_eq", terms, -constant, -constant)
            return
        chosen = [self.auxiliary("lin_max", index, position) for position in range(len(exprs))]
        for position, expr in enumerate(exprs):
            terms, constant = _add(target, expr, -1)
            self.row(f"{name}_ge{position}", terms, -constant, None)
            big = max(0, self.range_of((terms, constant))[1])
            with_choice = dict(terms)
            with_choice[chosen[position]] = big
            self.row(f"{name}_le{position}", with_choice, None, big - constant)
        self.row(f"{name}_one", dict.fromkeys(chosen, 1), 1, 1)

    def element(self, index: int, message: Any) -> None:
        name = f"c{index}"
        if message.has_linear_index() or len(message.exprs) > 0:
            selector = self.linear_expr(message.linear_index)
            target = self.linear_expr(message.linear_target)
            exprs = [self.linear_expr(expr) for expr in message.exprs]
        else:
            if message.index < 0 or message.target < 0 or any(v < 0 for v in message.vars):
                raise ExportRefused(f"Element constraint {index} names a negated reference.")
            selector = ({int(message.index): 1}, 0)
            target = ({int(message.target): 1}, 0)
            exprs = [({int(var): 1}, 0) for var in message.vars]
        low, high = self.range_of(selector)
        positions = [k for k in range(len(exprs)) if low <= k <= high]
        if not positions:
            raise ExportRefused(f"Element constraint {index} has no index its domain allows.")
        chosen = {k: self.auxiliary("element", index, k) for k in positions}
        self.row(f"{name}_one", dict.fromkeys(chosen.values(), 1), 1, 1)
        terms = dict(selector[0])
        for k, column in chosen.items():
            terms[column] = terms.get(column, 0) - k
        self.row(f"{name}_index", terms, -selector[1], -selector[1])
        if all(not exprs[k][0] for k in positions):
            terms = dict(target[0])
            for k, column in chosen.items():
                terms[column] = terms.get(column, 0) - exprs[k][1]
            self.row(f"{name}_target", terms, -target[1], -target[1])
            return
        for k, column in chosen.items():
            difference = _add(target, exprs[k], -1)
            low_d, high_d = self.range_of(difference)
            above = max(0, high_d)
            below = max(0, -low_d)
            terms_d, constant = difference
            up = dict(terms_d)
            up[column] = up.get(column, 0) + above
            self.row(f"{name}_up{k}", up, None, above - constant)
            down = dict(terms_d)
            down[column] = down.get(column, 0) - below
            self.row(f"{name}_lo{k}", down, -below - constant, None)

    def build(self) -> Milp:
        proto = self.proto
        if len(proto.assumptions) > 0:
            raise ExportRefused("The model carries assumptions.")
        for index, variable in enumerate(proto.variables):
            domain = [int(value) for value in variable.domain]
            if len(domain) != 2:
                raise ExportRefused(
                    f"Variable {index} ({variable.name!r}) has a domain with holes: {domain}."
                )
            lower = _exact(domain[0], f"Variable {index}'s lower bound")
            upper = _exact(domain[1], f"Variable {index}'s upper bound")
            self.columns.append(Column(f"x{index}", lower, upper))
        variables = len(self.columns)
        objective, offset, maximize = user_objective(proto)
        for var, coeff in objective.items():
            # A coefficient is written as it is and read by HiGHS as a double, so it is
            # held to the same limit as every row coefficient, bound and domain.
            if abs(coeff) >= EXACT_LIMIT:
                raise ExportRefused(
                    f"The objective coefficient of variable {var} is {coeff}, beyond what a "
                    "double holds exactly."
                )
        for index, constraint in enumerate(proto.constraints):
            self.constraint(index, constraint)
        return Milp(
            name=self.name,
            columns=self.columns,
            rows=self.rows,
            objective=dict(objective),
            objective_offset=offset,
            maximize=maximize,
            variables=variables,
            auxiliaries=self.auxiliaries,
            kinds=dict(sorted(self.kinds.items())),
        )


def export_milp(proto: Any, name: str = "model") -> Milp:
    """Translate a CP-SAT model into an equivalent all-integer MILP, or refuse."""

    return _Exporter(proto, name).build()


NativeExecutor = Callable[[Mapping[str, Any], float], Mapping[str, Any]]
_EXECUTOR: ContextVar[NativeExecutor | None] = ContextVar("native_window_executor", default=None)


@contextmanager
def native_window_executor(execute: NativeExecutor) -> Iterator[None]:
    """Bind an outer-ring process port to this server request, then restore it.

    No installed callback means the existing CP-SAT path. Context-local binding keeps
    concurrent API jobs independent, and does not put process management in the core.
    """

    token = _EXECUTOR.set(execute)
    try:
        yield
    finally:
        _EXECUTOR.reset(token)


def _wire_model(milp: Milp, seed: int) -> dict[str, Any]:
    coefficients = [milp.objective.get(index, 0) for index in range(len(milp.columns))]
    if any(not float(value).is_integer() for value in [*coefficients, milp.objective_offset]):
        raise ExportRefused("The native window objective must be integral.")
    extent = abs(milp.objective_offset) + sum(
        abs(cost) * max(abs(column.lower), abs(column.upper))
        for cost, column in zip(coefficients, milp.columns, strict=True)
    )
    if extent >= EXACT_LIMIT:
        raise ExportRefused("The objective range exceeds exact double precision.")
    return {
        "cost": coefficients,
        "offset": milp.objective_offset,
        "maximize": milp.maximize,
        "bounds": [[column.lower, column.upper] for column in milp.columns],
        "rows": [[row.lower, row.upper, sorted(row.terms.items())] for row in milp.rows],
        "seed": seed,
    }


def _checked_values(milp: Milp, result: Mapping[str, Any]) -> list[int]:
    if result.get("version") != NATIVE_VERSION or result.get("threads") != 1:
        raise ValueError("The native solver version or thread count is wrong.")
    if result.get("optimal") is not True:
        raise ValueError("The native solve did not prove an optimum.")
    values = result["values"]
    if not isinstance(values, list) or len(values) != len(milp.columns):
        raise ValueError("The native solution has the wrong number of columns.")
    rounded: list[int] = []
    for column, value in zip(milp.columns, values, strict=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("A native column is not numeric.")
        if not math.isfinite(value) or abs(value - round(value)) > 1e-5:
            raise ValueError("A native column is not finite and integral.")
        integer = round(value)
        if not column.lower <= integer <= column.upper:
            raise ValueError("A native column violates its exact domain.")
        rounded.append(integer)
    for row in milp.rows:
        value = sum(coefficient * rounded[index] for index, coefficient in row.terms.items())
        if (row.lower is not None and value < row.lower) or (
            row.upper is not None and value > row.upper
        ):
            raise ValueError("A native solution violates an exact integer row.")
    objective = milp.objective_offset + sum(
        coefficient * rounded[index] for index, coefficient in milp.objective.items()
    )
    reported, bound = float(result["objective"]), float(result["bound"])
    if not math.isfinite(reported) or not math.isfinite(bound):
        raise ValueError("The native optimum or bound is not finite.")
    if abs(reported - objective) > 1e-5 or abs(bound - objective) >= 0.5:
        raise ValueError("The native objective or bound disagrees with its integer witness.")
    return rounded[: milp.variables]


def solve_window_model(
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    solve: Callable[[cp_model.CpModel, cp_model.CpSolver], int],
    *,
    weeks: int,
) -> tuple[cp_model.CpSolver, int, dict[str, object]]:
    """Try native primary search for three/five weeks; certify or fall back.

    One-week calls and unbound callers are unchanged. The native attempt is a phase of
    its own: the child, its startup and the certificate together stay inside one primary
    wall ceiling, the same per-phase bound ``optimizer.py`` gives every phase. The CP-SAT
    fallback then runs on the caller's solver exactly as configured, with its whole wall
    ceiling and deterministic budget, so a fallback answers what CP-SAT alone would have
    answered and a native timeout can never leave it without time. A native
    clock-limited witness never seeds fallback: that would make a later deterministic
    CP-SAT search depend on the machine's speed. The existing CP-SAT tie-break remains.
    """

    execute = _EXECUTOR.get()
    if execute is None or weeks not in (3, 5):
        return solver, solve(model, solver), {}
    from ortools.sat.python import cp_model

    started = perf_counter()
    wall = float(solver.parameters.max_time_in_seconds)
    deterministic = float(solver.parameters.max_deterministic_time)
    verification_work = 0.0
    details: dict[str, object] = {"version": NATIVE_VERSION, "selected": False}
    try:
        milp = export_milp(model.proto)
        packet = _wire_model(milp, int(solver.parameters.random_seed))
        response = execute(packet, wall)
        values = _checked_values(milp, response)
        fixed = model.clone()
        fixed.clear_hints()  # type: ignore[no-untyped-call]
        for index, value in enumerate(values):
            fixed.add(fixed.get_int_var_from_proto_index(index) == value)
        certificate = cp_model.CpSolver()
        certificate.parameters.copy_from(solver.parameters)
        certificate.parameters.max_time_in_seconds = max(0.0, wall - (perf_counter() - started))
        certificate.parameters.max_deterministic_time = min(1.0, deterministic)
        raw = solve(fixed, certificate)
        verification_work = float(certificate.response_proto.deterministic_time)
        if raw != cp_model.OPTIMAL:
            raise ValueError("The native witness failed verification in the original CP model.")
        if abs(float(certificate.objective_value) - float(response["objective"])) > 1e-5:
            raise ValueError("The original CP objective disagrees with the native witness.")
        details["selected"] = True
        return certificate, int(cp_model.OPTIMAL), details
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
        details["fallback_reason"] = str(error)
    # The solver's own limits are left as the caller set them. Work the certificate spent
    # on a rejected witness is reported beside the search, never taken from its budget.
    details["verification_work_before_fallback"] = verification_work
    return solver, solve(model, solver), details


def native_solve(packet: Mapping[str, Any], seconds: float) -> dict[str, Any]:
    """Run in the platform's isolated interpreter, which must never import OR-Tools."""

    import highspy

    highs = highspy.Highs()  # type: ignore[no-untyped-call]
    if highs.version() != NATIVE_VERSION:
        raise RuntimeError(f"Native HiGHS {NATIVE_VERSION} is required.")
    for name, value in {
        "output_flag": False,
        "threads": 1,
        "random_seed": int(packet["seed"]),
        "mip_rel_gap": 0.0,
        "mip_abs_gap": 0.5,
        "time_limit": max(0.0, seconds),
    }.items():
        if highs.setOptionValue(name, value) != highspy.HighsStatus.kOk:
            raise RuntimeError(f"HiGHS refused option {name}.")
    lp = highspy.HighsLp()
    lp.num_col_ = len(packet["bounds"])
    lp.num_row_ = len(packet["rows"])
    lp.col_cost_ = packet["cost"]
    lp.col_lower_ = [bounds[0] for bounds in packet["bounds"]]
    lp.col_upper_ = [bounds[1] for bounds in packet["bounds"]]
    lp.integrality_ = [highspy.HighsVarType.kInteger] * lp.num_col_
    lp.sense_ = highspy.ObjSense.kMaximize if packet["maximize"] else highspy.ObjSense.kMinimize
    lp.offset_ = packet["offset"]
    lp.row_lower_ = [row[0] if row[0] is not None else -highspy.kHighsInf for row in packet["rows"]]
    lp.row_upper_ = [row[1] if row[1] is not None else highspy.kHighsInf for row in packet["rows"]]
    starts, indices, coefficients = [0], [], []
    for _, _, terms in packet["rows"]:
        for index, coefficient in terms:
            indices.append(index)
            coefficients.append(coefficient)
        starts.append(len(indices))
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.num_col_, lp.a_matrix_.num_row_ = lp.num_col_, lp.num_row_
    lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = starts, indices, coefficients
    if highs.passModel(lp) != highspy.HighsStatus.kOk:
        raise RuntimeError("HiGHS refused the window model.")
    highs.run()
    info = highs.getInfo()
    optimal = highs.getModelStatus() == highspy.HighsModelStatus.kOptimal
    return {
        "version": highs.version(),
        "threads": highs.getOptionValue("threads")[1],
        "optimal": optimal,
        "values": list(highs.getSolution().col_value) if optimal else [],
        "objective": float(info.objective_function_value) if optimal else None,
        "bound": float(info.mip_dual_bound) if optimal else None,
    }
