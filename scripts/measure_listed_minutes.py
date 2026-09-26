"""Measure what dividing season minutes by listed gameweeks does to one published week.

    python -m scripts.measure_listed_minutes
        --snapshot-id fpl-live-20260922T214539Z-364991a4f832
        --control-handoff data/handoffs/2026-27-gw06.json
        --published-records data/advice_records
        --development-only --workers 5 --work-dir <scratch directory>
        --output docs/in_season_listed_minutes.json

The control is the handoff members were advised from. The candidate is this code's handoff
for the same capture, built as a dry run with the flags the control was built with. Both are
solved through the same league publication calls into ``--work-dir`` (saf-puan at every
member window and every chip the member holds; no rival menu, no Top 100 menu, no manager's
word), and each advice document is compared on what it tells the member: captain, vice,
moves, eleven, bench, chip and the plan's weekly transfers. ``--published-records``
compares the control's solves with the advice records of that capture, which is what makes
the control a reproduction of what members were told rather than an assumption about it.

Nothing under the snapshot, handoff or record roots is written. The candidate handoff and
both solved trees go to ``--work-dir`` only; keep it short on Windows, where a solved tree
sits about seventy characters below it.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, repository_provenance, write_json

from squadopt.application import projection_handoff as producer
from squadopt.application.advice import member_horizon_builder
from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.chip_forecast_publication import forecast_source
from squadopt.application.league_publication import (
    LeaguePublicationRequest,
    prepare_league_publication,
)
from squadopt.application.league_views import build_league_views
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    in_season_totals,
    player_snapshot,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    InSeasonProjection,
    project,
    read_projection_handoff,
    read_season_rules,
    write_projection_handoff,
)
from squadopt.platform.publication_workers import league_mapper

#: The precision a handoff's fingerprint keeps. A rebuild on another run of the same code
#: differs from the published file by floating-point noise far below it, and that is not
#: a change this measurement is about.
NOISE = 1e-9


def _solve(
    arguments: argparse.Namespace, handoff: Path, out_root: Path
) -> dict[str, dict[str, Any]]:
    """Every saf-puan advice document, solved from one handoff into ``out_root``.

    Keyed by the path the site publishes it at, which is also the ``published_path`` an
    advice record names, so the two can be joined without a second convention.
    """

    request = LeaguePublicationRequest(
        snapshot_root=arguments.snapshot_root,
        snapshot_id=arguments.snapshot_id,
        archive_root=arguments.archive_root,
        registry_path=arguments.registry,
        out_dir=out_root / "site",
        league_id=arguments.league,
        handoff_path=handoff,
        rival_menu=False,
    )
    prepared = prepare_league_publication(request)
    request = replace(request, season=prepared.season)
    snapshot, inputs, season = prepared.snapshot, prepared.inputs, prepared.season
    panel = build_panel(request.archive_root)
    in_season = read_projection_handoff(handoff)
    league = request.out_dir / "data" / "league"
    with league_mapper(request, arguments.workers) as mapper:
        build_league_views(
            CapturePicksProvider(snapshot, request.snapshot_id),
            prepared.registrations,
            inputs,
            project(inputs, panel, in_season=in_season),
            read_season_rules(snapshot, season=season),
            league_id=request.league_id,
            league_name=prepared.league_name or f"League {request.league_id}",
            out_dir=league,
            standings=prepared.standings,
            scored_gameweek=prepared.scored_gameweek,
            rival_menu=False,
            mapper=mapper,
            horizon_builder=member_horizon_builder(
                snapshot, season=season, panel=panel, in_season=in_season
            ),
            chip_forecast_source=forecast_source(snapshot),
        )
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted((league / "advice").glob("*/saf-puan/**/*.json")):
        documents[path.relative_to(league).as_posix()] = json.loads(
            path.read_text(encoding="utf-8")
        )["payload"]
    return documents


def _ids(entries: Any) -> list[int]:
    return [int(entry["player_id"]) for entry in entries or []]


def _decision(payload: Mapping[str, Any]) -> dict[str, object]:
    """What the document tells the member, with every points figure left out."""

    return {
        "captain": (payload.get("captain") or {}).get("player_id"),
        "vice_captain": (payload.get("vice_captain") or {}).get("player_id"),
        "moves": [
            [move["player_out"]["player_id"], move["player_in"]["player_id"]]
            for move in payload.get("moves") or []
        ],
        "starting_xi": _ids(payload.get("starting_xi")),
        "bench": _ids(payload.get("bench")),
        "chip": payload.get("chip"),
        "plan_weeks": [
            [
                week["gameweek"],
                _ids(week["transfers_out"]),
                _ids(week["transfers_in"]),
                week["chip"],
            ]
            for week in payload.get("plan_weeks") or []
        ],
    }


def _kind(path: str) -> str:
    """``saf-puan/1.json`` is ``window_1``; ``saf-puan/1/chip-3xc.json`` is ``chip_3xc``."""

    tail = path.split("/saf-puan/", 1)[1].removesuffix(".json")
    if "/" in tail:
        return tail.split("/", 1)[1].replace("-", "_")
    return f"window_{tail}"


def _member(path: str, members: list[int]) -> int:
    """A member's position in entry order: the record names no entry."""

    return members.index(int(path.split("/")[1])) + 1


def _compare(
    control: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
    changed: set[int],
) -> dict[str, object]:
    """Document by document: does the candidate tell the member something different?"""

    members = sorted({int(path.split("/")[1]) for path in (*control, *candidate)})
    kinds: dict[str, dict[str, int]] = {}
    differing: list[dict[str, Any]] = []
    moved: list[float] = []
    status_changed = 0
    for path in sorted(set(control) | set(candidate)):
        tally = kinds.setdefault(_kind(path), {"documents": 0, "same_decision": 0})
        tally["documents"] += 1
        before, after = control.get(path), candidate.get(path)
        if before is None or after is None:
            differing.append(
                {"member": _member(path, members), "document": _kind(path), "fields": ["file"]}
            )
            continue
        total_before = before.get("expected_own_points")
        total_after = after.get("expected_own_points")
        if total_before is not None and total_after is not None:
            moved.append(float(total_after) - float(total_before))
        status_changed += before["solver_status"] != after["solver_status"]
        was, now = _decision(before), _decision(after)
        fields = [name for name in was if was[name] != now[name]]
        if not fields:
            tally["same_decision"] += 1
            continue
        squad_before = set(_ids(before.get("starting_xi"))) | set(_ids(before.get("bench")))
        squad_after = set(_ids(after.get("starting_xi"))) | set(_ids(after.get("bench")))
        differing.append(
            {
                "member": _member(path, members),
                "document": _kind(path),
                "fields": fields,
                "control_solver_status": before["solver_status"],
                "candidate_solver_status": after["solver_status"],
                "control_optimality_gap": round(float(before["optimality_gap"]), 3),
                "candidate_optimality_gap": round(float(after["optimality_gap"]), 3),
                "changed_players_brought_in": sorted((squad_after - squad_before) & changed),
            }
        )
    return {
        "members": len(members),
        "documents": sum(tally["documents"] for tally in kinds.values()),
        "by_kind": kinds,
        "captain_changed": sum(1 for row in differing if "captain" in row["fields"]),
        "solver_status_changed": status_changed,
        "differing": differing,
        "differing_with_both_solves_proved": sum(
            1
            for row in differing
            if row.get("control_solver_status") == "OPTIMAL"
            and row.get("candidate_solver_status") == "OPTIMAL"
        ),
        "totals_moved": sum(1 for value in moved if abs(value) > 1e-9),
        "largest_total_move": round(max((abs(value) for value in moved), default=0.0), 6),
    }


def _published(
    root: Path, snapshot_id: str, control: Mapping[str, Mapping[str, Any]]
) -> dict[str, int]:
    """How many published advice record entries the control's solves reproduce."""

    entries = reproduced = 0
    for path in sorted(root.glob(f"*/gw*/entry-*/{snapshot_id}/advice.json")):
        for entry in json.loads(path.read_text(encoding="utf-8"))["advice"]:
            entries += 1
            solved = control.get(entry["published_path"])
            if solved is None:
                continue
            decision = _decision(solved)
            told = {
                "captain": entry["captain"],
                "vice_captain": entry["vice_captain"],
                "moves": [[move["player_out"], move["player_in"]] for move in entry["moves"]],
                "starting_xi": entry["starting_xi"],
                "bench": entry["bench"],
                "chip": entry["chip"],
            }
            reproduced += all(decision[name] == value for name, value in told.items())
    return {"published_entries": entries, "reproduced_by_the_control": reproduced}


def _players(
    arguments: argparse.Namespace,
    control: InSeasonProjection,
    candidate: InSeasonProjection,
    report: Mapping[str, object],
) -> dict[str, Any]:
    """Which players moved, by how much, and what that did to each position's order."""

    snapshot = read_snapshot(arguments.snapshot_root, arguments.snapshot_id)
    bootstrap = snapshot.payloads[BOOTSTRAP_PAYLOAD]
    played = int(str(report["gameweeks_played"]))
    listed = producer._listed_gameweeks(snapshot.payloads, bootstrap, played) or {}
    roster = player_snapshot(bootstrap).set_index("player_id")
    totals = in_season_totals(
        bootstrap,
        snapshot.payloads[FIXTURES_PAYLOAD],
        captured_at_utc=snapshot.metadata.captured_at_utc,
    ).set_index("player_id")
    frame = pd.DataFrame({"player_id": sorted(control.expected_points)})
    frame["control"] = frame["player_id"].map(control.expected_points)
    frame["candidate"] = frame["player_id"].map(candidate.expected_points)
    for column, source in (
        ("name", roster["name"]),
        ("team", roster["team_id"]),
        ("position", roster["position"]),
        ("price_tenths", roster["price_tenths"]),
        ("season_minutes", totals["minutes"]),
        ("season_points", totals["total_points"]),
    ):
        frame[column] = frame["player_id"].map(source)
    frame["listed"] = frame["player_id"].map(lambda code: listed.get(int(code), 0))
    frame["delta"] = frame["candidate"] - frame["control"]
    for arm in ("control", "candidate"):
        ranks = frame.groupby("position")[arm].rank(ascending=False, method="min")
        frame[f"{arm}_rank"] = ranks.astype("int64")
    frame["position_size"] = frame.groupby("position")["player_id"].transform("size")
    changed = frame.loc[frame["delta"].abs().gt(NOISE)].sort_values(
        ["delta", "player_id"], ascending=[False, True]
    )
    rows: list[dict[str, Any]] = [
        {
            "player_id": int(row["player_id"]),
            "name": str(row["name"]),
            "team": str(row["team"]),
            "position": str(row["position"]),
            "price_tenths": int(row["price_tenths"]),
            "gameweeks_listed": int(row["listed"]),
            "season_minutes": int(row["season_minutes"]),
            "season_points": int(row["season_points"]),
            "control_expected_points": round(float(row["control"]), 6),
            "candidate_expected_points": round(float(row["candidate"]), 6),
            "change": round(float(row["delta"]), 6),
            "control_position_rank": int(row["control_rank"]),
            "candidate_position_rank": int(row["candidate_rank"]),
            "position_size": int(row["position_size"]),
        }
        for row in changed.to_dict("records")
    ]
    positions: dict[str, dict[str, Any]] = {}
    for position, group in frame.groupby("position"):
        moved = changed.loc[changed["position"].eq(position), "candidate_rank"]
        first = {
            arm: group.sort_values([arm, "player_id"], ascending=[False, True])["player_id"]
            .head(20)
            .tolist()
            for arm in ("control", "candidate")
        }
        positions[str(position)] = {
            "players": len(group),
            "top_20_order_unchanged": first["control"] == first["candidate"],
            "best_candidate_rank_of_a_changed_player": int(moved.min()) if len(moved) else None,
        }
    unchanged = frame.loc[frame["delta"].abs().le(NOISE)]
    control_chance = control.appearance_probability or {}
    candidate_chance = candidate.appearance_probability or {}
    return {
        "gameweeks_played": played,
        "roster": len(frame),
        "players_listed_in_fewer_gameweeks": int(frame["listed"].between(1, played - 1).sum()),
        "players_listed_in_no_gameweek": int(frame["listed"].eq(0).sum()),
        "players_changed": len(changed),
        "every_changed_player_listed_in_fewer_gameweeks": bool(changed["listed"].lt(played).all()),
        "largest_change_among_the_rest": float(unchanged["delta"].abs().max()),
        "appearance_probability_same_players": set(control_chance) == set(candidate_chance),
        "largest_appearance_probability_change": max(
            (abs(control_chance[code] - candidate_chance[code]) for code in control_chance),
            default=0.0,
        ),
        "change_mean": round(fmean(float(value) for value in changed["delta"]), 6),
        "change_min": round(float(changed["delta"].min()), 6),
        "change_max": round(float(changed["delta"].max()), 6),
        "changed": rows,
        "positions": positions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--control-handoff", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=Path("data/entries/registry.json"))
    parser.add_argument("--league", type=int, default=352490)
    parser.add_argument("--published-records", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--development-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    control = read_projection_handoff(arguments.control_handoff)
    if control.source_snapshot_id != arguments.snapshot_id:
        parser.error("The control handoff was built from another capture.")
    candidate, _, report = producer.build(
        arguments.snapshot_root,
        arguments.archive_root,
        arguments.work_dir / "unused",
        snapshot_id=arguments.snapshot_id,
        development_only=arguments.development_only,
        dry_run=True,
    )
    candidate_path = write_projection_handoff(
        arguments.work_dir / "candidate" / arguments.control_handoff.name, candidate
    )
    players = _players(arguments, control, candidate, report)
    changed = {int(row["player_id"]) for row in players["changed"]}
    solved_control = _solve(arguments, arguments.control_handoff, arguments.work_dir / "control")
    solved_candidate = _solve(arguments, candidate_path, arguments.work_dir / "solved")
    record: dict[str, object] = {
        "measurement": "in_season_listed_minutes",
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": repository_provenance(),
        "snapshot_id": arguments.snapshot_id,
        "control_handoff_fingerprint": control.fingerprint,
        "candidate_handoff_fingerprint": candidate.fingerprint,
        "candidate_minutes_denominator": report.get("in_season_minutes_denominator"),
        "players": players,
        "advice": _compare(solved_control, solved_candidate, changed),
    }
    if arguments.published_records is not None:
        record["control_against_published"] = _published(
            arguments.published_records, arguments.snapshot_id, solved_control
        )
    write_json(arguments.output, record)
    print(json.dumps({key: value for key, value in record.items() if key != "players"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
