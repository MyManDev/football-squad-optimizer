"""Raw player priors and physical exposure pooling, using synthetic sources only."""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType

import numpy as np
import pytest
from tests.unit.test_football_unit_experiment import baseline
from tests.unit.test_football_unit_physical import fit as physical_fit
from tests.unit.test_football_unit_physical import physical_rows
from tests.unit.test_football_unit_replay import current_projection
from tests.unit.test_football_unit_strength import T, observations, projection, unit

from squadopt.experiments.football_unit_experiment import _result_receipt, unit_fixture_components
from squadopt.features.football_unit_inputs import ClubUnit, UnitPlayer
from squadopt.prediction.football_unit_strength import (
    UNIT_LEGACY_IDENTITY_POLICY,
    UNIT_PHYSICAL_MODEL_VERSION,
    UNIT_POOLED_FEATURE_VERSION,
    UNIT_POOLED_IDENTITY_POLICY,
    UNIT_POOLED_MODEL_VERSION,
    UNIT_POOLED_OBJECTIVE,
    FootballUnitStrengthModel,
    _canonical,
    pooled_identity_columns,
)


def fit(rows=None, **options):
    return physical_fit(rows, identity_policy=UNIT_POOLED_IDENTITY_POLICY, **options)


def bare_rows(seconds=600, *, goals=4):
    first, second = physical_rows()
    catalog = replace(first.catalog, attributes=(), player_attributes=())
    first = replace(
        first,
        catalog=catalog,
        minutes=seconds / 60,
        own_goals=goals,
        opponent_goals=seconds // 600,
        causal_baseline_own_goal_rate=10,
        causal_baseline_opponent_goal_rate=10,
        exposure_clock=replace(
            first.exposure_clock, end_seconds=seconds, actual_duration_seconds=6000
        ),
    )
    second = replace(
        second,
        catalog=catalog,
        start_minute=seconds / 60,
        minutes=(6000 - seconds) / 60,
        own=unit(1),
        own_goals=(6000 - seconds) // 600,
        opponent_goals=(6000 - seconds) // 600,
        causal_baseline_own_goal_rate=10,
        causal_baseline_opponent_goal_rate=10,
        exposure_clock=replace(
            second.exposure_clock,
            start_seconds=seconds,
            end_seconds=6000,
            actual_duration_seconds=6000,
        ),
    )
    return first, second


def bare_projection():
    p = current_projection()
    return replace(p, catalog=replace(p.catalog, attributes=(), player_attributes=()))


def test_identity_keeps_raw_scale_under_unequal_exposure_and_has_no_home_parameters():
    model = fit(bare_rows())
    identities = set(pooled_identity_columns(model.player_vocabulary))
    for index, name in enumerate(model.feature_contract):
        if name in identities:
            assert model._feature_scales[index] == 1
        else:
            assert model._feature_scales[index] == model._scaler.scale_[index]
        assert name.removeprefix("home_interaction:") not in identities or not name.startswith(
            "home_"
        )
    index = model.feature_contract.index("own_player_12")
    assert 0 < model._scaler.scale_[index] < 1
    p = bare_projection()
    x = model._relative(
        p.catalog,
        p.states[0].own,
        p.states[0].opponent,
        p.reference_own,
        p.reference_opponent,
        p.home,
    )
    assert model._transform(x).toarray()[0, index] == 1


def test_less_exposure_pools_same_observed_rate_more_strongly_without_a_threshold():
    rare, common = fit(bare_rows()), fit(bare_rows(2400, goals=16))
    p = bare_projection()
    rare_ratio = rare.predict(p).own_goal_rate / p.causal_baseline_own_goal_rate
    common_ratio = common.predict(p).own_goal_rate / p.causal_baseline_own_goal_rate
    assert 1 < rare_ratio < common_ratio < 4
    assert rare._training_offset_sum == common._training_offset_sum == 20
    assert rare.regularization == common.regularization == 0.1


def test_count_likelihood_gradient_has_exact_normalization_and_raw_identity_penalty():
    model = fit(bare_rows())
    # Four independently specified oriented rows: changed home/away, then neutral home/away.
    x = np.zeros((4, len(model.feature_contract)))
    for row, side in ((0, "own"), (1, "opponent")):
        x[row, model.feature_contract.index(f"{side}_player_11")] = -1
        x[row, model.feature_contract.index(f"{side}_player_12")] = 1
    offsets, goals = np.array([1.0, 1.0, 9.0, 9.0]), np.array([4.0, 1.0, 9.0, 9.0])
    beta = model._head.coef_
    gradient = x.T @ (offsets * np.exp(x @ beta) - goals) / offsets.sum() + 0.1 * beta
    assert np.max(np.abs(gradient)) < 1e-7
    result = model.predict(bare_projection())
    assert result.metadata["regularization_objective"] == UNIT_POOLED_OBJECTIVE
    assert result.metadata["training_offset_sum"] == 20
    assert result.metadata["raw_identity_count_prior_precision"] == 2


def test_splitting_identical_actual_exposure_does_not_add_support_or_change_fit():
    first, _ = bare_rows(3000, goals=10)
    whole = replace(
        first,
        minutes=100,
        own_goals=20,
        opponent_goals=10,
        exposure_clock=replace(first.exposure_clock, end_seconds=6000),
    )
    left = replace(
        whole,
        minutes=50,
        own_goals=10,
        opponent_goals=5,
        exposure_clock=replace(whole.exposure_clock, end_seconds=3000),
    )
    right = replace(
        left,
        start_minute=50,
        exposure_clock=replace(
            left.exposure_clock,
            start_seconds=3000,
            end_seconds=6000,
            interval_id="fixture1:3000:6000",
        ),
    )
    merged, split = fit((whole,)), fit((left, right))
    assert merged._training_offset_sum == split._training_offset_sum
    assert split._head.coef_ == pytest.approx(merged._head.coef_, abs=1e-10)
    assert split.predict(bare_projection()).own_goal_rate == pytest.approx(
        merged.predict(bare_projection()).own_goal_rate, abs=1e-10
    )


def test_shared_values_and_training_statistics_remain_identical_to_physical_v3():
    legacy, pooled = physical_fit(), fit()
    identities = set(pooled_identity_columns(pooled.player_vocabulary))
    row = physical_rows()[0]
    args = (row.catalog, row.own, row.opponent, row.reference_own, row.reference_opponent, row.home)
    old = dict(zip(legacy.feature_contract, legacy._relative(*args).toarray()[0], strict=True))
    new = dict(zip(pooled.feature_contract, pooled._relative(*args).toarray()[0], strict=True))
    assert all(value == old[name] for name, value in new.items())
    for index, name in enumerate(pooled.feature_contract):
        old_index = legacy.feature_contract.index(name)
        assert pooled._scaler.var_[index] == pytest.approx(legacy._scaler.var_[old_index])
        if name not in identities:
            assert pooled._feature_scales[index] == legacy._scaler.scale_[old_index]
    assert new["own_FWD_fm:all_attributes_unobserved"] == 1 / 11
    assert new["own_FWD_fm:finishing_residual_missing"] == 0


def test_neutral_reversal_and_pickle_preserve_the_new_policy():
    model = pickle.loads(pickle.dumps(fit()))
    p = current_projection()
    forward = model.predict(p)
    reverse = model.predict(
        replace(
            p,
            home=False,
            reference_own=p.reference_opponent,
            reference_opponent=p.reference_own,
            states=tuple(replace(s, own=s.opponent, opponent=s.own) for s in p.states),
            causal_baseline_own_goal_rate=p.causal_baseline_opponent_goal_rate,
            causal_baseline_opponent_goal_rate=p.causal_baseline_own_goal_rate,
        )
    )
    assert forward.own_goal_rate == reverse.opponent_goal_rate
    assert forward.opponent_goal_rate == reverse.own_goal_rate
    neutral = model.predict(
        replace(
            p,
            states=tuple(
                replace(s, own=p.reference_own, opponent=p.reference_opponent) for s in p.states
            ),
        )
    )
    assert neutral.own_goal_rate == p.causal_baseline_own_goal_rate
    assert neutral.opponent_goal_rate == p.causal_baseline_opponent_goal_rate
    assert forward.model_version == UNIT_POOLED_MODEL_VERSION
    assert forward.metadata["feature_version"] == UNIT_POOLED_FEATURE_VERSION
    assert json.loads(_result_receipt(forward))["model_version"] == UNIT_POOLED_MODEL_VERSION
    assert set(unit_fixture_components(baseline(p), [forward], season=p.season).model_version) == {
        UNIT_POOLED_MODEL_VERSION
    }


def test_unseen_identity_has_no_fitted_residual_and_missing_attributes_stay_unknown():
    model = fit(bare_rows())
    p = bare_projection()
    mappings = tuple(
        replace(m, source_player_id="13", player_id=13)
        for m in p.catalog.mappings
        if m.player_id == 11
    )
    c = replace(p.catalog, mappings=(*p.catalog.mappings, *mappings))
    unknown = ClubUnit(1, (*unit(1).players[:-1], UnitPlayer(13, "FWD")))
    raw = model._unit_values(c, unknown)
    assert 13 not in model._identity_indexes
    assert "own_player_13" not in model.feature_contract
    assert sum(raw.get(i, 0) for i in model._identity_indexes.values()) == 10


@pytest.mark.parametrize("value", [True, None, 0, "unknown", ""])
def test_identity_policy_requires_an_exact_supported_string(value):
    with pytest.raises(ValueError, match="identity"):
        physical_fit(identity_policy=value)


def test_new_policy_requires_the_selected_physical_and_missingness_contract():
    with pytest.raises(ValueError, match="physical exposure"):
        FootballUnitStrengthModel(
            observations(),
            cutoff=T + timedelta(days=50),
            identity_policy=UNIT_POOLED_IDENTITY_POLICY,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"identity_policy": "exposure_standardized_v1"},
        {"player_home_interactions": 0},
        {"scaling": "train-only exposure-weighted StandardScaler(with_mean=False)"},
        {"regularization_objective": "unnormalized count loss"},
        {"identity_prior": "known ability"},
        {"training_offset_sum": True},
        {"training_offset_sum": 0},
        {"raw_identity_count_prior_precision": 0.1},
        {"identity_feature_columns": ()},
        {"feature_scales": ()},
        {"training_scaler_scales": ()},
    ],
)
def test_receipt_refuses_inconsistent_prior_or_feature_declarations(changes):
    result = fit().predict(current_projection())
    with pytest.raises(ValueError):
        _result_receipt(replace(result, metadata=MappingProxyType({**result.metadata, **changes})))


@pytest.mark.parametrize(
    "kind", ["identity", "shared", "nan", "bool", "missing", "version", "home"]
)
def test_receipt_refuses_scale_tampering_missing_policy_and_wrong_version(kind):
    result = fit().predict(current_projection())
    meta = dict(result.metadata)
    if kind == "missing":
        del meta["identity_prior"]
    elif kind == "version":
        result = replace(result, model_version=UNIT_PHYSICAL_MODEL_VERSION)
    elif kind == "home":
        columns = (*result.feature_contract, "home_interaction:own_player_11")
        result = replace(result, feature_contract=columns)
        meta["feature_columns"] = columns
    else:
        scales = list(meta["feature_scales"])
        index = result.feature_contract.index(
            "own_player_11" if kind == "identity" else "own_FWD_fm:finishing_value"
        )
        scales[index] = (
            float("nan") if kind == "nan" else True if kind == "bool" else scales[index] * 2
        )
        meta["feature_scales"] = tuple(scales)
    with pytest.raises(ValueError):
        _result_receipt(replace(result, metadata=MappingProxyType(meta)))


def test_v1_default_metadata_and_physical_v3_predictions_remain_exact():
    for options in ({}, {"identity_policy": UNIT_LEGACY_IDENTITY_POLICY}):
        old = FootballUnitStrengthModel(observations(), cutoff=T + timedelta(days=50), **options)
        result = old.predict(projection())
        assert (
            hashlib.sha256(_canonical(dict(result.metadata)).encode()).hexdigest()
            == "e92bbc4d4ccf2311018468115fc5de56b3ec563a1964eefc77b5a910f39620e1"
        )
    default = physical_fit().predict(current_projection())
    explicit = physical_fit(identity_policy=UNIT_LEGACY_IDENTITY_POLICY).predict(
        current_projection()
    )
    assert default == explicit
    assert default.model_version == UNIT_PHYSICAL_MODEL_VERSION
    assert "identity_policy" not in default.metadata
    with pytest.raises(ValueError, match="explicit model"):
        _result_receipt(
            replace(
                default,
                metadata=MappingProxyType(
                    {**default.metadata, "identity_policy": UNIT_POOLED_IDENTITY_POLICY}
                ),
            )
        )
