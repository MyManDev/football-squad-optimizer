"""Pin the published fixture difficulty before a ball is kicked, so it can be trusted later.

The opponent projection study found that an adjustment built on the archive's
``fixture_difficulty`` improves realized squad points by about 1.74 per gameweek — and that
the archived value is not admissible evidence, because in 2024-25 it tracks the season it
describes (+0.940) far better than the season before it (+0.372). A rating written down
after the fact cannot be a pre-match feature.

That leaves an obvious question the archive cannot answer and a live season can: **is the
platform's published difficulty a pre-season value that stays put, or is it revised as the
season reveals who is actually good?** The answer decides whether the largest fixture effect
this programme has measured is real or an artifact, and it is worth more than either of the
two models built in stages one and two.

Answering it needs one thing that expires: a capture taken **before the first kickoff**,
with its provenance intact. This module turns such a capture into a permanent, checksummed
record and refuses to build one from a capture that is already too late. Everything else —
comparing a later capture, or the end-of-season archive, against the record — is arithmetic
on top.

Nothing here fits, predicts, or changes a model. It writes down what was published and when,
which is the part that cannot be recovered afterwards.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    fixture_snapshot,
    gameweek_deadlines,
)
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError

PRESEASON_DIFFICULTY_RECORD_CONTRACT_VERSION: Final = "preseason_difficulty_record_v1"

#: Team-level fields the bootstrap payload publishes. Before a season starts the platform
#: fills only the coarse one-to-five ``strength`` pair and leaves the attack and defence
#: numbers at zero, which is itself part of the record: it says what was knowable.
TEAM_STRENGTH_FIELDS: Final = (
    "strength",
    "strength_overall_home",
    "strength_overall_away",
    "strength_attack_home",
    "strength_attack_away",
    "strength_defence_home",
    "strength_defence_away",
)

#: The columns a difficulty comparison joins and compares on.
DIFFICULTY_KEY_COLUMNS: Final = ("season", "fixture_id", "team_id", "is_home")
DIFFICULTY_VALUE_COLUMN: Final = "fixture_difficulty"


@dataclass(frozen=True, slots=True)
class PreseasonDifficultyRecord:
    """What the platform published about a season's fixtures before any of them were played."""

    contract_version: str
    snapshot_id: str
    source: str
    captured_at_utc: str
    fingerprint: str
    checksums: Mapping[str, str]
    season: str
    first_deadline_utc: str
    first_kickoff_utc: str
    difficulty: pd.DataFrame
    """One row per fixture side: season, fixture, club, venue, published difficulty."""
    team_strength: pd.DataFrame
    """One row per club, carrying whichever strength fields the payload had filled in."""
    diagnostics: Mapping[str, object]

    @property
    def fixtures(self) -> int:
        return int(self.difficulty["fixture_id"].nunique())

    @property
    def clubs(self) -> int:
        return int(self.difficulty["team_id"].nunique())


@dataclass(frozen=True, slots=True)
class DifficultyDrift:
    """Whether a later reading of the same fixtures still says what the record said."""

    compared_rows: int
    missing_rows: int
    """Fixture sides in the record that the later reading does not carry at all."""
    changed_rows: int
    mean_absolute_change: float
    changed_clubs: Mapping[str, int]
    examples: tuple[Mapping[str, object], ...]

    @property
    def unchanged(self) -> bool:
        return self.compared_rows > 0 and self.changed_rows == 0

    @property
    def changed_share(self) -> float:
        return float(self.changed_rows) / float(self.compared_rows) if self.compared_rows else 0.0


def _teams_from_bootstrap(bootstrap: bytes) -> pd.DataFrame:
    """The club table with whatever strength fields the payload filled in."""

    try:
        document = json.loads(bootstrap.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExperimentExecutionError(
            f"The bootstrap payload is not valid JSON: {error}"
        ) from error
    teams = document.get("teams") if isinstance(document, dict) else None
    if not isinstance(teams, list) or not teams:
        raise ExperimentExecutionError("The bootstrap payload declares no teams.")
    rows: list[dict[str, object]] = []
    for record in teams:
        if not isinstance(record, dict) or "code" not in record:
            raise ExperimentExecutionError("A bootstrap team record carries no club code.")
        row: dict[str, object] = {
            "team_id": int(record["code"]),
            "name": str(record.get("name", "")),
        }
        for field in TEAM_STRENGTH_FIELDS:
            value = record.get(field)
            row[field] = None if value is None else float(value)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("team_id", kind="stable").reset_index(drop=True)


def build_preseason_record(
    snapshot_root: Path | str,
    snapshot_id: str,
    *,
    season: str,
) -> PreseasonDifficultyRecord:
    """Turn one verified capture into a record, or refuse if it was taken too late.

    The refusal is the point of the function. A capture taken after the first kickoff cannot
    testify about what was published beforehand, and a record built from one would look
    exactly like a valid one a year from now, when nobody remembers.
    """

    if not isinstance(season, str) or not season.strip():
        raise ExperimentConfigurationError("season must be a non-empty string.")
    captured = read_snapshot(snapshot_root, snapshot_id)
    missing = [
        name for name in (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD) if name not in captured.payloads
    ]
    if missing:
        raise ExperimentExecutionError(f"{snapshot_id} carries no {missing!r} payload.")
    bootstrap = captured.payloads[BOOTSTRAP_PAYLOAD]
    fixtures = fixture_snapshot(
        captured.payloads[FIXTURES_PAYLOAD],
        bootstrap,
        season=season.strip(),
        snapshot_id=captured.metadata.snapshot_id,
        captured_at_utc=captured.metadata.captured_at_utc,
    )
    kickoffs = pd.to_datetime(fixtures["kickoff_time_utc"], utc=True, format="mixed")
    if bool(kickoffs.isna().all()):
        raise ExperimentExecutionError(f"{snapshot_id} publishes no kickoff time at all.")
    first_kickoff = pd.Timestamp(kickoffs.min())
    captured_at = pd.Timestamp(captured.metadata.captured_at_utc)
    if captured_at >= first_kickoff:
        raise ExperimentExecutionError(
            f"{snapshot_id} was captured at {captured_at.isoformat()}, at or after the first "
            f"kickoff at {first_kickoff.isoformat()}. It cannot testify about what was "
            "published before the season, which is the only thing this record is for."
        )
    played = fixtures.loc[fixtures["status"].astype("string") == "final"]
    if not played.empty:
        raise ExperimentExecutionError(
            f"{snapshot_id} already records {len(played)} finished fixture side(s); it is not "
            "a pre-season capture."
        )
    difficulty = fixtures.loc[
        :, ["season", "gameweek", "fixture_id", "team_id", "is_home", "fixture_difficulty"]
    ].copy()
    unrated = int(difficulty["fixture_difficulty"].isna().sum())
    deadlines = gameweek_deadlines(bootstrap)
    if not deadlines:
        raise ExperimentExecutionError(f"{snapshot_id} publishes no gameweek deadline.")
    strength = _teams_from_bootstrap(bootstrap)
    # "Populated" means present and non-zero: the platform leaves an unpublished field at
    # zero as often as it leaves it null, and both mean the same thing before a season.
    filled = {
        field: int(((strength[field].notna()) & (strength[field] != 0.0)).sum())
        for field in TEAM_STRENGTH_FIELDS
    }
    return PreseasonDifficultyRecord(
        contract_version=PRESEASON_DIFFICULTY_RECORD_CONTRACT_VERSION,
        snapshot_id=captured.metadata.snapshot_id,
        source=captured.metadata.source,
        captured_at_utc=captured.metadata.captured_at_utc,
        fingerprint=captured.metadata.fingerprint,
        checksums=dict(captured.metadata.checksums),
        season=season.strip(),
        first_deadline_utc=deadlines[0].deadline_utc,
        first_kickoff_utc=str(first_kickoff.isoformat()),
        difficulty=difficulty.sort_values(
            ["fixture_id", "is_home"], kind="stable", ascending=[True, False]
        ).reset_index(drop=True),
        team_strength=strength,
        diagnostics={
            "fixture_sides": len(difficulty),
            "fixtures": int(difficulty["fixture_id"].nunique()),
            "clubs": int(difficulty["team_id"].nunique()),
            "gameweeks": int(difficulty["gameweek"].nunique()),
            "sides_without_a_rating": unrated,
            "hours_before_first_kickoff": float(
                (first_kickoff - captured_at).total_seconds() / 3600.0
            ),
            "team_strength_fields_populated": filled,
            "difficulty_distribution": {
                str(rating): int(count)
                for rating, count in sorted(
                    difficulty["fixture_difficulty"]
                    .dropna()
                    .astype("int64")
                    .value_counts()
                    .to_dict()
                    .items()
                )
            },
        },
    )


def compare_to_later(record: PreseasonDifficultyRecord, later: pd.DataFrame) -> DifficultyDrift:
    """Ask whether a later reading of the same fixtures still says what was published.

    ``later`` is any fixture table carrying the snapshot columns — a capture taken this week,
    or the archive's own table once the season is over. The join is on the fixture and the
    side of it, so a re-scheduled fixture keeps its identity and a club that changed gameweek
    is still compared against itself.
    """

    required = (*DIFFICULTY_KEY_COLUMNS, DIFFICULTY_VALUE_COLUMN)
    absent = [column for column in required if column not in later.columns]
    if absent:
        raise ExperimentExecutionError(f"The later table lacks columns {absent!r}.")
    left = record.difficulty.loc[:, [*required]].copy()
    right = later.loc[:, [*required]].copy()
    for frame in (left, right):
        frame["season"] = frame["season"].astype("string")
        frame["fixture_id"] = frame["fixture_id"].astype("int64")
        frame["team_id"] = frame["team_id"].astype("int64")
        frame["is_home"] = frame["is_home"].astype("boolean").astype("bool")
        frame[DIFFICULTY_VALUE_COLUMN] = pd.to_numeric(
            frame[DIFFICULTY_VALUE_COLUMN], errors="coerce"
        ).astype("float64")
    merged = left.merge(
        right,
        on=list(DIFFICULTY_KEY_COLUMNS),
        how="left",
        suffixes=("_recorded", "_later"),
    )
    recorded = merged[f"{DIFFICULTY_VALUE_COLUMN}_recorded"]
    observed = merged[f"{DIFFICULTY_VALUE_COLUMN}_later"]
    present = observed.notna() & recorded.notna()
    difference = (observed - recorded).where(present)
    changed = present & (difference != 0.0)
    by_club = (
        merged.loc[changed].groupby("team_id").size().sort_values(ascending=False).head(10)
    ).to_dict()
    examples = tuple(
        {
            "fixture_id": int(row["fixture_id"]),
            "team_id": int(row["team_id"]),
            "is_home": bool(row["is_home"]),
            "recorded": float(row[f"{DIFFICULTY_VALUE_COLUMN}_recorded"]),
            "later": float(row[f"{DIFFICULTY_VALUE_COLUMN}_later"]),
        }
        for row in merged.loc[changed].head(10).to_dict("records")
    )
    return DifficultyDrift(
        compared_rows=int(present.sum()),
        missing_rows=int((~observed.notna()).sum()),
        changed_rows=int(changed.sum()),
        mean_absolute_change=(
            float(difference.loc[changed].abs().mean()) if bool(changed.any()) else 0.0
        ),
        changed_clubs={str(club): int(count) for club, count in by_club.items()},
        examples=examples,
    )


def record_to_dict(record: PreseasonDifficultyRecord) -> dict[str, object]:
    """The record as JSON-native values, difficulty table included in full."""

    return {
        "contract_version": record.contract_version,
        "snapshot_id": record.snapshot_id,
        "source": record.source,
        "captured_at_utc": record.captured_at_utc,
        "fingerprint": record.fingerprint,
        "checksums": dict(record.checksums),
        "season": record.season,
        "first_deadline_utc": record.first_deadline_utc,
        "first_kickoff_utc": record.first_kickoff_utc,
        "difficulty": [
            {
                "season": str(row["season"]),
                "gameweek": int(row["gameweek"]),
                "fixture_id": int(row["fixture_id"]),
                "team_id": int(row["team_id"]),
                "is_home": bool(row["is_home"]),
                "fixture_difficulty": (
                    None if pd.isna(row["fixture_difficulty"]) else int(row["fixture_difficulty"])
                ),
            }
            for row in record.difficulty.to_dict("records")
        ],
        "team_strength": [
            {
                "team_id": int(row["team_id"]),
                "name": str(row["name"]),
                **{
                    field: (None if pd.isna(row[field]) else float(row[field]))
                    for field in TEAM_STRENGTH_FIELDS
                },
            }
            for row in record.team_strength.to_dict("records")
        ],
        "diagnostics": dict(record.diagnostics),
    }


def drift_to_dict(drift: DifficultyDrift) -> dict[str, object]:
    return {
        "compared_rows": drift.compared_rows,
        "missing_rows": drift.missing_rows,
        "changed_rows": drift.changed_rows,
        "changed_share": drift.changed_share,
        "mean_absolute_change": drift.mean_absolute_change,
        "changed_clubs": dict(drift.changed_clubs),
        "examples": [dict(example) for example in drift.examples],
        "unchanged": drift.unchanged,
    }


def _number(diagnostics: Mapping[str, object], key: str) -> float:
    """Read one diagnostic as a float, so a formatted report cannot fail on a type."""

    value = diagnostics.get(key, 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def record_to_markdown(
    record: PreseasonDifficultyRecord, drift: DifficultyDrift | None = None
) -> str:
    """The artifact a reader can check without running anything."""

    diagnostics = record.diagnostics
    filled = diagnostics.get("team_strength_fields_populated", {})
    assert isinstance(filled, Mapping)
    lines = [
        f"# What the platform published about {record.season} before it started",
        "",
        f"- Contract `{record.contract_version}`; capture `{record.snapshot_id}` from "
        f"`{record.source}`, taken **{record.captured_at_utc}**.",
        f"- First kickoff **{record.first_kickoff_utc}**, first deadline "
        f"**{record.first_deadline_utc}** — the capture precedes the first kickoff by "
        f"**{_number(diagnostics, 'hours_before_first_kickoff'):.1f} hours**, and the "
        "record refuses to be built from a capture that does not.",
        f"- {diagnostics.get('fixtures')} fixtures across "
        f"{diagnostics.get('gameweeks')} gameweeks, {diagnostics.get('clubs')} clubs, "
        f"{diagnostics.get('fixture_sides')} fixture sides, "
        f"{diagnostics.get('sides_without_a_rating')} without a published rating.",
        f"- Snapshot fingerprint `{record.fingerprint[:16]}…`; payload checksums are recorded "
        "in the JSON beside this file, so an edited capture cannot be passed off as this one.",
        "",
        "## Published difficulty, as it stood",
        "",
        "| Rating | Fixture sides |",
        "| --- | ---: |",
    ]
    distribution = diagnostics.get("difficulty_distribution", {})
    assert isinstance(distribution, Mapping)
    for value, count in distribution.items():
        lines.append(f"| {value} | {count} |")
    lines += [
        "",
        "## What the platform did *not* publish yet",
        "",
        "Team strength is a separate field from fixture difficulty, and before a season it is "
        "largely empty. Fields carrying a non-zero value for at least one club:",
        "",
        "| Field | Clubs with a non-zero value |",
        "| --- | ---: |",
    ]
    for field, count in filled.items():
        lines.append(f"| `{field}` | {count} of {record.clubs} |")
    lines += [
        "",
        "That asymmetry is evidence in its own right. A completed season's archive carries "
        "populated attack and defence numbers on a thousand-point scale; before a season the "
        "same fields are zero and only a coarse one-to-five overall rating exists. Whatever "
        "the archive's strength columns are, they are not what was published in August.",
        "",
    ]
    if drift is not None:
        lines += [
            "## Drift against a later reading",
            "",
            f"- {drift.compared_rows} fixture sides compared, {drift.missing_rows} not found "
            f"in the later table.",
            f"- **{drift.changed_rows} changed** ({drift.changed_share:.1%}), mean absolute "
            f"change {drift.mean_absolute_change:.2f}.",
            "",
            (
                "The published difficulty has not moved since it was recorded."
                if drift.unchanged
                else "The published difficulty **has moved** since it was recorded, so a "
                "single stored value cannot be treated as the pre-season one."
            ),
            "",
        ]
    return "\n".join(lines) + "\n"


__all__ = [
    "DIFFICULTY_KEY_COLUMNS",
    "DIFFICULTY_VALUE_COLUMN",
    "PRESEASON_DIFFICULTY_RECORD_CONTRACT_VERSION",
    "TEAM_STRENGTH_FIELDS",
    "DifficultyDrift",
    "PreseasonDifficultyRecord",
    "build_preseason_record",
    "compare_to_later",
    "drift_to_dict",
    "record_to_dict",
    "record_to_markdown",
]
