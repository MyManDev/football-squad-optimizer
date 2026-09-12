"""The export writer and table digest now live in the data layer.

Both moved out of the laboratory so the product can write and digest a table without
importing `backtest` or `preflight`. The old locations re-export them for one release; these
tests pin that the new path writes the same bytes and computes the same digest as the old,
so every `table_sha256` already committed keeps identifying its table.
"""

from pathlib import Path

import pandas as pd
import pytest

from squadopt.backtest import export_precision as old_writer
from squadopt.data.checksums import compute_table_sha256, sha256_of_bytes
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import payload_checksum
from squadopt.data.tables import EXPORT_LINE_TERMINATOR, write_export_table
from squadopt.preflight import validator as old_digest


def _table() -> pd.DataFrame:
    return pd.DataFrame({"player_id": [1, 2], "predicted_points": [1.5, -0.25]})


def test_the_old_locations_re_export_the_same_objects() -> None:
    assert old_writer.write_export_table is write_export_table
    assert old_writer.EXPORT_LINE_TERMINATOR is EXPORT_LINE_TERMINATOR
    assert old_digest.compute_table_sha256 is compute_table_sha256


def test_the_new_writer_produces_the_bytes_the_old_one_did(tmp_path: Path) -> None:
    write_export_table(_table(), tmp_path / "new.csv")
    old_writer.write_export_table(_table(), tmp_path / "old.csv")

    assert (tmp_path / "new.csv").read_bytes() == (tmp_path / "old.csv").read_bytes()
    assert (tmp_path / "new.csv").read_bytes() == b"player_id,predicted_points\n1,1.5\n2,-0.25\n"


def test_a_table_digest_and_a_payload_digest_are_the_same_function(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    write_export_table(_table(), path)

    digest = compute_table_sha256(path)

    assert digest == payload_checksum(path.read_bytes()) == sha256_of_bytes(path.read_bytes())
    assert digest == "a259b4c2163109900ad042ee55f730de307154fbde5a59a176d93ec1971e6fc5"


def test_a_missing_table_is_a_data_source_error(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="does not exist"):
        compute_table_sha256(tmp_path / "absent.csv")
