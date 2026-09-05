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
import hashlib
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
from squadopt.features.component_targets import (
    START_TARGET_STATUS,
    START_TARGET_SUPPORTED_SEASONS,
    TARGET_CONTRACT_VERSION,
)
from squadopt.prediction.component_dataset import (
    COMPONENT_FEATURE_CONFIG,
    COMPONENT_TRAINING_SEASONS,
    DATASET_CONTRACT_VERSION,
    FEATURE_CONTRACT_VERSION,
    build_component_modelling_frame,
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
DEFAULT_SEASONS = COMPONENT_TRAINING_SEASONS
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
    "q_start_given_appearance",
    "start_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
    "expected_points_if_appearance",
    "control_expected_points",
    "composition_route",
    "evidence_status",
)

ROSTER_CONTRACT_VERSION = "phase_c_decision_roster_v1"

# The decision roster: who was selectable at each decision, on the same key as the
# out-of-fold table. Kept in its own artifact because a squad decision needs the optimizer's
# player fields and the out-of-fold table is a prediction record -- mixing them would make
# one table two contracts.
#
# Ownership is deliberately absent. `selected_by_percent` is the only candidate the panel
# carries and `data/schema.py` classifies it in `AMBIGUOUS_TIMING_COLUMNS`: its snapshot
# timing cannot be proven from the schema, so it fails the "only if timing is verified"
# condition rather than passing it quietly.
ROSTER_COLUMNS = (
    "contract_version",
    "season",
    "target_gameweek",
    "fold_id",
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
)

# Rounded first, because two of the exported values are derived from two others and the
# identity has to hold on the numbers a reader actually sees. See `_round_and_derive`.
_INDEPENDENT_FLOAT_COLUMNS = (
    "appearance_probability",
    "q_start_given_appearance",
    "start_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
)
_DERIVED_FLOAT_COLUMNS = ("expected_points_if_appearance", "control_expected_points")

# The declared public bound, recorded in the manifest and asserted by a test.
PUBLIC_POINTS_BOUND = (
    "control_expected_points = max(0, appearance_probability * "
    "raw_expected_points_if_appearance), both factors read at the exported precision"
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
    return panel, build_component_modelling_frame(
        panel,
        fixtures,
        team_codes,
        seasons=seasons,
        config=COMPONENT_FEATURE_CONFIG,
    )


def _training_key_digest(training: pd.DataFrame) -> str:
    """A digest over the ordered training keys.

    The compact form of "which rows trained this fold". A verifier that does not want to
    walk `training_fold_ids` can compare this instead, and it covers the row set rather
    than only the fold labels -- two runs that agree on the folds but disagree on the rows
    produce different digests.
    """

    keys = "\n".join(
        f"{season}|{gameweek}|{player}"
        for season, gameweek, player in zip(
            training["season"].astype("string"),
            training["gameweek"].astype("int64"),
            training["player_id"].astype("int64"),
            strict=True,
        )
    )
    return hashlib.sha256(keys.encode("utf-8")).hexdigest()


def _round_and_derive(table: pd.DataFrame) -> pd.DataFrame:
    """Round the exported values, then derive the two that depend on the others.

    The order is the point. Every column is written at nine decimals, so deriving
    ``control_expected_points`` from *unrounded* inputs leaves a reader who recomputes it
    from the file with a discrepancy near 1e-9 -- measured at 4.4e-09 across 100,130 rows,
    with only 201 of them exact. Rounding the independent columns first and composing from
    those makes the identity hold on the numbers the file actually carries. This is the
    same correction ``backtest.candidate_residuals.round_for_export`` applies to its
    residual, for the same reason.

    The public bound is applied here and nowhere else:
    ``control_expected_points = max(0, appearance_probability * raw)``. It is equivalent to
    clipping the conditional first, because a probability is non-negative; stating it this
    way matches the declared contract rather than an implementation detail.
    """

    rounded = table.copy(deep=True)
    for column in _INDEPENDENT_FLOAT_COLUMNS:
        rounded[column] = rounded[column].astype("Float64").round(PREDICTED_POINTS_DECIMALS)

    probability = rounded["appearance_probability"]
    raw = rounded["raw_expected_points_if_appearance"]
    rounded["expected_points_if_appearance"] = (
        raw.clip(lower=0.0).round(PREDICTED_POINTS_DECIMALS).astype("Float64")
    )
    rounded["control_expected_points"] = (
        (probability * raw).clip(lower=0.0).round(PREDICTED_POINTS_DECIMALS).astype("Float64")
    )
    return rounded


@dataclass(frozen=True, slots=True)
class FoldRecord:
    """One fold's provenance, as the evaluation side has to be able to check it.

    ``decision_timestamp_utc`` and ``training_cutoff_utc`` are ``None`` on every archive
    fold, and that is not an omission. ``data/schema.py`` leaves both empty for
    archive-backfilled rows because "a deadline the archive never published cannot be
    recovered from a kickoff time", and forging one would forge the single field every
    leakage argument rests on.

    ``training_cutoff_fold_id`` is the archive's honest analogue: the last fold in the
    training set under the declared season order. The check
    ``training_cutoff_utc < decision_timestamp_utc`` is unrunnable here; the check that
    replaces it is stronger, because it reads the set rather than a boundary --
    ``fold_id not in training_fold_ids`` and every training fold ranking before it. Both
    are enforced below rather than left to a reader.
    """

    fold_id: str
    season: str
    target_gameweek: int
    decision_timestamp_utc: str | None
    training_cutoff_utc: str | None
    training_cutoff_fold_id: str | None
    training_fold_ids: tuple[str, ...]
    training_key_digest: str
    training_rows: int
    scored_rows: int
    model_fitted: bool
    model_version: str
    feature_contract_version: str
    target_contract_version: str

    def as_record(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "season": self.season,
            "target_gameweek": self.target_gameweek,
            "decision_timestamp_utc": self.decision_timestamp_utc,
            "training_cutoff_utc": self.training_cutoff_utc,
            "training_cutoff_fold_id": self.training_cutoff_fold_id,
            "training_fold_ids": list(self.training_fold_ids),
            "training_key_digest": self.training_key_digest,
            "training_rows": self.training_rows,
            "scored_rows": self.scored_rows,
            "model_fitted": self.model_fitted,
            "model_version": self.model_version,
            "feature_contract_version": self.feature_contract_version,
            "target_contract_version": self.target_contract_version,
        }


@dataclass(frozen=True, slots=True)
class WalkSummary:
    """What the fold walk did, beyond the table it produced."""

    refused_folds: tuple[str, ...]
    training_rows_seen: int
    scored_folds: int
    folds: tuple[FoldRecord, ...]


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
    ranks = {season: rank for rank, season in enumerate(season_order)}
    pieces: list[pd.DataFrame] = []
    refused: list[str] = []
    records: list[FoldRecord] = []
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
        training_folds = tuple(
            f"{season}-gw{gameweek:02d}"
            for season, gameweek in sorted(
                {
                    (str(season), int(gameweek))
                    for season, gameweek in zip(
                        training["season"].astype("string"),
                        training["gameweek"].astype("int64"),
                        strict=True,
                    )
                },
                key=lambda pair: (ranks[pair[0]], pair[1]),
            )
        )
        # The invariant the manifest exists to let a reader verify, enforced here so a
        # violation stops the export rather than travelling in a record nobody re-checks.
        if decision.fold_id in training_folds:
            raise DataError(
                f"Fold {decision.fold_id} appears in its own training set; the walk is not "
                "out of fold."
            )
        models = fit_component_models(training, feature_columns=columns, config=config)
        if models is None:
            refused.append(decision.fold_id)
        else:
            training_rows += models.appearance_rows
        records.append(
            FoldRecord(
                fold_id=decision.fold_id,
                season=decision.season,
                target_gameweek=decision.gameweek,
                # Not published by the archive, and not recoverable from a kickoff time.
                decision_timestamp_utc=None,
                training_cutoff_utc=None,
                training_cutoff_fold_id=training_folds[-1] if training_folds else None,
                training_fold_ids=training_folds,
                training_key_digest=_training_key_digest(training),
                training_rows=len(training),
                scored_rows=len(scoring),
                model_fitted=models is not None,
                model_version=COMPONENT_MODEL_VERSION,
                feature_contract_version=FEATURE_CONTRACT_VERSION,
                target_contract_version=TARGET_CONTRACT_VERSION,
            )
        )
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
    table = _round_and_derive(table)
    table = (
        table.loc[:, list(OOF_COLUMNS)]
        .sort_values(["season", "target_gameweek", "player_id"], kind="stable")
        .reset_index(drop=True)
    )
    return table, WalkSummary(
        refused_folds=tuple(refused),
        training_rows_seen=training_rows,
        scored_folds=len(pieces),
        folds=tuple(records),
    )


def build_decision_roster(panel: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """The optimizer's player fields for exactly the rows the out-of-fold table scored.

    Kept in its own artifact rather than widened into the out-of-fold table, because the
    two answer different questions: one is a prediction record, the other says who was
    selectable. One table carrying both contracts is a table with two meanings.

    Built from the same key, so a decision-level comparison cannot silently score a
    different population than the one that was predicted -- the join is exact by
    construction and the row counts are asserted equal.
    """

    keys = ["season", "target_gameweek", "player_id"]
    source = panel.loc[
        :, ["season", "gameweek", "player_id", "name", "team_id", "position", "price_tenths"]
    ].rename(columns={"gameweek": "target_gameweek"})
    source["season"] = source["season"].astype("string")
    source["target_gameweek"] = pd.to_numeric(source["target_gameweek"], errors="raise").astype(
        "int64"
    )
    source["player_id"] = pd.to_numeric(source["player_id"], errors="raise").astype("int64")

    wanted = table.loc[:, [*keys, "fold_id"]].copy(deep=True)
    roster = wanted.merge(source, on=keys, how="left", validate="one_to_one")
    unresolved = int(roster["name"].isna().sum())
    if unresolved:
        raise DataError(
            f"{unresolved} scored row(s) have no roster record. A decision-level comparison "
            "would then score a different population than the one predicted."
        )
    roster["contract_version"] = ROSTER_CONTRACT_VERSION
    return (
        roster.loc[:, list(ROSTER_COLUMNS)].sort_values(keys, kind="stable").reset_index(drop=True)
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

    # The archive check comes last of the preconditions. The three above cost nothing and
    # depend on nothing outside the process, so ordering them first is what lets them be
    # tested without a data store -- the suite is offline by design, and a refusal that
    # only fires when the archive happens to be present is a refusal nobody can test.
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(f"Archive not found at {archive_root}.")
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
        roster = build_decision_roster(panel, table)
    except DataError as error:
        print(f"Component out-of-fold export refused: {error}")
        return 1

    output_dir: Path = arguments.output_dir
    table_path = output_dir / f"{arguments.table_name}.csv"
    manifest_path = output_dir / f"{arguments.table_name}.manifest.json"
    roster_path = output_dir / f"{arguments.table_name}.roster.csv"
    write_export_table(table, table_path)
    write_export_table(roster, roster_path)
    digest = compute_table_sha256(table_path)
    roster_digest = compute_table_sha256(roster_path)

    modelled = int((table["composition_route"] == "component_model").sum())
    manifest = {
        "contract_version": OOF_CONTRACT_VERSION,
        "model_version": COMPONENT_MODEL_VERSION,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "target_contract_version": TARGET_CONTRACT_VERSION,
        "dataset_contract_version": DATASET_CONTRACT_VERSION,
        "roster_contract_version": ROSTER_CONTRACT_VERSION,
        "development_seasons": list(seasons),
        "fold_ids": [decision.fold_id for decision in decisions],
        "fold_count": len(decisions),
        "scored_fold_count": walk.scored_folds,
        "folds_refused_for_thin_history": list(walk.refused_folds),
        # One record per scored fold, carrying what a chronology and leakage check needs.
        "folds": [record.as_record() for record in walk.folds],
        "chronology_check": (
            "training_cutoff_utc < decision_timestamp_utc is unrunnable on archive folds: "
            "neither timestamp is published and neither may be forged. The substitute is "
            "stronger because it reads the set rather than a boundary -- for every fold, "
            "fold_id is absent from training_fold_ids and every training fold ranks before "
            "it under development_seasons order. The export enforces both and refuses "
            "rather than recording a violation. training_cutoff_fold_id is the ordinal "
            "analogue of training_cutoff_utc, and training_key_digest covers the training "
            "row set rather than only its fold labels."
        ),
        "public_points_bound": PUBLIC_POINTS_BOUND,
        "public_points_bound_note": (
            "Equivalent to clipping the conditional first, because a probability is "
            "non-negative. The two derived columns are composed from the *rounded* "
            "independent columns, so a reader recomputing them from the file gets the "
            "value the file carries; deriving them from unrounded inputs left a "
            "discrepancy of 4.4e-09 with only 201 of 100,130 rows exact."
        ),
        "negative_raw_conditional_points": int(
            (table["raw_expected_points_if_appearance"].astype("Float64") < 0).sum()
        ),
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
        "reproduce": (
            "This artifact reads only the pinned public archive, so it can be rebuilt "
            "rather than transferred: python -m scripts.fetch_historical_data (verifies "
            "against the committed checksum manifest), then python -m "
            "scripts.export_component_oof, at the repository_commit below. Byte-identical "
            "output is the check -- compare table_sha256 and roster_sha256. Only "
            "generated_at_utc differs between runs."
        ),
        "repository_commit": revision,
        "working_tree_dirty": dirty,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "table_file": table_path.name,
        "table_sha256": digest,
        # Reported from the frame that was written rather than declared separately, so the
        # manifest cannot claim a schema the file does not carry. A CSV has no dtypes, and
        # a plain read_csv turns the nullable columns into float64 -- a consumer aligning
        # its evaluator schema needs the declared ones, not the inferred ones.
        "table_columns": list(OOF_COLUMNS),
        "table_column_dtypes": {str(column): str(dtype) for column, dtype in table.dtypes.items()},
        "roster_file": roster_path.name,
        "roster_sha256": roster_digest,
        "roster_row_count": len(roster),
        "roster_columns": list(ROSTER_COLUMNS),
        "roster_column_dtypes": {
            str(column): str(dtype) for column, dtype in roster.dtypes.items()
        },
        "roster_ownership_policy": (
            "Omitted. selected_by_percent is the only ownership column the panel carries "
            "and data/schema.py classifies it in AMBIGUOUS_TIMING_COLUMNS, so its snapshot "
            "timing cannot be proven -- it fails the 'only if timing is verified' "
            "condition rather than passing it quietly."
        ),
        "locked_holdout_read": False,
        "locked_holdout_season": LOCKED_HOLDOUT_SEASON,
        "promotes_anything": False,
    }
    write_json(manifest_path, manifest)

    print(f"Wrote {table_path}")
    print(f"      {roster_path}")
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
    print(f"  roster rows       {len(roster)}")
    print(f"  table sha256      {digest}")
    print(f"  roster sha256     {roster_digest}")
    print(f"  locked holdout    not read ({LOCKED_HOLDOUT_SEASON})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
