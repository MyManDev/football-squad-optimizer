"""Sequential exposure probabilities remain coherent, including absent categories."""

import numpy as np
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.experiments.football_minutes import (
    MODEL_ID,
    SequentialMinuteForecast,
    SequentialMinutes,
)


def test_constant_features_recover_empirical_category_probabilities():
    labels = np.array([0] * 40 + [1] * 10 + [2] * 20 + [3] * 30)
    head = SequentialMinutes().fit(np.zeros((100, 2)), labels)
    mass = head.predict_proba(np.zeros((3, 2)))
    np.testing.assert_allclose(mass, np.tile([0.4, 0.1, 0.2, 0.3], (3, 1)), atol=1e-4)
    np.testing.assert_allclose(mass.sum(axis=1), 1)


@pytest.mark.parametrize("category", range(4))
def test_single_category_does_not_invent_unobserved_exposure(category):
    head = SequentialMinutes().fit(np.zeros((8, 2)), np.full(8, category))
    expected = np.zeros((2, 4))
    expected[:, category] = 1
    np.testing.assert_array_equal(head.predict_proba(np.ones((2, 2))), expected)


def test_invalid_training_and_prediction_are_refused():
    with pytest.raises(ValueError, match="labels"):
        SequentialMinutes().fit(np.ones((2, 2)), np.array([0, 4]))
    head = SequentialMinutes().fit(np.ones((2, 2)), np.array([0, 1]))
    with pytest.raises(ValueError, match="invalid"):
        head.predict_proba(np.array([[np.nan, 1]]))


def test_new_identity_label_independence_and_control_immutability(football_fixture):  # noqa: F811
    control, _, _, _, train = football_fixture
    old_head = control.minutes
    candidate = SequentialMinuteForecast(control, train)
    target = train.tail(64).copy()
    first = candidate.predict(target)
    assert set(first.model_version) == {MODEL_ID}
    assert control.minutes is old_head
    target["m_bin"] = 0
    target["minutes"] = 0
    target["total_points"] = 999
    assert_frame_equal(first, candidate.predict(target))
    with pytest.raises(ValueError, match="unavailable"):
        SequentialMinuteForecast(control, train.assign(kickoff=control.cutoff))
