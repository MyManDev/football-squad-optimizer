"""Produce the optional live football forecast from an immutable capture and archive."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from numbers import Integral
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
from squadopt.live import RecommendationInputs, infer_season, read_inputs
from squadopt.live.football_artifact import (
    ARTIFACT_CONTRACT,
    SHARES_BEFORE_AVAILABILITY_LIMIT,
    forecast_digest,
)
from squadopt.live.football_horizon import build_football_horizon
from squadopt.prediction.availability import apply_availability
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, FixtureFootballModel
from squadopt.prediction.football_components import (
    COMPONENT_LIMITATIONS,
    FIXTURE_COMPONENTS_CONTRACT,
    captured_availability,
    component_rows,
)
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


def forecast_gameweeks(first: int, gameweeks: Sequence[int] | None = None) -> tuple[int, ...]:
    """The consecutive gameweeks one artifact forecasts, starting at the capture's own target.

    ``None`` is the artifact as it is served: five weeks from the target, fewer at the end
    of the season. A caller may name a longer run for research. It must still start at the
    target, because the first week is the decided forecast and the reader holds it to the
    capture's deadline. Nothing here invents a calendar: a named week the capture does not
    publish fails in the fixture calendar below, not by being filled in.
    """
    if gameweeks is None:
        return tuple(range(first, min(first + 5, 39)))
    weeks = tuple(gameweeks)
    if not weeks or any(isinstance(w, bool) or not isinstance(w, Integral) for w in weeks):
        raise ValueError("Forecast gameweeks must be a nonempty sequence of integers.")
    weeks = tuple(int(w) for w in weeks)
    if weeks[0] != first:
        raise ValueError("Forecast gameweeks must start at the capture's own target gameweek.")
    if weeks != tuple(range(weeks[0], weeks[-1] + 1)) or weeks[-1] > 38:
        raise ValueError("Forecast gameweeks must be consecutive and end by gameweek 38.")
    return weeks


def _forecast_and_components(
    snapshot: CapturedSnapshot,
    archive_root: Path,
    *,
    contextual: bool,
    manager_words: ManagerWords | None,
    gameweeks: Sequence[int] | None,
) -> tuple[dict[str, Any], pd.DataFrame, RecommendationInputs]:
    """One producer call: the served document, the per-fixture components and the inputs."""

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
    weeks = forecast_gameweeks(first, gameweeks)
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
    return document, components, inputs


def produce_football_forecast(
    snapshot: CapturedSnapshot,
    archive_root: Path,
    *,
    contextual: bool = False,
    manager_words: ManagerWords | None = None,
    gameweeks: Sequence[int] | None = None,
) -> dict[str, Any]:
    document, _components, _inputs = _forecast_and_components(
        snapshot,
        archive_root,
        contextual=contextual,
        manager_words=manager_words,
        gameweeks=gameweeks,
    )
    return document


def produce_football_components(
    snapshot: CapturedSnapshot,
    archive_root: Path,
    *,
    gameweeks: Sequence[int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The served v1 document and its per-fixture components, from one producer call.

    The first document is exactly what ``produce_football_forecast`` returns for the same
    arguments. The second is ``football_fixture_components_v1``: every scheduled player-fixture's
    model outputs, bound to the first by its fingerprint. The capture's availability is carried
    once in its header, as the multiplier ``apply_availability`` gives each player and the rule
    that gave it, and applied to no row. v1 only: the contextual model conditions its team
    components on availability and is not this contract.
    """

    document, components, inputs = _forecast_and_components(
        snapshot, archive_root, contextual=False, manager_words=None, gameweeks=gameweeks
    )
    roster = [int(player) for player in inputs.players.player_id]
    unit = pd.DataFrame({"player_id": roster, "expected_points": [1.0] * len(roster)})
    adjustment = apply_availability(unit, inputs.availability)
    multipliers = dict(zip(roster, (float(v) for v in adjustment.multiplier), strict=True))
    companion: dict[str, Any] = {
        "contract_version": FIXTURE_COMPONENTS_CONTRACT,
        "model_version": document["model_version"],
        "experimental": True,
        "season": document["season"],
        "gameweek": document["gameweek"],
        "gameweeks": sorted({int(row["gameweek"]) for row in document["rows"]}),
        "source_snapshot_id": document["source_snapshot_id"],
        "captured_at_utc": document["captured_at_utc"],
        "source_fingerprint": document["source_fingerprint"],
        "forecast_fingerprint": document["fingerprint"],
        "training_rows": document["training_rows"],
        "training_latest_kickoff": document["training_latest_kickoff"],
        "archive_hashes": dict(document["archive_hashes"]),
        "captured_availability": captured_availability(multipliers, adjustment.diagnostics),
        "limitations": [
            *document["limitations"],
            SHARES_BEFORE_AVAILABILITY_LIMIT,
            *COMPONENT_LIMITATIONS,
        ],
        "rows": []
        if components.empty
        else component_rows(
            components, model_version=document["model_version"], players=multipliers
        ),
    }
    companion["fingerprint"] = forecast_digest(companion)
    return document, companion
