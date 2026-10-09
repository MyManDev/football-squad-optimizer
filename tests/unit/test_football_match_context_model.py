"""Synthetic learned-head sensitivity, without a real fit or outcome measurement."""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, FixtureFootballModel
from squadopt.prediction.football_features import FEATURES, TEAM_FEATURES
from squadopt.prediction.football_match_context import (
    MATCH_CONTEXT_MODEL_VERSION,
    MatchContextFootballModel,
    match_context_features,
    match_context_metadata,
)
from squadopt.prediction.football_match_context_features import (
    CONTEXT_FEATURES,
    CONTEXT_TEAM_FEATURES,
)

pytest_plugins = ("tests.unit.test_football_development",)


@pytest.fixture(scope="module")
def synthetic_heads(football_fixture):
    _, original_history, _, _, original_train = football_fixture
    history = original_history.assign(
        season="2024-25", club=original_history.club + 1, opponent=original_history.opponent + 1
    )
    train = original_train.assign(
        season="2024-25", club=original_train.club + 1, opponent=original_train.opponent + 1
    )
    # Controlled synthetic covariates test whether the new heads consume their
    # declared columns. They are not recorded historical features or an evaluation.
    context = pd.DataFrame(0.0, index=train.index, columns=CONTEXT_FEATURES)
    context["player_pl_7d_minutes"] = 270.0 - train.m_bin.to_numpy(float) * 90.0
    context["own_venue_gf"] = train.team_goals.to_numpy(float) + 0.1
    context["opp_venue_gf"] = train.team_goals.to_numpy(float) + 0.1
    train = pd.concat([train, context], axis=1)
    cutoff = history.kickoff.max() + pd.Timedelta(days=1)
    return MatchContextFootballModel(train, history, cutoff=cutoff), train, history


def target_pair(train):
    rows = train.loc[train.GW.eq(train.GW.max()) & train.club.isin((1, 2))].copy()
    rows["GW"] = 17
    rows["fixture"] = 170
    rows["kickoff"] = rows.kickoff + pd.Timedelta(days=7)
    return rows


def test_calendar_workload_changes_fitted_minutes_without_second_eligibility(synthetic_heads):
    model, train, _ = synthetic_heads
    target = target_pair(train)
    rested = target.assign(player_pl_7d_minutes=0.0)
    loaded = target.assign(player_pl_7d_minutes=270.0)
    low, high = model.predict(rested), model.predict(loaded)
    assert (low.expected_minutes > high.expected_minutes).all()
    assert (low.appearance_probability > high.appearance_probability).all()
    assert not np.allclose(low.expected_points, high.expected_points)
    assert low.availability_multiplier.eq(1.0).all()
    assert high.availability_multiplier.eq(1.0).all()
    assert low.model_version.eq(MATCH_CONTEXT_MODEL_VERSION).all()


def test_opponent_venue_strength_changes_concessions_and_clean_sheet_points(synthetic_heads):
    model, train, _ = synthetic_heads
    target = target_pair(train)
    weaker = target.assign(own_venue_gf=0.1, opp_venue_gf=0.1)
    stronger = target.assign(own_venue_gf=0.1, opp_venue_gf=2.1)
    left, right = model.predict(weaker), model.predict(stronger)
    assert (left.opponent_goal_rate < right.opponent_goal_rate).all()
    # The minute head can also consume club context; components remain coherent.
    assert not np.allclose(left.clean_sheet_probability, right.clean_sheet_probability)
    assert not np.allclose(left.expected_points, right.expected_points)


@pytest.mark.parametrize("field", [c for c in CONTEXT_TEAM_FEATURES if c.startswith("own_")])
def test_every_own_opponent_context_field_reverses_with_the_fixture(
    synthetic_heads, monkeypatch, field
):
    model, train, _ = synthetic_heads
    target = target_pair(train)
    opposite = "opp_" + field.removeprefix("own_")
    target[field], target[opposite] = 0.0, 1.0
    own_index, opp_index = model.team_features.index(field), model.team_features.index(opposite)

    class AsymmetricTeamHead:
        def predict(self, values):
            return np.exp(0.05 * (2 * values[:, own_index] + values[:, opp_index]))

    # A deterministic asymmetric head exposes every reversal, including columns
    # whose coefficient happened to be zero in the fitted synthetic sample.
    monkeypatch.setattr(model, "team", AsymmetricTeamHead())
    output = model.predict(target)
    other = target.copy()
    for column in model.team_features:
        if column.startswith("own_"):
            counterpart = "opp_" + column.removeprefix("own_")
            other[column] = target[counterpart].to_numpy()
            other[counterpart] = target[column].to_numpy()
    other["home"] = 1.0 - target.home.to_numpy()
    swapped = model.predict(other)
    np.testing.assert_array_equal(output.team_goal_rate, swapped.opponent_goal_rate)
    np.testing.assert_array_equal(output.opponent_goal_rate, swapped.team_goal_rate)


@pytest.mark.parametrize("steps", [1, True, -1, 0.5])
def test_match_context_does_not_claim_role_transition_variant(synthetic_heads, steps):
    model, train, _ = synthetic_heads
    with pytest.raises(ValueError, match="role transitions"):
        model.predict(target_pair(train), role_steps=steps)


def test_base_feature_heads_and_identity_remain_unchanged(football_fixture):
    model, _, _, _, train = football_fixture
    assert FixtureFootballModel.minute_features == FEATURES
    assert FixtureFootballModel.team_features == TEAM_FEATURES
    assert model.predict(train.iloc[:8]).model_version.eq(FOOTBALL_MODEL_VERSION).all()
    metadata = match_context_metadata()
    assert metadata["residual_features"] == list(FEATURES)
    assert metadata["defensive_action_features"] == list(FEATURES)
    metadata["context_features"]["features"].clear()
    assert match_context_metadata()["context_features"]["features"]


def test_combined_feature_builder_ignores_target_week_and_target_labels(synthetic_heads):
    model, _, history = synthetic_heads
    target = history.loc[history.GW.eq(16)].copy()
    cutoff = model.cutoff
    target["fixture"] += 1000
    target["kickoff"] = cutoff + pd.Timedelta(days=1)
    with_week = match_context_features(history, target, cutoff)
    without_week = match_context_features(history.loc[history.GW.lt(16)], target, cutoff)
    poisoned = match_context_features(
        history,
        target.assign(minutes=999, team_goals=-999, expected_goals="unreadable", starts=1),
        cutoff,
    )
    assert_frame_equal(with_week, without_week)
    assert_frame_equal(with_week, poisoned)
    assert model.model_version == MATCH_CONTEXT_MODEL_VERSION


def test_empty_history_requires_its_normalized_column_contract(synthetic_heads):
    model, train, history = synthetic_heads
    target = target_pair(train)
    with pytest.raises(ValueError, match="normalized football history"):
        match_context_features(pd.DataFrame(), target, model.cutoff)
    empty = match_context_features(history.iloc[:0], target, model.cutoff)
    assert np.isfinite(empty.to_numpy(float)).all()
    assert empty.past_rows.eq(0).all()
    assert empty.own_pl_match_history_missing.eq(1).all()


def test_mixed_target_weeks_keep_each_causal_history_and_repeated_index(synthetic_heads):
    model, _, history = synthetic_heads
    early = history.loc[history.GW.eq(12)].iloc[:4].copy()
    later = history.loc[history.GW.eq(16)].iloc[:4].copy()
    target = pd.concat([later, early], ignore_index=True)
    target.index = [7, 8, 7, 9, 7, 8, 7, 9]
    combined = match_context_features(history, target, model.cutoff)
    expected_later = match_context_features(history, target.iloc[:4], model.cutoff)
    expected_early = match_context_features(history, target.iloc[4:], model.cutoff)
    assert_frame_equal(combined.iloc[:4], expected_later)
    assert_frame_equal(combined.iloc[4:], expected_early)
    assert combined.index.tolist() == target.index.tolist()
    assert combined.past_rows.iloc[0] > combined.past_rows.iloc[4]
