"""Tests for local data-source loaders."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from squadopt.data import DataSourceError, load_csv, load_local_dataset, load_parquet

HAS_PARQUET_ENGINE = importlib.util.find_spec("pyarrow") is not None

CSV_TEXT = "season,gameweek,player_id\n2025-26,1,007\n2025-26,2,008\n"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_every_column_as_text(tmp_path: Path) -> None:
    frame = load_csv(_write(tmp_path, "panel.csv", CSV_TEXT))

    assert list(frame.columns) == ["season", "gameweek", "player_id"]
    assert {str(dtype) for dtype in frame.dtypes} == {"str"}


def test_text_reading_preserves_identifier_leading_zeros(tmp_path: Path) -> None:
    """Type inference would turn '007' into 7 and silently break identity joins."""

    frame = load_csv(_write(tmp_path, "panel.csv", CSV_TEXT))

    assert frame["player_id"].tolist() == ["007", "008"]


def test_a_blank_field_stays_detectably_missing(tmp_path: Path) -> None:
    text = "season,gameweek,minutes\n2025-26,1,\n2025-26,2,90\n"

    frame = load_csv(_write(tmp_path, "panel.csv", text))

    assert bool(frame["minutes"].isna().iloc[0])
    assert frame["minutes"].iloc[1] == "90"


def test_row_order_is_preserved_verbatim(tmp_path: Path) -> None:
    """Loaders are faithful; imposing canonical order is a later stage's job."""

    text = "gameweek,player_id\n5,201\n1,202\n3,203\n"

    frame = load_csv(_write(tmp_path, "panel.csv", text))

    assert frame["gameweek"].tolist() == ["5", "1", "3"]


def test_extra_columns_are_not_dropped_by_the_loader(tmp_path: Path) -> None:
    text = "season,gameweek,player_id,vendor_note\n2025-26,1,1,x\n"

    frame = load_csv(_write(tmp_path, "panel.csv", text))

    assert "vendor_note" in frame.columns


def test_missing_file_names_the_path() -> None:
    with pytest.raises(DataSourceError, match="not found") as error:
        load_csv("does_not_exist_anywhere.csv")

    assert "does_not_exist_anywhere.csv" in str(error.value)


def test_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="not a readable file"):
        load_csv(tmp_path)


def test_empty_file_is_reported_as_a_source_error(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="Failed to read CSV"):
        load_csv(_write(tmp_path, "empty.csv", ""))


@pytest.mark.parametrize("name", ["panel.csv", "panel.CSV"])
def test_dispatch_selects_the_csv_reader_regardless_of_suffix_case(
    tmp_path: Path,
    name: str,
) -> None:
    frame = load_local_dataset(_write(tmp_path, name, CSV_TEXT))

    assert len(frame) == 2


def test_dispatch_rejects_unsupported_suffix_and_lists_alternatives(tmp_path: Path) -> None:
    path = _write(tmp_path, "panel.txt", CSV_TEXT)

    with pytest.raises(DataSourceError, match="Unsupported data source suffix") as error:
        load_local_dataset(path)

    message = str(error.value)
    assert ".csv" in message
    assert ".parquet" in message


def test_dispatch_rejects_a_suffixless_path(tmp_path: Path) -> None:
    path = _write(tmp_path, "panel", CSV_TEXT)

    with pytest.raises(DataSourceError, match="Unsupported data source suffix"):
        load_local_dataset(path)


def test_missing_parquet_file_names_the_path() -> None:
    with pytest.raises(DataSourceError, match="not found"):
        load_parquet("does_not_exist_anywhere.parquet")


@pytest.mark.skipif(not HAS_PARQUET_ENGINE, reason="requires a Parquet engine")
def test_parquet_round_trip_preserves_native_dtypes(tmp_path: Path) -> None:
    original = pd.DataFrame({"gameweek": [1, 2], "price_tenths": [55, 60]})
    path = tmp_path / "panel.parquet"
    original.to_parquet(path)

    loaded = load_parquet(path)

    pd.testing.assert_frame_equal(loaded, original)


@pytest.mark.skipif(HAS_PARQUET_ENGINE, reason="only meaningful without a Parquet engine")
def test_absent_parquet_engine_gives_an_actionable_error(tmp_path: Path) -> None:
    """A missing optional engine is a source problem, not a bare ImportError."""

    path = _write(tmp_path, "panel.parquet", "not really parquet")

    with pytest.raises(DataSourceError, match="pyarrow"):
        load_parquet(path)
