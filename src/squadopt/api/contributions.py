"""Public submission/read routes; moderation is deliberately not a public API."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response
from jsonschema import ValidationError
from starlette.concurrency import run_in_threadpool

from squadopt.application.player_catalog import validate_catalog
from squadopt.platform.contributions import ContributionsLimitedError, ContributionStore


class ContributionError(HTTPException):
    """A bounded public message whose status must survive the API's generic handler."""


def contribution_routes(store: ContributionStore, data_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1/contributions")

    def catalog() -> dict[str, Any]:
        try:
            return validate_catalog(json.loads((data_root / "players.json").read_text("utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise ContributionError(503, "Player list is unavailable") from exc

    @router.get("/players")
    def players(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return catalog()

    @router.get("")
    def comments(
        response: Response,
        season: str = Query(pattern=r"^[0-9]{4}-[0-9]{2}$"),
        player_id: int = Query(gt=0),
        before: int = Query(default=2**63 - 1, gt=0, le=2**63 - 1),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            rows = store.public(season, player_id, before)
        except (sqlite3.Error, OSError) as exc:
            raise ContributionError(503, "Comments temporarily unavailable") from exc
        return {"comments": rows, "next_before": rows[-1]["id"] if len(rows) == 50 else None}

    @router.post("", status_code=202)
    async def submit(request: Request) -> dict[str, Any]:
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise ContributionError(415, "JSON required")
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 12000:
                raise ContributionError(413, "Comment too large")
            raw.extend(chunk)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ContributionError(422, "Invalid JSON") from exc
        fields = {"season", "player_id", "author", "body", "source", "consent"}
        if not isinstance(body, dict) or set(body) != fields or body["consent"] is not True:
            raise ContributionError(
                422, "Explicit publication consent and declared fields required"
            )
        for name, minimum, maximum in (("author", 2, 40), ("body", 10, 1500), ("source", 0, 500)):
            value = body[name]
            if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
                raise ContributionError(422, "Invalid comment fields")
            if any(ord(char) < 32 and char not in "\n\t" for char in value):
                raise ContributionError(422, "Control characters are not allowed")
            body[name] = value.strip()
        if body["source"]:
            try:
                url = urlsplit(body["source"])
                if url.scheme != "https" or not url.hostname or url.username or url.password:
                    raise ValueError
            except ValueError as exc:
                raise ContributionError(422, "Source must be a public HTTPS URL") from exc
        current = await run_in_threadpool(catalog)
        player = next((p for p in current["players"] if p["id"] == body["player_id"]), None)
        if type(body["player_id"]) is not int or body["season"] != current["season"] or not player:
            raise ContributionError(422, "Choose a player from the current published roster")
        try:
            identity = await run_in_threadpool(
                store.submit,
                season=current["season"],
                player_id=player["id"],
                player_name=player["name"],
                author=body["author"],
                body=body["body"],
                source=body["source"],
                client=request.client.host if request.client else "unknown",
            )
        except ContributionsLimitedError as exc:
            raise ContributionError(
                429, "Submission limit reached", headers={"Retry-After": "3600"}
            ) from exc
        except (sqlite3.Error, OSError) as exc:
            raise ContributionError(503, "Comment was not saved; retry later") from exc
        return {"id": identity, "status": "pending"}

    return router
