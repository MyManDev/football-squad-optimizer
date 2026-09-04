"""Does an opponent-aware adjustment survive to the decision, or die on the way there?

Two earlier stages set this one up, and they disagree. The schedule signal study found that
scaling a five-week projection by the platform's published difficulty rating improves error
by a small but statistically clear amount and **loses 2.6 points a window** at the decision
level. The team rating study then found that a Dixon-Coles rating fitted to goals orders
attackers' points three times as well as that published rating does. So one instrument is
better; whether *better ordering* becomes *better decisions* is the open question, and it is
the only question that matters for the live path.

This stage measures the adjustment where the system actually lives: on the operational
control's own out-of-sample projections across 147 walk-forward folds, and on the squad a
CP-SAT optimizer builds from them.

The adjustment is deliberately the simplest shape that respects how the two halves of a
squad are paid:

- attackers scale with the goals the rating expects **their club** to score in the fixture;
- goalkeepers and defenders scale with the **clean-sheet probability** the rating implies.

Both signals are per fixture, not per gameweek, so a double gameweek does not enter through
the difficulty term — the control already scales by the calendar, and counting it twice
would measure the calendar again rather than the opponent. Coefficients are fitted per
position on the residuals of *earlier* seasons only, so no fold is judged by a fit that saw
it.

A published-rating variant of the same shape runs beside it. Without it the study could only
say whether an adjustment helps; with it, it can say whether **this** rating helps where the
published one did not.

Nothing here promotes anything. `prediction/` belongs to the data side, the team rating did
not clear its own gate, and the locked holdout is refused.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.control_residuals import build_control_residual_table
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.team_rating import (
    ATTACKING_POSITIONS,
    DixonColesConfig,
    fit_dixon_coles,
    load_match_results,
    measure_promoted_prior,
    promoted_clubs,
    select_dixon_coles_config,
)
from squadopt.optimization import OptimizationConfig, optimize_squad

OPPONENT_PROJECTION_STUDY_CONTRACT_VERSION: Final = "opponent_projection_study_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
POSITIONS: Final = ("GK", "DEF", "MID", "FWD")

#: Each candidate names the pair of per-fixture signal columns it scales by, attacking
#: first. Both candidates use the same functional shape so the comparison is of the
#: instruments, not of two different ideas.
CANDIDATES: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "R_team_rating": ("rating_attacking_signal", "rating_defensive_signal"),
        "P_published_rating": ("published_signal", "published_signal"),
    }
)
CONTROL_NAME: Final = "deterministic_baseline_control"


@dataclass(frozen=True, slots=True)
class OpponentProjectionConfig:
    """Which folds are judged, how the rating is fitted, and how the interval is drawn."""

    seasons: tuple[str, ...] = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
    development_seasons: tuple[str, ...] = ("2021-22", "2022-23", "2023-24", "2024-25")
    evaluated_seasons: tuple[str, ...] = ("2022-23", "2023-24", "2024-25")
    half_life_grid: tuple[float, ...] = (60.0, 120.0, 180.0, 300.0, 500.0)
    ridge_grid: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0)
    rating_selection_gameweek: int = 6
    bootstrap_resamples: int = 2000
    deterministic_seed: int = 0
    minimum_training_folds: int = 20

    def __post_init__(self) -> None:
        if LOCKED_HOLDOUT_SEASON in self.seasons or LOCKED_HOLDOUT_SEASON in self.evaluated_seasons:
            raise ExperimentConfigurationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be read."
            )
        if not set(self.development_seasons) <= set(self.seasons):
            raise ExperimentConfigurationError("Development seasons must be part of the study.")
        if not set(self.evaluated_seasons) <= set(self.development_seasons):
            raise ExperimentConfigurationError("Evaluated seasons must be development seasons.")
        for season in self.evaluated_seasons:
            if season == min(self.development_seasons):
                raise ExperimentConfigurationError(
                    "The earliest development season has no residuals before it to fit on."
                )
        if self.bootstrap_resamples < 100:
            raise ExperimentConfigurationError("bootstrap_resamples must be at least 100.")


# --- results ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FoldOutcome:
    """One walk-forward fold, judged twice: on error and on the squad it produces."""

    fold_id: str
    season: str
    gameweek: int
    rows: int
    control_absolute_error: float
    candidate_absolute_error: float
    control_rank_correlation: float
    candidate_rank_correlation: float
    control_realized_points: float
    candidate_realized_points: float
    changed_starters: int
    mean_multiplier: float
    minimum_multiplier: float
    maximum_multiplier: float

    @property
    def error_improvement(self) -> float:
        return self.control_absolute_error - self.candidate_absolute_error

    @property
    def rank_improvement(self) -> float:
        return self.candidate_rank_correlation - self.control_rank_correlation

    @property
    def decision_difference(self) -> float:
        return self.candidate_realized_points - self.control_realized_points


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    candidate: str
    folds: tuple[FoldOutcome, ...]
    coefficients: Mapping[str, Mapping[str, float]]
    error_improvement: float
    error_interval: tuple[float, float]
    per_season_error_improvement: Mapping[str, float]
    rank_improvement: float
    per_season_rank_improvement: Mapping[str, float]
    decision_difference: float
    decision_interval: tuple[float, float]
    per_season_decision_difference: Mapping[str, float]

    @property
    def accuracy_passes(self) -> bool:
        return (
            self.error_improvement > 0.0
            and self.error_interval[0] > 0.0
            and bool(self.per_season_error_improvement)
            and all(value > 0.0 for value in self.per_season_error_improvement.values())
        )

    @property
    def ordering_passes(self) -> bool:
        worse = sum(1 for value in self.per_season_rank_improvement.values() if value < 0.0)
        return self.rank_improvement >= 0.0 and worse <= 1

    @property
    def decision_passes(self) -> bool:
        return self.decision_difference > 0.0 and self.decision_interval[0] > 0.0


@dataclass(frozen=True, slots=True)
class OpponentProjectionStudy:
    contract_version: str
    config: OpponentProjectionConfig
    population: Mapping[str, Mapping[str, float]]
    candidates: tuple[CandidateOutcome, ...]
    verdict: Mapping[str, object]
    diagnostics: Mapping[str, object]


# --- population ---------------------------------------------------------------


def _club_bridge(archive_root: Path, seasons: Sequence[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for season in seasons:
        codes = load_team_codes(archive_root, season).loc[:, ["code", "name"]].copy()
        codes["season"] = season
        frames.append(codes)
    return pd.concat(frames, ignore_index=True).rename(columns={"name": "team_id"})


def build_opponent_rows(
    archive_root: Path | str, config: OpponentProjectionConfig | None = None
) -> pd.DataFrame:
    """The control's out-of-sample folds, with a per-fixture opponent signal attached.

    The rating is refitted once per fold, on matches that kicked off before that gameweek's
    first, and its half life and ridge are selected on the seasons before the fold's own —
    the same discipline the rating study used, carried into the place it would be consumed.
    """

    settings = OpponentProjectionConfig() if config is None else config
    root = Path(archive_root)
    panel = build_panel(root)
    panel = panel.loc[panel["season"].isin(list(settings.seasons))].copy()
    residuals = build_control_residual_table(
        panel, PolicyObjectiveConfig(development_seasons=settings.development_seasons)
    )
    matches = load_match_results(root, settings.seasons)
    fixtures = build_fixture_panel(root, seasons=tuple(settings.seasons))
    bridge = _club_bridge(root, settings.seasons)
    residuals = residuals.merge(bridge, on=["season", "team_id"], how="left")
    if bool(residuals["code"].isna().any()):
        raise ExperimentExecutionError("A residual row's club does not resolve to a code.")
    residuals["club"] = residuals["code"].astype("int64")
    prices = panel.loc[:, ["season", "gameweek", "player_id", "price_tenths", "name"]]
    residuals = residuals.merge(prices, on=["season", "gameweek", "player_id"], how="left")
    if bool(residuals["price_tenths"].isna().any()):
        raise ExperimentExecutionError("A residual row carries no deadline price.")

    promoted = promoted_clubs(matches)
    schedule = (
        fixtures.loc[:, ["season", "gameweek", "team_id", "opponent_team_id", "is_home"]]
        .rename(columns={"team_id": "club", "opponent_team_id": "opponent"})
        .astype({"club": "int64", "opponent": "int64"})
    )
    selected: dict[str, DixonColesConfig] = {}
    pieces: list[pd.DataFrame] = []
    for season, season_folds in residuals.groupby("season", sort=True):
        earlier = [value for value in settings.seasons if value < str(season)]
        if not earlier:
            continue
        if str(season) not in selected:
            selected[str(season)] = select_dixon_coles_config(
                matches.loc[matches["season"].isin(earlier)],
                earlier,
                half_life_grid=settings.half_life_grid,
                ridge_grid=settings.ridge_grid,
                first_gameweek=settings.rating_selection_gameweek,
            )
        chosen = selected[str(season)]
        prior = measure_promoted_prior(matches, earlier, chosen)
        arrivals = promoted.get(str(season), ())
        for label, block in season_folds.groupby("gameweek", sort=True):
            gameweek = int(str(label))
            kickoffs = matches.loc[
                (matches["season"] == season) & (matches["gameweek"] == gameweek), "kickoff"
            ]
            if kickoffs.empty:
                continue
            as_of = pd.Timestamp(kickoffs.min())
            if matches.loc[matches["kickoff"] < as_of].empty:
                continue
            rating = fit_dixon_coles(
                matches,
                as_of=as_of,
                config=chosen,
                promoted_prior=prior,
                newly_promoted=arrivals,
            )
            week_fixtures = schedule.loc[
                (schedule["season"] == season) & (schedule["gameweek"] == gameweek)
            ]
            attacking: dict[int, list[float]] = {}
            defensive: dict[int, list[float]] = {}
            published: dict[int, list[float]] = {}
            difficulty_lookup = _difficulty_lookup(matches, str(season), gameweek)
            for record in week_fixtures.to_dict("records"):
                club = int(record["club"])
                opponent = int(record["opponent"])
                is_home = bool(record["is_home"])
                home_rate, away_rate = (
                    rating.expected_goals(club, opponent)
                    if is_home
                    else rating.expected_goals(opponent, club)
                )
                attacking.setdefault(club, []).append(home_rate if is_home else away_rate)
                defensive.setdefault(club, []).append(
                    rating.clean_sheet_probability(club, opponent, is_home=is_home)
                )
                published.setdefault(club, []).append(
                    difficulty_lookup.get((club, opponent, is_home), float("nan"))
                )
            frame = block.copy()
            frame["rating_attacking_signal"] = [
                _mean_or_nan(attacking.get(int(club), [])) for club in frame["club"]
            ]
            frame["rating_defensive_signal"] = [
                _mean_or_nan(defensive.get(int(club), [])) for club in frame["club"]
            ]
            # The published scale runs one (easy) to five (hard); inverted here so both
            # instruments point the same way and a positive coefficient means the same thing.
            frame["published_signal"] = [
                -_mean_or_nan(published.get(int(club), [])) for club in frame["club"]
            ]
            frame["fixture_count"] = [
                float(len(attacking.get(int(club), []))) for club in frame["club"]
            ]
            pieces.append(frame)
    if not pieces:
        raise ExperimentExecutionError("No fold could be assembled.")
    rows = pd.concat(pieces, ignore_index=True)
    return rows.sort_values(["season", "gameweek", "player_id"], kind="stable").reset_index(
        drop=True
    )


def _mean_or_nan(values: Sequence[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return float(np.mean(finite)) if finite else float("nan")


def _difficulty_lookup(
    matches: pd.DataFrame, season: str, gameweek: int
) -> Mapping[tuple[int, int, bool], float]:
    block = matches.loc[(matches["season"] == season) & (matches["gameweek"] == gameweek)]
    lookup: dict[tuple[int, int, bool], float] = {}
    for record in block.to_dict("records"):
        home = int(record["home_club"])
        away = int(record["away_club"])
        lookup[(home, away, True)] = float(record["home_difficulty"])
        lookup[(away, home, False)] = float(record["away_difficulty"])
    return lookup


# --- is the published rating admissible evidence? --------------------------------


def _league_points(matches: pd.DataFrame) -> pd.Series:
    """The plain league table: three for a win, one for a draw."""

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


def _club_hardness(matches: pd.DataFrame) -> pd.Series:
    """How hard the published rating says each club is to play, averaged over both venues."""

    home = matches.loc[:, ["away_club", "home_difficulty"]].rename(
        columns={"away_club": "club", "home_difficulty": "difficulty"}
    )
    away = matches.loc[:, ["home_club", "away_difficulty"]].rename(
        columns={"home_club": "club", "away_difficulty": "difficulty"}
    )
    return pd.concat([home, away], ignore_index=True).groupby("club")["difficulty"].mean()


def published_rating_hindsight(
    matches: pd.DataFrame, seasons: Sequence[str]
) -> Mapping[str, Mapping[str, float]]:
    """Does the archived difficulty rating know the season it is describing?

    The rating is a pre-match input everywhere it is used, and the archive stores exactly one
    value per club per venue per season — constant across the season, so it cannot encode
    fixture-level hindsight. Whether it encodes *season-level* hindsight is a different
    question, and this answers it: a rating set before a season should track the previous
    season's table more closely than the coming one's. Where it does the reverse, the value
    in the archive was not knowable at the deadlines it is being used at.
    """

    ordered = sorted({str(value) for value in matches["season"]})
    report: dict[str, dict[str, float]] = {}
    for season in seasons:
        position = ordered.index(str(season)) if str(season) in ordered else -1
        if position < 1:
            continue
        block = matches.loc[matches["season"] == season]
        previous = matches.loc[matches["season"] == ordered[position - 1]]
        if block.empty or previous.empty:
            continue
        hardness = _club_hardness(block)
        current_table = _league_points(block)
        previous_table = _league_points(previous)
        report[str(season)] = {
            "against_this_season": _spearman_series(hardness, current_table),
            "against_previous_season": _spearman_series(hardness, previous_table),
            "clubs_shared_with_previous": float(
                len(hardness.index.intersection(previous_table.index))
            ),
        }
    return report


def _spearman_series(left: pd.Series, right: pd.Series) -> float:
    shared = left.index.intersection(right.index)
    if len(shared) < 5:
        return float("nan")
    frame = pd.DataFrame({"left": left[shared], "right": right[shared]})
    value = float(str(frame.corr(method="spearman").iloc[0, 1]))
    return value if math.isfinite(value) else float("nan")


def hindsight_flagged(report: Mapping[str, Mapping[str, float]]) -> tuple[str, ...]:
    """Seasons where the published rating tracks its own season better than the one before."""

    flagged: list[str] = []
    for season, values in report.items():
        current = values.get("against_this_season", float("nan"))
        previous = values.get("against_previous_season", float("nan"))
        if math.isfinite(current) and math.isfinite(previous) and current > previous:
            flagged.append(str(season))
    return tuple(sorted(flagged))


# --- fitting ------------------------------------------------------------------


def _signal_for(rows: pd.DataFrame, candidate: str) -> np.ndarray:
    """The per-fixture signal each row is scaled by, chosen by the row's position."""

    attacking_column, defensive_column = CANDIDATES[candidate]
    attacking = rows["position"].isin(ATTACKING_POSITIONS).to_numpy()
    values = np.where(
        attacking,
        rows[attacking_column].to_numpy(dtype="float64"),
        rows[defensive_column].to_numpy(dtype="float64"),
    )
    return np.asarray(values, dtype="float64")


def fit_adjustment(training: pd.DataFrame, candidate: str) -> Mapping[str, tuple[float, float]]:
    """Per position, how strongly the control's residual moves with the fixture signal.

    The fit is ``residual ~ predicted * (signal - mean signal)`` through the origin, which is
    the multiplicative shape the adjustment applies: a fixture kinder than average lifts a
    projection in proportion to what it already was, and a player projected at zero is not
    lifted by a kind fixture, because he is not playing.
    """

    signal = _signal_for(training, candidate)
    predicted = training["predicted_points"].to_numpy(dtype="float64")
    residual = training["residual"].to_numpy(dtype="float64")
    positions = training["position"].to_numpy()
    coefficients: dict[str, tuple[float, float]] = {}
    for position in POSITIONS:
        mask = (positions == position) & np.isfinite(signal)
        if not mask.any():
            coefficients[position] = (0.0, 0.0)
            continue
        centre = float(np.mean(signal[mask]))
        regressor = predicted[mask] * (signal[mask] - centre)
        denominator = float(np.sum(regressor**2))
        if denominator <= 0.0:
            coefficients[position] = (0.0, centre)
            continue
        slope = float(np.sum(regressor * residual[mask]) / denominator)
        coefficients[position] = (slope, centre)
    return coefficients


def apply_adjustment(
    rows: pd.DataFrame, candidate: str, coefficients: Mapping[str, tuple[float, float]]
) -> tuple[np.ndarray, np.ndarray]:
    """Return the adjusted projection and the multiplier that produced it."""

    signal = _signal_for(rows, candidate)
    predicted = rows["predicted_points"].to_numpy(dtype="float64")
    positions = rows["position"].to_numpy()
    multiplier = np.ones(len(rows), dtype="float64")
    for position in POSITIONS:
        mask = positions == position
        if not mask.any():
            continue
        slope, centre = coefficients.get(position, (0.0, 0.0))
        deviation = signal[mask] - centre
        # A club with no fixture has no opponent, so it has no adjustment either.
        deviation = np.nan_to_num(deviation, nan=0.0)
        multiplier[mask] = 1.0 + slope * deviation
    # A negative expectation is not a projection; the multiplier is floored rather than
    # capped, so a strong signal is allowed to say what it says.
    multiplier = np.clip(multiplier, 0.0, None)
    return predicted * multiplier, multiplier


def _rank_correlation(rows: pd.DataFrame, prediction: np.ndarray) -> float:
    frame = rows.loc[:, ["position", "realized_points"]].copy()
    frame["prediction"] = prediction
    values: list[float] = []
    for position in POSITIONS:
        block = frame.loc[frame["position"] == position]
        if len(block) < 5 or block["prediction"].nunique() < 2:
            continue
        correlation = float(
            str(block[["prediction", "realized_points"]].corr(method="spearman").iloc[0, 1])
        )
        if math.isfinite(correlation):
            values.append(correlation)
    return float(np.mean(values)) if values else 0.0


def _bootstrap(values: np.ndarray, *, resamples: int, seed: int) -> tuple[float, float]:
    """Percentile interval of the mean, resampled over folds rather than players.

    Players inside one gameweek share a projection model, a calendar and a set of matches,
    so treating them as independent draws would make every interval look far tighter than
    the evidence is. The fold is the independent unit here.
    """

    if values.size == 0:
        return (0.0, 0.0)
    generator = np.random.default_rng(seed)
    draws = np.empty(resamples, dtype="float64")
    for index in range(resamples):
        sample = generator.integers(0, values.size, values.size)
        draws[index] = float(values[sample].mean())
    return (float(np.quantile(draws, 0.05)), float(np.quantile(draws, 0.95)))


def _squad(
    block: pd.DataFrame, prediction: np.ndarray, optimization: OptimizationConfig
) -> tuple[tuple[int, ...], int]:
    projection = block.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]].copy()
    projection["expected_points"] = np.clip(np.nan_to_num(prediction, nan=0.0), 0.0, None)
    result = optimize_squad(projection, optimization)
    if not result.has_solution or result.captain is None:
        raise ExperimentExecutionError("A fold's squad could not be built.")
    starters = tuple(int(value) for value in result.starting_xi["player_id"])
    return starters, int(result.captain["player_id"])


def _realized(block: pd.DataFrame, starters: Sequence[int], captain: int) -> float:
    realized = dict(
        zip(
            (int(value) for value in block["player_id"]),
            (float(value) for value in block["realized_points"]),
            strict=True,
        )
    )
    total = float(sum(realized.get(int(player), 0.0) for player in starters))
    return total + float(realized.get(int(captain), 0.0))


def evaluate_candidate(
    rows: pd.DataFrame, candidate: str, config: OpponentProjectionConfig
) -> CandidateOutcome:
    """Walk forward across folds, judging error, ordering, and the squad each fold buys."""

    optimization = OptimizationConfig()
    outcomes: list[FoldOutcome] = []
    coefficients: Mapping[str, tuple[float, float]] = {}
    for season in config.evaluated_seasons:
        training = rows.loc[rows["season"] < season]
        if training["fold_id"].nunique() < config.minimum_training_folds:
            continue
        coefficients = fit_adjustment(training, candidate)
        judged = rows.loc[rows["season"] == season]
        for fold_id, block in judged.groupby("fold_id", sort=True):
            adjusted, multiplier = apply_adjustment(block, candidate, coefficients)
            control = block["predicted_points"].to_numpy(dtype="float64")
            realized = block["realized_points"].to_numpy(dtype="float64")
            control_starters, control_captain = _squad(block, control, optimization)
            candidate_starters, candidate_captain = _squad(block, adjusted, optimization)
            outcomes.append(
                FoldOutcome(
                    fold_id=str(fold_id),
                    season=str(season),
                    gameweek=int(block["gameweek"].iloc[0]),
                    rows=len(block),
                    control_absolute_error=float(np.abs(realized - control).mean()),
                    candidate_absolute_error=float(np.abs(realized - adjusted).mean()),
                    control_rank_correlation=_rank_correlation(block, control),
                    candidate_rank_correlation=_rank_correlation(block, adjusted),
                    control_realized_points=_realized(block, control_starters, control_captain),
                    candidate_realized_points=_realized(
                        block, candidate_starters, candidate_captain
                    ),
                    changed_starters=len(set(candidate_starters) - set(control_starters)),
                    mean_multiplier=float(np.mean(multiplier)),
                    minimum_multiplier=float(np.min(multiplier)),
                    maximum_multiplier=float(np.max(multiplier)),
                )
            )
    if not outcomes:
        raise ExperimentExecutionError(f"{candidate}: no fold could be judged.")
    errors = np.asarray([outcome.error_improvement for outcome in outcomes], dtype="float64")
    decisions = np.asarray([outcome.decision_difference for outcome in outcomes], dtype="float64")
    per_season_error: dict[str, float] = {}
    per_season_rank: dict[str, float] = {}
    per_season_decision: dict[str, float] = {}
    for season in config.evaluated_seasons:
        picked = [outcome for outcome in outcomes if outcome.season == season]
        if not picked:
            continue
        per_season_error[season] = float(np.mean([item.error_improvement for item in picked]))
        per_season_rank[season] = float(np.mean([item.rank_improvement for item in picked]))
        per_season_decision[season] = float(np.mean([item.decision_difference for item in picked]))
    return CandidateOutcome(
        candidate=candidate,
        folds=tuple(outcomes),
        coefficients={
            position: {"slope": values[0], "centre": values[1]}
            for position, values in coefficients.items()
        },
        error_improvement=float(errors.mean()),
        error_interval=_bootstrap(
            errors, resamples=config.bootstrap_resamples, seed=config.deterministic_seed
        ),
        per_season_error_improvement=per_season_error,
        rank_improvement=float(np.mean([outcome.rank_improvement for outcome in outcomes])),
        per_season_rank_improvement=per_season_rank,
        decision_difference=float(decisions.mean()),
        decision_interval=_bootstrap(
            decisions, resamples=config.bootstrap_resamples, seed=config.deterministic_seed + 1
        ),
        per_season_decision_difference=per_season_decision,
    )


# --- the gate -----------------------------------------------------------------


def gate_verdict(outcome: CandidateOutcome) -> dict[str, object]:
    """The bar, fixed before the numbers existed, applied by code rather than by hand.

    Three conditions, all required. The projection must be more accurate — pooled over folds,
    with the fold-level interval clear of zero and the sign holding in every judged season.
    Its ordering must not get worse. And the squad it builds must score more, with its own
    fold-level interval clear of zero: the schedule signal study is the standing proof that
    an adjustment can improve error and lose points, so the decision is not an afterthought
    here, it is the clause with the strictest interval.
    """

    return {
        "candidate": outcome.candidate,
        "accuracy_passes": outcome.accuracy_passes,
        "ordering_passes": outcome.ordering_passes,
        "decision_passes": outcome.decision_passes,
        "error_improvement": outcome.error_improvement,
        "decision_difference": outcome.decision_difference,
        "folds": len(outcome.folds),
        "passes": bool(
            outcome.accuracy_passes and outcome.ordering_passes and outcome.decision_passes
        ),
    }


def run_opponent_projection_study(
    archive_root: Path | str, config: OpponentProjectionConfig | None = None
) -> OpponentProjectionStudy:
    """Measure both instruments inside the control's own projection, and judge them."""

    settings = OpponentProjectionConfig() if config is None else config
    rows = build_opponent_rows(archive_root, settings)
    matches = load_match_results(Path(archive_root), settings.seasons)
    hindsight = published_rating_hindsight(matches, settings.evaluated_seasons)
    flagged = hindsight_flagged(hindsight)
    population = {
        str(season): {
            "folds": float(block["fold_id"].nunique()),
            "rows": float(len(block)),
            "mean_predicted_points": float(block["predicted_points"].mean()),
            "mean_realized_points": float(block["realized_points"].mean()),
            "mean_attacking_signal": float(block["rating_attacking_signal"].mean()),
            "mean_defensive_signal": float(block["rating_defensive_signal"].mean()),
        }
        for season, block in rows.groupby("season", sort=True)
    }
    candidates = tuple(evaluate_candidate(rows, name, settings) for name in CANDIDATES)
    verdicts = [gate_verdict(outcome) for outcome in candidates]
    passing = [verdict for verdict in verdicts if verdict["passes"]]
    # The gate is exactly what was declared and its verdicts stand as computed. Whether a
    # candidate may be carried forward is a separate question, and a signal that fails the
    # hindsight check is not admissible evidence however well it scored.
    admissible = [
        verdict
        for verdict in passing
        if not (verdict["candidate"] == "P_published_rating" and flagged)
    ]
    recommended = (
        max(admissible, key=lambda verdict: float(str(verdict["decision_difference"])))["candidate"]
        if admissible
        else None
    )
    blocked_by = "published_difficulty_hindsight" if passing and not admissible else None
    return OpponentProjectionStudy(
        contract_version=OPPONENT_PROJECTION_STUDY_CONTRACT_VERSION,
        config=settings,
        population=population,
        candidates=candidates,
        verdict={
            "per_candidate": verdicts,
            "any_candidate_passes": bool(passing),
            "recommended_candidate": recommended,
            "recommendation_blocked_by": blocked_by,
        },
        diagnostics={
            "control": CONTROL_NAME,
            "seasons": list(settings.seasons),
            "development_seasons": list(settings.development_seasons),
            "evaluated_seasons": list(settings.evaluated_seasons),
            "locked_holdout_accessed": False,
            "promotion_available": False,
            "published_rating_hindsight": {
                season: dict(values) for season, values in hindsight.items()
            },
            "published_rating_hindsight_flagged": list(flagged),
            "promotion_note": (
                "The team rating did not clear its own gate and `prediction/` belongs to the "
                "data side, so nothing here can promote a projection change. A passing "
                "result is evidence for a joint declared candidate, not a change."
            ),
        },
    )


def study_to_markdown(study: OpponentProjectionStudy) -> str:
    """The artifact a reader can check without running anything."""

    config = study.config
    lines = [
        "# An opponent-aware adjustment, measured where the decision is made",
        "",
        f"- Contract `{study.contract_version}`; the control is "
        f"`{study.diagnostics.get('control')}` on its own walk-forward folds over "
        f"{', '.join(config.development_seasons)}, judged on "
        f"{', '.join(config.evaluated_seasons)}.",
        "- The adjustment is fitted per position on the residuals of earlier seasons only: "
        "attackers scale with the goals the rating expects their club to score, goalkeepers "
        "and defenders with the clean-sheet probability it implies, both per fixture so the "
        "calendar is not counted twice.",
        f"- Intervals are bootstrapped over **folds**, not players "
        f"({config.bootstrap_resamples} resamples, seed {config.deterministic_seed}).",
        "- Measurement only. The locked 2025-26 holdout is refused, nothing under "
        "`prediction/` changed, and the verdict was computed by `gate_verdict`.",
        "",
        "## Population",
        "",
        "| Season | Folds | Rows | Mean predicted | Mean realized |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for season, values in study.population.items():
        lines.append(
            f"| {season} | {values['folds']:.0f} | {values['rows']:.0f} "
            f"| {values['mean_predicted_points']:.3f} | {values['mean_realized_points']:.3f} |"
        )
    lines += [
        "",
        "## Candidates",
        "",
        "| Candidate | Folds | Error improvement | 90% interval | Ordering | "
        "Decision (points/fold) | 90% interval |",
        "| --- | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for outcome in study.candidates:
        error_low, error_high = outcome.error_interval
        decision_low, decision_high = outcome.decision_interval
        lines.append(
            f"| `{outcome.candidate}` | {len(outcome.folds)} "
            f"| {outcome.error_improvement:+.4f} | [{error_low:+.4f}, {error_high:+.4f}] "
            f"| {outcome.rank_improvement:+.4f} | {outcome.decision_difference:+.3f} "
            f"| [{decision_low:+.3f}, {decision_high:+.3f}] |"
        )
    lines += [
        "",
        "### Per season",
        "",
        "| Candidate | Season | Error | Ordering | Decision |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for outcome in study.candidates:
        for season, value in outcome.per_season_error_improvement.items():
            lines.append(
                f"| `{outcome.candidate}` | {season} | {value:+.4f} "
                f"| {outcome.per_season_rank_improvement.get(season, 0.0):+.4f} "
                f"| {outcome.per_season_decision_difference.get(season, 0.0):+.3f} |"
            )
    lines += [
        "",
        "### Fitted coefficients and the multipliers they produce",
        "",
        "| Candidate | Position | Slope | Centre | Mean multiplier | Range |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for outcome in study.candidates:
        lowest = min((fold.minimum_multiplier for fold in outcome.folds), default=1.0)
        highest = max((fold.maximum_multiplier for fold in outcome.folds), default=1.0)
        mean = float(np.mean([fold.mean_multiplier for fold in outcome.folds]))
        for position, values in outcome.coefficients.items():
            lines.append(
                f"| `{outcome.candidate}` | {position} | {values['slope']:+.4f} "
                f"| {values['centre']:+.4f} | {mean:.4f} | [{lowest:.3f}, {highest:.3f}] |"
            )
    lines += [
        "",
        "## Verdict",
        "",
        "The gate: more accurate pooled over folds with the fold-level interval clear of "
        "zero and the sign holding every season; an ordering that does not get worse; and a "
        "squad that scores more, with its own fold-level interval clear of zero.",
        "",
    ]
    verdicts = study.verdict["per_candidate"]
    assert isinstance(verdicts, list)
    for verdict in verdicts:
        lines.append(
            f"- `{verdict['candidate']}`: {'passes' if verdict['passes'] else 'fails'} "
            f"(accuracy: {verdict['accuracy_passes']}; ordering: {verdict['ordering_passes']}; "
            f"decision: {verdict['decision_passes']}; "
            f"{verdict['decision_difference']:+.3f} realized points per fold over "
            f"{verdict['folds']} folds)."
        )
    hindsight = study.diagnostics.get("published_rating_hindsight", {})
    assert isinstance(hindsight, dict)
    lines += [
        "",
        "## Is the published rating admissible?",
        "",
        "The archive stores one difficulty value per club per venue per season, constant "
        "across the season, so it cannot encode fixture-level hindsight. Whether it encodes "
        "*season-level* hindsight is testable: a rating set before a season should track the "
        "previous season's table more closely than the coming one's.",
        "",
        "| Season | Correlation with this season's table | With the previous season's |",
        "| --- | ---: | ---: |",
    ]
    for season, values in hindsight.items():
        lines.append(
            f"| {season} | {values['against_this_season']:+.3f} "
            f"| {values['against_previous_season']:+.3f} |"
        )
    flagged = study.diagnostics.get("published_rating_hindsight_flagged", [])
    assert isinstance(flagged, list)
    lines += [
        "",
        (
            f"Flagged: {', '.join(str(value) for value in flagged)} — the rating tracks its "
            "own season better than the one before it, so at least part of what it knows was "
            "not knowable at the deadlines it is used at."
            if flagged
            else "No season is flagged."
        ),
        "",
    ]
    recommended = study.verdict["recommended_candidate"]
    blocked = study.verdict.get("recommendation_blocked_by")
    lines += [
        "",
        (
            f"Recommended candidate: `{recommended}` — evidence for a joint declared "
            "candidate with the data side, not a promotion."
            if recommended
            else (
                "A candidate cleared the gate but is **not** carried forward: its signal "
                f"failed the hindsight check (`{blocked}`)."
                if blocked
                else "No candidate cleared the gate; nothing is proposed."
            )
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "CANDIDATES",
    "CONTROL_NAME",
    "LOCKED_HOLDOUT_SEASON",
    "OPPONENT_PROJECTION_STUDY_CONTRACT_VERSION",
    "POSITIONS",
    "CandidateOutcome",
    "FoldOutcome",
    "OpponentProjectionConfig",
    "OpponentProjectionStudy",
    "apply_adjustment",
    "build_opponent_rows",
    "evaluate_candidate",
    "fit_adjustment",
    "gate_verdict",
    "hindsight_flagged",
    "published_rating_hindsight",
    "run_opponent_projection_study",
    "study_to_markdown",
]
