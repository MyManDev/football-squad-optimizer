"""The weekly scoreboard: our paper squad beside the league, the Top-100, and the field.

    python -m scripts.build_scoreboard --league 352490 --out web/public
    python -m scripts.build_scoreboard --league 352490 --snapshot-id <fpl-live id> \\
        --cohort-snapshot <fpl-top100 id> --elite-snapshot <fpl-elite-picks id>

Writes ``<out>/data/league/scoreboard.json`` in the provisional league envelope: one row
per gameweek whose deadline had passed when the live capture was taken, each carrying what
the files on disk prove and ``null`` where they prove nothing. Nothing is decided here; the
ledger is read, never written.

Where each number comes from, and what it is:

- ``average_entry_score`` and ``highest_score``: the game's own summary of every manager's
  week, from the live capture's bootstrap ``events[]``. Published for a finished gameweek
  only — before that the source carries ``0`` and ``null``, and a zero average is not a
  measurement.
- ``members[]``: each registered member's week from that member's own
  ``entry-<id>-history.json`` in the same capture. The history's ``points`` is gross of the
  week's transfer cost (its ``total_points`` advances by ``points - event_transfers_cost``),
  so a row carries both and ``net`` is the difference — the same net our ledger records,
  which is what makes the two columns comparable.
- ``ours``: the ledger entry for the gameweek, when one exists: the settled net and named-
  eleven score, the hit points, the projection, and the mode the decision was made in
  (``live`` decided before its deadline from a capture that run took; ``replay`` recorded
  after that deadline, or from a capture the run did not take but named). Its
  ``scoring_basis`` remains ``named_eleven_no_autosubs`` for legacy decisions.
  Frozen bench order and vice-captain permit ``official_autosub_captain_v2`` from
  finished, checked event-live captures. Settlement is computed in memory; ledger
  files remain unchanged. Missing decision-time inputs yield null diagnostics.
  When the local ledger is empty, already published rows are retained as before,
  unless a retained row states a score without a basis, which is dropped instead.
  A row that is not settled carries ``net`` and ``scoring_basis`` both null: the basis
  describes the number, and there is no number.
- ``cumulative.ours_net``: the running total, on one basis and one only, named by
  ``cumulative.ours_basis``. A finished week scored on any other basis stays published in
  its own row and is listed in ``cumulative.ours_excluded_gameweeks`` with the basis that
  produced it, rather than being added in. Gameweek 1 of 2026-27 is such a week: its
  decision froze no bench order and no vice-captain, so no autosub scorer could score it,
  and its number is not the same measurement as the weeks that follow. ``ours_net`` is
  null while no week is on the series basis, which reads as "nothing to total" and never
  as zero.
- ``top100``: the Top-100 cohort's mean week, for the cohort capture's current gameweek
  only. The cohort is re-ranked every week, so a total is never differenced across
  captures; ``final`` says whether the gameweek was finished and checked in the cohort
  capture's own bootstrap. ``basis`` says what the mean is:

  - ``net`` — every one of ranks 1..100 was found in the elite-picks capture for that same
    gameweek, so the mean is over each member's ``entry_history.points`` minus their
    ``event_transfers_cost``. ``hit_points`` is the cost taken off across the cohort. This
    is the same net the members' and our columns carry, so the numbers compare.
  - ``gross`` — no picks capture covered the cohort, so the mean is over the standings'
    ``event_total``, which is **before** the transfer cost (in the 2026-09-07 capture,
    entry 7018833's standings row reads ``event_total 78`` while its own history reads
    ``points 78, event_transfers_cost 4``). A gross mean is not comparable with the net
    columns, and the card says so rather than letting it sit beside them unmarked.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from squadopt.application.entries import EntryRegistry
from squadopt.application.league_views import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.application.scoreboard_baselines import human_baseline_rows
from squadopt.application.scoreboard_diagnostics import empty_diagnostics
from squadopt.application.scoreboard_history import settled_scoreboard_entries
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    EntryGameweekPoints,
    fpl_entry_history_points,
    gameweek_deadlines,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.evaluation.models import ScoringBasis
from squadopt.live import (
    LedgerEntry,
    decision_mode,
    infer_season,
    load_ledger,
    season_from_bootstrap,
)
from squadopt.prediction.component_models import COMPONENT_MODEL_VERSION

SCOREBOARD_FILE: Final = "scoreboard.json"
TOP100_SIZE: Final = 100
COMPARISON_KINDS: Final = (
    "system",
    "base",
    "elite_xi",
    "ownership_template",
    "league_mean",
    "game_mean",
)
#: The basis the running total is kept on. A week scored on any other basis is a different
#: measurement, so it is published with its own basis named and left out of the total
#: rather than folded in. Named here once, deliberately fixed rather than inferred from
#: the weeks on hand: a total that quietly re-bases itself whenever the scorer changes is
#: the exact failure this constant exists to prevent. Moving the series to a new basis is
#: a decision about the record, and it should cost an edit here and an explanation.
SERIES_SCORING_BASIS: Final = str(ScoringBasis.OFFICIAL_AUTOSUB_CAPTAIN_V2)
#: The Overall standings pages a cohort capture holds, in page order.
_COHORT_PAGE = re.compile(r"^league-314-standings-page-(\d+)\.json$")
#: One cohort member's picks inside an elite-picks capture.
_COHORT_PICKS = re.compile(r"^entry-(\d+)-picks-gw(\d+)\.json$")


@dataclass(frozen=True, slots=True)
class CohortCapture:
    """A Top-100 capture as the scoreboard reads it: when, its bootstrap, its pages."""

    snapshot_id: str
    captured_at_utc: str
    bootstrap: bytes
    pages: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class CohortPicks:
    """An elite-picks capture as the scoreboard reads it: one gameweek's net per entry.

    ``capture_elite_picks`` writes each cohort member's picks document for the gameweek
    before the one it was taken for, and each carries that member's own ``entry_history``
    — the same block a member's history row is read from. ``net`` is that row's ``points``
    minus its ``event_transfers_cost``, and ``hits`` is the cost, so the cohort's mean can
    be stated on the same basis as every other column.
    """

    snapshot_id: str
    gameweek: int
    net: Mapping[int, int]
    hits: Mapping[int, int]


def played_gameweeks(bootstrap: bytes, *, as_of_utc: str) -> list[int]:
    """Gameweeks whose deadline had passed at ``as_of_utc``: played, or being played.

    A deadline exactly equal to the instant counts as passed, the same boundary
    ``next_open_deadline`` draws from the other side.
    """

    moment = as_instant(normalize_utc_timestamp(as_of_utc, label="as_of_utc"))
    return [
        deadline.gameweek
        for deadline in gameweek_deadlines(bootstrap)
        if as_instant(deadline.deadline_utc) <= moment
    ]


def _events(bootstrap: bytes) -> dict[int, Mapping[str, Any]]:
    document = json.loads(bootstrap.decode("utf-8"))
    events = document.get("events") if isinstance(document, dict) else None
    if not isinstance(events, list):
        raise DataError("The bootstrap payload carries no events list.")
    return {int(event["id"]): event for event in events if isinstance(event, dict)}


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def cohort_standings(cohort: CohortCapture) -> dict[int, tuple[int, int]]:
    """Ranks 1..100 of a cohort capture: rank to (entry id, ``event_total``).

    All 100 must be present exactly once across the pages: a cohort missing a rank is not
    a smaller cohort but one whose composition depends on which page failed.
    """

    rows: dict[int, tuple[int, int]] = {}
    for page in cohort.pages:
        document = json.loads(page.decode("utf-8"))
        section = document.get("standings") if isinstance(document, dict) else None
        results = section.get("results") if isinstance(section, dict) else None
        if not isinstance(results, list):
            raise DataError("A cohort standings page carries no standings.results list.")
        for row in results:
            if not isinstance(row, dict):
                continue
            rank, total, entry = row.get("rank_sort"), row.get("event_total"), row.get("entry")
            if isinstance(rank, bool) or not isinstance(rank, int):
                raise DataError("A cohort standings row has no integer rank_sort.")
            if rank > TOP100_SIZE:
                continue
            if isinstance(total, bool) or not isinstance(total, int):
                raise DataError(f"Cohort rank {rank} has no integer event_total.")
            if isinstance(entry, bool) or not isinstance(entry, int):
                raise DataError(f"Cohort rank {rank} has no integer entry id.")
            if rank in rows:
                raise DataError(f"Cohort rank {rank} appears on more than one page.")
            rows[rank] = (entry, total)
    if set(rows) != set(range(1, TOP100_SIZE + 1)):
        raise DataError(
            f"The cohort pages hold {len(rows)} of ranks 1..{TOP100_SIZE}; the mean over a "
            "partial cohort would be a number nobody can place."
        )
    return rows


def top100_week(
    cohort: CohortCapture, picks: CohortPicks | None = None
) -> dict[str, object] | None:
    """The Top-100's mean week for the cohort capture's current gameweek, and its basis.

    Net when ``picks`` covers every one of the hundred for that same gameweek — the
    standings publish ``event_total`` before the transfer cost, so the picks capture's own
    ``entry_history`` is what makes the cohort comparable with the net columns. Gross, and
    labelled gross, when no picks capture covers them. ``None`` only when no deadline had
    passed at capture time, so the pages describe no played week at all.
    """

    played = played_gameweeks(cohort.bootstrap, as_of_utc=cohort.captured_at_utc)
    if not played:
        return None
    gameweek = played[-1]
    rows = cohort_standings(cohort)
    week: dict[str, object] = {
        "gameweek": gameweek,
        "cohort_size": TOP100_SIZE,
        "final": gameweek in scored_gameweeks(cohort.bootstrap),
    }
    entries = {entry for entry, _ in rows.values()}
    if picks is not None and picks.gameweek != gameweek:
        raise DataError(
            f"The picks capture {picks.snapshot_id} holds gameweek {picks.gameweek}, which "
            f"is not the cohort capture's gameweek {gameweek}; netting one week's cohort "
            "with another week's costs would be a number nobody can place."
        )
    if picks is not None and entries <= set(picks.net):
        return {
            **week,
            "basis": "net",
            "mean_score": sum(picks.net[entry] for entry in entries) / TOP100_SIZE,
            "hit_points": float(sum(picks.hits[entry] for entry in entries)),
            "picks_snapshot_id": picks.snapshot_id,
        }
    return {
        **week,
        "basis": "gross",
        "mean_score": sum(total for _, total in rows.values()) / TOP100_SIZE,
        "hit_points": None,
        "picks_snapshot_id": None,
    }


def _ours(entry: LedgerEntry) -> dict[str, object]:
    decision = entry.decision
    transfers = decision.get("transfers")
    block = transfers if isinstance(transfers, Mapping) else {}
    outcome = entry.outcome
    net = None if outcome is None else _number(outcome.get("realized_net_score"))
    basis = None if outcome is None else outcome.get("scoring_basis")
    if net is not None and basis is None:
        raise DataError(
            f"GW{entry.gameweek} publishes a settled score of {net} and no scoring_basis. "
            "The rule that produced a number is not recoverable from the number, so it is "
            "stated or the row is refused; it is never supplied by the reader."
        )
    return {
        "net": net,
        "xi": None if outcome is None else _number(outcome.get("realized_xi_score")),
        "hits": float(str(block.get("transfer_hit_points", 0.0))),
        "projected": float(str(decision["projected_score"])),
        "mode": decision_mode(decision),
        # The basis describes the number beside it. An unsettled row has no number, so it
        # states no basis: claiming one here would assert a rule that never ran, and from
        # GW2 on it would name the wrong one, since those decisions settle officially.
        "scoring_basis": None if net is None else str(basis),
        "diagnostics": empty_diagnostics()
        if outcome is None
        else outcome.get("diagnostics", empty_diagnostics()),
        "outcome_snapshot_id": None if outcome is None else outcome.get("source_snapshot_id"),
        "vice_captain_named": decision.get("vice_captain_player_id") is not None,
    }


def _states_its_basis(ours: Mapping[str, object]) -> bool:
    """Whether a published row says what produced its number, if it has one."""

    return _number(ours.get("net")) is None or ours.get("scoring_basis") is not None


def _published_ours(path: Path, season: str) -> dict[int, dict[str, object]]:
    """Our rows the scoreboard at ``path`` already publishes for ``season``, by gameweek.

    Empty when there is no such file or it describes another season; a row is taken only
    where the published ``ours`` is an object, never made up for a gameweek without one.

    A row carrying a score but no stated basis is dropped rather than carried. Inertia is
    not evidence: a row that cannot say what produced its number does not earn a place in
    the series by having been published once before.
    """

    try:
        document = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    payload = document.get("payload") if isinstance(document, dict) else None
    if not isinstance(payload, dict) or payload.get("season") != season:
        return {}
    rows = payload.get("gameweeks")
    if not isinstance(rows, list):
        return {}
    return {
        int(row["gameweek"]): dict(row["ours"])
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("gameweek"), int)
        and isinstance(row.get("ours"), dict)
        and _states_its_basis(row["ours"])
    }


def _member_row(entry_id: int, week: EntryGameweekPoints) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "points": week.points,
        "hit_cost": week.transfer_cost,
        "net": None if week.transfer_cost is None else week.points - week.transfer_cost,
        "total_points": week.total_points,
    }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def single_basis(rows: Iterable[Mapping[str, object]]) -> str | None:
    """The one scoring basis a group of settled rows shares, or a refusal.

    Handed rows on two bases this raises instead of picking one, because the caller was
    about to combine them and the combination means nothing: a week completed by automatic
    substitutions and a week scored on the eleven that were named measure different
    things, and their sum is not a season score. Handed a settled row that states no basis
    it raises too, for the same reason in a weaker form: an unknown basis cannot be shown
    to match a known one.

    Handed nothing settled it returns ``None``, which reads as "there is nothing to
    combine". That is not zero, and a caller must not render it as one.
    """

    bases: set[str] = set()
    for row in rows:
        if _number(row.get("net")) is None:
            continue
        basis = row.get("scoring_basis")
        if basis is None:
            raise DataError(
                "A settled row states no scoring basis, so it cannot be shown to share "
                "one with the rows it would be totalled with."
            )
        bases.add(str(basis))
    if len(bases) > 1:
        raise DataError(
            f"Two scoring bases cannot enter one total: {sorted(bases)}. Weeks scored "
            "under different rules are different measurements; publish each with its "
            "basis named rather than summing across them."
        )
    return next(iter(bases), None)


def scoreboard_payload(
    *,
    season: str,
    league_id: int,
    bootstrap: bytes,
    captured_at_utc: str,
    source_snapshot_id: str,
    histories: Mapping[int, bytes],
    registered: Sequence[int],
    ledger_entries: Sequence[LedgerEntry],
    cohort: CohortCapture | None,
    cohort_picks: CohortPicks | None = None,
    published_ours: Mapping[int, Mapping[str, object]] | None = None,
    generated_at_utc: str,
    baseline_entries: Sequence[LedgerEntry] = (),
    human_baselines: Mapping[int, Mapping[str, Mapping[str, object]]] | None = None,
) -> dict[str, object]:
    """The scoreboard envelope, from bytes and ledger entries alone; pure, so testable.

    ``published_ours`` is our row per gameweek as already published, used only for a
    gameweek ``ledger_entries`` does not cover; the ledger entry wins where there is one.
    """

    events = _events(bootstrap)
    played = played_gameweeks(bootstrap, as_of_utc=captured_at_utc)
    weeks: dict[int, dict[int, EntryGameweekPoints]] = {
        entry_id: {
            week.gameweek: week for week in fpl_entry_history_points(payload, entry_id=entry_id)
        }
        for entry_id, payload in histories.items()
    }
    ledger = {entry.gameweek: entry for entry in ledger_entries}
    baseline = {entry.gameweek: entry for entry in baseline_entries}
    if cohort is not None:
        # A gameweek number repeats every season, so the week check below proves the two
        # captures are from the same week only once they are known to be from the same
        # season. Both seasons come from the captures' own published deadlines.
        cohort_season = season_from_bootstrap(cohort.bootstrap)
        if cohort_season != season:
            raise DataError(
                f"The cohort capture {cohort.snapshot_id} describes season {cohort_season}, "
                f"not {season}; its mean would sit in another season's row unmarked."
            )
    top100 = top100_week(cohort, cohort_picks) if cohort is not None else None
    if top100 is not None and top100["gameweek"] not in played:
        raise DataError(
            f"The cohort capture describes gameweek {top100['gameweek']}, which the live "
            f"capture {source_snapshot_id} had not played; the two captures are not from "
            "the same week."
        )

    rows: list[dict[str, object]] = []
    for gameweek in played:
        event = events.get(gameweek)
        if event is None:
            raise DataError(f"The bootstrap publishes no gameweek {gameweek}.")
        finished = event.get("finished") is True
        members = [
            _member_row(entry_id, weeks[entry_id][gameweek])
            for entry_id in sorted(weeks)
            if gameweek in weeks[entry_id]
        ]
        nets = [float(str(row["net"])) for row in members if row["net"] is not None]
        entry = ledger.get(gameweek)
        our_row: dict[str, object] | None = None
        if entry is not None:
            our_row = _ours(entry)
        elif published_ours is not None and gameweek in published_ours:
            our_row = dict(published_ours[gameweek])
        settled = finished and event.get("data_checked") is True
        comparisons: list[dict[str, object]] = [
            {
                "kind": kind,
                "net": None,
                "diagnostics": empty_diagnostics(),
                "scoring_basis": None,
                "source_snapshot_id": None,
            }
            for kind in COMPARISON_KINDS
        ]
        if our_row is not None:
            comparisons[0].update(
                net=our_row["net"] if settled else None,
                diagnostics=our_row.get("diagnostics", empty_diagnostics())
                if settled
                else empty_diagnostics(),
                scoring_basis=our_row.get("scoring_basis"),
                source_snapshot_id=our_row.get("outcome_snapshot_id"),
            )
        control = baseline.get(gameweek)
        if control is not None:
            if (
                entry is None
                or control.season != season
                or control.decision.get("snapshot_id") != entry.decision.get("snapshot_id")
                or not control.decision.get("snapshot_id")
                or not control.decision.get("deadline_utc")
                or control.decision.get("deadline_utc") != entry.decision.get("deadline_utc")
            ):
                raise DataError(
                    "Paired base decision must use the system's same season and capture."
                )
            if control.decision.get("model_version") != COMPONENT_MODEL_VERSION:
                raise DataError("The bare component row needs a frozen component-only decision.")
            base_row = _ours(control)
            comparisons[1].update(
                net=base_row["net"] if settled else None,
                diagnostics=base_row.get("diagnostics", empty_diagnostics())
                if settled
                else empty_diagnostics(),
                scoring_basis=base_row.get("scoring_basis"),
                source_snapshot_id=base_row.get("outcome_snapshot_id"),
            )
        if settled:
            for index, kind in ((2, "elite_xi"), (3, "ownership_template")):
                human = (human_baselines or {}).get(gameweek, {}).get(kind)
                if human is not None:
                    comparisons[index].update(
                        {
                            key: human[key]
                            for key in (
                                "net",
                                "diagnostics",
                                "scoring_basis",
                                "source_snapshot_id",
                                "outcome_snapshot_id",
                                "construction",
                            )
                        }
                    )
        for index, value, basis in (
            (4, _mean(nets), "net"),
            (5, _number(event.get("average_entry_score")), "source_average"),
        ):
            comparisons[index].update(
                net=value if settled else None,
                scoring_basis=basis,
                source_snapshot_id=source_snapshot_id,
            )
        rows.append(
            {
                "gameweek": gameweek,
                "deadline_utc": str(event.get("deadline_time", "")),
                "finished": finished,
                "data_checked": event.get("data_checked") is True,
                "average_entry_score": (
                    _number(event.get("average_entry_score")) if finished else None
                ),
                "highest_score": _number(event.get("highest_score")) if finished else None,
                "ours": our_row,
                "top100": top100 if top100 is not None and top100["gameweek"] == gameweek else None,
                "members": members,
                "members_mean_net": _mean(nets),
                "members_counted": len(nets),
                "comparisons": comparisons,
            }
        )

    # Each cumulative figure names the weeks it covers, because they are not the same
    # weeks: our net is summed over the finished weeks the ledger has settled, the field's
    # average is summed over the finished weeks that published one, and the members'
    # figure is their own running total at the last finished week — which spans every week
    # they have played through it, finished or not. Those coincide while the finished
    # weeks run without a gap, and a gap (a week left unfinished by a postponed fixture,
    # with later weeks finished) is exactly when they do not.
    #
    # Our running total is kept on one basis and one only. A week scored under a different
    # rule is still published, with its own basis named, and appears in
    # ``ours_excluded_gameweeks`` rather than being added in: the reader is told the week
    # exists and is told why it is not in the total. Summing across bases would produce a
    # number that looks like a season score and is not one, which is worse than no total.
    finished_rows = [row for row in rows if row["finished"]]
    finished_gameweeks = [int(str(row["gameweek"])) for row in finished_rows]
    settled_ours: dict[int, Mapping[str, object]] = {}
    averages: list[float] = []
    for row in finished_rows:
        ours = row["ours"]
        if isinstance(ours, dict) and ours["net"] is not None:
            settled_ours[int(str(row["gameweek"]))] = ours
        if row["average_entry_score"] is not None:
            averages.append(float(str(row["average_entry_score"])))
    on_basis = {
        week: ours
        for week, ours in settled_ours.items()
        if str(ours.get("scoring_basis")) == SERIES_SCORING_BASIS
    }
    ours_excluded = [
        {"gameweek": week, "scoring_basis": str(settled_ours[week].get("scoring_basis"))}
        for week in sorted(settled_ours)
        if week not in on_basis
    ]
    # The filter above already leaves one basis behind. This re-derives it from the rows
    # actually being summed, so that a later edit which widens or drops that filter meets
    # a refusal here instead of silently producing a mixed total.
    ours_basis = single_basis(on_basis.values())
    ours_nets = {week: float(str(ours["net"])) for week, ours in on_basis.items()}
    through = finished_gameweeks[-1] if finished_gameweeks else None
    totals = [
        float(weeks[entry_id][through].total_points)
        for entry_id in sorted(weeks)
        if through is not None and through in weeks[entry_id]
    ]
    cumulative: dict[str, object] = {
        "through_gameweek": through,
        "gameweeks": finished_gameweeks,
        "ours_net": sum(ours_nets.values()) if ours_nets else None,
        "ours_gameweeks": sorted(ours_nets),
        "ours_basis": ours_basis,
        "ours_excluded_gameweeks": ours_excluded,
        "members_mean_total_points": _mean(totals),
        "members_gameweeks": (
            [] if through is None else [week for week in played if week <= through]
        ),
        "members_counted": len(totals),
        "average_entry_score": (
            sum(averages) if averages and len(averages) == len(finished_rows) else None
        ),
    }
    return {
        "contract_version": LEAGUE_VIEW_CONTRACT_VERSION,
        "generated_at_utc": generated_at_utc,
        "source_kind": "live",
        "payload": {
            "season": season,
            "league_id": int(league_id),
            "source_snapshot_id": source_snapshot_id,
            "captured_at_utc": captured_at_utc,
            "cohort_snapshot_id": None if cohort is None else cohort.snapshot_id,
            "cohort_picks_snapshot_id": None if cohort_picks is None else cohort_picks.snapshot_id,
            "registered_members": len(registered),
            "histories_held": len(histories),
            "gameweeks": rows,
            "cumulative": cumulative,
        },
    }


def resolve_live_snapshot_id(root: Path, requested: str | None) -> str:
    """The capture to read: the one named, or the most recent live one held.

    Only the automatic pick is filtered. Several collectors share this root and an
    identifier begins with its source, so a lexical listing orders by collector before
    capture time; ``list_snapshot_ids`` takes the source as a filter rather than this
    module keeping a copy of the prefix. A capture an operator names outright is still
    looked for in everything held, so any capture on disk stays replayable and a
    misspelling still reports against what is really there.
    """

    if requested:
        if requested not in list_snapshot_ids(root):
            raise DataError(f"No snapshot {requested!r} under {root}.")
        return requested
    live = list_snapshot_ids(root, source=FPL_LIVE_SOURCE)
    if not live:
        raise DataError(f"No {FPL_LIVE_SOURCE}-* snapshots under {root}; capture one first.")
    return live[-1]


def read_cohort(root: Path, snapshot_id: str) -> CohortCapture:
    """A Top-100 capture's bootstrap and its Overall standings pages, in page order."""

    snapshot = read_snapshot(root, snapshot_id)
    payloads = snapshot.payloads
    if BOOTSTRAP_PAYLOAD not in payloads:
        raise DataError(f"Cohort capture {snapshot_id} carries no bootstrap.")
    numbered = sorted(
        (int(match.group(1)), name)
        for name in payloads
        if (match := _COHORT_PAGE.match(name)) is not None
    )
    if not numbered:
        raise DataError(f"Cohort capture {snapshot_id} holds no Overall standings pages.")
    return CohortCapture(
        snapshot_id=snapshot_id,
        captured_at_utc=snapshot.metadata.captured_at_utc,
        bootstrap=payloads[BOOTSTRAP_PAYLOAD],
        pages=tuple(payloads[name] for _, name in numbered),
    )


def read_cohort_picks(root: Path, snapshot_id: str) -> CohortPicks:
    """One elite-picks capture's net week per cohort member, from their own histories.

    Every picks document in the capture must describe the same gameweek and carry an
    ``entry_history`` with both ``points`` and ``event_transfers_cost``: a mean netted
    from some rows and not others would be neither gross nor net.
    """

    snapshot = read_snapshot(root, snapshot_id)
    net: dict[int, int] = {}
    hits: dict[int, int] = {}
    gameweeks: set[int] = set()
    for name, payload in snapshot.payloads.items():
        match = _COHORT_PICKS.match(name)
        if match is None:
            continue
        entry_id, gameweek = int(match.group(1)), int(match.group(2))
        document = json.loads(payload.decode("utf-8"))
        history = document.get("entry_history") if isinstance(document, dict) else None
        if not isinstance(history, Mapping):
            raise DataError(f"{name} in {snapshot_id} carries no entry_history block.")
        points, cost = history.get("points"), history.get("event_transfers_cost")
        if isinstance(points, bool) or not isinstance(points, int):
            raise DataError(f"{name} in {snapshot_id} has no integer entry_history.points.")
        if isinstance(cost, bool) or not isinstance(cost, int):
            raise DataError(
                f"{name} in {snapshot_id} has no integer entry_history.event_transfers_cost; "
                "without it the row is gross and the cohort's mean cannot be netted."
            )
        gameweeks.add(gameweek)
        net[entry_id] = points - cost
        hits[entry_id] = cost
    if not net:
        raise DataError(f"Picks capture {snapshot_id} holds no entry-<id>-picks-gwNN.json.")
    if len(gameweeks) != 1:
        raise DataError(
            f"Picks capture {snapshot_id} spans gameweeks {sorted(gameweeks)}; one capture "
            "describes one week."
        )
    return CohortPicks(snapshot_id=snapshot_id, gameweek=gameweeks.pop(), net=net, hits=hits)


@dataclass(frozen=True, slots=True)
class ScoreboardPublicationRequest:
    snapshot_root: Path
    snapshot_id: str
    registry_path: Path
    ledger_root: Path
    out_dir: Path
    league_id: int
    season: str | None = None
    cohort_snapshot_id: str | None = None
    elite_snapshot_id: str | None = None
    now_utc: str | None = None
    baseline_ledger_root: Path | None = None
    evidence_root: Path | None = None


@dataclass(frozen=True, slots=True)
class ScoreboardPublicationResult:
    snapshot_id: str
    season: str
    target: Path
    document: Mapping[str, Any]
    histories_held: int
    registered_members: int
    ours_kept_from_published: tuple[int, ...] = ()
    """Gameweeks whose ``ours`` row came from the scoreboard already at ``target`` because
    the ledger root held no entry of the season."""

    @property
    def output_paths(self) -> tuple[Path, ...]:
        return (self.target,)


def publish_scoreboard(request: ScoreboardPublicationRequest) -> ScoreboardPublicationResult:
    """Write the existing scoreboard from explicitly named captured inputs."""

    snapshot_id = request.snapshot_id
    snapshot = read_snapshot(request.snapshot_root, snapshot_id)
    if BOOTSTRAP_PAYLOAD not in snapshot.payloads:
        raise DataError(f"Capture {snapshot_id} carries no bootstrap.")
    season = request.season or infer_season(snapshot)
    registry = EntryRegistry.load(request.registry_path)
    if not registry.entries:
        raise DataError(
            f"No registered entries in {request.registry_path}; seed it first with "
            "`python -m scripts.seed_entry_registry --league <id>`."
        )
    registered = registry.ids()
    histories = {
        entry_id: snapshot.payloads[name]
        for entry_id in registered
        if (name := f"entry-{entry_id}-history.json") in snapshot.payloads
    }
    ledger = load_ledger(request.ledger_root, season)
    controls = (
        load_ledger(request.baseline_ledger_root, season)
        if request.baseline_ledger_root is not None
        else ()
    )
    snapshot_ids = list_snapshot_ids(request.snapshot_root, source=FPL_LIVE_SOURCE)
    settled_entries = settled_scoreboard_entries(
        (*ledger, *controls),
        (
            snapshot if name == snapshot_id else read_snapshot(request.snapshot_root, name)
            for name in snapshot_ids
        ),
        season=season,
        as_of_utc=snapshot.metadata.captured_at_utc,
    )
    entries, baseline_entries = settled_entries[: len(ledger)], settled_entries[len(ledger) :]
    # Retain only decision and selected outcome captures, not the entire archive.
    needed_ids = {
        str(identifier)
        for entry in entries
        for identifier in (
            entry.decision.get("snapshot_id"),
            (entry.outcome or {}).get("source_snapshot_id"),
        )
        if identifier
    }
    baseline_snapshots = tuple(
        snapshot if name == snapshot_id else read_snapshot(request.snapshot_root, name)
        for name in sorted(needed_ids & set(snapshot_ids))
    )
    human_baselines = human_baseline_rows(
        entries,
        baseline_snapshots,
        evidence_root=request.evidence_root,
        as_of_utc=snapshot.metadata.captured_at_utc,
    )
    target = Path(request.out_dir) / "data" / "league" / SCOREBOARD_FILE
    # An empty ledger root beside a scoreboard that already publishes our rows: the
    # decisions were made, their local record is what is missing. Keep the rows.
    published_ours = _published_ours(target, season) if not entries else {}
    cohort = (
        read_cohort(request.snapshot_root, request.cohort_snapshot_id)
        if request.cohort_snapshot_id
        else None
    )
    cohort_picks = (
        read_cohort_picks(request.snapshot_root, request.elite_snapshot_id)
        if request.elite_snapshot_id
        else None
    )
    document = scoreboard_payload(
        season=season,
        league_id=request.league_id,
        bootstrap=snapshot.payloads[BOOTSTRAP_PAYLOAD],
        captured_at_utc=snapshot.metadata.captured_at_utc,
        source_snapshot_id=snapshot_id,
        histories=histories,
        registered=registered,
        ledger_entries=entries,
        baseline_entries=baseline_entries,
        human_baselines=human_baselines,
        cohort=cohort,
        cohort_picks=cohort_picks,
        published_ours=published_ours or None,
        generated_at_utc=request.now_utc
        or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    payload = document["payload"]
    published_rows: list[object] = payload["gameweeks"] if isinstance(payload, dict) else []
    kept = tuple(
        int(str(row["gameweek"]))
        for row in published_rows
        if isinstance(row, dict)
        and row.get("ours") is not None
        and int(str(row["gameweek"])) in published_ours
    )
    if kept:
        print(
            f"Ledger root {request.ledger_root} holds no {season} entry; kept our published "
            f"scoreboard rows for gameweeks {list(kept)} rather than publishing none."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # LF on every platform: the preview is what a publish commits, byte for byte, and a
    # platform newline here would be the one file git normalised on the way in.
    target.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ScoreboardPublicationResult(
        snapshot_id,
        season,
        target,
        document,
        len(histories),
        len(registered),
        kept,
    )
