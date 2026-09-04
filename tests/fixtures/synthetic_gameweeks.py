"""Small, synthetic player-gameweek panels for data-layer tests.

Values come from fixed arithmetic patterns rather than a random generator, so the
fixtures are reproducible without seeding anything.

The patterns are deliberately non-monotone and out of phase between players.
Constant or uniformly increasing synthetic data is useless for leakage testing: a
shifted rolling mean and an unshifted one produce identical numbers when every
gameweek looks the same, so a broken implementation would still pass.

The raw layout is a fictional source used only to exercise adapters. It is not a
claim about any real provider's schema.
"""

import pandas as pd

from squadopt.data.adapters import SourceAdapter
from squadopt.data.schema import CANONICAL_SORT_COLUMNS, REQUIRED_COLUMNS

SEASON = "2025-26"
GAMEWEEK_COUNT = 8
TEAM_COUNT = 6
FIRST_PLAYER_ID = 101

# One squad per team, so the pool satisfies the optimizer's default position
# quotas (2 GK, 5 DEF, 5 MID, 3 FWD) and its maximum of three players per team.
TEAM_POSITIONS: tuple[str, ...] = ("GK", "DEF", "DEF", "MID", "MID", "FWD")

BASE_PRICE_TENTHS: dict[str, int] = {"GK": 45, "DEF": 50, "MID": 65, "FWD": 70}

# Rotation-like minutes, including benched gameweeks.
MINUTES_PATTERN: tuple[int, ...] = (90, 90, 0, 72, 90, 15, 90, 60)

# Scoring pattern including a negative gameweek, which is realistic (cards, own
# goals) and confirms that realized points are never clamped.
POINTS_PATTERN: tuple[int, ...] = (2, 6, 1, 9, -1, 3, 12, 0, 5, 8, 1, 4)

# Fictional raw column layout, plus one column no adapter maps.
RAW_COLUMN_MAP: dict[str, str] = {
    "season_label": "season",
    "gw": "gameweek",
    "player_ref": "player_id",
    "display_name": "name",
    "club_ref": "team_id",
    "pos_code": "position",
    "price": "price_tenths",
    "minutes_played": "minutes",
    "points": "total_points",
}
RAW_UNMAPPED_COLUMN = "ingested_at"
RAW_POSITION_CODES: dict[str, str] = {"1": "GK", "2": "DEF", "3": "MID", "4": "FWD"}

SAMPLE_ADAPTER = SourceAdapter(
    name="synthetic-sample",
    column_map=RAW_COLUMN_MAP,
    position_codes=RAW_POSITION_CODES,
    price_unit="units",
)


def _players() -> list[tuple[int, int, str]]:
    """Return ``(player_id, team_id, position)`` for the whole synthetic pool."""

    players: list[tuple[int, int, str]] = []
    player_id = FIRST_PLAYER_ID
    for team_id in range(1, TEAM_COUNT + 1):
        for position in TEAM_POSITIONS:
            players.append((player_id, team_id, position))
            player_id += 1
    return players


def _price_tenths(index: int, position: str, gameweek: int) -> int:
    """Return a per-gameweek price so price is genuinely a row-level value."""

    drift = (gameweek - 1) // 4
    return BASE_PRICE_TENTHS[position] + (index % 5) * 5 + drift


def _minutes(index: int, gameweek: int) -> int:
    return MINUTES_PATTERN[(gameweek - 1 + index) % len(MINUTES_PATTERN)]


def _total_points(index: int, gameweek: int, minutes: int) -> int:
    if minutes == 0:
        return 0
    return POINTS_PATTERN[(gameweek * 3 + index * 5) % len(POINTS_PATTERN)]


def canonical_records() -> list[dict[str, object]]:
    """Return canonical player-gameweek records in canonical sort order."""

    records: list[dict[str, object]] = []
    for index, (player_id, team_id, position) in enumerate(_players()):
        for gameweek in range(1, GAMEWEEK_COUNT + 1):
            minutes = _minutes(index, gameweek)
            records.append(
                {
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": player_id,
                    "name": f"Synthetic {position} {player_id}",
                    "team_id": team_id,
                    "position": position,
                    "price_tenths": _price_tenths(index, position, gameweek),
                    "minutes": minutes,
                    "total_points": _total_points(index, gameweek, minutes),
                }
            )
    records.sort(key=lambda record: tuple(str(record[key]) for key in CANONICAL_SORT_COLUMNS))
    return records


def make_canonical_gameweeks() -> pd.DataFrame:
    """Return a clean canonical panel with the dtypes the contract requires."""

    frame = pd.DataFrame.from_records(canonical_records(), columns=list(REQUIRED_COLUMNS))
    return frame.astype(
        {
            "season": "string",
            "gameweek": "int64",
            "player_id": "int64",
            "name": "string",
            "team_id": "int64",
            "position": "string",
            "price_tenths": "int64",
            "minutes": "int64",
            "total_points": "int64",
        }
    )


PREVIOUS_SEASON = "2024-25"


def make_two_season_gameweeks() -> pd.DataFrame:
    """Return the same players across two seasons, with clearly distinct scoring.

    The earlier season's points are shifted far away from the later season's, so a
    rolling window that wrongly spans the season boundary changes the numbers
    visibly instead of blending into plausible noise.
    """

    later = make_canonical_gameweeks()
    earlier = later.assign(
        season=PREVIOUS_SEASON,
        total_points=later["total_points"] + 50,
        minutes=90,
    ).astype(later.dtypes.to_dict())
    combined = pd.concat([earlier, later], ignore_index=True)
    return combined.sort_values(list(CANONICAL_SORT_COLUMNS), kind="stable").reset_index(drop=True)


def _scramble_key(record: dict[str, object]) -> tuple[int, int, int]:
    """Deterministic non-canonical ordering, to prove output order is imposed."""

    gameweek = int(str(record["gameweek"]))
    player_id = int(str(record["player_id"]))
    return ((gameweek * 37 + player_id * 11) % 101, player_id, gameweek)


def raw_records() -> list[dict[str, str]]:
    """Return the synthetic panel in the fictional raw layout, as text."""

    inverse = {canonical: raw for raw, canonical in RAW_COLUMN_MAP.items()}
    position_codes = {position: code for code, position in RAW_POSITION_CODES.items()}

    scrambled = sorted(canonical_records(), key=_scramble_key)
    raw: list[dict[str, str]] = []
    for record in scrambled:
        price_tenths = int(str(record["price_tenths"]))
        raw.append(
            {
                inverse["season"]: str(record["season"]),
                inverse["gameweek"]: str(record["gameweek"]),
                inverse["player_id"]: str(record["player_id"]),
                inverse["name"]: str(record["name"]),
                inverse["team_id"]: str(record["team_id"]),
                inverse["position"]: position_codes[str(record["position"])],
                inverse["price_tenths"]: f"{price_tenths / 10:.1f}",
                inverse["minutes"]: str(record["minutes"]),
                inverse["total_points"]: str(record["total_points"]),
                RAW_UNMAPPED_COLUMN: f"{SEASON}-ingest",
            }
        )
    return raw


def make_raw_gameweeks() -> pd.DataFrame:
    """Return the raw-shaped panel as all-text columns, matching a CSV read.

    Rows are deliberately not in canonical order, prices are decimal strings in
    whole units, positions are numeric codes, and one column maps to nothing.
    """

    columns = [*RAW_COLUMN_MAP, RAW_UNMAPPED_COLUMN]
    frame = pd.DataFrame.from_records(raw_records(), columns=columns)
    # `str` rather than the nullable `string` dtype, so this matches what
    # `load_csv` returns exactly and the sample-data drift test can be exact.
    return frame.astype(str)
