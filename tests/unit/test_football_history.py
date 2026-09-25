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
from squadopt.data.sources.football_history import normalize_history


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
    ],
    ids=["text minutes", "text dc", "infinite xg", "negative", "no club", "130 minutes"],
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
