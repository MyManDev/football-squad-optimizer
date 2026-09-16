from pathlib import Path

import pytest
from scripts.measure_instrument import validate_destinations


def test_old_preview_cannot_silently_supply_retained_rows(tmp_path: Path) -> None:
    preview = tmp_path / ".pt" / "preview"
    output = tmp_path / "docs" / "record.json"
    validate_destinations(preview, output, tmp_path)
    preview.mkdir(parents=True)
    with pytest.raises(ValueError, match="already exists"):
        validate_destinations(preview, output, tmp_path)


@pytest.mark.parametrize(
    "output", ["data/record.json", "web/public/data/record.json", "../record.json"]
)
def test_records_cannot_overwrite_state_or_publications(tmp_path: Path, output: str) -> None:
    with pytest.raises(ValueError, match="output must"):
        validate_destinations(tmp_path / ".pt" / "fresh", tmp_path / output, tmp_path)


def test_preview_cannot_target_the_whole_scratch_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="new child"):
        validate_destinations(tmp_path / ".pt", tmp_path / "docs" / "record.json", tmp_path)
