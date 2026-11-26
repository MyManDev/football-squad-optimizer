"""Audit development crowd-field coverage without evaluating a forecast or squad."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
MINIMUM_VERIFIED_FOLDS = 60
CROWD_FIELDS = ("selected", "transfers_in", "transfers_out", "transfers_balance")
CAPTAIN_FIELDS = ("captained", "captaincy_share", "captain_share", "captaincy_count")
TIMING_TOKENS = ("captur", "scrap", "retriev", "deadline")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def audit_season(archive_root: Path, season: str) -> dict[str, Any]:
    """Read exactly one allowlisted season; never infer capture time from match time."""
    if season not in DEVELOPMENT_SEASONS:
        raise ValueError("The audit only accepts its four named development seasons.")
    season_root = archive_root / "data" / season
    relative = f"data/{season}/gws/merged_gw.csv"
    path = season_root / "gws" / "merged_gw.csv"
    gameweeks: Counter[int] = Counter()
    field_rows: Counter[str] = Counter()
    modified_types: Counter[str] = Counter()
    player_gameweeks: set[tuple[int, str]] = set()
    rows = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        if not {"GW", "element"}.issubset(columns):
            raise ValueError(f"Missing gameweek or player key in {relative}.")
        for row in reader:
            gameweek = int(row["GW"])
            if not 1 <= gameweek <= 38:
                raise ValueError(f"Invalid development gameweek in {relative}.")
            rows += 1
            gameweeks[gameweek] += 1
            player_gameweeks.add((gameweek, row["element"]))
            for field in CROWD_FIELDS:
                if row.get(field, "").strip():
                    field_rows[field] += 1
            if "modified" in columns:
                value = row["modified"].strip().lower()
                kind = (
                    "empty" if not value else "boolean" if value in {"true", "false"} else "other"
                )
                modified_types[kind] += 1

    headers: dict[str, list[str]] = {}
    for name in ("players_raw.csv", "fixtures.csv"):
        with (season_root / name).open(encoding="utf-8-sig", newline="") as handle:
            headers[name] = next(csv.reader(handle))
    merged_timing = [name for name in columns if any(token in name for token in TIMING_TOKENS)]
    other_timing = {
        name: [field for field in fields if any(token in field for token in TIMING_TOKENS)]
        for name, fields in headers.items()
    }
    # This audit has no adapter that authenticates an unknown timing field. Refuse
    # a changed schema instead of treating an arbitrary date as source provenance.
    if merged_timing or any(other_timing.values()):
        raise ValueError(f"Timing columns require a new provenance review for {season}.")
    sidecars = [
        item.relative_to(season_root).as_posix()
        for item in season_root.rglob("*")
        if item.is_file() and item.suffix.lower() in {".json", ".jsonl", ".yaml", ".yml"}
    ]
    if sidecars:
        raise ValueError(f"Season-local metadata needs an explicit provenance review for {season}.")
    return {
        "season": season,
        "crowd_input": relative,
        "crowd_input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "header_only_inputs": [f"data/{season}/{name}" for name in headers],
        "rows": rows,
        "distinct_player_gameweeks": len(player_gameweeks),
        "gameweeks": sorted(gameweeks),
        "candidate_decision_folds": sum(gameweek >= 2 for gameweek in gameweeks),
        "nonempty_crowd_field_rows": {field: field_rows[field] for field in CROWD_FIELDS},
        "captaincy_columns": [field for field in columns if field in CAPTAIN_FIELDS],
        "capture_or_deadline_columns": merged_timing,
        "header_only_capture_or_deadline_columns": other_timing,
        "season_local_metadata_sidecars": sidecars,
        "modified_value_types": dict(modified_types),
        "verified_predeadline_folds": 0,
        "timing_status": "unverified_capture_time_and_deadline",
    }


def build_audit(archive_root: Path, repository_commit: str) -> dict[str, Any]:
    seasons = [audit_season(archive_root, season) for season in DEVELOPMENT_SEASONS]
    return {
        "contract_version": "crowd_signal_data_audit_v1",
        "repository_commit": repository_commit,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "minimum_verified_folds": MINIMUM_VERIFIED_FOLDS,
        "candidate_decision_folds": sum(item["candidate_decision_folds"] for item in seasons),
        "verified_predeadline_folds": sum(item["verified_predeadline_folds"] for item in seasons),
        "crowd_input_rows": sum(item["rows"] for item in seasons),
        "stop_condition": "data_audit_failed",
        "preregistration_created": False,
        "forecast_or_decision_outcomes_computed": False,
        "locked_holdout_rows_accessed": False,
        "bookmaker_inputs_accessed": False,
        "snapshot_payloads_accessed": False,
        "seasons": seasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    document = build_audit(arguments.archive_root, revision)
    arguments.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(
        f"data_audit_failed: {document['verified_predeadline_folds']}/"
        f"{document['candidate_decision_folds']} verified folds; "
        f"minimum {MINIMUM_VERIFIED_FOLDS}; no outcome computed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
