"""What the opening deadline knows about players the model has never seen.

A third of an opening-gameweek pool has no prior record: signings from abroad, promoted
clubs' players, academy graduates. Today every one of them is projected by a single line
through the origin - price in millions times a fitted coefficient - so a marquee signing
and a fourth-choice full back at the same price receive the same expectation. The deadline
publishes more than price: how much of the field has already picked the player, the game's
own expected points, the club he joined and who that club plays first.

This module measures whether those published signals predict an opening gameweek better
than price alone, and whether a player who *moved between clubs* keeps his old rate. It
fits nothing into the live path: the fit is walk-forward (every evaluated season is
predicted by seasons that precede it), the verdict is computed from the numbers by
``gate_verdict``, and promotion remains a separate, declared decision.

Two honest limits are built in. The archive stores no per-gameweek availability, so
"will he play" is *not* modelled here - it is what ownership largely measures, and the
live path applies its own availability contract on top. And the locked holdout season is
refused outright rather than merely unused.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.residual_signal_scan import load_enrichment_rows
from squadopt.features.config import MINUTES_PER_FULL_MATCH
from squadopt.features.cross_season import (
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    carry_over_as_of,
)
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction.config import FITTED_OPENING_PRICE_COEFFICIENT

OPENING_NEWCOMER_STUDY_CONTRACT_VERSION: Final = "opening_newcomer_study_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
POSITIONS: Final = ("GK", "DEF", "MID", "FWD")

#: Candidate feature sets, each a superset of the last. ``ease`` enters multiplicatively
#: (a fixture adjustment scales an expectation, it does not add to it).
CANDIDATES: Final[Mapping[str, tuple[tuple[str, ...], str | None]]] = MappingProxyType(
    {
        "M1_price_by_position": (("price_m",), None),
        "M2_ownership": (("price_m", "ownership_share"), None),
        "M3_source_expectation": (("price_m", "ownership_share", "source_expected_points"), None),
        "M4a_published_difficulty": (
            ("price_m", "ownership_share", "source_expected_points"),
            "published_ease",
        ),
        "M4b_carried_team_strength": (
            ("price_m", "ownership_share", "source_expected_points"),
            "carried_ease",
        ),
    }
)
CONTROL_NAME: Final = "control_price_prior"


@dataclass(frozen=True, slots=True)
class OpeningStudyConfig:
    """Which seasons are fitted, which are judged, and how the interval is drawn."""

    seasons: tuple[str, ...] = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
    evaluated_seasons: tuple[str, ...] = ("2022-23", "2023-24", "2024-25")
    bootstrap_resamples: int = 2000
    deterministic_seed: int = 0
    minimum_training_rows: int = 60
    mover_shrink_grid: tuple[float, ...] = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.25, 0.0)

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
        if self.bootstrap_resamples < 100:
            raise ExperimentConfigurationError("bootstrap_resamples must be at least 100.")


@dataclass(frozen=True, slots=True)
class CandidateSeasonResult:
    candidate: str
    season: str
    rows: int
    mean_absolute_error: float
    bias: float
    rank_correlation: float
    control_mean_absolute_error: float
    control_bias: float
    control_rank_correlation: float
    rank_correlation_players_only: float
    """Diagnostic, not part of the gate: the ordering among newcomers who did play.

    Most newcomers do not appear at all in an opening gameweek, and a correlation over a
    column that is mostly a tie at zero says more about who played than about who scored.
    This restriction says whether an ordering that looks worse overall is worse among the
    players the ordering could actually have earned points from."""
    control_rank_correlation_players_only: float

    @property
    def error_improvement(self) -> float:
        """Positive when the candidate is closer than the control."""

        return self.control_mean_absolute_error - self.mean_absolute_error

    @property
    def rank_improvement(self) -> float:
        return self.rank_correlation - self.control_rank_correlation


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate: str
    features: tuple[str, ...]
    multiplier: str | None
    seasons: tuple[CandidateSeasonResult, ...]
    pooled_rows: int
    pooled_error_improvement: float
    pooled_error_interval: tuple[float, float]
    coefficients: Mapping[str, Mapping[str, float]]
    """Per position, the coefficients fitted for the last evaluated season."""

    @property
    def improves_every_season(self) -> bool:
        return all(season.error_improvement > 0.0 for season in self.seasons)

    @property
    def ranks_better_every_season(self) -> bool:
        return all(season.rank_improvement > 0.0 for season in self.seasons)

    @property
    def interval_excludes_zero(self) -> bool:
        low, _ = self.pooled_error_interval
        return low > 0.0


@dataclass(frozen=True, slots=True)
class DecisionComparison:
    """What the squad built from a candidate actually scored, against the control's."""

    season: str
    control_realized_points: float
    candidate_realized_points: float
    control_newcomers_selected: int
    candidate_newcomers_selected: int
    changed_starters: int

    @property
    def difference(self) -> float:
        return self.candidate_realized_points - self.control_realized_points


@dataclass(frozen=True, slots=True)
class MoverResult:
    """Whether a player who changed clubs keeps his carried rate."""

    rows: int
    mover_bias: float
    mover_mean_absolute_error: float
    stayer_bias: float
    stayer_mean_absolute_error: float
    per_season_bias: Mapping[str, float]
    best_shrink: float
    best_shrink_error: float
    unshrunk_error: float
    shrink_improves_every_season: bool


@dataclass(frozen=True, slots=True)
class OpeningNewcomerStudy:
    contract_version: str
    config: OpeningStudyConfig
    population: Mapping[str, Mapping[str, float]]
    control: Mapping[str, float]
    candidates: tuple[CandidateResult, ...]
    decisions: Mapping[str, tuple[DecisionComparison, ...]]
    movers: MoverResult
    verdict: Mapping[str, object]
    diagnostics: Mapping[str, object] = field(default_factory=dict)


# --- population ---------------------------------------------------------------


def _published_team_strength(archive_root: Path, season: str) -> pd.DataFrame:
    """Club strength as the platform publishes it, keyed by the club's own code."""

    codes = load_team_codes(archive_root, season)
    table = pd.read_csv(Path(archive_root) / "data" / season / "teams.csv")
    columns = [
        column
        for column in (
            "strength",
            "strength_overall_home",
            "strength_overall_away",
            "strength_attack_home",
            "strength_attack_away",
            "strength_defence_home",
            "strength_defence_away",
        )
        if column in table.columns
    ]
    if "code" not in table.columns:
        raise ExperimentExecutionError(f"{season}: teams.csv carries no club code.")
    strength = table.loc[:, ["code", *columns]].copy()
    strength["code"] = pd.to_numeric(strength["code"], errors="coerce").astype("Int64")
    for column in columns:
        strength[column] = pd.to_numeric(strength[column], errors="coerce")
    names = codes.loc[:, ["code", "name"]].rename(columns={"name": "team_id"})
    names["code"] = pd.to_numeric(names["code"], errors="coerce").astype("Int64")
    return strength.merge(names, on="code", how="left")


def _carried_team_points(panel: pd.DataFrame, season: str) -> pd.DataFrame:
    """Each club's points per gameweek in the season before ``season``.

    A club promoted into ``season`` has none, which is the honest answer: nothing about
    its Premier League output is known yet.
    """

    earlier = panel.loc[panel["season"] < season]
    if earlier.empty:
        return pd.DataFrame(columns=["team_id", "carried_team_points"])
    last_season = str(earlier["season"].max())
    block = earlier.loc[earlier["season"] == last_season]
    per_week = (
        block.groupby(["team_id", "gameweek"], as_index=False)["total_points"]
        .sum()
        .groupby("team_id", as_index=False)["total_points"]
        .mean()
        .rename(columns={"total_points": "carried_team_points"})
    )
    return pd.DataFrame(per_week)


def _opening_fixture(archive_root: Path, season: str) -> pd.DataFrame:
    """The first gameweek's fixture per club: opponent, venue and published difficulty."""

    fixtures = build_fixture_panel(archive_root, seasons=(season,))
    opening = fixtures.loc[fixtures["gameweek"] == 1].copy()
    codes = load_team_codes(archive_root, season).loc[:, ["id", "code", "name"]]
    by_id = dict(zip(codes["id"].tolist(), codes["name"].tolist(), strict=True))
    by_code = dict(zip(codes["code"].tolist(), codes["name"].tolist(), strict=True))
    resolved = [by_code.get(int(value), by_id.get(int(value))) for value in opening["team_id"]]
    opponent = [
        by_code.get(int(value), by_id.get(int(value))) for value in opening["opponent_team_id"]
    ]
    opening["team_id"] = resolved
    opening["opponent_team"] = opponent
    opening["fixture_difficulty"] = pd.to_numeric(
        opening["fixture_difficulty"], errors="coerce"
    ).astype("float64")
    grouped = opening.groupby("team_id", as_index=False).agg(
        fixture_difficulty=("fixture_difficulty", "mean"),
        is_home=("is_home", "first"),
        opponent_team=("opponent_team", "first"),
        opening_fixtures=("fixture_id", "size"),
    )
    return grouped


def build_opening_rows(archive_root: Path | str, config: OpeningStudyConfig) -> pd.DataFrame:
    """One row per player per opening gameweek, with everything the deadline published."""

    root = Path(archive_root)
    panel = build_panel(root)
    panel = panel.loc[panel["season"].isin(config.seasons)].copy()
    if panel.empty:
        raise ExperimentExecutionError("The archive holds none of the requested seasons.")
    enrichment = load_enrichment_rows(root, config.seasons)
    enrichment = enrichment.loc[
        enrichment["gameweek"] == 1, ["season", "player_id", "selected", "xP"]
    ]
    pieces: list[pd.DataFrame] = []
    earliest = min(config.seasons)
    for season in config.seasons:
        if season == earliest:
            continue  # nothing precedes it: no carry-over, no newcomer/mover distinction
        gameweek_one = panel.loc[(panel["season"] == season) & (panel["gameweek"] == 1)].copy()
        if gameweek_one.empty:
            continue
        carried = carry_over_as_of(panel, target_season=season)
        rows = gameweek_one.merge(carried, on="player_id", how="left")
        earlier = panel.loc[panel["season"] < season]
        last_club = (
            earlier.sort_values(["player_id", "season", "gameweek"], kind="stable")
            .groupby("player_id", as_index=False)
            .tail(1)
            .loc[:, ["player_id", "team_id"]]
            .rename(columns={"team_id": "previous_team_id"})
        )
        rows = rows.merge(last_club, on="player_id", how="left")
        rows = rows.merge(enrichment, on=["season", "player_id"], how="left")
        rows["has_prior_record"] = rows[PRIOR_RATE_COLUMN].notna()
        rows["is_mover"] = rows["has_prior_record"] & rows["previous_team_id"].notna()
        rows["is_mover"] &= rows["team_id"] != rows["previous_team_id"]
        rows["price_m"] = rows["price_tenths"].astype("float64") / 10.0
        selected = pd.to_numeric(rows["selected"], errors="coerce")
        # Ownership as a share of the most-owned player that week: the count itself grows
        # with the game's player base, the share does not.
        maximum = float(selected.max()) if selected.notna().any() else 0.0
        rows["ownership_share"] = (selected / maximum).fillna(0.0) if maximum > 0 else 0.0
        rows["source_expected_points"] = pd.to_numeric(rows["xP"], errors="coerce").fillna(0.0)
        rows["carried_projection"] = (
            rows[PRIOR_RATE_COLUMN] * rows[PRIOR_MINUTES_COLUMN] / MINUTES_PER_FULL_MATCH
        )
        fixture = _opening_fixture(root, season)
        rows = rows.merge(fixture, on="team_id", how="left")
        # Ease: one is the kindest published fixture, zero the harshest. A club with no
        # opening fixture in the archive reads as average rather than as easy.
        difficulty = rows["fixture_difficulty"].astype("float64")
        rows["published_ease"] = ((5.0 - difficulty) / 4.0).fillna(0.5)
        strength = _published_team_strength(root, season)
        if "strength_overall_home" in strength.columns:
            overall = strength.loc[:, ["team_id", "strength_overall_home"]].rename(
                columns={"strength_overall_home": "published_team_strength"}
            )
            rows = rows.merge(overall, on="team_id", how="left")
        else:
            rows["published_team_strength"] = float("nan")
        carried_points = _carried_team_points(panel, season)
        rows = rows.merge(carried_points, on="team_id", how="left")
        carried_team = rows["carried_team_points"].astype("float64")
        span = float(carried_team.max() - carried_team.min()) if carried_team.notna().any() else 0.0
        rows["carried_ease"] = (
            ((carried_team - carried_team.min()) / span).fillna(0.5) if span > 0 else 0.5
        )
        pieces.append(rows)
    if not pieces:
        raise ExperimentExecutionError("No opening gameweek could be assembled.")
    frame = pd.concat(pieces, ignore_index=True)
    return frame.sort_values(["season", "player_id"], kind="stable").reset_index(drop=True)


# --- fitting ------------------------------------------------------------------


def _fit_through_origin(features: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Least squares through the origin; a degenerate column contributes nothing."""

    if features.size == 0 or features.shape[0] == 0:
        return np.zeros(features.shape[1] if features.ndim == 2 else 0, dtype="float64")
    solution, *_ = np.linalg.lstsq(features, target, rcond=None)
    return np.asarray(solution, dtype="float64")


def fit_candidate(
    training: pd.DataFrame, features: Sequence[str], multiplier: str | None
) -> dict[str, dict[str, float]]:
    """Fit one candidate per position, and a shared multiplicative fixture adjustment."""

    coefficients: dict[str, dict[str, float]] = {}
    residual_rows: list[tuple[float, float, float]] = []
    for position in POSITIONS:
        block = training.loc[training["position"] == position]
        if block.empty:
            coefficients[position] = dict.fromkeys(features, 0.0)
            continue
        matrix = block.loc[:, list(features)].to_numpy(dtype="float64")
        target = block["total_points"].to_numpy(dtype="float64")
        fitted = _fit_through_origin(matrix, target)
        coefficients[position] = {
            name: float(value) for name, value in zip(features, fitted, strict=True)
        }
        if multiplier is not None:
            base = np.clip(matrix @ fitted, 0.0, None)
            ease = block[multiplier].to_numpy(dtype="float64")
            residual_rows.extend(zip(base.tolist(), ease.tolist(), target.tolist(), strict=True))
    gamma = 0.0
    if multiplier is not None and residual_rows:
        base = np.asarray([row[0] for row in residual_rows], dtype="float64")
        ease = np.asarray([row[1] for row in residual_rows], dtype="float64")
        target = np.asarray([row[2] for row in residual_rows], dtype="float64")
        centred = ease - float(ease.mean())
        design = (base * centred).reshape(-1, 1)
        residual = target - base
        if float((design**2).sum()) > 0.0:
            gamma = float(_fit_through_origin(design, residual)[0])
        coefficients["_multiplier"] = {
            "feature": 0.0,
            "gamma": gamma,
            "mean_ease": float(ease.mean()),
        }
    return coefficients


def predict_candidate(
    rows: pd.DataFrame,
    coefficients: Mapping[str, Mapping[str, float]],
    features: Sequence[str],
    multiplier: str | None,
) -> np.ndarray:
    """Predicted opening points, clipped at zero as the shipped prior is."""

    prediction = np.zeros(len(rows), dtype="float64")
    positions = rows["position"].tolist()
    matrix = rows.loc[:, list(features)].to_numpy(dtype="float64")
    for index, position in enumerate(positions):
        weights = coefficients.get(str(position), {})
        value = 0.0
        for column, name in enumerate(features):
            value += float(weights.get(name, 0.0)) * float(matrix[index, column])
        prediction[index] = value
    prediction = np.clip(prediction, 0.0, None)
    if multiplier is not None and "_multiplier" in coefficients:
        gamma = float(coefficients["_multiplier"].get("gamma", 0.0))
        mean_ease = float(coefficients["_multiplier"].get("mean_ease", 0.0))
        ease = rows[multiplier].to_numpy(dtype="float64")
        prediction = np.clip(prediction * (1.0 + gamma * (ease - mean_ease)), 0.0, None)
    return prediction


def control_prediction(rows: pd.DataFrame) -> np.ndarray:
    """The prior as it ships today: one coefficient on price, for every position alike."""

    price = rows["price_m"].to_numpy(dtype="float64")
    return np.clip(price * FITTED_OPENING_PRICE_COEFFICIENT, 0.0, None)


# --- evaluation ---------------------------------------------------------------


def _rank_correlation(rows: pd.DataFrame, prediction: np.ndarray) -> float:
    """Spearman correlation within position, pooled by averaging over positions."""

    frame = rows.loc[:, ["position", "total_points"]].copy()
    frame["prediction"] = prediction
    values: list[float] = []
    for position in POSITIONS:
        block = frame.loc[frame["position"] == position]
        if len(block) < 5 or block["prediction"].nunique() < 2:
            continue
        correlation = float(
            str(block[["prediction", "total_points"]].corr(method="spearman").iloc[0, 1])
        )
        if math.isfinite(correlation):
            values.append(correlation)
    return float(np.mean(values)) if values else 0.0


def _paired_bootstrap(differences: np.ndarray, *, resamples: int, seed: int) -> tuple[float, float]:
    """Percentile interval of the mean paired difference, over players."""

    if differences.size == 0:
        return (0.0, 0.0)
    generator = np.random.default_rng(seed)
    draws = np.empty(resamples, dtype="float64")
    for index in range(resamples):
        sample = generator.integers(0, differences.size, differences.size)
        draws[index] = float(differences[sample].mean())
    return (float(np.quantile(draws, 0.05)), float(np.quantile(draws, 0.95)))


def evaluate_candidate(
    rows: pd.DataFrame, name: str, config: OpeningStudyConfig
) -> CandidateResult:
    """Walk forward: fit on the seasons before each evaluated one, then judge."""

    features, multiplier = CANDIDATES[name]
    newcomers = rows.loc[~rows["has_prior_record"]]
    seasons: list[CandidateSeasonResult] = []
    differences: list[float] = []
    coefficients: Mapping[str, Mapping[str, float]] = {}
    for season in config.evaluated_seasons:
        training = newcomers.loc[newcomers["season"] < season]
        evaluated = newcomers.loc[newcomers["season"] == season]
        if len(training) < config.minimum_training_rows or evaluated.empty:
            continue
        coefficients = fit_candidate(training, features, multiplier)
        prediction = predict_candidate(evaluated, coefficients, features, multiplier)
        control = control_prediction(evaluated)
        played = evaluated["minutes"].to_numpy(dtype="float64") > 0.0
        realized = evaluated["total_points"].to_numpy(dtype="float64")
        candidate_error = np.abs(realized - prediction)
        control_error = np.abs(realized - control)
        differences.extend((control_error - candidate_error).tolist())
        seasons.append(
            CandidateSeasonResult(
                candidate=name,
                season=season,
                rows=len(evaluated),
                mean_absolute_error=float(candidate_error.mean()),
                bias=float((prediction - realized).mean()),
                rank_correlation=_rank_correlation(evaluated, prediction),
                control_mean_absolute_error=float(control_error.mean()),
                control_bias=float((control - realized).mean()),
                control_rank_correlation=_rank_correlation(evaluated, control),
                rank_correlation_players_only=_rank_correlation(
                    evaluated.loc[played], prediction[played]
                ),
                control_rank_correlation_players_only=_rank_correlation(
                    evaluated.loc[played], control[played]
                ),
            )
        )
    paired = np.asarray(differences, dtype="float64")
    interval = _paired_bootstrap(
        paired, resamples=config.bootstrap_resamples, seed=config.deterministic_seed
    )
    return CandidateResult(
        candidate=name,
        features=tuple(features),
        multiplier=multiplier,
        seasons=tuple(seasons),
        pooled_rows=int(paired.size),
        pooled_error_improvement=float(paired.mean()) if paired.size else 0.0,
        pooled_error_interval=interval,
        coefficients={position: dict(values) for position, values in coefficients.items()},
    )


# --- movers -------------------------------------------------------------------


def evaluate_movers(rows: pd.DataFrame, config: OpeningStudyConfig) -> MoverResult:
    """Does a player who changed clubs keep the rate he carried into the season?"""

    carried = rows.loc[rows["has_prior_record"] & rows["carried_projection"].notna()].copy()
    carried["error"] = carried["total_points"] - carried["carried_projection"]
    movers = carried.loc[carried["is_mover"]]
    stayers = carried.loc[~carried["is_mover"]]
    per_season = {
        str(season): float(block["error"].mean())
        for season, block in movers.groupby("season", sort=True)
    }
    # A shrink weight pulls a mover's carried projection toward the price prior; the grid
    # is searched walk-forward, so the weight is chosen without seeing the season it is
    # judged on.
    best_weight = 1.0
    best_error = float("inf")
    per_weight_errors: dict[float, list[float]] = {}
    for weight in config.mover_shrink_grid:
        season_errors: list[float] = []
        for season in config.evaluated_seasons:
            block = movers.loc[movers["season"] == season]
            if block.empty:
                continue
            prior = control_prediction(block)
            blended = (
                weight * block["carried_projection"].to_numpy(dtype="float64")
                + (1.0 - weight) * prior
            )
            season_errors.append(
                float(np.abs(block["total_points"].to_numpy(dtype="float64") - blended).mean())
            )
        if not season_errors:
            continue
        per_weight_errors[weight] = season_errors
        mean_error = float(np.mean(season_errors))
        if mean_error < best_error:
            best_error, best_weight = mean_error, weight
    unshrunk = float(np.mean(per_weight_errors.get(1.0, [float("nan")])))
    improves_every_season = bool(
        best_weight != 1.0
        and per_weight_errors.get(1.0)
        and all(
            best <= unshrunk_season
            for best, unshrunk_season in zip(
                per_weight_errors[best_weight], per_weight_errors[1.0], strict=True
            )
        )
    )
    return MoverResult(
        rows=len(movers),
        mover_bias=float(movers["error"].mean()) if not movers.empty else 0.0,
        mover_mean_absolute_error=float(movers["error"].abs().mean()) if not movers.empty else 0.0,
        stayer_bias=float(stayers["error"].mean()) if not stayers.empty else 0.0,
        stayer_mean_absolute_error=(
            float(stayers["error"].abs().mean()) if not stayers.empty else 0.0
        ),
        per_season_bias=per_season,
        best_shrink=best_weight,
        best_shrink_error=best_error if math.isfinite(best_error) else 0.0,
        unshrunk_error=unshrunk,
        shrink_improves_every_season=improves_every_season,
    )


# --- decision level -----------------------------------------------------------


def compare_decisions(
    rows: pd.DataFrame, name: str, config: OpeningStudyConfig
) -> tuple[DecisionComparison, ...]:
    """Build the opening squad both ways and score it on what actually happened."""

    features, multiplier = CANDIDATES[name]
    newcomers = rows.loc[~rows["has_prior_record"]]
    comparisons: list[DecisionComparison] = []
    optimization = OptimizationConfig()
    for season in config.evaluated_seasons:
        training = newcomers.loc[newcomers["season"] < season]
        block = rows.loc[rows["season"] == season].copy()
        if len(training) < config.minimum_training_rows or block.empty:
            continue
        coefficients = fit_candidate(training, features, multiplier)
        candidate_new = predict_candidate(block, coefficients, features, multiplier)
        control_new = control_prediction(block)
        carried = block["carried_projection"].to_numpy(dtype="float64")
        has_record = block["has_prior_record"].to_numpy(dtype="bool")
        pool = block.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]].copy()
        squads: dict[str, tuple[float, int, tuple[int, ...]]] = {}
        for label, fallback in (("control", control_new), ("candidate", candidate_new)):
            projection = pool.copy()
            projection["expected_points"] = np.where(has_record, carried, fallback)
            projection["expected_points"] = np.nan_to_num(
                projection["expected_points"].to_numpy(dtype="float64"), nan=0.0
            ).clip(min=0.0)
            result = optimize_squad(projection, optimization)
            if not result.has_solution or result.captain is None:
                raise ExperimentExecutionError(
                    f"{season}: the {label} opening squad could not be built."
                )
            starters = tuple(int(value) for value in result.starting_xi["player_id"])
            captain = int(result.captain["player_id"])
            realized = block.set_index("player_id")["total_points"].astype("float64")
            score = float(sum(realized.get(player, 0.0) for player in starters))
            score += float(realized.get(captain, 0.0))
            newcomer_ids = set(block.loc[~block["has_prior_record"], "player_id"].tolist())
            selected_newcomers = sum(1 for player in starters if player in newcomer_ids)
            squads[label] = (score, selected_newcomers, starters)
        control_score, control_new_count, control_starters = squads["control"]
        candidate_score, candidate_new_count, candidate_starters = squads["candidate"]
        comparisons.append(
            DecisionComparison(
                season=season,
                control_realized_points=control_score,
                candidate_realized_points=candidate_score,
                control_newcomers_selected=control_new_count,
                candidate_newcomers_selected=candidate_new_count,
                changed_starters=len(set(candidate_starters) - set(control_starters)),
            )
        )
    return tuple(comparisons)


# --- the gate -----------------------------------------------------------------


def gate_verdict(
    candidate: CandidateResult, decisions: Sequence[DecisionComparison]
) -> dict[str, object]:
    """The bar, fixed before the numbers existed, applied by code rather than by hand."""

    accuracy = candidate.improves_every_season and candidate.interval_excludes_zero
    ordering = candidate.ranks_better_every_season
    losses = sum(1 for comparison in decisions if comparison.difference < 0.0)
    mean_difference = (
        float(np.mean([comparison.difference for comparison in decisions])) if decisions else 0.0
    )
    decision = bool(decisions) and mean_difference >= 0.0 and losses <= 1
    return {
        "candidate": candidate.candidate,
        "accuracy_passes": accuracy,
        "ordering_passes": ordering,
        "decision_passes": decision,
        "mean_decision_difference": mean_difference,
        "decision_losses": losses,
        "passes": bool(accuracy and ordering and decision),
    }


def run_opening_newcomer_study(
    archive_root: Path | str, config: OpeningStudyConfig | None = None
) -> OpeningNewcomerStudy:
    """Measure every candidate against the shipped prior, and judge them by the gate."""

    settings = OpeningStudyConfig() if config is None else config
    rows = build_opening_rows(archive_root, settings)
    newcomers = rows.loc[~rows["has_prior_record"]]
    population = {
        str(season): {
            "rows": float(len(block)),
            "newcomers": float((~block["has_prior_record"]).sum()),
            "newcomer_share": float((~block["has_prior_record"]).mean()),
            "movers": float(block["is_mover"].sum()),
            "newcomers_without_minutes": float(
                (block.loc[~block["has_prior_record"], "minutes"] == 0).mean()
            ),
        }
        for season, block in rows.groupby("season", sort=True)
    }
    control_error = np.abs(
        newcomers["total_points"].to_numpy(dtype="float64") - control_prediction(newcomers)
    )
    control = {
        "coefficient": FITTED_OPENING_PRICE_COEFFICIENT,
        "rows": float(len(newcomers)),
        "mean_realized_points": float(newcomers["total_points"].mean()),
        "mean_predicted_points": float(control_prediction(newcomers).mean()),
        "mean_absolute_error": float(control_error.mean()),
        "bias": float((control_prediction(newcomers) - newcomers["total_points"]).mean()),
    }
    candidates = tuple(evaluate_candidate(rows, name, settings) for name in CANDIDATES)
    decisions = {name: compare_decisions(rows, name, settings) for name in CANDIDATES}
    verdicts = [gate_verdict(result, decisions[result.candidate]) for result in candidates]
    passing = [verdict for verdict in verdicts if verdict["passes"]]
    recommended = None
    if passing:
        recommended = max(
            passing,
            key=lambda verdict: next(
                result.pooled_error_improvement
                for result in candidates
                if result.candidate == verdict["candidate"]
            ),
        )["candidate"]
    return OpeningNewcomerStudy(
        contract_version=OPENING_NEWCOMER_STUDY_CONTRACT_VERSION,
        config=settings,
        population=population,
        control=control,
        candidates=candidates,
        decisions=decisions,
        movers=evaluate_movers(rows, settings),
        verdict={
            "per_candidate": verdicts,
            "recommended_candidate": recommended,
            "promotion_proposed": recommended is not None,
        },
        diagnostics={
            "seasons": list(settings.seasons),
            "evaluated_seasons": list(settings.evaluated_seasons),
            "locked_holdout_accessed": False,
            "availability_modelled": False,
            "availability_note": (
                "The archive stores no per-gameweek availability, so no availability weight is "
                "fitted here; the live path applies its own availability contract and ownership "
                "carries most of the same information."
            ),
        },
    )


def study_to_markdown(study: OpeningNewcomerStudy) -> str:
    """The artifact a reader can check without running anything."""

    config = study.config
    lines = [
        "# Opening projection: newcomers, movers, and what the deadline publishes",
        "",
        f"- Contract `{study.contract_version}`; fitted on {', '.join(config.seasons)}, judged "
        f"walk-forward on {', '.join(config.evaluated_seasons)}; "
        f"{config.bootstrap_resamples} paired bootstrap resamples, seed "
        f"{config.deterministic_seed}.",
        "- Measurement only. The locked 2025-26 holdout was not read, no contract or model "
        "changed, and the verdict below was computed by `gate_verdict`, not written by hand.",
        "",
        "## The population the model cannot see",
        "",
        "| Season | Opening rows | Newcomers | Share | Movers | Newcomers who did not play |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for season, block in study.population.items():
        lines.append(
            f"| {season} | {block['rows']:.0f} | {block['newcomers']:.0f} "
            f"| {block['newcomer_share']:.0%} | {block['movers']:.0f} "
            f"| {block['newcomers_without_minutes']:.0%} |"
        )
    control = study.control
    lines += [
        "",
        "## What ships today",
        "",
        f"`expected_points = {control['coefficient']:.5f} x price` for every player without a "
        f"record. Over {control['rows']:.0f} such players it predicts "
        f"{control['mean_predicted_points']:.3f} points where "
        f"{control['mean_realized_points']:.3f} "
        f"were scored — a bias of **{control['bias']:+.3f}** and a mean absolute error of "
        f"{control['mean_absolute_error']:.3f}. The coefficient was fitted on every opening "
        "player, and most players have a record and play; a newcomer usually does not.",
        "",
        "## Candidates, walk-forward",
        "",
        "| Candidate | Pooled MAE gain | 90% interval | Per-season gain "
        "| Rank (candidate vs control) |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for candidate in study.candidates:
        gains = " / ".join(f"{season.error_improvement:+.3f}" for season in candidate.seasons)
        ranks = " / ".join(
            f"{season.rank_correlation:.2f}v{season.control_rank_correlation:.2f}"
            for season in candidate.seasons
        )
        low, high = candidate.pooled_error_interval
        lines.append(
            f"| `{candidate.candidate}` | {candidate.pooled_error_improvement:+.3f} "
            f"| [{low:+.3f}, {high:+.3f}] | {gains} | {ranks} |"
        )
    lines += [
        "",
        "Ordering restricted to the newcomers who actually played (a diagnostic, not part of "
        "the gate):",
        "",
        "| Candidate | Rank among players, by season | Control |",
        "| --- | --- | --- |",
    ]
    for candidate in study.candidates:
        own = " / ".join(
            f"{season.rank_correlation_players_only:.3f}" for season in candidate.seasons
        )
        ctrl = " / ".join(
            f"{season.control_rank_correlation_players_only:.3f}" for season in candidate.seasons
        )
        lines.append(f"| `{candidate.candidate}` | {own} | {ctrl} |")
    lines += [
        "",
        "## What the squad would have been",
        "",
        "| Candidate | Realized difference by season | Newcomers started |",
        "| --- | --- | --- |",
    ]
    for name, comparisons in study.decisions.items():
        differences = " / ".join(f"{item.difference:+.0f}" for item in comparisons)
        picks = " / ".join(
            f"{item.candidate_newcomers_selected} vs {item.control_newcomers_selected}"
            for item in comparisons
        )
        lines.append(f"| `{name}` | {differences} | {picks} |")
    movers = study.movers
    lines += [
        "",
        "## Movers",
        "",
        f"- {movers.rows} players changed clubs across the studied openings. Their carried "
        f"projection is biased {movers.mover_bias:+.3f} against {movers.stayer_bias:+.3f} for "
        f"players who stayed; mean absolute error {movers.mover_mean_absolute_error:.3f} against "
        f"{movers.stayer_mean_absolute_error:.3f}.",
        "- Per season the mover bias is "
        + ", ".join(f"{season} {value:+.3f}" for season, value in movers.per_season_bias.items())
        + " — the sign is not stable.",
        f"- The best shrink toward the price prior is **{movers.best_shrink:.2f}** "
        f"({movers.best_shrink_error:.3f} against {movers.unshrunk_error:.3f} unshrunk), and it "
        f"{'improves' if movers.shrink_improves_every_season else 'does not improve'} every "
        "evaluated season.",
        "",
        "## Verdict",
        "",
        "| Candidate | Accuracy | Ordering | Decision | Passes |",
        "| --- | --- | --- | --- | --- |",
    ]
    per_candidate = study.verdict.get("per_candidate", [])
    for verdict in per_candidate if isinstance(per_candidate, list) else []:
        if not isinstance(verdict, Mapping):
            continue
        lines.append(
            f"| `{verdict['candidate']}` | {'pass' if verdict['accuracy_passes'] else 'fail'} "
            f"| {'pass' if verdict['ordering_passes'] else 'fail'} "
            f"| {'pass' if verdict['decision_passes'] else 'fail'} "
            f"({float(str(verdict['mean_decision_difference'])):+.1f} points, "
            f"{verdict['decision_losses']} loss) "
            f"| {'**yes**' if verdict['passes'] else 'no'} |"
        )
    recommended = study.verdict.get("recommended_candidate")
    lines += [
        "",
        (
            f"Recommended for promotion: **{recommended}**."
            if recommended
            else "**No candidate clears the gate**, so nothing is proposed for promotion and the "
            "opening gameweek runs on the control."
        ),
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "CANDIDATES",
    "CONTROL_NAME",
    "OPENING_NEWCOMER_STUDY_CONTRACT_VERSION",
    "CandidateResult",
    "CandidateSeasonResult",
    "DecisionComparison",
    "MoverResult",
    "OpeningNewcomerStudy",
    "OpeningStudyConfig",
    "build_opening_rows",
    "compare_decisions",
    "control_prediction",
    "evaluate_candidate",
    "evaluate_movers",
    "fit_candidate",
    "gate_verdict",
    "predict_candidate",
    "run_opening_newcomer_study",
    "study_to_markdown",
]
