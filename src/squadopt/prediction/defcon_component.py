"""Fixed fixture-appearance DEFCON arithmetic for the proposed #1000 component.

This module fits only the declared 2026-27 event-rate counts. It reads no file,
trains no base estimator and promotes no version. The reading command must verify
the merged declaration before supplying real inputs.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from squadopt.data.timestamps import as_instant

DEFCON_COMPONENT_CONTRACT_VERSION = "defcon_augmentation_2026_v1"
DEFCON_PRIOR_APPEARANCES = 20
DEFCON_SEASON = "2026-27"
DEFCON_CANDIDATE_VERSIONS = MappingProxyType(
    {
        "phase_c_control_components_v1": "phase_c_control_components_defcon_2026_v1",
        "phase-c-component-elite-top100-v1": "phase-c-component-elite-top100-defcon-2026-v1",
    }
)
POSITIONS = frozenset(("GK", "DEF", "MID", "FWD"))


class DefconComponentError(ValueError):
    """The fixed component cannot be computed from these inputs."""


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DefconComponentError(f"{label} must be an integer at least {minimum}.")
    return value


@dataclass(frozen=True, slots=True)
class FixtureAppearance:
    season: str
    gameweek: int
    fixture: int
    player_code: int
    position: str
    kickoff_utc: str
    minutes: int
    awarded_points: int


@dataclass(frozen=True, slots=True)
class DefconRates:
    player_appearances: Mapping[int, int]
    player_awards: Mapping[int, int]
    position_appearances: Mapping[str, int]
    position_awards: Mapping[str, int]

    def __post_init__(self) -> None:
        for name in (
            "player_appearances",
            "player_awards",
            "position_appearances",
            "position_awards",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def rate(self, player_code: int, position: str) -> float:
        if position == "GK":
            return 0.0
        appearances = self.position_appearances.get(position, 0)
        if appearances <= 0:
            raise DefconComponentError("A required position has no prior fixture appearances.")
        prior = self.position_awards.get(position, 0) / appearances
        return (self.player_awards.get(player_code, 0) + DEFCON_PRIOR_APPEARANCES * prior) / (
            self.player_appearances.get(player_code, 0) + DEFCON_PRIOR_APPEARANCES
        )

    def document(self) -> dict[str, object]:
        return {
            "prior_fixture_appearances": DEFCON_PRIOR_APPEARANCES,
            "player_appearances": {
                str(key): value for key, value in self.player_appearances.items()
            },
            "player_awards": {str(key): value for key, value in self.player_awards.items()},
            "position_appearances": dict(self.position_appearances),
            "position_awards": dict(self.position_awards),
        }


def fit_defcon_rates(
    rows: Sequence[FixtureAppearance],
    *,
    target_gameweek: int,
    deadline_utc: str,
    award_points: Mapping[str, int],
    required_positions: frozenset[str],
) -> DefconRates:
    """Count prior fixture appearances; doubles contribute two actual observations."""
    _integer(target_gameweek, "target gameweek", minimum=1)
    deadline = as_instant(deadline_utc)
    if not required_positions.issubset(POSITIONS - {"GK"}):
        raise DefconComponentError("Required positions must be DEF, MID or FWD.")
    for position in POSITIONS:
        _integer(award_points.get(position), "captured position award")
    player_a: Counter[int] = Counter()
    player_b: Counter[int] = Counter()
    position_a: Counter[str] = Counter()
    position_b: Counter[str] = Counter()
    seen: set[tuple[int, int]] = set()
    for row in rows:
        # Season and cutoff checks precede using any label or count.
        if row.season != DEFCON_SEASON:
            raise DefconComponentError("Only 2026-27 fit rows are admitted; 2025-26 is forbidden.")
        _integer(row.gameweek, "fit gameweek", minimum=1)
        if not 1 <= row.gameweek < target_gameweek or as_instant(row.kickoff_utc) >= deadline:
            raise DefconComponentError("Fit rows must precede the target deadline and gameweek.")
        _integer(row.fixture, "fixture", minimum=1)
        _integer(row.player_code, "player code", minimum=1)
        _integer(row.minutes, "fixture minutes")
        _integer(row.awarded_points, "awarded points")
        if row.position not in POSITIONS:
            raise DefconComponentError("A fit row has an unknown position.")
        if row.awarded_points not in (0, award_points[row.position]):
            raise DefconComponentError("A fit award differs from the captured position award.")
        key = (row.player_code, row.fixture)
        if key in seen:
            raise DefconComponentError("A player-fixture fit row is duplicated.")
        seen.add(key)
        if row.position == "GK" or row.minutes == 0:
            continue
        player_a[row.player_code] += 1
        position_a[row.position] += 1
        if row.awarded_points > 0:
            player_b[row.player_code] += 1
            position_b[row.position] += 1
    if any(position_a[position] == 0 for position in required_positions):
        raise DefconComponentError("A required position has no prior fixture appearances.")
    return DefconRates(player_a, player_b, position_a, position_b)


def expected_defcon_term(
    *,
    player_code: int,
    position: str,
    appearance_probability: float | None,
    fixture_count: int,
    award_points: int,
    rates: DefconRates,
) -> float:
    """The published appearance estimate is used unchanged once per fixture."""
    _integer(fixture_count, "fixture count")
    _integer(award_points, "position award")
    if position not in POSITIONS:
        raise DefconComponentError("The target row has an unknown position.")
    if position == "GK" or fixture_count == 0:
        return 0.0
    if appearance_probability is None:
        return 0.0
    if (
        isinstance(appearance_probability, bool)
        or not math.isfinite(appearance_probability)
        or not 0.0 <= appearance_probability <= 1.0
    ):
        raise DefconComponentError("A nonblank target needs its published appearance estimate.")
    return fixture_count * appearance_probability * rates.rate(player_code, position) * award_points
