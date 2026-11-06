"""Read and address on-demand public-entry plans using the existing advice queue."""

from __future__ import annotations

from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.platform.advice_cache import AdviceCacheRepository, advice_cache_key
from squadopt.platform.advice_read import (
    AdviceBackendNotReadyError,
    AdviceContextProvider,
    AdviceInputsNotPreparedError,
    AdviceReadStore,
    LeagueDirectory,
    ResolvedAdviceRequest,
    UnsupportedAdviceRequestError,
)
from squadopt.platform.advice_switches import SwitchIdentity
from squadopt.platform.public_entry_inputs import PUBLIC_ENTRY_SWITCH, PublicEntryInputs


class PublicEntryAdviceReader(AdviceReadStore):
    """GET reads only pinned inputs and cached answers. POST prepares one team's inputs."""

    def __init__(
        self,
        directory: LeagueDirectory,
        cache: AdviceCacheRepository,
        context: AdviceContextProvider,
        inputs: PublicEntryInputs,
    ) -> None:
        super().__init__(directory, cache, context, {"saf-puan": False})
        self._public_inputs = inputs

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
        if (
            type(league_id) is not int
            or not 0 <= league_id <= 9_007_199_254_740_991
            or type(entry_id) is not int
            or not 1 <= entry_id <= 9_007_199_254_740_991
            or strategy != "saf-puan"
            or type(window) is not int
            or window != 1
            or rival_entry_id is not None
            or top100_weight != 0
            or managers_word
            or chip is not None
            or model != "current"
            or preferences.active
        ):
            raise UnsupportedAdviceRequestError("Public teams support the plain one-week plan.")
        context = self._context.current()
        if context is None:
            raise AdviceBackendNotReadyError("No capture context is loaded yet.")
        fingerprint = self._public_inputs.fingerprint(context, entry_id)
        if fingerprint is None:
            raise AdviceInputsNotPreparedError(context)
        switches: SwitchIdentity = {PUBLIC_ENTRY_SWITCH: {"fingerprint": fingerprint}}
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
            switches=switches,
        )
        return ResolvedAdviceRequest(key=key, context=context, switches=switches)
