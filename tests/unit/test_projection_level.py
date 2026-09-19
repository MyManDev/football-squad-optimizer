"""The projection level audit's arithmetic, on tables small enough to check by hand."""

import numpy as np
import pandas as pd
import pytest

from squadopt.evaluation.projection_level import (
    ProjectionLevelAuditError,
    level_block,
    sign_agreement,
    summarise_level,
)


def _rows(fold: str, season: str = "2021-22", shift: float = 0.0) -> list[dict[str, object]]:
    # A regular who plays and beats his forecast, a squad player the season has not seen who
    # is forecast to play a little and does not, and a thin-history row with no components.
    return [
        {
            "season": season,
            "fold_id": fold,
            "player_id": 1,
            "position": "MID",
            "forecast": 4.5,
            "realized": 6.0 + shift,
            "appearance_forecast": 0.9,
            "appeared": 1,
            "conditional_forecast": 5.0,
            "prior_minutes_per_week": 88.0,
        },
        {
            "season": season,
            "fold_id": fold,
            "player_id": 2,
            "position": "DEF",
            "forecast": 0.3,
            "realized": 0.0,
            "appearance_forecast": 0.1,
            "appeared": 0,
            "conditional_forecast": 3.0,
            "prior_minutes_per_week": 0.0,
        },
        {
            "season": season,
            "fold_id": fold,
            "player_id": 3,
            "position": "FWD",
            "forecast": 2.0,
            "realized": 1.0,
            "appearance_forecast": np.nan,
            "appeared": np.nan,
            "conditional_forecast": np.nan,
            "prior_minutes_per_week": np.nan,
        },
    ]


def _table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            *_rows("2021-22-gw04"),
            *_rows("2021-22-gw05", shift=2.0),
            *_rows("2022-23-gw04", season="2022-23"),
        ]
    )


def test_a_bucket_states_the_level_and_both_of_its_sources() -> None:
    summary = summarise_level(_table())
    pooled = summary["pooled"]
    assert isinstance(pooled, dict)
    assert pooled["rows"] == 9 and pooled["decisions"] == 3
    # The thin-history row has no prior: it is counted as such and sits in no bucket.
    assert pooled["rows_without_a_prior"] == 3
    regulars = pooled["by_prior_minutes"]["60_and_above"]
    assert regulars["rows"] == 3
    assert regulars["forecast_points"] == pytest.approx(13.5)
    assert regulars["realized_points"] == pytest.approx(20.0)
    assert regulars["bias"] == pytest.approx(6.5 / 3)
    # Who plays: 0.9 forecast, always appeared. What they score when they do: 5.0 against 6, 8, 6.
    assert regulars["who_plays"]["bias"] == pytest.approx(0.1)
    scored = regulars["what_they_score_when_they_play"]
    assert scored["mean_forecast"] == 5.0 and scored["mean_realized"] == pytest.approx(20 / 3)
    unseen = pooled["by_prior_minutes"]["none"]
    assert unseen["bias"] == pytest.approx(-0.3)
    assert unseen["who_plays"]["appearances"] == 0.0
    # Nobody appeared, so there is nothing to say about what they scored, and it says so.
    assert unseen["what_they_score_when_they_play"] == {"rows": 0}
    assert pooled["by_prior_minutes"]["under_30"] == {"rows": 0}


def test_rows_without_components_count_for_the_level_and_never_for_the_sources() -> None:
    pooled = summarise_level(_table())["pooled"]
    assert isinstance(pooled, dict)
    band = pooled["by_forecast_size"]["1.0_to_2.5"]
    assert band["rows"] == 3 and band["bias"] == pytest.approx(-1.0)
    assert band["who_plays"] == {"rows": 0}
    everyone = pooled["all"]
    assert everyone["rows"] == 9 and everyone["who_plays"]["rows"] == 6


def test_the_interval_resamples_decisions_and_counts_the_empty_ones() -> None:
    table = _table()
    folds = np.sort(table["fold_id"].unique())
    regulars = table.loc[table["player_id"] == 1]
    block = level_block(regulars, folds)
    low, high = block["bias_interval"]  # type: ignore[misc]
    # Per decision the error is 1.5, 3.5 and 1.5, so no resample can leave that range.
    assert 1.5 <= low <= high <= 3.5
    assert level_block(regulars, folds) == block  # seeded
    # One decision gives nothing to resample.
    assert level_block(regulars.iloc[[0]], folds[:1])["bias_interval"] is None


def test_a_candidate_opens_only_on_an_interval_off_zero_and_three_seasons_agreeing() -> None:
    seasons = ("2021-22", "2022-23", "2023-24", "2024-25")
    table = pd.DataFrame(
        [
            row
            for season in seasons
            for week in (4, 5, 6)
            for row in _rows(f"{season}-gw{week:02d}", season=season)
        ]
    )
    verdict = sign_agreement(summarise_level(table), "by_prior_minutes", "60_and_above")
    assert verdict["pooled_interval_excludes_zero"] is True
    assert verdict["seasons_with_the_pooled_sign"] == 4 and verdict["opens_a_candidate"] is True
    # Two seasons only: the interval may be off zero, the rule still refuses.
    two = table.loc[table["season"].isin(seasons[:2])]
    refused = sign_agreement(summarise_level(two), "by_prior_minutes", "60_and_above")
    assert refused["seasons_read"] == 2 and refused["opens_a_candidate"] is False
    # An empty bucket opens nothing.
    empty = sign_agreement(summarise_level(table), "by_prior_minutes", "under_30")
    assert empty["pooled_bias"] is None and empty["opens_a_candidate"] is False


def test_tables_that_cannot_be_read_are_refused() -> None:
    table = _table()
    with pytest.raises(ProjectionLevelAuditError, match="lacks"):
        summarise_level(table.drop(columns=["appeared"]))
    with pytest.raises(ProjectionLevelAuditError, match="twice"):
        summarise_level(pd.concat([table, table.iloc[[0]]]))
    with pytest.raises(ProjectionLevelAuditError, match="empty"):
        summarise_level(table.iloc[0:0])
