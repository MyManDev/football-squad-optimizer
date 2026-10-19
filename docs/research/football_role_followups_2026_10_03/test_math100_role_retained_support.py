"""Synthetic-only preregistered checks; importing the operator never runs main."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

spec = importlib.util.spec_from_file_location('retained_support_experiment', Path(__file__).with_name('math100-role-retained-support.py'))
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)
from squadopt.prediction.football_features import FEATURES, RATE_LABELS, football_features
from squadopt.prediction.football_minutes_role import JointRoleMinutes


def rows():
    records = []
    for i, (start, minutes) in enumerate(((1, 40), (1, 80), (1, 90), (0, 10), (0, 65), (0, 90)) * 2):
        records.append({**dict.fromkeys(FEATURES, 0.), 'past_rows': float(i % 3),
                        'season': '2024-25', 'GW': 1, 'fixture': i + 1,
                        'player_code': i + 1, 'position': 'MID', 'starts': float(start),
                        'minutes': float(minutes), 'm_bin': 1 if minutes < 60 else 2 if minutes < 90 else 3,
                        'kickoff': pd.Timestamp('2024-09-01T15:00Z'),
                        'feature_cutoff': pd.Timestamp('2024-08-31T15:00Z')})
    return pd.DataFrame(records)


def feature_history(*, season='2024-25', minutes=90.):
    return pd.DataFrame([
        {**dict.fromkeys(RATE_LABELS, 0.), 'season': season, 'GW': 1, 'fixture': 1,
         'player_code': player, 'position': 'MID', 'club': club, 'opponent': opponent,
         'home': player == 1, 'kickoff': pd.Timestamp('2024-09-01T15:00Z') if season == '2024-25' else pd.Timestamp('2026-08-20T15:00Z'),
         'minutes': minutes, 'appeared': float(minutes > 0), 'long': float(minutes >= 60),
         'starts': float(minutes > 0), 'clean_sheets': 0., 'team_goals': 0., 'team_conceded': 0.,
         'defensive_contribution': np.nan, 'dc_event': np.nan}
        for player, club, opponent in ((1, 'A', 'B'), (2, 'B', 'A'))
    ])


def targets(player=1):
    return pd.DataFrame([{'season': '2026-27', 'GW': 2, 'player_code': player, 'position': 'MID',
                          'club': 'A', 'opponent': 'B', 'home': True}], index=[17])


def test_no_retained_history_is_zero_but_old_retained_season_is_present():
    history = feature_history()
    cutoff = pd.Timestamp('2026-08-22T12:00Z')
    missing = football_features(history, targets(999), cutoff)
    old = football_features(history, targets(), cutoff)
    assert missing.past_rows.iloc[0] == 0 and old.past_rows.iloc[0] == 1
    assert missing.season_rows.iloc[0] == old.season_rows.iloc[0] == 0
    assert experiment.retained_design(missing)[0, -1] == 0
    assert experiment.retained_design(old)[0, -1] == 1


def test_actual_current_nonappearance_is_history_not_an_appearance_indicator():
    history = feature_history(season='2026-27', minutes=0.)
    result = football_features(history, targets(), pd.Timestamp('2026-08-22T12:00Z'))
    assert result.past_rows.iloc[0] == result.season_rows.iloc[0] == 1
    assert result.past_apps.iloc[0] == 0
    assert experiment.retained_design(result)[0, -1] == 1


def test_target_label_changes_cannot_enter_design_and_future_history_is_refused():
    history, target, cutoff = feature_history(), targets(), pd.Timestamp('2026-08-22T12:00Z')
    before = football_features(history, target, cutoff)
    after = football_features(history, target.assign(starts=1, minutes=90, total_points=999), cutoff)
    assert_frame_equal(before, after, check_exact=True)
    with pytest.raises(ValueError, match='unavailable'):
        football_features(history.assign(kickoff=cutoff), target, cutoff)



def test_future_outcome_mutations_do_not_enter_causally_selected_history():
    cutoff = pd.Timestamp('2026-08-22T12:00Z')
    old = feature_history(season='2026-27', minutes=0.)
    future = feature_history(season='2026-27', minutes=90.).assign(
        GW=3, fixture=3, kickoff=pd.Timestamp('2026-08-23T15:00Z')
    )
    history = pd.concat([old, future], ignore_index=True)
    poisoned = pd.concat([old, future.assign(minutes=999., starts=1., appeared=1.)], ignore_index=True)
    left = history.loc[experiment.study._earlier(history, '2026-27', 2, cutoff)]
    right = poisoned.loc[experiment.study._earlier(poisoned, '2026-27', 2, cutoff)]
    assert_frame_equal(left, right, check_exact=True)
    before = football_features(left, targets(), cutoff)
    after = football_features(right, targets(), cutoff)
    np.testing.assert_array_equal(experiment.retained_design(before), experiment.retained_design(after))
    assert before.past_rows.iloc[0] == 1


def test_design_appends_only_binary_column_without_mutating_existing_features():
    frame = rows()
    saved = frame.copy(deep=True)
    actual = experiment.retained_design(frame)
    assert actual.shape == (len(frame), len(FEATURES) + 1)
    np.testing.assert_array_equal(actual[:, :-1], frame[list(FEATURES)].to_numpy(float))
    np.testing.assert_array_equal(actual[:, -1], frame.past_rows.gt(0).to_numpy(float))
    assert_frame_equal(frame, saved, check_exact=True)
    assert experiment.INDICATOR not in FEATURES


@pytest.mark.parametrize('past', [-1., .5, np.nan, np.inf])
def test_invalid_history_count_refused(past):
    with pytest.raises(ValueError):
        experiment.retained_design(rows().assign(past_rows=past))


@pytest.mark.parametrize('label', [0, 1])
def test_single_class_has_exact_native_constant_and_no_estimator_fit(label):
    frame = rows()
    head = experiment.RetainedHistoryHead(frame, np.full(len(frame), label))
    assert head.model is None
    np.testing.assert_array_equal(head.predict(frame), np.tile(np.eye(2)[label], (len(frame), 1)))


def test_missing_known_labels_copies_unchanged_native_fallback_without_fit():
    frame = rows().assign(starts=np.nan)
    base = SimpleNamespace(role_minutes=JointRoleMinutes(frame, cutoff=pd.Timestamp('2024-09-03T00:00Z')))
    attempts = []
    changed, metadata = experiment.candidate_model(base, frame, attempts.append)
    assert changed is not base and changed.role_minutes is not base.role_minutes
    assert changed.role_minutes.role is None and base.role_minutes.role is None
    assert attempts == [] and metadata['head_fit_attempts'] == 0
    assert metadata['status'] == 'unavailable_no_known_start_labels'


@pytest.mark.parametrize('q', [0., .6, 1.])
def test_candidate_changes_only_role_head_and_keeps_q_minute_heads_and_base(q):
    frame = rows()
    head = JointRoleMinutes(frame, cutoff=pd.Timestamp('2024-09-03T00:00Z'))
    base = SimpleNamespace(role_minutes=head)
    native_role = head.role
    saved_role = native_role.predict(frame)
    saved_conditional = {name: obj.predict(frame) for name, obj in head.conditional.items()}
    changed, metadata = experiment.candidate_model(base, frame)
    assert base.role_minutes.role is native_role
    assert changed.role_minutes.role is not native_role
    assert metadata['head_fit_attempts'] == metadata['estimator_fit_attempts'] == 1
    np.testing.assert_array_equal(native_role.predict(frame), saved_role)
    assert changed.role_minutes.means.keys() == head.means.keys()
    for key, value in head.means.items():
        np.testing.assert_array_equal(changed.role_minutes.means[key], value)
    for name, original in saved_conditional.items():
        assert changed.role_minutes.conditional[name] is not head.conditional[name]
        np.testing.assert_array_equal(changed.role_minutes.conditional[name].predict(frame), original)
    law = np.tile([1 - q, q / 4, q / 4, q / 2], (len(frame), 1))
    kwargs = dict(baseline_probabilities=law, baseline_minutes=np.array([0, 30, 75, 90]))
    before, after = head.predict(frame, **kwargs), changed.role_minutes.predict(frame, **kwargs)
    np.testing.assert_array_equal(before.appearance, after.appearance)
    np.testing.assert_array_equal(before.probabilities[:, 0], after.probabilities[:, 0])
    np.testing.assert_allclose(after.probabilities.sum(axis=1), 1)
    if q == 0:
        np.testing.assert_array_equal(after.expected_minutes, np.zeros(len(frame)))


def records():
    base, candidate = [], []
    for season, week in (*experiment.study.ORIGINS, *((experiment.study.CURRENT_SEASON, w) for w in range(1, 6))):
        for position in experiment.study.POSITIONS:
            row = {'fold': f'{season}-gw{week:02d}', 'position': position,
                   'arm': 'joint_role', 'rows': 5, 'role_known_rows': 4,
                   'role_unknown_rows': 1, 'role_scored_rows': 4,
                   'role_nll': 1., 'role_brier': 1., 'points_mae': 1., 'minutes_mae': 1.}
            base.append(row)
            candidate.append({**row, 'arm': experiment.ARM, 'role_nll': .99})
    return base, candidate


def test_full_equal_origin_acceptance_and_negative_candidates():
    base, candidate = records()
    assert experiment.acceptance(base, candidate)['accepted']
    identical = [{**r, 'arm': experiment.ARM} for r in base]
    assert not experiment.acceptance(base, identical)['accepted']
    worse_points = deepcopy(candidate)
    for row in worse_points:
        if row['position'] == 'ALL' and row['fold'].startswith('2026-27'):
            row['points_mae'] = 1.0001
    assert not experiment.acceptance(base, worse_points)['accepted']
    worse_position = deepcopy(candidate)
    for row in worse_position:
        if row['position'] == 'GK':
            row['role_brier'] = 1.010001
    assert not experiment.acceptance(base, worse_position)['accepted']


def test_missing_fold_or_population_mismatch_cannot_be_averaged_away():
    base, candidate = records()
    with pytest.raises(ValueError, match='thirteen'):
        experiment.acceptance(base, candidate[1:])
    altered = deepcopy(candidate)
    altered[0]['role_scored_rows'] = 3
    with pytest.raises(ValueError, match='populations'):
        experiment.acceptance(base, altered)
    absent = deepcopy(candidate)
    absent[0]['role_nll'] = None
    assert not experiment.acceptance(base, absent)['accepted']
    absent = deepcopy(candidate)
    absent[0]['points_mae'] = None
    assert not experiment.acceptance(base, absent)['accepted']


def test_zero_baseline_position_loss_allows_only_zero_candidate_loss():
    base, candidate = records()
    for row in base:
        if row['position'] == 'GK':
            row['role_brier'] = 0.
    for row in candidate:
        if row['position'] == 'GK':
            row['role_brier'] = 0.
    assert experiment.acceptance(base, candidate)['accepted']
    candidate[1]['role_brier'] = 1e-15
    assert not experiment.acceptance(base, candidate)['accepted']
