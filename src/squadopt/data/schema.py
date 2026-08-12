"""Canonical player-gameweek schema, controlled vocabularies, and key constants.

This module is the single source of truth for the data layer. No other data,
feature, or prediction module may hard-code canonical column names, position
labels, price factors, or grouping/sorting keys; they import them from here.

Position labels and the optimizer projection contract are imported from the
optimization package rather than redefined, so the two layers cannot drift
apart. The shared vocabulary arguably belongs in a neutral module owned by the
software architecture layer; moving it there later is a mechanical change
because every data-layer reference points at this module.
"""

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import Literal, TypeAlias

from squadopt.data.errors import InvalidValueError
from squadopt.optimization.config import POSITIONS, Position
from squadopt.optimization.validation import REQUIRED_COLUMNS as PROJECTION_REQUIRED_COLUMNS

__all__ = [
    "AMBIGUOUS_TIMING_COLUMNS",
    "CANONICAL_COLUMNS",
    "CANONICAL_SORT_COLUMNS",
    "COLUMN_KINDS",
    "EXTERNALLY_SUPPLIED_COLUMNS",
    "KEY_COLUMNS",
    "MIN_GAMEWEEK",
    "NON_NEGATIVE_COLUMNS",
    "OPTIONAL_COLUMNS",
    "OUTCOME_COLUMNS",
    "PLAYER_GROUP_COLUMNS",
    "PLAYER_TIME_SORT_COLUMNS",
    "POSITIONS",
    "POSITION_ALIASES",
    "PRE_MATCH_COLUMNS",
    "PRICE_TENTHS_PER_UNIT",
    "PROJECTION_REQUIRED_COLUMNS",
    "REQUIRED_COLUMNS",
    "ColumnKind",
    "Position",
    "canonical_column_order",
    "is_outcome_column",
    "normalize_position",
    "season_rank_map",
]

# Identity of one canonical record. A player may appear once per season/gameweek.
KEY_COLUMNS: tuple[str, ...] = ("season", "gameweek", "player_id")

# Minimum viable canonical dataset. Present and non-null in every canonical row.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "season",
    "gameweek",
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
    "minutes",
    "total_points",
)

# Recognized canonical names for fields that are carried through only when the
# raw source actually provides them. Absent fields are never fabricated.
OPTIONAL_COLUMNS: tuple[str, ...] = (
    "opponent_team_id",
    "is_home",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "yellow_cards",
    "red_cards",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "selected_by_percent",
    "availability_status",
    "fixture_difficulty",
)

# Every recognized canonical column name, required first then optional. A source
# column that maps to none of these is dropped rather than renamed on a guess.
CANONICAL_COLUMNS: tuple[str, ...] = (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)

# --- Time-of-knowledge classification -------------------------------------
#
# A canonical row for gameweek t is not uniformly "future". Some of its columns
# are already fixed when the gameweek t decision is made, and some only exist
# once the gameweek has been played. Leakage safety is therefore a per-column
# property, not a per-row property, and the split below is what the feature
# layer enforces mechanically.

# Known before the gameweek t deadline. A gameweek t feature, and the projection
# table for gameweek t, may read these from row t itself. Player price is the
# important case: the optimizer must spend the price actually payable at the
# deadline, so taking it from row t is correct rather than leaky.
PRE_MATCH_COLUMNS: tuple[str, ...] = (
    "season",
    "gameweek",
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
    "opponent_team_id",
    "is_home",
    "fixture_difficulty",
)

# Produced by playing gameweek t. A gameweek t feature may only read these from
# rows strictly before t, which is why every rolling aggregation over them is
# shifted by one gameweek before the window is applied.
OUTCOME_COLUMNS: tuple[str, ...] = (
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "yellow_cards",
    "red_cards",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
)

# Timing depends on how the source snapshotted the value, so it cannot be proven
# safe from the schema alone. Excluded from Sprint 0 features until a real source
# is inspected and its snapshot semantics are documented.
AMBIGUOUS_TIMING_COLUMNS: tuple[str, ...] = (
    "selected_by_percent",
    "availability_status",
)

# Canonical columns a caller may legitimately supply as metadata, because a
# single-season extract does not carry them in the file itself. Adapters are not
# required to map these; the pipeline can declare them instead.
EXTERNALLY_SUPPLIED_COLUMNS: tuple[str, ...] = ("season",)

# --- Canonical representation ----------------------------------------------
#
# The kind of each column drives coercion, so cleaning dispatches on a
# declarative table here instead of accumulating per-column branches.

ColumnKind: TypeAlias = Literal["identifier", "text", "position", "integer", "float", "boolean"]

COLUMN_KINDS: Mapping[str, ColumnKind] = MappingProxyType(
    {
        "season": "text",
        "gameweek": "integer",
        "player_id": "identifier",
        "name": "text",
        "team_id": "identifier",
        "position": "position",
        "price_tenths": "integer",
        "minutes": "integer",
        "total_points": "integer",
        "opponent_team_id": "identifier",
        "is_home": "boolean",
        "goals_scored": "integer",
        "assists": "integer",
        "clean_sheets": "integer",
        "goals_conceded": "integer",
        "saves": "integer",
        "bonus": "integer",
        "yellow_cards": "integer",
        "red_cards": "integer",
        "starts": "integer",
        "expected_goals": "float",
        "expected_assists": "float",
        "expected_goal_involvements": "float",
        "selected_by_percent": "float",
        "availability_status": "text",
        "fixture_difficulty": "float",
    }
)

# Columns that may never be negative. Realized `total_points` is deliberately
# absent: cards and own goals produce genuinely negative scores.
NON_NEGATIVE_COLUMNS: tuple[str, ...] = (
    "gameweek",
    "price_tenths",
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "yellow_cards",
    "red_cards",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goal_involvements",
    "selected_by_percent",
)

# Deterministic output row order for canonical and projection tables.
CANONICAL_SORT_COLUMNS: tuple[str, ...] = ("season", "gameweek", "player_id")

# Required row order before any time-dependent operation. Rolling windows are
# only meaningful when each player's history is contiguous and ascending in time.
PLAYER_TIME_SORT_COLUMNS: tuple[str, ...] = ("season", "player_id", "gameweek")

# Grouping key for every rolling or shifted feature. `season` is part of the key
# on purpose: it prevents one season's final gameweeks from leaking into the next
# season's opening gameweeks.
PLAYER_GROUP_COLUMNS: tuple[str, ...] = ("season", "player_id")

# Gameweeks are 1-based. No upper bound is defined here, because the maximum
# gameweek count is competition-specific and is supplied by validation config.
MIN_GAMEWEEK = 1

# Canonical prices are integer tenths of a currency unit: 5.5 -> 55, 10.0 -> 100.
PRICE_TENTHS_PER_UNIT = 10

# Conservative, extensible alias table. Platform-specific encodings (for example
# numeric position codes) belong in source adapters, not in the canonical schema.
_POSITION_ALIAS_SOURCES: Mapping[Position, tuple[str, ...]] = {
    "GK": ("GK", "GKP", "GOALKEEPER"),
    "DEF": ("DEF", "DEFENDER"),
    "MID": ("MID", "MIDFIELDER"),
    "FWD": ("FWD", "FORWARD"),
}

POSITION_ALIASES: Mapping[str, Position] = MappingProxyType(
    {alias: position for position, aliases in _POSITION_ALIAS_SOURCES.items() for alias in aliases}
)


def normalize_position(value: object) -> Position:
    """Map a raw position label to a canonical GK/DEF/MID/FWD value.

    Matching ignores surrounding whitespace and letter case. Unknown labels
    raise instead of falling back to a default, because a silently mis-assigned
    position would corrupt every downstream positional constraint.
    """

    if isinstance(value, str):
        canonical = POSITION_ALIASES.get(value.strip().upper())
        if canonical is not None:
            return canonical
    raise InvalidValueError(
        f"Unsupported position value {value!r}; expected one of "
        f"{sorted(POSITION_ALIASES)!r} (case-insensitive)."
    )


def season_rank_map(
    seasons: Iterable[str],
    *,
    season_order: Sequence[str] | None = None,
) -> Mapping[str, int]:
    """Return a chronological rank per season label.

    Season labels are ordered by sorting unless an explicit order is given. Sorting
    is correct for the conventional ``YYYY-YY`` form — ``2016-17`` precedes
    ``2017-18`` — but that is a property of the naming convention rather than a
    guarantee, so a caller with unconventional labels states the order instead.

    This lives at schema level because two layers need it — walk-forward splitting
    and cross-season features — and the higher of the two must not become a
    dependency of the lower.
    """

    present = sorted({str(season).strip() for season in seasons})
    if not present:
        raise InvalidValueError("At least one season label is required to rank seasons.")

    if season_order is None:
        return MappingProxyType({season: rank for rank, season in enumerate(present)})

    if isinstance(season_order, str) or not isinstance(season_order, Sequence):
        raise InvalidValueError("season_order must be a sequence of season labels.")
    declared = [str(season).strip() for season in season_order]
    if len(declared) != len(set(declared)):
        raise InvalidValueError(f"season_order contains duplicates: {declared!r}.")
    unranked = [season for season in present if season not in declared]
    if unranked:
        raise InvalidValueError(
            f"season_order does not cover seasons present in the data: {unranked!r}."
        )
    return MappingProxyType({season: rank for rank, season in enumerate(declared)})


def canonical_column_order(columns: Iterable[str]) -> list[str]:
    """Order columns canonically, keeping any unrecognized names last.

    Output column order is part of determinism, so it is imposed rather than
    inherited from whatever order a source happened to use.
    """

    requested = list(columns)
    present = set(requested)
    known = [column for column in CANONICAL_COLUMNS if column in present]
    extra = [column for column in requested if column not in CANONICAL_COLUMNS]
    return [*known, *extra]


def is_outcome_column(column: str) -> bool:
    """Return whether a column is only known after its gameweek has been played.

    The feature layer calls this to refuse unshifted aggregations over outcome
    columns. Columns whose snapshot timing has not been verified count as
    outcome columns. An unclassified column raises rather than defaulting,
    so adding a canonical column forces an explicit timing decision here.
    """

    if column in PRE_MATCH_COLUMNS:
        return False
    if column in OUTCOME_COLUMNS or column in AMBIGUOUS_TIMING_COLUMNS:
        return True
    raise InvalidValueError(
        f"Column {column!r} has no time-of-knowledge classification; add it to "
        "PRE_MATCH_COLUMNS, OUTCOME_COLUMNS, or AMBIGUOUS_TIMING_COLUMNS."
    )
