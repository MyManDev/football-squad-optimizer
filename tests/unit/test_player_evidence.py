"""Leakage, missingness, identity and provenance tests for the Phase B handoff.

All people, entries and squads in this file are synthetic placeholders. The committed
suite never contains the identities stored by a real local cohort capture.
"""

import json
from typing import Any

import pandas as pd
import pytest

from squadopt.data.errors import DataSourceError, DuplicateRecordsError
from squadopt.data.snapshots import (
    SNAPSHOT_SCHEMA_VERSION,
    CapturedSnapshot,
    SnapshotMetadata,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    entry_history_payload,
    entry_picks_payload,
    league_standings_page_payload,
)
from squadopt.features.evidence import EVIDENCE_COLUMNS, build_player_evidence_table

DEADLINE = "2026-09-04T17:30:00Z"
COHORT_CAPTURED = "2026-09-01T12:00:00Z"
PICKS_CAPTURED = "2026-09-02T12:00:00Z"
FIRST_ENTRY = 900_001
FIRST_PLAYER = 700_001


def _json(document: object) -> bytes:
    return json.dumps(document, sort_keys=True).encode("utf-8")


def _bootstrap(*, selected: str | None = "10.0") -> bytes:
    elements: list[dict[str, Any]] = []
    for element in range(1, 16):
        row: dict[str, Any] = {
            "id": element,
            "code": FIRST_PLAYER + element,
            "element_type": 1 if element <= 2 else (2 if element <= 7 else 3),
            "transfers_in_event": 10 + element,
            "transfers_out_event": element,
            "status": "a",
            "chance_of_playing_next_round": 100,
            "news": "",
        }
        if selected is not None:
            row["selected_by_percent"] = selected
        elements.append(row)
    return _json(
        {
            "events": [
                {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": True},
                {"id": 3, "deadline_time": DEADLINE, "finished": False},
            ],
            "elements": elements,
        }
    )


def _standings_page(page: int, *, reverse: bool = False) -> bytes:
    first = (page - 1) * 50 + 1
    ranks = list(range(first, first + 50))
    entries = list(reversed(ranks)) if reverse else ranks
    return _json(
        {
            "league": {"id": 314, "name": "Synthetic Overall"},
            "standings": {
                "page": page,
                "has_next": page < 4,
                "results": [
                    {
                        "entry": FIRST_ENTRY + entry,
                        "entry_name": f"Synthetic Squad {entry}",
                        "player_name": f"Synthetic Manager {entry}",
                        "rank": rank,
                        "rank_sort": rank,
                    }
                    for rank, entry in zip(ranks, entries, strict=True)
                ],
            },
            "last_updated_data": COHORT_CAPTURED,
        }
    )


def _cohort_payloads() -> dict[str, bytes]:
    return {
        BOOTSTRAP_PAYLOAD: _bootstrap(),
        **{league_standings_page_payload(314, page): _standings_page(page) for page in range(1, 5)},
    }


def _picks() -> bytes:
    return _json(
        {
            "picks": [
                {
                    "element": element,
                    "position": element,
                    "is_captain": element == 1,
                    "is_vice_captain": element == 2,
                    "multiplier": 2 if element == 1 else (1 if element <= 11 else 0),
                }
                for element in range(1, 16)
            ],
            "active_chip": None,
            "entry_history": {"bank": 0, "event_transfers": 0, "event_transfers_cost": 0},
        }
    )


def _history() -> bytes:
    return _json({"chips": [], "current": []})


def _snapshot(payloads: dict[str, bytes], *, captured: str, source: str) -> CapturedSnapshot:
    checksums = {name: payload_checksum(content) for name, content in payloads.items()}
    fingerprint = snapshot_fingerprint(
        source=source,
        captured_at_utc=captured,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        checksums=checksums,
    )
    snapshot_id = build_snapshot_id(
        source=source, captured_at_utc=captured, fingerprint=fingerprint
    )
    return CapturedSnapshot(
        metadata=SnapshotMetadata(
            snapshot_id=snapshot_id,
            source=source,
            captured_at_utc=captured,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            checksums=checksums,
            fingerprint=fingerprint,
        ),
        payloads=payloads,
    )


def _cohort() -> CapturedSnapshot:
    return _snapshot(_cohort_payloads(), captured=COHORT_CAPTURED, source="synthetic-cohort")


def _picks_snapshot(*, entries: int = 1, gameweek: int = 2) -> CapturedSnapshot:
    payloads = {BOOTSTRAP_PAYLOAD: _bootstrap()}
    for offset in range(entries):
        entry_id = FIRST_ENTRY + 1 + offset
        payloads[entry_picks_payload(entry_id, gameweek)] = _picks()
        payloads[entry_history_payload(entry_id)] = _history()
    return _snapshot(payloads, captured=PICKS_CAPTURED, source="synthetic-picks")


def _build(*snapshots: CapturedSnapshot, cohort: CapturedSnapshot | None = None) -> pd.DataFrame:
    return build_player_evidence_table(
        target_gameweek=3,
        deadline_timestamp_utc=DEADLINE,
        snapshots=snapshots,
        cohort_snapshot=cohort or _cohort(),
    )


def test_lag_one_picks_are_used_with_persistent_player_identity() -> None:
    frame = _build(_picks_snapshot())
    first = frame.set_index("player_id").loc[FIRST_PLAYER + 1]

    assert tuple(frame.columns) == EVIDENCE_COLUMNS
    assert first["elite_squad_count_lag1"] == 1
    assert first["elite_start_count_lag1"] == 1
    assert first["elite_captain_count_lag1"] == 1
    assert first["elite_squad_share_lag1"] == 1.0
    assert first["elite_members_observed"] == 1


def test_target_gameweek_picks_never_enter_target_features() -> None:
    frame = _build(_picks_snapshot(gameweek=3))

    assert frame["elite_members_observed"].eq(0).all()
    assert frame["elite_squad_share_lag1"].isna().all()


def test_missing_member_reduces_denominator_instead_of_becoming_zero() -> None:
    frame = _build(_picks_snapshot(entries=2))
    first = frame.set_index("player_id").loc[FIRST_PLAYER + 1]

    assert first["elite_members_observed"] == 2
    assert first["elite_squad_count_lag1"] == 2
    assert first["elite_squad_share_lag1"] == 1.0


def test_missing_evidence_and_a_true_zero_are_distinct() -> None:
    no_picks = _build()
    observed = _build(_picks_snapshot())

    assert pd.isna(no_picks.iloc[0]["elite_squad_share_lag1"])
    assert observed.set_index("player_id").loc[FIRST_PLAYER + 15, "elite_start_share_lag1"] == 0.0


def test_post_deadline_capture_is_excluded_from_market_evidence() -> None:
    late = _snapshot(
        {BOOTSTRAP_PAYLOAD: _bootstrap(selected="99.9")},
        captured="2026-09-04T18:00:00Z",
        source="synthetic-late",
    )
    frame = _build(late)

    assert frame["overall_selected_by_percent"].eq(10.0).all()
    assert not frame["source_snapshot_ids"].str.contains(late.metadata.snapshot_id).any()


def test_cohort_snapshot_itself_must_be_pre_deadline() -> None:
    late = _snapshot(_cohort_payloads(), captured="2026-09-04T18:00:00Z", source="synthetic-cohort")
    with pytest.raises(DataSourceError, match="not pre-deadline evidence"):
        _build(cohort=late)


def test_later_standings_cannot_change_frozen_cohort_membership() -> None:
    changed = _snapshot(
        {
            league_standings_page_payload(314, page): _standings_page(page, reverse=True)
            for page in range(1, 5)
        },
        captured=PICKS_CAPTURED,
        source="synthetic-later-standings",
    )
    pd.testing.assert_frame_equal(_build(), _build(changed))


def test_same_inputs_produce_the_same_table_without_mutating_payloads() -> None:
    cohort = _cohort()
    picks = _picks_snapshot()
    before = (dict(cohort.payloads), dict(picks.payloads))

    first = _build(picks, cohort=cohort)
    second = _build(picks, cohort=cohort)

    pd.testing.assert_frame_equal(first, second)
    assert before == (dict(cohort.payloads), dict(picks.payloads))


def test_duplicate_snapshot_is_rejected() -> None:
    picks = _picks_snapshot()
    with pytest.raises(DuplicateRecordsError, match="same snapshot"):
        _build(picks, picks)


def test_incomplete_provenance_fails_closed() -> None:
    cohort = _cohort()
    broken = CapturedSnapshot(
        metadata=SnapshotMetadata(
            snapshot_id="",
            source=cohort.metadata.source,
            captured_at_utc=cohort.metadata.captured_at_utc,
            schema_version=cohort.metadata.schema_version,
            checksums=cohort.metadata.checksums,
            fingerprint=cohort.metadata.fingerprint,
        ),
        payloads=cohort.payloads,
    )
    with pytest.raises(DataSourceError, match="provenance is incomplete"):
        _build(cohort=broken)


def test_locked_holdout_is_refused_before_snapshot_inputs_are_inspected() -> None:
    with pytest.raises(DataSourceError, match="locked holdout"):
        build_player_evidence_table(
            target_gameweek=3,
            deadline_timestamp_utc="2025-09-01T12:00:00Z",
            snapshots=(),
            cohort_snapshot=object(),  # type: ignore[arg-type]
        )


def test_output_contains_no_entry_manager_squad_or_raw_news_fields() -> None:
    frame = _build(_picks_snapshot())
    forbidden = {"entry_id", "entry_name", "manager_name", "squad_name", "team_name", "news"}

    assert forbidden.isdisjoint(frame.columns)
    assert frame["source_snapshot_ids"].str.startswith("synthetic-").all()


def test_market_missingness_and_observed_flags_travel_together() -> None:
    market = _snapshot(
        {BOOTSTRAP_PAYLOAD: _bootstrap(selected=None)},
        captured=PICKS_CAPTURED,
        source="synthetic-market",
    )
    frame = _build(market)

    assert frame["overall_selected_by_percent"].isna().all()
    assert not frame["ownership_evidence_observed"].any()
    assert frame["transfer_evidence_observed"].all()
    assert frame["availability_evidence_observed"].all()
