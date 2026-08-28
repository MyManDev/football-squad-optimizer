"""Characterization of the four nearest-rank quantile rules that live in this codebase.

Three of them are the finite-sample split-conformal rule ``k = min(n, ceil((n + 1) * q))``
over sorted absolute residuals; the fourth, ``squadopt.risk.evaluation._nearest_rank``, is a
DELIBERATELY DIFFERENT lower-tail reporting rule ``k = max(1, ceil(p * n))`` over *signed*
values, with no ``(n + 1)`` correction and no cap. These tests pin the current behaviour of
each copy on hand-computed inputs so a later consolidation can be shown to preserve it — and
they pin the divergences AS divergences, with the exact inequality asserted, so that a future
consolidation cannot quietly absorb the risk rule into the conformal one.

All four helpers are private (leading underscore). Importing and calling them directly is
intentional here: characterization must exercise the real functions, and reimplementing the
formula in the test would pin nothing. No helper is re-derived in Python below; every expected
value is hand-computed and the arithmetic is shown in a comment beside it.

Two tests drive a probability outside the range the configuration objects validate
(``0 < confidence_level < 1``): ``q = 0.0`` and ``p = 1.5``. The ``min(n, ...)`` cap does NOT
need them — the in-range rows ``(3, 0.80)`` and ``(10, 0.95)`` of the shared table observe it
binding. What only these two reach is the ``max(1, ...)`` floor and the absence of a cap on
the risk rule. They record what the code does today; they do not endorse it, and an explicit
domain guard added later is an improvement that should update them deliberately.
"""

import pytest

from squadopt.recalibration.models import RecalibrationValidationError
from squadopt.recalibration.study import _finite_sample_quantile as study_quantile
from squadopt.risk.evaluation import _nearest_rank as risk_nearest_rank
from squadopt.uncertainty.calibration import _conformal_radius as canonical_radius
from squadopt.uncertainty.fixture_conformal import _conformal_radius as fixture_radius

# The conformal rank table, shared by all three conformal copies.
# Each row is (n, q, expected one-based rank) with the arithmetic beside it.
SHARED_RANK_CASES: tuple[tuple[int, float, int], ...] = (
    (1, 0.90, 1),  # (1+1)*0.90 = 1.8  -> ceil 2  -> min(1, 2) = 1   [n = 1, cap binds]
    (3, 0.25, 1),  # (3+1)*0.25 = 1.0  -> ceil 1  -> min(3, 1) = 1   [exact integer boundary]
    (4, 0.50, 3),  # (4+1)*0.50 = 2.5  -> ceil 3  -> min(4, 3) = 3
    (5, 0.50, 3),  # (5+1)*0.50 = 3.0  -> ceil 3  -> min(5, 3) = 3   [exact integer boundary]
    (7, 0.50, 4),  # (7+1)*0.50 = 4.0  -> ceil 4  -> min(7, 4) = 4   [exact integer boundary]
    (9, 0.90, 9),  # (9+1)*0.90 = 9.0  -> ceil 9  -> min(9, 9) = 9   [integer boundary, == n]
    (10, 0.90, 10),  # (10+1)*0.90 = 9.9   -> ceil 10 -> min(10, 10) = 10  [rank == n, uncapped]
    (19, 0.90, 18),  # (19+1)*0.90 = 18.0  -> ceil 18 -> min(19, 18) = 18  [integer boundary]
    (20, 0.80, 17),  # (20+1)*0.80 = 16.8  -> ceil 17 -> min(20, 17) = 17
    (3, 0.80, 3),  # (3+1)*0.80 = 3.2   -> ceil 4  -> min(3, 4) = 3   [CAP binds]
    (10, 0.95, 10),  # (10+1)*0.95 = 10.45 -> ceil 11 -> min(10, 11) = 10 [CAP binds]
)

# The risk rule's own table: (n, p, expected one-based rank), no (n+1), no cap.
NEAREST_RANK_CASES: tuple[tuple[int, float, int], ...] = (
    (1, 0.90, 1),  # ceil(0.90*1) = ceil(0.9)  = 1 -> max(1, 1) = 1
    (3, 0.25, 1),  # ceil(0.25*3) = ceil(0.75) = 1 -> max(1, 1) = 1
    (4, 0.50, 2),  # ceil(0.50*4) = ceil(2.0)  = 2 -> max(1, 2) = 2  [exact integer boundary]
    (5, 0.50, 3),  # ceil(0.50*5) = ceil(2.5)  = 3 -> max(1, 3) = 3
    (9, 0.90, 9),  # ceil(0.90*9) = ceil(8.1)  = 9 -> max(1, 9) = 9
    (10, 0.90, 9),  # ceil(0.90*10) = ceil(9.0) = 9 -> max(1, 9) = 9  [exact integer boundary]
    (20, 0.80, 16),  # ceil(0.80*20) = ceil(16.0) = 16 -> max(1, 16) = 16 [integer boundary]
    (3, 0.80, 3),  # ceil(0.80*3) = ceil(2.4000000000000004) = 3 -> max(1, 3) = 3
    (10, 0.95, 10),  # ceil(0.95*10) = ceil(9.5) = 10 -> max(1, 10) = 10
)

# (n, probability, conformal rank, risk rank) where the two rules provably disagree.
DISAGREEMENT_CASES: tuple[tuple[int, float, int, int], ...] = (
    # ceil((4+1)*0.50) = ceil(2.5) = 3   vs  ceil(0.50*4) = ceil(2.0) = 2
    (4, 0.50, 3, 2),
    # ceil((10+1)*0.90) = ceil(9.9) = 10 vs  ceil(0.90*10) = ceil(9.0) = 9
    (10, 0.90, 10, 9),
    # ceil((20+1)*0.80) = ceil(16.8) = 17 vs ceil(0.80*20) = ceil(16.0) = 16
    (20, 0.80, 17, 16),
    # ceil((20+1)*0.90) = ceil(18.9) = 19 vs ceil(0.90*20) = ceil(18.0) = 18
    (20, 0.90, 19, 18),
)


def _scrambled_ramp(size: int) -> list[float]:
    """A deterministic non-sorted permutation of ``[1.0, 2.0, ..., size]``.

    Handing the helpers an out-of-order list is what makes the returned value pin the
    *order statistic*: for this ramp the k-th smallest is exactly ``float(k)``, so the
    expected radius for a hand-computed rank k is ``float(k)`` with no further arithmetic.
    """

    values = [float(index) for index in range(1, size + 1)]
    half = size // 2
    return values[half:][::-1] + values[:half]


@pytest.mark.parametrize(("count", "confidence", "expected_rank"), SHARED_RANK_CASES)
def test_canonical_conformal_rule_returns_hand_computed_radius_and_rank(
    count: int, confidence: float, expected_rank: int
) -> None:
    """calibration._conformal_radius: k = min(n, ceil((n+1)*q)) over sorted |residual|."""

    radius, rank = canonical_radius(_scrambled_ramp(count), confidence)

    assert rank == expected_rank
    # k-th smallest of [1.0 .. n] is float(k).
    assert radius == float(expected_rank)


@pytest.mark.parametrize(("count", "confidence", "expected_rank"), SHARED_RANK_CASES)
def test_fixture_conformal_copy_agrees_with_the_canonical_rule(
    count: int, confidence: float, expected_rank: int
) -> None:
    """EQUALITY: the deliberate copy in fixture_conformal.py is the canonical rule.

    Includes both cap rows — (3, 0.80) and (10, 0.95) — where ceil((n+1)*q) > n.
    """

    values = _scrambled_ramp(count)

    assert fixture_radius(values, confidence) == canonical_radius(values, confidence)
    assert fixture_radius(values, confidence) == (float(expected_rank), expected_rank)


@pytest.mark.parametrize(("count", "confidence", "expected_rank"), SHARED_RANK_CASES)
def test_study_quantile_agrees_numerically_on_already_positive_scores(
    count: int, confidence: float, expected_rank: int
) -> None:
    """EQUALITY: study._finite_sample_quantile picks the same order statistic.

    Its callers hand it ``abs(residual) / scale``, i.e. already-positive standardized
    scores, so on this positive ramp it selects the same element as the canonical rule.
    """

    values = _scrambled_ramp(count)

    assert study_quantile(values, confidence) == canonical_radius(values, confidence)[0]
    assert study_quantile(values, confidence) == float(expected_rank)


def test_the_canonical_rule_reports_the_rank_the_third_copy_discards() -> None:
    """The canonical rule carries its rank into artifacts; the third copy's is unobservable.

    Only the VALUE is pinned. The third copy's return shape is deliberately not asserted:
    a consolidation that made every copy return ``(radius, rank)`` and had this call site
    unpack ``[0]`` would change nothing observable, and must not fail here.
    """

    values = _scrambled_ramp(10)

    assert canonical_radius(values, 0.90) == (10.0, 10)
    assert study_quantile(values, 0.90) == canonical_radius(values, 0.90)[0]


def test_canonical_and_fixture_rules_fold_signed_residuals_through_abs() -> None:
    """Both conformal copies sort ``abs(value)``, so sign is discarded before ranking."""

    # abs -> [1.0, 2.0, 3.0, 6.0]; (4+1)*0.50 = 2.5 -> ceil 3 -> min(4, 3) = 3 -> 3.0
    values = [-6.0, -2.0, 1.0, 3.0]

    assert canonical_radius(values, 0.50) == (3.0, 3)
    assert fixture_radius(values, 0.50) == (3.0, 3)


def test_one_signed_input_splits_all_three_rules_apart() -> None:
    """INEQUALITY: abs-folding, sign-preserving conformal, and the signed risk rule differ.

    The same four values give three different answers, which is the whole reason the copies
    cannot be merged blindly.
    """

    values = [-6.0, -2.0, 1.0, 3.0]

    # canonical: abs -> [1.0, 2.0, 3.0, 6.0], rank 3 -> 3.0
    canonical = canonical_radius(values, 0.50)[0]
    # study: NO abs, sorted -> [-6.0, -2.0, 1.0, 3.0], rank 3 -> 1.0
    study = study_quantile(values, 0.50)
    # risk: NO abs, sorted -> [-6.0, -2.0, 1.0, 3.0], rank max(1, ceil(2.0)) = 2 -> -2.0
    risk = risk_nearest_rank(values, 0.50)

    assert canonical == 3.0
    assert study == 1.0
    assert risk == -2.0
    assert study != canonical
    assert risk != canonical
    assert risk != study


def test_risk_rule_reports_a_negative_lower_tail_value() -> None:
    """The risk rule is a signed lower-tail report; a conformal radius can never be negative."""

    # sorted -> [-9.0, -4.0, -1.0, 2.0, 8.0]; ceil(0.25*5) = ceil(1.25) = 2 -> -4.0
    values = [8.0, -1.0, -9.0, 2.0, -4.0]

    assert risk_nearest_rank(values, 0.25) == -4.0
    assert risk_nearest_rank(values, 0.25) < 0.0
    # The canonical rule on the same input: abs -> [1.0, 2.0, 4.0, 8.0, 9.0],
    # (5+1)*0.25 = 1.5 -> ceil 2 -> min(5, 2) = 2 -> 2.0.
    assert canonical_radius(values, 0.25) == (2.0, 2)
    assert risk_nearest_rank(values, 0.25) != canonical_radius(values, 0.25)[0]


@pytest.mark.parametrize(("count", "probability", "expected_rank"), NEAREST_RANK_CASES)
def test_risk_nearest_rank_returns_hand_computed_order_statistic(
    count: int, probability: float, expected_rank: int
) -> None:
    """risk.evaluation._nearest_rank: k = max(1, ceil(p*n)) over sorted signed values."""

    # The ramp is positive, so signed order and abs order coincide: only the rank differs.
    assert risk_nearest_rank(_scrambled_ramp(count), probability) == float(expected_rank)


@pytest.mark.parametrize(
    ("count", "probability", "conformal_rank", "risk_rank"), DISAGREEMENT_CASES
)
def test_risk_rule_provably_disagrees_with_the_conformal_rank(
    count: int, probability: float, conformal_rank: int, risk_rank: int
) -> None:
    """INEQUALITY (the point of this file): the missing (n+1) correction shifts the rank.

    On a positive ramp — where sign and abs cannot explain any difference — the two rules
    still select different order statistics. A consolidation that made these equal would be
    a behaviour change to the risk screening's downside reporting, not a refactor.
    """

    values = _scrambled_ramp(count)

    conformal_radius_value, observed_conformal_rank = canonical_radius(values, probability)
    observed_risk_value = risk_nearest_rank(values, probability)

    assert observed_conformal_rank == conformal_rank
    assert conformal_radius_value == float(conformal_rank)
    assert observed_risk_value == float(risk_rank)
    assert observed_risk_value != conformal_radius_value
    # The conformal rule is always the more conservative (higher) rank here.
    assert conformal_rank == risk_rank + 1


def test_when_the_conformal_cap_binds_the_two_rules_agree_in_rank_but_not_in_value() -> None:
    """EQUALITY in rank, INEQUALITY in value, at the cap boundary.

    n = 3, p = q = 0.80. Conformal: (3+1)*0.80 = 3.2 -> ceil 4 -> capped to 3.
    Risk: ceil(0.80*3) = ceil(2.4000000000000004) = 3. Same rank — but the conformal rule
    ranks |value| and the risk rule ranks the signed value, so the answers still differ.
    """

    values = [-7.0, 1.0, 2.0]

    radius, rank = canonical_radius(values, 0.80)

    # abs -> [1.0, 2.0, 7.0], 3rd -> 7.0
    assert (radius, rank) == (7.0, 3)
    # signed -> [-7.0, 1.0, 2.0], 3rd -> 2.0
    assert risk_nearest_rank(values, 0.80) == 2.0
    assert risk_nearest_rank(values, 0.80) != radius


def test_a_single_observation_collapses_all_four_rules_to_that_observation() -> None:
    """EQUALITY at n = 1: every rule returns the only value, at rank 1.

    Conformal: (1+1)*0.90 = 1.8 -> ceil 2 -> min(1, 2) = 1 [the cap binds].
    Risk: ceil(0.90*1) = ceil(0.9) = 1 -> max(1, 1) = 1 [the floor is not needed].
    """

    values = [4.25]

    assert canonical_radius(values, 0.90) == (4.25, 1)
    assert fixture_radius(values, 0.90) == (4.25, 1)
    assert study_quantile(values, 0.90) == 4.25
    assert risk_nearest_rank(values, 0.90) == 4.25


def test_a_single_negative_observation_still_splits_abs_folding_from_the_signed_rules() -> None:
    """INEQUALITY at n = 1: the conformal copies report +4.25, the signed rules report -4.25."""

    values = [-4.25]

    assert canonical_radius(values, 0.90) == (4.25, 1)
    assert fixture_radius(values, 0.90) == (4.25, 1)
    assert study_quantile(values, 0.90) == -4.25
    assert risk_nearest_rank(values, 0.90) == -4.25
    assert study_quantile(values, 0.90) != canonical_radius(values, 0.90)[0]


def test_ties_are_resolved_by_rank_position_and_can_expose_the_rank_divergence() -> None:
    """Duplicated values: the rank still moves, and here it lands on a different value."""

    # sorted -> [1.0, 1.0, 4.0, 4.0]
    values = [4.0, 1.0, 4.0, 1.0]

    # (4+1)*0.50 = 2.5 -> ceil 3 -> min(4, 3) = 3 -> 3rd element = 4.0
    assert canonical_radius(values, 0.50) == (4.0, 3)
    assert fixture_radius(values, 0.50) == (4.0, 3)
    assert study_quantile(values, 0.50) == 4.0
    # ceil(0.50*4) = 2 -> 2nd element = 1.0
    assert risk_nearest_rank(values, 0.50) == 1.0
    assert risk_nearest_rank(values, 0.50) != canonical_radius(values, 0.50)[0]


def test_a_run_of_ties_can_mask_the_rank_divergence_behind_an_equal_value() -> None:
    """The ranks still differ (3 vs 2); the tie run makes the returned values coincide.

    Pinned so nobody reads an equal value here as evidence that the rules agree.
    """

    # sorted -> [2.0, 2.0, 2.0, 5.0]; conformal rank 3 -> 2.0, risk rank 2 -> 2.0
    values = [5.0, 2.0, 2.0, 2.0]

    assert canonical_radius(values, 0.50) == (2.0, 3)
    assert risk_nearest_rank(values, 0.50) == 2.0
    assert risk_nearest_rank(values, 0.50) == canonical_radius(values, 0.50)[0]


def test_both_conformal_copies_refuse_empty_input() -> None:
    """EMPTY INPUT: n = 0 -> rank = min(0, ceil(1*0.90)) = 0 -> ordered[-1] on an empty list.

    DECISION POINT, not a contract: the lookup failure is an accident of indexing, and
    both call sites already guard emptiness upstream. ``LookupError`` is asserted rather
    than ``IndexError`` so that giving these copies the typed guard the third one already
    has stays a deliberate change, not a test break.
    """

    with pytest.raises(LookupError):
        canonical_radius([], 0.90)
    with pytest.raises(LookupError):
        fixture_radius([], 0.90)


def test_study_quantile_raises_a_typed_domain_error_on_empty_input() -> None:
    """INEQUALITY in empty-input handling: a typed RecalibrationValidationError, not IndexError.

    This is the third copy's one behavioural improvement over the canonical rule, and a
    consolidation must decide deliberately which of the two behaviours survives.
    """

    with pytest.raises(RecalibrationValidationError, match=r"at least one standardized residual"):
        study_quantile([], 0.90)


def test_risk_nearest_rank_refuses_empty_input() -> None:
    """EMPTY INPUT: rank = max(1, ceil(0.90*0)) = 1 -> ordered[0] on an empty list.

    Same decision point as the conformal copies: the caller guards emptiness, so this
    pins refusal rather than the particular lookup error.
    """

    with pytest.raises(LookupError):
        risk_nearest_rank([], 0.90)


def test_zero_probability_wraps_the_conformal_rules_to_the_largest_value() -> None:
    """INEQUALITY at q = 0: rank 0 indexes ordered[-1]; the risk rule floors to rank 1.

    q = 0 is outside the range the configuration objects accept (strictly between 0 and 1);
    this pins the raw helpers' current behaviour, which is the only way to observe that the
    conformal rules have no lower guard while the risk rule does.
    """

    # sorted -> [1.0, 2.0, 5.0]; (3+1)*0.0 = 0.0 -> ceil 0 -> min(3, 0) = 0 -> ordered[-1]
    values = [5.0, 1.0, 2.0]

    assert canonical_radius(values, 0.0) == (5.0, 0)
    assert fixture_radius(values, 0.0) == (5.0, 0)
    assert study_quantile(values, 0.0) == 5.0
    # ceil(0.0*3) = 0 -> max(1, 0) = 1 -> ordered[0] = 1.0
    assert risk_nearest_rank(values, 0.0) == 1.0
    assert risk_nearest_rank(values, 0.0) != canonical_radius(values, 0.0)[0]


def test_probability_above_one_is_capped_by_the_conformal_rules_and_overruns_the_risk_rule() -> (
    None
):
    """INEQUALITY: the missing ``min(n, ...)`` cap becomes an IndexError.

    p = 1.5 is outside the validated configuration range; it is the only way to observe the
    cap as behaviour. Conformal: (3+1)*1.5 = 6.0 -> ceil 6 -> min(3, 6) = 3 -> the maximum.
    Risk: ceil(1.5*3) = ceil(4.5) = 5 -> max(1, 5) = 5 -> ordered[4] on a 3-element list.
    """

    values = [5.0, 1.0, 2.0]

    # The conformal cap is already observed in range by the (3, 0.80) and (10, 0.95)
    # rows of the shared table; what this case adds is the risk rule's missing cap.
    assert canonical_radius(values, 1.5) == (5.0, 3)
    with pytest.raises(IndexError):
        risk_nearest_rank(values, 1.5)
