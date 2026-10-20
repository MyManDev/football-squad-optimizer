"""Exact compact recipient parity and strict independent byte/transform refusals."""

from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any

import numpy as np
import pytest
from tests.unit.test_football_observed_tactical import (
    encoded,
    fit,
    observation,
    projection,
    replayed,
    sha,
)

from squadopt.prediction import football_observed_tactical as full_module
from squadopt.prediction.football_observed_tactical import ObservedTacticalModel
from squadopt.prediction.football_observed_tactical_serving import (
    MAX_ARTIFACT_BYTES,
    ObservedTacticalServingModel,
    export_observed_tactical_serving_model,
    read_observed_tactical_serving_model,
)


@pytest.fixture(scope="module")
def fitted() -> ObservedTacticalModel:
    return fit(tuple(observation(i) for i in range(3)))


def restore(raw: bytes) -> ObservedTacticalServingModel:
    return read_observed_tactical_serving_model(raw, expected_sha256=sha(raw))


@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_exact_recipient_moments_metadata_and_separate_receipt(
    fitted: ObservedTacticalModel, control: bool, missing: bool
) -> None:
    before = fitted.metadata_json
    raw = export_observed_tactical_serving_model(fitted)
    compact = restore(raw)
    p = projection(current=True, missing=missing)
    original, result = (
        fitted.predict_recipients(p, control=control),
        compact.predict_recipients(p, control=control),
    )
    assert result.home == original.home and result.away == original.away
    assert result.projection_sha256 == original.projection_sha256
    assert result.source_hashes == original.source_hashes
    assert result.control == control and result.policy == original.policy
    assert result.serving_receipt.original_metadata_sha256 == sha(before.encode())
    assert result.serving_receipt.artifact_sha256 == sha(raw)
    assert result.serving_receipt.artifact_sha256 != original.model_sha256
    assert fitted.metadata_json == before
    assert (
        b'"training_receipts"' not in raw
        and b'"team_transform"' not in raw
        and b'"beta"' not in raw
    )
    assert not hasattr(result, "model_sha256")
    assert not hasattr(result.home, "team_goal_rate")
    assert compact.metadata.goal_transform == fitted.metadata.goal_transform
    assert compact.metadata.assist_transform == fitted.metadata.assist_transform
    assert compact.metadata.goal_gamma == fitted.metadata.goal_gamma
    assert compact.metadata.assist_gamma == fitted.metadata.assist_gamma


def test_compact_inference_has_no_count_head_or_full_model_dependency(
    fitted: ObservedTacticalModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    compact = restore(export_observed_tactical_serving_model(fitted))
    p = projection(current=True)
    expected = compact.predict_recipients(p)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Count head or original model used by compact inference")

    monkeypatch.setattr(full_module, "_rates", forbidden)
    monkeypatch.setattr(full_module, "team_features", forbidden)
    monkeypatch.setattr(fitted, "predict_recipients", forbidden)
    assert compact.predict_recipients(p) == expected


def test_compact_storage_and_parameter_arrays_are_immutable(fitted: ObservedTacticalModel) -> None:
    compact = restore(export_observed_tactical_serving_model(fitted))
    with pytest.raises(FrozenInstanceError):
        compact.artifact_sha256 = "a" * 64  # type: ignore[misc]
    with pytest.raises(TypeError):
        compact._gammas["goals"] = np.zeros(1)  # type: ignore[index]
    with pytest.raises(ValueError):
        compact._gammas["goals"].setflags(write=True)
    with pytest.raises(ValueError, match="artifact hash"):
        ObservedTacticalServingModel(
            replace(compact.metadata, goal_events=999), compact.artifact_sha256
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("serving_version", "unknown"),
        ("model_version", "unknown"),
        ("feature_version", "unknown"),
        ("input_version", "unknown"),
        ("role_policy", "current_FPL_position"),
        ("context_policy", "realized_XI"),
        ("recipient_policy", "paired_rate_adjustment"),
        ("style_version", "six_invented_channels"),
        ("original_metadata_sha256", "z" * 64),
        ("observation_count", True),
        ("observation_count", 0),
        ("target_gameweek", 39),
        ("target_gameweek", "7"),
        ("cutoff", "2026-10-01"),
        ("target_season", "2026-2027"),
        ("allowed_seasons", ["2027-28"]),
        ("allowed_seasons", ["2024-25", "2024-25"]),
        ("allowed_seasons", []),
        ("allowed_seasons", ["2025-26"]),
        ("allow_released_2025_26", 1),
        ("goal_events", True),
        ("goal_events", -1),
        ("goal_gamma", [0]),
    ],
)
def test_canonical_self_hashed_invalid_metadata_still_refuses(
    fitted: ObservedTacticalModel, field: str, value: Any
) -> None:
    document = asdict(restore(export_observed_tactical_serving_model(fitted)).metadata)
    document[field] = value
    with pytest.raises(ValueError):
        restore(encoded(document))


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "unknown"),
        ("weighting", "outcome_weighted"),
        ("unsupported_policy", "new_column_enabled"),
        ("features", ("invented",)),
        ("means", (0,)),
        ("scales", ()),
    ],
)
def test_transform_schema_and_feature_order_refuse(
    fitted: ObservedTacticalModel, field: str, value: Any
) -> None:
    document = asdict(restore(export_observed_tactical_serving_model(fitted)).metadata)
    document["goal_transform"][field] = value
    with pytest.raises(ValueError):
        restore(encoded(document))


@pytest.mark.parametrize(
    "field,value",
    [
        ("means", True),
        ("means", "1"),
        ("scales", 0),
        ("scales", -1),
        ("observed_weights", -1),
        ("observed_weights", 100),
        ("observed_counts", 0.5),
        ("observed_counts", True),
        ("observed_counts", 1000000),
        ("mask_means", -1),
        ("mask_means", 1.1),
        ("mask_scales", 0.1),
        ("active", 1),
        ("active", False),
    ],
)
def test_transform_support_moments_and_strict_numeric_types_refuse(
    fitted: ObservedTacticalModel, field: str, value: Any
) -> None:
    document = asdict(restore(export_observed_tactical_serving_model(fitted)).metadata)
    vector = list(document["goal_transform"][field])
    vector[0] = value
    document["goal_transform"][field] = vector
    with pytest.raises(ValueError):
        restore(encoded(document))


@pytest.mark.parametrize("bad", [True, "1", float("inf"), float("nan")])
def test_invalid_coefficients_refuse(fitted: ObservedTacticalModel, bad: Any) -> None:
    compact = restore(export_observed_tactical_serving_model(fitted))
    metadata = replace(compact.metadata, goal_gamma=(bad, *compact.metadata.goal_gamma[1:]))
    with pytest.raises(ValueError):
        ObservedTacticalServingModel(metadata, compact.artifact_sha256)


def test_disabled_and_unsupported_head_parameters_refuse_and_control_remains_native() -> None:
    o = observation(missing=True)
    o = replace(o, credits=tuple(replace(c, assists=0) for c in o.credits))
    model = fit((o,))
    compact = restore(export_observed_tactical_serving_model(model))
    p = projection(current=True, missing=True)
    with pytest.raises(ValueError, match="credited-event support"):
        compact.predict_recipients(p)
    native = compact.predict_recipients(p, control=True)
    assert native.home == model.predict_recipients(p, control=True).home
    document = asdict(compact.metadata)
    document["assist_gamma"] = [1, *document["assist_gamma"][1:]]
    with pytest.raises(ValueError, match="unsupported head"):
        restore(encoded(document))
    document = asdict(compact.metadata)
    assert not document["goal_transform"]["active"][0]
    document["goal_gamma"] = [1, *document["goal_gamma"][1:]]
    with pytest.raises(ValueError, match="disabled column"):
        restore(encoded(document))


def test_strict_bytes_and_external_expected_hash(fitted: ObservedTacticalModel) -> None:
    raw = export_observed_tactical_serving_model(fitted)
    with pytest.raises(ValueError, match="expected SHA256"):
        read_observed_tactical_serving_model(raw, expected_sha256="a" * 64)
    with pytest.raises(ValueError, match="canonical"):
        restore(raw + b" ")
    with pytest.raises(ValueError, match="repeats"):
        restore(raw.replace(b"{", b'{"cutoff":"extra",', 1))
    with pytest.raises(ValueError, match="bounded"):
        restore(b" " * (MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(ValueError, match="fields"):
        restore(encoded({"made_up": 1}))
    with pytest.raises(ValueError):
        restore(b'{"bad":NaN}')
    with pytest.raises(ValueError):
        export_observed_tactical_serving_model(ObservedTacticalModel())


def test_current_window_control_type_and_replay_refusals(fitted: ObservedTacticalModel) -> None:
    compact = restore(export_observed_tactical_serving_model(fitted))
    p = projection(current=True)
    with pytest.raises(ValueError, match="Boolean"):
        compact.predict_recipients(p, control=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="target window"):
        compact.predict_recipients(replace(p, gameweek=4))
    with pytest.raises(ValueError, match="prospective"):
        compact.predict_recipients(replayed().projection)


def test_valid_current_projection_before_fit_cutoff_refuses(fitted: ObservedTacticalModel) -> None:
    p = projection(current=True)
    body = asdict(restore(export_observed_tactical_serving_model(fitted)).metadata)
    body["cutoff"] = "2026-10-09T13:00:00Z"
    compact = restore(encoded(body))
    from squadopt.features.football_observed_tactical_inputs import validate_projection

    validate_projection(p)
    with pytest.raises(ValueError, match="target window"):
        compact.predict_recipients(p)


@pytest.mark.parametrize("field", ["scope", "role_policy", "native_share_policy"])
def test_export_never_relabels_another_original_model_scope(
    fitted: ObservedTacticalModel, field: str
) -> None:
    stored = fitted._fitted
    assert stored is not None
    metadata = replace(stored.metadata, **{field: "different-policy"})
    document = full_module._canonical(metadata)
    altered = ObservedTacticalModel()
    altered._fitted = replace(
        stored, metadata=metadata, metadata_json=document, sha256=sha(document.encode())
    )
    with pytest.raises(ValueError, match=r"scope|policies"):
        export_observed_tactical_serving_model(altered)
