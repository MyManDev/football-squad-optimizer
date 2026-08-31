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
from typing import Protocol

import pandas as pd

from squadopt.application.views import _View
from squadopt.evaluation import FrozenSquadDecision
from squadopt.live.transfers import HeldSquad

ENTRY_REGISTRY_CONTRACT_VERSION = "entry_registry_v1"


class EntryError(ValueError):
    """An entry record could not be used."""


@dataclass(frozen=True, slots=True)
class EntryPicks:
    """A manager's team as the public FPL entry endpoints report it, at one gameweek.

    ``element`` ids are FPL element ids (the same ids the capture's bootstrap uses);
    ``purchase_prices`` may be empty when the endpoint does not publish them, in which
    case the held squad values players at their current price.
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
    """False when the source does not publish the banked count and ``free_transfers`` is
    the rule-implied floor of one. The public endpoints never state it, so a capture-built
    picks object carries ``1`` here with this flag down — and anything that plans transfers
    on it must surface that the second free transfer, if banked, is invisible."""
    chips_used: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    """Chip name -> the gameweeks it was played (what the planner's windows need)."""
    purchase_prices: Mapping[int, int] = field(default_factory=dict)
    purchase_prices_known: bool = False
    """False when selling prices cannot be derived. The public endpoints do not publish
    purchase prices, so a held squad built from such picks values every player at his
    *current* price — which overstates the budget whenever a player has risen since he was
    bought. A consumer that spends real budget on these numbers must say so to the user."""
    source_snapshot_id: str | None = None

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

    That fallback is not free, and the picks object now says so:
    ``picks.purchase_prices_known`` is False on capture-built picks because the public
    endpoints publish no purchase prices, so every selling price here is the *current*
    price — an overstatement of the real budget for any player who has risen since he was
    bought. The planner will spend that phantom budget. Any surface that shows a plan built
    from such a squad must carry the caveat; this function stays honest by construction
    only when its caller does.
    """

    missing = [p for p in picks.squad if p not in current_prices]
    if missing:
        raise EntryError(
            f"No current price for players {missing[:5]!r}; the capture must cover the squad."
        )
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
    )


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
