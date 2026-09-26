"""Publish completed outcomes without producing another decision.

This is a new capability, not a refactor: the repository had no settled publisher.
The ordinary publisher either solves the league again or inherits it wholesale;
``settled`` previously only named a publication. This path reads existing captures,
records and an already settled ledger. It never captures, settles, solves or deploys.
It publishes what the ledger and the capture already decided, and refuses everything else.
It never removes evidence a previous publication carried.

Only the explicitly approved outcome documents may change. Every other accepted
byte, including entries and advice, survives. A new required path must be approved
before it can be added to the boundary below.

The checks an operator used to run by hand on the finished candidate run here, before
the candidate is written: the rebuilt season documents against the schemas the accepted
tree froze, the frozen root index against the candidate's files, the fixture list against
the outcome capture, and (from the command line) the league tree release check, which
refuses what it finds in the candidate and not in the accepted tree. A candidate that
fails any of them is refused and never appears on disk.
"""

import hashlib
import json
import re
import shutil
import stat
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from squadopt.application.entries import EntryRegistry
from squadopt.application.league_views import MemberStanding, _rank_movement
from squadopt.application.scoreboard import scoreboard_payload
from squadopt.application.site import build_site
from squadopt.application.weekly_suggestion_eval import (
    publish_suggestion_histories,
    review_member_weeks,
)
from squadopt.data.atomic import replace_retrying
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    EntryGameweekPoints,
    fpl_entry_history_points,
    fpl_league_standings,
    scored_gameweeks,
)
from squadopt.live import infer_season, load_ledger
from squadopt.live.tick import HeldSnapshot, LedgerState, plan_tick

# These are emitted by the existing season builder, but deliberately NOT carried.
_SEASON_AUXILIARIES = frozenset(
    (
        "index.json",
        "schema/ui_view_v1.schema.json",
        "schema/live_score_v1.schema.json",
        "schema/fixtures_v1.schema.json",
    )
)


@dataclass(frozen=True, slots=True)
class SettledPublicationRequest:
    accepted_dir: Path
    snapshot_root: Path
    snapshot_id: str
    registry_path: Path
    record_root: Path
    ledger_root: Path
    out_dir: Path
    season: str
    gameweek: int
    league_id: int = 352490


@dataclass(frozen=True, slots=True)
class SettledPublicationResult:
    out_dir: Path
    generated_at_utc: str
    changed_files: tuple[str, ...]
    #: What was checked on the candidate before it was written, one line per check.
    checks: tuple[str, ...] = ()


#: The league tree release check of a ``data`` directory, returning its findings. It runs
#: on the accepted tree and on the candidate before the candidate is written; a finding
#: the candidate has and the accepted tree does not refuses the candidate.
LeagueTreeCheck = Callable[[Path], Sequence[str]]

_CONTRACT_VERSION = re.compile(r"[a-z0-9_]+")


def _files(root: Path) -> dict[str, bytes]:
    result = {}
    for path in sorted(root.rglob("*")):
        if (
            path.is_symlink()
            or getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise DataError(f"Publication tree contains a link: {path.relative_to(root)}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _document(content: bytes, name: str) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict) or not isinstance(value.get("payload"), dict):
        raise DataError(f"Invalid publication document: {name}")
    return value


def _allowed(name: str, request: SettledPublicationRequest) -> bool:
    if {"advice", "entries"} & set(Path(name).parts):
        return False
    if name.startswith(f"data/{request.season}/"):
        return True
    # series-horizon is derived from the SAME history rows. Its consumer requires
    # the same member-week key set, so histories and this companion travel together.
    if name in (
        "data/league/members.json",
        "data/league/scoreboard.json",
        "data/league/series-horizon.json",
        "data/fixtures.json",
    ):
        return True
    path = Path(name)
    return path.parent.as_posix() == "data/league/history" and path.suffix == ".json"


def _preflight(
    request: SettledPublicationRequest,
) -> tuple[dict[str, bytes], dict[str, Any], CapturedSnapshot, dict[int, EntryGameweekPoints]]:
    if (request.season, request.gameweek, request.league_id) != ("2026-27", 5, 352490):
        raise DataError("This approved publisher is limited to 2026-27 GW5, league 352490.")
    out = request.out_dir.resolve()
    inputs = (
        request.accepted_dir,
        request.snapshot_root,
        request.registry_path,
        request.record_root,
        request.ledger_root,
    )
    if out.exists() or not out.parent.is_dir():
        raise DataError("Output must be a new scratch directory with an existing parent.")
    if any(out.is_relative_to(p.resolve()) or p.resolve().is_relative_to(out) for p in inputs):
        raise DataError("Output must be separate from every input path.")
    accepted = _files(request.accepted_dir)
    name = "data/league/members.json"
    if name not in accepted:
        raise DataError(f"Accepted tree is missing {name}")
    members = _document(accepted[name], name)
    payload = members["payload"]
    if (payload.get("season"), payload.get("gameweek"), payload.get("league_id")) != (
        request.season,
        request.gameweek,
        request.league_id,
    ):
        raise DataError("Accepted members must identify the GW5 decision publication.")
    rows = payload.get("members", [])
    ids = EntryRegistry.load(request.registry_path).ids()
    if len(ids) != 15 or len(rows) != 15 or {row.get("entry_id") for row in rows} != set(ids):
        raise DataError("The accepted tree and registry must identify the same fifteen members.")
    for path, content in accepted.items():
        if Path(path).name == "recommendation.json":
            decision_week = _document(content, path)["payload"].get("gameweek")
            if not isinstance(decision_week, int) or decision_week > request.gameweek:
                raise DataError(f"Later or unreadable decision in accepted tree: {path}")
        if "advice" in Path(path).parts and path.endswith(".json"):
            advice = _document(content, path)["payload"]
            if advice.get("gameweek") != request.gameweek:
                raise DataError(f"Advice outside the accepted GW5 decision: {path}")
    snapshot = read_snapshot(request.snapshot_root, request.snapshot_id)
    if snapshot.metadata.source != FPL_LIVE_SOURCE or infer_season(snapshot) != request.season:
        raise DataError("Outcome capture must be fpl-live in the accepted season.")
    if request.gameweek not in scored_gameweeks(snapshot.payloads[BOOTSTRAP_PAYLOAD]):
        raise DataError("GW5 must be finished AND data_checked before publication.")
    standings_name = f"league-{request.league_id}-standings.json"
    if standings_name not in snapshot.payloads:
        raise DataError(f"Missing completed capture standings: {standings_name}")
    standings = {
        row.entry_id: row
        for row in fpl_league_standings(
            snapshot.payloads[standings_name], league_id=request.league_id
        )
    }
    missing, extra = sorted(set(ids) - standings.keys()), sorted(standings.keys() - set(ids))
    if missing or extra:
        raise DataError(f"Standings member set differs: missing {missing}, extra {extra}.")
    for member in rows:
        standing = standings[member["entry_id"]]
        movement, places = _rank_movement(
            MemberStanding(
                entry_id=standing.entry_id,
                team_name=standing.entry_name,
                manager_name=standing.player_name,
                rank=standing.rank,
                last_rank=standing.last_rank,
            )
        )
        member.update(rank=standing.rank, movement=movement, movement_places=places)
    rows.sort(key=lambda member: (member["rank"], member["entry_id"]))
    scores = {}
    for entry_id in ids:
        history_name = f"entry-{entry_id}-history.json"
        history_content = snapshot.payloads.get(history_name)
        weeks = (
            fpl_entry_history_points(history_content, entry_id=entry_id) if history_content else ()
        )
        row = next((week for week in weeks if week.gameweek == request.gameweek), None)
        if row is None or row.transfer_cost is None or row.transfer_cost < 0:
            raise DataError(f"Missing complete GW5 member outcome: {history_name}")
        scores[entry_id] = row
    reviews = review_member_weeks(
        record_root=request.record_root,
        snapshot_root=request.snapshot_root,
        as_of_snapshot=snapshot,
        season=request.season,
        league_id=request.league_id,
        entry_ids=ids,
    )
    for entry_id, reviewed_weeks in reviews.items():
        if any(week.gameweek > request.gameweek for week in reviewed_weeks):
            raise DataError(f"Later advice record exists for member {entry_id}.")
        reviewed = next(
            (week for week in reviewed_weeks if week.gameweek == request.gameweek), None
        )
        if reviewed is None or reviewed.status != "available" or reviewed.actual is None:
            raise DataError(
                f"GW5 history cannot carry a realized comparison for member {entry_id}."
            )
        if reviewed.outcome_snapshot_id != request.snapshot_id:
            raise DataError(f"Member {entry_id} history did not settle on the named capture.")
        advice_path = f"data/league/advice/{entry_id}/saf-puan/1.json"
        # WeekReview carries advice_sha256: the canonical payload digest, not
        # published_sha256 (the envelope's original bytes and publication clock).
        payload = (
            _document(accepted[advice_path], advice_path)["payload"]
            if advice_path in accepted
            else None
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if payload is None or hashlib.sha256(encoded).hexdigest() != reviewed.advice_sha256:
            raise DataError(f"Recorded comparison does not match accepted advice: {advice_path}")
    ledger = load_ledger(request.ledger_root, request.season)
    if any(entry.gameweek > request.gameweek for entry in ledger):
        raise DataError("The ledger contains a later decision; this is only a GW5 outcome publish.")
    if not any(
        entry.gameweek == request.gameweek and entry.outcome is not None for entry in ledger
    ):
        raise DataError(
            f"Ledger {request.ledger_root} has no GW5 outcome; no settlement runs here."
        )
    ledger_path = f"data/{request.season}/ledger.json"
    if ledger_path in accepted:
        published_weeks = {
            row["gameweek"]
            for row in _document(accepted[ledger_path], ledger_path)["payload"]["rows"]
        }
        if published_weeks != {entry.gameweek for entry in ledger}:
            raise DataError("Ledger decision weeks differ from the accepted season ledger.")
    return accepted, members, snapshot, scores


def _carry_scoreboard_evidence(
    request: SettledPublicationRequest, document: dict[str, Any]
) -> None:
    """Retain independent historical cells, with their original week and sources.

    These cells do not enter the builder's system/member/game cumulative arithmetic.
    GW5 evidence is a separate approval: never infer it from an earlier comparison.
    """
    name = "data/league/scoreboard.json"
    source = request.accepted_dir / name
    if not source.exists():
        return
    previous = _document(source.read_bytes(), name)["payload"]
    if (previous.get("season"), previous.get("league_id")) != (
        request.season,
        request.league_id,
    ):
        raise DataError("Accepted scoreboard evidence belongs to another season or league.")
    payload = document["payload"]
    current = {row["gameweek"]: row for row in payload["gameweeks"]}
    independent = {"base", "elite_xi", "ownership_template"}
    ordinary = {"system", "league_mean", "game_mean"}
    seen = set()
    for row in previous["gameweeks"]:
        week = row["gameweek"]
        if type(week) is not int or week < 1 or week in seen:
            raise DataError("Accepted scoreboard has an invalid or repeated evidence week.")
        seen.add(week)
        cells = {}
        for cell in row.get("comparisons", []):
            kind = cell["kind"]
            if kind in ordinary:
                continue
            if kind not in independent or kind in cells:
                raise DataError(f"Cannot carry scoreboard comparison {kind!r} in GW{week}.")
            cells[kind] = cell
        top100 = row.get("top100")
        if week >= request.gameweek:
            if top100 is not None or any(cell.get("net") is not None for cell in cells.values()):
                raise DataError(f"Cannot carry unapproved scoreboard evidence for GW{week}.")
            continue
        if week not in current:
            raise DataError(f"Cannot carry scoreboard history: GW{week} is absent from capture.")
        if top100 is not None:
            if top100.get("gameweek") != week or not previous.get("cohort_snapshot_id"):
                raise DataError(f"Cannot carry Top-100 evidence with unclear GW{week} provenance.")
            current[week]["top100"] = top100
            # The carried cell still names its old week. These are that cohort's
            # original identities, not claims that the new capture includes it.
            for key in ("cohort_snapshot_id", "cohort_picks_snapshot_id"):
                payload[key] = previous.get(key)
        if cells:
            current[week]["comparisons"] = [
                cells.get(cell["kind"], cell) for cell in current[week]["comparisons"]
            ]


def _publish_scoreboard(
    request: SettledPublicationRequest,
    snapshot: CapturedSnapshot,
    candidate: Path,
    ids: tuple[int, ...],
) -> None:
    # The ordinary scoreboard service re-settles ledger entries in memory. This
    # command is explicitly forbidden to do that: render the persisted outcomes
    # through its existing pure document builder instead.
    document = scoreboard_payload(
        season=request.season,
        league_id=request.league_id,
        bootstrap=snapshot.payloads[BOOTSTRAP_PAYLOAD],
        captured_at_utc=snapshot.metadata.captured_at_utc,
        source_snapshot_id=request.snapshot_id,
        histories={i: snapshot.payloads[f"entry-{i}-history.json"] for i in ids},
        registered=ids,
        ledger_entries=load_ledger(request.ledger_root, request.season),
        cohort=None,
        generated_at_utc=snapshot.metadata.captured_at_utc,
    )
    _carry_scoreboard_evidence(request, document)
    (candidate / "data/league/scoreboard.json").write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _envelope(data: Path, relative: str) -> dict[str, Any]:
    name = f"data/{relative}"
    path = data / relative
    if not path.is_file():
        raise DataError(f"The candidate has no {name}.")
    return _document(path.read_bytes(), name)


def _check_frozen_schemas(data: Path, season: str) -> str:
    """Hold every rebuilt season document and the fixture list to the frozen schemas.

    The builder writes its own copy of each schema, and that copy is deliberately not
    carried (``_SEASON_AUXILIARIES``): the schemas the site serves are the ones the accepted
    tree froze. A rebuilt document is therefore checked against those, chosen by the
    ``contract_version`` it names, so a view whose shape moved since the accepted publish
    is refused here rather than served beside a schema it no longer matches.
    """

    relatives = [
        path.relative_to(data).as_posix() for path in sorted((data / season).rglob("*.json"))
    ] + ["fixtures.json"]
    validators: dict[str, Draft202012Validator] = {}
    for relative in relatives:
        document = _envelope(data, relative)
        version = document.get("contract_version")
        if not isinstance(version, str) or not _CONTRACT_VERSION.fullmatch(version):
            raise DataError(
                f"data/{relative} names no contract version a frozen schema could check: "
                f"{version!r}."
            )
        schema_name = f"data/schema/{version}.schema.json"
        if version not in validators:
            schema_path = data / "schema" / f"{version}.schema.json"
            if not schema_path.is_file():
                raise DataError(
                    f"data/{relative} is {version}, and the accepted tree froze no "
                    f"{schema_name} to check it against."
                )
            validators[version] = Draft202012Validator(json.loads(schema_path.read_bytes()))
        error = best_match(validators[version].iter_errors(document))
        if error is not None:
            raise DataError(
                f"data/{relative} does not match the frozen {schema_name} at "
                f"{error.json_path}: {error.message}"
            )
    return f"{len(relatives)} rebuilt documents match the frozen schemas"


def _check_fixtures_source(data: Path, snapshot_id: str) -> str:
    """The fixture list must be the outcome capture's, or its scores are an older week's.

    ``build_site`` skips the fixture list, with a printed line and nothing else, when the
    capture's fixtures cannot be read; the accepted tree's copy then stays in the candidate
    and would ship the decision capture's scores beside the settled outcomes.
    """

    payload = _envelope(data, "fixtures.json")["payload"]
    source = payload.get("source_snapshot_id")
    if source != snapshot_id:
        raise DataError(
            f"data/fixtures.json comes from {source!r}, not the outcome capture "
            f"{snapshot_id!r}: the capture's fixture list was not published, so the fixture "
            "scores would be an older capture's."
        )
    return f"data/fixtures.json comes from {snapshot_id}"


def _check_root_index(data: Path, season: str) -> str:
    """Hold the frozen root index to the candidate it will be served beside.

    The index is carried from the accepted tree and never rebuilt, so nothing else ties
    it to what the settled publish wrote: every file it names must be in the candidate,
    every gameweek view in the candidate must be named, and its weeks and latest view
    must be the ones the candidate's season ledger holds.
    """

    payload = _envelope(data, "index.json")["payload"]
    files = payload.get("files")
    if not isinstance(files, list) or not all(isinstance(name, str) for name in files):
        raise DataError("The frozen data/index.json names no list of files.")
    for name in files:
        parts = PurePosixPath(name).parts
        if not parts or PurePosixPath(name).is_absolute() or ".." in parts:
            raise DataError(f"The frozen data/index.json names a path outside data/: {name!r}.")
    missing = sorted(name for name in files if not (data / name).is_file())
    if missing:
        raise DataError(
            f"The frozen data/index.json names {len(missing)} file(s) the candidate lacks: "
            f"{missing[:5]}."
        )
    views = {path.relative_to(data).as_posix() for path in (data / season).glob("gw*/*.json")}
    unnamed = sorted(views - set(files))
    if unnamed:
        raise DataError(
            f"The candidate carries {len(unnamed)} gameweek view(s) the frozen "
            f"data/index.json does not name: {unnamed[:5]}."
        )
    rows = _envelope(data, f"{season}/ledger.json")["payload"].get("rows")
    if not isinstance(rows, list):
        raise DataError(f"data/{season}/ledger.json has no rows.")
    weeks: list[int] = []
    for row in rows:
        week = row.get("gameweek") if isinstance(row, dict) else None
        if type(week) is not int:
            raise DataError(f"data/{season}/ledger.json has a row without a gameweek number.")
        weeks.append(week)
    weeks.sort()
    gameweeks = payload.get("gameweeks")
    indexed = gameweeks.get(season) if isinstance(gameweeks, dict) else None
    if (
        not isinstance(indexed, list)
        or not all(type(week) is int for week in indexed)
        or sorted(indexed) != weeks
    ):
        raise DataError(
            f"The frozen data/index.json lists {season} gameweeks {indexed}, and the "
            f"candidate's data/{season}/ledger.json holds {weeks}."
        )
    expected = (
        {
            "season": season,
            "gameweek": weeks[-1],
            "path": f"{season}/gw{weeks[-1]:02d}/recommendation.json",
        }
        if weeks
        else None
    )
    if payload.get("latest") != expected:
        raise DataError(
            f"The frozen data/index.json names {payload.get('latest')} as the latest view, "
            f"and the candidate's ledger ends at {expected}."
        )
    return f"the frozen data/index.json names the candidate's {len(files)} files and weeks"


def _check_league_tree(
    data: Path, request: SettledPublicationRequest, league_tree_check: LeagueTreeCheck
) -> str:
    """Refuse what the league tree check finds in the candidate and not in the accepted tree.

    The check reads mostly advice, and this publish can change none of it: a finding the
    accepted tree already has is in bytes members read before the deadline, which only a
    new decision publish could replace. Refusing on it would leave the week unpublishable
    whenever the checker grew stricter after the decision shipped (measured on 2026-09-25: a
    stricter price rule proposed for the checker finds 600 problems in the shipped GW5
    advice). So those are counted and reported, and only a finding this publish introduced
    refuses.
    """

    accepted = Counter(league_tree_check(request.accepted_dir / "data"))
    introduced = list((Counter(league_tree_check(data)) - accepted).elements())
    if introduced:
        raise DataError(
            f"The candidate fails the league tree check with {len(introduced)} finding(s) "
            f"the accepted tree does not have; the first: {introduced[0]}"
        )
    carried = sum(accepted.values())
    if carried:
        return (
            f"the league tree check found nothing new ({carried} finding(s) the accepted "
            "tree already had)"
        )
    return "the league tree check found nothing"


def _check_candidate(
    data: Path, request: SettledPublicationRequest, league_tree_check: LeagueTreeCheck | None
) -> tuple[str, ...]:
    checks = [
        _check_frozen_schemas(data, request.season),
        _check_fixtures_source(data, request.snapshot_id),
        _check_root_index(data, request.season),
    ]
    if league_tree_check is not None:
        checks.append(_check_league_tree(data, request, league_tree_check))
    return tuple(checks)


def publish_settled(
    request: SettledPublicationRequest, *, league_tree_check: LeagueTreeCheck | None = None
) -> SettledPublicationResult:
    """Build a complete scratch candidate, or expose no candidate at all on refusal.

    ``league_tree_check`` runs with the other checks, on the accepted tree and on the
    candidate, before the candidate is written. The command line passes
    ``scripts.check_league_tree``, which this package cannot import.
    """
    accepted, members, snapshot, scores = _preflight(request)
    stamp = snapshot.metadata.captured_at_utc
    with TemporaryDirectory(prefix="settled-", dir=request.out_dir.parent) as temporary:
        root = Path(temporary)
        candidate = root / "candidate"
        shutil.copytree(request.accepted_dir, candidate)
        season_stage = root / "season"
        shutil.copytree(
            request.accepted_dir / "data" / request.season, season_stage / "data" / request.season
        )
        ledger = load_ledger(request.ledger_root, request.season)
        plan = plan_tick(
            now_utc=stamp,
            held=[HeldSnapshot(request.snapshot_id, stamp)],
            latest=snapshot,
            ledger=LedgerState(
                decided=frozenset(entry.gameweek for entry in ledger),
                settled=frozenset(entry.gameweek for entry in ledger if entry.outcome is not None),
            ),
            handoff_root=root / "no-handoffs",
            season=request.season,
        )
        next_week = plan.diagnostics.get("next_gameweek")
        if not isinstance(next_week, int) or next_week <= request.gameweek:
            raise DataError("The outcome capture must move status beyond GW5.")
        build_site(
            ledger_root=request.ledger_root,
            season=request.season,
            out_dir=season_stage,
            snapshot=snapshot,
            plan=plan,
            now=datetime.fromisoformat(stamp.replace("Z", "+00:00")),
        )
        for path, content in _files(season_stage / "data").items():
            if path.startswith(f"{request.season}/") or path == "fixtures.json":
                target = candidate / "data" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            elif path not in _SEASON_AUXILIARIES:
                raise DataError(
                    f"Season publisher needs a path outside the approved list: data/{path}"
                )
        _publish_scoreboard(request, snapshot, candidate, tuple(scores))
        publish_suggestion_histories(
            record_root=request.record_root,
            snapshot_root=request.snapshot_root,
            as_of_snapshot=snapshot,
            season=request.season,
            league_id=request.league_id,
            entry_ids=tuple(scores),
            out_dir=candidate / "data" / "league",
        )
        members["generated_at_utc"] = stamp
        members["payload"]["scored_gameweek"] = request.gameweek
        for member in members["payload"]["members"]:
            score = scores[member["entry_id"]]
            member.update(
                gameweek_points=score.points,
                transfer_cost=score.transfer_cost,
                total_points=score.total_points,
            )
        (candidate / "data/league/members.json").write_text(
            json.dumps(members, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        proposed = _files(candidate)
        changed = tuple(
            sorted(
                name
                for name in accepted.keys() | proposed.keys()
                if accepted.get(name) != proposed.get(name)
            )
        )
        for path in changed:
            if not _allowed(path, request):
                raise DataError(f"Publisher changed a path outside the approved list: {path}")
        checks = _check_candidate(candidate / "data", request, league_tree_check)
        if _files(request.accepted_dir) != accepted:
            raise DataError("The accepted tree changed during generation; no candidate published.")
        replace_retrying(candidate, request.out_dir)
    return SettledPublicationResult(request.out_dir, stamp, changed, checks)
