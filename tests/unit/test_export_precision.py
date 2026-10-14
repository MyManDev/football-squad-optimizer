"""Tests for the bytes an export is written in.

The export-precision measurement (docs/export_precision.md) settled how many decimals an
export keeps; its runner and module have since been removed. What stays is the other half of
the same claim: identical values still cross machines badly if the line terminator does not.
"""

from pathlib import Path

import pandas as pd

from squadopt.data.tables import write_export_table
from squadopt.preflight import compute_table_sha256

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
