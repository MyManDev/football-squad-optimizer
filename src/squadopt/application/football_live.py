"""Produce the optional live football forecast from an immutable capture and archive."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.application.football_context import bind_football_context
from squadopt.application.manager_words import ManagerWords
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.football_history import (
    ARCHIVE_SEASONS,
    archive_history,
    captured_history,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.data.sources.fpl_set_pieces import TAKER_FIELDS, captured_taker_priorities
from squadopt.live import infer_season, read_inputs
from squadopt.live.football_artifact import ARTIFACT_CONTRACT, forecast_digest
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, FixtureFootballModel
from squadopt.prediction.football_contextual import (
    CONTEXTUAL_MODEL_VERSION,
    ContextualFootballModel,
)
from squadopt.prediction.football_features import football_features


def causal_training(history: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for (season, week), target in history.groupby(["season", "GW"], sort=True):
        season, week = str(season), int(str(week))
        if season == ARCHIVE_SEASONS[0]:
            continue  # first season supplies historical priors only, as measured
        cutoff = target.kickoff.min()
        earlier = (history.season < season) | (history.season.eq(season) & history.GW.lt(week))
        past = history.loc[earlier & (history.kickoff + pd.Timedelta(hours=3) < cutoff)]
        features = football_features(past, target, cutoff)
        frame = pd.concat([target.drop(columns="home"), features], axis=1)
        goal = frame.position.map(
            {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
        )
        components = (
            frame.appeared
            + frame.long
            + goal * frame.goals_scored
            + 3 * frame.assists
            + frame.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}) * frame.clean_sheets
        )
        if season >= "2025-26":
            components = components + 2 * frame.dc_event.fillna(0)
        frame["residual_target"] = frame.total_points - components
        frame["feature_cutoff"] = cutoff
        parts.append(frame)
    if not parts:
        raise ValueError("No causal football training rows.")
    return pd.concat(parts, ignore_index=True)


def produce_football_forecast(
    snapshot: CapturedSnapshot,
    archive_root: Path,
    *,
    contextual: bool = False,
    manager_words: ManagerWords | None = None,
) -> dict[str, Any]:
    if not isinstance(contextual, bool):
        raise ValueError("contextual must be a boolean.")
    if manager_words is not None and not contextual:
        raise ValueError("Manager context requires the contextual candidate.")
    season = infer_season(snapshot)
    inputs = read_inputs(snapshot, season=season)
    cutoff = pd.Timestamp(inputs.captured_at_utc)
    first = int(inputs.deadline.gameweek)
    history = archive_history(archive_root)
    history = history.loc[
        (history.season < season) & (history.kickoff + pd.Timedelta(hours=3) < cutoff)
    ]
    current = captured_history(snapshot, season=season, gameweek=first)
    if not current.empty:
        history = pd.concat([history, current], ignore_index=True)
    training = causal_training(history)
    model = (
        ContextualFootballModel(training, history, cutoff=cutoff)
        if contextual
        else FixtureFootballModel(training, history, cutoff=cutoff)
    )
    boot = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    clubs = {t["id"]: t["code"] for t in boot["teams"]}
    player_clubs = {p["code"]: clubs[p["team"]] for p in boot["elements"]}
    roster = inputs.players.copy()
    roster["club"] = roster.player_id.map(player_clubs)
    context_audit: list[dict[str, Any]] = []
    if contextual:
        roster = roster.merge(
            captured_taker_priorities(snapshot.payloads[BOOTSTRAP_PAYLOAD]),
            on="player_id",
            how="left",
            validate="one_to_one",
        )
        roster, context_audit = bind_football_context(
            roster,
            inputs.availability,
            season=season,
            gameweek=first,
            cutoff=cutoff,
            manager_words=manager_words,
        )
    fixtures = pd.DataFrame(json.loads(snapshot.payloads[FIXTURES_PAYLOAD]))
    weeks = tuple(range(first, min(first + 5, 39)))
    fixtures = fixtures.loc[fixtures.event.isin(weeks)]
    if fixtures.kickoff_time.isna().any():
        raise ValueError("Football window contains an undated fixture.")
    calendar = pd.concat(
        [
            pd.DataFrame(
                {
                    "fixture": fixtures.id,
                    "club": fixtures["team_h" if home else "team_a"].map(clubs),
                    "opponent": fixtures["team_a" if home else "team_h"].map(clubs),
                    "home": float(home),
                    "GW": fixtures.event,
                    "kickoff": pd.to_datetime(fixtures.kickoff_time, utc=True),
                }
            )
            for home in (True, False)
        ],
        ignore_index=True,
    )
    horizon, components = build_football_horizon(
        model,
        history,
        roster,
        calendar,
        gameweeks=weeks,
        season=season,
        source_snapshot_id=inputs.snapshot_id,
        captured_at=cutoff,
    )
    table = horizon.table.copy()
    # Probability of at least one appearance. Independent fixture minutes are an approximation.
    chance = (
        components.groupby(["GW", "player_code"]).appearance_probability.agg(
            lambda x: 1.0 - float((1.0 - x.to_numpy(dtype=float)).prod())
        )
        if not components.empty
        else pd.Series(dtype=float)
    )
    if not contextual:  # v3 already contains the shared-eligibility weekly probability.
        table["appearance_probability"] = [
            float(chance.get((int(w), int(p)), 0))
            for w, p in zip(table.gameweek, table.player_id, strict=True)
        ]
    hashes = {}
    for prior in ARCHIVE_SEASONS:
        for name in ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv"):
            path = archive_root / "data" / prior / name
            hashes[f"{prior}/{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    document = {
        "contract_version": ARTIFACT_CONTRACT,
        "model_version": CONTEXTUAL_MODEL_VERSION if contextual else FOOTBALL_MODEL_VERSION,
        "season": season,
        "gameweek": first,
        "source_snapshot_id": inputs.snapshot_id,
        "captured_at_utc": inputs.captured_at_utc,
        "source_fingerprint": snapshot.metadata.fingerprint,
        "training_rows": len(training),
        "training_latest_kickoff": history.kickoff.max().isoformat(),
        "archive_hashes": hashes,
        "experimental": True,
        "limitations": [
            "Development data reused; independent superiority unverified.",
            "Future availability uses the captured state; "
            "independent fixture minutes approximation.",
            "Current club assigned only to unambiguous captured single-fixture weeks.",
        ],
        "rows": table.to_dict("records"),
    }
    if contextual:
        document["availability_application"] = "before_team_shares_v1"
        document["projection_contract"] = horizon.contract_version
        document["manager_context"] = context_audit
        document["taker_priorities"] = {
            "source_snapshot_id": inputs.snapshot_id,
            "captured_at_utc": inputs.captured_at_utc,
            "scoring_effect": "none_until_event_channel_rates_are_validated",
            "rows": [
                {
                    "player_id": int(row["player_id"]),
                    **{key: None if pd.isna(row[key]) else int(row[key]) for key in TAKER_FIELDS},
                }
                for row in roster[["player_id", *TAKER_FIELDS]].to_dict("records")
            ],
        }
        document["limitations"].extend(
            [
                "Joint intensity uncertainty is a moment-matched working approximation.",
                "Source playing percentages are eligibility rules, not calibrated start forecasts.",
                "Current-club roles do not identify separate penalty/set-piece intensities.",
            ]
        )
    document["fingerprint"] = forecast_digest(document)
    return document
