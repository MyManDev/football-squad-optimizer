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
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSION,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
    FixtureFootballModel,
    JointRoleFootballModel,
    RetainedHistoryRoleFootballModel,
)
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
from squadopt.prediction.football_team_form import (
    TEAM_FORM_FEATURE_VERSION,
    TEAM_FORM_MODEL_VERSION,
    TeamFormFootballModel,
    football_team_form_features,
    team_form_metadata,
)

# The archives team form may select beside the captured season. The 2025-26 outcome
# population is locked, so it is absent here and refused by name before any read.
TEAM_FORM_ARCHIVE_SEASONS = ("2022-23", "2023-24", "2024-25")
LOCKED_OUTCOME_SEASON = "2025-26"


def causal_training(
    history: pd.DataFrame, *, prior_only_season: str | None = None, team_form: bool = False
) -> pd.DataFrame:
    if not isinstance(team_form, bool):
        raise ValueError("team_form must be boolean.")
    prior_season = ARCHIVE_SEASONS[0] if prior_only_season is None else prior_only_season
    parts = []
    for (season, week), target in history.groupby(["season", "GW"], sort=True):
        season, week = str(season), int(str(week))
        if season == prior_season:
            continue  # first season supplies historical priors only, as measured
        cutoff = target.kickoff.min()
        earlier = (history.season < season) | (history.season.eq(season) & history.GW.lt(week))
        past = history.loc[earlier & (history.kickoff + pd.Timedelta(hours=3) < cutoff)]
        features = (
            football_team_form_features(past, target, cutoff)
            if team_form
            else football_features(past, target, cutoff)
        )
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


def _training_sources(
    selected: Sequence[str] | None, current_season: str
) -> tuple[tuple[str, ...], bool]:
    """Resolve an allowlist before opening either archive or captured outcome history."""
    if selected is None:
        return ARCHIVE_SEASONS, True
    supported = {*ARCHIVE_SEASONS, current_season}
    if (
        isinstance(selected, (str, bytes))
        or not isinstance(selected, Sequence)
        or not selected
        or any(not isinstance(season, str) or season not in supported for season in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("Training seasons must be a nonempty unique supported selection.")
    return tuple(sorted(set(selected) & set(ARCHIVE_SEASONS))), current_season in selected


def _season_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        str(season): int(count)
        for season, count in frame.groupby("season", sort=True).size().items()
    }


def _forecast_and_components(
    snapshot: CapturedSnapshot,
    archive_root: Path,
    *,
    contextual: bool,
    manager_words: ManagerWords | None,
    gameweeks: Sequence[int] | None,
    training_seasons: Sequence[str] | None,
    role_minutes: bool = False,
    retained_role_history: bool = False,
    team_form: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame, RecommendationInputs]:
    """One producer call: the served document, the per-fixture components and the inputs."""

    if not isinstance(contextual, bool):
        raise ValueError("contextual must be a boolean.")
    if not isinstance(role_minutes, bool) or (role_minutes and contextual):
        raise ValueError("role_minutes must be boolean and cannot be combined with contextual.")
    if not isinstance(retained_role_history, bool) or (retained_role_history and not role_minutes):
        raise ValueError("retained_role_history must be boolean and requires role_minutes.")
    if role_minutes and training_seasons is None:
        raise ValueError("Joint role minutes require an explicit training-season allowlist.")
    if not isinstance(team_form, bool) or (team_form and (contextual or role_minutes)):
        raise ValueError("team_form must be boolean and excludes contextual/role_minutes.")
    if team_form and training_seasons is None:
        raise ValueError("Team form requires an explicit training-season allowlist.")
    if (
        team_form
        and isinstance(training_seasons, Sequence)
        and LOCKED_OUTCOME_SEASON in training_seasons
    ):
        raise ValueError("Team form cannot read the locked 2025-26 outcome population.")
    if manager_words is not None and not contextual:
        raise ValueError("Manager context requires the contextual candidate.")
    season = infer_season(snapshot)
    inputs = read_inputs(snapshot, season=season)
    cutoff = pd.Timestamp(inputs.captured_at_utc)
    first = int(inputs.deadline.gameweek)
    archives, include_current = _training_sources(training_seasons, season)
    if role_minutes and (archives != ("2022-23", "2023-24", "2024-25") or not include_current):
        raise ValueError(
            "Joint role minutes require exactly 2022-23, 2023-24, 2024-25 and the captured season."
        )
    if team_form and not set(archives) <= set(TEAM_FORM_ARCHIVE_SEASONS):
        raise ValueError(
            "Team form may select only 2022-23, 2023-24, 2024-25 and the captured season."
        )
    history = (
        archive_history(archive_root)
        if training_seasons is None
        else archive_history(archive_root, seasons=archives)
        if archives
        else pd.DataFrame()
    )
    if not history.empty:
        history = history.loc[
            (history.season < season) & (history.kickoff + pd.Timedelta(hours=3) < cutoff)
        ]
    if include_current:
        current = captured_history(snapshot, season=season, gameweek=first)
        if not current.empty:
            history = pd.concat([history, current], ignore_index=True)
    if history.empty:
        raise ValueError("The selected training seasons contain no usable history.")
    prior_season = (
        str(history.season.min()) if role_minutes or team_form else next(iter(ARCHIVE_SEASONS), "")
    )
    training = (
        causal_training(history, prior_only_season=prior_season, team_form=True)
        if team_form
        else causal_training(history, prior_only_season=prior_season)
        if role_minutes
        else causal_training(history)
    )
    model = (
        TeamFormFootballModel(training, history, cutoff=cutoff)
        if team_form
        else ContextualFootballModel(training, history, cutoff=cutoff)
        if contextual
        else RetainedHistoryRoleFootballModel(training, history, cutoff=cutoff)
        if retained_role_history
        else JointRoleFootballModel(training, history, cutoff=cutoff)
        if role_minutes
        else FixtureFootballModel(training, history, cutoff=cutoff)
    )
    boot = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    clubs = {t["id"]: t["code"] for t in boot["teams"]}
    player_clubs = {p["code"]: clubs[p["team"]] for p in boot["elements"]}
    roster = inputs.players.copy()
    roster["club"] = roster.player_id.map(player_clubs)
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
    context_audit: list[dict[str, Any]] = []
    takers = (
        captured_taker_priorities(snapshot.payloads[BOOTSTRAP_PAYLOAD])
        if contextual or role_minutes
        else None
    )
    if contextual:
        assert takers is not None
        roster = roster.merge(
            takers,
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
            fixture_calendar=calendar,
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
    for prior in archives:
        for name in ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv"):
            path = archive_root / "data" / prior / name
            hashes[f"{prior}/{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    document = {
        "contract_version": ARTIFACT_CONTRACT,
        "model_version": TEAM_FORM_MODEL_VERSION
        if team_form
        else CONTEXTUAL_MODEL_VERSION
        if contextual
        else JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION
        if retained_role_history
        else JOINT_ROLE_MODEL_VERSION
        if role_minutes
        else FOOTBALL_MODEL_VERSION,
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
    if training_seasons is not None:
        document["training_selection"] = {
            "contract_version": "football_training_selection_v1",
            "allowed_seasons": sorted(training_seasons),
            "archive_seasons_read": list(archives),
            "captured_history_included": include_current,
            "captured_history_season": season if include_current else None,
            "prior_only_seasons": [prior_season] if prior_season in set(history.season) else [],
            "history_rows_by_season": _season_counts(history),
            "supervised_rows_by_season": _season_counts(training),
        }
    if team_form:
        document["feature_contract_version"] = TEAM_FORM_FEATURE_VERSION
        document["team_form_metadata"] = team_form_metadata()
        document["training_selection"]["prior_policy"] = "first_selected_usable_season_prior_only"
    if role_minutes:
        assert isinstance(model, JointRoleFootballModel)
        document["role_metadata"] = model.role_metadata
        document["training_selection"]["prior_policy"] = "first_selected_usable_season_prior_only"
        document["limitations"].append(
            "Start and substitute probabilities are development estimates, "
            "not independently calibrated."
        )
    if contextual:
        document["availability_application"] = "before_team_shares_v1"
        document["projection_contract"] = horizon.contract_version
        document["manager_context"] = context_audit
    if contextual or role_minutes:
        assert takers is not None
        # Source facts only: ranks do not identify event-channel intensities and
        # must not change the joint role model's roster, features or predictions.
        document["taker_priorities"] = {
            "source_snapshot_id": inputs.snapshot_id,
            "captured_at_utc": inputs.captured_at_utc,
            "scoring_effect": "none_until_event_channel_rates_are_validated",
            "rows": [
                {
                    "player_id": int(row["player_id"]),
                    **{key: None if pd.isna(row[key]) else int(row[key]) for key in TAKER_FIELDS},
                }
                for row in (roster[["player_id", *TAKER_FIELDS]] if contextual else takers).to_dict(
                    "records"
                )
            ],
        }
        if role_minutes:
            document["limitations"].append(
                "Captured penalty and set-piece priorities are source facts only; "
                "separate event-channel rates are not estimated."
            )
    if contextual:
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
    training_seasons: Sequence[str] | None = None,
    role_minutes: bool = False,
    retained_role_history: bool = False,
    team_form: bool = False,
) -> dict[str, Any]:
    document, _components, _inputs = _forecast_and_components(
        snapshot,
        archive_root,
        contextual=contextual,
        manager_words=manager_words,
        gameweeks=gameweeks,
        training_seasons=training_seasons,
        role_minutes=role_minutes,
        retained_role_history=retained_role_history,
        team_form=team_form,
    )
    return document


def produce_football_components(
    snapshot: CapturedSnapshot,
    archive_root: Path,
    *,
    gameweeks: Sequence[int] | None = None,
    training_seasons: Sequence[str] | None = None,
    role_minutes: bool = False,
    retained_role_history: bool = False,
    team_form: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The served football document and per-fixture components, from one producer call.

    The first document is exactly what ``produce_football_forecast`` returns for the same
    arguments. The second is ``football_fixture_components_v1``: every scheduled player-fixture's
    model outputs, bound to the first by its fingerprint. The capture's availability is carried
    once in its header, as the multiplier ``apply_availability`` gives each player and the rule
    that gave it, and applied to no row. Both v1 and joint role minutes retain this rule;
    the contextual model conditions its team
    components on availability and is not this contract.
    """

    document, components, inputs = _forecast_and_components(
        snapshot,
        archive_root,
        contextual=False,
        manager_words=None,
        gameweeks=gameweeks,
        training_seasons=training_seasons,
        role_minutes=role_minutes,
        retained_role_history=retained_role_history,
        team_form=team_form,
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
    if "training_selection" in document:
        companion["training_selection"] = json.loads(json.dumps(document["training_selection"]))
    if "role_metadata" in document:
        companion["role_metadata"] = json.loads(json.dumps(document["role_metadata"]))
    if "team_form_metadata" in document:
        companion["team_form_metadata"] = json.loads(json.dumps(document["team_form_metadata"]))
        companion["feature_contract_version"] = document["feature_contract_version"]
    companion["fingerprint"] = forecast_digest(companion)
    return document, companion
