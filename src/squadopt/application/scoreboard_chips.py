"""Read recorded chip alternatives into the scoreboard; never solve retrospectively."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.application.chip_contract import validate_chip_recommendations
from squadopt.application.scoreboard_diagnostics import score_recorded_decision
from squadopt.application.weekly_suggestion_eval import select_record
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.live import infer_season


def recorded_chip_rows(
    root: Path,
    *,
    snapshot: CapturedSnapshot,
    snapshots: Sequence[CapturedSnapshot],
    entry_ids: Sequence[int],
) -> dict[int, list[dict[str, Any]]]:
    """Index by the week advice was issued; outcome names its own chip gameweek.

    Each source week/member is read once, and each settled event is decoded at most
    once. Missing records, unplayed alternatives and future outcomes remain null.
    """
    season = infer_season(snapshot)
    cutoff = as_instant(snapshot.metadata.captured_at_utc)
    captures = sorted(
        (
            item
            for item in snapshots
            if BOOTSTRAP_PAYLOAD in item.payloads
            and infer_season(item) == season
            and as_instant(item.metadata.captured_at_utc) <= cutoff
        ),
        key=lambda item: (as_instant(item.metadata.captured_at_utc), item.metadata.snapshot_id),
        reverse=True,
    )
    outcomes: dict[int, tuple[pd.DataFrame, str] | None] = {}
    result: dict[int, list[dict[str, Any]]] = {}
    for deadline in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD]):
        # Only evaluate completed publication periods. Current advice stays on the member card.
        if as_instant(deadline.deadline_utc) > cutoff:
            continue
        directory = root / season / f"gw{deadline.gameweek:02d}"
        if not directory.is_dir():
            continue
        for entry_id in entry_ids:
            record = select_record(
                root,
                season=season,
                gameweek=deadline.gameweek,
                entry_id=entry_id,
                deadline_utc=deadline.deadline_utc,
            )
            if record is None:
                continue
            for advice in record["advice"]:
                if advice["strategy"] != "saf-puan" or advice.get("rival_entry_id") is not None:
                    continue
                block = advice.get("chip_recommendations")
                if block is None:
                    continue
                validate_chip_recommendations(
                    block, gameweeks=range(deadline.gameweek, deadline.gameweek + advice["window"])
                )
                for item in block["comparisons"]:
                    gameweek = item["gameweek"]
                    realized = None
                    source_id = None
                    if gameweek is not None:
                        if gameweek not in outcomes:
                            source = next(
                                (
                                    source
                                    for source in captures
                                    if live_payload(gameweek) in source.payloads
                                    and gameweek
                                    in scored_gameweeks(source.payloads[BOOTSTRAP_PAYLOAD])
                                ),
                                None,
                            )
                            outcomes[gameweek] = (
                                None
                                if source is None
                                else (
                                    live_event_outcomes(
                                        source.payloads[live_payload(gameweek)],
                                        source.payloads[BOOTSTRAP_PAYLOAD],
                                        gameweek=gameweek,
                                    ),
                                    source.metadata.snapshot_id,
                                )
                            )
                        settled = outcomes[gameweek]
                        decision = item["decision"]
                        if settled is not None and decision is not None:
                            players = [*decision["starting_xi"], *decision["bench"]]
                            frozen = {
                                "squad_player_ids": [row["player_id"] for row in players],
                                "starting_xi_player_ids": [
                                    row["player_id"] for row in decision["starting_xi"]
                                ],
                                "bench_player_ids": [row["player_id"] for row in decision["bench"]],
                                "ordered_bench_player_ids": [
                                    row["player_id"] for row in decision["bench"]
                                ],
                                "captain_player_id": decision["captain"]["player_id"],
                                "vice_captain_player_id": decision["vice_captain"]["player_id"],
                                "transfers": {
                                    "chip": decision["chip"],
                                    "transfer_hit_points": decision["transfer_hit_points"],
                                },
                            }
                            realized = score_recorded_decision(
                                frozen, pd.DataFrame(players), settled[0]
                            )["net"]
                            source_id = settled[1]
                    result.setdefault(deadline.gameweek, []).append(
                        {
                            "entry_id": entry_id,
                            "window": advice["window"],
                            "chip": item["chip"],
                            "action": item["action"],
                            "gameweek": gameweek,
                            "available_from_gameweek": item["available_from_gameweek"],
                            "last_usable_gameweek": item["last_usable_gameweek"],
                            "expected_points_gain": item["expected_points_gain"],
                            "realized_chip_week_net": realized,
                            "advice_sha256": advice["advice_sha256"],
                            "source_snapshot_id": record["capture"]["snapshot_id"],
                            "outcome_snapshot_id": source_id,
                        }
                    )
    return result
