"""The write-free LLMOPT draft endpoint."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from squadopt.platform import ApiError, ApiErrorResponse
from squadopt.platform.advice_submit import client_address_bucket
from squadopt.platform.llmopt_intent import (
    INTENT_BODY_MAX_BYTES,
    IntentLimited,
    IntentService,
    IntentUnavailable,
    IntentValidationError,
    parse_intent_request,
    read_intent_json,
)


def _error(status: int, code: str, message: str, *, retry_after: int | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        ApiErrorResponse(ApiError(code=code, message=message)).to_dict(),
        status_code=status,
        headers=headers,
    )


def intent_routes(service: IntentService | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/llmopt")

    @router.post("/intent")
    async def prepare_intent(request: Request) -> JSONResponse:
        if service is None:
            return _error(503, "LLMOPT_DISABLED", "LLMOPT text interpretation is not configured.")
        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type != "application/json":
            return _error(415, "UNSUPPORTED_MEDIA_TYPE", "JSON required.")
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > INTENT_BODY_MAX_BYTES:
                return _error(413, "PAYLOAD_TOO_LARGE", "Intent request too large.")
            raw.extend(chunk)
        try:
            intent = parse_intent_request(read_intent_json(raw))
        except IntentValidationError as error:
            return _error(422, "VALIDATION_FAILED", str(error))
        client = client_address_bucket(request.client.host if request.client else "unknown")
        try:
            result = await run_in_threadpool(service.prepare, intent, client)
        except IntentLimited as error:
            return _error(429, "RATE_LIMITED", str(error), retry_after=error.retry_after)
        except IntentUnavailable:
            return _error(
                503, "LLMOPT_UNAVAILABLE", "The intent provider is temporarily unavailable."
            )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    return router
