"""Deadline-safe player evidence for the probabilistic-model handoff.

The builder accepts only already captured bytes. It freezes cohort membership from one
explicit snapshot, reads elite picks at a one-gameweek lag, and chooses market evidence
only from captures strictly before the target deadline. Missing evidence stays missing;
it is never recoded as a negative observation.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

import pandas as pd

from squadopt.data.cohorts import ranked_entries_from_pages, require_pre_deadline_capture
from squadopt.data.errors import DataSourceError, DuplicateRecordsError, InvalidValueError
from squadopt.data.snapshots import (
    CapturedSnapshot,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    entry_history_payload,
    entry_picks_payload,
    fpl_entry_picks,
    fpl_league_standings_page,
    gameweek_deadlines,
    league_standings_page_payload,
    player_codes,
    player_evidence_snapshot,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp

PLAYER_EVIDENCE_CONTRACT_VERSION: Final = "player_evidence_v1"
OVERALL_LEAGUE_ID: Final = 314
ELITE_COHORT_SIZE: Final = 200
LOCKED_HOLDOUT_SEASON: Final = "2025-26"

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


def build_player_evidence_table(
    *,
    target_gameweek: int,
    deadline_timestamp_utc: str,
    snapshots: Sequence[CapturedSnapshot],
    cohort_snapshot: CapturedSnapshot,
) -> pd.DataFrame:
    """Build one deterministic player-by-decision-week evidence table.

    The target season is derived from the deadline before any snapshot is inspected, so
    the locked 2025-26 holdout cannot even be listed or hashed through this interface.
    """

    week = _positive_week(target_gameweek)
    if week == 1:
        raise InvalidValueError("target_gameweek must be at least 2 for lag-one evidence.")
    deadline = normalize_utc_timestamp(deadline_timestamp_utc, label="deadline_timestamp_utc")
    season = _season_for_deadline(deadline)
    if season == LOCKED_HOLDOUT_SEASON:
        raise DataSourceError(f"Season {season} is a locked holdout and cannot be inspected.")

    ordered_snapshots = (cohort_snapshot, *snapshots)
    identifiers = [_validate_snapshot(snapshot) for snapshot in ordered_snapshots]
    if len(set(identifiers)) != len(identifiers):
        raise DuplicateRecordsError("The same snapshot was supplied more than once.")

    cohort_id = cohort_snapshot.metadata.snapshot_id
    require_pre_deadline_capture(
        captured_at_utc=cohort_snapshot.metadata.captured_at_utc,
        deadline_timestamp_utc=deadline,
    )
    cohort_members = _cohort_members(cohort_snapshot)

    eligible = tuple(
        snapshot
        for snapshot in ordered_snapshots
        if as_instant(snapshot.metadata.captured_at_utc) < as_instant(deadline)
    )
    market_candidates = tuple(
        snapshot for snapshot in eligible if BOOTSTRAP_PAYLOAD in snapshot.payloads
    )
    if not market_candidates:
        raise DataSourceError("No verified pre-deadline bootstrap capture is available.")
    market_snapshot = max(market_candidates, key=_capture_order)
    market = player_evidence_snapshot(market_snapshot.payloads[BOOTSTRAP_PAYLOAD]).copy(deep=True)

    squad_counts: Counter[int] = Counter()
    start_counts: Counter[int] = Counter()
    captain_counts: Counter[int] = Counter()
    picks_snapshot_ids: set[str] = set()
    observed_members = 0
    lag_week = week - 1
    newest_first = sorted(eligible, key=_capture_order, reverse=True)
    for entry_id in cohort_members:
        source = _latest_eligible_picks_snapshot(newest_first, entry_id, lag_week)
        if source is None:
            continue
        bootstrap = source.payloads[BOOTSTRAP_PAYLOAD]
        mapping = player_codes(bootstrap)
        record = fpl_entry_picks(
            source.payloads[entry_picks_payload(entry_id, lag_week)],
            source.payloads[entry_history_payload(entry_id)],
            entry_id=entry_id,
            season=season,
            gameweek=lag_week,
            source_snapshot_id=source.metadata.snapshot_id,
        )
        squad = _translate_elements(record.squad, mapping, source.metadata.snapshot_id)
        starting = _translate_elements(record.starting_xi, mapping, source.metadata.snapshot_id)
        captain = _translate_elements((record.captain,), mapping, source.metadata.snapshot_id)[0]
        squad_counts.update(squad)
        start_counts.update(starting)
        captain_counts[captain] += 1
        observed_members += 1
        picks_snapshot_ids.add(source.metadata.snapshot_id)

    player_ids = sorted(
        set(market["player_id"].astype(int))
        | set(squad_counts)
        | set(start_counts)
        | set(captain_counts)
    )
    frame = pd.DataFrame({"player_id": pd.Series(player_ids, dtype="int64")})
    frame = frame.merge(market, on="player_id", how="left", validate="one_to_one")
    frame["elite_squad_count_lag1"] = frame["player_id"].map(squad_counts).fillna(0)
    frame["elite_start_count_lag1"] = frame["player_id"].map(start_counts).fillna(0)
    frame["elite_captain_count_lag1"] = frame["player_id"].map(captain_counts).fillna(0)
    for column in (
        "elite_squad_count_lag1",
        "elite_start_count_lag1",
        "elite_captain_count_lag1",
    ):
        frame[column] = frame[column].astype("int64")
        share = column.replace("count", "share")
        frame[share] = (
            frame[column].astype("Float64") / observed_members
            if observed_members
            else pd.Series(pd.NA, index=frame.index, dtype="Float64")
        )

    frame["net_transfers_event"] = (
        frame["transfers_in_event"] - frame["transfers_out_event"]
    ).astype("Int64")
    frame["elite_evidence_observed"] = pd.Series(
        observed_members > 0, index=frame.index, dtype="boolean"
    )
    frame["ownership_evidence_observed"] = (
        frame["overall_selected_by_percent"].notna().astype("boolean")
    )
    frame["transfer_evidence_observed"] = (
        frame["transfers_in_event"].notna() & frame["transfers_out_event"].notna()
    ).astype("boolean")
    frame["availability_evidence_observed"] = (
        frame[
            [
                "availability_status",
                "chance_of_playing_next_round",
                "official_news_present",
            ]
        ]
        .notna()
        .any(axis="columns")
        .astype("boolean")
    )

    used_ids = tuple(sorted({cohort_id, market_snapshot.metadata.snapshot_id, *picks_snapshot_ids}))
    used_by_id = {snapshot.metadata.snapshot_id: snapshot for snapshot in ordered_snapshots}
    captured_at = max(
        (used_by_id[snapshot_id].metadata.captured_at_utc for snapshot_id in used_ids),
        key=as_instant,
    )
    frame["contract_version"] = PLAYER_EVIDENCE_CONTRACT_VERSION
    frame["season"] = season
    frame["target_gameweek"] = week
    frame["captured_at_utc"] = captured_at
    frame["deadline_timestamp_utc"] = deadline
    frame["source_snapshot_ids"] = ",".join(used_ids)
    frame["timing_verified"] = True
    frame["elite_cohort_size"] = ELITE_COHORT_SIZE
    frame["elite_members_observed"] = observed_members
    _cast_output_dtypes(frame)
    if frame["player_id"].duplicated().any():
        raise DuplicateRecordsError("The evidence table contains duplicate player identities.")
    result = frame.loc[:, list(EVIDENCE_COLUMNS)]
    return result.sort_values("player_id", kind="stable").reset_index(drop=True)


def _positive_week(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidValueError(f"target_gameweek must be a positive integer, got {value!r}.")
    return value


def _season_for_deadline(deadline: str) -> str:
    instant = as_instant(deadline)
    start = instant.year if instant.month >= 7 else instant.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _validate_snapshot(snapshot: CapturedSnapshot) -> str:
    if not isinstance(snapshot, CapturedSnapshot):
        raise DataSourceError("Every evidence input must be a CapturedSnapshot.")
    metadata = snapshot.metadata
    text_fields = {
        "snapshot_id": metadata.snapshot_id,
        "source": metadata.source,
        "schema_version": metadata.schema_version,
        "fingerprint": metadata.fingerprint,
    }
    missing = [name for name, value in text_fields.items() if not value or not value.strip()]
    if missing:
        raise DataSourceError(f"Snapshot provenance is incomplete: {', '.join(missing)}.")
    captured = normalize_utc_timestamp(metadata.captured_at_utc, label="captured_at_utc")
    if set(snapshot.payloads) != set(metadata.checksums):
        raise DataSourceError("Snapshot payload names do not match its recorded checksums.")
    checksums = {name: payload_checksum(content) for name, content in snapshot.payloads.items()}
    if checksums != dict(metadata.checksums):
        raise DataSourceError("Snapshot payload bytes do not match their recorded checksums.")
    fingerprint = snapshot_fingerprint(
        source=metadata.source,
        captured_at_utc=captured,
        schema_version=metadata.schema_version,
        checksums=checksums,
    )
    if fingerprint != metadata.fingerprint:
        raise DataSourceError("Snapshot fingerprint does not match its provenance.")
    expected_id = build_snapshot_id(
        source=metadata.source, captured_at_utc=captured, fingerprint=fingerprint
    )
    if expected_id != metadata.snapshot_id:
        raise DataSourceError("Snapshot identifier does not match its provenance.")
    return metadata.snapshot_id


def _cohort_members(snapshot: CapturedSnapshot) -> tuple[int, ...]:
    pages = []
    for page in range(1, 5):
        name = league_standings_page_payload(OVERALL_LEAGUE_ID, page)
        if name not in snapshot.payloads:
            raise DataSourceError(f"Cohort snapshot is missing {name}.")
        pages.append(
            fpl_league_standings_page(
                snapshot.payloads[name],
                league_id=OVERALL_LEAGUE_ID,
                expected_page=page,
            )
        )
    return ranked_entries_from_pages(pages, expected_ranks=ELITE_COHORT_SIZE)


def _capture_order(snapshot: CapturedSnapshot) -> tuple[object, str]:
    return (as_instant(snapshot.metadata.captured_at_utc), snapshot.metadata.snapshot_id)


def _latest_eligible_picks_snapshot(
    snapshots: Sequence[CapturedSnapshot], entry_id: int, lag_week: int
) -> CapturedSnapshot | None:
    required = {
        BOOTSTRAP_PAYLOAD,
        entry_picks_payload(entry_id, lag_week),
        entry_history_payload(entry_id),
    }
    for snapshot in snapshots:
        if not required <= set(snapshot.payloads):
            continue
        deadlines = {
            item.gameweek: item for item in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD])
        }
        lag_deadline = deadlines.get(lag_week)
        if lag_deadline is None:
            raise DataSourceError(
                f"Picks snapshot does not publish gameweek {lag_week}'s deadline."
            )
        if as_instant(snapshot.metadata.captured_at_utc) < as_instant(lag_deadline.deadline_utc):
            continue
        return snapshot
    return None


def _translate_elements(
    elements: Sequence[int], mapping: Mapping[int, int], snapshot_id: str
) -> tuple[int, ...]:
    unknown = [element for element in elements if element not in mapping]
    if unknown:
        raise DataSourceError(
            f"Snapshot {snapshot_id} cannot translate seasonal elements {unknown[:5]!r}."
        )
    return tuple(mapping[element] for element in elements)


def _cast_output_dtypes(frame: pd.DataFrame) -> None:
    for column in (
        "contract_version",
        "season",
        "captured_at_utc",
        "deadline_timestamp_utc",
        "source_snapshot_ids",
    ):
        frame[column] = frame[column].astype("string")
    for column in (
        "target_gameweek",
        "player_id",
        "elite_cohort_size",
        "elite_members_observed",
        "elite_squad_count_lag1",
        "elite_start_count_lag1",
        "elite_captain_count_lag1",
    ):
        frame[column] = frame[column].astype("int64")
    for column in (
        "timing_verified",
        "elite_evidence_observed",
        "ownership_evidence_observed",
        "transfer_evidence_observed",
        "availability_evidence_observed",
    ):
        frame[column] = frame[column].astype("boolean")
