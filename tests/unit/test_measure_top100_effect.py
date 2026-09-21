"""Refusal boundaries and official scoring on synthetic recorded publications."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from scripts import measure_top100_effect as runner

from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata


def capture(through: int, checked: bool = True) -> CapturedSnapshot:
    bootstrap = json.dumps(
        {
            "events": [
                {
                    "id": week,
                    "deadline_time": f"2026-09-{week:02d}T10:00:00Z",
                    "finished": True,
                    "data_checked": checked,
                }
                for week in range(1, through + 1)
            ]
        }
    ).encode()
    return CapturedSnapshot(
        SnapshotMetadata(
            "synthetic", "fpl-live", "2026-09-22T00:00:00Z", "snapshot_v1", {}, "a" * 64
        ),
        {runner.BOOTSTRAP_PAYLOAD: bootstrap},
    )


@pytest.mark.parametrize(
    "latest,target,checked",
    [(11, 12, True), (13, 12, True), (12, 12, False), (19, 20, True), (21, 20, True)],
)
def test_checkpoint_refuses_before_reading_decisions_or_outcomes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, latest: int, target: int, checked: bool
) -> None:
    monkeypatch.setattr(runner, "list_snapshot_ids", lambda *a, **k: ["synthetic"])
    monkeypatch.setattr(runner, "read_snapshot", lambda *a, **k: capture(latest, checked))
    monkeypatch.setattr(runner, "infer_season", lambda s: runner.SEASON)

    def forbidden(*a: Any, **k: Any) -> None:
        pytest.fail("post-checkpoint reader called")

    for name in (
        "load_entry",
        "live_event_outcomes",
        "read_projection_handoff",
        "select_record",
        "read_player_evidence_artifact",
    ):
        monkeypatch.setattr(runner, name, forbidden)
    with pytest.raises(ValueError, match="Checkpoint"):
        runner.collect(tmp_path, tmp_path, runner.SEASON, target)


@pytest.mark.parametrize("week", [12, 20])
def test_exact_checkpoint_allowed(monkeypatch: pytest.MonkeyPatch, week: int) -> None:
    monkeypatch.setattr(runner, "infer_season", lambda s: runner.SEASON)
    runner.checkpoint(capture(week), runner.SEASON, week)


def record() -> dict[str, Any]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    base = {
        "strategy": "saf-puan",
        "window": 1,
        "rival_entry_id": None,
        "published_path": "advice/101/saf-puan/1.json",
        "starting_xi": [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15],
        "bench": [2, 12, 6, 7],
        "captain": 8,
        "vice_captain": 9,
        "scoring_complete": True,
        "chip": None,
        "transfer_hit_points": 0,
        "moves": [],
    }
    weighted = {
        **copy.deepcopy(base),
        "published_path": "advice/101/saf-puan/1/top100-5.json",
        "top100_weight": 5,
        "expected_points_cost": 0.2,
    }
    return {
        "entry_id": 101,
        "players": {str(i): {"name": f"P{i}", "position": p} for i, p in enumerate(positions, 1)},
        "advice": [base, weighted],
    }


def outcomes() -> pd.DataFrame:
    frame = pd.DataFrame({"player_id": range(1, 16), "total_points": 2.0, "minutes": 90})
    frame.loc[frame.player_id == 8, ["total_points", "minutes"]] = [0, 0]
    frame.loc[frame.player_id == 9, "total_points"] = 5
    return frame


def test_real_official_scorer_uses_vice_autosubs_chip_and_recorded_hits() -> None:
    document = record()
    document["advice"][1]["chip"] = "3xc"
    document["advice"][1]["transfer_hit_points"] = 4
    pairs, omitted = runner.score_pairs(document, outcomes(), 6)
    assert len(pairs) == 1
    assert pairs[0]["difference"] == 1  # extra vice bonus 5, minus actual hit 4
    assert pairs[0]["changed"] and pairs[0]["published_cost"] == 0.2
    assert omitted["missing_or_ambiguous_weight"] == 5


def test_incomplete_pairs_are_excluded_and_not_rebuilt() -> None:
    document = record()
    document["advice"][1]["scoring_complete"] = False
    pairs, omitted = runner.score_pairs(document, outcomes(), 6)
    assert not pairs and omitted["incomplete_or_unscorable_pair"] == 1


def test_variants_duplicate_weight_and_missing_price() -> None:
    document = record()
    document["advice"].append({**document["advice"][1], "managers_word": True})
    document["advice"][1].pop("expected_points_cost")
    pairs, _ = runner.score_pairs(document, outcomes(), 6)
    assert len(pairs) == 1 and pairs[0]["published_cost"] is None
    document["advice"].append(copy.deepcopy(document["advice"][1]))
    assert not runner.score_pairs(document, outcomes(), 6)[0]


def test_existing_record_refuses_before_collect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "top100_effect_gw12.md").write_text("frozen")
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(runner, "collect", lambda *a: pytest.fail("repeat read"))
    with pytest.raises(ValueError, match="already exists"):
        runner.main(["--season", runner.SEASON, "--through-gameweek", "12"])


def test_player_join_preserves_roster_and_missing_support_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "availability_snapshot", lambda b: None)
    monkeypatch.setattr(
        runner, "apply_availability", lambda *a: SimpleNamespace(multiplier=pd.Series([0.5, 1.0]))
    )
    monkeypatch.setattr(
        runner,
        "player_snapshot",
        lambda b: pd.DataFrame({"player_id": [1, 2], "position": ["GK", "MID"]}),
    )
    projection = SimpleNamespace(expected_points={1: 4.0, 2: 6.0}, gameweek=5)
    evidence = pd.DataFrame({"player_id": [1], "elite_start_count_lag1": [50]})
    actual = pd.DataFrame({"player_id": [1, 2], "total_points": [0.0, 8.0], "minutes": [0, 90]})
    frame = runner.player_frame(capture(12), projection, evidence, actual)
    assert frame.m.tolist() == [2.0, 6.0]
    assert frame.s.tolist() == [0.5, 0.0]
    with pytest.raises(ValueError, match="Incomplete"):
        runner.player_frame(capture(12), projection, evidence, actual.iloc[:1])


def test_export_uses_real_gate_and_refuses_late_or_partial_cohort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    csv = tmp_path / "player_evidence_v1_2026-27_gw05_top100.csv"
    csv.touch()
    evidence = pd.DataFrame(
        {
            "season": runner.SEASON,
            "target_gameweek": 5,
            "captured_at_utc": "2026-09-01T00:00:00Z",
            "deadline_timestamp_utc": "2026-09-23T00:00:00Z",
            "player_id": range(1, 12),
            "elite_cohort_size": 100,
            "elite_members_observed": 100,
            "elite_start_count_lag1": 100,
            "elite_start_share_lag1": 1.0,
            "elite_evidence_observed": True,
        }
    )
    evidence.attrs.update(
        generated_at_utc="2026-09-01T01:00:00Z",
        elite_members_missing_picks=0,
        unmapped_picked_elements=(),
        table_sha256="b" * 64,
    )
    monkeypatch.setattr(runner, "read_player_evidence_artifact", lambda *a: evidence)
    projection = SimpleNamespace(
        expected_points={i: 2.0 for i in range(1, 16)}, season=runner.SEASON, gameweek=5
    )
    selected = runner._evidence(tmp_path, projection, capture(12), "2026-09-23T00:00:00Z")
    assert selected is evidence
    assert projection.expected_points[1] == 2.0  # gate does not apply uplift to base
    evidence["elite_members_observed"] = 99
    with pytest.raises(ValueError, match="No eligible"):
        runner._evidence(tmp_path, projection, capture(12), "2026-09-23T00:00:00Z")
    evidence["elite_members_observed"] = 100
    evidence.attrs["generated_at_utc"] = "2026-09-24T00:00:00Z"
    with pytest.raises(ValueError, match="No eligible"):
        runner._evidence(tmp_path, projection, capture(12), "2026-09-23T00:00:00Z")


@pytest.mark.parametrize("mismatch", ["capture", "uplift", "fingerprint"])
def test_exact_base_identity_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mismatch: str
) -> None:
    directory = tmp_path / "handoffs" / "by-capture" / "synthetic"
    directory.mkdir(parents=True)
    (directory / "base.json").touch()
    projection = SimpleNamespace(
        fingerprint="a" * 64,
        season=runner.SEASON,
        gameweek=5,
        source_snapshot_id="synthetic",
        evidence_fingerprint=None,
    )
    if mismatch == "capture":
        projection.source_snapshot_id = "other"
    elif mismatch == "uplift":
        projection.evidence_fingerprint = "b" * 64
    else:
        projection.fingerprint = "c" * 64
    monkeypatch.setattr(runner, "read_projection_handoff", lambda p: projection)
    with pytest.raises(ValueError):
        runner._projection(tmp_path, "synthetic", "a" * 64, runner.SEASON, 5)


def test_synthetic_collect_and_immutable_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(runner, "list_snapshot_ids", lambda *a, **k: ["synthetic"])
    monkeypatch.setattr(runner, "read_snapshot", lambda *a, **k: capture(12))
    monkeypatch.setattr(runner, "infer_season", lambda s: runner.SEASON)
    synthetic = capture(12)
    payloads = dict(synthetic.payloads)
    payloads.update({runner.live_payload(w): b"synthetic" for w in range(5, 13)})
    synthetic = CapturedSnapshot(synthetic.metadata, payloads)
    monkeypatch.setattr(runner, "read_snapshot", lambda *a, **k: synthetic)
    monkeypatch.setattr(runner, "live_event_outcomes", lambda *a, **k: outcomes())
    monkeypatch.setattr(
        runner,
        "load_entry",
        lambda *a: SimpleNamespace(
            decision={
                "snapshot_id": "synthetic",
                "metadata": {"projection_handoff_fingerprint": "a" * 64},
            }
        ),
    )
    evidence = pd.DataFrame()
    evidence.attrs["table_sha256"] = "b" * 64
    monkeypatch.setattr(
        runner, "_context", lambda *a: (synthetic, SimpleNamespace(fingerprint="a" * 64), evidence)
    )

    def frame(*args: Any) -> pd.DataFrame:
        # Distinct gameweek rows are supplied in the declared chronological order.
        frame.week += 1
        return pd.DataFrame(
            {
                "gameweek": frame.week,
                "player_id": [1, 2],
                "position": "MID",
                "m": [2.0, 4.0],
                "s": [0.2, 0.4],
                "y": [3.0, 5.0],
                "minutes": 90,
            }
        )

    frame.week = 4
    monkeypatch.setattr(runner, "player_frame", frame)
    for week in range(6, 13):
        (tmp_path / "advice_records" / runner.SEASON / f"gw{week:02d}" / "entry-101").mkdir(
            parents=True
        )
    document = record()
    document.update(
        provenance={"projection_handoff_fingerprint": "a" * 64},
        capture={"snapshot_id": "synthetic"},
        generated_at_utc="2026-09-01T01:00:00Z",
    )
    calls = []

    def select(*a: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["gameweek"])
        return document

    monkeypatch.setattr(runner, "select_record", select)
    assert (
        runner.main(
            ["--season", runner.SEASON, "--through-gameweek", "12", "--data-root", str(tmp_path)]
        )
        == 0
    )
    output = json.loads((tmp_path / "docs" / "top100_effect_gw12.json").read_text())
    assert output["player_level"]["all"]["gameweeks"] == 8
    assert output["plan_level"]["5"]["pairs"] == 7
    assert calls == list(range(6, 13))  # GW5 plans are never assembled
    assert output["solver_invoked"] is False
    assert not output["excluded_weeks"]
    assert len(output["inputs"][-1]["member_record_sha256"]) == 64
    assert str(tmp_path) not in json.dumps(output)
    with pytest.raises(ValueError, match="already exists"):
        runner.main(["--season", runner.SEASON, "--through-gameweek", "12"])
