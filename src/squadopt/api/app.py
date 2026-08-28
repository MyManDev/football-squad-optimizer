"""FastAPI entry point for SquadOpt's read-only HTTP surface."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final

from fastapi import FastAPI, Query, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHttpException

from squadopt.api.views import (
    FilePublishedViewStore,
    JsonDocument,
    PublishedViewIntegrityError,
    PublishedViewNotFoundError,
    PublishedViewStore,
)
from squadopt.platform import BACKEND_API_VERSION, ApiError, ApiErrorResponse, ApiServiceInfo
from squadopt.platform.advice_documents import AdviceDocumentError
from squadopt.platform.advice_read import (
    AdviceBackendNotReadyError,
    AdviceNotComputedError,
    AdviceReadStore,
    LeagueNotConnectedError,
    UnknownEntryError,
    UnknownStrategyError,
)
from squadopt.platform.advice_submit import (
    AdviceSubmitService,
    IdempotencyConflictError,
    RateLimitedError,
)
from squadopt.platform.api_contract import BackendApiContractError

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


def _parse_advise_body(body: object) -> tuple[str, int, int | None]:
    """The AdviseRequestBody schema, enforced in one place.

    Exactly the declared keys (additionalProperties: false), a string strategy, an
    integer window of 1/3/5 with bool explicitly refused, and a rival that is null or
    a positive integer. Every refusal is a contract error the route maps onto 422 —
    a malformed body is the client's mistake, never this process's 500.
    """

    if not isinstance(body, dict):
        raise BackendApiContractError("The POST body must be an object.")
    allowed = {"strategy", "window", "rival_entry_id"}
    unexpected = set(body) - allowed
    if unexpected:
        raise BackendApiContractError(f"Unexpected body fields: {sorted(unexpected)!r}.")
    strategy = body.get("strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        raise BackendApiContractError("strategy must be a non-empty string.")
    window = body.get("window")
    if isinstance(window, bool) or window not in (1, 3, 5):
        raise BackendApiContractError("window must be 1, 3, or 5.")
    rival = body.get("rival_entry_id")
    if rival is not None and (isinstance(rival, bool) or not isinstance(rival, int) or rival < 1):
        raise BackendApiContractError("rival_entry_id must be null or a positive integer.")
    return strategy, window, rival


def create_app(
    *,
    data_root: str | Path = DEFAULT_SITE_DATA_ROOT,
    view_store: PublishedViewStore | None = None,
    advice_store: AdviceReadStore | None = None,
    advice_submit: AdviceSubmitService | None = None,
    allowed_origins: tuple[str, ...] = (),
    utc_now: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build the API with an injectable read adapter and no solver startup work.

    ``advice_store`` is the on-demand read side; without one (the default, and the
    whole app before this existed) the advice routes answer 503 with an explicit
    code rather than pretending an empty cache is a computed absence.
    """

    store = view_store if view_store is not None else FilePublishedViewStore(data_root)
    application = FastAPI(
        title="SquadOpt API",
        description="Read-only access to published SquadOpt application views.",
        version=BACKEND_API_VERSION,
    )
    if allowed_origins:
        # An allowlist, never a wildcard: the origins are the Pages domains, read from
        # configuration by the composition root. No origins configured means no CORS
        # headers at all, which fails closed.
        if "*" in allowed_origins:
            raise ValueError("The CORS allowlist may not contain a wildcard.")
        from starlette.middleware.cors import CORSMiddleware

        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Idempotency-Key"],
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

    @application.exception_handler(LeagueNotConnectedError)
    async def league_not_connected(
        _request: Request, error: LeagueNotConnectedError
    ) -> JSONResponse:
        return _contract_error(404, "LEAGUE_NOT_CONNECTED", str(error))

    @application.exception_handler(UnknownEntryError)
    async def unknown_entry(_request: Request, error: UnknownEntryError) -> JSONResponse:
        return _contract_error(404, "UNKNOWN_ENTRY", str(error))

    @application.exception_handler(UnknownStrategyError)
    async def unknown_strategy(_request: Request, error: UnknownStrategyError) -> JSONResponse:
        return _contract_error(404, "UNKNOWN_STRATEGY", str(error))

    @application.exception_handler(AdviceNotComputedError)
    async def advice_not_computed(_request: Request, error: AdviceNotComputedError) -> JSONResponse:
        return _contract_error(404, "NOT_COMPUTED", str(error))

    @application.exception_handler(AdviceDocumentError)
    async def advice_document_invalid(request: Request, error: AdviceDocumentError) -> JSONResponse:
        _log_exception("api.advice_document_invalid", request, error)
        return _contract_error(500, "INTERNAL_ERROR", "The stored advice is unavailable.")

    @application.exception_handler(AdviceBackendNotReadyError)
    async def advice_not_ready(
        _request: Request, error: AdviceBackendNotReadyError
    ) -> JSONResponse:
        return _contract_error(503, "NOT_READY", str(error))

    @application.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(
        _request: Request, error: IdempotencyConflictError
    ) -> JSONResponse:
        return _contract_error(409, "IDEMPOTENCY_CONFLICT", str(error))

    @application.exception_handler(RateLimitedError)
    async def rate_limited(_request: Request, error: RateLimitedError) -> JSONResponse:
        return _contract_error(429, "RATE_LIMITED", str(error))

    @application.get("/api/v1/leagues/{league_id}", response_class=JSONResponse)
    def league_state(league_id: Annotated[int, ApiPath(ge=1)]) -> JSONResponse:
        if advice_store is None:
            return _contract_error(503, "ADVICE_BACKEND_DISABLED", "No advice backend here.")
        return JSONResponse(
            content=advice_store.league_state(league_id),
            headers={"Cache-Control": "no-cache"},
        )

    @application.get(
        "/api/v1/leagues/{league_id}/entries/{entry_id}/advice",
        response_class=Response,
    )
    def read_advice(
        league_id: Annotated[int, ApiPath(ge=1)],
        entry_id: Annotated[int, ApiPath(ge=1)],
        strategy: Annotated[str, Query(pattern=r"^[a-z][a-z0-9._-]{0,63}$")],
        window: Annotated[int, Query()],
        rival: Annotated[int | None, Query(ge=1)] = None,
    ) -> Response:
        if advice_store is None:
            return _contract_error(503, "ADVICE_BACKEND_DISABLED", "No advice backend here.")
        if window not in (1, 3, 5):
            return _contract_error(422, "VALIDATION_FAILED", "window must be 1, 3, or 5.")
        payload = advice_store.read_advice(
            league_id=league_id,
            entry_id=entry_id,
            strategy=strategy,
            window=window,
            rival_entry_id=rival,
        )
        # The cache holds the exact published bytes; serving them unparsed keeps the
        # api a reader and the answer identical wherever it is read from.
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Cache-Control": "no-cache"},
        )

    @application.post(
        "/api/v1/leagues/{league_id}/entries/{entry_id}/advice",
        response_class=Response,
    )
    async def request_advice(
        request: Request,
        league_id: Annotated[int, ApiPath(ge=1)],
        entry_id: Annotated[int, ApiPath(ge=1)],
    ) -> Response:
        if advice_submit is None:
            return _contract_error(503, "ADVICE_BACKEND_DISABLED", "No advice backend here.")
        try:
            body = await request.json()
        except Exception:
            return _contract_error(422, "VALIDATION_FAILED", "The POST body must be JSON.")
        try:
            strategy, window, rival = _parse_advise_body(body)
        except BackendApiContractError as error:
            return _contract_error(422, "VALIDATION_FAILED", str(error))
        current = datetime.now(UTC) if utc_now is None else utc_now()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("utc_now must return a timezone-aware datetime.")

        outcome = advice_submit.submit(
            league_id=league_id,
            entry_id=entry_id,
            strategy=strategy,
            window=window,
            rival_entry_id=rival,
            idempotency_key=request.headers.get("Idempotency-Key"),
            client_bucket=request.client.host if request.client else "unknown",
            at_utc=current.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        if outcome.kind == "hit" and outcome.payload is not None:
            return Response(
                content=outcome.payload,
                media_type="application/json",
                headers={"Cache-Control": "no-cache"},
            )
        assert outcome.job is not None
        return JSONResponse(
            status_code=202,
            content={"job_id": outcome.job.job_id, "status": outcome.job.status},
        )

    @application.get("/api/v1/advice-jobs/{job_id}", response_class=JSONResponse)
    def advice_job(job_id: str) -> JSONResponse:
        if advice_submit is None:
            return _contract_error(503, "ADVICE_BACKEND_DISABLED", "No advice backend here.")
        try:
            view = advice_submit.public_job_view(job_id)
        except Exception:
            return _contract_error(404, "NOT_FOUND", "No such advice job.")
        if view is None:
            return _contract_error(404, "NOT_FOUND", "No such advice job.")
        return JSONResponse(content=view, headers={"Cache-Control": "no-cache"})

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
