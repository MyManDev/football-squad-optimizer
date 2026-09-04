"""The scorecard appender: refusals and the arithmetic of one row."""

import json
from pathlib import Path

import pytest
import scripts.append_weekly_scorecard as scorecard


def _ledger(root: Path, *, with_outcome: bool = True) -> None:
    entry = root / "2026-27" / "gw01"
    entry.mkdir(parents=True)
    (entry / "decision.json").write_text(
        json.dumps(
            {
                "gameweek": 1,
                "model_version": "test-v1",
                "projected_score": 56.0,
                "captain_player_id": 7,
            }
        ),
        encoding="utf-8",
    )
    if with_outcome:
        (entry / "outcome.json").write_text(
            json.dumps(
                {
                    "realized_xi_score": 60.0,
                    "realized_net_score": 60.0,
                    "realized_points_by_player": {"7": 12.0},
                }
            ),
            encoding="utf-8",
        )


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *extra: str) -> int:
    argv = [
        "x",
        "--gameweek",
        "1",
        "--ledger-root",
        str(tmp_path / "ledger"),
        "--output",
        str(tmp_path / "scorecard.md"),
        *extra,
    ]
    monkeypatch.setattr("sys.argv", argv)
    return scorecard.main()


def test_a_row_carries_the_error_and_the_captain_share(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ledger(tmp_path / "ledger")
    assert _run(monkeypatch, tmp_path) == 0
    text = (tmp_path / "scorecard.md").read_text(encoding="utf-8")
    assert "| 1 | test-v1 | 56.00 | 60 | 60 | +4.00 | 24 | 40% |" in text


def test_an_unsettled_gameweek_and_a_duplicate_row_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ledger(tmp_path / "ledger", with_outcome=False)
    assert _run(monkeypatch, tmp_path) == 1
    (tmp_path / "ledger" / "2026-27" / "gw01" / "outcome.json").write_text(
        json.dumps(
            {
                "realized_xi_score": 60.0,
                "realized_net_score": 60.0,
                "realized_points_by_player": {"7": 12.0},
            }
        ),
        encoding="utf-8",
    )
    assert _run(monkeypatch, tmp_path) == 0
    assert _run(monkeypatch, tmp_path) == 1  # immutable rows
