"""A team rating estimated from goals, and whether it beats the rating the platform ships.

The schedule signal study found that scaling a projection by the platform's published
difficulty rating improves error slightly and loses points at the decision level. That
rating is an opaque integer from one to five, fixed for a season and never explained. This
module builds the alternative on its own terms — a Dixon-Coles attack and defence rating
fitted to goals actually scored — and judges it on what a rating is *for* before anything
is allowed to consume it:

1. **Goals.** Out-of-sample log-likelihood of the scorelines it did not see, against a
   constant-rate baseline that knows only the league's home and away averages.
2. **Clean sheets.** The Brier score of the clean-sheet probabilities it implies, against a
   logistic fitted on the published difficulty rating — the defensive half of a fantasy
   squad is paid in clean sheets, so this is the calibration that matters most.
3. **Players.** Whether the rating orders player outcomes at least as well as the published
   one does: an opponent's defence against attackers' points, an implied clean-sheet
   probability against goalkeepers' and defenders' points.

The model is the standard one. Home goals are Poisson with rate ``exp(home + attack_home -
defence_away)``, away goals with ``exp(attack_away - defence_home)``, and the Dixon-Coles
tau correction lifts the dependence between the four low scorelines that an independent
Poisson pair gets wrong. Matches are weighted by an exponential decay in days, which is
also what carries a club's rating across a season boundary — a club starts a season where
last season left it, pulled toward the league mean by the weight its old matches have lost.

A promoted club has no top-flight matches at all, so it cannot be fitted. It is given the
average rating that promoted clubs earned in earlier seasons, each of those seasons fitted
on its own matches so a club promoted three years ago does not contribute its later,
established form. That prior is the mean the club's ridge penalty pulls toward, so it also
governs how a promoted club is rated three matches into a season. It is measured, not
assumed.

Fitting is refit at every judged gameweek on matches that kicked off before it, which is
the only timing that makes the evaluation honest. The locked holdout season is refused.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError

TEAM_RATING_STUDY_CONTRACT_VERSION: Final = "team_rating_study_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
ATTACKING_POSITIONS: Final = ("MID", "FWD")
DEFENSIVE_POSITIONS: Final = ("GK", "DEF")
#: Scorelines beyond this are negligible and truncating them keeps the joint distribution
#: a fixed-size matrix rather than an open sum.
MAXIMUM_GOALS: Final = 10


@dataclass(frozen=True, slots=True)
class DixonColesConfig:
    """How the rating is fitted: how fast the past fades, and how hard it is shrunk."""

    half_life_days: float = 180.0
    ridge: float = 2.0
    """Penalty pulling every club's parameters toward its prior mean.

    It does two jobs. It makes the fit identifiable without a hard sum-to-zero constraint,
    and it keeps a club with three matches played from being rated on three matches."""
    rho_grid: tuple[float, ...] = tuple(float(value) for value in np.linspace(-0.25, 0.15, 41))
    maximum_iterations: int = 400

    def __post_init__(self) -> None:
        if self.half_life_days <= 0.0:
            raise ExperimentConfigurationError("half_life_days must be positive.")
        if self.ridge < 0.0:
            raise ExperimentConfigurationError("ridge must not be negative.")
        if not self.rho_grid:
            raise ExperimentConfigurationError("rho_grid must hold at least one value.")

    @property
    def decay_per_day(self) -> float:
        return math.log(2.0) / self.half_life_days


@dataclass(frozen=True, slots=True)
class TeamRating:
    """One fitted rating: what each club does to goals, and when it was fitted."""

    as_of: pd.Timestamp
    attack: Mapping[int, float]
    defence: Mapping[int, float]
    home_advantage: float
    rho: float
    matches_used: int
    promoted_attack_prior: float
    promoted_defence_prior: float

    def attack_of(self, club: int) -> float:
        """A club's attacking rating, falling back to the promoted prior when unseen."""

        return float(self.attack.get(int(club), self.promoted_attack_prior))

    def defence_of(self, club: int) -> float:
        """A club's defensive rating; higher keeps more out."""

        return float(self.defence.get(int(club), self.promoted_defence_prior))

    def expected_goals(self, home_club: int, away_club: int) -> tuple[float, float]:
        """The two Poisson rates for one fixture, home side first."""

        home = math.exp(
            self.home_advantage + self.attack_of(home_club) - self.defence_of(away_club)
        )
        away = math.exp(self.attack_of(away_club) - self.defence_of(home_club))
        return home, away

    def score_matrix(self, home_club: int, away_club: int) -> np.ndarray:
        """The joint distribution over scorelines, with the Dixon-Coles correction applied."""

        home_rate, away_rate = self.expected_goals(home_club, away_club)
        goals = np.arange(MAXIMUM_GOALS + 1)
        home_marginal = _poisson_pmf(goals, home_rate)
        away_marginal = _poisson_pmf(goals, away_rate)
        matrix = np.outer(home_marginal, away_marginal)
        matrix[0, 0] *= 1.0 - home_rate * away_rate * self.rho
        matrix[0, 1] *= 1.0 + home_rate * self.rho
        matrix[1, 0] *= 1.0 + away_rate * self.rho
        matrix[1, 1] *= 1.0 - self.rho
        total = float(matrix.sum())
        if total <= 0.0:
            raise ExperimentExecutionError("The scoreline distribution has no mass.")
        return matrix / total

    def clean_sheet_probability(self, club: int, opponent: int, *, is_home: bool) -> float:
        """The chance ``club`` concedes nothing, under the fitted joint distribution."""

        home_club, away_club = (club, opponent) if is_home else (opponent, club)
        matrix = self.score_matrix(home_club, away_club)
        # A clean sheet for the home side means the away column is zero, and the reverse.
        return float(matrix[:, 0].sum()) if is_home else float(matrix[0, :].sum())


def _poisson_pmf(goals: np.ndarray, rate: float) -> np.ndarray:
    logs = (
        goals * math.log(max(rate, 1e-12))
        - rate
        - np.array([math.lgamma(int(value) + 1) for value in goals])
    )
    return np.asarray(np.exp(logs), dtype="float64")


# --- matches ------------------------------------------------------------------


def load_match_results(archive_root: Path | str, seasons: Sequence[str]) -> pd.DataFrame:
    """Every completed fixture with its scoreline, keyed by persistent club codes.

    The fixture panel the rest of the repository uses deliberately carries no goals — it
    describes who plays whom and when. Goals live only in the archive's own fixture file, so
    they are read here, in the study that needs them, rather than widened into a contract
    nothing else consumes.
    """

    root = Path(archive_root)
    if LOCKED_HOLDOUT_SEASON in set(seasons):
        raise ExperimentConfigurationError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be read."
        )
    pieces: list[pd.DataFrame] = []
    for season in seasons:
        path = root / "data" / season / "fixtures.csv"
        if not path.is_file():
            raise ExperimentExecutionError(f"{season}: no fixtures file at {path}.")
        table = pd.read_csv(path)
        required = ("event", "team_h", "team_a", "team_h_score", "team_a_score", "kickoff_time")
        missing = [column for column in required if column not in table.columns]
        if missing:
            raise ExperimentExecutionError(f"{season}: fixtures.csv lacks {missing!r}.")
        codes = load_team_codes(root, season).set_index("id")["code"]
        block = table.loc[
            table["event"].notna() & table["team_h_score"].notna() & table["team_a_score"].notna()
        ].copy()
        if block.empty:
            raise ExperimentExecutionError(f"{season}: no completed fixture carries a score.")
        block["season"] = season
        block["gameweek"] = block["event"].astype("int64")
        block["home_club"] = [int(codes.loc[int(value)]) for value in block["team_h"]]
        block["away_club"] = [int(codes.loc[int(value)]) for value in block["team_a"]]
        block["home_goals"] = block["team_h_score"].astype("int64")
        block["away_goals"] = block["team_a_score"].astype("int64")
        block["kickoff"] = pd.to_datetime(block["kickoff_time"], utc=True, format="mixed")
        for column, name in (
            ("team_h_difficulty", "home_difficulty"),
            ("team_a_difficulty", "away_difficulty"),
        ):
            # Some archive seasons omit the published rating entirely; a column of missing
            # values says that plainly and the comparison against it is skipped downstream.
            if column in block.columns:
                block[name] = pd.to_numeric(block[column], errors="coerce").astype("float64")
            else:
                block[name] = float("nan")
        pieces.append(
            block.loc[
                :,
                [
                    "season",
                    "gameweek",
                    "kickoff",
                    "home_club",
                    "away_club",
                    "home_goals",
                    "away_goals",
                    "home_difficulty",
                    "away_difficulty",
                ],
            ]
        )
    frame = pd.concat(pieces, ignore_index=True)
    return frame.sort_values(["kickoff", "home_club"], kind="stable").reset_index(drop=True)


def promoted_clubs(matches: pd.DataFrame) -> Mapping[str, tuple[int, ...]]:
    """Per season, the clubs that did not play in the season before it.

    The first season in the frame has no season before it, so every club in it would look
    promoted; it is excluded rather than mislabelled.
    """

    seasons = sorted({str(value) for value in matches["season"]})
    by_season = {
        season: set(
            int(value)
            for value in pd.concat(
                [
                    matches.loc[matches["season"] == season, "home_club"],
                    matches.loc[matches["season"] == season, "away_club"],
                ]
            )
        )
        for season in seasons
    }
    promoted: dict[str, tuple[int, ...]] = {}
    for index, season in enumerate(seasons):
        if index == 0:
            continue
        previous = by_season[seasons[index - 1]]
        promoted[season] = tuple(sorted(by_season[season] - previous))
    return promoted


# --- fitting ------------------------------------------------------------------


def _observations(matches: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split each match into the two scoring observations a log-linear fit needs."""

    scorer = np.concatenate(
        [matches["home_club"].to_numpy(dtype="int64"), matches["away_club"].to_numpy(dtype="int64")]
    )
    conceder = np.concatenate(
        [matches["away_club"].to_numpy(dtype="int64"), matches["home_club"].to_numpy(dtype="int64")]
    )
    goals = np.concatenate(
        [
            matches["home_goals"].to_numpy(dtype="float64"),
            matches["away_goals"].to_numpy(dtype="float64"),
        ]
    )
    at_home = np.concatenate([np.ones(len(matches)), np.zeros(len(matches))])
    return scorer, conceder, goals, at_home


def measure_promoted_prior(
    matches: pd.DataFrame,
    seasons: Sequence[str],
    config: DixonColesConfig | None = None,
) -> tuple[float, float]:
    """What a newly promoted club's rating looks like, measured on seasons already played.

    A club arriving from the second tier has no top-flight matches, so nothing can be fitted
    for it. The honest substitute is not zero — the league average — but what promoted clubs
    have actually looked like. Each named season is fitted on its own matches so a club
    promoted three seasons ago does not contribute its later, established form, and the
    promoted clubs' parameters are averaged over the seasons given.
    """

    settings = DixonColesConfig() if config is None else config
    promoted = promoted_clubs(matches)
    attacks: list[float] = []
    defences: list[float] = []
    for season in seasons:
        arrivals = promoted.get(str(season), ())
        block = matches.loc[matches["season"] == season]
        if not arrivals or block.empty:
            continue
        end = pd.Timestamp(block["kickoff"].max()) + pd.Timedelta(days=1)
        rating = fit_dixon_coles(block, as_of=end, config=settings)
        attacks.extend(rating.attack[club] for club in arrivals if club in rating.attack)
        defences.extend(rating.defence[club] for club in arrivals if club in rating.defence)
    if not attacks or not defences:
        return (0.0, 0.0)
    return (float(np.mean(attacks)), float(np.mean(defences)))


def fit_dixon_coles(
    matches: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    config: DixonColesConfig | None = None,
    promoted_prior: tuple[float, float] = (0.0, 0.0),
    newly_promoted: Sequence[int] = (),
) -> TeamRating:
    """Fit attack, defence, home advantage and the low-score correction on past matches only.

    ``newly_promoted`` names the clubs whose ridge penalty pulls toward the promoted prior
    rather than toward the league average. A club three matches into its first top-flight
    season is shrunk toward what promoted clubs look like, which is the honest place to
    start; every other club is shrunk toward the middle.
    """

    settings = DixonColesConfig() if config is None else config
    history = matches.loc[matches["kickoff"] < as_of]
    if history.empty:
        raise ExperimentExecutionError(f"No match kicked off before {as_of!s}.")
    clubs = sorted(
        {int(value) for value in history["home_club"]}
        | {int(value) for value in history["away_club"]}
    )
    index = {club: position for position, club in enumerate(clubs)}
    count = len(clubs)
    scorer, conceder, goals, at_home = _observations(history)
    scorer_index = np.array([index[int(value)] for value in scorer], dtype="int64")
    conceder_index = np.array([index[int(value)] for value in conceder], dtype="int64")
    age_days = (
        as_of - pd.concat([history["kickoff"], history["kickoff"]], ignore_index=True)
    ).dt.total_seconds().to_numpy(dtype="float64") / 86400.0
    weights = np.exp(-settings.decay_per_day * np.clip(age_days, 0.0, None))
    prior_attack = np.zeros(count, dtype="float64")
    prior_defence = np.zeros(count, dtype="float64")
    for club in newly_promoted:
        position = index.get(int(club))
        if position is not None:
            prior_attack[position] = promoted_prior[0]
            prior_defence[position] = promoted_prior[1]

    def negative_log_likelihood(theta: np.ndarray) -> tuple[float, np.ndarray]:
        attack = theta[:count]
        defence = theta[count : 2 * count]
        home = float(theta[-1])
        eta = attack[scorer_index] - defence[conceder_index] + home * at_home
        rate = np.exp(np.clip(eta, -20.0, 20.0))
        value = float(np.sum(weights * (rate - goals * eta)))
        attack_gap = attack - prior_attack
        defence_gap = defence - prior_defence
        value += settings.ridge * float(np.sum(attack_gap**2) + np.sum(defence_gap**2))
        residual = weights * (rate - goals)
        gradient = np.zeros_like(theta)
        gradient[:count] = np.bincount(scorer_index, weights=residual, minlength=count)
        gradient[count : 2 * count] = -np.bincount(
            conceder_index, weights=residual, minlength=count
        )
        gradient[:count] += 2.0 * settings.ridge * attack_gap
        gradient[count : 2 * count] += 2.0 * settings.ridge * defence_gap
        gradient[-1] = float(np.sum(residual * at_home))
        return value, gradient

    start = np.zeros(2 * count + 1, dtype="float64")
    start[-1] = 0.25
    solution = minimize(
        negative_log_likelihood,
        start,
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": settings.maximum_iterations},
    )
    theta = np.asarray(solution.x, dtype="float64")
    attack = {club: float(theta[index[club]]) for club in clubs}
    defence = {club: float(theta[count + index[club]]) for club in clubs}
    home_advantage = float(theta[-1])
    rho = _fit_rho(history, attack, defence, home_advantage, weights[: len(history)], settings)
    return TeamRating(
        as_of=as_of,
        attack=attack,
        defence=defence,
        home_advantage=home_advantage,
        rho=rho,
        matches_used=len(history),
        promoted_attack_prior=float(promoted_prior[0]),
        promoted_defence_prior=float(promoted_prior[1]),
    )


def _fit_rho(
    history: pd.DataFrame,
    attack: Mapping[int, float],
    defence: Mapping[int, float],
    home_advantage: float,
    weights: np.ndarray,
    config: DixonColesConfig,
) -> float:
    """Choose the low-score correction by weighted likelihood, holding the rates fixed.

    Separating this from the main fit costs a little statistical efficiency and buys an
    exact gradient for the part with hundreds of parameters, which is the part that has to
    be refitted at every judged gameweek.
    """

    home_rate = np.exp(
        np.array(
            [
                home_advantage + attack[int(h)] - defence[int(a)]
                for h, a in zip(history["home_club"], history["away_club"], strict=True)
            ]
        )
    )
    away_rate = np.exp(
        np.array(
            [
                attack[int(a)] - defence[int(h)]
                for h, a in zip(history["home_club"], history["away_club"], strict=True)
            ]
        )
    )
    home_goals = history["home_goals"].to_numpy(dtype="int64")
    away_goals = history["away_goals"].to_numpy(dtype="int64")
    best_rho = 0.0
    best_value = -math.inf
    for rho in config.rho_grid:
        tau = _tau(home_goals, away_goals, home_rate, away_rate, rho)
        if np.any(tau <= 0.0):
            continue
        value = float(np.sum(weights * np.log(tau)))
        if value > best_value:
            best_value = value
            best_rho = float(rho)
    return best_rho


def _tau(
    home_goals: np.ndarray,
    away_goals: np.ndarray,
    home_rate: np.ndarray,
    away_rate: np.ndarray,
    rho: float,
) -> np.ndarray:
    """The Dixon-Coles correction, one factor per match."""

    tau = np.ones_like(home_rate, dtype="float64")
    zero_zero = (home_goals == 0) & (away_goals == 0)
    zero_one = (home_goals == 0) & (away_goals == 1)
    one_zero = (home_goals == 1) & (away_goals == 0)
    one_one = (home_goals == 1) & (away_goals == 1)
    tau[zero_zero] = 1.0 - home_rate[zero_zero] * away_rate[zero_zero] * rho
    tau[zero_one] = 1.0 + home_rate[zero_one] * rho
    tau[one_zero] = 1.0 + away_rate[one_zero] * rho
    tau[one_one] = 1.0 - rho
    return tau


# --- the study ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TeamRatingStudyConfig:
    """Which seasons are fitted, which gameweeks are judged, and how the rating is fitted."""

    seasons: tuple[str, ...] = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
    evaluated_seasons: tuple[str, ...] = ("2022-23", "2023-24", "2024-25")
    first_evaluated_gameweek: int = 6
    dixon_coles: DixonColesConfig = DixonColesConfig()
    half_life_grid: tuple[float, ...] = (60.0, 120.0, 180.0, 300.0, 500.0)
    ridge_grid: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0)
    bootstrap_resamples: int = 2000
    deterministic_seed: int = 0

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
        if self.first_evaluated_gameweek < 2:
            raise ExperimentConfigurationError(
                "A judged gameweek must have at least one completed gameweek before it."
            )
        if self.bootstrap_resamples < 100:
            raise ExperimentConfigurationError("bootstrap_resamples must be at least 100.")


def walk_forward_log_likelihood(
    matches: pd.DataFrame,
    seasons: Sequence[str],
    config: DixonColesConfig,
    *,
    first_gameweek: int,
) -> float:
    """Mean log-likelihood of scorelines the fit had not seen, over the named seasons.

    This is the quantity a rating is selected on. It is deliberately the same measure the
    study reports, computed on seasons that precede whichever season is being judged, so
    the half life and ridge are never chosen with the judged season in view.
    """

    promoted = promoted_clubs(matches)
    values: list[float] = []
    for season in seasons:
        judged = matches.loc[matches["season"] == season]
        if judged.empty:
            continue
        earlier = sorted({str(value) for value in matches["season"] if str(value) < season})
        prior = (0.0, 0.0)
        arrivals = promoted.get(str(season), ())
        gameweeks = sorted(
            int(value) for value in judged["gameweek"].unique() if int(value) >= first_gameweek
        )
        for gameweek in gameweeks:
            block = judged.loc[judged["gameweek"] == gameweek]
            as_of = pd.Timestamp(block["kickoff"].min())
            if matches.loc[matches["kickoff"] < as_of].empty:
                continue
            rating = fit_dixon_coles(
                matches,
                as_of=as_of,
                config=config,
                promoted_prior=prior,
                newly_promoted=arrivals if earlier else (),
            )
            for record in block.to_dict("records"):
                matrix = rating.score_matrix(int(record["home_club"]), int(record["away_club"]))
                observed = float(
                    matrix[
                        min(int(record["home_goals"]), MAXIMUM_GOALS),
                        min(int(record["away_goals"]), MAXIMUM_GOALS),
                    ]
                )
                values.append(math.log(max(observed, 1e-12)))
    if not values:
        raise ExperimentExecutionError("No fixture was available to select on.")
    return float(np.mean(values))


def select_dixon_coles_config(
    matches: pd.DataFrame,
    seasons: Sequence[str],
    *,
    half_life_grid: Sequence[float],
    ridge_grid: Sequence[float],
    first_gameweek: int,
    base: DixonColesConfig | None = None,
) -> DixonColesConfig:
    """Choose the half life and ridge on earlier seasons, by out-of-sample goal likelihood.

    Hard-coding a decay rate would make the rating's showing partly a matter of taste. The
    grid is searched on seasons that precede the judged one and never on the judged one, so
    the selection is part of the model rather than part of the result.
    """

    settings = DixonColesConfig() if base is None else base
    candidates = [season for season in seasons]
    if len(candidates) < 2:
        # One season cannot be walked forward, so nothing can be selected on it.
        return settings
    scored = candidates[1:]
    best = settings
    best_value = -math.inf
    for half_life in half_life_grid:
        for ridge in ridge_grid:
            candidate = DixonColesConfig(
                half_life_days=float(half_life),
                ridge=float(ridge),
                rho_grid=settings.rho_grid,
                maximum_iterations=settings.maximum_iterations,
            )
            value = walk_forward_log_likelihood(
                matches.loc[matches["season"].isin(candidates)],
                scored,
                candidate,
                first_gameweek=first_gameweek,
            )
            if value > best_value:
                best_value = value
                best = candidate
    return best


@dataclass(frozen=True, slots=True)
class SeasonScorecard:
    """One judged season, on all three of the things a rating is for."""

    season: str
    fixtures: int
    rating_log_likelihood: float
    baseline_log_likelihood: float
    rating_clean_sheet_brier: float
    uncalibrated_clean_sheet_brier: float
    published_clean_sheet_brier: float
    rating_attacking_correlation: float
    published_attacking_correlation: float
    rating_defensive_correlation: float
    published_defensive_correlation: float
    mean_clean_sheet_probability: float
    realized_clean_sheet_rate: float
    refits: int

    @property
    def log_likelihood_improvement(self) -> float:
        return self.rating_log_likelihood - self.baseline_log_likelihood

    @property
    def brier_improvement(self) -> float:
        """Positive when the rating's clean-sheet probabilities are better calibrated."""

        return self.published_clean_sheet_brier - self.rating_clean_sheet_brier


@dataclass(frozen=True, slots=True)
class TeamRatingStudy:
    contract_version: str
    config: TeamRatingStudyConfig
    seasons: tuple[SeasonScorecard, ...]
    pooled: Mapping[str, float]
    intervals: Mapping[str, tuple[float, float]]
    reliability: tuple[Mapping[str, float], ...]
    example_rating: Mapping[str, object]
    verdict: Mapping[str, object]
    diagnostics: Mapping[str, object]


def _baseline_rates(
    history: pd.DataFrame, decay_per_day: float, as_of: pd.Timestamp
) -> tuple[float, float]:
    """The league's own home and away scoring averages, decayed the same way the rating is."""

    age = (as_of - history["kickoff"]).dt.total_seconds().to_numpy(dtype="float64") / 86400.0
    weights = np.exp(-decay_per_day * np.clip(age, 0.0, None))
    total = float(weights.sum())
    if total <= 0.0:
        raise ExperimentExecutionError("The baseline has no weighted matches to average.")
    home = float(np.sum(weights * history["home_goals"].to_numpy(dtype="float64")) / total)
    away = float(np.sum(weights * history["away_goals"].to_numpy(dtype="float64")) / total)
    return max(home, 1e-6), max(away, 1e-6)


def _poisson_log_pmf(goals: int, rate: float) -> float:
    return goals * math.log(max(rate, 1e-12)) - rate - math.lgamma(goals + 1)


def _fit_logistic(design: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Newton's method on a small logistic, with a whisper of ridge for conditioning."""

    theta = np.zeros(design.shape[1], dtype="float64")
    for _ in range(50):
        probability = 1.0 / (1.0 + np.exp(-np.clip(design @ theta, -30.0, 30.0)))
        weight = np.clip(probability * (1.0 - probability), 1e-8, None)
        gradient = design.T @ (target - probability)
        hessian = design.T @ (design * weight[:, None]) + 1e-6 * np.eye(design.shape[1])
        step = np.linalg.solve(hessian, gradient)
        theta = theta + step
        if float(np.max(np.abs(step))) < 1e-9:
            break
    return theta


def _logit(probability: np.ndarray | float) -> np.ndarray:
    clipped = np.clip(np.asarray(probability, dtype="float64"), 1e-6, 1.0 - 1e-6)
    return np.asarray(np.log(clipped / (1.0 - clipped)), dtype="float64")


def _logistic_on_published_difficulty(matches: pd.DataFrame) -> tuple[float, float, float]:
    """Fit ``clean sheet ~ difficulty + venue`` on past matches.

    A logistic on the published rating is the fairest comparison available: it lets the
    opaque one-to-five scale be mapped to probabilities as well as any monotone map can,
    rather than being compared against a probability model on a scale it never claimed.
    The rating gets exactly the same courtesy in ``fit_clean_sheet_calibration``.
    """

    difficulty = np.concatenate(
        [
            matches["home_difficulty"].to_numpy(dtype="float64"),
            matches["away_difficulty"].to_numpy(dtype="float64"),
        ]
    )
    at_home = np.concatenate([np.ones(len(matches)), np.zeros(len(matches))])
    clean = np.concatenate(
        [
            (matches["away_goals"].to_numpy(dtype="int64") == 0).astype("float64"),
            (matches["home_goals"].to_numpy(dtype="int64") == 0).astype("float64"),
        ]
    )
    keep = np.isfinite(difficulty)
    design = np.column_stack([np.ones(int(keep.sum())), difficulty[keep], at_home[keep]])
    theta = _fit_logistic(design, clean[keep])
    return float(theta[0]), float(theta[1]), float(theta[2])


def fit_clean_sheet_calibration(
    matches: pd.DataFrame,
    seasons: Sequence[str],
    config: DixonColesConfig,
    *,
    first_gameweek: int,
) -> tuple[float, float]:
    """Recalibrate the rating's clean-sheet probability on seasons already played.

    The published baseline is a logistic fitted on outcomes, so it is calibrated by
    construction. A goal model is not: it is fitted to scorelines and its clean-sheet
    probability is a by-product. Comparing an uncalibrated by-product against a fitted
    logistic would measure the fitting, not the rating, so the rating is given the same
    one-parameter-per-slope treatment on the same kind of data — walked forward over the
    seasons before the judged one, never the judged one itself.
    """

    promoted = promoted_clubs(matches)
    logits: list[float] = []
    realized: list[float] = []
    for season in seasons:
        judged = matches.loc[matches["season"] == season]
        if judged.empty:
            continue
        arrivals = promoted.get(str(season), ())
        gameweeks = sorted(
            int(value) for value in judged["gameweek"].unique() if int(value) >= first_gameweek
        )
        for gameweek in gameweeks:
            block = judged.loc[judged["gameweek"] == gameweek]
            as_of = pd.Timestamp(block["kickoff"].min())
            if matches.loc[matches["kickoff"] < as_of].empty:
                continue
            rating = fit_dixon_coles(matches, as_of=as_of, config=config, newly_promoted=arrivals)
            for record in block.to_dict("records"):
                home_club = int(record["home_club"])
                away_club = int(record["away_club"])
                for is_home, club, opponent, conceded in (
                    (True, home_club, away_club, int(record["away_goals"])),
                    (False, away_club, home_club, int(record["home_goals"])),
                ):
                    probability = rating.clean_sheet_probability(club, opponent, is_home=is_home)
                    logits.append(float(_logit(probability)))
                    realized.append(1.0 if conceded == 0 else 0.0)
    if not logits:
        return (0.0, 1.0)
    design = np.column_stack([np.ones(len(logits)), np.asarray(logits, dtype="float64")])
    theta = _fit_logistic(design, np.asarray(realized, dtype="float64"))
    return (float(theta[0]), float(theta[1]))


def _calibrated_clean_sheet(coefficients: tuple[float, float], probability: float) -> float:
    intercept, slope = coefficients
    value = intercept + slope * float(_logit(probability))
    return float(1.0 / (1.0 + math.exp(-max(min(value, 30.0), -30.0))))


def _published_clean_sheet(
    coefficients: tuple[float, float, float], difficulty: float, *, is_home: bool
) -> float:
    intercept, slope, venue = coefficients
    if not math.isfinite(difficulty):
        difficulty = 3.0
    value = intercept + slope * difficulty + venue * (1.0 if is_home else 0.0)
    return float(1.0 / (1.0 + math.exp(-max(min(value, 30.0), -30.0))))


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    if left.size < 5 or np.unique(left).size < 2 or np.unique(right).size < 2:
        return 0.0
    frame = pd.DataFrame({"left": left, "right": right})
    value = float(str(frame.corr(method="spearman").iloc[0, 1]))
    return value if math.isfinite(value) else 0.0


def _bootstrap(values: np.ndarray, *, resamples: int, seed: int) -> tuple[float, float]:
    if values.size == 0:
        return (0.0, 0.0)
    generator = np.random.default_rng(seed)
    draws = np.empty(resamples, dtype="float64")
    for index in range(resamples):
        sample = generator.integers(0, values.size, values.size)
        draws[index] = float(values[sample].mean())
    return (float(np.quantile(draws, 0.05)), float(np.quantile(draws, 0.95)))


def player_fixture_rows(archive_root: Path | str, seasons: Sequence[str]) -> pd.DataFrame:
    """Player-gameweek points joined to the club code and the opponent they were earned against."""

    root = Path(archive_root)
    panel = build_panel(root)
    panel = panel.loc[panel["season"].isin(list(seasons))].copy()
    fixtures = build_fixture_panel(root, seasons=tuple(seasons))
    names: list[pd.DataFrame] = []
    for season in seasons:
        codes = load_team_codes(root, season).loc[:, ["code", "name"]].copy()
        codes["season"] = season
        names.append(codes)
    bridge = pd.concat(names, ignore_index=True).rename(columns={"name": "team_id"})
    panel = panel.merge(bridge, on=["season", "team_id"], how="left")
    if bool(panel["code"].isna().any()):
        raise ExperimentExecutionError("A panel club does not resolve to a persistent code.")
    panel["club"] = panel["code"].astype("int64")
    schedule = (
        fixtures.loc[:, ["season", "gameweek", "team_id", "opponent_team_id", "is_home"]]
        .rename(columns={"team_id": "club", "opponent_team_id": "opponent"})
        .astype({"club": "int64", "opponent": "int64"})
    )
    # A double gameweek gives a player two opponent rows; the panel already summed his
    # points across both, so each row is kept and the pair share the same outcome.
    return panel.merge(schedule, on=["season", "gameweek", "club"], how="inner")


def _fixture_lookup(matches: pd.DataFrame) -> Mapping[tuple[int, int, int], Mapping[str, float]]:
    """Index a season's fixtures by gameweek and the unordered pair of clubs."""

    lookup: dict[tuple[int, int, int], Mapping[str, float]] = {}
    for record in matches.to_dict("records"):
        home = int(record["home_club"])
        away = int(record["away_club"])
        gameweek = int(record["gameweek"])
        lookup[(gameweek, home, away)] = {
            "home_difficulty": float(record["home_difficulty"]),
            "away_difficulty": float(record["away_difficulty"]),
        }
    return lookup


def run_team_rating_study(
    archive_root: Path | str, config: TeamRatingStudyConfig | None = None
) -> TeamRatingStudy:
    """Fit the rating forward and judge it on goals, on clean sheets, and on players."""

    settings = TeamRatingStudyConfig() if config is None else config
    root = Path(archive_root)
    matches = load_match_results(root, settings.seasons)
    promoted = promoted_clubs(matches)
    players = player_fixture_rows(root, settings.evaluated_seasons)
    scorecards: list[SeasonScorecard] = []
    pooled_likelihood: list[float] = []
    pooled_brier: list[float] = []
    reliability_rows: list[dict[str, float]] = []
    example: dict[str, object] = {}
    selected: dict[str, DixonColesConfig] = {}
    for season in settings.evaluated_seasons:
        earlier = [value for value in settings.seasons if value < season]
        chosen = select_dixon_coles_config(
            matches.loc[matches["season"].isin(earlier)],
            earlier,
            half_life_grid=settings.half_life_grid,
            ridge_grid=settings.ridge_grid,
            first_gameweek=settings.first_evaluated_gameweek,
            base=settings.dixon_coles,
        )
        selected[season] = chosen
        prior = measure_promoted_prior(matches, earlier, chosen)
        published = _logistic_on_published_difficulty(matches.loc[matches["season"].isin(earlier)])
        calibration = fit_clean_sheet_calibration(
            matches.loc[matches["season"].isin(earlier)],
            earlier[1:],
            chosen,
            first_gameweek=settings.first_evaluated_gameweek,
        )
        arrivals = promoted.get(season, ())
        judged = matches.loc[matches["season"] == season]
        lookup = _fixture_lookup(judged)
        gameweeks = sorted(
            int(value)
            for value in judged["gameweek"].unique()
            if int(value) >= settings.first_evaluated_gameweek
        )
        likelihood_difference: list[float] = []
        brier_difference: list[float] = []
        rating_likelihood: list[float] = []
        baseline_likelihood: list[float] = []
        rating_brier: list[float] = []
        raw_brier: list[float] = []
        published_brier: list[float] = []
        clean_probabilities: list[float] = []
        clean_realized: list[float] = []
        attacking: list[tuple[float, float, float]] = []
        defensive: list[tuple[float, float, float]] = []
        refits = 0
        for gameweek in gameweeks:
            block = judged.loc[judged["gameweek"] == gameweek]
            as_of = pd.Timestamp(block["kickoff"].min())
            history = matches.loc[matches["kickoff"] < as_of]
            if history.empty:
                continue
            rating = fit_dixon_coles(
                matches,
                as_of=as_of,
                config=chosen,
                promoted_prior=prior,
                newly_promoted=arrivals,
            )
            refits += 1
            if not example:
                example = {
                    "season": season,
                    "gameweek": gameweek,
                    "matches_used": rating.matches_used,
                    "home_advantage": rating.home_advantage,
                    "rho": rating.rho,
                    "promoted_attack_prior": rating.promoted_attack_prior,
                    "promoted_defence_prior": rating.promoted_defence_prior,
                }
            home_rate, away_rate = _baseline_rates(history, chosen.decay_per_day, as_of)
            for record in block.to_dict("records"):
                home_club = int(record["home_club"])
                away_club = int(record["away_club"])
                home_goals = int(record["home_goals"])
                away_goals = int(record["away_goals"])
                matrix = rating.score_matrix(home_club, away_club)
                observed = float(
                    matrix[min(home_goals, MAXIMUM_GOALS), min(away_goals, MAXIMUM_GOALS)]
                )
                rating_value = math.log(max(observed, 1e-12))
                baseline_value = _poisson_log_pmf(home_goals, home_rate) + _poisson_log_pmf(
                    away_goals, away_rate
                )
                rating_likelihood.append(rating_value)
                baseline_likelihood.append(baseline_value)
                likelihood_difference.append(rating_value - baseline_value)
                sides = (
                    (True, home_club, away_club, away_goals, float(record["home_difficulty"])),
                    (False, away_club, home_club, home_goals, float(record["away_difficulty"])),
                )
                for is_home, club, opponent, conceded, difficulty in sides:
                    raw = rating.clean_sheet_probability(club, opponent, is_home=is_home)
                    probability = _calibrated_clean_sheet(calibration, raw)
                    realized = 1.0 if conceded == 0 else 0.0
                    reference = _published_clean_sheet(published, difficulty, is_home=is_home)
                    rating_brier.append((probability - realized) ** 2)
                    raw_brier.append((raw - realized) ** 2)
                    published_brier.append((reference - realized) ** 2)
                    brier_difference.append(
                        (reference - realized) ** 2 - (probability - realized) ** 2
                    )
                    clean_probabilities.append(probability)
                    clean_realized.append(realized)
                    reliability_rows.append(
                        {
                            "probability": probability,
                            "realized": realized,
                            "published": reference,
                        }
                    )
            block_players = players.loc[
                (players["season"] == season) & (players["gameweek"] == gameweek)
            ]
            for record in block_players.to_dict("records"):
                club = int(record["club"])
                opponent = int(record["opponent"])
                is_home = bool(record["is_home"])
                points = float(record["total_points"])
                home_key = (gameweek, club, opponent) if is_home else (gameweek, opponent, club)
                fixture = lookup.get(home_key)
                if fixture is None:
                    continue
                difficulty = float(
                    fixture["home_difficulty"] if is_home else fixture["away_difficulty"]
                )
                position = str(record["position"])
                if position in ATTACKING_POSITIONS:
                    # The published rating scores a *fixture*, not an opponent: it already
                    # folds in where the match is played. The rating's like-for-like answer
                    # is therefore how many goals it expects the player's club to score in
                    # this fixture, not the opponent's defence in isolation.
                    home_rate, away_rate = (
                        rating.expected_goals(club, opponent)
                        if is_home
                        else rating.expected_goals(opponent, club)
                    )
                    attacking.append((home_rate if is_home else away_rate, -difficulty, points))
                elif position in DEFENSIVE_POSITIONS:
                    # Recalibration is monotone, so it cannot change an ordering; the raw
                    # probability is used here and the two agree by construction.
                    defensive.append(
                        (
                            rating.clean_sheet_probability(club, opponent, is_home=is_home),
                            -difficulty,
                            points,
                        )
                    )
        if not rating_likelihood:
            continue
        attacking_array = np.asarray(attacking, dtype="float64")
        defensive_array = np.asarray(defensive, dtype="float64")
        scorecards.append(
            SeasonScorecard(
                season=season,
                fixtures=len(rating_likelihood),
                rating_log_likelihood=float(np.mean(rating_likelihood)),
                baseline_log_likelihood=float(np.mean(baseline_likelihood)),
                rating_clean_sheet_brier=float(np.mean(rating_brier)),
                uncalibrated_clean_sheet_brier=float(np.mean(raw_brier)),
                published_clean_sheet_brier=float(np.mean(published_brier)),
                rating_attacking_correlation=(
                    _spearman(attacking_array[:, 0], attacking_array[:, 2])
                    if attacking_array.size
                    else 0.0
                ),
                published_attacking_correlation=(
                    _spearman(attacking_array[:, 1], attacking_array[:, 2])
                    if attacking_array.size
                    else 0.0
                ),
                rating_defensive_correlation=(
                    _spearman(defensive_array[:, 0], defensive_array[:, 2])
                    if defensive_array.size
                    else 0.0
                ),
                published_defensive_correlation=(
                    _spearman(defensive_array[:, 1], defensive_array[:, 2])
                    if defensive_array.size
                    else 0.0
                ),
                mean_clean_sheet_probability=float(np.mean(clean_probabilities)),
                realized_clean_sheet_rate=float(np.mean(clean_realized)),
                refits=refits,
            )
        )
        pooled_likelihood.extend(likelihood_difference)
        pooled_brier.extend(brier_difference)
    if not scorecards:
        raise ExperimentExecutionError("No season could be judged.")
    likelihood_array = np.asarray(pooled_likelihood, dtype="float64")
    brier_array = np.asarray(pooled_brier, dtype="float64")
    pooled = {
        "log_likelihood_improvement": float(likelihood_array.mean()),
        "brier_improvement": float(brier_array.mean()),
        "rating_attacking_correlation": float(
            np.mean([card.rating_attacking_correlation for card in scorecards])
        ),
        "published_attacking_correlation": float(
            np.mean([card.published_attacking_correlation for card in scorecards])
        ),
        "rating_defensive_correlation": float(
            np.mean([card.rating_defensive_correlation for card in scorecards])
        ),
        "published_defensive_correlation": float(
            np.mean([card.published_defensive_correlation for card in scorecards])
        ),
    }
    intervals = {
        "log_likelihood_improvement": _bootstrap(
            likelihood_array,
            resamples=settings.bootstrap_resamples,
            seed=settings.deterministic_seed,
        ),
        "brier_improvement": _bootstrap(
            brier_array,
            resamples=settings.bootstrap_resamples,
            seed=settings.deterministic_seed + 1,
        ),
    }
    return TeamRatingStudy(
        contract_version=TEAM_RATING_STUDY_CONTRACT_VERSION,
        config=settings,
        seasons=tuple(scorecards),
        pooled=pooled,
        intervals=intervals,
        reliability=_reliability(reliability_rows),
        example_rating=example,
        verdict=rating_gate_verdict(tuple(scorecards), pooled, intervals),
        diagnostics={
            "seasons": list(settings.seasons),
            "evaluated_seasons": list(settings.evaluated_seasons),
            "first_evaluated_gameweek": settings.first_evaluated_gameweek,
            "selected_half_life_days": {
                season: value.half_life_days for season, value in selected.items()
            },
            "selected_ridge": {season: value.ridge for season, value in selected.items()},
            "locked_holdout_accessed": False,
            "refits": sum(card.refits for card in scorecards),
        },
    )


def _reliability(
    rows: Sequence[Mapping[str, float]], bins: int = 10
) -> tuple[Mapping[str, float], ...]:
    """Predicted against realized clean-sheet rate, in equal-width probability bins."""

    if not rows:
        return ()
    frame = pd.DataFrame(list(rows))
    edges = np.linspace(0.0, 1.0, bins + 1)
    frame["bin"] = np.clip(np.digitize(frame["probability"], edges[1:-1]), 0, bins - 1)
    summary: list[Mapping[str, float]] = []
    for index, block in frame.groupby("bin", sort=True):
        position = int(str(index))
        summary.append(
            {
                "bin_low": float(edges[position]),
                "bin_high": float(edges[position + 1]),
                "rows": float(len(block)),
                "mean_predicted": float(block["probability"].mean()),
                "mean_published": float(block["published"].mean()),
                "realized": float(block["realized"].mean()),
            }
        )
    return tuple(summary)


def rating_gate_verdict(
    scorecards: Sequence[SeasonScorecard],
    pooled: Mapping[str, float],
    intervals: Mapping[str, tuple[float, float]],
) -> dict[str, object]:
    """The bar, fixed before the numbers existed, applied by code rather than by hand.

    Three conditions. The rating must predict goals better than a constant-rate baseline in
    every judged season, with the pooled interval clear of zero; its clean-sheet
    probabilities must be better calibrated than a logistic on the published rating, pooled
    and in all but at most one season; and it must order player points at least as well as
    the published rating on both sides of the ball. Nothing here promotes anything — passing
    means the rating has earned the right to be measured inside a projection.
    """

    goals = bool(scorecards) and all(card.log_likelihood_improvement > 0.0 for card in scorecards)
    goals_interval = intervals["log_likelihood_improvement"][0] > 0.0
    better_seasons = sum(1 for card in scorecards if card.brier_improvement > 0.0)
    clean_sheets = pooled["brier_improvement"] > 0.0 and better_seasons >= max(
        1, len(scorecards) - 1
    )
    players = (
        pooled["rating_attacking_correlation"] >= pooled["published_attacking_correlation"]
        and pooled["rating_defensive_correlation"] >= pooled["published_defensive_correlation"]
    )
    return {
        "goals_passes": bool(goals and goals_interval),
        "goals_sign_consistent": goals,
        "goals_interval_excludes_zero": goals_interval,
        "clean_sheets_passes": bool(clean_sheets),
        "clean_sheet_seasons_better": better_seasons,
        "players_passes": bool(players),
        "passes": bool(goals and goals_interval and clean_sheets and players),
    }


def study_to_markdown(study: TeamRatingStudy) -> str:
    """The artifact a reader can check without running anything."""

    config = study.config
    lines = [
        "# A team rating from goals, against the rating the platform ships",
        "",
        f"- Contract `{study.contract_version}`; fitted on {', '.join(config.seasons)}, judged "
        f"walk-forward on {', '.join(config.evaluated_seasons)} from gameweek "
        f"{config.first_evaluated_gameweek}.",
        f"- Dixon-Coles refitted at every judged gameweek on matches that kicked off before "
        f"it ({study.diagnostics.get('refits')} fits). The half life and ridge are chosen per "
        f"judged season on the seasons before it: half lives "
        f"{study.diagnostics.get('selected_half_life_days')}, ridges "
        f"{study.diagnostics.get('selected_ridge')}.",
        f"- {config.bootstrap_resamples} bootstrap resamples, seed {config.deterministic_seed}.",
        "- Measurement only. The locked 2025-26 holdout is refused by the configuration, no "
        "model or contract changed, and the verdict was computed by `rating_gate_verdict`.",
        "",
        "## Season by season",
        "",
        "| Season | Fixtures | Rating log-lik | Baseline log-lik | Rating Brier | "
        "Uncalibrated | Published Brier | Refits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for card in study.seasons:
        lines.append(
            f"| {card.season} | {card.fixtures} | {card.rating_log_likelihood:.4f} "
            f"| {card.baseline_log_likelihood:.4f} | {card.rating_clean_sheet_brier:.4f} "
            f"| {card.uncalibrated_clean_sheet_brier:.4f} "
            f"| {card.published_clean_sheet_brier:.4f} | {card.refits} |"
        )
    lines += [
        "",
        "| Season | Attacking (rating / published) | Defensive (rating / published) | "
        "Clean sheets predicted / realized |",
        "| --- | --- | --- | --- |",
    ]
    for card in study.seasons:
        lines.append(
            f"| {card.season} | {card.rating_attacking_correlation:+.4f} / "
            f"{card.published_attacking_correlation:+.4f} "
            f"| {card.rating_defensive_correlation:+.4f} / "
            f"{card.published_defensive_correlation:+.4f} "
            f"| {card.mean_clean_sheet_probability:.3f} / {card.realized_clean_sheet_rate:.3f} |"
        )
    likelihood = study.intervals["log_likelihood_improvement"]
    brier = study.intervals["brier_improvement"]
    lines += [
        "",
        "## Pooled",
        "",
        f"- Log-likelihood per fixture against the constant-rate baseline: "
        f"**{study.pooled['log_likelihood_improvement']:+.4f}** "
        f"[{likelihood[0]:+.4f}, {likelihood[1]:+.4f}].",
        f"- Clean-sheet Brier against a logistic on the published rating: "
        f"**{study.pooled['brier_improvement']:+.4f}** [{brier[0]:+.4f}, {brier[1]:+.4f}] "
        "(positive means the rating is better calibrated).",
        f"- Ordering player points, attacking side: rating "
        f"{study.pooled['rating_attacking_correlation']:+.4f} against published "
        f"{study.pooled['published_attacking_correlation']:+.4f}; defensive side: "
        f"{study.pooled['rating_defensive_correlation']:+.4f} against "
        f"{study.pooled['published_defensive_correlation']:+.4f}.",
        "",
        "## Clean-sheet reliability",
        "",
        "| Bin | Rows | Predicted | Published | Realized |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in study.reliability:
        lines.append(
            f"| {row['bin_low']:.1f}-{row['bin_high']:.1f} | {row['rows']:.0f} "
            f"| {row['mean_predicted']:.3f} | {row['mean_published']:.3f} "
            f"| {row['realized']:.3f} |"
        )
    verdict = study.verdict
    lines += [
        "",
        "## Verdict",
        "",
        "The gate: better than a constant-rate baseline at predicting goals in every judged "
        "season with the pooled interval clear of zero; better calibrated clean sheets than a "
        "logistic on the published rating, pooled and in all but at most one season; and an "
        "ordering of player points at least as strong as the published rating on both sides "
        "of the ball.",
        "",
        f"- Goals: {'passes' if verdict['goals_passes'] else 'fails'} "
        f"(sign consistent: {verdict['goals_sign_consistent']}; interval clears zero: "
        f"{verdict['goals_interval_excludes_zero']}).",
        f"- Clean sheets: {'passes' if verdict['clean_sheets_passes'] else 'fails'} "
        f"({verdict['clean_sheet_seasons_better']} of {len(study.seasons)} seasons better).",
        f"- Players: {'passes' if verdict['players_passes'] else 'fails'}.",
        "",
        (
            "**The rating clears its gate**, which earns it a measurement inside a "
            "projection — not a promotion."
            if verdict["passes"]
            else "**The rating does not clear its gate.**"
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "ATTACKING_POSITIONS",
    "DEFENSIVE_POSITIONS",
    "LOCKED_HOLDOUT_SEASON",
    "MAXIMUM_GOALS",
    "TEAM_RATING_STUDY_CONTRACT_VERSION",
    "DixonColesConfig",
    "SeasonScorecard",
    "TeamRating",
    "TeamRatingStudy",
    "TeamRatingStudyConfig",
    "fit_clean_sheet_calibration",
    "fit_dixon_coles",
    "load_match_results",
    "measure_promoted_prior",
    "player_fixture_rows",
    "promoted_clubs",
    "rating_gate_verdict",
    "run_team_rating_study",
    "select_dixon_coles_config",
    "study_to_markdown",
    "walk_forward_log_likelihood",
]
