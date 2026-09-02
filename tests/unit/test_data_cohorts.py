"""Tests for the nested elite cohorts derived from one standings capture.

Every fixture is synthetic. Entry ids are small integers from a reserved block and the
names are placeholders, because a committed test that carried a real manager's name or
entry id would leak exactly what the capture keeps out of git.
"""

import json
import sys
from pathlib import Path

import pytest
from scripts import capture_top100_cohort as capture

from squadopt.data.cohorts import (
    CONTRACT_VERSION,
    MEMBERS_PER_PAGE,
    NESTED_COHORT_SIZES,
    RankedCohort,
    nested_cohorts,
    pages_for_cohort_size,
    ranked_entries_from_pages,
)
from squadopt.data.errors import DataSourceError, DuplicateRecordsError, InvalidValueError
from squadopt.data.sources.fpl_live import LeagueStanding, LeagueStandingsPage

CAPTURED = "2026-09-01T04:07:25Z"
DEADLINE = "2026-09-04T17:30:00Z"
SNAPSHOT = "fpl-top200-20260901T040725Z-0000000000ff"

# Synthetic identifiers only. 900001+ is a reserved block that matches no real entry.
FIRST_SYNTHETIC_ENTRY = 900_001


def _member(rank: int) -> LeagueStanding:
    return LeagueStanding(
        entry_id=FIRST_SYNTHETIC_ENTRY + rank,
        entry_name=f"Synthetic Squad {rank}",
        player_name=f"Synthetic Manager {rank}",
        rank=rank,
        rank_sort=rank,
    )


def _page(number: int, *, members: list[LeagueStanding] | None = None) -> LeagueStandingsPage:
    first = (number - 1) * MEMBERS_PER_PAGE + 1
    return LeagueStandingsPage(
        page=number,
        has_next=True,
        members=tuple(
            members
            if members is not None
            else [_member(rank) for rank in range(first, first + MEMBERS_PER_PAGE)]
        ),
        last_updated_data="2026-09-01T03:30:00Z",
    )


def _pages(count: int) -> list[LeagueStandingsPage]:
    return [_page(number) for number in range(1, count + 1)]


def _cohorts(count: int = 4, **overrides: object) -> dict[int, RankedCohort]:
    ordered = ranked_entries_from_pages(_pages(count), expected_ranks=count * MEMBERS_PER_PAGE)
    keywords: dict[str, object] = {
        "target_gameweek": 3,
        "captured_at_utc": CAPTURED,
        "deadline_timestamp_utc": DEADLINE,
        "source_snapshot_id": SNAPSHOT,
    }
    keywords.update(overrides)
    return dict(nested_cohorts(ordered, **keywords))  # type: ignore[arg-type]


# --- the ordering the cohorts are prefixes of --------------------------------


def test_four_pages_cover_two_hundred_ranks_in_order() -> None:
    ordered = ranked_entries_from_pages(_pages(4), expected_ranks=200)

    assert len(ordered) == 200
    assert len(set(ordered)) == 200
    assert ordered[0] == FIRST_SYNTHETIC_ENTRY + 1
    assert ordered[-1] == FIRST_SYNTHETIC_ENTRY + 200


def test_a_missing_rank_is_refused_rather_than_shortening_the_cohort() -> None:
    """A cohort missing a rank is not a smaller cohort.

    Its composition would depend on which page failed, and every share computed against
    it would be wrong by an amount nobody can state.
    """

    pages = _pages(4)
    thinned = _page(4, members=[member for member in pages[3].members if member.rank_sort != 173])
    with pytest.raises(DataSourceError, match="do not cover ranks 1 to 200"):
        ranked_entries_from_pages([*pages[:3], thinned], expected_ranks=200)


def test_a_repeated_rank_sort_is_refused() -> None:
    pages = _pages(2)
    clashing = _page(2, members=[_member(51), _member(51)])
    with pytest.raises(DuplicateRecordsError, match="rank_sort 51 appears more than once"):
        ranked_entries_from_pages([pages[0], clashing], expected_ranks=100)


def test_an_entry_at_two_different_ranks_is_refused() -> None:
    twinned = list(_page(1).members)
    twinned[7] = LeagueStanding(
        entry_id=twinned[0].entry_id,
        entry_name="Synthetic Squad dup",
        player_name="Synthetic Manager dup",
        rank=8,
        rank_sort=8,
    )
    with pytest.raises(DuplicateRecordsError, match="same entry at two different ranks"):
        ranked_entries_from_pages([_page(1, members=twinned)], expected_ranks=50)


def test_a_member_without_rank_sort_is_refused() -> None:
    """``rank`` alone cannot order a cohort: the platform's tie handling lives in rank_sort."""

    unsorted = list(_page(1).members)
    unsorted[3] = LeagueStanding(
        entry_id=unsorted[3].entry_id,
        entry_name="Synthetic Squad 4",
        player_name="Synthetic Manager 4",
        rank=4,
        rank_sort=None,
    )
    with pytest.raises(DataSourceError, match="no rank_sort"):
        ranked_entries_from_pages([_page(1, members=unsorted)], expected_ranks=50)


def test_the_same_page_twice_is_refused() -> None:
    with pytest.raises(DuplicateRecordsError, match="page 1 appears more than once"):
        ranked_entries_from_pages([_page(1), _page(1)], expected_ranks=50)


def test_the_exact_numbered_pages_are_required_in_order() -> None:
    with pytest.raises(DataSourceError, match="require standings pages"):
        ranked_entries_from_pages([_page(1), _page(3)], expected_ranks=100)


def test_a_rank_outside_the_requested_prefix_is_refused() -> None:
    members = list(_page(4).members)
    members[-1] = _member(201)
    with pytest.raises(DataSourceError, match=r"outside=.*201"):
        ranked_entries_from_pages([*_pages(3), _page(4, members=members)], expected_ranks=200)


# --- nesting -----------------------------------------------------------------


def test_top_fifty_is_inside_top_one_hundred_is_inside_top_two_hundred() -> None:
    """The property the sensitivity reading rests on, asserted rather than assumed.

    Containment is structural — each cohort is a prefix of one ordering — but a future
    refactor could take the prefixes from different orderings, and nothing else here
    would notice.
    """

    cohorts = _cohorts()

    assert sorted(cohorts) == list(NESTED_COHORT_SIZES)
    fifty, hundred, two_hundred = (set(cohorts[size].entry_ids) for size in NESTED_COHORT_SIZES)
    assert fifty < hundred < two_hundred
    assert cohorts[100].entry_ids[:50] == cohorts[50].entry_ids
    assert cohorts[200].entry_ids[:100] == cohorts[100].entry_ids


def test_every_cohort_carries_the_capture_it_came_from() -> None:
    """Provenance travels with membership, so a cohort cannot be re-attributed later."""

    for cohort in _cohorts().values():
        assert cohort.source_snapshot_id == SNAPSHOT
        assert cohort.captured_at_utc == CAPTURED
        assert cohort.deadline_timestamp_utc == DEADLINE
        assert cohort.target_gameweek == 3


def test_a_size_larger_than_the_capture_is_refused() -> None:
    ordered = ranked_entries_from_pages(_pages(2), expected_ranks=100)

    with pytest.raises(DataSourceError, match="needs 200 ranked entries"):
        nested_cohorts(
            ordered,
            target_gameweek=3,
            captured_at_utc=CAPTURED,
            deadline_timestamp_utc=DEADLINE,
            source_snapshot_id=SNAPSHOT,
        )


def test_a_two_page_capture_still_yields_the_two_smaller_cohorts() -> None:
    cohorts = _cohorts(count=2, sizes=[50, 100])

    assert sorted(cohorts) == [50, 100]
    assert set(cohorts[50].entry_ids) < set(cohorts[100].entry_ids)


# --- timing ------------------------------------------------------------------


def test_a_capture_at_or_after_the_deadline_is_not_pre_deadline_evidence() -> None:
    with pytest.raises(DataSourceError, match="not pre-deadline evidence"):
        _cohorts(captured_at_utc=DEADLINE)


def test_a_capture_after_the_deadline_is_refused_too() -> None:
    with pytest.raises(DataSourceError, match="not pre-deadline evidence"):
        _cohorts(captured_at_utc="2026-09-04T18:00:00Z")


def test_a_late_capture_writes_no_identity_bearing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deadline = "2026-09-04T17:30:00Z"
    bootstrap = json.dumps(
        {"events": [{"id": 3, "deadline_time": deadline, "finished": False}]}
    ).encode()
    payloads: dict[str, bytes] = {"bootstrap": bootstrap}
    for page in range(1, 5):
        first = (page - 1) * MEMBERS_PER_PAGE + 1
        payloads[f"page-{page}"] = json.dumps(
            {
                "league": {"id": 314, "name": "Overall"},
                "standings": {
                    "page": page,
                    "has_next": page < 4,
                    "results": [
                        {
                            "entry": FIRST_SYNTHETIC_ENTRY + rank,
                            "entry_name": f"Synthetic Squad {rank}",
                            "player_name": f"Synthetic Manager {rank}",
                            "rank": rank,
                            "rank_sort": rank,
                        }
                        for rank in range(first, first + MEMBERS_PER_PAGE)
                    ],
                },
                "last_updated_data": "2026-09-01T03:30:00Z",
            }
        ).encode()

    reads = iter([bootstrap, *(payloads[f"page-{page}"] for page in range(1, 5))])
    clocks = iter(["2026-09-01T12:00:00Z", deadline])
    monkeypatch.setattr(capture, "fetch", lambda _: next(reads))
    monkeypatch.setattr(capture, "_utc_now", lambda: next(clocks))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_top100_cohort",
            "--target-gameweek",
            "3",
            "--cohort-size",
            "200",
            "--snapshot-root",
            str(tmp_path),
        ],
    )

    assert capture.main() == 1
    assert list(tmp_path.iterdir()) == []


# --- determinism and privacy -------------------------------------------------


def test_the_same_pages_produce_the_same_cohorts() -> None:
    first = _cohorts()
    second = _cohorts()

    assert {size: cohort.entry_ids for size, cohort in first.items()} == {
        size: cohort.entry_ids for size, cohort in second.items()
    }


def test_page_counts_follow_the_platforms_page_size() -> None:
    assert pages_for_cohort_size(100) == (1, 2)
    assert pages_for_cohort_size(200) == (1, 2, 3, 4)


@pytest.mark.parametrize("size", [0, -50, 75])
def test_a_size_that_is_not_a_whole_number_of_pages_is_refused(size: int) -> None:
    with pytest.raises(InvalidValueError, match="positive multiple"):
        pages_for_cohort_size(size)


def test_a_cohort_carries_no_manager_or_squad_names() -> None:
    """Membership is entry ids and counts. Names stay in the local snapshot.

    The standings pages this is built from *do* carry both names; the cohort deliberately
    drops them, so nothing downstream can publish one by accident.
    """

    cohort = _cohorts()[50]
    fields = {name for name in RankedCohort.__dataclass_fields__}

    assert "entry_name" not in fields
    assert "player_name" not in fields
    assert not any("name" in name for name in fields)
    assert all(isinstance(entry_id, int) for entry_id in cohort.entry_ids)


def test_the_contract_version_is_declared() -> None:
    assert CONTRACT_VERSION == "nested_elite_cohorts_v1"


def test_missing_provenance_is_refused() -> None:
    with pytest.raises(DataSourceError, match="source_snapshot_id"):
        _cohorts(source_snapshot_id="  ")
