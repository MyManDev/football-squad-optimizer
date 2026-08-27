"""Transport-neutral backend API request, response, and schema contracts."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from squadopt.platform import (
    BACKEND_API_CONTRACT_VERSION,
    BACKEND_API_SCHEMA_PATH,
    BACKEND_API_VERSION,
    ApiCommandRequest,
    ApiError,
    ApiErrorResponse,
    ApiRunResponse,
    ApiServiceInfo,
    BackendApiContractError,
    backend_api_schema,
    serialize_api_document,
)

FINGERPRINT = "a" * 64
REPRODUCIBILITY = "b" * 64
SNAPSHOT_ID = "fpl-live-20260820T153000Z-abc123"


def _decide(**changes: object) -> ApiCommandRequest:
    values: dict[str, object] = {
        "operation": "gameweek.decide",
        "idempotency_key": "client:gw01:1",
        "season": "2026-27",
        "gameweek": 1,
        "snapshot_id": SNAPSHOT_ID,
        "mode": "replay",
    }
    values.update(changes)
    return ApiCommandRequest(**values)  # type: ignore[arg-type]


def _completed(**changes: object) -> ApiRunResponse:
    values: dict[str, object] = {
        "run_id": "run-gw01-abc123",
        "operation": "gameweek.decide",
        "status": "completed",
        "request_fingerprint": FINGERPRINT,
        "reproducibility_fingerprint": REPRODUCIBILITY,
        "started_at_utc": "2026-08-20T15:30:00Z",
        "finished_at_utc": "2026-08-20T15:30:02Z",
        "runtime_seconds": 2.0,
        "output_artifact_ids": ("artifact-decision",),
        "result": {"season": "2026-27", "gameweek": 1},
    }
    values.update(changes)
    return ApiRunResponse(**values)  # type: ignore[arg-type]


def _validate(document: dict[str, Any], definition: str) -> None:
    schema = backend_api_schema()
    jsonschema.validate(document, {**schema["$defs"][definition], "$defs": schema["$defs"]})


def test_command_fingerprint_is_pinned_and_excludes_client_retry_key() -> None:
    request = _decide()
    retry = replace(request, idempotency_key="client:gw01:retry")

    assert request.contract_version == BACKEND_API_CONTRACT_VERSION
    assert request.request_fingerprint == (
        "24cce5cfa645f3fab2e534ff4840768a8ecf64b63e93c3da45f21c5a8e0478ca"
    )
    assert retry.request_fingerprint == request.request_fingerprint
    assert replace(request, gameweek=2).request_fingerprint != request.request_fingerprint
    assert replace(request, snapshot_id="snapshot-other").request_fingerprint != (
        request.request_fingerprint
    )


def test_each_command_has_one_strict_portable_shape_and_round_trips() -> None:
    commands = (
        _decide(),
        ApiCommandRequest(
            operation="gameweek.settle",
            idempotency_key="settle:2026-27:1",
            season="2026-27",
            gameweek=1,
            snapshot_id=SNAPSHOT_ID,
        ),
        ApiCommandRequest(
            operation="season.tick",
            idempotency_key="tick:2026-08-20T1530Z",
            season="2026-27",
            dry_run=True,
        ),
    )

    for request in commands:
        document = request.to_dict()
        assert ApiCommandRequest.from_dict(document) == request
        assert not any(key.endswith("_root") or key.endswith("_path") for key in document)
        _validate(document, "ApiCommandRequest")


def test_request_parser_rejects_added_server_paths_and_tampered_fingerprint() -> None:
    document = _decide().to_dict()
    document["snapshot_root"] = "C:\\private\\snapshots"
    with pytest.raises(BackendApiContractError, match="unexpected"):
        ApiCommandRequest.from_dict(document)
    with pytest.raises(jsonschema.ValidationError):
        _validate(document, "ApiCommandRequest")

    document = _decide().to_dict()
    document["request_fingerprint"] = "f" * 64
    with pytest.raises(BackendApiContractError, match="request_fingerprint"):
        ApiCommandRequest.from_dict(document)


def test_http_body_schemas_contain_only_client_choices() -> None:
    _validate({"mode": "live"}, "DecideRequestBody")
    _validate({}, "SettleRequestBody")
    _validate({}, "TickRequestBody")
    _validate({"dry_run": True}, "TickRequestBody")

    with pytest.raises(jsonschema.ValidationError):
        _validate({"mode": "live", "snapshot_root": "C:\\private"}, "DecideRequestBody")
    with pytest.raises(jsonschema.ValidationError):
        _validate({"snapshot_id": SNAPSHOT_ID, "season": "2026-27"}, "SettleRequestBody")
    with pytest.raises(jsonschema.ValidationError):
        _validate({"mode": "replay"}, "TickRequestBody")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"season": None}, "requires season"),
        ({"gameweek": True}, "gameweek"),
        ({"season": "26/27"}, "season"),
        ({"snapshot_id": None}, "replay mode requires"),
        ({"idempotency_key": "spaces are unsafe"}, "idempotency_key"),
        ({"mode": "preview"}, "mode"),
        ({"dry_run": True}, "dry_run"),
    ],
)
def test_invalid_decide_commands_are_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(BackendApiContractError, match=message):
        _decide(**changes)


def test_operation_specific_fields_cannot_leak_between_commands() -> None:
    with pytest.raises(BackendApiContractError, match="settle accepts no"):
        ApiCommandRequest(
            operation="gameweek.settle",
            idempotency_key="settle-1",
            season="2026-27",
            gameweek=1,
            chip="wildcard",
        )
    with pytest.raises(BackendApiContractError, match="tick accepts only"):
        ApiCommandRequest(
            operation="season.tick",
            idempotency_key="tick-1",
            season="2026-27",
            gameweek=1,
        )


def test_terminal_run_responses_enforce_success_and_failure_shapes() -> None:
    completed = _completed(started_at_utc="2026-08-20T15:30:00+00:00")
    assert completed.started_at_utc == "2026-08-20T15:30:00Z"
    assert completed.to_dict()["error"] is None
    _validate(completed.to_dict(), "ApiRunResponse")

    error = ApiError(
        code="INTERNAL_ERROR",
        message="The run failed unexpectedly.",
        run_id="run-gw01-abc123",
    )
    failed = _completed(
        status="failed",
        result=None,
        output_artifact_ids=(),
        error=error,
    )
    assert failed.to_dict()["error"] == error.to_dict()
    _validate(failed.to_dict(), "ApiRunResponse")

    with pytest.raises(BackendApiContractError, match="completed run"):
        _completed(error=error)
    with pytest.raises(BackendApiContractError, match="same run_id"):
        _completed(
            status="failed",
            result=None,
            error=replace(error, run_id="another-run"),
        )
    with pytest.raises(BackendApiContractError, match="finite non-negative"):
        _completed(runtime_seconds=float("nan"))


def test_errors_and_results_accept_json_values_but_reject_runtime_objects() -> None:
    response = ApiErrorResponse(
        ApiError(
            code="VALIDATION_FAILED",
            message="The command was rejected.",
            details={"fields": ["gameweek"], "retryable": False},
        )
    )
    _validate(response.to_dict(), "ApiErrorResponse")

    with pytest.raises(BackendApiContractError, match="JSON-native"):
        ApiError(
            code="INTERNAL_ERROR",
            message="Safe message.",
            details={"path": Path("private")},
        )
    with pytest.raises(BackendApiContractError, match="JSON-native"):
        _completed(result={"path": Path("private")})


def test_service_info_and_serialization_are_stable() -> None:
    info = ApiServiceInfo()
    assert info.to_dict() == {
        "contract_version": BACKEND_API_CONTRACT_VERSION,
        "service": "squadopt",
        "status": "ok",
        "api_version": BACKEND_API_VERSION,
    }
    _validate(info.to_dict(), "ApiServiceInfo")
    assert json.loads(serialize_api_document(info)) == info.to_dict()
    with pytest.raises(BackendApiContractError, match="cannot be overridden"):
        ApiServiceInfo(status="degraded")


def test_schema_is_valid_committed_deterministic_and_accepts_every_document() -> None:
    schema = backend_api_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    committed = json.loads(BACKEND_API_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == schema
    assert BACKEND_API_SCHEMA_PATH.read_text(encoding="utf-8") == (
        json.dumps(schema, indent=2, sort_keys=True) + "\n"
    )

    documents = (
        _decide().to_dict(),
        _completed().to_dict(),
        ApiErrorResponse(ApiError("NOT_FOUND", "No such run.")).to_dict(),
        ApiServiceInfo().to_dict(),
    )
    for document in documents:
        jsonschema.validate(document, schema)


# --- league.advise, added without moving a byte of the other three ------------------


def _advise(**changes: object) -> ApiCommandRequest:
    values: dict[str, object] = {
        "operation": "league.advise",
        "idempotency_key": "client:advise:1",
        "season": "2026-27",
        "gameweek": 3,
        "league_id": 352490,
        "entry_id": 313686,
        "strategy": "saf-puan",
        "window": 1,
    }
    values.update(changes)
    return ApiCommandRequest(**values)  # type: ignore[arg-type]


def test_advise_round_trips_validates_and_pins_its_own_fingerprint() -> None:
    request = _advise()
    document = request.to_dict()
    assert ApiCommandRequest.from_dict(document) == request
    _validate(document, "AdviseCommandRequest")
    # Pinned like the decide fingerprint: a normalization change must declare itself.
    assert request.request_fingerprint == (
        "55fa6a9c807bfd8de3e598ccd22deae004a087df3d941699f13c7e6a6e9d894f"
    )
    assert _advise(rival_entry_id=2199732).request_fingerprint != request.request_fingerprint
    assert _advise(window=3).request_fingerprint != request.request_fingerprint


def test_advise_shape_is_strict() -> None:
    with pytest.raises(BackendApiContractError, match="requires season"):
        _advise(window=None)
    with pytest.raises(BackendApiContractError, match="window must be 1, 3, or 5"):
        _advise(window=2)
    with pytest.raises(BackendApiContractError, match="may not equal entry_id"):
        _advise(rival_entry_id=313686)
    with pytest.raises(BackendApiContractError, match="current capture"):
        _advise(snapshot_id=SNAPSHOT_ID)
    with pytest.raises(BackendApiContractError, match="accepts no league"):
        _decide(league_id=352490)


def test_the_original_three_operations_did_not_move_a_byte() -> None:
    """The additive proof: the pinned decide fingerprint above is the primary gate;
    this one closes the loop for settle and tick payload shapes."""

    settle = ApiCommandRequest(
        operation="gameweek.settle",
        idempotency_key="settle:2026-27:1",
        season="2026-27",
        gameweek=1,
        snapshot_id=SNAPSHOT_ID,
    )
    tick = ApiCommandRequest(
        operation="season.tick", idempotency_key="tick:1", season="2026-27", dry_run=True
    )
    assert set(settle.to_dict()) == {
        "contract_version",
        "operation",
        "season",
        "gameweek",
        "snapshot_id",
        "idempotency_key",
        "request_fingerprint",
    }
    assert set(tick.to_dict()) == {
        "contract_version",
        "operation",
        "season",
        "dry_run",
        "idempotency_key",
        "request_fingerprint",
    }
