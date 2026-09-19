"""The chip threshold by backward induction: kinds, samples, the recursion, the hold-out.

Synthetic samples only. No chain is walked and no record is read from disk: the point is
the arithmetic, and every expected number below is derived by hand in a comment.
"""

from itertools import pairwise

import pandas as pd
import pytest

from squadopt.experiments.chip_threshold import (
    BLANK_GAMEWEEK,
    CHIP_VALUE_FIELDS,
    DOUBLE_GAMEWEEK,
    GAMEWEEK_KINDS,
    SINGLE_GAMEWEEK,
    classify_gameweek_kinds,
    exercise_values_by_kind,
    induction_thresholds,
    leave_one_season_out_thresholds,
    window_thresholds,
)
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.season_chain import ChipWindowRule

SENTINEL = 1000.0


def _fixture_counts(rows: list[tuple[int, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["gameweek", "team_id", "fixture_count"])


def _week(
    gameweek: int,
    *,
    captain: float | None,
    bench: float | None,
    captain_realized: float = 0.0,
    bench_realized: float = 0.0,
) -> dict[str, object]:
    return {
        "gameweek": gameweek,
        "captain_projected_points": captain,
        "bench_projected_points": bench,
        "captain_realized_points": captain_realized,
        "bench_realized_points": bench_realized,
    }


# --- kinds -----------------------------------------------------------------------------


def test_kinds_of_a_small_season_including_a_week_that_is_both_blank_and_double() -> None:
    counts = _fixture_counts(
        [
            # Gameweek 1: every club once.
            (1, "A", 1),
            (1, "B", 1),
            (1, "C", 1),
            (1, "D", 1),
            # Gameweek 2: A doubles.
            (2, "A", 2),
            (2, "B", 1),
            (2, "C", 1),
            (2, "D", 1),
            # Gameweek 3: A has no row, which is how a counted table writes a blank.
            (3, "B", 1),
            (3, "C", 1),
            (3, "D", 1),
            # Gameweek 4: A doubles and B is blank. The double takes precedence.
            (4, "A", 2),
            (4, "C", 1),
            (4, "D", 1),
            # Gameweek 5: an explicit zero reads the same as a missing row.
            (5, "A", 1),
            (5, "B", 1),
            (5, "C", 0),
            (5, "D", 1),
        ]
    )

    assert classify_gameweek_kinds(counts) == {
        1: SINGLE_GAMEWEEK,
        2: DOUBLE_GAMEWEEK,
        3: BLANK_GAMEWEEK,
        4: DOUBLE_GAMEWEEK,
        5: BLANK_GAMEWEEK,
    }


def test_a_named_gameweek_nobody_plays_in_is_blank() -> None:
    counts = _fixture_counts([(1, "A", 1), (1, "B", 1)])

    assert classify_gameweek_kinds(counts, gameweeks=[1, 2]) == {
        1: SINGLE_GAMEWEEK,
        2: BLANK_GAMEWEEK,
    }


def test_kinds_refuse_a_table_that_is_not_a_count_table() -> None:
    with pytest.raises(ExperimentExecutionError, match="missing required columns"):
        classify_gameweek_kinds(pd.DataFrame({"gameweek": [1], "team_id": ["A"]}))
    with pytest.raises(ExperimentExecutionError, match="two rows"):
        classify_gameweek_kinds(_fixture_counts([(1, "A", 1), (1, "A", 1)]))
    with pytest.raises(ExperimentExecutionError, match="not a count"):
        classify_gameweek_kinds(_fixture_counts([(1, "A", -1)]))
    with pytest.raises(ExperimentExecutionError, match="no row"):
        classify_gameweek_kinds(_fixture_counts([]))


# --- samples ---------------------------------------------------------------------------


def test_values_are_grouped_by_chip_and_kind_and_none_is_skipped() -> None:
    kinds = {1: SINGLE_GAMEWEEK, 2: DOUBLE_GAMEWEEK, 3: SINGLE_GAMEWEEK, 4: BLANK_GAMEWEEK}
    weeks = [
        _week(1, captain=6.0, bench=5.0),
        _week(2, captain=13.0, bench=11.0),
        _week(3, captain=None, bench=4.0),
        _week(4, captain=7.0, bench=None),
    ]

    values = exercise_values_by_kind(weeks, kinds)

    assert set(values) == set(CHIP_VALUE_FIELDS)
    assert values["3xc"] == {
        SINGLE_GAMEWEEK: (6.0,),
        DOUBLE_GAMEWEEK: (13.0,),
        BLANK_GAMEWEEK: (7.0,),
    }
    assert values["bboost"] == {
        SINGLE_GAMEWEEK: (5.0, 4.0),
        DOUBLE_GAMEWEEK: (11.0,),
        BLANK_GAMEWEEK: (),
    }


def test_the_realized_columns_are_never_read() -> None:
    weeks = [_week(1, captain=5.0, bench=3.0, captain_realized=SENTINEL, bench_realized=SENTINEL)]

    values = exercise_values_by_kind(weeks, {1: SINGLE_GAMEWEEK})

    assert values["3xc"][SINGLE_GAMEWEEK] == (5.0,)
    assert values["bboost"][SINGLE_GAMEWEEK] == (3.0,)


def test_a_record_without_the_projected_columns_yields_empty_samples() -> None:
    values = exercise_values_by_kind(
        [{"gameweek": 1, "captain_realized_points": 9.0}], {1: "single"}
    )

    assert all(sample == () for by_kind in values.values() for sample in by_kind.values())


def test_values_refuse_an_unclassified_gameweek_and_a_value_that_is_not_a_number() -> None:
    with pytest.raises(ExperimentExecutionError, match="no kind"):
        exercise_values_by_kind([_week(9, captain=1.0, bench=1.0)], {1: SINGLE_GAMEWEEK})
    with pytest.raises(ExperimentExecutionError, match="not finite"):
        exercise_values_by_kind([_week(1, captain=float("nan"), bench=1.0)], {1: SINGLE_GAMEWEEK})
    with pytest.raises(ExperimentExecutionError, match="not a number"):
        exercise_values_by_kind(
            [{"gameweek": 1, "captain_projected_points": "6"}], {1: SINGLE_GAMEWEEK}
        )
    with pytest.raises(ExperimentConfigurationError, match="kind must be one of"):
        exercise_values_by_kind([_week(1, captain=1.0, bench=1.0)], {1: "triple"})


# --- the recursion ---------------------------------------------------------------------


def test_three_gameweeks_by_hand() -> None:
    # The window's remaining gameweeks are single, single, double.
    # Samples: single {2, 10}, double {4, 12}.
    #
    #   tau_3 = 0                                      the window's last gameweek
    #   tau_2 = mean over the double sample of max(g, tau_3)
    #         = (max(4, 0) + max(12, 0)) / 2 = 16 / 2 = 8
    #   tau_1 = mean over the single sample of max(g, tau_2)
    #         = (max(2, 8) + max(10, 8)) / 2 = 18 / 2 = 9
    #
    # The kind of gameweek 1 is never averaged over: its own value is known when decided.
    result = induction_thresholds(
        [SINGLE_GAMEWEEK, SINGLE_GAMEWEEK, DOUBLE_GAMEWEEK],
        {SINGLE_GAMEWEEK: [2.0, 10.0], DOUBLE_GAMEWEEK: [4.0, 12.0]},
    )

    assert result.thresholds == (9.0, 8.0, 0.0)
    assert result.pooled_fallback_kinds == ()


def test_a_double_ahead_raises_the_threshold_before_it() -> None:
    values = {SINGLE_GAMEWEEK: [2.0, 4.0], DOUBLE_GAMEWEEK: [8.0, 12.0]}
    # Four plain gameweeks: tau_4 = 0, tau_3 = (2 + 4) / 2 = 3,
    # tau_2 = (max(2, 3) + max(4, 3)) / 2 = 3.5, tau_1 = (3.5 + 4) / 2 = 3.75.
    plain = induction_thresholds([SINGLE_GAMEWEEK] * 4, values)
    # The third is a double: tau_4 = 0, tau_3 = 3 (a single follows),
    # tau_2 = (max(8, 3) + max(12, 3)) / 2 = 10, tau_1 = (max(2, 10) + max(4, 10)) / 2 = 10.
    with_double = induction_thresholds(
        [SINGLE_GAMEWEEK, SINGLE_GAMEWEEK, DOUBLE_GAMEWEEK, SINGLE_GAMEWEEK], values
    )

    assert plain.thresholds == (3.75, 3.5, 3.0, 0.0)
    assert with_double.thresholds == (10.0, 10.0, 3.0, 0.0)
    # Before the double the wait is worth more; from the double on, the same.
    assert with_double.thresholds[0] > plain.thresholds[0]
    assert with_double.thresholds[1] > plain.thresholds[1]
    assert with_double.thresholds[2:] == plain.thresholds[2:]


def test_thresholds_are_never_negative_never_rise_and_end_at_zero() -> None:
    kinds = [SINGLE_GAMEWEEK, BLANK_GAMEWEEK, DOUBLE_GAMEWEEK, SINGLE_GAMEWEEK, BLANK_GAMEWEEK]
    # A sample with negative values: a projection can be below zero, a threshold cannot.
    values = {
        SINGLE_GAMEWEEK: [-3.0, -1.0, 2.0],
        DOUBLE_GAMEWEEK: [-2.0, 5.0],
        BLANK_GAMEWEEK: [-4.0, -4.0],
    }

    thresholds = induction_thresholds(kinds, values).thresholds

    assert thresholds[-1] == 0.0
    assert all(threshold >= 0.0 for threshold in thresholds)
    assert all(earlier >= later for earlier, later in pairwise(thresholds))


def test_a_window_of_one_gameweek_has_a_zero_threshold() -> None:
    result = induction_thresholds([DOUBLE_GAMEWEEK], {SINGLE_GAMEWEEK: [5.0]})

    assert result.thresholds == (0.0,)
    assert result.pooled_fallback_kinds == ()


def test_a_kind_without_a_sample_falls_back_to_the_pooled_sample_and_says_so() -> None:
    # No blank was ever sampled. Pooled sample: {2, 10, 4, 12}.
    #   tau_3 = 0
    #   tau_2 = pooled mean of max(g, 0) = (2 + 10 + 4 + 12) / 4 = 7      (blank: fallback)
    #   tau_1 = mean over the double sample of max(g, 7) = (7 + 12) / 2 = 9.5
    result = induction_thresholds(
        [SINGLE_GAMEWEEK, DOUBLE_GAMEWEEK, BLANK_GAMEWEEK],
        {SINGLE_GAMEWEEK: [2.0, 10.0], DOUBLE_GAMEWEEK: [4.0, 12.0], BLANK_GAMEWEEK: []},
    )

    assert result.thresholds == (9.5, 7.0, 0.0)
    assert result.pooled_fallback_kinds == (BLANK_GAMEWEEK,)


def test_a_missing_sample_that_is_never_averaged_over_is_not_reported() -> None:
    # The blank is the gameweek being decided; its sample is not consulted.
    result = induction_thresholds([BLANK_GAMEWEEK, SINGLE_GAMEWEEK], {SINGLE_GAMEWEEK: [2.0, 10.0]})

    assert result.thresholds == (6.0, 0.0)
    assert result.pooled_fallback_kinds == ()


def test_the_recursion_refuses_what_it_cannot_compute() -> None:
    with pytest.raises(ExperimentExecutionError, match="No exercise value"):
        induction_thresholds([SINGLE_GAMEWEEK, SINGLE_GAMEWEEK], {SINGLE_GAMEWEEK: []})
    with pytest.raises(ExperimentExecutionError, match="No exercise value"):
        induction_thresholds([SINGLE_GAMEWEEK], {})
    with pytest.raises(ExperimentConfigurationError, match="at least one gameweek"):
        induction_thresholds([], {SINGLE_GAMEWEEK: [1.0]})
    with pytest.raises(ExperimentConfigurationError, match="kind must be one of"):
        induction_thresholds(["triple"], {SINGLE_GAMEWEEK: [1.0]})
    with pytest.raises(ExperimentConfigurationError, match="kind must be one of"):
        induction_thresholds([SINGLE_GAMEWEEK], {"triple": [1.0]})
    with pytest.raises(ExperimentExecutionError, match="not finite"):
        induction_thresholds([SINGLE_GAMEWEEK], {SINGLE_GAMEWEEK: [float("inf")]})


# --- windows and the hold-out ----------------------------------------------------------


def test_a_window_reads_only_its_own_classified_gameweeks() -> None:
    # Gameweek 3 has no kind (nobody decided it), so the window 2..5 is 2, 4, 5.
    kinds = {1: DOUBLE_GAMEWEEK, 2: SINGLE_GAMEWEEK, 4: SINGLE_GAMEWEEK, 5: DOUBLE_GAMEWEEK}
    values = {SINGLE_GAMEWEEK: [2.0, 10.0], DOUBLE_GAMEWEEK: [4.0, 12.0]}

    result = window_thresholds(
        ChipWindowRule("3xc", 2, 5), kinds, values, sample_seasons=("2021-22",)
    )

    # The same three kinds as the hand example: single, single, double.
    assert result.gameweeks == (2, 4, 5)
    assert result.thresholds == (9.0, 8.0, 0.0)
    assert result.threshold_at(4) == 8.0
    assert result.sample_sizes == ((SINGLE_GAMEWEEK, 2), (DOUBLE_GAMEWEEK, 2), (BLANK_GAMEWEEK, 0))
    assert result.as_record() == {
        "chip": "3xc",
        "start_gameweek": 2,
        "stop_gameweek": 5,
        "thresholds": {"2": 9.0, "4": 8.0, "5": 0.0},
        "pooled_fallback_kinds": [],
        "sample_seasons": ["2021-22"],
        "sample_sizes": {"single": 2, "double": 2, "blank": 0},
    }
    with pytest.raises(ExperimentExecutionError, match="not a classified gameweek"):
        result.threshold_at(3)


def test_a_window_refuses_a_chip_with_no_recorded_value_and_an_empty_range() -> None:
    values = {SINGLE_GAMEWEEK: [1.0]}
    with pytest.raises(ExperimentConfigurationError, match="No weekly exercise value"):
        window_thresholds(ChipWindowRule("wildcard", 2, 19), {2: SINGLE_GAMEWEEK}, values)
    with pytest.raises(ExperimentExecutionError, match="covers no classified gameweek"):
        window_thresholds(ChipWindowRule("3xc", 20, 38), {2: SINGLE_GAMEWEEK}, values)


def _chain(season: str, variant: str, captain: float, bench: float) -> dict[str, object]:
    return {
        "season": season,
        "variant": variant,
        "weeks": [_week(gameweek, captain=captain, bench=bench) for gameweek in (1, 2, 3)],
    }


def test_leave_one_season_out_never_sees_the_held_out_season() -> None:
    kinds = {1: SINGLE_GAMEWEEK, 2: SINGLE_GAMEWEEK, 3: SINGLE_GAMEWEEK}
    chains = [
        _chain("2021-22", "decaying", captain=4.0, bench=2.0),
        _chain("2022-23", "decaying", captain=8.0, bench=6.0),
        # The held-out season carries a value no other season could produce.
        _chain("2023-24", "decaying", captain=SENTINEL, bench=SENTINEL),
        # Another arm of a sampled season, which must not be read either.
        _chain("2021-22", "off", captain=SENTINEL, bench=SENTINEL),
    ]
    windows = (ChipWindowRule("3xc", 1, 3), ChipWindowRule("bboost", 1, 3))

    result = leave_one_season_out_thresholds(
        chains,
        {season: kinds for season in ("2021-22", "2022-23", "2023-24")},
        windows,
        variant="decaying",
    )

    assert sorted(result) == ["2021-22", "2022-23", "2023-24"]
    held_out = result["2023-24"]
    assert [window.chip for window in held_out] == ["3xc", "bboost"]
    assert all(window.sample_seasons == ("2021-22", "2022-23") for window in held_out)
    assert all(window.sample_sizes[0] == (SINGLE_GAMEWEEK, 6) for window in held_out)
    # Captain sample {4, 4, 4, 8, 8, 8}: tau_3 = 0, tau_2 = 6, tau_1 = (3 * 6 + 3 * 8) / 6 = 7.
    assert held_out[0].thresholds == (7.0, 6.0, 0.0)
    # Bench sample {2, 2, 2, 6, 6, 6}: tau_2 = 4, tau_1 = (3 * 4 + 3 * 6) / 6 = 5.
    assert held_out[1].thresholds == (5.0, 4.0, 0.0)
    assert all(threshold < SENTINEL for window in held_out for threshold in window.thresholds)
    # The sentinel is a real value of the sample wherever its season is not held out, so
    # its absence above is the hold-out and not an accident of the data.
    # Sample {4, 4, 4, 1000, 1000, 1000}: tau_2 = 502, tau_1 = (3 * 502 + 3 * 1000) / 6 = 751.
    assert result["2022-23"][0].sample_seasons == ("2021-22", "2023-24")
    assert result["2022-23"][0].thresholds == (751.0, 502.0, 0.0)


def test_leave_one_season_out_uses_the_held_out_seasons_own_calendar() -> None:
    plain = {1: SINGLE_GAMEWEEK, 2: SINGLE_GAMEWEEK, 3: SINGLE_GAMEWEEK}
    ends_on_a_double = {1: SINGLE_GAMEWEEK, 2: SINGLE_GAMEWEEK, 3: DOUBLE_GAMEWEEK}
    chains = [
        _chain("2021-22", "decaying", captain=4.0, bench=2.0),
        _chain("2022-23", "decaying", captain=8.0, bench=6.0),
    ]

    result = leave_one_season_out_thresholds(
        chains,
        {"2021-22": plain, "2022-23": ends_on_a_double},
        (ChipWindowRule("3xc", 1, 3),),
        variant="decaying",
    )

    # 2022-23 ends on a double, and the only other season never sampled one: the pooled
    # sample stands in, and the result says so.
    assert result["2022-23"][0].pooled_fallback_kinds == (DOUBLE_GAMEWEEK,)
    assert result["2022-23"][0].thresholds == (4.0, 4.0, 0.0)
    assert result["2021-22"][0].pooled_fallback_kinds == ()


def test_leave_one_season_out_refuses_what_would_leak_or_cannot_be_held_out() -> None:
    kinds = {1: SINGLE_GAMEWEEK, 2: SINGLE_GAMEWEEK, 3: SINGLE_GAMEWEEK}
    windows = (ChipWindowRule("3xc", 1, 3),)
    one = [_chain("2021-22", "decaying", captain=4.0, bench=2.0)]
    with pytest.raises(ExperimentExecutionError, match="at least two seasons"):
        leave_one_season_out_thresholds(one, {"2021-22": kinds}, windows, variant="decaying")
    with pytest.raises(ExperimentExecutionError, match="Two chains"):
        leave_one_season_out_thresholds(one + one, {"2021-22": kinds}, windows, variant="decaying")
    two = [*one, _chain("2022-23", "decaying", captain=8.0, bench=6.0)]
    with pytest.raises(ExperimentExecutionError, match="No gameweek kinds"):
        leave_one_season_out_thresholds(two, {"2021-22": kinds}, windows, variant="decaying")
    with pytest.raises(ExperimentExecutionError, match="no list of week records"):
        leave_one_season_out_thresholds(
            [*one, {"season": "2022-23", "variant": "decaying", "weeks": None}],
            {"2021-22": kinds, "2022-23": kinds},
            windows,
            variant="decaying",
        )


def test_the_kinds_are_the_three_the_protocol_names() -> None:
    assert GAMEWEEK_KINDS == ("single", "double", "blank")
    assert dict(CHIP_VALUE_FIELDS) == {
        "3xc": "captain_projected_points",
        "bboost": "bench_projected_points",
    }
