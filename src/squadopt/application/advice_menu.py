"""One entry point for the whole member menu, for a caller that answers one request.

The batch (``league_views.render_member``) walks a member's menu in one pass and hands
each producer what the pass already solved. A request path has one address to answer and
nothing in hand, so this module is the same dispatch turned inside out: it validates the
combination, computes whatever the chosen producer needs first (the member's control, the
pricing plan, the pure-points window at setting 0, the strategy's own document at 0) and
calls the producer the batch calls, with the same arguments. Nothing about advice is
decided here; for the same inputs the payload is the batch's payload.

Experimental football windows use one budget for the requested Top 100 setting. They
state base-model points and the setting's source, without an unmeasured comparison to
a second plan at setting 0.

A plain request, no setting and no word, on a combination ``advise_entry`` answers is
``advise_entry``'s own payload, byte for byte.

**Counting what is solved.** ``menu_documents`` names, without solving anything, the
documents a request needs: what it is priced or compared against at setting 0, then the
asked one. ``documents_to_solve`` leaves out the ones a lookup already holds, and
``advise_menu_entry`` tells ``on_document`` about exactly those, once each, as it solves
them. A caller can therefore say "one of three" before the first solve and count up from
there, with nothing estimated from time.

**Adding a switch.** A switch is a field on ``MenuRequest`` with an off default, a tuple
of windows on ``AdviceCapability``, a per-capture input handed in as a keyword that may be
``None``, and one more branch in ``advise_menu_entry``. A chosen chip reads the member's
captured history and needs no separate artifact.
"""

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from squadopt.application.advice import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    TOP100_LIMIT,
    AdviseEntryRequest,
    HorizonBuilder,
    _requested_picks,
    advise_entry,
    advise_with_managers_word,
    advise_with_top100,
    solve_member_control,
    solve_pricing_control,
)
from squadopt.application.advice_capabilities import (
    advice_capabilities,
    menu_capabilities,
    validate_advice_selection,
)
from squadopt.application.advice_chip_strategy import advise_chip_strategy
from squadopt.application.advice_chips import advise_with_chip, member_chip_menu
from squadopt.application.advice_variants import (
    TOP100_WINDOW_LIMIT,
    advise_rival_window,
    advise_rival_with_top100,
    advise_window_with_top100,
)
from squadopt.application.chip_forecast_publication import (
    ForecastSource,
    member_chip_forecast,
    published_chip_gains,
)
from squadopt.application.entries import EntryError, EntryPicksProvider, held_squad_from_picks
from squadopt.application.manager_words import ManagerWords
from squadopt.application.top100_weight import Top100Counts
from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.live import Projection, RecommendationInputs, SeasonRules
from squadopt.optimization import SolverExecutionError
from squadopt.planning import TransferPlanningError

__all__ = [
    "MANAGER_WORDS_INPUT",
    "TOP100_COUNTS_INPUT",
    "DocumentSolved",
    "ManagersWordNotSolved",
    "MenuInputUnavailable",
    "MenuRequest",
    "PrerequisiteLookup",
    "advise_menu_entry",
    "documents_to_solve",
    "menu_documents",
]

TOP100_COUNTS_INPUT = "top100_counts"
MANAGER_WORDS_INPUT = "manager_words"


#: What the planner raises when it finds no plan for a selection. Their text is a solver's
#: diagnostic (deterministic time, gaps, player ids), so a caller that serves its failures
#: to the public names the outcome and keeps the text on its own side.
PLAN_NOT_FOUND_ERRORS: tuple[type[Exception], ...] = (SolverExecutionError, TransferPlanningError)


class MenuInputUnavailable(EntryError):
    """A switch was asked for and the capture has no input for it; ``input_name`` says which."""

    def __init__(self, input_name: str, detail: str) -> None:
        super().__init__(detail)
        self.input_name = input_name


class ManagersWordNotSolved(EntryError):
    """The word was asked for with a Top 100 setting and this member's plan has none.

    Not a missing input, which is refused before anything is solved: the capture has the
    coded club news, and the plan under the word could not be produced for this one
    member. It has its own type so a caller that records why a request failed can say
    this, rather than file a known outcome with the unexpected ones.
    """


class ChipUnavailable(EntryError):
    """The captured history cannot support the member's declared chip."""

    def __init__(self, code: str) -> None:
        super().__init__("This chip is not available from the member's captured history.")
        self.code = code


@dataclass(frozen=True, slots=True)
class MenuRequest:
    """One address on the member menu: an ``AdviseEntryRequest`` plus the switches."""

    season: str
    gameweek: int
    league_id: int
    entry_id: int
    strategy: str = COMPUTED_MODE
    window: int = COMPUTED_WINDOW
    rival_entry_id: int | None = None
    top100_weight: int = 0
    managers_word: bool = False
    chip: str | None = None
    preferences: DecisionPreferences = NO_PREFERENCES

    def __post_init__(self) -> None:
        self.entry_request()  # the shared fields are refused by the type that owns them
        try:
            self.preferences.validate_selection(self.strategy, self.managers_word, self.chip)
        except ValueError as error:
            raise EntryError(str(error)) from error
        if isinstance(self.top100_weight, bool) or not isinstance(self.top100_weight, int):
            raise EntryError("top100_weight must be an integer.")
        if not isinstance(self.managers_word, bool):
            raise EntryError("managers_word must be true or false.")

    def entry_request(self) -> AdviseEntryRequest:
        """The same address with every switch off."""

        return AdviseEntryRequest(
            season=self.season,
            gameweek=self.gameweek,
            league_id=self.league_id,
            entry_id=self.entry_id,
            strategy=self.strategy,
            window=self.window,
            rival_entry_id=self.rival_entry_id,
        )

    @property
    def is_plain(self) -> bool:
        return (
            self.top100_weight == 0
            and not self.managers_word
            and self.chip is None
            and not self.preferences.active
        )


def held_member_chips(
    request: AdviseEntryRequest,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    rules: SeasonRules,
) -> tuple[str, ...] | None:
    """Read captured chip availability without solving; None means unknown history."""
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    menu = member_chip_menu(rules, request.gameweek, picks.chips_used)
    return menu.held if menu.known else None


def held_member_squad(
    request: AdviseEntryRequest,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
) -> tuple[int, ...]:
    """The fifteen codes the member holds going into the deadline, read without solving.

    The same picks, read the same way, that become the planner's held squad, so a kept
    player accepted against this is one the solver accepts too.
    """
    return _requested_picks(request, request.entry_id, provider=provider, inputs=inputs).squad


#: Where a document this computation depends on may already exist: handed the address,
#: it returns that document's payload as computed from these same inputs, or ``None``.
PrerequisiteLookup = Callable[[MenuRequest], Mapping[str, object] | None]

#: Told the address of a document ``advise_menu_entry`` has just solved.
DocumentSolved = Callable[[MenuRequest], None]


def _one_budget_window(request: MenuRequest, projection: Projection) -> bool:
    """An experimental football window under a setting: one budget, nothing at setting 0."""

    return (
        projection.diagnostics.get("model_name") == "fixture_football_candidate"
        and request.strategy == COMPUTED_MODE
        and request.window in (3, 5)
        and request.top100_weight > 0
    )


def menu_documents(request: MenuRequest, *, projection: Projection) -> tuple[MenuRequest, ...]:
    """The documents ``advise_menu_entry`` produces for ``request``, in the order it solves them.

    The ones it is priced or compared against come first, each at setting 0, and the asked
    one last. That is the asked one alone, except for a window under a setting (the same
    window at 0 first), a rival window (the pure-points window at 0 first, then, under a
    setting, the rival window at 0) and a rival week under a setting (the rival week at 0
    first). So there are at most three. Nothing is solved or read: the request and which
    model ``projection`` is decide it, in the same order ``advise_menu_entry`` dispatches.
    """

    if (
        _one_budget_window(request, projection)
        or request.preferences.active
        or request.chip is not None
    ):
        return (request,)
    supported = advice_capabilities().get(request.strategy)
    if request.is_plain and supported is not None and request.window in supported.windows:
        return (request,)
    if request.strategy == COMPUTED_MODE:
        if request.window != COMPUTED_WINDOW:
            return (replace(request, top100_weight=0), request)
        return (request,)
    if request.window != COMPUTED_WINDOW:
        control = replace(request, strategy=COMPUTED_MODE, rival_entry_id=None, top100_weight=0)
        if not request.top100_weight:
            return (control, request)
        return (control, replace(request, top100_weight=0), request)
    return (replace(request, top100_weight=0), request)


def documents_to_solve(
    request: MenuRequest,
    *,
    projection: Projection,
    prerequisite: PrerequisiteLookup | None = None,
) -> tuple[MenuRequest, ...]:
    """``menu_documents`` without the ones ``prerequisite`` holds now: what will be solved.

    Handed the same lookup, ``advise_menu_entry`` tells ``on_document`` about exactly these,
    once each. The asked document is always among them, since it is never looked up.
    """

    *before, asked = menu_documents(request, projection=projection)
    return (
        *(address for address in before if prerequisite is None or prerequisite(address) is None),
        asked,
    )


class _ReportOnce:
    """Passes an address to ``on_document`` the first time a document is solved for it.

    A rival window under a setting asks for the pure-points window at 0, and so does the
    rival window at 0 it is compared with. ``_SolvedInThisCall`` has the second need read
    what the first one solved, so it is solved once; this keeps it told once as well,
    should a document ever be solved twice in one call.
    """

    __slots__ = ("_on_document", "_told")

    def __init__(self, on_document: DocumentSolved) -> None:
        self._on_document = on_document
        self._told: set[MenuRequest] = set()

    def __call__(self, address: MenuRequest) -> None:
        if address not in self._told:
            self._told.add(address)
            self._on_document(address)


class _SolvedInThisCall:
    """The caller's lookup, plus every prerequisite one ``advise_menu_entry`` call solved.

    A rival window under a setting depends on the pure-points window at 0 twice: it is
    priced against it, and so is the strategy's window at 0 it is compared with, which a
    nested call answers. The nested call is handed this same lookup, so the second need
    reads the document the first one solved instead of solving the window again. Each
    reader gets its own copy. It lives for one call: what is kept across calls is the
    caller's lookup alone.
    """

    def __init__(self, caller: PrerequisiteLookup | None) -> None:
        self._caller = caller
        self._solved: dict[MenuRequest, dict[str, object]] = {}

    def __call__(self, address: MenuRequest) -> Mapping[str, object] | None:
        solved = self._solved.get(address)
        if solved is not None:
            return copy.deepcopy(solved)
        return self._caller(address) if self._caller is not None else None

    def keep(self, address: MenuRequest, payload: Mapping[str, object]) -> None:
        self._solved[address] = copy.deepcopy(dict(payload))


def _require_capture(
    request: MenuRequest, inputs: RecommendationInputs, rules: SeasonRules
) -> None:
    """The checks ``advise_entry`` makes, for the producers that do not pass through it."""

    if request.season != str(inputs.season):
        raise EntryError(
            f"Request season {request.season!r} is not the capture's {inputs.season!r}."
        )
    if request.gameweek != int(inputs.deadline.gameweek):
        raise EntryError(
            f"Request gameweek {request.gameweek} is not the capture's "
            f"{int(inputs.deadline.gameweek)}."
        )
    if rules.season != inputs.season:
        raise EntryError("The advice rules belong to another season.")
    if rules.source_snapshot_id != inputs.snapshot_id:
        raise EntryError("The advice rules belong to another capture.")


def advise_menu_entry(
    request: MenuRequest,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    horizon_builder: HorizonBuilder | None = None,
    top100_counts: Top100Counts | None = None,
    manager_words: ManagerWords | None = None,
    prerequisite: PrerequisiteLookup | None = None,
    chip_forecast_source: ForecastSource | None = None,
    on_document: DocumentSolved | None = None,
) -> dict[str, object]:
    """Compute one document of the member menu from the member's own picks.

    ``top100_counts`` and ``manager_words`` are the capture's inputs for the two switches;
    ``None`` means the capture has none, and a request that needs one is refused with
    ``MenuInputUnavailable`` naming it. ``prerequisite`` lets a caller that keeps answers
    hand back a document this one is priced or compared against (the pure-points window
    at 0, the strategy's own document at 0) rather than have it solved again; it must
    have been computed from these same inputs, and anything it does not hold is solved
    here, once per call however many parts of the request depend on it.

    ``on_document`` is told the address of each document solved here, once per address:
    each one this is priced or compared against as it is solved (not one ``prerequisite``
    handed back, nor one this call already solved), then the asked one, just before it is
    returned. These are the documents ``documents_to_solve`` names for the same lookup. A
    request that fails tells nothing more after the failure.
    """

    report = (
        on_document
        if on_document is None or isinstance(on_document, _ReportOnce)
        else _ReportOnce(on_document)
    )
    payload = _advise_menu_entry(
        request,
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
        horizon_builder=horizon_builder,
        top100_counts=top100_counts,
        manager_words=manager_words,
        prerequisite=prerequisite,
        chip_forecast_source=chip_forecast_source,
        report=report,
    )
    if report is not None:
        report(request)
    return payload


def _advise_menu_entry(
    request: MenuRequest,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    horizon_builder: HorizonBuilder | None,
    top100_counts: Top100Counts | None,
    manager_words: ManagerWords | None,
    prerequisite: PrerequisiteLookup | None,
    chip_forecast_source: ForecastSource | None,
    report: DocumentSolved | None,
) -> dict[str, object]:
    """``advise_menu_entry`` itself; ``report`` hears of each document this one solves first."""

    validate_advice_selection(
        strategy=request.strategy,
        window=request.window,
        entry_id=request.entry_id,
        rival_entry_id=request.rival_entry_id,
        capabilities=menu_capabilities(),
        top100_weight=request.top100_weight,
        managers_word=request.managers_word,
        chip=request.chip,
    )
    if request.top100_weight and top100_counts is None:
        raise MenuInputUnavailable(
            TOP100_COUNTS_INPUT,
            "A Top 100 setting was asked for and this capture has no Top 100 counts "
            f"({TOP100_COUNTS_INPUT} is missing).",
        )
    if request.managers_word and manager_words is None:
        raise MenuInputUnavailable(
            MANAGER_WORDS_INPUT,
            "The manager's word was asked for and this capture has no coded club news "
            f"({MANAGER_WORDS_INPUT} is missing).",
        )
    _require_capture(request, inputs, rules)
    plain = request.entry_request()
    football_weighted_window = _one_budget_window(request, projection)
    if (
        football_weighted_window
        or request.preferences.active
        or (
            request.chip is not None
            and (request.chip == "auto" or request.window != 1 or request.top100_weight)
        )
    ):
        payload = advise_chip_strategy(
            plain,
            chip=request.chip,
            top100_weight=request.top100_weight,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            horizon_builder=horizon_builder,
            counts=top100_counts,
            preferences=request.preferences,
        )
        if football_weighted_window:
            assert top100_counts is not None
            payload["selection_top100_source"] = top100_counts.source_record()
            limits = payload.get("stated_limits")
            assert isinstance(limits, list)
            for sentence in (
                TOP100_LIMIT.format(weight=request.top100_weight),
                TOP100_WINDOW_LIMIT,
            ):
                if sentence not in limits:
                    limits.append(sentence)
        return payload
    if request.chip is not None:
        held_chips = held_member_chips(plain, provider=provider, inputs=inputs, rules=rules)
        if held_chips is None or request.chip not in held_chips:
            raise ChipUnavailable("CHIP_HISTORY_UNKNOWN" if held_chips is None else "CHIP_NOT_HELD")
        try:
            payload = advise_with_chip(
                plain,
                chip=request.chip,
                provider=provider,
                inputs=inputs,
                projection=projection,
                rules=rules,
            ).payload
            if chip_forecast_source is not None:
                picks = provider.picks(request.entry_id, request.season, request.gameweek - 1)
                payload["chip_forecast"] = member_chip_forecast(
                    league_id=request.league_id,
                    picks=picks,
                    inputs=inputs,
                    projection=projection,
                    rules=rules,
                    source=chip_forecast_source,
                    gains=published_chip_gains(((request.chip, payload),)),
                )
            return payload
        except EntryError as error:
            raise TransferPlanningError(str(error)) from error

    # A nested call is handed the lookup its outer call made, so the whole call shares it.
    lookup = (
        prerequisite
        if isinstance(prerequisite, _SolvedInThisCall)
        else _SolvedInThisCall(prerequisite)
    )

    def at_zero(address: MenuRequest) -> dict[str, object]:
        """A document this one depends on: taken from the lookup when held, else solved."""

        held = lookup(address)
        if held is not None:
            return dict(held)
        solved = advise_menu_entry(
            address,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            horizon_builder=horizon_builder,
            prerequisite=lookup,
            on_document=report,
        )
        lookup.keep(address, solved)
        return solved

    supported = advice_capabilities().get(request.strategy)
    if request.is_plain and supported is not None and request.window in supported.windows:
        return advise_entry(
            plain,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            horizon_builder=horizon_builder,
        )
    weight = request.top100_weight
    if request.strategy == COMPUTED_MODE:
        if request.window != COMPUTED_WINDOW:
            assert top100_counts is not None
            return advise_window_with_top100(
                plain,
                weight=weight,
                counts=top100_counts,
                provider=provider,
                inputs=inputs,
                projection=projection,
                rules=rules,
                horizon_builder=horizon_builder,
                control_payload=at_zero(replace(request, top100_weight=0)),
            ).payload
        if not weight:
            assert manager_words is not None
            return advise_with_managers_word(
                plain,
                words=manager_words,
                provider=provider,
                inputs=inputs,
                projection=projection,
                rules=rules,
            )
        assert top100_counts is not None
        advice = advise_with_top100(
            plain,
            weight=weight,
            counts=top100_counts,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            words=manager_words if request.managers_word else None,
        )
        if not request.managers_word:
            return advice.payload
        if advice.word_payload is None:
            raise ManagersWordNotSolved(
                advice.word_unavailable or "The manager's word could not be applied to this plan."
            )
        return advice.word_payload
    if request.window != COMPUTED_WINDOW:
        # Priced against the pure-points window at 0 whatever the setting; under a setting
        # it is also compared with this same strategy's window at 0.
        control_payload = at_zero(
            replace(request, strategy=COMPUTED_MODE, rival_entry_id=None, top100_weight=0)
        )
        window_at_zero = at_zero(replace(request, top100_weight=0)) if weight else None
        return advise_rival_window(
            plain,
            weight=weight,
            counts=top100_counts,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            horizon_builder=horizon_builder,
            control_payload=control_payload,
            reference_payload=window_at_zero,
        ).payload
    assert top100_counts is not None
    picks = _requested_picks(plain, request.entry_id, provider=provider, inputs=inputs)
    control = solve_member_control(picks, inputs, projection, rules)
    reference_address = replace(request, top100_weight=0)
    held_reference = prerequisite(reference_address) if prerequisite is not None else None
    if held_reference is not None:
        reference = dict(held_reference)
    else:
        reference = advise_entry(
            plain,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            control=control,
        )
        if report is not None:
            report(reference_address)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    pricing = solve_pricing_control(
        inputs, projection, held_squad_from_picks(picks, current_prices=prices), rules, control
    )
    return advise_rival_with_top100(
        plain,
        weight=weight,
        counts=top100_counts,
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
        control=control,
        pricing=pricing,
        reference_payload=reference,
    ).payload
