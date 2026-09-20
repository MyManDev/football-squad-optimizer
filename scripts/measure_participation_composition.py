r"""Read what composing the control through the conditional start probability does.

    python -m scripts.measure_participation_composition \
        --table .../phase_c_component_oof_v1.csv \
        --roster .../phase_c_component_oof_v1.roster.csv \
        --manifest .../phase_c_component_oof_v1.manifest.json

**Descriptive. It promotes nothing, moves no threshold, states no gate and changes no
operational control.** There is no pre-registration to read here, and the reason is a
counted one rather than a preference: the archive declares ``starts`` over two seasons,
2023-24 is spent fitting, and what is left to judge on is one season. A gate written over
one season is a gate one season of noise can clear, so none is written.

Three arms, all fitted on 2023-24 and scored on 2024-25, sharing one appearance model and
differing only in the points side:

- ``uncomposed`` -- ``p_appearance * E[points | appearance]``, the control's construction;
- ``state_split`` -- the points model split by state and weighted by a scalar, the training
  season's own start rate. It knows that starters and substitutes score differently; it does
  not know which player is which;
- ``composed`` -- the same split weighted by ``q_start_given_appearance`` per row.

The ladder is what makes the reading attributable. A difference already present in
``state_split`` is the state split; a difference that appears only in ``composed`` is
rotation knowledge, which is also the only arm carrying a feature the control's points
design does not have.

Two things are read: the points error on 2024-25, on the whole population **and** on
appeared rows side by side, because 15,179 of the judged season's 26,303 handoff rows are
never appearances and a single all-rows number is mostly a reading of those; and the
decisions, over the judged season's 37 folds, solved under ``measurement_optimization_config``
and scored with the official autosub policy.

The locked 2025-26 holdout is refused before anything is read, and the record is never
overwritten.
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    measurement_optimization_config,
    solver_record,
    write_json,
    write_text,
)

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.evaluation import (
    EvaluationConfig,
    ScoringPolicy,
    evaluate_prepared_folds,
    prepare_phase_c_component_folds,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.component_handoff import LOCKED_HOLDOUT_SEASON
from squadopt.evaluation.participation_composition import (
    ARM_NAMES,
    PARTICIPATION_COMPOSITION_CONTRACT_VERSION,
    STATE_LABELS,
    compose_arms,
    fit_state_points,
    points_reading,
    realized_state,
    state_points,
)
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.features import CrossSeasonConfig
from squadopt.features.component_targets import START_TARGET_SUPPORTED_SEASONS
from squadopt.optimization.models import SolverStatus
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

DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "participation_composition.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "participation_composition.md"

#: Fitted on the first, judged on the second. Both are declared development seasons.
TRAINING_SEASON = "2023-24"
JUDGED_SEASON = "2024-25"

#: The panel the ridge walk-forward folds are built from, as the other decision runners
#: build them. The modelling frame is built from the two declared seasons alone, which is
#: what `measure_participation_calibration` fits on, so `q` here is the object that record
#: already read rather than a second one fitted on a wider panel.
DECISION_HISTORY_SEASONS = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
DECISION_SEASONS = DECISION_HISTORY_SEASONS[1:]

BOOTSTRAP_RESAMPLES = 2000
BLOCK_LENGTH = 4
INTERVAL_LEVEL = 0.90


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument(
        "--points-only",
        action="store_true",
        help="read the points error, skip the solves, write nothing",
    )
    return parser.parse_args(argv)


def modelling_frame(archive_root: Path, seasons: tuple[str, ...]) -> pd.DataFrame:
    """The repository's own component modelling frame, plus the team-strength control.

    Built the way `measure_participation_calibration` builds it, through
    `build_component_modelling_frame` rather than assembled here, so the design fitted is the
    design the estimators are fitted on -- including `fixture_count`, which the minutes bound
    needs and a hand-rolled join would silently omit.
    """

    panel = build_panel(archive_root, seasons=seasons)
    fixtures = build_fixture_panel(archive_root, seasons=seasons)
    team_codes = pd.concat(
        [load_team_codes(archive_root, season).assign(season=season) for season in seasons],
        ignore_index=True,
    )
    frame = build_component_modelling_frame(
        panel, fixtures, team_codes, seasons=seasons, config=COMPONENT_FEATURE_CONFIG
    )
    carried = attach_team_strength(panel).loc[
        :, ["season", "gameweek", "player_id", "position", TEAM_STRENGTH_COLUMN]
    ]
    joined = frame.merge(
        carried, on=["season", "gameweek", "player_id"], how="left", validate="one_to_one"
    )
    joined.index = frame.index
    return joined


def arm_forecasts(archive_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """The three arms on the judged season's rows, and what the fits were.

    Returns a frame keyed by season, gameweek and player id carrying one column per arm plus
    the pieces the record needs to describe them.
    """

    seasons = (TRAINING_SEASON, JUDGED_SEASON)
    undeclared = [season for season in seasons if season not in START_TARGET_SUPPORTED_SEASONS]
    if undeclared:
        raise SystemExit(
            f"Seasons {undeclared!r} are outside the declared start-label population "
            f"{list(START_TARGET_SUPPORTED_SEASONS)!r}."
        )

    frame = modelling_frame(archive_root, seasons)
    training = frame.loc[frame["season"].astype("string") == TRAINING_SEASON]
    judged = frame.loc[frame["season"].astype("string") == JUDGED_SEASON]

    base = tuple(column for column in component_feature_columns() if column in frame.columns)
    start_columns = start_feature_columns(base)

    components = fit_component_models(training, feature_columns=base)
    if components is None:
        raise SystemExit("The component models refused the training season.")
    start_model = fit_start_model(training, feature_columns=start_columns)
    if start_model is None:
        raise SystemExit("The conditional start model refused the training season.")
    points_models = fit_state_points(training, feature_columns=base)
    if points_models is None:
        raise SystemExit(
            "One of the three points row sets is thinner than the control's own minimum; "
            "a composition cannot be read from a fit that did not happen."
        )

    predicted = predict_components(components, judged, feature_columns=base)
    appearance = pd.to_numeric(predicted["appearance_probability"], errors="coerce").astype(
        "Float64"
    )
    appearance.index = judged.index
    conditional = predict_start_given_appearance(start_model, judged, feature_columns=start_columns)
    points = state_points(points_models, judged)
    arms = compose_arms(
        appearance,
        conditional,
        points,
        training_start_rate=points_models.training_start_rate,
    )

    # Every fitted column is prefixed. The frozen table already carries an (empty)
    # `q_start_given_appearance` and a (populated) `appearance_probability`, and a merge that
    # let those names collide would quietly hand the reading the table's columns instead of
    # these ones.
    carried = judged.loc[:, ["season", "gameweek", "player_id"]].copy(deep=True)
    for name in ARM_NAMES:
        carried[name] = arms[name]
    carried["fitted_q"] = conditional
    carried["fitted_appearance_probability"] = appearance
    carried["fitted_start_target"] = judged["start_target"]
    fits = {
        "component_model_version": components.model_version,
        "component_appearance_rows": components.appearance_rows,
        "component_conditional_rows": components.conditional_rows,
        "start_model_version": CONDITIONAL_START_MODEL_VERSION,
        "start_training_rows": start_model.training_rows,
        "points_pooled_rows": points_models.pooled_rows,
        "points_started_rows": points_models.started_rows,
        "points_substitute_rows": points_models.substitute_rows,
        "training_start_rate": points_models.training_start_rate,
        "feature_columns": list(base),
        "start_feature_columns": list(start_columns),
        "modelling_frame_rows": len(frame),
    }
    return carried, fits


def joined_rows(handoff_rows: pd.DataFrame, forecasts: pd.DataFrame) -> pd.DataFrame:
    """The judged season's handoff rows with the three arms attached, plus the outcome.

    The join is on the handoff's own key. A handoff row the two-season fit cannot price keeps
    a missing value in every arm, so all three fall back through the same route rather than
    one of them being quietly filled.
    """

    rows = handoff_rows.loc[handoff_rows["season"].astype(str) == JUDGED_SEASON].copy(deep=True)
    keyed = forecasts.rename(columns={"gameweek": "target_gameweek"})
    keyed["season"] = keyed["season"].astype(str)
    keyed["target_gameweek"] = keyed["target_gameweek"].astype("int64")
    keyed["player_id"] = keyed["player_id"].astype("int64")
    collisions = sorted(
        set(keyed.columns) & set(rows.columns) - {"season", "target_gameweek", "player_id"}
    )
    if collisions:
        raise SystemExit(
            f"The fitted columns {collisions!r} share a name with the handoff's own. A merge "
            "would decide silently which one the reading gets."
        )
    merged = rows.merge(
        keyed, on=["season", "target_gameweek", "player_id"], how="left", validate="one_to_one"
    )
    merged.index = rows.index
    appeared = pd.to_numeric(merged["appearance_target"], errors="coerce") == 1
    merged["realized_points"] = (
        pd.to_numeric(merged["points_target"], errors="coerce")
        .astype("float64")
        .where(appeared, 0.0)
    )
    merged["appeared"] = appeared
    # The start label comes from the panel, never from the frozen table's own `start_target`,
    # which is empty on every row because it was written before the label was declared.
    merged["state"] = realized_state(merged["appearance_target"], merged["fitted_start_target"])
    return merged


def points_block(rows: pd.DataFrame) -> dict[str, Any]:
    """The points error for every arm, on both populations and then sliced.

    The whole population and the appeared rows are reported beside each other rather than one
    after the other, because most of this population never appears and an all-rows number is
    mostly a reading of rows whose outcome is a zero both arms already price near zero.

    The position comes from the handoff's own rows, which the reader has already joined to the
    decision roster, rather than from a second join here that could disagree with it.
    """

    position = rows["position"].astype("string")
    appeared = rows["appeared"]
    realized = rows["realized_points"]

    block: dict[str, Any] = {
        "judged_rows": len(rows),
        "appeared_rows": int(appeared.sum()),
        "rows_without_a_fitted_forecast": int(rows["uncomposed"].isna().sum()),
        "rows_where_q_is_present": int(rows["fitted_q"].notna().sum()),
        "rows_with_a_start_label": int(rows["state"].notna().sum()),
        "rows_where_composed_differs_from_uncomposed": int(
            (rows["composed"].astype("Float64") != rows["uncomposed"].astype("Float64"))
            .fillna(False)
            .sum()
        ),
        "arms": {},
    }
    for name in ARM_NAMES:
        forecast = rows[name]
        by_state = {
            label: points_reading(
                forecast.loc[rows["state"] == label], realized.loc[rows["state"] == label]
            )
            for label in STATE_LABELS
        }
        by_position = {
            str(label): points_reading(
                forecast.loc[position == label], realized.loc[position == label]
            )
            for label in sorted(position.dropna().unique())
        }
        block["arms"][name] = {
            "whole_population": points_reading(forecast, realized),
            "appeared_rows": points_reading(forecast.loc[appeared], realized.loc[appeared]),
            "by_state": by_state,
            "by_position": by_position,
        }
    return block


def _scores(result: Any) -> dict[str, float]:
    return {
        item.fold_id: float(item.realized_squad_points)
        for item in result.folds
        if item.realized_squad_points is not None
    }


def _squads(result: Any) -> dict[str, frozenset[int]]:
    return {
        item.fold_id: frozenset(
            int(value) for value in item.optimization_result.selected_squad["player_id"]
        )
        for item in result.folds
        if item.optimization_result.has_solution
    }


def _arm_summary(result: Any) -> dict[str, Any]:
    solved = [item for item in result.folds if item.optimization_result.has_solution]
    proven = sum(
        1 for item in solved if item.optimization_result.solver_status is SolverStatus.OPTIMAL
    )
    values = list(_scores(result).values())
    return {
        "scored_decisions": len(values),
        "mean_realized_points": sum(values) / len(values) if values else None,
        # The count as well as the share. A decision mean over unproved solves is a different
        # object from one over proofs, and a reader who cannot tell which cannot tell whether
        # a re-run would move it. The share alone makes that arithmetic rather than reading.
        "solved_decisions": len(solved),
        "proved_decisions": proven,
        "proven_share": proven / len(solved) if solved else 0.0,
    }


def decision_block(results: Mapping[str, Any], order: Sequence[str]) -> dict[str, Any]:
    """Every arm against ``uncomposed`` on the same folds, paired decision by decision."""

    scores = {name: _scores(result) for name, result in results.items()}
    squads = {name: _squads(result) for name, result in results.items()}
    base = scores["uncomposed"]
    block: dict[str, Any] = {"arms": {}, "paired_against_uncomposed": {}}
    for name, result in results.items():
        block["arms"][name] = _arm_summary(result)
    for name in ARM_NAMES:
        if name == "uncomposed":
            continue
        paired = [fold for fold in order if fold in base and fold in scores[name]]
        differences = [scores[name][fold] - base[fold] for fold in paired]
        if not differences:
            block["paired_against_uncomposed"][name] = {"paired_decisions": 0}
            continue
        pairs = [(fold[:7], value) for fold, value in zip(paired, differences, strict=True)]
        interval = (
            season_aware_moving_block_interval(
                pairs,
                policy=PromotionPolicy(
                    bootstrap_resamples=BOOTSTRAP_RESAMPLES, moving_block_length=BLOCK_LENGTH
                ),
                candidate_id=f"{PARTICIPATION_COMPOSITION_CONTRACT_VERSION}:{name}",
            )
            if len(pairs) >= 2
            else None
        )
        block["paired_against_uncomposed"][name] = {
            "paired_decisions": len(differences),
            "mean_difference": sum(differences) / len(differences),
            "interval": None if interval is None else [float(interval[0]), float(interval[1])],
            "interval_level": INTERVAL_LEVEL,
            "interval_block_length": BLOCK_LENGTH,
            "interval_resamples": BOOTSTRAP_RESAMPLES,
            # One judged season: the block bootstrap resamples weeks inside it and cannot
            # speak to season-to-season variation. Named here rather than left to a reader.
            "interval_covers_one_season": True,
            "wins": sum(value > 0 for value in differences),
            "ties": sum(value == 0 for value in differences),
            "losses": sum(value < 0 for value in differences),
            "decisions_with_a_different_squad": sum(
                1 for fold in paired if squads["uncomposed"].get(fold) != squads[name].get(fold)
            ),
        }
    return block


def _points_table(block: Mapping[str, Any]) -> list[str]:
    lines = [
        "| arm | all rows: mean error | all rows: MAE | appeared rows: mean error"
        " | appeared rows: MAE |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in ARM_NAMES:
        whole = block["arms"][name]["whole_population"]
        appeared = block["arms"][name]["appeared_rows"]
        lines.append(
            f"| `{name}` | {whole['mean_error']:+.4f} | {whole['mean_absolute_error']:.4f} | "
            f"{appeared['mean_error']:+.4f} | {appeared['mean_absolute_error']:.4f} |"
        )
    return lines


def _state_table(block: Mapping[str, Any]) -> list[str]:
    lines = [
        "| arm | " + " | ".join(f"{label}: mean error" for label in STATE_LABELS) + " |",
        "| --- | " + " | ".join("---:" for _ in STATE_LABELS) + " |",
    ]
    for name in ARM_NAMES:
        cells = []
        for label in STATE_LABELS:
            reading = block["arms"][name]["by_state"][label]
            cells.append("n/a" if not reading.get("rows") else f"{reading['mean_error']:+.4f}")
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    return lines


def markdown(record: Mapping[str, Any]) -> str:
    points = record["points"]
    decisions = record.get("decisions")
    lines = [
        "# Composing the control through the conditional start probability",
        "",
        f"Contract `{record['contract_version']}`. **Descriptive.** Nothing is promoted, no"
        " threshold moves, no gate is stated, the operational control is unchanged and the"
        " locked 2025-26 holdout was not read.",
        "",
        "## Why there is no gate here",
        "",
        record["why_one_judged_season"],
        "",
        "## The three arms",
        "",
        "All three are fitted on "
        f"{record['training_season']} and read on {record['judged_season']}, share one"
        " appearance model, and differ only in the points side.",
        "",
        "```text",
        "uncomposed  = p_appearance * E[points | appearance]",
        "state_split = p_appearance * (c * E[points | start] + (1 - c) * E[points | substitute])",
        "composed    = p_appearance * (q * E[points | start] + (1 - q) * E[points | substitute])",
        "```",
        "",
        f"`c` is the training season's own start rate among appeared rows,"
        f" {float(record['fits']['training_start_rate']):.4f}, so `state_split` knows that the"
        " two states score differently and knows nothing about which player is which. `q` is"
        f" `{record['fits']['start_model_version']}`, fitted on"
        f" {record['fits']['start_training_rows']} appeared and labelled rows. The state"
        f" points models are the control's own ridge over"
        f" {record['fits']['points_started_rows']} started and"
        f" {record['fits']['points_substitute_rows']} substitute rows against the pooled"
        f" fit's {record['fits']['points_pooled_rows']}.",
        "",
        "## Points error",
        "",
        f"{points['judged_rows']} rows of the judged season, {points['appeared_rows']} of them"
        " appearances. Both populations are reported together because the majority never"
        " appears and an all-rows number is mostly a reading of those rows. A realized value"
        " is `points_target` on an appearance and zero elsewhere; error is forecast minus"
        " realized, so a positive number is over-forecasting.",
        "",
        *_points_table(points),
        "",
        "By realized state, mean error:",
        "",
        *_state_table(points),
        "",
        f"`q` is present on {points['rows_where_q_is_present']} rows, and `composed` differs"
        f" from `uncomposed` on {points['rows_where_composed_differs_from_uncomposed']}."
        f" {points['rows_without_a_fitted_forecast']} rows carry no fitted forecast in any arm"
        " and fall back identically in all three.",
        "",
    ]
    if decisions is None:
        lines += ["## Decisions", "", "Not run in this record.", ""]
        return "\n".join(lines) + "\n"

    lines += [
        "## Decisions",
        "",
        "| arm | decisions | mean realized points | proved optimal |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in ARM_NAMES:
        summary = decisions["arms"][name]
        proved = summary.get("proved_decisions")
        solved = summary.get("solved_decisions")
        share = (
            f"{summary['proven_share']:.2f}"
            if proved is None or solved is None
            else f"{proved} of {solved}"
        )
        lines.append(
            f"| `{name}` | {summary['scored_decisions']} | "
            f"{float(summary['mean_realized_points']):.3f} | {share} |"
        )
    lines += [
        "",
        "Paired against `uncomposed`, decision by decision:",
        "",
        "| arm | decisions | mean difference | interval | W/T/L | different squad |",
        "| --- | ---: | ---: | --- | ---: | ---: |",
    ]
    for name in ARM_NAMES:
        if name == "uncomposed":
            continue
        paired = decisions["paired_against_uncomposed"][name]
        interval = paired.get("interval")
        lines.append(
            f"| `{name}` | {paired['paired_decisions']} | {paired['mean_difference']:+.3f} | "
            + ("n/a" if interval is None else f"[{interval[0]:+.3f}, {interval[1]:+.3f}]")
            + f" | {paired['wins']}/{paired['ties']}/{paired['losses']} | "
            f"{paired['decisions_with_a_different_squad']} |"
        )
    lines += [
        "",
        "The interval is a moving-block bootstrap over the weeks of one season. It describes"
        " how much these 37 weeks move; it cannot describe how much the next season would.",
        "",
        "## What would make this a gate, and when",
        "",
        record["follow_up"],
        "",
        "## What else was running",
        "",
        record["machine"],
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    if not arguments.points_only and arguments.json_output.exists():
        print(f"{arguments.json_output} exists; retire it in its own commit before re-running.")
        return 1
    handoff = read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    seasons = {str(value) for value in handoff.rows["season"].unique()}
    if LOCKED_HOLDOUT_SEASON in seasons or handoff.development_contract is not None:
        print("Only the frozen v1 development handoff is read.")
        return 1
    if JUDGED_SEASON not in seasons:
        print(f"The handoff carries no {JUDGED_SEASON} decisions.")
        return 1

    started = datetime.now(UTC)
    forecasts, fits = arm_forecasts(arguments.archive_root)
    rows = joined_rows(handoff.rows, forecasts)
    points = points_block(rows)

    record: dict[str, Any] = {
        "contract_version": PARTICIPATION_COMPOSITION_CONTRACT_VERSION,
        "generated_at_utc": started.replace(microsecond=0).isoformat(),
        "descriptive_only": True,
        "promotion_decision": "none",
        "gate": None,
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "training_season": TRAINING_SEASON,
        "judged_season": JUDGED_SEASON,
        "declared_start_seasons": list(START_TARGET_SUPPORTED_SEASONS),
        "why_one_judged_season": (
            "`START_TARGET_SUPPORTED_SEASONS` declares the archive's `starts` label over"
            " 2023-24 and 2024-25 and no other season. 2022-23 carries the column and not its"
            " values, summing to zero over GW1-GW15 beside normal minutes, and"
            " `src/squadopt/data/cleaning.py` refuses a partly populated canonical column"
            ' ("complete, so supply the values or drop the column"), so the season goes'
            " whole. 2025-26"
            " carries the column and is the locked holdout. Two declared seasons, one spent on"
            " the fit, leaves one judged season. A threshold written over one season is a"
            " threshold one season of noise can clear, so this record states none and asks to"
            " be read as a description."
        ),
        "follow_up": (
            "The second judged season is the **live 2026-27 season**, not the locked 2025-26"
            " holdout, which stays locked: nothing here loads it, lists it or hashes it, and"
            " reading it early would spend the one season that could confirm this one. After"
            " gameweek 9 the live record can offer the weeks it has settled by then, and the"
            " same three arms are read on them."
            " The label there is **not** the archive's `starts`."
            " `docs/rotation_evidence_prereg.md` declares the prospective source as a settled"
            " capture's `stats.starts > 0` and admits a gameweek only once its"
            " `rotation_evidence_v1` artifact and its settled outcome are both on disk. That"
            " dependency is the plan's first step rather than an assumption behind it: no such"
            " artifact exists under `data/` today, checked by listing rather than taken on"
            " trust, so the follow-up begins by establishing whether the weeks it needs carry"
            " one, and reports that it does not rather than quietly reading a shorter"
            " population. Only with a second judged season in hand is it worth asking whether a"
            " gate is worth writing, and that gate would be pre-registered before the run and"
            " never after it."
        ),
        "machine": (
            "Another session's parallel `pytest -n 2` run was on this machine while these"
            " solves ran, and a third session holds the live backend. Both solver limits are"
            " deterministic, so no number in this record moves under that load; `elapsed_seconds`"
            " does, and is not a quiet-machine timing."
        ),
        "table_sha256": handoff.table_sha256,
        "roster_sha256": handoff.roster_sha256,
        "manifest_sha256": handoff.manifest_sha256,
        "producer_repository_commit": handoff.repository_commit,
        "fits": fits,
        "points": points,
    }

    if arguments.points_only:
        record["decisions"] = None
        print(markdown(record))
        return 0

    panel = build_panel(arguments.archive_root, seasons=DECISION_HISTORY_SEASONS)
    ridge = build_walk_forward_folds(
        panel,
        seasons=DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    order = [
        fold
        for fold in handoff.rows["fold_id"].astype(str).drop_duplicates().tolist()
        if fold.startswith(JUDGED_SEASON)
    ]
    controls = tuple(fold for fold in ridge if fold.fold_id in set(order))
    if [fold.fold_id for fold in controls] != order:
        print("The ridge folds do not cover the judged season's decisions in the same order.")
        return 1

    judged_rows = handoff.rows.loc[handoff.rows["fold_id"].astype(str).isin(order)]
    judged = replace(
        handoff,
        rows=judged_rows,
        roster=handoff.roster.loc[handoff.roster["fold_id"].astype(str).isin(order)],
    )
    config = EvaluationConfig(
        optimization_config=measurement_optimization_config(),
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        run_metadata={"study": PARTICIPATION_COMPOSITION_CONTRACT_VERSION},
    )
    priced = judged_rows["control_expected_points"].notna()
    results: dict[str, Any] = {}
    for name in ARM_NAMES:
        # A `direct_control` row keeps its missing value so every arm falls back through the
        # same route; only rows the handoff itself priced are replaced.
        arm = replace(
            judged,
            rows=judged_rows.assign(
                control_expected_points=rows[name].astype("Float64").where(priced)
            ),
        )
        results[name] = evaluate_prepared_folds(
            prepare_phase_c_component_folds(arm, controls), config
        )
        print(f"{name}: {_arm_summary(results[name])}")

    record["decisions"] = decision_block(results, order)
    record["solver"] = solver_record(*results.values())
    record["elapsed_seconds"] = (datetime.now(UTC) - started).total_seconds()
    record.update(artifact_metadata(panel_rows=len(panel), history_seasons=list(seasons)))

    provenance = record.get("provenance")
    if isinstance(provenance, dict) and provenance.get("working_tree_dirty"):
        print(
            "Refusing to write: the working tree is dirty, so the recorded commit would not "
            "describe the code that produced these numbers."
        )
        print(markdown(record))
        return 1
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, markdown(record))
    print(markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
