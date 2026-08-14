"""Turn a captured deadline snapshot into a squad recommendation.

Two modes, and the difference between them is the whole point. **Live** resolves the next
deadline that has not closed and recommends for it. **Replay** rebuilds a past
recommendation from a stored snapshot and must return exactly what it returned then —
which is only possible because the capture is immutable and every input is either in it or
pinned.

The projection comes from the **operational control**, the deterministic baseline, and not
from the production candidate. The candidate was measured against the pre-registered gates
and did not clear them, so it is not what decides a real squad. That is not a formality:
recommending from an unpromoted model would make the gates decorative.

Availability is applied after the projection as an explicit multiplier, never as a model
input, because a live capture can prove it preceded the deadline and the archive cannot.
Every adjustment it makes is reported.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    GameweekDeadline,
    availability_snapshot,
    gameweek_deadlines,
    next_open_deadline,
    player_snapshot,
)
from squadopt.data.timestamps import as_instant
from squadopt.features.cross_season import CrossSeasonConfig
from squadopt.prediction.availability import (
    AvailabilityRuleConfig,
    apply_availability,
)
from squadopt.prediction.config import BaselineProjectionConfig
from squadopt.prediction.opening import build_opening_projection_from_snapshot

# Named so a report cannot describe itself as coming from a model that was never promoted.
CONTROL_MODEL_NAME: Final = "squadopt-deterministic-baseline"
CONTROL_MODEL_VERSION: Final = "opening-carry-over-v1"
OPENING_FEATURE_CONTRACT_VERSION: Final = "opening-carry-over-features-v1"

# What the projection can answer today. The opening path carries a completed season into a
# season with no played gameweeks; a later gameweek needs the current season's own history,
# which no live source in this project captures yet.
SUPPORTED_TARGET_GAMEWEEK: Final = 1


def infer_season(snapshot: CapturedSnapshot) -> str:
    """Name the season a capture describes, from its own published deadlines.

    A season is named for the calendar year it starts in, and its first deadline falls in
    that year, so the earliest published deadline settles it. Deriving it beats asking the
    caller: a season passed by hand can be wrong, and a capture filed under the wrong
    season would join the wrong history.
    """

    bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if bootstrap is None:
        raise DataSourceError(
            f"Snapshot {snapshot.metadata.snapshot_id!r} carries no {BOOTSTRAP_PAYLOAD!r} "
            "payload, so its season cannot be determined."
        )
    deadlines = gameweek_deadlines(bootstrap)
    earliest = min(deadlines, key=lambda entry: entry.gameweek)
    start = as_instant(earliest.deadline_utc).year
    return f"{start}-{(start + 1) % 100:02d}"


@dataclass(frozen=True, slots=True)
class RecommendationInputs:
    """Everything read out of a capture, before any projection is made."""

    snapshot_id: str
    captured_at_utc: str
    season: str
    deadline: GameweekDeadline
    players: pd.DataFrame
    availability: pd.DataFrame


@dataclass(frozen=True, slots=True)
class Projection:
    """A projection with the route it took and what availability did to it."""

    table: pd.DataFrame
    unavailable_players: tuple[int, ...]
    diagnostics: Mapping[str, object]


def read_inputs(
    snapshot: CapturedSnapshot,
    *,
    season: str,
    gameweek: int | None = None,
) -> RecommendationInputs:
    """Read the roster, the availability and the target deadline out of one capture.

    ``gameweek`` names a target explicitly, which is what replay does. Left out, the
    target is the earliest deadline that had not closed when the capture was taken —
    resolved from the capture's own instant rather than from the clock now, so replaying
    an old capture asks the question that capture was taken to answer.
    """

    bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if bootstrap is None:
        raise DataSourceError(
            f"Snapshot {snapshot.metadata.snapshot_id!r} carries no {BOOTSTRAP_PAYLOAD!r} "
            "payload, so it cannot describe a roster."
        )

    deadlines = gameweek_deadlines(bootstrap)
    if gameweek is None:
        deadline = next_open_deadline(deadlines, as_of_utc=snapshot.metadata.captured_at_utc)
    else:
        matched = [entry for entry in deadlines if entry.gameweek == gameweek]
        if not matched:
            published = sorted(entry.gameweek for entry in deadlines)
            raise DataSourceError(
                f"Snapshot {snapshot.metadata.snapshot_id!r} publishes no gameweek "
                f"{gameweek}; it carries {published[:5]!r} through {published[-1:]!r}."
            )
        deadline = matched[0]

    return RecommendationInputs(
        snapshot_id=snapshot.metadata.snapshot_id,
        captured_at_utc=snapshot.metadata.captured_at_utc,
        season=season,
        deadline=deadline,
        players=player_snapshot(bootstrap),
        availability=availability_snapshot(bootstrap),
    )


def project(
    inputs: RecommendationInputs,
    panel: pd.DataFrame,
    *,
    projection_config: BaselineProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
    availability_config: AvailabilityRuleConfig | None = None,
) -> Projection:
    """Project the captured roster with the operational control, then apply availability.

    Only an opening gameweek is supported. A later gameweek would need the current
    season's played history, and the archive publishes a gameweek only after it has been
    played, so there is nothing to read at a mid-season deadline. Refusing is the honest
    answer; projecting from carry-over alone in gameweek twenty would silently ignore
    everything that had happened that season.
    """

    if inputs.deadline.gameweek != SUPPORTED_TARGET_GAMEWEEK:
        raise DataSourceError(
            f"Gameweek {inputs.deadline.gameweek} needs the current season's played "
            "history, which no captured source provides yet. Only the opening gameweek "
            "can be recommended from a capture plus completed seasons."
        )

    table = build_opening_projection_from_snapshot(
        panel,
        inputs.players,
        season=inputs.season,
        config=projection_config,
        cross_season=cross_season,
    )
    adjusted = apply_availability(table, inputs.availability, config=availability_config)

    projected = adjusted.table
    carried = int(projected["has_prior_record"].sum())
    return Projection(
        table=projected,
        unavailable_players=adjusted.unavailable_players,
        diagnostics={
            **dict(adjusted.diagnostics),
            "players": len(projected),
            "players_with_prior_record": carried,
            "players_priced_from_prior": len(projected) - carried,
            "model_name": CONTROL_MODEL_NAME,
            "model_version": CONTROL_MODEL_VERSION,
            "feature_contract_version": OPENING_FEATURE_CONTRACT_VERSION,
            "projection_source": "operational_control",
        },
    )
