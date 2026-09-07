"""A replaceable score view, never an immutable ledger outcome.

All source bytes come from the one verified capture supplied to the site builder.
The live endpoint has no embedded week: its capture payload name is the week evidence.
No older capture is searched when that payload is missing.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from squadopt.application.views import JsonValue, _View
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, payload_checksum
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    FPL_LIVE_SOURCE,
    fpl_live_event_points,
    gameweek_deadlines,
    live_payload,
    player_codes,
)
from squadopt.data.timestamps import as_instant
from squadopt.live.ledger import LedgerEntry, LedgerError, score_named_eleven

LIVE_SCORE_CONTRACT_VERSION = "live_score_v1"


def live_score_schema() -> dict[str, JsonValue]:
    """The separate, closed wire contract, also shipped with each site build."""
    properties: dict[str, JsonValue] = {
        "season": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
        "gameweek": {"type": "integer", "minimum": 1},
        "decision_snapshot_id": {"type": "string"},
        "prediction_fingerprint": {"type": "string"},
        "status": {"enum": ["available", "unavailable"]},
        "reason": {"type": ["string", "null"]},
        "source_snapshot_id": {"type": ["string", "null"]},
        "captured_at_utc": {"type": ["string", "null"], "format": "date-time"},
        **{
            key: {"type": ["number", "null"]}
            for key in ("named_score", "transfer_hit_points", "net_score")
        },
        "fixtures_finished": {"type": ["integer", "null"], "minimum": 0},
        "fixtures_total": {"type": ["integer", "null"], "minimum": 1},
        "bonus_confirmed": {"type": ["boolean", "null"]},
    }
    values = (
        "named_score",
        "transfer_hit_points",
        "net_score",
        "fixtures_finished",
        "fixtures_total",
        "bonus_confirmed",
    )
    payload: dict[str, JsonValue] = {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
        "allOf": [
            {
                "if": {"properties": {"status": {"const": "available"}}},
                "then": {
                    "properties": {
                        **{
                            key: {"not": {"type": "null"}}
                            for key in (*values, "source_snapshot_id", "captured_at_utc")
                        },
                        "reason": {"type": "null"},
                        "transfer_hit_points": {"minimum": 0},
                    }
                },
                "else": {
                    "properties": {
                        **{key: {"type": "null"} for key in values},
                        "reason": {"type": "string"},
                    }
                },
            }
        ],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": LIVE_SCORE_CONTRACT_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_version", "generated_at_utc", "payload"],
        "properties": {
            "contract_version": {"const": LIVE_SCORE_CONTRACT_VERSION},
            "generated_at_utc": {"type": "string", "format": "date-time"},
            "payload": payload,
        },
    }


@dataclass(frozen=True, slots=True)
class LiveScoreView(_View):
    season: str
    gameweek: int
    decision_snapshot_id: str
    prediction_fingerprint: str
    status: str = "unavailable"
    reason: str | None = "missing_capture"
    source_snapshot_id: str | None = None
    captured_at_utc: str | None = None
    named_score: float | None = None
    transfer_hit_points: float | None = None
    net_score: float | None = None
    fixtures_finished: int | None = None
    fixtures_total: int | None = None
    bonus_confirmed: bool | None = None


def live_score_view(
    entry: LedgerEntry, snapshot: CapturedSnapshot | None, *, generated_at_utc: str
) -> LiveScoreView:
    """Score a frozen decision through the existing named-XI rule, without writes."""
    decision = entry.decision
    view = LiveScoreView(
        season=entry.season,
        gameweek=entry.gameweek,
        decision_snapshot_id=str(decision["snapshot_id"]),
        prediction_fingerprint=str(decision["prediction_fingerprint"]),
    )
    if entry.outcome is not None:
        return replace(view, reason="settled")
    if snapshot is None:
        return view
    metadata = snapshot.metadata
    view = replace(
        view,
        source_snapshot_id=metadata.snapshot_id,
        captured_at_utc=metadata.captured_at_utc,
    )
    required = (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload(entry.gameweek))
    if any(name not in snapshot.payloads for name in required):
        return replace(view, reason="missing_payload")
    if metadata.source != FPL_LIVE_SOURCE or any(
        payload_checksum(snapshot.payloads[name]) != metadata.checksums.get(name)
        for name in required
    ):
        return replace(view, reason="capture_mismatch")
    try:
        bootstrap = snapshot.payloads[BOOTSTRAP_PAYLOAD]
        deadlines = gameweek_deadlines(bootstrap)
        first_year = as_instant(min(d.deadline_utc for d in deadlines)).year
        if entry.season != f"{first_year}-{(first_year + 1) % 100:02d}":
            return replace(view, reason="season_mismatch")
        target = next((d for d in deadlines if d.gameweek == entry.gameweek), None)
        if target is None or as_instant(target.deadline_utc) != as_instant(
            str(decision["deadline_utc"])
        ):
            return replace(view, reason="gameweek_mismatch")
        captured = as_instant(metadata.captured_at_utc)
        if captured < as_instant(target.deadline_utc):
            return replace(view, reason="before_deadline")
        if captured > as_instant(generated_at_utc):
            return replace(view, reason="capture_mismatch")
        live = fpl_live_event_points(
            snapshot.payloads[live_payload(entry.gameweek)],
            snapshot.payloads[FIXTURES_PAYLOAD],
            gameweek=entry.gameweek,
            source_snapshot_id=metadata.snapshot_id,
        )
        codes = player_codes(bootstrap)
        points = {
            codes[element]: float(value)
            for element, value in live.points_by_player.items()
            if element in codes
        }
        try:
            score = score_named_eleven(decision, points)
        except LedgerError:
            return replace(view, reason="missing_players")
        transfers = decision.get("transfers")
        hit = float(transfers["transfer_hit_points"]) if isinstance(transfers, Mapping) else 0.0
        if not math.isfinite(hit) or hit < 0:
            return replace(view, reason="invalid_decision")
        return replace(
            view,
            status="available",
            reason=None,
            named_score=score,
            transfer_hit_points=hit,
            net_score=score - hit,
            fixtures_finished=live.fixtures_finished,
            fixtures_total=live.fixtures_total,
            bonus_confirmed=live.bonus_confirmed,
        )
    except (DataError, ValueError, KeyError, TypeError):
        return replace(view, reason="invalid_payload")
