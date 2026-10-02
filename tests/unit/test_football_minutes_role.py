"""Offline joint roles: empirical labels, coherent components, and honest fallback."""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scipy.stats import nbinom
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION, JointRoleFootballModel
from squadopt.prediction.football_components import IDENTITY_COLUMNS, component_rows
from squadopt.prediction.football_features import FEATURES
from squadopt.prediction.football_minutes_role import (
    MINUTE_PRIOR_ROWS,
    ROLE_COMPONENT_COLUMNS,
    ROLE_METADATA_COLUMNS,
    JointRoleMinutes,
)


def training():
    rows = []
    for position in ("GK", "DEF", "MID", "FWD"):
        # Both roles have short/long/full support; short starters and long cameos
        # deliberately prove that minutes are not substituted for the starts label.
        for start, minutes in ((1, 40), (1, 80), (1, 90), (0, 10), (0, 65), (0, 90)):
            for _ in range(4):
                rows.append(
                    {
                        **dict.fromkeys(FEATURES, 0.0),
                        "season": "2024-25",
                        "fixture": len(rows) + 1,
                        "player_code": len(rows) + 1,
                        "position": position,
                        "starts": float(start),
                        "minutes": float(minutes),
                        "m_bin": 1 if minutes < 60 else 2 if minutes < 90 else 3,
                        "kickoff": pd.Timestamp("2024-09-01T15:00Z"),
                        "feature_cutoff": pd.Timestamp("2024-08-31T15:00Z"),
                    }
                )
    return pd.DataFrame(rows)


CUTOFF = pd.Timestamp("2024-09-02T00:00Z")


def predict(head, target=None, q=0.8):
    target = training().iloc[:4] if target is None else target
    baseline = np.tile([1 - q, q / 4, q / 4, q / 2], (len(target), 1))
    return head.predict(
        target, baseline_probabilities=baseline, baseline_minutes=np.array([0, 30, 75, 90])
    )


def test_joint_empirical_roles_and_bins_form_one_law_with_same_q():
    head = JointRoleMinutes(training(), cutoff=CUTOFF)
    state = predict(head)
    np.testing.assert_allclose(
        state.probabilities, np.tile([0.2, *([0.8 / 6] * 6)], (4, 1)), atol=1e-4
    )
    np.testing.assert_allclose(state.probabilities.sum(axis=1), 1)
    np.testing.assert_allclose(state.appearance, 0.8)
    fields = head.fields(state, index=pd.RangeIndex(4))
    np.testing.assert_allclose(
        fields.start_probability + fields.cameo_probability, state.appearance
    )
    np.testing.assert_allclose(
        fields.expected_minutes_if_appearance * state.appearance, state.expected_minutes
    )
    assert (state.p60 <= state.appearance).all()
    assert head.metadata["minute_prior_rows"] == MINUTE_PRIOR_ROWS


def test_position_role_bin_mean_uses_same_known_population_only():
    train = training()
    mask = train.position.eq("GK") & train.starts.eq(1) & train.m_bin.eq(1)
    train.loc[mask, "minutes"] = 50.0
    extra = train.iloc[:20].copy().assign(starts=np.nan, minutes=59.0, m_bin=1)
    extra["fixture"] += 1000
    extra["player_code"] += 1000
    head = JointRoleMinutes(pd.concat([train, extra]), cutoff=CUTOFF)
    # Four GK observations, pooled same starter/short-bin prior = (50+3*40)/4.
    expected = (4 * 50 + 10 * 42.5) / 14
    assert head.means["GK", "start"][0] == pytest.approx(expected)
    assert head.means["GK", "cameo"][0] == 10.0
    assert head.known_start_label_rows == len(train)
    assert head.unknown_start_label_rows == 20


@pytest.mark.parametrize("remove_column", [False, True])
def test_missing_start_labels_preserve_minute_law_with_null_roles(remove_column):
    train = training().assign(starts=np.nan)
    if remove_column:
        train = train.drop(columns="starts")
    head = JointRoleMinutes(train, cutoff=CUTOFF)
    state = predict(head)
    np.testing.assert_allclose(state.probabilities, np.tile([0.2, 0.2, 0.2, 0.4], (4, 1)))
    fields = head.fields(state, index=pd.RangeIndex(4))
    assert fields.start_probability.isna().all() and fields.cameo_probability.isna().all()
    assert fields.unknown_role_probability.eq(0.8).all()
    assert fields.minute_role_status.eq("unavailable_no_known_start_labels").all()


def test_target_outcomes_never_change_role_predictions_and_zero_q_stays_zero():
    head = JointRoleMinutes(training(), cutoff=CUTOFF)
    target = training().iloc[:4]
    poisoned = target.assign(starts=100, minutes=-999, m_bin=99)
    np.testing.assert_array_equal(
        predict(head, target).probabilities, predict(head, poisoned).probabilities
    )
    state = predict(head, target, q=0)
    assert np.all(state.probabilities[:, 0] == 1)
    assert np.all(state.expected_minutes == 0) and np.all(state.p60 == 0)


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda t: t.assign(starts=2), "binary"),
        (lambda t: t.assign(minutes=0, m_bin=0, starts=1), "positive"),
        (lambda t: t.assign(m_bin=0), "bins"),
        (lambda t: t.assign(kickoff=CUTOFF), "unavailable"),
    ],
)
def test_invalid_or_future_role_labels_are_refused(change, message):
    with pytest.raises(ValueError, match=message):
        JointRoleMinutes(change(training()), cutoff=CUTOFF)


@pytest.fixture(scope="module")
def candidate(football_fixture):  # noqa: F811
    control, history, _, _, train = football_fixture
    return control, JointRoleFootballModel(train, history, cutoff=control.cutoff), train.tail(64)


def test_all_scoring_components_use_joint_exposure_and_control_is_unchanged(candidate):
    control, model, target = candidate
    old = control.predict(target)
    output = model.predict(target)
    assert_frame_equal(control.predict(target), old)
    assert set(output.model_version) == {JOINT_ROLE_MODEL_VERSION}
    np.testing.assert_allclose(output.appearance_probability, old.appearance_probability)
    np.testing.assert_allclose(
        output.start_probability + output.cameo_probability, output.appearance_probability
    )
    for head in ("goals", "assists"):
        np.testing.assert_allclose(
            output.groupby([target.fixture, target.club])[head].sum(),
            old.groupby([target.fixture, target.club])[head].sum(),
        )
    cs = np.zeros(len(target))
    dc = np.zeros(len(target))
    threshold = np.where(target.position.eq("DEF"), 10, 12)
    for role in ("start", "cameo"):
        for b in (1, 2, 3):
            p = output[f"{role}_minute_probability_{b}"].to_numpy(float)
            minute = output[f"{role}_minute_value_{b}"].to_numpy(float)
            if b >= 2:
                cs += p * np.exp(-output.opponent_goal_rate.to_numpy(float) * minute / 90)
            mu = np.maximum(output.defcon_rate90.to_numpy(float) * minute / 90, 1e-12)
            size = output.defcon_dispersion.to_numpy(float)
            dc += p * nbinom.sf(threshold - 1, size, size / (size + mu))
    dc[target.position.eq("GK").to_numpy()] = 0
    np.testing.assert_allclose(output.clean_sheet_probability, cs)
    np.testing.assert_allclose(output.defcon_probability, dc)
    assert (output.clean_sheet_probability <= output.p60 + 1e-12).all()
    assert (output.defcon_probability <= output.appearance_probability + 1e-12).all()
    goal = target.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}).to_numpy(float)
    clean = target.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy(float)
    np.testing.assert_allclose(
        output.raw_expected_points,
        output.appearance_probability
        + output.p60
        + goal * output.goals
        + 3 * output.assists
        + clean * cs
        + 2 * dc
        + output.appearance_probability * output.residual_if_appearance,
    )


def test_component_export_keeps_joint_identity_and_rejects_marginal_tamper(candidate):
    _, model, target = candidate
    output = model.predict(target)
    frame = pd.concat([target[list(IDENTITY_COLUMNS)], output], axis=1)
    rows = component_rows(
        frame, model_version=JOINT_ROLE_MODEL_VERSION, players=set(target.player_code)
    )
    assert set((*ROLE_COMPONENT_COLUMNS, *ROLE_METADATA_COLUMNS)) <= set(rows[0])
    bad = frame.copy()
    bad["start_probability"] += 0.05
    with pytest.raises(ValueError, match="role mass"):
        component_rows(bad, model_version=JOINT_ROLE_MODEL_VERSION, players=set(target.player_code))


def test_model_missing_roles_keeps_all_original_component_values(football_fixture):  # noqa: F811
    control, history, _, _, train = football_fixture
    model = JointRoleFootballModel(train.assign(starts=np.nan), history, cutoff=control.cutoff)
    target = train.tail(32)
    old, actual = control.predict(target), model.predict(target)
    assert_frame_equal(actual[old.columns.drop("model_version")], old.drop(columns="model_version"))
    assert actual.start_probability.isna().all()
    assert model.role_metadata["known_start_label_rows"] == 0
