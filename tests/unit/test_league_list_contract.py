"""The league list: the operator's one statement of which leagues the site serves."""

import json
from pathlib import Path

import pytest

from squadopt.contracts.league_list import (
    LEAGUE_LIST_CONTRACT_VERSION,
    LEAGUE_LIST_FILE,
    LeagueListError,
    parse_league_list,
    read_league_list,
)

ROOT = Path(__file__).resolve().parents[2]


def _document(*ids: object) -> dict[str, object]:
    return {
        "contract_version": LEAGUE_LIST_CONTRACT_VERSION,
        "leagues": [{"league_id": league_id} for league_id in ids],
    }


def test_the_repository_list_names_the_league_the_site_publishes() -> None:
    assert read_league_list(ROOT / LEAGUE_LIST_FILE) == (352490,)


def test_the_list_is_read_in_its_order(tmp_path: Path) -> None:
    assert parse_league_list(_document(9, 7)) == (9, 7)
    target = tmp_path / "leagues.json"
    target.write_text(json.dumps(_document(352490, 7)), encoding="utf-8")
    assert read_league_list(target) == (352490, 7)


@pytest.mark.parametrize(
    "document",
    [
        pytest.param({"leagues": [{"league_id": 7}]}, id="no-contract"),
        pytest.param(_document(), id="no-league"),
        pytest.param(_document(7, 7), id="a-league-twice"),
        pytest.param(_document(0), id="zero"),
        pytest.param(_document("7"), id="text"),
        pytest.param(_document(True), id="bool"),
        pytest.param({"contract_version": LEAGUE_LIST_CONTRACT_VERSION, "leagues": [7]}, id="bare"),
    ],
)
def test_a_list_of_the_wrong_shape_is_refused(document: object) -> None:
    with pytest.raises(LeagueListError):
        parse_league_list(document)


def test_a_missing_or_broken_file_names_the_problem(tmp_path: Path) -> None:
    with pytest.raises(LeagueListError, match="No league list"):
        read_league_list(tmp_path / "leagues.json")
    (tmp_path / "leagues.json").write_text("{", encoding="utf-8")
    with pytest.raises(LeagueListError, match="does not parse"):
        read_league_list(tmp_path / "leagues.json")
