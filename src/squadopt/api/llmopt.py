"""The write-free LLMOPT draft endpoints.

``/prompt`` and ``/check`` call no model, and the backend has none of its own: a member's
browser sends the call ``/prompt`` returns to the member's own provider with the member's
own key, and ``/check`` validates the reply (ADR 0017). The backend never receives that
key, so both routes refuse any request that carries one.
"""

from collections.abc import Callable
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from squadopt.platform import ApiError, ApiErrorResponse
from squadopt.platform.advice_submit import FixedWindowRateLimiter, client_address_bucket
from squadopt.platform.llmopt_intent import (
    INTENT_BODY_MAX_BYTES,
    IntentValidationError,
    check_reply,
    parse_check_request,
    parse_intent_request,
    prompt_for,
    read_intent_json,
)

#: Requests a visitor may make to each keyless route in a minute.
KEYLESS_PER_MINUTE: Final = 20
#: Headers that carry a model key. A keyless route refuses a request with any of them.
_KEY_HEADERS: Final = ("authorization", "x-api-key", "x-goog-api-key")


class _Refusal(Exception):
    def __init__(self, response: JSONResponse) -> None:
        super().__init__(response.status_code)
        self.response = response


def _error(status: int, code: str, message: str, *, retry_after: int | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        ApiErrorResponse(ApiError(code=code, message=message)).to_dict(),
        status_code=status,
        headers=headers,
    )


def _client(request: Request) -> str:
    return client_address_bucket(request.client.host if request.client else "unknown")


async def _json_body(request: Request) -> object:
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/json":
        raise _Refusal(_error(415, "UNSUPPORTED_MEDIA_TYPE", "JSON required."))
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > INTENT_BODY_MAX_BYTES:
            raise _Refusal(_error(413, "PAYLOAD_TOO_LARGE", "Intent request too large."))
        raw.extend(chunk)
    try:
        return read_intent_json(raw)
    except IntentValidationError as error:
        raise _Refusal(_error(422, "VALIDATION_FAILED", str(error))) from None


async def _keyless_body(request: Request, limiter: FixedWindowRateLimiter) -> object:
    """The JSON body of a keyless route, after its key-header and per-visitor checks."""
    if any(name in request.headers for name in _KEY_HEADERS):
        raise _Refusal(_error(400, "CREDENTIAL_REFUSED", "This route never takes a model key."))
    body = await _json_body(request)
    if not limiter.allow(_client(request)):
        raise _Refusal(
            _error(
                429,
                "RATE_LIMITED",
                "Intent request limit reached.",
                retry_after=int(limiter.window_seconds),
            )
        )
    return body


def intent_routes(
    *,
    keyless_per_minute: int = KEYLESS_PER_MINUTE,
    server_data_id: Callable[[], str | None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/llmopt")
    # Each keyless route counts on its own: one message is one prompt and one check.
    prompt_limiter = FixedWindowRateLimiter(keyless_per_minute, 60)
    check_limiter = FixedWindowRateLimiter(keyless_per_minute, 60)

    @router.post("/prompt")
    async def intent_prompt(request: Request) -> JSONResponse:
        try:
            intent = parse_intent_request(await _keyless_body(request, prompt_limiter))
        except _Refusal as refusal:
            return refusal.response
        except IntentValidationError as error:
            return _error(422, "VALIDATION_FAILED", str(error))
        call = await run_in_threadpool(prompt_for, intent)
        return JSONResponse(call.payload(), headers={"Cache-Control": "no-store"})

    @router.post("/check")
    async def intent_check(request: Request) -> JSONResponse:
        try:
            intent, reply = parse_check_request(await _keyless_body(request, check_limiter))
        except _Refusal as refusal:
            return refusal.response
        except IntentValidationError as error:
            return _error(422, "VALIDATION_FAILED", str(error))
        try:
            current = server_data_id() if server_data_id is not None else None
            result = await run_in_threadpool(check_reply, intent, reply, server_data_id=current)
        except IntentValidationError:
            return _error(422, "REPLY_REFUSED", "The model's reply is not a valid draft.")
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    return router
