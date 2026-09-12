"""Read-only, settled evaluation of recorded member advice; never invokes a solver.

The archive proves recorded publication bytes, not that a member viewed or adopted them.
Both capture and recorded publication must precede the deadline. Scores are descriptive
counterfactuals; a difference against the member's actual score is not a causal gain.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from squadopt.application.advice_record import (
    MEMBER_ADVICE_RECORD_CONTRACT_VERSION,
    load_member_advice_record,
    recorded_captures,
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FPL_LIVE_SOURCE,
    entry_history_payload,
    fpl_entry_history_points,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.evaluation.models import EvaluationValidationError, FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.live.recommendation import infer_season

CONTRACT_VERSION = "weekly_suggestion_history_v1"
SUPPORTED_LEAGUE_ID = 352490


class SuggestionEvaluationError(DataError):
    """A historical result cannot be supported by its recorded inputs."""


@dataclass(frozen=True, slots=True)
class ActualScore:
    gross_points: float
    transfer_hit_points: float
    net_points: float


@dataclass(frozen=True, slots=True)
class SuggestedScore:
    gross_points: float
    transfer_hit_points: float
    net_points: float
    captain_bonus_points: float
    autosub_points: float
    chip: str | None


@dataclass(frozen=True, slots=True)
class PlayerReview:
    player_id: int
    name: str
    position: str
    role: str
    captain: bool
    vice_captain: bool
    expected_points: float | None
    realized_points: float
    minutes: int
    multiplier: int
    counted_points: float
    forecast_error: float | None


@dataclass(frozen=True, slots=True)
class WeekReview:
    gameweek: int
    status: str
    reason: str | None
    deadline_utc: str | None = None
    advice_snapshot_id: str | None = None
    advice_captured_at_utc: str | None = None
    advice_generated_at_utc: str | None = None
    advice_sha256: str | None = None
    outcome_snapshot_id: str | None = None
    outcome_captured_at_utc: str | None = None
    expected_own_points: float | None = None
    suggested: SuggestedScore | None = None
    actual: ActualScore | None = None
    actual_reason: str | None = None
    net_difference: float | None = None
    players: tuple[PlayerReview, ...] = ()


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SuggestionEvaluationError("Expected a finite recorded number.")
    return float(value)


def _identifier(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SuggestionEvaluationError("Expected a positive integer identity.")
    return value


def _ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise SuggestionEvaluationError("Missing recorded lineup.")
    return tuple(_identifier(item) for item in value)


def select_record(
    root: Path,
    *,
    season: str,
    gameweek: int,
    entry_id: int,
    deadline_utc: str,
    as_of_utc: str | None = None,
) -> dict[str, Any] | None:
    """Select the latest recorded publication, checking both clocks and all identities.

    This intentionally does not change the legacy capture-ordered reader's semantics.
    An unreadable candidate is refused instead of silently falling back to an older one.
    """
    deadline = as_instant(normalize_utc_timestamp(deadline_utc, label="deadline_utc"))
    cutoff = as_instant(as_of_utc) if as_of_utc is not None else None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for capture in recorded_captures(root, season, gameweek, entry_id):
        record = load_member_advice_record(root, season, gameweek, entry_id, capture.snapshot_id)
        if (
            record.get("contract_version") != MEMBER_ADVICE_RECORD_CONTRACT_VERSION
            or record.get("season") != season
            or _identifier(record.get("gameweek")) != gameweek
            or _identifier(record.get("entry_id")) != entry_id
            or _identifier(record.get("league_id")) != SUPPORTED_LEAGUE_ID
            or record.get("player_id_space") != "fpl_element_code"
        ):
            raise SuggestionEvaluationError("Record identity does not match the requested member.")
        stamp = record.get("generated_at_utc")
        if not isinstance(stamp, str):
            raise SuggestionEvaluationError("Recorded publication time is missing.")
        published = as_instant(normalize_utc_timestamp(stamp, label="generated_at_utc"))
        if published < capture.instant:
            raise SuggestionEvaluationError("Recorded publication precedes its capture.")
        if (
            capture.instant < deadline
            and published < deadline
            and (cutoff is None or published <= cutoff)
        ):
            try:
                _advice(record)
            except SuggestionEvaluationError as error:
                if str(error) == "missing_advice":
                    continue
                raise
            candidates.append((published, record))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    if len(candidates) > 1 and candidates[-2][0] == candidates[-1][0]:
        raise SuggestionEvaluationError("ambiguous_record")
    return candidates[-1][1]


def score_recorded_advice(
    record: Mapping[str, Any], advice: Mapping[str, Any], outcomes: pd.DataFrame
) -> tuple[SuggestedScore, tuple[PlayerReview, ...]]:
    """Use the existing official autosub/captain scorer, then known chip/hit adjustments."""
    if advice.get("scoring_complete") is not True:
        raise SuggestionEvaluationError("incomplete_advice")
    starters, bench = _ids(advice.get("starting_xi")), _ids(advice.get("bench"))
    captain = _identifier(advice.get("captain"))
    vice = _identifier(advice.get("vice_captain"))
    if vice not in starters:
        raise SuggestionEvaluationError("Recorded vice-captain must start.")
    players = record.get("players")
    if not isinstance(players, dict):
        raise SuggestionEvaluationError("Recorded player metadata is missing.")
    metadata = [players[str(player)] for player in (*starters, *bench)]
    squad = pd.DataFrame(
        {"player_id": (*starters, *bench), "position": [row["position"] for row in metadata]}
    )
    decision = FrozenSquadDecision(squad, starters, bench, captain, vice)
    scored = score_frozen_squad_decision(decision, outcomes)
    rows = outcomes.to_dict("records")
    points = {int(row["player_id"]): float(row["total_points"]) for row in rows}
    minutes = {int(row["player_id"]): int(row["minutes"]) for row in rows}
    chip = advice.get("chip")
    if chip not in (None, "wildcard", "freehit", "bboost", "3xc"):
        raise SuggestionEvaluationError("unsupported_chip")
    hits = _number(advice.get("transfer_hit_points"))
    if hits < 0 or (chip in ("wildcard", "freehit") and hits != 0):
        raise SuggestionEvaluationError("Invalid recorded transfer charge.")
    counted = (
        set((*starters, *bench))
        if chip == "bboost"
        else set(cast(tuple[int, ...], scored.final_xi))
    )
    bonus_multiplier = 2 if chip == "3xc" else 1
    bonus = scored.captain_bonus_points * bonus_multiplier
    gross = sum(points[int(player)] for player in counted) + bonus
    reviews = []
    for player, meta in zip((*starters, *bench), metadata, strict=True):
        expected = meta.get("expected_points")
        expected = _number(expected) if expected is not None else None
        multiplier = int(player in counted) + (
            bonus_multiplier if player == scored.captain_bonus_player_id else 0
        )
        reviews.append(
            PlayerReview(
                player,
                str(meta["name"]),
                str(meta["position"]),
                "starter" if player in starters else "bench",
                player == captain,
                player == vice,
                expected,
                points[player],
                minutes[player],
                multiplier,
                points[player] * multiplier,
                points[player] - expected if expected is not None else None,
            )
        )
    return (
        SuggestedScore(
            gross,
            hits,
            gross - hits,
            bonus,
            0.0 if chip == "bboost" else scored.autosub_points,
            chip,
        ),
        tuple(reviews),
    )


def _advice(record: Mapping[str, Any]) -> Mapping[str, Any]:
    documents = record.get("advice")
    if not isinstance(documents, list):
        raise SuggestionEvaluationError("missing_advice")
    found = [
        doc
        for doc in documents
        if isinstance(doc, dict)
        and doc.get("strategy") == "saf-puan"
        and type(doc.get("window")) is int
        and doc["window"] == 1
        and doc.get("rival_entry_id") is None
    ]
    if not found:
        raise SuggestionEvaluationError("missing_advice")
    if len(found) != 1:
        raise SuggestionEvaluationError("ambiguous_advice")
    return found[0]


def evaluate_week(
    root: Path,
    *,
    season: str,
    gameweek: int,
    entry_id: int,
    deadline_utc: str,
    captures: Sequence[CapturedSnapshot],
) -> WeekReview:
    base: dict[str, Any] = {"gameweek": gameweek, "deadline_utc": deadline_utc}
    try:
        record = select_record(
            root, season=season, gameweek=gameweek, entry_id=entry_id, deadline_utc=deadline_utc
        )
        if record is None:
            return WeekReview(**base, status="unavailable", reason="no_pre_deadline_record")
        advice = _advice(record)
        base.update(
            advice_snapshot_id=record["capture"]["snapshot_id"],
            advice_captured_at_utc=record["capture"]["captured_at_utc"],
            advice_generated_at_utc=record["generated_at_utc"],
            advice_sha256=advice["advice_sha256"],
            expected_own_points=(
                None
                if advice.get("expected_own_points") is None
                else _number(advice["expected_own_points"])
            ),
        )
    except (DataError, ValueError, TypeError, KeyError, OSError) as error:
        reason = (
            str(error) if str(error) in ("ambiguous_record", "missing_advice") else "invalid_record"
        )
        return WeekReview(**base, status="unavailable", reason=reason)
    try:
        settled = [
            capture
            for capture in captures
            if as_instant(capture.metadata.captured_at_utc) >= as_instant(deadline_utc)
            and gameweek in scored_gameweeks(capture.payloads[BOOTSTRAP_PAYLOAD])
        ]
    except (DataError, ValueError, TypeError, KeyError):
        return WeekReview(**base, status="unavailable", reason="invalid_outcomes")
    if not settled:
        return WeekReview(**base, status="unsettled", reason="not_settled")
    with_outcomes = [capture for capture in settled if live_payload(gameweek) in capture.payloads]
    if not with_outcomes:
        return WeekReview(**base, status="unavailable", reason="missing_outcomes")
    capture = max(with_outcomes, key=lambda item: as_instant(item.metadata.captured_at_utc))
    base.update(
        outcome_snapshot_id=capture.metadata.snapshot_id,
        outcome_captured_at_utc=capture.metadata.captured_at_utc,
    )
    try:
        outcomes = live_event_outcomes(
            capture.payloads[live_payload(gameweek)],
            capture.payloads[BOOTSTRAP_PAYLOAD],
            gameweek=gameweek,
        )
        suggested, players = score_recorded_advice(record, advice, outcomes)
    except (DataError, EvaluationValidationError, ValueError, TypeError, KeyError) as error:
        reason = (
            str(error)
            if str(error) in ("incomplete_advice", "unsupported_chip")
            else "invalid_outcomes"
        )
        return WeekReview(**base, status="unavailable", reason=reason)
    actual = None
    actual_reason: str | None = "actual_score_missing"
    try:
        history = capture.payloads.get(entry_history_payload(entry_id))
        rows = fpl_entry_history_points(history, entry_id=entry_id) if history is not None else ()
        row = next((row for row in rows if row.gameweek == gameweek), None)
        if row is not None and row.transfer_cost is not None and row.transfer_cost >= 0:
            actual = ActualScore(
                float(row.points), float(row.transfer_cost), float(row.points - row.transfer_cost)
            )
            actual_reason = None
    except (DataError, ValueError, TypeError):
        actual_reason = "actual_score_invalid"
    return WeekReview(
        **base,
        status="available",
        reason=None,
        suggested=suggested,
        actual=actual,
        actual_reason=actual_reason,
        net_difference=suggested.net_points - actual.net_points if actual else None,
        players=players,
    )


def publish_suggestion_histories(
    *,
    record_root: Path,
    snapshot_root: Path,
    as_of_snapshot: CapturedSnapshot,
    season: str,
    league_id: int,
    entry_ids: Sequence[int],
    out_dir: Path,
) -> tuple[Path, ...]:
    """Publish member-safe derived documents from existing verified, bounded captures."""
    if league_id != SUPPORTED_LEAGUE_ID or not re.fullmatch(r"\d{4}-\d{2}", season):
        raise SuggestionEvaluationError("Only league 352490 and a valid season are supported.")
    if infer_season(as_of_snapshot) != season:
        raise SuggestionEvaluationError("The publication anchor belongs to another season.")
    cutoff = as_instant(as_of_snapshot.metadata.captured_at_utc)
    captures = []
    for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        captured = read_snapshot(snapshot_root, identifier)
        if (
            as_instant(captured.metadata.captured_at_utc) <= cutoff
            and infer_season(captured) == season
        ):
            captures.append(captured)
    deadlines = {
        row.gameweek: row.deadline_utc
        for row in gameweek_deadlines(as_of_snapshot.payloads[BOOTSTRAP_PAYLOAD])
    }
    written = []
    for entry_id in entry_ids:
        _identifier(entry_id)
        weeks = []
        for directory in sorted((record_root / season).glob("gw[0-9][0-9]"), reverse=True):
            if not (directory / f"entry-{entry_id}").is_dir():
                continue
            week = int(directory.name[2:])
            if week not in deadlines:
                weeks.append(WeekReview(week, "unavailable", "missing_deadline"))
            else:
                weeks.append(
                    evaluate_week(
                        record_root,
                        season=season,
                        gameweek=week,
                        entry_id=entry_id,
                        deadline_utc=deadlines[week],
                        captures=captures,
                    )
                )
        document = {
            "contract_version": CONTRACT_VERSION,
            "generated_at_utc": as_of_snapshot.metadata.captured_at_utc,
            "payload": {
                "league_id": league_id,
                "entry_id": entry_id,
                "season": season,
                "as_of_snapshot_id": as_of_snapshot.metadata.snapshot_id,
                "weeks": [asdict(week) for week in weeks],
            },
        }
        path = out_dir / "history" / f"{entry_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        written.append(path)
    return tuple(written)
