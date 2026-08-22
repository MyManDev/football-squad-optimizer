"""The operational control extended into a season that has started.

The opening control projects from carry-over alone, which is the only honest thing to do
when no gameweek has been played. Once one has, there are two records for every player
and neither should be thrown away: a full completed season, and a handful of matches that
describe the situation the player is actually in now.

What this module does is blend them, in the two-stage shape the rest of the projection
layer uses -- expected minutes times a scoring rate -- rather than blending the finished
points. That distinction is not cosmetic. Blending the products collapses:

    in_season_rate * in_season_minutes_per_gameweek / 90
        == (points / minutes * 90) * (minutes / n) / 90
        == points / n

so a blend of expected points is algebraically a blend of season-to-date points per
gameweek, and the minutes term disappears. It would then be unable to tell a player who
played ninety minutes from one who played twenty for the same return, which is exactly the
distinction that predicts the next gameweek. Blending the two stages separately keeps it.

The weights are declared, not fitted, and there are two of them because the two stages are
estimated from different samples. Playing time is shrunk by gameweeks elapsed --
``played / (played + prior_gameweek_equivalent)``, the equivalent set to the production
control's ``rate_window`` so the blend reaches an even split exactly when the season so far
fills the window the control already calls relevant. A scoring *rate* is shrunk by minutes
instead, ``minutes / (minutes + prior_minute_equivalent)``, because gameweeks are the wrong
unit for it: a substitute who played eight minutes has a full gameweek of evidence about
his playing time and almost none about his rate. The minute equivalent is
``CrossSeasonConfig.min_minutes`` -- three full matches, the threshold the carry-over path
already applies before it trusts a rate at all.

A player with in-season minutes but no completed season has evidence and no two-stage prior
to shrink it against. The shrinkage then happens on the points scale, toward the same
opening-price prior the opening control gives exactly these players, at the same rate
weight. Without that, one appearance is taken at full weight: the first version of this
module projected a player with seventy-five minutes and six points at 6.0 expected points,
above the best player in the game.

**A known consequence, recorded rather than hidden.** Because each stage is shrunk in its
own unit, a small-minutes high-return cameo is not fully discounted and can out-project a
full match with a modest return -- twenty minutes for four points lands slightly above
ninety minutes for four, since a per-ninety rate of eighteen survives even at seven per
cent weight. Both weights are individually defensible and the gap is small, but whether the
minute equivalent is strong enough is a question for a walk-forward measurement over
completed seasons, not for an intuition. ``test_in_season_blend.py`` pins the current
numbers so that measurement has a recorded starting point to move.
"""

import math
from dataclasses import dataclass
from typing import Final

import pandas as pd

from squadopt.data.errors import format_examples
from squadopt.features import PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN
from squadopt.features.config import MINUTES_PER_FULL_MATCH
from squadopt.prediction.config import PredictionConfigurationError

# The identity a decision made through this path records. The model *name* is not chosen
# here: a live decision must carry the operational control's name, checked unconditionally
# in the application layer, so only the version distinguishes this path from the opening
# one. The version is a sibling of ``opening-carry-over-v1`` because that is what it is --
# the same control, told about the season so far.
IN_SEASON_MODEL_VERSION: Final = "in-season-carry-over-v1"
IN_SEASON_FEATURE_CONTRACT_VERSION: Final = "in-season-carry-over-features-v1"

# A local contract identity, deliberately. Measuring this path must not move a constant
# another frozen candidate reads; a shared bump belongs in a promotion change, not here.
IN_SEASON_BLEND_CONTRACT_VERSION: Final = "in_season_blend_v1"

_ROSTER_COLUMNS: Final = ("player_id", "name", "team_id", "position", "price_tenths")


@dataclass(frozen=True, slots=True)
class InSeasonBlendConfig:
    """How much the season so far is allowed to say."""

    # How many played gameweeks the carried season counts for. The production control's
    # rate window, so the blend reaches an even split exactly when the season so far
    # fills the window the control already calls relevant.
    prior_gameweek_equivalent: int = 6

    # How many minutes an in-season *rate* must accumulate before it is worth as much as
    # the prior it is shrunk toward. Gameweeks are the wrong unit for a rate: a player who
    # came on for eight minutes has played a gameweek but has told us almost nothing about
    # his scoring rate. This is CrossSeasonConfig.min_minutes -- three full matches, the
    # threshold the carry-over path already uses before it trusts a rate at all.
    prior_minute_equivalent: int = 270

    def __post_init__(self) -> None:
        if isinstance(self.prior_gameweek_equivalent, bool) or not isinstance(
            self.prior_gameweek_equivalent, int
        ):
            raise PredictionConfigurationError(
                "prior_gameweek_equivalent must be an integer, got "
                f"{self.prior_gameweek_equivalent!r}."
            )
        if self.prior_gameweek_equivalent < 1:
            raise PredictionConfigurationError(
                "prior_gameweek_equivalent must be at least 1, got "
                f"{self.prior_gameweek_equivalent}."
            )
        if isinstance(self.prior_minute_equivalent, bool) or not isinstance(
            self.prior_minute_equivalent, int
        ):
            raise PredictionConfigurationError(
                f"prior_minute_equivalent must be an integer, got {self.prior_minute_equivalent!r}."
            )
        if self.prior_minute_equivalent < 1:
            raise PredictionConfigurationError(
                f"prior_minute_equivalent must be at least 1, got {self.prior_minute_equivalent}."
            )


@dataclass(frozen=True, slots=True)
class InSeasonBlend:
    """A projection for a started season, with the routes each player took."""

    table: pd.DataFrame
    gameweeks_played: int
    in_season_weight: float
    players: int
    players_with_in_season_minutes: int
    players_blended_two_stage: int
    players_shrunk_against_the_price_prior: int
    players_from_carry_over_only: int
    players_priced_from_the_prior: int
    contract_version: str = IN_SEASON_BLEND_CONTRACT_VERSION

    @property
    def diagnostics(self) -> dict[str, object]:
        """What a weekly report should be able to say about this projection."""

        return {
            "in_season_blend_contract_version": self.contract_version,
            "gameweeks_played": self.gameweeks_played,
            "in_season_weight": round(self.in_season_weight, 6),
            "carry_over_weight": round(1.0 - self.in_season_weight, 6),
            "players": self.players,
            "players_with_in_season_minutes": self.players_with_in_season_minutes,
            "players_blended_two_stage": self.players_blended_two_stage,
            "players_shrunk_against_the_price_prior": (self.players_shrunk_against_the_price_prior),
            "players_from_carry_over_only": self.players_from_carry_over_only,
            "players_priced_from_the_prior": self.players_priced_from_the_prior,
        }


def in_season_weight(gameweeks_played: int, config: InSeasonBlendConfig | None = None) -> float:
    """Return the share of the blend the season so far earns.

    Zero before a gameweek has been played, and approaching one as the season fills out.
    """

    settings = InSeasonBlendConfig() if config is None else config
    if isinstance(gameweeks_played, bool) or not isinstance(gameweeks_played, int):
        raise PredictionConfigurationError(
            f"gameweeks_played must be an integer, got {gameweeks_played!r}."
        )
    if gameweeks_played < 0:
        raise PredictionConfigurationError(
            f"gameweeks_played cannot be negative, got {gameweeks_played}."
        )
    played = float(gameweeks_played)
    return played / (played + float(settings.prior_gameweek_equivalent))


def in_season_rate_weight(
    played_minutes: pd.Series, config: InSeasonBlendConfig | None = None
) -> pd.Series:
    """Return how much each player's in-season scoring rate has earned, per player.

    Shrunk by minutes rather than by gameweeks, because minutes are the sample a rate is
    estimated from. Eight minutes is a gameweek's worth of appearances and almost nothing
    of a rate, and treating the two the same is how one substitute cameo becomes a
    season-best projection.
    """

    settings = InSeasonBlendConfig() if config is None else config
    minutes = played_minutes.astype("float64").fillna(0.0).clip(lower=0.0)
    return minutes / (minutes + float(settings.prior_minute_equivalent))


def _blend(current: pd.Series, carried: pd.Series, weight: pd.Series) -> pd.Series:
    """Combine a current-season term with a carried one at a per-player weight.

    Where only the carried side has a number it is the answer; where only the current side
    has one the result is left missing rather than taken at face value. That is the whole
    correction: a lone current-season observation has no prior to be shrunk toward here,
    so it is handled on the points scale by the caller, against the fallback price. Taking
    it at full weight is what made a single seventy-five-minute appearance out-project the
    best player in the game.
    """

    both = current.notna() & carried.notna()
    blended = pd.Series(float("nan"), index=current.index, dtype="float64")
    blended = blended.where(~both, weight * current + (1.0 - weight) * carried)
    return blended.where(~(~current.notna() & carried.notna()), carried)


def blend_in_season_projection(
    roster: pd.DataFrame,
    carried: pd.DataFrame,
    history: pd.DataFrame,
    fallback: pd.DataFrame,
    *,
    gameweeks_played: int,
    config: InSeasonBlendConfig | None = None,
) -> InSeasonBlend:
    """Project every rostered player for a gameweek in a season already under way.

    ``roster`` is the capture's deadline-known table, ``carried`` the completed-season
    record from :func:`squadopt.features.cross_season.carry_over_as_of`, ``history`` the
    season-to-date counters, and ``fallback`` an already-computed projection used only for
    players with neither record -- normally the opening control's own output, so the two
    paths price a player with no history identically by construction rather than by two
    copies of one rule agreeing.

    Every rostered player gets a number. A handoff that omits a player does not fail
    downstream; the live path reads a missing code as zero expected points, so the player
    is silently never selected and the check that looks like it covers this only fires for
    players that *were* selected. Coverage is therefore enforced here, at the only place
    that can see it.
    """

    settings = InSeasonBlendConfig() if config is None else config
    for name, frame in (("roster", roster), ("carried", carried), ("history", history)):
        if not isinstance(frame, pd.DataFrame):
            raise PredictionConfigurationError(f"{name} must be a pandas DataFrame.")
    if not isinstance(fallback, pd.DataFrame):
        raise PredictionConfigurationError("fallback must be a pandas DataFrame.")
    missing_roster = [column for column in _ROSTER_COLUMNS if column not in roster.columns]
    if missing_roster:
        raise PredictionConfigurationError(f"roster is missing columns: {missing_roster!r}.")
    if roster.empty:
        raise PredictionConfigurationError("roster must contain at least one player.")
    if roster["player_id"].duplicated().any():
        raise PredictionConfigurationError("roster repeats a player_id.")
    for name, frame, column in (
        ("history", history, "minutes"),
        ("history", history, "total_points"),
        ("fallback", fallback, "expected_points"),
    ):
        if column not in frame.columns:
            raise PredictionConfigurationError(f"{name} is missing the {column!r} column.")
    if gameweeks_played < 1:
        raise PredictionConfigurationError(
            "A started season has at least one played gameweek; "
            f"got {gameweeks_played}. The opening control projects gameweek one."
        )

    weight = in_season_weight(gameweeks_played, settings)
    merged = (
        roster.loc[:, list(_ROSTER_COLUMNS)]
        .merge(carried, on="player_id", how="left", validate="one_to_one")
        .merge(
            history.loc[:, ["player_id", "minutes", "total_points"]],
            on="player_id",
            how="left",
            validate="one_to_one",
        )
        .merge(
            fallback.loc[:, ["player_id", "expected_points"]].rename(
                columns={"expected_points": "fallback_expected_points"}
            ),
            on="player_id",
            how="left",
            validate="one_to_one",
        )
    )

    played_minutes = merged["minutes"].astype("float64")
    played_points = merged["total_points"].astype("float64")
    has_minutes = played_minutes.notna() & (played_minutes > 0.0)

    # A rate needs minutes to divide by; a player who has not played has no in-season
    # rate, which is different from having a rate of zero.
    current_rate = (played_points * MINUTES_PER_FULL_MATCH / played_minutes).where(has_minutes)
    # Minutes per gameweek is an observation for everyone whose counters are present,
    # including a zero: not playing is information about playing time, unlike scoring.
    current_minutes = (played_minutes / float(gameweeks_played)).where(played_minutes.notna())

    # Each stage is shrunk in the unit its own sample is measured in: the rate by minutes
    # played, the playing time by gameweeks elapsed.
    rate_weight = in_season_rate_weight(played_minutes, settings)
    minute_weight = pd.Series(weight, index=merged.index, dtype="float64")

    carried_rate = merged[PRIOR_RATE_COLUMN].astype("float64")
    carried_minutes = merged[PRIOR_MINUTES_COLUMN].astype("float64")
    blended_rate = _blend(current_rate, carried_rate, rate_weight)
    blended_minutes = _blend(current_minutes, carried_minutes, minute_weight)
    projected = blended_rate.mul(blended_minutes).div(MINUTES_PER_FULL_MATCH)

    fallback_points = merged["fallback_expected_points"].astype("float64")

    # A player with in-season minutes but no carried record has evidence and no two-stage
    # prior to shrink it against, so the shrinkage happens on the points scale instead,
    # toward the same price prior the opening control gives exactly these players. At the
    # same rate weight, so one appearance moves the answer by what one appearance is worth.
    unpriored = projected.isna() & has_minutes & fallback_points.notna()
    from_in_season_alone = current_rate.mul(current_minutes).div(MINUTES_PER_FULL_MATCH)
    shrunk = rate_weight * from_in_season_alone + (1.0 - rate_weight) * fallback_points
    projected = projected.where(~unpriored, shrunk)

    unpriced = projected.isna() & fallback_points.isna()
    if unpriced.any():
        codes = merged.loc[unpriced, "player_id"].tolist()
        raise PredictionConfigurationError(
            "No projection and no fallback price for "
            f"{format_examples(codes)}; every rostered player must carry a number, "
            "because a handoff that omits one is read downstream as zero."
        )
    expected = projected.where(projected.notna(), fallback_points).clip(lower=0.0)
    non_finite = [value for value in expected.tolist() if not math.isfinite(float(value))]
    if non_finite:
        raise PredictionConfigurationError(
            f"In-season projections contain non-finite values: {format_examples(non_finite)}."
        )

    table = merged.loc[:, list(_ROSTER_COLUMNS)].copy(deep=True)
    table["expected_points"] = expected.astype("float64")
    table = table.sort_values("player_id", kind="stable").reset_index(drop=True)

    from_prior = int(projected.isna().sum())
    with_minutes = int(has_minutes.sum())
    shrunk_against_price = int(unpriored.sum())
    two_stage = with_minutes - shrunk_against_price
    return InSeasonBlend(
        table=table,
        gameweeks_played=gameweeks_played,
        in_season_weight=weight,
        players=len(table),
        players_with_in_season_minutes=with_minutes,
        players_blended_two_stage=two_stage,
        players_shrunk_against_the_price_prior=shrunk_against_price,
        players_from_carry_over_only=len(table) - with_minutes - from_prior,
        players_priced_from_the_prior=from_prior,
    )
