"""Synthetic parity for the retained-history head; no captured or archive inputs."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from tests.unit.test_football_development import football_fixture  # noqa: F401
from tests.unit.test_football_minutes_role import CUTOFF, training

from squadopt.prediction.football import (
    JOINT_ROLE_MODEL_VERSION,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
    FixtureFootballModel,
    JointRoleFootballModel,
    RetainedHistoryRoleFootballModel,
)
from squadopt.prediction.football_features import FEATURES, RATE_LABELS, football_features
from squadopt.prediction.football_minutes_role import (
    RETAINED_HISTORY_FEATURE,
    RETAINED_HISTORY_ROLE_FEATURE_VERSION,
    ROLE_MINUTE_VERSION,
    JointRoleMinutes,
    RetainedHistoryRoleMinutes,
    _matrix,
)


def retained_training():
    frame = training()
    frame["past_rows"] = np.resize(np.array([0.0, 1.0, 2.0, 10.0, 0.0, 100.0]), len(frame))
    return frame


class FrozenResearchHead:
    """The measured local head's design and estimator, independent of production."""

    def __init__(self, frame, labels):
        design = self.design(frame)
        self.constant = None
        self.model = None
        if not len(frame):
            self.constant = np.zeros(2)
        elif len(np.unique(labels)) == 1:
            self.constant = np.eye(2)[int(labels[0])]
        else:
            self.model = make_pipeline(
                StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=0)
            )
            self.model.fit(design, labels)

    @staticmethod
    def design(frame):
        values = frame.loc[:, list(FEATURES)].to_numpy(float, copy=True)
        past = frame.past_rows.to_numpy(float)
        if (
            not np.isfinite(values).all()
            or (past < 0).any()
            or not np.equal(past, np.floor(past)).all()
        ):
            raise ValueError("Invalid research role features.")
        return np.column_stack((values, (past > 0).astype(float)))

    def predict(self, frame):
        design = self.design(frame)
        if self.constant is not None:
            return np.tile(self.constant, (len(frame), 1))
        output = np.zeros((len(frame), 2))
        output[:, self.model[-1].classes_.astype(int)] = self.model.predict_proba(design)
        return output


def test_design_preserves_existing_features_and_adds_only_retained_history_indicator():
    frame = retained_training()
    saved = frame.copy(deep=True)
    matrix = _matrix(frame, retained_history=True)
    np.testing.assert_array_equal(matrix[:, :-1], _matrix(frame))
    np.testing.assert_array_equal(matrix[:, -1], frame.past_rows.gt(0).to_numpy(float))
    assert RETAINED_HISTORY_FEATURE not in FEATURES
    assert_frame_equal(frame, saved, check_exact=True)


@pytest.mark.parametrize("past", [-1.0, 0.5, np.nan, np.inf])
def test_invalid_history_counts_are_refused_even_for_a_constant_role(past):
    with pytest.raises(ValueError):
        RetainedHistoryRoleMinutes(training().assign(starts=1.0, past_rows=past), cutoff=CUTOFF)


@pytest.mark.parametrize("q", [0.0, 0.6, 1.0])
def test_known_label_head_matches_frozen_research_and_keeps_q_and_minute_heads(q):
    frame = retained_training()
    # Unknown positive rows and known nonappearance rows are not binary role labels.
    unknown = frame.iloc[:2].assign(starts=np.nan, fixture=lambda t: t.fixture + 1000)
    absent = frame.iloc[:2].assign(
        starts=0.0, minutes=0.0, m_bin=0, fixture=lambda t: t.fixture + 2000
    )
    frame = pd.concat([frame, unknown, absent], ignore_index=True)
    target = retained_training().iloc[:12].copy()
    original = JointRoleMinutes(frame, cutoff=CUTOFF)
    changed = RetainedHistoryRoleMinutes(frame, cutoff=CUTOFF)
    known = frame.minutes.gt(0) & frame.starts.notna()
    oracle = FrozenResearchHead(frame.loc[known], frame.loc[known, "starts"].to_numpy(np.int64))
    assert original.role is not None and changed.role is not None
    saved_original = original.role.predict(target).copy()
    np.testing.assert_array_equal(changed.role.predict(target), oracle.predict(target))
    assert changed.known_start_label_rows == original.known_start_label_rows == len(training())
    assert changed.unknown_start_label_rows == original.unknown_start_label_rows == 2
    for role in ("start", "cameo"):
        np.testing.assert_array_equal(
            changed.conditional[role].predict(target), original.conditional[role].predict(target)
        )
    for key in original.means:
        np.testing.assert_array_equal(changed.means[key], original.means[key])
    baseline = np.tile([1 - q, q / 4, q / 4, q / 2], (len(target), 1))
    options = dict(
        baseline_probabilities=baseline, baseline_minutes=np.array([0.0, 30.0, 75.0, 90.0])
    )
    before, after = original.predict(target, **options), changed.predict(target, **options)
    np.testing.assert_array_equal(after.probabilities[:, 0], before.probabilities[:, 0])
    np.testing.assert_array_equal(after.appearance, before.appearance)
    np.testing.assert_allclose(after.probabilities.sum(axis=1), 1.0)
    np.testing.assert_array_equal(original.role.predict(target), saved_original)
    if q == 0:
        np.testing.assert_array_equal(after.expected_minutes, np.zeros(len(target)))
    fields = changed.fields(after, index=target.index)
    assert fields.minute_role_version.eq(ROLE_MINUTE_VERSION).all()
    assert changed.metadata["role_feature_version"] == RETAINED_HISTORY_ROLE_FEATURE_VERSION
    assert changed.metadata["role_features"] == [*FEATURES, RETAINED_HISTORY_FEATURE]
    assert changed.metadata["retained_history_definition"] == "past_rows > 0"
    assert original.metadata["version"] == ROLE_MINUTE_VERSION
    assert "role_features" not in original.metadata


@pytest.mark.parametrize("label", [0.0, 1.0])
def test_constant_role_uses_no_estimator_and_has_exact_original_fallback(label):
    frame = retained_training().assign(starts=label)
    old, new = (
        JointRoleMinutes(frame, cutoff=CUTOFF),
        RetainedHistoryRoleMinutes(frame, cutoff=CUTOFF),
    )
    assert new.role.model is None
    np.testing.assert_array_equal(new.role.predict(frame), old.role.predict(frame))


def test_no_known_labels_preserves_entire_original_four_bin_law():
    frame = retained_training().assign(starts=np.nan)
    head = RetainedHistoryRoleMinutes(frame, cutoff=CUTOFF)
    assert head.role is None and not head.conditional
    baseline = np.tile([0.2, 0.1, 0.3, 0.4], (len(frame), 1))
    minutes = np.tile([0.0, 20.0, 70.0, 90.0], (len(frame), 1))
    result = head.predict(frame, baseline_probabilities=baseline, baseline_minutes=minutes)
    np.testing.assert_array_equal(result.probabilities, baseline)
    np.testing.assert_array_equal(result.minutes, minutes)
    assert not result.supported
    assert head.metadata["status"] == "unavailable_no_known_start_labels"


def feature_history(*, season="2024-25", minutes=90.0):
    return pd.DataFrame(
        [
            {
                **dict.fromkeys(RATE_LABELS, 0.0),
                "season": season,
                "GW": 1,
                "fixture": 1,
                "player_code": player,
                "position": "MID",
                "club": club,
                "opponent": opponent,
                "home": player == 1,
                "kickoff": pd.Timestamp("2024-09-01T15:00Z")
                if season == "2024-25"
                else pd.Timestamp("2026-08-20T15:00Z"),
                "minutes": minutes,
                "appeared": float(minutes > 0),
                "long": float(minutes >= 60),
                "starts": float(minutes > 0),
                "clean_sheets": 0.0,
                "team_goals": 0.0,
                "team_conceded": 0.0,
                "defensive_contribution": np.nan,
                "dc_event": np.nan,
            }
            for player, club, opponent in ((1, "A", "B"), (2, "B", "A"))
        ]
    )


def test_old_season_and_actual_nonappearance_count_as_retained_history_without_target_labels():
    target = pd.DataFrame(
        [
            {
                "season": "2026-27",
                "GW": 2,
                "player_code": 1,
                "position": "MID",
                "club": "A",
                "opponent": "B",
                "home": True,
            }
        ],
        index=[17],
    )
    cutoff = pd.Timestamp("2026-08-22T12:00Z")
    old = football_features(feature_history(), target, cutoff)
    missing = football_features(feature_history(), target.assign(player_code=999), cutoff)
    zero = football_features(feature_history(season="2026-27", minutes=0.0), target, cutoff)
    assert old.past_rows.iloc[0] == 1 and old.season_rows.iloc[0] == 0
    assert zero.past_rows.iloc[0] == 1 and zero.past_apps.iloc[0] == 0
    assert _matrix(old, retained_history=True)[0, -1] == 1
    assert _matrix(zero, retained_history=True)[0, -1] == 1
    assert _matrix(missing, retained_history=True)[0, -1] == 0
    poisoned = football_features(feature_history(), target.assign(starts=1, minutes=999), cutoff)
    assert_frame_equal(old, poisoned, check_exact=True)
    with pytest.raises(ValueError, match="unavailable"):
        football_features(feature_history().assign(kickoff=cutoff), target, cutoff)


def test_explicit_model_constructor_fits_base_and_selected_role_law_once(monkeypatch):
    calls = []

    def base(self, train, history, *, cutoff):
        calls.append(("base", train, history, cutoff))

    def roles(train, *, cutoff):
        calls.append(("retained_role", train, cutoff))
        return SimpleNamespace(
            metadata={
                "version": ROLE_MINUTE_VERSION,
                "role_feature_version": RETAINED_HISTORY_ROLE_FEATURE_VERSION,
            }
        )

    monkeypatch.setattr(FixtureFootballModel, "__init__", base)
    monkeypatch.setattr(RetainedHistoryRoleFootballModel, "role_minutes_type", staticmethod(roles))
    frame = retained_training()
    model = RetainedHistoryRoleFootballModel(frame, frame, cutoff=CUTOFF)
    assert [call[0] for call in calls] == ["base", "retained_role"]
    assert model.model_version == JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION
    assert JointRoleFootballModel.model_version == JOINT_ROLE_MODEL_VERSION
    assert JointRoleFootballModel.role_minutes_type is JointRoleMinutes


def test_named_model_matches_research_without_mutating_default(football_fixture):  # noqa: F811
    control, history, _, _, train = football_fixture
    default = JointRoleFootballModel(train, history, cutoff=control.cutoff)
    new = RetainedHistoryRoleFootballModel(train, history, cutoff=control.cutoff)
    target = train.tail(32)
    original = default.predict(target)
    oracle = deepcopy(default)
    known = train.minutes.gt(0) & train.starts.notna()
    oracle.role_minutes.role = FrozenResearchHead(
        train.loc[known], train.loc[known, "starts"].to_numpy(np.int64)
    )
    research = oracle.predict(target)
    actual = new.predict(target)
    identity_columns = ["model_version"]
    assert_frame_equal(
        actual.drop(columns=identity_columns),
        research.drop(columns=identity_columns),
        check_exact=True,
    )
    assert actual.model_version.eq(JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION).all()
    assert actual.minute_role_version.eq(ROLE_MINUTE_VERSION).all()
    assert new.role_metadata["role_feature_version"] == RETAINED_HISTORY_ROLE_FEATURE_VERSION
    assert_frame_equal(default.predict(target), original, check_exact=True)
    np.testing.assert_array_equal(actual.appearance_probability, original.appearance_probability)
    np.testing.assert_array_equal(actual.zero_probability, original.zero_probability)
    assert actual.availability_multiplier.eq(1.0).all()
