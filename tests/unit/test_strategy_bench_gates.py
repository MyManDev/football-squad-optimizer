"""The direction gate compares three bands on the same explicitly reported folds."""

import pytest
import scripts.measure_strategy_bench as bench


def _outcome(wins_big: bool) -> bench.BandOutcome:
    return bench.BandOutcome(
        realized_points=16.0 if wins_big else 10.0,
        rival_realized_points=10.0,
        claimed_cost=0.0,
        hit_points=0.0,
        overlap_count=5,
    )


def test_unpaired_weeks_cannot_give_the_differential_an_artificial_direction_pass() -> None:
    rows = {
        "paired-win": {band: _outcome(True) for band in bench.BANDS},
        "paired-loss": {
            "control": _outcome(True),
            "high_overlap": _outcome(True),
            "differential": _outcome(False),
        },
        "missing-1": {"control": _outcome(False), "high_overlap": _outcome(False)},
        "missing-2": {"control": _outcome(False), "high_overlap": _outcome(False)},
    }

    frequency, passes, coverage = bench._direction_gate(rows, list(rows))

    # The old band-specific means tied at 0.5 and passed. On the common population
    # the comparator bands win both weeks, while the differential wins only one.
    assert frequency == {"control": 1.0, "high_overlap": 1.0, "differential": 0.5}
    assert passes is False
    assert coverage["paired_fold_ids"] == ["paired-loss", "paired-win"]
    assert coverage["paired_share"] == 0.5
    assert coverage["feasible_fold_count_by_band"] == {
        "control": 4,
        "high_overlap": 4,
        "differential": 2,
    }
    assert coverage["excluded_fold_ids_by_band"] == {
        "control": [],
        "high_overlap": [],
        "differential": ["missing-1", "missing-2"],
    }


def test_all_bands_seen_on_disjoint_folds_are_not_a_common_population() -> None:
    rows = {
        "a": {"control": _outcome(False), "high_overlap": _outcome(True)},
        "b": {"control": _outcome(False), "differential": _outcome(True)},
    }

    frequency, passes, coverage = bench._direction_gate(rows, ["a", "b", "control-unproven"])

    assert frequency == dict.fromkeys(bench.BANDS)
    assert passes is None
    assert coverage["paired_fold_count"] == 0
    assert coverage["eligible_fold_count"] == 3
    assert coverage["excluded_fold_ids"] == ["a", "b", "control-unproven"]
    assert coverage["excluded_fold_ids_by_band"] == {
        "control": ["control-unproven"],
        "high_overlap": ["b", "control-unproven"],
        "differential": ["a", "control-unproven"],
    }


def test_empty_population_is_unmeasured_not_zero_or_pass() -> None:
    frequency, passes, coverage = bench._direction_gate({}, [])

    assert frequency == dict.fromkeys(bench.BANDS)
    assert passes is None
    assert coverage["paired_share"] is None


@pytest.mark.parametrize("differential_wins", [False, True])
def test_complete_population_preserves_the_existing_tie_rule(differential_wins: bool) -> None:
    rows = {"a": {band: _outcome(differential_wins) for band in bench.BANDS}}

    frequency, passes, coverage = bench._direction_gate(rows, ["a"])

    assert frequency == {band: float(differential_wins) for band in bench.BANDS}
    assert passes is True
    assert coverage["paired_share"] == 1.0
    assert coverage["excluded_fold_ids"] == []


def test_scored_rows_outside_the_declared_population_are_refused() -> None:
    with pytest.raises(ValueError, match="eligible population"):
        bench._direction_gate({"unexpected": {"control": _outcome(True)}}, ["declared"])
