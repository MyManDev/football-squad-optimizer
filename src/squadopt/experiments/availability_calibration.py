"""Deadline-aligned, descriptive calibration of captured FPL availability fields."""

import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant


def availability_observations(
    snapshots: Iterable[CapturedSnapshot], *, season_of: Callable[[bytes], str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep every forecast capture, but join only checked post-deadline outcomes.

    The caller verifies capture digests. Missing status or stated values remain missing.
    Each capture's next-round value belongs exclusively to its published next event.
    """
    contexts: list[tuple[SnapshotMetadata, dict[str, Any], str]] = []
    exclusions: list[dict[str, Any]] = []
    outcomes: dict[tuple[str, int], tuple[Any, str, Any]] = {}
    for snapshot in snapshots:
        if BOOTSTRAP_PAYLOAD not in snapshot.payloads:
            exclusions.append(
                {"snapshot_id": snapshot.metadata.snapshot_id, "reason": "no_bootstrap"}
            )
            continue
        bootstrap_bytes = snapshot.payloads[BOOTSTRAP_PAYLOAD]
        bootstrap = json.loads(bootstrap_bytes)
        season = season_of(bootstrap_bytes)
        at = as_instant(snapshot.metadata.captured_at_utc)
        contexts.append(
            (
                snapshot.metadata,
                {
                    "events": bootstrap["events"],
                    "elements": [
                        {
                            key: player.get(key)
                            for key in ("code", "status", "chance_of_playing_next_round")
                        }
                        for player in bootstrap["elements"]
                    ],
                },
                season,
            )
        )
        for event in bootstrap["events"]:
            week = event["id"]
            if (
                week not in scored_gameweeks(bootstrap_bytes)
                or live_payload(week) not in snapshot.payloads
            ):
                continue
            if at <= as_instant(event["deadline_time"]):
                continue
            key = (season, week)
            candidate_key = (at, snapshot.metadata.snapshot_id)
            if key not in outcomes or candidate_key > outcomes[key][:2]:
                actual = live_event_outcomes(
                    snapshot.payloads[live_payload(week)], bootstrap_bytes, gameweek=week
                )
                if actual["player_id"].duplicated().any():
                    raise ValueError("Availability outcomes contain duplicate player codes.")
                minutes = actual.set_index("player_id")["minutes"]
                if minutes.isna().any() or (minutes < 0).any() or (minutes % 1 != 0).any():
                    raise ValueError(
                        "Availability outcomes need observed, non-negative whole minutes."
                    )
                outcomes[key] = (*candidate_key, minutes)
    rows: list[dict[str, Any]] = []
    for metadata, bootstrap, season in contexts:
        next_events = [event for event in bootstrap["events"] if event.get("is_next") is True]
        if len(next_events) != 1:
            exclusions.append(
                {"snapshot_id": metadata.snapshot_id, "reason": "no_unique_next_event"}
            )
            continue
        event = next_events[0]
        deadline = as_instant(event["deadline_time"])
        if as_instant(metadata.captured_at_utc) >= deadline:
            exclusions.append(
                {"snapshot_id": metadata.snapshot_id, "reason": "not_before_deadline"}
            )
            continue
        source = outcomes.get((season, event["id"]))
        seen: set[int] = set()
        for player in bootstrap["elements"]:
            code = player["code"]
            if isinstance(code, bool) or not isinstance(code, int) or code <= 0 or code in seen:
                raise ValueError("Availability captures need unique positive player codes.")
            seen.add(code)
            stated = player.get("chance_of_playing_next_round")
            if stated is not None and (
                isinstance(stated, bool) or not isinstance(stated, int) or not 0 <= stated <= 100
            ):
                raise ValueError("Invalid captured chance-of-playing value.")
            status = player.get("status")
            if status is not None and (not isinstance(status, str) or not status):
                raise ValueError("Invalid captured status flag.")
            observed = source is not None and code in source[2].index
            rows.append(
                {
                    "season": season,
                    "gameweek": event["id"],
                    "player_id": code,
                    "snapshot_id": metadata.snapshot_id,
                    "captured_at_utc": metadata.captured_at_utc,
                    "deadline_utc": event["deadline_time"],
                    "status": status,
                    "stated_value": stated,
                    "played": bool(source[2].loc[code] > 0)
                    if observed and source is not None
                    else None,
                    "outcome_snapshot_id": source[1] if source else None,
                    "missing_reason": None
                    if observed
                    else "player_outcome_missing"
                    if source
                    else "no_checked_outcome",
                }
            )
    return rows, exclusions


def _bins(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str | None, int | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["status"], row["stated_value"]].append(row)
    result: list[dict[str, Any]] = []
    for (status, stated), group in sorted(grouped.items(), key=lambda item: str(item[0])):
        observed = [row["played"] for row in group if row["played"] is not None]
        result.append(
            {
                "status": status,
                "stated_value": stated,
                "forecasts": len(group),
                "observed": len(observed),
                "played": sum(observed) if observed else None,
                "realized_rate": sum(observed) / len(observed) if observed else None,
            }
        )
    return result


def calibration_report(
    rows: Sequence[dict[str, Any]], exclusions: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Primary sampling is one last pre-deadline forecast per player and gameweek."""
    latest: dict[tuple[str, int, int], dict[str, Any]] = {}
    by_capture: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(
        rows, key=lambda item: (as_instant(item["captured_at_utc"]), item["snapshot_id"])
    ):
        latest[row["season"], row["gameweek"], row["player_id"]] = row
        by_capture[row["snapshot_id"]].append(row)
    primary = list(latest.values())
    observed = sum(row["played"] is not None for row in primary)
    return {
        "status": "measured" if observed else "insufficient_settled_pairs",
        "primary_sampling": (
            "latest pre-deadline capture per season/gameweek/player; no repeated-capture weighting"
        ),
        "captured_forecasts": len(rows),
        "unique_player_weeks": len(primary),
        "observed_player_weeks": observed,
        "bins": _bins(primary),
        "per_capture": [
            {"snapshot_id": name, "bins": _bins(group)}
            for name, group in sorted(by_capture.items())
        ],
        "excluded_captures": list(exclusions),
        "interpretation": (
            "descriptive empirical rates; missing stated values are not zero or one hundred"
        ),
    }
