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
