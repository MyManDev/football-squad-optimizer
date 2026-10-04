"""Where a published league's tree lives, and the directory that lists the leagues.

A site publishes ``data/leagues.json``, the directory, and one tree per league under
``data/leagues/<league_id>/`` (members.json, entries/, advice/, scoreboard.json, the
device-plan document, history/). The directory is the set of leagues the last publication
rendered: one run renders every league from one capture for one week, and writes the
directory whole. Readers read the directory first; a site from before it carried one
league under ``data/league/`` and is read as a directory of one, and the first
publication into the new layout adopts that tree as the league's own. Every writer and
reader of a league tree takes its path from here, so no module spells the layout.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

LEAGUE_DIRECTORY_CONTRACT_VERSION: Final = "league_directory_v1"
LEAGUE_DIRECTORY_FILE: Final = "leagues.json"
LEAGUES_ROOT: Final = "leagues"
#: The single tree a site published before the directory existed.
LEGACY_TREE: Final = "league"


class LeagueDirectoryError(ValueError):
    """The directory is not the document the contract describes."""


def league_tree(league_id: int) -> PurePosixPath:
    """The league's tree, relative to ``data/``: ``leagues/<league_id>``."""

    if isinstance(league_id, bool) or not isinstance(league_id, int) or league_id <= 0:
        raise LeagueDirectoryError(f"A league id is a positive integer; got {league_id!r}.")
    return PurePosixPath(LEAGUES_ROOT) / str(league_id)


def league_tree_dir(site_data_root: Path, league_id: int) -> Path:
    """The league's tree under a site's ``data/`` directory."""

    return Path(site_data_root) / Path(*league_tree(league_id).parts)


@dataclass(frozen=True, slots=True)
class PublishedLeague:
    """One line of the directory: the league, its season and deadline, and its tree."""

    league_id: int
    league_name: str
    season: str
    gameweek: int
    path: str

    def as_record(self) -> dict[str, Any]:
        return {
            "league_id": int(self.league_id),
            "league_name": str(self.league_name),
            "season": str(self.season),
            "gameweek": int(self.gameweek),
            "path": str(self.path),
        }


def _published(record: object) -> PublishedLeague:
    if not isinstance(record, dict):
        raise LeagueDirectoryError("A directory line is an object.")
    league_id, name, season, gameweek, path = (
        record.get("league_id"),
        record.get("league_name"),
        record.get("season"),
        record.get("gameweek"),
        record.get("path"),
    )
    if (
        isinstance(league_id, bool)
        or not isinstance(league_id, int)
        or league_id <= 0
        or not isinstance(name, str)
        or not name.strip()
        or not isinstance(season, str)
        or not season.strip()
        or isinstance(gameweek, bool)
        or not isinstance(gameweek, int)
        or gameweek <= 0
        or not isinstance(path, str)
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or not path
    ):
        raise LeagueDirectoryError(f"A directory line is not a published league: {record!r}.")
    return PublishedLeague(league_id, name, season, gameweek, path)


def read_league_directory(site_data_root: Path) -> list[PublishedLeague]:
    """The directory under ``data/``; an empty list where the site publishes none yet."""

    target = Path(site_data_root) / LEAGUE_DIRECTORY_FILE
    if not target.is_file():
        return []
    document = json.loads(target.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("contract_version") != LEAGUE_DIRECTORY_CONTRACT_VERSION
        or not isinstance(document.get("payload"), dict)
        or not isinstance(document["payload"].get("leagues"), list)
    ):
        raise LeagueDirectoryError(f"{target} is not a league directory.")
    leagues = [_published(record) for record in document["payload"]["leagues"]]
    ids = [league.league_id for league in leagues]
    if len(set(ids)) != len(ids):
        raise LeagueDirectoryError(f"{target} lists a league twice.")
    return leagues


def write_league_directory(
    site_data_root: Path,
    leagues: Iterable[PublishedLeague],
    *,
    generated_at_utc: str,
    source_kind: str = "live",
) -> Path:
    """Write the directory: exactly the leagues given, sorted by league id.

    The directory is what the last publication rendered, so it is written whole; a league
    the run did not render is not listed, and every line is checked the way a reader
    checks it before it is written, so no line can be written that no reader accepts.
    """

    rows = sorted((_published(league.as_record()) for league in leagues), key=lambda r: r.league_id)
    if not rows:
        raise LeagueDirectoryError("A directory lists at least one league.")
    if len({row.league_id for row in rows}) != len(rows):
        raise LeagueDirectoryError("A directory lists a league once.")
    if len({row.path for row in rows}) != len(rows):
        raise LeagueDirectoryError("Two leagues cannot share a tree.")
    target = Path(site_data_root) / LEAGUE_DIRECTORY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "contract_version": LEAGUE_DIRECTORY_CONTRACT_VERSION,
                "generated_at_utc": generated_at_utc,
                "source_kind": source_kind,
                "payload": {"leagues": [row.as_record() for row in rows]},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def _tree_path(site_data_root: Path, league: PublishedLeague) -> Path:
    return Path(site_data_root) / Path(*PurePosixPath(league.path).parts)


def legacy_tree_league_id(site_data_root: Path) -> int | None:
    """The league the legacy tree names, or None where there is no legacy tree.

    A members document that cannot be read names no league; the caller decides whether
    an unreadable tree is a refusal.
    """

    members = Path(site_data_root) / LEGACY_TREE / "members.json"
    if not members.is_file():
        return None
    try:
        document = json.loads(members.read_text(encoding="utf-8"))
        league_id = document["payload"]["league_id"]
    except (ValueError, KeyError, TypeError, OSError):
        return None
    return league_id if isinstance(league_id, int) and not isinstance(league_id, bool) else None


def find_league_tree(site_data_root: Path, league_id: int) -> Path | None:
    """The tree a reader opens for a league, or None where the site does not publish it.

    The directory's line for the league. A site from before the directory has one league
    under ``data/league/``, read for any id: its members document names the league, and
    the caller checks it (an unreadable one is the caller's refusal, not an absence). A
    directory that does not list the league is a site that does not publish it, legacy
    tree or not.
    """

    leagues = read_league_directory(site_data_root)
    if not leagues:
        return Path(site_data_root) / LEGACY_TREE
    for league in leagues:
        if league.league_id == league_id:
            return _tree_path(site_data_root, league)
    return None


def published_league_trees(site_data_root: Path) -> list[Path]:
    """Every tree the site publishes: one per directory line, in directory order, or the
    legacy tree alone where the site publishes no directory."""

    leagues = read_league_directory(site_data_root)
    if not leagues:
        return [Path(site_data_root) / LEGACY_TREE]
    return [_tree_path(site_data_root, league) for league in leagues]


def single_league_tree(site_data_root: Path, league_id: int | None = None) -> Path:
    """The one tree a single-league reader opens.

    With an id, that league's tree, which the site must publish. Without one, the only
    league the directory lists, or the legacy tree where the site publishes no directory;
    a directory listing several leagues needs the id.
    """

    if league_id is not None:
        tree = find_league_tree(site_data_root, league_id)
        if tree is None:
            raise LeagueDirectoryError(f"The site does not publish league {league_id}.")
        return tree
    leagues = read_league_directory(site_data_root)
    if len(leagues) > 1:
        raise LeagueDirectoryError(
            f"{Path(site_data_root) / LEAGUE_DIRECTORY_FILE} lists {len(leagues)} leagues; "
            "say which one."
        )
    if leagues:
        return _tree_path(site_data_root, leagues[0])
    return Path(site_data_root) / LEGACY_TREE
