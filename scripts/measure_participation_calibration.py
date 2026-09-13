"""Measure whether the conditional start estimator is calibrated, and record it.

    python -m scripts.measure_participation_calibration

The pre-registration is ``docs/participation_model_prereg.md``. It declares the label, the
population and the estimator; this reads what that estimator does, and reads it in the order
the document fixes: calibration before discrimination.

Two quantities are scored against the same start label:

- ``q_start_given_appearance``, the object the work fits, on appeared rows. The direct
  reading of whether the new estimator is calibrated.
- ``p_start = p_appearance * q``, the composition, on rows where both halves exist. The
  reading that matters downstream, and the one that can be wrong while ``q`` is right,
  because it inherits the appearance model's calibration.

``p_appearance`` alone is not re-measured. It is the promoted control's own number and
``docs/phase_c_component_evaluation.json`` already reports it; re-reading it under a
different population would invite a comparison that is not like-for-like.

The split is out-of-sample inside the declared population: fitted on 2023-24, scored on
2024-25. Neither season is the locked 2025-26 holdout, which is not loaded, not listed and
not hashed here. The reading is descriptive. It promotes nothing, moves no threshold, and
changes no operational control.

Only the pinned archive on disk is read. Nothing is fetched, so the numbers this writes are
reproducible from what the manifest already verifies.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, artifact_metadata, write_json, write_text

from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.features.component_targets import START_TARGET_SUPPORTED_SEASONS
from squadopt.prediction.component_dataset import (
    COMPONENT_FEATURE_CONFIG,
    build_component_modelling_frame,
    component_feature_columns,
)
from squadopt.prediction.component_models import fit_component_models, predict_components
from squadopt.prediction.participation import (
    CONDITIONAL_START_MODEL_VERSION,
    TEAM_STRENGTH_COLUMN,
    attach_team_strength,
    fit_start_model,
    predict_start_given_appearance,
    start_feature_columns,
)

PARTICIPATION_CALIBRATION_CONTRACT_VERSION: Final = "participation_calibration_v1"

#: Fitted on the first, scored on the second. Both are declared development seasons.
TRAINING_SEASON: Final = "2023-24"
SCORING_SEASON: Final = "2024-25"

#: Ten fixed-width bins, the same shape `evaluation/appearance.py` reports.
RELIABILITY_BINS: Final = 10

DEFAULT_RECORD: Final = Path("docs/participation_calibration.json")
DEFAULT_SUMMARY: Final = Path("docs/participation_calibration.md")


def _binary_metrics(probability: pd.Series, label: pd.Series) -> dict[str, object]:
    """Brier, log loss and a ten-bin reliability diagram over the scored rows.

    Log loss is clipped away from the open ends of the interval before the logarithm, because
    a single confident miss would otherwise return infinity and destroy a pooled mean that
    describes a hundred thousand rows. The clip is named in the record rather than hidden.
    """

    scored = probability.notna() & label.notna()
    values = probability.loc[scored].to_numpy(dtype="float64")
    outcomes = label.loc[scored].to_numpy(dtype="float64")
    if values.size == 0:
        return {"scored_rows": 0}

    clipped = np.clip(values, 1e-15, 1 - 1e-15)
    bins: list[dict[str, object]] = []
    edges = np.linspace(0.0, 1.0, RELIABILITY_BINS + 1)
    index = np.clip(np.digitize(values, edges[1:-1], right=False), 0, RELIABILITY_BINS - 1)
    for position in range(RELIABILITY_BINS):
        selected = index == position
        count = int(selected.sum())
        bins.append(
            {
                "index": position,
                "lower_bound": float(edges[position]),
                "upper_bound": float(edges[position + 1]),
                "observations": count,
                "mean_probability": float(values[selected].mean()) if count else None,
                "event_rate": float(outcomes[selected].mean()) if count else None,
            }
        )

    mean_probability = float(values.mean())
    event_rate = float(outcomes.mean())
    return {
        "scored_rows": int(values.size),
        "mean_probability": mean_probability,
        "event_rate": event_rate,
        "mean_calibration_bias": mean_probability - event_rate,
        "brier_score": float(np.mean((values - outcomes) ** 2)),
        "log_loss": float(
            -np.mean(outcomes * np.log(clipped) + (1.0 - outcomes) * np.log(1.0 - clipped))
        ),
        "log_loss_clip": 1e-15,
        "reliability_bins": bins,
    }


def _by_position(
    frame: pd.DataFrame, probability: pd.Series, label: pd.Series
) -> dict[str, object]:
    slices: dict[str, object] = {}
    for position in sorted(frame["position"].astype("string").dropna().unique()):
        selected = frame["position"].astype("string") == position
        slices[str(position)] = _binary_metrics(probability.loc[selected], label.loc[selected])
    return slices


def _frame(archive_root: Path, seasons: tuple[str, ...]) -> pd.DataFrame:
    """The repository's own component modelling frame, plus the team-strength control.

    Built through `build_component_modelling_frame` rather than assembled here, so the design
    this measures is the design the estimators are fitted on -- including `fixture_count`,
    which the minutes bound needs and which a hand-rolled join would silently omit.
    """

    panel = build_panel(archive_root, seasons=seasons)
    fixtures = build_fixture_panel(archive_root, seasons=seasons)
    # `load_team_codes` returns one season's table without naming the season.
    team_codes = pd.concat(
        [load_team_codes(archive_root, season).assign(season=season) for season in seasons],
        ignore_index=True,
    )
    frame = build_component_modelling_frame(
        panel, fixtures, team_codes, seasons=seasons, config=COMPONENT_FEATURE_CONFIG
    )
    # The modelling frame is a design matrix and carries neither the club nor the position.
    # Both come back from the panel by the panel's own key rather than being recomputed, so
    # the control and the position slice describe the same rows the design does.
    carried = attach_team_strength(panel).loc[
        :, ["season", "gameweek", "player_id", "position", TEAM_STRENGTH_COLUMN]
    ]
    joined = frame.merge(
        carried, on=["season", "gameweek", "player_id"], how="left", validate="one_to_one"
    )
    joined.index = frame.index
    return joined


def measure(archive_root: Path) -> dict[str, object]:
    """Fit on the training season, score the next, and describe what came out."""

    seasons = (TRAINING_SEASON, SCORING_SEASON)
    undeclared = [season for season in seasons if season not in START_TARGET_SUPPORTED_SEASONS]
    if undeclared:
        raise SystemExit(
            f"Seasons {undeclared!r} are outside the declared start-label population "
            f"{list(START_TARGET_SUPPORTED_SEASONS)!r}; the pre-registration would have to "
            "move before they could be read."
        )

    frame = _frame(archive_root, seasons)
    training = frame.loc[frame["season"].astype("string") == TRAINING_SEASON]
    scoring = frame.loc[frame["season"].astype("string") == SCORING_SEASON]

    base = tuple(column for column in component_feature_columns() if column in frame.columns)
    columns = start_feature_columns(base)

    start_model = fit_start_model(training, feature_columns=columns)
    if start_model is None:
        raise SystemExit(
            "The conditional start model refused the training season; a record cannot "
            "describe a fit that did not happen."
        )

    component_models = fit_component_models(training, feature_columns=base)
    if component_models is None:
        raise SystemExit("The component models refused the training season.")

    conditional = predict_start_given_appearance(start_model, scoring, feature_columns=columns)
    predicted = predict_components(component_models, scoring, feature_columns=base)
    appearance = pd.to_numeric(predicted["appearance_probability"], errors="coerce").astype(
        "Float64"
    )
    appearance.index = scoring.index
    composed = (appearance * conditional).astype("Float64")

    label = pd.to_numeric(scoring["start_target"], errors="coerce").astype("Float64")
    appeared = pd.to_numeric(scoring["appearance_target"], errors="coerce") == 1

    record: dict[str, object] = {
        "artifact_type": "record",
        "contract_version": PARTICIPATION_CALIBRATION_CONTRACT_VERSION,
        "prereg": "docs/participation_model_prereg.md",
        "descriptive_only": True,
        "promotion_decision": "none",
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "model_version": CONDITIONAL_START_MODEL_VERSION,
        "training_season": TRAINING_SEASON,
        "scoring_season": SCORING_SEASON,
        "declared_seasons": list(START_TARGET_SUPPORTED_SEASONS),
        "feature_columns": list(columns),
        "training_rows": start_model.training_rows,
        "scoring_rows": len(scoring),
        "scoring_appeared_rows": int(appeared.sum()),
        "conditional_start": {
            "pooled": _binary_metrics(conditional.loc[appeared], label.loc[appeared]),
            "by_position": _by_position(
                scoring.loc[appeared], conditional.loc[appeared], label.loc[appeared]
            ),
        },
        "composed_start": {
            "pooled": _binary_metrics(composed, label),
            "by_position": _by_position(scoring, composed, label),
        },
    }
    record.update(artifact_metadata(panel_rows=len(frame), history_seasons=list(seasons)))
    return record


def _bin_rows(metrics: dict[str, object]) -> str:
    bins = metrics.get("reliability_bins")
    if not isinstance(bins, list):
        return ""
    lines = [
        "| Bin | Observations | Mean probability | Observed rate |",
        "| --- | --- | --- | --- |",
    ]
    for entry in bins:
        if not isinstance(entry, dict):
            continue
        mean = entry.get("mean_probability")
        rate = entry.get("event_rate")
        span = f"{entry['lower_bound']:.1f} to {entry['upper_bound']:.1f}"
        lines.append(
            f"| {span} | {entry['observations']} | "
            f"{'-' if mean is None else f'{float(mean):.4f}'} | "
            f"{'-' if rate is None else f'{float(rate):.4f}'} |"
        )
    return "\n".join(lines)


def _headline(metrics: dict[str, object]) -> str:
    if not metrics.get("scored_rows"):
        return "No row was scored."
    return (
        f"{metrics['scored_rows']} rows, mean probability {float(metrics['mean_probability']):.4f} "
        f"against an observed rate of {float(metrics['event_rate']):.4f} "
        f"(bias {float(metrics['mean_calibration_bias']):+.4f}), "
        f"Brier {float(metrics['brier_score']):.4f}, log loss {float(metrics['log_loss']):.4f}."
    )


def summary(record: dict[str, object]) -> str:
    """Render the record from the record, so the prose cannot drift from the numbers."""

    conditional = record["conditional_start"]
    composed = record["composed_start"]
    assert isinstance(conditional, dict) and isinstance(composed, dict)
    conditional_pooled = conditional["pooled"]
    composed_pooled = composed["pooled"]
    assert isinstance(conditional_pooled, dict) and isinstance(composed_pooled, dict)

    return (
        "\n".join(
            [
                "# Participation calibration",
                "",
                f"Pre-registration: `{record['prereg']}`. Descriptive only: nothing is"
                " promoted, no threshold moves, the operational control is unchanged, and the"
                " locked 2025-26 holdout was not read.",
                "",
                f"Fitted on {record['training_season']} over"
                f" {record['training_rows']} appeared and labelled rows, then scored on"
                f" {record['scoring_season']} ({record['scoring_rows']} rows,"
                f" {record['scoring_appeared_rows']} of them appearances).",
                "",
                "## `q_start_given_appearance`, on appeared rows",
                "",
                _headline(conditional_pooled),
                "",
                _bin_rows(conditional_pooled),
                "",
                "## `p_start = p_appearance * q`",
                "",
                _headline(composed_pooled),
                "",
                _bin_rows(composed_pooled),
                "",
                "`p_appearance` is not re-measured here."
                " `docs/phase_c_component_evaluation.json` reports it on its own population,"
                " and re-reading it under this one would invite a comparison that is not"
                " like-for-like.",
            ]
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    arguments = parser.parse_args()

    record = measure(arguments.archive_root)

    conditional = record["conditional_start"]
    composed = record["composed_start"]
    assert isinstance(conditional, dict) and isinstance(composed, dict)
    for name, section in (("q_start_given_appearance", conditional), ("p_start", composed)):
        pooled = section["pooled"]
        assert isinstance(pooled, dict)
        print(f"{name}: {_headline(pooled)}")

    if arguments.dry_run:
        return 0

    # Checked here rather than before the numbers are printed: a dry run exists to show them,
    # and only a written record has to name the commit that produced it.
    provenance = record.get("provenance")
    if isinstance(provenance, dict) and provenance.get("working_tree_dirty"):
        print(
            "Refusing to write: the working tree is dirty, so the recorded commit would not "
            "describe the code that produced these numbers."
        )
        return 1
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, summary(record))
    print(f"Wrote {arguments.json_output} and {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
