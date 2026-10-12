"""What a member's one-week plan needs, published so the member's own device can solve it.

The advice backend runs on one machine. The shared part of every answer, the projection
table for the capture, is produced once; the per-member part is one optimisation over it.
This module publishes exactly the inputs the live path hands its own solver, so that a page
on the member's device can state the same problem and return the same answer:

- ``device_plan_table``: the capture's table in the order the solver sees it, with the
  server's own integer objective coefficients, and the season's rules and the member
  planning policy as numbers. One document per league tree (contract v1).
- ``device_plan_capture_table``: the same table once per capture (contract v2), with no
  league in it, each player's element id and start price beside his code and price, and
  the season's chip windows and per-week transfer cap beside the policy's numbers. Written
  under ``data/device/<capture>/`` so every league of a run shares it. A republish of the
  capture replaces it, so the directory line names it with the sha256 of its bytes.
- ``device_plan_entry``: one member's fifteen, the bank after the spending-power rule, the
  free transfers under the cap, and the sale price of each held player. One block per
  entry document, or ``None`` when the live path would refuse to plan for that member.

Nothing here solves anything. The solve on the device restates the one-week model and is
held to the server's answer by a parity test; the numbers published here are the numbers
the server uses, not a description of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from squadopt.application.strategies.catalog import STRATEGY_CATALOG
from squadopt.application.top100_weight import TOP100_WEIGHTS, Top100Counts, weighted_projection
from squadopt.contracts.league_tree import DEVICE_PLAN_FILE
from squadopt.contracts.players import sort_players_by_id
from squadopt.data.errors import DataSourceError
from squadopt.data.sources.fpl_live import element_prices, player_codes
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
from squadopt.prediction.elite_evidence import ELITE_COHORT_SIZE

DEVICE_PLAN_CONTRACT_VERSION: Final = "league_device_plan_v1"
#: The per-capture table: one document per capture, no league in it.
DEVICE_PLAN_TABLE_CONTRACT_VERSION: Final = "league_device_plan_v2"
DEVICE_PLAN_DOCUMENT: Final = DEVICE_PLAN_FILE


def device_plan_table(
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    optimization: OptimizationConfig | None = None,
    top100: Top100Counts | None = None,
) -> dict[str, object]:
    """The capture's table and rules, as the member path's solver receives them.

    With ``top100``, the week's Top 100 counts: each player's start count and, for every
    weight the menu offers, his weighted points on the objective's integer scale, scaled
    exactly as the server scales them (``weighted_projection`` then
    ``scale_expected_points``), so a device chooses on the same integers the server
    chooses on. The device derives the bench coefficient from the integer by the
    server's own rounding rule and never multiplies a float.

    The players are sorted by id, the order the planner sorts its own table into before
    it solves: the server breaks ties between equal plans by rank in that order, and a
    device that reorders the table would resolve the same tie differently.

    A sale price is published for the held fifteen only; the planner fills a non-held
    player's with the buy price, which the one-week answer never uses since a player not
    held cannot be sold. No per-week transfer cap applies under the member policy.
    """

    body = _table_body(inputs, projection, rules, optimization=optimization, top100=top100)
    return {
        "contract_version": DEVICE_PLAN_CONTRACT_VERSION,
        "league_id": int(league_id),
        **body,
    }


def device_plan_capture_table(
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    bootstrap: bytes,
    optimization: OptimizationConfig | None = None,
    top100: Top100Counts | None = None,
) -> dict[str, object]:
    """The capture's table once for every league of the run (contract v2).

    Everything ``device_plan_table`` publishes except the league, so every league of a run
    shares it under ``data/device/<capture>/``. It also depends on the run's inputs (the
    handoff, the Top 100 inputs, the code), so a republish of the capture can replace it.
    Each player also carries ``element_id``, the game's per-season id the entry endpoints
    name him by, and ``start_tenths``, his price at the season's first deadline, both read
    from the capture's bootstrap; a table player the bootstrap does not name is refused.
    ``rules`` also carries ``chips``, the season's chip windows as the rules state them,
    and ``transfers_cap``, the game's cap on transfers in one week (null where it states
    none), beside the policy's cap on banked free transfers.
    """

    body = _table_body(inputs, projection, rules, optimization=optimization, top100=top100)
    codes = player_codes(bootstrap)
    elements = {code: element for element, code in codes.items()}
    prices = element_prices(bootstrap)
    players: list[dict[str, object]] = []
    for row in body["players"]:
        code = int(str(row["id"]))
        element = elements.get(code)
        if element is None:
            raise DataSourceError(
                f"The capture's bootstrap names no element for player code {code}; the table "
                "cannot carry his element id or start price."
            )
        players.append(
            {
                "id": row["id"],
                "element_id": int(element),
                "name": row["name"],
                "short_name": row["short_name"],
                "team": row["team"],
                "position": row["position"],
                "buy_tenths": row["buy_tenths"],
                "start_tenths": int(prices[element].start_tenths),
                **{key: value for key, value in row.items() if key not in _V1_PLAYER_KEYS},
            }
        )
    body_rules = dict(body["rules"])
    body_rules["transfers_cap"] = (
        None if rules.transfers.transfers_cap is None else int(rules.transfers.transfers_cap)
    )
    body_rules["chips"] = [
        {
            "name": window.name,
            "number": window.number,
            "start_event": window.start_event,
            "stop_event": window.stop_event,
            "chip_type": window.chip_type,
        }
        for window in rules.chips
    ]
    return {
        "contract_version": DEVICE_PLAN_TABLE_CONTRACT_VERSION,
        **{key: value for key, value in body.items() if key not in ("rules", "players")},
        "rules": body_rules,
        "players": players,
    }


_V1_PLAYER_KEYS: Final = ("id", "name", "short_name", "team", "position", "buy_tenths")


def _table_body(
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    optimization: OptimizationConfig | None,
    top100: Top100Counts | None,
) -> dict[str, Any]:
    """The fields the two table contracts share: the deadline, the policy, the rules and
    the players in solver order."""

    settings = OptimizationConfig() if optimization is None else optimization
    table = sort_players_by_id(
        projection.table.loc[
            :, ["player_id", "name", "team_id", "position", "price_tenths", "expected_points"]
        ]
    )
    coefficients = objective_coefficients(table["expected_points"].tolist(), settings)
    policy = member_planning_policy(rules)
    weights = tuple(weight for weight in TOP100_WEIGHTS if weight != 0)
    weighted_scaled: dict[int, dict[str, int]] = {}
    if top100 is not None:
        for weight in weights:
            weighted = sort_players_by_id(
                weighted_projection(projection, top100.counts, weight).table
            )
            for player, points in zip(
                weighted["player_id"].tolist(), weighted["expected_points"].tolist(), strict=True
            ):
                weighted_scaled.setdefault(int(str(player)), {})[str(weight)] = (
                    scale_expected_points(points, settings.expected_points_scale)
                )
    return {
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
            # What the game charges per paid transfer, the number the page shows, and
            # the same on the objective scale: the rival price tag's anchor is solved at
            # the charge, not at the margin.
            "hit_points_charged": float(policy.hit_points_charged),
            "hit_charged_scaled": scale_expected_points(
                policy.hit_points_charged, settings.expected_points_scale
            ),
            "expected_points_scale": settings.expected_points_scale,
            # Each rival strategy's overlap band on the decided week, from the catalogue:
            # a floor is relaxed downward and a ceiling upward until the free transfers
            # reach it (``advice._solve_within_free_transfers``).
            "strategies": {
                slug: {
                    "overlap_floor": strategy.constraints.overlap_floor,
                    "overlap_ceiling": strategy.constraints.overlap_ceiling,
                }
                for slug, strategy in sorted(STRATEGY_CATALOG.items())
                if strategy.constraints.overlap_floor is not None
                or strategy.constraints.overlap_ceiling is not None
            },
            # The Top 100 influence's inputs, where the week has them: the weights the
            # menu offers, the cohort the counts are out of, and where the counts came from.
            **(
                {}
                if top100 is None
                else {
                    "top100": {
                        "weights": list(weights),
                        "cohort_size": ELITE_COHORT_SIZE,
                        **top100.source_record(),
                    }
                }
            ),
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
                **(
                    {}
                    if top100 is None
                    else {
                        "top100_count": int(top100.counts.get(int(str(row.player_id)), 0)),
                        "top100_scaled": weighted_scaled.get(int(str(row.player_id)), {}),
                    }
                ),
            }
            for index, row in enumerate(table.itertuples(index=False))
        ],
    }


def device_plan_entry(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    top100: Top100Counts | None = None,
) -> dict[str, object] | None:
    """One member's side of the problem, or ``None`` where the live path would not plan.

    The bank and the sale prices are the ones the solver uses: for a member whose purchase
    prices were rebuilt, the raw bank and the rule's sale prices; otherwise the spending
    power the live path computes from the stated squad sale value. A held squad
    the live path refuses (a departed player, a squad from another week) publishes no
    block rather than a block the device would solve differently.
    """

    try:
        prepared: MemberPlanningInputs = member_planning_inputs(inputs, projection, held, rules)
    except DataSourceError:
        return None
    sell: Mapping[int, int] = prepared.sell_prices_tenths
    weights = [weight for weight in TOP100_WEIGHTS if weight != 0]
    return {
        # The weights the shared document carries this week, so a page can offer them
        # before it reads the document; none where the week has no counts.
        **({} if top100 is None else {"top100_weights": weights}),
        "held": [int(player) for player in held.squad_player_ids],
        "bank_tenths": int(prepared.bank_tenths),
        "free_transfers": int(prepared.free_transfers),
        "sell_tenths": {
            str(int(player)): int(sell[int(player)]) for player in held.squad_player_ids
        },
    }
