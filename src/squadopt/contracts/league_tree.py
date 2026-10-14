"""Where a published league's tree lives, and the directory that lists the leagues.

A site publishes ``data/leagues.json``, the directory, and one tree per league under
``data/leagues/<league_id>/`` (members.json, entries/, advice/, scoreboard.json, the
device-plan document, history/). The directory is the set of leagues the last publication
rendered: one run renders every league from one capture for one week, and writes the
directory whole. Beside the trees, one device-plan table per capture lives under
``data/device/<capture>/device-plan.json``: the same table for every league of the run.
A directory line names its league's table under ``device_plan`` and the sha256 of the
table file's bytes under ``device_plan_sha256``. The path is the capture's, but the table
is replaced when the week is published again from that capture, so the digest is its
version: a reader asks for it at that digest and checks the bytes against it. The site
lets a browser keep the path for a year whatever the query, so the bare path can still
serve an earlier table of the capture. A line from before the table has neither. Readers
read the directory first; a site from before it carried one league under
``data/league/`` and is read as a directory of one, and the first publication into the
new layout adopts that tree as the league's own. Every writer and reader of a league tree
takes its path from here, so no module spells the layout.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

LEAGUE_DIRECTORY_CONTRACT_VERSION: Final = "league_directory_v1"
LEAGUE_DIRECTORY_FILE: Final = "leagues.json"
LEAGUES_ROOT: Final = "leagues"
#: The single tree a site published before the directory existed.
LEGACY_TREE: Final = "league"
#: The per-capture device-plan tables, one directory per capture.
DEVICE_ROOT: Final = "device"
DEVICE_PLAN_FILE: Final = "device-plan.json"
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


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


def device_plan_path(snapshot_id: str) -> PurePosixPath:
    """The capture's device-plan table, relative to ``data/``:
    ``device/<capture>/device-plan.json``."""

    if (
        not isinstance(snapshot_id, str)
        or not snapshot_id
        or snapshot_id != snapshot_id.strip()
        or "/" in snapshot_id
        or "\\" in snapshot_id
        or snapshot_id in (".", "..")
    ):
        raise LeagueDirectoryError(f"A capture id names one directory; got {snapshot_id!r}.")
    return PurePosixPath(DEVICE_ROOT) / snapshot_id / DEVICE_PLAN_FILE


def device_plan_capture(device_plan: str) -> str | None:
    """The capture a directory line's ``device_plan`` names, or None where the path is
    not a per-capture table (``device/<capture>/device-plan.json``)."""

    parts = PurePosixPath(device_plan).parts
    if len(parts) == 3 and parts[0] == DEVICE_ROOT and parts[2] == DEVICE_PLAN_FILE:
        return parts[1]
    return None


def device_plan_sha256(site_data_root: Path, device_plan: str) -> str | None:
    """The sha256 of the table a directory line names, as its file's bytes, or None where
    the file is missing. A line carries it as ``device_plan_sha256``."""

    target = Path(site_data_root) / Path(*PurePosixPath(device_plan).parts)
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class PublishedLeague:
    """One line of the directory: the league, its season and deadline, and its tree."""

    league_id: int
    league_name: str
    season: str
    gameweek: int
    path: str
    #: The league's device-plan table, relative to ``data/`` (``device_plan_path``); None on
    #: a line from before the per-capture table, whose readers take the tree's own copy.
    device_plan: str | None = None
    #: The sha256 of that table's file, its version: the table at a path is replaced when
    #: its capture is published again. Present exactly when ``device_plan`` is.
    device_plan_sha256: str | None = None

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "league_id": int(self.league_id),
            "league_name": str(self.league_name),
            "season": str(self.season),
            "gameweek": int(self.gameweek),
            "path": str(self.path),
        }
        if self.device_plan is not None:
            # Not coerced: a value that is not a path is refused where the line is checked.
            record["device_plan"] = self.device_plan
        if self.device_plan_sha256 is not None:
            record["device_plan_sha256"] = self.device_plan_sha256
        return record


def _published(record: object) -> PublishedLeague:
    if not isinstance(record, dict):
        raise LeagueDirectoryError("A directory line is an object.")
    league_id, name, season, gameweek, path, device_plan, digest = (
        record.get("league_id"),
        record.get("league_name"),
        record.get("season"),
        record.get("gameweek"),
        record.get("path"),
        record.get("device_plan"),
        record.get("device_plan_sha256"),
    )
    if device_plan is not None and (
        not isinstance(device_plan, str)
        or not device_plan
        or PurePosixPath(device_plan).is_absolute()
        or ".." in PurePosixPath(device_plan).parts
    ):
        raise LeagueDirectoryError(f"A directory line names no usable device plan: {record!r}.")
    if (device_plan is None) != (digest is None) or (
        digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest))
    ):
        raise LeagueDirectoryError(
            f"A directory line names its device plan with the sha256 of its bytes: {record!r}."
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
    return PublishedLeague(league_id, name, season, gameweek, path, device_plan, digest)


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
            "say which one (--league)."
        )
    if leagues:
        return _tree_path(site_data_root, leagues[0])
    return Path(site_data_root) / LEGACY_TREE
