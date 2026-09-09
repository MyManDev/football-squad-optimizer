"""Tests for the Phase C v2 development scope of the out-of-fold export.

The v1 path must be untouched by the new parameters, the v2 path must name its contract
and its arm on every row and fold record, the per-fold weights must follow the declared
rule, and the refusals must fire before any archive is read.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scripts.compare_component_oof_development import main as compare_main
from scripts.export_component_oof import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    DEVELOPMENT_SEASONS_V2,
    OOF_COLUMNS,
    OOF_CONTRACT_VERSION,
    build_oof_table,
    main,
)

from squadopt.backtest.splits import DecisionPoint
from squadopt.data.errors import DataError
from squadopt.evaluation import DEVELOPMENT_OOF_CONTRACT_VERSION as READER_DEVELOPMENT_CONTRACT
from squadopt.evaluation import EvaluationValidationError, read_phase_c_component_handoff
from squadopt.features.component_targets import build_component_targets
from squadopt.prediction.component_dataset import (
    COMPONENT_DEVELOPMENT_SEASONS_V2,
    COMPONENT_TRAINING_SEASONS,
    build_component_frame,
    component_feature_columns,
)
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    EQUAL_WEIGHTING,
    SEASON_HALF_LIFE_WEIGHTING,
    SEASON_WEIGHTED_MODEL_VERSION,
    ComponentModelConfig,
)

FEATURES = component_feature_columns()
SMALL = ComponentModelConfig(minimum_training_rows=10)
OLD = "2023-24"
NEW = "2024-25"
LOCKED = "2025-26"
ORDER = (OLD, NEW)
THREE = (OLD, NEW, LOCKED)
# The v1 manifest schema, pinned: the v2 scope must not add a key to it.
V1_MANIFEST_KEYS = (
    "archive_commit",
    "chronology_check",
    "component_model_rows",
    "contract_version",
    "dataset_contract_version",
    "decision_timestamp_policy",
    "deterministic_seed",
    "development_seasons",
    "direct_control_rows",
    "excluded_ratio_features",
    "feature_columns",
    "feature_contract_version",
    "fold_count",
    "fold_ids",
    "folds",
    "folds_refused_for_thin_history",
    "generated_at_utc",
    "locked_holdout_read",
    "locked_holdout_season",
    "missing_data_policy",
    "model_version",
    "negative_raw_conditional_points",
    "promotes_anything",
    "public_points_bound",
    "public_points_bound_note",
    "repository_commit",
    "reproduce",
    "roster_column_dtypes",
    "roster_columns",
    "roster_contract_version",
    "roster_file",
    "roster_ownership_policy",
    "roster_row_count",
    "roster_sha256",
    "row_count",
    "scored_fold_count",
    "start_target_status",
    "start_target_supported_seasons",
    "table_column_dtypes",
    "table_columns",
    "table_file",
    "table_sha256",
    "target_contract_version",
    "training_rows_seen",
    "working_tree_dirty",
)
V2_MANIFEST_KEYS = (
    *V1_MANIFEST_KEYS,
    "development_note",
    "development_only",
    "development_scope",
    "rule_era",
    "weighting",
)
DEFENSIVE_ACTION_COLUMNS = (
    "defensive_contribution",
    "clearances_blocks_interceptions",
    "recoveries",
    "tackles",
)


def _panel(season: str, gameweeks: int, players: int) -> pd.DataFrame:
    rows = []
    for gameweek in range(1, gameweeks + 1):
        for player in range(1, players + 1):
            plays = (player + gameweek) % 5 != 0
            rows.append(
                (season, gameweek, player, 90 if plays else 0, 3 + player % 4 if plays else 0)
            )
    raw = pd.DataFrame(rows, columns=["season", "gameweek", "player_id", "minutes", "total_points"])
    return pd.DataFrame(
        {
            "season": raw["season"].astype("string"),
            "gameweek": raw["gameweek"].astype("int64"),
            "player_id": raw["player_id"].astype("int64"),
            "name": ("P" + raw["player_id"].astype(str)).astype("string"),
            "team_id": pd.Series(1, index=raw.index, dtype="int64"),
            "position": pd.Series("MID", index=raw.index, dtype="string"),
            "price_tenths": (40 + raw["player_id"]).astype("int64"),
            "minutes": raw["minutes"].astype("int64"),
            "total_points": raw["total_points"].astype("int64"),
        }
    )


def _panels(gameweeks: int, players: int, seasons: Sequence[str] = ORDER) -> pd.DataFrame:
    return pd.concat([_panel(season, gameweeks, players) for season in seasons], ignore_index=True)


def _frame(gameweeks: int, players: int, seasons: Sequence[str] = ORDER) -> pd.DataFrame:
    panel = _panels(gameweeks, players, seasons)
    features = panel.loc[:, ["season", "gameweek", "player_id", "price_tenths"]].copy(deep=True)
    for offset, column in enumerate(FEATURES, start=1):
        if column == "price_tenths":
            continue
        if column == "fixture_count":
            features[column] = (1 + (panel["player_id"] % 4 == 0)).astype("int64")
        elif column == "home_fixture_count":
            features[column] = (panel["player_id"] % 2).astype("int64")
        else:
            features[column] = (panel["player_id"] % 7 * offset + panel["gameweek"]).astype(
                "float64"
            )
    return build_component_frame(features, build_component_targets(panel))


def _decisions(gameweeks: range, seasons: Sequence[str] = ORDER) -> tuple[DecisionPoint, ...]:
    return tuple(
        DecisionPoint(season=season, gameweek=gameweek)
        for season in seasons
        for gameweek in gameweeks
    )


def test_the_v1_walk_is_unchanged_by_the_new_parameters() -> None:
    frame = _frame(6, 12)
    decisions = _decisions(range(3, 7))

    implicit, implicit_walk = build_oof_table(frame, decisions, season_order=ORDER, config=SMALL)
    explicit, explicit_walk = build_oof_table(
        frame,
        decisions,
        season_order=ORDER,
        config=SMALL,
        weighting="equal",
        contract_version=OOF_CONTRACT_VERSION,
    )

    assert_frame_equal(implicit, explicit)
    assert list(implicit.columns) == list(OOF_COLUMNS)
    assert set(implicit["contract_version"]) == {OOF_CONTRACT_VERSION}
    assert set(implicit["model_version"]) == {COMPONENT_MODEL_VERSION}
    for record in (*implicit_walk.folds, *explicit_walk.folds):
        assert record.weighting is None
        assert "weighting" not in record.as_record()
        assert "training_weight_by_season" not in record.as_record()


def test_the_v1_contract_refuses_the_weighted_candidate() -> None:
    frame = _frame(6, 12)

    with pytest.raises(DataError, match="v2 development candidate"):
        build_oof_table(
            frame,
            _decisions(range(3, 5)),
            season_order=ORDER,
            config=SMALL,
            weighting="season_half_life",
        )


@pytest.mark.parametrize(
    ("weighting", "model_version", "label"),
    [
        ("equal", COMPONENT_MODEL_VERSION, EQUAL_WEIGHTING),
        ("season_half_life", SEASON_WEIGHTED_MODEL_VERSION, SEASON_HALF_LIFE_WEIGHTING),
    ],
)
def test_a_v2_table_names_its_contract_and_its_arm_on_every_row_and_record(
    weighting: str, model_version: str, label: str
) -> None:
    table, walk = build_oof_table(
        _frame(6, 12),
        _decisions(range(3, 7)),
        season_order=ORDER,
        config=SMALL,
        weighting=weighting,
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )

    assert list(table.columns) == list(OOF_COLUMNS)
    assert set(table["contract_version"]) == {DEVELOPMENT_OOF_CONTRACT_VERSION}
    assert set(table["model_version"]) == {model_version}
    assert walk.folds
    for record in walk.folds:
        document = record.as_record()
        assert record.model_version == model_version
        assert document["weighting"] == label
        assert isinstance(document["training_weight_by_season"], dict)


def test_v2_fold_weights_follow_the_declared_rule_for_every_fold() -> None:
    _, walk = build_oof_table(
        _frame(6, 12),
        _decisions(range(3, 7)),
        season_order=ORDER,
        config=SMALL,
        weighting="season_half_life",
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )
    _, equal_walk = build_oof_table(
        _frame(6, 12),
        _decisions(range(3, 7)),
        season_order=ORDER,
        config=SMALL,
        weighting="equal",
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )

    for record in walk.folds:
        expected = {OLD: 1.0} if record.season == OLD else {OLD: 0.5, NEW: 1.0}
        assert record.training_weight_by_season == expected
    for record in equal_walk.folds:
        expected = {OLD: 1.0} if record.season == OLD else {OLD: 1.0, NEW: 1.0}
        assert record.training_weight_by_season == expected


def test_the_v2_equal_arm_reproduces_the_v1_predictions_row_for_row() -> None:
    frame = _frame(6, 12)
    decisions = _decisions(range(3, 7))

    v1, _ = build_oof_table(frame, decisions, season_order=ORDER, config=SMALL)
    v2, _ = build_oof_table(
        frame,
        decisions,
        season_order=ORDER,
        config=SMALL,
        weighting="equal",
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )

    assert_frame_equal(v1.drop(columns=["contract_version"]), v2.drop(columns=["contract_version"]))


def test_the_weighted_arm_differs_only_where_an_older_season_enters_training() -> None:
    frame = _frame(6, 12)
    decisions = _decisions(range(3, 7))
    columns = [
        "appearance_probability",
        "expected_minutes_if_appearance",
        "control_expected_points",
    ]

    equal, _ = build_oof_table(
        frame,
        decisions,
        season_order=ORDER,
        config=SMALL,
        weighting="equal",
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )
    weighted, _ = build_oof_table(
        frame,
        decisions,
        season_order=ORDER,
        config=SMALL,
        weighting="season_half_life",
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )

    # Every 2023-24 fold trains on 2023-24 rows only, which all weigh 1 under the rule.
    first = equal["season"].eq(OLD)
    assert_frame_equal(
        equal.loc[first, columns].astype("float64").reset_index(drop=True),
        weighted.loc[first, columns].astype("float64").reset_index(drop=True),
        check_exact=False,
        atol=1e-8,
    )
    # A 2024-25 fold trains on both seasons, and the older one now weighs half.
    second = equal["season"].eq(NEW)
    assert (
        not equal.loc[second, columns]
        .astype("float64")
        .equals(weighted.loc[second, columns].astype("float64"))
    )
    # The arms score the same rows with the same targets; only the predictions move.
    shared = [
        "season",
        "target_gameweek",
        "player_id",
        "fixture_count",
        "appearance_target",
        "points_target",
        "composition_route",
    ]
    assert_frame_equal(equal.loc[:, shared], weighted.loc[:, shared])


def test_main_refuses_the_weighted_candidate_under_the_v1_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--season-weighting",
            "season_half_life",
            "--archive-root",
            "does-not-exist",
        ],
    )

    assert main() == 1
    assert "--development-scope v2" in capsys.readouterr().out


def test_main_refuses_a_season_outside_the_v2_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--development-scope",
            "v2",
            "--seasons",
            "2020-21,2025-26",
            "--archive-root",
            "does-not-exist",
        ],
    )

    assert main() == 1
    assert "2020-21" in capsys.readouterr().out


def test_the_v2_scope_admits_the_locked_season_up_to_the_archive_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under v2 the holdout refusal does not fire; the next precondition is the archive."""

    monkeypatch.setattr("scripts.export_component_oof._git_revision", lambda: ("0" * 40, False))
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--development-scope",
            "v2",
            "--season-weighting",
            "season_half_life",
            "--archive-root",
            "does-not-exist",
        ],
    )

    assert main() == 1
    output = capsys.readouterr().out
    assert "Archive not found" in output
    assert "locked holdout" not in output


def test_the_v2_scope_is_the_v1_scope_plus_the_development_season() -> None:
    assert DEVELOPMENT_SEASONS_V2 == COMPONENT_DEVELOPMENT_SEASONS_V2
    assert (*COMPONENT_TRAINING_SEASONS, "2025-26") == DEVELOPMENT_SEASONS_V2


def test_the_export_and_the_reader_agree_on_the_development_contract() -> None:
    assert DEVELOPMENT_OOF_CONTRACT_VERSION == READER_DEVELOPMENT_CONTRACT
    assert DEVELOPMENT_OOF_CONTRACT_VERSION != OOF_CONTRACT_VERSION


def test_no_defensive_action_column_is_a_feature_and_the_target_adds_nothing() -> None:
    """The new scoring era enters only through the official total, never twice or as zero."""

    assert not set(DEFENSIVE_ACTION_COLUMNS) & set(FEATURES)

    panel = _panel("2025-26", 3, 8)
    with_actions = panel.assign(defensive_contribution=pd.Series(12, index=panel.index))
    targets = build_component_targets(with_actions)

    assert not set(DEFENSIVE_ACTION_COLUMNS) & set(targets.columns)
    appeared = panel["minutes"].gt(0)
    joined = panel.merge(targets, on=["season", "gameweek", "player_id"], validate="one_to_one")
    assert (
        joined.loc[appeared, "points_target"].astype("int64").tolist()
        == joined.loc[appeared, "total_points"].tolist()
    )
    assert joined.loc[~appeared, "points_target"].isna().all()


def test_a_three_season_v2_walk_weights_every_fold_from_its_own_season() -> None:
    """The 2025-26 folds see 0.25 / 0.5 / 1, and every training fold ranks before the fold."""

    _, walk = build_oof_table(
        _frame(6, 12, THREE),
        _decisions(range(3, 7), THREE),
        season_order=THREE,
        config=SMALL,
        weighting="season_half_life",
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )
    expected = {
        OLD: {OLD: 1.0},
        NEW: {OLD: 0.5, NEW: 1.0},
        LOCKED: {OLD: 0.25, NEW: 0.5, LOCKED: 1.0},
    }
    ranks = {season: rank for rank, season in enumerate(THREE)}

    assert {record.season for record in walk.folds} == set(THREE)
    for record in walk.folds:
        assert record.training_weight_by_season == expected[record.season]
        decision = (ranks[record.season], record.target_gameweek)
        assert record.training_fold_ids
        assert all(
            (ranks[fold[:7]], int(fold[-2:])) < decision for fold in record.training_fold_ids
        )


def _run_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *arguments: str
) -> tuple[Path, Path, Path]:
    """Run ``main`` end to end on a synthetic three-season frame, returning the artifacts."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    panel = _panels(6, 12, THREE)
    frame = _frame(6, 12, THREE)
    monkeypatch.setattr(
        "scripts.export_component_oof._modelling_frame",
        lambda archive_root, seasons: (panel, frame),
    )
    monkeypatch.setattr(
        "scripts.export_component_oof.season_ranks",
        lambda panel: {season: rank for rank, season in enumerate(THREE)},
    )
    monkeypatch.setattr(
        "scripts.export_component_oof.walk_forward_decision_points",
        lambda panel, *, seasons: _decisions(range(3, 7), tuple(seasons)),
    )
    monkeypatch.setattr("scripts.export_component_oof._git_revision", lambda: ("0" * 40, False))
    output = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--archive-root",
            str(tmp_path),
            "--output-dir",
            str(output),
            "--minimum-training-rows",
            "10",
            *arguments,
        ],
    )
    assert main() == 0
    written = sorted(output.glob("*.manifest.json"))
    assert len(written) == 1
    manifest = written[0]
    name = manifest.name[: -len(".manifest.json")]
    return output / f"{name}.csv", output / f"{name}.roster.csv", manifest


def test_main_writes_v2_artifacts_the_development_reader_and_the_comparison_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seasons = ",".join(THREE)
    equal = _run_export(
        tmp_path / "equal",
        monkeypatch,
        "--development-scope",
        "v2",
        "--season-weighting",
        "equal",
        "--seasons",
        seasons,
    )
    weighted = _run_export(
        tmp_path / "weighted",
        monkeypatch,
        "--development-scope",
        "v2",
        "--season-weighting",
        "season_half_life",
        "--seasons",
        seasons,
    )

    for paths, label, model_version in (
        (equal, EQUAL_WEIGHTING, COMPONENT_MODEL_VERSION),
        (weighted, SEASON_HALF_LIFE_WEIGHTING, SEASON_WEIGHTED_MODEL_VERSION),
    ):
        table_path, _, manifest_path = paths
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert sorted(manifest) == sorted(V2_MANIFEST_KEYS)
        assert manifest["development_only"] is True
        assert manifest["locked_holdout_read"] is True
        assert manifest["weighting"]["label"] == label
        assert manifest["weighting"]["model_version"] == model_version
        assert manifest["rule_era"]["defensive_contribution_seasons"] == [LOCKED]
        assert all("training_weight_by_season" in record for record in manifest["folds"])
        assert table_path.name.endswith(
            f"_{'equal' if label == EQUAL_WEIGHTING else 'season_half_life'}.csv"
        )

        handoff = read_phase_c_component_handoff(
            *paths, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
        )
        assert handoff.weighting == label
        assert handoff.model_version == model_version
        assert set(handoff.rows["season"]) == set(THREE)
        with pytest.raises(EvaluationValidationError):
            read_phase_c_component_handoff(*paths)

    # The comparison reads exactly what the export wrote; both live in one directory.
    artifact_dir = tmp_path / "pair"
    artifact_dir.mkdir()
    for paths in (equal, weighted):
        for path in paths:
            (artifact_dir / path.name).write_bytes(path.read_bytes())
    assert compare_main(["--artifact-dir", str(artifact_dir)]) == 0
    report = json.loads(
        (artifact_dir / "comparison" / "comparison.json").read_text(encoding="utf-8")
    )
    assert report["primary_season"]["season"] == LOCKED
    assert report["control_era_season"]["season"] == NEW
    assert report["verdict"]["verdict"] in {"candidate_preferred", "no_selection"}


def test_main_under_the_v1_scope_writes_the_pinned_manifest_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _run_export(tmp_path, monkeypatch, "--seasons", f"{OLD},{NEW}")
    table_path, _, manifest_path = paths
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert table_path.name == f"{OOF_CONTRACT_VERSION}.csv"
    assert sorted(manifest) == sorted(V1_MANIFEST_KEYS)
    assert manifest["contract_version"] == OOF_CONTRACT_VERSION
    assert manifest["model_version"] == COMPONENT_MODEL_VERSION
    assert manifest["locked_holdout_read"] is False
    assert (
        "then python -m scripts.export_component_oof, at the repository_commit"
        in (manifest["reproduce"])
    )
    assert all("weighting" not in record for record in manifest["folds"])
    assert read_phase_c_component_handoff(*paths).development_contract is None
