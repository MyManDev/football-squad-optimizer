"""Compare the two Phase C v2 development arms on identical out-of-fold rows.

    python -m scripts.compare_component_oof_development --artifact-dir artifacts/phase_c_v2

Reads two development handoffs written by ``scripts.export_component_oof`` under
``--development-scope v2``: the equal-weight control and the season-age-weighted
candidate. Both must come from the same commit, score exactly the same rows with the same
targets and the same coverage, and differ only in their predictions. Each arm is scored
with the existing component metrics; the comparison itself is the one fixed before the
measurement -- per-fold points MAE differences on the primary development season under the
existing season-aware moving-block interval, with the previous scoring era reported
separately and never averaged in.

Nothing here promotes, pins or deploys anything. The verdict is a development reading
under a rule written down in advance, and the numbers it produces stay with the run.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean

import pandas as pd
from scripts._experiment_cli import write_json, write_text

from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    EvaluationValidationError,
    PhaseCComponentEvaluation,
    PhaseCComponentHandoff,
    evaluate_component_oof,
    read_phase_c_component_handoff,
)
from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.phase_c_reporting import phase_c_component_evaluation_to_dict
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    EQUAL_WEIGHTING,
    SEASON_HALF_LIFE_WEIGHTING,
    SEASON_WEIGHTED_MODEL_VERSION,
)

COMPARISON_CONTRACT_VERSION = "phase_c_v2_development_comparison_v1"
# The two seasons the rule was written for. Constants, not options: a primary season that
# could be chosen after the numbers are seen would not be a fixed rule.
PRIMARY_SEASON = "2025-26"
CONTROL_ERA_SEASON = "2024-25"
DEVELOPMENT_SEASONS = (PRIMARY_SEASON,)
CANDIDATE_ID = "phase_c_v2_season_half_life_vs_equal"
# The existing paired-inference policy at its declared defaults. `min_mean_improvement` is
# a squad-points gate and has no meaning for a per-player MAE, so it is not consulted and
# no substitute threshold is invented.
POLICY = PromotionPolicy(
    confidence_level=0.90, bootstrap_resamples=5000, moving_block_length=4, deterministic_seed=0
)
KEY = ["season", "target_gameweek", "fold_id", "player_id"]
# Everything two arms of one measurement must agree on before their predictions are read.
PAIRING_COLUMNS = (
    "fixture_count",
    "appearance_target",
    "start_target",
    "minutes_target",
    "points_target",
    "composition_route",
)
ACCEPTANCE_RULE = (
    "The candidate is preferred only if (i) its primary-season points MAE is lower than the "
    "control's, (ii) the 90% season-aware moving-block interval of the per-fold paired "
    "differences (control MAE minus candidate MAE) on the primary season lies entirely "
    "above zero, and (iii) the same interval on the previous-era season does not lie "
    "entirely below zero. Otherwise there is no selection and the control remains the "
    "reference. No minimum effect size is imposed and none is added afterwards."
)


@dataclass(frozen=True, slots=True)
class SeasonComparison:
    """The paired reading for one season, both arms on the same folds."""

    season: str
    scored_folds: int
    control_points_mae: float
    candidate_points_mae: float
    mean_paired_difference: float
    interval_low: float
    interval_high: float
    fold_differences: tuple[tuple[str, float], ...]

    def as_record(self) -> dict[str, object]:
        return {
            "season": self.season,
            "scored_folds": self.scored_folds,
            "control_points_mae": self.control_points_mae,
            "candidate_points_mae": self.candidate_points_mae,
            "mean_paired_difference": self.mean_paired_difference,
            "paired_difference_sign": "control MAE minus candidate MAE; positive favours the "
            "candidate",
            "interval_low": self.interval_low,
            "interval_high": self.interval_high,
            "fold_differences": [
                {"fold_id": fold, "difference": value} for fold, value in self.fold_differences
            ],
        }


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--control", default=f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_equal")
    parser.add_argument(
        "--candidate", default=f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_season_half_life"
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


def load_arm(directory: Path, name: str) -> PhaseCComponentHandoff:
    """Read one development arm through the explicit development reader."""

    return read_phase_c_component_handoff(
        directory / f"{name}.csv",
        directory / f"{name}.roster.csv",
        directory / f"{name}.manifest.json",
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )


def check_paired(control: PhaseCComponentHandoff, candidate: PhaseCComponentHandoff) -> None:
    """Refuse two arms that are not one measurement with two sets of predictions."""

    if control.weighting != EQUAL_WEIGHTING or candidate.weighting != SEASON_HALF_LIFE_WEIGHTING:
        raise EvaluationValidationError(
            "The declared comparison is the equal-weight control against the season-half-life "
            f"candidate; got control {control.weighting!r} and candidate "
            f"{candidate.weighting!r}."
        )
    # A label alone is a claim; the model version is what the fit actually recorded.
    if (
        control.model_version != COMPONENT_MODEL_VERSION
        or candidate.model_version != SEASON_WEIGHTED_MODEL_VERSION
    ):
        raise EvaluationValidationError(
            "Arm labels and model versions disagree: the control must carry "
            f"{COMPONENT_MODEL_VERSION!r} and the candidate {SEASON_WEIGHTED_MODEL_VERSION!r}, "
            f"got {control.model_version!r} and {candidate.model_version!r}."
        )
    if control.repository_commit != candidate.repository_commit:
        raise EvaluationValidationError("Both arms must come from the same commit.")
    for field in (
        "feature_contract_version",
        "target_contract_version",
        "dataset_contract_version",
    ):
        if getattr(control, field) != getattr(candidate, field):
            raise EvaluationValidationError(f"The two arms disagree on {field}.")
    left = control.rows.sort_values(KEY, kind="stable").reset_index(drop=True)
    right = candidate.rows.sort_values(KEY, kind="stable").reset_index(drop=True)
    if len(left) != len(right) or not left.loc[:, KEY].equals(right.loc[:, KEY]):
        raise EvaluationValidationError("The two arms do not score the same rows.")
    for column in PAIRING_COLUMNS:
        if not left[column].equals(right[column]):
            raise EvaluationValidationError(
                f"The two arms disagree on {column}; they are not one paired measurement."
            )


def _scored_points(rows: pd.DataFrame) -> pd.DataFrame:
    """The rows the component points metric scores, with its realized target.

    Mirrors ``evaluate_component_oof`` exactly: non-blank rows with a prediction, where a
    player who did not appear -- or whose appearance is unknown -- realized zero points.
    """

    appearance = pd.to_numeric(rows["appearance_target"], errors="raise").astype("Float64")
    appeared = appearance.eq(1.0).fillna(False).astype(bool)
    points = pd.to_numeric(rows["points_target"], errors="raise").astype("Float64")
    realized = points.where(appeared, 0.0)
    prediction = pd.to_numeric(rows["control_expected_points"], errors="raise").astype("Float64")
    fixtures = pd.to_numeric(rows["fixture_count"], errors="raise").astype("int64")
    scored = pd.DataFrame(
        {
            "fold_id": rows["fold_id"].astype("string"),
            "target_gameweek": pd.to_numeric(rows["target_gameweek"], errors="raise"),
            "prediction": prediction,
            "realized": realized,
        },
        index=rows.index,
    )
    mask = fixtures.gt(0) & prediction.notna() & realized.notna()
    return scored.loc[mask]


def fold_points_mae(rows: pd.DataFrame) -> pd.Series:
    """Points MAE per fold over exactly the rows the component metric scores."""

    scored = _scored_points(rows)
    error = (scored["prediction"] - scored["realized"]).abs().astype("float64")
    return error.groupby(scored["fold_id"], sort=False).mean()


def paired_fold_differences(
    control_rows: pd.DataFrame, candidate_rows: pd.DataFrame, *, season: str
) -> tuple[tuple[str, float], ...]:
    """(fold_id, control MAE - candidate MAE) per scored fold of ``season``, in order."""

    control_season = control_rows.loc[control_rows["season"].eq(season)]
    candidate_season = candidate_rows.loc[candidate_rows["season"].eq(season)]
    control = fold_points_mae(control_season)
    candidate = fold_points_mae(candidate_season)
    if set(control.index) != set(candidate.index):
        raise EvaluationValidationError(
            f"The two arms score different folds in {season}; they are not one measurement."
        )
    order = (
        _scored_points(control_season)
        .loc[:, ["fold_id", "target_gameweek"]]
        .drop_duplicates()
        .sort_values("target_gameweek", kind="stable")
    )
    return tuple((str(fold), float(control[fold] - candidate[fold])) for fold in order["fold_id"])


def _season_points_mae(metrics: PhaseCComponentEvaluation, season: str) -> float:
    if season not in metrics.by_season:
        raise EvaluationValidationError(f"No scored rows in {season}.")
    value = metrics.by_season[season].points.mean_absolute_error
    if value is None:
        raise EvaluationValidationError(f"No points observations in {season}.")
    return float(value)


def compare_season(
    control_rows: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    *,
    season: str,
    control_metrics: PhaseCComponentEvaluation,
    candidate_metrics: PhaseCComponentEvaluation,
) -> SeasonComparison:
    """The fixed paired reading for one season."""

    differences = paired_fold_differences(control_rows, candidate_rows, season=season)
    if not differences:
        raise EvaluationValidationError(f"No scored fold in {season}.")
    low, high = season_aware_moving_block_interval(
        [(season, value) for _, value in differences], policy=POLICY, candidate_id=CANDIDATE_ID
    )
    return SeasonComparison(
        season=season,
        scored_folds=len(differences),
        control_points_mae=_season_points_mae(control_metrics, season),
        candidate_points_mae=_season_points_mae(candidate_metrics, season),
        mean_paired_difference=fmean(value for _, value in differences),
        interval_low=float(low),
        interval_high=float(high),
        fold_differences=differences,
    )


def decide(primary: SeasonComparison, control_era: SeasonComparison) -> dict[str, object]:
    """Apply the acceptance rule exactly as written before the measurement."""

    lower_primary_mae = primary.candidate_points_mae < primary.control_points_mae
    primary_interval_above_zero = primary.interval_low > 0.0
    control_era_interval_below_zero = control_era.interval_high < 0.0
    preferred = (
        lower_primary_mae and primary_interval_above_zero and not control_era_interval_below_zero
    )
    return {
        "rule": ACCEPTANCE_RULE,
        "candidate_has_lower_primary_mae": lower_primary_mae,
        "primary_interval_excludes_zero_in_candidate_favour": primary_interval_above_zero,
        "control_era_interval_excludes_zero_against_candidate": control_era_interval_below_zero,
        "verdict": "candidate_preferred" if preferred else "no_selection",
        "phase_d_reference": (
            "season_half_life candidate" if preferred else "equal-weight control (no selection)"
        ),
    }


def _arm_record(handoff: PhaseCComponentHandoff, name: str) -> dict[str, object]:
    return {
        "name": name,
        "weighting": handoff.weighting,
        "model_version": handoff.model_version,
        "development_contract": handoff.development_contract,
        "repository_commit": handoff.repository_commit,
        "table_sha256": handoff.table_sha256,
        "roster_sha256": handoff.roster_sha256,
        "manifest_sha256": handoff.manifest_sha256,
        "rows": len(handoff.rows),
        "component_model_rows": int(handoff.rows["composition_route"].eq("component_model").sum()),
    }


def _markdown(report: dict[str, object]) -> str:
    verdict = report["verdict"]
    assert isinstance(verdict, dict)
    lines = [
        "# Phase C v2 development comparison",
        "",
        f"Contract `{report['contract_version']}`, generated {report['generated_at_utc']}.",
        "Development-only reading; nothing here is promoted, pinned or deployed.",
        "",
        f"**Verdict:** `{verdict['verdict']}` -- Phase D reference: "
        f"{verdict['phase_d_reference']}.",
        "",
        f"Rule: {verdict['rule']}",
        "",
        "| season | role | folds | control points MAE | candidate points MAE | mean paired "
        "difference | 90% interval |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for role in ("primary_season", "control_era_season"):
        item = report[role]
        assert isinstance(item, dict)
        lines.append(
            f"| {item['season']} | {role.replace('_', ' ')} | {item['scored_folds']} | "
            f"{item['control_points_mae']:.5f} | {item['candidate_points_mae']:.5f} | "
            f"{item['mean_paired_difference']:+.5f} | [{item['interval_low']:+.5f}, "
            f"{item['interval_high']:+.5f}] |"
        )
    descriptive = report["descriptive_seasons"]
    assert isinstance(descriptive, dict)
    if descriptive:
        lines += ["", "Descriptive only (not part of the rule):", ""]
        lines += ["| season | control points MAE | candidate points MAE |", "| --- | --- | --- |"]
        for season, item in descriptive.items():
            assert isinstance(item, dict)
            lines.append(
                f"| {season} | {item['control_points_mae']:.5f} | "
                f"{item['candidate_points_mae']:.5f} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    artifact_dir: Path = arguments.artifact_dir
    output_dir: Path = (
        artifact_dir / "comparison" if arguments.output_dir is None else arguments.output_dir
    )
    primary_season = PRIMARY_SEASON
    control_era_season = CONTROL_ERA_SEASON
    try:
        control = load_arm(artifact_dir, str(arguments.control))
        candidate = load_arm(artifact_dir, str(arguments.candidate))
        check_paired(control, candidate)
        control_metrics = evaluate_component_oof(
            control.rows, development_seasons=DEVELOPMENT_SEASONS
        )
        candidate_metrics = evaluate_component_oof(
            candidate.rows, development_seasons=DEVELOPMENT_SEASONS
        )
        primary = compare_season(
            control.rows,
            candidate.rows,
            season=primary_season,
            control_metrics=control_metrics,
            candidate_metrics=candidate_metrics,
        )
        control_era = compare_season(
            control.rows,
            candidate.rows,
            season=control_era_season,
            control_metrics=control_metrics,
            candidate_metrics=candidate_metrics,
        )
    except EvaluationValidationError as error:
        print(f"Phase C v2 comparison refused: {error}")
        return 1

    descriptive = {
        season: {
            "control_points_mae": control_metrics.by_season[season].points.mean_absolute_error,
            "candidate_points_mae": candidate_metrics.by_season[season].points.mean_absolute_error,
        }
        for season in sorted(control_metrics.by_season)
        if season not in (primary_season, control_era_season)
    }
    verdict = decide(primary, control_era)
    report: dict[str, object] = {
        "contract_version": COMPARISON_CONTRACT_VERSION,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "development_only": True,
        "promotes_anything": False,
        "acceptance_rule": ACCEPTANCE_RULE,
        "policy": {
            "confidence_level": POLICY.confidence_level,
            "bootstrap_resamples": POLICY.bootstrap_resamples,
            "moving_block_length": POLICY.moving_block_length,
            "deterministic_seed": POLICY.deterministic_seed,
            "candidate_id": CANDIDATE_ID,
        },
        "arms": {
            "control": _arm_record(control, str(arguments.control)),
            "candidate": _arm_record(candidate, str(arguments.candidate)),
        },
        "primary_season": primary.as_record(),
        "control_era_season": control_era.as_record(),
        "descriptive_seasons": descriptive,
        "metrics": {
            "control": phase_c_component_evaluation_to_dict(control_metrics),
            "candidate": phase_c_component_evaluation_to_dict(candidate_metrics),
        },
        "verdict": verdict,
    }
    write_json(output_dir / "comparison.json", report)
    write_text(output_dir / "comparison.md", _markdown(report))
    print(f"Wrote {output_dir / 'comparison.json'}")
    print(f"      {output_dir / 'comparison.md'}")
    print(f"  verdict           {verdict['verdict']}")
    print(f"  primary season    {primary.season} ({primary.scored_folds} paired folds)")
    print(f"  control era       {control_era.season} ({control_era.scored_folds} paired folds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
