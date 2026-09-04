"""Tests for the per-gameweek opponent signal.

The signal is an input a declared candidate would read, so the two things worth testing are
the ones a declaration would rest on: that it cannot see the gameweek it describes, and that
its coverage is accounted for rather than assumed. A declared input that is silently missing
on a scorable row drops that row down the rate ladder, which is the failure this file exists
to make impossible to introduce quietly.

The match frame is borrowed from the rating's own tests rather than rebuilt, for the same
reason every other borrowed fixture in this suite is: two copies drift.
"""

from functools import lru_cache

import pandas as pd
import pytest
from scripts.build_opponent_signal import (
    OPPONENT_SIGNAL_CONTRACT_VERSION,
    SIGNAL_COLUMNS,
    build_opponent_signal,
    signal_fingerprint,
    signal_markdown,
    signal_record,
)
from tests.unit.test_team_rating import _matches

from squadopt.experiments.config import ExperimentConfigurationError

SEASONS = ("2021-22", "2022-23", "2023-24")


@lru_cache(maxsize=1)
def _cached() -> tuple[pd.DataFrame, object]:
    """Fit once for the whole module.

    Every clean-signal assertion below reads the same table, and a rating refit per gameweek
    is seconds rather than milliseconds. Twelve independent builds would put a minute on the
    suite to re-derive one answer.
    """

    return build_opponent_signal(_matches(), SEASONS)


def _signal() -> tuple[pd.DataFrame, object]:
    table, coverage = _cached()
    return table.copy(deep=True), coverage


# --- it cannot see the gameweek it describes ---------------------------------


@pytest.mark.slow
def test_the_signal_reads_nothing_from_the_gameweek_it_describes() -> None:
    """A mutation test, not an argument.

    Every match from the second season onwards is rewritten to a 9-0 rout. The first
    season's signal must not move: its ratings were fitted at instants that precede every
    poisoned kickoff.
    """

    clean, _ = _signal()

    poisoned = _matches()
    cut = poisoned.loc[poisoned["season"] == "2022-23", "kickoff"].min()
    later = poisoned["kickoff"] >= cut
    poisoned.loc[later, "home_goals"] = 9
    poisoned.loc[later, "away_goals"] = 0
    dirty, _ = build_opponent_signal(poisoned, SEASONS)

    first = clean.loc[clean["season"] == "2021-22"].reset_index(drop=True)
    also_first = dirty.loc[dirty["season"] == "2021-22"].reset_index(drop=True)

    pd.testing.assert_frame_equal(first, also_first)


def test_altering_history_does_change_the_signal() -> None:
    """The converse: without it the test above would pass on a signal that reads nothing."""

    clean, _ = _signal()

    altered = _matches()
    first_season = altered["season"] == "2021-22"
    altered.loc[first_season, "home_goals"] = 7

    dirty, _ = build_opponent_signal(altered, SEASONS)

    later_clean = clean.loc[clean["season"] == "2022-23"].reset_index(drop=True)
    later_dirty = dirty.loc[dirty["season"] == "2022-23"].reset_index(drop=True)
    assert not later_clean["rating_attacking_signal"].equals(later_dirty["rating_attacking_signal"])


# --- coverage is counted, not assumed ----------------------------------------


def test_every_uncovered_cell_is_an_opening_gameweek() -> None:
    """The only honest gap: a rating needs a match before it can rate anybody."""

    _, coverage = _signal()

    assert coverage.unsignalled == coverage.first_gameweek_cells  # type: ignore[attr-defined]
    assert coverage.signalled > 0  # type: ignore[attr-defined]


def test_the_earliest_season_is_the_one_without_selected_controls() -> None:
    """It has no earlier season to choose on, and no fold is judged in it."""

    _, coverage = _signal()

    assert coverage.seasons_on_default_config == ("2021-22",)  # type: ignore[attr-defined]


def test_a_later_season_starts_at_its_own_first_gameweek() -> None:
    """The previous season is history, so a second season's opener is rateable."""

    table, _ = _signal()

    assert int(table.loc[table["season"] == "2022-23", "gameweek"].min()) == 1


# --- the shape a consumer joins on -------------------------------------------


def test_the_grain_is_one_row_per_club_gameweek() -> None:
    table, _ = _signal()

    assert not table.duplicated(subset=["season", "gameweek", "club"]).any()
    assert tuple(table.columns) == SIGNAL_COLUMNS


def test_no_signal_is_missing_on_a_row_that_exists() -> None:
    """Absent rows are the contract; a present row with a null signal would not be."""

    table, _ = _signal()

    assert bool(table["rating_attacking_signal"].notna().all())
    assert bool(table["rating_defensive_signal"].notna().all())


def test_the_fixture_count_states_what_the_average_was_taken_over() -> None:
    """Every fixture gives one side to each of two clubs, so each gameweek's total is even."""

    table, _ = _signal()

    assert int(table["fixtures_in_gameweek"].min()) >= 1
    totals = table.groupby(["season", "gameweek"])["fixtures_in_gameweek"].sum()
    assert (totals % 2 == 0).all()


# --- the record -------------------------------------------------------------


def test_the_record_states_its_coverage_and_claims_nothing_else() -> None:
    table, coverage = _signal()

    record = signal_record(table, coverage, SEASONS)  # type: ignore[arg-type]

    assert record["contract_version"] == OPPONENT_SIGNAL_CONTRACT_VERSION
    assert record["gate_evidence"] is False
    assert record["measurement_only"] is True
    assert record["locked_holdout_accessed"] is False
    assert record["club_gameweeks_signalled"] == len(table)


def test_the_summary_names_the_gap_as_a_property_when_it_is_one() -> None:
    table, coverage = _signal()

    text = signal_markdown(signal_record(table, coverage, SEASONS))  # type: ignore[arg-type]

    assert "Every uncovered cell is an opening gameweek" in text
    assert "decides nothing on its own" in text


def test_the_summary_calls_an_unexplained_gap_a_defect() -> None:
    """The sentence that matters is the one printed when the numbers disagree."""

    table, coverage = _signal()
    record = signal_record(table, coverage, SEASONS)  # type: ignore[arg-type]
    record["club_gameweeks_without_a_signal"] = int(str(record["opening_gameweek_cells"])) + 5

    text = signal_markdown(record)

    assert "is a defect rather than a property" in text
    assert "must not be declared against this file" in text


def test_the_locked_holdout_cannot_be_requested() -> None:
    """Refused by this function, not only by the loader it usually arrives through."""

    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        build_opponent_signal(_matches(), ("2024-25", "2025-26"))


# --- the fingerprint a declaration binds its input to ------------------------


def test_the_same_frame_fingerprints_the_same_way() -> None:
    """A declaration that bound a value which moved between runs would bind nothing."""

    first, _ = _signal()
    second, _ = _signal()

    assert signal_fingerprint(first) == signal_fingerprint(second)


def test_row_order_does_not_change_the_fingerprint() -> None:
    """A frame differing only in row order is the same input and must read as one."""

    table, _ = _signal()
    shuffled = table.sample(frac=1.0, random_state=7).reset_index(drop=True)

    assert signal_fingerprint(shuffled) == signal_fingerprint(table)


def test_a_changed_signal_changes_the_fingerprint() -> None:
    """The converse: without it the two tests above would pass on a constant."""

    table, _ = _signal()
    altered = table.copy(deep=True)
    altered.loc[0, "rating_attacking_signal"] = float(altered.loc[0, "rating_attacking_signal"]) + 1

    assert signal_fingerprint(altered) != signal_fingerprint(table)


def test_a_changed_fixture_count_changes_the_fingerprint() -> None:
    """Every column here is part of the input, so none may move without moving the digest."""

    table, _ = _signal()
    altered = table.copy(deep=True)
    altered.loc[0, "fixtures_in_gameweek"] = int(altered.loc[0, "fixtures_in_gameweek"]) + 1

    assert signal_fingerprint(altered) != signal_fingerprint(table)


def test_the_record_carries_the_fingerprint() -> None:
    """A declaration reads it from the record, so it has to be in the record."""

    table, coverage = _signal()

    record = signal_record(table, coverage, SEASONS)  # type: ignore[arg-type]

    assert record["frame_fingerprint"] == signal_fingerprint(table)
    assert len(str(record["frame_fingerprint"])) == 64


def test_the_summary_shows_the_fingerprint() -> None:
    table, coverage = _signal()

    text = signal_markdown(signal_record(table, coverage, SEASONS))  # type: ignore[arg-type]

    assert signal_fingerprint(table) in text
