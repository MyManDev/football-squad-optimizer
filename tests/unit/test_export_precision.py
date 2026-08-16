"""Tests for the export-precision measurement.

The measurement exists to answer a question with a number instead of a preference, so what
matters here is that the number means what the report says it means: a surviving precision
is one where *no* row moves, and the recommendation is the coarsest survivor rather than
the finest.
"""

import math

import pandas as pd
import pytest

from squadopt.backtest.export_precision import (
    EXPORT_PRECISION_CONTRACT_VERSION,
    ExportPrecisionResult,
    PrecisionRow,
    measure_export_precision,
    precision_to_dict,
    precision_to_markdown,
)
from squadopt.backtest.splits import BacktestConfigurationError


def _table(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"predicted_points": values, "realized_points": [0.0] * len(values)})


def _row(result: ExportPrecisionResult, perturbation: float, decimals: int | None) -> PrecisionRow:
    return next(
        row
        for row in result.rows
        if row.relative_perturbation == perturbation and row.decimals == decimals
    )


# --- what the count means ---------------------------------------------------


def test_an_unrounded_value_moves_under_any_perturbation() -> None:
    """The finding that started this: sixteen digits records the last bit."""

    result = measure_export_precision(_table([1.25, 3.5, 7.75]), perturbations=(1e-15,))

    assert _row(result, 1e-15, None).changed_rows == 3


def test_a_zero_never_moves() -> None:
    """A relative perturbation of zero is zero, so blank rows cost nothing."""

    result = measure_export_precision(_table([0.0, 0.0, 1.0]), perturbations=(1e-15,))

    assert _row(result, 1e-15, None).changed_rows == 1


def test_a_coarse_precision_absorbs_a_small_perturbation() -> None:
    result = measure_export_precision(_table([1.234567891234]), perturbations=(1e-15,))

    assert _row(result, 1e-15, 6).changed_rows == 0
    assert _row(result, 1e-15, 6).survives


def test_a_value_sitting_on_a_rounding_boundary_does_move() -> None:
    """The failure mode a coarse precision cannot rule out, shown rather than argued."""

    result = measure_export_precision(_table([1.0000005]), perturbations=(1e-6,), decimals=(6,))

    assert _row(result, 1e-6, 6).changed_rows == 1
    assert not _row(result, 1e-6, 6).survives


def test_a_bigger_perturbation_never_moves_fewer_rows() -> None:
    values = [0.5 + index * 0.137 for index in range(200)]
    result = measure_export_precision(_table(values), perturbations=(1e-15, 1e-12))

    for decimals in (12, 9, 6):
        small = _row(result, 1e-15, decimals).changed_rows
        large = _row(result, 1e-12, decimals).changed_rows
        assert large >= small


# --- the recommendation -----------------------------------------------------


def test_the_recommendation_is_the_coarsest_survivor() -> None:
    """Quoting the finest survivor would imply the margin is thinner than it is."""

    values = [0.5 + index * 0.137 for index in range(200)]
    result = measure_export_precision(_table(values), perturbations=(1e-15,))

    recommended = result.recommended_decimals(perturbation=1e-15)

    assert recommended == 12
    assert _row(result, 1e-15, 12).survives


def test_no_survivor_reports_none_rather_than_a_number() -> None:
    result = measure_export_precision(_table([1.0000005]), perturbations=(1e-6,), decimals=(6,))

    assert result.recommended_decimals(perturbation=1e-6) is None


# --- inputs -----------------------------------------------------------------


def test_a_missing_column_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="no column"):
        measure_export_precision(_table([1.0]), column="absent")


def test_a_non_finite_value_is_refused() -> None:
    """A NaN would silently compare unequal to itself and inflate every count."""

    with pytest.raises(BacktestConfigurationError, match="finite"):
        measure_export_precision(_table([1.0, math.nan]))


@pytest.mark.parametrize("perturbation", [0.0, -1e-15, math.inf])
def test_an_invalid_perturbation_is_refused(perturbation: float) -> None:
    with pytest.raises(BacktestConfigurationError, match="perturbations"):
        measure_export_precision(_table([1.0]), perturbations=(perturbation,))


def test_an_invalid_precision_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="decimals"):
        measure_export_precision(_table([1.0]), decimals=(-1,))


# --- the record -------------------------------------------------------------


def test_the_record_names_its_contract_and_population() -> None:
    document = precision_to_dict(measure_export_precision(_table([1.0, 2.0, 0.0])))

    assert document["contract_version"] == EXPORT_PRECISION_CONTRACT_VERSION
    assert document["observations"] == 3
    assert document["non_zero_observations"] == 2
    assert document["gate_evidence"] is False


def test_the_report_states_the_unrounded_case_plainly() -> None:
    """A reader should not have to infer why two hashes differed."""

    text = precision_to_markdown(measure_export_precision(_table([1.25, 3.5])))

    assert "every non-zero row moves" in text
    assert "table hashes" in text
