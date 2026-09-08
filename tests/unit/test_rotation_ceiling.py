"""The oracle's flagging rule, the exclusion's shape, and how the record reads its own number.

The panels here are written by hand rather than taken from ``synthetic_gameweeks``, because
the rule under test is about *specific* histories: a rate of exactly 1.0, a rate one
appearance short of it, and a player without enough history to have a rate at all. A shared
fixture chosen for other properties cannot be relied on to contain those three side by side.

The last group covers the runner's three readings of the finished numbers. They exist because
a mean alone would be read as more certain and more general than the measurement is, and each
has a branch that the one real run did not exercise -- an interval wholly above the threshold,
one wholly below, a set of seasons that all agree. A branch no run reaches is a branch a test
has to reach.
"""

import pandas as pd
import pytest
from scripts.measure_rotation_ceiling import (
    _autosub_reading,
    _concentration_reading,
    _interval_reading,
)
from tests.fixtures.synthetic_players import make_baseline_players

from squadopt.evaluation.evaluator import evaluate_prepared_folds
from squadopt.evaluation.models import (
    EvaluationConfig,
    EvaluationFold,
    ScoringPolicy,
)
from squadopt.evaluation.rotation_ceiling import (
    ORACLE_APPEARANCE_WINDOW,
    ORACLE_VERSION,
    FoldDecisionDetail,
    RotationCeilingError,
    apply_rotation_exclusion,
    attach_realized_minutes,
    build_oracle_flags,
    compare_rotation_ceiling,
    fold_decision_details,
    fold_key,
)

SEASON = "2024-25"
TARGET_GAMEWEEK = 8


def _panel(histories: dict[int, list[int]]) -> pd.DataFrame:
    """Return a minimal panel from ``player_id -> minutes per gameweek`` histories.

    Gameweeks are numbered from 1, so a history of eight entries ends at gameweek 8. Only
    the four columns the oracle reads are present, which also proves it needs no others.
    """

    records: list[dict[str, object]] = []
    for player_id, minutes in sorted(histories.items()):
        for offset, played in enumerate(minutes):
            records.append(
                {
                    "season": SEASON,
                    "gameweek": offset + 1,
                    "player_id": player_id,
                    "minutes": played,
                }
            )
    frame = pd.DataFrame.from_records(records)
    frame["minutes"] = frame["minutes"].astype("int64")
    frame["gameweek"] = frame["gameweek"].astype("int64")
    return frame.sort_values(["season", "gameweek", "player_id"], kind="stable").reset_index(
        drop=True
    )


# Six prior gameweeks of history, then gameweek 8's own minutes as the last entry. Gameweek 7
# is a full appearance for everyone, so the six-gameweek window ending at gameweek 7 is what
# separates these players.
_RESTED_REGULAR = [90, 90, 90, 90, 90, 90, 90, 0]
_PLAYED_REGULAR = [90, 90, 90, 90, 90, 90, 90, 62]
_NOT_QUITE_REGULAR = [90, 0, 90, 90, 90, 90, 90, 0]
_SHORT_HISTORY = [0, 0, 0, 0, 0, 0, 90, 0]


def test_the_oracle_flags_a_regular_who_did_not_play() -> None:
    flags = build_oracle_flags(_panel({1: _RESTED_REGULAR}))

    assert flags.version == ORACLE_VERSION
    assert flags.window == ORACLE_APPEARANCE_WINDOW
    assert flags.by_fold == {(SEASON, TARGET_GAMEWEEK): (1,)}
    assert flags.flagged_rows == 1


def test_a_regular_who_played_is_not_flagged() -> None:
    """The first negative case: the history says regular, the outcome says he played."""

    flags = build_oracle_flags(_panel({2: _PLAYED_REGULAR}))

    assert flags.by_fold == {}
    assert flags.flagged_rows == 0
    # He is still eligible -- he has the full window of history. Eligible and flagged are
    # different facts, and the record reports both.
    assert flags.eligible_rows == 2


def test_a_player_one_appearance_short_of_regular_is_not_flagged() -> None:
    """The second negative case: zero minutes, but a rate of 5/6 rather than 1.0."""

    flags = build_oracle_flags(_panel({3: _NOT_QUITE_REGULAR}))

    assert flags.by_fold == {}
    assert flags.zero_minute_eligible_rows == 1


def test_a_player_without_the_full_window_is_not_eligible() -> None:
    """The third negative case, and the trap the rule exists to avoid.

    ``shifted_rolling_mean`` defaults to ``min_periods=1``, under which one prior
    appearance yields a rate of 1.0 and the rule would read "played once" as "nailed-on
    starter". The oracle requires the whole window, so a player with five prior gameweeks
    has no rate at all and cannot be flagged.
    """

    flags = build_oracle_flags(_panel({4: _SHORT_HISTORY}))

    assert flags.by_fold == {}
    assert flags.eligible_rows == 2
    assert flags.panel_rows == 8


def test_the_rate_is_shifted_so_a_gameweek_cannot_enter_its_own_rate() -> None:
    """A player who featured in every prior gameweek is flagged in the one he misses.

    If the rate were unshifted, gameweek 8's own zero would drag the rate to 7/8 and the
    rule could never fire at all. That the rule fires is itself the proof of the shift.
    """

    seven_and_out = [90] * 7 + [0, 90]
    flags = build_oracle_flags(_panel({5: seven_and_out}))

    assert flags.by_fold == {(SEASON, 8): (5,)}
    assert 9 not in [gameweek for _, gameweek in flags.by_fold]


def test_the_three_negative_cases_coexist_with_the_positive_one() -> None:
    flags = build_oracle_flags(
        _panel(
            {
                1: _RESTED_REGULAR,
                2: _PLAYED_REGULAR,
                3: _NOT_QUITE_REGULAR,
                4: _SHORT_HISTORY,
            }
        )
    )

    assert flags.by_fold == {(SEASON, TARGET_GAMEWEEK): (1,)}
    assert flags.by_season == {SEASON: 1}


def test_a_missing_minute_is_refused_rather_than_read_as_a_zero() -> None:
    panel = _panel({1: _RESTED_REGULAR})
    panel["minutes"] = panel["minutes"].astype("float64")
    panel.loc[panel["gameweek"] == TARGET_GAMEWEEK, "minutes"] = None

    with pytest.raises(RotationCeilingError, match="a missing value is not a zero"):
        build_oracle_flags(panel)


def test_the_oracle_names_the_columns_it_needs() -> None:
    with pytest.raises(RotationCeilingError, match="missing columns"):
        build_oracle_flags(pd.DataFrame({"season": [SEASON], "gameweek": [1]}))


def _fold(fold_id: str = "2024-25-gw08") -> EvaluationFold:
    pool = make_baseline_players()
    realized = pd.DataFrame(
        {
            "player_id": pool["player_id"],
            "total_points": [int(3 + (index % 5)) for index in range(len(pool))],
        }
    )
    return EvaluationFold(
        fold_id=fold_id,
        projections=pool,
        realized_points=realized,
        metadata={"season": SEASON, "gameweek": TARGET_GAMEWEEK},
    )


def _panel_for_fold(fold: EvaluationFold, *, rested: set[int]) -> pd.DataFrame:
    ids = [int(value) for value in fold.realized_points["player_id"].tolist()]
    return pd.DataFrame(
        {
            "season": [SEASON] * len(ids),
            "gameweek": pd.Series([TARGET_GAMEWEEK] * len(ids), dtype="int64"),
            "player_id": ids,
            "minutes": pd.Series(
                [0 if player_id in rested else 90 for player_id in ids], dtype="int64"
            ),
        }
    )


def test_fold_key_refuses_a_fold_that_does_not_name_its_decision() -> None:
    fold = _fold()
    without_season = EvaluationFold(
        fold_id=fold.fold_id,
        projections=fold.projections,
        realized_points=fold.realized_points,
        metadata={"gameweek": TARGET_GAMEWEEK},
    )

    with pytest.raises(RotationCeilingError, match="does not name its season"):
        fold_key(without_season)


def test_realized_minutes_are_joined_from_the_panel() -> None:
    fold = _fold()
    with_minutes = attach_realized_minutes(fold, _panel_for_fold(fold, rested={3}))

    assert "minutes" in with_minutes.realized_points.columns
    assert len(with_minutes.realized_points) == len(fold.realized_points)
    rested = with_minutes.realized_points.loc[
        with_minutes.realized_points["player_id"] == 3, "minutes"
    ]
    assert int(rested.iloc[0]) == 0


def test_a_second_minutes_column_is_refused() -> None:
    fold = _fold()
    once = attach_realized_minutes(fold, _panel_for_fold(fold, rested=set()))

    with pytest.raises(RotationCeilingError, match="already carries realized minutes"):
        attach_realized_minutes(once, _panel_for_fold(fold, rested=set()))


def test_a_scored_player_with_no_panel_minutes_is_refused() -> None:
    fold = _fold()
    panel = _panel_for_fold(fold, rested=set())

    with pytest.raises(RotationCeilingError, match="have no minutes in the panel"):
        attach_realized_minutes(fold, panel.loc[panel["player_id"] != 3])


def test_the_exclusion_zeroes_expected_points_and_keeps_the_rows() -> None:
    fold = _fold()
    excluded = apply_rotation_exclusion(fold, (3, 4))

    assert excluded.applied == (3, 4)
    assert excluded.absent == ()
    # The pool is the same size. Dropping rows could turn a fold infeasible and would
    # destroy the pairing the whole measurement rests on.
    assert len(excluded.fold.projections) == len(fold.projections)
    zeroed = excluded.fold.projections.loc[
        excluded.fold.projections["player_id"].isin([3, 4]), "expected_points"
    ]
    assert zeroed.tolist() == [0.0, 0.0]
    untouched = excluded.fold.projections.loc[
        ~excluded.fold.projections["player_id"].isin([3, 4]), "expected_points"
    ]
    assert (
        untouched.tolist()
        == (
            fold.projections.loc[~fold.projections["player_id"].isin([3, 4]), "expected_points"]
        ).tolist()
    )
    assert excluded.fold.metadata["rotation_excluded_players"] == 2


def test_the_exclusion_reports_a_flagged_player_the_projection_pool_never_had() -> None:
    fold = _fold()
    excluded = apply_rotation_exclusion(fold, (3, 9_999))

    assert excluded.applied == (3,)
    assert excluded.absent == (9_999,)


def test_the_exclusion_leaves_the_original_fold_alone() -> None:
    fold = _fold()
    before = fold.projections["expected_points"].tolist()
    apply_rotation_exclusion(fold, (3,))

    assert fold.projections["expected_points"].tolist() == before


def _details(
    *, rested: set[int]
) -> tuple[tuple[FoldDecisionDetail, ...], tuple[FoldDecisionDetail, ...]]:
    """Solve and score both arms of one fold, differing only by the exclusion."""

    base = _fold()
    control = attach_realized_minutes(base, _panel_for_fold(base, rested=rested))
    excluded_by_fold: dict[tuple[str, int], tuple[object, ...]] = {
        (SEASON, TARGET_GAMEWEEK): tuple(sorted(rested))
    }
    oracle = apply_rotation_exclusion(control, excluded_by_fold[(SEASON, TARGET_GAMEWEEK)]).fold
    config = EvaluationConfig(scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2)
    return (
        fold_decision_details(
            evaluate_prepared_folds([control], config),
            [control],
            excluded_by_fold=excluded_by_fold,
        ),
        fold_decision_details(
            evaluate_prepared_folds([oracle], config),
            [oracle],
            excluded_by_fold=excluded_by_fold,
        ),
    )


def test_the_excluded_player_leaves_the_starting_eleven() -> None:
    """End to end on one real solve: the arms differ, and only in the intended direction."""

    control_details, oracle_details = _details(rested={20, 21, 22})

    assert len(control_details) == 1
    assert len(oracle_details) == 1
    assert control_details[0].excluded_starters > 0
    assert oracle_details[0].excluded_starters == 0


def test_the_comparison_pairs_fold_by_fold_and_names_what_it_dropped() -> None:
    def detail(fold_id: str, points: float, *, excluded: int = 0) -> FoldDecisionDetail:
        return FoldDecisionDetail(
            fold_id=fold_id,
            season=fold_id[:7],
            gameweek=int(fold_id[-2:]),
            points=points,
            zero_minute_starters=1,
            autosub_points=2.0,
            excluded_starters=excluded,
        )

    comparison = compare_rotation_ceiling(
        [
            detail("2024-25-gw02", 50.0, excluded=2),
            detail("2024-25-gw03", 60.0),
            detail("2024-25-gw04", 40.0),
        ],
        [detail("2024-25-gw02", 55.0), detail("2024-25-gw03", 60.0)],
        attempted_folds=3,
    )

    assert comparison.attempted_folds == 3
    assert comparison.comparable_folds == 2
    assert comparison.dropped_fold_ids == ("2024-25-gw04",)
    assert (comparison.oracle_wins, comparison.ties, comparison.oracle_losses) == (1, 1, 0)
    assert comparison.mean_difference == 2.5
    assert comparison.season_mean_differences == {"2024-25": 2.5}
    assert comparison.control_started_excluded_players == 2


def test_the_comparison_reaches_no_verdict_of_its_own() -> None:
    """The ceiling describes; it does not promote.

    The threshold G0 is read against is a promotion policy in a layer above this one, so
    there is no gate field here to be mistaken for a decision. This test pins that: if a
    verdict ever appears on the comparison, it was added on purpose and this fails.
    """

    comparison = compare_rotation_ceiling([], [], attempted_folds=0)
    fields = set(type(comparison).__dataclass_fields__)

    assert not fields & {"gate_evidence", "verdict", "promoted", "passes", "licensed"}
    assert comparison.mean_difference is None
    assert comparison.comparable_folds == 0


def _comparison_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "comparable_folds": 147,
        "ties": 93,
        "median_difference": 0.0,
        "mean_difference": 0.9659863945578231,
        "interval_lower": 0.027210884353741496,
        "interval_upper": 1.6326530612244898,
        "control_autosub_points": 186.0,
        "oracle_autosub_points": 75.0,
        "season_mean_differences": {"2021-22": -0.378, "2023-24": 2.892},
    }
    record.update(overrides)
    return record


_VERDICT_RECORD: dict[str, object] = {"threshold_points_per_decision": 0.5}


def test_an_interval_that_still_contains_the_threshold_says_so() -> None:
    """The measured case. The mean decides the verdict; the interval qualifies it."""

    reading = _interval_reading(_comparison_record(), _VERDICT_RECORD)

    assert "the interval does not" in reading
    assert "not ruled out" in reading


def test_an_interval_wholly_above_the_threshold_says_that_instead() -> None:
    reading = _interval_reading(
        _comparison_record(interval_lower=0.8, interval_upper=1.6), _VERDICT_RECORD
    )

    assert "at or above" in reading
    assert "not ruled out" not in reading


def test_an_interval_wholly_below_the_threshold_says_that_instead() -> None:
    reading = _interval_reading(
        _comparison_record(interval_lower=-0.4, interval_upper=0.2), _VERDICT_RECORD
    )

    assert "below the 0.5" in reading
    assert "does not reach it" in reading


def test_the_concentration_reading_names_a_season_that_goes_the_other_way() -> None:
    reading = _concentration_reading(_comparison_record())

    assert "93 of 147" in reading
    assert "2021-22 goes the other way" in reading


def test_the_concentration_reading_stays_silent_when_every_season_agrees() -> None:
    reading = _concentration_reading(
        _comparison_record(season_mean_differences={"2021-22": 0.4, "2023-24": 2.892})
    )

    assert "the other way" not in reading


def test_the_autosub_reading_charges_the_surrendered_recovery_back() -> None:
    """The arithmetic that makes the rejected scoring path auditable rather than argued."""

    reading = _autosub_reading(_comparison_record())

    # 186/147 = 1.27 recovered by the control, 75/147 = 0.51 by the oracle arm, so the arm
    # surrenders 0.76 to gain 0.97 -- and a path without autosubs would have reported 1.72.
    assert "1.27 points per decision for the control" in reading
    assert "surrenders 0.76" in reading
    assert "ceiling near 1.72" in reading
