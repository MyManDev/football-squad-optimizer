"""Synthetic-only tests for the isolated one-candidate operator. No real fit/data."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location(
    'role_temperature_experiment', Path(__file__).with_name('math100-role-temperature.py'))
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)
from squadopt.prediction.football_minutes_role import JointRoleMinutes


def train_world():
    rows = []
    for week in range(1, 9):
        for player in range(40):
            kickoff = pd.Timestamp('2024-08-01T15:00Z') + pd.Timedelta(weeks=week)
            rows.append({'season': '2024-25', 'GW': week, 'player_code': player,
                         'minutes': 75, 'starts': player % 2, 'kickoff': kickoff,
                         'feature_cutoff': kickoff - pd.Timedelta(minutes=90),
                         'role_feature': .9 if player % 4 else .1})
    return pd.DataFrame(rows)


class Head:
    def __init__(self, frame, labels, classes):
        assert len(frame) >= 100 and classes == 2
        assert frame.GW.max() == 4
        assert set(labels) == {0, 1}

    def predict(self, frame):
        r = frame.role_feature.to_numpy(float)
        return np.column_stack((1-r, r))


def outer_cutoff(frame):
    return frame.kickoff.max() + pd.Timedelta(days=7)


def test_temporal_prefix_and_last_four_groups_have_one_logged_fit():
    frame = train_world()
    seen = []
    result = experiment.inner_temperature(frame, outer_cutoff(frame), seen.append, Head)
    assert result['validation_groups'] == [['2024-25', w] for w in range(5, 9)]
    assert result['prefix_known_rows'] == 160
    assert result['validation_known_rows'] == 160
    assert result['validation_class_counts'] == [80, 80]
    assert result['inner_role_fits'] == len(seen) == 1
    assert result['inner_cutoff'] == (frame.loc[frame.GW.eq(5), 'kickoff'].min()
                                      - pd.Timedelta(minutes=90)).isoformat()
    assert .5 <= result['beta'] <= 1 and 1 <= result['temperature'] <= 2
    assert result['inner_candidate_nll'] <= result['inner_base_nll']


def test_outer_target_labels_cannot_enter_temperature_and_future_train_is_rejected():
    frame = train_world()
    target = frame.iloc[:4].assign(GW=9, kickoff=outer_cutoff(frame), starts=0)
    first = experiment.inner_temperature(frame, outer_cutoff(frame), head_factory=Head)
    target['starts'] = 1  # No outer targets enter inner_temperature's API.
    second = experiment.inner_temperature(frame, outer_cutoff(frame), head_factory=Head)
    assert first == second
    with pytest.raises(ValueError, match='future'):
        experiment.inner_temperature(pd.concat([frame, target]), outer_cutoff(frame),
                                     head_factory=Head)


def test_settlement_boundary_is_excluded_from_prefix():
    frame = train_world()
    inner = frame.loc[frame.GW.eq(5), 'kickoff'].min() - pd.Timedelta(minutes=90)
    frame.loc[frame.GW.eq(4), 'kickoff'] = inner - pd.Timedelta(hours=3)
    captured = []

    def head(frame, labels, classes):
        captured.append(frame.copy())
        return Head(frame.assign(GW=4), labels, classes)

    result = experiment.inner_temperature(frame, outer_cutoff(frame), head_factory=head)
    assert result['prefix_known_rows'] == 120
    assert len(captured) == 1 and captured[0].GW.max() == 3


@pytest.mark.parametrize('case', ['empty', 'few_groups', 'few_rows', 'constant_prefix', 'few_val_label'])
def test_unsupported_support_never_fits_and_returns_identity(case):
    frame = train_world()
    cutoff = outer_cutoff(frame)
    if case == 'empty':
        frame = frame.iloc[:0]
    elif case == 'few_groups':
        frame = frame.loc[frame.GW.le(4)]
    elif case == 'few_rows':
        frame = frame.groupby('GW').head(8)
    elif case == 'constant_prefix':
        frame.loc[frame.GW.le(4), 'starts'] = 1
    else:
        frame.loc[frame.GW.ge(5), 'starts'] = 1

    def refuse(*args):
        pytest.fail('Unavailable calibration must not fit or log a fit.')

    result = experiment.inner_temperature(frame, cutoff, refuse, refuse)
    assert result['beta'] == result['temperature'] == 1
    assert result['status'].startswith('unavailable_') and result['inner_role_fits'] == 0


def test_bisection_solves_known_scalar_optimum_without_a_grid():
    p = np.tile([.1, .9], (100, 1))
    y = np.array([1]*80 + [0]*20)
    expected = np.log(4) / np.log(9)
    result = experiment.choose_beta(p, y)
    assert result['beta'] == pytest.approx(expected, abs=2e-14)
    assert result['inner_candidate_nll'] < result['inner_base_nll']
    assert experiment.choose_beta(p, np.array([1]*95+[0]*5))['beta'] == 1
    assert experiment.choose_beta(p, np.array([1]*50+[0]*50))['beta'] == .5


def test_exact_endpoints_and_unsupported_wrong_endpoint_are_not_smoothed():
    p = np.array([[1., 0.], [0., 1.], [.2, .8]])
    result = experiment.temperature_probabilities(p, .5)
    assert np.array_equal(result[:2], p[:2])
    assert np.array_equal(experiment.temperature_probabilities(p, 1), p)
    assert experiment.choose_beta(p[:2], np.array([0, 1]))['status'] == 'unavailable_no_interior_probability'
    result = experiment.choose_beta(p, np.array([1, 1, 1]))
    assert result['status'] == 'unavailable_wrong_exact_endpoint'
    assert result['beta'] == 1


def test_real_joint_probability_composition_preserves_q_and_conditional_minutes(monkeypatch):
    class Fixed:
        def __init__(self, values):
            self.values = np.asarray(values, float)

        def predict(self, target):
            return np.tile(self.values, (len(target), 1))

    role = JointRoleMinutes.__new__(JointRoleMinutes)
    role.supported = True
    role.role = Fixed([.1, .9])
    role.conditional = {'start': Fixed([.1, .2, .7]), 'cameo': Fixed([.8, .2, 0.])}
    role.means = {('MID', 'start'): np.array([45., 75., 90.]),
                  ('MID', 'cameo'): np.array([15., 70., 90.])}
    target = pd.DataFrame({'position': ['MID']*3})
    baseline = np.array([[1., 0, 0, 0], [.25, .25, .25, .25], [0, .2, .3, .5]])
    means = np.array([0., 30., 75., 90.])
    original = role.role
    before = role.predict(target, baseline_probabilities=baseline, baseline_minutes=means)
    role.role = experiment.TemperatureHead(original, .5)
    after = role.predict(target, baseline_probabilities=baseline, baseline_minutes=means)
    role.role = original
    np.testing.assert_array_equal(before.appearance, after.appearance)
    np.testing.assert_array_equal(before.probabilities[:, 0], after.probabilities[:, 0])
    np.testing.assert_array_equal(before.minutes, after.minutes)
    np.testing.assert_allclose(after.probabilities.sum(1), 1)
    assert after.probabilities[1, 1:4].sum() < before.probabilities[1, 1:4].sum()
    assert role.role is original

    class ScorePath:
        @staticmethod
        def predict(model, selected):
            state = model.role_minutes.predict(selected, baseline_probabilities=baseline,
                                              baseline_minutes=means)
            return pd.DataFrame({'appearance_probability': state.appearance,
                                 'zero_probability': state.probabilities[:, 0]})

    monkeypatch.setattr(experiment, 'JointRoleFootballModel', ScorePath)
    model = SimpleNamespace(role_minutes=role)
    changed = experiment.calibrated_prediction(model, target, .5)
    assert role.role is original
    np.testing.assert_array_equal(changed.appearance_probability, before.appearance)
    assert changed.model_version.eq(experiment.EXPERIMENT).all()
    with pytest.raises(ValueError, match='role_steps=0'):
        experiment.calibrated_prediction(model, target, .5, role_steps=1)
    assert role.role is original


def test_acceptance_requires_all_metrics_including_small_position_regression():
    base, changed = [], []
    for season, weeks in [('2023-24', [11, 19, 27, 35]), ('2024-25', [11, 19, 27, 35]),
                          ('2026-27', range(1, 6))]:
        for week in weeks:
            for position in experiment.study.POSITIONS:
                row = {'fold': f'{season}-gw{week:02d}', 'position': position,
                       'arm': 'joint_role', 'role_nll': .5, 'role_brier': .3,
                       'rows': 100, 'role_known_rows': 100, 'role_unknown_rows': 0,
                       'role_scored_rows': 100,
                       'points_mae': 1.5, 'minutes_mae': 15.}
                base.append(row)
                changed.append({**row, 'arm': experiment.ARM, 'role_nll': .49})
    assert experiment.acceptance(base, changed)['accepted']
    complete_first = changed[0].copy()
    changed[0]['role_nll'] = None
    assert not experiment.acceptance(base, changed)['accepted']
    changed[0] = complete_first.copy()
    changed[0]['role_scored_rows'] = 99
    assert not experiment.acceptance(base, changed)['accepted']
    changed[0] = complete_first.copy()
    changed[0]['points_mae'] = None
    assert not experiment.acceptance(base, changed)['accepted']
    changed[0] = complete_first
    for row in changed:
        if row['position'] == 'GK':
            row['role_nll'] = .5051
    assert not experiment.acceptance(base, changed)['accepted']
