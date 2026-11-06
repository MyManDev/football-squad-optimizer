"""Join retained requests and captures for the existing settled-history scorer."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any

from squadopt.application.advice_record import _scoring_document
from squadopt.application.weekly_suggestion_eval import score_selected_week
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, POSITION_CODES, gameweek_deadlines
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live.recommendation import infer_season


def requested_week(
    exported: Mapping[str, Any],
    *,
    captures: Sequence[CapturedSnapshot],
    as_of: CapturedSnapshot,
) -> dict[str, Any] | None:
    """Use the latest completed plain answer before the captured FPL deadline.

    Equally recent but different plans are ambiguous. Nothing is manufactured when
    no successful request exists. This returns a separate product-history row; it
    never enters the weekly publication record store or its research population.
    """
    season = exported["season"]
    gameweek, entry_id = exported["gameweek"], exported["entry_id"]
    if exported.get("format") != "requested_advice_export_v1" or infer_season(as_of) != season:
        raise ValueError("Requested history and its outcome anchor must identify one season.")
    if any(type(value) is not int or value < 1 for value in (gameweek, entry_id)):
        raise ValueError("Requested history requires positive entry and gameweek identities.")
    deadlines = {
        row.gameweek: row.deadline_utc
        for row in gameweek_deadlines(as_of.payloads[BOOTSTRAP_PAYLOAD])
    }
    deadline = deadlines.get(gameweek)
    if deadline is None or as_instant(deadline) != as_instant(exported["deadline_utc"]):
        raise ValueError("The export deadline differs from the captured FPL event.")
    cutoff = as_instant(as_of.metadata.captured_at_utc)
    bounded = [
        capture
        for capture in captures
        if as_instant(capture.metadata.captured_at_utc) <= cutoff
        and infer_season(capture) == season
    ]
    by_id = {capture.metadata.snapshot_id: capture for capture in bounded}
    candidates: list[tuple[datetime, str, str, dict[str, Any]]] = []
    for row in exported["records"]:
        raw = row["response_json"].encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != row["response_sha256"]:
            raise ValueError("Requested history response digest differs.")
        if not isinstance(row["cache_key"], str) or not re.fullmatch(
            r"[a-f0-9]{64}", row["cache_key"]
        ):
            raise ValueError("Requested history has no complete answer identity.")
        document = json.loads(raw)
        payload = document["payload"]
        spec = row["request"]
        context = spec["context"]
        expected = (season, gameweek, entry_id)
        if (
            (payload.get("season"), payload.get("gameweek"), payload.get("entry_id")) != expected
            or (context.get("season"), context.get("gameweek"), spec.get("entry_id")) != expected
            or payload.get("league_id") != spec.get("league_id")
            or payload.get("source_snapshot_id") != context.get("capture_snapshot_id")
            or document.get("source_kind") != "live"
            or document.get("contract_version") != context.get("advice_contract_version")
            or spec.get("strategy") != "saf-puan"
            or spec.get("window") != 1
            or spec.get("rival_entry_id") is not None
            or set(spec.get("switches", {})) - {"public_entry"}
            or payload.get("mode") != "saf-puan"
            or payload.get("window") != 1
            or any(key in payload for key in ("evidence", "top100", "preferences", "plan_weeks"))
        ):
            raise ValueError("Requested history carries a different answer or request.")
        capture = by_id.get(context["capture_snapshot_id"])
        if capture is None:
            raise ValueError("The decision capture is absent from this history snapshot.")
        completed = normalize_utc_timestamp(row["completed_at_utc"], label="completed_at_utc")
        captured = capture.metadata.captured_at_utc
        if as_instant(document["generated_at_utc"]) != as_instant(captured):
            raise ValueError("The response clock differs from the decision capture.")
        if not as_instant(captured) <= as_instant(completed) < as_instant(deadline):
            raise ValueError("The request did not complete before the captured deadline.")
        if as_instant(completed) > cutoff:
            continue
        decision_deadlines = {
            event.gameweek: event.deadline_utc
            for event in gameweek_deadlines(capture.payloads[BOOTSTRAP_PAYLOAD])
        }
        if gameweek not in decision_deadlines or as_instant(
            decision_deadlines[gameweek]
        ) != as_instant(deadline):
            raise ValueError("Decision and outcome captures disagree on the deadline.")
        players = _players(payload, capture)
        advice = _scoring_document(payload, strategy="saf-puan", window=1, rival_entry_id=None)
        semantic = json.dumps(
            {k: v for k, v in payload.items() if k != "league_id"}, sort_keys=True
        )
        candidates.append(
            (
                as_instant(completed),
                row["cache_key"],
                semantic,
                {
                    "record": {"players": players},
                    "advice": advice,
                    "base": {
                        "gameweek": gameweek,
                        "deadline_utc": deadline,
                        "advice_snapshot_id": capture.metadata.snapshot_id,
                        "advice_captured_at_utc": captured,
                        "advice_generated_at_utc": completed,
                        "advice_sha256": advice["advice_sha256"],
                        "expected_own_points": advice["expected_own_points"],
                    },
                },
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected_time, key, semantic, selected = candidates[-1]
    if any(stamp == selected_time and meaning != semantic for stamp, _, meaning, _ in candidates):
        raise ValueError("Equally recent requested answers disagree; no plan can be selected.")
    reviewed = score_selected_week(
        selected["record"],
        selected["advice"],
        base=selected["base"],
        captures=bounded,
        gameweek=gameweek,
        entry_id=entry_id,
        deadline_utc=deadline,
    )
    # Dataclass tuples become JSON arrays, including nested actual-transfer details.
    result: dict[str, Any] = json.loads(
        json.dumps(
            {**asdict(reviewed), "advice_source": "requested_server", "request_cache_key": key},
            allow_nan=False,
        )
    )
    return result


def _players(payload: Mapping[str, Any], capture: CapturedSnapshot) -> dict[str, Any]:
    starters, bench = payload.get("starting_xi"), payload.get("bench")
    if (
        not isinstance(starters, list)
        or not isinstance(bench, list)
        or (len(starters), len(bench)) != (11, 4)
    ):
        raise ValueError("Requested history requires the complete eleven and bench.")
    roster = {
        row["code"]: POSITION_CODES.get(row.get("element_type"))
        for row in json.loads(capture.payloads[BOOTSTRAP_PAYLOAD])["elements"]
    }
    players = {}
    for row in (*starters, *bench):
        identifier, expected = row.get("player_id"), row.get("expected_points")
        if (
            type(identifier) is not int
            or identifier < 1
            or str(identifier) in players
            or row.get("position") not in ("GK", "DEF", "MID", "FWD")
            or roster.get(identifier) != row["position"]
            or not isinstance(row.get("name"), str)
            or not row["name"].strip()
            or (
                expected is not None
                and (type(expected) not in (int, float) or not math.isfinite(expected))
            )
        ):
            raise ValueError("Requested lineup metadata differs from the captured player roster.")
        players[str(identifier)] = dict(row)
    ids = {row["player_id"] for row in starters}
    for role in ("captain", "vice_captain"):
        if not isinstance(payload.get(role), dict) or payload[role].get("player_id") not in ids:
            raise ValueError("The recorded captain and vice-captain must start.")
    return players
