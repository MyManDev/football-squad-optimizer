"""Official captured ranks are evidence of responsibility, not goal frequency."""

import json

import pandas as pd
import pytest

from squadopt.data.errors import (
    DataError,
    DataValidationError,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
)
from squadopt.data.sources.fpl_set_pieces import TAKER_FIELDS, captured_taker_priorities


def _element(code: object, **ranks: object) -> dict[str, object]:
    """One bootstrap element as FPL publishes it: every taker field present, null when unranked."""

    return {"id": code, "code": code, **dict.fromkeys(TAKER_FIELDS), **ranks}


def _bootstrap(*elements: dict[str, object]) -> bytes:
    return json.dumps({"elements": list(elements)}).encode()


def test_capture_uses_stable_code_and_preserves_unknown_and_ties() -> None:
    payload = _bootstrap(
        _element(101, penalties_order=1),
        _element(102, penalties_order=1, corners_and_indirect_freekicks_order=2),
    )
    table = captured_taker_priorities(payload).set_index("player_id")
    assert list(table.index) == [101, 102]
    assert table.penalties_order.tolist() == [1, 1]
    assert table.direct_freekicks_order.isna().all()
    assert pd.isna(table.loc[101, "corners_and_indirect_freekicks_order"])
    assert table.loc[102, "corners_and_indirect_freekicks_order"] == 2


@pytest.mark.parametrize("rank", [True, False, 0, -1, 1.5, "1"])
def test_invalid_ranks_are_not_silently_coerced(rank: object) -> None:
    with pytest.raises(InvalidValueError, match="integer ranks"):
        captured_taker_priorities(_bootstrap(_element(101, penalties_order=rank)))


def test_duplicate_stable_codes_are_rejected() -> None:
    with pytest.raises(DuplicateRecordsError, match="101"):
        captured_taker_priorities(_bootstrap(_element(101), _element(101)))


# --- a renamed field is refused, not read as every rank unknown ---------------


def test_a_renamed_taker_field_is_refused_rather_than_read_as_all_null() -> None:
    """The silent case: `.get` read a renamed key as null for every player.

    Two players hold the penalties under the new name. Read with `.get`, the table said
    nobody takes a penalty, and the football model lost every penalty-taker signal.
    """

    renamed = []
    for element in (_element(101), _element(102)):
        element["penalty_order"] = element.pop("penalties_order")
        renamed.append(element)
    renamed[0]["penalty_order"] = 1

    with pytest.raises(MissingColumnsError, match="'penalties_order'") as raised:
        captured_taker_priorities(_bootstrap(*renamed))

    assert "101" in str(raised.value)
    assert "102" in str(raised.value)


@pytest.mark.parametrize("field", TAKER_FIELDS)
def test_one_element_without_a_taker_field_is_refused(field: str) -> None:
    partial = _element(102)
    del partial[field]

    with pytest.raises(MissingColumnsError, match=field):
        captured_taker_priorities(_bootstrap(_element(101), partial))


def test_an_explicit_null_is_a_published_unknown_and_is_kept() -> None:
    """Absent and null are different statements; only the second is FPL's "no rank"."""

    table = captured_taker_priorities(_bootstrap(_element(101)))

    assert table[list(TAKER_FIELDS)].isna().all().all()


def test_an_element_without_a_code_is_refused() -> None:
    element = _element(101)
    del element["code"]

    with pytest.raises(MissingColumnsError, match="code"):
        captured_taker_priorities(_bootstrap(element))


@pytest.mark.parametrize("code", [0, -3, True, "101", None])
def test_an_unusable_player_code_is_refused(code: object) -> None:
    with pytest.raises(InvalidValueError, match="stable player code"):
        captured_taker_priorities(_bootstrap(_element(code)))


def test_an_empty_roster_is_refused() -> None:
    with pytest.raises(DataValidationError, match="nonempty"):
        captured_taker_priorities(_bootstrap())


# --- the data error contract --------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        _bootstrap(_element(101, penalties_order=0)),
        _bootstrap(_element(101), _element(101)),
        _bootstrap({"id": 1, "code": 101}),
        _bootstrap(),
    ],
    ids=["bad rank", "duplicate", "absent fields", "empty"],
)
def test_every_refusal_is_a_data_error_and_not_a_value_error(payload: bytes) -> None:
    """`docs/data_contract.md`: data-layer exceptions derive from DataError."""

    with pytest.raises(DataError) as raised:
        captured_taker_priorities(payload)

    assert not isinstance(raised.value, ValueError)
