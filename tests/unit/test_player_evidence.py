"""Leakage and missingness tests for the deadline-safe player evidence table.

Every fixture is synthetic. Entry ids come from a reserved 900001+ block that matches no
real entry, player codes from 700001+, and the club and manager names are placeholders
labelled as such — a committed test that carried a real name or a real entry id would leak
exactly what the capture keeps out of git.

The tests are grouped by what they protect: the timing rule, the lag rule, identity,
missingness, privacy and determinism. Several are written so that loosening the rule they
guard makes them fail; a leakage test that passes under the leak is decoration.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import pytest

from squadopt.data.errors import DataSourceError, InvalidValueError
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata, payload_checksum
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    entry_picks_payload,
    league_standings_page_payload,
)
from squadopt.features.evidence import (
    CONTRACT_VERSION,
    EVIDENCE_COLUMNS,
    LOCKED_HOLDOUT_SEASON,
    build_player_evidence_table,
)

SEASON = "2026-27"
TARGET = 3
DEADLINE = "2026-09-04T17:30:00Z"
BEFORE = "2026-09-01T16:37:12Z"
AFTER = "2026-09-04T18:00:00Z"

FIRST_ENTRY = 900_001
FIRST_CODE = 700_001
# A synthetic standings page carries a full fifty, because the page reader checks that a
# capture is *whole* -- pages 1..k covering ranks 1..50k -- and that check is separate from
# how many of those ranks a cohort is cut to. COHORT is the cut.
PAGE_MEMBERS = 50
COHORT = 4


def _element(index: int, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        # element id i maps to persistent code FIRST_CODE + i - 1, so element 1 is
        # FIRST_CODE and a code/id mix-up cannot pass unnoticed.
        "code": FIRST_CODE + index - 1,
        "id": index,
        "first_name": "Placeholder",
        "second_name": f"Player {index}",
        "team": 1,
        "element_type": 1 + (index % 4),
        "now_cost": 50,
        "selected_by_percent": "12.5",
        "transfers_in_event": 1_000 + index,
        "transfers_out_event": 400 + index,
        "status": "a",
        "chance_of_playing_next_round": 100,
        "news": "",
    }
    record.update(overrides)
    return record


def _bootstrap(elements: list[dict[str, Any]] | None = None) -> bytes:
    document = {
        "teams": [{"id": 1, "code": 1, "name": "Placeholder FC", "short_name": "PLA"}],
        "elements": elements if elements is not None else [_element(i) for i in range(1, 21)],
        "events": [
            {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": True},
            {"id": 3, "deadline_time": DEADLINE, "finished": False},
        ],
    }
    return json.dumps(document).encode("utf-8")


def _standings_page(count: int = PAGE_MEMBERS) -> bytes:
    document = {
        "league": {"id": 314, "name": "Overall"},
        "last_updated_data": "2026-09-01T03:30:00Z",
        "standings": {
            "has_next": False,
            "page": 1,
            "results": [
                {
                    "entry": FIRST_ENTRY + rank,
                    "entry_name": f"Placeholder Squad {rank}",
                    "player_name": f"Placeholder Manager {rank}",
                    "rank": rank,
                    "rank_sort": rank,
                }
                for rank in range(1, count + 1)
            ],
        },
    }
    return json.dumps(document).encode("utf-8")


def _picks(*, elements: Sequence[int], captain: int, vice: int) -> bytes:
    document = {
        "picks": [
            {
                "element": element,
                "position": position,
                "is_captain": element == captain,
                "is_vice_captain": element == vice,
                "multiplier": 2 if element == captain else (1 if position <= 11 else 0),
            }
            for position, element in enumerate(elements, start=1)
        ],
        "active_chip": None,
        "entry_history": {"bank": 0, "event_transfers": 0, "event_transfers_cost": 0},
    }
    return json.dumps(document).encode("utf-8")


def _snapshot(source: str, captured_at: str, payloads: Mapping[str, bytes]) -> CapturedSnapshot:
    checksums = {name: payload_checksum(content) for name, content in payloads.items()}
    return CapturedSnapshot(
        metadata=SnapshotMetadata(
            snapshot_id=f"{source}-{captured_at.replace('-', '').replace(':', '')}-0000",
            source=source,
            captured_at_utc=captured_at,
            schema_version="1",
            checksums=checksums,
            fingerprint="f" * 64,
        ),
        payloads=payloads,
    )


def _cohort_snapshot(captured_at: str = BEFORE, count: int = PAGE_MEMBERS) -> CapturedSnapshot:
    return _snapshot(
        "fpl-top200",
        captured_at,
        {
            BOOTSTRAP_PAYLOAD: _bootstrap(),
            league_standings_page_payload(314, 1): _standings_page(count),
        },
    )


def _picks_snapshot(gameweek: int, captured_at: str = BEFORE) -> CapturedSnapshot:
    """Every synthetic member holds elements 1..15 and captains element 1."""

    payloads = {
        entry_picks_payload(FIRST_ENTRY + rank, gameweek): _picks(
            elements=list(range(1, 16)), captain=1, vice=2
        )
        for rank in range(1, COHORT + 1)
    }
    return _snapshot("fpl-elite-picks", captured_at, payloads)


def _build(**overrides: Any) -> pd.DataFrame:
    cohort = overrides.pop("cohort_snapshot", None) or _cohort_snapshot()
    keywords: dict[str, Any] = {
        "season": SEASON,
        "target_gameweek": TARGET,
        "deadline_timestamp_utc": DEADLINE,
        "snapshots": [cohort, _picks_snapshot(TARGET - 1)],
        "cohort_snapshot": cohort,
        "cohort_size": COHORT,
    }
    keywords.update(overrides)
    return build_player_evidence_table(**keywords)


# --- shape -------------------------------------------------------------------


def test_the_table_carries_exactly_the_declared_columns_in_order() -> None:
    table = _build()

    assert tuple(table.columns) == EVIDENCE_COLUMNS
    assert table["contract_version"].unique().tolist() == [CONTRACT_VERSION]
    assert table["player_id"].is_unique


# --- 1. timing ---------------------------------------------------------------


def test_a_capture_after_the_deadline_cannot_supply_pre_match_evidence() -> None:
    """The rule the whole layer rests on, and the one a hurried operator would break."""

    late = _snapshot("fpl-top200", AFTER, dict(_cohort_snapshot().payloads))

    with pytest.raises(DataSourceError, match="No pre-deadline capture"):
        _build(snapshots=[late], cohort_snapshot=late)


def test_a_cohort_frozen_after_the_deadline_is_refused() -> None:
    late_cohort = _cohort_snapshot(captured_at=AFTER)

    with pytest.raises(DataSourceError):
        _build(cohort_snapshot=late_cohort, snapshots=[_cohort_snapshot(), late_cohort])


def test_the_ownership_reading_is_the_newest_legal_capture_not_the_newest_capture() -> None:
    """A later capture must not be preferred into the table just because it is later."""

    early = _snapshot("fpl-live", "2026-09-01T10:00:00Z", {BOOTSTRAP_PAYLOAD: _bootstrap()})
    legal_latest = _snapshot("fpl-live", "2026-09-04T17:00:00Z", {BOOTSTRAP_PAYLOAD: _bootstrap()})
    illegal = _snapshot("fpl-live", AFTER, {BOOTSTRAP_PAYLOAD: _bootstrap()})
    cohort = _cohort_snapshot()

    table = _build(snapshots=[early, illegal, legal_latest, cohort], cohort_snapshot=cohort)

    assert table.attrs["ownership_snapshot_id"] == legal_latest.metadata.snapshot_id
    assert table["captured_at_utc"].unique().tolist() == ["2026-09-04T17:00:00Z"]


# --- 2 and 3. the lag rule ---------------------------------------------------


def test_gameweek_n_picks_cannot_inform_a_gameweek_n_feature() -> None:
    """Picks for the target week are not read even when they are sitting in the capture.

    They become public only after the deadline they would be describing, so a table that
    counted them would be reading the answer. Loosening the lag to N makes this fail.
    """

    cohort = _cohort_snapshot()
    same_week = _picks_snapshot(TARGET)

    table = _build(snapshots=[cohort, same_week], cohort_snapshot=cohort)

    assert table["elite_members_observed"].unique().tolist() == [0]
    assert table["elite_evidence_observed"].unique().tolist() == [False]
    assert table["elite_squad_share_lag1"].isna().all()


def test_gameweek_n_minus_one_picks_do_inform_a_gameweek_n_feature() -> None:
    table = _build()

    assert table["elite_members_observed"].unique().tolist() == [COHORT]
    held = table.loc[table["player_id"] == FIRST_CODE, "elite_squad_share_lag1"]
    assert held.tolist() == [1.0]


def test_a_gameweek_one_target_is_refused_because_it_has_no_previous_week() -> None:
    with pytest.raises(InvalidValueError, match="at least"):
        _build(target_gameweek=1)


def test_the_counts_are_internally_consistent_with_the_squad_rules() -> None:
    """Fifteen held and eleven started per observed member, one captain each.

    Three sums that cannot all be right by accident, so they catch a miscount that a
    per-player assertion would miss.
    """

    table = _build()

    assert int(table["elite_squad_count_lag1"].sum()) == 15 * COHORT
    assert int(table["elite_start_count_lag1"].sum()) == 11 * COHORT
    assert int(table["elite_captain_count_lag1"].sum()) == COHORT
    assert table["elite_captain_share_lag1"].sum() == pytest.approx(1.0)


# --- 4 and 5. cohort membership ----------------------------------------------


def test_cohort_membership_comes_from_the_capture_it_was_frozen_in() -> None:
    """Membership is attributed to one snapshot, so it cannot be re-derived from a later one."""

    cohort = _cohort_snapshot()
    table = _build(cohort_snapshot=cohort)

    assert table.attrs["cohort_snapshot_id"] == cohort.metadata.snapshot_id
    assert table["elite_cohort_size"].unique().tolist() == [COHORT]


def test_a_cohort_snapshot_without_standings_pages_is_refused() -> None:
    bare = _snapshot("fpl-live", BEFORE, {BOOTSTRAP_PAYLOAD: _bootstrap()})

    with pytest.raises(DataSourceError, match="no Overall standings pages"):
        _build(cohort_snapshot=bare, snapshots=[bare])


def test_a_cohort_larger_than_the_capture_is_refused() -> None:
    """Larger than the ordering the capture actually holds, not larger than the cut."""

    with pytest.raises(DataSourceError, match="needs 51 ranked entries"):
        _build(cohort_size=PAGE_MEMBERS + 1)


# --- 6 and 7. missing is not zero -------------------------------------------


def test_an_unobserved_member_is_not_counted_as_zero_ownership() -> None:
    """The distinction the whole missingness policy exists for.

    With two of four members readable the denominator is two, not four. Counting the
    unreadable pair as zero holdings would halve every share and read as a real signal.
    """

    cohort = _cohort_snapshot()
    partial = _snapshot(
        "fpl-elite-picks",
        BEFORE,
        {
            entry_picks_payload(FIRST_ENTRY + rank, TARGET - 1): _picks(
                elements=list(range(1, 16)), captain=1, vice=2
            )
            for rank in (1, 2)
        },
    )

    table = _build(snapshots=[cohort, partial], cohort_snapshot=cohort)

    assert table["elite_members_observed"].unique().tolist() == [2]
    held = table.loc[table["player_id"] == FIRST_CODE, "elite_squad_share_lag1"]
    assert held.tolist() == [1.0]  # two of two, not two of four
    assert table.attrs["elite_members_missing_picks"] == COHORT - 2


def test_no_observed_member_leaves_the_share_missing_rather_than_zero() -> None:
    cohort = _cohort_snapshot()

    table = _build(snapshots=[cohort], cohort_snapshot=cohort)

    assert table["elite_squad_share_lag1"].isna().all()
    assert not (table["elite_squad_share_lag1"] == 0).any()
    assert table["elite_squad_count_lag1"].isna().all()


def test_a_real_zero_is_told_apart_from_a_missing_value() -> None:
    """A player no observed member held is a true zero; the flag says the evidence was read."""

    table = _build()
    unheld = table.loc[table["player_id"] == FIRST_CODE + 19]

    assert unheld["elite_squad_count_lag1"].tolist() == [0]
    assert unheld["elite_squad_share_lag1"].tolist() == [0.0]
    assert unheld["elite_evidence_observed"].tolist() == [True]


def test_an_unparseable_ownership_value_is_missing_rather_than_zero() -> None:
    elements = [_element(i) for i in range(1, 21)]
    elements[0] = _element(1, selected_by_percent="not a number")
    cohort = _snapshot(
        "fpl-top200",
        BEFORE,
        {
            BOOTSTRAP_PAYLOAD: _bootstrap(elements),
            league_standings_page_payload(314, 1): _standings_page(),
        },
    )

    table = _build(cohort_snapshot=cohort, snapshots=[cohort, _picks_snapshot(TARGET - 1)])
    row = table.loc[table["player_id"] == FIRST_CODE]

    assert row["overall_selected_by_percent"].isna().all()
    assert row["ownership_evidence_observed"].tolist() == [False]


# --- 8. duplicates -----------------------------------------------------------


def test_a_renamed_bootstrap_field_is_refused_by_name() -> None:
    elements = [_element(i) for i in range(1, 21)]
    del elements[0]["transfers_in_event"]
    cohort = _snapshot(
        "fpl-top200",
        BEFORE,
        {
            BOOTSTRAP_PAYLOAD: _bootstrap(elements),
            league_standings_page_payload(314, 1): _standings_page(),
        },
    )

    with pytest.raises(DataSourceError, match="missing fields"):
        _build(cohort_snapshot=cohort, snapshots=[cohort])


def test_no_snapshots_at_all_is_refused() -> None:
    with pytest.raises(DataSourceError, match="At least one capture"):
        _build(snapshots=[])


# --- 9 and 10. privacy and identity -----------------------------------------


def test_no_entry_id_or_manager_name_reaches_the_table() -> None:
    """The standings pages carry both; the table must carry neither."""

    table = _build()
    rendered = table.to_csv(index=False)

    assert "Placeholder Manager" not in rendered
    assert "Placeholder Squad" not in rendered
    for rank in range(1, COHORT + 1):
        assert str(FIRST_ENTRY + rank) not in rendered
    assert not any("entry" in column for column in table.columns)


def test_rows_key_on_the_persistent_player_code_not_the_seasonal_element_id() -> None:
    """Element ids are 1..20 here and codes are 700001+, so a mix-up cannot hide."""

    table = _build()

    assert table["player_id"].min() == FIRST_CODE
    assert table["player_id"].max() == FIRST_CODE + 19
    assert not table["player_id"].isin(range(1, 21)).any()


def test_a_picked_element_the_bootstrap_cannot_map_is_counted_not_dropped() -> None:
    """An unrecognised element is a diagnostic, never a silent omission."""

    cohort = _cohort_snapshot()
    stranger = _snapshot(
        "fpl-elite-picks",
        BEFORE,
        {
            entry_picks_payload(FIRST_ENTRY + rank, TARGET - 1): _picks(
                elements=[*range(1, 15), 999], captain=1, vice=2
            )
            for rank in range(1, COHORT + 1)
        },
    )

    table = _build(snapshots=[cohort, stranger], cohort_snapshot=cohort)

    assert table.attrs["unmapped_picked_elements"] == (999,)
    assert int(table["elite_squad_count_lag1"].sum()) == 14 * COHORT


# --- 11, 12. determinism and purity -----------------------------------------


def test_the_same_input_produces_the_same_table() -> None:
    assert _build().equals(_build())


def test_the_input_payloads_are_not_mutated() -> None:
    """There is no input DataFrame to mutate; the payload mappings are the inputs instead."""

    cohort = _cohort_snapshot()
    picks = _picks_snapshot(TARGET - 1)
    before = ({**cohort.payloads}, {**picks.payloads})

    _build(snapshots=[cohort, picks], cohort_snapshot=cohort)

    assert ({**cohort.payloads}, {**picks.payloads}) == before


# --- 13, 14. the holdout and provenance -------------------------------------


def test_the_locked_holdout_season_is_refused() -> None:
    with pytest.raises(DataSourceError, match="locked holdout"):
        _build(season=LOCKED_HOLDOUT_SEASON)


@pytest.mark.parametrize("season", ["", "   "])
def test_an_empty_season_is_refused_rather_than_labelled_blank(season: str) -> None:
    with pytest.raises(InvalidValueError, match="season must be non-empty"):
        _build(season=season)


def test_every_row_names_the_captures_it_came_from() -> None:
    """Provenance is per row, so a table cannot be split from its sources."""

    cohort = _cohort_snapshot()
    picks = _picks_snapshot(TARGET - 1)

    table = _build(snapshots=[cohort, picks], cohort_snapshot=cohort)
    ids = table["source_snapshot_ids"].unique().tolist()

    assert len(ids) == 1
    assert cohort.metadata.snapshot_id in ids[0]
    assert picks.metadata.snapshot_id in ids[0]
    assert table["timing_verified"].all()
    assert table.attrs["hours_pre_deadline"] > 0


# --- 15. the dtype contract ---------------------------------------------------


_EXPECTED_DTYPES = {
    "contract_version": "string",
    "season": "string",
    "target_gameweek": "int64",
    "player_id": "int64",
    "captured_at_utc": "string",
    "deadline_timestamp_utc": "string",
    "source_snapshot_ids": "string",
    "timing_verified": "boolean",
    "elite_cohort_size": "int64",
    "elite_members_observed": "int64",
    "elite_squad_count_lag1": "Int64",
    "elite_squad_share_lag1": "Float64",
    "elite_start_count_lag1": "Int64",
    "elite_start_share_lag1": "Float64",
    "elite_captain_count_lag1": "Int64",
    "elite_captain_share_lag1": "Float64",
    "overall_selected_by_percent": "Float64",
    "transfers_in_event": "Int64",
    "transfers_out_event": "Int64",
    "net_transfers_event": "Int64",
    "availability_status": "string",
    "chance_of_playing_next_round": "Int64",
    "official_news_present": "boolean",
    "elite_evidence_observed": "boolean",
    "ownership_evidence_observed": "boolean",
    "transfer_evidence_observed": "boolean",
    "availability_evidence_observed": "boolean",
}


def _sparse_cohort_snapshot() -> CapturedSnapshot:
    """Element 1 arrives with no transfers, no chance, no news and an empty status."""

    elements = [_element(i) for i in range(1, 21)]
    elements[0] = _element(
        1, transfers_in_event=None, chance_of_playing_next_round=None, news=None, status=""
    )
    return _snapshot(
        "fpl-top200",
        BEFORE,
        {
            BOOTSTRAP_PAYLOAD: _bootstrap(elements),
            league_standings_page_payload(314, 1): _standings_page(),
        },
    )


def test_the_table_carries_one_dtype_per_column_whatever_was_observed() -> None:
    """The contract is the dtypes as much as the names; left to inference they drift.

    A count column came out int64 when picks were observed and object when none were, and
    a nullable column turned object the moment one value was missing. The same contract
    across three capture scopes must carry the same dtypes.
    """

    cohort = _cohort_snapshot()
    sparse = _sparse_cohort_snapshot()
    tables = (
        _build(),
        _build(snapshots=[cohort], cohort_snapshot=cohort),
        _build(snapshots=[sparse, _picks_snapshot(TARGET - 1)], cohort_snapshot=sparse),
    )

    for table in tables:
        assert {name: str(dtype) for name, dtype in table.dtypes.items()} == _EXPECTED_DTYPES
        assert tuple(table.columns) == EVIDENCE_COLUMNS


def test_missing_evidence_is_typed_missing_rather_than_zero_or_false() -> None:
    """With no picks read and a sparse element, every nullable cell is ``pd.NA`` -- not 0,
    not False, not an empty string -- and the flags that say so are real booleans."""

    sparse = _sparse_cohort_snapshot()

    table = _build(snapshots=[sparse], cohort_snapshot=sparse)
    row = table.loc[table["player_id"] == FIRST_CODE].iloc[0]

    for column in (
        "elite_squad_count_lag1",
        "elite_squad_share_lag1",
        "elite_captain_count_lag1",
        "transfers_in_event",
        "net_transfers_event",
        "chance_of_playing_next_round",
        "official_news_present",
        "availability_status",
    ):
        assert row[column] is pd.NA, column
    flags = table.loc[table["player_id"] == FIRST_CODE]
    assert flags["elite_evidence_observed"].tolist() == [False]
    assert flags["transfer_evidence_observed"].tolist() == [False]
    assert flags["availability_evidence_observed"].tolist() == [False]
    assert table["elite_squad_count_lag1"].isna().all()


# --- 16. exact provenance -----------------------------------------------------


def test_provenance_names_only_the_captures_that_were_read() -> None:
    """A legal capture that contributed nothing is not a source.

    Listing every pre-deadline input would let a table claim an input it never used. The
    cohort capture, the ownership capture and every capture a member's picks came from are
    named; an idle one is not.
    """

    cohort = _cohort_snapshot()
    first = _snapshot(
        "fpl-elite-picks",
        BEFORE,
        {
            entry_picks_payload(FIRST_ENTRY + rank, TARGET - 1): _picks(
                elements=list(range(1, 16)), captain=1, vice=2
            )
            for rank in (1, 2)
        },
    )
    second = _snapshot(
        "fpl-elite-picks",
        "2026-09-01T17:00:00Z",
        {
            entry_picks_payload(FIRST_ENTRY + rank, TARGET - 1): _picks(
                elements=list(range(1, 16)), captain=1, vice=2
            )
            for rank in (3, 4)
        },
    )
    # Legal, and carrying a bootstrap -- but older than the cohort capture, so it loses the
    # newest-wins ownership choice and nothing is read from it.
    idle = _snapshot("fpl-live", "2026-09-01T10:00:00Z", {BOOTSTRAP_PAYLOAD: _bootstrap()})

    table = _build(snapshots=[idle, first, cohort, second], cohort_snapshot=cohort)
    ids = set(table["source_snapshot_ids"].iloc[0].split(";"))

    assert idle.metadata.snapshot_id not in ids
    assert ids == {
        cohort.metadata.snapshot_id,  # membership, and the newest legal bootstrap
        first.metadata.snapshot_id,
        second.metadata.snapshot_id,
    }
    assert table["source_snapshot_ids"].nunique() == 1
