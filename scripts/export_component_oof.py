"""Export the Phase C control components' out-of-fold predictions.

    python -m scripts.export_component_oof --output-dir artifacts/phase_c

Walks the chronological development folds, fits the three control component estimators on
the rows strictly before each decision, predicts that decision's rows, and writes one
`phase_c_component_oof_v1` table plus its manifest. Every row is out of fold: no row was
ever in the training slice of the model that predicted it.

The table is the evaluation side's input. Nothing here measures a model, compares it to
the operational control, or promotes anything.

**Why the fold walk lives in a script.** `backtest.splits` and `preflight` sit above
`prediction` in the layer order, so the package cannot import them. The estimators, the
targets and the modelling frame are package API; this shell computes the fold boundaries
with the repository's own splitter, hands them in as data, and writes the bytes.

The 2025-26 locked holdout is refused before anything is read.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    _git_revision,
    write_json,
)

from squadopt.backtest.candidate_residuals import PREDICTED_POINTS_DECIMALS
from squadopt.backtest.export_precision import write_export_table
from squadopt.backtest.splits import DecisionPoint, season_ranks, walk_forward_decision_points
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    build_fixture_panel,
    build_panel,
    load_team_codes,
)
from squadopt.features import build_feature_dataset
from squadopt.features.component_targets import (
    START_TARGET_STATUS,
    START_TARGET_SUPPORTED_SEASONS,
    TARGET_CONTRACT_VERSION,
    build_component_targets,
)
from squadopt.features.fixtures import attach_fixture_features
from squadopt.prediction.component_dataset import (
    COMPONENT_FEATURE_CONFIG,
    DATASET_CONTRACT_VERSION,
    FEATURE_CONTRACT_VERSION,
    build_component_frame,
    component_feature_columns,
    excluded_ratio_features,
    rows_at,
    rows_strictly_before,
)
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    ComponentModelConfig,
    fit_component_models,
    predict_components,
)
from squadopt.preflight import compute_table_sha256

OOF_CONTRACT_VERSION = "phase_c_component_oof_v1"

# The chronological development seasons. 2025-26 is the locked holdout and 2020-21 sits
# before the window every recorded development measurement uses, so neither is a default.
DEFAULT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
LOCKED_HOLDOUT_SEASON = "2025-26"

OOF_COLUMNS = (
    "contract_version",
    "model_version",
    "feature_contract_version",
    "target_contract_version",
    "dataset_contract_version",
    "season",
    "target_gameweek",
    "decision_timestamp_utc",
    "fold_id",
    "player_id",
    "fixture_count",
    "appearance_target",
    "start_target",
    "minutes_target",
    "points_target",
    "appearance_probability",
    "start_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
    "expected_points_if_appearance",
    "control_expected_points",
    "composition_route",
    "evidence_status",
)

_FLOAT_COLUMNS = (
    "appearance_probability",
    "start_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
    "expected_points_if_appearance",
    "control_expected_points",
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument(
        "--output-dir", type=Path, default=REPOSITORY_ROOT / "artifacts" / "phase_c"
    )
    parser.add_argument("--table-name", default=OOF_CONTRACT_VERSION)
    parser.add_argument("--minimum-training-rows", type=int, default=200)
    return parser.parse_args()


def _modelling_frame(archive_root: Path, seasons: tuple[str, ...]) -> tuple[pd.DataFrame, ...]:
    """Return the panel and the joined modelling frame for the requested seasons."""

    panel = build_panel(archive_root, seasons=seasons)
    fixtures = build_fixture_panel(archive_root, seasons=seasons)
    # `load_team_codes` returns one season's table without naming the season, so the
    # caller labels it -- the same shape `run_fixture_group_conformal` uses.
    team_codes = pd.concat(
        [load_team_codes(archive_root, season).assign(season=season) for season in seasons],
        ignore_index=True,
    )
    features = build_feature_dataset(panel, config=COMPONENT_FEATURE_CONFIG)

    # Attached per season, as the production backtest does: the fixture table and the team
    # bridge are both per-season objects. "omit" because the archive publishes no capture
    # instant, so its difficulty is not a pre-match value -- and the two omitted columns
    # are not in this feature set anyway.
    attached = [
        attach_fixture_features(
            features.loc[features["season"].astype("string") == season],
            fixtures.loc[fixtures["season"].astype("string") == season],
            team_codes.loc[team_codes["season"].astype("string") == season],
            unproven_difficulty="omit",
        )
        for season in seasons
    ]
    with_fixtures = pd.concat(attached, ignore_index=True)
    targets = build_component_targets(panel)
    return panel, build_component_frame(with_fixtures, targets)


@dataclass(frozen=True, slots=True)
class WalkSummary:
    """What the fold walk did, beyond the table it produced."""

    refused_folds: tuple[str, ...]
    training_rows_seen: int
    scored_folds: int


def build_oof_table(
    frame: pd.DataFrame,
    decisions: Sequence[DecisionPoint],
    *,
    season_order: Sequence[str],
    config: ComponentModelConfig | None = None,
) -> tuple[pd.DataFrame, WalkSummary]:
    """Walk the decisions, fitting before each and predicting at it.

    Separated from :func:`main` so the property the whole table rests on -- that no row was
    in the training slice of the model that predicted it -- is testable on a synthetic
    frame, without an archive. The test suite is offline by design.
    """

    columns = component_feature_columns()
    pieces: list[pd.DataFrame] = []
    refused: list[str] = []
    training_rows = 0
    for decision in decisions:
        scoring = rows_at(frame, season=decision.season, gameweek=decision.gameweek)
        if scoring.empty:
            continue
        training = rows_strictly_before(
            frame,
            season_order=season_order,
            season=decision.season,
            gameweek=decision.gameweek,
        )
        models = fit_component_models(training, feature_columns=columns, config=config)
        if models is None:
            refused.append(decision.fold_id)
        else:
            training_rows += models.appearance_rows
        predicted = predict_components(models, scoring, feature_columns=columns)
        piece = pd.concat(
            [
                scoring.loc[
                    :,
                    [
                        "season",
                        "gameweek",
                        "player_id",
                        "fixture_count",
                        "appearance_target",
                        "start_target",
                        "minutes_target",
                        "points_target",
                    ],
                ].reset_index(drop=True),
                predicted.reset_index(drop=True),
            ],
            axis=1,
        )
        piece["fold_id"] = decision.fold_id
        pieces.append(piece)

    if not pieces:
        raise DataError("No decision produced a scoring population.")

    table = pd.concat(pieces, ignore_index=True)
    table = table.rename(columns={"gameweek": "target_gameweek"})
    table["contract_version"] = OOF_CONTRACT_VERSION
    table["model_version"] = COMPONENT_MODEL_VERSION
    table["feature_contract_version"] = FEATURE_CONTRACT_VERSION
    table["target_contract_version"] = TARGET_CONTRACT_VERSION
    table["dataset_contract_version"] = DATASET_CONTRACT_VERSION
    # The archive publishes no deadline, and `data/schema.py` refuses to recover one from a
    # kickoff time: fabricating it would forge the single field every leakage argument
    # rests on. Missing, and the manifest says what guarantees these rows instead.
    table["decision_timestamp_utc"] = pd.Series(pd.NA, index=table.index, dtype="string")
    for column in _FLOAT_COLUMNS:
        table[column] = table[column].astype("Float64").round(PREDICTED_POINTS_DECIMALS)
    table = (
        table.loc[:, list(OOF_COLUMNS)]
        .sort_values(["season", "target_gameweek", "player_id"], kind="stable")
        .reset_index(drop=True)
    )
    return table, WalkSummary(
        refused_folds=tuple(refused),
        training_rows_seen=training_rows,
        scored_folds=len(pieces),
    )


def main() -> int:
    arguments = _parse_arguments()
    seasons = tuple(
        season.strip() for season in str(arguments.seasons).split(",") if season.strip()
    )
    if not seasons:
        print("At least one season is required.")
        return 1
    if LOCKED_HOLDOUT_SEASON in seasons:
        print(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout. It is not read, listed or "
            "measured here; spending it is a three-owner decision under its own protocol."
        )
        return 1
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(f"Archive not found at {archive_root}.")
        return 1

    revision, dirty = _git_revision()
    if dirty:
        # The manifest records the commit this artifact came from, and a commit reproduces
        # an artifact only if the tree it was built from was that commit. The sibling
        # evidence exporter refuses for the same reason; recording `dirty: true` beside a
        # hash that does not reproduce would be a manifest that misleads politely.
        print(
            "The working tree has uncommitted changes, so the recorded commit would not "
            "reproduce this artifact. Commit or stash them first."
        )
        return 1
    config = ComponentModelConfig(minimum_training_rows=int(arguments.minimum_training_rows))

    try:
        panel, frame = _modelling_frame(archive_root, seasons)
        ranks = season_ranks(panel)
        season_order = tuple(sorted(ranks, key=lambda season: ranks[season]))
        decisions = walk_forward_decision_points(panel, seasons=seasons)
        if not decisions:
            raise DataError("The panel produced no decision points.")
        table, walk = build_oof_table(frame, decisions, season_order=season_order, config=config)
    except DataError as error:
        print(f"Component out-of-fold export refused: {error}")
        return 1

    output_dir: Path = arguments.output_dir
    table_path = output_dir / f"{arguments.table_name}.csv"
    manifest_path = output_dir / f"{arguments.table_name}.manifest.json"
    write_export_table(table, table_path)
    digest = compute_table_sha256(table_path)

    modelled = int((table["composition_route"] == "component_model").sum())
    manifest = {
        "contract_version": OOF_CONTRACT_VERSION,
        "model_version": COMPONENT_MODEL_VERSION,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "target_contract_version": TARGET_CONTRACT_VERSION,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "development_seasons": list(seasons),
        "fold_ids": [decision.fold_id for decision in decisions],
        "fold_count": len(decisions),
        "scored_fold_count": walk.scored_folds,
        "folds_refused_for_thin_history": list(walk.refused_folds),
        "deterministic_seed": 0,
        "training_rows_seen": walk.training_rows_seen,
        "row_count": len(table),
        "component_model_rows": modelled,
        "direct_control_rows": int(len(table) - modelled),
        "feature_columns": list(component_feature_columns()),
        "excluded_ratio_features": list(excluded_ratio_features()),
        "start_target_status": START_TARGET_STATUS,
        "start_target_supported_seasons": list(START_TARGET_SUPPORTED_SEASONS),
        "missing_data_policy": (
            "A missing value is missing. Conditional targets are absent where the player "
            "did not appear; a row without complete features takes the direct_control "
            "route and carries no component prediction; the start component is "
            "unavailable, not zero. Nothing is imputed."
        ),
        "decision_timestamp_policy": (
            "The archive publishes no deadline and one cannot be recovered from a kickoff "
            "time, so decision_timestamp_utc is missing on every row. What guarantees "
            "these rows is structural: every feature is a shift(1) rolling aggregate or a "
            "declared pre-match column, each fold trains strictly before its own "
            "gameweek, and no outcome column is in the feature set."
        ),
        "archive_commit": ARCHIVE_COMMIT,
        "repository_commit": revision,
        "working_tree_dirty": dirty,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "table_file": table_path.name,
        "table_sha256": digest,
        "locked_holdout_read": False,
        "locked_holdout_season": LOCKED_HOLDOUT_SEASON,
        "promotes_anything": False,
    }
    write_json(manifest_path, manifest)

    print(f"Wrote {table_path}")
    print(f"      {manifest_path}")
    print(f"  contract          {OOF_CONTRACT_VERSION}")
    print(f"  seasons           {', '.join(seasons)}")
    print(
        f"  folds             {walk.scored_folds} scored of {len(decisions)} "
        f"({len(walk.refused_folds)} refused for thin history)"
    )
    print(f"  rows              {len(table)}")
    print(f"  component rows    {modelled}")
    print(f"  fallback rows     {len(table) - modelled}")
    print(f"  start component   {START_TARGET_STATUS}")
    print(f"  table sha256      {digest}")
    print(f"  locked holdout    not read ({LOCKED_HOLDOUT_SEASON})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
