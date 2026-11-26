"""Synthetic checks for the audit's season and timing boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "crowd_signal_data_audit", Path(__file__).with_name("crowd_signal_data_audit.py")
)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def synthetic_season(tmp_path: Path, *, extra_column: str = "modified") -> Path:
    season_root = tmp_path / "data" / "2024-25"
    (season_root / "gws").mkdir(parents=True)
    (season_root / "gws" / "merged_gw.csv").write_text(
        f"GW,element,selected,transfers_in,transfers_out,transfers_balance,{extra_column}\n"
        "1,7,100,10,2,8,False\n"
        "2,7,110,20,4,16,False\n"
        "2,7,110,20,4,16,False\n"
        "3,8,0,0,0,0,True\n",
        encoding="utf-8",
    )
    (season_root / "players_raw.csv").write_text(
        "id,selected_by_percent,news_added\n", encoding="utf-8"
    )
    (season_root / "fixtures.csv").write_text("id,kickoff_time\n", encoding="utf-8")
    return tmp_path


def test_named_season_refuses_missing_timing_and_counts_folds_once(tmp_path: Path) -> None:
    result = AUDIT.audit_season(synthetic_season(tmp_path), "2024-25")
    assert result["candidate_decision_folds"] == 2
    assert result["rows"] == 4
    assert result["distinct_player_gameweeks"] == 3
    assert result["verified_predeadline_folds"] == 0
    assert result["nonempty_crowd_field_rows"]["selected"] == 4
    assert result["modified_value_types"] == {"boolean": 4}
    assert result["captaincy_columns"] == []


def test_disallowed_season_is_rejected_before_io(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="four named development seasons"):
        AUDIT.audit_season(tmp_path / "does-not-exist", "outside-development")


def test_unknown_capture_column_requires_review(tmp_path: Path) -> None:
    root = synthetic_season(tmp_path, extra_column="captured_at_utc")
    with pytest.raises(ValueError, match="new provenance review"):
        AUDIT.audit_season(root, "2024-25")


def test_metadata_sidecar_requires_review_without_reading_it(tmp_path: Path) -> None:
    root = synthetic_season(tmp_path)
    (root / "data" / "2024-25" / "capture.json").write_text("invalid JSON", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata needs an explicit provenance review"):
        AUDIT.audit_season(root, "2024-25")
