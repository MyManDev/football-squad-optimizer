"""Capture-bound availability information for the experimental window consumer.

This is a declared one-deadline information experiment, not a recovery model. Only
explicit source percentages are eligible. Rotation and conditional minutes stay in
the existing prediction. Contextual team shares cannot be inverted from weekly totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from squadopt.planning.models import InitialSquadState, PlanningHorizon
from squadopt.planning.recourse import ObservationNode
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, JOINT_ROLE_MODEL_VERSIONS
from squadopt.prediction.football_team_form import TEAM_FORM_MODEL_VERSION

AVAILABILITY_OBSERVATION_VERSION = "captured_next_deadline_resolution_v1"


@dataclass(frozen=True)
class AvailabilityObservations:
    nodes: tuple[ObservationNode, ...]
    reason: str
    source_snapshot_id: str
    captured_at_utc: str
    player_id: int | None = None
    stated_probability: float | None = None
    information_gameweek: int | None = None
    contract_version: str = AVAILABILITY_OBSERVATION_VERSION


def availability_observations(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    availability: pd.DataFrame,
    *,
    model_version: str,
    source_snapshot_id: str,
    captured_at_utc: str,
    deadline_utc: str,
) -> AvailabilityObservations:
    """Resolve one held player's stated eligibility before the second decision.

    Both posterior horizons average exactly to the original forecast. The percentage
    was already applied upstream; dividing that factor out on the eligible branch
    preserves conditional minutes rather than multiplying availability a second time.
    Only the next week changes. Later recovery dates are neither known nor invented.
    Choosing one held uncertainty bounds the action menu without correlating unrelated
    injuries. Blank weeks contribute no information value and are skipped.
    """

    def result(reason: str) -> AvailabilityObservations:
        return AvailabilityObservations((), reason, source_snapshot_id, captured_at_utc)

    captured = datetime.fromisoformat(captured_at_utc.replace("Z", "+00:00"))
    deadline = datetime.fromisoformat(deadline_utc.replace("Z", "+00:00"))
    if (
        not source_snapshot_id
        or captured.tzinfo is None
        or deadline.tzinfo is None
        or captured > deadline
    ):
        raise ValueError(
            "Availability information must be capture-bound and known before deadline."
        )
    # These models allocate fixture components before the reader applies captured
    # eligibility to weekly E and q. Invert only that external multiplier: the
    # fitted start/cameo/minute law remains inside the conditional forecast. The
    # contextual model reallocates team shares after availability and is not invertible
    # from weekly totals. A current-week minute intervention is also preserved:
    # the two nodes start next week and never replace the decided week's forecast.
    if model_version not in (
        FOOTBALL_MODEL_VERSION,
        *JOINT_ROLE_MODEL_VERSIONS,
        TEAM_FORM_MODEL_VERSION,
    ):
        return result("conditional_team_components_unavailable")
    if len(horizon.gameweeks) not in (3, 5):
        return result("unsupported_window")
    if "appearance_probability" not in horizon.table:
        return result("appearance_forecast_unavailable")
    if not {"player_id", "chance_of_playing"}.issubset(availability.columns):
        return result("stated_chance_unavailable")
    if availability.player_id.duplicated().any():
        raise ValueError("Availability information repeats a player.")
    stated = pd.to_numeric(availability.set_index("player_id").chance_of_playing, errors="coerce")
    future_week = horizon.gameweeks[1]
    rows = horizon.table.loc[
        horizon.table.gameweek.eq(future_week)
        & horizon.table.player_id.isin(initial.squad_player_ids)
    ].copy()
    rows["eligibility"] = rows.player_id.map(stated) / 100
    rows = rows.loc[rows.eligibility.isin((0.25, 0.5, 0.75)) & rows.expected_points.gt(0)]
    # A conditional appearance probability over one means the forecast was not scaled
    # by this source probability. Reject the inversion, including a mismatched producer.
    rows = rows.loc[rows.appearance_probability.le(rows.eligibility + 1e-10)]
    if rows.empty:
        return result("no_usable_held_uncertainty")
    rows["exposure"] = rows.expected_points * (1 - rows.eligibility)
    row = rows.sort_values(["exposure", "player_id"], ascending=[False, True]).iloc[0]
    player = int(row.player_id)
    probability = float(row.eligibility)
    future = horizon.table.loc[horizon.table.gameweek.ne(horizon.gameweeks[0])].copy()
    target = future.gameweek.eq(future_week) & future.player_id.eq(player)
    yes, no = future.copy(), future.copy()
    for column in ("expected_points", "appearance_probability"):
        yes.loc[target, column] /= probability
        no.loc[target, column] = 0.0
    yes["appearance_probability"] = yes.appearance_probability.clip(0, 1)
    return AvailabilityObservations(
        (
            ObservationNode("eligible", probability, PlanningHorizon(yes)),
            ObservationNode("unavailable", 1 - probability, PlanningHorizon(no)),
        ),
        "captured_eligibility_resolves_next_deadline",
        source_snapshot_id,
        captured_at_utc,
        player,
        probability,
        future_week,
    )
