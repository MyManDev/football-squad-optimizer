"""Public fixture-role estimates from the same component law used by the planner."""

from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Any, cast

import pandas as pd

from squadopt.live import RecommendationInputs
from squadopt.live.minute_evidence import FixtureComponentBasis
from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION


def fixture_role_estimates(
    basis: FixtureComponentBasis | None,
    inputs: RecommendationInputs,
    *,
    revised_rows: pd.DataFrame | None = None,
    applied_fixtures: Set[tuple[int, int]] = frozenset(),
) -> list[dict[str, Any]]:
    """Keep source eligibility separate from model roles; never infer a role from minutes."""
    if basis is None or basis.companion["model_version"] != JOINT_ROLE_MODEL_VERSION:
        return []
    rows = basis.fixture_rows if revised_rows is None else revised_rows
    multipliers = {
        int(row["player_code"]): float(row["multiplier"])
        for row in cast(dict[str, Any], basis.companion["captured_availability"])["multipliers"]
    }
    names = inputs.players.set_index("player_id").name.to_dict()
    estimates = []
    for row in rows.loc[rows.GW.eq(inputs.deadline.gameweek)].to_dict("records"):
        eligibility = multipliers[int(row["player_code"])]
        estimates.append(
            {
                "player_id": int(row["player_code"]),
                "name": str(names[int(row["player_code"])]),
                "fixture_id": int(row["fixture"]),
                "gameweek": int(row["GW"]),
                "kickoff": pd.Timestamp(row["kickoff"]).isoformat(),
                "status": str(row["minute_role_status"]),
                "start_probability": None
                if pd.isna(row["start_probability"])
                else float(row["start_probability"]) * eligibility,
                "cameo_probability": None
                if pd.isna(row["cameo_probability"])
                else float(row["cameo_probability"]) * eligibility,
                "zero_probability": 1 - float(row["appearance_probability"]) * eligibility,
                "unknown_role_probability": float(row["unknown_role_probability"]) * eligibility,
                "expected_minutes": float(row["expected_minutes"]) * eligibility,
                "sixty_minute_probability": float(row["p60"]) * eligibility,
                "captured_eligibility_multiplier": eligibility,
                "news_applied": (int(row["player_code"]), int(row["fixture"])) in applied_fixtures,
            }
        )
    return estimates


def bind_role_absences(
    rows: list[dict[str, Any]], final_week: pd.DataFrame
) -> list[dict[str, Any]]:
    """A verified absence zeroes this fixture's law; no other role is re-estimated here."""
    absent = set(final_week.loc[final_week.appearance_probability.eq(0), "player_id"])
    result = []
    for row in rows:
        updated = dict(row)
        if row["player_id"] in absent and row["zero_probability"] < 1:
            for key in ("start_probability", "cameo_probability"):
                if updated[key] is not None:
                    updated[key] = 0.0
            updated.update(
                zero_probability=1.0,
                unknown_role_probability=0.0,
                expected_minutes=0.0,
                sixty_minute_probability=0.0,
                news_applied=True,
            )
        result.append(updated)
    return result


def role_forecast_summary(
    diagnostics: Mapping[str, object], player_ids: Set[int]
) -> dict[str, Any] | None:
    rows = diagnostics.get("fixture_role_estimates")
    if not isinstance(rows, list):
        return None
    selected = [row for row in rows if row["player_id"] in player_ids]
    if not selected:
        return None
    return {
        "version": "football_role_forecast_v1",
        "model_version": JOINT_ROLE_MODEL_VERSION,
        "calibration": "not_independently_verified",
        "scope": "current_gameweek_fixtures",
        "rows": selected,
    }
