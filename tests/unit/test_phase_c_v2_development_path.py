"""Tests for the explicit Phase C v2 development allowances and the arm comparison.

The scorer and the handoff reader keep refusing the locked 2025-26 season by default; a
caller has to name the v2 development contract to read it, and a v2 artifact has to say
what it is. The comparison script then applies the acceptance rule that was written before
the measurement, on synthetic arms whose answer is known.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd
import pytest
from scripts.compare_component_oof_development import (
    ACCEPTANCE_RULE,
    check_paired,
    decide,
    fold_points_mae,
    load_arm,
    main,
)

from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    OOF_ARTIFACT_COLUMNS,
    OOF_CONTRACT_VERSION,
    ROSTER_ARTIFACT_COLUMNS,
    EvaluationValidationError,
    evaluate_component_oof,
    read_phase_c_component_handoff,
)
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    EQUAL_WEIGHTING,
    SEASON_HALF_LIFE_WEIGHTING,
    SEASON_WEIGHTED_MODEL_VERSION,
)

LOCKED = "2025-26"
PREVIOUS = "2024-25"
COMMIT = "b" * 40
ErrorRule = Callable[[str, int, int], float]


def _table(
    *,
    seasons: Sequence[str],
    gameweeks: range,
    players: int,
    model_version: str,
    contract_version: str,
    error: ErrorRule,
) -> pd.DataFrame:
    """One arm's OOF rows: every player appears, and the prediction misses by ``error``."""

    rows = []
    for season in seasons:
        for gameweek in gameweeks:
            for player in range(1, players + 1):
                points = float(2 + (player + gameweek) % 5)
                predicted = points + error(season, gameweek, player)
                rows.append(
                    {
                        "season": season,
                        "target_gameweek": gameweek,
                        "fold_id": f"{season}-gw{gameweek:02d}",
                        "player_id": 100 + player,
                        "points_target": points,
                        "raw": predicted,
                    }
                )
    raw = pd.DataFrame(rows)
    count = len(raw)

    def text(value: str) -> pd.Series:
        return pd.Series([value] * count, dtype="string")

    return pd.DataFrame(
        {
            "contract_version": text(contract_version),
            "model_version": text(model_version),
            "feature_contract_version": text("phase_c_component_form_window_v1"),
            "target_contract_version": text("phase_c_component_targets_v1"),
            "dataset_contract_version": text("phase_c_component_dataset_v1"),
            "season": raw["season"].astype("string"),
            "target_gameweek": raw["target_gameweek"].astype("int64"),
            "decision_timestamp_utc": pd.Series([pd.NA] * count, dtype="string"),
            "fold_id": raw["fold_id"].astype("string"),
            "player_id": raw["player_id"].astype("int64"),
            "fixture_count": pd.Series([1] * count, dtype="int64"),
            "appearance_target": pd.Series([1] * count, dtype="int64"),
            "start_target": pd.Series([pd.NA] * count, dtype="Int64"),
            "minutes_target": pd.Series([90] * count, dtype="Int64"),
            "points_target": raw["points_target"].astype("Float64"),
            "appearance_probability": pd.Series([1.0] * count, dtype="Float64"),
            "q_start_given_appearance": pd.Series([pd.NA] * count, dtype="Float64"),
            "start_probability": pd.Series([pd.NA] * count, dtype="Float64"),
            "expected_minutes_if_appearance": pd.Series([80.0] * count, dtype="Float64"),
            "raw_expected_points_if_appearance": raw["raw"].astype("Float64"),
            "expected_points_if_appearance": raw["raw"].astype("Float64"),
            "control_expected_points": raw["raw"].astype("Float64"),
            "composition_route": text("component_model"),
            "evidence_status": text("not_requested"),
        }
    ).loc[:, list(OOF_ARTIFACT_COLUMNS)]


def _write_arm(
    directory: Path,
    name: str,
    table: pd.DataFrame,
    *,
    seasons: Sequence[str],
    weighting_label: str | None,
    development: bool = True,
    commit: str = COMMIT,
    edit: Callable[[dict[str, object]], None] | None = None,
) -> tuple[Path, Path, Path]:
    """Write one arm's table, roster and manifest the way the v2 export does."""

    directory.mkdir(parents=True, exist_ok=True)
    roster = pd.DataFrame(
        {
            "contract_version": pd.Series(
                ["phase_c_decision_roster_v1"] * len(table), dtype="string"
            ),
            "season": table["season"],
            "target_gameweek": table["target_gameweek"],
            "fold_id": table["fold_id"],
            "player_id": table["player_id"],
            "name": ("P" + table["player_id"].astype(str)).astype("string"),
            "team_id": pd.Series(["T01"] * len(table), dtype="string"),
            "position": pd.Series(["MID"] * len(table), dtype="string"),
            "price_tenths": pd.Series([65] * len(table), dtype="int64"),
        }
    ).loc[:, list(ROSTER_ARTIFACT_COLUMNS)]
    table_path = directory / f"{name}.csv"
    roster_path = directory / f"{name}.roster.csv"
    manifest_path = directory / f"{name}.manifest.json"
    table.to_csv(table_path, index=False, lineterminator="\n")
    roster.to_csv(roster_path, index=False, lineterminator="\n")
    model_version = str(table["model_version"].iloc[0])
    fold_ids = table["fold_id"].drop_duplicates().tolist()
    folds = []
    for fold_id in fold_ids:
        season, gameweek = fold_id[:7], int(fold_id[-2:])
        folds.append(
            {
                "fold_id": fold_id,
                "season": season,
                "target_gameweek": gameweek,
                "decision_timestamp_utc": None,
                "training_cutoff_utc": None,
                "training_cutoff_fold_id": f"{season}-gw01",
                "training_fold_ids": [f"{season}-gw01"],
                "training_key_digest": "a" * 64,
                "training_rows": 100,
                "scored_rows": int(table["fold_id"].eq(fold_id).sum()),
                "model_fitted": True,
                "model_version": model_version,
                "feature_contract_version": "phase_c_component_form_window_v1",
                "target_contract_version": "phase_c_component_targets_v1",
            }
        )
    manifest: dict[str, object] = {
        "contract_version": str(table["contract_version"].iloc[0]),
        "model_version": model_version,
        "feature_contract_version": "phase_c_component_form_window_v1",
        "target_contract_version": "phase_c_component_targets_v1",
        "dataset_contract_version": "phase_c_component_dataset_v1",
        "roster_contract_version": "phase_c_decision_roster_v1",
        "development_seasons": list(seasons),
        "fold_ids": fold_ids,
        "fold_count": len(fold_ids),
        "scored_fold_count": len(fold_ids),
        "folds": folds,
        "repository_commit": commit,
        "working_tree_dirty": False,
        "table_file": table_path.name,
        "table_sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
        "table_columns": list(table.columns),
        "table_column_dtypes": {str(column): str(dtype) for column, dtype in table.dtypes.items()},
        "row_count": len(table),
        "roster_file": roster_path.name,
        "roster_sha256": hashlib.sha256(roster_path.read_bytes()).hexdigest(),
        "roster_columns": list(roster.columns),
        "roster_column_dtypes": {
            str(column): str(dtype) for column, dtype in roster.dtypes.items()
        },
        "roster_row_count": len(roster),
        "locked_holdout_read": LOCKED in seasons,
        "locked_holdout_season": LOCKED,
    }
    if development:
        manifest["development_only"] = True
        manifest["weighting"] = {"label": weighting_label, "model_version": model_version}
    if edit is not None:
        edit(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    return table_path, roster_path, manifest_path


def _development_table(
    error: ErrorRule,
    *,
    model_version: str = COMPONENT_MODEL_VERSION,
    gameweeks: range = range(2, 8),
) -> pd.DataFrame:
    return _table(
        seasons=(PREVIOUS, LOCKED),
        gameweeks=gameweeks,
        players=6,
        model_version=model_version,
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
        error=error,
    )


def _oof_rows(season: str) -> pd.DataFrame:
    table = _table(
        seasons=(season,),
        gameweeks=range(2, 4),
        players=3,
        model_version=COMPONENT_MODEL_VERSION,
        contract_version=OOF_CONTRACT_VERSION,
        error=lambda *_: 1.0,
    )
    return table.assign(position=pd.Series(["MID"] * len(table), dtype="string"))


# --- scorer -----------------------------------------------------------------------------


def test_the_scorer_still_refuses_the_locked_season_by_default() -> None:
    with pytest.raises(EvaluationValidationError, match="locked 2025-26"):
        evaluate_component_oof(_oof_rows(LOCKED))


def test_the_scorer_accepts_the_locked_season_only_when_declared_development_data() -> None:
    result = evaluate_component_oof(_oof_rows(LOCKED), development_seasons=(LOCKED,))

    assert result.overall.population_rows == 6
    assert set(result.by_season) == {LOCKED}


def test_the_scorer_treats_the_previous_season_as_before() -> None:
    assert evaluate_component_oof(_oof_rows(PREVIOUS)).overall.population_rows == 6
    assert (
        evaluate_component_oof(
            _oof_rows(PREVIOUS), development_seasons=(LOCKED,)
        ).overall.population_rows
        == 6
    )


@pytest.mark.parametrize("declared", [(PREVIOUS,), ("2026-27",), LOCKED, (1,)])
def test_only_a_locked_season_can_be_declared_and_only_as_a_collection(declared: object) -> None:
    with pytest.raises(EvaluationValidationError, match="development_seasons"):
        evaluate_component_oof(_oof_rows(LOCKED), development_seasons=declared)  # type: ignore[arg-type]


# --- handoff reader ---------------------------------------------------------------------


def test_the_development_reader_accepts_a_declared_v2_artifact_with_the_locked_season(
    tmp_path: Path,
) -> None:
    paths = _write_arm(
        tmp_path,
        "candidate",
        _development_table(lambda *_: 1.0, model_version=SEASON_WEIGHTED_MODEL_VERSION),
        seasons=(PREVIOUS, LOCKED),
        weighting_label=SEASON_HALF_LIFE_WEIGHTING,
    )

    handoff = read_phase_c_component_handoff(
        *paths, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
    )

    assert handoff.development_contract == DEVELOPMENT_OOF_CONTRACT_VERSION
    assert handoff.weighting == SEASON_HALF_LIFE_WEIGHTING
    assert handoff.model_version == SEASON_WEIGHTED_MODEL_VERSION
    assert set(handoff.rows["season"]) == {PREVIOUS, LOCKED}
    assert "position" in handoff.rows.columns


def test_the_default_reader_refuses_a_v2_artifact(tmp_path: Path) -> None:
    paths = _write_arm(
        tmp_path,
        "control",
        _development_table(lambda *_: 1.0),
        seasons=(PREVIOUS, LOCKED),
        weighting_label=EQUAL_WEIGHTING,
    )

    with pytest.raises(EvaluationValidationError, match="contract version"):
        read_phase_c_component_handoff(*paths)


def test_the_development_reader_refuses_a_v1_artifact(tmp_path: Path) -> None:
    table = _table(
        seasons=(PREVIOUS,),
        gameweeks=range(2, 4),
        players=3,
        model_version=COMPONENT_MODEL_VERSION,
        contract_version=OOF_CONTRACT_VERSION,
        error=lambda *_: 1.0,
    )
    paths = _write_arm(
        tmp_path, "v1", table, seasons=(PREVIOUS,), weighting_label=None, development=False
    )

    assert read_phase_c_component_handoff(*paths).development_contract is None
    with pytest.raises(EvaluationValidationError, match=r"missing fields|contract version"):
        read_phase_c_component_handoff(
            *paths, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
        )


def test_an_unknown_development_contract_is_refused(tmp_path: Path) -> None:
    paths = _write_arm(
        tmp_path,
        "control",
        _development_table(lambda *_: 1.0),
        seasons=(PREVIOUS, LOCKED),
        weighting_label=EQUAL_WEIGHTING,
    )

    with pytest.raises(EvaluationValidationError, match="Unsupported"):
        read_phase_c_component_handoff(*paths, development_contract="phase_c_component_oof_v3")


def _drop_development_only(manifest: dict[str, object]) -> None:
    manifest["development_only"] = False


def _deny_the_read(manifest: dict[str, object]) -> None:
    manifest["locked_holdout_read"] = False


def _drop_weighting(manifest: dict[str, object]) -> None:
    del manifest["weighting"]


def _mismatch_weighting_model(manifest: dict[str, object]) -> None:
    manifest["weighting"] = {"label": EQUAL_WEIGHTING, "model_version": "something-else"}


@pytest.mark.parametrize(
    "edit", [_drop_development_only, _deny_the_read, _drop_weighting, _mismatch_weighting_model]
)
def test_a_v2_artifact_that_does_not_say_what_it_is_is_refused(
    tmp_path: Path, edit: Callable[[dict[str, object]], None]
) -> None:
    paths = _write_arm(
        tmp_path,
        "control",
        _development_table(lambda *_: 1.0),
        seasons=(PREVIOUS, LOCKED),
        weighting_label=EQUAL_WEIGHTING,
        edit=edit,
    )

    with pytest.raises(EvaluationValidationError):
        read_phase_c_component_handoff(
            *paths, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
        )


def test_a_v2_artifact_without_the_locked_season_must_not_claim_to_have_read_it(
    tmp_path: Path,
) -> None:
    table = _table(
        seasons=(PREVIOUS,),
        gameweeks=range(2, 4),
        players=3,
        model_version=COMPONENT_MODEL_VERSION,
        contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
        error=lambda *_: 1.0,
    )

    def claim(manifest: dict[str, object]) -> None:
        manifest["locked_holdout_read"] = True

    honest = _write_arm(
        tmp_path / "honest", "arm", table, seasons=(PREVIOUS,), weighting_label=EQUAL_WEIGHTING
    )
    claimed = _write_arm(
        tmp_path / "claimed",
        "arm",
        table,
        seasons=(PREVIOUS,),
        weighting_label=EQUAL_WEIGHTING,
        edit=claim,
    )

    assert (
        read_phase_c_component_handoff(
            *honest, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
        ).weighting
        == EQUAL_WEIGHTING
    )
    with pytest.raises(EvaluationValidationError, match="2025-26"):
        read_phase_c_component_handoff(
            *claimed, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
        )


# --- comparison -------------------------------------------------------------------------


def test_fold_points_mae_scores_exactly_what_the_component_metric_scores() -> None:
    rows = pd.DataFrame(
        {
            "fold_id": ["f1", "f1", "f1", "f1", "f2"],
            "target_gameweek": [2, 2, 2, 2, 3],
            "fixture_count": [1, 1, 0, 1, 1],
            "appearance_target": [1, 0, 1, 1, 1],
            "points_target": [5.0, pd.NA, 3.0, 4.0, 2.0],
            "control_expected_points": [6.0, 1.0, 0.0, pd.NA, 2.5],
        }
    )

    mae = fold_points_mae(rows)

    # f1: |6-5| and |1-0| (non-appearance realizes zero); the blank and the missing
    # prediction are outside the scored population. f2: |2.5-2|.
    assert mae.to_dict() == pytest.approx({"f1": 1.0, "f2": 0.5})


def _write_pair(
    directory: Path,
    control_error: ErrorRule,
    candidate_error: ErrorRule,
    *,
    candidate_commit: str = COMMIT,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write_arm(
        directory,
        "control",
        _development_table(control_error),
        seasons=(PREVIOUS, LOCKED),
        weighting_label=EQUAL_WEIGHTING,
    )
    _write_arm(
        directory,
        "candidate",
        _development_table(candidate_error, model_version=SEASON_WEIGHTED_MODEL_VERSION),
        seasons=(PREVIOUS, LOCKED),
        weighting_label=SEASON_HALF_LIFE_WEIGHTING,
        commit=candidate_commit,
    )


def _run(directory: Path) -> dict[str, object]:
    assert (
        main(
            [
                "--artifact-dir",
                str(directory),
                "--control",
                "control",
                "--candidate",
                "candidate",
            ]
        )
        == 0
    )
    report = json.loads((directory / "comparison" / "comparison.json").read_text(encoding="utf-8"))
    assert isinstance(report, dict)
    return report


def test_a_candidate_that_is_closer_on_every_fold_is_preferred(tmp_path: Path) -> None:
    _write_pair(tmp_path, lambda *_: 2.0, lambda *_: 1.0)

    report = _run(tmp_path)

    verdict = report["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "candidate_preferred"
    assert verdict["rule"] == ACCEPTANCE_RULE
    primary = report["primary_season"]
    assert isinstance(primary, dict)
    assert primary["season"] == LOCKED
    assert primary["scored_folds"] == 6
    assert primary["control_points_mae"] == pytest.approx(2.0)
    assert primary["candidate_points_mae"] == pytest.approx(1.0)
    assert primary["interval_low"] == pytest.approx(1.0)
    assert report["development_only"] is True
    assert report["promotes_anything"] is False
    assert (tmp_path / "comparison" / "comparison.md").exists()


def test_a_candidate_indistinguishable_from_the_control_gives_no_selection(
    tmp_path: Path,
) -> None:
    # The candidate alternates between better and worse folds: no direction to prefer.
    _write_pair(tmp_path, lambda *_: 2.0, lambda _s, gameweek, _p: 1.0 if gameweek % 2 else 3.0)

    report = _run(tmp_path)

    verdict = report["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["verdict"] == "no_selection"
    assert "control" in str(verdict["phase_d_reference"])
    primary = report["primary_season"]
    assert isinstance(primary, dict)
    assert primary["interval_low"] <= 0.0 <= primary["interval_high"]


def test_a_clear_regression_in_the_previous_era_blocks_selection(tmp_path: Path) -> None:
    _write_pair(
        tmp_path,
        lambda *_: 2.0,
        lambda season, *_: 1.0 if season == LOCKED else 3.5,
    )

    report = _run(tmp_path)

    verdict = report["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["candidate_has_lower_primary_mae"] is True
    assert verdict["primary_interval_excludes_zero_in_candidate_favour"] is True
    assert verdict["control_era_interval_excludes_zero_against_candidate"] is True
    assert verdict["verdict"] == "no_selection"


def test_arms_that_are_not_one_paired_measurement_are_refused(tmp_path: Path) -> None:
    _write_pair(tmp_path, lambda *_: 2.0, lambda *_: 1.0)
    control = load_arm(tmp_path, "control")
    candidate = load_arm(tmp_path, "candidate")

    drifted = candidate.rows.copy(deep=True)
    drifted.loc[0, "points_target"] = 99.0
    with pytest.raises(EvaluationValidationError, match="points_target"):
        check_paired(control, type(candidate)(**{**vars_of(candidate), "rows": drifted}))

    with pytest.raises(EvaluationValidationError, match="declared comparison"):
        check_paired(candidate, control)


def vars_of(handoff: object) -> dict[str, object]:
    return {name: getattr(handoff, name) for name in handoff.__slots__}  # type: ignore[attr-defined]


def test_arms_from_different_commits_are_refused(tmp_path: Path) -> None:
    _write_pair(tmp_path, lambda *_: 2.0, lambda *_: 1.0, candidate_commit="c" * 40)

    assert (
        main(["--artifact-dir", str(tmp_path), "--control", "control", "--candidate", "candidate"])
        == 1
    )


def test_decide_applies_each_clause_of_the_rule() -> None:
    from scripts.compare_component_oof_development import SeasonComparison

    def season(
        season: str, control: float, candidate: float, low: float, high: float
    ) -> SeasonComparison:
        return SeasonComparison(
            season=season,
            scored_folds=6,
            control_points_mae=control,
            candidate_points_mae=candidate,
            mean_paired_difference=control - candidate,
            interval_low=low,
            interval_high=high,
            fold_differences=(),
        )

    good_primary = season(LOCKED, 2.0, 1.0, 0.5, 1.5)
    neutral_previous = season(PREVIOUS, 2.0, 2.0, -0.5, 0.5)
    assert decide(good_primary, neutral_previous)["verdict"] == "candidate_preferred"
    # Lower MAE but an interval touching zero is not enough.
    assert decide(season(LOCKED, 2.0, 1.9, 0.0, 0.3), neutral_previous)["verdict"] == "no_selection"
    # A previous-era interval entirely below zero blocks selection.
    assert decide(good_primary, season(PREVIOUS, 2.0, 3.0, -1.5, -0.5))["verdict"] == "no_selection"
    # A previous-era interval merely touching zero does not.
    assert (
        decide(good_primary, season(PREVIOUS, 2.0, 2.4, -0.9, 0.0))["verdict"]
        == "candidate_preferred"
    )
