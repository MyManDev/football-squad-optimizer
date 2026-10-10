"""Read #1009(b)'s fixed comparison once, after the declared settled GW20 capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from squadopt.data.atomic import WRITTEN, write_document_once
from squadopt.data.errors import DataError
from squadopt.data.snapshots import (
    CapturedSnapshot,
    SnapshotMetadata,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    gameweek_deadlines,
    live_payload,
    next_open_deadline,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.evaluation.promotion import ExperimentExecutionError
from squadopt.experiments.published_difficulty_live import (
    SEASON,
    DifficultyInputError,
    DifficultyMissingInputs,
    DifficultySolveFailure,
    DifficultyWeek,
    decode,
    measure_week,
    require_season,
    summarize,
    verify_coefficients,
)
from squadopt.live.recommendation import (
    InSeasonProjection,
    infer_season,
    project,
    read_inputs,
    read_projection_handoff,
)
from squadopt.live.tick import handoff_path_for
from squadopt.optimization.models import SquadOptimizationError
from squadopt.platform.capture_context import handoff_fingerprint_for

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = "docs/research/published_difficulty_live_prereg.md"
DECLARATION_SHA256 = "2ef26f6033483f686b98487696e09d7dfbb62ff253fc1a3a730bf2e053fa10bd"
CAPTURE_NAME = re.compile(r"fpl-live-(?:2026(?:0[89]|1[012])|20270[1-5])\d{2}T\d{6}Z-[0-9a-f]{12}")
HASH = re.compile(r"[0-9a-f]{64}")


def safe_path(path: Path) -> Path:
    resolved = path.resolve()
    spelling = resolved.as_posix().casefold()
    if any(spelling == p or spelling.startswith(p + "/") for p in ("c:/sqr", "c:/sqrweb")):
        raise DifficultyInputError("Rehearsal folders are forbidden inputs and outputs.")
    return resolved


def command(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def digest(content: bytes) -> str:
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def frozen_declaration() -> dict[str, str]:
    info = json.loads(
        command(
            "gh",
            "pr",
            "view",
            "1033",
            "--repo",
            "MyManDev/football-squad-optimizer",
            "--json",
            "state,mergedAt,mergeCommit",
        )
    )
    if info.get("state") != "MERGED" or not info.get("mergedAt"):
        raise DifficultyInputError(
            "The preregistration must merge before any real input is opened."
        )
    merged = info["mergeCommit"]["oid"]
    content = subprocess.run(
        ["git", "show", f"{merged}:{DECLARATION}"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    if (
        digest(content) != DECLARATION_SHA256
        or digest((ROOT / DECLARATION).read_bytes()) != DECLARATION_SHA256
    ):
        raise DifficultyInputError("The accepted declaration differs; runner review is required.")
    command("git", "merge-base", "--is-ancestor", merged, "HEAD")
    if command("git", "status", "--porcelain", "--untracked-files=normal"):
        raise DifficultyInputError("The reading requires clean committed code.")
    verify_coefficients((ROOT / "docs/opponent_projection_study.json").read_bytes())
    return {
        "merge_commit": merged,
        "merged_at": normalize_utc_timestamp(info["mergedAt"], label="merge"),
        "sha256": DECLARATION_SHA256,
        "code_commit": command("git", "rev-parse", "HEAD"),
    }


def partial_snapshot(
    directory: Path, names: tuple[str, ...] = (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD)
) -> CapturedSnapshot:
    directory = safe_path(directory)
    if not CAPTURE_NAME.fullmatch(directory.name):
        raise DifficultyInputError("A capture name is outside the admitted 2026-27 season range.")
    doc = decode((directory / "metadata.json").read_bytes())
    hashes = doc["checksums"]
    if (
        not isinstance(hashes, dict)
        or not hashes
        or any(
            not isinstance(k, str)
            or not re.fullmatch(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", k)
            or not isinstance(v, str)
            or not HASH.fullmatch(v)
            for k, v in hashes.items()
        )
    ):
        raise DifficultyInputError("The payload inventory is invalid.")
    stamp = normalize_utc_timestamp(doc["captured_at_utc"], label="capture")
    fingerprint = snapshot_fingerprint(
        source=doc["source"],
        captured_at_utc=stamp,
        schema_version=doc["schema_version"],
        checksums=hashes,
    )
    if (
        doc["source"] != "fpl-live"
        or doc["schema_version"] != "snapshot_v1"
        or (
            fingerprint != doc["fingerprint"]
            or directory.name != doc["snapshot_id"]
            or directory.name
            != build_snapshot_id(source="fpl-live", captured_at_utc=stamp, fingerprint=fingerprint)
        )
    ):
        raise DifficultyInputError("The capture identity is invalid.")
    metadata = SnapshotMetadata(
        directory.name, "fpl-live", stamp, "snapshot_v1", hashes, fingerprint
    )
    payloads: dict[str, bytes] = {}
    # Season is checked from verified bootstrap bytes before any outcome loader call.
    for name in dict.fromkeys((BOOTSTRAP_PAYLOAD, *names)):
        if name not in hashes:
            raise DifficultyMissingInputs("A required captured payload is absent.")
        content = safe_path(directory / "payloads" / name).read_bytes()
        if payload_checksum(content) != hashes[name]:
            raise DifficultyMissingInputs("A payload differs from its captured checksum.")
        payloads[name] = content
        if name == BOOTSTRAP_PAYLOAD:
            require_season(infer_season(CapturedSnapshot(metadata, payloads)))
    return CapturedSnapshot(metadata, payloads)


def inventory(root: Path, *, season: str, as_of: str) -> dict[str, CapturedSnapshot]:
    require_season(season)
    result = {}
    for directory in sorted(safe_path(root).iterdir()):
        if directory.is_dir() and CAPTURE_NAME.fullmatch(directory.name):
            named_instant = datetime.strptime(
                directory.name.split("-")[2], "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=UTC)
            if named_instant > as_instant(as_of):
                continue
            snapshot = partial_snapshot(directory)
            if as_instant(snapshot.metadata.captured_at_utc) <= as_instant(as_of):
                result[snapshot.metadata.snapshot_id] = snapshot
    return result


def bootstrap(snapshot: CapturedSnapshot) -> dict[str, Any]:
    return dict(decode(snapshot.payloads[BOOTSTRAP_PAYLOAD]))


def fixtures(snapshot: CapturedSnapshot) -> list[dict[str, Any]]:
    values = decode(snapshot.payloads[FIXTURES_PAYLOAD])
    if not isinstance(values, list) or len({f["id"] for f in values}) != len(values):
        raise DifficultyInputError("The fixture inventory has invalid or duplicate ids.")
    return values


def first_settled(captures: Mapping[str, CapturedSnapshot]) -> CapturedSnapshot:
    for snapshot in sorted(
        captures.values(),
        key=lambda s: (as_instant(s.metadata.captured_at_utc), s.metadata.snapshot_id),
    ):
        events = [e for e in bootstrap(snapshot)["events"] if e["id"] == 20]
        played = [f for f in fixtures(snapshot) if f.get("event") == 20]
        if (
            len(events) == 1
            and events[0].get("finished") is True
            and events[0].get("data_checked") is True
            and as_instant(events[0]["deadline_time"])
            < as_instant(snapshot.metadata.captured_at_utc)
            and all(
                f.get("finished") is True
                and f.get("finished_provisional") is True
                and isinstance(f.get("kickoff_time"), str)
                and as_instant(f["kickoff_time"]) < as_instant(snapshot.metadata.captured_at_utc)
                for f in played
            )
        ):
            return snapshot
    raise DifficultyMissingInputs("GW20 is not settled; no real comparison can be printed.")


def eligible_weeks(snapshot: CapturedSnapshot, merged_at: str) -> tuple[int, ...]:
    deadlines = gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    return tuple(
        sorted(
            d.gameweek
            for d in deadlines
            if d.gameweek <= 20 and as_instant(d.deadline_utc) > as_instant(merged_at)
        )
    )


def decision_capture(captures: Mapping[str, CapturedSnapshot], week: int) -> CapturedSnapshot:
    matches = []
    for snapshot in captures.values():
        deadlines = gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD])
        try:
            target = next_open_deadline(deadlines, as_of_utc=snapshot.metadata.captured_at_utc)
        except DataError:
            continue
        if target.gameweek == week:
            matches.append(snapshot)
    if not matches:
        raise DifficultyMissingInputs("No targeting pre-deadline decision capture is retained.")
    instant = max(as_instant(s.metadata.captured_at_utc) for s in matches)
    latest = [s for s in matches if as_instant(s.metadata.captured_at_utc) == instant]
    if len(latest) != 1:
        raise DifficultyMissingInputs("The latest decision capture instant is ambiguous.")
    return latest[0]


def paired_handoff(
    root: Path, snapshot: CapturedSnapshot, week: int
) -> tuple[InSeasonProjection, dict[str, Any]]:
    root = safe_path(root)
    inputs = read_inputs(snapshot, season=SEASON, gameweek=week)
    alias = handoff_path_for(root, SEASON, week)
    retained = root / "by-capture" / snapshot.metadata.snapshot_id
    matched: dict[str, tuple[InSeasonProjection, Path, str]] = {}
    for path in (alias, *sorted(retained.glob("*.json"))):
        try:
            content = safe_path(path).read_bytes()
            decode(content)
            handoff = read_projection_handoff(path)
            if (handoff.source_snapshot_id, handoff.season, handoff.gameweek) != (
                snapshot.metadata.snapshot_id,
                SEASON,
                week,
            ):
                continue
            if path.stat().st_mtime >= as_instant(inputs.deadline.deadline_utc).timestamp():
                continue
            matched[handoff.fingerprint] = (handoff, path, hashlib.sha256(content).hexdigest())
        except (DataError, OSError, ValueError):
            continue
    fingerprint = handoff_fingerprint_for(root, SEASON, week, snapshot.metadata.snapshot_id)
    if len(matched) != 1 or fingerprint not in matched:
        raise DifficultyMissingInputs("The capture cannot pair with exactly one stored handoff.")
    handoff, path, file_hash = matched[fingerprint]
    return handoff, {
        "handoff_fingerprint": fingerprint,
        "handoff_version": handoff.model_version,
        "handoff_sha256": file_hash,
        "handoff_file": str(path),
        "handoff_file_time": path.stat().st_mtime,
    }


def elements(snapshot: CapturedSnapshot) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    codes = set()
    for item in bootstrap(snapshot)["elements"]:
        if (
            type(item["id"]) is not int
            or item["id"] <= 0
            or type(item["code"]) is not int
            or item["code"] <= 0
            or item["id"] in result
            or item["code"] in codes
        ):
            raise DifficultyInputError("The roster has an invalid or duplicate player identity.")
        result[item["id"]] = item
        codes.add(item["code"])
    return result


def captured_club_ratings(decision: CapturedSnapshot, week: int) -> dict[int, list[float]]:
    held_fixtures = [f for f in fixtures(decision) if f.get("event") == week]
    clubs: dict[int, list[float]] = {}
    for fixture in held_fixtures:
        for side in ("h", "a"):
            rating = fixture.get("team_" + side + "_difficulty")
            if not isinstance(rating, (int, float)) or isinstance(rating, bool):
                raise DifficultyMissingInputs(
                    "A captured fixture difficulty is missing or invalid."
                )
            if not np.isfinite(rating) or not 1 <= rating <= 5:
                raise DifficultyMissingInputs(
                    "A captured fixture difficulty is missing or invalid."
                )
            clubs.setdefault(fixture["team_" + side], []).append(float(rating))
    return clubs


def joined_rows(
    decision: CapturedSnapshot,
    handoff: InSeasonProjection,
    outcome: CapturedSnapshot,
    week: int,
    *,
    projected: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[int]]:
    decided = elements(decision)
    realized_ids = elements(outcome)
    if projected is None:
        projected = project(
            read_inputs(decision, season=SEASON, gameweek=week), in_season=handoff
        ).table
    totals = {}
    seen = set()
    for item in decode(outcome.payloads[live_payload(week)])["elements"]:
        if type(item["id"]) is not int or item["id"] in seen:
            raise DifficultyMissingInputs("A realized player identity is invalid or duplicated.")
        seen.add(item["id"])
        if item["id"] in realized_ids:
            points = item["stats"]["total_points"]
            if type(points) is not int:
                raise DifficultyMissingInputs("A realized points row is invalid.")
            totals[realized_ids[item["id"]]["code"]] = points
    clubs = captured_club_ratings(decision, week)
    code_to_club = {item["code"]: item["team"] for item in decided.values()}
    rows = projected.rename(columns={"expected_points": "predicted_points"}).copy()
    dropped = sorted(set(int(v) for v in rows["player_id"]) - set(totals))
    rows = rows.loc[rows["player_id"].isin(totals)].copy()
    if rows.empty:
        raise DifficultyMissingInputs("No captured player has a settled outcome row.")
    rows["realized_points"] = rows["player_id"].map(totals)
    rows["fixture_count"] = [
        len(clubs.get(code_to_club[int(code)], [])) for code in rows["player_id"]
    ]
    rows["published_signal"] = [
        -float(np.mean(clubs[code_to_club[int(code)]]))
        if code_to_club[int(code)] in clubs
        else float("nan")
        for code in rows["player_id"]
    ]
    return rows.sort_values("player_id").reset_index(drop=True), dropped


def reading(
    captures: Mapping[str, CapturedSnapshot],
    *,
    snapshot_root: Path,
    handoff_root: Path,
    declaration: Mapping[str, str],
    as_of: str,
    output_directory: Path,
    owner_approved: bool,
    weekly_run_idle: bool,
) -> dict[str, Any]:
    if not owner_approved or not weekly_run_idle:
        raise DifficultyInputError(
            "The owner must authorize the reading outside weekly operations."
        )
    selected = first_settled(captures)
    if as_instant(selected.metadata.captured_at_utc) > as_instant(as_of):
        raise DifficultyMissingInputs("The reading instant precedes the settled capture.")
    # Every week joins this roster, so it is refused before the claim, not after.
    elements(selected)
    weeks = eligible_weeks(selected, declaration["merged_at"])
    output = safe_path(output_directory)
    private = safe_path(ROOT / "artifacts")
    if not output.is_relative_to(private):
        raise DifficultyInputError(
            "Reading evidence must stay under this worktree's ignored artifacts."
        )
    if command(
        "git", "log", "--all", "--format=%H", "--", "docs/research/published_difficulty_live.json"
    ):
        raise DifficultyInputError("A committed verdict record prevents another reading.")
    claims = safe_path(
        Path(command("git", "rev-parse", "--path-format=absolute", "--git-common-dir"))
        / "research-claims/published-difficulty"
    )
    claim = claims / (DECLARATION_SHA256 + "-claim.json")
    if claim.exists():
        raise DifficultyInputError("This declaration already claimed its single reading.")
    if not safe_path(handoff_root).is_dir():
        raise DifficultyMissingInputs("The handoff root is absent; no reading was claimed.")
    prepared = {}
    audit: list[dict[str, Any]] = []
    for week in weeks:
        proof: dict[str, Any] = {}
        try:
            decision = decision_capture(captures, week)
            handoff, proof = paired_handoff(handoff_root, decision, week)
            projected = project(
                read_inputs(decision, season=SEASON, gameweek=week), in_season=handoff
            ).table
            elements(decision)
            captured_club_ratings(decision, week)
            prepared[week] = (decision, handoff, proof, projected)
        except (DifficultyMissingInputs, DataError, OSError, KeyError, TypeError) as error:
            audit.append(
                {
                    "gameweek": week,
                    "status": "missing",
                    "reason": type(error).__name__,
                    "identity": proof,
                    "solver_decisions": None,
                }
            )
    if not prepared:
        raise DifficultyMissingInputs(
            "No week pairs with valid projection inputs; no reading was claimed."
        )
    output.mkdir(parents=True, exist_ok=True)
    claims.mkdir(parents=True, exist_ok=True)
    if (
        write_document_once(
            {"capture": selected.metadata.snapshot_id, "declaration": dict(declaration)}, claim
        )
        != WRITTEN
    ):
        raise DifficultyInputError("This declaration already claimed its single reading.")
    measured: list[DifficultyWeek] = []
    evidence = []
    try:
        for week, (decision, handoff, proof, projected) in prepared.items():
            try:
                settled = partial_snapshot(
                    safe_path(snapshot_root) / selected.metadata.snapshot_id,
                    (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload(week)),
                )
                events = [e for e in bootstrap(settled)["events"] if e["id"] == week]
                played = [f for f in fixtures(settled) if f.get("event") == week]
                if (
                    len(events) != 1
                    or events[0].get("finished") is not True
                    or events[0].get("data_checked") is not True
                    or not all(f.get("finished") is True for f in played)
                ):
                    raise DifficultyMissingInputs(
                        "The selected reading capture has no settled week."
                    )
                rows, dropped = joined_rows(decision, handoff, settled, week, projected=projected)
                measured_week, player_evidence = measure_week(
                    rows, season=SEASON, gameweek=week, handoff_version=handoff.model_version
                )
                measured.append(measured_week)
                evidence.append((week, player_evidence))
                audit.append(
                    {
                        "gameweek": week,
                        "status": "scored",
                        "identity": proof,
                        "decision_capture": decision.metadata.snapshot_id,
                        "decision_fingerprint": decision.metadata.fingerprint,
                        "decision_input_hashes": dict(decision.metadata.checksums),
                        "dropped_player_codes": dropped,
                        "reading_input_hashes": dict(settled.metadata.checksums),
                        "reading": asdict(measured_week),
                    }
                )
            except (
                DifficultyMissingInputs,
                DataError,
                OSError,
                KeyError,
                TypeError,
                ExperimentExecutionError,
                SquadOptimizationError,
            ) as error:
                audit.append(
                    {
                        "gameweek": week,
                        "status": "missing",
                        "reason": type(error).__name__,
                        "identity": proof,
                        "solver_decisions": error.decisions
                        if isinstance(error, DifficultySolveFailure)
                        else None,
                    }
                )
        report = {
            "contract_version": "published_difficulty_live_reading_v1",
            "season": SEASON,
            "declaration": dict(declaration),
            "as_of": as_of,
            "reading_capture": selected.metadata.snapshot_id,
            "reading_fingerprint": selected.metadata.fingerprint,
            "reading_input_hashes": dict(selected.metadata.checksums),
            "eligible_weeks": list(weeks),
            "week_identities": sorted(audit, key=lambda item: item["gameweek"]),
            **summarize(tuple(measured)),
        }
        if write_document_once(report, output / "reading.json") != WRITTEN:
            raise DifficultyInputError("A saved reading record already exists.")
        for week, frame in evidence:
            with (output / f"gw{week:02d}-players.csv").open(
                "x", encoding="utf-8", newline=""
            ) as stream:
                frame.to_csv(stream, index=False)
        return report
    except (ValueError, DataError, OSError, KeyError, TypeError):
        write_document_once(
            {"status": "reading_refused", "declaration": dict(declaration)}, output / "refused.json"
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=SEASON)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--handoff-root", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--weekly-run-idle", action="store_true")
    args = parser.parse_args()
    try:
        require_season(args.season)
        declaration = frozen_declaration()
        if not args.owner_approved or not args.weekly_run_idle:
            raise DifficultyInputError("Owner approval and an idle weekly-run window are required.")
        as_of = normalize_utc_timestamp(args.as_of, label="reading instant")
        captures = inventory(args.snapshot_root, season=args.season, as_of=as_of)
        report = reading(
            captures,
            snapshot_root=args.snapshot_root,
            handoff_root=args.handoff_root,
            declaration=declaration,
            as_of=as_of,
            output_directory=args.output_directory,
            owner_approved=args.owner_approved,
            weekly_run_idle=args.weekly_run_idle,
        )
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, DataError, OSError, KeyError, TypeError, subprocess.CalledProcessError):
        print(
            json.dumps(
                {
                    "status": "refused",
                    "promotion": False,
                    "reason": "fixed_identity_or_verdict_date_gate_failed",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
