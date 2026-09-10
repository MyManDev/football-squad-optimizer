"""Map chip alternatives to the member publication contract."""

from collections.abc import Sequence

from squadopt.application.lineup_publication import lineup_fields
from squadopt.live.chip_advice import ChipRecommendation
from squadopt.live.transfers import MEMBER_PLANNING_POLICY_ID
from squadopt.planning import TransferPlanResult


def chip_recommendation_payload(
    recommendations: Sequence[ChipRecommendation],
    control: TransferPlanResult,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for item in recommendations:
        plan = item.plan
        week = (
            next((week for week in plan.weeks if week.gameweek == item.gameweek), None)
            if plan
            else None
        )
        decision = (
            None
            if week is None
            else {
                **lineup_fields(week),
                "gameweek": week.gameweek,
                "transfer_hit_points": float(week.transfer_hit_points),
            }
        )
        rows.append(
            {
                "chip": item.window.name,
                "available_from_gameweek": item.window.start_event,
                "last_usable_gameweek": item.window.stop_event,
                "remaining": item.remaining,
                "action": "play" if item.gameweek is not None else "hold",
                "gameweek": item.gameweek,
                "expected_points_gain": item.expected_gain,
                "reason": item.reason,
                "solver_status": None if plan is None else plan.solver_status.name,
                "optimality_gap": None
                if plan is None
                else plan.diagnostics.get("absolute_optimality_gap"),
                "decision": decision,
            }
        )
    return {
        "contract_version": "member_chip_recommendations_v1",
        "planning_policy_id": MEMBER_PLANNING_POLICY_ID,
        "gameweeks": [week.gameweek for week in control.weeks],
        "control_solver_status": control.solver_status.name,
        "control_optimality_gap": control.diagnostics.get("absolute_optimality_gap"),
        "comparisons": rows,
    }
