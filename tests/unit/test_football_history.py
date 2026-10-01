"""The football history refuses bad input in the data layer's own error classes.

``docs/data_contract.md`` says data-layer exceptions derive from ``DataError`` and are
disjoint from the solver's. These readers raised ``ValueError`` (and a renamed column a
``KeyError``), which no data-error handler catches. Each refusal is checked for its class,
for not being a ``ValueError``, and for naming what it refused.
"""

import pandas as pd
import pytest

from squadopt.data.errors import (
    DataError,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
)
from squadopt.data.sources.football_history import archive_history, normalize_history


def _history() -> pd.DataFrame:
    """Two settled player-fixture rows, the fields ``normalize_history`` reads and no more."""

    return pd.DataFrame(
        [
            {
                "season": "2026-27",
                "GW": 1,
                "fixture": 10,
                "player_code": 101,
                "position": "DEF",
                "club": 3,
                "opponent": 7,
                "home": 1.0,
                "kickoff": "2026-08-22T14:00:00Z",
                "minutes": 90,
                "goals_scored": 0,
                "assists": 1,
                "clean_sheets": 1,
                "expected_goals": 0.1,
                "expected_assists": 0.4,
                "starts": 1,
                "total_points": 9,
                "team_goals": 2,
                "team_conceded": 0,
                "defensive_contribution": 11,
            },
            {
                "season": "2026-27",
                "GW": 1,
                "fixture": 10,
                "player_code": 202,
                "position": "FWD",
                "club": 3,
                "opponent": 7,
                "home": 1.0,
                "kickoff": "2026-08-22T14:00:00Z",
                "minutes": 30,
                "goals_scored": 1,
                "assists": 0,
                "clean_sheets": 0,
                "expected_goals": 0.6,
                "expected_assists": 0.0,
                "starts": 0,
                "total_points": 5,
                "team_goals": 2,
                "team_conceded": 0,
                "defensive_contribution": 2,
            },
        ]
    )


def test_a_well_formed_history_still_normalizes() -> None:
    frame = normalize_history(_history())

    assert frame.appeared.tolist() == [1.0, 1.0]
    assert frame.dc_event.tolist() == [1.0, 0.0]


def test_a_renamed_column_is_refused_by_name() -> None:
    renamed = _history().rename(columns={"expected_goals": "xg"})

    with pytest.raises(MissingColumnsError, match="expected_goals"):
        normalize_history(renamed)


def test_two_different_rows_for_one_player_fixture_are_refused() -> None:
    history = _history()
    conflicting = pd.concat([history, history.iloc[[0]].assign(total_points=2)])

    with pytest.raises(DuplicateRecordsError, match="101"):
        normalize_history(conflicting)


@pytest.mark.parametrize(
    ("column", "value", "error", "named"),
    [
        ("minutes", "ninety", InvalidValueError, "minutes"),
        ("defensive_contribution", "many", InvalidValueError, "defensive_contribution"),
        ("expected_goals", float("inf"), InvalidValueError, "expected_goals"),
        ("assists", -1, InvalidValueError, "assists"),
        ("club", None, InvalidValueError, "club"),
        ("minutes", 130, InvalidValueError, "101"),
        ("kickoff", "not a date", InvalidValueError, "kickoff"),
        ("kickoff", "2026-13-45T14:00:00Z", InvalidValueError, "kickoff"),
        ("kickoff", 12345678901234567890, InvalidValueError, "kickoff"),
        ("club", [3], InvalidValueError, "club"),
    ],
    ids=[
        "text minutes",
        "text dc",
        "infinite xg",
        "negative",
        "no club",
        "130 minutes",
        "text kickoff",
        "impossible kickoff",
        "out of range kickoff",
        "unhashable club",
    ],
)
def test_a_bad_value_is_a_data_error_that_names_it(
    column: str, value: object, error: type[DataError], named: str
) -> None:
    history = _history()
    values: list[object] = history[column].tolist()
    values[0] = value
    history[column] = pd.Series(values, index=history.index, dtype=object)

    with pytest.raises(error, match=named) as raised:
        normalize_history(history)

    assert not isinstance(raised.value, ValueError)


def test_a_short_appearance_with_a_clean_sheet_is_refused_by_player() -> None:
    history = _history()
    history.loc[1, "clean_sheets"] = 1

    with pytest.raises(InvalidValueError, match="202"):
        normalize_history(history)


@pytest.mark.parametrize(
    "seasons", [(), "2024-25", ("2024-25", "2024-25"), ("2024-25", "2099-00"), (None,)]
)
def test_archive_allowlist_is_validated_entirely_before_access(tmp_path, monkeypatch, seasons):
    reads = []
    monkeypatch.setattr(pd, "read_csv", lambda *a, **kw: reads.append(a))
    with pytest.raises(InvalidValueError, match="Archive seasons"):
        archive_history(tmp_path, seasons=seasons)
    assert reads == []


def test_archive_reader_never_opens_an_excluded_season(tmp_path, monkeypatch):
    reads = []
    raw = _history().assign(element=[1, 2], was_home=True, team_h_score=2, team_a_score=0)
    raw["kickoff_time"] = raw.kickoff
    files = {
        "merged_gw.csv": raw,
        "players_raw.csv": pd.DataFrame({"id": [1, 2], "code": [101, 202]}),
        "teams.csv": pd.DataFrame({"id": [11, 22], "code": [3, 7]}),
        "fixtures.csv": pd.DataFrame({"id": [10], "team_h": [11], "team_a": [22]}),
    }

    def read(path, **kwargs):
        reads.append(path)
        return files[path.name].copy()

    monkeypatch.setattr(pd, "read_csv", read)
    history = archive_history(tmp_path, seasons=("2024-25",))
    assert len(reads) == 4
    assert all("2024-25" in path.parts for path in reads)
    assert history.season.eq("2024-25").all()
    assert history.player_code.tolist() == [101, 202]
