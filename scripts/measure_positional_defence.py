r"""Read the positional structure for goalkeepers and defenders, as its protocol fixes it.

    python -m scripts.measure_positional_defence \
        --table .../phase_c_component_oof_v1.csv \
        --roster .../phase_c_component_oof_v1.roster.csv \
        --manifest .../phase_c_component_oof_v1.manifest.json

Protocol: ``docs/positional_defence_prereg.md``, whose population, candidate, three clauses,
tolerance and drop rule are fixed there and only read here. The gate is read once: this
refuses to overwrite its own record, refuses the locked holdout before anything is loaded,
and refuses a working tree that does not describe the code that produced the numbers.

**Three constants the protocol did not fix, and where they come from.** It names
``fit_clean_sheet_calibration`` and says the recalibration is one that function "already
performs", so the constants that function and its rating need are inherited from the study
that declares them, ``experiments/team_rating_cs.py``'s ``CsRemeasureConfig``, rather than
chosen here: the calibration's ``first_gameweek`` (6), the half-life and ridge grids
``select_dixon_coles_config`` searches, and the seasons the rating is fitted over. Inheriting
a declared value is not selecting one; each is named in the record beside the config it came
from, and none is touched again whatever the run says. That config's own
``evaluated_seasons`` is already exactly this protocol's three judged seasons.
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
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    EvaluationConfig,
    ScoringPolicy,
    evaluate_prepared_folds,
    prepare_phase_c_component_folds,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.component_handoff import LOCKED_HOLDOUT_SEASON
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.experiments.positional_defence import (
    DEFENCE_POSITIONS,
    JUDGED_SEASONS,
    MINIMUM_TRAINING_ROWS,
    POSITIONAL_DEFENCE_CONTRACT_VERSION,
    accuracy_clause,
    bonus_by_position,
    calibration_by_decile,
    candidate_points,
    club_codes,
    decision_clause,
    eligible_rows,
    long_indicator,
    mean_absolute_error,
    ordering_clause,
    positional_defence_gate,
    realized_bonus,
    training_row_counts,
    within_position_rank,
)
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.experiments.team_rating import (
    calibrated_clean_sheet,
    fit_clean_sheet_calibration,
    fit_dixon_coles,
    load_match_results,
    measure_promoted_prior,
    promoted_clubs,
    select_dixon_coles_config,
)
from squadopt.experiments.team_rating_cs import CsRemeasureConfig
from squadopt.features import CrossSeasonConfig
from squadopt.optimization.models import SolverStatus

DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "positional_defence.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "positional_defence.md"

#: Inherited from `CsRemeasureConfig`, not chosen here. See the module docstring.
RATING = CsRemeasureConfig()

#: The panel the ridge walk-forward folds are built from, as the other decision runners do.
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
        "--readings-only",
        action="store_true",
        help="read clauses 1 and 2, skip the solves and clause 3, write nothing",
    )
    return parser.parse_args(argv)


def clean_sheet_table(archive_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """A recalibrated clean-sheet probability per judged season, gameweek and club.

    Walked forward: for each judged season the configuration, the promoted prior and the
    calibration are fitted on strictly earlier seasons, and the rating itself is refitted at
    each gameweek's first kickoff so it never sees the fixtures it prices.
    """

    matches = load_match_results(archive_root, RATING.seasons)
    promoted = promoted_clubs(matches)
    rows: list[dict[str, Any]] = []
    chosen_by_season: dict[str, Any] = {}
    for season in JUDGED_SEASONS:
        earlier = [value for value in RATING.seasons if value < season]
        training = matches.loc[matches["season"].isin(earlier)]
        chosen = select_dixon_coles_config(
            training,
            earlier,
            half_life_grid=RATING.half_life_grid,
            ridge_grid=RATING.ridge_grid,
            first_gameweek=RATING.first_evaluated_gameweek,
        )
        prior = measure_promoted_prior(matches, earlier, chosen)
        calibration = fit_clean_sheet_calibration(
            training, earlier[1:], chosen, first_gameweek=RATING.first_evaluated_gameweek
        )
        chosen_by_season[season] = {
            "half_life_days": chosen.half_life_days,
            "ridge": chosen.ridge,
            "training_seasons": list(earlier),
            "calibration_intercept": calibration[0],
            "calibration_slope": calibration[1],
            "promoted_prior": list(prior),
        }
        arrivals = promoted.get(season, ())
        judged = matches.loc[matches["season"] == season]
        for gameweek in sorted(int(value) for value in judged["gameweek"].unique()):
            block = judged.loc[judged["gameweek"] == gameweek]
            as_of = pd.Timestamp(block["kickoff"].min())
            if matches.loc[matches["kickoff"] < as_of].empty:
                continue
            rating = fit_dixon_coles(
                matches,
                as_of=as_of,
                config=chosen,
                promoted_prior=prior,
                newly_promoted=arrivals,
            )
            for record in block.to_dict("records"):
                home = int(record["home_club"])
                away = int(record["away_club"])
                for is_home, club, opponent, conceded in (
                    (True, home, away, int(record["away_goals"])),
                    (False, away, home, int(record["home_goals"])),
                ):
                    raw = rating.clean_sheet_probability(club, opponent, is_home=is_home)
                    rows.append(
                        {
                            "season": str(season),
                            "gameweek": gameweek,
                            "club": club,
                            "raw_clean_sheet": float(raw),
                            "clean_sheet_probability": calibrated_clean_sheet(calibration, raw),
                            "clean_sheet_happened": 1.0 if conceded == 0 else 0.0,
                        }
                    )
    return pd.DataFrame(rows), chosen_by_season


def priced_rows(
    handoff_rows: pd.DataFrame, archive_root: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """The protocol's population with the candidate priced on it, and what that took."""

    rows, counts = eligible_rows(handoff_rows)
    roster_clubs = club_codes(archive_root, JUDGED_SEASONS)
    rows = rows.merge(
        roster_clubs,
        left_on=["season", "team_id"],
        right_on=["season", "team_id"],
        how="left",
        validate="many_to_one",
    )
    sheets, chosen = clean_sheet_table(archive_root)
    rows = rows.merge(
        sheets,
        left_on=["season", "target_gameweek", "club"],
        right_on=["season", "gameweek", "club"],
        how="left",
        validate="many_to_one",
    )
    bonus_rows = realized_bonus(archive_root, RATING.seasons)
    bonus: dict[str, dict[str, float]] = {}
    training_rows: dict[str, int] = {}
    for season in JUDGED_SEASONS:
        earlier = [value for value in RATING.seasons if value < season]
        bonus[season] = bonus_by_position(bonus_rows, earlier)
        training_rows[season] = training_row_counts(bonus_rows, earlier)

    long = long_indicator(rows)
    candidate = pd.Series(pd.NA, index=rows.index, dtype="Float64")
    for season in JUDGED_SEASONS:
        selected = rows["season"].astype("string") == season
        if not bool(selected.any()):
            continue
        candidate.loc[selected] = candidate_points(
            rows.loc[selected],
            long.loc[selected],
            rows.loc[selected, "clean_sheet_probability"],
            bonus[season],
        )
    appeared = pd.to_numeric(rows["appearance_target"], errors="coerce") == 1
    rows = rows.assign(
        long=long,
        candidate_expected_points=candidate,
        appeared=appeared,
        realized_points=pd.to_numeric(rows["points_target"], errors="coerce")
        .astype("float64")
        .where(appeared, 0.0),
    )
    detail = {
        "population": {
            "rows_before_drops": counts.rows_before_drops,
            "appeared_before_drops": counts.appeared_before_drops,
            "direct_control_dropped": counts.direct_control_dropped,
            "double_gameweek_dropped": counts.double_gameweek_dropped,
            "blank_gameweek_dropped": counts.blank_gameweek_dropped,
            "dropped_by_both": counts.dropped_by_both,
            "rows": counts.rows,
            "appeared_rows": counts.appeared_rows,
            "rows_without_a_club_rating": int(rows["clean_sheet_probability"].isna().sum()),
            "rows_without_a_long_indicator": int(rows["long"].isna().sum()),
            "rows_the_candidate_could_not_price": int(
                rows["candidate_expected_points"].isna().sum()
            ),
            "blank_gameweek_rule_note": (
                "The protocol drops a row whose club has no fixture that gameweek beside the"
                " doubles. On this population that rule binds on nothing: `fixture_count`"
                " takes only the values 1 and 2. It is implemented and its zero is reported"
                " anyway, because a rule that binds on nothing today and is quietly left out"
                " is a rule that binds on something tomorrow and is not there."
            ),
        },
        "rating": {
            "inherited_from": "experiments/team_rating_cs.py CsRemeasureConfig",
            "protocol_fixed_these": False,
            "seasons": list(RATING.seasons),
            "calibration_first_gameweek": RATING.first_evaluated_gameweek,
            "half_life_grid": list(RATING.half_life_grid),
            "ridge_grid": list(RATING.ridge_grid),
            "selected_by_season": chosen,
        },
        "bonus_by_position": {season: dict(values) for season, values in bonus.items()},
        "training_rows_by_season": training_rows,
        "minimum_training_rows": MINIMUM_TRAINING_ROWS,
        "seasons_refused_for_thin_training": sorted(
            season for season, count in training_rows.items() if count < MINIMUM_TRAINING_ROWS
        ),
    }
    return rows, detail


def _paired_by_decision(
    rows: pd.DataFrame,
) -> list[tuple[str, float]]:
    """Per decision, the candidate's mean absolute error minus the control's.

    The unit is the decision and not the row, because players inside one gameweek share
    fixtures. The protocol fixes that, and the two conventions differ by about an order of
    magnitude in width, so it may not be chosen once the widths are visible.
    """

    pairs: list[tuple[str, float]] = []
    for fold_id, block in rows.groupby(rows["fold_id"].astype(str), sort=True):
        candidate = mean_absolute_error(
            block["candidate_expected_points"], block["realized_points"]
        )
        control = mean_absolute_error(block["control_expected_points"], block["realized_points"])
        if candidate is None or control is None:
            continue
        pairs.append((str(fold_id)[:7], candidate - control))
    return pairs


def readings(rows: pd.DataFrame) -> dict[str, Any]:
    """Clauses 1 and 2, read where the protocol says to read them."""

    appeared = rows.loc[rows["appeared"]]
    pairs = _paired_by_decision(appeared)
    interval = (
        season_aware_moving_block_interval(
            pairs,
            policy=PromotionPolicy(
                bootstrap_resamples=BOOTSTRAP_RESAMPLES, moving_block_length=BLOCK_LENGTH
            ),
            candidate_id=POSITIONAL_DEFENCE_CONTRACT_VERSION,
        )
        if len(pairs) >= 2
        else None
    )
    # The paired quantity is candidate minus control, so a negative mean is an improvement
    # and the clause wants the interval's lower bound above zero on the improvement, which
    # is the negated difference. Negating here keeps the sign the protocol's words use.
    negated = None if interval is None else (-float(interval[1]), -float(interval[0]))
    mean_difference = -sum(value for _, value in pairs) / len(pairs) if pairs else None

    by_season: dict[str, dict[str, float | None]] = {}
    for season in JUDGED_SEASONS:
        block = appeared.loc[appeared["season"].astype("string") == season]
        by_season[season] = {
            "candidate": mean_absolute_error(
                block["candidate_expected_points"], block["realized_points"]
            ),
            "control": mean_absolute_error(
                block["control_expected_points"], block["realized_points"]
            ),
            "rows": len(block),
        }
    floor = {
        "candidate": mean_absolute_error(
            rows["candidate_expected_points"], rows["realized_points"]
        ),
        "control": mean_absolute_error(rows["control_expected_points"], rows["realized_points"]),
        "rows": len(rows),
    }
    accuracy = accuracy_clause(
        {
            "mean_difference": mean_difference,
            "interval": negated,
            "paired_decisions": len(pairs),
        },
        by_season,
        floor,
    )

    season_ranks: dict[str, dict[str, dict[str, float | None]]] = {}
    for season in JUDGED_SEASONS:
        block = appeared.loc[appeared["season"].astype("string") == season]
        candidate = within_position_rank(
            block, block["candidate_expected_points"], block["realized_points"]
        )
        control = within_position_rank(
            block, block["control_expected_points"], block["realized_points"]
        )
        season_ranks[season] = {
            position: {"candidate": candidate[position], "control": control[position]}
            for position in DEFENCE_POSITIONS
        }
    # Pooled for a rank is the mean of the seasons' own correlations, because a correlation
    # pooled across seasons would rank players from different seasons against each other.
    pooled: dict[str, dict[str, float | None]] = {}
    for position in DEFENCE_POSITIONS:
        pooled[position] = {}
        for arm in ("candidate", "control"):
            values = [
                season_ranks[season][position][arm]
                for season in JUDGED_SEASONS
                if season_ranks[season][position][arm] is not None
            ]
            pooled[position][arm] = (
                sum(float(value) for value in values) / len(values) if values else None
            )
    ordering = ordering_clause(season_ranks, pooled)
    return {"accuracy": accuracy, "ordering": ordering, "paired_decisions": len(pairs)}


def reported_not_gated(rows: pd.DataFrame) -> dict[str, Any]:
    """Everything the protocol asks to be reported without gating on it."""

    appeared = rows.loc[rows["appeared"]]
    happened = pd.to_numeric(rows["clean_sheet_happened"], errors="coerce")
    split: dict[str, Any] = {}
    for label, selected in (("clean_sheet", happened == 1.0), ("conceded", happened == 0.0)):
        block = appeared.loc[selected.loc[appeared.index].fillna(False)]
        split[label] = {
            "rows": len(block),
            "candidate": mean_absolute_error(
                block["candidate_expected_points"], block["realized_points"]
            ),
            "control": mean_absolute_error(
                block["control_expected_points"], block["realized_points"]
            ),
        }
    by_position: dict[str, Any] = {}
    for position in DEFENCE_POSITIONS:
        block = appeared.loc[appeared["position"].astype("string") == position]
        by_position[position] = {
            "appeared_rows": len(block),
            "candidate": mean_absolute_error(
                block["candidate_expected_points"], block["realized_points"]
            ),
            "control": mean_absolute_error(
                block["control_expected_points"], block["realized_points"]
            ),
        }
    return {
        "clean_sheet_calibration_by_decile": list(
            calibration_by_decile(rows["clean_sheet_probability"], rows["clean_sheet_happened"])
        ),
        "error_by_whether_the_clean_sheet_happened": split,
        "by_position_on_appeared_rows": by_position,
    }


def _scores(result: Any) -> dict[str, float]:
    return {
        item.fold_id: float(item.realized_squad_points)
        for item in result.folds
        if item.realized_squad_points is not None
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
        # a re-run would move it.
        "solved_decisions": len(solved),
        "proved_decisions": proven,
        "proven_share": proven / len(solved) if solved else 0.0,
    }


def _markdown(record: Mapping[str, Any]) -> str:
    gate = record["gate"]
    accuracy = record["accuracy"]
    ordering = record["ordering"]
    population = record["detail"]["population"]
    lines = [
        "# A positional structure for goalkeepers and defenders",
        "",
        f"Contract `{record['contract_version']}`. Protocol:"
        f" `{record['prereg']}`. Verdict: **`{gate['verdict']}`**.",
        "",
        f"Population: {population['rows']} goalkeeper and defender rows over the judged"
        f" seasons' decisions from target gameweek 4, {population['appeared_rows']} of them"
        f" appearances. Before the drop rules there were {population['rows_before_drops']} rows"
        f" and {population['appeared_before_drops']} appearances;"
        f" {population['direct_control_dropped']} `direct_control` rows,"
        f" {population['double_gameweek_dropped']} double-gameweek rows and"
        f" {population['blank_gameweek_dropped']} blank-gameweek rows were removed,"
        f" {population['dropped_by_both']} of them by more than one rule.",
        "",
        "## Clause 1: accuracy",
        "",
        f"Binding, on appeared rows: mean improvement"
        f" {accuracy['binding_on_appeared_rows']['mean_difference']}, interval"
        f" {accuracy['binding_on_appeared_rows']['interval']},"
        f" improves every judged season"
        f" {accuracy['binding_on_appeared_rows']['improves_every_judged_season']}."
        f" Passes: **{accuracy['binding_on_appeared_rows']['passes']}**.",
        "",
        f"Floor, over the {population['rows']} surviving rows: candidate"
        f" {accuracy['floor_over_surviving_rows']['candidate']} against control"
        f" {accuracy['floor_over_surviving_rows']['control']}."
        f" Passes: **{accuracy['floor_over_surviving_rows']['passes']}**.",
        "",
        "## Clause 2: ordering",
        "",
        f"Within-position Spearman on appeared rows, tolerance {ordering['tolerance']}."
        f" Passes: **{ordering['passes']}**.",
        "",
    ]
    decision = record.get("decision")
    if decision is None:
        lines += ["## Clause 3: decisions", "", "Not run in this record.", ""]
        return "\n".join(lines) + "\n"
    lines += [
        "## Clause 3: decisions",
        "",
        f"{decision['paired_decisions']} paired decisions, mean difference"
        f" {decision['mean_difference']}, losing seasons {decision['losing_seasons']}."
        f" Passes: **{decision['passes']}**. The interval"
        f" {decision['interval']} is reported and does not gate.",
        "",
        "## What else was running",
        "",
        record["machine"],
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    if not arguments.readings_only and arguments.json_output.exists():
        print(f"{arguments.json_output} exists; a gate is read once. Retire it in its own commit.")
        return 1
    handoff = read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    seasons = {str(value) for value in handoff.rows["season"].unique()}
    if LOCKED_HOLDOUT_SEASON in seasons or handoff.development_contract is not None:
        print("Only the frozen v1 development handoff is read.")
        return 1

    started = datetime.now(UTC)
    rows, detail = priced_rows(handoff.rows, arguments.archive_root)
    if detail["seasons_refused_for_thin_training"]:
        print(
            "Judged seasons with fewer than "
            f"{MINIMUM_TRAINING_ROWS} appeared training rows: "
            f"{detail['seasons_refused_for_thin_training']}"
        )
    read = readings(rows)
    record: dict[str, Any] = {
        "contract_version": POSITIONAL_DEFENCE_CONTRACT_VERSION,
        "prereg": "docs/positional_defence_prereg.md",
        "generated_at_utc": started.replace(microsecond=0).isoformat(),
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "table_sha256": handoff.table_sha256,
        "roster_sha256": handoff.roster_sha256,
        "manifest_sha256": handoff.manifest_sha256,
        "producer_repository_commit": handoff.repository_commit,
        "judged_seasons": list(JUDGED_SEASONS),
        "detail": detail,
        "accuracy": read["accuracy"],
        "ordering": read["ordering"],
        "reported_not_gated": reported_not_gated(rows),
        "machine": (
            "Other sessions share this machine. Both solver limits are deterministic, so no"
            " measured number moves under that load; `elapsed_seconds` does, and is not a"
            " quiet-machine timing."
        ),
    }

    if arguments.readings_only:
        record["decision"] = None
        record["gate"] = positional_defence_gate(
            read["accuracy"], read["ordering"], {"passes": False}
        )
        print(_markdown(record))
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
        if str(fold)[:7] in set(JUDGED_SEASONS)
        and int(
            handoff.rows.loc[handoff.rows["fold_id"].astype(str) == fold, "target_gameweek"].iloc[0]
        )
        >= 4
    ]
    controls = tuple(fold for fold in ridge if fold.fold_id in set(order))
    if [fold.fold_id for fold in controls] != order:
        print("The ridge folds do not cover the judged decisions in the same order.")
        return 1

    judged_rows = handoff.rows.loc[handoff.rows["fold_id"].astype(str).isin(order)]
    judged = replace(
        handoff,
        rows=judged_rows,
        roster=handoff.roster.loc[handoff.roster["fold_id"].astype(str).isin(order)],
    )
    priced = judged_rows["control_expected_points"].notna()
    # Only the goalkeeper and defender rows the candidate priced are replaced. Every other
    # row is left exactly as the table has it, in both arms.
    replacement = pd.Series(pd.NA, index=judged_rows.index, dtype="Float64")
    keyed = rows.set_index(["fold_id", "player_id"])["candidate_expected_points"]
    lookup = judged_rows.set_index(["fold_id", "player_id"]).index
    replacement.loc[:] = [keyed.get(key, pd.NA) for key in lookup]
    candidate_column = replacement.where(
        replacement.notna(), judged_rows["control_expected_points"]
    ).where(priced)

    config = EvaluationConfig(
        optimization_config=measurement_optimization_config(),
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        run_metadata={"study": POSITIONAL_DEFENCE_CONTRACT_VERSION},
    )
    control_result = evaluate_prepared_folds(
        prepare_phase_c_component_folds(judged, controls), config
    )
    candidate_result = evaluate_prepared_folds(
        prepare_phase_c_component_folds(
            replace(judged, rows=judged_rows.assign(control_expected_points=candidate_column)),
            controls,
        ),
        config,
    )
    control_scores = _scores(control_result)
    candidate_scores = _scores(candidate_result)
    paired = [fold for fold in order if fold in control_scores and fold in candidate_scores]
    differences = [candidate_scores[fold] - control_scores[fold] for fold in paired]
    pairs = [(fold[:7], value) for fold, value in zip(paired, differences, strict=True)]
    interval = (
        season_aware_moving_block_interval(
            pairs,
            policy=PromotionPolicy(
                bootstrap_resamples=BOOTSTRAP_RESAMPLES, moving_block_length=BLOCK_LENGTH
            ),
            candidate_id=POSITIONAL_DEFENCE_CONTRACT_VERSION,
        )
        if len(pairs) >= 2
        else None
    )
    season_values: dict[str, list[float]] = {}
    for season, value in pairs:
        season_values.setdefault(season, []).append(value)
    season_means = {
        season: sum(values) / len(values) for season, values in sorted(season_values.items())
    }
    decision = decision_clause(
        sum(differences) / len(differences) if differences else None,
        season_means,
        interval,
        len(differences),
    )
    decision["by_season"] = season_means
    decision["arms"] = {
        "control": _arm_summary(control_result),
        "candidate": _arm_summary(candidate_result),
    }
    record["decision"] = decision
    record["gate"] = positional_defence_gate(read["accuracy"], read["ordering"], decision)
    record["solver"] = solver_record(control_result, candidate_result)
    record["elapsed_seconds"] = (datetime.now(UTC) - started).total_seconds()
    record.update(artifact_metadata(panel_rows=len(panel), history_seasons=list(RATING.seasons)))

    provenance = record.get("provenance")
    if isinstance(provenance, dict) and provenance.get("working_tree_dirty"):
        print("Refusing to write: the working tree is dirty.")
        print(_markdown(record))
        return 1
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(_markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
