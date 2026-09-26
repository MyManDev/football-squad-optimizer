"""What `docs/data_followups.md` says about the code is what the code does.

The file is a list of deferred data work, and its sentences about which module reads which
column, or how often the panel is built, are prose constants: nothing re-derives them, so a
wrong one survives every other check. Four did. The difficulty summaries were said not to be
computed on the development folds, the two-stage model was said to read both fixture counts,
the member-publication workers were said to be the one caller that builds the panel once per
worker process, and every other caller was said to build it once per run. Each test below pins
the code fact and the sentence that states it, so the next change to either one fails here
instead of misleading a reader.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

import squadopt.features.fixtures as fixtures_module
from squadopt.application.league_publication import LeaguePublicationRequest
from squadopt.data.fixtures import aggregate_team_gameweek
from squadopt.data.schema import FIXTURE_COLUMNS
from squadopt.features import PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN
from squadopt.features.fixtures import (
    CALENDAR_ONLY_COLUMNS,
    FIXTURE_FEATURE_COLUMNS,
    attach_fixture_features,
)
from squadopt.platform.publication_workers import league_mapper
from squadopt.prediction import (
    PredictionProvenance,
    ProductionProjectionConfig,
    production_component_prediction,
    production_projection,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FOLLOWUPS = REPOSITORY_ROOT / "docs" / "data_followups.md"
RUNBOOK = REPOSITORY_ROOT / "docs" / "weekly_runbook.md"
PACKAGE = REPOSITORY_ROOT / "src" / "squadopt"

DIFFICULTY_COLUMNS = ("mean_fixture_difficulty", "minimum_fixture_difficulty")
SEASON = "2025-26"
TEAM_CODES = pd.DataFrame(
    [
        {"season": SEASON, "name": "Arsenal", "code": 3},
        {"season": SEASON, "name": "Liverpool", "code": 14},
    ]
)


def _flat(text: str) -> str:
    """Collapse line wrapping, so a phrase matches wherever the paragraph breaks it."""

    return " ".join(text.split())


def _item(number: str) -> str:
    """Return one numbered item of the followups list, from its heading to the next one."""

    text = FOLLOWUPS.read_text(encoding="utf-8")
    found = re.search(
        rf"^### {re.escape(number)}\. .*?(?=^#{{2,3}} |\Z)", text, flags=re.MULTILINE | re.DOTALL
    )
    assert found is not None, f"docs/data_followups.md has no item {number}."
    return _flat(found.group(0))


# --- item 4: the difficulty summaries ---------------------------------------


def _fixtures(captured_at_utc: object) -> pd.DataFrame:
    shared: dict[str, object] = {
        "snapshot_id": "claims",
        "captured_at_utc": captured_at_utc,
        "season": SEASON,
        "gameweek": 1,
        "fixture_id": 1,
        "kickoff_time_utc": "2025-08-15T19:00:00Z",
        "deadline_timestamp_utc": pd.NA,
        "status": "final",
    }
    rows = [
        {**shared, "team_id": 3, "opponent_team_id": 14, "is_home": True, "fixture_difficulty": 2},
        {**shared, "team_id": 14, "opponent_team_id": 3, "is_home": False, "fixture_difficulty": 5},
    ]
    frame = pd.DataFrame(rows, columns=list(FIXTURE_COLUMNS))
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    frame["is_home"] = frame["is_home"].astype("boolean")
    frame["fixture_difficulty"] = frame["fixture_difficulty"].astype("Int64")
    for column in (
        "snapshot_id",
        "season",
        "kickoff_time_utc",
        "status",
        "captured_at_utc",
        "deadline_timestamp_utc",
    ):
        frame[column] = frame[column].astype("string")
    return frame


def test_the_difficulty_summaries_are_computed_on_every_call_and_attached_only_from_a_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Computed and dropped on archive rows; computed and attached on a live capture.

    Both calls pass ``unproven_difficulty="omit"``, as every caller in the repository does,
    including the live scoring frame. So "not computed" is false on either path, and the
    open question item 4 keeps (whether to compute two columns nothing reads) is live on both.
    """

    assert tuple(c for c in FIXTURE_FEATURE_COLUMNS if c not in CALENDAR_ONLY_COLUMNS) == (
        DIFFICULTY_COLUMNS
    )
    aggregates: list[pd.DataFrame] = []

    def recording(fixtures: pd.DataFrame) -> pd.DataFrame:
        aggregate = aggregate_team_gameweek(fixtures)
        aggregates.append(aggregate)
        return aggregate

    monkeypatch.setattr(fixtures_module, "aggregate_team_gameweek", recording)
    panel = pd.DataFrame([{"season": SEASON, "gameweek": 1, "player_id": 1, "team_id": "Arsenal"}])

    archive = attach_fixture_features(
        panel, _fixtures(pd.NA), TEAM_CODES, unproven_difficulty="omit"
    )
    live = attach_fixture_features(
        panel, _fixtures("2025-08-14T18:00:00Z"), TEAM_CODES, unproven_difficulty="omit"
    )

    assert len(aggregates) == 2
    for aggregate in aggregates:
        assert set(DIFFICULTY_COLUMNS) <= set(aggregate.columns)
    assert not set(DIFFICULTY_COLUMNS) & set(archive.columns)
    assert set(DIFFICULTY_COLUMNS) <= set(live.columns)

    item = _item("4")
    assert "not computed" not in item
    assert "`aggregate_team_gameweek`" in item


# --- item 4: what the two-stage model reads ----------------------------------

CONTROL = ProductionProjectionConfig()


def _two_stage_features(home: list[int] | None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5, 6, 7, 8],
            CONTROL.minutes.appearance_rate_column: [0.5, 0.0, pd.NA, pd.NA, 0.8, 0.5, 0.5, 0.5],
            CONTROL.minutes.minutes_per_appearance_column: [
                80.0,
                pd.NA,
                pd.NA,
                pd.NA,
                80.0,
                200.0,
                80.0,
                80.0,
            ],
            CONTROL.rate_column: [9.0, pd.NA, pd.NA, pd.NA, 6.0, 6.0, 6.0, pd.NA],
            PRIOR_MINUTES_COLUMN: [pd.NA, pd.NA, 80.0, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA],
            PRIOR_RATE_COLUMN: [pd.NA, pd.NA, 6.0, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA],
            "fixture_count": [1, 1, 1, 1, 0, 1, 2, 1],
            "price_tenths": [80, 70, 60, 100, 90, 80, 80, 90],
        }
    )
    if home is not None:
        frame["home_fixture_count"] = home
    return frame


def _component_table(features: pd.DataFrame) -> pd.DataFrame:
    provenance = PredictionProvenance(
        model_name="squadopt-two-stage-control",
        model_version="control-v1",
        feature_contract_version="two-stage-appearance-calendar-v1",
        training_cutoff="2024-25:GW38",
        training_data_fingerprint="a" * 64,
    )
    return production_component_prediction(
        features, provenance, decision_timestamp_utc="2026-09-01T12:00:00Z", config=CONTROL
    ).table


def test_the_two_stage_model_reads_fixture_count_and_never_home_fixture_count() -> None:
    """Flipping or dropping the home count changes nothing; changing the fixture count does."""

    assert "home_fixture_count" not in CONTROL.required_columns
    home = [1, 0, 1, 0, 0, 1, 1, 0]
    counts = [1, 1, 1, 1, 0, 1, 2, 1]
    flipped = [count - at_home for count, at_home in zip(counts, home, strict=True)]
    reference = _two_stage_features(home)
    projected = production_projection(reference, config=CONTROL)
    table = _component_table(reference)

    for variant in (_two_stage_features(flipped), _two_stage_features(None)):
        other = production_projection(variant, config=CONTROL)
        for name in (
            "expected_points",
            "expected_minutes",
            "expected_points_per_90",
            "minutes_source",
            "rate_source",
            "points_source",
        ):
            assert_series_equal(getattr(other, name), getattr(projected, name))
        assert_frame_equal(_component_table(variant), table)

    # The contrast that keeps the test from passing vacuously.
    doubled = reference.assign(fixture_count=[2, 1, 1, 1, 0, 1, 2, 1])
    assert not production_projection(doubled, config=CONTROL).expected_points.equals(
        projected.expected_points
    )

    item = _item("4")
    assert re.search(r"`backtest/production\.py`[^.;]*reads only `fixture_count`", item), (
        "Item 4 must say the two-stage model in backtest/production.py reads only fixture_count."
    )


# --- item 7: who builds the panel once per worker process --------------------


def _calls(function: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _builds_the_panel(module: ast.Module, initializer: str) -> bool:
    """Whether a pool initializer builds the panel, following calls within its own module.

    A call into another module is not followed. The two initializers that do not build a
    panel today (`scripts/measure_member_window_proofs.py` and
    `scripts/probe_phase_e_runtime.py`) were read by hand: one projects from a handoff, the
    other copies a state dictionary.
    """

    functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
    pending: list[str] = [initializer]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        called = _calls(functions[name])
        if "build_panel" in called:
            return True
        pending.extend(called)
    return False


def _panel_building_pool_initializers() -> list[Path]:
    found: list[Path] = []
    sources = [*PACKAGE.rglob("*.py"), *(REPOSITORY_ROOT / "scripts").glob("*.py")]
    for path in sorted(sources):
        text = path.read_text(encoding="utf-8")
        if "initializer=" not in text:
            continue
        module = ast.parse(text)
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "initializer"
                    and isinstance(keyword.value, ast.Name)
                    and _builds_the_panel(module, keyword.value.id)
                ):
                    found.append(path)
    return found


def _as_cited(path: Path) -> str:
    """The house citation: relative to `src/squadopt/` for the package, else to the root."""

    if path.is_relative_to(PACKAGE):
        return path.relative_to(PACKAGE).as_posix()
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def test_every_pool_that_builds_the_panel_per_worker_is_named_in_item_7() -> None:
    found = [_as_cited(path) for path in _panel_building_pool_initializers()]
    # The scan must find the one this item has always named, or it is looking nowhere.
    assert "platform/publication_workers.py" in found

    item = _item("7")
    missing = [cited for cited in found if f"`{cited}`" not in item]
    assert not missing, f"Item 7 does not name these per-worker panel builders: {missing}."


def test_one_publication_worker_is_no_pool_so_the_parent_cleans_the_archive_once(
    tmp_path: Path,
) -> None:
    request = LeaguePublicationRequest(
        snapshot_root=tmp_path,
        snapshot_id="claims",
        archive_root=tmp_path,
        registry_path=tmp_path / "registry.json",
        out_dir=tmp_path / "site",
        league_id=1,
    )
    with league_mapper(request, workers=1) as mapper:
        assert mapper is map

    item = _item("7")
    assert re.search(r"N workers above one[^.]*N \+ 1 times", item), (
        "Item 7's N + 1 count must be stated for more than one worker only."
    )


def test_the_league_stage_duration_item_7_quotes_is_the_one_the_runbook_measured() -> None:
    runbook = _flat(RUNBOOK.read_text(encoding="utf-8"))
    measured = re.search(r"The league tree takes \*\*(about [a-z-]+ minutes)\*\*", runbook)
    assert measured is not None, "docs/weekly_runbook.md no longer states the league stage."

    assert measured.group(1) in _item("7")


# --- item 7: who builds the panel more than once in one run ------------------

SCRIPTS = REPOSITORY_ROOT / "scripts"
PANEL_BUILD = ("squadopt.data.sources.vaastav", "build_panel")
#: A loop or comprehension whose body builds the panel can build it more than once.
REPEATED = 2.0
#: The count of a path that has ended (a `return` or `raise`), so nothing after it runs.
ENDED = -math.inf

Function = ast.FunctionDef | ast.AsyncFunctionDef
Key = tuple[str, str]


def _module_name(path: Path) -> str:
    base = REPOSITORY_ROOT / "src" if path.is_relative_to(PACKAGE) else REPOSITORY_ROOT
    parts = path.relative_to(base).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


class _PanelBuilds:
    """How many panel builds one call of a function can reach, on its costliest path.

    Counted: every module-level function of the package and of `scripts/`, and every method
    of a module-level class there, keyed `Class.method`. A call is followed when it names
    one of those: a function defined in the same module, one imported by name (through
    re-exports), one reached through an imported module (`producer.build`), or a method of
    the caller's own class called through `self`. A branch counts its costlier side, a
    `return` or `raise` ends its path, and a loop or comprehension whose body builds the
    panel counts as more than once. Not followed: nested functions, an inherited method or
    one called through anything but `self`, a call through a dotted module path
    (`a.b.f()`), a function passed as an argument rather than called (`decide`'s
    `panel_builder`, the weekly run's stages, which a test below sums), and a pool's
    initializer, which the test above covers. A module found here can build the panel twice
    in one call; one not found may still do so only through one of those routes.
    """

    def __init__(self) -> None:
        sources = [*PACKAGE.rglob("*.py"), *SCRIPTS.glob("*.py")]
        self.paths = {_module_name(path): path for path in sources}
        self.functions: dict[str, dict[str, Function]] = {}
        self.imports: dict[str, dict[str, tuple[str, str | None]]] = {}
        for module, path in self.paths.items():
            self.add(module, path, ast.parse(path.read_text(encoding="utf-8")))
        self._counted: dict[Key, int] = {}
        self._open: set[Key] = set()
        #: The class of each method being counted, innermost last (None for a function).
        self._classes: list[str | None] = []

    def add(self, module: str, path: Path, tree: ast.Module) -> None:
        """Register one module's functions, its classes' methods and its imports."""

        self.functions[module] = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        self.functions[module].update(
            (f"{node.name}.{member.name}", member)
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            for member in node.body
            if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
        )
        self.imports[module] = self._imports(module, path, tree)

    def _imports(
        self, module: str, path: Path, tree: ast.Module
    ) -> dict[str, tuple[str, str | None]]:
        """Each imported name: a module (second item None) or a name inside one."""

        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        bound: dict[str, tuple[str, str | None]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname is not None:
                        bound[alias.asname] = (alias.name, None)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
                    base = ".".join([*anchor, base] if base else anchor)
                for alias in node.names:
                    full = f"{base}.{alias.name}"
                    bound[alias.asname or alias.name] = (
                        (full, None) if full in self.paths else (base, alias.name)
                    )
        return bound

    def _resolve(self, module: str, name: str, depth: int = 0) -> Key | None:
        if (module, name) == PANEL_BUILD or name in self.functions.get(module, {}):
            return (module, name)
        found = self.imports.get(module, {}).get(name)
        if found is None or found[1] is None or depth > 10:
            return None
        return self._resolve(found[0], found[1], depth + 1)

    def _callee(self, module: str, call: ast.Call) -> Key | None:
        if isinstance(call.func, ast.Name):
            return self._resolve(module, call.func.id)
        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
            within = self._classes[-1] if self._classes else None
            if call.func.value.id == "self" and within is not None:
                method = f"{within}.{call.func.attr}"
                return (module, method) if method in self.functions[module] else None
            found = self.imports.get(module, {}).get(call.func.value.id)
            if found is not None and found[1] is None:
                return self._resolve(found[0], call.func.attr)
        return None

    def count(self, key: Key) -> int:
        if key == PANEL_BUILD:
            return 1
        if key in self._counted:
            return self._counted[key]
        if key in self._open:
            return 0
        self._open.add(key)
        self._classes.append(key[1].rpartition(".")[0] or None)
        through, ended = self._block(key[0], self.functions[key[0]][key[1]].body)
        self._classes.pop()
        self._open.discard(key)
        self._counted[key] = int(max(through, ended, 0))
        return self._counted[key]

    def _block(self, module: str, statements: list[ast.stmt]) -> tuple[float, float]:
        """The costliest path that runs through the block, and the costliest that ends in it."""

        through, ended = 0.0, ENDED
        for statement in statements:
            passes, stops = self._statement(module, statement)
            ended = max(ended, through + stops)
            through += passes
        return through, ended

    def _statement(self, module: str, node: ast.stmt) -> tuple[float, float]:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return 0.0, ENDED
        if isinstance(node, ast.Return | ast.Raise):
            value = node.value if isinstance(node, ast.Return) else node.exc
            return ENDED, (self._expression(module, value) if value is not None else 0.0)
        if isinstance(node, ast.If):
            test = self._expression(module, node.test)
            body, orelse = self._block(module, node.body), self._block(module, node.orelse)
            return test + max(body[0], orelse[0]), test + max(body[1], orelse[1])
        if isinstance(node, ast.For | ast.AsyncFor | ast.While):
            head = self._expression(module, node.test if isinstance(node, ast.While) else node.iter)
            body, orelse = self._block(module, node.body), self._block(module, node.orelse)
            repeated = REPEATED if max(*body, *orelse) > 0 else 0.0
            can_end = max(body[1], orelse[1]) > ENDED
            return head + repeated, (head + repeated if can_end else ENDED)
        if isinstance(node, ast.Try | ast.TryStar):
            body, orelse = self._block(module, node.body), self._block(module, node.orelse)
            final = self._block(module, node.finalbody)[0]
            handlers = [self._block(module, handler.body) for handler in node.handlers]
            through = max([body[0] + orelse[0], *(body[0] + h[0] for h in handlers)])
            ended = max([body[1], body[0] + orelse[1], *(body[0] + h[1] for h in handlers)])
            return through + final, ended + final
        if isinstance(node, ast.With | ast.AsyncWith):
            head = sum(self._expression(module, item.context_expr) for item in node.items)
            body = self._block(module, node.body)
            return head + body[0], head + body[1]
        if isinstance(node, ast.Match):
            subject = self._expression(module, node.subject)
            cases = [self._block(module, case.body) for case in node.cases]
            through = max([0.0, *(case[0] for case in cases)])
            return subject + through, subject + max([ENDED, *(case[1] for case in cases)])
        cost = 0.0
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                cost += self._expression(module, child)
        return cost, ENDED

    def _expression(self, module: str, node: ast.expr) -> float:
        if isinstance(node, ast.IfExp):
            branches = (self._expression(module, node.body), self._expression(module, node.orelse))
            return self._expression(module, node.test) + max(branches)
        if isinstance(node, ast.Lambda):
            return 0.0
        cost = 0.0
        if isinstance(node, ast.Call):
            key = self._callee(module, node)
            if key is not None:
                cost += self.count(key)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                cost += self._expression(module, child)
            elif isinstance(child, ast.keyword):
                cost += self._expression(module, child.value)
            elif isinstance(child, ast.comprehension):
                cost += sum(self._expression(module, part) for part in (child.iter, *child.ifs))
        comprehension = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
        if isinstance(node, comprehension) and cost > 0:
            return max(cost, REPEATED)
        return cost


def test_every_caller_that_can_build_the_panel_twice_in_one_run_is_named_in_item_7() -> None:
    """Item 7 once said every caller loads the panel once at the top of a run; not so.

    A module is found when one of its module-level functions, or a method of one of its
    module-level classes, can reach two panel builds in one call. Item 7 must cite each one,
    in the house form `_as_cited` gives. A new script that builds the panel twice fails here
    until item 7 names it.
    """

    builds = _PanelBuilds()
    found = sorted(
        _as_cited(builds.paths[module])
        for module, functions in builds.functions.items()
        if any(builds.count((module, name)) > 1 for name in functions)
    )
    # The scan must find the callers this item names, each by a different rule (a call into
    # another module, a call within the module, a build inside a loop, a method), or it is
    # looking nowhere. The last line follows a module alias and a re-export
    # (`producer._component_table` in `scripts/_phase_e_live.py`), so a resolver that stopped
    # following either fails here.
    assert {
        "application/projection_handoff.py",
        "platform/weekly_operations.py",
        "scripts/build_projection_handoff.py",
        "scripts/measure_participation_composition.py",
        "scripts/probe_phase_e_runtime.py",
    } <= set(found)
    assert builds.count(("scripts._phase_e_live", "live_component_decision")) == 1

    item = _item("7")
    missing = [cited for cited in found if f"`{cited}`" not in item]
    assert not missing, f"Item 7 does not name these callers that build the panel twice: {missing}."


def test_the_weekly_run_builds_the_panel_in_the_stages_item_7_names() -> None:
    """The weekly run's stages run one after another in one process, so their builds add up.

    `WeeklyOperations.execute` hands each stage method to its journal as `operation=`, which
    the scan above does not follow, so this sums the stages it hands over. The count is per
    stage method on its costliest path: the league stage's workers are the pool test's, and
    `decide`'s opening-gameweek build is reached through its `panel_builder`, which the
    decide stage never takes (it always passes the handoff).
    """

    builds = _PanelBuilds()
    module = "squadopt.platform.weekly_operations"
    execute = builds.functions[module]["WeeklyOperations.execute"]
    stages = [
        keyword.value.attr
        for node in ast.walk(execute)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "operation"
        and isinstance(keyword.value, ast.Attribute)
        and isinstance(keyword.value.value, ast.Name)
        and keyword.value.value.id == "self"
    ]
    # Every stage the runbook lists, or the sum below is looking at part of the run.
    assert {"_capture", "_handoff", "_decide", "_league", "_site", "_publish"} <= set(stages)

    building = {
        stage: count
        for stage in stages
        if (count := builds.count((module, f"WeeklyOperations.{stage}"))) > 0
    }
    assert building == {"_capture": 1, "_handoff": 2, "_league": 1}
    assert sum(building.values()) == 4

    item = _item("7")
    for phrase in (
        "(`platform/weekly_operations.py`) builds it up to four times in its own process",
        "once in the capture stage",
        "twice in the handoff stage",
        "once in the league stage's parent",
        "No other stage builds one",
    ):
        assert phrase in item, f"Item 7 must say how the weekly run builds the panel: {phrase!r}."


def test_the_scan_counts_a_method_and_follows_self_within_its_class() -> None:
    """The two rules the weekly run needs, on a module small enough to count by hand."""

    builds = _PanelBuilds()
    source = """
from squadopt.data.sources.vaastav import build_panel


class Run:
    def one(self, root):
        return build_panel(root)

    def both(self, root):
        self.one(root)
        return self.one(root)


class Other:
    def through_another_instance(self, run, root):
        return run.one(root) + run.one(root)


def outside(run, root):
    run.one(root)
    return run.one(root)
"""
    builds.add("claims_synthetic", Path("claims_synthetic.py"), ast.parse(source))

    assert builds.count(("claims_synthetic", "Run.one")) == 1
    assert builds.count(("claims_synthetic", "Run.both")) == 2
    # Only `self` within the method's own class is followed, as the docstring says.
    assert builds.count(("claims_synthetic", "Other.through_another_instance")) == 0
    assert builds.count(("claims_synthetic", "outside")) == 0
