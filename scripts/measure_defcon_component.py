"""Offline #1000 input inventory and the single preregistered DEFCON reading.

The input check verifies metadata and publication identities without opening any
event-live payload. The owner authorizes the reading outside weekly operations.
No mode fetches FPL, trains a base model, publishes or promotes a candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.application.defcon_component import (
    DefconInputError,
    DefconMissingInputs,
    candidate_handoff,
    decode,
    fixture_counts,
    fixture_map,
    history_week,
    identity,
    integer,
    settled,
)
from squadopt.data.atomic import WRITTEN, write_document_once
from squadopt.data.errors import DataError
from squadopt.data.snapshots import (
    CapturedSnapshot,
    SnapshotMetadata,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.experiments.defcon_component_reading import PairedDefconRow, summarize
from squadopt.live.recommendation import project, read_inputs, read_projection_handoff
from squadopt.live.rules import read_season_rules
from squadopt.prediction.defcon_component import (
    DEFCON_CANDIDATE_VERSIONS,
    DEFCON_SEASON,
    DefconComponentError,
)

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = "docs/defcon_component_prereg.md"
DECLARATION_SHA256 = "1c8b409cd3f49ccc7fd1de3364cce64828fbd827d607135a1c108856c2839afc"
RECORD = "docs/research/defcon_component_reading"
MERGE_BOUNDARY = "2026-10-12T19:00:00Z"
CAPTURE_NAME = re.compile(r"fpl-live-(?:2026(?:0[89]|1[012])|20270[1-5])\d{2}T\d{6}Z-[0-9a-f]{12}")
HASH = re.compile(r"[0-9a-f]{64}")


def safe_path(path: Path) -> Path:
    resolved = path.resolve()
    spelling = resolved.as_posix().casefold()
    if any(
        spelling == prefix or spelling.startswith(prefix + "/")
        for prefix in ("c:/sqr", "c:/sqrweb")
    ):
        raise DefconInputError("Rehearsal directories are forbidden inputs and outputs.")
    return resolved


def normalized_digest(content: bytes) -> str:
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def command(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def frozen_declaration() -> dict[str, str]:
    """Require authoritative merge time and identical, clean declaration bytes."""
    info = json.loads(
        command(
            "gh",
            "pr",
            "view",
            "1017",
            "--repo",
            "MyManDev/football-squad-optimizer",
            "--json",
            "state,mergedAt,mergeCommit",
        )
    )
    if info.get("state") != "MERGED" or not info.get("mergedAt"):
        raise DefconInputError("The preregistration PR must be merged before any input mode.")
    merged = info["mergeCommit"]["oid"]
    blob = subprocess.run(
        ["git", "show", f"{merged}:{DECLARATION}"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    if (
        normalized_digest(blob) != DECLARATION_SHA256
        or normalized_digest((ROOT / DECLARATION).read_bytes()) != DECLARATION_SHA256
    ):
        raise DefconInputError(
            "The accepted declaration differs from this fixed runner; review is required."
        )
    command("git", "merge-base", "--is-ancestor", merged, "HEAD")
    if command("git", "status", "--porcelain", "--untracked-files=normal"):
        raise DefconInputError("Use a clean committed worktree for input checks and the reading.")
    return {
        "merged_at": normalize_utc_timestamp(info["mergedAt"], label="declaration merge"),
        "merge_commit": merged,
        "sha256": DECLARATION_SHA256,
        "code_commit": command("git", "rev-parse", "HEAD"),
    }


def window(declaration: Mapping[str, str]) -> tuple[int, ...]:
    start = 6 if as_instant(declaration["merged_at"]) < as_instant(MERGE_BOUNDARY) else 7
    return tuple(range(start, start + 7))


def partial_snapshot(
    directory: Path, names: tuple[str, ...] = (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD)
) -> CapturedSnapshot:
    """Verify the metadata binding, then read only named payloads, never all of them."""
    directory = safe_path(directory)
    if not CAPTURE_NAME.fullmatch(directory.name):
        raise DefconInputError("Only named 2026-27 fpl-live captures are admitted.")
    doc = decode((directory / "metadata.json").read_bytes())
    checksums = doc["checksums"]
    if (
        not isinstance(checksums, dict)
        or not checksums
        or any(
            not re.fullmatch(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", key)
            or not isinstance(value, str)
            or not HASH.fullmatch(value)
            for key, value in checksums.items()
        )
    ):
        raise DefconInputError("The payload inventory or its checksums are invalid.")
    stamp = normalize_utc_timestamp(doc["captured_at_utc"], label="capture")
    fingerprint = snapshot_fingerprint(
        source=doc["source"],
        captured_at_utc=stamp,
        schema_version=doc["schema_version"],
        checksums=checksums,
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
        raise DefconInputError("The retained capture identity fails validation.")
    metadata = SnapshotMetadata(
        directory.name, "fpl-live", stamp, "snapshot_v1", checksums, fingerprint
    )
    payloads = {}
    for name in names:
        if name not in checksums:
            raise DefconMissingInputs("A required payload is not in the retained inventory.")
        content = safe_path(directory / "payloads" / name).read_bytes()
        if payload_checksum(content) != checksums[name]:
            raise DefconMissingInputs("A required payload differs from its captured checksum.")
        payloads[name] = content
    snapshot = CapturedSnapshot(metadata, payloads)
    identity(snapshot)
    return snapshot


def inventory(root: Path, *, as_of: str) -> dict[str, CapturedSnapshot]:
    result = {}
    for directory in sorted(safe_path(root).iterdir()):
        if directory.is_dir() and CAPTURE_NAME.fullmatch(directory.name):
            snapshot = partial_snapshot(directory)
            if as_instant(snapshot.metadata.captured_at_utc) <= as_instant(as_of):
                result[directory.name] = snapshot
    return result


def published_pair(
    publications: Path,
    handoffs: Path,
    captures: Mapping[str, CapturedSnapshot],
    week: int,
    *,
    as_of: str,
) -> tuple[CapturedSnapshot, Any, dict[str, Any]]:
    records: list[tuple[datetime, Any, CapturedSnapshot | None, str]] = []
    for path in sorted(
        (safe_path(publications) / DEFCON_SEASON / f"gw{week:02d}").glob("entry-*/*/advice.json")
    ):
        content = safe_path(path).read_bytes()
        doc = decode(content)
        if doc["season"] != DEFCON_SEASON or integer(doc["gameweek"], minimum=1) != week:
            raise DefconInputError("The retained publication has an invalid season or target.")
        if (
            doc["contract_version"] != "member_advice_record_v2"
            or doc["player_id_space"] != "fpl_element_code"
        ):
            raise DefconMissingInputs("The publication identity contract is unsupported.")
        capture = captures.get(doc["capture"]["snapshot_id"])
        stamp = as_instant(doc["generated_at_utc"])
        if stamp > as_instant(as_of):
            continue
        if capture is None:
            # An absent last publication capture must not silently select an earlier one.
            records.append((stamp, doc, None, payload_checksum(content)))
            continue
        inputs = read_inputs(capture, season=DEFCON_SEASON, gameweek=week)
        if stamp >= as_instant(inputs.deadline.deadline_utc) or stamp > as_instant(as_of):
            continue
        if doc["capture"]["captured_at_utc"] != capture.metadata.captured_at_utc or (
            as_instant(capture.metadata.captured_at_utc) > stamp
        ):
            raise DefconMissingInputs("The publication and retained capture instant disagree.")
        records.append((stamp, doc, capture, payload_checksum(content)))
    if not records:
        raise DefconMissingInputs("No final pre-deadline publication identity is retained.")
    last = max(item[0] for item in records)
    finalists = [item for item in records if item[0] == last]
    identities = {
        (item[1]["capture"]["snapshot_id"], item[1]["provenance"]["projection_handoff_fingerprint"])
        for item in finalists
    }
    if len(identities) != 1:
        raise DefconMissingInputs("The last publication has ambiguous default identity.")
    selected = finalists[0]
    capture = selected[2]
    if capture is None:
        raise DefconMissingInputs("The final publication decision capture is absent.")
    identifier, fingerprint = next(iter(identities))
    if any(
        item[1]["provenance"]["projection_handoff_fingerprint"] != fingerprint
        for item in records
        if item[1]["capture"]["snapshot_id"] == identifier
    ):
        raise DefconMissingInputs(
            "The final publication capture has inconsistent default identities."
        )
    matches = []
    for path in sorted((safe_path(handoffs) / "by-capture" / identifier).glob("*.json")):
        content = safe_path(path).read_bytes()
        doc = decode(content)
        if doc.get("season") != DEFCON_SEASON:
            raise DefconInputError("A 2025-26 or other-season handoff is forbidden.")
        keys = list(doc.get("expected_points", {}))
        if any(not re.fullmatch(r"[1-9][0-9]*", key) for key in keys):
            raise DefconInputError("The handoff roster keys are not canonical persistent codes.")
        handoff = read_projection_handoff(path)
        if doc.get("fingerprint") != handoff.fingerprint:
            raise DefconInputError("The handoff lacks an exact recorded fingerprint.")
        if handoff.fingerprint == fingerprint:
            if (
                handoff.gameweek != week
                or handoff.source_snapshot_id != identifier
                or handoff.model_version not in DEFCON_CANDIDATE_VERSIONS
            ):
                raise DefconMissingInputs("The publication's handoff is not the declared default.")
            deadline = read_inputs(
                capture, season=DEFCON_SEASON, gameweek=week
            ).deadline.deadline_utc
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) >= as_instant(deadline):
                raise DefconMissingInputs(
                    "The retained handoff has no pre-deadline existence proof."
                )
            matches.append((handoff, payload_checksum(content)))
    if len(matches) != 1:
        raise DefconMissingInputs("The final published default handoff is absent or ambiguous.")
    base, handoff_hash = matches[0]
    _, elements = identity(capture)
    if set(base.expected_points) != {element["code"] for element in elements.values()}:
        raise DefconInputError("The published default roster differs from its decision capture.")
    return (
        capture,
        base,
        {
            "capture": identifier,
            "handoff_fingerprint": fingerprint,
            "handoff_sha256": handoff_hash,
            "published_at_utc": selected[0].isoformat(),
            "publication_sha256": sorted(
                item[3] for item in records if item[1]["capture"]["snapshot_id"] == identifier
            ),
            "capture_fingerprint": capture.metadata.fingerprint,
            "input_hashes": dict(capture.metadata.checksums),
        },
    )


def first_settled(
    captures: Mapping[str, CapturedSnapshot], weeks: tuple[int, ...]
) -> CapturedSnapshot:
    for snapshot in sorted(
        captures.values(),
        key=lambda s: (as_instant(s.metadata.captured_at_utc), s.metadata.snapshot_id),
    ):
        bootstrap, _ = identity(snapshot)
        fixtures = fixture_map(snapshot)
        if not all(
            settled(bootstrap, fixtures, week) and live_payload(week) in snapshot.metadata.checksums
            for week in weeks
        ):
            continue
        selected = [f for f in fixtures.values() if f.get("event") in weeks]
        if not selected:
            # The reading must follow an actual match in its declared window.
            continue
        if any(
            not isinstance(f.get("kickoff_time"), str)
            or as_instant(f["kickoff_time"]) >= as_instant(snapshot.metadata.captured_at_utc)
            for f in selected
        ):
            continue
        return snapshot
    raise DefconMissingInputs(
        "The declared first settled capture is not yet retained; reading refused."
    )


def check_inputs(
    captures: Mapping[str, CapturedSnapshot],
    *,
    publications: Path,
    handoffs: Path,
    weeks: tuple[int, ...],
    as_of: str,
) -> dict[str, Any]:
    rows = []
    for week in weeks:
        row: dict[str, Any] = {"gameweek": week, "status": "missing"}
        try:
            capture, base, proof = published_pair(
                publications, handoffs, captures, week, as_of=as_of
            )
            bootstrap, elements = identity(capture)
            fixtures = fixture_map(capture)
            counts = fixture_counts(fixtures, elements, week)
            absent_appearance = [
                element["code"]
                for element in elements.values()
                if element["element_type"] != 1
                and counts[element["code"]]
                and element["code"] not in (base.appearance_probability or {})
            ]
            if absent_appearance:
                row.update(
                    reason="published_appearance_inputs_missing",
                    identity=proof,
                    absent_player_codes=sorted(absent_appearance),
                )
                rows.append(row)
                continue
            # Only the inventory is consulted. No prior or scored event-live bytes are read.
            absent = [
                w
                for w in range(1, week)
                if live_payload(w) not in capture.metadata.checksums
                or not settled(bootstrap, fixtures, w)
            ]
            if absent:
                row.update(
                    reason="prior_history_inventory_missing_or_unsettled",
                    absent_weeks=absent,
                    identity=proof,
                )
            else:
                read_season_rules(capture, season=DEFCON_SEASON)
                row.update(
                    status="identity_and_inventory_ready",
                    identity=proof,
                    prior_history_weeks=list(range(1, week)),
                    appearance_field_present=base.appearance_probability is not None,
                )
        except (DefconMissingInputs, DataError, OSError, KeyError, TypeError) as error:
            row["reason"] = type(error).__name__
            if isinstance(error, DefconMissingInputs):
                row["detail"] = str(error)
        rows.append(row)
    return {
        "contract_version": "defcon_component_inputs_v1",
        "season": DEFCON_SEASON,
        "as_of": as_of,
        "weeks": rows,
        "outcomes_read": False,
        "promotion": False,
    }


def paired_week(
    decision: CapturedSnapshot, base: Any, outcome: CapturedSnapshot
) -> tuple[tuple[PairedDefconRow, ...], list[int], str]:
    candidate = candidate_handoff(decision, base, declaration_sha256=DECLARATION_SHA256)
    inputs = read_inputs(decision, season=DEFCON_SEASON, gameweek=base.gameweek)
    control_table = project(inputs, in_season=base).table.set_index("player_id")
    candidate_table = project(inputs, in_season=candidate).table.set_index("player_id")
    out_bootstrap, out_elements = identity(outcome)
    out_fixtures = fixture_map(outcome)
    _, elements = identity(decision)
    awards = {
        ("GK" if p == "GKP" else p): v
        for p, v in read_season_rules(
            decision, season=DEFCON_SEASON
        ).scoring.defensive_contribution.items()
    }
    observed = history_week(
        outcome,
        week=base.gameweek,
        bootstrap=out_bootstrap,
        elements=out_elements,
        fixtures=out_fixtures,
        award_points=awards,
    )
    awarded: dict[int, int] = {}
    for row in observed.rows:
        awarded[row.player_code] = awarded.get(row.player_code, 0) + row.awarded_points
    totals = {}
    seen = set()
    for element in decode(outcome.payloads[live_payload(base.gameweek)])["elements"]:
        identifier = integer(element["id"], minimum=1)
        if identifier in seen:
            raise DefconInputError("A realized element is duplicated.")
        seen.add(identifier)
        if identifier in out_elements:
            value = element["stats"]["total_points"]
            if type(value) is not int:
                raise DefconMissingInputs("Realized total points are absent or invalid.")
            totals[out_elements[identifier]["code"]] = value
    component = candidate.diagnostics["defcon_component"]
    if not isinstance(component, dict):
        raise DefconInputError("The component diagnostics are invalid.")
    # Clubs are the pre-deadline clubs, even if a player transferred before the reading.
    settled_counts = fixture_counts(out_fixtures, elements, base.gameweek)
    rows = []
    dropped = []
    for element in elements.values():
        code = element["code"]
        position = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[element["element_type"]]
        if position == "GK":
            continue
        if code not in totals:
            dropped.append(code)
            continue
        if settled_counts[code] != component["fixture_counts"][str(code)]:
            raise DefconMissingInputs("Decided and settled target fixture counts disagree.")
        comparator = float(control_table.loc[code, "expected_points"])
        decided_candidate = float(candidate_table.loc[code, "expected_points"])
        rows.append(
            PairedDefconRow(
                base.gameweek,
                code,
                position,
                comparator,
                decided_candidate,
                totals[code],
                component["terms"][str(code)],
                decided_candidate - comparator,
                awarded.get(code, 0),
                component["prior_minutes"][str(code)],
            )
        )
    if not rows:
        raise DefconMissingInputs("The paired population is empty.")
    return tuple(rows), sorted(dropped), candidate.fingerprint


def reading(
    captures: Mapping[str, CapturedSnapshot],
    *,
    snapshot_root: Path,
    publications: Path,
    handoffs: Path,
    declaration: Mapping[str, str],
    as_of: str,
    claim_directory: Path,
    owner_approved: bool,
    weekly_run_idle: bool,
) -> dict[str, Any]:
    if not owner_approved or not weekly_run_idle:
        raise DefconInputError(
            "The owner must authorize this single reading outside weekly operations."
        )
    weeks = window(declaration)
    selected = first_settled(captures, weeks)
    if as_instant(as_of) < as_instant(selected.metadata.captured_at_utc):
        raise DefconMissingInputs("The reading instant precedes the declared settled capture.")
    if (ROOT / (RECORD + ".json")).exists() or command(
        "git", "log", "--all", "--format=%H", "--", RECORD + ".json"
    ):
        raise DefconInputError(
            "A saved or committed completed record prevents another gate reading."
        )
    claim = safe_path(claim_directory) / (DECLARATION_SHA256 + ".json")
    claim.parent.mkdir(parents=True, exist_ok=True)
    if claim.exists():
        raise DefconInputError("This declaration already claimed its single gate reading.")
    # The claim survives crashes and failed inputs. It is never removed by the command.
    claimed = write_document_once(
        {
            "declaration_sha256": DECLARATION_SHA256,
            "reading_capture": selected.metadata.snapshot_id,
            "as_of": as_of,
        },
        claim,
    )
    if claimed != WRITTEN:
        raise DefconInputError("Another process already claimed this single reading.")
    try:
        outcome = partial_snapshot(
            safe_path(snapshot_root) / selected.metadata.snapshot_id,
            (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, *(live_payload(w) for w in weeks)),
        )
        all_rows: list[PairedDefconRow] = []
        audit = []
        for week in weeks:
            proof: dict[str, Any] = {}
            try:
                partial, base, proof = published_pair(
                    publications, handoffs, captures, week, as_of=as_of
                )
                decision = partial_snapshot(
                    safe_path(snapshot_root) / partial.metadata.snapshot_id,
                    (
                        BOOTSTRAP_PAYLOAD,
                        FIXTURES_PAYLOAD,
                        *(live_payload(w) for w in range(1, week)),
                    ),
                )
                paired, dropped, fingerprint = paired_week(decision, base, outcome)
                all_rows.extend(paired)
                audit.append(
                    {
                        "gameweek": week,
                        "status": "scored",
                        "identity": proof,
                        "dropped_players": dropped,
                        "dropped_player_count": len(dropped),
                        "candidate_fingerprint": fingerprint,
                    }
                )
            except (
                DefconMissingInputs,
                DefconComponentError,
                DataError,
                OSError,
                KeyError,
                TypeError,
            ) as error:
                audit.append(
                    {
                        "gameweek": week,
                        "status": "missing",
                        "reason": type(error).__name__,
                        "detail": str(error)
                        if isinstance(error, (DefconMissingInputs, DefconComponentError))
                        else None,
                        "identity": proof,
                    }
                )
        report = {
            "contract_version": "defcon_component_reading_v1",
            "season": DEFCON_SEASON,
            "declaration": dict(declaration),
            "as_of": as_of,
            "reading_capture": selected.metadata.snapshot_id,
            "reading_capture_fingerprint": selected.metadata.fingerprint,
            "reading_input_hashes": dict(selected.metadata.checksums),
            "scored_window": list(weeks),
            "week_identities": audit,
            **summarize(tuple(all_rows), scored_weeks=weeks),
        }
    except (DefconInputError, DataError, OSError, ValueError, KeyError, TypeError):
        write_document_once(
            {
                "status": "input_validation_refused",
                "reading_capture": selected.metadata.snapshot_id,
                "declaration": dict(declaration),
            },
            claim.with_name(claim.stem + "-refused.json"),
        )
        raise
    write_document_once(report, ROOT / (RECORD + ".json"))
    markdown = "# DEFCON component reading\n\nVerdict: `" + report["verdict"] + "`.\n\n"
    markdown += (
        "The JSON twin records every identity, input hash, fixed constant, "
        "paired week and diagnostic.\n\n"
    )
    markdown += (
        "```json\n" + json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n```\n"
    )
    path = ROOT / (RECORD + ".md")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(markdown)
    index = ROOT / "docs/measurements_index.md"
    row = (
        "| [DEFCON component](research/defcon_component_reading.md) / "
        "[record](research/defcon_component_reading.json) | "
        + report["verdict"]
        + "; "
        + str(report["valid_weeks"])
        + " paired weeks; fixed whole-week gate, no promotion. | This change |"
    )
    contents = index.read_text(encoding="utf-8")
    header = "| --- | --- | --- |"
    if contents.count(header) != 1:
        raise DefconInputError("The measurements index table needs review before recording.")
    index.write_text(contents.replace(header, header + "\n" + row, 1), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "handoff-root", "publication-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument("--check-through", type=int, choices=(7, 10))
    parser.add_argument("--claim-directory", type=Path)
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--weekly-run-idle", action="store_true")
    args = parser.parse_args()
    try:
        declaration = frozen_declaration()
        as_of = normalize_utc_timestamp(args.as_of, label="reading instant")
        captures = inventory(args.snapshot_root, as_of=as_of)
        if args.check_inputs:
            if args.check_through is None:
                raise DefconInputError("The input check requires its GW7 or GW10 checkpoint.")
            weeks = tuple(w for w in window(declaration) if w <= args.check_through)
            report = check_inputs(
                captures,
                publications=args.publication_root,
                handoffs=args.handoff_root,
                weeks=weeks,
                as_of=as_of,
            )
            report["declaration"] = declaration
        else:
            if args.claim_directory is None or args.check_through is not None:
                raise DefconInputError("The reading requires a persistent private claim directory.")
            report = reading(
                captures,
                snapshot_root=args.snapshot_root,
                publications=args.publication_root,
                handoffs=args.handoff_root,
                declaration=declaration,
                as_of=as_of,
                claim_directory=args.claim_directory,
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
                    "reason": "fixed_input_identity_or_reading_gate_failed",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
