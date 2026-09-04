"""Tests for reconciling a captured roster against identities already on record."""

import pandas as pd
import pytest

from squadopt.data.errors import InvalidValueError
from squadopt.data.identity import reconcile_player_identity


def _captured(*player_ids: int) -> pd.DataFrame:
    return pd.DataFrame({"player_id": list(player_ids), "name": ["x"] * len(player_ids)})


# --- reconciliation ---------------------------------------------------------


def test_a_fully_known_roster_reports_no_new_players() -> None:
    report = reconcile_player_identity(_captured(1, 2, 3), [1, 2, 3, 4])

    assert (report.captured_players, report.known_players, report.new_players) == (3, 3, 0)
    assert report.new_player_ids == ()


def test_new_players_are_reported_in_full_and_sorted() -> None:
    """These are the players a projection has to cold-start, so they are named."""

    report = reconcile_player_identity(_captured(3, 99, 1, 50), [1, 2, 3])

    assert report.new_player_ids == (50, 99)
    assert report.new_players == 2
    assert report.known_players == 2


def test_a_new_season_roster_of_mostly_newcomers_is_not_an_error() -> None:
    """An opening gameweek genuinely carries a large minority of debutants."""

    report = reconcile_player_identity(_captured(1, 10, 11, 12, 13), [1, 2])

    assert report.new_players == 4
    assert report.known_fraction == pytest.approx(0.2)


def test_known_fraction_reports_how_much_history_is_available() -> None:
    report = reconcile_player_identity(_captured(1, 2, 3, 4), [1, 2, 9])

    assert report.known_fraction == pytest.approx(0.5)


def test_duplicate_captured_identifiers_are_counted_once() -> None:
    report = reconcile_player_identity(_captured(1, 1, 2), [1, 2])

    assert report.captured_players == 2


def test_the_report_is_immutable() -> None:
    report = reconcile_player_identity(_captured(1), [1])

    with pytest.raises(AttributeError):
        report.new_players = 5  # type: ignore[misc]


# --- the failure this check exists for --------------------------------------


def test_a_total_mismatch_is_reported_as_a_keying_error() -> None:
    """Element ids on one side and persistent codes on the other match nothing."""

    with pytest.raises(InvalidValueError, match="different identifier spaces"):
        reconcile_player_identity(_captured(1, 2, 3), [118748, 154043, 209289])


def test_the_mismatch_message_shows_both_sides() -> None:
    with pytest.raises(InvalidValueError, match="118748"):
        reconcile_player_identity(_captured(1), [118748])


# --- input validation -------------------------------------------------------


def test_a_missing_player_id_column_names_what_was_there() -> None:
    with pytest.raises(InvalidValueError, match="missing column 'player_id'"):
        reconcile_player_identity(pd.DataFrame({"code": [1]}), [1])


def test_an_empty_roster_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="no rows to reconcile"):
        reconcile_player_identity(_captured(), [1])


def test_an_empty_history_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="No known player identifiers"):
        reconcile_player_identity(_captured(1), [])


def test_a_non_frame_roster_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="must be a pandas DataFrame"):
        reconcile_player_identity([1, 2], [1])  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["118748", 118748.0, None, True])
def test_non_integer_identifiers_are_rejected_rather_than_coerced(value: object) -> None:
    """Coercing would let a text identifier silently fail to match every integer."""

    with pytest.raises(InvalidValueError, match="must be integers"):
        reconcile_player_identity(_captured(1), [value])


def test_a_non_integer_captured_identifier_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="must be integers"):
        reconcile_player_identity(pd.DataFrame({"player_id": ["118748"]}), [118748])


def test_numpy_integers_from_a_panel_are_accepted() -> None:
    """The archive panel yields numpy integers, which are still integers."""

    known = pd.Series([1, 2, 3], dtype="int64").tolist()

    report = reconcile_player_identity(_captured(1, 2), known)

    assert report.known_players == 2
