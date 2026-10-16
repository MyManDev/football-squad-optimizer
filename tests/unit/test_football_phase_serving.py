"""Compact phase restoration retains every allocation moment and refuses altered contracts."""

import hashlib
import json
from dataclasses import FrozenInstanceError, asdict, replace

import pytest
from tests.unit.test_football_phase_duties import (
    CODES,
    _fit,
    _observation,
    _players,
    _projection,
    _rank_training,
)
from tests.unit.test_football_phase_replay_training import CUTOFF as REPLAY_CUTOFF
from tests.unit.test_football_phase_replay_training import read_observation, replay_case

from squadopt.features.football_phase_inputs import PHASES, PhaseGoal, PhaseState
from squadopt.prediction.football_phase_duties import PhaseDutyModel
from squadopt.prediction.football_phase_serving import (
    MAX_ARTIFACT_BYTES,
    SERVING_RECEIPT,
    PhaseServingModel,
    export_phase_serving_model,
    read_phase_serving_model,
)


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _restore(payload):
    return read_phase_serving_model(payload, expected_sha256=_sha(payload))


@pytest.fixture(scope="module")
def fitted():
    events = tuple(
        PhaseGoal(f"{phase}-{index}", phase, player, CODES[(index + 1) % 3], False, "synthetic")
        for phase in PHASES
        for index, player in enumerate(CODES)
    )
    return _fit((_observation(events=events, ranks=(None, None, None)),))


@pytest.mark.parametrize("zero_mass", [False, True])
def test_compact_roundtrip_matches_every_player_state_moment_without_mutating_legacy(
    fitted, zero_mass
):
    states = (
        PhaseState(
            "partial", 0.25, _players((0, 30, 90)), 0 if zero_mass else 2, 0 if zero_mass else 1, 3
        ),
        PhaseState(
            "reversed",
            0.75,
            _players((90, 65, 0)),
            0 if zero_mass else 1,
            0 if zero_mass else 0.5,
            3,
        ),
    )
    projection = _projection(states=states, ranks=(None, None, None))
    legacy = fitted.predict(projection)
    original_metadata = _bytes(asdict(fitted.metadata))
    original_result = _bytes(asdict(legacy))
    payload = export_phase_serving_model(fitted)
    serving = _restore(payload)
    actual = asdict(serving.predict(projection))
    expected = asdict(legacy)
    del expected["metadata"]
    receipt = actual.pop("serving_receipt")
    assert actual == expected
    assert receipt["contract_version"] == SERVING_RECEIPT
    assert receipt["artifact_sha256"] == _sha(payload)
    assert receipt["original_metadata_sha256"] == _sha(original_metadata)
    assert _bytes(asdict(fitted.metadata)) == original_metadata
    assert _bytes(asdict(fitted.predict(projection))) == original_result
    assert serving.metadata.recipient_heads == fitted.metadata.recipient_heads
    assert len(payload) < MAX_ARTIFACT_BYTES
    assert b"training_receipts" not in payload and b"observation_sha256" not in payload
    assert b"synthetic" not in payload
    assert export_phase_serving_model(fitted) == payload


@pytest.mark.parametrize("name", ["_phase_shares", "_coefficients"])
def test_serving_parameters_and_model_fields_are_immutable(fitted, name):
    model = _restore(export_phase_serving_model(fitted))
    values = getattr(model, name)
    array = next(iter(values.values()))
    with pytest.raises(TypeError):
        values["invented"] = array
    with pytest.raises(ValueError):
        array[0] = 10
    with pytest.raises(ValueError):
        array.setflags(write=True)
    with pytest.raises(FrozenInstanceError):
        model.metadata = None


@pytest.mark.parametrize("phase", ["penalty", "direct_free_kick", "corner", "delivered_free_kick"])
def test_nonzero_recipient_effects_and_partial_phase_support_remain_exact(phase):
    observations = _rank_training(phase)
    if phase in ("corner", "delivered_free_kick"):
        observations = tuple(
            replace(
                row,
                events=tuple(
                    replace(event, scorer=event.assist, assist=event.scorer) for event in row.events
                ),
                totals=tuple(
                    replace(total, goals=total.assists, assists=total.goals) for total in row.totals
                ),
            )
            for row in observations
        )
    fitted = _fit(observations)
    serving = _restore(export_phase_serving_model(fitted))
    assert any(
        value != 0 for head in fitted.metadata.recipient_heads for value in head.coefficients
    )
    projection = _projection(ranks=(3, None, 1))
    before, after = asdict(fitted.predict(projection)), asdict(serving.predict(projection))
    del before["metadata"], after["serving_receipt"]
    assert before == after


def test_released_replay_metadata_is_exported_without_inventing_training_receipts():
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    fitted = PhaseDutyModel().fit(
        (observation,),
        cutoff=REPLAY_CUTOFF,
        allowed_seasons=("2025-26",),
        target_season="2026-27",
        target_gameweek=7,
        allow_released_2025_26=True,
    )
    model = _restore(export_phase_serving_model(fitted))
    assert model.metadata.released_2025_26 is True
    assert model.metadata.allowed_seasons == ("2025-26",)
    assert model.metadata.fit_contract_version == "football_phase_duty_replay_fit_v2"
    assert model.metadata.original_metadata_sha256 == _sha(_bytes(asdict(fitted.metadata)))
    assert not hasattr(model.metadata, "training_receipts")


@pytest.mark.parametrize(
    "contract,released",
    [
        ("football_phase_duty_fit_v1", False),
        ("football_phase_duty_replay_fit_v1", False),
        ("football_phase_duty_replay_fit_v1", True),
    ],
)
def test_legacy_fit_contracts_keep_original_option_bit_semantics(fitted, contract, released):
    document = json.loads(export_phase_serving_model(fitted))
    document.update(fit_contract_version=contract, released_2025_26=released)
    model = _restore(_bytes(document))
    assert model.metadata.fit_contract_version == contract
    assert model.metadata.released_2025_26 is released
    document["allowed_seasons"] = ["2024-25", "2025-26"]
    if not released:
        with pytest.raises(ValueError, match="release/window"):
            _restore(_bytes(document))
    else:
        assert _restore(_bytes(document)).metadata.released_2025_26


def test_flag_only_v2_export_does_not_claim_replay_or_released_rows():
    from tests.unit.test_football_phase_replay_training import _fit_rows

    fitted = _fit_rows((read_observation(),))
    model = _restore(export_phase_serving_model(fitted))
    assert model.metadata.fit_contract_version == "football_phase_duty_fit_v2"
    assert model.metadata.released_2025_26 is False
    assert model.metadata.allowed_seasons == ("2024-25", "2025-26")


def test_v2_release_use_requires_replay_contract_and_selected_season(fitted):
    document = json.loads(export_phase_serving_model(fitted))
    document.update(fit_contract_version="football_phase_duty_replay_fit_v2", released_2025_26=True)
    with pytest.raises(ValueError, match="explicit fit contract"):
        _restore(_bytes(document))
    document["allowed_seasons"] = ["2025-26"]
    assert _restore(_bytes(document)).metadata.released_2025_26
    document["fit_contract_version"] = "football_phase_duty_fit_v2"
    with pytest.raises(ValueError, match="explicit fit contract"):
        _restore(_bytes(document))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", "other"),
        ("model_version", "other"),
        ("feature_version", "other"),
        ("phase_definition_version", "other"),
        ("fit_contract_version", "other"),
        ("original_metadata_sha256", "A" * 64),
        ("observation_count", 0),
        ("observation_count", True),
        ("observation_count", 0.5),
        ("max_iter", False),
        ("alpha", -1),
        ("alpha", True),
        ("cutoff", "2026-10-09"),
        ("cutoff", 10),
        ("target_season", "2025-26"),
        ("target_season", "2026-26"),
        ("target_gameweek", True),
        ("target_gameweek", 39),
        ("allowed_seasons", []),
        ("allowed_seasons", ["2024-25", "2024-25"]),
        ("allowed_seasons", ["2027-28"]),
        ("allowed_seasons", ["2025-26"]),
        ("released_2025_26", 1),
        ("released_2025_26", True),
        ("goal_events", True),
        ("goal_events", 16),
        ("assist_events", 0),
        ("goal_status", "unavailable_no_credited_events"),
        ("penalty_miss_treatment", "new adjustment"),
        ("output_scope", "joint_events"),
        ("physical_check", "ignored"),
    ],
)
def test_rehashed_semantic_tampering_is_refused(fitted, field, value):
    document = json.loads(export_phase_serving_model(fitted))
    document[field] = value
    with pytest.raises(ValueError):
        _restore(_bytes(document))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head", "own_goals"),
        ("phase", "free_kick"),
        ("features", ["position_gk"]),
        ("coefficients", []),
        ("coefficients", [True] * 9),
        ("credited_events", 0),
        ("credited_events", True),
        ("fitting_groups", 0),
        ("fitting_groups", 2),
    ],
)
def test_rehashed_head_tampering_is_refused(fitted, field, value):
    document = json.loads(export_phase_serving_model(fitted))
    document["recipient_heads"][0][field] = value
    with pytest.raises(ValueError):
        _restore(_bytes(document))


def test_duplicate_or_reordered_head_identity_is_refused(fitted):
    document = json.loads(export_phase_serving_model(fitted))
    document["recipient_heads"][1] = document["recipient_heads"][0]
    with pytest.raises(ValueError, match="unique"):
        _restore(_bytes(document))
    document = json.loads(export_phase_serving_model(fitted))
    document["recipient_heads"].reverse()
    with pytest.raises(ValueError, match="fitted order"):
        _restore(_bytes(document))


def test_reader_requires_exact_external_hash_and_canonical_bounded_bytes(fitted):
    payload = export_phase_serving_model(fitted)
    with pytest.raises(ValueError, match="expected SHA256"):
        read_phase_serving_model(payload, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="SHA256"):
        read_phase_serving_model(payload, expected_sha256=None)
    for malformed in (payload + b"\n", b"[]", b"{}", b"{", b"x" * (MAX_ARTIFACT_BYTES + 1)):
        with pytest.raises(ValueError):
            _restore(malformed)
    duplicate = b'{"contract_version":"a","contract_version":"b"}'
    with pytest.raises(ValueError, match="repeats"):
        _restore(duplicate)
    document = json.loads(payload)
    document["extra"] = 1
    with pytest.raises(ValueError, match="fields"):
        _restore(_bytes(document))
    nan = payload.replace(b'"alpha":0.1', b'"alpha":NaN')
    assert nan != payload
    with pytest.raises(ValueError):
        _restore(nan)


def test_export_requires_fitted_parameters_matching_full_metadata():
    with pytest.raises(ValueError, match="actual fitted"):
        export_phase_serving_model(PhaseDutyModel())
    fitted = _fit()
    fitted._fitted = replace(fitted._fitted, metadata=replace(fitted.metadata, goal_events=2))
    with pytest.raises(ValueError, match="totals"):
        export_phase_serving_model(fitted)

    fitted = _fit()
    coefficients = dict(fitted._fitted.coefficients)
    key = next(iter(coefficients))
    coefficients[key] = coefficients[key] + 1
    fitted._fitted = replace(fitted._fitted, coefficients=coefficients)
    with pytest.raises(ValueError, match="parameters differ"):
        export_phase_serving_model(fitted)


def test_serving_preserves_unavailable_support_and_physical_refusals():
    empty = _restore(export_phase_serving_model(_fit((_observation(events=()),))))
    with pytest.raises(ValueError, match="unavailable without"):
        empty.predict(_projection())
    zero = _projection(states=(PhaseState("zero", 1, _players(), 0, 0, 0),))
    assert empty.predict(zero).total_goals == 0
    fitted = _restore(export_phase_serving_model(_fit()))
    absent = _projection(states=(PhaseState("absent", 1, _players((0, 0, 0)), 1, 0, 1),))
    with pytest.raises(ValueError, match="exposure"):
        fitted.predict(absent)
    concentrated = _projection(
        states=(PhaseState("one", 1, _players(weights=(1e9, 1e-9, 1e-9)), 1, 1, 1),)
    )
    with pytest.raises(ValueError, match="physical scoring-event"):
        fitted.predict(concentrated)


@pytest.mark.parametrize(
    "change", [{"gameweek": 5}, {"season": "2027-28"}, {"decision_at": "2026-10-08T00:00:00Z"}]
)
def test_serving_retains_projection_target_and_cutoff_guards(fitted, change):
    model = _restore(export_phase_serving_model(fitted))
    with pytest.raises(ValueError):
        model.predict(replace(_projection(), **change))


def test_direct_constructor_cannot_attach_a_false_artifact_hash(fitted):
    model = _restore(export_phase_serving_model(fitted))
    with pytest.raises(ValueError, match="retained artifact hash"):
        PhaseServingModel(model.metadata, "a" * 64)
