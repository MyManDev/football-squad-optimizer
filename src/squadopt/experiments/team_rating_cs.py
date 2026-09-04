"""S1's clean-sheet clause, re-measured against a baseline that could actually be known.

The team rating study (#139) failed one clause of three: its clean-sheet probabilities had
to be better calibrated than a logistic on the platform's published difficulty rating.
The Decision 1 ruling then established that the archived difficulty column is written
after the season it describes — the clause had pitted the rating against a baseline that
had seen the answers, and lost to it by ties.

This module runs the pre-registered measurable form of that clause
(`docs/team_rating_cs_prereg.md`): the same Brier comparison, the same threshold, the same
seasons and refit discipline — with the baseline replaced by a logistic on the *opponent's
previous-season league points*, which is knowable at every deadline of the following
season. Nothing here re-opens #139's verdict; it produces the dated, measurable form of
the clause that ruling made unmeasurable.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.team_rating import (
    DixonColesConfig,
    _calibrated_clean_sheet,
    _fit_logistic,
    _spearman,
    fit_clean_sheet_calibration,
    fit_dixon_coles,
    load_match_results,
    measure_promoted_prior,
    promoted_clubs,
    select_dixon_coles_config,
)

CS_REMEASURE_CONTRACT_VERSION: Final = "team_rating_cs_remeasure_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"


@dataclass(frozen=True, slots=True)
class CsRemeasureConfig:
    """The original study's frame, unchanged; only the baseline definition is new."""

    seasons: tuple[str, ...] = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
    evaluated_seasons: tuple[str, ...] = ("2022-23", "2023-24", "2024-25")
    first_evaluated_gameweek: int = 6
    half_life_grid: tuple[float, ...] = (60.0, 120.0, 180.0, 300.0, 500.0)
    ridge_grid: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0)

    def __post_init__(self) -> None:
        if LOCKED_HOLDOUT_SEASON in self.seasons or LOCKED_HOLDOUT_SEASON in self.evaluated_seasons:
            raise ExperimentConfigurationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be read."
            )
        if not set(self.evaluated_seasons) <= set(self.seasons):
            raise ExperimentConfigurationError("Evaluated seasons must be part of the study.")


@dataclass(frozen=True, slots=True)
class CsSeasonRow:
    season: str
    fixture_sides: int
    rating_brier: float
    table_baseline_brier: float
    constant_baseline_brier: float
    rating_defensive_ordering: float
    table_defensive_ordering: float

    @property
    def improvement(self) -> float:
        """Positive when the rating is better calibrated than the table baseline."""

        return self.table_baseline_brier - self.rating_brier


@dataclass(frozen=True, slots=True)
class CsRemeasureStudy:
    contract_version: str
    config: CsRemeasureConfig
    seasons: tuple[CsSeasonRow, ...]
    pooled_rating_brier: float
    pooled_table_brier: float
    pooled_constant_brier: float
    verdict: Mapping[str, object]
    diagnostics: Mapping[str, object]


def _league_points(matches: pd.DataFrame) -> pd.Series:
    """The plain league table: three for a win, one for a draw, per club code."""

    rows: list[tuple[int, int]] = []
    for record in matches.to_dict("records"):
        home_goals = int(record["home_goals"])
        away_goals = int(record["away_goals"])
        rows.append(
            (
                int(record["home_club"]),
                3 if home_goals > away_goals else int(home_goals == away_goals),
            )
        )
        rows.append(
            (
                int(record["away_club"]),
                3 if away_goals > home_goals else int(home_goals == away_goals),
            )
        )
    table = pd.DataFrame(rows, columns=["club", "points"])
    return table.groupby("club")["points"].sum()


def previous_season_points(
    matches: pd.DataFrame, season: str, *, promoted_fill: float
) -> Mapping[int, float]:
    """Each club's previous-season final points, promoted clubs at the measured fill.

    The previous season's table is complete before the following season's first deadline,
    which is the entire admissibility requirement the published rating failed.
    """

    ordered = sorted({str(value) for value in matches["season"]})
    position = ordered.index(str(season))
    if position == 0:
        raise ExperimentExecutionError(f"{season} has no previous season in the frame.")
    previous = matches.loc[matches["season"] == ordered[position - 1]]
    table = _league_points(previous)
    current_clubs = set(
        int(value)
        for value in pd.concat(
            [
                matches.loc[matches["season"] == season, "home_club"],
                matches.loc[matches["season"] == season, "away_club"],
            ]
        )
    )
    return {club: float(table.get(club, promoted_fill)) for club in current_clubs}


def promoted_points_fill(matches: pd.DataFrame, training_seasons: Sequence[str]) -> float:
    """The mean previous-season points a promoted club 'carries': measured, not assumed.

    Promoted clubs have no previous top-flight season, so their fill is the mean *final*
    points that promoted clubs actually earned in the training seasons — the same
    measured-prior idea the rating uses for its own promoted clubs.
    """

    promoted = promoted_clubs(matches)
    values: list[float] = []
    for season in training_seasons:
        arrivals = promoted.get(str(season), ())
        if not arrivals:
            continue
        table = _league_points(matches.loc[matches["season"] == season])
        values.extend(float(table.get(club, 0.0)) for club in arrivals)
    if not values:
        return 0.0
    return float(np.mean(values))


def fit_table_baseline(
    matches: pd.DataFrame, training_seasons: Sequence[str], *, promoted_fill: float
) -> tuple[float, float, float]:
    """``clean sheet ~ opponent's previous-season points + venue`` on training seasons.

    Every row the logistic sees is walk-forward legal: the season's outcomes are paired
    with the *previous* season's table, exactly as a live deadline would pair them.
    """

    designs: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    for season in training_seasons:
        block = matches.loc[matches["season"] == season]
        if block.empty:
            continue
        try:
            points = previous_season_points(matches, season, promoted_fill=promoted_fill)
        except ExperimentExecutionError:
            continue  # the frame's first season has no previous table to pair with
        for record in block.to_dict("records"):
            home = int(record["home_club"])
            away = int(record["away_club"])
            for is_home, opponent, conceded in (
                (1.0, away, int(record["away_goals"])),
                (0.0, home, int(record["home_goals"])),
            ):
                designs.append(np.array([1.0, float(points.get(opponent, promoted_fill)), is_home]))
                targets.append(np.array([1.0 if conceded == 0 else 0.0]))
    if not designs:
        raise ExperimentExecutionError("No training season offers a previous-season table.")
    theta = _fit_logistic(np.vstack(designs), np.concatenate(targets))
    return float(theta[0]), float(theta[1]), float(theta[2])


def _table_probability(
    coefficients: tuple[float, float, float], opponent_points: float, *, is_home: bool
) -> float:
    intercept, slope, venue = coefficients
    value = intercept + slope * opponent_points + venue * (1.0 if is_home else 0.0)
    return float(1.0 / (1.0 + np.exp(-np.clip(value, -30.0, 30.0))))


def run_cs_remeasure(
    archive_root: Path | str, config: CsRemeasureConfig | None = None
) -> CsRemeasureStudy:
    """The failed clause, re-run with an admissible baseline; the gate applied by code."""

    settings = CsRemeasureConfig() if config is None else config
    matches = load_match_results(Path(archive_root), settings.seasons)
    promoted = promoted_clubs(matches)
    rows: list[CsSeasonRow] = []
    selected: dict[str, DixonColesConfig] = {}
    for season in settings.evaluated_seasons:
        earlier = [value for value in settings.seasons if value < season]
        training_frame = matches.loc[matches["season"].isin(earlier)]
        chosen = select_dixon_coles_config(
            training_frame,
            earlier,
            half_life_grid=settings.half_life_grid,
            ridge_grid=settings.ridge_grid,
            first_gameweek=settings.first_evaluated_gameweek,
        )
        selected[season] = chosen
        prior = measure_promoted_prior(matches, earlier, chosen)
        calibration = fit_clean_sheet_calibration(
            training_frame,
            earlier[1:],
            chosen,
            first_gameweek=settings.first_evaluated_gameweek,
        )
        fill = promoted_points_fill(matches, earlier)
        table_coefficients = fit_table_baseline(matches, earlier, promoted_fill=fill)
        # The constant floor: the training seasons' clean-sheet frequency by venue.
        home_clean: list[float] = []
        away_clean: list[float] = []
        for record in training_frame.to_dict("records"):
            home_clean.append(1.0 if int(record["away_goals"]) == 0 else 0.0)
            away_clean.append(1.0 if int(record["home_goals"]) == 0 else 0.0)
        constant_home = float(np.mean(home_clean))
        constant_away = float(np.mean(away_clean))

        season_points = previous_season_points(matches, season, promoted_fill=fill)
        arrivals = promoted.get(season, ())
        judged = matches.loc[matches["season"] == season]
        gameweeks = sorted(
            int(value)
            for value in judged["gameweek"].unique()
            if int(value) >= settings.first_evaluated_gameweek
        )
        rating_brier: list[float] = []
        table_brier: list[float] = []
        constant_brier: list[float] = []
        defensive_rating: list[tuple[float, float]] = []
        defensive_table: list[tuple[float, float]] = []
        for gameweek in gameweeks:
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
                    realized = 1.0 if conceded == 0 else 0.0
                    raw = rating.clean_sheet_probability(club, opponent, is_home=is_home)
                    calibrated = _calibrated_clean_sheet(calibration, raw)
                    table_probability = _table_probability(
                        table_coefficients,
                        float(season_points.get(opponent, fill)),
                        is_home=is_home,
                    )
                    constant = constant_home if is_home else constant_away
                    rating_brier.append((calibrated - realized) ** 2)
                    table_brier.append((table_probability - realized) ** 2)
                    constant_brier.append((constant - realized) ** 2)
                    defensive_rating.append((calibrated, realized))
                    defensive_table.append((table_probability, realized))
        if not rating_brier:
            continue
        rating_array = np.asarray(defensive_rating, dtype="float64")
        table_array = np.asarray(defensive_table, dtype="float64")
        rows.append(
            CsSeasonRow(
                season=season,
                fixture_sides=len(rating_brier),
                rating_brier=float(np.mean(rating_brier)),
                table_baseline_brier=float(np.mean(table_brier)),
                constant_baseline_brier=float(np.mean(constant_brier)),
                rating_defensive_ordering=_spearman(rating_array[:, 0], rating_array[:, 1]),
                table_defensive_ordering=_spearman(table_array[:, 0], table_array[:, 1]),
            )
        )
    if not rows:
        raise ExperimentExecutionError("No season could be judged.")
    pooled_rating = float(np.mean([row.rating_brier for row in rows]))
    pooled_table = float(np.mean([row.table_baseline_brier for row in rows]))
    pooled_constant = float(np.mean([row.constant_baseline_brier for row in rows]))
    better = sum(1 for row in rows if row.improvement > 0.0)
    verdict = {
        "pooled_improvement": pooled_table - pooled_rating,
        "seasons_better": better,
        "seasons_total": len(rows),
        "passes": bool(pooled_rating < pooled_table and better >= max(1, len(rows) - 1)),
        "note": (
            "This is the measurable form of #139's failed clause, dated and gated per "
            "docs/team_rating_cs_prereg.md; it does not reopen #139's verdict."
        ),
    }
    return CsRemeasureStudy(
        contract_version=CS_REMEASURE_CONTRACT_VERSION,
        config=settings,
        seasons=tuple(rows),
        pooled_rating_brier=pooled_rating,
        pooled_table_brier=pooled_table,
        pooled_constant_brier=pooled_constant,
        verdict=verdict,
        diagnostics={
            "selected_half_life_days": {s: c.half_life_days for s, c in selected.items()},
            "selected_ridge": {s: c.ridge for s, c in selected.items()},
            "baseline": "previous_season_table_logistic",
            "locked_holdout_accessed": False,
        },
    )


def study_to_markdown(study: CsRemeasureStudy) -> str:
    """The artifact a reader can check without running anything."""

    lines = [
        "# S1's clean-sheet clause, against a baseline that could actually be known",
        "",
        f"- Contract `{study.contract_version}`; the frame of `team_rating_study` unchanged "
        f"(seasons {', '.join(study.config.evaluated_seasons)} from gameweek "
        f"{study.config.first_evaluated_gameweek}, weekly refits, same recalibration for "
        "both sides); baseline replaced per `team_rating_cs_prereg.md` — a logistic on the "
        "opponent's previous-season league points, walk-forward, promoted clubs at the "
        "measured promoted-club mean.",
        "- This does not reopen #139's verdict; it is the dated, measurable form of the "
        "clause the Decision 1 ruling made unmeasurable.",
        "",
        "| Season | Sides | Rating Brier | Table baseline | Constant floor | Improvement |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in study.seasons:
        lines.append(
            f"| {row.season} | {row.fixture_sides} | {row.rating_brier:.4f} "
            f"| {row.table_baseline_brier:.4f} | {row.constant_baseline_brier:.4f} "
            f"| {row.improvement:+.4f} |"
        )
    lines += [
        f"| **pooled** | — | **{study.pooled_rating_brier:.4f}** "
        f"| **{study.pooled_table_brier:.4f}** | {study.pooled_constant_brier:.4f} | "
        f"**{float(str(study.verdict['pooled_improvement'])):+.4f}** |",
        "",
        "Defensive ordering beside it (reported, not gated):",
        "",
        "| Season | Rating | Table baseline |",
        "| --- | ---: | ---: |",
    ]
    for row in study.seasons:
        lines.append(
            f"| {row.season} | {row.rating_defensive_ordering:+.4f} "
            f"| {row.table_defensive_ordering:+.4f} |"
        )
    verdict = study.verdict
    lines += [
        "",
        "## Verdict",
        "",
        f"- Better in {verdict['seasons_better']} of {verdict['seasons_total']} seasons; "
        f"pooled improvement {float(str(verdict['pooled_improvement'])):+.4f}.",
        (
            "**The clause passes in its measurable form**: the rating's clean-sheet channel "
            "carries information beyond last season's table. #139's recorded verdict is "
            "unchanged; what changes is what Route C may consume, per the pre-registration."
            if verdict["passes"]
            else "**The clause fails in its measurable form**: the rating's clean-sheet "
            "channel adds nothing over last season's table. Route C must not consume it "
            "uncapped, and the negative is recorded."
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "CS_REMEASURE_CONTRACT_VERSION",
    "CsRemeasureConfig",
    "CsRemeasureStudy",
    "CsSeasonRow",
    "fit_table_baseline",
    "previous_season_points",
    "promoted_points_fill",
    "run_cs_remeasure",
    "study_to_markdown",
]
