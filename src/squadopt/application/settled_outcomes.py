"""Accumulate what actually happened, one artifact per settled gameweek.

    python -m scripts.export_settled_outcomes --season 2026-27 --dry-run
    python -m scripts.export_settled_outcomes --season 2026-27

`docs/phase_c_operational_component.md` records the failure this exists to avoid, about a
different signal and in the past tense: live squads are decided while *"the only evidence
that could ever price it -- a prospective, week-by-week record built from live captures --
has not been accumulated... Nothing currently accumulates it."* This is the thing that
accumulates.

For every gameweek the captures say is **finished and checked**, one table + manifest pair
is written: per player, what the settled capture says he did, beside what the *pre-deadline*
capture said about whether he could play. Neither half is a claim and nothing here scores
anything -- putting the two in one row is what lets a later, separately pre-registered
measurement ask whether one predicted the other.

Two captures are needed per gameweek and both must already be on disk: the settled one, and
the last one taken before that gameweek's deadline. A gameweek missing either is **skipped
with its reason** and no row is written for it -- a table of zeros would read as "nobody
played".

`--dry-run` writes nothing and prints what is on disk, which is also how to find out which
gameweeks are available before spending anything.

The tables are evidence, not records: they go to `artifacts/`, which is gitignored, per ADR
0003's tiers. The committed record is the summary this script also writes to `docs/`, which
carries enough numbers to be checked without the tables.
"""

import json
import os
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.application.evidence_io import write_json, write_text
from squadopt.backtest.export_precision import write_export_table
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    availability_snapshot,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.features.settled_outcomes import (
    ARTIFACT_CONTRACT_VERSION,
    CONTRACT_VERSION,
    build_settled_outcomes,
    read_settled_outcomes_artifact,
)
from squadopt.live import infer_season
from squadopt.prediction.availability import apply_availability
from squadopt.preflight.validator import compute_table_sha256

DEFAULT_SNAPSHOT_ROOT: Final = Path("data/snapshots")
DEFAULT_OUTPUT_DIR: Final = Path("artifacts/rotation")
DEFAULT_RECORD: Final = Path("docs/settled_outcomes.json")
DEFAULT_SUMMARY: Final = Path("docs/settled_outcomes.md")


@dataclass(frozen=True, slots=True)
class SettledOutcomesRequest:
    season: str
    snapshot_root: Path
    output_dir: Path
    json_output: Path
    markdown_output: Path
    repository_commit: str
    as_of_snapshot_id: str
    before_gameweek: int


@dataclass(frozen=True, slots=True)
class SettledOutcomesResult:
    output_paths: tuple[Path, ...]
    gameweeks_exported: tuple[int, ...]
    skipped: tuple[str, ...]


def export_settled_outcomes(request: SettledOutcomesRequest) -> SettledOutcomesResult:
    """Export only earlier finished/checked weeks visible by the selected decision capture."""

    anchor = read_snapshot(request.snapshot_root, request.as_of_snapshot_id)
    if infer_season(anchor) != request.season:
        raise SettledOutcomeExportError("Selected capture is not from the requested season.")
    cutoff = as_instant(anchor.metadata.captured_at_utc)
    captures = tuple(
        capture
        for capture in _captures(request.snapshot_root)
        if as_instant(capture.captured_at_utc) <= cutoff
        and infer_season(read_snapshot(request.snapshot_root, capture.snapshot_id))
        == request.season
    )
    available, skipped = pair_captures(captures)
    pairs = tuple(pair for pair in available if pair.gameweek < request.before_gameweek)
    if not pairs:
        skipped = (*skipped, "No earlier finished and checked gameweek has both required captures.")
    weeks: list[dict[str, object]] = []
    outputs: list[Path] = []
    for pair in pairs:
        availability = availability_snapshot(pair.pre_deadline.bootstrap)
        outcomes = live_event_outcomes(
            pair.settled.payloads[live_payload(pair.gameweek)],
            pair.settled.bootstrap,
            gameweek=pair.gameweek,
        )
        table = build_settled_outcomes(
            outcomes,
            availability,
            _multiplier(availability),
            season=request.season,
            gameweek=pair.gameweek,
        )
        name = table_name(request.season, pair)
        manifest = write_artifact(
            table,
            request.output_dir,
            name,
            pair=pair,
            season=request.season,
            repository_commit=request.repository_commit,
        )
        table_path = request.output_dir / f"{name}.csv"
        manifest_path = request.output_dir / f"{name}.manifest.json"
        read_settled_outcomes_artifact(table_path, manifest_path)
        outputs.extend((table_path, manifest_path))
        weeks.append(_week_summary(table, manifest, pair))
    record: dict[str, object] = {
        "artifact_type": "settled_outcomes",
        "contract_version": CONTRACT_VERSION,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "season": request.season,
        "gameweeks_exported": len(weeks),
        "gameweeks_skipped": len(skipped),
        "skipped": list(skipped),
        "gameweeks": weeks,
        "gate_evidence": False,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    write_json(request.json_output, record)
    write_text(request.markdown_output, summary(record))
    outputs.extend((request.json_output, request.markdown_output))
    return SettledOutcomesResult(tuple(outputs), tuple(pair.gameweek for pair in pairs), skipped)


class SettledOutcomeExportError(RuntimeError):
    """The stored captures cannot support the artifact that was asked for."""


@dataclass(frozen=True, slots=True)
class _Capture:
    """One stored live capture and the payloads it carries."""

    snapshot_id: str
    captured_at_utc: str
    payloads: Mapping[str, bytes]

    @property
    def bootstrap(self) -> bytes:
        return self.payloads[BOOTSTRAP_PAYLOAD]


@dataclass(frozen=True, slots=True)
class _Pair:
    """The two captures one gameweek's artifact is built from."""

    gameweek: int
    deadline_utc: str
    settled: _Capture
    pre_deadline: _Capture


def _captures(snapshot_root: Path) -> tuple[_Capture, ...]:
    """Every stored live capture that carries a bootstrap, oldest first."""

    captures: list[_Capture] = []
    for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        snapshot = read_snapshot(snapshot_root, identifier)
        if BOOTSTRAP_PAYLOAD not in snapshot.payloads:
            # What an interrupted capture leaves behind. One of those must not stop the rest.
            continue
        captures.append(
            _Capture(
                snapshot_id=identifier,
                captured_at_utc=snapshot.metadata.captured_at_utc,
                payloads=snapshot.payloads,
            )
        )
    return tuple(sorted(captures, key=lambda entry: as_instant(entry.captured_at_utc)))


def _deadline(capture: _Capture, gameweek: int) -> str | None:
    for deadline in gameweek_deadlines(capture.bootstrap):
        if deadline.gameweek == gameweek:
            return deadline.deadline_utc
    return None


def pair_captures(captures: Sequence[_Capture]) -> tuple[tuple[_Pair, ...], tuple[str, ...]]:
    """Pair each settled gameweek with the last capture taken before its deadline.

    The settled capture is the **earliest** one whose bootstrap says the gameweek is
    finished and checked and which also carries that gameweek's live document: the earliest,
    because every later capture says the same thing about a closed week and the first one to
    say it is the one that establishes it.

    The pre-deadline capture is the **latest** one taken strictly before the deadline, which
    is the capture the week was actually decided from -- the availability that applied.
    """

    pairs: list[_Pair] = []
    skipped: list[str] = []
    settled_weeks: set[int] = set()
    for capture in captures:
        settled_weeks.update(scored_gameweeks(capture.bootstrap))

    for gameweek in sorted(settled_weeks):
        payload_name = live_payload(gameweek)
        settled = next(
            (
                capture
                for capture in captures
                if gameweek in scored_gameweeks(capture.bootstrap)
                and payload_name in capture.payloads
            ),
            None,
        )
        if settled is None:
            skipped.append(
                f"gw{gameweek:02d}: settled, but no capture that says so carries {payload_name}"
            )
            continue
        deadline_utc = _deadline(settled, gameweek)
        if deadline_utc is None:
            skipped.append(f"gw{gameweek:02d}: the settled capture publishes no deadline for it")
            continue
        moment = as_instant(deadline_utc)
        before = [capture for capture in captures if as_instant(capture.captured_at_utc) < moment]
        if not before:
            skipped.append(
                f"gw{gameweek:02d}: no capture was taken before its deadline "
                f"{deadline_utc}, so the availability that applied was never recorded"
            )
            continue
        pairs.append(
            _Pair(
                gameweek=gameweek,
                deadline_utc=deadline_utc,
                settled=settled,
                pre_deadline=before[-1],
            )
        )
    return tuple(pairs), tuple(skipped)


def _multiplier(availability: pd.DataFrame) -> dict[int, float]:
    """Read the availability rule's own multiplier, rather than reimplementing it.

    ``apply_availability`` scales a projection, so it is handed a projection of ones: the
    scaled column is then the multiplier itself, and there is exactly one implementation of
    the rule in the repository. Its semantics are untouched -- this only reads it.
    """

    projection = pd.DataFrame(
        {
            "player_id": availability["player_id"].astype("int64"),
            "expected_points": 1.0,
        }
    ).reset_index(drop=True)
    adjustment = apply_availability(projection, availability)
    values = adjustment.multiplier.reset_index(drop=True)
    if len(values) != len(projection):
        raise SettledOutcomeExportError(
            f"The availability rule returned {len(values)} multipliers for "
            f"{len(projection)} players; the two cannot be paired."
        )
    return {
        int(player): float(value)
        for player, value in zip(projection["player_id"], values, strict=True)
    }


def _temporary(final: Path) -> Path:
    return final.with_name(f".{final.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")


def _publish(temporary: Path, final: Path) -> None:
    """Create-once: an identical artifact is kept, a different one is never overwritten."""

    if final.exists():
        if final.read_bytes() == temporary.read_bytes():
            return
        raise SettledOutcomeExportError(
            f"{final} already exists with different content; an artifact is never "
            "overwritten in place. Remove it deliberately, or name another output."
        )
    os.replace(temporary, final)


def _canonical(manifest: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in manifest.items() if key != "generated_at_utc"}


def table_name(season: str, pair: _Pair) -> str:
    """Name the artifact after both captures it was built from.

    The settled snapshot's tail is in the name because a week re-read from a later capture
    is a different artifact, not an overwrite of this one -- the same trick the weekly runner
    uses so a rehearsal cannot collide with the real thing.
    """

    return f"settled_outcomes_v1_{season}_gw{pair.gameweek:02d}_{pair.settled.snapshot_id[-12:]}"


def write_artifact(
    table: pd.DataFrame,
    output_dir: Path,
    name: str,
    *,
    pair: _Pair,
    season: str,
    repository_commit: str,
    generated_at_utc: str | None = None,
) -> dict[str, object]:
    """Write ``<name>.csv`` and ``<name>.manifest.json``, create-once, and return the manifest.

    Mirrors the write path `scripts/export_player_evidence.py` established rather than
    sharing it: that script is Phase B's frozen `player_evidence_v1` export and this lane
    may not touch it. A shared helper is the right move once a third artifact needs one.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / f"{name}.csv"
    manifest_path = output_dir / f"{name}.manifest.json"

    temporary = _temporary(table_path)
    try:
        write_export_table(table, temporary)
        table_sha256 = compute_table_sha256(temporary)
        _publish(temporary, table_path)
    finally:
        temporary.unlink(missing_ok=True)

    manifest: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "season": season,
        "gameweek": pair.gameweek,
        "deadline_timestamp_utc": pair.deadline_utc,
        "settled_captured_at_utc": pair.settled.captured_at_utc,
        "pre_deadline_captured_at_utc": pair.pre_deadline.captured_at_utc,
        "generated_at_utc": generated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository_commit": repository_commit,
        "table_file": table_path.name,
        "table_sha256": table_sha256,
        "row_count": len(table),
        "settled_snapshot_id": pair.settled.snapshot_id,
        "pre_deadline_snapshot_id": pair.pre_deadline.snapshot_id,
        "source_snapshot_ids": [pair.pre_deadline.snapshot_id, pair.settled.snapshot_id],
        "appearances": int(table["appearance"].sum()),
        "starts": int(table["start"].sum()),
        "players_without_pre_deadline_availability": int(table["pre_deadline_status"].isna().sum()),
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or _canonical(existing) != _canonical(manifest):
            raise SettledOutcomeExportError(
                f"{manifest_path} already exists and describes a different artifact; "
                "refusing to overwrite it."
            )
        return existing
    temporary_manifest = _temporary(manifest_path)
    try:
        write_json(temporary_manifest, manifest)
        os.replace(temporary_manifest, manifest_path)
    finally:
        temporary_manifest.unlink(missing_ok=True)
    return manifest


def _week_summary(
    table: pd.DataFrame, manifest: Mapping[str, object], pair: _Pair
) -> dict[str, object]:
    """The per-gameweek numbers the committed record carries instead of the table."""

    priced = table.loc[table["pre_deadline_availability_multiplier"].notna()]
    fully_available = priced.loc[priced["pre_deadline_availability_multiplier"] == 1.0]
    lead = as_instant(pair.deadline_utc) - as_instant(pair.pre_deadline.captured_at_utc)
    return {
        "gameweek": pair.gameweek,
        "deadline_utc": pair.deadline_utc,
        "settled_snapshot_id": pair.settled.snapshot_id,
        "pre_deadline_snapshot_id": pair.pre_deadline.snapshot_id,
        "pre_deadline_lead_time_hours": round(lead.total_seconds() / 3600.0, 2),
        "table_file": manifest["table_file"],
        "table_sha256": manifest["table_sha256"],
        "row_count": manifest["row_count"],
        "appearances": manifest["appearances"],
        "starts": manifest["starts"],
        "players_without_pre_deadline_availability": manifest[
            "players_without_pre_deadline_availability"
        ],
        # The block the rule makes no distinction inside: a multiplier of exactly one, and
        # what those players then did. Counts, not a claim -- nothing here says the rule
        # should have known better.
        "fully_available_players": len(fully_available),
        "fully_available_who_did_not_start": int((~fully_available["start"]).sum()),
        "fully_available_who_did_not_appear": int((~fully_available["appearance"]).sum()),
    }


def summary(record: Mapping[str, object]) -> str:
    """Write the record as prose: what accumulated, and what it does not license."""

    weeks = [entry for entry in list(record["gameweeks"]) if isinstance(entry, dict)]  # type: ignore[call-overload]
    lines = [
        "# What actually happened, per settled gameweek",
        "",
        f"Contract: `{record['contract_version']}` / `{record['artifact_contract_version']}`",
        "",
        "One row per player per settled gameweek: what the settled capture says he did,",
        "beside what the capture the week was decided from said about whether he could play.",
        "The tables themselves are evidence and are not committed; these are the numbers a",
        "reader needs to check the record without them.",
        "",
        "| gw | rows | appeared | started | pre-deadline lead | no availability |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for entry in weeks:
        lines.append(
            f"| {entry['gameweek']} | {entry['row_count']} | {entry['appearances']} | "
            f"{entry['starts']} | {entry['pre_deadline_lead_time_hours']} h | "
            f"{entry['players_without_pre_deadline_availability']} |"
        )

    lines += [
        "",
        "A player the pre-deadline capture never listed has **no** availability rather than",
        "a zero one: he was not in the squad that week, and filling in a multiplier would",
        "turn an absence into a statement.",
        "",
        "## Inside the block the rule does not separate",
        "",
        "| gw | multiplier exactly 1.0 | did not start | did not appear |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for entry in weeks:
        lines.append(
            f"| {entry['gameweek']} | {entry['fully_available_players']} | "
            f"{entry['fully_available_who_did_not_start']} | "
            f"{entry['fully_available_who_did_not_appear']} |"
        )

    lines += [
        "",
        "Counts, and nothing more. The availability rule is applied once from the capture and",
        "makes no distinction among the players it prices at one; how many of them then did",
        "not start is a fact about those weeks, not evidence that anything should have known",
        "better. What could be predicted, by what, and whether acting on it earns points are",
        "three separate questions and none of them is asked here.",
        "",
        "## What this decides",
        "",
        "Nothing. No gate is evaluated, no model is promoted, no operational control moves",
        "and no probability is published. The locked holdout is not read: every row comes",
        "from a capture we took ourselves, this season, after the gameweek it describes.",
        "",
        f"Gameweeks accumulated: {record['gameweeks_exported']}. "
        f"Skipped: {record['gameweeks_skipped']}.",
        "",
    ]
    skipped = [str(reason) for reason in list(record["skipped"])]  # type: ignore[call-overload]
    if skipped:
        lines += ["Skipped, with reasons:", ""] + [f"- {reason}" for reason in skipped] + [""]
    return "\n".join(lines)
