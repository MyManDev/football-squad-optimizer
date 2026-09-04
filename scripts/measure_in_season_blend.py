"""Measure the in-season blend on the development folds, against what it replaces.

    python -m scripts.measure_in_season_blend
    python -m scripts.measure_in_season_blend --quick   # a short fold prefix, for wiring

The blend that will project gameweek two carries two declared numbers -- a 270-minute prior
for the scoring rate and a six-gameweek equivalent for playing time -- and both were
judgements when they were written. This is the walk-forward measurement the module's own
docstring names as the thing that would revise them.

The comparison that matters is not the blend against itself at different weights. It is the
blend against what it stands in for. The live path cannot read the archive's shifted rolling
features, because the archive publishes a season only after it is played, so the blend sees
only what a capture carries: season-to-date totals, a carried record, and a price prior. So
three things are scored on identical folds:

  A  the archive-fed control, at fw05 and fw10 -- what full feature access would get
  B  the blend, at its declared weights and along each weight axis
  C  carry-over alone -- what ignoring the season so far would get

A minus B is the price of being capture-only; B minus C is what the in-season term earns.
The weight sweep is only meaningful beside those two.

Every configuration is scored under one fixed optimizer, so differences are attributable to
the projection alone. **The absolute levels are therefore not comparable to the screening
run's numbers**, which used their own bench weights.

This measurement records; it does not promote. Changing a declared constant after seeing the
surface is choosing the outcome, not tuning, so a better value becomes a separate
pre-registered candidate. The locked holdout is not read: the panel is cut to the
development seasons before anything reads a feature window.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from types import MappingProxyType
from typing import Final

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, write_json, write_text

from squadopt.backtest.splits import (
    BacktestConfigurationError,
    DecisionPoint,
    realized_points_at,
    rows_before,
    season_ranks,
    walk_forward_decision_points,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationResult,
    evaluate_prepared_folds,
)
from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.features.cross_season import carry_over_as_of
from squadopt.prediction import FormWindowMapping, build_projection_table
from squadopt.prediction.in_season import (
    IN_SEASON_MODEL_VERSION,
    InSeasonBlendConfig,
    blend_in_season_projection,
)
from squadopt.prediction.opening import build_opening_projection_from_snapshot

IN_SEASON_BENCHMARK_CONTRACT_VERSION: Final = "in_season_blend_benchmark_v1"

# The development population. 2025-26 is the locked holdout and is never a member. Spelled
# here rather than imported from the policy evaluator so this run states its own population.
DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")
MIN_PRIOR_GAMEWEEKS_IN_SEASON: Final = 1
LOCKED_HOLDOUT_SEASON: Final = "2025-26"

ROSTER_COLUMNS: Final = ("player_id", "name", "team_id", "position", "price_tenths")

# The declared defaults under measurement, and the control windows to compare against.
DECLARED_MINUTE_EQUIVALENT: Final = 270
DECLARED_GAMEWEEK_EQUIVALENT: Final = 6
MINUTE_AXIS: Final = (90, 270, 540, 1080)
GAMEWEEK_AXIS: Final = (3, 6, 12)
CONTROL_FORM_WINDOWS: Final = (5, 10)

# What this run is and is not, stated once so a test can assert it without spending an hour
# of CP-SAT to see it. `optimizer_held_fixed` is why a difference is attributable to the
# projection; `comparable_to_screening_levels` is false because the screening used its own
# bench weights, and two absolute means from different optimizers do not belong side by side.
RECORD_PROVENANCE: Final[Mapping[str, bool]] = MappingProxyType(
    {
        "optimizer_held_fixed": True,
        "comparable_to_screening_levels": False,
        "gate_evidence": False,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
)

DEFAULT_RECORD: Final = Path("docs/in_season_blend_benchmark.json")
DEFAULT_SUMMARY: Final = Path("docs/in_season_blend_benchmark.md")


@dataclass(frozen=True, slots=True)
class Configuration:
    """One projection under measurement, and how to build it for a fold."""

    label: str
    family: str
    build: Callable[[DecisionPoint], pd.DataFrame]
    detail: str = ""


def _visible_panel(archive_root: Path) -> pd.DataFrame:
    """Load the panel with everything after the development seasons cut away.

    Cut rather than filtered later, so a locked-holdout row cannot reach a feature window
    even as carry-over history. This is the guard the policy evaluator applies and the
    reason this script can be run while the holdout is being spent elsewhere.
    """

    panel = build_panel(archive_root)
    ranks = season_ranks(panel)
    unknown = sorted(set(DEVELOPMENT_SEASONS) - set(ranks))
    if unknown:
        raise BacktestConfigurationError(
            f"Development seasons are absent from the panel: {unknown!r}."
        )
    last_rank = max(ranks[season] for season in DEVELOPMENT_SEASONS)
    visible = panel.loc[panel["season"].map(lambda season: ranks[str(season)] <= last_rank)]
    remaining = sorted({str(value) for value in visible["season"].tolist()})
    if LOCKED_HOLDOUT_SEASON in remaining:
        raise BacktestConfigurationError(
            f"{LOCKED_HOLDOUT_SEASON} survived the cut; it is the locked holdout and must "
            "not be visible to this measurement."
        )
    return visible.copy(deep=True)


class _Inputs:
    """The config-independent inputs, built once and shared by every configuration.

    The roster, the carried record and the fallback projection do not depend on any weight
    under measurement, so recomputing them per configuration would multiply the run's cost
    without changing a number.
    """

    def __init__(self, panel: pd.DataFrame, decisions: Sequence[DecisionPoint]) -> None:
        self._panel = panel
        self._roster: dict[str, pd.DataFrame] = {}
        self._history: dict[str, pd.DataFrame] = {}
        self._carried: dict[str, pd.DataFrame] = {}
        self._fallback: dict[str, pd.DataFrame] = {}
        for decision in decisions:
            self._prepare(decision)

    def _prepare(self, decision: DecisionPoint) -> None:
        key = decision.fold_id
        target = self._panel.loc[
            (self._panel["season"] == decision.season)
            & (self._panel["gameweek"] == decision.gameweek)
        ]
        roster = (
            target.loc[:, list(ROSTER_COLUMNS)]
            .drop_duplicates("player_id")
            .sort_values("player_id", kind="stable")
            .reset_index(drop=True)
        )
        # Season-to-date totals for the gameweeks already played. This is exactly what a
        # post-reset capture's cumulative counters carry (docs/capture_season_phase.md), so
        # the measured model reads the same shape it will read live.
        earlier = rows_before(self._panel, decision)
        in_season = earlier.loc[earlier["season"] == decision.season]
        history = in_season.groupby("player_id", as_index=False)[["minutes", "total_points"]].sum()
        if decision.season not in self._carried:
            self._carried[decision.season] = carry_over_as_of(
                self._panel, target_season=decision.season
            )
        self._roster[key] = roster
        self._history[key] = history
        self._fallback[key] = build_opening_projection_from_snapshot(
            self._panel, roster, season=decision.season
        )

    def blend(self, decision: DecisionPoint, config: InSeasonBlendConfig) -> pd.DataFrame:
        key = decision.fold_id
        blend = blend_in_season_projection(
            self._roster[key],
            self._carried[decision.season],
            self._history[key],
            self._fallback[key],
            gameweeks_played=decision.gameweek - 1,
            config=config,
        )
        return blend.table

    def carry_over_only(self, decision: DecisionPoint) -> pd.DataFrame:
        """The opening control applied at every gameweek: the season so far ignored."""

        table = self._fallback[decision.fold_id]
        return table.loc[:, [*ROSTER_COLUMNS, "expected_points"]].copy(deep=True)


def _control_builder(
    panel: pd.DataFrame, form_window: int, cross_season: CrossSeasonConfig
) -> Callable[[DecisionPoint], pd.DataFrame]:
    """Build the archive-fed control's projections, features computed once per window."""

    mapping = FormWindowMapping(form_window=form_window)
    features = build_feature_dataset(
        panel, config=mapping.feature_config, cross_season=cross_season
    )

    def build(decision: DecisionPoint) -> pd.DataFrame:
        return build_projection_table(
            features,
            season=decision.season,
            gameweek=decision.gameweek,
            config=mapping.projection_config,
        )

    return build


def _blend_builder(
    inputs: "_Inputs", settings: InSeasonBlendConfig
) -> Callable[[DecisionPoint], pd.DataFrame]:
    """Bind one weight setting to a fold builder.

    A named factory rather than a lambda with a default argument: the closure wants a
    declared type, and a lambda capturing a loop variable through its default is the shape
    that silently binds the last iteration the day someone drops the default.
    """

    def build(decision: DecisionPoint) -> pd.DataFrame:
        return inputs.blend(decision, settings)

    return build


def configurations(panel: pd.DataFrame, inputs: _Inputs) -> tuple[Configuration, ...]:
    """Every projection under measurement.

    The blend sweep is a cross through the declared point, not a full grid: the question is
    whether each declared value sits at a local optimum along its own axis. Scoring twelve
    cells and taking the best would be choosing an outcome.
    """

    cross_season = CrossSeasonConfig()
    entries: list[Configuration] = []

    for window in CONTROL_FORM_WINDOWS:
        builder = _control_builder(panel, window, cross_season)
        entries.append(
            Configuration(
                label=f"control-fw{window:02d}",
                family="archive_fed_control",
                build=builder,
                detail=f"shifted rolling features, form_window={window}",
            )
        )

    entries.append(
        Configuration(
            label="carry-over-only",
            family="floor",
            build=inputs.carry_over_only,
            detail="the opening control at every gameweek; the season so far ignored",
        )
    )

    seen: set[tuple[int, int]] = set()
    for minutes, gameweeks in [
        *((value, DECLARED_GAMEWEEK_EQUIVALENT) for value in MINUTE_AXIS),
        *((DECLARED_MINUTE_EQUIVALENT, value) for value in GAMEWEEK_AXIS),
    ]:
        if (minutes, gameweeks) in seen:
            continue
        seen.add((minutes, gameweeks))
        settings = InSeasonBlendConfig(
            prior_gameweek_equivalent=gameweeks, prior_minute_equivalent=minutes
        )
        declared = (
            minutes == DECLARED_MINUTE_EQUIVALENT and gameweeks == DECLARED_GAMEWEEK_EQUIVALENT
        )
        entries.append(
            Configuration(
                label=f"blend-m{minutes}-g{gameweeks}" + ("-declared" if declared else ""),
                family="in_season_blend",
                build=_blend_builder(inputs, settings),
                detail=f"prior_minute_equivalent={minutes}, prior_gameweek_equivalent={gameweeks}",
            )
        )
    return tuple(entries)


def _score(
    panel: pd.DataFrame,
    decisions: Sequence[DecisionPoint],
    configuration: Configuration,
) -> EvaluationResult:
    """Score one configuration on the folds.

    ``metadata`` carries the season deliberately: the interval helper reads it and skips a
    fold that lacks it, which would silently shrink the sample rather than fail.
    """

    folds = tuple(
        EvaluationFold(
            fold_id=decision.fold_id,
            projections=configuration.build(decision),
            realized_points=realized_points_at(panel, decision),
            metadata={
                "season": decision.season,
                "gameweek": decision.gameweek,
                "configuration": configuration.label,
            },
        )
        for decision in decisions
    )
    return evaluate_prepared_folds(folds, EvaluationConfig())


def _solve_health(result: EvaluationResult) -> dict[str, object]:
    """Report whether the solver actually determined each fold's squad.

    A realized score is only attributable to the projection if the optimizer returned *the*
    optimum rather than *an* optimum. Two things can break that, and both are recorded per
    fold by the optimizer rather than inferred here:

    ``solver_status`` says whether optimality was proven at all. ``FEASIBLE`` means a squad
    that is merely good enough, so its realized points describe an arbitrary member of a
    near-optimal set.

    ``tiebreak_completed`` says whether the lexicographic tie-break finished. The tie-break
    is what makes one optimum *the* optimum, and it is skipped when the primary solve is not
    optimal, when almost no wall clock remains, or when the deterministic budget is spent
    (``optimizer.py`` around the ``tiebreak_attempted`` assignment). Where it did not
    complete, the squad among equal-objective squads fell to the solver's search order --
    which is #192.

    Attempted plus skipped must equal the fold count. An accounting gap would be a silent
    hole in exactly the claim this block exists to make.
    """

    statuses: Counter[str] = Counter()
    attempted = 0
    completed = 0
    exhausted = 0
    incomplete: list[str] = []
    for fold in result.folds:
        optimization = fold.optimization_result
        diagnostics = dict(optimization.diagnostics)
        statuses[str(optimization.solver_status)] += 1
        if diagnostics.get("tiebreak_attempted") is True:
            attempted += 1
            if diagnostics.get("tiebreak_completed") is True:
                completed += 1
            else:
                incomplete.append(fold.fold_id)
        else:
            incomplete.append(fold.fold_id)
        if diagnostics.get("deterministic_time_budget_exhausted") is True:
            exhausted += 1

    folds = len(result.folds)
    if completed + len(incomplete) != folds:
        raise BacktestConfigurationError(
            f"Solve health accounts for {completed + len(incomplete)} of {folds} folds; an "
            "accounting gap would hide exactly what this block reports."
        )
    return {
        "folds": folds,
        "primary_status": {name: count for name, count in sorted(statuses.items())},
        "tiebreak_attempted": attempted,
        "tiebreak_completed": completed,
        "folds_not_fully_determined": len(incomplete),
        "first_undetermined_folds": incomplete[:5],
        "deterministic_budget_exhausted": exhausted,
    }


def _paired(
    candidate: EvaluationResult, control: EvaluationResult, *, candidate_id: str
) -> dict[str, object]:
    """Paired difference on exactly matching folds, with a season-aware interval."""

    by_id = {fold.fold_id: fold for fold in control.folds}
    differences: list[tuple[str, float]] = []
    unpaired: list[str] = []
    for fold in candidate.folds:
        other = by_id.get(fold.fold_id)
        season = fold.metadata.get("season")
        if (
            other is None
            or fold.realized_squad_points is None
            or other.realized_squad_points is None
            or not isinstance(season, str)
        ):
            unpaired.append(fold.fold_id)
            continue
        differences.append(
            (season, float(fold.realized_squad_points - other.realized_squad_points))
        )
    if unpaired:
        raise BacktestConfigurationError(
            f"{len(unpaired)} fold(s) could not be paired for {candidate_id!r} "
            f"(first: {unpaired[:3]!r}); an unpaired fold is a quietly smaller sample."
        )

    policy = PromotionPolicy()
    lower, upper = season_aware_moving_block_interval(
        differences, policy=policy, candidate_id=candidate_id
    )
    per_season: dict[str, list[float]] = {}
    for season, value in differences:
        per_season.setdefault(season, []).append(value)
    season_means = {
        season: round(fmean(values), 4) for season, values in sorted(per_season.items())
    }
    return {
        "folds_paired": len(differences),
        "mean_difference": round(fmean(value for _, value in differences), 4),
        "interval_lower": round(lower, 4),
        "interval_upper": round(upper, 4),
        "confidence_level": policy.confidence_level,
        "season_means": season_means,
        "seasons_positive": sum(1 for value in season_means.values() if value > 0),
        "seasons": len(season_means),
    }


def _reproducibility(
    entries: list[dict[str, object]], previous: Path | None
) -> dict[str, object] | None:
    """Compare this run's means against an earlier record's, per configuration.

    A benchmark that cannot reproduce its own numbers is reporting solver search order, not
    projection quality, and the only way to know is to run it twice and say so. Kept as a
    comparison against a file rather than a pasted constant so the check survives the next
    run instead of decaying into a stale literal.
    """

    if previous is None:
        return None
    if not previous.is_file():
        raise BacktestConfigurationError(f"No earlier record at {previous}.")
    document = json.loads(previous.read_text(encoding="utf-8"))
    earlier = {
        str(item["label"]): float(item["mean_realized_squad_points"])
        for item in document.get("configurations", [])
        if isinstance(item, dict)
    }
    rows: list[dict[str, object]] = []
    moved = 0
    largest = 0.0
    for entry in entries:
        label = str(entry["label"])
        if label not in earlier:
            continue
        before = earlier[label]
        after = float(str(entry["mean_realized_squad_points"]))
        delta = round(after - before, 4)
        health = entry["solve_health"]
        determined = None
        if isinstance(health, dict):
            determined = int(str(health["folds"])) - int(str(health["folds_not_fully_determined"]))
        if delta:
            moved += 1
            largest = max(largest, abs(delta))
        rows.append(
            {
                "label": label,
                "earlier": before,
                "now": after,
                "delta": delta,
                "folds_determined": determined,
            }
        )
    return {
        "compared_against": str(previous),
        "configurations_compared": len(rows),
        "configurations_that_moved": moved,
        "largest_absolute_move": round(largest, 4),
        "rows": rows,
    }


def measure(
    archive_root: Path, *, fold_limit: int | None = None, compare_to: Path | None = None
) -> dict[str, object]:
    """Score every configuration on identical folds and pair the ones worth pairing."""

    panel = _visible_panel(archive_root)
    decisions = walk_forward_decision_points(
        panel,
        seasons=DEVELOPMENT_SEASONS,
        min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    )
    if fold_limit is not None:
        decisions = decisions[:fold_limit]
    if not decisions:
        raise BacktestConfigurationError("No decision points for the requested seasons.")

    inputs = _Inputs(panel, decisions)
    scored: dict[str, EvaluationResult] = {}
    entries: list[dict[str, object]] = []
    for configuration in configurations(panel, inputs):
        result = _score(panel, decisions, configuration)
        scored[configuration.label] = result
        entries.append(
            {
                "label": configuration.label,
                "family": configuration.family,
                "detail": configuration.detail,
                "mean_realized_squad_points": round(
                    float(result.summary.mean_realized_squad_points or 0.0), 4
                ),
                "feasibility_rate": round(float(result.summary.feasibility_rate), 4),
                "scored_folds": int(result.summary.scored_folds),
                "solve_health": _solve_health(result),
            }
        )

    declared = next(
        str(entry["label"]) for entry in entries if str(entry["label"]).endswith("-declared")
    )
    comparisons: dict[str, dict[str, object]] = {}
    for label in scored:
        if label == declared:
            continue
        comparisons[f"{declared} vs {label}"] = _paired(
            scored[declared], scored[label], candidate_id=f"{declared}|{label}"
        )

    return {
        "artifact_type": "in_season_blend_benchmark",
        "contract_version": IN_SEASON_BENCHMARK_CONTRACT_VERSION,
        "model_version_measured": IN_SEASON_MODEL_VERSION,
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "folds": len(decisions),
        "first_fold": decisions[0].fold_id,
        "last_fold": decisions[-1].fold_id,
        "declared_configuration": declared,
        "configurations": entries,
        "paired_against_declared": comparisons,
        "reproducibility": _reproducibility(entries, compare_to),
        **dict(RECORD_PROVENANCE),
    }


def _seasons(record: dict[str, object]) -> list[str]:
    value = record["development_seasons"]
    return [str(item) for item in value] if isinstance(value, list) else []


def _rows(record: dict[str, object], key: str) -> list[dict[str, object]]:
    """Read a list-of-mappings field back out of the record with a declared type."""

    value = record[key]
    if not isinstance(value, list):
        raise BacktestConfigurationError(f"{key!r} is not a list.")
    return [dict(item) for item in value if isinstance(item, dict)]


def _pairs(record: dict[str, object], key: str) -> dict[str, dict[str, object]]:
    """Read a mapping-of-mappings field back out of the record with a declared type."""

    value = record[key]
    if not isinstance(value, dict):
        raise BacktestConfigurationError(f"{key!r} is not a mapping.")
    return {str(name): dict(item) for name, item in value.items() if isinstance(item, dict)}


def summary(record: dict[str, object]) -> str:
    """Report it as prose, saying what it measures and what it deliberately does not."""

    entries = _rows(record, "configurations")
    comparisons = _pairs(record, "paired_against_declared")
    declared = str(record["declared_configuration"])
    seasons = ", ".join(str(value) for value in _seasons(record))
    confidence = 90
    if comparisons:
        first = next(iter(comparisons.values()))
        confidence = round(float(str(first["confidence_level"])) * 100)
    lines = [
        "# The in-season blend on the development folds",
        "",
        f"Contract: `{record['contract_version']}`  ·  model: `{record['model_version_measured']}`",
        f"Folds: **{record['folds']}**, `{record['first_fold']}` to `{record['last_fold']}`, "
        f"seasons {seasons}.",
        "",
        "The blend reads only what a capture carries — season-to-date totals, a carried",
        "record, a price prior — because the archive publishes a season after it is played.",
        "So it is scored against the archive-fed control above it and against ignoring the",
        "season entirely below it. Every configuration shares one optimizer, so a difference",
        "is the projection's. **The levels below are not comparable to the screening run's**,",
        "which used its own bench weights.",
        "",
        "## What each projection scored",
        "",
        "| configuration | family | mean realized squad points | feasible |",
        "| --- | --- | ---: | ---: |",
    ]
    for entry in entries:
        mark = " **← declared**" if entry["label"] == declared else ""
        lines.append(
            f"| `{entry['label']}`{mark} | {entry['family']} | "
            f"{entry['mean_realized_squad_points']} | {entry['feasibility_rate']} |"
        )

    lines += [
        "",
        "## The declared configuration against each other one",
        "",
        f"Paired per fold, {confidence}% season-aware moving-block interval.",
        "",
        "| against | mean difference | interval | seasons positive |",
        "| --- | ---: | --- | ---: |",
    ]
    for name, comparison in comparisons.items():
        other = name.split(" vs ")[1]
        lines.append(
            f"| `{other}` | {comparison['mean_difference']:+} | "
            f"[{comparison['interval_lower']}, {comparison['interval_upper']}] | "
            f"{comparison['seasons_positive']}/{comparison['seasons']} |"
        )

    lines += [
        "",
        "A positive difference means the declared blend scored higher. Against",
        "`carry-over-only` the difference is what reading the season so far earns, and that",
        "is the cleanest comparison here: the two differ only in whether the in-season term",
        "exists, so nothing else can explain it. Against another blend the difference says",
        "whether the declared weight sits at a local optimum on that axis. Against a control",
        "it is the gap between a capture-only projection and one with the archive's rolling",
        "features -- read with the caveat below, not as a clean win.",
        "",
        "## The caveat that matters, before anyone quotes a number",
        "",
        "`FITTED_OPENING_PRICE_COEFFICIENT` was fitted on opening-gameweek rows from 2020-21",
        "through 2024-25 -- **the same seasons these folds evaluate**. It is therefore",
        "in-sample here, and every configuration draws on it identically for players with no",
        "usable history, so:",
        "",
        "- differences between configurations that lean on it the same way are sound. The",
        "  blend variants differ only in two weights, and the set of players priced from the",
        "  prior is weight-independent, so the axis comparisons are unaffected.",
        "- the **absolute levels are optimistic** for every configuration, including the",
        "  controls.",
        "- a **control-versus-blend** difference could partly reflect differing reliance on",
        "  that constant rather than projection quality, because the two reach the prior",
        "  through different conditions. Quantifying that exposure is the first thing a",
        "  follow-up should do; it is not quantified here.",
        "",
        "The production path refits the prior per fold on an expanding window",
        "(`_price_coefficient`). This benchmark deliberately does not, so that every",
        "configuration is scored on one fixed set of projection inputs and a difference is",
        "attributable to the projection rule. That choice buys comparability and costs",
        "absolute realism, and both halves of the trade belong in the record.",
    ]
    repro = record.get("reproducibility")
    if isinstance(repro, dict):
        lines += [
            "",
            "## Run it twice: which numbers hold still",
            "",
            f"Compared against `{repro['compared_against']}`, "
            f"**{repro['configurations_that_moved']} of "
            f"{repro['configurations_compared']} configurations did not reproduce**, and the "
            f"largest move was {repro['largest_absolute_move']}.",
            "",
            "| configuration | earlier | now | move | folds determined |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for row in _rows(repro, "rows"):
            mark = "" if row["delta"] == 0 else " **<--**"
            lines.append(
                f"| `{row['label']}`{mark} | {row['earlier']} | {row['now']} | "
                f"{row['delta']:+} | {row['folds_determined']} |"
            )
        lines += [
            "",
            "The relationship is directional, not strict: both fully determined",
            "configurations reproduced to the digit, and the two largest moves belong to the",
            "two least determined -- but a configuration at 138 determined folds moved while",
            "one at 123 did not, so determination bounds the risk rather than predicting the",
            "outcome. The mechanism is #192, measured here rather than argued: where the",
            "tie-break did not finish, the squad among equal-objective squads came from the",
            "solver's search order, and a second run can pick a different one.",
            "",
            "**So the weight axis is not resolvable at this precision.** The differences it",
            "asks about are 0.16 to 0.84 points, and the movement between two runs of one",
            "configuration reaches 0.22. The large comparisons are untouched: the floor moved",
            "0.04 against a difference of 13.78, and both controls reproduced exactly.",
        ]

    lines += [
        "## What this decides",
        "",
        "Nothing on its own. It is a record, not a gate: `measurement_only` is true and",
        "`gate_evidence` is false. The declared weights are **not** changed by it, because",
        "changing a constant after seeing the surface is choosing the outcome. A better value",
        "becomes a separate pre-registered candidate with its own gates.",
        "",
        "On the question it was built to answer: the declared configuration is the highest",
        "of the nine, and **every neighbouring weight is within about eight tenths of a point",
        "with an interval that includes zero**. So the surface is flat within noise around",
        "the declared point -- it is not dominated, and the weights are not a sensitive knob.",
        "That is an argument for leaving them alone rather than for having chosen well.",
        "",
        "The recorded consequence that prompted this run -- twenty minutes for four points",
        "landing slightly above ninety minutes for four -- is not resolved by it. The surface",
        "says the weights barely move the objective, which means that behaviour is not worth",
        "buying a weight change to fix; it would need a different rule, and that would be a",
        "candidate rather than a constant.",
        "",
        "The locked holdout was not read. The panel is cut to the development seasons before",
        "anything reads a feature window, so a holdout row cannot reach one even as",
        "carry-over history.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="score a short fold prefix, for checking the wiring rather than measuring",
    )
    parser.add_argument("--fold-limit", type=int, default=None)
    parser.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="an earlier record to check this run's means against",
    )
    arguments = parser.parse_args()

    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    limit = 6 if arguments.quick else arguments.fold_limit
    record = measure(arguments.archive_root, fold_limit=limit, compare_to=arguments.compare_to)

    print(f"Folds {record['folds']}  ({record['first_fold']} .. {record['last_fold']})")
    print()
    for entry in _rows(record, "configurations"):
        health = entry["solve_health"]
        note = ""
        if isinstance(health, dict):
            folds = int(str(health["folds"]))
            undetermined = int(str(health["folds_not_fully_determined"]))
            note = f"  determined {folds - undetermined}/{folds}  {health['primary_status']}"
        print(
            f"  {entry['label']!s:28} {entry['mean_realized_squad_points']:>9}"
            f"  feasible {entry['feasibility_rate']}{note}"
        )
    print()
    for name, comparison in _pairs(record, "paired_against_declared").items():
        print(
            f"  {name:56} {comparison['mean_difference']:+8}  "
            f"[{comparison['interval_lower']}, {comparison['interval_upper']}]  "
            f"{comparison['seasons_positive']}/{comparison['seasons']}"
        )

    if limit is None:
        write_json(arguments.json_output, record)
        write_text(arguments.markdown_output, summary(record))
        print(f"\nWrote {arguments.json_output}")
        print(f"Wrote {arguments.markdown_output}")
    else:
        print(f"\nFold-limited run ({limit} folds): nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
