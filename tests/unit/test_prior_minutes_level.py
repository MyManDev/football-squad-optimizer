"""The level correction's factor: what it is fitted on, and what it can never see."""

import numpy as np
import pandas as pd
import pytest

from squadopt.evaluation.prior_minutes_level import (
    MINIMUM_EARLIER_DECISIONS,
    PriorMinutesLevelError,
    corrected_forecast,
    online_factors,
    prior_bucket,
)


def _decision(fold: str, *, gameweek: int = 5, regular: float = 6.0) -> list[dict[str, object]]:
    # A regular forecast 4 and an unseen player forecast 1 who scores nothing.
    return [
        {
            "fold_id": fold,
            "target_gameweek": gameweek,
            "player_id": 1,
            "forecast": 4.0,
            "realized": regular,
            "prior_minutes_per_week": 85.0,
        },
        {
            "fold_id": fold,
            "target_gameweek": gameweek,
            "player_id": 2,
            "forecast": 1.0,
            "realized": 0.0,
            "prior_minutes_per_week": 0.0,
        },
    ]


def _season(decisions: int = 12) -> tuple[pd.DataFrame, list[str]]:
    order = [f"2021-22-gw{week:02d}" for week in range(4, 4 + decisions)]
    rows = [row for fold in order for row in _decision(fold)]
    return pd.DataFrame(rows), order


def test_buckets_are_the_live_audits_and_an_absent_prior_has_none() -> None:
    labels = prior_bucket(pd.Series([0.0, 12.0, 30.0, 59.9, 60.0, np.nan]))
    assert labels.iloc[:5].tolist() == ["none", "under_30", "30_to_60", "30_to_60", "60_and_above"]
    assert pd.isna(labels.iloc[5])


def test_a_factor_waits_for_enough_earlier_decisions_and_then_is_their_ratio() -> None:
    frame, order = _season()
    factors = online_factors(frame, order).set_index(["fold_id", "bucket"])
    early = order[MINIMUM_EARLIER_DECISIONS - 1]
    ready = order[MINIMUM_EARLIER_DECISIONS]
    assert factors.loc[(early, "60_and_above"), "factor"] == 1.0
    assert factors.loc[(ready, "60_and_above"), "factor"] == pytest.approx(6.0 / 4.0)
    assert factors.loc[(ready, "60_and_above"), "earlier_decisions"] == MINIMUM_EARLIER_DECISIONS
    # The unseen scored nothing in every earlier decision: the ratio is zero, the lower bound.
    assert factors.loc[(ready, "none"), "factor"] == 0.0
    # Nobody was ever in this bucket, so there is nothing to divide by and nothing is changed.
    assert factors.loc[(ready, "under_30"), "factor"] == 1.0


def test_no_factor_can_see_its_own_decision_or_a_later_one() -> None:
    frame, order = _season()
    before = online_factors(frame, order)
    target = order[MINIMUM_EARLIER_DECISIONS + 1]
    position = order.index(target)
    changed = frame.copy()
    # Rewrite the outcome of the target decision and of everything after it.
    later = changed["fold_id"].isin(order[position:])
    changed.loc[later, "realized"] = 99.0
    after = online_factors(changed, order)
    same = before["fold_id"].isin(order[: position + 1])
    pd.testing.assert_frame_equal(before.loc[same], after.loc[same])
    # And the decision after it does move, so the test is not passing on a constant.
    moved = order[position + 1]
    assert not before.loc[before["fold_id"] == moved].equals(after.loc[after["fold_id"] == moved])


def test_early_gameweeks_neither_teach_nor_receive_a_factor() -> None:
    frame, order = _season()
    opening = pd.DataFrame(_decision("2021-22-gw03", gameweek=3, regular=40.0))
    full = pd.concat([opening, frame], ignore_index=True)
    full_order = ["2021-22-gw03", *order]
    factors = online_factors(full, full_order)
    ready = order[MINIMUM_EARLIER_DECISIONS]
    regulars = factors.set_index(["fold_id", "bucket"]).loc[(ready, "60_and_above")]
    assert regulars["factor"] == pytest.approx(1.5)  # the 40 never entered
    corrected = corrected_forecast(full, factors)
    assert corrected.iloc[0] == 4.0  # gameweek 3 keeps its forecast
    last = full.index[full["fold_id"] == order[-1]]
    assert corrected.loc[last[0]] == pytest.approx(6.0) and corrected.loc[last[1]] == 0.0


def test_the_factor_is_bounded_and_absent_stays_absent() -> None:
    frame, order = _season()
    frame.loc[frame["player_id"] == 1, "realized"] = 20.0
    frame.loc[frame.index[-1], "forecast"] = np.nan
    frame.loc[frame.index[-2], "prior_minutes_per_week"] = np.nan
    factors = online_factors(frame, order)
    assert factors["factor"].max() == 2.0
    corrected = corrected_forecast(frame, factors)
    assert np.isnan(corrected.iloc[-1])
    assert corrected.iloc[-2] == 4.0  # no prior, no bucket, no correction


def test_tables_that_cannot_be_read_are_refused() -> None:
    frame, order = _season()
    with pytest.raises(PriorMinutesLevelError, match="lacks"):
        online_factors(frame.drop(columns=["realized"]), order)
    with pytest.raises(PriorMinutesLevelError, match="outside"):
        online_factors(frame, order[:-1])
    with pytest.raises(PriorMinutesLevelError, match="twice"):
        online_factors(frame, [*order, order[0]])
