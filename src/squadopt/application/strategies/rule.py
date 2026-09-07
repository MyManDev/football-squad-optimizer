"""The strategy rule: which of the three computable strategies a member plays this week.

One question, answered by a rule that is **written down** rather than learned from
anything: given how far behind or ahead a member is against their rival, and how many
gameweeks are left, which of ``saf-puan``, ``ortak-koru`` and ``fark-yarat`` does the
member play? The answer is a band on the gap, and nothing else enters it.

The shape follows from the arithmetic of the constraints the catalogue already
declares, not from any measurement of what wins:

- Players both squads hold cancel from the *difference* of the two scores. A member who
  mirrors their rival therefore keeps whatever gap they already have — which is exactly
  what a member who is **ahead** wants, and exactly what a member who is **behind**
  cannot afford. ``ortak-koru`` (overlap floor nine) is the mirroring constraint;
  ``fark-yarat`` (overlap ceiling five) is its opposite.
- ``saf-puan`` is the unconstrained pick. Both rival-relative constraints cost expected
  points — the catalogue prices that cost on every advice file — so the rule spends it
  only outside the band, and says ``saf-puan`` whenever the gap is small next to the
  weeks still to be played.

**Where the band edges come from.** They are not invented constants. They are written in
units of ``WEEKLY_POINTS_DIFFERENTIAL_POINTS`` — the measured week-to-week points
difference between two members of this league — multiplied by the square root of the
gameweeks remaining, because a difference accumulated over ``w`` weeks carries ``w``
weeks of that week-to-week movement. The edge therefore widens with a long season left
and closes as the season runs out: a gap the band absorbs in September falls outside it
in May. That is the whole statement — a band on points, never a chance of anything.

**What this rule is not.** Nothing here has been measured. No bench has compared a member
who follows it against a member who ignores it; all three strategies still stand at
``EvidenceStatus.PREREG_OPEN`` in the catalogue. It is a declared rule awaiting
measurement, published as a suggestion the member is free to ignore, and its identifier
and version travel in every payload it reaches so a later measurement can name exactly
which rule it measured.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from squadopt.application.strategies.catalog import StrategyConfigurationError

#: This rule, by name and version — the provenance stamp that travels in the payload,
#: in the style of ``MEMBER_PLANNING_POLICY_ID``. A change to any number below is a new
#: version, so a measurement can never be attributed to a rule it did not run against.
STRATEGY_RULE_ID: Final = "gap_and_weeks_strategy_rule_v1"

#: The measured scale the bands are written in: the standard deviation, in points, of
#: the week-to-week score difference between two members of this league.
#:
#: Provenance: entry histories in the real capture
#: ``fpl-live-20260907T131414Z-db9314d00961`` (league 352490, the 2026-27 season through
#: gameweek 3). For every gameweek and every unordered pair of the fifteen members, the
#: difference of their gameweek scores net of transfer hits — 105 pairs x 3 gameweeks =
#: 315 pair-weeks, taken with both signs so the mean is zero by construction. The
#: historical archive under ``data/raw/vaastav-fpl`` could not extend this: it carries
#: per-player gameweek rows only and holds no manager entries at all, so no comparable
#: manager-level weekly total can be built from it. Three gameweeks is a thin sample and
#: this number is expected to move; it is a measurement to be repeated, not a constant of
#: nature, which is why the rule's version is stamped beside it.
WEEKLY_POINTS_DIFFERENTIAL_POINTS: Final = 21.2

#: The last gameweek of a Premier League season; the weeks-remaining count runs to it.
SEASON_FINAL_GAMEWEEK: Final = 38

#: The band edge, in units of the measured differential: a member is "behind" once the
#: gap exceeds one differential's worth of the remaining season, and "ahead" once the
#: lead does. The two sides use the same multiple by declaration — an asymmetry would be
#: a claim about which side of a gap is harder to hold, and nothing has measured that.
BAND_EDGE_DIFFERENTIALS: Final = 1.0

#: The strategies the rule chooses between: the catalogue's computable three.
RULE_STRATEGIES: Final[tuple[str, ...]] = ("saf-puan", "ortak-koru", "fark-yarat")

#: The two of them that need a rival to be stated at all. A caller that has not computed
#: both cannot honestly carry a suggestion, because the rule may name either.
RIVAL_RULE_STRATEGIES: Final[tuple[str, ...]] = ("ortak-koru", "fark-yarat")


class GapBand(StrEnum):
    """Which side of the band the member's gap falls on."""

    BEHIND = "behind"
    LEVEL = "level"
    AHEAD = "ahead"


@dataclass(frozen=True, slots=True)
class StrategySuggestion:
    """One member's suggested strategy, with everything needed to re-check the rule.

    The payload carries the rule's inputs — the signed gap and the gameweeks remaining —
    and the band edge those inputs were compared against, so a reader can apply the rule
    themselves rather than take the answer on trust.
    """

    strategy: str
    band: GapBand
    rival_entry_id: int
    points_ahead_of_rival: int
    scored_gameweek: int
    gameweeks_remaining: int
    band_edge_points: float
    rule_id: str = STRATEGY_RULE_ID

    def to_dict(self) -> dict[str, object]:
        """The published shape. No field here reads as a chance of anything."""

        return {
            "strategy": self.strategy,
            "rule_id": self.rule_id,
            "band": str(self.band),
            "rival_entry_id": int(self.rival_entry_id),
            "points_ahead_of_rival": int(self.points_ahead_of_rival),
            "scored_gameweek": int(self.scored_gameweek),
            "gameweeks_remaining": int(self.gameweeks_remaining),
            "band_edge_points": float(self.band_edge_points),
        }


def gameweeks_remaining(gameweek: int) -> int:
    """How many gameweeks are still to be played, counting the one being decided."""

    if isinstance(gameweek, bool) or not isinstance(gameweek, int):
        raise StrategyConfigurationError("gameweek must be an integer.")
    return max(0, SEASON_FINAL_GAMEWEEK - gameweek + 1)


def band_edge_points(weeks_remaining: int) -> float:
    """The band edge in points for a season with ``weeks_remaining`` gameweeks left.

    One measured week-to-week differential, carried over the weeks still to be played.
    Rounded to a tenth of a point so the published number reads as the declared quantity
    it is rather than as a float's last bits.
    """

    if isinstance(weeks_remaining, bool) or not isinstance(weeks_remaining, int):
        raise StrategyConfigurationError("weeks_remaining must be an integer.")
    if weeks_remaining < 0:
        raise StrategyConfigurationError("weeks_remaining must not be negative.")
    edge = BAND_EDGE_DIFFERENTIALS * WEEKLY_POINTS_DIFFERENTIAL_POINTS * math.sqrt(weeks_remaining)
    return round(edge, 1)


def suggest_strategy(
    *,
    rival_entry_id: int,
    points_ahead_of_rival: int,
    gameweek: int,
    scored_gameweek: int,
) -> StrategySuggestion:
    """Apply the rule: the gap against the rival, the weeks left, one of three slugs.

    ``points_ahead_of_rival`` is signed — the member's league total minus the rival's,
    negative when the member is behind — and belongs to ``scored_gameweek``, the last
    week both totals are proven for. ``gameweek`` is the week being decided.
    """

    for name, value in (
        ("rival_entry_id", rival_entry_id),
        ("points_ahead_of_rival", points_ahead_of_rival),
        ("gameweek", gameweek),
        ("scored_gameweek", scored_gameweek),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise StrategyConfigurationError(f"{name} must be an integer.")
    weeks = gameweeks_remaining(gameweek)
    edge = band_edge_points(weeks)
    if points_ahead_of_rival < -edge:
        band, chosen = GapBand.BEHIND, "fark-yarat"
    elif points_ahead_of_rival > edge:
        band, chosen = GapBand.AHEAD, "ortak-koru"
    else:
        band, chosen = GapBand.LEVEL, "saf-puan"
    return StrategySuggestion(
        strategy=chosen,
        band=band,
        rival_entry_id=int(rival_entry_id),
        points_ahead_of_rival=int(points_ahead_of_rival),
        scored_gameweek=int(scored_gameweek),
        gameweeks_remaining=weeks,
        band_edge_points=edge,
    )
