"""Tests for the export-precision measurement and the bytes an export is written in.

The measurement exists to answer a question with a number instead of a preference, so what
matters here is that the number means what the report says it means: a surviving precision
is one where *no* row moves, and the recommendation is the coarsest survivor rather than
the finest.

The second half of the file holds the other half of the same claim: identical values still
cross machines badly if the line terminator does not.
"""

import math
from pathlib import Path

import pandas as pd
import pytest

from squadopt.backtest.export_precision import (
    EXPORT_PRECISION_CONTRACT_VERSION,
    ExportPrecisionResult,
    PrecisionRow,
    measure_export_precision,
    precision_to_dict,
    precision_to_markdown,
    write_export_table,
)
from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.preflight import compute_table_sha256


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


# --- the bytes --------------------------------------------------------------
#
# Rounding the values is half of "two machines write the same bytes"; the line terminator is
# the other half. `DataFrame.to_csv` defaults to os.linesep, and `compute_table_sha256`
# digests the raw file bytes, so an export written with the default identifies the operating
# system as much as the table.
#
# Note what these tests can and cannot see. On a platform where os.linesep is already "\n"
# the default and the canonical form produce identical bytes, so a regression here is
# invisible on Linux CI and fails only on Windows. That asymmetry is exactly why the defect
# survived: both owners who compared hashes were on Windows, where the bytes agreed with
# each other and with nothing else. The pinned digest below is the part that holds
# everywhere.


def _residual_export() -> pd.DataFrame:
    """A small stand-in for an export table: two rows, one rounded float column."""

    return pd.DataFrame(
        {
            "player_id": [1, 2],
            "predicted_points": [1.5, -0.25],
        }
    )


def test_an_export_is_written_with_line_feeds_only(tmp_path: Path) -> None:
    path = tmp_path / "residuals.csv"

    write_export_table(_residual_export(), path)

    assert b"\r" not in path.read_bytes()


def test_an_export_writes_the_bytes_every_platform_agrees_on(tmp_path: Path) -> None:
    path = tmp_path / "residuals.csv"

    write_export_table(_residual_export(), path)

    assert path.read_bytes() == b"player_id,predicted_points\n1,1.5\n2,-0.25\n"


def test_the_digest_of_a_known_export_is_pinned(tmp_path: Path) -> None:
    """The digest a manifest records, pinned so any change to the bytes has to be declared.

    This is the check that holds on every platform. It moves if the terminator changes, if
    float formatting changes, or if the column order changes — all of which would make a
    recorded `table_sha256` stop identifying the table it claims to.
    """

    path = tmp_path / "residuals.csv"

    write_export_table(_residual_export(), path)

    assert (
        compute_table_sha256(path)
        == "a259b4c2163109900ad042ee55f730de307154fbde5a59a176d93ec1971e6fc5"
    )


def test_a_missing_parent_directory_is_created(tmp_path: Path) -> None:
    """A caller may name an output path without preparing it."""

    path = tmp_path / "nested" / "deeper" / "residuals.csv"

    write_export_table(_residual_export(), path)

    assert path.exists()
