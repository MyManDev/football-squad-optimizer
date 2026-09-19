"""The three properties the tail-mean rank criterion is allowed to be trusted on.

The null reproduces today's mean selector, a constant per-rival edge cannot move the pick,
and an exact tie goes to the control. The first is what makes the measurement's null arm an
instrument check rather than a second result; the second is the whole licence for preferring
a tail mean to a rank probability; the third is what stops a criterion that cannot separate
the menu from answering arbitrarily.
"""

import random
from fractions import Fraction

import pytest

from squadopt.experiments.config import ExperimentConfigurationError
from squadopt.experiments.rank_tail_selector import (
    NULL_TAIL_FRACTION,
    TAIL_FRACTION_GRID,
    TailSide,
    select_rank_tail_candidate,
    tail_side_from_gap,
)

SIDES = (TailSide.BEHIND, TailSide.LEVEL, TailSide.AHEAD)


def _fold(
    seed: int, *, candidates: int = 8, rivals: int = 14, scenarios: int = 200
) -> tuple[list[list[float]], list[list[float]], list[TailSide]]:
    """One deterministic pseudo-fold: whole-point scores, every side represented.

    Scores are whole points because official FPL scores are, and because an exact tie has to
    be constructible for the tie-break test to mean anything.
    """

    generator = random.Random(seed)
    candidate_rows = [
        [float(generator.randint(20, 110)) for _ in range(scenarios)] for _ in range(candidates)
    ]
    rival_rows = [
        [float(generator.randint(20, 110)) for _ in range(scenarios)] for _ in range(rivals)
    ]
    sides = [SIDES[index % len(SIDES)] for index in range(rivals)]
    return candidate_rows, rival_rows, sides


def _mean_selector_pick(candidate_rows: list[list[float]]) -> int:
    """Today's rule, written independently of the module under test: the highest mean."""

    totals = [sum(row) for row in candidate_rows]
    return max(range(len(totals)), key=totals.__getitem__)


def _mean_gap_selector_pick(
    candidate_rows: list[list[float]], rival_rows: list[list[float]]
) -> int:
    """The same rule stated as a gap: the rival term is a constant and cannot move it."""

    totals = [
        sum(
            sum(own - theirs for own, theirs in zip(row, rival, strict=True))
            for rival in rival_rows
        )
        for row in candidate_rows
    ]
    return max(range(len(totals)), key=totals.__getitem__)


@pytest.mark.parametrize("seed", range(20))
def test_the_null_arm_reproduces_the_mean_selector_exactly(seed: int) -> None:
    """At a tail fraction of one the criterion is the mean selector, on every fold."""

    candidate_rows, rival_rows, sides = _fold(seed)
    selection = select_rank_tail_candidate(
        candidate_rows, rival_rows, sides, tail_fraction=NULL_TAIL_FRACTION
    )
    assert selection.selected_index == _mean_selector_pick(candidate_rows)
    assert selection.selected_index == _mean_gap_selector_pick(candidate_rows, rival_rows)
    # Bit for bit, not merely the same winner: the null's ordering is the mean's ordering.
    ranked = sorted(
        range(len(candidate_rows)),
        key=lambda index: (-selection.criterion_by_candidate[index], index),
    )
    by_mean = sorted(
        range(len(candidate_rows)), key=lambda index: (-sum(candidate_rows[index]), index)
    )
    assert ranked == by_mean


@pytest.mark.parametrize("tail_fraction", TAIL_FRACTION_GRID)
@pytest.mark.parametrize("shift", [7.5, -13.25, 100.125])
def test_a_constant_rival_edge_cannot_change_the_pick(
    tail_fraction: Fraction, shift: float
) -> None:
    """The measured failure of the rank-probability line was location; this is immune to it.

    Every candidate's term for the shifted rival moves by the same amount, so the argmax
    cannot move. The check is exact rather than tolerant: the criterion is an integer and the
    shift is representable at the points scale, so the differences are identical.
    """

    candidate_rows, rival_rows, sides = _fold(seed=7)
    before = select_rank_tail_candidate(
        candidate_rows, rival_rows, sides, tail_fraction=tail_fraction
    )
    for index in range(len(rival_rows)):
        shifted = [list(row) for row in rival_rows]
        shifted[index] = [value + shift for value in shifted[index]]
        after = select_rank_tail_candidate(
            candidate_rows, shifted, sides, tail_fraction=tail_fraction
        )
        assert after.selected_index == before.selected_index
        moved = {
            later - earlier
            for later, earlier in zip(
                after.criterion_by_candidate, before.criterion_by_candidate, strict=True
            )
        }
        assert len(moved) == 1


@pytest.mark.parametrize("tail_fraction", TAIL_FRACTION_GRID)
def test_the_control_wins_every_tie(tail_fraction: Fraction) -> None:
    """Matching ``scenarios/selection.py:258-262``: an exact tie keeps the lowest index."""

    _, rival_rows, sides = _fold(seed=3, scenarios=200)
    row = [float(value) for value in _fold(seed=4, candidates=1, scenarios=200)[0][0]]

    # Every candidate identical: the criterion cannot separate them and must return control.
    identical = [list(row) for _ in range(6)]
    flat = select_rank_tail_candidate(identical, rival_rows, sides, tail_fraction=tail_fraction)
    assert flat.selected_index == 0
    assert len(set(flat.criterion_by_candidate)) == 1

    # The control tied at the top by a later candidate, with a worse one between them.
    worse = [value - 1.0 for value in row]
    menu = [list(row), list(worse), list(row)]
    tied = select_rank_tail_candidate(menu, rival_rows, sides, tail_fraction=tail_fraction)
    assert tied.selected_index == 0
    assert tied.criterion_by_candidate[0] == tied.criterion_by_candidate[2]
    assert tied.criterion_by_candidate[1] < tied.criterion_by_candidate[0]


def test_the_side_rule_reads_the_published_band_and_no_second_constant() -> None:
    """Level is the closed band; behind and ahead are strictly outside it."""

    assert tail_side_from_gap(-124.0, 123.6) is TailSide.BEHIND
    assert tail_side_from_gap(-123.6, 123.6) is TailSide.LEVEL
    assert tail_side_from_gap(123.6, 123.6) is TailSide.LEVEL
    assert tail_side_from_gap(124.0, 123.6) is TailSide.AHEAD
    with pytest.raises(ExperimentConfigurationError):
        tail_side_from_gap(0.0, -1.0)


def test_an_undeclared_arm_is_refused() -> None:
    """The searched space is the pre-registered space; a level nobody froze is not run."""

    candidate_rows, rival_rows, sides = _fold(seed=1, scenarios=100)
    with pytest.raises(ExperimentConfigurationError):
        select_rank_tail_candidate(candidate_rows, rival_rows, sides, tail_fraction=Fraction(1, 4))


def test_the_criterion_cannot_reach_the_member_path() -> None:
    """Additive by construction: the laboratory module imports no product package.

    ``lint-imports`` already forbids the product from importing the laboratory. This is the
    other direction, and it is what keeps this measurement unable to change a published
    plan: nothing here can touch the strategies, the advice builder or a payload.
    """

    from pathlib import Path

    import squadopt.experiments.rank_tail_selector as module

    source = Path(str(module.__file__)).read_text(encoding="utf-8")
    for forbidden in ("squadopt.application", "squadopt.live", "squadopt.api", "squadopt.platform"):
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source
