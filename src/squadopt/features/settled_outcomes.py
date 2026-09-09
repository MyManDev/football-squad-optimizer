"""The prospective record of what actually happened, week by week, from our own captures.

`docs/phase_c_operational_component.md` records why this exists, for a different signal and
in the past tense: the elite uplift decides live squads while *"the only evidence that could
ever price it -- a prospective, week-by-week record built from live captures -- has not been
accumulated... Nothing currently accumulates it... 'unmeasured' here means unmeasured
indefinitely, not unmeasured yet."* This module is the thing that accumulates, so that
sentence does not have to be written a second time about rotation.

One row per player per settled gameweek, and each row carries two halves that were true at
two different times: what the settled capture says he did, and what the *pre-deadline*
capture said about whether he could play. Neither half is a claim. Putting them in one row
is what later lets someone ask whether the second predicted the first -- and asking that is
a separate deliverable with its own pre-registration, not this one.

Nothing here scores, gates, promotes or publishes anything. It is a table.

**Two absences, and they are different.** A settled capture that carries no ``stats`` for a
player is a broken payload and the export refuses -- a row of nulls would read as "played
nothing". A player the *pre-deadline* capture never listed is a legitimate absence: he was
not in the squad that week, so his availability is unknown rather than zero, and the three
availability columns stay ``pd.NA``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError, DataValidationError, InvalidValueError

#: The table's own contract. Bumped when a column is added, removed or redefined, because a
#: row written under one version cannot be read under another.
CONTRACT_VERSION: Final = "settled_outcome_v1"

#: The export's contract, separate from the table's: how the pair is written and checked can
#: change without the columns moving.
ARTIFACT_CONTRACT_VERSION: Final = "settled_outcome_export_v1"

#: Column order is part of the contract, so a reader can reject a rearranged file rather
#: than silently read one column as another.
SETTLED_OUTCOME_COLUMNS: Final = (
    "contract_version",
    "season",
    "gameweek",
    "player_id",
    "appearance",
    "start",
    "minutes",
    "total_points",
    "pre_deadline_status",
    "pre_deadline_chance_of_playing",
    "pre_deadline_availability_multiplier",
)

_SETTLED_OUTCOME_DTYPES: Final[tuple[tuple[str, str], ...]] = (
    ("contract_version", "string"),
    ("season", "string"),
    ("gameweek", "int64"),
    ("player_id", "int64"),
    ("appearance", "boolean"),
    ("start", "boolean"),
    ("minutes", "int64"),
    ("total_points", "int64"),
    ("pre_deadline_status", "string"),
    ("pre_deadline_chance_of_playing", "Int64"),
    ("pre_deadline_availability_multiplier", "Float64"),
)

_REQUIRED_MANIFEST_FIELDS: Final = frozenset(
    {
        "contract_version",
        "artifact_contract_version",
        "season",
        "gameweek",
        "deadline_timestamp_utc",
        "settled_captured_at_utc",
        "pre_deadline_captured_at_utc",
        "generated_at_utc",
        "repository_commit",
        "table_file",
        "table_sha256",
        "row_count",
        "settled_snapshot_id",
        "pre_deadline_snapshot_id",
        "source_snapshot_ids",
        "appearances",
        "starts",
        "players_without_pre_deadline_availability",
    }
)


def build_settled_outcomes(
    outcomes: pd.DataFrame,
    availability: pd.DataFrame,
    availability_multiplier: Mapping[int, float],
    *,
    season: str,
    gameweek: int,
) -> pd.DataFrame:
    """Join a settled gameweek's outcome to what the pre-deadline capture said.

    ``outcomes`` is :func:`squadopt.data.sources.fpl_live.live_event_outcomes`'s frame and
    ``availability`` is :func:`~squadopt.data.sources.fpl_live.availability_snapshot`'s, both
    keyed on the persistent player code.

    The multiplier arrives as a mapping rather than being computed here, and that is
    deliberate twice over. The rule that computes it lives above this layer, so this module
    may not import it; and a mapping keyed on the player code cannot be misaligned the way a
    positional series can. The caller reads the real rule and hands the answer in, which
    keeps one implementation of the multiplier in the repository.

    The outcome side is the left join: every player the settled capture scores gets a row,
    and a player the pre-deadline capture never listed keeps ``pd.NA`` availability rather
    than a fabricated 1.0.
    """

    if not isinstance(outcomes, pd.DataFrame) or not isinstance(availability, pd.DataFrame):
        raise InvalidValueError("Outcomes and availability must both be pandas DataFrames.")
    week = int(gameweek)
    if week < 1:
        raise InvalidValueError(f"gameweek must be positive, got {gameweek!r}.")
    if not season.strip():
        raise InvalidValueError("season must be named.")

    for label, frame, columns in (
        ("Outcomes", outcomes, ("player_id", "appearance", "start", "minutes", "total_points")),
        ("Availability", availability, ("player_id", "status", "chance_of_playing")),
    ):
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise DataValidationError(f"{label} table is missing columns {missing!r}.")
    if not outcomes["player_id"].is_unique:
        raise DataValidationError("The settled outcome table repeats a player code.")
    if not availability["player_id"].is_unique:
        raise DataValidationError("The availability table repeats a player code.")
    if outcomes.empty:
        raise DataValidationError(
            f"Gameweek {week} scores no players, so there is no outcome to record."
        )

    table = outcomes.loc[:, list(("player_id", "appearance", "start", "minutes", "total_points"))]
    table = table.merge(
        availability.loc[:, ["player_id", "status", "chance_of_playing"]].rename(
            columns={
                "status": "pre_deadline_status",
                "chance_of_playing": "pre_deadline_chance_of_playing",
            }
        ),
        on="player_id",
        how="left",
    )
    # Only for players the pre-deadline capture actually listed. A player it never named has
    # no multiplier, and filling one in would turn "not in the squad that week" into "the
    # rule said he was fully available".
    known = table["pre_deadline_status"].notna()
    table["pre_deadline_availability_multiplier"] = pd.Series(
        [
            availability_multiplier.get(int(player)) if flag else None
            for player, flag in zip(table["player_id"], known, strict=True)
        ],
        index=table.index,
        dtype="Float64",
    )
    unpriced = table.loc[known & table["pre_deadline_availability_multiplier"].isna(), "player_id"]
    if len(unpriced):
        raise DataValidationError(
            f"The pre-deadline capture lists {len(unpriced)} player(s) the availability rule "
            f"priced no multiplier for, first {int(unpriced.iloc[0])}. A listed player without "
            "a multiplier is a gap in the rule's own output, not an absent record."
        )

    table.insert(0, "contract_version", CONTRACT_VERSION)
    table.insert(1, "season", season)
    table.insert(2, "gameweek", week)
    table = table.loc[:, list(SETTLED_OUTCOME_COLUMNS)]
    # Cast column by column rather than in a loop over the dtype table: each call then names
    # one literal dtype, which is what a strict type check can actually resolve. The dtype
    # table stays the single declaration -- the reader restores the file under it.
    table["contract_version"] = table["contract_version"].astype("string")
    table["season"] = table["season"].astype("string")
    table["gameweek"] = table["gameweek"].astype("int64")
    table["player_id"] = table["player_id"].astype("int64")
    table["appearance"] = table["appearance"].astype("boolean")
    table["start"] = table["start"].astype("boolean")
    table["minutes"] = table["minutes"].astype("int64")
    table["total_points"] = table["total_points"].astype("int64")
    table["pre_deadline_status"] = table["pre_deadline_status"].astype("string")
    table["pre_deadline_chance_of_playing"] = table["pre_deadline_chance_of_playing"].astype(
        "Int64"
    )
    return table.sort_values("player_id", kind="stable").reset_index(drop=True)


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DataSourceError(f"Cannot read settled-outcome manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise DataValidationError("A settled-outcome manifest must be a JSON object.")
    missing = sorted(_REQUIRED_MANIFEST_FIELDS - document.keys())
    if missing:
        raise DataValidationError(
            f"The settled-outcome manifest is missing required fields {missing!r}."
        )
    return document


def _single_value(table: pd.DataFrame, column: str) -> object:
    values = table[column].drop_duplicates().tolist()
    if len(values) != 1:
        raise DataValidationError(
            f"Settled-outcome column {column!r} must carry exactly one value; found {values!r}."
        )
    return values[0]


def _validate_manifest_and_table(
    table: pd.DataFrame, manifest: dict[str, object], table_path: Path
) -> None:
    if manifest["contract_version"] != CONTRACT_VERSION:
        raise DataValidationError(
            f"A settled-outcome manifest's contract_version must be {CONTRACT_VERSION!r}."
        )
    if manifest["artifact_contract_version"] != ARTIFACT_CONTRACT_VERSION:
        raise DataValidationError(
            "A settled-outcome manifest's artifact_contract_version must be "
            f"{ARTIFACT_CONTRACT_VERSION!r}."
        )
    if manifest["table_file"] != table_path.name:
        raise DataValidationError(
            f"The manifest names table_file {manifest['table_file']!r}, not {table_path.name!r}."
        )
    if tuple(table.columns) != SETTLED_OUTCOME_COLUMNS:
        raise DataValidationError(
            "Settled-outcome CSV columns do not match settled_outcome_v1 in its declared order."
        )
    if table.empty:
        raise DataValidationError("A settled-outcome CSV must carry at least one player.")
    if manifest["row_count"] != len(table):
        raise DataValidationError(
            f"The manifest's row_count {manifest['row_count']!r} does not match the CSV's "
            f"{len(table)}."
        )
    if not table["player_id"].is_unique:
        raise DataValidationError("Settled-outcome player_id values must be unique.")
    if not table["player_id"].is_monotonic_increasing:
        raise DataValidationError("Settled-outcome rows must be sorted by player_id.")

    for column, field in (
        ("contract_version", "contract_version"),
        ("season", "season"),
        ("gameweek", "gameweek"),
    ):
        value = _single_value(table, column)
        if value != manifest[field]:
            raise DataValidationError(
                f"The manifest's {field} {manifest[field]!r} does not match the CSV's {value!r}."
            )

    # The outcome half is never absent: a payload that carried no stats for a player was
    # refused at export, so a null here means the file was edited after it was written.
    for column in ("appearance", "start", "minutes", "total_points"):
        if table[column].isna().any():
            raise DataValidationError(
                f"Settled-outcome column {column!r} carries an absent value. The outcome half "
                "is refused at export when the capture is thin, so this file is not the one "
                "that was exported."
            )

    counted = {
        "appearances": int(table["appearance"].sum()),
        "starts": int(table["start"].sum()),
        "players_without_pre_deadline_availability": int(table["pre_deadline_status"].isna().sum()),
    }
    for field, value in counted.items():
        if manifest[field] != value:
            raise DataValidationError(
                f"The manifest's {field} {manifest[field]!r} does not match the CSV's {value}."
            )

    # A start with no appearance cannot happen in the game's own terms, and the export does
    # not refuse it -- the payload has never been observed from here, so refusing might
    # reject a real capture. It is surfaced on read instead, where a reader can see it.
    impossible = int((table["start"].fillna(False) & ~table["appearance"].fillna(True)).sum())
    if impossible:
        raise DataValidationError(
            f"{impossible} row(s) record a start with no appearance. The two come out of one "
            "stats blob, so they disagree about the same player and the table cannot be read "
            "as either."
        )

    raw_sources = manifest["source_snapshot_ids"]
    if not isinstance(raw_sources, list) or any(
        not isinstance(value, str) or not value for value in raw_sources
    ):
        raise DataValidationError("The manifest's source_snapshot_ids must be strings.")
    for field in ("settled_snapshot_id", "pre_deadline_snapshot_id"):
        if manifest[field] not in raw_sources:
            raise DataValidationError(f"The manifest's {field} is not among source_snapshot_ids.")

    try:
        settled = pd.Timestamp(str(manifest["settled_captured_at_utc"]))
        pre_deadline = pd.Timestamp(str(manifest["pre_deadline_captured_at_utc"]))
        deadline = pd.Timestamp(str(manifest["deadline_timestamp_utc"]))
    except (TypeError, ValueError) as error:
        raise DataValidationError(f"The manifest's timestamps are invalid: {error}") from error
    if not pre_deadline < deadline:
        raise DataValidationError(
            f"The pre-deadline capture {pre_deadline} is not earlier than the deadline "
            f"{deadline}, so what it says about availability was not known before the week "
            "was decided."
        )
    if not deadline < settled:
        raise DataValidationError(
            f"The settled capture {settled} is not later than the deadline {deadline}, so it "
            "cannot describe a played gameweek."
        )


def read_settled_outcomes_artifact(
    table_path: Path | str, manifest_path: Path | str
) -> pd.DataFrame:
    """Return a contract-checked settled-outcome table with its dtypes restored.

    A checksum, schema, ordering, count, timing or manifest disagreement rejects the pair.
    The availability columns may legitimately be absent for a player the pre-deadline capture
    never listed; the outcome columns may not be absent at all.
    """

    table_path = Path(table_path)
    manifest_path = Path(manifest_path)
    manifest = _read_manifest(manifest_path)
    try:
        table_bytes = table_path.read_bytes()
    except OSError as error:
        raise DataSourceError(f"Cannot read settled-outcome CSV {table_path}: {error}") from error
    digest = hashlib.sha256(table_bytes).hexdigest()
    if manifest["table_sha256"] != digest:
        raise DataValidationError(
            f"Settled-outcome CSV checksum {digest} does not match the manifest's "
            f"table_sha256 {manifest['table_sha256']!r}."
        )
    try:
        table = pd.read_csv(table_path, dtype=dict(_SETTLED_OUTCOME_DTYPES))
    except (OSError, TypeError, ValueError, pd.errors.ParserError) as error:
        raise DataValidationError(
            f"The settled-outcome CSV cannot be read under its schema: {error}"
        ) from error

    _validate_manifest_and_table(table, manifest, table_path)
    table.attrs.update(
        {
            "artifact_contract_version": manifest["artifact_contract_version"],
            "settled_snapshot_id": manifest["settled_snapshot_id"],
            "pre_deadline_snapshot_id": manifest["pre_deadline_snapshot_id"],
            "generated_at_utc": manifest["generated_at_utc"],
            "repository_commit": manifest["repository_commit"],
            "table_sha256": digest,
        }
    )
    return table
