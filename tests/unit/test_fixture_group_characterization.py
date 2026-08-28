"""Characterization of the FIXTURE_GROUPS rule as it exists today, in four copies.

This file records current fact before any consolidation. Four modules each define a
module-level ``FIXTURE_GROUPS`` tuple and four functions each classify a fixture count
into a group name. They do NOT all say the same thing, and the differences are the
point of these tests:

* ``squadopt.uncertainty`` (fixture_conformal, calibration) carries a TWO-element
  family ``("single", "double_plus")`` with the blank case held in a separate sentinel
  constant, because blank rows are zero by construction and are excluded from a
  conformal fit rather than calibrated.
* ``squadopt.recalibration`` (models) and ``squadopt.backtest`` (horizon_decay) carry a
  THREE-element family ``("blank", "single", "double_plus")``, because those
  measurements *report* the blank population instead of dropping it.

So the same public name ``FIXTURE_GROUPS`` means two different tuples depending on the
package it is imported from, and the classifiers split on ``count <= 0`` in one pair and
``count == 0`` in the other. Every assertion below pins observable behaviour on concrete
inputs; the inequalities are asserted as inequalities so that a refactor which quietly
makes the two families equal fails here instead of silently changing a measurement.

Nothing here is a proposal. No aliasing, renaming or consolidation is implied.
"""

import importlib
import pkgutil
from pathlib import Path

import pandas as pd

import squadopt
import squadopt.backtest
import squadopt.recalibration
import squadopt.uncertainty
from squadopt.backtest import horizon_decay
from squadopt.optimization.config import POSITIONS
from squadopt.recalibration import measurement as recalibration_measurement
from squadopt.recalibration import models as recalibration_models
from squadopt.uncertainty import calibration as uncertainty_calibration
from squadopt.uncertainty import fixture_conformal

# The two families, written out by hand so the tests do not read them from the code
# under test. These literals are the pin.
TWO_ELEMENT_FAMILY = ("single", "double_plus")
THREE_ELEMENT_FAMILY = ("blank", "single", "double_plus")

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


# --------------------------------------------------------------------------------------
# 1. Every current definition and its exact value.
# --------------------------------------------------------------------------------------


def test_fixture_conformal_defines_the_two_element_family() -> None:
    """uncertainty/fixture_conformal.py: singles and doubles only, blank held aside."""

    assert fixture_conformal.FIXTURE_GROUPS == ("single", "double_plus")
    assert fixture_conformal.BLANK_GROUP == "blank"
    # The sentinel is deliberately NOT a member of this module's tuple.
    assert fixture_conformal.BLANK_GROUP not in fixture_conformal.FIXTURE_GROUPS
    assert len(fixture_conformal.FIXTURE_GROUPS) == 2


def test_calibration_defines_the_two_element_family_and_its_own_blank_sentinel() -> None:
    """uncertainty/calibration.py: a second, independent copy of the same two-tuple."""

    assert uncertainty_calibration.FIXTURE_GROUPS == ("single", "double_plus")
    assert uncertainty_calibration.BLANK_FIXTURE_GROUP == "blank"
    assert uncertainty_calibration.BLANK_FIXTURE_GROUP not in uncertainty_calibration.FIXTURE_GROUPS
    # EQUALITY between the two members of the two-element family, asserted as an
    # equality: these two copies agree today and the refactor must keep them agreeing.
    assert uncertainty_calibration.FIXTURE_GROUPS == fixture_conformal.FIXTURE_GROUPS
    assert uncertainty_calibration.BLANK_FIXTURE_GROUP == fixture_conformal.BLANK_GROUP


def test_recalibration_models_defines_the_three_element_family() -> None:
    """recalibration/models.py: blank is a reported group, first in the tuple."""

    assert recalibration_models.FIXTURE_GROUPS == ("blank", "single", "double_plus")
    assert recalibration_models.FIXTURE_GROUPS[0] == "blank"
    assert len(recalibration_models.FIXTURE_GROUPS) == 3


def test_horizon_decay_defines_the_three_element_family() -> None:
    """backtest/horizon_decay.py: a second, independent copy of the same three-tuple."""

    assert horizon_decay.FIXTURE_GROUPS == ("blank", "single", "double_plus")
    # EQUALITY between the two members of the three-element family.
    assert horizon_decay.FIXTURE_GROUPS == recalibration_models.FIXTURE_GROUPS


def test_the_census_of_definitions_is_exactly_four_modules() -> None:
    """A census by imported VALUE: every module the name is reachable through.

    The population matters for the consolidation work, and reachability is the fact
    that matters rather than where the assignment is typed: eight import sites resolve
    ``FIXTURE_GROUPS`` today, and which family each one hands you is exactly what a
    consolidation must not silently change. Reading module attributes rather than
    scraping source text means reformatting a tuple does not break this test and only
    a real new binding does.
    """

    found: dict[str, tuple[str, ...]] = {}
    for module_info in pkgutil.walk_packages(squadopt.__path__, prefix="squadopt."):
        try:
            module = importlib.import_module(module_info.name)
        except ImportError:  # pragma: no cover - optional extras are not installed
            continue
        value = module.__dict__.get("FIXTURE_GROUPS")
        if isinstance(value, tuple):
            found[module_info.name] = value

    assert found == {
        # Defined here.
        "squadopt.uncertainty.fixture_conformal": TWO_ELEMENT_FAMILY,
        "squadopt.uncertainty.calibration": TWO_ELEMENT_FAMILY,
        "squadopt.recalibration.models": THREE_ELEMENT_FAMILY,
        "squadopt.backtest.horizon_decay": THREE_ELEMENT_FAMILY,
        # Re-exported or imported — the same name, resolving to two different families
        # depending on which package a reader imports it from.
        "squadopt.uncertainty": TWO_ELEMENT_FAMILY,
        "squadopt.recalibration": THREE_ELEMENT_FAMILY,
        "squadopt.recalibration.measurement": THREE_ELEMENT_FAMILY,
        "squadopt.recalibration.study": THREE_ELEMENT_FAMILY,
    }

    blanks: dict[str, str] = {}
    for name in ("squadopt.uncertainty.fixture_conformal", "squadopt.uncertainty.calibration"):
        module = importlib.import_module(name)
        for attribute in ("BLANK_GROUP", "BLANK_FIXTURE_GROUP"):
            if attribute in module.__dict__:
                blanks[f"{name}.{attribute}"] = module.__dict__[attribute]
    assert blanks == {
        "squadopt.uncertainty.fixture_conformal.BLANK_GROUP": "blank",
        "squadopt.uncertainty.calibration.BLANK_FIXTURE_GROUP": "blank",
    }


# 2. The membership difference, asserted as a difference.
# --------------------------------------------------------------------------------------


def test_the_two_families_are_not_equal() -> None:
    """INEQUALITY: the uncertainty family and the measurement family differ by "blank"."""

    assert fixture_conformal.FIXTURE_GROUPS == TWO_ELEMENT_FAMILY
    assert recalibration_models.FIXTURE_GROUPS == THREE_ELEMENT_FAMILY
    assert fixture_conformal.FIXTURE_GROUPS != recalibration_models.FIXTURE_GROUPS
    assert horizon_decay.FIXTURE_GROUPS != uncertainty_calibration.FIXTURE_GROUPS
    # The whole of the difference, both ways round, read from the modules themselves.
    assert set(recalibration_models.FIXTURE_GROUPS) - set(fixture_conformal.FIXTURE_GROUPS) == {
        "blank"
    }
    assert set(fixture_conformal.FIXTURE_GROUPS) - set(recalibration_models.FIXTURE_GROUPS) == set()


def test_the_same_public_name_resolves_to_two_different_tuples() -> None:
    """``squadopt.uncertainty.FIXTURE_GROUPS`` is not ``squadopt.recalibration.FIXTURE_GROUPS``.

    Which package re-export resolves to which definition is recorded here as current
    fact, because it is the collision a consolidation has to resolve deliberately.
    """

    assert squadopt.uncertainty.FIXTURE_GROUPS is fixture_conformal.FIXTURE_GROUPS
    assert squadopt.recalibration.FIXTURE_GROUPS is recalibration_models.FIXTURE_GROUPS
    assert squadopt.uncertainty.FIXTURE_GROUPS == ("single", "double_plus")
    assert squadopt.recalibration.FIXTURE_GROUPS == ("blank", "single", "double_plus")
    # INEQUALITY: one name, two meanings, live in the public interface right now.
    assert squadopt.uncertainty.FIXTURE_GROUPS != squadopt.recalibration.FIXTURE_GROUPS
    assert "FIXTURE_GROUPS" in squadopt.uncertainty.__all__
    assert "FIXTURE_GROUPS" in squadopt.recalibration.__all__


def test_only_the_calibration_blank_sentinel_is_publicly_exported() -> None:
    """``BLANK_FIXTURE_GROUP`` is public; fixture_conformal's ``BLANK_GROUP`` is not."""

    assert squadopt.uncertainty.BLANK_FIXTURE_GROUP == "blank"
    assert squadopt.uncertainty.BLANK_FIXTURE_GROUP is uncertainty_calibration.BLANK_FIXTURE_GROUP
    assert "BLANK_FIXTURE_GROUP" in squadopt.uncertainty.__all__


# --------------------------------------------------------------------------------------
# 3. Classifier equivalence -- and the one place the four classifiers disagree.
# --------------------------------------------------------------------------------------


def test_public_classifiers_agree_on_every_enumerable_count() -> None:
    """``fixture_group`` and ``fixture_group_of`` are the same function on counts >= 0.

    Hand-computed: 0 -> blank (no fixture), 1 -> single, and every count of two or more
    collapses to double_plus -- 2, 3, 5 and a full-blank-week 9 all land in one group.
    """

    expected = {
        0: "blank",
        1: "single",
        2: "double_plus",
        3: "double_plus",
        4: "double_plus",
        5: "double_plus",
        9: "double_plus",
    }
    for count, group in expected.items():
        assert fixture_conformal.fixture_group(count) == group
        assert uncertainty_calibration.fixture_group_of(count) == group
        # EQUALITY over the whole enumerable non-negative domain.
        assert fixture_conformal.fixture_group(count) == uncertainty_calibration.fixture_group_of(
            count
        )


def test_private_classifiers_agree_with_the_public_pair_on_non_negative_counts() -> None:
    """horizon_decay._fixture_group and measurement._fixture_group match on counts >= 0."""

    for count in range(0, 10):
        expected = fixture_conformal.fixture_group(count)
        assert horizon_decay._fixture_group(count) == expected
        assert recalibration_measurement._fixture_group(count) == expected
        assert uncertainty_calibration.fixture_group_of(count) == expected


def test_the_classifiers_diverge_on_negative_counts() -> None:
    """INEQUALITY at the boundary: ``count <= 0`` (public) vs ``count == 0`` (private).

    The public pair treats any non-positive count as blank. The private pair tests
    equality with zero, so a negative count falls through both branches and is reported
    as a DOUBLE gameweek. Negative counts are rejected upstream by the residual-table
    validators today, so this divergence is currently unreachable through the public
    entry points -- but the functions themselves are not equivalent, and a consolidation
    that picks either rule silently changes the other pair's behaviour here.
    """

    assert fixture_conformal.fixture_group(-1) == "blank"
    assert uncertainty_calibration.fixture_group_of(-1) == "blank"
    assert horizon_decay._fixture_group(-1) == "double_plus"
    assert recalibration_measurement._fixture_group(-1) == "double_plus"
    assert fixture_conformal.fixture_group(-1) != horizon_decay._fixture_group(-1)
    assert uncertainty_calibration.fixture_group_of(-3) != recalibration_measurement._fixture_group(
        -3
    )


def test_both_classifier_names_are_exported_from_the_uncertainty_package() -> None:
    """Two public names for one behaviour, both reachable from ``squadopt.uncertainty``."""

    assert squadopt.uncertainty.fixture_group is fixture_conformal.fixture_group
    assert squadopt.uncertainty.fixture_group_of is uncertainty_calibration.fixture_group_of
    assert "fixture_group" in squadopt.uncertainty.__all__
    assert "fixture_group_of" in squadopt.uncertainty.__all__
    # Two public names; whether they stay two objects or become one alias is a
    # consolidation's choice, so only the behavioural equality is pinned here.
    assert squadopt.uncertainty.fixture_group(2) == squadopt.uncertainty.fixture_group_of(2)


def test_the_classifier_codomain_is_the_three_element_family_not_its_own_tuple() -> None:
    """Every classifier can return "blank", which the uncertainty tuples do not contain."""

    codomain = {fixture_conformal.fixture_group(count) for count in range(0, 10)}
    assert codomain == set(THREE_ELEMENT_FAMILY)
    # EQUALITY with the measurement family; INEQUALITY with the module's own tuple.
    assert codomain == set(recalibration_models.FIXTURE_GROUPS)
    assert codomain == set(horizon_decay.FIXTURE_GROUPS)
    assert codomain != set(fixture_conformal.FIXTURE_GROUPS)
    assert codomain != set(uncertainty_calibration.FIXTURE_GROUPS)
    assert fixture_conformal.fixture_group(0) not in fixture_conformal.FIXTURE_GROUPS


# --------------------------------------------------------------------------------------
# 4. Future-member behaviour: the guard, not a prediction.
# --------------------------------------------------------------------------------------


def test_the_two_element_family_is_exactly_the_three_minus_the_blank_sentinel() -> None:
    """GUARD, NOT A PREDICTION -- what happens if one tuple gains a member the other lacks.

    Today the relation between the families is exact: the two-element tuple is a strict
    subset of the three-element one, and the three-element one is the blank sentinel
    followed by the two-element one in order. Nothing in production code enforces that;
    the tuples are four independent literals and a new group added to one of them would
    be picked up by that family's consumers alone -- the other family would keep
    reporting the old populations with no error anywhere. This test is the enforcement.
    A member added to either tuple, or added to both in a different order, fails here,
    which is the signal to decide deliberately whether the other family should follow.
    """

    two = set(fixture_conformal.FIXTURE_GROUPS)
    three = set(recalibration_models.FIXTURE_GROUPS)
    # Strict subset: every uncertainty group is a measurement group, but not the reverse.
    assert two < three
    assert not three <= two
    # Exact composition, order included: three == (blank sentinel, *two-element family).
    blank_then_two = (fixture_conformal.BLANK_GROUP, *fixture_conformal.FIXTURE_GROUPS)
    assert blank_then_two == recalibration_models.FIXTURE_GROUPS
    calibration_blank_then_two = (
        uncertainty_calibration.BLANK_FIXTURE_GROUP,
        *uncertainty_calibration.FIXTURE_GROUPS,
    )
    assert calibration_blank_then_two == horizon_decay.FIXTURE_GROUPS
    # And the classifier can name every member of the larger family and nothing else, so
    # a new group added to a tuple without a matching classifier branch would be a group
    # no row can ever land in.
    reachable = {fixture_conformal.fixture_group(count) for count in range(0, 40)}
    assert reachable == three


def test_cell_key_counts_follow_the_two_element_family_not_the_three() -> None:
    """GUARD: the calibration grid is positions x groups, so a new member resizes it.

    Hand-computed: 4 positions x 2 uncertainty groups = 8 cells, against 4 x 3 = 12 if
    the blank sentinel were ever folded into the uncertainty family. The inequality is
    the pin: a fit that started producing 12 cells would be a contract change.
    """

    assert POSITIONS == ("GK", "DEF", "MID", "FWD")
    uncertainty_cells = len(POSITIONS) * len(fixture_conformal.FIXTURE_GROUPS)
    measurement_cells = len(POSITIONS) * len(recalibration_models.FIXTURE_GROUPS)
    assert uncertainty_cells == 8
    assert measurement_cells == 12
    assert uncertainty_cells != measurement_cells


# --------------------------------------------------------------------------------------
# The membership difference, observed through a public entry point rather than asserted
# against the literals: a real fit over rows that include blanks.
# --------------------------------------------------------------------------------------


def _residual_table() -> pd.DataFrame:
    """Five chronological folds; per fold and position one single, one double, one blank.

    5 gameweeks x 4 positions x 3 players = 60 rows, of which 5 x 4 = 20 are blanks.
    """

    rows: list[dict[str, object]] = []
    player_id = 0
    for gameweek in range(1, 6):
        for position in POSITIONS:
            for count, residual in ((1, 0.4), (2, 1.2), (0, 0.0)):
                player_id += 1
                rows.append(
                    {
                        "fold_id": f"2021-22-gw{gameweek:02d}",
                        "season": "2021-22",
                        "gameweek": gameweek,
                        "player_id": player_id,
                        "position": position,
                        "residual": residual,
                        "fixture_count": count,
                    }
                )
    return pd.DataFrame(rows)


def test_a_conformal_fit_produces_no_blank_cell_and_excludes_blank_rows() -> None:
    """The two-element family is observable in the fitted result: 8 cells, none blank."""

    result = fixture_conformal.fit_and_evaluate_fixture_group_conformal(_residual_table())

    # 4 positions x 2 groups = 8 cells; no ("GK", "blank") and no blank population.
    assert set(result.fixture_cells) == {
        (position, group) for position in POSITIONS for group in ("single", "double_plus")
    }
    assert len(result.fixture_cells) == 8
    assert all(group != "blank" for _, group in result.fixture_cells)
    assert {cell.fixture_group for cell in result.fixture_cells.values()} == {
        "single",
        "double_plus",
    }

    # Scored populations: overall, each of the two groups, and each position/group cell.
    # 1 + 2 + 8 = 11 keys, and nothing named for the blank population.
    assert len(result.fixture_metrics) == 11
    assert "blank" not in result.fixture_metrics
    assert not any(key.endswith("/blank") for key in result.fixture_metrics)
    assert set(result.position_metrics) == set(result.fixture_metrics)

    # Blank rows are counted and dropped, not calibrated: 60 rows, 20 blanks, 40 kept;
    # floor(5 folds x 0.60) = 3 calibration folds x 4 positions x 2 = 24 rows, and the
    # remaining 2 folds x 8 = 16 evaluation rows, 8 per group.
    assert result.diagnostics["rows_total"] == 60
    assert result.diagnostics["blank_rows_excluded"] == 20
    assert result.diagnostics["calibration_rows"] == 24
    assert result.diagnostics["evaluation_rows"] == 16
    assert result.diagnostics["evaluation_rows_by_group"] == {"single": 8, "double_plus": 8}
    assert len(result.calibration_folds) == 3
    assert len(result.evaluation_folds) == 2
