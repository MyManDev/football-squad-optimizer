"""What `docs/data_followups.md` says about the code is what the code does.

The file is a list of deferred data work, and its sentences about which module reads which
column, or how often the panel is built, are prose constants: nothing re-derives them, so a
wrong one survives every other check. Three did. The difficulty summaries were said not to be
computed on the development folds, the two-stage model was said to read both fixture counts,
and the member-publication workers were said to be the one caller that builds the panel once
per worker process. Each test below pins the code fact and the sentence that states it, so the
next change to either one fails here instead of misleading a reader.
"""

from __future__ import annotations

import ast
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
