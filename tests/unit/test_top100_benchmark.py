"""Leakage, coverage, and aggregation rules for the as-of Top-100 baseline."""

import pytest

from squadopt.evaluation import (
    TOP_MANAGER_COHORT_VERSION,
    AsOfTop100Cohort,
    EvaluationValidationError,
    RankedManager,
    aggregate_top_100_scores,
    select_as_of_top_100,
)


def _rankings(count: int = 120) -> list[RankedManager]:
    return [RankedManager(entry_id=1000 + rank, rank=rank) for rank in range(1, count + 1)]


def _cohort() -> AsOfTop100Cohort:
    return select_as_of_top_100(
        _rankings(),
        target_gameweek=3,
        captured_at_utc="2026-09-03T12:00:00Z",
        deadline_timestamp_utc="2026-09-04T17:30:00Z",
        source_snapshot_id="standings-before-gw03",
    )


def test_selects_exactly_the_as_of_top_100() -> None:
    cohort = _cohort()

    assert cohort.contract_version == TOP_MANAGER_COHORT_VERSION
    assert len(cohort.entry_ids) == 100
    assert cohort.entry_ids[0] == 1001
    assert cohort.entry_ids[-1] == 1100


def test_selection_is_deterministic_when_rank_is_tied() -> None:
    rankings = _rankings()
    tied = [RankedManager(entry_id=record.entry_id, rank=1) for record in rankings]

    first = select_as_of_top_100(
        tied,
        target_gameweek=2,
        captured_at_utc="2026-08-27T10:00:00Z",
        deadline_timestamp_utc="2026-08-28T17:30:00Z",
        source_snapshot_id="tied-ranks",
    )
    second = select_as_of_top_100(
        list(reversed(tied)),
        target_gameweek=2,
        captured_at_utc="2026-08-27T10:00:00Z",
        deadline_timestamp_utc="2026-08-28T17:30:00Z",
        source_snapshot_id="tied-ranks",
    )

    assert first.entry_ids == second.entry_ids


def test_gameweek_one_has_no_current_season_top_100() -> None:
    with pytest.raises(EvaluationValidationError, match="Gameweek 1"):
        select_as_of_top_100(
            _rankings(),
            target_gameweek=1,
            captured_at_utc="2026-08-20T10:00:00Z",
            deadline_timestamp_utc="2026-08-21T17:30:00Z",
            source_snapshot_id="before-gw01",
        )


def test_membership_capture_after_the_deadline_is_rejected() -> None:
    with pytest.raises(EvaluationValidationError, match="not be later"):
        select_as_of_top_100(
            _rankings(),
            target_gameweek=3,
            captured_at_utc="2026-09-04T18:00:00Z",
            deadline_timestamp_utc="2026-09-04T17:30:00Z",
            source_snapshot_id="too-late",
        )


def test_fewer_than_100_ranked_entries_cannot_define_the_cohort() -> None:
    with pytest.raises(EvaluationValidationError, match="At least 100"):
        select_as_of_top_100(
            _rankings(99),
            target_gameweek=3,
            captured_at_utc="2026-09-03T12:00:00Z",
            deadline_timestamp_utc="2026-09-04T17:30:00Z",
            source_snapshot_id="short-page",
        )


def test_duplicate_entry_is_rejected_before_selection() -> None:
    rankings = _rankings()
    rankings[-1] = RankedManager(entry_id=rankings[0].entry_id, rank=120)

    with pytest.raises(EvaluationValidationError, match="duplicate entry_id"):
        select_as_of_top_100(
            rankings,
            target_gameweek=3,
            captured_at_utc="2026-09-03T12:00:00Z",
            deadline_timestamp_utc="2026-09-04T17:30:00Z",
            source_snapshot_id="duplicates",
        )


def test_80_valid_scores_produce_a_paired_aggregate() -> None:
    cohort = _cohort()
    scores = {entry_id: 50.0 for entry_id in cohort.entry_ids[:80]}

    result = aggregate_top_100_scores(cohort, scores, system_points=55.0)

    assert result.status == "scored"
    assert result.valid_count == 80
    assert result.coverage == 0.8
    assert result.cohort_mean_points == 50.0
    assert result.cohort_median_points == 50.0
    assert result.system_minus_cohort_mean == 5.0


def test_79_valid_scores_abstain_instead_of_becoming_zero() -> None:
    cohort = _cohort()
    scores = {entry_id: 50.0 for entry_id in cohort.entry_ids[:79]}

    result = aggregate_top_100_scores(cohort, scores, system_points=55.0)

    assert result.status == "insufficient_coverage"
    assert result.valid_count == 79
    assert result.cohort_mean_points is None
    assert result.system_minus_cohort_mean is None


def test_rank_101_cannot_backfill_a_missing_cohort_member() -> None:
    cohort = _cohort()
    scores = {entry_id: 50.0 for entry_id in cohort.entry_ids[:79]}
    scores[1101] = 80.0

    with pytest.raises(EvaluationValidationError, match="outside the frozen"):
        aggregate_top_100_scores(cohort, scores, system_points=55.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_manager_scores_are_rejected(value: float) -> None:
    cohort = _cohort()

    with pytest.raises(EvaluationValidationError, match="finite"):
        aggregate_top_100_scores(
            cohort,
            {cohort.entry_ids[0]: value},
            system_points=55.0,
        )
