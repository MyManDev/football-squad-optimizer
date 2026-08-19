"""Platform run identity and the portable ``run_manifest_v1`` contract."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from squadopt.platform import (
    RUN_CONTEXT_CONTRACT_VERSION,
    RUN_MANIFEST_CONTRACT_VERSION,
    RUN_MANIFEST_SCHEMA_PATH,
    RunContext,
    RunContextError,
    RunManifestError,
    parse_run_manifest,
    read_run_manifest,
    run_manifest_document,
    run_manifest_schema,
    serialize_run_manifest,
    write_run_manifest,
    write_run_manifest_schema,
)

COMMIT = "a" * 40
CONFIG = "b" * 64
SNAPSHOT = "c" * 64
PROJECTIONS = "d" * 64
NOW = datetime(2026, 8, 19, 12, 30, 15, 123000, tzinfo=UTC)


def _context(**changes: object) -> RunContext:
    values: dict[str, object] = {
        "run_id": "gw01-20260819-a81f",
        "repository_commit": COMMIT,
        "configuration_fingerprint": CONFIG,
        "input_fingerprints": {
            "snapshot": SNAPSHOT,
            "projections": PROJECTIONS,
        },
        "component_versions": {
            "optimizer": "cvar-v3",
            "prediction": "learned-rate-v2",
        },
        "deterministic_seed": 20260819,
        "created_at_utc": "2026-08-19T12:30:15.123000Z",
    }
    values.update(changes)
    return RunContext(**values)  # type: ignore[arg-type]


def test_context_is_normalized_deeply_immutable_and_has_a_pinned_fingerprint() -> None:
    inputs = {"snapshot": SNAPSHOT, "projections": PROJECTIONS}
    components = {"prediction": "learned-rate-v2", "optimizer": "cvar-v3"}
    context = _context(
        input_fingerprints=inputs,
        component_versions=components,
        created_at_utc="2026-08-19T12:30:15.123000+00:00",
    )
    inputs["snapshot"] = "e" * 64
    components["prediction"] = "changed"

    assert context.contract_version == RUN_CONTEXT_CONTRACT_VERSION
    assert context.created_at_utc == "2026-08-19T12:30:15.123000Z"
    assert list(context.input_fingerprints) == ["projections", "snapshot"]
    assert list(context.component_versions) == ["optimizer", "prediction"]
    assert context.input_fingerprints["snapshot"] == SNAPSHOT
    assert context.component_versions["prediction"] == "learned-rate-v2"
    assert context.reproducibility_fingerprint == (
        "afa00cda057ab4587e6f4927b17dc7b8d285fe7181458c0bcb6f13dcd585334e"
    )


def test_attempt_identity_does_not_change_reproducibility_identity() -> None:
    first = _context()
    retry = replace(
        first,
        run_id="gw01-20260819-retry",
        created_at_utc="2026-08-19T12:35:00Z",
    )
    assert retry.run_id != first.run_id
    assert retry.created_at_utc != first.created_at_utc
    assert retry.reproducibility_fingerprint == first.reproducibility_fingerprint


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository_commit", "f" * 40),
        ("configuration_fingerprint", "f" * 64),
        ("input_fingerprints", {"snapshot": "f" * 64}),
        ("component_versions", {"optimizer": "mean-v1"}),
        ("deterministic_seed", 7),
    ],
)
def test_each_determining_input_changes_the_reproducibility_identity(
    field: str, value: object
) -> None:
    baseline = _context()
    changed = replace(baseline, **{field: value})
    assert changed.reproducibility_fingerprint != baseline.reproducibility_fingerprint


def test_factory_generates_distinct_operational_ids_and_accepts_injected_values() -> None:
    values = {
        "repository_commit": COMMIT,
        "configuration_fingerprint": CONFIG,
        "input_fingerprints": {"snapshot": SNAPSHOT},
        "deterministic_seed": 42,
    }
    first = RunContext.create(**values, now=NOW)
    second = RunContext.create(**values, now=NOW)
    replay = RunContext.create(**values, now=NOW, run_id="replay-01")

    assert first.run_id.startswith("20260819T123015Z-")
    assert first.run_id != second.run_id
    assert replay.run_id == "replay-01"
    assert replay.created_at_utc == "2026-08-19T12:30:15.123000Z"
    assert first.reproducibility_fingerprint == replay.reproducibility_fingerprint


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"run_id": "spaces are unsafe"}, "run_id"),
        ({"repository_commit": "abc123"}, "repository_commit"),
        ({"configuration_fingerprint": "A" * 64}, "configuration_fingerprint"),
        ({"input_fingerprints": {}}, "input_fingerprints"),
        ({"input_fingerprints": {"Bad Name": SNAPSHOT}}, "input_fingerprints name"),
        ({"component_versions": {"optimizer": " "}}, "component_versions"),
        ({"deterministic_seed": True}, "deterministic_seed"),
        ({"deterministic_seed": -1}, "deterministic_seed"),
        ({"created_at_utc": "2026-08-19T12:30:15"}, "created_at_utc"),
        ({"created_at_utc": "2026-08-19T15:30:15+03:00"}, "created_at_utc"),
        ({"contract_version": "run_context_v2"}, "contract_version"),
    ],
)
def test_invalid_context_values_are_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(RunContextError, match=message):
        _context(**changes)


def test_factory_rejects_a_naive_or_non_utc_clock() -> None:
    values = {
        "repository_commit": COMMIT,
        "configuration_fingerprint": CONFIG,
        "input_fingerprints": {"snapshot": SNAPSHOT},
        "deterministic_seed": 42,
    }
    with pytest.raises(RunContextError, match="now"):
        RunContext.create(**values, now=datetime(2026, 8, 19, 12, 30))
    with pytest.raises(RunContextError, match="now"):
        RunContext.create(
            **values,
            now=datetime(2026, 8, 19, 15, 30, tzinfo=timezone(timedelta(hours=3))),
        )


def test_manifest_schema_is_valid_committed_and_accepts_the_document(tmp_path: Path) -> None:
    schema = run_manifest_schema()
    document = run_manifest_document(_context())

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(document, schema)
    assert json.loads(RUN_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8")) == schema
    written = write_run_manifest_schema(tmp_path / "schema.json")
    assert json.loads(written.read_text(encoding="utf-8")) == schema
    assert document["contract_version"] == RUN_MANIFEST_CONTRACT_VERSION


def test_manifest_serialization_is_deterministic_and_round_trips() -> None:
    context = _context()
    reordered = _context(
        input_fingerprints={"projections": PROJECTIONS, "snapshot": SNAPSHOT},
        component_versions={"optimizer": "cvar-v3", "prediction": "learned-rate-v2"},
    )

    encoded = serialize_run_manifest(context)
    assert encoded == serialize_run_manifest(reordered)
    assert encoded.endswith(b"\n") and b"\r\n" not in encoded
    assert parse_run_manifest(encoded) == context
    assert parse_run_manifest(encoded.decode("utf-8")) == context


def test_manifest_parser_rejects_tampering_unknown_fields_and_bad_json() -> None:
    document = run_manifest_document(_context())
    context = document["context"]
    assert isinstance(context, dict)
    context["deterministic_seed"] = 7

    with pytest.raises(RunManifestError, match="reproducibility_fingerprint"):
        parse_run_manifest(json.dumps(document))

    document = run_manifest_document(_context())
    document["unexpected"] = True
    with pytest.raises(RunManifestError, match="exactly"):
        parse_run_manifest(json.dumps(document))
    with pytest.raises(RunManifestError, match="valid JSON"):
        parse_run_manifest("{broken")
    with pytest.raises(RunManifestError, match="UTF-8"):
        parse_run_manifest(b"\xff")


def test_manifest_parser_rejects_a_noncanonical_utc_spelling() -> None:
    document = run_manifest_document(_context())
    context = document["context"]
    assert isinstance(context, dict)
    context["created_at_utc"] = "2026-08-19T12:30:15.123000+00:00"

    with pytest.raises(RunManifestError, match="canonical UTC"):
        parse_run_manifest(json.dumps(document))


def test_manifest_write_is_atomic_idempotent_and_refuses_reuse(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "gw01" / "manifest.json"
    context = _context()

    assert write_run_manifest(path, context) == path
    first_bytes = path.read_bytes()
    assert write_run_manifest(path, context) == path
    assert path.read_bytes() == first_bytes
    assert read_run_manifest(path) == context
    assert not tuple(path.parent.glob(".manifest.json.tmp-*"))

    with pytest.raises(RunManifestError, match="different content"):
        write_run_manifest(path, replace(context, deterministic_seed=7))
    assert path.read_bytes() == first_bytes
