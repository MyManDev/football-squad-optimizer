"""A runner that writes a committed record names the limits it solved under.

`OptimizationConfig()` binds on ten wall-clock seconds. A busy machine therefore gives the
solver less work, a solve that would have been proved comes back an incumbent, and the same
commit writes a different record: #590 measured the rotation ceiling moving from 0.959 to
0.667 and losing five of its 147 folds under load. `measurement_optimization_config()` is the
answer that landed with #631, and this holds the rule for every runner rather than for the
one that was fixed first.

It is one test over a directory rather than one test per runner on purpose. Thirteen copies
of the same assertion would be the duplication #554 is about, and a copy is exactly what
nobody adds when they write the fourteenth runner. The exemption list below is the work that
remains, by name, and it has to reach zero.
"""

import ast
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

#: Runners that still solve under the inherited wall clock. Each entry is one pull request of
#: task 2 on #621, and removing the last of them is what finishes it. A name may leave this
#: list only when its runner names the configuration, never by being quietly deleted.
NOT_YET_NAMED: frozenset[str] = frozenset(
    {
        "_phase_e_evaluation.py",
        "evaluate_phase_c_components.py",
        "measure_in_season_blend.py",
        "probe_phase_e_runtime.py",
        "run_component_squad_calibration.py",
        "run_scenario_benchmark.py",
    }
)

#: Solved under a budget of its own, measured and recorded rather than inherited. The rank
#: objective has carried its own deterministic budget since #244, so the squad model's number
#: does not apply to it (#621), and the member window's budget is the subject of the
#: measurement that uses it rather than a limit on it.
OWN_BUDGET: frozenset[str] = frozenset(
    {"measure_windowed_rank.py", "measure_member_window_proofs.py"}
)


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) == name or getattr(node.func, "attr", None) == name)
    ]


def _inherits_the_wall_clock(tree: ast.AST) -> bool:
    """Whether this source builds a solver configuration without saying what binds it."""

    for call in _calls(tree, "OptimizationConfig"):
        named = {keyword.arg for keyword in call.keywords}
        if "solver_deterministic_time_limit" not in named:
            return True
    for call in _calls(tree, "EvaluationConfig"):
        if "optimization_config" not in {keyword.arg for keyword in call.keywords}:
            return True
    return False


def _solving_runners() -> dict[str, ast.AST]:
    trees: dict[str, ast.AST] = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not any(
            marker in source
            for marker in (
                "OptimizationConfig(",
                "EvaluationConfig(",
                "measurement_optimization_config(",
            )
        ):
            continue
        trees[path.name] = ast.parse(source)
    return trees


def test_every_runner_that_solves_names_its_limits_or_is_named_here() -> None:
    """The rule, and the list of what has not met it yet."""

    offenders = {
        name
        for name, tree in _solving_runners().items()
        if _inherits_the_wall_clock(tree) and name not in OWN_BUDGET
    }

    assert offenders <= NOT_YET_NAMED, (
        "These runners solve under the inherited wall clock and are not on the list of ones "
        f"known to: {sorted(offenders - NOT_YET_NAMED)}. A record written under a wall-clock "
        "limit is the machine's as much as the run's (#590)."
    )


def test_the_exemption_list_names_only_runners_that_still_need_the_work() -> None:
    """A stale exemption is worse than none: it hides a rule that is already held."""

    trees = _solving_runners()
    still_inheriting = {name for name, tree in trees.items() if _inherits_the_wall_clock(tree)}
    unknown = NOT_YET_NAMED - set(trees)

    assert unknown == set(), f"Exempted runners that no longer exist or no longer solve: {unknown}"
    assert still_inheriting >= NOT_YET_NAMED, (
        "These are exempted and already name their limits, so the exemption should go: "
        f"{sorted(NOT_YET_NAMED - still_inheriting)}"
    )


def test_the_converted_runners_name_the_measurement_configuration() -> None:
    """Asserted by what they call rather than by the absence of the old call."""

    trees = _solving_runners()
    for name in (
        "measure_anchored_calibration.py",
        "measure_mode_plan_selection.py",
        "measure_overlap_calibration.py",
        "measure_rival_calibration.py",
        "measure_strategy_bench.py",
        "measure_strategy_screening.py",
        "measure_template_rival.py",
        "run_opening_backtest.py",
        "run_planner_horizon_seasons.py",
        "run_season_chain_seasons.py",
        "run_transfer_discipline_seasons.py",
    ):
        assert _calls(trees[name], "measurement_optimization_config"), name
        assert not _inherits_the_wall_clock(trees[name]), name
