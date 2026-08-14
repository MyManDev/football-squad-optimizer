"""Apply captured availability to a projection, as a rule rather than as a feature.

This is the asymmetry the prediction layer is built around. Historical availability
cannot be learned from: the archive records a player's status after the fact and its
as-of time cannot be recovered, so any coefficient fitted on it would rest on
information nobody held at the deadline. Live availability is different only because we
captured it ourselves, at an instant we stamped, before the deadline it applies to.

So it never enters a model matrix. It is applied afterwards, as an explicit and
inspectable multiplier, and every adjustment it makes is reported. A projection that was
quietly halved is indistinguishable from a model that predicted half as much, and those
are different claims.

The status vocabulary is undocumented, so it is declared here from what the source was
observed to publish and an unrecognised status stops the run. That is deliberate: the
alternative is to guess, and a wrong guess about the meaning of the most common status
would misprice the entire roster at once. A capture is normally inspected with a dry run
before a deadline, which is where such a change should surface.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.prediction.config import PredictionConfigurationError

# Observed in the 2026-27 pre-season capture across 584 squad-eligible players:
# `a` 514, `i` 35, `u` 18, `d` 14, `s` 3.
STATUS_AVAILABLE: Final = "a"
STATUS_DOUBTFUL: Final = "d"

# Statuses that mean a player cannot be selected. `n` is included although it was not
# observed in that capture: the platform uses it for a player who is not in the squad,
# and treating an absent-from-squad player as available would be plainly wrong.
UNAVAILABLE_STATUSES: Final = ("i", "s", "u", "n")

KNOWN_STATUSES: Final = (STATUS_AVAILABLE, STATUS_DOUBTFUL, *UNAVAILABLE_STATUSES)

# The source states a chance of playing as a whole percentage, quantised in practice to
# 0, 25, 50, 75 and 100.
FULL_CHANCE: Final = 100


@dataclass(frozen=True, slots=True)
class AvailabilityRuleConfig:
    """Controls for how captured availability adjusts a projection.

    ``unknown_is_available`` decides what an absent availability record means. It
    defaults to treating the player as available, because absence of news is the normal
    state for the large majority of a roster and treating silence as doubt would
    penalise every unremarkable player.

    ``doubtful_multiplier_floor`` bounds how far a stated chance can reduce a
    projection. It exists so that a stated chance of zero on a player the source still
    lists as available cannot be read as a certainty; set it to zero to let a stated
    chance speak for itself.
    """

    unknown_is_available: bool = True
    doubtful_multiplier_floor: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.unknown_is_available, bool):
            raise PredictionConfigurationError("unknown_is_available must be a boolean.")
        if isinstance(self.doubtful_multiplier_floor, bool) or not isinstance(
            self.doubtful_multiplier_floor, Real
        ):
            raise PredictionConfigurationError(
                "doubtful_multiplier_floor must be a number, got "
                f"{self.doubtful_multiplier_floor!r}."
            )
        floor = float(self.doubtful_multiplier_floor)
        if not math.isfinite(floor) or not 0.0 <= floor <= 1.0:
            raise PredictionConfigurationError(
                f"doubtful_multiplier_floor must be within [0, 1], got {floor!r}."
            )
        object.__setattr__(self, "doubtful_multiplier_floor", floor)


@dataclass(frozen=True, slots=True)
class AvailabilityAdjustment:
    """A projection after availability, with everything the rule did to it.

    ``unavailable_players`` lists whom the rule reduced to zero. They are reported
    rather than removed: pool membership is a decision-layer concern, and dropping rows
    here could turn a squad problem infeasible for reasons the decision layer never
    sees.
    """

    table: pd.DataFrame
    multiplier: pd.Series
    unavailable_players: tuple[int, ...]
    diagnostics: Mapping[str, object]


def _require_frame(value: object, label: str, columns: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise PredictionConfigurationError(f"{label} must be a pandas DataFrame.")
    missing = [column for column in columns if column not in value.columns]
    if missing:
        raise PredictionConfigurationError(
            f"{label} is missing columns {missing!r}; it carries "
            f"{sorted(map(str, value.columns))!r}."
        )
    return value


def _status_multiplier(status: str, config: AvailabilityRuleConfig) -> float:
    if status == STATUS_AVAILABLE:
        return 1.0
    if status in UNAVAILABLE_STATUSES:
        return 0.0
    if status == STATUS_DOUBTFUL:
        # Doubtful with no stated chance: the source is signalling uncertainty without
        # quantifying it. Half is the only neutral reading of "we do not know".
        return 0.5
    raise PredictionConfigurationError(
        f"Availability status {status!r} is not one of {list(KNOWN_STATUSES)!r}. The "
        "source does not document this field, so an unrecognised value stops the run "
        "rather than being guessed — a wrong guess about the most common status would "
        "misprice the whole roster."
    )


def apply_availability(
    projection: pd.DataFrame,
    availability: pd.DataFrame,
    *,
    config: AvailabilityRuleConfig | None = None,
) -> AvailabilityAdjustment:
    """Scale a projection by what the capture says about who can play.

    A stated chance of playing takes precedence over the status, because it is the more
    specific claim: the source publishes it exactly when it has something quantitative
    to say. Where no chance is stated the status decides, and where neither is present
    the player is treated as available.

    Returns an independent copy; the inputs are never modified.
    """

    settings = AvailabilityRuleConfig() if config is None else config
    if not isinstance(settings, AvailabilityRuleConfig):
        raise PredictionConfigurationError("config must be an AvailabilityRuleConfig.")

    _require_frame(projection, "Projection table", ("player_id", "expected_points"))
    _require_frame(availability, "Availability table", ("player_id", "status", "chance_of_playing"))

    duplicated = availability.loc[availability["player_id"].duplicated(), "player_id"].tolist()
    if duplicated:
        raise PredictionConfigurationError(f"Availability table repeats player_id {duplicated!r}.")

    table = projection.copy(deep=True)
    joined = table.merge(
        availability.loc[:, ["player_id", "status", "chance_of_playing"]],
        on="player_id",
        how="left",
        validate="many_to_one",
    )

    stated = pd.to_numeric(joined["chance_of_playing"], errors="coerce").astype("float64")
    from_chance = stated.div(float(FULL_CHANCE))

    default = 1.0 if settings.unknown_is_available else 0.0
    from_status = pd.Series(default, index=joined.index, dtype="float64")
    known = joined["status"].notna()
    if bool(known.any()):
        from_status = from_status.mask(
            known,
            joined.loc[known, "status"]
            .astype("string")
            .map(lambda value: _status_multiplier(str(value), settings)),
        )

    multiplier = from_chance.where(stated.notna(), from_status)
    multiplier = multiplier.clip(lower=settings.doubtful_multiplier_floor, upper=1.0)

    points = pd.to_numeric(table["expected_points"], errors="coerce").astype("float64")
    if bool(points.isna().any()):
        raise PredictionConfigurationError(
            "expected_points must be present for every projected player before "
            "availability is applied."
        )
    table["expected_points"] = points.mul(multiplier.to_numpy()).clip(lower=0.0)

    unavailable = tuple(
        int(value) for value in table.loc[multiplier.to_numpy() <= 0.0, "player_id"].tolist()
    )
    reduced = int(((multiplier > 0.0) & (multiplier < 1.0)).sum())

    return AvailabilityAdjustment(
        table=table,
        multiplier=multiplier.astype("float64"),
        unavailable_players=unavailable,
        diagnostics=MappingProxyType(
            {
                "availability_players_matched": int(known.sum()),
                "availability_players_unmatched": int((~known).sum()),
                "availability_chance_stated": int(stated.notna().sum()),
                "availability_unavailable": len(unavailable),
                "availability_reduced": reduced,
                "availability_unknown_is_available": settings.unknown_is_available,
                "availability_multiplier_floor": settings.doubtful_multiplier_floor,
            }
        ),
    )
