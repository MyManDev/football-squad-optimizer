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
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from squadopt.application.advice_capabilities import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    MEMBER_WINDOWS,
    TOP100_WEIGHTS,
    AdviceCapability,
    validate_advice_selection,
)
from squadopt.application.entries import EntryError
from squadopt.application.league_views import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.platform.advice_cache import AdviceCacheRepository, advice_cache_key
from squadopt.platform.advice_documents import (
    LEAGUE_CAPABILITIES_CONTRACT_VERSION,
    LEAGUE_STATE_CONTRACT_VERSION,
    validate_advice_document,
    validate_league_capabilities,
    validate_league_state,
)
from squadopt.platform.advice_switches import (
    MANAGERS_WORD_SWITCH,
    MODEL_SWITCH,
    TOP100_SWITCH,
    AdviceSwitchInputs,
    SwitchIdentity,
    SwitchInputUnavailable,
    switch_identity,
)

LEAGUE_TREE_CONTRACT_VERSION: Final = LEAGUE_VIEW_CONTRACT_VERSION


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


class Top100InputsUnavailableError(AdviceReadError):
    """A Top 100 setting was asked for and this capture has no usable counts."""


class ModelInputsUnavailableError(AdviceReadError):
    """The requested model has no verified forecast for this capture."""


class ManagersWordUnavailableError(AdviceReadError):
    """The manager's word was asked for and this capture has no coded club news."""


class ChipUnavailableError(AdviceReadError):
    """A chip cannot be offered from this member's captured history."""

    def __init__(self, code: str) -> None:
        super().__init__("This chip is not available from the member's captured history.")
        self.code = code


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


class SwitchInputsProvider(Protocol):
    """What the current context offers the switches; ``None`` when it is not current."""

    def switch_inputs(self, context: AdviceRequestContext) -> AdviceSwitchInputs | None: ...


@dataclass(frozen=True, slots=True)
class PreferencePlayers:
    """The player codes one member's preferences may name in one capture.

    ``squad`` is the fifteen the member holds going into the deadline, the only players a
    request may keep; ``roster`` is every player the capture offers, the only ones it may
    avoid. Both are the ids the solver checks the same preferences against.
    """

    squad: frozenset[int]
    roster: frozenset[int]


@dataclass(frozen=True, slots=True)
class ResolvedAdviceRequest:
    """One validated request: its address, the context, and the switched-on identity."""

    key: str
    context: AdviceRequestContext
    switches: SwitchIdentity


def league_tree_matches(payload: Mapping[str, object], context: AdviceRequestContext) -> bool:
    """Whether the published member directory is for the week the capture targets.

    The tree and the capture are published separately, so one can be a week ahead of the
    other: last week's members beside this week's capture, or the reverse. Both are
    readable, which is why being readable proves nothing about this. Only what the api
    already holds is compared, the directory's own season and gameweek against the
    context's, so nothing is loaded to find out. A tree that names no gameweek is an
    older one and matches nothing.
    """

    gameweek = payload.get("gameweek")
    if isinstance(gameweek, bool) or not isinstance(gameweek, int):
        return False
    return payload.get("season") == context.season and gameweek == context.gameweek


def _tree_week(payload: Mapping[str, object]) -> str:
    gameweek = payload.get("gameweek")
    named = isinstance(gameweek, int) and not isinstance(gameweek, bool)
    week = f"gameweek {gameweek}" if named else "no gameweek"
    return f"{payload.get('season') or 'no season'} {week}"


class LeagueDirectory(Protocol):
    """What the read side may know about connected leagues."""

    def league(self, league_id: int) -> Mapping[str, object] | None: ...


class FileLeagueDirectory:
    """Reads the published league tree — the same bytes the static site serves."""

    def __init__(self, site_data_root: Path | str) -> None:
        self._root = Path(site_data_root)
        self.published_capture_unusable_reason: str | None = None

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

    def published_snapshot_id(self) -> tuple[str, str, int] | None:
        """The agreed capture, season and week, or a reason the tree cannot name them."""

        self.published_capture_unusable_reason = None
        try:
            payload = self._read()
            if payload is None:
                return None
            identifiers = set()
            for entry_id in _member_entry_ids(payload):
                path = self._root / "league" / "entries" / f"{entry_id}.json"
                document = json.loads(path.read_text(encoding="utf-8"))
                identifier = document["payload"]["source_snapshot_id"]
                if not isinstance(identifier, str) or not re.fullmatch(
                    r"fpl-live-[A-Za-z0-9_-]+", identifier
                ):
                    raise ValueError(f"Entry {entry_id} has no usable source_snapshot_id.")
                identifiers.add(identifier)
            if len(identifiers) != 1:
                raise ValueError("Published human entries are empty or disagree on the capture.")
            return identifiers.pop(), str(payload["season"]), int(str(payload["gameweek"]))
        except (
            AdviceBackendNotReadyError,
            OSError,
            UnicodeError,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            self.published_capture_unusable_reason = str(error)
            return None

    def matches(self, context: AdviceRequestContext | None) -> bool:
        """Whether the tree is there and is for ``context``'s week; never raises."""

        if context is None:
            return False
        try:
            payload = self._read()
        except (AdviceBackendNotReadyError, OSError, UnicodeError):
            return False
        return payload is not None and league_tree_matches(payload, context)


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

    ``capabilities`` is the fuller statement of the same thing (windows, and which
    windows each switch may be asked at); left out, it is derived from ``strategies`` as
    it always was, with no switch offered. ``switches`` is where the current context's
    switch inputs come from; without one every switched-on request is refused by name.
    ``preference_players`` reads the member's captured squad and the capture's roster;
    without one, and for a member whose squad it cannot read, a request that keeps or
    avoids a player is refused, because its ids cannot be checked.
    """

    def __init__(
        self,
        directory: LeagueDirectory,
        cache: AdviceCacheRepository,
        context_provider: AdviceContextProvider,
        strategies: Mapping[str, bool],
        *,
        capabilities: Mapping[str, AdviceCapability] | None = None,
        switches: SwitchInputsProvider | None = None,
        chip_availability: Callable[
            [AdviceRequestContext, int, tuple[int, ...]], Mapping[int, tuple[str, ...] | None]
        ]
        | None = None,
        preference_players: Callable[[AdviceRequestContext, int, int], PreferencePlayers | None]
        | None = None,
    ) -> None:
        self._directory = directory
        self._cache = cache
        self._context = context_provider
        self._strategies = dict(strategies)
        self._capabilities = (
            {
                slug: AdviceCapability(
                    MEMBER_WINDOWS if slug == COMPUTED_MODE else (COMPUTED_WINDOW,), rival
                )
                for slug, rival in strategies.items()
            }
            if capabilities is None
            else {slug: capabilities[slug] for slug in strategies}
        )
        self._switches = switches
        self._chip_availability = chip_availability
        self._preference_players = preference_players

    def _check_preference_players(
        self,
        context: AdviceRequestContext,
        league_id: int,
        entry_id: int,
        preferences: DecisionPreferences,
    ) -> None:
        """Refuse a kept or avoided player the capture does not have for this member.

        The contract accepts any positive id, and every distinct set is a distinct
        address, so ids nobody holds used to reach the queue as new work and fail only in
        the worker. The same two sets the solver checks are checked here, before a token
        is spent or a job exists.
        """

        if not (preferences.keep_players or preferences.avoid_players):
            return
        players = (
            None
            if self._preference_players is None
            else self._preference_players(context, league_id, entry_id)
        )
        if players is None:
            raise UnsupportedAdviceRequestError(
                "This member's captured squad cannot be read, so kept or avoided players "
                "cannot be checked."
            )
        if not set(preferences.keep_players) <= players.squad:
            raise UnsupportedAdviceRequestError(
                "Only a player the member holds in this capture can be kept."
            )
        if not set(preferences.avoid_players) <= players.roster:
            raise UnsupportedAdviceRequestError(
                "An avoided player is not in this capture's roster."
            )

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

    def _switch_inputs(self, context: AdviceRequestContext) -> AdviceSwitchInputs:
        if self._switches is None:
            return AdviceSwitchInputs()
        return self._switches.switch_inputs(context) or AdviceSwitchInputs()

    def _held_chips(
        self, context: AdviceRequestContext, league_id: int, entries: tuple[int, ...]
    ) -> Mapping[int, tuple[str, ...] | None]:
        if self._chip_availability is None or not any(
            c.chip_windows for c in self._capabilities.values()
        ):
            return {}
        return self._chip_availability(context, league_id, entries)

    def league_capabilities(self, league_id: int) -> dict[str, object]:
        """What may be asked for this league right now, so a page enables only that.

        The strategies and their windows are this deployment's; the two switches are
        offered only while the current capture has the input each one is computed from.
        """

        league = self._directory.league(league_id)
        if league is None:
            raise LeagueNotConnectedError(f"League {league_id} is not connected here.")
        context = self._context.current()
        if context is None:
            raise AdviceBackendNotReadyError("No capture context is loaded yet.")
        inputs = self._switch_inputs(context)
        chips = self._held_chips(context, league_id, tuple(sorted(_member_entry_ids(league))))
        top100 = inputs.top100_counts is not None and any(
            capability.top100_windows for capability in self._capabilities.values()
        )
        word = (
            inputs.manager_words is not None
            and inputs.rotation_table_sha256 is not None
            and any(capability.managers_word_windows for capability in self._capabilities.values())
        )
        document: dict[str, object] = {
            "contract_version": LEAGUE_CAPABILITIES_CONTRACT_VERSION,
            "league_id": int(league_id),
            "capture_snapshot_id": context.capture_snapshot_id,
            "season": context.season,
            "gameweek": context.gameweek,
            "strategies": {
                slug: {
                    "windows": list(capability.windows),
                    "requires_rival": capability.requires_rival,
                }
                for slug, capability in sorted(self._capabilities.items())
            },
            # The settings that would be accepted now: zero is always one of them.
            "top100": {"available": top100, "weights": list(TOP100_WEIGHTS) if top100 else [0]},
            "managers_word": {"available": word},
            "preferences": {"available": True},
            "chips": {
                "strategy": {
                    "version": "model_opportunity_reservation_v1",
                    "windows": [1, 3, 5],
                },
                "held_by_entry": {
                    str(entry): list(held) for entry, held in chips.items() if held is not None
                },
            },
        }
        if inputs.football is not None:
            document["models"] = ["current", "football"]
        validate_league_capabilities(document)
        return document

    def resolve(
        self,
        *,
        league_id: int,
        entry_id: int,
        strategy: str,
        window: int,
        rival_entry_id: int | None = None,
        top100_weight: int = 0,
        managers_word: bool = False,
        chip: str | None = None,
        model: str = "current",
        preferences: DecisionPreferences = NO_PREFERENCES,
    ) -> ResolvedAdviceRequest:
        """Validate one request against what this deployment knows and address it.

        The same validation and the same key serve the GET and the POST: a request the
        reader would refuse is a request the writer must refuse, or the two sides of
        the cache disagree about what exists.
        """

        try:
            preferences.validate_selection(strategy, managers_word, chip)
        except ValueError as error:
            raise UnsupportedAdviceRequestError(str(error)) from error
        if model not in ("current", "football"):
            raise UnsupportedAdviceRequestError("Unknown prediction model.")
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
                top100_weight=top100_weight,
                managers_word=managers_word,
                chip=chip,
            )
        except EntryError as error:
            raise UnsupportedAdviceRequestError(str(error)) from error
        context = self._context.current()
        if context is None:
            raise AdviceBackendNotReadyError("No capture context is loaded yet.")
        if not league_tree_matches(payload, context):
            # Readiness, like the missing context: the members just checked are another
            # week's, and an answer computed for this capture would be filed beside a
            # league page that is not about it. Both weeks are named so the operator
            # knows which of the two publications is behind.
            raise AdviceBackendNotReadyError(
                f"The published league tree is for {_tree_week(payload)}, and the current "
                f"capture is for {context.season} gameweek {context.gameweek}; advice "
                "waits until the two are for the same week."
            )
        switches: SwitchIdentity = {}
        if chip is not None:
            held = self._held_chips(context, league_id, (entry_id,)).get(entry_id)
            if held is None or (chip != "auto" and chip not in held):
                raise ChipUnavailableError(
                    "CHIP_HISTORY_UNKNOWN" if held is None else "CHIP_NOT_HELD"
                )
        self._check_preference_players(context, league_id, entry_id, preferences)
        if (
            top100_weight
            or managers_word
            or chip is not None
            or model != "current"
            or preferences.active
        ):
            # Refused here, before a job exists: a switch whose input this capture does
            # not have can never be computed, and a queued job would only say so later.
            try:
                switches = switch_identity(
                    self._switch_inputs(context)
                    if top100_weight or managers_word or model != "current"
                    else AdviceSwitchInputs(),
                    top100_weight=top100_weight,
                    managers_word=managers_word,
                    chip=chip,
                    model=model,
                    preferences=preferences,
                )
            except SwitchInputUnavailable as error:
                if error.switch == MODEL_SWITCH:
                    raise ModelInputsUnavailableError(str(error)) from error
                if error.switch == TOP100_SWITCH:
                    raise Top100InputsUnavailableError(str(error)) from error
                assert error.switch == MANAGERS_WORD_SWITCH
                raise ManagersWordUnavailableError(str(error)) from error
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
            switches=switches,
        )
        return ResolvedAdviceRequest(key=key, context=context, switches=switches)

    def resolve_key(
        self,
        *,
        league_id: int,
        entry_id: int,
        strategy: str,
        window: int,
        rival_entry_id: int | None = None,
        top100_weight: int = 0,
        managers_word: bool = False,
        chip: str | None = None,
        model: str = "current",
        preferences: DecisionPreferences = NO_PREFERENCES,
    ) -> tuple[str, AdviceRequestContext]:
        """``resolve`` for a caller that needs only the address and its context."""

        resolved = self.resolve(
            league_id=league_id,
            entry_id=entry_id,
            strategy=strategy,
            window=window,
            rival_entry_id=rival_entry_id,
            top100_weight=top100_weight,
            managers_word=managers_word,
            chip=chip,
            model=model,
            preferences=preferences,
        )
        return resolved.key, resolved.context

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
        top100_weight: int = 0,
        managers_word: bool = False,
        chip: str | None = None,
        model: str = "current",
        preferences: DecisionPreferences = NO_PREFERENCES,
    ) -> bytes:
        """The cached answer under the complete key, or a typed refusal."""

        key, _context = self.resolve_key(
            league_id=league_id,
            entry_id=entry_id,
            strategy=strategy,
            window=window,
            rival_entry_id=rival_entry_id,
            top100_weight=top100_weight,
            managers_word=managers_word,
            chip=chip,
            model=model,
            preferences=preferences,
        )
        cached = self.cached(key)
        if cached is None:
            raise AdviceNotComputedError(
                f"No advice computed for entry {entry_id} under {strategy}/{window}."
            )
        # The route serves these bytes verbatim under a versioned claim, so bytes that
        # do not carry the version are an internal error, never a published document.
        return cached
