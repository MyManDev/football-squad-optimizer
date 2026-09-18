"""One entry point for the whole member menu, for a caller that answers one request.

The batch (``league_views.render_member``) walks a member's menu in one pass and hands
each producer what the pass already solved. A request path has one address to answer and
nothing in hand, so this module is the same dispatch turned inside out: it validates the
combination, computes whatever the chosen producer needs first (the member's control, the
pricing plan, the pure-points window at setting 0, the strategy's own document at 0) and
calls the producer the batch calls, with the same arguments. Nothing about advice is
decided here; for the same inputs the payload is the batch's payload.

A plain request, no setting and no word, on a combination ``advise_entry`` answers is
``advise_entry``'s own payload, byte for byte.

**Adding a switch.** A switch is a field on ``MenuRequest`` with an off default, a tuple
of windows on ``AdviceCapability``, a per-capture input handed in as a keyword that may be
``None``, and one more branch in ``advise_menu_entry``. A chosen chip reads the member's
captured history and needs no separate artifact.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from squadopt.application.advice import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
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
from squadopt.application.advice_chips import advise_with_chip, member_chip_menu
from squadopt.application.advice_variants import (
    advise_rival_window,
    advise_rival_with_top100,
    advise_window_with_top100,
)
from squadopt.application.entries import EntryError, EntryPicksProvider, held_squad_from_picks
from squadopt.application.manager_words import ManagerWords
from squadopt.application.top100_weight import Top100Counts
from squadopt.live import Projection, RecommendationInputs, SeasonRules
from squadopt.optimization import SolverExecutionError
from squadopt.planning import TransferPlanningError

__all__ = [
    "MANAGER_WORDS_INPUT",
    "TOP100_COUNTS_INPUT",
    "ManagersWordNotSolved",
    "MenuInputUnavailable",
    "MenuRequest",
    "PrerequisiteLookup",
    "advise_menu_entry",
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

    def __post_init__(self) -> None:
        self.entry_request()  # the shared fields are refused by the type that owns them
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
        return self.top100_weight == 0 and not self.managers_word and self.chip is None


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


#: Where a document this computation depends on may already exist: handed the address,
#: it returns that document's payload as computed from these same inputs, or ``None``.
PrerequisiteLookup = Callable[[MenuRequest], Mapping[str, object] | None]


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
) -> dict[str, object]:
    """Compute one document of the member menu from the member's own picks.

    ``top100_counts`` and ``manager_words`` are the capture's inputs for the two switches;
    ``None`` means the capture has none, and a request that needs one is refused with
    ``MenuInputUnavailable`` naming it. ``prerequisite`` lets a caller that keeps answers
    hand back a document this one is priced or compared against (the pure-points window
    at 0, the strategy's own document at 0) rather than have it solved again; it must
    have been computed from these same inputs, and anything it does not hold is solved
    here.
    """

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
    if request.chip is not None:
        held_chips = held_member_chips(plain, provider=provider, inputs=inputs, rules=rules)
        if held_chips is None or request.chip not in held_chips:
            raise ChipUnavailable("CHIP_HISTORY_UNKNOWN" if held_chips is None else "CHIP_NOT_HELD")
        return advise_with_chip(
            plain,
            chip=request.chip,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
        ).payload

    def at_zero(address: MenuRequest) -> dict[str, object]:
        """A document this one depends on: taken from the caller when held, else solved."""

        held = prerequisite(address) if prerequisite is not None else None
        if held is not None:
            return dict(held)
        return advise_menu_entry(
            address,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            horizon_builder=horizon_builder,
            prerequisite=prerequisite,
        )

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
    held_reference = (
        prerequisite(replace(request, top100_weight=0)) if prerequisite is not None else None
    )
    reference = (
        dict(held_reference)
        if held_reference is not None
        else advise_entry(
            plain,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            control=control,
        )
    )
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
