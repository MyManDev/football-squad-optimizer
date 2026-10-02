"""Public conditional plan explanation, with base points separate from choice utility."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from squadopt.live.recommendation import Projection
from squadopt.planning import ProjectionHorizon, TransferPlanResult


def information_review_payload(
    plan: TransferPlanResult,
    projection: Projection,
    *,
    base_horizon: ProjectionHorizon | None = None,
    weighted: bool = False,
) -> dict[str, Any] | None:
    information = plan.diagnostics.get("availability_information")
    if not isinstance(information, Mapping):
        return None
    review = cast(dict[str, Any] | None, plan.diagnostics.get("observed_window"))
    players = {int(str(row.player_id)): str(row.name) for row in projection.table.itertuples()}
    base = (
        base_horizon.table.set_index(["gameweek", "player_id"]).expected_points
        if base_horizon is not None
        else None
    )

    def names(ids: list[int]) -> list[str]:
        return [players.get(int(player), str(player)) for player in ids]

    def named_lineup(action: Mapping[str, Any]) -> dict[str, Any] | None:
        if action.get("vice_captain") is None or "bench" not in action:
            return None
        return {
            "starting_xi": names(action["starters"]),
            "captain": names([action["captain"]])[0],
            "vice_captain": names([action["vice_captain"]])[0],
            "bench": names(action["bench"]),
        }

    def net(branch: Mapping[str, Any]) -> float | None:
        if weighted and base is None:
            return None
        total = -float(branch["hit_points"])
        for term in branch["point_terms"]:
            forecast = float(term["forecast"])
            original = float(term["baseline_forecast"])
            if base is not None:
                forecast = (
                    float(base.loc[(term["gameweek"], term["player_id"])]) * forecast / original
                    if original
                    else 0
                )
            total += float(term["multiplier"]) * forecast
        return total

    candidates = []
    compared = isinstance(review, Mapping) and review.get("status") == "compared"
    if compared:
        assert review is not None
        for index, candidate in enumerate(review["candidates"]):
            first = candidate["branches"][0].get("first_action", {})
            first_lineup = named_lineup(first)
            branches = []
            for branch in candidate["branches"]:
                branches.append(
                    {
                        "state": branch["id"],
                        "expected_net_points": net(branch),
                        "hit_points": branch["hit_points"],
                        "weeks": [
                            {
                                "gameweek": w["gameweek"],
                                "transfers_in": names(w["in"]),
                                "transfers_out": names(w["out"]),
                                "chip": w["chip"],
                                "bank_tenths": w["bank"],
                                "free_transfers": w["ft"],
                                **(
                                    {"lineup": lineup}
                                    if (lineup := named_lineup(w)) is not None
                                    else {}
                                ),
                            }
                            for w in branch["weeks"]
                        ],
                    }
                )
            estimates = [b["expected_net_points"] for b in branches]
            candidates.append(
                {
                    "selected": index == review["chosen_index"],
                    "baseline": index == 0,
                    "transfers_in": names(candidate["first_in"]),
                    "transfers_out": names(candidate["first_out"]),
                    "chip": candidate["first_chip"],
                    **({"first_lineup": first_lineup} if first_lineup is not None else {}),
                    "expected_net_points": (
                        sum(
                            raw["probability"] * shown["expected_net_points"]
                            for raw, shown in zip(candidate["branches"], branches, strict=True)
                        )
                        if None not in estimates
                        else None
                    ),
                    "branches": branches,
                }
            )
    return {
        "version": "football_information_review_v1",
        "status": "compared" if compared else "baseline_retained",
        "reason": information["reason"] if not isinstance(review, Mapping) else review["status"],
        "source_snapshot_id": information["source_snapshot_id"],
        "captured_at_utc": information["captured_at_utc"],
        "player_name": players.get(int(str(information["player_id"])))
        if information.get("player_id") is not None
        else None,
        "source_playing_chance_percent": (
            round(float(str(information["probability"])) * 100)
            if information.get("probability") is not None
            else None
        ),
        "information_gameweek": information.get("gameweek"),
        "candidates": candidates,
    }
