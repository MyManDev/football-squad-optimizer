"""Source-level absence, partial profiles and representation-invariant priors."""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType

import pytest
from tests.unit.test_football_unit_experiment import baseline
from tests.unit.test_football_unit_strength import T, observations, projection, unit

from squadopt.experiments.football_unit_experiment import _result_receipt, unit_fixture_components
from squadopt.features.football_unit_inputs import NumericAttributeSpec, PlayerAttributes
from squadopt.prediction.football_unit_strength import (
    UNIT_FEATURE_VERSION,
    UNIT_LEGACY_MISSINGNESS_POLICY,
    UNIT_MODEL_VERSION,
    UNIT_SOURCE_MISSINGNESS_FEATURE_VERSION,
    UNIT_SOURCE_MISSINGNESS_MODEL_VERSION,
    UNIT_SOURCE_MISSINGNESS_POLICY,
    FootballUnitStrengthModel,
    _canonical,
)


def traits(catalog, count=2, *, two_sources=False, partial=False):
    source_ids = ("synthetic", "other") if two_sources else ("synthetic",)
    specs = tuple(
        NumericAttributeSpec(f"trait_{i:02d}", source_id, 0, 20, "synthetic rating", "Test value")
        for source_id in source_ids
        for i in range(count)
    )
    mappings = tuple(
        replace(m, source_id=source_id) for source_id in source_ids for m in catalog.mappings
    )
    snapshots = []
    for mapping in mappings:
        values = [0.0] * count
        if partial and mapping.player_id in (11, 12):
            if mapping.source_id == "synthetic":
                values = [None, None] if mapping.player_id == 11 else [0.0, None]
            else:
                values = [3.0, None] if mapping.player_id == 11 else [None, None]
        elif mapping.player_id == 12:
            values = [None] * count
        snapshots.append(
            PlayerAttributes(
                mapping.source_id,
                mapping.source_player_id,
                tuple((f"trait_{i:02d}", value) for i, value in enumerate(values)),
            )
        )
    return replace(
        catalog,
        sources=tuple(replace(catalog.sources[0], source_id=s) for s in source_ids),
        attributes=specs,
        mappings=mappings,
        player_attributes=tuple(snapshots),
    )


def fit(count=2, **options):
    rows = tuple(replace(o, catalog=traits(o.catalog, count, **options)) for o in observations())
    return FootballUnitStrengthModel(
        rows, cutoff=T + timedelta(days=50), missingness_policy=UNIT_SOURCE_MISSINGNESS_POLICY
    )


def target(count=2, **options):
    p = projection()
    return replace(p, catalog=traits(p.catalog, count, **options))


def test_sources_separate_absence_from_partial_profiles_and_observed_zero():
    model = fit(two_sources=True, partial=True)
    p = target(two_sources=True, partial=True)
    values = dict(
        zip(
            model.feature_contract,
            model._relative(
                p.catalog,
                p.states[0].own,
                p.states[0].opponent,
                p.reference_own,
                p.reference_opponent,
                p.home,
            ).toarray()[0],
            strict=True,
        )
    )
    expected = {
        "own_FWD_synthetic:all_attributes_unobserved": -1 / 11,
        "own_FWD_other:all_attributes_unobserved": 1 / 11,
        "own_FWD_synthetic:trait_00_residual_missing": 0,
        "own_FWD_synthetic:trait_01_residual_missing": 1 / 11,
        "own_FWD_other:trait_00_residual_missing": 0,
        "own_FWD_other:trait_01_residual_missing": -1 / 11,
        "own_FWD_synthetic:trait_00_value": 0,
        "own_FWD_other:trait_00_value": -3 / 11,
    }
    for name, value in expected.items():
        assert values[name] == pytest.approx(value)
        assert values[f"home_interaction:{name}"] == pytest.approx(value)
    assert p.catalog.value(12, p.catalog.attributes[1]) is None
    result = model.predict(p)
    assert result.metadata["source_attribute_groups"] == (
        ("other", ("trait_00", "trait_01")),
        ("synthetic", ("trait_00", "trait_01")),
    )
    assert result.model_version == UNIT_SOURCE_MISSINGNESS_MODEL_VERSION
    assert result.metadata["feature_version"] == UNIT_SOURCE_MISSINGNESS_FEATURE_VERSION


def test_missing_source_snapshot_and_explicit_none_profile_have_identical_features():
    model = fit()
    p = target()
    absent = replace(
        p.catalog,
        player_attributes=tuple(
            row for row in p.catalog.player_attributes if row.source_player_id != "12"
        ),
    )
    assert model._unit_values(absent, unit(1, replacement=True)) == model._unit_values(
        p.catalog, unit(1, replacement=True)
    )
    assert model.predict(replace(p, catalog=absent)).own_goal_rate == model.predict(p).own_goal_rate


def test_full_absence_prior_is_invariant_to_one_versus_47_zero_numeric_traits():
    one, many = fit(1), fit(47)
    a, b = one.predict(target(1)), many.predict(target(47))
    assert a.own_goal_rate == pytest.approx(b.own_goal_rate, rel=1e-12)
    assert a.opponent_goal_rate == pytest.approx(b.opponent_goal_rate, rel=1e-12)
    assert one.regularization == many.regularization == 0.1
    for model, p in ((one, target(1)), (many, target(47))):
        values = model._unit_values(p.catalog, p.states[0].own)
        columns = model._base_columns[: model._unit_width]
        assert (
            sum(
                value != 0
                for index, value in values.items()
                if columns[index].endswith(":all_attributes_unobserved")
            )
            == 1
        )
        assert not any(
            value != 0
            for index, value in values.items()
            if columns[index].endswith("_residual_missing")
        )


def test_numeric_values_are_unchanged_by_new_missingness_representation():
    legacy = FootballUnitStrengthModel(observations(), cutoff=T + timedelta(days=50))
    current = FootballUnitStrengthModel(
        observations(),
        cutoff=T + timedelta(days=50),
        missingness_policy=UNIT_SOURCE_MISSINGNESS_POLICY,
    )
    p = projection()
    for own in (unit(1), unit(1, replacement=True)):
        old = {
            legacy._base_columns[i]: value
            for i, value in legacy._unit_values(p.catalog, own).items()
            if legacy._base_columns[i].endswith("_value")
        }
        new = {
            current._base_columns[i]: value
            for i, value in current._unit_values(p.catalog, own).items()
            if current._base_columns[i].endswith("_value")
        }
        assert new == old


def test_reference_neutrality_reversal_and_pickle_preserve_new_policy():
    model = pickle.loads(pickle.dumps(fit()))
    p = target()
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


def test_default_and_explicit_legacy_metadata_remain_frozen():
    rows, cutoff = observations(), T + timedelta(days=50)
    for options in ({}, {"missingness_policy": UNIT_LEGACY_MISSINGNESS_POLICY}):
        model = FootballUnitStrengthModel(rows, cutoff=cutoff, **options)
        result = model.predict(projection())
        assert result.model_version == UNIT_MODEL_VERSION
        assert hashlib.sha256(_canonical(dict(result.metadata)).encode()).hexdigest() == (
            "e92bbc4d4ccf2311018468115fc5de56b3ec563a1964eefc77b5a910f39620e1"
        )
        # Existing persisted v1 objects lack the new instance field.
        del model.missingness_policy
        assert model.predict(projection()).own_goal_rate == result.own_goal_rate


@pytest.mark.parametrize("policy", [None, True, 1, "unknown", ""])
def test_missingness_policy_is_strict(policy):
    with pytest.raises(ValueError, match="missingness"):
        FootballUnitStrengthModel(
            observations(), cutoff=T + timedelta(days=50), missingness_policy=policy
        )


def test_new_result_receipt_and_private_adapter_retain_new_version():
    p = target()
    result = fit().predict(p)
    receipt = json.loads(_result_receipt(result))
    assert receipt["model_version"] == UNIT_SOURCE_MISSINGNESS_MODEL_VERSION
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    assert set(components.model_version) == {UNIT_SOURCE_MISSINGNESS_MODEL_VERSION}


@pytest.mark.parametrize(
    "mutation",
    [
        "policy",
        "groups",
        "all_semantics",
        "residual_semantics",
        "columns",
        "feature_version",
        "model_version",
        "strip_contract",
        "alpha",
    ],
)
def test_result_boundary_refuses_source_feature_contract_tampering(mutation):
    result = fit().predict(target())
    metadata = dict(result.metadata)
    if mutation == "policy":
        metadata["missingness_policy"] = UNIT_LEGACY_MISSINGNESS_POLICY
    elif mutation == "groups":
        metadata["source_attribute_groups"] = ()
    elif mutation == "all_semantics":
        metadata["all_unobserved_semantics"] = "FM UID missing"
    elif mutation == "residual_semantics":
        metadata["residual_missingness_semantics"] = "all missing values"
    elif mutation == "columns":
        columns = tuple(x.replace("residual_missing", "missing") for x in result.feature_contract)
        metadata["feature_columns"] = columns
        result = replace(result, feature_contract=columns)
    elif mutation == "feature_version":
        metadata["feature_version"] = UNIT_FEATURE_VERSION
    elif mutation == "model_version":
        result = replace(result, model_version=UNIT_MODEL_VERSION)
    elif mutation == "alpha":
        metadata["regularization"] = 0.2
    else:
        for key in (
            "missingness_policy",
            "source_attribute_groups",
            "all_unobserved_semantics",
            "residual_missingness_semantics",
        ):
            metadata.pop(key)
        metadata["feature_version"] = UNIT_FEATURE_VERSION
        result = replace(result, model_version=UNIT_MODEL_VERSION)
    with pytest.raises(ValueError):
        _result_receipt(replace(result, metadata=MappingProxyType(metadata)))


@pytest.mark.parametrize(
    "mutation", ["invented_source", "provider", "training_family", "current_family"]
)
def test_result_boundary_binds_attribute_families_to_every_source_group(mutation):
    result = fit().predict(target())
    metadata = dict(result.metadata)
    if mutation == "invented_source":
        metadata["attribute_contract"] = tuple(
            ("invented", *row[1:]) for row in metadata["attribute_contract"]
        )
        metadata["source_attribute_groups"] = tuple(
            ("invented", row[1]) for row in metadata["source_attribute_groups"]
        )
        columns = tuple(name.replace("synthetic:", "invented:") for name in result.feature_contract)
        metadata["feature_columns"] = columns
        result = replace(result, feature_contract=columns)
    elif mutation == "provider":
        metadata["attribute_contract"] = tuple(
            (*row[:6], "another provider", row[7]) for row in metadata["attribute_contract"]
        )
    elif mutation == "training_family":
        groups = list(metadata["training_source_receipts"])
        groups[0] = tuple((row[0], "another provider", *row[2:]) for row in groups[0])
        metadata["training_source_receipts"] = tuple(groups)
    else:
        metadata["projection_source_receipts"] = tuple(
            (row[0], "another provider", *row[2:]) for row in metadata["projection_source_receipts"]
        )
    with pytest.raises(ValueError, match="Attribute source families"):
        _result_receipt(replace(result, metadata=MappingProxyType(metadata)))
