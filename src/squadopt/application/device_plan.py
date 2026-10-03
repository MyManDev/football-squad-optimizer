"""What a member's one-week plan needs, published so the member's own device can solve it.

The advice backend runs on one machine. The shared part of every answer, the projection
table for the capture, is produced once; the per-member part is one optimisation over it.
This module publishes exactly the inputs the live path hands its own solver, so that a page
on the member's device can state the same problem and return the same answer:

- ``device_plan_table``: the capture's table in the order the solver sees it, with the
  server's own integer objective coefficients, and the season's rules and the member
  planning policy as numbers. One document per publication.
- ``device_plan_entry``: one member's fifteen, the bank after the spending-power rule, the
  free transfers under the cap, and the sale price of each held player. One block per
  entry document, or ``None`` when the live path would refuse to plan for that member.

Nothing here solves anything. The solve on the device restates the one-week model and is
held to the server's answer by a parity test; the numbers published here are the numbers
the server uses, not a description of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from squadopt.contracts.players import sort_players_by_id
from squadopt.data.errors import DataSourceError
from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.live.rules import SeasonRules
from squadopt.live.transfers import (
    MEMBER_PLANNING_POLICY_ID,
    HeldSquad,
    MemberPlanningInputs,
    member_planning_inputs,
    member_planning_policy,
)
from squadopt.optimization import OptimizationConfig
from squadopt.optimization.coefficients import objective_coefficients, scale_expected_points

DEVICE_PLAN_CONTRACT_VERSION: Final = "league_device_plan_v1"
DEVICE_PLAN_DOCUMENT: Final = "device-plan.json"


def device_plan_table(
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    optimization: OptimizationConfig | None = None,
) -> dict[str, object]:
    """The capture's table and rules, as the member path's solver receives them.

    The players are sorted by id, the order the planner sorts its own table into before
    it solves: the server breaks ties between equal plans by rank in that order, and a
    device that reorders the table would resolve the same tie differently.

    A sale price is published for the held fifteen only; the planner fills a non-held
    player's with the buy price, which the one-week answer never uses since a player not
    held cannot be sold. No per-week transfer cap applies under the member policy.
    """

    settings = OptimizationConfig() if optimization is None else optimization
    table = sort_players_by_id(
        projection.table.loc[
            :, ["player_id", "name", "team_id", "position", "price_tenths", "expected_points"]
        ]
    )
    coefficients = objective_coefficients(table["expected_points"].tolist(), settings)
    policy = member_planning_policy(rules)
    return {
        "contract_version": DEVICE_PLAN_CONTRACT_VERSION,
        "league_id": int(league_id),
        "season": str(inputs.season),
        "gameweek": int(inputs.deadline.gameweek),
        "source_snapshot_id": str(inputs.snapshot_id),
        "policy_id": MEMBER_PLANNING_POLICY_ID,
        "rules": {
            "squad_size": settings.squad_size,
            "starting_size": settings.starting_size,
            "squad_position_limits": dict(settings.squad_position_limits),
            "starting_position_min": dict(settings.starting_position_min),
            "starting_position_max": dict(settings.starting_position_max),
            "max_players_per_team": settings.max_players_per_team,
            "max_free_transfers": policy.max_free_transfers,
            # The planner's caution margin per paid transfer, scaled as the planner scales
            # it, so the device's objective and the server's are one integer.
            "hit_cost_scaled": scale_expected_points(
                policy.transfer_hit_cost_points, settings.expected_points_scale
            ),
            # What the game charges per paid transfer, the number the page shows.
            "hit_points_charged": float(policy.hit_points_charged),
            "expected_points_scale": settings.expected_points_scale,
        },
        "players": [
            {
                "id": int(str(row.player_id)),
                "name": str(row.name),
                "short_name": str(row.name).rsplit(" ", 1)[-1],
                "team": str(row.team_id),
                "position": str(row.position),
                "buy_tenths": int(str(row.price_tenths)),
                "expected_points": float(str(row.expected_points)),
                # (squad, starter, captain): the server's exact integer coefficients.
                "coefficients": list(coefficients[index]),
            }
            for index, row in enumerate(table.itertuples(index=False))
        ],
    }


def device_plan_entry(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
) -> dict[str, object] | None:
    """One member's side of the problem, or ``None`` where the live path would not plan.

    The bank is the spending power the live path computes from the stated squad sale
    value, not the raw bank; the sale prices are the ones the solver uses. A held squad
    the live path refuses (a departed player, a squad from another week) publishes no
    block rather than a block the device would solve differently.
    """

    try:
        prepared: MemberPlanningInputs = member_planning_inputs(inputs, projection, held, rules)
    except DataSourceError:
        return None
    sell: Mapping[int, int] = prepared.sell_prices_tenths
    return {
        "held": [int(player) for player in held.squad_player_ids],
        "bank_tenths": int(prepared.bank_tenths),
        "free_transfers": int(prepared.free_transfers),
        "sell_tenths": {
            str(int(player)): int(sell[int(player)]) for player in held.squad_player_ids
        },
    }
