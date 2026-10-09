"""Strict private JSON checks using complete synthetic units and fictional receipts."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

import pytest
from tests.unit.test_football_unit_strength import T, catalog, observations, projection

from squadopt.features.football_unit_catalog import (
    read_unit_catalog,
    read_unit_observations,
    read_unit_projection,
)
from squadopt.features.football_unit_inputs import UNIT_INPUT_VERSION

READERS = {
    "catalog": read_unit_catalog,
    "observations": read_unit_observations,
    "projection": read_unit_projection,
}


def _json_values(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            key: _json_values(dict(item) if key == "values" else item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_values(item) for item in value]
    return value


def _document(kind: str) -> dict[str, Any]:
    if kind == "catalog":
        data: Any = asdict(catalog())
    elif kind == "observations":
        data = [asdict(item) for item in observations()]
    else:
        data = asdict(projection())
    return {"version": UNIT_INPUT_VERSION, "kind": kind, kind: _json_values(data)}


def _payload(document: dict[str, Any]) -> bytes:
    return json.dumps(document, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _set(document: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize("kind", ["catalog", "observations", "projection"])
def test_json_roundtrip_retains_exact_source_scope_units_and_missing_values(kind: str) -> None:
    originals = {"catalog": catalog(), "observations": observations(), "projection": projection()}
    restored = READERS[kind](_payload(_document(kind)))
    assert restored == originals[kind]
    document = _document(kind)
    nested = document["observations"][0]["catalog"] if kind == "observations" else document[kind]
    if kind == "projection":
        nested = nested["catalog"]
    assert nested["player_attributes"][0]["values"] == {"finishing": 8.0}


def test_declared_unknown_attribute_values_remain_none() -> None:
    expected = catalog(missing=True)
    document = _document("catalog")
    document["catalog"] = _json_values(asdict(expected))
    restored = read_unit_catalog(_payload(document))
    assert restored == expected
    assert all(dict(item.values)["finishing"] is None for item in restored.player_attributes)


def test_utf8_provider_and_definition_text_roundtrip_without_identity_rewriting() -> None:
    document = _document("catalog")
    document["catalog"]["sources"][0]["provider"] = "Sentetik kaynak Ş"
    document["catalog"]["attributes"][0]["definition"] = "Örnek bitiricilik"
    result = read_unit_catalog(_payload(document))
    assert result.sources[0].provider == "Sentetik kaynak Ş"
    assert result.attributes[0].definition == "Örnek bitiricilik"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "utf-32", "utf-32-be"])
def test_non_utf8_encoded_json_refuses_instead_of_autodetecting(encoding: str) -> None:
    raw = _payload(_document("catalog")).decode("utf-8").encode(encoding)
    with pytest.raises(ValueError, match="UTF-8"):
        read_unit_catalog(raw)


@pytest.mark.parametrize("kind", ["catalog", "observations", "projection"])
@pytest.mark.parametrize("container", [str, bytearray, memoryview])
def test_only_immutable_bytes_enter_the_parser(kind: str, container: Any) -> None:
    raw = _payload(_document(kind))
    supplied = raw.decode() if container is str else container(raw)
    with pytest.raises(ValueError, match=r"immutable.*bytes"):
        READERS[kind](supplied)


@pytest.mark.parametrize("raw", [b"", b"{", b"\xff", b"[]", b"null", b"true"])
def test_malformed_json_or_nonobject_envelope_refuses(raw: bytes) -> None:
    with pytest.raises(ValueError):
        read_unit_catalog(raw)


@pytest.mark.parametrize("kind", ["catalog", "observations", "projection"])
@pytest.mark.parametrize("damage", ["wrong_version", "wrong_kind", "extra_field", "missing_field"])
def test_envelope_is_exactly_versioned_and_kind_specific(kind: str, damage: str) -> None:
    document = _document(kind)
    if damage == "wrong_version":
        document["version"] = "football_unit_inputs_v2"
    elif damage == "wrong_kind":
        document["kind"] = "catalog" if kind != "catalog" else "projection"
    elif damage == "extra_field":
        document["source_hint"] = "unversioned"
    else:
        document.pop("version")
    with pytest.raises(ValueError):
        READERS[kind](_payload(document))


@pytest.mark.parametrize(
    ("kind", "original", "repeated"),
    [
        (
            "catalog",
            '"version":"football_unit_inputs_v1"',
            '"version":"football_unit_inputs_v1","version":"football_unit_inputs_v1"',
        ),
        (
            "catalog",
            '"source_id":"synthetic"',
            '"source_id":"synthetic","source_id":"synthetic"',
        ),
        (
            "catalog",
            '"finishing":8.0',
            '"finishing":8.0,"finishing":8.0',
        ),
        (
            "projection",
            '"player_id":1,"position":"GK"',
            '"player_id":1,"player_id":1,"position":"GK"',
        ),
    ],
)
def test_duplicate_keys_refuse_even_when_the_values_agree(
    kind: str, original: str, repeated: str
) -> None:
    raw = _payload(_document(kind)).decode("utf-8")
    assert original in raw
    damaged = raw.replace(original, repeated, 1).encode("utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON fields"):
        READERS[kind](damaged)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_constants_are_refused_before_numeric_conversion(token: str) -> None:
    raw = _payload(_document("catalog"))
    assert b'"maximum":20.0' in raw or b'"maximum":20' in raw
    if b'"maximum":20.0' in raw:
        raw = raw.replace(b'"maximum":20.0', f'"maximum":{token}'.encode(), 1)
    else:
        raw = raw.replace(b'"maximum":20', f'"maximum":{token}'.encode(), 1)
    with pytest.raises(ValueError, match="Nonfinite JSON"):
        read_unit_catalog(raw)


def test_json_exponent_overflow_is_not_a_valid_numeric_attribute() -> None:
    document = _document("catalog")
    document["catalog"]["attributes"][0]["minimum"] = "overflow"
    raw = _payload(document).replace(b'"overflow"', b"1e400", 1)
    with pytest.raises(ValueError, match="finite"):
        read_unit_catalog(raw)


def test_integer_outside_float_range_has_a_declared_parser_refusal() -> None:
    document = _document("catalog")
    document["catalog"]["attributes"][0]["maximum"] = 10**400
    with pytest.raises(ValueError, match=r"numeric|range|finite"):
        read_unit_catalog(_payload(document))


@pytest.mark.parametrize(
    ("kind", "path", "value"),
    [
        ("catalog", ("catalog", "gameweek"), True),
        ("catalog", ("catalog", "gameweek"), "1"),
        ("catalog", ("catalog", "gameweek"), 1.0),
        ("catalog", ("catalog", "mappings", 0, "player_id"), True),
        ("catalog", ("catalog", "mappings", 0, "player_id"), "1"),
        ("catalog", ("catalog", "mappings", 0, "player_id"), 1.0),
        ("catalog", ("catalog", "mappings", 0, "club"), False),
        ("catalog", ("catalog", "mappings", 0, "source_player_id"), 1),
        ("catalog", ("catalog", "sources", 0, "permitted_model_development"), "true"),
        ("catalog", ("catalog", "sources", 0, "permitted_model_development"), 1),
        ("catalog", ("catalog", "sources", 0, "permitted_model_development"), False),
        ("catalog", ("catalog", "attributes", 0, "minimum"), True),
        ("catalog", ("catalog", "attributes", 0, "minimum"), "1"),
        ("catalog", ("catalog", "player_attributes", 0, "values", "finishing"), True),
        ("catalog", ("catalog", "player_attributes", 0, "values", "finishing"), "8"),
        ("projection", ("projection", "home"), 1),
        ("projection", ("projection", "home"), "true"),
        ("projection", ("projection", "states", 0, "probability"), True),
        ("projection", ("projection", "states", 0, "probability"), "1"),
        ("observations", ("observations", 0, "own_goals"), True),
        ("observations", ("observations", 0, "own_goals"), "1"),
        ("observations", ("observations", 0, "own_goals"), 1.0),
        ("observations", ("observations", 0, "causal_baseline_own_goal_rate"), False),
        ("observations", ("observations", 0, "causal_baseline_own_goal_rate"), "1.5"),
    ],
)
def test_json_types_are_not_coerced_into_numeric_boolean_or_persistent_identity(
    kind: str, path: tuple[str | int, ...], value: Any
) -> None:
    document = _document(kind)
    _set(document, path, value)
    with pytest.raises(ValueError):
        READERS[kind](_payload(document))


@pytest.mark.parametrize("field", ["published_at", "captured_at", "effective_at", "valid_until"])
def test_naive_source_clocks_refuse(field: str) -> None:
    document = _document("catalog")
    document["catalog"]["sources"][0][field] = T.replace(tzinfo=None).isoformat()
    with pytest.raises(ValueError, match="timezone"):
        read_unit_catalog(_payload(document))


@pytest.mark.parametrize("field", ["published_at", "captured_at", "effective_at"])
def test_catalog_cannot_import_information_known_after_decision(field: str) -> None:
    document = _document("catalog")
    future = (T + timedelta(seconds=1)).isoformat()
    document["catalog"]["sources"][0][field] = future
    if field == "published_at":
        document["catalog"]["sources"][0]["captured_at"] = future
    with pytest.raises(ValueError, match="decision cutoff"):
        read_unit_catalog(_payload(document))


@pytest.mark.parametrize("damage", ["expired", "publication_after_capture", "effect_after_expiry"])
def test_source_receipt_clocks_are_checked_at_the_catalog_cutoff(damage: str) -> None:
    document = _document("catalog")
    record = document["catalog"]["sources"][0]
    if damage == "expired":
        record["valid_until"] = (T - timedelta(minutes=1)).isoformat()
    elif damage == "publication_after_capture":
        record["published_at"] = T.isoformat()
    else:
        record["effective_at"] = (T + timedelta(days=366)).isoformat()
    with pytest.raises(ValueError, match=r"stale|clocks"):
        read_unit_catalog(_payload(document))


@pytest.mark.parametrize("kind", ["provider", "fm"])
def test_synthetic_permission_receipt_cannot_authorize_an_actual_provider(kind: str) -> None:
    document = _document("catalog")
    document["catalog"]["sources"][0]["kind"] = kind
    with pytest.raises(ValueError, match="Synthetic receipts"):
        read_unit_catalog(_payload(document))


def test_fictional_fm_receipt_roundtrip_enforces_its_declared_scale() -> None:
    # This exercises parsing only and does not establish actual provider permission.
    document = _document("catalog")
    document["catalog"]["sources"][0].update(
        kind="fm", rights_reference="fictional-test-license:model-development"
    )
    result = read_unit_catalog(_payload(document))
    assert result.sources[0].kind == "fm"
    assert result.attributes[0].minimum == 1
    assert result.attributes[0].maximum == 20
    document["catalog"]["attributes"][0]["minimum"] = 0
    with pytest.raises(ValueError, match="1 to 20"):
        read_unit_catalog(_payload(document))


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("catalog", ("catalog",)),
        ("catalog", ("catalog", "sources", 0)),
        ("catalog", ("catalog", "attributes", 0)),
        ("catalog", ("catalog", "mappings", 0)),
        ("projection", ("projection", "states", 0)),
        ("projection", ("projection", "reference_own", "players", 0)),
        ("observations", ("observations", 0, "outcome_source")),
    ],
)
def test_unknown_nested_fields_are_not_silently_discarded(
    kind: str, path: tuple[str | int, ...]
) -> None:
    document = _document(kind)
    row: Any = document
    for key in path:
        row = row[key]
    row["unversioned"] = "ignored would be wrong"
    with pytest.raises(ValueError, match="exactly"):
        READERS[kind](_payload(document))


@pytest.mark.parametrize(
    "damage", ["unknown_source", "unknown_player", "expired_mapping", "overlap"]
)
def test_player_mapping_receipts_must_identify_one_active_known_player(damage: str) -> None:
    document = _document("catalog")
    row = document["catalog"]
    if damage == "unknown_source":
        row["mappings"][0]["source_id"] = "absent"
    elif damage == "unknown_player":
        row["player_attributes"][0]["source_player_id"] = "unmapped"
    elif damage == "expired_mapping":
        row["mappings"][0]["valid_until"] = (T - timedelta(seconds=1)).isoformat()
    else:
        row["mappings"].append(dict(row["mappings"][0]))
    with pytest.raises(
        ValueError, match=r"Mapping source|active persistent|temporal player mapping"
    ):
        read_unit_catalog(_payload(document))


def test_undeclared_attribute_cannot_become_a_numeric_input() -> None:
    document = _document("catalog")
    document["catalog"]["player_attributes"][0]["values"] = {"invented_skill": 8}
    with pytest.raises(ValueError, match="undeclared numeric field"):
        read_unit_catalog(_payload(document))


@pytest.mark.parametrize("field", ["sources", "attributes", "mappings", "player_attributes"])
def test_catalog_collections_require_arrays_not_objects(field: str) -> None:
    document = _document("catalog")
    document["catalog"][field] = {}
    with pytest.raises(ValueError, match="JSON array"):
        read_unit_catalog(_payload(document))


def test_attribute_values_require_a_named_object_not_asdict_pair_array() -> None:
    document = _document("catalog")
    document["catalog"]["player_attributes"][0]["values"] = [["finishing", 8]]
    with pytest.raises(ValueError, match="named JSON object"):
        read_unit_catalog(_payload(document))


@pytest.mark.parametrize("damage", ["capture_after_decision", "kickoff_at_decision", "wrong_scope"])
def test_projection_requires_the_exact_predeadline_scope(damage: str) -> None:
    document = _document("projection")
    row = document["projection"]
    decision = datetime.fromisoformat(row["decision_cutoff"])
    if damage == "capture_after_decision":
        row["captured_at"] = (decision + timedelta(seconds=1)).isoformat()
    elif damage == "kickoff_at_decision":
        row["kickoff"] = decision.isoformat()
    else:
        row["fixture_id"] += 1
    with pytest.raises(ValueError, match=r"decision cutoff|captured for this fixture"):
        read_unit_projection(_payload(document))


@pytest.mark.parametrize(
    "damage", ["partial_unit", "duplicate_player", "unsupported_position", "mass"]
)
def test_projection_cannot_fabricate_a_complete_supported_joint_unit(damage: str) -> None:
    document = _document("projection")
    state = document["projection"]["states"][0]
    players = state["own"]["players"]
    if damage == "partial_unit":
        players.pop()
    elif damage == "duplicate_player":
        players[-1] = dict(players[0])
    elif damage == "unsupported_position":
        players[-1]["position"] = "AM"
    else:
        state["probability"] = 0.75
    with pytest.raises(ValueError):
        read_unit_projection(_payload(document))


@pytest.mark.parametrize(
    "damage", ["unsettled", "outcome_source_future", "zero_exposure", "bad_goals"]
)
def test_observation_requires_settled_source_and_recorded_exposure(damage: str) -> None:
    document = _document("observations")
    row = document["observations"][0]
    if damage == "unsettled":
        kickoff = datetime.fromisoformat(row["kickoff"])
        row["outcome_available_at"] = (kickoff + timedelta(hours=2)).isoformat()
    elif damage == "outcome_source_future":
        available = datetime.fromisoformat(row["outcome_available_at"])
        row["outcome_source"]["captured_at"] = (available + timedelta(seconds=1)).isoformat()
    elif damage == "zero_exposure":
        row["minutes"] = 0
    else:
        row["own_goals"] = -1
    with pytest.raises(ValueError):
        read_unit_observations(_payload(document))


def test_empty_observation_document_is_not_a_training_population() -> None:
    document = {"version": UNIT_INPUT_VERSION, "kind": "observations", "observations": []}
    with pytest.raises(ValueError, match="nonempty"):
        read_unit_observations(_payload(document))
