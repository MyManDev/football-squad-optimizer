"""Join retained requests and captures for the existing settled-history scorer."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema

from squadopt.application.advice_record import scoring_document
from squadopt.application.weekly_suggestion_eval import CONTRACT_VERSION, score_selected_week
from squadopt.data.atomic import replace_retrying
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FPL_LIVE_SOURCE,
    POSITION_CODES,
    gameweek_deadlines,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live.recommendation import infer_season
from squadopt.platform.advice_cache import advice_cache_key
from squadopt.platform.advice_documents import validate_advice_document
from squadopt.platform.advice_job_spec import AdviceJobSpec
from squadopt.platform.history_documents import history_schema
from squadopt.platform.jobs_contract import AdviceJob, _instant, _utc


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
        completed = normalize_utc_timestamp(row["completed_at_utc"], label="completed_at_utc")
        if as_instant(completed) > cutoff:
            continue
        capture = by_id.get(context["capture_snapshot_id"])
        if capture is None:
            raise ValueError("The decision capture is absent from this history snapshot.")
        captured = capture.metadata.captured_at_utc
        if as_instant(document["generated_at_utc"]) != as_instant(captured):
            raise ValueError("The response clock differs from the decision capture.")
        if not as_instant(captured) <= as_instant(completed) < as_instant(deadline):
            raise ValueError("The request did not complete before the captured deadline.")
        decision_deadlines = {
            event.gameweek: event.deadline_utc
            for event in gameweek_deadlines(capture.payloads[BOOTSTRAP_PAYLOAD])
        }
        if gameweek not in decision_deadlines or as_instant(
            decision_deadlines[gameweek]
        ) != as_instant(deadline):
            raise ValueError("Decision and outcome captures disagree on the deadline.")
        players = _players(payload, capture)
        advice = scoring_document(payload, strategy="saf-puan", window=1, rival_entry_id=None)
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


def _key(spec: AdviceJobSpec) -> str:
    context = spec.context
    return advice_cache_key(
        advice_contract_version=context.advice_contract_version,
        capture_snapshot_id=context.capture_snapshot_id,
        season=context.season,
        gameweek=context.gameweek,
        league_id=spec.league_id,
        entry_id=spec.entry_id,
        strategy=spec.strategy,
        window=spec.window,
        rival_entry_id=spec.rival_entry_id,
        projection_handoff_fingerprint=context.projection_handoff_fingerprint,
        repository_commit=context.repository_commit,
        configuration_fingerprint=context.configuration_fingerprint,
        switches=spec.switches,
    )


def _completed(store: Path) -> list[AdviceJob]:
    jobs: dict[str, AdviceJob] = {}
    for directory in (store / "jobs", store / "jobs" / "archive"):
        for path in sorted(directory.glob("*.json")):
            job = AdviceJob.from_payload(json.loads(path.read_bytes()))
            if path.stem != job.job_id:
                raise ValueError("A job's filename differs from its recorded identity.")
            if job.job_id in jobs and jobs[job.job_id] != job:
                raise ValueError("Live and archived copies of a job disagree.")
            jobs[job.job_id] = job
    return [job for job in jobs.values() if job.status == "completed"]


def requested_history(
    store: Path,
    *,
    season: str,
    gameweek: int,
    entry_id: int,
    deadline_utc: str,
) -> dict[str, Any]:
    """Export successful plain one-week requests, including public-entry requests.

    Completion time is the queue's terminal clock, never the advice envelope's
    capture clock. A completed result proves availability, not a page view or
    adoption. Distinct full cache identities remain distinct even for one capture.
    """
    return _requested_history(
        store,
        season=season,
        gameweek=gameweek,
        entry_id=entry_id,
        deadline_utc=deadline_utc,
        jobs=_completed(store),
    )


def _requested_history(
    store: Path,
    *,
    season: str,
    gameweek: int,
    entry_id: int,
    deadline_utc: str,
    jobs: Sequence[AdviceJob],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", season):
        raise ValueError("season must have the shape YYYY-YY.")
    if any(type(value) is not int or value < 1 for value in (gameweek, entry_id)):
        raise ValueError("gameweek and entry_id must be positive integers.")
    deadline_utc = _utc(deadline_utc, label="deadline_utc")
    deadline = _instant(deadline_utc)
    if not all((store / part).is_dir() for part in ("jobs", "specs", "cache")):
        raise ValueError("Expected an offline store snapshot with jobs, specs and cache.")

    records: dict[str, dict[str, Any]] = {}
    for job in jobs:
        key = job.cache_key
        if job.result_ref != key:
            raise ValueError("A completed job does not name its own answer.")
        spec = AdviceJobSpec.from_payload(
            json.loads((store / "specs" / key[:2] / f"{key}.json").read_bytes())
        )
        if (spec.context.season, spec.context.gameweek, spec.entry_id) != (
            season,
            gameweek,
            entry_id,
        ):
            continue
        if (
            spec.strategy != "saf-puan"
            or spec.window != 1
            or spec.rival_entry_id is not None
            or set(spec.switches) - {"public_entry"}
        ):
            continue
        if _key(spec) != key:
            raise ValueError("The request specification differs from its cache address.")
        raw = (store / "cache" / key[:2] / f"{key}.json").read_bytes()
        validate_advice_document(raw)
        document = json.loads(raw)
        payload = document["payload"]
        expected = {
            "season": season,
            "gameweek": gameweek,
            "entry_id": entry_id,
            "league_id": spec.league_id,
            "mode": "saf-puan",
            "window": 1,
            "source_snapshot_id": spec.context.capture_snapshot_id,
        }
        if (
            document["contract_version"] != spec.context.advice_contract_version
            or document.get("source_kind") != "live"
            or any(payload.get(name) != value for name, value in expected.items())
            or any(name in payload for name in ("evidence", "top100", "preferences", "plan_weeks"))
        ):
            raise ValueError("The cached advice does not identify the recorded request.")
        captured = _instant(_utc(document["generated_at_utc"], label="capture time"))
        completed = _instant(job.updated_at_utc)
        if completed < captured:
            raise ValueError("Completion precedes the advice capture.")
        # Validate candidates before choosing: damaged later evidence must not make
        # an earlier answer silently authoritative. Never backdate a late completion.
        if completed >= deadline:
            continue
        held = records.get(key)
        if held is not None and _instant(held["completed_at_utc"]) <= completed:
            continue
        records[key] = {
            "cache_key": key,
            "completed_at_utc": job.updated_at_utc,
            "request": spec.as_payload(),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "response_json": raw.decode("utf-8"),
        }
    return {
        "format": "requested_advice_export_v1",
        "season": season,
        "gameweek": gameweek,
        "entry_id": entry_id,
        "deadline_utc": deadline_utc,
        "records": sorted(
            records.values(), key=lambda row: (_instant(row["completed_at_utc"]), row["cache_key"])
        ),
    }


def build_requested_history(
    *,
    store_snapshot: Path,
    snapshot_root: Path,
    as_of_snapshot_id: str,
    league_id: int,
    entry_id: int,
    gameweeks: Sequence[int],
    out_dir: Path,
) -> Path:
    """Write only history/requested/{entry}.json; leave legacy history files untouched."""
    return _build_requested_history(
        store_snapshot=store_snapshot,
        as_of=read_snapshot(snapshot_root, as_of_snapshot_id),
        captures=[
            read_snapshot(snapshot_root, identifier)
            for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
        ],
        jobs=_completed(store_snapshot),
        league_id=league_id,
        entry_id=entry_id,
        gameweeks=gameweeks,
        out_dir=out_dir,
    )


def _build_requested_history(
    *,
    store_snapshot: Path,
    as_of: CapturedSnapshot,
    captures: Sequence[CapturedSnapshot],
    jobs: Sequence[AdviceJob],
    league_id: int,
    entry_id: int,
    gameweeks: Sequence[int],
    out_dir: Path,
) -> Path:
    if type(league_id) is not int or league_id < 1 or type(entry_id) is not int or entry_id < 1:
        raise ValueError("History publication requires a positive league and entry identity.")
    if not gameweeks or any(type(week) is not int or week < 1 for week in gameweeks):
        raise ValueError("At least one positive gameweek is required.")
    season = infer_season(as_of)
    deadlines = {
        event.gameweek: event.deadline_utc
        for event in gameweek_deadlines(as_of.payloads[BOOTSTRAP_PAYLOAD])
    }
    path = out_dir / "history" / "requested" / f"{entry_id}.json"
    weeks: dict[int, Any] = {}
    if path.exists():
        previous = json.loads(path.read_bytes())
        jsonschema.validate(previous, history_schema())
        payload = previous["payload"]
        if (payload["season"], payload["league_id"], payload["entry_id"]) != (
            season,
            league_id,
            entry_id,
        ):
            raise ValueError("Existing requested history identifies another member or season.")
        if as_instant(previous["generated_at_utc"]) > as_instant(as_of.metadata.captured_at_utc):
            raise ValueError("An older capture cannot replace a newer history publication.")
        for row in payload["weeks"]:
            if row.get("advice_source") != "requested_server" or row["gameweek"] in weeks:
                raise ValueError("Existing requested history has invalid or duplicate weeks.")
            weeks[row["gameweek"]] = row
    for week in sorted(set(gameweeks)):
        if week not in deadlines:
            raise ValueError("The captured FPL calendar has no requested gameweek.")
        exported = _requested_history(
            store_snapshot,
            season=season,
            gameweek=week,
            entry_id=entry_id,
            deadline_utc=deadlines[week],
            jobs=jobs,
        )
        reviewed = requested_week(exported, captures=captures, as_of=as_of)
        if reviewed is None:
            if week in weeks:
                raise ValueError("The supplied store would erase an existing requested week.")
            continue
        weeks[week] = reviewed
    document = {
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": as_of.metadata.captured_at_utc,
        "payload": {
            "league_id": league_id,
            "entry_id": entry_id,
            "season": season,
            "as_of_snapshot_id": as_of.metadata.snapshot_id,
            "weeks": [weeks[week] for week in sorted(weeks, reverse=True)],
        },
    }
    jsonschema.validate(document, history_schema())
    raw = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        replace_retrying(Path(temporary), path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def publish_requested_histories(
    *,
    store_snapshot: Path,
    snapshot_root: Path,
    as_of: CapturedSnapshot,
    league_id: int,
    entry_ids: Sequence[int],
    out_dir: Path,
) -> tuple[Path, ...]:
    """Refresh requested weeks for this league's members from one offline evidence set.

    Inventory and captures are read once, and only entries with requests or retained
    requested weeks produce files. A member with no request never causes a plan solve.
    """
    if not all((store_snapshot / part).is_dir() for part in ("jobs", "specs", "cache")):
        raise ValueError("Expected an offline store snapshot with jobs, specs and cache.")
    season = infer_season(as_of)
    members = set(entry_ids)
    jobs_by_entry: dict[int, list[AdviceJob]] = {}
    weeks_by_entry: dict[int, set[int]] = {}
    for job in _completed(store_snapshot):
        key = job.cache_key
        spec = AdviceJobSpec.from_payload(
            json.loads((store_snapshot / "specs" / key[:2] / f"{key}.json").read_bytes())
        )
        if (
            spec.entry_id not in members
            or spec.context.season != season
            or spec.strategy != "saf-puan"
            or spec.window != 1
            or spec.rival_entry_id is not None
            or set(spec.switches) - {"public_entry"}
        ):
            continue
        jobs_by_entry.setdefault(spec.entry_id, []).append(job)
        weeks_by_entry.setdefault(spec.entry_id, set()).add(spec.context.gameweek)
    for entry_id in members:
        previous = out_dir / "history" / "requested" / f"{entry_id}.json"
        if previous.is_file():
            document = json.loads(previous.read_bytes())
            jsonschema.validate(document, history_schema())
            payload = document["payload"]
            if (payload["season"], payload["league_id"], payload["entry_id"]) != (
                season,
                league_id,
                entry_id,
            ):
                raise ValueError("Existing requested history identifies another member or season.")
            weeks_by_entry.setdefault(entry_id, set()).update(
                row["gameweek"] for row in payload["weeks"]
            )
    if not any(weeks_by_entry.values()):
        return ()
    captures = [
        read_snapshot(snapshot_root, identifier)
        for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    ]
    return tuple(
        _build_requested_history(
            store_snapshot=store_snapshot,
            as_of=as_of,
            captures=captures,
            jobs=jobs_by_entry.get(entry_id, ()),
            league_id=league_id,
            entry_id=entry_id,
            gameweeks=sorted(weeks),
            out_dir=out_dir,
        )
        for entry_id, weeks in sorted(weeks_by_entry.items())
        if weeks
    )


#: Where a public team's requested history is published, under the site's ``data/``: one
#: tree per league the team was asked under, in the shape a league's own tree has, so the
#: page reads it with the same loader. A team asked for on its own (league 0) has no page
#: that reads a history, and is not published.
PUBLIC_HISTORY_ROOT = "public"


def publish_public_requested_histories(
    *,
    store_snapshot: Path,
    snapshot_root: Path,
    as_of: CapturedSnapshot,
    listed_leagues: Sequence[int],
    out_dir: Path,
) -> tuple[Path, ...]:
    """Refresh requested weeks for every public team the store holds, outside listed leagues.

    A member of a league the site does not publish asked the service for a plan through the
    public route; what that plan scored is theirs to read as a listed member's is. Each
    (league, entry) pair with a completed plain one-week request, or a requested history
    published before, gets ``data/public/<league>/history/requested/<entry>.json``. Listed
    leagues' members are the league publisher's; league 0 is nobody's page.
    """
    if not all((store_snapshot / part).is_dir() for part in ("jobs", "specs", "cache")):
        raise ValueError("Expected an offline store snapshot with jobs, specs and cache.")
    season = infer_season(as_of)
    listed = {int(league) for league in listed_leagues}
    jobs_by_team: dict[tuple[int, int], list[AdviceJob]] = {}
    weeks_by_team: dict[tuple[int, int], set[int]] = {}
    for job in _completed(store_snapshot):
        key = job.cache_key
        spec = AdviceJobSpec.from_payload(
            json.loads((store_snapshot / "specs" / key[:2] / f"{key}.json").read_bytes())
        )
        if (
            "public_entry" not in spec.switches
            or set(spec.switches) != {"public_entry"}
            or spec.league_id < 1
            or spec.league_id in listed
            or spec.context.season != season
            or spec.strategy != "saf-puan"
            or spec.window != 1
            or spec.rival_entry_id is not None
        ):
            continue
        team = (spec.league_id, spec.entry_id)
        jobs_by_team.setdefault(team, []).append(job)
        weeks_by_team.setdefault(team, set()).add(spec.context.gameweek)
    root = out_dir / PUBLIC_HISTORY_ROOT
    if root.is_dir():
        for previous in sorted(root.glob("*/history/requested/*.json")):
            league_text = previous.parents[2].name
            if not (league_text.isdigit() and previous.stem.isdigit()):
                continue
            team = (int(league_text), int(previous.stem))
            if team[0] in listed:
                continue
            document = json.loads(previous.read_bytes())
            jsonschema.validate(document, history_schema())
            payload = document["payload"]
            if (payload["season"], payload["league_id"], payload["entry_id"]) != (
                season,
                *team,
            ):
                raise ValueError("Existing public history identifies another team or season.")
            weeks_by_team.setdefault(team, set()).update(
                row["gameweek"] for row in payload["weeks"]
            )
    if not any(weeks_by_team.values()):
        return ()
    captures = [
        read_snapshot(snapshot_root, identifier)
        for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    ]
    return tuple(
        _build_requested_history(
            store_snapshot=store_snapshot,
            as_of=as_of,
            captures=captures,
            jobs=jobs_by_team.get(team, ()),
            league_id=team[0],
            entry_id=team[1],
            gameweeks=sorted(weeks),
            out_dir=root / str(team[0]),
        )
        for team, weeks in sorted(weeks_by_team.items())
        if weeks
    )
