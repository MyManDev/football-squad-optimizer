"""The deadline-safe player evidence table Phase C reads.

One row is one player for one decision week. Every column is something that was knowable
*before* the target gameweek's deadline, and every column that could be missing says so in
its own flag rather than arriving as a zero.

Three rules shape the whole module.

**Timing.** ``captured_at_utc < deadline_timestamp_utc`` or the capture is not pre-deadline
evidence. This is checked, not assumed, and a capture that fails it is not used.

**The lag rule.** Gameweek N's picks become public only after gameweek N's deadline, so they
can never inform a gameweek N feature. Elite squad evidence for gameweek N comes from
gameweek **N-1** picks. That is why the table refuses a target gameweek below 2: there is no
N-1 to read.

**Missing is not zero.** A share carries its denominator. ``elite_squad_share_lag1`` is
``elite_squad_count_lag1 / elite_members_observed``, and when no member's picks could be read
the share is missing rather than 0.0 -- an unobserved member is not a member who left the
player out. The two say opposite things about the same player and a model cannot tell them
apart afterwards.

Nothing here trains, promotes, or publishes a probability. It builds a table.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import pandas as pd

from squadopt.data.cohorts import RankedCohort, nested_cohorts, ranked_entries_from_pages
from squadopt.data.errors import DataSourceError, InvalidValueError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    entry_picks_payload,
    entry_squad_from_picks,
    fpl_league_standings_page,
    league_standings_page_payload,
    player_codes,
)
from squadopt.data.timestamps import as_instant

CONTRACT_VERSION: Final = "player_evidence_v1"

# The official Overall league. Declared here rather than imported from the capture script,
# which is a command rather than a library.
OVERALL_LEAGUE_ID: Final = 314

# Declared locally on purpose. The constant also lives in ``backtest.learned``, which sits
# *above* this layer, so importing it would invert the dependency the layer contract
# enforces. The value is a project fact, not this module's opinion.
LOCKED_HOLDOUT_SEASON: Final = "2025-26"

# The smallest target gameweek the lag rule permits: gameweek 1 has no N-1 picks.
MIN_TARGET_GAMEWEEK: Final = 2

EVIDENCE_COLUMNS: Final = (
    "contract_version",
    "season",
    "target_gameweek",
    "player_id",
    "captured_at_utc",
    "deadline_timestamp_utc",
    "source_snapshot_ids",
    "timing_verified",
    "elite_cohort_size",
    "elite_members_observed",
    "elite_squad_count_lag1",
    "elite_squad_share_lag1",
    "elite_start_count_lag1",
    "elite_start_share_lag1",
    "elite_captain_count_lag1",
    "elite_captain_share_lag1",
    "overall_selected_by_percent",
    "transfers_in_event",
    "transfers_out_event",
    "net_transfers_event",
    "availability_status",
    "chance_of_playing_next_round",
    "official_news_present",
    "elite_evidence_observed",
    "ownership_evidence_observed",
    "transfer_evidence_observed",
    "availability_evidence_observed",
)

_ELEMENT_EVIDENCE_FIELDS: Final = (
    "code",
    "id",
    "selected_by_percent",
    "transfers_in_event",
    "transfers_out_event",
    "status",
    "chance_of_playing_next_round",
    "news",
)


@dataclass(frozen=True, slots=True)
class _EliteCounts:
    """How many observed cohort members held, started and captained each player."""

    members_observed: int
    squad: Mapping[int, int]
    started: Mapping[int, int]
    captained: Mapping[int, int]
    members_missing_picks: tuple[int, ...]
    unmapped_elements: tuple[int, ...]


def _pre_deadline(
    snapshots: Sequence[CapturedSnapshot], *, deadline_timestamp_utc: str
) -> list[CapturedSnapshot]:
    """The captures that were taken strictly before the deadline, newest last."""

    deadline = as_instant(deadline_timestamp_utc)
    eligible = [
        snapshot
        for snapshot in snapshots
        if as_instant(snapshot.metadata.captured_at_utc) < deadline
    ]
    return sorted(eligible, key=lambda snapshot: as_instant(snapshot.metadata.captured_at_utc))


def _ownership_source(
    snapshots: Sequence[CapturedSnapshot], *, deadline_timestamp_utc: str
) -> CapturedSnapshot:
    """The newest pre-deadline capture carrying a bootstrap.

    Newest, because ownership and transfer counts move continuously and the closest legal
    reading is the most informative one. Newest *among the legal ones* -- the filter runs
    first, so a later capture can never be preferred into the table.
    """

    carrying = [
        snapshot
        for snapshot in _pre_deadline(snapshots, deadline_timestamp_utc=deadline_timestamp_utc)
        if BOOTSTRAP_PAYLOAD in snapshot.payloads
    ]
    if not carrying:
        raise DataSourceError(
            "No pre-deadline capture carries a bootstrap payload, so there is no legal "
            f"source for ownership evidence before {deadline_timestamp_utc}. Evidence is "
            "refused rather than assembled from a post-deadline read."
        )
    return carrying[-1]


def _cohort(
    cohort_snapshot: CapturedSnapshot,
    *,
    target_gameweek: int,
    deadline_timestamp_utc: str,
    cohort_size: int,
) -> RankedCohort:
    """Read the frozen cohort out of its own capture.

    ``RankedCohort`` refuses a capture at or after the deadline, so a cohort that saw the
    answer cannot be built at all.
    """

    pages = []
    page_number = 1
    while True:
        name = league_standings_page_payload(OVERALL_LEAGUE_ID, page_number)
        if name not in cohort_snapshot.payloads:
            break
        pages.append(
            fpl_league_standings_page(
                cohort_snapshot.payloads[name],
                league_id=OVERALL_LEAGUE_ID,
                expected_page=page_number,
            )
        )
        page_number += 1
    if not pages:
        raise DataSourceError(
            "The cohort snapshot carries no Overall standings pages, so cohort membership "
            "cannot be established."
        )
    ordered = ranked_entries_from_pages(pages, expected_ranks=cohort_size)
    return nested_cohorts(
        ordered,
        target_gameweek=target_gameweek,
        captured_at_utc=cohort_snapshot.metadata.captured_at_utc,
        deadline_timestamp_utc=deadline_timestamp_utc,
        source_snapshot_id=cohort_snapshot.metadata.snapshot_id,
        sizes=[cohort_size],
    )[cohort_size]


def _elite_counts(
    cohort: RankedCohort,
    snapshots: Sequence[CapturedSnapshot],
    *,
    lag_gameweek: int,
    element_to_code: Mapping[int, int],
    deadline_timestamp_utc: str,
) -> _EliteCounts:
    """Count cohort holdings from gameweek ``lag_gameweek`` picks only.

    A member whose picks are not in any legal capture is *not observed* -- it lowers the
    denominator and is listed, rather than counting as a member who left every player out.
    """

    legal = _pre_deadline(snapshots, deadline_timestamp_utc=deadline_timestamp_utc)
    squad: dict[int, int] = {}
    started: dict[int, int] = {}
    captained: dict[int, int] = {}
    missing: list[int] = []
    unmapped: set[int] = set()
    observed = 0

    for entry_id in cohort.entry_ids:
        name = entry_picks_payload(entry_id, lag_gameweek)
        payload = next(
            (snapshot.payloads[name] for snapshot in reversed(legal) if name in snapshot.payloads),
            None,
        )
        if payload is None:
            missing.append(entry_id)
            continue
        named = entry_squad_from_picks(payload, entry_id=entry_id, gameweek=lag_gameweek)
        observed += 1
        for element in named.squad:
            code = element_to_code.get(element)
            if code is None:
                unmapped.add(element)
                continue
            squad[code] = squad.get(code, 0) + 1
        for element in named.starting_xi:
            code = element_to_code.get(element)
            if code is not None:
                started[code] = started.get(code, 0) + 1
        captain_code = element_to_code.get(named.captain)
        if captain_code is not None:
            captained[captain_code] = captained.get(captain_code, 0) + 1

    return _EliteCounts(
        members_observed=observed,
        squad=squad,
        started=started,
        captained=captained,
        members_missing_picks=tuple(missing),
        unmapped_elements=tuple(sorted(unmapped)),
    )


def _whole_number(raw: object) -> int | None:
    """An integer the source published as one, or ``None``.

    ``bool`` is excluded deliberately: it is an ``int`` subclass, and a flag arriving in a
    count column is the kind of type confusion the data contract already forbids elsewhere.
    """

    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _share(count: int, observed: int) -> float:
    """A share with its denominator visible; missing when nothing was observed."""

    if observed <= 0:
        return math.nan
    return count / observed


def _selected_by_percent(raw: object) -> float:
    """The platform publishes this as a string. An unparseable value is missing, not zero."""

    if isinstance(raw, bool) or raw is None:
        return math.nan
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return math.nan
    return math.nan


def build_player_evidence_table(
    *,
    season: str,
    target_gameweek: int,
    deadline_timestamp_utc: str,
    snapshots: Sequence[CapturedSnapshot],
    cohort_snapshot: CapturedSnapshot,
    cohort_size: int = 100,
) -> pd.DataFrame:
    """Build the deadline-safe evidence table for one decision week.

    ``season`` is required and not derived. The captured payloads do not publish a season
    label, and inferring one needs a model of the calendar that lives above this layer;
    guessing it would mislabel every row in the table.

    Diagnostics that do not belong in a column ride on ``DataFrame.attrs``: which cohort
    members had no readable picks, and which picked elements the bootstrap could not map to a
    persistent code. Neither is silently dropped.
    """

    if season == LOCKED_HOLDOUT_SEASON:
        raise DataSourceError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout; evidence for it is not built, "
            "listed or fingerprinted."
        )
    if not season.strip():
        raise InvalidValueError("season must be non-empty.")
    if target_gameweek < MIN_TARGET_GAMEWEEK:
        raise InvalidValueError(
            f"Evidence needs gameweek {target_gameweek - 1} picks for a gameweek "
            f"{target_gameweek} decision, so the target must be at least "
            f"{MIN_TARGET_GAMEWEEK}."
        )
    deadline = as_instant(deadline_timestamp_utc)
    if not snapshots:
        raise DataSourceError("At least one capture is required to build evidence.")

    ownership = _ownership_source(snapshots, deadline_timestamp_utc=deadline_timestamp_utc)
    bootstrap = ownership.payloads[BOOTSTRAP_PAYLOAD]
    element_to_code = player_codes(bootstrap)
    cohort = _cohort(
        cohort_snapshot,
        target_gameweek=target_gameweek,
        deadline_timestamp_utc=deadline_timestamp_utc,
        cohort_size=cohort_size,
    )
    counts = _elite_counts(
        cohort,
        snapshots,
        lag_gameweek=target_gameweek - 1,
        element_to_code=element_to_code,
        deadline_timestamp_utc=deadline_timestamp_utc,
    )

    document = ownership.payloads[BOOTSTRAP_PAYLOAD]
    elements = _bootstrap_elements(document)
    snapshot_ids = ";".join(
        sorted(
            {
                *(
                    snapshot.metadata.snapshot_id
                    for snapshot in _pre_deadline(
                        snapshots, deadline_timestamp_utc=deadline_timestamp_utc
                    )
                ),
                cohort_snapshot.metadata.snapshot_id,
            }
        )
    )
    observed_elite = counts.members_observed > 0

    rows: list[dict[str, object]] = []
    for element in elements:
        code = element_to_code.get(_whole_number(element.get("id")) or -1)
        if code is None:
            continue
        squad_count = counts.squad.get(code, 0)
        start_count = counts.started.get(code, 0)
        captain_count = counts.captained.get(code, 0)
        selected = _selected_by_percent(element.get("selected_by_percent"))
        transfers_in = _whole_number(element.get("transfers_in_event"))
        transfers_out = _whole_number(element.get("transfers_out_event"))
        has_transfers = transfers_in is not None and transfers_out is not None
        status = element.get("status")
        chance = element.get("chance_of_playing_next_round")
        news = element.get("news")
        rows.append(
            {
                "contract_version": CONTRACT_VERSION,
                "season": season,
                "target_gameweek": target_gameweek,
                "player_id": code,
                "captured_at_utc": ownership.metadata.captured_at_utc,
                "deadline_timestamp_utc": deadline_timestamp_utc,
                "source_snapshot_ids": snapshot_ids,
                "timing_verified": True,
                "elite_cohort_size": cohort.size,
                "elite_members_observed": counts.members_observed,
                "elite_squad_count_lag1": squad_count if observed_elite else pd.NA,
                "elite_squad_share_lag1": _share(squad_count, counts.members_observed),
                "elite_start_count_lag1": start_count if observed_elite else pd.NA,
                "elite_start_share_lag1": _share(start_count, counts.members_observed),
                "elite_captain_count_lag1": captain_count if observed_elite else pd.NA,
                "elite_captain_share_lag1": _share(captain_count, counts.members_observed),
                "overall_selected_by_percent": selected,
                "transfers_in_event": transfers_in if has_transfers else pd.NA,
                "transfers_out_event": transfers_out if has_transfers else pd.NA,
                "net_transfers_event": (
                    transfers_in - transfers_out
                    if transfers_in is not None and transfers_out is not None
                    else pd.NA
                ),
                "availability_status": status if isinstance(status, str) and status else pd.NA,
                "chance_of_playing_next_round": (
                    chance if _whole_number(chance) is not None else pd.NA
                ),
                "official_news_present": bool(news) if isinstance(news, str) else pd.NA,
                "elite_evidence_observed": observed_elite,
                "ownership_evidence_observed": not math.isnan(selected),
                "transfer_evidence_observed": has_transfers,
                "availability_evidence_observed": isinstance(status, str) and bool(status),
            }
        )

    table = pd.DataFrame(rows, columns=list(EVIDENCE_COLUMNS))
    table = table.sort_values("player_id", kind="stable").reset_index(drop=True)
    table.attrs["cohort_snapshot_id"] = cohort_snapshot.metadata.snapshot_id
    table.attrs["ownership_snapshot_id"] = ownership.metadata.snapshot_id
    table.attrs["elite_members_missing_picks"] = len(counts.members_missing_picks)
    table.attrs["unmapped_picked_elements"] = counts.unmapped_elements
    table.attrs["deadline_timestamp_utc"] = deadline_timestamp_utc
    table.attrs["hours_pre_deadline"] = round(
        (deadline - as_instant(ownership.metadata.captured_at_utc)).total_seconds() / 3600.0, 3
    )
    return table


def _bootstrap_elements(bootstrap: bytes) -> tuple[Mapping[str, object], ...]:
    """The bootstrap's element records, with every field this module reads present."""

    import json

    parsed = json.loads(bootstrap.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise DataSourceError("Bootstrap payload must be a JSON object.")
    raw = parsed.get("elements")
    if not isinstance(raw, list) or not raw:
        raise DataSourceError("Bootstrap payload must carry a non-empty 'elements' array.")
    records = tuple(record for record in raw if isinstance(record, dict))
    missing = sorted(
        {field for record in records for field in _ELEMENT_EVIDENCE_FIELDS if field not in record}
    )
    if missing:
        raise DataSourceError(
            f"Bootstrap elements are missing fields {missing!r} that the evidence table "
            "reads. The source is undocumented and may have renamed them; the builder has "
            "to be updated rather than allowed to emit a column of nulls."
        )
    return records
