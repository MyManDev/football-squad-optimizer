"""Adapter for the vaastav Fantasy-Premier-League historical archive.

Everything specific to this source lives here: its file layout, its column names,
its numeric position codes, and the two corrections its data requires. The
canonical layers above know none of it.

The archive's own licence covers its code, not its data — the author states the
data belongs to fantasy.premierleague.com and understat.com. Nothing downloaded
through this module is committed to the repository; see ``data/sources/README.md``.

Two source-specific facts drive the design, both established by inspecting the
archive rather than assumed:

**Player identity.** ``merged_gw.csv`` carries ``element``, which is a per-season
identifier: of 479 players present in both 2024-25 and 2025-26, 479 share a
``code`` and only 1 shares an ``id``. Using ``element`` would fragment every
player's history at each season boundary, which is precisely the history a
cross-season feature needs. The loader therefore joins each gameweek row to
``players_raw.csv`` to recover the stable ``code``.

**Price timing.** The archive documents ``value`` as "player price at this gameweek"
without saying whether that is the deadline price or a price recorded afterwards. In
2025-26 gameweek 1, ``value`` differs from ``players_raw`` ``now_cost`` for 537 of
692 players and is systematically higher, which is consistent with a post-gameweek
capture but does not prove it. Between a stale price and a leaky one this module
prefers stale: see :func:`shift_price_to_deadline`.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from squadopt.data.adapters import SourceAdapter, apply_adapter
from squadopt.data.cleaning import clean_canonical_dataset
from squadopt.data.errors import DataSourceError, DuplicateRecordsError, MissingColumnsError
from squadopt.data.fixtures import validate_fixture_snapshot
from squadopt.data.loaders import load_csv
from squadopt.data.schema import (
    CANONICAL_SORT_COLUMNS,
    FIXTURE_COLUMNS,
    PLAYER_TIME_SORT_COLUMNS,
    POSITION_ALIASES,
)
from squadopt.data.timestamps import normalize_utc_timestamp
from squadopt.data.validation import validate_canonical_dataset

# The archive is still updated, so an unpinned read would give two people different
# data. Every fetch and every manifest entry is tied to this commit.
ARCHIVE_REPOSITORY = "vaastav/Fantasy-Premier-League"
ARCHIVE_COMMIT = "8c97b2adb123863c3dd581e730f1360e89815ac2"

# Provenance for rows backfilled from the archive. The fixture table's snapshot field
# expects a live capture, and the archive is not one: it has no capture instant, so the
# pin itself is what identifies these rows. Naming the commit keeps them reproducible
# and keeps them visibly distinct from anything captured before a deadline.
ARCHIVE_SNAPSHOT_ID = f"vaastav-{ARCHIVE_COMMIT[:7]}"

# Seasons whose `merged_gw.csv` carries `position` and `team`. Earlier seasons omit
# both, so canonicalizing them would need a further join; that is deliberately out
# of scope rather than silently approximated.
SUPPORTED_SEASONS: tuple[str, ...] = (
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
    "2025-26",
)

GAMEWEEK_FILE = "gws/merged_gw.csv"
ROSTER_FILE = "players_raw.csv"

# Fixture-level files. The gameweek file cannot answer who a team played, because a
# gameweek can hold more than one fixture for the same player and the archive's own
# two team references disagree: `team` there is a display name while `opponent_team`
# is a per-season integer. Both files below are needed to reconcile them.
FIXTURES_FILE = "fixtures.csv"
TEAMS_FILE = "teams.csv"

# Only columns present in every supported season are mapped. Advanced metrics such
# as expected goals and `starts` appear in some seasons and not others, and a panel
# with a column missing for one season would fail canonical validation. Adding them
# means either restricting the season range or handling per-season availability.
# `opponent_team` and `was_home` are deliberately absent. They are fixture-level
# attributes, and a gameweek can hold more than one fixture for the same player — up
# to three in the rescheduled 2020-21 season — so at player-gameweek grain they have
# no single correct value. Representing them properly needs a fixture-level grain,
# which is a schema change requiring cross-owner agreement.
COLUMN_MAP: Mapping[str, str] = MappingProxyType(
    {
        "season": "season",
        "round": "gameweek",
        "player_code": "player_id",
        "name": "name",
        "team": "team_id",
        "position": "position",
        "value": "price_tenths",
        "minutes": "minutes",
        "total_points": "total_points",
    }
)

# Canonical player-position labels and aliases. The archive spells goalkeeper as
# `GKP` in 2021-22 GW37 and `GK` elsewhere, so both must survive this filter.
# From 2024-25 the archive also carries `AM`
# rows — twenty per season, one per club — which are managers rather than players.
# They are excluded because a manager is not a squad-eligible player under the
# canonical contract, not because they are inconvenient.
PLAYER_POSITIONS: frozenset[str] = frozenset(POSITION_ALIASES)

# Summed when a player appears in more than one fixture within a gameweek. Price is
# not summed: it is identical across a player's fixtures in every supported season,
# verified across all six.
_ADDITIVE_COLUMNS: tuple[str, ...] = ("minutes", "total_points")

# FPL encodes position numerically in `players_raw.csv`. `merged_gw.csv` already
# carries the label from 2020-21 onwards, so both spellings are accepted.
POSITION_CODES: Mapping[str, str] = MappingProxyType(
    {"1": "GK", "2": "DEF", "3": "MID", "4": "FWD"}
)

VAASTAV_ADAPTER = SourceAdapter(
    name="vaastav-fpl",
    column_map=COLUMN_MAP,
    position_codes=POSITION_CODES,
    price_unit="tenths",
)

# Columns the loader needs before adaptation can begin.
_REQUIRED_GAMEWEEK_COLUMNS: tuple[str, ...] = (
    "element",
    "fixture",
    "round",
    "name",
    "team",
    "position",
    "value",
    "minutes",
    "total_points",
)
_REQUIRED_ROSTER_COLUMNS: tuple[str, ...] = ("id", "code")
_REQUIRED_TEAM_COLUMNS: tuple[str, ...] = ("id", "code", "name")
_REQUIRED_FIXTURE_COLUMNS: tuple[str, ...] = (
    "id",
    "event",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
    "kickoff_time",
    "finished",
    "provisional_start_time",
)


def season_directory(root: Path | str, season: str) -> Path:
    """Return the archive directory for one season inside a local checkout."""

    return Path(root) / "data" / season


def _read_required(path: Path, required: Sequence[str], label: str) -> pd.DataFrame:
    if not path.is_file():
        raise DataSourceError(
            f"{label} not found at {path}; run 'python -m scripts.fetch_historical_data' first."
        )
    frame = load_csv(path)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise MissingColumnsError(
            f"{label} at {path} is missing columns {missing!r}; the archive layout may have "
            f"changed since commit {ARCHIVE_COMMIT}."
        )
    return frame


def attach_player_code(gameweeks: pd.DataFrame, roster: pd.DataFrame) -> pd.DataFrame:
    """Join each gameweek row to the roster's stable ``code``.

    ``element`` is only unique within a season, so it cannot be the canonical
    player identity. Every gameweek row must find a roster match: an unmatched row
    would silently lose a player rather than raise, so the join is checked.
    """

    codes = roster.loc[:, ["id", "code"]].copy(deep=True)
    codes = codes.rename(columns={"id": "element", "code": "player_code"})
    duplicated = codes.loc[codes["element"].duplicated(), "element"].tolist()
    if duplicated:
        raise DataSourceError(
            f"Roster contains duplicate element ids: {duplicated[:10]!r}; cannot join safely."
        )

    joined = gameweeks.merge(codes, on="element", how="left", validate="many_to_one")
    unmatched = joined.loc[joined["player_code"].isna(), "element"].drop_duplicates().tolist()
    if unmatched:
        raise DataSourceError(
            f"{len(unmatched)} gameweek rows have no roster entry (element ids "
            f"{unmatched[:10]!r}); the archive files may be from different snapshots."
        )
    return joined


def drop_non_player_rows(gameweeks: pd.DataFrame) -> pd.DataFrame:
    """Remove rows whose position is not a squad-eligible player position."""

    normalized_labels = gameweeks["position"].map(
        lambda value: str(value).strip().upper() if not pd.isna(value) else ""
    )
    keep = normalized_labels.isin(PLAYER_POSITIONS)
    return gameweeks.loc[keep].copy(deep=True)


def collapse_to_player_gameweek(gameweeks: pd.DataFrame) -> pd.DataFrame:
    """Reduce fixture-level rows to one row per player and gameweek.

    Two different situations produce more than one row per player-gameweek, and
    treating them alike would corrupt the data:

    **Repeated records.** The archive contains a small number of byte-identical rows
    for the same fixture — ten in 2025-26. Summing those would double a player's
    minutes and points. They are dropped on ``(element, round, fixture)`` first.

    **Genuine double gameweeks.** A player really can play twice, or three times in
    the rescheduled 2020-21 season. Those rows describe separate matches, so minutes
    and points are summed while price is taken once, since a player's price does not
    move within a gameweek — verified across all six supported seasons.
    """

    deduplicated = gameweeks.drop_duplicates(
        subset=["element", "fixture", "round"], keep="first"
    ).copy(deep=True)

    additive = [column for column in _ADDITIVE_COLUMNS if column in deduplicated.columns]

    # Coerce before summing. The loader reads every column as text on purpose, and
    # summing text concatenates it: two gameweeks of "1" point would become "11",
    # which then parses as eleven. That failure is silent, so it is prevented here
    # rather than hoped against.
    for column in additive:
        try:
            deduplicated[column] = pd.to_numeric(deduplicated[column], errors="raise")
        except (TypeError, ValueError) as error:
            raise DataSourceError(
                f"Column {column!r} must be numeric before gameweek rows are combined: {error}"
            ) from error

    other = [
        column
        for column in deduplicated.columns
        if column not in {*additive, "element", "round", "fixture"}
    ]
    aggregation = {column: "sum" for column in additive}
    aggregation.update({column: "first" for column in other})

    collapsed = (
        deduplicated.sort_values(["element", "round", "fixture"], kind="stable")
        .groupby(["element", "round"], as_index=False, sort=True)
        .agg(aggregation)
    )
    return collapsed.drop(columns=["fixture"], errors="ignore")


def shift_price_to_deadline(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace each row's price with the previous gameweek's, per player and season.

    The archive does not document whether ``value`` is the deadline price or a price
    recorded after the gameweek. If it is the latter, using it directly would let a
    gameweek's own result reach that gameweek's decision: a player who scored well
    rises in price, so the price would quietly encode the outcome. Shifting instead
    costs at most one price change of accuracy, and an accuracy cost is preferable to
    a leakage one.

    The opening gameweek of each season has no earlier price, so it keeps its own
    value. That residual approximation is confined to exactly the gameweek that
    walk-forward folds already exclude by default.
    """

    ordered = frame.sort_values(list(PLAYER_TIME_SORT_COLUMNS), kind="stable").copy(deep=True)
    grouped = ordered.groupby(["season", "player_id"], sort=False)["price_tenths"]
    shifted = grouped.shift(1)
    ordered["price_tenths"] = shifted.fillna(ordered["price_tenths"]).astype("int64")
    return ordered


def load_season(
    root: Path | str,
    season: str,
    *,
    shift_price: bool = True,
) -> pd.DataFrame:
    """Load one archive season as a validated canonical player-gameweek dataset."""

    directory = season_directory(root, season)
    gameweeks = _read_required(
        directory / GAMEWEEK_FILE, _REQUIRED_GAMEWEEK_COLUMNS, f"{season} gameweek data"
    )
    roster = _read_required(directory / ROSTER_FILE, _REQUIRED_ROSTER_COLUMNS, f"{season} roster")

    players_only = drop_non_player_rows(gameweeks)
    collapsed = collapse_to_player_gameweek(players_only)
    joined = attach_player_code(collapsed, roster).assign(season=season)
    adapted = apply_adapter(joined, VAASTAV_ADAPTER)
    cleaned = clean_canonical_dataset(adapted, price_unit=VAASTAV_ADAPTER.price_unit)
    if shift_price:
        cleaned = shift_price_to_deadline(cleaned)
    validated = validate_canonical_dataset(cleaned)
    return validated.sort_values(list(CANONICAL_SORT_COLUMNS), kind="stable").reset_index(drop=True)


def build_panel(
    root: Path | str,
    *,
    seasons: Sequence[str] | None = None,
    shift_price: bool = True,
) -> pd.DataFrame:
    """Load several archive seasons into one canonical panel.

    Seasons are validated individually and then concatenated, so a fault is reported
    against the season that caused it rather than against the whole panel.
    """

    requested = tuple(SUPPORTED_SEASONS if seasons is None else seasons)
    if not requested:
        raise DataSourceError("At least one season is required.")
    unsupported = [season for season in requested if season not in SUPPORTED_SEASONS]
    if unsupported:
        raise DataSourceError(
            f"Seasons {unsupported!r} are outside the supported range {list(SUPPORTED_SEASONS)!r}; "
            "earlier archive seasons omit 'position' and 'team' from their gameweek files."
        )

    frames = [load_season(root, season, shift_price=shift_price) for season in requested]
    panel = pd.concat(frames, ignore_index=True)
    return panel.sort_values(list(CANONICAL_SORT_COLUMNS), kind="stable").reset_index(drop=True)


def load_team_codes(root: Path | str, season: str) -> pd.DataFrame:
    """Return one season's team table: per-season id, persistent code, display name.

    All three are needed because the archive uses two of them in the same breath. Its
    gameweek file names a club by display name while its fixture file names the same
    club by the per-season integer, and this table is the only bridge between them.
    Verified across all six supported seasons: the gameweek names match this file's
    ``name`` column exactly, and every ``opponent_team`` value appears in its ``id``.
    """

    path = season_directory(root, season) / TEAMS_FILE
    teams = _read_required(path, _REQUIRED_TEAM_COLUMNS, f"{season} teams")

    selected = teams.loc[:, ["id", "code", "name"]].copy(deep=True)
    for column in ("id", "code"):
        values = pd.to_numeric(selected[column], errors="coerce")
        if bool(values.isna().any()):
            raise DataSourceError(f"{season} teams file has non-numeric {column!r} values.")
        selected[column] = values.astype("int64")
    duplicated = selected.loc[selected["id"].duplicated(), "id"].tolist()
    if duplicated:
        raise DuplicateRecordsError(f"{season} teams file repeats team id(s) {duplicated!r}.")
    selected["name"] = selected["name"].astype("string").str.strip()
    return selected.sort_values("id", kind="stable").reset_index(drop=True)


_TRUE_FLAGS: frozenset[str] = frozenset({"true", "1"})
_FALSE_FLAGS: frozenset[str] = frozenset({"false", "0"})


def _archive_flag(value: object, label: str) -> bool:
    """Read one of the archive's boolean columns without trusting ``bool()``.

    CSV booleans arrive as native ``bool`` only while a column happens to be
    uniformly true or false. One blank value turns the whole column to text, and
    ``bool("False")`` is ``True`` — which would silently classify an unplayed fixture
    as final. An unrecognised flag therefore stops the run instead.
    """

    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_FLAGS:
        return True
    if text in _FALSE_FLAGS:
        return False
    raise DataSourceError(
        f"{label} must be a boolean flag, got {value!r}. Guessing would risk reporting "
        "an unplayed fixture as finished."
    )


def _fixture_status(finished: object, provisional: object, label: str) -> str:
    """Classify a fixture from the two flags the archive publishes about it."""

    if _archive_flag(finished, f"{label} 'finished'"):
        return "final"
    if _archive_flag(provisional, f"{label} 'provisional_start_time'"):
        return "provisional"
    return "scheduled"


def load_fixture_snapshot(root: Path | str, season: str) -> pd.DataFrame:
    """Build the fixture table for one archive season.

    Each fixture becomes two rows describing it from either side, because that is the
    only grain at which "who is the opponent" has an answer when a gameweek holds more
    than one fixture for the same club.

    Two provenance fields stay empty and cannot be otherwise. The archive is published
    after the fact and records neither when it was scraped nor the deadline that
    preceded each gameweek — deadlines live in the platform's event list, which the
    archive does not ship. A capture time invented here would forge the one field every
    leakage argument depends on, and a deadline cannot be recovered from a kickoff time.

    Fixtures with no gameweek assigned are excluded rather than stored with an empty
    one. That is how the source represents a postponement awaiting refixturing, and it
    is also the right answer: a club whose match was postponed has no fixture in that
    gameweek, and a later read carries it under whichever gameweek it is played in.
    """

    codes = load_team_codes(root, season).set_index("id")["code"]
    path = season_directory(root, season) / FIXTURES_FILE
    fixtures = _read_required(path, _REQUIRED_FIXTURE_COLUMNS, f"{season} fixtures")

    scheduled = fixtures.loc[fixtures["event"].notna()].copy(deep=True)
    unscheduled = len(fixtures) - len(scheduled)

    rows: list[dict[str, object]] = []
    unknown_teams: list[int] = []
    for record in scheduled.to_dict("records"):
        home_id = int(record["team_h"])
        away_id = int(record["team_a"])
        if home_id not in codes.index or away_id not in codes.index:
            unknown_teams.extend(
                identifier for identifier in (home_id, away_id) if identifier not in codes.index
            )
            continue
        status = _fixture_status(
            record["finished"],
            record["provisional_start_time"],
            f"{season} fixture {record['id']}",
        )
        kickoff = normalize_utc_timestamp(
            record["kickoff_time"], label=f"{season} fixture {record['id']} kickoff_time"
        )
        shared = {
            "snapshot_id": ARCHIVE_SNAPSHOT_ID,
            "captured_at_utc": pd.NA,
            "season": season,
            "gameweek": int(record["event"]),
            "fixture_id": int(record["id"]),
            "kickoff_time_utc": kickoff,
            "deadline_timestamp_utc": pd.NA,
            "status": status,
        }
        rows.append(
            {
                **shared,
                "team_id": int(codes.loc[home_id]),
                "opponent_team_id": int(codes.loc[away_id]),
                "is_home": True,
                "fixture_difficulty": record["team_h_difficulty"],
            }
        )
        rows.append(
            {
                **shared,
                "team_id": int(codes.loc[away_id]),
                "opponent_team_id": int(codes.loc[home_id]),
                "is_home": False,
                "fixture_difficulty": record["team_a_difficulty"],
            }
        )

    if unknown_teams:
        raise DataSourceError(
            f"{season} fixtures reference team ids the season's teams file does not "
            f"declare: {sorted(set(unknown_teams))!r}."
        )
    if not rows:
        raise DataSourceError(
            f"{season} produced no fixture rows; {unscheduled} fixture(s) had no gameweek."
        )

    frame = pd.DataFrame(rows, columns=list(FIXTURE_COLUMNS))
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    frame["is_home"] = frame["is_home"].astype("boolean")
    frame["fixture_difficulty"] = pd.to_numeric(
        frame["fixture_difficulty"], errors="coerce"
    ).astype("Int64")
    # The two archive-empty columns are typed explicitly rather than left as all-NA
    # object columns, so concatenating seasons cannot silently change their dtype.
    for column in (
        "snapshot_id",
        "season",
        "kickoff_time_utc",
        "status",
        "captured_at_utc",
        "deadline_timestamp_utc",
    ):
        frame[column] = frame[column].astype("string")
    return validate_fixture_snapshot(frame)


def build_fixture_panel(root: Path | str, *, seasons: Sequence[str] | None = None) -> pd.DataFrame:
    """Load several seasons' fixtures into one table.

    Seasons are validated individually and then concatenated, so a fault names the
    season that caused it.
    """

    requested = tuple(SUPPORTED_SEASONS if seasons is None else seasons)
    if not requested:
        raise DataSourceError("At least one season is required.")
    unsupported = [season for season in requested if season not in SUPPORTED_SEASONS]
    if unsupported:
        raise DataSourceError(
            f"Seasons {unsupported!r} are outside the supported range {list(SUPPORTED_SEASONS)!r}."
        )

    frames = [load_fixture_snapshot(root, season) for season in requested]
    return validate_fixture_snapshot(pd.concat(frames, ignore_index=True))


def load_upcoming_roster(root: Path | str, season: str) -> pd.DataFrame:
    """Load a season's roster before it starts: the player pool and opening prices.

    A season with no completed gameweeks has no ``merged_gw.csv``, but its
    ``players_raw.csv`` already lists the pool with ``now_cost``. That price is
    unambiguous — the season has not begun, so nothing can have moved it — which
    makes it the right source for an opening-gameweek decision.

    Numeric position codes are translated here rather than downstream, because a
    platform's encoding is source knowledge and the canonical schema deliberately
    knows nothing about it. Non-player entries — element types outside the four
    squad-eligible positions, such as managers — are dropped for the same reason they
    are dropped from gameweek rows.
    """

    path = season_directory(root, season) / ROSTER_FILE
    roster = _read_required(
        path, ("id", "code", "element_type", "team", "now_cost", "web_name"), f"{season} roster"
    )

    selected = roster.loc[:, ["code", "web_name", "team", "element_type", "now_cost"]].copy(
        deep=True
    )
    selected["position"] = [
        POSITION_CODES.get(str(value).strip().upper()) for value in selected["element_type"]
    ]
    players_only = selected.loc[selected["position"].notna()].copy(deep=True)
    return players_only.drop(columns=["element_type"]).reset_index(drop=True)
