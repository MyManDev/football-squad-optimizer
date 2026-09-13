"""Render per-member league views: the JSON tree the site's league pages read.

The web side (Package 5) reads ``data/league/members.json``, ``entries/{id}.json``,
``advice/{id}/{mode}/{window}.json``, ``advice/{id}/{strategy}/{window}/vs-{rival}.json``
and ``advice/{id}/index.json`` under the provisional contract its
``PROVISIONAL_CONTRACT.md`` records; this module is the producing half. It consumes the
`EntryPicksProvider` seam — today a test double, after #127 the capture-built provider —
and turns each member's held squad into a transfer plan with the same planner that
decides our own gameweek — without the decide path's proof-or-refuse gate: our ledger
refuses an unproven plan, a member's page publishes it with its ``solver_status`` and
measured ``optimality_gap`` instead — a found plan with its missing proof stated is
more honest than a vanished member. Given scenario paths it also prices each member's transfer
menu per play mode against a real rival from their own league (`mode_selection`), and
publishes one advice file per computed mode.

Two rules are load-bearing and tested rather than asserted:

- **Independence.** A member's advice is computed from that member's picks and the
  shared projection only. Nothing here reads the ledger, the system's own squad, or any
  other member's state — the system cannot protect its rank by advising anyone worse,
  and the invariance test pins that as bit-for-bit fact.
- **One failure does not sink the batch.** A member whose picks cannot be read or whose
  plan cannot be solved is recorded as failed with the reason, and the rest render.
"""

import functools
import json
import shutil
import unicodedata
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

from squadopt.application.advice import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    MEMBER_WINDOWS,
    AdviseEntryRequest,
    HorizonBuilder,
    advise_entry,
    build_advice_payload,
    solve_member_control,
)
from squadopt.application.advice_record import (
    AdviceRecordConflictError,
    PublishedAdvice,
    RecordCapture,
    build_member_advice_record,
    record_member_advice,
    repository_commit,
)
from squadopt.application.entries import (
    EntryError,
    EntryPicks,
    EntryPicksProvider,
    EntryRegistration,
    chip_states,
    held_squad_from_picks,
)
from squadopt.application.mode_selection import (
    ModeSelectionError,
    choose_rival,
    rival_squad_from_picks,
    select_member_modes,
)
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.application.strategies.rule import RIVAL_RULE_STRATEGIES, suggest_strategy
from squadopt.data.errors import DataError
from squadopt.evaluation.promotion import ExperimentError
from squadopt.live import (
    Projection,
    RecommendationInputs,
    SeasonRules,
)
from squadopt.live.transfers import plan_transfer_menu
from squadopt.scenarios import RivalSquad
from squadopt.scenarios.paths import ScenarioPathSet

LEAGUE_VIEW_CONTRACT_VERSION = "provisional_league_ui_v1"


def computable_rival_strategies() -> tuple[str, ...]:
    """The catalogue's rival strategies whose constraint reaches the solver today."""

    return tuple(
        slug
        for slug, strategy in STRATEGY_CATALOG.items()
        if strategy.rival_required
        and (
            strategy.constraints.overlap_floor is not None
            or strategy.constraints.overlap_ceiling is not None
        )
    )


@dataclass(frozen=True, slots=True)
class MemberRenderTask:
    """One member's unit of work: the baseline plus the rival menu, from their picks.

    Primitives and tuples only, so a caller may hand the tasks to a process pool. The
    rival ids are the other members whose picks the capture holds; the default rival is
    the standings neighbour the site shows before any rival is chosen.
    """

    entry_id: int
    label: str
    season: str
    gameweek: int
    league_id: int
    rival_ids: tuple[int, ...]
    default_rival_id: int | None
    rival_strategies: tuple[str, ...]
    #: The saf-puan windows beyond one week to solve; empty without a horizon builder.
    windows: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class MemberRender:
    """What one member's task produced: payloads, not files."""

    entry_id: int
    baseline: dict[str, object] | None
    reason: str
    rival_payloads: tuple[tuple[str, int, dict[str, object]], ...]
    unavailable: tuple[tuple[str, int, str], ...]
    #: The saf-puan windows that solved, and the ones that did not, with the reason.
    window_payloads: tuple[tuple[int, dict[str, object]], ...] = ()
    window_unavailable: tuple[tuple[int, str], ...] = ()
    #: The digest of every transfer-planning control this member's own plan was solved
    #: under, carried out of the task because the advice record has to state it and the
    #: control it comes from does not cross a process pool. Empty when the baseline failed.
    transfer_config_fingerprint: str = ""


def render_member(
    task: MemberRenderTask,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    horizon_builder: HorizonBuilder | None = None,
) -> MemberRender:
    """Solve one member's control once, then every (rival strategy, rival) from it, and
    every saf-puan window the task names.

    The baseline is ``advise_entry`` byte for byte; the rival files are ``advise_entry``
    with the same control handed back in, so nothing here can drift from the on-demand
    seam. One rival that cannot be priced — a band the squad cannot satisfy, a rival
    with players the projection lacks — is recorded as unavailable with its reason and
    the rest of the menu renders; a window that cannot be solved — a calendar the
    capture does not publish that far, no plan inside the budget — is recorded the same
    way, never dropped silently; a baseline that fails takes the member out of the
    menu entirely, with the reason on the members row.
    """

    try:
        picks = provider.picks(task.entry_id, task.season, task.gameweek - 1)
        control = solve_member_control(picks, inputs, projection, rules)
        baseline = advise_entry(
            AdviseEntryRequest(
                season=task.season,
                gameweek=task.gameweek,
                league_id=task.league_id,
                entry_id=task.entry_id,
            ),
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            control=control,
        )
    except (EntryError, DataError) as error:
        return MemberRender(task.entry_id, None, str(error), (), ())
    payloads: list[tuple[str, int, dict[str, object]]] = []
    unavailable: list[tuple[str, int, str]] = []
    for strategy in task.rival_strategies:
        for rival_id in task.rival_ids:
            try:
                payload = advise_entry(
                    AdviseEntryRequest(
                        season=task.season,
                        gameweek=task.gameweek,
                        league_id=task.league_id,
                        entry_id=task.entry_id,
                        strategy=strategy,
                        rival_entry_id=rival_id,
                    ),
                    provider=provider,
                    inputs=inputs,
                    projection=projection,
                    rules=rules,
                    control=control,
                )
            except (EntryError, DataError) as error:
                unavailable.append((strategy, rival_id, str(error)))
                continue
            payloads.append((strategy, rival_id, payload))
    window_payloads: list[tuple[int, dict[str, object]]] = []
    window_unavailable: list[tuple[int, str]] = []
    for window in task.windows:
        try:
            payload = advise_entry(
                AdviseEntryRequest(
                    season=task.season,
                    gameweek=task.gameweek,
                    league_id=task.league_id,
                    entry_id=task.entry_id,
                    window=window,
                ),
                provider=provider,
                inputs=inputs,
                projection=projection,
                rules=rules,
                horizon_builder=horizon_builder,
            )
        except (EntryError, DataError) as error:
            window_unavailable.append((window, str(error)))
            continue
        window_payloads.append((window, payload))
    return MemberRender(
        task.entry_id,
        baseline,
        "",
        tuple(payloads),
        tuple(unavailable),
        tuple(window_payloads),
        tuple(window_unavailable),
        control.transfer_config.configuration_fingerprint,
    )


#: How a caller runs the member tasks: ``map`` in-process, or a process pool's ``map``.
MemberMapper = Callable[
    [Callable[[MemberRenderTask], MemberRender], Iterable[MemberRenderTask]],
    Iterable[MemberRender],
]

# The site addresses advice by mode and window. The baseline pair — saf-puan at window
# one — is always computed, and it is always the deterministic planner's own answer.
# The competitive modes are computed only when the caller supplies scenario paths to
# price the member's menu on (`mode_paths`); without them the other combinations are
# simply absent and the page says so. The saf-puan windows beyond one are computed only
# when the caller supplies a projection horizon builder for the capture; a rival
# strategy stays at one week. Publishing a file for a combination nobody computed would
# make the site show an answer where none was measured, so the index names exactly the
# windows that solved and records the ones that did not, with the reason.


@dataclass(frozen=True, slots=True)
class MemberViewResult:
    """What one member's render produced, or why it did not."""

    entry_id: int
    label: str
    rendered: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MemberStanding:
    """Where a member sits in the league, as the standings page reports it.

    Declared here rather than imported from the data adapter so this module states what
    it needs rather than what one source happens to publish: a caller reading a different
    standings source maps into this and nothing else changes.

    Points are optional, and ``None`` is a claim rather than a placeholder: it says the
    capture does not prove this member's score for the week being published — no history
    row for it, or the week not yet final. A zero would say the member scored nothing,
    which is a different and possibly untrue statement. Both must survive to the page, so
    the renderer distinguishes them rather than collapsing both to falsy.

    ``gameweek_points`` is the week **gross** of the transfer hit, because that is what
    the source states; ``transfer_cost`` is the hit taken that week, so a reader of this
    can state the net week — the amount ``total_points`` actually advanced by. It is
    optional under the same rule as the points beside it: an absent cost says the capture
    does not carry this member's hit, not that the member took none, and a zero would be
    the untrue half of that pair.
    """

    entry_id: int
    team_name: str
    manager_name: str
    rank: int
    gameweek_points: int | None = None
    total_points: int | None = None
    transfer_cost: int | None = None


#: The longest team or manager name this publishes. Not a claim about what the game
#: allows — a bound on what we put in a document, so one member's name cannot decide the
#: size of a payload every other member downloads. Every name the real capture carries is
#: far inside it; a name that is not is truncated to it and the build says so.
PUBLISHED_NAME_LIMIT: Final = 64


def _entry_stand_in(entry_id: int) -> str:
    """The stand-in a member with no readable name is published under. ``advice.py``
    already labels a rival it cannot name this way, so a reader meets one convention,
    not two."""

    return f"entry-{int(entry_id)}"


def published_member_name(raw: str | None, *, entry_id: int, field: str) -> tuple[str | None, str]:
    """One member-typed name, and what had to be done to it to publish it.

    A team name and a manager name come out of the game as text the member typed. They
    are the only free text in this tree, and they land in ``members.json``, in
    ``entries/{id}.json``, in the rival label and in the page's own ``<h1>``. The page is
    React and escapes markup, but the page is not the only reader: these documents are
    fetched by whatever wants them, and a document is not made safe by one of its
    consumers. So the producer decides, once, what may be published — refusing at the
    page would leave the file itself carrying whatever arrived.

    What the producer decides is a question of *safety and shape*, not of wording. A
    member's team name is the member's own words, chosen inside the game and public there
    the moment the deadline passes; it is not a claim this site is making, so the honesty
    envelope — no probability, percentage, quantile, spread, likelihood or chance wording
    on a member-facing surface — does not reach it. That envelope governs the text *we*
    generate: strategy names, notes, badges, rule copy, everything in this tree that a
    member did not type. It is still enforced there, unchanged. A name that reads as a
    chance or a percentage in either language is published as captured, and the note that
    used to accompany the substitution is gone with it;
    ``tests/unit/test_public_probability_guards.py`` names the cases on both sides of
    that line.

    Two rules, in order, and each returns the reason it fired so the build can state it:

    - **Normalise.** Every character in Unicode's ``C`` classes becomes a space: the C0
      and C1 controls (a NUL that truncates a C string, an ESC that a terminal reads as a
      command, a newline that forges a second log line) and the format class, which is
      where the bidi overrides live — ``U+202E`` reverses everything printed after it, so
      a name carrying one rewrites the sentence it sits in. No real name contains any of
      them. Whitespace runs collapse afterwards, so removing a newline never joins two
      words. ``<`` and ``>`` go with them: our page is React and escapes markup — a
      ``<script>`` in a team name renders as five visible words and injects no node, and
      the probe confirmed it — but that is a property of one reader, and these files are
      served to whoever asks. The two characters open every markup and template language
      a name might be pasted into and mean nothing inside a name, so the producer does
      not hand them on.
    - **Bound.** Longer than ``PUBLISHED_NAME_LIMIT`` is truncated to it.

    ``None`` in stays ``None`` out: a name the capture never carried and a name that
    normalised away to nothing are different facts, and only the second one gets the
    entry's id as a stand-in — a member we hold no name for must read as unavailable
    rather than as a blank.
    """

    if raw is None:
        return None, ""
    notes: list[str] = []
    cleaned = "".join(
        " " if unicodedata.category(char).startswith("C") or char in "<>" else char for char in raw
    )
    cleaned = " ".join(cleaned.split())
    if cleaned != raw:
        notes.append(f"{field}: unprintable characters and markup delimiters removed")
    if len(cleaned) > PUBLISHED_NAME_LIMIT:
        cleaned = cleaned[:PUBLISHED_NAME_LIMIT].rstrip()
        notes.append(f"{field}: truncated to {PUBLISHED_NAME_LIMIT} characters")
    if not cleaned:
        # Nothing printable survived. The capture did carry something, so ``None`` — "no
        # name was captured" — would be the wrong claim; the id says what we know.
        return _entry_stand_in(entry_id), f"{field}: nothing printable survived normalisation"
    return cleaned, "; ".join(notes)


def _published_standing(placing: MemberStanding) -> tuple[MemberStanding, tuple[str, ...]]:
    """One standings row with both of its free-text fields put through the rule above."""

    entry_id = int(placing.entry_id)
    team, team_note = published_member_name(placing.team_name, entry_id=entry_id, field="team_name")
    manager, manager_note = published_member_name(
        placing.manager_name, entry_id=entry_id, field="manager_name"
    )
    notes = tuple(note for note in (team_note, manager_note) if note)
    # ``MemberStanding`` types both names as ``str``; only a name that was never captured
    # is None, and this path is only reached for one the capture did carry.
    return replace(placing, team_name=team or "", manager_name=manager or ""), notes


@dataclass(frozen=True, slots=True)
class LeagueViewsReport:
    league_id: int
    season: str
    gameweek: int
    members: tuple[MemberViewResult, ...]
    files: tuple[str, ...]
    #: Documents from an earlier publish that this run removed because it did not produce
    #: them. Reported rather than done quietly: a deletion under ``web/public`` is a change
    #: to what the site serves, and the operator reads this line beside "not rendered".
    removed: tuple[str, ...] = ()

    @property
    def rendered_count(self) -> int:
        return sum(1 for member in self.members if member.rendered)


def _prune_unpublished_members(
    out: Path, published: Collection[int], *, refused: Collection[int] = ()
) -> tuple[str, ...]:
    """Remove the member documents this run did not write, and name them.

    A publish is a whole picture of one gameweek, not an overlay on the last one — but the
    tree it builds into is the previous publish's. ``publish_gameweek_site`` checks a
    worktree out of ``origin/develop``, which carries the committed tree from last week, and
    then commits ``git add web/public/data``: the union of what it finds. Nothing here used
    to remove anything, so a member whose render failed kept last week's
    ``entries/{id}.json`` and ``advice/{id}/**`` while ``members.json`` was rewritten to this
    gameweek. Their row still linked, their page still rendered, and what it rendered was a
    finished gameweek's transfer recommendation served as this week's advice.

    Refusing the whole publish was the other way to answer that, and it is the wrong one. A
    member's picks go missing for reasons that have nothing to do with the other fourteen —
    a member with no current price took the whole batch out once — and this module's stated
    rule is that one failure does not sink the batch. Refusing would answer one member's
    data gap by withholding everyone else's advice, which is a larger harm than the one
    being fixed.

    So the publish stands and the absence becomes honest. The tree can already *say* absent:
    the member's row carries ``data_quality`` "empty". What it could not do was *be* absent,
    because the old document was still at the address. Removing it means the page has
    nothing to render rather than something wrong — absent, which is not the same as zero
    and not the same as stale.

    Only entry-shaped names are touched: a file under ``entries/`` or a directory under
    ``advice/`` whose name is an entry id this run did not publish. Anything else in the
    tree — ``scoreboard.json``, which a different script writes into the same directory
    after this one — is left exactly as found, because a rule that deletes what it did not
    anticipate is a worse failure than the one it fixes.

    A ``refused`` member is one this run wrote an ``advice/{id}/index.json`` for and nothing
    else: the index carries the reason the page shows, so it stays, and every other name
    under that directory — last week's documents — goes, along with ``entries/{id}.json``.
    """

    removed: list[str] = []
    kept = frozenset(refused)

    def _stale(name: str) -> bool:
        try:
            return int(name) not in published
        except ValueError:
            return False

    entries = out / "entries"
    if entries.is_dir():
        for path in sorted(entries.iterdir()):
            if path.is_file() and path.suffix == ".json" and _stale(path.stem):
                path.unlink()
                removed.append(f"entries/{path.name}")
    advice = out / "advice"
    if advice.is_dir():
        for path in sorted(advice.iterdir()):
            if not path.is_dir() or not _stale(path.name):
                continue
            if int(path.name) not in kept:
                shutil.rmtree(path)
                removed.append(f"advice/{path.name}/")
                continue
            for child in sorted(path.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child)
                    removed.append(f"advice/{path.name}/{child.name}/")
                elif child.name != "index.json":
                    child.unlink()
                    removed.append(f"advice/{path.name}/{child.name}")
    return tuple(removed)


def _refused_member_index(task: MemberRenderTask, *, reason: str) -> dict[str, object]:
    """The index of a member with no advice this week, under the successful index's shape.

    Every declared strategy is listed and none is computed; the reason sits in
    ``unavailable`` once per strategy with no rival, where the page already reads reasons.
    ``windows`` names no window for any strategy, so a reader that checks each listed
    window's file finds nothing promised.
    """

    strategies = [COMPUTED_MODE, *task.rival_strategies]
    return {
        "league_id": task.league_id,
        "season": task.season,
        "gameweek": task.gameweek,
        "entry_id": task.entry_id,
        "window": COMPUTED_WINDOW,
        "windows": {strategy: [] for strategy in strategies},
        "strategies": strategies,
        "rival_entry_ids": list(task.rival_ids),
        "default_rival_entry_id": task.default_rival_id,
        "suggested_strategy": None,
        "computed": [],
        "unavailable": [
            {"strategy": strategy, "rival_entry_id": None, "reason": reason}
            for strategy in strategies
        ],
    }


def _envelope(payload: Mapping[str, object], *, generated_at_utc: str) -> dict[str, object]:
    return {
        "contract_version": LEAGUE_VIEW_CONTRACT_VERSION,
        "generated_at_utc": generated_at_utc,
        "source_kind": "live",
        "payload": dict(payload),
    }


def _entry_player(
    row: "pd.Series[Any]",
    *,
    role: str,
    is_captain: bool,
    bench_order: int | None,
    is_vice_captain: bool | None,
) -> dict[str, object]:
    name = str(row["name"])
    return {
        "player_id": int(str(row["player_id"])),
        "name": name,
        "short_name": name.rsplit(" ", 1)[-1],
        "position": str(row["position"]),
        "team": str(row["team_id"]),
        "price_tenths": int(str(row["price_tenths"])),
        "expected_points": float(str(row["expected_points"])),
        "event_points": None,
        "is_captain": is_captain,
        # Absent, never false, when no held vice could be established (``None`` here):
        # a reader that saw ``false`` on all fifteen would take it as "this member named
        # nobody", which is a different and unproven claim.
        **({} if is_vice_captain is None else {"is_vice_captain": is_vice_captain}),
        "bench_order": bench_order,
        "role": role,
    }


def _held_vice_captain(picks: EntryPicks, pool: Mapping[int, object]) -> int | None:
    """The vice-captain the member actually holds, or ``None`` when none can be stated.

    ``EntryPicks`` requires a vice rather than defaulting one (see the field's docstring:
    a guessed vice hands the armband to the wrong player in exactly the weeks the captain
    blanked), but the application type validates nothing about the value, so the two facts
    the capture parser proves are re-established here instead of assumed: the vice is one
    of the fifteen, and he is not the captain. A value that fails either is a stand-in, and
    publishing a stand-in would hand the page a guess wearing the shape of a fact.

    He must also be in the projection pool, because a player the pool does not carry is
    dropped from the published fifteen below; flagging the other fourteen ``false`` would
    then read as "nobody holds it" rather than "the holder is not on this page".

    He may be on the bench. The parser deliberately accepts a benched vice, and one of the
    fifteen real entries in the September capture names one.
    """

    vice = int(picks.vice_captain)
    if vice == int(picks.captain) or vice not in set(picks.squad) or vice not in pool:
        return None
    return vice


def _entry_squad_payload(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    member_row: Mapping[str, object],
    missing: list[str],
    scored_gameweek: int | None,
) -> dict[str, object]:
    """The member's own squad, as the site's entry page renders it."""

    pool = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
    vice = _held_vice_captain(picks, pool)
    starters: list[dict[str, object]] = []
    bench: list[dict[str, object]] = []
    bench_index = 0
    for player_id in picks.squad:
        row = pool.get(int(player_id))
        if row is None:
            continue
        # None on every record when no vice is held, so the field is absent from the whole
        # document rather than present and false: the page's "not stated" path is the one
        # that must stay live for such a member.
        wears_vice = None if vice is None else int(player_id) == vice
        if int(player_id) in set(picks.starting_xi):
            starters.append(
                _entry_player(
                    row,
                    role="starter",
                    is_captain=int(player_id) == int(picks.captain),
                    bench_order=None,
                    is_vice_captain=wears_vice,
                )
            )
        else:
            bench_index += 1
            bench.append(
                _entry_player(
                    row,
                    role="bench",
                    is_captain=False,
                    bench_order=bench_index,
                    is_vice_captain=wears_vice,
                )
            )
    # What is still playable, per half, read before the upcoming deadline. A capture-built
    # EntryPicks always carries the history (the capture reader refuses a payload without
    # its chips list), so ``known`` is true for every document the site publishes today;
    # it is derived rather than written so that a provider without the history publishes
    # the same shape with ``known`` false and every window ``unknown``, and the raw history
    # absent rather than an empty map that would read as "no chip played".
    upcoming = picks.gameweek + 1
    states = chip_states(rules, upcoming, picks.chips_used)
    windows = [window for halves in states.values() for window in halves.values()]
    chips_known = picks.chips_used is not None and all(
        window.state != "unknown" for window in windows if window is not None
    )
    return {
        "league_id": int(league_id),
        "season": picks.season,
        "gameweek": upcoming,
        "scored_gameweek": scored_gameweek,
        "entry": dict(member_row),
        "starting_xi": starters,
        "bench": bench,
        "bank_tenths": int(picks.bank_tenths),
        "free_transfers": int(picks.free_transfers),
        "free_transfers_known": bool(picks.free_transfers_known),
        "chips_used": (
            {name: list(weeks) for name, weeks in picks.chips_used.items()} if chips_known else None
        ),
        "chips": {
            "known": chips_known,
            "gameweek": upcoming,
            "states": {
                name: {
                    half: None if window is None else window.to_dict()
                    for half, window in halves.items()
                }
                for name, halves in states.items()
            },
        },
        # Which squad the fifteen above are: the captured week's own, or the squad held
        # before a Free Hit voided it (``pre_free_hit_gwNN``), and the chip active in the
        # captured week. The advice documents already say this; the squad page must too,
        # or a pre-Free-Hit fifteen reads as the week's picks.
        "squad_basis": picks.squad_basis,
        "active_chip": picks.active_chip,
        "purchase_prices_known": bool(picks.purchase_prices_known),
        # What the fifteen would raise if sold, and that plus the bank: what the member
        # may spend. The endpoints publish no purchase price, so no page may add up the
        # fifteen current prices and call the total a budget, because the game keeps half
        # of every rise since a player was bought. The aggregate is published instead, and
        # it is what the plan on this page was held to. Null where a source states neither.
        "squad_sell_value_tenths": (
            None if picks.squad_sell_value_tenths is None else int(picks.squad_sell_value_tenths)
        ),
        "spendable_budget_tenths": (
            None
            if picks.squad_sell_value_tenths is None
            else int(picks.squad_sell_value_tenths) + int(picks.bank_tenths)
        ),
        "source_snapshot_id": picks.source_snapshot_id,
        # Comparing a member's gameweek score with ours needs both scores; the standings
        # view does not carry points yet, so this stays absent rather than guessed.
        "squadopt_comparison": None,
        "data_quality": "partial" if missing else "complete",
        "missing_fields": list(missing),
    }


def _suggested_strategy(
    task: MemberRenderTask,
    *,
    placings: Mapping[int, MemberStanding],
    gameweek: int,
    scored_gameweek: int | None,
) -> dict[str, object] | None:
    """The declared rule's pick for this member, or ``None`` when it cannot be stated.

    The rule reads two numbers: the member's league total minus their default rival's,
    and the gameweeks left in the season (``strategies/rule.py``). Both totals must be
    proven for the same scored week — ``MemberStanding`` carries ``None`` rather than a
    zero when they are not — and both rival strategies must actually have been computed,
    or the rule could name a file this batch never wrote. Anything missing makes the
    suggestion absent, which is a smaller claim than a guessed one.

    The rule names a strategy, not a file. Whether that strategy solved against this
    particular rival is a separate fact, already recorded in ``computed`` and
    ``unavailable`` beside it, and the page reads both.

    This decides which of the member's own three advice files to point at. It does not
    enter any of them: every advice file is still computed from that member's squad
    alone, and the invariance test pins that.
    """

    rival_id = task.default_rival_id
    if rival_id is None or scored_gameweek is None:
        return None
    if any(slug not in task.rival_strategies for slug in RIVAL_RULE_STRATEGIES):
        return None
    mine = placings.get(task.entry_id)
    theirs = placings.get(rival_id)
    if mine is None or theirs is None:
        return None
    if mine.total_points is None or theirs.total_points is None:
        return None
    return suggest_strategy(
        rival_entry_id=int(rival_id),
        points_ahead_of_rival=int(mine.total_points) - int(theirs.total_points),
        gameweek=int(gameweek),
        scored_gameweek=int(scored_gameweek),
    ).to_dict()


def build_league_views(
    provider: EntryPicksProvider,
    registrations: tuple[EntryRegistration, ...],
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    league_name: str,
    out_dir: Path,
    standings: Mapping[int, MemberStanding] | None = None,
    scored_gameweek: int | None = None,
    now: datetime | None = None,
    mode_paths: ScenarioPathSet | None = None,
    menu_plan_count: int = 5,
    rival_strategies: tuple[str, ...] | None = None,
    rival_menu: bool = True,
    mapper: MemberMapper = map,
    horizon_builder: HorizonBuilder | None = None,
    advice_record_root: Path | None = None,
) -> LeagueViewsReport:
    """Render every registered member's squad and advice under ``out_dir``.

    The system's own squad is deliberately not an input: member advice must be
    invariant to it (the test pins this bit-for-bit), and the system's row on the
    members page is rendered by the site from its own ledger views, not here.

    ``rival_menu`` renders, beside the baseline, every computable rival strategy
    (``rival_strategies``, default: the catalogue's) against every other member whose
    picks the capture holds: ``advice/{id}/{strategy}/{window}/vs-{rival}.json``, plus
    ``advice/{id}/{strategy}/{window}.json`` for the standings-neighbour default and
    ``advice/{id}/index.json`` naming what was computed and what was not, with the
    reason. ``mapper`` runs the per-member tasks — ``map`` here, or a process pool's
    ``map`` from the site script; the bytes do not depend on which.

    The index also carries ``suggested_strategy``: the declared rule's pick among the
    three, from the member's points gap to their default rival and the gameweeks
    remaining (``strategies/rule.py``), with those inputs published beside it so a
    reader can re-apply the rule. It is a pointer at one of the files below, not an
    input to any of them, and it is ``null`` whenever either total is unproven.

    ``horizon_builder`` turns on the saf-puan windows beyond one week
    (``advice/{id}/saf-puan/3.json``, ``5.json``): the index then lists, per strategy,
    the windows that solved (``windows``), and a window that did not is in
    ``unavailable`` with its reason. The one-week baseline's bytes are the same with or
    without it. Without a builder the index lists window one only, as before.

    ``mode_paths`` — one-week scenario paths for this deadline — turns on the
    competitive modes: each member's transfer menu is priced on the shared paths
    against a real rival from their own league (their nearest standings neighbour),
    and one advice file per competitive mode is written beside the baseline. The
    baseline saf-puan file stays byte-identical either way: it is always the
    deterministic planner's answer, never a scenario-scored re-pick. A member whose
    menu or selection fails keeps their baseline advice, with the reason recorded.

    ``advice_record_root`` turns on the immutable per-member, per-gameweek, per-capture
    advice record (``application/advice_record.py``). The published tree has no gameweek in
    its paths and is overwritten every week, so without this nothing on disk survives to say
    what a member was told for a given week. The record is written here, by the same call
    that writes the published bytes, from the same picks, projection and payloads; a runner
    around this could only guess. The weekly run passes it for the preview it will publish,
    since that preview's tree is what its publish stage commits, without solving again.

    The record is keyed by ``inputs``' capture, so the mid-week publish and the one taken
    shortly before the deadline each write their own and neither refuses the other. A
    re-publish of *one* capture is a replay and keeps the record it already wrote: the
    envelopes below are stamped with ``generated``, which moves whenever ``now`` is not
    passed — and no caller here passes it — so the same advice re-published is never the
    same bytes. What is still refused is a rebuild of one capture that produces different
    *advice*: the capture is the whole input, so that is our own non-determinism, and it
    raises ``AdviceRecordConflictError`` naming the difference.

    The records are written after every member's files are on disk, so a refusal can never
    stop the advice being published; the refusal is raised once, after every writable record
    has been written. The published bytes are identical with and without this argument.
    """

    # Every member-typed name is normalised here, once, before anything reads a standings
    # row: ``_row`` writes both names into ``members.json`` and into the ``entry`` block
    # of ``entries/{id}.json``, and the rival label below is the same ``team_name`` again.
    # Normalising at the source is what makes those three agree; doing it at each of them
    # would be three chances to miss one. The wording of a name is the member's own and is
    # published as captured; only its shape is ours to decide.
    name_notes: dict[int, tuple[str, ...]] = {}
    placings: dict[int, MemberStanding] = {}
    for entry_id, raw_placing in (standings or {}).items():
        placings[entry_id], notes = _published_standing(raw_placing)
        if notes:
            name_notes[int(entry_id)] = notes
    # The registry's label is the same free text by another route — ``seed_entry_registry``
    # records each member's own team name as the label — and it is what every row falls
    # back to when the capture holds no standings page, so it is filtered on the same rule.
    labels: dict[int, str] = {}
    for registration in registrations:
        registered_id = int(registration.entry_id)
        safe_label, label_note = published_member_name(
            registration.label, entry_id=registered_id, field="label"
        )
        labels[registered_id] = safe_label or _entry_stand_in(registered_id)
        if label_note:
            name_notes[registered_id] = (*name_notes.get(registered_id, ()), label_note)
    if mode_paths is not None:
        window_weeks = tuple(int(week) for week in mode_paths.target.gameweeks)
        if window_weeks != (int(inputs.deadline.gameweek),):
            raise ValueError(
                f"mode_paths cover gameweeks {window_weeks!r}; these views decide "
                f"gameweek {int(inputs.deadline.gameweek)}."
            )
    # A score and the week it belongs to are one fact. The members view is labelled with
    # the *upcoming* gameweek, so points travelling without their own week would be read
    # under the wrong heading — publish both or neither.
    if scored_gameweek is None and any(
        placing.gameweek_points is not None
        or placing.total_points is not None
        or placing.transfer_cost is not None
        for placing in placings.values()
    ):
        raise ValueError(
            "Member points were supplied without the gameweek they were scored in. "
            "The number and its week ship together or not at all."
        )

    def _row(entry_id: int, label: str, quality: str) -> dict[str, object]:
        placing = placings.get(entry_id)
        return {
            "member_kind": "human",
            "entry_id": entry_id,
            "manager_name": placing.manager_name if placing else label,
            "team_name": placing.team_name if placing else None,
            "rank": placing.rank if placing else 0,
            "gameweek_points": placing.gameweek_points if placing else None,
            # The week's hit travels beside the week's gross score so the page can show
            # one basis for everyone. Null stays null: no hit was proven, not no hit.
            "transfer_cost": placing.transfer_cost if placing else None,
            "total_points": placing.total_points if placing else None,
            "movement": "unknown",
            "movement_places": None,
            "data_quality": quality,
        }

    generated = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    season = inputs.season
    gameweek = int(inputs.deadline.gameweek)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    results: list[MemberViewResult] = []
    member_rows: list[dict[str, object]] = []

    # Every member's picks are fetched once, up front: a rival is another member's real
    # squad, so the batch needs all of them before any single member's modes can render.
    # The system's squad is not here — the provider reads the league capture, which
    # cannot contain the ledger's paper entry — so rival choice preserves invariance.
    fetched: dict[int, EntryPicks | str] = {}
    for registration in registrations:
        entry_id = int(registration.entry_id)
        try:
            fetched[entry_id] = provider.picks(entry_id, season, gameweek - 1)
        except (EntryError, DataError) as error:
            fetched[entry_id] = str(error)
    rival_squads: dict[int, RivalSquad] = {}
    for registration in registrations:
        entry_id = int(registration.entry_id)
        picks_or_error = fetched[entry_id]
        if isinstance(picks_or_error, EntryPicks):
            placing = placings.get(entry_id)
            label = placing.team_name if placing is not None else labels[entry_id]
            rival_squads[entry_id] = rival_squad_from_picks(picks_or_error, label=label)
    ranks = {entry_id: placing.rank for entry_id, placing in placings.items()}
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    strategies = (
        tuple(rival_strategies) if rival_strategies is not None else computable_rival_strategies()
    )
    for slug in strategies:
        if slug not in computable_rival_strategies():
            raise ValueError(f"Rival strategy {slug!r} is not computable on this path.")

    def _default_rival(entry_id: int) -> int | None:
        candidates = {i: squad for i, squad in rival_squads.items() if i != entry_id}
        chosen = choose_rival(entry_id, ranks, candidates)
        if chosen is None:
            return None
        return next(i for i, squad in candidates.items() if squad is chosen)

    windows = (
        tuple(window for window in MEMBER_WINDOWS if window != COMPUTED_WINDOW)
        if horizon_builder is not None
        else ()
    )
    tasks = [
        MemberRenderTask(
            entry_id=int(registration.entry_id),
            label=labels[int(registration.entry_id)],
            season=season,
            gameweek=gameweek,
            league_id=int(league_id),
            rival_ids=(
                tuple(i for i in rival_squads if i != int(registration.entry_id))
                if rival_menu
                else ()
            ),
            default_rival_id=_default_rival(int(registration.entry_id)) if rival_menu else None,
            rival_strategies=strategies if rival_menu else (),
            windows=windows,
        )
        for registration in registrations
    ]
    renders = {
        render.entry_id: render
        for render in mapper(
            functools.partial(
                render_member,
                provider=provider,
                inputs=inputs,
                projection=projection,
                rules=rules,
                horizon_builder=horizon_builder,
            ),
            tasks,
        )
    }

    def _write(relative: str, payload: Mapping[str, object]) -> bytes:
        """Write one published file and return the exact bytes that landed at that path."""

        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(_envelope(payload, generated_at_utc=generated), indent=2)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(relative)
        # ``newline="\n"`` writes the text untranslated, so these are the file's bytes.
        return text.encode("utf-8")

    # Per rendered member: the picks the advice was computed from, the transfer-planning
    # digest it was solved under, and every advice document with the bytes that landed.
    # Records are written from this after the whole tree is on disk.
    publications: list[tuple[EntryPicks, str, list[PublishedAdvice], dict[str, object]]] = []
    #: Members with no advice this week, whose index names why.
    refused: set[int] = set()

    for registration, task in zip(registrations, tasks, strict=True):
        entry_id = int(registration.entry_id)
        picks_or_error = fetched[entry_id]
        render = renders[entry_id]
        if not isinstance(picks_or_error, EntryPicks) or render.baseline is None:
            reason = "; ".join(
                part
                for part in (
                    *name_notes.get(entry_id, ()),
                    render.reason
                    if isinstance(picks_or_error, EntryPicks)
                    else str(picks_or_error),
                )
                if part
            )
            results.append(MemberViewResult(entry_id, labels[entry_id], False, reason=reason))
            member_rows.append(_row(entry_id, labels[entry_id], "empty"))
            # The page reads this member's index for the reason; without one it can only
            # say "unavailable". The row keeps ``data_quality`` "empty" — no advice exists.
            refused.add(entry_id)
            _write(f"advice/{entry_id}/index.json", _refused_member_index(task, reason=reason))
            continue
        picks = picks_or_error
        advice = render.baseline
        quality = str(advice["data_quality"])
        member_row = _row(entry_id, labels[entry_id], quality)
        raw_missing = advice.get("missing_fields")
        missing = [str(field) for field in raw_missing] if isinstance(raw_missing, list) else []

        # The site addresses these by path: entries/{id}.json for the squad, and
        # advice/{id}/{mode}/{window}.json for a decision under one mode and horizon.
        squad_path = out / "entries" / f"{entry_id}.json"
        squad_path.parent.mkdir(parents=True, exist_ok=True)
        squad_payload = _entry_squad_payload(
            picks,
            inputs,
            projection,
            rules,
            league_id=league_id,
            member_row=member_row,
            missing=missing,
            scored_gameweek=scored_gameweek,
        )
        squad_path.write_text(
            json.dumps(_envelope(squad_payload, generated_at_utc=generated), indent=2),
            encoding="utf-8",
            newline="\n",
        )
        written.append(f"entries/{entry_id}.json")

        # Every advice document this member gets, kept with the bytes that landed so the
        # record digests what was published rather than a re-rendering of the payload.
        emitted: list[PublishedAdvice] = []

        relative = f"advice/{entry_id}/{COMPUTED_MODE}/{COMPUTED_WINDOW}.json"
        emitted.append(
            PublishedAdvice(
                COMPUTED_MODE, COMPUTED_WINDOW, None, relative, advice, _write(relative, advice)
            )
        )

        # The saf-puan windows beyond one week, beside the baseline at their own paths.
        for window, payload in render.window_payloads:
            relative = f"advice/{entry_id}/{COMPUTED_MODE}/{window}.json"
            emitted.append(
                PublishedAdvice(
                    COMPUTED_MODE, window, None, relative, payload, _write(relative, payload)
                )
            )

        # The rival menu: one file per (strategy, rival), the standings neighbour's copy
        # at the strategy's plain path, and an index that says what exists and why not.
        computed: list[dict[str, object]] = []
        for strategy, rival_id, payload in render.rival_payloads:
            relative = f"advice/{entry_id}/{strategy}/{COMPUTED_WINDOW}/vs-{rival_id}.json"
            emitted.append(
                PublishedAdvice(
                    strategy,
                    COMPUTED_WINDOW,
                    rival_id,
                    relative,
                    payload,
                    _write(relative, payload),
                )
            )
            computed.append({"strategy": strategy, "rival_entry_id": rival_id, "path": relative})
            if rival_id == task.default_rival_id:
                default_relative = f"advice/{entry_id}/{strategy}/{COMPUTED_WINDOW}.json"
                emitted.append(
                    PublishedAdvice(
                        strategy,
                        COMPUTED_WINDOW,
                        rival_id,
                        default_relative,
                        payload,
                        _write(default_relative, payload),
                    )
                )
        suggested = _suggested_strategy(
            task, placings=placings, gameweek=gameweek, scored_gameweek=scored_gameweek
        )
        if rival_menu or task.windows:
            unavailable: list[dict[str, object]] = [
                {"strategy": strategy, "rival_entry_id": rival_id, "reason": reason}
                for strategy, rival_id, reason in render.unavailable
            ]
            # A window that did not solve is a recorded reason at the same address the
            # rival pairs use, with no rival and the window named.
            unavailable.extend(
                {
                    "strategy": COMPUTED_MODE,
                    "rival_entry_id": None,
                    "window": window,
                    "reason": reason,
                }
                for window, reason in render.window_unavailable
            )
            _write(
                f"advice/{entry_id}/index.json",
                {
                    "league_id": int(league_id),
                    "season": season,
                    "gameweek": gameweek,
                    "entry_id": entry_id,
                    "window": COMPUTED_WINDOW,
                    # Per strategy, the windows whose file exists: saf-puan's solved
                    # windows, every rival strategy at one week.
                    "windows": {
                        COMPUTED_MODE: [
                            COMPUTED_WINDOW,
                            *(window for window, _payload in render.window_payloads),
                        ],
                        **{strategy: [COMPUTED_WINDOW] for strategy in task.rival_strategies},
                    },
                    "strategies": [COMPUTED_MODE, *task.rival_strategies],
                    "rival_entry_ids": list(task.rival_ids),
                    "default_rival_entry_id": task.default_rival_id,
                    # The declared rule's pick among the three, with the gap and the
                    # weeks remaining it read; null when either input is unproven.
                    "suggested_strategy": suggested,
                    "computed": computed,
                    "unavailable": unavailable,
                },
            )

        mode_note = ""
        rival = (
            choose_rival(
                entry_id,
                ranks,
                {i: squad for i, squad in rival_squads.items() if i != entry_id},
            )
            if mode_paths is not None
            else None
        )
        # Without a league neighbour the competitive modes are honestly absent, and the
        # member's menu is not worth solving for nobody.
        if mode_paths is not None and rival is not None:
            try:
                held = held_squad_from_picks(picks, current_prices=prices)
                menu = plan_transfer_menu(
                    inputs, projection, held, rules, plan_count=menu_plan_count
                )
                selection = select_member_modes(menu, mode_paths, rival)
                for item in selection.advice:
                    if item.mode == COMPUTED_MODE:
                        # The published saf-puan stays the deterministic baseline above;
                        # a scenario-mean re-pick of the same menu would let sampling
                        # noise move the one answer the control also gives.
                        continue
                    chosen_plan = menu[item.plan_index][0]
                    chosen_gap = chosen_plan.diagnostics.get("absolute_optimality_gap")
                    mode_payload = build_advice_payload(
                        picks,
                        inputs,
                        projection,
                        rules,
                        league_id=league_id,
                        mode=item.mode,
                        decision=item.decision,
                        expected_points_cost=item.expected_points_cost,
                        rival_label=item.rival_label,
                        solver_status=chosen_plan.solver_status.name,
                        optimality_gap=(float(str(chosen_gap)) if chosen_gap is not None else None),
                    )
                    mode_relative = f"advice/{entry_id}/{item.mode}/{COMPUTED_WINDOW}.json"
                    emitted.append(
                        PublishedAdvice(
                            item.mode,
                            COMPUTED_WINDOW,
                            None,
                            mode_relative,
                            mode_payload,
                            _write(mode_relative, mode_payload),
                        )
                    )
            except (EntryError, DataError, ModeSelectionError, ExperimentError, KeyError) as error:
                # One member's modes failing must not sink their baseline, or the batch.
                # KeyError is the scenario scorer meeting a player the paths do not
                # carry — a data gap for this member, not a reason the league fails.
                mode_note = f"competitive modes unavailable: {error}"

        # Which of the member's documents is the one we told them. The page points at the
        # declared rule's pick when there is one and its file was actually written; when
        # the rule could not be stated, or its file did not solve, the page shows the
        # pure-points baseline, and the record says which of the two it was rather than
        # leaving a later reader to re-apply a rule from inputs that have since moved.
        emitted_paths = {item.relative_path for item in emitted}
        suggested_slug = str(suggested["strategy"]) if suggested is not None else None
        suggested_path = (
            f"advice/{entry_id}/{suggested_slug}/{COMPUTED_WINDOW}.json"
            if suggested_slug is not None
            else None
        )
        told: dict[str, object] = (
            {
                "strategy": suggested_slug,
                "window": COMPUTED_WINDOW,
                # The rival of the document pointed at, not the rival the rule compared
                # against: the pure-points file is rival-free whoever suggested it.
                "rival_entry_id": (
                    None if suggested_slug == COMPUTED_MODE else task.default_rival_id
                ),
                "published_path": suggested_path,
                "source": "suggested_strategy",
            }
            if suggested_path is not None and suggested_path in emitted_paths
            else {
                "strategy": COMPUTED_MODE,
                "window": COMPUTED_WINDOW,
                "rival_entry_id": None,
                "published_path": f"advice/{entry_id}/{COMPUTED_MODE}/{COMPUTED_WINDOW}.json",
                "source": "baseline",
            }
        )
        publications.append((picks, render.transfer_config_fingerprint, emitted, told))

        # What was changed about this member's own name before it was published travels
        # on their row of the report, so the operator running the publish sees it. A name
        # we altered and never mentioned would be the quiet half of this fix.
        note = "; ".join(part for part in (*name_notes.get(entry_id, ()), mode_note) if part)
        results.append(MemberViewResult(entry_id, labels[entry_id], True, reason=note))
        member_rows.append(member_row)
    # The standings order is the league's order; registry order is arbitrary.
    if placings:
        member_rows.sort(
            key=lambda row: (int(str(row["rank"])) or 10**6, int(str(row["entry_id"])))
        )
    members_payload = {
        "league_id": int(league_id),
        "league_name": str(league_name),
        "season": season,
        "gameweek": gameweek,
        "public_after_deadline": True,
        "scored_gameweek": scored_gameweek,
        "members": member_rows,
    }
    members_path = out / "members.json"
    members_path.write_text(
        json.dumps(_envelope(members_payload, generated_at_utc=generated), indent=2),
        encoding="utf-8",
        newline="\n",
    )
    written.append(members_path.name)

    # Whatever this run did not produce is not this week's advice, and the tree it wrote
    # into is last week's. Removed after members.json rather than before the renders, so a
    # run that dies mid-batch leaves the old tree whole rather than half-deleted.
    removed = _prune_unpublished_members(
        out, {picks.entry_id for picks, _, _, _ in publications}, refused=refused
    )

    # The record comes last, after every published file is on disk: a refusal here must
    # never be able to stop a member's advice reaching them. Every member is attempted
    # even after one refuses, so a second deploy names every disagreement it found rather
    # than the first one, and every week that *can* be recorded still is.
    if advice_record_root is not None:
        commit = repository_commit()
        # The capture this build read is part of the record's key: a week published twice
        # from two captures leaves two records, and neither refuses the other.
        capture = RecordCapture(inputs.snapshot_id, inputs.captured_at_utc)
        conflicts: list[str] = []
        for picks, fingerprint, emitted, told in publications:
            record = build_member_advice_record(
                picks,
                projection,
                emitted,
                capture=capture,
                league_id=league_id,
                generated_at_utc=generated,
                league_view_contract_version=LEAGUE_VIEW_CONTRACT_VERSION,
                told=told,
                transfer_config_fingerprint=fingerprint or None,
                commit=commit,
            )
            try:
                record_member_advice(Path(advice_record_root), record)
            except AdviceRecordConflictError as error:
                conflicts.append(str(error))
        if conflicts:
            raise AdviceRecordConflictError("\n".join(conflicts))

    return LeagueViewsReport(
        league_id=int(league_id),
        season=season,
        gameweek=gameweek,
        members=tuple(results),
        files=tuple(sorted(written)),
        removed=removed,
    )
