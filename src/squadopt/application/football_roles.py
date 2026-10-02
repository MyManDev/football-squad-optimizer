"""Internal fixture-role estimates and their restricted public explanation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Set
from typing import Any, cast

import pandas as pd

from squadopt.live import RecommendationInputs
from squadopt.live.minute_evidence import FixtureComponentBasis
from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION


def _point_components(row: Mapping[str, Any], season: str, eligibility: float) -> dict[str, float]:
    """Explain the existing individual fixture score, before captain or Top100 weighting."""
    goal = {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
    clean = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
    values = {
        "appearance": row["appearance_probability"] + row["p60"],
        "goals": goal[row["position"]] * row["goals"],
        "assists": 3 * row["assists"],
        "clean_sheet": clean[row["position"]] * row["clean_sheet_probability"],
        "defcon": 2 * row["defcon_probability"] if season >= "2025-26" else 0.0,
        "other": row["appearance_probability"] * row["residual_if_appearance"],
        "clipping": row["expected_points"] - row["raw_expected_points"],
        "total": row["expected_points"],
    }
    return {key: float(value) * eligibility for key, value in values.items()}


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
    season = str(basis.served["season"])
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
                "point_components": _point_components(
                    cast(Mapping[str, Any], row), season, eligibility
                ),
            }
        )
    return estimates


def bind_role_absences(
    rows: list[dict[str, Any]], final_week: pd.DataFrame
) -> list[dict[str, Any]]:
    """Apply absence and withhold any explanation that differs from the final weekly score."""
    absent = set(final_week.loc[final_week.appearance_probability.eq(0), "player_id"])
    result = []
    for row in rows:
        updated = dict(row)
        if "point_components" in row:
            updated["point_components"] = dict(row["point_components"])
            if row["player_id"] in absent:
                updated["point_components"] = dict.fromkeys(updated["point_components"], 0.0)
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
    final_points = final_week.set_index("player_id").expected_points.to_dict()
    for player in {row["player_id"] for row in result}:
        fixtures = [row for row in result if row["player_id"] == player]
        components = [row.get("point_components") for row in fixtures]
        consistent = all(
            part is not None
            and all(math.isfinite(value) for value in part.values())
            and all(value >= 0 for key, value in part.items() if key != "other")
            and math.isclose(
                math.fsum(value for key, value in part.items() if key != "total"),
                part["total"],
                rel_tol=1e-10,
                abs_tol=1e-10,
            )
            for part in components
        )
        if (
            not consistent
            or player not in final_points
            or not math.isclose(
                math.fsum(part["total"] for part in components if part is not None),
                float(final_points[player]),
                rel_tol=1e-10,
                abs_tol=1e-10,
            )
        ):
            for row in fixtures:
                row.pop("point_components", None)
    return result


# Keep modeled role probabilities internal until a publication gate admits them.
# An allowlist also prevents future diagnostic fields from reaching member payloads.
_PUBLIC_ROLE_FIELDS = (
    "player_id",
    "name",
    "fixture_id",
    "gameweek",
    "kickoff",
    "status",
    "expected_minutes",
    "captured_eligibility_multiplier",
    "news_applied",
    "point_components",
)


def role_forecast_summary(
    diagnostics: Mapping[str, object], player_ids: Set[int]
) -> dict[str, Any] | None:
    rows = diagnostics.get("fixture_role_estimates")
    if not isinstance(rows, list):
        return None
    selected = [
        {key: row[key] for key in _PUBLIC_ROLE_FIELDS if key in row}
        for row in rows
        if row["player_id"] in player_ids
    ]
    if not selected:
        return None
    return {
        "version": "football_role_forecast_v1",
        "model_version": JOINT_ROLE_MODEL_VERSION,
        "calibration": "not_independently_verified",
        "scope": "current_gameweek_fixtures",
        "rows": selected,
    }
