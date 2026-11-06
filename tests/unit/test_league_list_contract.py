"""The league list: the operator's one statement of which leagues the site serves."""

import json
from pathlib import Path
from typing import Any

import pytest

from squadopt.application.league_publication import records_advice_for
from squadopt.application.weekly_suggestion_eval import legacy_record_league
from squadopt.contracts.league_list import (
    LEAGUE_LIST_CONTRACT_VERSION,
    LEAGUE_LIST_FILE,
    LeagueListError,
    parse_league_list,
    parse_legacy_record_league,
    read_league_list,
)
from squadopt.platform.weekly_operations import read_league_menus

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "squadopt"


def _document(*ids: object) -> dict[str, Any]:
    return {
        "contract_version": LEAGUE_LIST_CONTRACT_VERSION,
        "leagues": [{"league_id": league_id} for league_id in ids],
    }


def test_the_repository_list_names_the_league_the_site_publishes() -> None:
    assert read_league_list(ROOT / LEAGUE_LIST_FILE) == (352490,)


def test_the_repository_list_marks_the_league_that_keeps_the_legacy_records() -> None:
    document = json.loads((ROOT / LEAGUE_LIST_FILE).read_text(encoding="utf-8"))
    assert parse_legacy_record_league(document) == 352490
    assert legacy_record_league(ROOT / LEAGUE_LIST_FILE) == 352490


def test_no_module_under_src_names_the_legacy_league() -> None:
    """The league list is the one place that names the league: the code reads it there.

    A league id written into the code would keep its meaning when the list changes, so every
    file under ``src/squadopt`` is read for the legacy league's number.
    """
    league = legacy_record_league(ROOT / LEAGUE_LIST_FILE)
    assert league is not None
    named = sorted(
        path.relative_to(ROOT).as_posix()
        for path in SOURCE.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and str(league).encode("ascii") in path.read_bytes()
    )
    assert named == []


@pytest.mark.parametrize(
    ("flags", "league"),
    [
        pytest.param({}, None, id="none"),
        pytest.param({0: False}, None, id="false"),
        pytest.param({1: True}, 7, id="second-line"),
        pytest.param({0: True, 1: False}, 9, id="first-line"),
    ],
)
def test_the_legacy_record_league_is_the_line_that_says_so(
    flags: dict[int, bool], league: int | None
) -> None:
    document = _document(9, 7)
    for line, flag in flags.items():
        document["leagues"][line]["legacy_advice_records"] = flag
    assert parse_legacy_record_league(document) == league
    assert parse_league_list(document) == (9, 7)


@pytest.mark.parametrize(
    ("flags", "said"),
    [
        pytest.param({0: True, 1: True}, "At most one league", id="two-lines"),
        pytest.param({0: "yes"}, "true or false", id="text"),
        pytest.param({0: 1}, "true or false", id="number"),
    ],
)
def test_a_legacy_flag_of_the_wrong_shape_is_refused(flags: dict[int, object], said: str) -> None:
    document = _document(9, 7)
    for line, flag in flags.items():
        document["leagues"][line]["legacy_advice_records"] = flag
    for parse in (parse_league_list, parse_legacy_record_league):
        with pytest.raises(LeagueListError, match=said):
            parse(document)


def test_the_recording_league_follows_the_list_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which league writes the legacy records is read from the list on every call."""

    monkeypatch.chdir(tmp_path)
    with pytest.raises(LeagueListError, match="No league list"):
        records_advice_for(352490)
    (tmp_path / "config").mkdir()
    document = _document(352490, 7)
    document["leagues"][1]["legacy_advice_records"] = True
    (tmp_path / LEAGUE_LIST_FILE).write_text(json.dumps(document), encoding="utf-8")
    assert legacy_record_league() == 7
    assert [records_advice_for(league) for league in (352490, 7)] == [False, True]
    del document["leagues"][1]["legacy_advice_records"]
    (tmp_path / LEAGUE_LIST_FILE).write_text(json.dumps(document), encoding="utf-8")
    assert legacy_record_league() is None
    assert [records_advice_for(league) for league in (352490, 7)] == [False, False]


def test_the_list_is_read_in_its_order(tmp_path: Path) -> None:
    assert parse_league_list(_document(9, 7)) == (9, 7)
    target = tmp_path / "leagues.json"
    target.write_text(json.dumps(_document(352490, 7)), encoding="utf-8")
    assert read_league_list(target) == (352490, 7)


def test_device_menus_are_opt_in_and_read_with_the_ids(tmp_path: Path) -> None:
    document = _document(352490, 755941)
    document["leagues"][1]["menu"] = "device"
    target = tmp_path / "leagues.json"
    target.write_text(json.dumps(document), encoding="utf-8")
    assert read_league_menus(target) == {352490: "full", 755941: "device"}
    document["leagues"][1]["menu"] = "typo"
    with pytest.raises(LeagueListError, match="full or device"):
        parse_league_list(document)


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
