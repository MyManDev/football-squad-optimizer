"""Nested elite cohorts derived from one pre-deadline standings capture.

A cohort here is *membership*, not performance: who stood in the official Overall
league's first N ranks at the instant a capture was taken, before the deadline it is
used for. Nothing in this module scores anyone.

Why derivation rather than storage. The capture records the standings pages and the
bootstrap atomically; the cohorts are read back out of it. That keeps three sizes
honest for free — Top-50, Top-100 and Top-200 taken from one capture are prefixes of a
single ordering, so containment is structural rather than something a test has to hope
for. It also means a cohort cannot be quietly re-derived from a *later* capture: the
snapshot id travels with it.

This module deliberately does not import ``squadopt.evaluation``. The primary Top-100
benchmark cohort is frozen by ``evaluation.select_as_of_top_100`` and stays that way;
what is built here is the sensitivity/evidence source, and duplicating a freeze rule
across two layers is how two answers to one question appear.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from squadopt.data.errors import DataSourceError, DuplicateRecordsError, InvalidValueError
from squadopt.data.sources.fpl_live import LeagueStandingsPage
from squadopt.data.timestamps import as_instant

CONTRACT_VERSION: Final = "nested_elite_cohorts_v1"

# The sizes one 200-rank capture can answer for. Each is a prefix of the same ordering.
NESTED_COHORT_SIZES: Final = (50, 100, 200)

# The platform serves fifty ranked members per standings page.
MEMBERS_PER_PAGE: Final = 50


@dataclass(frozen=True, slots=True)
class RankedCohort:
    """The first ``size`` entries of one capture's ordering, with its provenance.

    ``entry_ids`` is ordered by ``rank_sort`` ascending. It holds raw public entry ids
    and therefore belongs to the git-ignored snapshot store and to in-process use --
    never to a committed artifact. Committed reports carry counts, not identities.
    """

    size: int
    entry_ids: tuple[int, ...]
    target_gameweek: int
    captured_at_utc: str
    deadline_timestamp_utc: str
    source_snapshot_id: str

    def __post_init__(self) -> None:
        if self.size != len(self.entry_ids):
            raise InvalidValueError(
                f"A Top-{self.size} cohort must hold {self.size} entries, got "
                f"{len(self.entry_ids)}."
            )
        if len(set(self.entry_ids)) != len(self.entry_ids):
            raise DuplicateRecordsError(
                f"The Top-{self.size} cohort lists the same entry more than once."
            )
        if as_instant(self.captured_at_utc) >= as_instant(self.deadline_timestamp_utc):
            raise DataSourceError(
                f"A Top-{self.size} cohort captured at {self.captured_at_utc} is not "
                f"pre-deadline evidence for a deadline at {self.deadline_timestamp_utc}."
            )


def ranked_entries_from_pages(
    pages: Sequence[LeagueStandingsPage],
    *,
    expected_ranks: int,
) -> tuple[int, ...]:
    """Return the entry ids of ranks 1..``expected_ranks``, in rank order.

    Every failure here is a refusal rather than a shorter list. A cohort that is missing
    a rank is not a smaller cohort: it is a cohort whose composition depends on which
    page happened to fail, and any share computed against it would be wrong by an amount
    nobody can state.
    """

    if expected_ranks < 1:
        raise InvalidValueError(f"expected_ranks must be positive, got {expected_ranks}.")

    seen_pages: list[int] = []
    by_rank: dict[int, int] = {}
    for page in pages:
        if page.page in seen_pages:
            raise DuplicateRecordsError(
                f"Standings page {page.page} appears more than once in this capture."
            )
        seen_pages.append(page.page)
        for member in page.members:
            if member.rank_sort is None:
                raise DataSourceError(
                    f"Standings page {page.page} lists an entry with no rank_sort; the "
                    "ordering this cohort is a prefix of would be a guess."
                )
            if member.rank_sort in by_rank:
                raise DuplicateRecordsError(
                    f"rank_sort {member.rank_sort} appears more than once across the "
                    "captured standings pages."
                )
            by_rank[member.rank_sort] = member.entry_id

    missing = [rank for rank in range(1, expected_ranks + 1) if rank not in by_rank]
    if missing:
        raise DataSourceError(
            f"The captured standings pages do not cover ranks 1 to {expected_ranks}; "
            f"{len(missing)} are missing, first {missing[:5]}."
        )

    ordered = tuple(by_rank[rank] for rank in range(1, expected_ranks + 1))
    if len(set(ordered)) != len(ordered):
        raise DuplicateRecordsError(
            "The captured standings pages name the same entry at two different ranks."
        )
    return ordered


def nested_cohorts(
    entry_ids: Sequence[int],
    *,
    target_gameweek: int,
    captured_at_utc: str,
    deadline_timestamp_utc: str,
    source_snapshot_id: str,
    sizes: Sequence[int] = NESTED_COHORT_SIZES,
) -> Mapping[int, RankedCohort]:
    """Cut one ordering into nested cohorts, smallest inside largest.

    Containment is structural: each cohort is a prefix of the same tuple, so Top-50 is
    inside Top-100 is inside Top-200 by construction rather than by coincidence. A test
    still asserts it, because the property is what the sensitivity reading rests on and
    a future refactor could take the prefixes from different orderings.
    """

    ordered = tuple(entry_ids)
    requested = sorted(set(sizes))
    if not requested:
        raise InvalidValueError("At least one cohort size is required.")
    if requested[0] < 1:
        raise InvalidValueError(f"Cohort sizes must be positive, got {requested[0]}.")
    if requested[-1] > len(ordered):
        raise DataSourceError(
            f"A Top-{requested[-1]} cohort needs {requested[-1]} ranked entries; the "
            f"capture carries {len(ordered)}."
        )
    return MappingProxyType(
        {
            size: RankedCohort(
                size=size,
                entry_ids=ordered[:size],
                target_gameweek=target_gameweek,
                captured_at_utc=captured_at_utc,
                deadline_timestamp_utc=deadline_timestamp_utc,
                source_snapshot_id=source_snapshot_id,
            )
            for size in requested
        }
    )


def pages_for_cohort_size(size: int) -> tuple[int, ...]:
    """Which standings pages a cohort of ``size`` needs, at fifty members a page."""

    if size < 1 or size % MEMBERS_PER_PAGE:
        raise InvalidValueError(
            f"A cohort size must be a positive multiple of {MEMBERS_PER_PAGE}, got {size}."
        )
    return tuple(range(1, size // MEMBERS_PER_PAGE + 1))
