"""Read-only access to published ``ui_view_v1`` documents.

The HTTP adapter is allowed to expose the deterministic site views, not arbitrary files.
This store therefore presents one method per public resource and validates every document
against the application-owned schema before it crosses the HTTP boundary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Final, NoReturn, TypeAlias, cast

from jsonschema import Draft202012Validator, ValidationError

from squadopt.application.contract import ui_view_schema
from squadopt.platform import (
    JsonDocument,
    PublishedViewError,
    PublishedViewIntegrityError,
    PublishedViewNotFoundError,
    PublishedViewStore,
)

PayloadDefinition: TypeAlias = str

_SEASON_PATTERN: Final = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_PAYLOAD_DEFINITIONS: Final = (
    "SiteIndex",
    "StatusView",
    "LeagueView",
    "LedgerView",
    "RecommendationView",
    "PoolView",
)


def _reject_non_finite_json(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant {value!r}")


def _validate_season(season: str) -> str:
    if not isinstance(season, str) or not _SEASON_PATTERN.fullmatch(season):
        raise PublishedViewIntegrityError("season is not a safe published-view identifier")
    return season


def _validate_gameweek(gameweek: int) -> int:
    if isinstance(gameweek, bool) or not isinstance(gameweek, int) or gameweek < 1:
        raise PublishedViewIntegrityError("gameweek is not a positive integer")
    return gameweek


class FilePublishedViewStore:
    """Serve schema-checked views from the deterministic site data tree."""

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root).resolve()
        schema = ui_view_schema()
        Draft202012Validator.check_schema(schema)
        self._validators = {
            definition: Draft202012Validator(
                {
                    "$schema": schema["$schema"],
                    "$defs": schema["$defs"],
                    "allOf": [
                        {"$ref": "#/$defs/ViewEnvelope"},
                        {
                            "type": "object",
                            "properties": {
                                "payload": {"$ref": f"#/$defs/{definition}"},
                            },
                            "required": ["payload"],
                        },
                    ],
                }
            )
            for definition in _PAYLOAD_DEFINITIONS
        }

    def seasons(self) -> JsonDocument:
        return self._load(PurePosixPath("index.json"), "SiteIndex")

    def season_status(self, season: str) -> JsonDocument:
        return self._season_view(season, "status.json", "StatusView")

    def league(self, season: str) -> JsonDocument:
        return self._season_view(season, "league.json", "LeagueView")

    def ledger(self, season: str) -> JsonDocument:
        return self._season_view(season, "ledger.json", "LedgerView")

    def recommendation(self, season: str, gameweek: int) -> JsonDocument:
        return self._gameweek_view(
            season,
            gameweek,
            "recommendation.json",
            "RecommendationView",
        )

    def pool(self, season: str, gameweek: int) -> JsonDocument:
        return self._gameweek_view(season, gameweek, "pool.json", "PoolView")

    def _season_view(
        self,
        season: str,
        filename: str,
        definition: PayloadDefinition,
    ) -> JsonDocument:
        safe_season = _validate_season(season)
        return self._load(PurePosixPath(safe_season, filename), definition)

    def _gameweek_view(
        self,
        season: str,
        gameweek: int,
        filename: str,
        definition: PayloadDefinition,
    ) -> JsonDocument:
        safe_season = _validate_season(season)
        safe_gameweek = _validate_gameweek(gameweek)
        relative_path = PurePosixPath(safe_season, f"gw{safe_gameweek:02d}", filename)
        return self._load(relative_path, definition)

    def _load(
        self,
        relative_path: PurePosixPath,
        definition: PayloadDefinition,
    ) -> JsonDocument:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PublishedViewIntegrityError("published view path escaped its data root")
        try:
            validator = self._validators[definition]
        except KeyError as error:
            raise PublishedViewIntegrityError("unknown published view definition") from error

        candidate = self._root.joinpath(*relative_path.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise PublishedViewNotFoundError("published view does not exist") from error
        except (OSError, RuntimeError) as error:
            raise PublishedViewIntegrityError("published view path cannot be resolved") from error
        try:
            resolved.relative_to(self._root)
        except ValueError as error:
            raise PublishedViewIntegrityError("published view escaped its data root") from error

        try:
            encoded = resolved.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise PublishedViewNotFoundError("published view does not exist") from error
        except (OSError, UnicodeError) as error:
            raise PublishedViewIntegrityError("published view cannot be read") from error
        try:
            loaded: object = json.loads(encoded, parse_constant=_reject_non_finite_json)
        except (ValueError, UnicodeError) as error:
            raise PublishedViewIntegrityError("published view is not strict JSON") from error
        if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
            raise PublishedViewIntegrityError("published view must be a JSON object")
        document = cast(JsonDocument, loaded)
        try:
            validator.validate(document)
        except ValidationError as error:
            raise PublishedViewIntegrityError(
                "published view does not satisfy ui_view_v1"
            ) from error
        return document


__all__ = [
    "FilePublishedViewStore",
    "JsonDocument",
    "PublishedViewError",
    "PublishedViewIntegrityError",
    "PublishedViewNotFoundError",
    "PublishedViewStore",
]
