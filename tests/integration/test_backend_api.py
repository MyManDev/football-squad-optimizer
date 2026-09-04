"""HTTP integration tests for the read-only backend boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient

from squadopt.api import (
    FilePublishedViewStore,
    PublishedViewIntegrityError,
    create_app,
)
from squadopt.application import ui_view_schema
from squadopt.platform import ApiServiceInfo, backend_api_schema

REPOSITORY_ROOT = Path(__file__).parents[2]
SITE_DATA_ROOT = REPOSITORY_ROOT / "web" / "public" / "data"


def _validate_backend(document: dict[str, Any], definition: str) -> None:
    schema = backend_api_schema()
    jsonschema.validate(document, {**schema["$defs"][definition], "$defs": schema["$defs"]})


def _validate_view(document: dict[str, Any], definition: str) -> None:
    schema = ui_view_schema()
    exact_envelope = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "allOf": [
            {"$ref": "#/$defs/ViewEnvelope"},
            {
                "type": "object",
                "properties": {"payload": {"$ref": f"#/$defs/{definition}"}},
                "required": ["payload"],
            },
        ],
    }
    jsonschema.validate(document, exact_envelope)


class _ExplodingStore:
    def seasons(self) -> dict[str, object]:
        raise AssertionError("health endpoints must not query published views")

    def season_status(self, season: str) -> dict[str, object]:
        raise AssertionError(season)

    def league(self, season: str) -> dict[str, object]:
        raise AssertionError(season)

    def ledger(self, season: str) -> dict[str, object]:
        raise AssertionError(season)

    def recommendation(self, season: str, gameweek: int) -> dict[str, object]:
        raise AssertionError((season, gameweek))

    def pool(self, season: str, gameweek: int) -> dict[str, object]:
        raise AssertionError((season, gameweek))


def test_health_and_info_are_contract_exact_without_querying_the_engine() -> None:
    client = TestClient(create_app(view_store=_ExplodingStore()))

    for route in ("/health", "/api/v1/info"):
        response = client.get(route)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == ApiServiceInfo().to_dict()
        _validate_backend(response.json(), "ApiServiceInfo")


@pytest.mark.parametrize(
    ("route", "relative_path", "definition"),
    [
        ("/api/v1/seasons", "index.json", "SiteIndex"),
        ("/api/v1/seasons/2026-27/status", "2026-27/status.json", "StatusView"),
        ("/api/v1/seasons/2026-27/league", "2026-27/league.json", "LeagueView"),
        ("/api/v1/seasons/2026-27/ledger", "2026-27/ledger.json", "LedgerView"),
        (
            "/api/v1/seasons/2026-27/gameweeks/1/recommendation",
            "2026-27/gw01/recommendation.json",
            "RecommendationView",
        ),
        (
            "/api/v1/seasons/2026-27/gameweeks/1/pool",
            "2026-27/gw01/pool.json",
            "PoolView",
        ),
    ],
)
def test_read_routes_return_the_exact_checked_site_documents(
    route: str,
    relative_path: str,
    definition: str,
) -> None:
    client = TestClient(create_app(data_root=SITE_DATA_ROOT))
    expected = json.loads((SITE_DATA_ROOT / relative_path).read_text(encoding="utf-8"))

    response = client.get(route)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.json() == expected
    _validate_view(response.json(), definition)


def test_missing_view_returns_the_standard_public_error() -> None:
    client = TestClient(create_app(data_root=SITE_DATA_ROOT))

    response = client.get("/api/v1/seasons/2099-00/status")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    _validate_backend(response.json(), "ApiErrorResponse")


@pytest.mark.parametrize(
    "route",
    [
        "/api/v1/seasons/2026_27/status",
        "/api/v1/seasons/2026-27/gameweeks/0/pool",
    ],
)
def test_invalid_route_values_return_the_standard_validation_error(route: str) -> None:
    client = TestClient(create_app(data_root=SITE_DATA_ROOT))

    response = client.get(route)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    _validate_backend(response.json(), "ApiErrorResponse")


def test_unknown_route_returns_the_standard_not_found_error() -> None:
    client = TestClient(create_app(data_root=SITE_DATA_ROOT))

    response = client.get("/api/v1/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    _validate_backend(response.json(), "ApiErrorResponse")


def test_tampered_view_is_rejected_without_exposing_its_path() -> None:
    data_root = REPOSITORY_ROOT / "tests" / "fixtures" / "api_invalid_data"
    private_path = data_root / "index.json"
    client = TestClient(create_app(data_root=data_root), raise_server_exceptions=False)

    response = client.get("/api/v1/seasons")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert str(private_path) not in response.text
    assert "tampered" not in response.text
    _validate_backend(response.json(), "ApiErrorResponse")


def test_store_rejects_non_route_identifiers_before_touching_the_filesystem() -> None:
    store = FilePublishedViewStore(SITE_DATA_ROOT)

    with pytest.raises(PublishedViewIntegrityError, match="safe published-view identifier"):
        store.season_status("../private")
    with pytest.raises(PublishedViewIntegrityError, match="positive integer"):
        store.pool("2026-27", 0)


class _UnexpectedFailureStore(_ExplodingStore):
    def seasons(self) -> dict[str, object]:
        raise RuntimeError(r"database password at C:\private\secrets.txt")


def test_unexpected_errors_are_logged_but_publicly_sanitized() -> None:
    client = TestClient(
        create_app(view_store=_UnexpectedFailureStore()),
        raise_server_exceptions=False,
    )

    response = client.get("/api/v1/seasons")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "password" not in response.text
    assert "private" not in response.text
    _validate_backend(response.json(), "ApiErrorResponse")
