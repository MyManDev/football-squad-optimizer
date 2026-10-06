"""The #984 runner: its exporter, its two checks, its guards and its rebuild of the model.

The exporter is held to CP-SAT on small synthetic models, one per constraint kind it
translates: CP-SAT's optimum must be the optimum of the exported MILP, solved here with
``scipy.optimize.milp``. That solver is a test instrument on models of a few variables, never
the measured one. The rebuild is held to the live path itself on the shared member world:
the arguments the runner hands ``optimize_transfer_plan`` are the ones ``solve_window_plan``
and ``plan_transfers`` hand it. Nothing here times a solve.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from ortools.sat.python import cp_model
from scipy.optimize import Bounds, LinearConstraint, milp
from scripts import measure_window_solver_highs as runner
from tests.unit.test_member_windows import ENTRY, LEAGUE
from tests.unit.test_member_windows import _window_world as window_world_fixture

from squadopt.application.advice import solve_window_plan, window_horizon
from squadopt.application.device_plan import device_plan_entry, device_plan_table
from squadopt.application.entries import held_squad_from_picks
from squadopt.live import transfers as live_transfers
from squadopt.live.transfers import plan_transfers

window_world = window_world_fixture  # re-register the shared window world here


# --------------------------------------------------------------------------------------
# Synthetic models, one per constraint kind the exporter translates.


def _lin_max() -> cp_model.CpModel:
    model = cp_model.CpModel()
    x = model.new_int_var(0, 5, "x")
    y = model.new_int_var(0, 5, "y")
    t = model.new_int_var(0, 9, "t")
    model.add_max_equality(t, [x - y, 2 - x, 1])
    model.add(x + y <= 6)
    model.maximize(2 * x + y - 3 * t)
    return model


def _lin_min() -> cp_model.CpModel:
    model = cp_model.CpModel()
    x = model.new_int_var(0, 6, "x")
    y = model.new_int_var(0, 6, "y")
    t = model.new_int_var(-5, 9, "t")
    model.add_min_equality(t, [x + 1, 7 - y, 4])
    model.add(x + y <= 8)
    model.maximize(4 * t + x - 2 * y)
    return model


def _element_constant() -> cp_model.CpModel:
    model = cp_model.CpModel()
    index = model.new_int_var(0, 3, "index")
    price = model.new_int_var(0, 20, "price")
    sell = model.new_bool_var("sell")
    model.add_element(index, [3, 11, 7, 5], price)
    model.add(index <= 2).only_enforce_if(sell.Not())
    model.maximize(price - 4 * index - 2 * sell)
    return model


def _element_variable() -> cp_model.CpModel:
    model = cp_model.CpModel()
    index = model.new_int_var(0, 3, "index")
    x = model.new_int_var(0, 4, "x")
    y = model.new_int_var(0, 3, "y")
    target = model.new_int_var(-10, 20, "target")
    model.add_element(index, [3, x, 2 * y + 1, 7], target)
    model.add(x + y + index <= 5)
    model.maximize(target + x - index)
    return model


def _enforcement() -> cp_model.CpModel:
    model = cp_model.CpModel()
    a = model.new_bool_var("a")
    b = model.new_bool_var("b")
    x = model.new_int_var(0, 10, "x")
    y = model.new_int_var(-3, 6, "y")
    model.add(x >= 7).only_enforce_if(a)
    model.add(x <= 3).only_enforce_if(b.Not())
    model.add(x + y <= 4).only_enforce_if([a, b])
    model.add(x - y == 2).only_enforce_if([a.Not(), b])
    model.maximize(x + 2 * y + 5 * a + 3 * b)
    return model


def _booleans() -> cp_model.CpModel:
    model = cp_model.CpModel()
    v = [model.new_bool_var(f"v{i}") for i in range(6)]
    model.add_bool_or([v[0], v[1].Not(), v[2]])
    model.add_bool_and([v[3], v[4].Not()]).only_enforce_if(v[0])
    model.add_at_most_one([v[1], v[2], v[5]])
    model.add_exactly_one([v[0], v[3], v[4].Not()])
    model.add_bool_or([v[5], v[2]]).only_enforce_if(v[1].Not())
    model.maximize(3 * v[0] + v[1] + 2 * v[2] + 4 * v[3] + 5 * v[4] + v[5])
    return model


def _minimise() -> cp_model.CpModel:
    model = cp_model.CpModel()
    x = model.new_int_var(-4, 8, "x")
    y = model.new_int_var(0, 5, "y")
    paid = model.new_int_var(0, 8, "paid")
    model.add_max_equality(paid, [x - y, 0])
    model.add(x + 2 * y >= 7)
    model.minimize(3 * paid + 2 * y - x + 10)
    return model


def _scaled(scaling: float, offset: float) -> Callable[[], cp_model.CpModel]:
    def build() -> cp_model.CpModel:
        model = _lin_max()
        model.proto.objective.scaling_factor = scaling
        model.proto.objective.offset = offset
        return model

    return build


MODELS: dict[str, Callable[[], cp_model.CpModel]] = {
    "lin_max": _lin_max,
    "lin_min": _lin_min,
    "element_constant": _element_constant,
    "element_variable": _element_variable,
    "enforcement": _enforcement,
    "booleans": _booleans,
    "minimise": _minimise,
    "scaled_maximise": _scaled(-2.5, 3.0),
    "scaled_minimise": _scaled(0.5, -1.0),
}


def _cp_sat(model: cp_model.CpModel) -> tuple[float, list[int]]:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    assert solver.solve(model) == cp_model.OPTIMAL
    return float(solver.objective_value), [int(v) for v in solver.response_proto.solution]


def _export(model: cp_model.CpModel) -> tuple[runner.Milp, runner.ParsedMps, str]:
    exported = runner.export_milp(model.proto, "test")
    text = runner.write_mps(exported)
    return exported, runner.read_mps(text), text


def _scipy(parsed: runner.ParsedMps, offset: float) -> tuple[float, list[float]]:
    columns = len(parsed.column_names)
    cost = np.zeros(columns)
    for j, coeff in parsed.objective.items():
        cost[j] = float(coeff)
    sign = -1.0 if parsed.maximize else 1.0
    matrix = np.zeros((len(parsed.rows), columns))
    for r, terms in enumerate(parsed.rows):
        for j, coeff in terms.items():
            matrix[r, j] = float(coeff)
    result = milp(
        sign * cost,
        integrality=np.array([1 if flag else 0 for flag in parsed.integer]),
        bounds=Bounds(parsed.lower, parsed.upper),
        constraints=[LinearConstraint(matrix, parsed.row_lower, parsed.row_upper)],
        options={"mip_rel_gap": 0.0},
    )
    assert result.success, result.message
    return sign * float(result.fun) + offset, [float(v) for v in result.x]


@pytest.mark.parametrize("name", sorted(MODELS))
def test_the_exported_milp_has_cp_sat_s_optimum(name: str) -> None:
    model = MODELS[name]()
    optimum, _ = _cp_sat(model)
    exported, parsed, _ = _export(model)
    value, _ = _scipy(parsed, float(exported.objective_offset))
    assert value == pytest.approx(optimum, abs=1e-6)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_check_one_passes_on_cp_sat_s_solution(name: str) -> None:
    model = MODELS[name]()
    optimum, solution = _cp_sat(model)
    exported, parsed, _ = _export(model)
    check = runner.check_one(exported, parsed, model.proto, solution, optimum)
    assert check["passed"], check
    assert check["worst_violation"] == 0.0


@pytest.mark.parametrize("name", sorted(MODELS))
def test_check_two_passes_on_the_milp_s_solution(name: str) -> None:
    model = MODELS[name]()
    exported, parsed, _ = _export(model)
    _, solution = _scipy(parsed, float(exported.objective_offset))
    check = runner.check_two(exported, parsed, model.proto, solution)
    assert check["passed"], check
    optimum, _ = _cp_sat(model)
    assert check["value"] == pytest.approx(optimum, abs=1e-6)


def test_each_handled_kind_is_seen_by_the_exporter() -> None:
    seen: set[str] = set()
    for build in MODELS.values():
        seen |= set(runner.export_milp(build().proto).kinds)
    assert {
        "linear",
        "linear (enforced)",
        "lin_max",
        "element",
        "bool_or",
        "bool_or (enforced)",
        "bool_and (enforced)",
        "at_most_one",
        "exactly_one",
    } <= seen


def test_the_scaled_objective_keeps_its_direction_and_constant() -> None:
    exported = runner.export_milp(_scaled(-2.5, 3.0)().proto)
    assert exported.maximize is True
    assert exported.objective_offset == pytest.approx(-7.5)
    assert runner.export_milp(_scaled(0.5, -1.0)().proto).maximize is False
    assert runner.export_milp(_minimise().proto).objective_offset == 10


def _corrupt_rhs(text: str, row: str, value: int) -> str:
    lines = text.splitlines()
    marker = f"    RHS  {row}  "
    index = next(i for i, line in enumerate(lines) if line.startswith(marker))
    lines[index] = f"{marker}{value}"
    return "\n".join(lines) + "\n"


def test_check_one_fails_on_a_corrupted_row() -> None:
    model = _lin_max()
    optimum, solution = _cp_sat(model)
    exported, _, text = _export(model)
    one = next(row.name for row in exported.rows if row.name.endswith("_one"))
    corrupted = runner.read_mps(_corrupt_rhs(text, one, 2))
    check = runner.check_one(exported, corrupted, model.proto, solution, optimum)
    assert not check["passed"]
    assert any(one in violation for violation in check["violations"])


def test_check_one_fails_on_a_corrupted_objective() -> None:
    model = _lin_max()
    optimum, solution = _cp_sat(model)
    exported, parsed, _ = _export(model)
    x = parsed.column("x0")
    parsed.objective[x] = int(parsed.objective[x]) + 1
    check = runner.check_one(exported, parsed, model.proto, solution, optimum)
    assert not check["passed"]
    assert check["same_value"] is False


def test_check_two_fails_on_an_infeasible_point() -> None:
    model = _enforcement()
    exported, parsed, _ = _export(model)
    _, solution = _scipy(parsed, 0.0)
    a, x = parsed.column("x0"), parsed.column("x2")
    solution[a], solution[x] = 1.0, 2.0  # a forces x >= 7
    check = runner.check_two(exported, parsed, model.proto, solution)
    assert not check["passed"]
    assert check["cp_sat_status"] == "INFEASIBLE"


def test_check_two_fails_when_the_mps_objective_is_not_the_model_s() -> None:
    model = _lin_max()
    exported, parsed, _ = _export(model)
    _, solution = _scipy(parsed, 0.0)
    x = parsed.column("x0")
    assert round(solution[x]) != 0
    parsed.objective[x] = int(parsed.objective[x]) + 1
    check = runner.check_two(exported, parsed, model.proto, solution)
    assert not check["passed"]
    assert check["value"] != check["mps_value"]


def test_check_two_rounds_a_near_integer_solution() -> None:
    model = _booleans()
    exported, parsed, _ = _export(model)
    _, solution = _scipy(parsed, 0.0)
    nudged = [value + (2e-7 if value < 0.5 else -2e-7) for value in solution]
    check = runner.check_two(exported, parsed, model.proto, nudged)
    assert check["passed"]
    assert check["rounding_distance"] == pytest.approx(2e-7)


def _refused(model: cp_model.CpModel, match: str) -> None:
    with pytest.raises(runner.ExportRefused, match=match):
        runner.export_milp(model.proto)


def test_a_constraint_kind_the_exporter_does_not_translate_is_refused_by_name() -> None:
    model = cp_model.CpModel()
    x = model.new_int_var(0, 3, "x")
    y = model.new_int_var(0, 3, "y")
    z = model.new_int_var(0, 9, "z")
    model.add_multiplication_equality(z, [x, y])
    _refused(model, "int_prod")
    model = cp_model.CpModel()
    model.add_all_different([model.new_int_var(0, 3, f"v{i}") for i in range(3)])
    _refused(model, "all_diff")


def test_an_enforced_maximum_is_refused() -> None:
    model = cp_model.CpModel()
    b = model.new_bool_var("b")
    x = model.new_int_var(0, 3, "x")
    t = model.new_int_var(0, 3, "t")
    model.add_max_equality(t, [x, 1]).only_enforce_if(b)
    _refused(model, "enforced lin_max")


def test_a_domain_with_holes_is_refused() -> None:
    model = cp_model.CpModel()
    model.new_int_var_from_domain(cp_model.Domain.from_values([1, 3, 5]), "holes")
    _refused(model, "holes")
    model = cp_model.CpModel()
    x = model.new_int_var(0, 9, "x")
    model.add_linear_expression_in_domain(x, cp_model.Domain.from_intervals([[0, 2], [5, 9]]))
    _refused(model, "holes")


def test_a_floating_point_objective_is_refused() -> None:
    model = cp_model.CpModel()
    x = model.new_int_var(0, 3, "x")
    model.minimize(0.5 * x)
    _refused(model, "floating-point objective")


def test_the_mps_reads_back_as_written() -> None:
    model = _element_variable()
    exported, parsed, text = _export(model)
    assert parsed.column_names == [column.name for column in exported.columns]
    assert all(parsed.integer)
    assert parsed.row_names == [row.name for row in exported.rows]
    assert text.startswith("NAME test\nOBJSENSE\n    MAX\nROWS\n N  OBJ\n")
    for row, low, high in zip(exported.rows, parsed.row_lower, parsed.row_upper, strict=True):
        assert low == (-np.inf if row.lower is None else row.lower)
        assert high == (np.inf if row.upper is None else row.upper)


# --------------------------------------------------------------------------------------
# Guards.


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 10, 9, 0, 0, tzinfo=UTC),
        datetime(2026, 10, 10, 23, 59, 59, tzinfo=UTC),
        datetime(2026, 10, 10, 2, 0, tzinfo=timezone(timedelta(hours=3))),
        datetime(2026, 10, 11, 1, 0, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_no_solve_runs_on_9_or_10_october_utc(moment: datetime) -> None:
    with pytest.raises(runner.ProtocolRefusal, match="9 or 10"):
        runner.refuse_blocked_date(moment)


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 10, 8, 23, 59, 59, tzinfo=UTC),
        datetime(2026, 10, 11, 0, 0, tzinfo=UTC),
        datetime(2026, 10, 9, 2, 0, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_the_days_around_the_blocked_two_are_allowed(moment: datetime) -> None:
    runner.refuse_blocked_date(moment)


GOOD_DAY = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
GOOD_WASM = {"core_version": "1.15.3", "node_version": "v22.23.3", "package_version": "1.15.3"}


def _never() -> Any:
    raise AssertionError("a version reader ran before the slot was claimed")


def test_measuring_without_the_slot_is_refused_before_any_version_is_read() -> None:
    with pytest.raises(runner.ProtocolRefusal, match="slot"):
        runner.measure_guards(
            have_slot=False, now=GOOD_DAY, native_version=_never, wasm_version=_never
        )


@pytest.mark.parametrize(
    ("native", "wasm", "match"),
    [
        ("1.15.2", GOOD_WASM, "highspy reports HiGHS 1.15.2"),
        ("1.12.0", GOOD_WASM, "highspy reports HiGHS 1.12.0"),
        ("1.15.3", {**GOOD_WASM, "core_version": "1.15.2"}, "package reports HiGHS 1.15.2"),
        ("1.15.3", {**GOOD_WASM, "node_version": "v24.1.0"}, "Node is v24.1.0"),
        ("1.15.3", {"core_version": "1.15.3"}, "Node is unknown"),
    ],
)
def test_measuring_with_another_version_is_refused(
    native: str, wasm: dict[str, Any], match: str
) -> None:
    with pytest.raises(runner.ProtocolRefusal, match=match):
        runner.measure_guards(
            have_slot=True, now=GOOD_DAY, native_version=lambda: native, wasm_version=lambda: wasm
        )


def test_measuring_on_a_blocked_day_is_refused_even_with_the_slot() -> None:
    with pytest.raises(runner.ProtocolRefusal, match="9 or 10"):
        runner.measure_guards(
            have_slot=True,
            now=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
            native_version=_never,
            wasm_version=_never,
        )


def test_the_guards_pass_the_versions_through_when_everything_holds() -> None:
    versions = runner.measure_guards(
        have_slot=True,
        now=GOOD_DAY,
        native_version=lambda: "1.15.3",
        wasm_version=lambda: GOOD_WASM,
    )
    assert versions == {"native_core": "1.15.3", "wasm": GOOD_WASM}


def test_the_measure_command_refuses_without_the_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "native_core_version", _never)
    monkeypatch.setattr(runner, "wasm_report", lambda node: _never())
    monkeypatch.setattr(runner, "run_measure", lambda *a, **k: _never())
    assert runner.main(["measure"]) == 2
    assert "slot" in capsys.readouterr().err


def test_the_measure_command_refuses_a_wrong_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "native_core_version", lambda: "1.15.0")
    monkeypatch.setattr(runner, "wasm_report", lambda node: GOOD_WASM)
    monkeypatch.setattr(runner, "run_measure", lambda *a, **k: _never())
    monkeypatch.setattr(runner, "datetime", _FixedDateTime)
    monkeypatch.setattr(runner, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(runner, "RECORD_JSON", tmp_path / "never.json")
    assert runner.main(["measure", "--i-have-the-slot"]) == 2
    assert "1.15.0" in capsys.readouterr().err
    stopped = json.loads((tmp_path / "stopped.json").read_text(encoding="utf-8"))
    assert "1.15.0" in stopped["reason"]
    assert not (tmp_path / "never.json").exists()


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> _FixedDateTime:
        return cls(2026, 10, 7, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------------------
# The committed inputs and the capture.


def test_the_committed_inputs_are_the_protocol_s_capture() -> None:
    inputs = runner.load_inputs()
    assert len(inputs.members) == 15
    assert inputs.gameweek == 6
    for week in range(6, 11):
        assert set(inputs.fixture_counts[week].values()) == {1}


def _copy_inputs(tmp_path: Path) -> tuple[Path, Path]:
    league = tmp_path / "league"
    (league / "entries").mkdir(parents=True)
    shutil.copy(runner.LEAGUE_DIR / "device-plan.json", league / "device-plan.json")
    for path in (runner.LEAGUE_DIR / "entries").glob("*.json"):
        shutil.copy(path, league / "entries" / path.name)
    fixtures = tmp_path / "fixtures.json"
    shutil.copy(runner.FIXTURES_PATH, fixtures)
    return league, fixtures


def _restamp(path: Path, capture: str) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["payload"]["source_snapshot_id"] = capture
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.mark.parametrize("which", ["device-plan", "entry", "fixtures"])
def test_an_input_from_another_capture_is_refused(tmp_path: Path, which: str) -> None:
    league, fixtures = _copy_inputs(tmp_path)
    assert len(runner.load_inputs(league, fixtures).members) == 15
    target = {
        "device-plan": league / "device-plan.json",
        "entry": sorted((league / "entries").glob("*.json"))[0],
        "fixtures": fixtures,
    }[which]
    _restamp(target, "fpl-live-20260922T214539Z-364991a4f832")
    with pytest.raises(runner.ProtocolRefusal, match="20260922T214539Z"):
        runner.load_inputs(league, fixtures)


def test_published_advice_from_another_capture_is_refused(tmp_path: Path) -> None:
    league, fixtures = _copy_inputs(tmp_path)
    inputs = runner.load_inputs(league, fixtures)
    entry = sorted(inputs.members)[0]
    advice = league / "advice" / str(entry) / "saf-puan"
    advice.mkdir(parents=True)
    source = runner.LEAGUE_DIR / "advice" / str(entry) / "saf-puan" / "1.json"
    shutil.copy(source, advice / "1.json")
    assert runner.published_advice(inputs, entry, 1)["entry_id"] == entry
    _restamp(advice / "1.json", "another-capture")
    with pytest.raises(runner.ProtocolRefusal, match="another-capture"):
        runner.published_advice(inputs, entry, 1)


# --------------------------------------------------------------------------------------
# The rebuild is the live path's own call, on the shared member world.


class _Stop(Exception):
    pass


def _world_inputs(world: dict[str, Any], tmp_path: Path) -> runner.PublishedInputs:
    inputs, projection, rules = world["inputs"], world["projection"], world["rules"]
    picks = world["provider"].picks(ENTRY, inputs.season, int(inputs.deadline.gameweek) - 1)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    table = device_plan_table(inputs, projection, rules, league_id=LEAGUE)
    block = device_plan_entry(inputs, projection, held, rules)
    assert block is not None
    gameweek = int(inputs.deadline.gameweek)
    horizon = world["builder"](tuple(range(gameweek, gameweek + 5)))
    counts: dict[int, dict[str, int]] = {}
    for row in horizon.table.itertuples(index=False):
        counts.setdefault(int(row.gameweek), {})[str(row.team_id)] = int(row.fixture_count)
    return runner.PublishedInputs(table, {ENTRY: block}, counts, tmp_path)


def _recorded_call(monkeypatch: pytest.MonkeyPatch, solve: Callable[[], object]) -> dict[str, Any]:
    recorded: dict[str, Any] = {}

    def record(*args: Any, **kwargs: Any) -> Any:
        recorded["args"], recorded["kwargs"] = args, kwargs
        raise _Stop

    monkeypatch.setattr(live_transfers, "optimize_transfer_plan", record)
    with pytest.raises(_Stop):
        solve()
    return recorded


def _assert_same_call(recorded: dict[str, Any], call: runner.PlannerCall) -> None:
    horizon, state, settings, policy = recorded["args"]
    assert call.horizon.horizon_fingerprint == horizon.horizon_fingerprint
    assert call.state == state
    assert call.settings == settings
    assert call.policy == policy
    assert call.policy.configuration_fingerprint == policy.configuration_fingerprint
    kwargs = recorded["kwargs"]
    assert kwargs.get("chips") is None
    assert kwargs.get("linearization_level") == call.linearization_level
    assert bool(kwargs.get("protect_hold", False)) is call.protect_hold
    for name in ("first_week_overlap", "first_week_transfer_cap", "first_week_exclusion"):
        assert kwargs.get(name) is None
    assert kwargs.get("preferences") is None


@pytest.mark.parametrize("window", [3, 5])
def test_the_window_call_is_the_one_solve_window_plan_makes(
    window_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, window: int
) -> None:
    world = window_world
    inputs, rules = world["inputs"], world["rules"]
    assert rules.transfers.sell_on_fee == runner.SELL_ON_FEE
    published = _world_inputs(world, tmp_path)
    picks = world["provider"].picks(ENTRY, inputs.season, int(inputs.deadline.gameweek) - 1)
    horizon = window_horizon(inputs, window, world["builder"])
    recorded = _recorded_call(
        monkeypatch, lambda: solve_window_plan(picks, inputs, rules, horizon, window=window)
    )
    call = runner.window_call(published, ENTRY, window)
    _assert_same_call(recorded, call)
    assert call.linearization_level == 2 and call.protect_hold is True


def test_the_one_week_call_is_the_one_plan_transfers_makes(
    window_world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = window_world
    inputs, projection, rules = world["inputs"], world["projection"], world["rules"]
    published = _world_inputs(world, tmp_path)
    picks = world["provider"].picks(ENTRY, inputs.season, int(inputs.deadline.gameweek) - 1)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    recorded = _recorded_call(monkeypatch, lambda: plan_transfers(inputs, projection, held, rules))
    _assert_same_call(recorded, runner.one_week_call(published, ENTRY))


# --------------------------------------------------------------------------------------
# The captured models of a real window solve, exported and checked.


@pytest.fixture(name="world_instance")
def _world_instance(window_world: dict[str, Any], tmp_path: Path) -> runner.Instance:
    published = _world_inputs(window_world, tmp_path)
    call = runner.window_call(published, ENTRY, 3)
    with runner.capture_cp_sat_solves() as solves:
        plan = call.solve()
    instance = runner.Instance(ENTRY, 3, call, plan, runner.identify_window_solves(solves, 3))
    runner.export_instance(instance, tmp_path / "mps")
    return instance


def test_the_capture_names_the_hold_probe_and_the_primary(world_instance: runner.Instance) -> None:
    solves = world_instance.solves
    assert solves.hold.parameters["max_deterministic_time"] == 1.0
    assert solves.primary.parameters["max_deterministic_time"] == 60.0
    assert solves.primary.parameters["linearization_level"] == 2
    assert solves.primary.parameters["num_search_workers"] == 1
    assert len(solves.hold.proto.constraints) == solves.base_constraints + 3
    assert len(solves.primary.proto.constraints) == solves.base_constraints + 1
    assert solves.floor_value == round(float(solves.hold.objective_value or 0))
    assert solves.primary.status == "OPTIMAL" and solves.tiebreak is not None
    assert world_instance.plan.solver_status.name == "OPTIMAL"
    record = runner.cp_sat_record(world_instance, with_time=False)
    assert record["proved"] and "seconds" not in record
    expected = world_instance.plan.diagnostics["scaled_model_objective_value"]
    assert record["value_points"] == pytest.approx(expected)


def test_the_capture_leaves_the_solver_as_it_found_it() -> None:
    before = cp_model.CpSolver.solve
    with runner.capture_cp_sat_solves() as solves:
        model = _lin_max()
        cp_model.CpSolver().Solve(model)
    assert cp_model.CpSolver.solve is before
    assert [solve.status for solve in solves] == ["OPTIMAL"]
    assert solves[0].solution and solves[0].objective_value is not None


def test_a_window_whose_extra_constraint_is_not_the_floor_is_refused(
    world_instance: runner.Instance,
) -> None:
    solves = world_instance.solves
    swapped = [solves.primary, solves.hold]
    with pytest.raises(runner.ProtocolRefusal):
        runner.identify_window_solves(swapped, 3)


def test_the_world_window_exports_and_passes_check_one(world_instance: runner.Instance) -> None:
    export = world_instance.export
    assert export["check_1_passed"], export
    assert export["hold_floor_dropped"] is True
    assert export["hold"]["rows"] > export["primary"]["rows"]
    assert export["primary"]["check_1"]["solution_from"] == "primary"
    assert {"linear", "lin_max"} <= set(export["primary"]["constraint_kinds"])


def _milp_point(instance: runner.Instance, solution: tuple[int, ...], proto: Any) -> list[float]:
    assert instance.primary_milp is not None
    values = runner.cp_sat_assignment(instance.primary_milp, proto, solution)
    assert values is not None
    return [float(value) for value in values]


def test_a_highs_answer_is_read_on_the_integer_scale(world_instance: runner.Instance) -> None:
    solves = world_instance.solves
    primary = _milp_point(world_instance, solves.primary.solution, world_instance.primary_proto)
    hold = _milp_point(world_instance, solves.hold.solution, solves.hold.proto)
    raw = {
        "load_seconds": 0.1,
        "hold": {"model_status": 7, "seconds": 0.5, "objective": solves.hold.objective_value},
        "hold_solution": hold,
        "floor": solves.floor_value,
        "primary": {"model_status": 7, "seconds": 1.5, "bound": solves.primary.objective_value},
        "primary_solution": primary,
    }
    run = runner.interpret_run(world_instance, raw, None)
    assert run["status"] == "proved_optimal"
    assert run["value"] == solves.primary_value
    assert run["agrees_with_cp_sat"] is True
    assert run["check_2_passed"] and len(run["check_2"]) == 2
    assert run["seconds"] == pytest.approx(2.0)
    assert run["gap_units"] == pytest.approx(0.0)
    timed_out = {**raw, "primary": {"model_status": 13, "seconds": 9.0}, "primary_solution": None}
    run = runner.interpret_run(world_instance, timed_out, None)
    assert (run["status"], run["value_from"]) == ("feasible", "hold")
    assert run["value"] == solves.floor_value
    run = runner.interpret_run(world_instance, None, "exit 3")
    assert run["status"] == "error" and run["value"] is None


def test_the_floor_is_the_objective_at_the_rounded_hold_solution(
    world_instance: runner.Instance,
) -> None:
    solves = world_instance.solves
    assert world_instance.primary_milp is not None
    hold = _milp_point(world_instance, solves.hold.solution, solves.hold.proto)
    nudged = [value + 3e-7 for value in hold]
    costs = world_instance.primary_milp.objective
    assert runner.floor_value(nudged, costs) == solves.floor_value


def test_a_plan_s_own_transfers_are_valued_at_its_objective(
    world_instance: runner.Instance,
) -> None:
    """The published-plan valuation is exact: CP-SAT's own optimal plan values at its optimum."""

    plan = world_instance.plan
    published = {
        "solver_status": plan.solver_status.name,
        "plan_weeks": [
            {
                "gameweek": int(week.gameweek),
                "transfers_in": [{"player_id": int(p)} for p in week.transfers_in["player_id"]],
                "transfers_out": [{"player_id": int(p)} for p in week.transfers_out["player_id"]],
            }
            for week in plan.weeks
        ],
    }
    valued = runner.published_plan_value(world_instance.call, published)
    assert valued["value"] == world_instance.solves.primary_value


# --------------------------------------------------------------------------------------
# Verdicts.


def _run(
    status: str, value: int | None, seconds: float | None, agrees: bool | None
) -> dict[str, Any]:
    return {"status": status, "value": value, "seconds": seconds, "agrees_with_cp_sat": agrees}


def _row(
    entry: int, window: int, *, cp_proved: bool = True, plan_status: str = "OPTIMAL", **runs: Any
) -> dict[str, Any]:
    proved = _run("proved_optimal", 100_000, 2.0, True)
    return {
        "entry_id": entry,
        "window": window,
        "cp_sat": {"proved": cp_proved, "value": 100_000, "plan_status": plan_status},
        "highs": {
            build: {
                "wall_matched": runs.get(f"{build}_matched", proved),
                "ceiling": runs.get(f"{build}_ceiling", proved),
            }
            for build in ("native", "wasm")
        },
    }


def _league(**changes: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for window in (3, 5):
        for entry in range(15):
            feasible = window == 5 and entry < 4
            row = _row(
                entry,
                window,
                cp_proved=not feasible,
                plan_status="FEASIBLE" if feasible else "OPTIMAL",
            )
            for key, value in changes.get(f"{entry}-{window}", {}).items():
                build, run = key.split("_", 1)
                row["highs"][build][run] = value
            rows.append(row)
    return rows


def test_both_verdicts_pass_when_every_threshold_holds() -> None:
    result = runner.verdicts(_league())
    assert result["verdict"] is None
    assert result["device"] == "Device can carry windows on a flat calendar"
    assert result["server"] == "A switch is supported"


def test_a_three_week_proof_over_15_seconds_keeps_windows_on_the_server() -> None:
    slow = {"0-3": {"wasm_ceiling": _run("proved_optimal", 100_000, 15.5, True)}}
    assert runner.verdicts(_league(**slow))["device"] == "windows stay on the server"
    one_slow_five = {"0-5": {"wasm_ceiling": _run("proved_optimal", 100_000, 15.5, True)}}
    assert runner.verdicts(_league(**one_slow_five))["device"] == (
        "Device can carry windows on a flat calendar"
    )
    two = {
        "0-5": {"wasm_ceiling": _run("feasible", 100_000, 1800.0, True)},
        "1-5": {"wasm_ceiling": _run("error", None, None, None)},
    }
    assert runner.verdicts(_league(**two))["device"] == "windows stay on the server"


def test_the_server_conditions_each_fail_on_their_own() -> None:
    missed = {"5-3": {"native_wall_matched": _run("feasible", 100_000, 2.0, True)}}
    assert runner.verdicts(_league(**missed))["server"] == "the server stays on CP-SAT"
    unproved = {
        f"{entry}-5": {"native_ceiling": _run("feasible", 100_000, 1800.0, True)}
        for entry in range(3)
    }
    result = runner.verdicts(_league(**unproved))
    assert result["server_conditions"]["ceiling_proves_half_of_feasible_five_week"] is False
    below = {"6-3": {"native_ceiling": _run("feasible", 98_999, 1800.0, False)}}
    result = runner.verdicts(_league(**below))
    assert result["server_conditions"]["ceiling_never_below_cp_sat"] is False
    nothing = {"6-3": {"native_ceiling": _run("no_solution", None, 1800.0, None)}}
    assert runner.verdicts(_league(**nothing))["server"] == "the server stays on CP-SAT"


def test_no_five_week_left_feasible_fails_the_second_server_condition() -> None:
    rows = [_row(entry, window) for window in (3, 5) for entry in range(15)]
    result = runner.verdicts(rows)
    assert result["server_conditions"]["five_week_left_feasible_by_cp_sat"] == 0
    assert result["server"] == "the server stays on CP-SAT"


def test_a_proved_disagreement_replaces_both_verdicts() -> None:
    wrong = {"7-3": {"wasm_ceiling": _run("proved_optimal", 101_001, 3.0, False)}}
    result = runner.verdicts(_league(**wrong))
    assert result["verdict"] == "the models disagree"
    assert result["device"] is None and result["server"] is None
    assert result["disagreements"] == [{"entry_id": 7, "window": 3, "build": "wasm"}]
