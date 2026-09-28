import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.football_defcon import direct_tail


def frames():
    history = pd.DataFrame(
        [
            dict(
                season="2025-26",
                GW=1,
                fixture=1,
                player_code=1,
                position="DEF",
                minutes=90,
                dc_event=1,
                kickoff="2025-08-01T10:00:00Z",
            )
        ]
    )
    target = pd.DataFrame([dict(season="2025-26", GW=2, player_code=1, position="DEF")])
    return history, target, pd.Timestamp("2025-08-08T10:00:00Z")


def test_analytic_shrinkage_and_minute_mixture():
    history, target, cutoff = frames()
    value = direct_tail(history, target, np.array([[0.5, 0, 0, 0.5]]), cutoff)
    assert value[0] == pytest.approx(0.5 * (1 + 10 * 2 / 3) / 11)
    target["position"] = "GK"
    assert direct_tail(history, target, np.array([[0, 0, 0, 1]]), cutoff)[0] == 0


def test_target_labels_and_unsettled_same_week_cannot_leak():
    history, target, cutoff = frames()
    mass = np.array([[0, 0, 0, 1]])
    original = direct_tail(history, target, mass, cutoff)
    future = pd.concat(
        [
            history.assign(GW=2, fixture=2),
            history.assign(fixture=3, kickoff=cutoff - pd.Timedelta(hours=3)),
        ]
    )
    target["dc_event"], target["minutes"] = 0, 0
    np.testing.assert_array_equal(
        original, direct_tail(pd.concat([history, future]), target, mass, cutoff)
    )


def test_missing_is_not_zero_and_pre_rule_is_excluded():
    history, target, cutoff = frames()
    mass = np.array([[0, 0, 0, 1]])
    unknown = history.assign(dc_event=np.nan)
    assert direct_tail(unknown, target, mass, cutoff)[0] == 0.5
    assert direct_tail(history.assign(season="2024-25"), target, mass, cutoff)[0] == 0.5
    assert direct_tail(history.assign(dc_event=0), target, mass, cutoff)[0] < 0.5
    assert direct_tail(history, target, np.array([[1, 0, 0, 0]]), cutoff)[0] == 0


@pytest.mark.parametrize("mass", [[[0, 0, 0, 0.5]], [[-1, 0, 0, 2]], [[0, 0, 0, np.nan]]])
def test_invalid_probability_refused(mass):
    history, target, cutoff = frames()
    with pytest.raises(ValueError, match="probability"):
        direct_tail(history, target, np.asarray(mass), cutoff)


def test_duplicate_training_rows_refused():
    history, target, cutoff = frames()
    with pytest.raises(ValueError, match="Duplicate"):
        direct_tail(pd.concat([history, history]), target, np.array([[0, 0, 0, 1]]), cutoff)
