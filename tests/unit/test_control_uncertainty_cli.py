"""CLI tests for the development-internal control uncertainty calibration.

The synthetic two-season panel stands in for the archive; its seasons are relabeled to
neutral years so the test also exercises the guard that refuses to read the 2025-26
locked holdout.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import scripts.run_control_uncertainty_calibration as calibration_cli
from tests.fixtures.synthetic_gameweeks import make_two_season_gameweeks

CALIBRATION_SEASON = "1998-99"
EVALUATION_SEASON = "1999-00"


def _relabeled_panel() -> pd.DataFrame:
    panel = make_two_season_gameweeks()
    return panel.assign(
        season=panel["season"]
        .map({"2024-25": CALIBRATION_SEASON, "2025-26": EVALUATION_SEASON})
        .astype("string")
    )


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *extra: str) -> int:
    monkeypatch.setattr(calibration_cli, "build_panel", lambda *_a, **_k: _relabeled_panel())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_control_uncertainty_calibration",
            "--archive-root",
            str(tmp_path),
            "--calibration-seasons",
            CALIBRATION_SEASON,
            "--evaluation-season",
            EVALUATION_SEASON,
            "--json-output",
            str(tmp_path / "calibration.json"),
            "--markdown-output",
            str(tmp_path / "calibration.md"),
            *extra,
        ],
    )
    return calibration_cli.main()


def test_the_cli_scores_both_calibrations_on_the_held_out_season(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(monkeypatch, tmp_path) == 0

    document = json.loads((tmp_path / "calibration.json").read_text(encoding="utf-8"))
    assert document["locked_holdout_accessed"] is False
    assert document["evaluation_season"] == EVALUATION_SEASON
    for regime in ("position_level", "player_adaptive"):
        metrics = document[regime]["metrics"]
        assert metrics["observations"] > 0
        assert 0.0 <= metrics["empirical_coverage"] <= 1.0
        assert metrics["mean_interval_width"] > 0.0
    markdown = (tmp_path / "calibration.md").read_text(encoding="utf-8")
    assert "Player-adaptive" in markdown
    assert "locked holdout was **not** read" in markdown


def test_the_cli_refuses_to_read_the_locked_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration_cli, "build_panel", lambda *_a, **_k: _relabeled_panel())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_control_uncertainty_calibration",
            "--archive-root",
            str(tmp_path),
            "--calibration-seasons",
            CALIBRATION_SEASON,
            "--evaluation-season",
            "2025-26",
        ],
    )

    assert calibration_cli.main() == 1
