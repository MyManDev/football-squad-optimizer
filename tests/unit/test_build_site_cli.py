"""CLI test for scripts.build_site: the shell over squadopt.application.build_site."""

import json
import sys
from pathlib import Path

import pytest
import scripts.build_site as cli
from tests.unit.test_season_ledger import _capture, _panel

from squadopt.application import UI_VIEW_CONTRACT_VERSION
from squadopt.live import build_recommendation, project, read_inputs, record_decision

SEASON = "2026-27"


def test_the_shell_writes_the_tree_from_a_ledger_and_the_schema_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _capture(tmp_path / "snapshots")
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    recommendation = build_recommendation(inputs, projection)
    record_decision(tmp_path / "ledger", recommendation, projection, report_text="report")

    monkeypatch.setattr(cli, "write_ui_view_schema", lambda: tmp_path / "schema.json")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_site",
            "--season",
            SEASON,
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--snapshot-root",
            str(tmp_path / "snapshots"),
            "--handoff-root",
            str(tmp_path / "handoffs"),
            "--log-root",
            str(tmp_path / "logs"),
            "--out",
            str(tmp_path / "site"),
            "--now",
            "2026-08-21T15:30:00Z",
        ],
    )
    assert cli.main() == 0
    index = json.loads((tmp_path / "site" / "data" / "index.json").read_text("utf-8"))
    assert index["contract_version"] == UI_VIEW_CONTRACT_VERSION
    assert index["payload"]["gameweeks"] == {SEASON: [1]}
    assert (tmp_path / "site" / "data" / SEASON / "status.json").is_file()

    monkeypatch.setattr(sys, "argv", ["build_site", "--schema-only"])
    monkeypatch.setattr(cli, "write_ui_view_schema", lambda: tmp_path / "only.json")
    assert cli.main() == 0
