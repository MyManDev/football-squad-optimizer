"""The record's claim about an arm is derived from that arm's interval, not written by hand.

A record's prose is where an overstated result hides: a sentence is not audited the way a
number is, and a negative is audited least of all, because it reads as modesty. This pins the
derivation so that no future edit can put "costs decisions" over an interval covering zero.
"""

from scripts.measure_participation_composition import _claim


def _paired(lower: float | None, upper: float | None, mean: float) -> dict[str, object]:
    return {
        "interval": None if lower is None or upper is None else [lower, upper],
        "mean_difference": mean,
        "paired_decisions": 37,
    }


def test_an_interval_covering_zero_claims_neither_a_loss_nor_a_gain() -> None:
    sentence = _claim("composed", _paired(-3.569, 0.164, -1.405))
    assert "No loss or gain is claimed" in sentence
    assert "cannot separate it from nothing" in sentence
    assert "-1.405" in sentence and "37" in sentence
    # The words a hand-written sentence would have reached for are absent.
    assert "costs" not in sentence and "worse" not in sentence


def test_an_interval_below_zero_reads_as_a_loss_and_above_zero_as_a_gain() -> None:
    loss = _claim("state_split", _paired(-6.649, -1.539, -3.432))
    assert "excludes zero" in loss and "loss of -3.432" in loss
    gain = _claim("candidate", _paired(0.5, 2.0, 1.25))
    assert "gain of +1.250" in gain
    # Even an excluded zero is qualified by the population it was read on.
    assert "a single season" in loss and "a single season" in gain


def test_a_boundary_touching_zero_is_not_an_exclusion() -> None:
    """Zero at either end covers zero. A clause that read it as excluded would claim more."""

    assert "No loss or gain is claimed" in _claim("x", _paired(-2.0, 0.0, -1.0))
    assert "No loss or gain is claimed" in _claim("x", _paired(0.0, 2.0, 1.0))


def test_an_arm_without_an_interval_claims_nothing() -> None:
    sentence = _claim("x", _paired(None, None, -1.0))
    assert "no interval" in sentence and "nothing about its difference is claimed" in sentence
