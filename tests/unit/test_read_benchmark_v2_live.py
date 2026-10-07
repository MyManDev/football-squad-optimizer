"""The command refuses early, repeated and holdout readings before capture access."""

import json

import pytest
from scripts import read_benchmark_v2_live as cli

from squadopt.experiments.benchmark_v2_live import CLAIM_FILE


@pytest.mark.parametrize("refusal", ["early", "repeat", "holdout"])
def test_command_refusal_opens_no_capture(tmp_path, monkeypatch, refusal):
    manifest = tmp_path / "private-manifest.json"
    record = tmp_path / "record"
    weeks = [
        {
            "gameweek": week,
            **{
                role + "_snapshot_id": "fpl-live-20251010T080000Z-aabbcc"
                for role in ("decision", "freeze", "cohort", "picks", "outcome")
            },
        }
        for week in range(6, 14)
    ]
    if refusal == "early":
        weeks = weeks[:7]
    if refusal == "repeat":
        record.mkdir()
        (record / CLAIM_FILE).write_bytes(b"claimed")
    manifest.write_text(json.dumps({"season": "2026-27", "weeks": weeks}), encoding="utf-8")
    monkeypatch.setattr(cli, "read_snapshot", lambda *_: pytest.fail("Refused capture was opened"))
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **k: pytest.fail("Early git gate was reached")
    )
    assert (
        cli.main(
            [
                "--manifest",
                str(manifest),
                "--snapshot-root",
                str(tmp_path / "no-store"),
                "--record-root",
                str(record),
            ]
        )
        == 1
    )
