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
from typing import Any, Final, cast

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
from squadopt.evaluation.live_series import (
    BACKTEST_PRECISION_ARTIFACT,
    BACKTEST_PRECISION_FLOOR_POINTS,
    DEFAULT_DETECTION_POLICY,
    MINIMUM_WEEKS_FOR_CORRELATION,
    DetectionPolicy,
    LiveSeriesPower,
    LiveSeriesReading,
    MemberWeekComparison,
    read_live_series,
)
from squadopt.evaluation.models import (
    EvaluationValidationError,
    FrozenSquadDecision,
    ScoringPolicy,
)
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.live.recommendation import infer_season

CONTRACT_VERSION = "weekly_suggestion_history_v1"
SUPPORTED_LEAGUE_ID = 352490

# The horizon handoff, specified in docs/contracts/member_week_horizon_v1.md. The reader
# rejects the whole document when any one of these disagrees with the scoreboard it is shown
# beside, and reports no reason for the rejection, so each constant is the contract's own
# spelling rather than a description of it.
MEMBER_WEEK_HORIZON_CONTRACT_VERSION: Final = "member_week_horizon_v1"
SERIES_HORIZON_FILE: Final = "series-horizon.json"
# The contract fixes these two. They are promises about what produced the numbers, so the
# document builder refuses a series that does not carry them instead of stamping them over
# one that was built some other way. They are compared against, never assigned from.
CONTRACT_SCORING_BASIS: Final = ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2.value
CONTRACT_POPULATION: Final = "recorded_member_suggestions_vs_actual"
_MEASUREMENT_ARTIFACT = re.compile(r"docs/[a-z0-9_-]+\.json")
# A recorded advice digest is a lowercase sha256 hexdigest. Checking it here rather than
# trusting it keeps a malformed key out of a set the reader compares for exact equality.
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


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
    root: Path, *, season: str, gameweek: int, entry_id: int, deadline_utc: str
) -> dict[str, Any] | None:
    """Select the latest recorded publication, checking both clocks and all identities.

    This intentionally does not change the legacy capture-ordered reader's semantics.
    An unreadable candidate is refused instead of silently falling back to an older one.
    """
    deadline = as_instant(normalize_utc_timestamp(deadline_utc, label="deadline_utc"))
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
        if capture.instant < deadline and published < deadline:
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


#: The basis ``score_recorded_advice`` produces, named where the scorer is chosen rather than
#: at the publication that quotes it. That function completes the eleven from the recorded
#: bench order and falls back to the recorded vice-captain, and refuses a record that froze
#: neither, so a number on the named-eleven basis cannot enter this series and be relabelled
#: as this one. If this function ever selects between scorers, this stops being a constant
#: and becomes something it returns.
RECORDED_ADVICE_SCORING_BASIS: Final = ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2.value


def score_recorded_advice(
    record: Mapping[str, Any], advice: Mapping[str, Any], outcomes: pd.DataFrame
) -> tuple[SuggestedScore, tuple[PlayerReview, ...]]:
    """Use the existing official autosub/captain scorer, then known chip/hit adjustments.

    One scorer, unconditionally: the result is on ``RECORDED_ADVICE_SCORING_BASIS`` and on no
    other. A record without a full recorded bench order and a starting vice-captain has
    nothing to complete the eleven with, and is refused below rather than scored on the
    named-eleven basis and carried onwards under this one.
    """
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


def review_member_weeks(
    *,
    record_root: Path,
    snapshot_root: Path,
    as_of_snapshot: CapturedSnapshot,
    season: str,
    league_id: int,
    entry_ids: Sequence[int],
) -> dict[int, tuple[WeekReview, ...]]:
    """Review every recorded week of every member, newest gameweek first, from evidence only.

    This is the body the publisher serializes, so the document and any later reading of the
    same weeks are the same reviews rather than two walks that could drift apart.
    """
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
    reviews: dict[int, tuple[WeekReview, ...]] = {}
    for entry_id in entry_ids:
        _identifier(entry_id)
        if entry_id in reviews:
            continue
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
        reviews[entry_id] = tuple(weeks)
    return reviews


#: The population ``settled_member_week_comparisons`` selects: members who have both a
#: recorded suggestion and a settled actual score, and no others. Named at the filter that
#: produces it so a publication can state what it is holding rather than assert it.
SETTLED_COMPARISON_POPULATION: Final = "recorded_member_suggestions_vs_actual"


def settled_member_week_comparisons(
    reviews: Mapping[int, Sequence[WeekReview]], *, season: str
) -> tuple[MemberWeekComparison, ...]:
    """Keep the member-weeks that actually settled into a comparison, and only those.

    An unsettled week, a refused week and a settled week whose actual score is unknown each
    contribute nothing. An unknown actual score is not a difference of zero.

    The same filter decides what is measured and what is named, so the published key set and
    the measured rows are one list rather than two that could drift. The reader applies the
    matching filter to the histories it loaded; a week either enters both sides or neither.
    """
    comparisons = []
    for entry_id, weeks in reviews.items():
        for week in weeks:
            if week.status != "available" or week.actual is None or week.net_difference is None:
                continue
            if week.advice_sha256 is None or week.outcome_snapshot_id is None:
                raise SuggestionEvaluationError(
                    "A settled member-week must name the advice it scored and the capture it "
                    f"settled on; gameweek {week.gameweek} for member {entry_id} names neither."
                )
            if not _SHA256_HEX.fullmatch(week.advice_sha256):
                raise SuggestionEvaluationError(
                    f"Recorded advice digest {week.advice_sha256!r} is not a sha256 hexdigest."
                )
            comparisons.append(
                MemberWeekComparison(
                    season=season,
                    gameweek=week.gameweek,
                    entry_id=entry_id,
                    difference=week.net_difference,
                    advice_sha256=week.advice_sha256,
                    outcome_snapshot_id=week.outcome_snapshot_id,
                )
            )
    return tuple(comparisons)


def series_horizon_document(
    reading: LiveSeriesReading,
    *,
    season: str,
    league_id: int,
    scoring_basis: str,
    population: str,
    measurement_artifact: str = BACKTEST_PRECISION_ARTIFACT,
    effect: float = BACKTEST_PRECISION_FLOOR_POINTS,
) -> dict[str, Any] | None:
    """Build the member_week_horizon_v1 handoff, or return None when there is no horizon.

    The basis and the population are arguments rather than constants because the contract
    fixes both to one value each, and a fixed value in a schema is a promise about what
    produced the numbers. A series measured on any other basis or over any other population
    is refused here instead of being stamped with the two constants and published as
    something it is not.

    None is the whole answer to a refusal. The reading refuses below two settled weeks,
    below any within-week replication and on a record with no variation, and it carries no
    correlation to publish in those states. The page already renders "not yet" for an absent
    document, so the true statement is the absent document; a document built from a
    substituted correlation would be a claim, and zero, the only substitution available, is
    the most optimistic one there is.

    ``required_week_clusters`` is floored at the instrument's own two-week minimum. A
    clustered reading does not exist below two settled weeks, so an arithmetic target of one
    is not a count anyone could measure at, and the reader refuses anything under two. The
    floor applies to the published target only; the estimator's arithmetic is unchanged.
    """
    if scoring_basis != CONTRACT_SCORING_BASIS or population != CONTRACT_POPULATION:
        raise SuggestionEvaluationError(
            f"{MEMBER_WEEK_HORIZON_CONTRACT_VERSION} fixes the basis to "
            f"{CONTRACT_SCORING_BASIS!r} over {CONTRACT_POPULATION!r}; a series measured as "
            f"{scoring_basis!r} over {population!r} would be mislabelled by those constants."
        )
    if not _MEASUREMENT_ARTIFACT.fullmatch(measurement_artifact):
        raise SuggestionEvaluationError(
            f"The measurement artifact {measurement_artifact!r} is not a committed "
            "docs/<slug>.json record the reader will accept."
        )
    if not isinstance(reading, LiveSeriesPower):
        return None
    horizon = reading.weeks_to_detect(effect)
    return {
        "contract_version": MEMBER_WEEK_HORIZON_CONTRACT_VERSION,
        "season": season,
        "league_id": league_id,
        "scoring_basis": scoring_basis,
        "population": population,
        # The committed record the target effect and the two error rates come from. The
        # reader validates the path and never fetches it, so the producer is what stands
        # behind it being a real, indexed measurement.
        "measurement_artifact": measurement_artifact,
        # Published although nothing renders it: it is the entire distance between this
        # target and the one an independence assumption would have produced, and it cannot be
        # recovered later from a record that has since grown. Dropping it also pins the page
        # at "unknown" with no visible cause, because the reader rejects the whole document.
        "within_week_correlation": reading.within_week_correlation,
        "required_week_clusters": max(MINIMUM_WEEKS_FOR_CORRELATION, horizon.total_weeks),
        "member_week_keys": list(reading.member_week_keys),
    }


def publish_series_horizon(
    reading: LiveSeriesReading,
    *,
    season: str,
    league_id: int,
    scoring_basis: str,
    population: str,
    out_dir: Path,
    measurement_artifact: str = BACKTEST_PRECISION_ARTIFACT,
    effect: float = BACKTEST_PRECISION_FLOOR_POINTS,
) -> Path | None:
    """Write the horizon handoff, or remove a stale one and publish nothing.

    A previous week's document names a key set this publication no longer measures, which the
    reader would reject anyway; removing it keeps a target that nothing supports from sitting
    on disk beside the histories that replaced it.
    """
    path = out_dir / SERIES_HORIZON_FILE
    document = series_horizon_document(
        reading,
        season=season,
        league_id=league_id,
        scoring_basis=scoring_basis,
        population=population,
        measurement_artifact=measurement_artifact,
        effect=effect,
    )
    if document is None:
        path.unlink(missing_ok=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def live_series_reading(
    *,
    record_root: Path,
    snapshot_root: Path,
    as_of_snapshot: CapturedSnapshot,
    season: str,
    league_id: int,
    entry_ids: Sequence[int],
    policy: DetectionPolicy = DEFAULT_DETECTION_POLICY,
) -> LiveSeriesReading:
    """Read how much the settled record can support, from the same reviews we publish.

    This walks the record itself, so it is the entry point for a reader asking the question
    outside a publication. The weekly publication does not call it; it reads the reviews it
    already has. Either way the reading writes nothing and says nothing about which of the
    two columns scores better, and neither does the document built from it.
    """
    reviews = review_member_weeks(
        record_root=record_root,
        snapshot_root=snapshot_root,
        as_of_snapshot=as_of_snapshot,
        season=season,
        league_id=league_id,
        entry_ids=entry_ids,
    )
    return read_live_series(settled_member_week_comparisons(reviews, season=season), policy=policy)


def publish_suggestion_histories(
    *,
    record_root: Path,
    snapshot_root: Path,
    as_of_snapshot: CapturedSnapshot,
    season: str,
    league_id: int,
    entry_ids: Sequence[int],
    out_dir: Path,
    policy: DetectionPolicy = DEFAULT_DETECTION_POLICY,
) -> tuple[Path, ...]:
    """Publish member-safe derived documents from existing verified, bounded captures.

    Two documents come out of one walk: each member's history, and the horizon those same
    member-weeks can support. They are published together because the reader compares the
    horizon's key set against the keys it builds from these very histories, and two separate
    walks could return two sets that no reader could reconcile. A record that supports no
    horizon publishes histories and no horizon file.
    """
    reviews = review_member_weeks(
        record_root=record_root,
        snapshot_root=snapshot_root,
        as_of_snapshot=as_of_snapshot,
        season=season,
        league_id=league_id,
        entry_ids=entry_ids,
    )
    written = []
    for entry_id in entry_ids:
        document = {
            "contract_version": CONTRACT_VERSION,
            "generated_at_utc": as_of_snapshot.metadata.captured_at_utc,
            "payload": {
                "league_id": league_id,
                "entry_id": entry_id,
                "season": season,
                "as_of_snapshot_id": as_of_snapshot.metadata.snapshot_id,
                "weeks": [asdict(week) for week in reviews[entry_id]],
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
    horizon = publish_series_horizon(
        read_live_series(settled_member_week_comparisons(reviews, season=season), policy=policy),
        season=season,
        league_id=league_id,
        # Both read from where they were produced: the scorer that ran, and the filter that
        # chose the rows. Neither is the contract's constant repeated at the call site.
        scoring_basis=RECORDED_ADVICE_SCORING_BASIS,
        population=SETTLED_COMPARISON_POPULATION,
        out_dir=out_dir,
    )
    if horizon is not None:
        written.append(horizon)
    return tuple(written)
