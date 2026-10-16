"""Strict compact parameters and exact full-model inference, synthetic inputs only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import timedelta

import numpy as np
import pytest
from tests.unit.test_football_unit_physical import fit as physical_fit
from tests.unit.test_football_unit_pooled import fit
from tests.unit.test_football_unit_replay import current_projection, replay_catalog
from tests.unit.test_football_unit_strength import unit

from squadopt.features.football_unit_inputs import ProjectedUnitState
from squadopt.prediction.football_unit_serving import (
    MAX_ARTIFACT_BYTES,
    UNIT_LEGACY_SERVING_VERSION,
    UNIT_SERVING_VERSION,
    UnitServingModel,
    export_unit_serving_model,
    read_unit_serving_model,
)
from squadopt.prediction.football_unit_strength import UNIT_LEGACY_PHYSICAL_FIT_VERSION


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read(payload):
    return read_unit_serving_model(payload, expected_sha256=hashlib.sha256(payload).hexdigest())


@pytest.fixture(scope="module")
def fitted():
    return fit()


@pytest.fixture(scope="module")
def payload(fitted):
    return export_unit_serving_model(
        fitted, original_fit_sha256="a" * 64, target_season="2026-27", target_gameweek=1
    )


def test_exact_full_model_parity_and_distinct_small_result(fitted, payload):
    serving = read(payload)
    projection = current_projection()
    full, compact = fitted.predict(projection), serving.predict(projection)
    assert compact.state_rates == full.state_rates
    assert compact.own_goal_rate == full.own_goal_rate
    assert compact.opponent_goal_rate == full.opponent_goal_rate
    assert compact.serving_receipt.projection_sha256 == full.metadata["projection_sha256"]
    assert compact.serving_receipt.original_fit_sha256 == "a" * 64
    assert compact.serving_receipt.artifact_sha256 == hashlib.sha256(payload).hexdigest()
    assert "training_sources" not in payload.decode()
    assert not hasattr(compact, "metadata")
    assert not hasattr(serving, "_observations")
    assert serving.metadata.coefficients == tuple(fitted._head.coef_)
    assert serving.metadata.applied_scales == tuple(fitted._feature_scales)


def test_multiple_states_order_reversal_and_neutral_reference(fitted, payload):
    serving, p = read(payload), current_projection()
    p = replace(
        p,
        states=(
            ProjectedUnitState(0.3, unit(1, replacement=True), unit(2)),
            ProjectedUnitState(0.7, unit(1), unit(2)),
        ),
    )
    a, b = fitted.predict(p), serving.predict(p)
    assert a.state_rates == b.state_rates
    assert a.own_goal_rate == b.own_goal_rate
    assert a.opponent_goal_rate == b.opponent_goal_rate
    reordered = serving.predict(replace(p, states=tuple(reversed(p.states))))
    assert reordered.state_rates == b.state_rates
    assert reordered.own_goal_rate == b.own_goal_rate
    assert reordered.opponent_goal_rate == b.opponent_goal_rate
    reverse = serving.predict(
        replace(
            p,
            home=not p.home,
            reference_own=p.reference_opponent,
            reference_opponent=p.reference_own,
            states=tuple(replace(x, own=x.opponent, opponent=x.own) for x in p.states),
            causal_baseline_own_goal_rate=p.causal_baseline_opponent_goal_rate,
            causal_baseline_opponent_goal_rate=p.causal_baseline_own_goal_rate,
        )
    )
    assert reverse.own_goal_rate == b.opponent_goal_rate
    assert reverse.opponent_goal_rate == b.own_goal_rate
    neutral = serving.predict(replace(p, states=(ProjectedUnitState(1, unit(1), unit(2)),)))
    assert neutral.own_goal_rate == p.causal_baseline_own_goal_rate
    assert neutral.opponent_goal_rate == p.causal_baseline_opponent_goal_rate


def test_parameters_are_immutable_and_hash_bound(payload):
    model = read(payload)
    with pytest.raises(FrozenInstanceError):
        model.metadata = replace(model.metadata, alpha=2)
    with pytest.raises(FrozenInstanceError):
        model.metadata.coefficients = ()
    with pytest.raises(TypeError):
        model.metadata.coefficients[0] = 4
    with pytest.raises(ValueError, match="artifact bytes"):
        UnitServingModel(
            replace(model.metadata, original_fit_sha256="b" * 64), model.artifact_sha256
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_version", "other"),
        ("model_version", "v3"),
        ("feature_version", "other"),
        ("fit_contract_version", "prefix"),
        ("identity_policy", "exposure_standardized_v1"),
        ("alpha", 0.2),
        ("alpha", True),
        ("training_offset_sum", 0),
        ("raw_identity_count_prior_precision", 1),
        ("coefficients", []),
        ("coefficients", [True]),
        ("applied_scales", []),
        ("training_scaler_scales", []),
        ("player_vocabulary", [True]),
        ("player_vocabulary", [2, 1]),
        ("player_vocabulary", [1, 1]),
        ("player_vocabulary", [2**54]),
        ("feature_columns", []),
        ("training_scopes", []),
        ("training_scopes", [["2025-25", 1]]),
        ("training_scopes", [["2025-26", True]]),
        ("training_scopes", [["2025-26", 1], ["2025-26", 1]]),
        ("allow_released_2025_26", False),
        ("allow_released_2025_26", 1),
        ("cutoff", "2026-10-15T20:00:00"),
        ("cutoff", 1),
        ("original_fit_sha256", "A" * 64),
        ("fm_game_vintage", "2023"),
        ("attributes", [{}]),
        ("attributes", "not-an-array"),
    ],
)
def test_recomputed_hash_cannot_bypass_semantic_validation(payload, field, value):
    body = json.loads(payload)
    body[field] = value
    with pytest.raises(ValueError):
        read(canonical(body))


@pytest.mark.parametrize(
    "vector,value",
    [
        ("coefficients", True),
        ("coefficients", float("nan")),
        ("coefficients", float("inf")),
        ("applied_scales", 0),
        ("applied_scales", True),
        ("applied_scales", 2),
        ("training_scaler_scales", -1),
    ],
)
def test_valid_width_vectors_reject_boolean_nonfinite_or_wrong_identity_scale(
    payload, vector, value
):
    body = json.loads(payload)
    body[vector][0] = value
    with pytest.raises(ValueError):
        read(canonical(body))


def test_shared_scales_must_retain_the_actual_observed_scale(payload):
    body = json.loads(payload)
    index = body["feature_columns"].index("own_GK_count")
    body["applied_scales"][index] *= 2
    with pytest.raises(ValueError, match="scales disagree"):
        read(canonical(body))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b + b"\n",
        lambda b: b.replace(b"{", b'{"alpha":0.1,', 1),
        lambda b: b.replace(b'"alpha":0.1,', b'"alpha":0.1,"unknown":0,', 1),
        lambda b: b.replace(b'"alpha":0.1,', b"", 1),
        lambda b: b"[1]",
        lambda b: b"\xff",
        lambda b: b"{" * 1100,
    ],
)
def test_strict_json_transport(payload, mutation):
    with pytest.raises(ValueError):
        read(mutation(payload))


def test_wrong_digest_wrong_type_and_size(payload):
    with pytest.raises(ValueError, match="expected SHA256"):
        read_unit_serving_model(payload, expected_sha256="0" * 64)
    for invalid in (b"", b" " * (MAX_ARTIFACT_BYTES + 1), bytearray(payload), payload.decode()):
        with pytest.raises(ValueError, match="bounded nonempty bytes"):
            read_unit_serving_model(invalid, expected_sha256="0" * 64)


def test_producer_fit_digest_is_provenance_not_a_claim_of_reauditing(payload):
    body = json.loads(payload)
    body["original_fit_sha256"] = "b" * 64
    assert read(canonical(body)).metadata.original_fit_sha256 == "b" * 64
    assert "not reaudited" in body["provenance_scope"]


def test_current_source_family_must_equal_fit_even_with_consistent_artifact_hash(payload):
    body = json.loads(payload)
    body["attributes"][0]["provider"] = "invented-provider"
    with pytest.raises(ValueError, match="source families differ"):
        read(canonical(body)).predict(current_projection())
    with pytest.raises(ValueError, match="source families differ"):
        read(payload).predict(
            replace(
                current_projection(),
                catalog=replace(
                    current_projection().catalog,
                    attributes=tuple(
                        replace(x, definition="changed")
                        for x in current_projection().catalog.attributes
                    ),
                ),
            )
        )


@pytest.mark.parametrize("scope", [[["2026-27", 1]], [["2027-28", 1]]])
def test_current_prediction_rejects_same_or_future_training_scope(payload, scope):
    body = json.loads(payload)
    body["training_scopes"] = scope
    with pytest.raises(ValueError, match="target week"):
        read(canonical(body)).predict(current_projection())


def test_current_prediction_rejects_unavailable_fit_and_replay(payload):
    body = json.loads(payload)
    body["cutoff"] = (current_projection().decision_cutoff + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="unavailable"):
        read(canonical(body)).predict(current_projection())
    with pytest.raises(ValueError, match="Historical replay"):
        replace(current_projection(), catalog=replay_catalog())
    with pytest.raises(ValueError, match="typed projection"):
        read(payload).predict(None)


def test_unseen_player_identity_has_no_fitted_residual_and_exact_full_parity(fitted, payload):
    p = current_projection()
    # Player 112 has a source mapping but never appears in the fitted unit vocabulary.
    assert 112 not in fitted.player_vocabulary
    p = replace(p, states=(ProjectedUnitState(1, unit(1), unit(2, replacement=True)),))
    assert read(payload).predict(p).state_rates == fitted.predict(p).state_rates


def test_model_exports_only_actual_v4_and_fixed_parameters(fitted):
    with pytest.raises(ValueError, match="only the actual fitted"):
        export_unit_serving_model(
            physical_fit(), original_fit_sha256="a" * 64, target_season="2026-27", target_gameweek=1
        )
    with pytest.raises(ValueError):
        export_unit_serving_model(
            fitted, original_fit_sha256="not-sha", target_season="2026-27", target_gameweek=1
        )


def test_compact_sparse_numerics_independently_reproduce_log_ratio(payload):
    serving = read(payload)
    metadata = serving.metadata
    p = current_projection()
    # Directly specify the changed home FWD, including complete source absence.
    values = {
        "own_player_11": -1,
        "own_player_12": 1,
        "own_FWD_fm:all_attributes_unobserved": 1 / 11,
        "own_FWD_fm:finishing_value": -8 / 11,
    }
    values.update(
        {
            "home_interaction:" + key: value
            for key, value in list(values.items())
            if not key.startswith("own_player_")
        }
    )
    log_ratio = sum(
        values.get(name, 0) / scale * coefficient
        for name, scale, coefficient in zip(
            metadata.feature_columns, metadata.applied_scales, metadata.coefficients, strict=True
        )
    )
    changed = replace(p, states=(ProjectedUnitState(1, unit(1, replacement=True), unit(2)),))
    result = serving.predict(changed)
    assert result.own_goal_rate == pytest.approx(
        np.exp(log_ratio) * p.causal_baseline_own_goal_rate, abs=1e-14
    )
    assert asdict(result.serving_receipt)["model_version"] == metadata.model_version


@pytest.mark.parametrize(
    "changes",
    [
        {"target_season": None},
        {"target_gameweek": None},
        {"target_gameweek": True},
        {"target_gameweek": 0},
        {"target_season": "2025-26", "target_gameweek": 1},
        {"target_season": "2024-25", "target_gameweek": 38},
    ],
)
def test_v2_requires_explicit_causal_target(payload, changes):
    values = json.loads(payload)
    values.update(changes)
    with pytest.raises(ValueError):
        read(canonical(values))


def test_v2_target_identity_is_explicit_and_supports_later_horizons(payload):
    serving = read(payload)
    assert serving.metadata.contract_version == UNIT_SERVING_VERSION
    assert (serving.metadata.target_season, serving.metadata.target_gameweek) == ("2026-27", 1)
    p = current_projection()
    later = replace(p, gameweek=3, catalog=replace(p.catalog, gameweek=3))
    assert serving.predict(later).own_goal_rate == serving.predict(p).own_goal_rate
    other = replace(p, season="2027-28", catalog=replace(p.catalog, season="2027-28"))
    with pytest.raises(ValueError, match="target season"):
        serving.predict(other)
    values = json.loads(payload)
    values["target_gameweek"] = 2
    with pytest.raises(ValueError, match="target season"):
        read(canonical(values)).predict(p)


def test_legacy_v1_bytes_remain_canonical_and_keep_missing_target_fields(payload):
    values = json.loads(payload)
    values["contract_version"] = UNIT_LEGACY_SERVING_VERSION
    values["fit_contract_version"] = UNIT_LEGACY_PHYSICAL_FIT_VERSION
    values.pop("target_season")
    values.pop("target_gameweek")
    legacy_bytes = canonical(values)
    legacy = read(legacy_bytes)
    assert legacy.artifact_sha256 == hashlib.sha256(legacy_bytes).hexdigest()
    assert legacy.metadata.target_season is legacy.metadata.target_gameweek is None
    assert (
        legacy.predict(current_projection()).own_goal_rate
        == read(payload).predict(current_projection()).own_goal_rate
    )
    for field in ("target_season", "target_gameweek"):
        with pytest.raises(ValueError, match="Legacy unit bytes"):
            read(canonical({**values, field: None}))
    wrong = replace(legacy.metadata, target_season="2026-27", target_gameweek=1)
    with pytest.raises(ValueError, match="cannot claim"):
        UnitServingModel(wrong, legacy.artifact_sha256)


def test_v2_release_flag_matches_rows_but_v1_preserves_original_option_meaning(payload):
    values = json.loads(payload)
    values["training_scopes"] = [["2024-25", 38]]
    assert values["allow_released_2025_26"] is True
    with pytest.raises(ValueError, match="actual training scopes"):
        read(canonical(values))
    legacy = {
        **values,
        "contract_version": UNIT_LEGACY_SERVING_VERSION,
        "fit_contract_version": UNIT_LEGACY_PHYSICAL_FIT_VERSION,
    }
    legacy.pop("target_season")
    legacy.pop("target_gameweek")
    assert read(canonical(legacy)).metadata.allow_released_2025_26 is True
    values["allow_released_2025_26"] = False
    assert read(canonical(values)).metadata.allow_released_2025_26 is False
