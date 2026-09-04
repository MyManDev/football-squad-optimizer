"""Transport-neutral contracts for querying published application views."""

from __future__ import annotations

from typing import Protocol, TypeAlias

JsonDocument: TypeAlias = dict[str, object]


class PublishedViewError(RuntimeError):
    """Base class for failures at the published-view boundary."""


class PublishedViewNotFoundError(PublishedViewError):
    """The requested published resource does not exist."""


class PublishedViewIntegrityError(PublishedViewError):
    """A published resource is unsafe, unreadable, or violates its contract."""


class PublishedViewStore(Protocol):
    """Query seam implemented by storage adapters and consumed by entry points."""

    def seasons(self) -> JsonDocument: ...

    def season_status(self, season: str) -> JsonDocument: ...

    def league(self, season: str) -> JsonDocument: ...

    def ledger(self, season: str) -> JsonDocument: ...

    def recommendation(self, season: str, gameweek: int) -> JsonDocument: ...

    def pool(self, season: str, gameweek: int) -> JsonDocument: ...


__all__ = [
    "JsonDocument",
    "PublishedViewError",
    "PublishedViewIntegrityError",
    "PublishedViewNotFoundError",
    "PublishedViewStore",
]
