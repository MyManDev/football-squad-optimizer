"""Reconcile surviving publications with newly collected public outcomes.

This is not reconstruction of a historical capture, projection pool or ledger.
Missing historical information stays missing. GW1 uses the committed paper decision;
member advice is kept separate from both that paper squad and members' actual picks.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.application.scoreboard_diagnostics import empty_diagnostics, score_recorded_decision
from squadopt.application.weekly_suggestion_eval import select_record
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.live import LedgerEntry, infer_season


def _settled_capture(
    current: CapturedSnapshot,
    others: Sequence[CapturedSnapshot],
    gameweek: int,
) -> CapturedSnapshot:
    candidates = [
        item
        for item in (current, *others)
        if BOOTSTRAP_PAYLOAD in item.payloads
        and infer_season(item) == infer_season(current)
        and as_instant(item.metadata.captured_at_utc)
        <= as_instant(current.metadata.captured_at_utc)
        and gameweek in scored_gameweeks(item.payloads[BOOTSTRAP_PAYLOAD])
        and live_payload(gameweek) in item.payloads
    ]
    return max(
        candidates,
        key=lambda item: (as_instant(item.metadata.captured_at_utc), item.metadata.snapshot_id),
        default=current,
    )


def _score(
    decision: Mapping[str, Any], players: pd.DataFrame, snapshot: CapturedSnapshot, gameweek: int
) -> dict[str, object] | None:
    if (
        gameweek not in scored_gameweeks(snapshot.payloads[BOOTSTRAP_PAYLOAD])
        or live_payload(gameweek) not in snapshot.payloads
    ):
        return None
    outcomes = live_event_outcomes(
        snapshot.payloads[live_payload(gameweek)],
        snapshot.payloads[BOOTSTRAP_PAYLOAD],
        gameweek=gameweek,
    )
    return score_recorded_decision(decision, players, outcomes)


@dataclass(frozen=True)
class PublicationRecovery:
    entry: LedgerEntry
    records: tuple[dict[str, Any], ...]
    provenance: Mapping[str, object]


def load_publication_recovery(
    *,
    snapshot: CapturedSnapshot,
    publication_root: Path,
    advice_root: Path,
    league_id: int,
    entry_ids: tuple[int, ...],
    outcome_snapshots: Sequence[CapturedSnapshot] = (),
) -> PublicationRecovery:
    season = infer_season(snapshot)
    if season != "2026-27":
        raise DataError("The historical recovery sources belong to 2026-27.")
    source = publication_root / "data" / season / "gw01" / "recommendation.json"
    raw = source.read_bytes()
    published = json.loads(raw)["payload"]
    if published["season"] != season or published["gameweek"] != 1:
        raise DataError("GW1 publication names another decision.")
    if as_instant(published["captured_at_utc"]) >= as_instant(published["deadline_utc"]):
        raise DataError("GW1 decision capture was not before its deadline.")
    decision = {
        **published,
        "squad_player_ids": [row["player_id"] for row in published["squad"]],
        "starting_xi_player_ids": [row["player_id"] for row in published["starting_xi"]],
        "bench_player_ids": [row["player_id"] for row in published["bench"]],
    }
    # A displayed bench list is not proof that the original ledger froze that order.
    players = pd.DataFrame(published["squad"])
    settled = _settled_capture(snapshot, outcome_snapshots, 1)
    scored = _score(decision, players, settled, 1)
    outcome = (
        None
        if scored is None
        else {
            "realized_net_score": scored["net"],
            "realized_xi_score": scored["xi"],
            "diagnostics": scored["diagnostics"],
            "scoring_basis": scored["scoring_basis"],
            "source_snapshot_id": settled.metadata.snapshot_id,
        }
    )
    entry = LedgerEntry(season, 1, decision, outcome, source.parent)
    bootstrap = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    events = {event["id"]: event for event in bootstrap["events"]}
    records: list[dict[str, Any]] = []
    for entry_id in entry_ids:
        directory = advice_root / season / "gw04" / f"entry-{entry_id}"
        if not directory.is_dir():
            continue
        record = select_record(
            advice_root,
            season=season,
            gameweek=4,
            entry_id=entry_id,
            deadline_utc=events[4]["deadline_time"],
            as_of_utc=snapshot.metadata.captured_at_utc,
        )
        if record is None:
            continue
        if (
            record.get("league_id") != league_id
            or record.get("player_id_space") != "fpl_element_code"
        ):
            raise DataError("Advice record has a different league or identity space.")
        records.append(record)
    return PublicationRecovery(
        entry,
        tuple(records),
        {
            "contract_version": "publication_recovery_v1",
            "gw1_publication_sha256": hashlib.sha256(raw).hexdigest(),
            "gw1_original_reported_net": published.get("outcome_net_score"),
            "gw1_api_net": None if outcome is None else outcome["realized_net_score"],
            "gw4_member_records": len(records),
            "missing_decision_gameweeks": [2, 3],
            "historical_availability": "lost",
            "collection_purpose": "settled_outcomes_only",
        },
    )


def enrich_recovered_scoreboard(
    document: dict[str, object],
    recovery: PublicationRecovery,
    snapshot: CapturedSnapshot,
    outcome_snapshots: Sequence[CapturedSnapshot] = (),
) -> None:
    """Attach surviving advice and actual picks to the standard scoreboard envelope."""
    payload = document["payload"]
    assert isinstance(payload, dict)
    rows = {row["gameweek"]: row for row in payload["gameweeks"]}
    for gameweek, row in rows.items():
        if gameweek <= 4:
            row["decision_record_status"] = "missing" if gameweek in (2, 3) else "available"
        if gameweek not in scored_gameweeks(snapshot.payloads[BOOTSTRAP_PAYLOAD]):
            continue
        for member in row["members"]:
            name = f"entry-{member['entry_id']}-picks-gw{gameweek:02d}.json"
            if name in snapshot.payloads:
                member["settled_picks"] = settled_member_picks(
                    snapshot, gameweek=gameweek, entry_id=member["entry_id"]
                )
    for record in recovery.records:
        variants = record["advice"]
        assert isinstance(variants, list)
        # The one-week pure-points recommendation is a consistent comparison arm.
        advice = next(
            (
                item
                for item in variants
                if item["strategy"] == "saf-puan"
                and item["window"] == 1
                and item.get("rival_entry_id") is None
            ),
            None,
        )
        if advice is None or not advice["scoring_complete"]:
            continue
        player_map = record["players"]
        assert isinstance(player_map, dict)
        projections = pd.DataFrame(
            [{"player_id": int(code), **row} for code, row in player_map.items()]
        )
        decision = {
            "squad_player_ids": [*advice["starting_xi"], *advice["bench"]],
            "starting_xi_player_ids": advice["starting_xi"],
            "bench_player_ids": advice["bench"],
            "ordered_bench_player_ids": advice["bench"],
            "captain_player_id": advice["captain"],
            "vice_captain_player_id": advice["vice_captain"],
            "transfers": {
                "chip": advice["chip"],
                "transfer_hit_points": advice["transfer_hit_points"],
            },
        }
        settled = _settled_capture(snapshot, outcome_snapshots, 4)
        scored = _score(decision, projections, settled, 4)
        capture = record["capture"]
        assert isinstance(capture, dict)
        rows[4]["comparisons"].append(
            {
                "kind": "member_advice",
                "entry_id": record["entry_id"],
                "net": None if scored is None else scored["net"],
                "diagnostics": empty_diagnostics() if scored is None else scored["diagnostics"],
                "scoring_basis": "official_autosub_captain_v2",
                "source_snapshot_id": capture["snapshot_id"],
                "outcome_snapshot_id": None if scored is None else settled.metadata.snapshot_id,
                "expected_net": float(advice["expected_own_points"])
                - float(advice["transfer_hit_points"]),
                "advice_sha256": advice["advice_sha256"],
            }
        )
    payload["recovery"] = dict(recovery.provenance)


def settled_member_picks(
    snapshot: CapturedSnapshot, *, gameweek: int, entry_id: int
) -> list[dict[str, int]]:
    """Keep API multipliers as settled facts, not invented pre-deadline decisions.

    Multipliers already include the game's captain and substitution decisions. Their
    weighted points must reconcile to the gross entry-history score before publication.
    """
    bootstrap = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    identities = {row["id"]: row["code"] for row in bootstrap["elements"]}
    if len(identities) != len(bootstrap["elements"]) or len(set(identities.values())) != len(
        identities
    ):
        raise DataError("Settled member identity mapping must be one-to-one.")
    outcomes = live_event_outcomes(
        snapshot.payloads[live_payload(gameweek)],
        snapshot.payloads[BOOTSTRAP_PAYLOAD],
        gameweek=gameweek,
    ).set_index("player_id")
    document = json.loads(snapshot.payloads[f"entry-{entry_id}-picks-gw{gameweek:02d}.json"])
    if document["entry_history"].get("event") != gameweek:
        raise DataError("Settled member picks name another gameweek.")
    picks = document["picks"]
    if len(picks) != 15 or len({pick["element"] for pick in picks}) != 15:
        raise DataError("Settled member picks must contain 15 distinct players.")
    for pick in picks:
        for name, low, high in (("position", 1, 15), ("multiplier", 0, 3)):
            value = pick.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise DataError(f"Settled member pick has invalid {name}.")
    if {pick["position"] for pick in picks} != set(range(1, 16)):
        raise DataError("Settled member picks must occupy each position exactly once.")
    result = []
    for pick in picks:
        code = identities.get(pick["element"])
        if code is None or code not in outcomes.index:
            raise DataError("Settled member pick has no mapped outcome.")
        result.append(
            {
                "player_id": int(code),
                "position": int(pick["position"]),
                "multiplier": int(pick["multiplier"]),
                "points": int(str(outcomes.at[code, "total_points"])),
                "minutes": int(str(outcomes.at[code, "minutes"])),
            }
        )
    gross = sum(row["points"] * row["multiplier"] for row in result)
    reported_points = document["entry_history"]["points"]
    if isinstance(reported_points, bool) or not isinstance(reported_points, int):
        raise DataError("Settled entry-history points must be an integer.")
    if gross != reported_points:
        raise DataError("Settled member picks do not reconcile to entry-history points.")
    return result
