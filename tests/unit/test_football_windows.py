import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.football_windows import paired_window_losses


def frames():
    control = pd.DataFrame(
        {
            "season": ["2025-26"] * 4,
            "fixture": [1, 2, 1, 2],
            "player_code": [10, 10, 20, 20],
            "expected_points": [2.0, 3.0, 1.0, 1.0],
        }
    )
    actual = control.drop(columns="expected_points").assign(total_points=[4.0, 1.0, 0.0, 0.0])
    return control, control.assign(expected_points=[3.0, 4.0, 0.0, 0.0]), actual


def test_sum_error_includes_cross_fixture_cancellation_and_pairs_rows():
    control, candidate, actual = frames()
    result = paired_window_losses(control, candidate.iloc[::-1], actual)
    assert result["v1"]["fixture_mse"] == 2.5
    assert result["v1"]["sum_mse"] == 2.0
    assert result["contextual"]["sum_mse"] == 2.0
    assert result["v1"]["complete_players"] == 2


def test_one_missing_fixture_excludes_whole_player_for_both_arms():
    control, candidate, actual = frames()
    actual.loc[3, "total_points"] = np.nan
    result = paired_window_losses(control, candidate, actual)
    assert result["v1"]["sum_mse"] == 0
    assert result["contextual"]["sum_mse"] == 4
    for arm in result.values():
        assert arm["excluded_incomplete_players"] == 1
        assert arm["missing_fixture_labels"] == 1


@pytest.mark.parametrize("fault", ["duplicate", "missing_key", "missing_forecast", "infinite"])
def test_invalid_forecasts_are_not_silently_selected_away(fault):
    control, candidate, actual = frames()
    if fault == "duplicate":
        candidate = pd.concat([candidate, candidate.iloc[:1]])
    elif fault == "missing_key":
        candidate = candidate.iloc[:-1]
    else:
        candidate.loc[0, "expected_points"] = np.nan if fault == "missing_forecast" else np.inf
    with pytest.raises(ValueError):
        paired_window_losses(control, candidate, actual)
