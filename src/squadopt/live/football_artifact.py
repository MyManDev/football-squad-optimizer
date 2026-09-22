"""Versioned, capture-bound football forecasts. Reading never fits or fetches a model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.planning.horizon import APPEARANCE_HORIZON_CONTRACT_VERSION, ProjectionHorizon
from squadopt.prediction.availability import apply_availability
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_contextual import CONTEXTUAL_MODEL_VERSION

FOOTBALL_CHOICE = "football"
MODEL_CHOICES = ("current", FOOTBALL_CHOICE)
ARTIFACT_CONTRACT = "live_football_forecast_v1"
FEATURE_CONTRACT = "causal_football_fixture_features_v1"


def football_artifact_path(root: Path, snapshot_id: str) -> Path:
    if not snapshot_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        for c in snapshot_id
    ):
        raise ValueError("Invalid football capture identifier.")
    return root / "football" / (snapshot_id + ".json")


def forecast_digest(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "fingerprint"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class FootballForecast:
    horizon: ProjectionHorizon
    projection: Projection
    fingerprint: str

    def build_horizon(self, weeks: tuple[int, ...]) -> ProjectionHorizon:
        available = set(self.horizon.table.gameweek)
        if not weeks or not set(weeks).issubset(available):
            raise ValueError("Football forecast does not cover the requested window.")
        return replace(
            self.horizon,
            table=self.horizon.table.loc[self.horizon.table.gameweek.isin(weeks)].copy(),
        )


def read_football_forecast(path: Path, inputs: RecommendationInputs) -> FootballForecast:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("fingerprint") != forecast_digest(document):
        raise ValueError("Football forecast fingerprint mismatch.")
    contextual = document.get("model_version") == CONTEXTUAL_MODEL_VERSION
    version = CONTEXTUAL_MODEL_VERSION if contextual else FOOTBALL_MODEL_VERSION
    if contextual and (
        document.get("availability_application") != "before_team_shares_v1"
        or document.get("projection_contract") != APPEARANCE_HORIZON_CONTRACT_VERSION
    ):
        raise ValueError("Contextual football requires pre-allocation availability and appearance.")
    for key, expected in {
        "contract_version": ARTIFACT_CONTRACT,
        "model_version": version,
        "season": inputs.season,
        "source_snapshot_id": inputs.snapshot_id,
        "captured_at_utc": inputs.captured_at_utc,
        "gameweek": inputs.deadline.gameweek,
    }.items():
        if document.get(key) != expected:
            raise ValueError(f"Football forecast mismatches {key}.")
    first = int(inputs.deadline.gameweek)
    table = pd.DataFrame(document["rows"])
    horizon = ProjectionHorizon(
        table,
        inputs.season,
        inputs.snapshot_id,
        "fixture_football_candidate",
        version,
        FEATURE_CONTRACT,
        "fixture_sum_blank_zero_v1",
        **({"contract_version": APPEARANCE_HORIZON_CONTRACT_VERSION} if contextual else {}),
    )
    if set(horizon.table.gameweek) != set(range(first, min(first + 5, 39))):
        raise ValueError("Football forecast must cover the full available five-week window.")
    roster = inputs.players.set_index("player_id")
    if set(horizon.table.player_id) != set(roster.index):
        raise ValueError("Football forecast roster coverage mismatch.")
    for col in ("name", "team_id", "position", "price_tenths"):
        if not (
            horizon.table[col].to_numpy() == horizon.table.player_id.map(roster[col]).to_numpy()
        ).all():
            raise ValueError(f"Football forecast roster mismatches {col}.")
    # Availability is the existing explicit capture-time rule, applied once per week.
    adjusted = []
    first_projection = None
    for week, frame in table.groupby("gameweek", sort=True):
        chance = pd.to_numeric(frame["appearance_probability"], errors="raise")
        if not chance.between(0, 1).all():
            raise ValueError("Football appearance probability outside [0, 1].")
        result = None if contextual else apply_availability(frame, inputs.availability)
        adjusted_frame = frame if result is None else result.table
        adjusted.append(adjusted_frame)
        if week == first:
            first_projection = Projection(
                adjusted_frame,
                tuple(adjusted_frame.loc[adjusted_frame.appearance_probability.eq(0), "player_id"])
                if result is None
                else result.unavailable_players,
                {
                    **(
                        {"availability_application": "before_team_shares_v1"}
                        if result is None
                        else dict(result.diagnostics)
                    ),
                    "model_name": "fixture_football_candidate",
                    "model_version": version,
                    "feature_contract_version": FEATURE_CONTRACT,
                    "projection_source": "live_football_artifact",
                    "projection_handoff_fingerprint": document["fingerprint"],
                    "projection_evidence_fingerprint": None,
                    "experimental": True,
                },
            )
    assert first_projection is not None
    return FootballForecast(
        replace(horizon, table=pd.concat(adjusted, ignore_index=True)),
        first_projection,
        document["fingerprint"],
    )
