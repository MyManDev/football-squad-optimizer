"""Read and address on-demand public-entry plans using the existing advice queue.

A public team is one the weekly capture does not hold: a member of a league the site does
not publish, or a team opened on its own (league 0). Its inputs are pinned once per capture
from the FPL forwarder (``PublicEntryInputs``), and the menu it is offered is the pure-points
plan at every window the deployment computes, with every switch the capture has the input
for: the Top 100 setting, the manager's word, the football model, a held chip and the
member's preferences. The chip a public team holds and the squad its preferences are checked
against are read from its pinned inputs, never from the capture. A rival strategy pins the
rival's inputs beside the member's, and the answer is filed under both pins.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from squadopt.application.advice import AdviseEntryRequest
from squadopt.application.advice_capabilities import menu_capabilities
from squadopt.application.advice_menu import held_member_chips, held_member_squad
from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.live import RecommendationInputs, read_season_rules
from squadopt.platform.advice_cache import AdviceCacheRepository, advice_cache_key
from squadopt.platform.advice_read import (
    AdviceBackendNotReadyError,
    AdviceInputsNotPreparedError,
    AdviceReadStore,
    AdviceRequestContext,
    LeagueDirectory,
    PreferencePlayers,
    ResolvedAdviceRequest,
    SwitchInputsProvider,
    UnsupportedAdviceRequestError,
)
from squadopt.platform.advice_switches import SwitchIdentity
from squadopt.platform.capture_context import CaptureIdentity
from squadopt.platform.public_entry_inputs import PUBLIC_ENTRY_SWITCH, PublicEntryInputs

MAX_ID = 9_007_199_254_740_991


class PublicCaptureContexts(Protocol):
    """The capture context provider, with the identity the pinned inputs are read beside."""

    def current(self) -> AdviceRequestContext | None: ...

    def identity(self) -> CaptureIdentity | None: ...


class PublicEntryAdviceReader(AdviceReadStore):
    """GET reads only pinned inputs and cached answers. POST prepares one team's inputs."""

    def __init__(
        self,
        directory: LeagueDirectory,
        cache: AdviceCacheRepository,
        context: PublicCaptureContexts,
        inputs: PublicEntryInputs,
        *,
        switches: SwitchInputsProvider | None = None,
    ) -> None:
        menu = menu_capabilities()
        super().__init__(
            directory,
            cache,
            context,
            {slug: capability.requires_rival for slug, capability in menu.items()},
            capabilities=menu,
            switches=switches,
        )
        self._contexts = context
        self._public_inputs = inputs

    def _pinned(
        self, context: AdviceRequestContext, entry_id: int
    ) -> tuple[CapturePicksProvider, RecommendationInputs, CapturedSnapshot]:
        """The pinned team's picks provider beside the loaded capture's inputs and snapshot.

        Not pinned yet is the submitter's cue to fetch the team's inputs first.
        """

        fingerprint = self._public_inputs.fingerprint(context, entry_id)
        if fingerprint is None:
            raise AdviceInputsNotPreparedError(context)
        identity = self._contexts.identity()
        if identity is None or identity.context != context:
            raise AdviceBackendNotReadyError("The capture context is no longer current.")
        provider = self._public_inputs.provider(
            context, entry_id, fingerprint, identity.snapshot.payloads
        )
        return provider, identity.inputs, identity.snapshot

    def _held_chips(
        self, context: AdviceRequestContext, league_id: int, entries: tuple[int, ...]
    ) -> Mapping[int, tuple[str, ...] | None]:
        """The chips each pinned team may still play, from its own history; None if unread."""

        held: dict[int, tuple[str, ...] | None] = {}
        for entry_id in entries:
            # A team whose inputs are not pinned yet has no chips to name: its capabilities
            # leave it out, and a plan request pins it first.
            if self._public_inputs.fingerprint(context, entry_id) is None:
                continue
            provider, inputs, snapshot = self._pinned(context, entry_id)
            try:
                held[entry_id] = held_member_chips(
                    AdviseEntryRequest(context.season, context.gameweek, league_id, entry_id),
                    provider=provider,
                    inputs=inputs,
                    rules=read_season_rules(snapshot, season=inputs.season),
                )
            except Exception:
                held[entry_id] = None
        return held

    def _preference_players_of(
        self, context: AdviceRequestContext, league_id: int, entry_id: int
    ) -> PreferencePlayers | None:
        """The pinned team's fifteen and the capture's roster; None where the squad is unread."""

        provider, inputs, _snapshot = self._pinned(context, entry_id)
        try:
            squad = held_member_squad(
                AdviseEntryRequest(context.season, context.gameweek, league_id, entry_id),
                provider=provider,
                inputs=inputs,
            )
        except Exception:
            return None
        roster = frozenset(int(code) for code in inputs.players["player_id"])
        return PreferencePlayers(squad=frozenset(squad), roster=roster)

    @staticmethod
    def _check_ids(league_id: int, entry_id: int) -> None:
        if (
            type(league_id) is not int
            or not 0 <= league_id <= MAX_ID
            or type(entry_id) is not int
            or not 1 <= entry_id <= MAX_ID
        ):
            raise UnsupportedAdviceRequestError("A public team needs a league and team number.")

    def public_capabilities(self, league_id: int, entry_id: int) -> dict[str, object]:
        """What may be asked for one public team right now: the pure-points menu.

        League 0 is a team opened on its own. The team's held chips are named once its
        inputs are pinned, which the first plan request does; before that the document
        names no chips for it, and the page offers what the team's own documents show.
        """

        self._check_ids(league_id, entry_id)
        context = self._context.current()
        if context is None:
            raise AdviceBackendNotReadyError("No capture context is loaded yet.")
        return self._capabilities_document(league_id, context, (entry_id,))

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
        self._check_ids(league_id, entry_id)
        if type(window) is not int:
            raise UnsupportedAdviceRequestError("A public team needs a league and team number.")
        if rival_entry_id is not None and (
            type(rival_entry_id) is not int or not 1 <= rival_entry_id <= MAX_ID
        ):
            raise UnsupportedAdviceRequestError("A rival is a team number.")
        self._check_selection(
            strategy=strategy,
            window=window,
            entry_id=entry_id,
            rival_entry_id=rival_entry_id,
            top100_weight=top100_weight,
            managers_word=managers_word,
            chip=chip,
            model=model,
            preferences=preferences,
        )
        context = self._context.current()
        if context is None:
            raise AdviceBackendNotReadyError("No capture context is loaded yet.")
        # A switch whose input this capture lacks is refused before the team's inputs are
        # fetched: the answer could never be computed, whatever the team holds.
        if top100_weight or managers_word or model != "current":
            self._switch_inputs_identity(
                context,
                top100_weight=top100_weight,
                managers_word=managers_word,
                chip=None,
                model=model,
                preferences=NO_PREFERENCES,
            )
        # The member's pin, and the rival's where the strategy names one. Whichever is missing
        # is named, so the submitter fetches exactly those before asking again.
        teams = (entry_id,) if rival_entry_id is None else (entry_id, rival_entry_id)
        pins: dict[int, str] = {}
        missing: list[int] = []
        for team in teams:
            pinned = self._public_inputs.fingerprint(context, team)
            if pinned is None:
                missing.append(team)
            else:
                pins[team] = pinned
        if missing:
            raise AdviceInputsNotPreparedError(context, tuple(missing))
        public: dict[str, str | int | bool | None] = {"fingerprint": pins[entry_id]}
        if rival_entry_id is not None:
            public["rival_fingerprint"] = pins[rival_entry_id]
        switches: SwitchIdentity = {
            PUBLIC_ENTRY_SWITCH: public,
            **self._switches_for(
                context,
                league_id,
                entry_id,
                top100_weight=top100_weight,
                managers_word=managers_word,
                chip=chip,
                model=model,
                preferences=preferences,
            ),
        }
        key = advice_cache_key(
            advice_contract_version=context.advice_contract_version,
            capture_snapshot_id=context.capture_snapshot_id,
            season=context.season,
            gameweek=context.gameweek,
            league_id=league_id,
            entry_id=entry_id,
            strategy=strategy,
            window=window,
            projection_handoff_fingerprint=context.projection_handoff_fingerprint,
            repository_commit=context.repository_commit,
            configuration_fingerprint=context.configuration_fingerprint,
            rival_entry_id=rival_entry_id,
            strategy_uses_rival=self._strategies[strategy],
            switches=switches,
        )
        return ResolvedAdviceRequest(key=key, context=context, switches=switches)
