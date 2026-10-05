"""The league tree contract: where a league's tree is, and the directory of leagues."""

import json
from pathlib import Path

import pytest

from squadopt.application.league_publication import adopt_legacy_tree
from squadopt.contracts.league_tree import (
    LEAGUE_DIRECTORY_FILE,
    LEGACY_TREE,
    LeagueDirectoryError,
    PublishedLeague,
    find_league_tree,
    league_tree,
    league_tree_dir,
    legacy_tree_league_id,
    published_league_trees,
    read_league_directory,
    single_league_tree,
    write_league_directory,
)


def _league(league_id: int, **changes: object) -> PublishedLeague:
    record = {
        "league_id": league_id,
        "league_name": f"League {league_id}",
        "season": "2026-27",
        "gameweek": 7,
        "path": league_tree(league_id).as_posix(),
    }
    record.update(changes)
    return PublishedLeague(**record)  # type: ignore[arg-type]


def _legacy(root: Path, league_id: int | None) -> Path:
    tree = root / LEGACY_TREE
    tree.mkdir(parents=True)
    payload = {} if league_id is None else {"league_id": league_id}
    (tree / "members.json").write_text(json.dumps({"payload": payload}), encoding="utf-8")
    return tree


def test_a_league_tree_is_its_id_under_leagues() -> None:
    assert league_tree(352490).as_posix() == "leagues/352490"
    assert league_tree_dir(Path("site/data"), 7) == Path("site/data/leagues/7")
    for bad in (0, -1, True, "7"):
        with pytest.raises(LeagueDirectoryError):
            league_tree(bad)  # type: ignore[arg-type]


def test_the_directory_is_written_whole_and_read_back(tmp_path: Path) -> None:
    write_league_directory(
        tmp_path, [_league(9), _league(7)], generated_at_utc="2026-10-04T10:00:00Z"
    )
    document = json.loads((tmp_path / LEAGUE_DIRECTORY_FILE).read_text(encoding="utf-8"))
    assert document["contract_version"] == "league_directory_v1"
    assert document["generated_at_utc"] == "2026-10-04T10:00:00Z"
    assert [row["league_id"] for row in document["payload"]["leagues"]] == [7, 9]
    assert read_league_directory(tmp_path) == [_league(7), _league(9)]
    # Written whole: a league the next publication did not render is not listed.
    write_league_directory(tmp_path, [_league(9)], generated_at_utc="2026-10-11T10:00:00Z")
    assert [row.league_id for row in read_league_directory(tmp_path)] == [9]


@pytest.mark.parametrize(
    "leagues",
    [
        pytest.param([], id="no-league"),
        pytest.param([_league(7), _league(7)], id="a-league-twice"),
        pytest.param([_league(7), _league(9, path="leagues/7")], id="two-leagues-one-tree"),
        pytest.param([_league(7, league_name="")], id="no-name"),
        pytest.param([_league(7, gameweek=0)], id="no-week"),
        pytest.param([_league(7, path="../elsewhere")], id="path-outside"),
    ],
)
def test_a_directory_no_reader_accepts_is_not_written(
    tmp_path: Path, leagues: list[PublishedLeague]
) -> None:
    with pytest.raises(LeagueDirectoryError):
        write_league_directory(tmp_path, leagues, generated_at_utc="2026-10-04T10:00:00Z")
    assert not (tmp_path / LEAGUE_DIRECTORY_FILE).exists()


def test_a_directory_of_the_wrong_shape_is_refused_on_read(tmp_path: Path) -> None:
    assert read_league_directory(tmp_path) == []
    (tmp_path / LEAGUE_DIRECTORY_FILE).write_text('{"payload": {"leagues": []}}', encoding="utf-8")
    with pytest.raises(LeagueDirectoryError):
        read_league_directory(tmp_path)


def test_a_site_without_a_directory_is_read_as_the_legacy_tree(tmp_path: Path) -> None:
    assert find_league_tree(tmp_path, 352490) == tmp_path / LEGACY_TREE
    assert published_league_trees(tmp_path) == [tmp_path / LEGACY_TREE]
    assert single_league_tree(tmp_path) == tmp_path / LEGACY_TREE
    assert legacy_tree_league_id(tmp_path) is None
    _legacy(tmp_path, 352490)
    assert legacy_tree_league_id(tmp_path) == 352490


def test_a_directory_says_which_leagues_the_site_publishes(tmp_path: Path) -> None:
    write_league_directory(tmp_path, [_league(7), _league(9)], generated_at_utc="x")
    assert find_league_tree(tmp_path, 7) == tmp_path / "leagues" / "7"
    # A league the directory does not list is not published, legacy tree or not.
    _legacy(tmp_path, 352490)
    assert find_league_tree(tmp_path, 352490) is None
    with pytest.raises(LeagueDirectoryError, match="does not publish league 352490"):
        single_league_tree(tmp_path, 352490)
    with pytest.raises(LeagueDirectoryError, match="lists 2 leagues"):
        single_league_tree(tmp_path)
    assert published_league_trees(tmp_path) == [
        tmp_path / "leagues" / "7",
        tmp_path / "leagues" / "9",
    ]


def test_the_legacy_tree_is_adopted_once_and_refused_when_it_is_not_the_leagues(
    tmp_path: Path,
) -> None:
    assert adopt_legacy_tree(tmp_path, 352490) is None
    legacy = _legacy(tmp_path, 352490)
    (legacy / "history").mkdir()
    (legacy / "history" / "101.json").write_text("{}", encoding="utf-8")
    assert adopt_legacy_tree(tmp_path, 352490) == ("adopted", tmp_path / "leagues" / "352490")
    assert not legacy.exists()
    assert (tmp_path / "leagues" / "352490" / "history" / "101.json").is_file()
    assert adopt_legacy_tree(tmp_path, 352490) is None

    # Another league's tree, or one that names no league, cannot be adopted.
    other = tmp_path / "other"
    _legacy(other, 7)
    with pytest.raises(LeagueDirectoryError, match="names league 7, not league 352490"):
        adopt_legacy_tree(other, 352490)
    unnamed = tmp_path / "unnamed"
    _legacy(unnamed, None)
    with pytest.raises(LeagueDirectoryError, match="names league None"):
        adopt_legacy_tree(unnamed, 352490)

    # Beside a directory, a legacy tree is a leftover nothing lists.
    write_league_directory(tmp_path, [_league(352490)], generated_at_utc="x")
    leftover = _legacy(tmp_path, 352490)
    assert adopt_legacy_tree(tmp_path, 352490) == ("removed", leftover)
    assert not leftover.exists()
