"""Recommendations for anyone by FPL entry (team) id: the seam, before the data.

Phase C of the web plan lets a registered manager see what SquadOpt would do with *their*
squad. Three pieces meet here and this module fixes their shapes so each side can be
built independently:

- ``EntryPicks``: what the public FPL entry endpoints say about a team at a gameweek
  (picks, bank, chips used, transfers made). Producing it is the data role's work — a
  capture payload plus a parser in ``squadopt.data.sources`` — so this module only
  *declares* the ``EntryPicksProvider`` protocol it needs.
- ``EntryRegistry``: the list of entry ids the site precomputes for; a small JSON file
  today (``data/entries/registry.json``), a table later.
- ``held_squad_from_picks``: turns ``EntryPicks`` into the ``HeldSquad`` the transfer
  planner already understands, so the recommendation itself is the same code path as
  our own decision (``build_transfer_recommendation``).

Nothing here touches the network or the live path.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

import pandas as pd

from squadopt.application.views import _View
from squadopt.evaluation import FrozenSquadDecision
from squadopt.live.free_hit import FREE_HIT_CHIP, played_free_hit_last_week
from squadopt.live.rules import CHIP_NAMES, SeasonRules
from squadopt.live.transfers import HeldSquad

ENTRY_REGISTRY_CONTRACT_VERSION = "entry_registry_v1"
CAPTURED_SQUAD_BASIS = "captured"
"""``EntryPicks.squad_basis`` when the squad is the captured week's own; the data twin
declares the same literal, and the twin test keeps the two field lists identical."""


class EntryError(ValueError):
    """An entry record could not be used."""


@dataclass(frozen=True, slots=True)
class EntryPicks:
    """A manager's team as the public FPL entry endpoints report it, at one gameweek.

    ``element`` ids are FPL element ids (the same ids the capture's bootstrap uses);
    ``purchase_prices`` may be empty when the endpoint does not publish them, in which
    case the held squad prices each player at his current price and
    ``squad_sell_value_tenths`` states what the fifteen together are really worth.
    """

    entry_id: int
    season: str
    gameweek: int
    """The last gameweek whose picks are known (the squad held going into the next)."""
    squad: tuple[int, ...]
    """The fifteen picks in the platform's order; ``squad[11:]`` is the bench in the
    substitution order the platform walks when a starter plays no minutes (#262)."""
    starting_xi: tuple[int, ...]
    captain: int
    vice_captain: int
    """Who inherits the multiplier when the captain plays no minutes. Required rather than
    defaulted: a guessed vice hands the armband to the wrong player in exactly the weeks the
    captain blanked. Held in the squad, not necessarily in the starting eleven."""
    bank_tenths: int
    free_transfers: int
    free_transfers_known: bool = True
    """False when ``free_transfers`` is the rule-implied floor of one rather than the
    banked count. The public endpoints never state the count; a capture-built picks
    object derives it from the member's history (``live.banking.banked_free_transfers``)
    and raises this flag only when every week was present and the recorded hits agreed
    with the banking model. With the flag down, anything that
    plans transfers on it must surface that a banked second transfer is invisible."""
    chips_used: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    """Chip name -> the gameweeks it was played (what the planner's windows need)."""
    purchase_prices: Mapping[int, int] = field(default_factory=dict)
    purchase_prices_known: bool = False
    """False when no *per-player* selling price can be derived. The public endpoints do
    not publish purchase prices, so nothing says what any one of the fifteen would raise
    on his own. What the fifteen raise together is a different question and
    ``squad_sell_value_tenths`` answers it; a consumer that needs the split, to price one
    named sale, still has to say it does not have it."""
    squad_sell_value_tenths: int | None = None
    """What the fifteen would raise if all were sold, in tenths, or None when the source
    does not state it.

    The endpoints publish the entry's whole worth at the deadline (squad plus bank), so
    subtracting the bank leaves the squad's selling value exactly. It is the budget a
    plan may spend, and it is below the sum of the current prices for anyone holding a
    player who has risen, because the game keeps half of that rise. A held squad built
    without it, and without purchase prices, has no honest budget at all."""
    source_snapshot_id: str | None = None
    active_chip: str | None = None
    """The chip active in ``gameweek`` as the capture reported it, or None."""
    squad_basis: str = CAPTURED_SQUAD_BASIS
    """Which squad ``squad`` and ``bank_tenths`` describe. ``"captured"`` is the
    picks document of ``gameweek`` itself. After a Free Hit that squad is void at the
    next deadline, so the provider substitutes the squad held before the chip and says
    so here (``pre_free_hit_gw02`` for a Free Hit played in gameweek 3, see
    ``pre_free_hit_basis``), so the advice can state which squad it stands on."""

    def __post_init__(self) -> None:
        if (
            isinstance(self.entry_id, bool)
            or not isinstance(self.entry_id, int)
            or self.entry_id < 1
        ):
            raise EntryError("entry_id must be a positive integer.")
        if len(self.squad) != 15 or len(set(self.squad)) != 15:
            raise EntryError("An entry's squad has fifteen distinct players.")
        if len(self.starting_xi) != 11 or not set(self.starting_xi) <= set(self.squad):
            raise EntryError("The starting eleven must be eleven of the squad's players.")
        if self.captain not in self.starting_xi:
            raise EntryError("The captain must be in the starting eleven.")
        if self.bank_tenths < 0 or self.free_transfers < 0:
            raise EntryError("bank_tenths and free_transfers cannot be negative.")
        if self.purchase_prices and not self.purchase_prices_known:
            raise EntryError(
                "purchase_prices are present but flagged unknown; a consumer could not "
                "tell whether to trust them."
            )
        if self.squad_sell_value_tenths is not None and self.squad_sell_value_tenths < 0:
            raise EntryError("squad_sell_value_tenths must be None or a count of tenths.")
        if not isinstance(self.squad_basis, str) or not self.squad_basis.strip():
            raise EntryError("squad_basis must be non-empty text.")
        if self.active_chip is not None and (
            not isinstance(self.active_chip, str) or not self.active_chip.strip()
        ):
            raise EntryError("active_chip must be None or a chip name.")


def pre_free_hit_basis(gameweek: int) -> str:
    """The ``squad_basis`` for a squad taken from ``gameweek``'s picks before a Free Hit."""

    return f"pre_free_hit_gw{gameweek:02d}"


class EntryPicksProvider(Protocol):
    """What the data side supplies: an entry's picks for a season and gameweek."""

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks: ...


@dataclass(frozen=True, slots=True)
class EntryRegistration:
    entry_id: int
    label: str
    registered_at_utc: str


@dataclass(frozen=True, slots=True)
class EntryRegistry:
    """The entry ids the site precomputes for.

    ``data/entries/registry.json``, and it is deliberately **not** committed. The real file
    lists a live classic league's members by entry id and team name, which is third-party
    data about identifiable people, so it stays local like the captures do — the reasoning
    is in ``.gitignore`` beside the rule. ``data/sample/entry_registry_v1.example.json``
    carries the shape, and ``scripts/seed_entry_registry.py`` rebuilds the real file from a
    captured standings page.

    ``load`` returning an empty registry for a missing path is what makes that workable: a
    fresh clone has no file and must not fail for the lack of one.
    """

    entries: tuple[EntryRegistration, ...]
    contract_version: str = ENTRY_REGISTRY_CONTRACT_VERSION

    @classmethod
    def load(cls, path: Path) -> "EntryRegistry":
        if not Path(path).is_file():
            return cls(entries=())
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("contract_version") != ENTRY_REGISTRY_CONTRACT_VERSION:
            raise EntryError(f"{path} is not an {ENTRY_REGISTRY_CONTRACT_VERSION} registry.")
        seen: set[int] = set()
        entries: list[EntryRegistration] = []
        for item in document.get("entries", []):
            entry_id = int(item["entry_id"])
            if entry_id in seen:
                raise EntryError(f"Entry {entry_id} is registered twice.")
            seen.add(entry_id)
            entries.append(
                EntryRegistration(
                    entry_id=entry_id,
                    label=str(item.get("label", "")),
                    registered_at_utc=str(item.get("registered_at_utc", "")),
                )
            )
        return cls(entries=tuple(entries))

    def ids(self) -> tuple[int, ...]:
        return tuple(sorted(e.entry_id for e in self.entries))


def held_squad_from_picks(picks: EntryPicks, *, current_prices: Mapping[int, int]) -> HeldSquad:
    """The ``HeldSquad`` the transfer planner starts from, for a registered entry.

    ``current_prices`` are the capture's prices (element id -> tenths); purchase prices
    fall back to them when the entry endpoints do not publish what was paid.

    That fallback is an upper bound, not an answer: the game sells a risen player for his
    purchase price plus half the rise, never for the market price, so a squad priced this
    way is worth more on paper than the member could raise. What stops a plan spending the
    difference is ``picks.squad_sell_value_tenths``, which the endpoints do publish for the
    fifteen together; it travels to the planner on the held squad and caps the budget
    there. Without it, and without purchase prices, there is no honest budget to plan on
    and this refuses rather than guessing the optimistic one.
    """

    missing = [p for p in picks.squad if p not in current_prices]
    if missing:
        raise EntryError(
            f"No current price for players {missing[:5]!r}; the capture must cover the squad."
        )
    # The aggregate is the answer to the question the purchase prices cannot answer, so it
    # travels only when they are the fallback. With real purchase prices the per-player
    # rule is exact and a second, older aggregate could only fight it.
    stated_sell_value: int | None = None
    if not picks.purchase_prices_known:
        if picks.squad_sell_value_tenths is None:
            raise EntryError(
                f"Entry {picks.entry_id} has neither purchase prices nor a stated squad "
                "selling value, so what it can spend is unknown. Planning on the current "
                "prices would credit the member with the half of every price rise the "
                "game keeps."
            )
        stated_sell_value = int(picks.squad_sell_value_tenths)
    purchase = {int(p): int(picks.purchase_prices.get(p, current_prices[p])) for p in picks.squad}
    return HeldSquad(
        season=picks.season,
        decided_gameweek=picks.gameweek,
        squad_player_ids=tuple(int(p) for p in picks.squad),
        purchase_prices=purchase,
        bank_tenths=int(picks.bank_tenths),
        free_transfers=int(picks.free_transfers),
        chips_used={
            str(name): tuple(int(w) for w in weeks) for name, weeks in picks.chips_used.items()
        },
        squad_sell_value_tenths=stated_sell_value,
    )


CHIP_HALF_LABELS: Final = ("first_half", "second_half")
"""The halves a chip's windows belong to, in the order the source publishes them: the
2026-27 bootstrap lists each of the four chips twice, once ending at gameweek 19 and
once starting at 20 (``live/rules.py`` reads them; nothing here fixes the boundary)."""


@dataclass(frozen=True, slots=True)
class ChipWindowState:
    """One published window of one chip, as the member stands before ``gameweek``.

    ``state`` is ``used`` (with ``gameweek`` the week it was played), ``expired`` (the
    window closed unplayed), ``not_yet`` (it cannot be played this week but can later:
    the window has not opened, or a Free Hit played last week bars this week's),
    ``available``, or ``unknown`` when the member's chip history was not captured at
    all: no history is not the same thing as no chips played.
    """

    state: str
    start_event: int
    stop_event: int
    gameweek: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "gameweek": self.gameweek,
            "start_event": self.start_event,
            "stop_event": self.stop_event,
        }


def chip_states(
    rules: SeasonRules,
    gameweek: int,
    chips_used: Mapping[str, Sequence[int]] | None,
) -> dict[str, dict[str, ChipWindowState | None]]:
    """Each chip's windows by half, read before ``gameweek``'s deadline.

    A window counts as spent once ``number`` plays fall inside it (``chip_availability_for``
    applies the same reading to the planner's horizon); a play outside every window is a
    history the rules cannot place and is refused. A chip the season lists once carries
    ``None`` for its second half; more windows than halves is a rule set this shape
    cannot state.

    One rule the published windows do not state is applied on top of them: "The Free Hit
    chip cannot be played in consecutive Gameweeks." A member who played the first half's
    Free Hit in gameweek 19 cannot play the second half's in gameweek 20, so that window
    reads ``not_yet`` in gameweek 20 and ``available`` from gameweek 21. Calling it
    available would be advice the game refuses.
    """

    played = (
        None
        if chips_used is None
        else {name: sorted(int(week) for week in weeks) for name, weeks in chips_used.items()}
    )
    states: dict[str, dict[str, ChipWindowState | None]] = {}
    for name in CHIP_NAMES:
        windows = sorted((w for w in rules.chips if w.name == name), key=lambda w: w.start_event)
        if len(windows) > len(CHIP_HALF_LABELS):
            raise EntryError(f"Chip {name!r} has {len(windows)} windows; halves cannot name them.")
        weeks = None if played is None else played.get(name, [])
        if weeks and not all(any(w.covers(week) for w in windows) for week in weeks):
            raise EntryError(f"Chip {name!r} was played in {weeks!r}, outside every window.")
        by_half: dict[str, ChipWindowState | None] = dict.fromkeys(CHIP_HALF_LABELS)
        for half, window in zip(CHIP_HALF_LABELS, windows, strict=False):
            inside = None if weeks is None else [week for week in weeks if window.covers(week)]
            if inside is None:
                state, when = "unknown", None
            elif len(inside) >= window.number:
                state, when = "used", inside[0]
            elif gameweek > window.stop_event:
                state, when = "expired", None
            elif gameweek < window.start_event:
                state, when = "not_yet", None
            elif name == FREE_HIT_CHIP and played_free_hit_last_week(gameweek, weeks or ()):
                # Open, unspent, and still not playable this week: the chip cannot be
                # played in consecutive gameweeks. ``weeks`` is the whole season's plays
                # because the forbidden pair (19 and 20) straddles the two windows.
                state, when = "not_yet", None
            else:
                state, when = "available", None
            by_half[half] = ChipWindowState(state, window.start_event, window.stop_event, when)
        states[name] = by_half
    return states


def frozen_decision_from_picks(
    picks: EntryPicks,
    *,
    player_pool: pd.DataFrame,
    player_codes: Mapping[int, object],
) -> FrozenSquadDecision:
    """Translate one captured entry from seasonal element ids to persistent player ids."""

    if not isinstance(picks, EntryPicks):
        raise EntryError("picks must be an EntryPicks instance.")
    if not isinstance(player_pool, pd.DataFrame):
        raise EntryError("player_pool must be a pandas DataFrame.")
    missing_columns = [
        column for column in ("player_id", "position") if column not in player_pool.columns
    ]
    if missing_columns:
        raise EntryError(f"player_pool is missing columns {missing_columns!r}.")
    if bool(player_pool[["player_id", "position"]].isna().any().any()):
        raise EntryError("player_pool player_id and position cannot be missing.")
    if bool(player_pool["player_id"].duplicated().any()):
        raise EntryError("player_pool player_id values must be unique.")

    missing_elements = [element for element in picks.squad if element not in player_codes]
    if missing_elements:
        raise EntryError(
            f"No persistent player code for captured elements {missing_elements[:5]!r}."
        )
    translated = {element: player_codes[element] for element in picks.squad}
    squad_ids = tuple(translated[element] for element in picks.squad)
    if len(set(squad_ids)) != len(squad_ids):
        raise EntryError("Captured element ids do not map to distinct persistent player codes.")

    indexed = player_pool.set_index("player_id", drop=False)
    missing_players = [player_id for player_id in squad_ids if player_id not in indexed.index]
    if missing_players:
        raise EntryError(
            f"player_pool does not cover translated squad players {missing_players[:5]!r}."
        )
    squad = indexed.loc[list(squad_ids)].reset_index(drop=True).copy(deep=True)
    return FrozenSquadDecision(
        squad=squad,
        starting_xi=tuple(translated[element] for element in picks.starting_xi),
        bench=tuple(translated[element] for element in picks.squad[11:]),
        captain_id=translated[picks.captain],
        vice_captain_id=translated[picks.vice_captain],
        completion_policy="captured_entry_v1",
    )


@dataclass(frozen=True, slots=True)
class EntryView(_View):
    """The page an entry sees: who they are, what they hold, and the decision proposed."""

    entry_id: int
    label: str
    season: str
    gameweek: int
    held_squad: Sequence[int]
    held_captain: int
    bank_tenths: int
    free_transfers: int
    chips_used: Mapping[str, Sequence[int]]
    recommendation_path: str
    """Relative site path of the RecommendationView computed for this entry."""
    source_snapshot_id: str | None
