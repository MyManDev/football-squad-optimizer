"""Does the published schedule predict a five-week window better than a flat projection?

Every recommendation this system makes over a one-, three- or five-week window rests on an
assumption nobody here has measured: that the weeks inside the window differ. Today's
projection is opponent-blind, so a five-week plan is five copies of the same number scaled
by how many fixtures the calendar holds. Knowing the *calendar* is already worth about 58
points a season against a calendar-blind control; whether knowing the *difficulty* inside
that calendar is worth anything on top is the question that decides whether a team rating
and an opponent-aware projection are worth building at all.

Four rules are compared over the same windows, each fitted the same way on the seasons that
precede the judged one:

- ``A_flat`` — window length times a player's recent per-week rate. Calendar-blind.
- ``B_calendar`` — the rate times the number of fixtures the window actually holds.
- ``C_published_difficulty`` — the calendar, with each fixture scaled by the platform's own
  published difficulty rating.
- ``D_carried_strength`` — the calendar, with each fixture scaled by an opponent-strength
  proxy computed from results already played, split by the side of the ball the player's
  position is paid for.

Two comparisons matter and they answer different questions. ``B`` against ``A`` asks whether
the schedule carries information at all. ``C`` and ``D`` against ``B`` ask whether the
*difficulty* carries information beyond the count — and that is the increment stage one of
the programme is proposing to buy. The gate below was fixed before the numbers existed and
is applied by :func:`gate_verdict`, not by hand.

Everything read here is known before the window's first deadline: the rate is taken from
gameweeks strictly before the origin, the fixture list and its published difficulty are
published in advance, and the strength proxy uses only completed gameweeks. The locked
holdout season is refused rather than merely unused.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, NamedTuple

import numpy as np
import pandas as pd

from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.optimization import OptimizationConfig, optimize_squad

SCHEDULE_SIGNAL_STUDY_CONTRACT_VERSION: Final = "schedule_signal_study_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
POSITIONS: Final = ("GK", "DEF", "MID", "FWD")
ATTACKING_POSITIONS: Final = ("MID", "FWD")
DEFENSIVE_POSITIONS: Final = ("GK", "DEF")

#: Each rule names the ease column it scales fixtures by; ``None`` means "count only".
#: ``A_flat`` is the one rule that ignores the fixture count as well.
RULES: Final[Mapping[str, str | None]] = MappingProxyType(
    {
        "A_flat": None,
        "B_calendar": None,
        "C_published_difficulty": "published_ease",
        "D_carried_strength": "carried_ease",
    }
)
FLAT_RULE: Final = "A_flat"
CALENDAR_RULE: Final = "B_calendar"
DIFFICULTY_RULES: Final = ("C_published_difficulty", "D_carried_strength")


@dataclass(frozen=True, slots=True)
class ScheduleSignalConfig:
    """Which seasons are fitted, which windows are judged, and how the interval is drawn."""

    seasons: tuple[str, ...] = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
    evaluated_seasons: tuple[str, ...] = ("2022-23", "2023-24", "2024-25")
    window_length: int = 5
    origin_gameweeks: tuple[int, ...] = (6, 11, 16, 21, 26, 31)
    form_window: int = 5
    minimum_prior_minutes: int = 180
    bootstrap_resamples: int = 2000
    deterministic_seed: int = 0
    transfer_cost_points: float = 4.0
    minimum_training_rows: int = 200

    def __post_init__(self) -> None:
        if LOCKED_HOLDOUT_SEASON in self.seasons or LOCKED_HOLDOUT_SEASON in self.evaluated_seasons:
            raise ExperimentConfigurationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be read."
            )
        if not set(self.evaluated_seasons) <= set(self.seasons):
            raise ExperimentConfigurationError("Evaluated seasons must be part of the study.")
        for season in self.evaluated_seasons:
            if season == min(self.seasons):
                raise ExperimentConfigurationError(
                    "The earliest season has nothing before it to fit on."
                )
        if self.window_length < 1:
            raise ExperimentConfigurationError("window_length must be at least one gameweek.")
        if not self.origin_gameweeks:
            raise ExperimentConfigurationError("At least one origin gameweek is required.")
        if min(self.origin_gameweeks) <= self.form_window:
            raise ExperimentConfigurationError(
                "Every origin must leave a full form window of completed gameweeks before it."
            )
        if self.bootstrap_resamples < 100:
            raise ExperimentConfigurationError("bootstrap_resamples must be at least 100.")


# --- results ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleSeasonResult:
    """One rule judged on one season's windows."""

    rule: str
    season: str
    rows: int
    mean_absolute_error: float
    bias: float
    rank_correlation: float


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule: str
    seasons: tuple[RuleSeasonResult, ...]
    pooled_rows: int
    pooled_mean_absolute_error: float
    pooled_rank_correlation: float
    coefficients: Mapping[str, Mapping[str, float]]
    """Per position, the coefficients fitted for the last evaluated season."""


@dataclass(frozen=True, slots=True)
class Comparison:
    """One rule measured against another, paired player by player."""

    rule: str
    reference: str
    rows: int
    error_improvement: float
    error_interval: tuple[float, float]
    per_season_error_improvement: Mapping[str, float]
    rank_improvement: float
    per_season_rank_improvement: Mapping[str, float]

    @property
    def interval_excludes_zero(self) -> bool:
        low, high = self.error_interval
        return low > 0.0 or high < 0.0

    @property
    def sign_consistent(self) -> bool:
        values = list(self.per_season_error_improvement.values())
        return bool(values) and all(value > 0.0 for value in values)

    @property
    def ordering_not_worse(self) -> bool:
        """Pooled ordering at least as good, and worse in at most one season."""

        worse = sum(1 for value in self.per_season_rank_improvement.values() if value < 0.0)
        return self.rank_improvement >= 0.0 and worse <= 1


@dataclass(frozen=True, slots=True)
class WindowDecision:
    """One origin's squad built two ways, and the best single transfer from the reference."""

    season: str
    origin_gameweek: int
    rule: str
    reference: str
    rule_realized_points: float
    reference_realized_points: float
    changed_starters: int
    transfer_realized_gain: float
    """Realized window points of the player moved in minus the player moved out."""
    transfer_net_gain: float
    """The same, net of the transfer cost; zero when the rule proposes no transfer."""
    rule_proposes_transfer: bool

    @property
    def squad_difference(self) -> float:
        return self.rule_realized_points - self.reference_realized_points


@dataclass(frozen=True, slots=True)
class ScheduleSignalStudy:
    contract_version: str
    config: ScheduleSignalConfig
    population: Mapping[str, Mapping[str, float]]
    rules: tuple[RuleResult, ...]
    comparisons: tuple[Comparison, ...]
    decisions: tuple[WindowDecision, ...]
    verdict: Mapping[str, object]
    diagnostics: Mapping[str, object]


# --- population ---------------------------------------------------------------


def _team_name_by_code(archive_root: Path, season: str) -> Mapping[int, str]:
    codes = load_team_codes(archive_root, season).loc[:, ["code", "name"]]
    return {int(code): str(name) for code, name in zip(codes["code"], codes["name"], strict=True)}


def _club_form(panel: pd.DataFrame, season: str, origin: int) -> pd.DataFrame:
    """Each club's attacking and defensive output per gameweek, from completed weeks only.

    A club's fantasy points split by unit is a proxy for its quality and is deliberately
    named one: midfielders and forwards stand in for attacking threat, goalkeepers and
    defenders for what a defence keeps out. Only gameweeks strictly before the origin are
    read, so nothing here is known later than the deadline the window opens on.
    """

    played = panel.loc[
        (panel["season"] == season) & (panel["gameweek"] < origin) & (panel["gameweek"] >= 1)
    ]
    if played.empty:
        raise ExperimentExecutionError(f"{season} gameweek {origin}: no completed gameweeks.")
    weeks = float(origin - 1)
    attacking = pd.DataFrame(
        played.loc[played["position"].isin(ATTACKING_POSITIONS)]
        .groupby("team_id", as_index=False)["total_points"]
        .sum()
    ).rename(columns={"total_points": "club_attack"})
    defensive = pd.DataFrame(
        played.loc[played["position"].isin(DEFENSIVE_POSITIONS)]
        .groupby("team_id", as_index=False)["total_points"]
        .sum()
    ).rename(columns={"total_points": "club_defence"})
    form = attacking.merge(defensive, on="team_id", how="outer").fillna(0.0)
    form["club_attack"] = form["club_attack"].astype("float64") / weeks
    form["club_defence"] = form["club_defence"].astype("float64") / weeks
    return form


def _normalized_ease(values: pd.Series) -> pd.Series:
    """Map a strength column to ease in [0, 1], one being the kindest opponent.

    Normalising within the origin rather than across the study keeps the scale comparable
    when a season's overall scoring level drifts, and uses only values already known.
    """

    numeric = pd.to_numeric(values, errors="coerce").astype("float64")
    low = float(numeric.min()) if numeric.notna().any() else 0.0
    high = float(numeric.max()) if numeric.notna().any() else 0.0
    span = high - low
    if span <= 0.0:
        return pd.Series(np.full(len(numeric), 0.5), index=numeric.index, dtype="float64")
    # A weak opponent is an easy fixture, so the strength column is inverted here.
    ease = (high - numeric) / span
    return pd.Series(ease.fillna(0.5), index=numeric.index, dtype="float64")


def _window_fixtures(
    fixtures: pd.DataFrame,
    club_form: pd.DataFrame,
    names: Mapping[int, str],
    *,
    season: str,
    origin: int,
    window_length: int,
) -> pd.DataFrame:
    """Per club, what the window's fixtures hold: how many, and how kind, by position side."""

    block = fixtures.loc[
        (fixtures["season"] == season)
        & (fixtures["gameweek"] >= origin)
        & (fixtures["gameweek"] < origin + window_length)
    ].copy()
    if block.empty:
        raise ExperimentExecutionError(f"{season} gameweek {origin}: the window holds no fixtures.")
    block["club"] = [names.get(int(value)) for value in block["team_id"]]
    block["opponent"] = [names.get(int(value)) for value in block["opponent_team_id"]]
    unresolved = int(block["club"].isna().sum() + block["opponent"].isna().sum())
    if unresolved:
        raise ExperimentExecutionError(
            f"{season} gameweek {origin}: {unresolved} fixture side(s) name no known club."
        )
    difficulty = pd.to_numeric(block["fixture_difficulty"], errors="coerce").astype("float64")
    # The platform publishes difficulty on a one-to-five scale where five is hardest.
    block["published_ease"] = ((5.0 - difficulty) / 4.0).fillna(0.5)
    strength = club_form.rename(columns={"team_id": "opponent"})
    block = block.merge(strength, on="opponent", how="left")
    league_attack = float(club_form["club_attack"].mean())
    league_defence = float(club_form["club_defence"].mean())
    block["club_attack"] = block["club_attack"].fillna(league_attack)
    block["club_defence"] = block["club_defence"].fillna(league_defence)
    # An attacker's fixture is easy when the opponent's defence is poor; a defender's is
    # easy when the opponent's attack is poor. One ease column per side of the ball.
    block["attacking_ease"] = _normalized_ease(block["club_defence"])
    block["defensive_ease"] = _normalized_ease(block["club_attack"])
    grouped = block.groupby("club", as_index=False).agg(
        fixture_count=("fixture_id", "size"),
        published_ease_sum=("published_ease", "sum"),
        attacking_ease_sum=("attacking_ease", "sum"),
        defensive_ease_sum=("defensive_ease", "sum"),
    )
    return grouped.rename(columns={"club": "team_id"})


def build_window_rows(
    archive_root: Path | str, config: ScheduleSignalConfig | None = None
) -> pd.DataFrame:
    """One row per player per window: the rate he carried in, and what the window held."""

    settings = ScheduleSignalConfig() if config is None else config
    root = Path(archive_root)
    panel = build_panel(root)
    panel = panel.loc[panel["season"].isin(settings.seasons)].copy()
    if panel.empty:
        raise ExperimentExecutionError("The archive holds none of the requested seasons.")
    fixtures = build_fixture_panel(root, seasons=tuple(settings.seasons))
    pieces: list[pd.DataFrame] = []
    for season in settings.seasons:
        names = _team_name_by_code(root, season)
        season_panel = panel.loc[panel["season"] == season]
        if season_panel.empty:
            continue
        last_gameweek = int(season_panel["gameweek"].max())
        for origin in settings.origin_gameweeks:
            if origin + settings.window_length - 1 > last_gameweek:
                continue
            prior = season_panel.loc[
                (season_panel["gameweek"] >= origin - settings.form_window)
                & (season_panel["gameweek"] < origin)
            ]
            if prior.empty:
                continue
            history = (
                prior.groupby("player_id", as_index=False)
                .agg(
                    prior_points=("total_points", "sum"),
                    prior_minutes=("minutes", "sum"),
                )
                .assign(rate=lambda frame: frame["prior_points"] / float(settings.form_window))
            )
            latest = (
                prior.sort_values(["player_id", "gameweek"], kind="stable")
                .groupby("player_id", as_index=False)
                .tail(1)
                .loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]]
            )
            rows = history.merge(latest, on="player_id", how="inner")
            rows = rows.loc[rows["prior_minutes"] >= settings.minimum_prior_minutes]
            if rows.empty:
                continue
            realized = pd.DataFrame(
                season_panel.loc[
                    (season_panel["gameweek"] >= origin)
                    & (season_panel["gameweek"] < origin + settings.window_length)
                ]
                .groupby("player_id", as_index=False)["total_points"]
                .sum()
            ).rename(columns={"total_points": "realized_points"})
            rows = rows.merge(realized, on="player_id", how="left")
            # A player absent from every gameweek in the window scored nothing in it; that
            # is an outcome, not a missing value.
            rows["realized_points"] = rows["realized_points"].fillna(0.0).astype("float64")
            club_form = _club_form(panel, season, origin)
            window = _window_fixtures(
                fixtures,
                club_form,
                names,
                season=season,
                origin=origin,
                window_length=settings.window_length,
            )
            rows = rows.merge(window, on="team_id", how="left")
            # A club with no fixture in the window has a blank window, not an average one.
            rows["fixture_count"] = rows["fixture_count"].fillna(0.0).astype("float64")
            for column in ("published_ease_sum", "attacking_ease_sum", "defensive_ease_sum"):
                rows[column] = rows[column].fillna(0.0).astype("float64")
            attacking = rows["position"].isin(ATTACKING_POSITIONS)
            rows["carried_ease_sum"] = np.where(
                attacking, rows["attacking_ease_sum"], rows["defensive_ease_sum"]
            )
            rows["season"] = season
            rows["origin_gameweek"] = int(origin)
            pieces.append(rows)
    if not pieces:
        raise ExperimentExecutionError("No window could be assembled from the archive.")
    frame = pd.concat(pieces, ignore_index=True)
    frame["window_length"] = float(settings.window_length)
    return frame.sort_values(["season", "origin_gameweek", "player_id"], kind="stable").reset_index(
        drop=True
    )


# --- fitting ------------------------------------------------------------------


def _design(rows: pd.DataFrame, rule: str) -> np.ndarray:
    """The regressors one rule fits, each already multiplied by the player's rate."""

    rate = rows["rate"].to_numpy(dtype="float64")
    if rule == FLAT_RULE:
        return np.column_stack([rate * rows["window_length"].to_numpy(dtype="float64")])
    counts = rate * rows["fixture_count"].to_numpy(dtype="float64")
    ease_column = RULES[rule]
    if ease_column is None:
        return np.column_stack([counts])
    column = "published_ease_sum" if ease_column == "published_ease" else "carried_ease_sum"
    return np.column_stack([counts, rate * rows[column].to_numpy(dtype="float64")])


def _least_squares_through_origin(design: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Ordinary least squares with no intercept; a rank-deficient design is handled."""

    if design.size == 0 or target.size == 0:
        return np.zeros(design.shape[1], dtype="float64")
    solution, _, _, _ = np.linalg.lstsq(design, target, rcond=None)
    return np.asarray(solution, dtype="float64")


def fit_rule(training: pd.DataFrame, rule: str) -> Mapping[str, tuple[float, ...]]:
    """Fit one rule's coefficients per position.

    Every rule is fitted, including the two that need no ease column, so no rule is
    handicapped by a scale the others were allowed to correct.
    """

    coefficients: dict[str, tuple[float, ...]] = {}
    for position in POSITIONS:
        block = training.loc[training["position"] == position]
        if block.empty:
            coefficients[position] = (1.0,) if rule in (FLAT_RULE, CALENDAR_RULE) else (1.0, 0.0)
            continue
        design = _design(block, rule)
        target = block["realized_points"].to_numpy(dtype="float64")
        coefficients[position] = tuple(
            float(value) for value in _least_squares_through_origin(design, target)
        )
    return coefficients


def predict_rule(
    rows: pd.DataFrame, rule: str, coefficients: Mapping[str, Sequence[float]]
) -> np.ndarray:
    """Apply a fitted rule to rows, position by position."""

    prediction = np.zeros(len(rows), dtype="float64")
    positions = rows["position"].to_numpy()
    for position in POSITIONS:
        mask = positions == position
        if not mask.any():
            continue
        block = rows.loc[mask]
        design = _design(block, rule)
        weights = np.asarray(coefficients.get(position, ()), dtype="float64")
        if weights.size != design.shape[1]:
            weights = np.zeros(design.shape[1], dtype="float64")
        prediction[mask] = design @ weights
    return np.clip(prediction, 0.0, None)


def _rank_correlation(rows: pd.DataFrame, prediction: np.ndarray) -> float:
    """Spearman correlation within position, pooled by averaging over positions."""

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


def _paired_bootstrap(differences: np.ndarray, *, resamples: int, seed: int) -> tuple[float, float]:
    """Percentile interval of the mean paired difference."""

    if differences.size == 0:
        return (0.0, 0.0)
    generator = np.random.default_rng(seed)
    draws = np.empty(resamples, dtype="float64")
    for index in range(resamples):
        sample = generator.integers(0, differences.size, differences.size)
        draws[index] = float(differences[sample].mean())
    return (float(np.quantile(draws, 0.05)), float(np.quantile(draws, 0.95)))


def evaluate_rules(
    rows: pd.DataFrame, config: ScheduleSignalConfig
) -> tuple[tuple[RuleResult, ...], Mapping[str, Mapping[str, np.ndarray]]]:
    """Walk forward: fit each rule on the seasons before the judged one, then judge it."""

    results: list[RuleResult] = []
    errors: dict[str, dict[str, np.ndarray]] = {}
    for rule in RULES:
        seasons: list[RuleSeasonResult] = []
        per_season_error: dict[str, np.ndarray] = {}
        coefficients: Mapping[str, Sequence[float]] = {}
        pooled_error: list[float] = []
        pooled_rank: list[float] = []
        pooled_rows = 0
        for season in config.evaluated_seasons:
            training = rows.loc[rows["season"] < season]
            evaluated = rows.loc[rows["season"] == season]
            if len(training) < config.minimum_training_rows or evaluated.empty:
                continue
            coefficients = fit_rule(training, rule)
            prediction = predict_rule(evaluated, rule, coefficients)
            realized = evaluated["realized_points"].to_numpy(dtype="float64")
            absolute = np.abs(realized - prediction)
            per_season_error[season] = absolute
            correlation = _rank_correlation(evaluated, prediction)
            seasons.append(
                RuleSeasonResult(
                    rule=rule,
                    season=season,
                    rows=len(evaluated),
                    mean_absolute_error=float(absolute.mean()),
                    bias=float((prediction - realized).mean()),
                    rank_correlation=correlation,
                )
            )
            pooled_error.extend(absolute.tolist())
            pooled_rank.append(correlation)
            pooled_rows += len(evaluated)
        results.append(
            RuleResult(
                rule=rule,
                seasons=tuple(seasons),
                pooled_rows=pooled_rows,
                pooled_mean_absolute_error=float(np.mean(pooled_error)) if pooled_error else 0.0,
                pooled_rank_correlation=float(np.mean(pooled_rank)) if pooled_rank else 0.0,
                coefficients={
                    position: {
                        f"coefficient_{index}": float(value) for index, value in enumerate(values)
                    }
                    for position, values in coefficients.items()
                },
            )
        )
        errors[rule] = per_season_error
    return tuple(results), errors


def compare_rules(
    results: Sequence[RuleResult],
    errors: Mapping[str, Mapping[str, np.ndarray]],
    *,
    rule: str,
    reference: str,
    config: ScheduleSignalConfig,
) -> Comparison:
    """Pair one rule against another on the same rows and draw the interval."""

    by_name = {result.rule: result for result in results}
    rule_seasons = {season.season: season for season in by_name[rule].seasons}
    reference_seasons = {season.season: season for season in by_name[reference].seasons}
    differences: list[float] = []
    per_season_error: dict[str, float] = {}
    per_season_rank: dict[str, float] = {}
    for season in config.evaluated_seasons:
        if season not in errors[rule] or season not in errors[reference]:
            continue
        paired = errors[reference][season] - errors[rule][season]
        differences.extend(paired.tolist())
        per_season_error[season] = float(paired.mean())
        per_season_rank[season] = (
            rule_seasons[season].rank_correlation - reference_seasons[season].rank_correlation
        )
    array = np.asarray(differences, dtype="float64")
    return Comparison(
        rule=rule,
        reference=reference,
        rows=int(array.size),
        error_improvement=float(array.mean()) if array.size else 0.0,
        error_interval=_paired_bootstrap(
            array, resamples=config.bootstrap_resamples, seed=config.deterministic_seed
        ),
        per_season_error_improvement=per_season_error,
        rank_improvement=(
            by_name[rule].pooled_rank_correlation - by_name[reference].pooled_rank_correlation
        ),
        per_season_rank_improvement=per_season_rank,
    )


# --- the decision ---------------------------------------------------------------


class _PoolPlayer(NamedTuple):
    """One selectable player during the transfer search."""

    player_id: int
    club: str
    position: str
    price_tenths: float
    projection: float


def _squad_from_projection(
    block: pd.DataFrame, prediction: np.ndarray, optimization: OptimizationConfig
) -> tuple[tuple[int, ...], int]:
    projection = block.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]].copy()
    projection["expected_points"] = np.clip(np.nan_to_num(prediction, nan=0.0), 0.0, None)
    result = optimize_squad(projection, optimization)
    if not result.has_solution or result.captain is None:
        raise ExperimentExecutionError("A window squad could not be built.")
    starters = tuple(int(value) for value in result.starting_xi["player_id"])
    return starters, int(result.captain["player_id"])


def _realized_squad_points(block: pd.DataFrame, starters: Sequence[int], captain: int) -> float:
    realized = block.set_index("player_id")["realized_points"].astype("float64")
    total = float(sum(float(realized.get(player, 0.0)) for player in starters))
    return total + float(realized.get(captain, 0.0))


def _best_single_transfer(
    block: pd.DataFrame,
    prediction: np.ndarray,
    held: Sequence[int],
    *,
    club_limit: int,
) -> tuple[int, int] | None:
    """The best legal one-for-one swap out of a held squad under one projection.

    Legality is deliberately conservative: same position, no more expensive than the
    player leaving (a bank of zero), and no more than three players from one club. A
    swap the rule does not think improves the window is not proposed.
    """

    frame = block.loc[:, ["player_id", "team_id", "position", "price_tenths"]].copy()
    frame["projection"] = prediction
    # Plain records rather than positional pandas lookups: the search touches every held
    # player against every eligible replacement, and a dictionary says what it means.
    pool = [
        _PoolPlayer(
            player_id=int(record["player_id"]),
            club=str(record["team_id"]),
            position=str(record["position"]),
            price_tenths=float(record["price_tenths"]),
            projection=float(record["projection"]),
        )
        for record in frame.to_dict("records")
    ]
    by_identifier = {record.player_id: record for record in pool}
    held_set = {int(player) for player in held}
    if not held_set <= set(by_identifier):
        return None
    club_counts: dict[str, int] = {}
    for player in held_set:
        club_counts[by_identifier[player].club] = club_counts.get(by_identifier[player].club, 0) + 1
    best: tuple[float, int, int] | None = None
    for outgoing in sorted(held_set):
        out_row = by_identifier[outgoing]
        for record in pool:
            if record.player_id in held_set:
                continue
            if record.position != out_row.position or record.price_tenths > out_row.price_tenths:
                continue
            count = club_counts.get(record.club, 0) - (1 if record.club == out_row.club else 0)
            if count >= club_limit:
                continue
            gain = record.projection - out_row.projection
            if gain <= 0.0:
                continue
            if best is None or gain > best[0]:
                best = (gain, outgoing, record.player_id)
    if best is None:
        return None
    return best[1], best[2]


def compare_decisions(
    rows: pd.DataFrame,
    config: ScheduleSignalConfig,
    *,
    rule: str,
    reference: str,
) -> tuple[WindowDecision, ...]:
    """Build the squad both ways at each origin, and price the transfer the rule proposes.

    Two checks, and they answer different questions. The squad comparison asks whether the
    rule's ordering changes what an optimizer buys and whether the changed squad scores
    more. The transfer comparison asks the operational question — whether a manager holding
    the reference squad gains more than the four points a transfer costs — and it prices
    the two players only, not the bench and captaincy decisions that follow, which is a
    limit of the check rather than a claim about it.
    """

    optimization = OptimizationConfig()
    decisions: list[WindowDecision] = []
    for season in config.evaluated_seasons:
        training = rows.loc[rows["season"] < season]
        if len(training) < config.minimum_training_rows:
            continue
        rule_coefficients = fit_rule(training, rule)
        reference_coefficients = fit_rule(training, reference)
        evaluated = rows.loc[rows["season"] == season]
        for origin in sorted({int(value) for value in evaluated["origin_gameweek"]}):
            block = evaluated.loc[evaluated["origin_gameweek"] == origin].copy()
            if block.empty:
                continue
            rule_prediction = predict_rule(block, rule, rule_coefficients)
            reference_prediction = predict_rule(block, reference, reference_coefficients)
            rule_starters, rule_captain = _squad_from_projection(
                block, rule_prediction, optimization
            )
            reference_starters, reference_captain = _squad_from_projection(
                block, reference_prediction, optimization
            )
            realized = block.set_index("player_id")["realized_points"].astype("float64")
            swap = _best_single_transfer(
                block,
                rule_prediction,
                reference_starters,
                club_limit=optimization.max_players_per_team,
            )
            if swap is None:
                gain = 0.0
                net = 0.0
                proposes = False
            else:
                outgoing, incoming = swap
                gain = float(realized.get(incoming, 0.0)) - float(realized.get(outgoing, 0.0))
                net = gain - config.transfer_cost_points
                proposes = True
            decisions.append(
                WindowDecision(
                    season=season,
                    origin_gameweek=origin,
                    rule=rule,
                    reference=reference,
                    rule_realized_points=_realized_squad_points(block, rule_starters, rule_captain),
                    reference_realized_points=_realized_squad_points(
                        block, reference_starters, reference_captain
                    ),
                    changed_starters=len(set(rule_starters) - set(reference_starters)),
                    transfer_realized_gain=gain,
                    transfer_net_gain=net,
                    rule_proposes_transfer=proposes,
                )
            )
    return tuple(decisions)


# --- the gate -----------------------------------------------------------------


def gate_verdict(comparison: Comparison, decisions: Sequence[WindowDecision]) -> dict[str, object]:
    """The bar, fixed before the numbers existed, applied by code rather than by hand.

    Four conditions, all of which must hold: the paired interval clears zero, the sign is
    the same in every judged season, the ordering does not get worse, and the decision
    check is not negative once a transfer is charged for.
    """

    squad_differences = [decision.squad_difference for decision in decisions]
    transfer_net = [
        decision.transfer_net_gain for decision in decisions if decision.rule_proposes_transfer
    ]
    mean_squad = float(np.mean(squad_differences)) if squad_differences else 0.0
    mean_transfer = float(np.mean(transfer_net)) if transfer_net else 0.0
    decision_passes = bool(decisions) and mean_squad >= 0.0 and mean_transfer >= 0.0
    return {
        "rule": comparison.rule,
        "reference": comparison.reference,
        "interval_excludes_zero": comparison.interval_excludes_zero,
        "sign_consistent": comparison.sign_consistent,
        "ordering_not_worse": comparison.ordering_not_worse,
        "decision_passes": decision_passes,
        "mean_squad_difference": mean_squad,
        "mean_transfer_net_gain": mean_transfer,
        "transfers_proposed": len(transfer_net),
        "passes": bool(
            comparison.interval_excludes_zero
            and comparison.sign_consistent
            and comparison.ordering_not_worse
            and decision_passes
        ),
    }


def run_schedule_signal_study(
    archive_root: Path | str, config: ScheduleSignalConfig | None = None
) -> ScheduleSignalStudy:
    """Measure the schedule against a flat projection, and difficulty against the calendar."""

    settings = ScheduleSignalConfig() if config is None else config
    rows = build_window_rows(archive_root, settings)
    population = {
        f"{season}": {
            "rows": float(len(block)),
            "windows": float(block["origin_gameweek"].nunique()),
            "mean_fixture_count": float(block["fixture_count"].mean()),
            "blank_window_share": float((block["fixture_count"] < 1.0).mean()),
            "double_week_share": float((block["fixture_count"] > settings.window_length).mean()),
            "mean_realized_points": float(block["realized_points"].mean()),
        }
        for season, block in rows.groupby("season", sort=True)
    }
    results, errors = evaluate_rules(rows, settings)
    comparisons: list[Comparison] = []
    decisions: list[WindowDecision] = []
    verdicts: list[dict[str, object]] = []
    # The calendar against the flat control, then each difficulty rule against the calendar.
    pairs = [(CALENDAR_RULE, FLAT_RULE)] + [(rule, CALENDAR_RULE) for rule in DIFFICULTY_RULES]
    for rule, reference in pairs:
        comparison = compare_rules(results, errors, rule=rule, reference=reference, config=settings)
        rule_decisions = compare_decisions(rows, settings, rule=rule, reference=reference)
        comparisons.append(comparison)
        decisions.extend(rule_decisions)
        verdicts.append(gate_verdict(comparison, rule_decisions))
    schedule_verdict = next(verdict for verdict in verdicts if verdict["reference"] == FLAT_RULE)
    difficulty_verdicts = [verdict for verdict in verdicts if verdict["reference"] == CALENDAR_RULE]
    passing = [verdict for verdict in difficulty_verdicts if verdict["passes"]]
    return ScheduleSignalStudy(
        contract_version=SCHEDULE_SIGNAL_STUDY_CONTRACT_VERSION,
        config=settings,
        population=population,
        rules=results,
        comparisons=tuple(comparisons),
        decisions=tuple(decisions),
        verdict={
            "schedule_over_flat": schedule_verdict,
            "difficulty_over_calendar": difficulty_verdicts,
            "difficulty_carries_signal": bool(passing),
            "recommended_rule": (
                max(
                    passing,
                    key=lambda verdict: next(
                        comparison.error_improvement
                        for comparison in comparisons
                        if comparison.rule == verdict["rule"]
                    ),
                )["rule"]
                if passing
                else None
            ),
        },
        diagnostics={
            "seasons": list(settings.seasons),
            "evaluated_seasons": list(settings.evaluated_seasons),
            "window_length": settings.window_length,
            "origin_gameweeks": list(settings.origin_gameweeks),
            "locked_holdout_accessed": False,
            "transfer_check_note": (
                "The transfer check prices the two players swapped over the window; it does "
                "not re-pick the eleven or the captain week by week, so it measures the "
                "ordering the rule imposes rather than a full season of play."
            ),
        },
    )


def study_to_markdown(study: ScheduleSignalStudy) -> str:
    """The artifact a reader can check without running anything."""

    config = study.config
    lines = [
        "# Schedule signal: does a five-week window know more than a flat projection?",
        "",
        f"- Contract `{study.contract_version}`; fitted on {', '.join(config.seasons)}, judged "
        f"walk-forward on {', '.join(config.evaluated_seasons)}.",
        f"- Windows of {config.window_length} gameweeks opening at "
        f"{', '.join(str(value) for value in config.origin_gameweeks)}; a player enters a "
        f"window with at least {config.minimum_prior_minutes} minutes in the "
        f"{config.form_window} gameweeks before it.",
        f"- {config.bootstrap_resamples} paired bootstrap resamples, seed "
        f"{config.deterministic_seed}; the transfer check charges "
        f"{config.transfer_cost_points:.0f} points.",
        "- Measurement only. The locked 2025-26 holdout is refused by the configuration, no "
        "model or contract changed, and the verdict below was computed by `gate_verdict`.",
        "",
        "## Population",
        "",
        "| Season | Rows | Windows | Mean fixtures in window | Blank | Mean realized |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for season, values in study.population.items():
        lines.append(
            f"| {season} | {values['rows']:.0f} | {values['windows']:.0f} "
            f"| {values['mean_fixture_count']:.2f} | {values['blank_window_share']:.1%} "
            f"| {values['mean_realized_points']:.2f} |"
        )
    lines += [
        "",
        "## Rules",
        "",
        "| Rule | Rows | Mean absolute error | Rank correlation |",
        "| --- | ---: | ---: | ---: |",
    ]
    for result in study.rules:
        lines.append(
            f"| `{result.rule}` | {result.pooled_rows} "
            f"| {result.pooled_mean_absolute_error:.4f} "
            f"| {result.pooled_rank_correlation:.4f} |"
        )
    lines += [
        "",
        "## Comparisons",
        "",
        "| Rule | Against | Rows | Error improvement | 90% interval | Rank improvement |",
        "| --- | --- | ---: | ---: | --- | ---: |",
    ]
    for comparison in study.comparisons:
        low, high = comparison.error_interval
        lines.append(
            f"| `{comparison.rule}` | `{comparison.reference}` | {comparison.rows} "
            f"| {comparison.error_improvement:+.4f} | [{low:+.4f}, {high:+.4f}] "
            f"| {comparison.rank_improvement:+.4f} |"
        )
    lines += [
        "",
        "### Per season",
        "",
        "| Rule | Against | Season | Error | Ordering |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for comparison in study.comparisons:
        for season, value in comparison.per_season_error_improvement.items():
            rank = comparison.per_season_rank_improvement.get(season, 0.0)
            lines.append(
                f"| `{comparison.rule}` | `{comparison.reference}` | {season} "
                f"| {value:+.4f} | {rank:+.4f} |"
            )
    lines += [
        "",
        "## Decisions",
        "",
        "| Rule | Against | Season | Origin | Squad difference | Changed starters | Transfer net |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for decision in study.decisions:
        moved = decision.rule_proposes_transfer
        net = f"{decision.transfer_net_gain:+.2f}" if moved else "no move"
        lines.append(
            f"| `{decision.rule}` | `{decision.reference}` | {decision.season} "
            f"| {decision.origin_gameweek} | {decision.squad_difference:+.2f} "
            f"| {decision.changed_starters} | {net} |"
        )
    schedule = study.verdict["schedule_over_flat"]
    assert isinstance(schedule, dict)
    lines += [
        "",
        "## Verdict",
        "",
        "The gate: the paired interval clears zero, the sign holds in every judged season, "
        "the ordering does not get worse, and the decision check is not negative once a "
        "transfer is charged for.",
        "",
        f"- **Schedule over a flat projection** (`{schedule['rule']}` vs "
        f"`{schedule['reference']}`): {'passes' if schedule['passes'] else 'fails'} "
        f"(interval clears zero: {schedule['interval_excludes_zero']}; sign consistent: "
        f"{schedule['sign_consistent']}; ordering not worse: {schedule['ordering_not_worse']}; "
        f"decision: {schedule['decision_passes']}).",
    ]
    difficulty = study.verdict["difficulty_over_calendar"]
    assert isinstance(difficulty, list)
    for verdict in difficulty:
        lines.append(
            f"- **Difficulty over the calendar** (`{verdict['rule']}`): "
            f"{'passes' if verdict['passes'] else 'fails'} (interval clears zero: "
            f"{verdict['interval_excludes_zero']}; sign consistent: "
            f"{verdict['sign_consistent']}; ordering not worse: "
            f"{verdict['ordering_not_worse']}; decision: {verdict['decision_passes']}; "
            f"mean squad difference {verdict['mean_squad_difference']:+.3f}; mean transfer "
            f"net {verdict['mean_transfer_net_gain']:+.3f} over "
            f"{verdict['transfers_proposed']} proposed moves)."
        )
    recommended = study.verdict["recommended_rule"]
    lines += [
        "",
        (
            f"Recommended rule: `{recommended}`."
            if recommended
            else "No difficulty rule cleared the gate."
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "CALENDAR_RULE",
    "DIFFICULTY_RULES",
    "FLAT_RULE",
    "LOCKED_HOLDOUT_SEASON",
    "RULES",
    "SCHEDULE_SIGNAL_STUDY_CONTRACT_VERSION",
    "Comparison",
    "RuleResult",
    "RuleSeasonResult",
    "ScheduleSignalConfig",
    "ScheduleSignalStudy",
    "WindowDecision",
    "build_window_rows",
    "compare_decisions",
    "compare_rules",
    "evaluate_rules",
    "fit_rule",
    "gate_verdict",
    "predict_rule",
    "run_schedule_signal_study",
    "study_to_markdown",
]
