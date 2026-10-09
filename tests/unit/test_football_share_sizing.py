import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
from scripts.measure_football_shares import _forecast_source

from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.experiments.football_share_sizing import size_attacking_shares


class SyntheticBasis:
    def __init__(self, multipliers, *, double=False):
        self.served = {
            "season": "2026-27",
            "gameweek": 6,
            "source_snapshot_id": "synthetic",
            "model_version": "football_joint_role_retained_history_v1",
            "captured_at_utc": "2026-10-02T10:00:00Z",
            "fingerprint": "a" * 64,
        }
        self.companion = {
            "fingerprint": "b" * 64,
            "captured_availability": {
                "multipliers": [
                    {"player_code": i + 1, "multiplier": m} for i, m in enumerate(multipliers)
                ]
            },
        }
        self.fixture_rows = pd.DataFrame(
            [
                {
                    "GW": week,
                    "fixture": fixture,
                    "club": 1,
                    "player_code": i + 1,
                    "position": "MID",
                    "goals_share": 0.5,
                    "assists_share": 0.5,
                    "goals": 1.0,
                    "assists": 0.5,
                }
                for week, fixture in [(6, 61), (7, 71)] + ([(6, 62)] if double else [])
                for i in range(2)
            ]
        )


def test_hand_computed_binary_attack_and_decision_week_only():
    record, evidence = size_attacking_shares(SyntheticBasis([1.0, 0.0]))
    assert record["s1_total"] == 6.5
    assert record["s1_by_club"] == {"1": 6.5}
    assert record["s2_maximum"] == 6.5
    assert record["s2_players_at_threshold"] == 1
    assert record["go"] is True
    assert evidence.candidate_credited_attack.sum() == 13.0


@pytest.mark.parametrize(
    "multipliers, lost, gain",
    [
        ([1.0, 1.0], 0.0, 0.0),
        ([1.0, 0.5], 3.25, 6.5 / 3),
        ([0.0, 0.0], 13.0, 0.0),
    ],
)
def test_one_application_and_boundaries(multipliers, lost, gain):
    record, evidence = size_attacking_shares(SyntheticBasis(multipliers))
    assert record["s1_total"] == pytest.approx(lost)
    assert record["s2_maximum"] == pytest.approx(gain)
    if multipliers == [1.0, 1.0]:
        assert evidence.gain.eq(0).all()


def test_double_and_input_unchanged():
    basis = SyntheticBasis([1.0, 0.0], double=True)
    original = deepcopy(basis.fixture_rows)
    record, _ = size_attacking_shares(basis)
    assert record["s1_total"] == 13.0
    assert record["s2_maximum"] == 13.0
    pd.testing.assert_frame_equal(original, basis.fixture_rows)


def test_zero_channel_and_exact_threshold():
    basis = SyntheticBasis([1.0, 0.0])
    basis.fixture_rows["goals"] = 0.04
    basis.fixture_rows["assists"] = 0.0
    record, _ = size_attacking_shares(basis)
    assert record["s2_maximum"] == 0.2
    assert record["go"] is True
    basis.fixture_rows["goals"] = 0.039999
    assert size_attacking_shares(basis)[0]["go"] is False
    basis.fixture_rows[["goals_share", "assists_share", "goals", "assists"]] = 0.0
    record, evidence = size_attacking_shares(basis)
    assert record["go"] is False
    assert evidence.gain.eq(0).all()


def test_source_reader_does_not_open_outcome_payload(tmp_path, monkeypatch):
    metadata = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc="2026-10-02T10:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: b"{}", FIXTURES_PAYLOAD: b"[]", "outcomes.json": b"{}"},
    )
    original = Path.read_bytes
    opened = []

    def tracked(path):
        assert path.name != "outcomes.json"
        opened.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    source = _forecast_source(tmp_path, metadata.snapshot_id)
    assert set(source.payloads) == {BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD}
    assert set(opened) == {BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD}
    (tmp_path / metadata.snapshot_id / "payloads" / FIXTURES_PAYLOAD).write_bytes(b"[1]")
    with pytest.raises(ValueError, match="checksum"):
        _forecast_source(tmp_path, metadata.snapshot_id)


def test_fractional_gains_are_per_player_and_opponents_do_not_share_mass():
    basis = SyntheticBasis([1, 0.5, 0, 1, 1])
    basis.fixture_rows = pd.DataFrame(
        [
            {
                "GW": 6,
                "fixture": 61,
                "club": club,
                "player_code": player,
                "position": "MID",
                "goals_share": share,
                "assists_share": share,
                "goals": goals,
                "assists": assists,
            }
            for player, club, share, goals, assists in [
                (1, 1, 1 / 3, 1, 0.5),
                (2, 1, 1 / 3, 1, 0.5),
                (3, 1, 1 / 3, 1, 0.5),
                (4, 2, 0.5, 0.8, 0.4),
                (5, 2, 0.5, 0.8, 0.4),
            ]
        ]
    )
    record, evidence = size_attacking_shares(basis)
    assert evidence.set_index("player_code").gain.to_dict() == pytest.approx(
        {1: 6.5, 2: 1.625, 3: 0, 4: 0, 5: 0}
    )
    assert record["s1_by_club"] == {"1": 9.75, "2": 0.0}
    assert record["available_players_with_fixtures"] == 4


def test_distinct_assist_shares_use_the_assist_channel_mass():
    basis = SyntheticBasis([1, 0.5, 0])
    basis.fixture_rows = pd.DataFrame(
        [
            {
                "GW": 6,
                "fixture": 61,
                "club": 1,
                "player_code": player,
                "position": "MID",
                "goals_share": 1 / 3,
                "assists_share": assists,
                "goals": 1.0,
                "assists": assists,
            }
            for player, assists in ((1, 0.5), (2, 0.25), (3, 0.25))
        ]
    )
    record, evidence = size_attacking_shares(basis)
    assert evidence.set_index("player_code").gain.to_dict() == pytest.approx(
        {1: 5.9, 2: 1.375, 3: 0}
    )
    assert record["s1_total"] == pytest.approx(8.625)
    assert record["s2_maximum"] == pytest.approx(5.9)
    assert record["available_players_with_fixtures"] == 2


@pytest.mark.parametrize("position, points", [("GK", 10), ("DEF", 6), ("MID", 5), ("FWD", 4)])
def test_goal_points_by_position(position, points):
    basis = SyntheticBasis([1, 0])
    basis.fixture_rows["position"] = position
    basis.fixture_rows["assists"] = 0.0
    record, _ = size_attacking_shares(basis)
    assert record["s1_total"] == points
    assert record["s2_maximum"] == points


def test_evidence_and_both_record_copies_use_identical_lf_bytes(tmp_path, monkeypatch):
    from scripts import measure_football_shares as runner

    monkeypatch.setattr(os, "linesep", "\r\n")
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)
    record, frame = size_attacking_shares(SyntheticBasis([1, 0.5]))
    root = tmp_path / "artifacts/evidence"
    runner._write_record(record, frame, root)
    evidence = (root / "player-fixtures.csv").read_bytes()
    summary = (root / "summary.json").read_bytes()
    assert b"\r" not in evidence
    assert b"\r" not in summary
    assert record["evidence_sha256"] == hashlib.sha256(evidence).hexdigest()
    assert summary == (tmp_path / "docs/research/football_share_sizing.json").read_bytes()
    companion = root / "rebuilt.components.json"
    runner._write_lf_json(companion, {"name": "synthetic", "rows": []})
    assert companion.read_bytes() == b'{\n  "name": "synthetic",\n  "rows": []\n}\n'


def test_main_rebuilt_companion_has_lf_bytes_under_windows_text_translation(
    tmp_path, monkeypatch, capsys
):
    from scripts import measure_football_shares as runner

    from squadopt.application import football_live

    basis = SyntheticBasis([1, 0.5])
    basis.served.update(
        rows=[{"gameweek": 6}, {"gameweek": 7}],
        training_selection={"allowed_seasons": ["2024-25"]},
    )
    served = deepcopy(basis.served)
    companion = deepcopy(basis.companion)
    artifact_root = tmp_path / "served-artifacts"
    evidence_root = tmp_path / "artifacts/synthetic-sizing"
    snapshot_root = tmp_path / "synthetic-captures"
    archive_root = tmp_path / "synthetic-archive"
    forecast_path = runner.football_artifact_path(artifact_root, "synthetic")
    forecast_path.parent.mkdir(parents=True)
    forecast_bytes = json.dumps(served).encode("utf-8")
    forecast_path.write_bytes(forecast_bytes)
    source = object()
    inputs = object()
    football = object()
    producer_calls = []

    def source_for(root, identifier):
        assert root == snapshot_root
        assert identifier == "synthetic"
        return source

    def inputs_for(captured, *, season):
        assert captured is source
        assert season == "2026-27"
        return inputs

    def forecast_for(path, captured_inputs):
        assert path == forecast_path
        assert captured_inputs is inputs
        return football

    def produce(captured, archive, **kwargs):
        assert captured is source
        assert archive == archive_root
        producer_calls.append(kwargs)
        return deepcopy(served), deepcopy(companion)

    def basis_for(loaded_served, loaded_companion, captured, captured_inputs, loaded_football):
        assert loaded_served == served
        assert loaded_companion == companion
        assert captured is source
        assert captured_inputs is inputs
        assert loaded_football is football
        return basis

    original_write_text = Path.write_text

    def windows_write_text(path, text, encoding=None, errors=None, newline=None):
        if newline is None:
            text = text.replace("\n", "\r\n")
        return original_write_text(path, text, encoding=encoding, errors=errors, newline="")

    monkeypatch.setattr(Path, "write_text", windows_write_text)
    monkeypatch.setattr(os, "linesep", "\r\n")
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_forecast_source", source_for)
    monkeypatch.setattr(runner, "read_snapshot", source_for)
    monkeypatch.setattr(runner, "read_inputs", inputs_for)
    monkeypatch.setattr(runner, "read_football_forecast", forecast_for)
    monkeypatch.setattr(runner, "_basis_from_snapshot", basis_for)
    monkeypatch.setattr(runner, "_git_revision", lambda: ("synthetic-code", False))
    monkeypatch.setattr(football_live, "produce_football_components", produce)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure_football_shares",
            "--snapshot-root",
            str(snapshot_root),
            "--snapshot-id",
            "synthetic",
            "--artifact-root",
            str(artifact_root),
            "--archive-root",
            str(archive_root),
            "--evidence-root",
            str(evidence_root),
        ],
    )
    runner.main()
    assert producer_calls == [
        {
            "gameweeks": [6, 7],
            "training_seasons": ["2024-25"],
            "role_minutes": True,
            "retained_role_history": True,
        }
    ]
    rebuilt_path = evidence_root / "rebuilt.components.json"
    expected_bytes = (json.dumps(companion, indent=2, sort_keys=True) + "\n").encode("utf-8")
    assert rebuilt_path.read_bytes() == expected_bytes
    assert not forecast_path.with_suffix(".components.json").exists()
    record = json.loads(capsys.readouterr().out)
    assert record["companion_rebuilt"] is True
    assert record["companion_sha256"] == hashlib.sha256(expected_bytes).hexdigest()
    assert record["forecast_sha256"] == hashlib.sha256(forecast_bytes).hexdigest()
    assert record["target_outcomes_read"] is False
    assert record["repository_commit"] == "synthetic-code"
    summary = (evidence_root / "summary.json").read_bytes()
    assert json.loads(summary) == record
    assert summary == (tmp_path / "docs/research/football_share_sizing.json").read_bytes()
    assert b"\r" not in summary
