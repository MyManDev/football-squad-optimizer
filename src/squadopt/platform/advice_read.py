"""The read side of on-demand advice: league state and pure cache lookups.

Everything here is a read. The api process serves these without importing a solver:
league connection state comes from the published league tree (the same
``members.json`` the static site serves), and an advice lookup is a cache ``get``
under the complete key — a miss is an honest 404, never a computation. The compute
path lives with the queue and the worker; this module cannot start one.

The context provider is the seam that keeps the api stateless: which capture, which
handoff, which commit and configuration answer requests *now* is operational state
owned by the deployment, injected here, and recorded in every key. Without a context
the advice read is honestly "not ready" — a backend that has never seen a capture has
no answers, and pretending otherwise would 404 in a way that reads as "not computed",
which is a different fact.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from squadopt.application.advice_capabilities import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    MEMBER_WINDOWS,
    AdviceCapability,
    validate_advice_selection,
)
from squadopt.application.entries import EntryError
from squadopt.platform.advice_cache import AdviceCacheRepository, advice_cache_key
from squadopt.platform.advice_documents import (
    LEAGUE_STATE_CONTRACT_VERSION,
    validate_advice_document,
    validate_league_state,
)

LEAGUE_TREE_CONTRACT_VERSION: Final = "provisional_league_ui_v1"


class AdviceReadError(ValueError):
    """Base for read-side refusals; the api maps subclasses onto status codes."""


class LeagueNotConnectedError(AdviceReadError):
    """The league is not operator-connected here; an honest state, not a fault."""


class UnknownEntryError(AdviceReadError):
    """The entry (or requested rival) is not in the connected league's members."""


class UnknownStrategyError(AdviceReadError):
    """The strategy slug is not one this deployment computes."""


class AdviceNotComputedError(AdviceReadError):
    """Nothing cached under the complete key: 404, never a computation."""


class AdviceBackendNotReadyError(AdviceReadError):
    """No capture context yet; readiness, not absence of an answer."""


class UnsupportedAdviceRequestError(AdviceReadError):
    """A validly encoded request is not a computable strategy/window/rival combination."""


@dataclass(frozen=True, slots=True)
class AdviceRequestContext:
    """What the deployment knows at read time; every field enters the cache key."""

    advice_contract_version: str
    capture_snapshot_id: str
    season: str
    gameweek: int
    projection_handoff_fingerprint: str
    repository_commit: str
    configuration_fingerprint: str


class AdviceContextProvider(Protocol):
    """Where the current capture context comes from; ``None`` means not ready."""

    def current(self) -> AdviceRequestContext | None: ...


class LeagueDirectory(Protocol):
    """What the read side may know about connected leagues."""

    def league(self, league_id: int) -> Mapping[str, object] | None: ...


class FileLeagueDirectory:
    """Reads the published league tree — the same bytes the static site serves."""

    def __init__(self, site_data_root: Path | str) -> None:
        self._root = Path(site_data_root)

    def _read(self) -> Mapping[str, object] | None:
        path = self._root / "league" / "members.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as error:
            raise AdviceBackendNotReadyError(
                "The published member directory is unreadable."
            ) from error
        try:
            document = json.loads(raw)
            payload = document.get("payload") if isinstance(document, dict) else None
            if not isinstance(payload, dict):
                raise ValueError("Missing member payload.")
            if document.get("contract_version") != LEAGUE_TREE_CONTRACT_VERSION:
                raise ValueError("Unsupported member contract.")
            for name in ("league_id", "gameweek"):
                value = payload.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError("Invalid member publication identity.")
            for name in ("league_name", "season"):
                if not isinstance(payload.get(name), str) or not payload[name].strip():
                    raise ValueError("Missing member publication identity.")
            members = payload.get("members")
            if not isinstance(members, list):
                raise ValueError("Missing member rows.")
            seen = set()
            for member in members:
                if not isinstance(member, dict):
                    raise ValueError("Invalid member row.")
                kind, identifier = member.get("member_kind"), member.get("entry_id")
                if kind == "system" and (
                    identifier is None or (type(identifier) is int and identifier == 0)
                ):
                    continue
                if (
                    kind != "human"
                    or isinstance(identifier, bool)
                    or not isinstance(identifier, int)
                ):
                    raise ValueError("Invalid member identity.")
                if identifier < 1 or identifier in seen:
                    raise ValueError("Invalid or duplicate member identity.")
                seen.add(identifier)
        except (ValueError, TypeError) as error:
            raise AdviceBackendNotReadyError(
                "The published member directory is unreadable."
            ) from error
        return payload

    def league(self, league_id: int) -> Mapping[str, object] | None:
        payload = self._read()
        return payload if payload is not None and payload["league_id"] == league_id else None

    def readable(self) -> bool:
        try:
            return self._read() is not None
        except (AdviceBackendNotReadyError, OSError, UnicodeError):
            return False


def _member_entry_ids(payload: Mapping[str, object]) -> frozenset[int]:
    members = payload.get("members")
    if not isinstance(members, list):
        return frozenset()
    ids = set()
    for row in members:
        if isinstance(row, dict) and row.get("member_kind") == "human":
            ids.add(int(str(row.get("entry_id", 0))))
    return frozenset(ids)


class AdviceReadStore:
    """League state and cached advice, composed from injected collaborators.

    ``strategies`` maps each computable slug onto whether it uses a rival — the
    forced-null rule's input. It is injected rather than imported so this module
    states no opinion about the catalogue; the composition root wires the real one.
    """

    def __init__(
        self,
        directory: LeagueDirectory,
        cache: AdviceCacheRepository,
        context_provider: AdviceContextProvider,
        strategies: Mapping[str, bool],
    ) -> None:
        self._directory = directory
        self._cache = cache
        self._context = context_provider
        self._strategies = dict(strategies)
        self._capabilities = {
            slug: AdviceCapability(
                MEMBER_WINDOWS if slug == COMPUTED_MODE else (COMPUTED_WINDOW,), rival
            )
            for slug, rival in strategies.items()
        }

    def league_state(self, league_id: int) -> dict[str, object]:
        """Connected or not, from the published tree — never an upstream call."""

        payload = self._directory.league(league_id)
        if payload is None:
            document: dict[str, object] = {
                "contract_version": LEAGUE_STATE_CONTRACT_VERSION,
                "league_id": int(league_id),
                "connected": False,
            }
        else:
            document = {
                "contract_version": LEAGUE_STATE_CONTRACT_VERSION,
                "league_id": int(league_id),
                "connected": True,
                "league_name": payload.get("league_name"),
                "season": payload.get("season"),
                "gameweek": payload.get("gameweek"),
                "member_count": len(_member_entry_ids(payload)),
            }
        validate_league_state(document)  # the route serves only what the contract names
        return document

    def resolve_key(
        self,
        *,
        league_id: int,
        entry_id: int,
        strategy: str,
        window: int,
        rival_entry_id: int | None = None,
    ) -> tuple[str, AdviceRequestContext]:
        """Validate one request against what this deployment knows and address it.

        The same validation and the same key serve the GET and the POST: a request the
        reader would refuse is a request the writer must refuse, or the two sides of
        the cache disagree about what exists.
        """

        if strategy not in self._strategies:
            raise UnknownStrategyError(f"Strategy {strategy!r} is not computed here.")
        payload = self._directory.league(league_id)
        if payload is None:
            raise LeagueNotConnectedError(f"League {league_id} is not connected here.")
        members = _member_entry_ids(payload)
        if int(entry_id) not in members:
            raise UnknownEntryError(f"Entry {entry_id} is not in league {league_id}.")
        if rival_entry_id is not None and int(rival_entry_id) not in members:
            raise UnknownEntryError(f"Rival {rival_entry_id} is not in league {league_id}.")
        try:
            validate_advice_selection(
                strategy=strategy,
                window=window,
                entry_id=entry_id,
                rival_entry_id=rival_entry_id,
                capabilities=self._capabilities,
            )
        except EntryError as error:
            raise UnsupportedAdviceRequestError(str(error)) from error
        context = self._context.current()
        if context is None:
            raise AdviceBackendNotReadyError("No capture context is loaded yet.")
        key = advice_cache_key(
            advice_contract_version=context.advice_contract_version,
            capture_snapshot_id=context.capture_snapshot_id,
            season=context.season,
            gameweek=context.gameweek,
            league_id=int(league_id),
            entry_id=int(entry_id),
            strategy=strategy,
            window=int(window),
            projection_handoff_fingerprint=context.projection_handoff_fingerprint,
            repository_commit=context.repository_commit,
            configuration_fingerprint=context.configuration_fingerprint,
            rival_entry_id=rival_entry_id,
            strategy_uses_rival=self._strategies[strategy],
        )
        return key, context

    def strategy_uses_rival(self, strategy: str) -> bool:
        """Whether a rival is part of this strategy's identity, or dropped before hashing.

        The same fact ``advice_cache_key`` applies, exposed so a caller that has to record
        a request *beside* the key normalizes it the same way. Two requests that reach one
        key must describe one question.
        """

        if strategy not in self._strategies:
            raise UnknownStrategyError(f"Strategy {strategy!r} is not computed here.")
        return self._strategies[strategy]

    def cached(self, key: str) -> bytes | None:
        """GET and POST share the same validation of exact cached bytes."""

        cached = self._cache.get(key)
        if cached is not None:
            validate_advice_document(cached)
        return cached

    def read_advice(
        self,
        *,
        league_id: int,
        entry_id: int,
        strategy: str,
        window: int,
        rival_entry_id: int | None = None,
    ) -> bytes:
        """The cached answer under the complete key, or a typed refusal."""

        key, _context = self.resolve_key(
            league_id=league_id,
            entry_id=entry_id,
            strategy=strategy,
            window=window,
            rival_entry_id=rival_entry_id,
        )
        cached = self.cached(key)
        if cached is None:
            raise AdviceNotComputedError(
                f"No advice computed for entry {entry_id} under {strategy}/{window}."
            )
        # The route serves these bytes verbatim under a versioned claim, so bytes that
        # do not carry the version are an internal error, never a published document.
        return cached
