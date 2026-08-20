"""FastAPI entry point for SquadOpt's read-only HTTP surface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Final

from fastapi import FastAPI, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHttpException

from squadopt.api.views import (
    FilePublishedViewStore,
    JsonDocument,
    PublishedViewIntegrityError,
    PublishedViewNotFoundError,
    PublishedViewStore,
)
from squadopt.platform import BACKEND_API_VERSION, ApiError, ApiErrorResponse, ApiServiceInfo

DEFAULT_SITE_DATA_ROOT: Final = Path("web") / "public" / "data"
_SEASON_PATTERN: Final = r"^[0-9]{4}-[0-9]{2}$"
_LOGGER = logging.getLogger(__name__)

SeasonPath = Annotated[str, ApiPath(pattern=_SEASON_PATTERN)]
GameweekPath = Annotated[int, ApiPath(ge=1)]


def _contract_error(status_code: int, code: str, message: str) -> JSONResponse:
    document = ApiErrorResponse(ApiError(code=code, message=message)).to_dict()
    return JSONResponse(status_code=status_code, content=document)


def _view_response(document: JsonDocument) -> JSONResponse:
    return JSONResponse(content=document, headers={"Cache-Control": "no-cache"})


def _log_exception(message: str, request: Request, error: Exception) -> None:
    _LOGGER.error(
        message,
        exc_info=(type(error), error, error.__traceback__),
        extra={"fields": {"method": request.method, "path": request.url.path}},
    )


def create_app(
    *,
    data_root: str | Path = DEFAULT_SITE_DATA_ROOT,
    view_store: PublishedViewStore | None = None,
) -> FastAPI:
    """Build the API with an injectable read adapter and no solver startup work."""

    store = view_store if view_store is not None else FilePublishedViewStore(data_root)
    application = FastAPI(
        title="SquadOpt API",
        description="Read-only access to published SquadOpt application views.",
        version=BACKEND_API_VERSION,
    )

    @application.exception_handler(PublishedViewNotFoundError)
    async def published_view_not_found(
        _request: Request,
        _error: PublishedViewNotFoundError,
    ) -> JSONResponse:
        return _contract_error(404, "NOT_FOUND", "The requested published view was not found.")

    @application.exception_handler(PublishedViewIntegrityError)
    async def published_view_invalid(
        request: Request,
        error: PublishedViewIntegrityError,
    ) -> JSONResponse:
        _log_exception("api.published_view_invalid", request, error)
        return _contract_error(500, "INTERNAL_ERROR", "The published view is unavailable.")

    @application.exception_handler(RequestValidationError)
    async def request_invalid(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return _contract_error(
            422,
            "VALIDATION_FAILED",
            "The request did not match the API contract.",
        )

    @application.exception_handler(StarletteHttpException)
    async def http_error(
        _request: Request,
        error: StarletteHttpException,
    ) -> JSONResponse:
        if error.status_code == 404:
            return _contract_error(404, "NOT_FOUND", "The requested API route was not found.")
        return _contract_error(400, "BAD_REQUEST", "The HTTP request is not supported.")

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        _log_exception("api.unexpected_error", request, error)
        return _contract_error(500, "INTERNAL_ERROR", "The request failed unexpectedly.")

    @application.get("/health", response_class=JSONResponse)
    def health() -> JSONResponse:
        return JSONResponse(content=ApiServiceInfo().to_dict())

    @application.get("/api/v1/info", response_class=JSONResponse)
    def info() -> JSONResponse:
        return JSONResponse(content=ApiServiceInfo().to_dict())

    @application.get("/api/v1/seasons", response_class=JSONResponse)
    def seasons() -> JSONResponse:
        return _view_response(store.seasons())

    @application.get("/api/v1/seasons/{season}/status", response_class=JSONResponse)
    def season_status(season: SeasonPath) -> JSONResponse:
        return _view_response(store.season_status(season))

    @application.get("/api/v1/seasons/{season}/league", response_class=JSONResponse)
    def league(season: SeasonPath) -> JSONResponse:
        return _view_response(store.league(season))

    @application.get("/api/v1/seasons/{season}/ledger", response_class=JSONResponse)
    def ledger(season: SeasonPath) -> JSONResponse:
        return _view_response(store.ledger(season))

    @application.get(
        "/api/v1/seasons/{season}/gameweeks/{gameweek}/recommendation",
        response_class=JSONResponse,
    )
    def recommendation(season: SeasonPath, gameweek: GameweekPath) -> JSONResponse:
        return _view_response(store.recommendation(season, gameweek))

    @application.get(
        "/api/v1/seasons/{season}/gameweeks/{gameweek}/pool",
        response_class=JSONResponse,
    )
    def pool(season: SeasonPath, gameweek: GameweekPath) -> JSONResponse:
        return _view_response(store.pool(season, gameweek))

    return application


app = create_app()

__all__ = ["DEFAULT_SITE_DATA_ROOT", "app", "create_app"]
