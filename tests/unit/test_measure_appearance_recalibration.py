"""Refusal ordering and evidence completeness for the single-attempt runner."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts import measure_appearance_recalibration as runner

from squadopt.evaluation.component_handoff import (
    OOF_ARTIFACT_COLUMNS,
    ROSTER_ARTIFACT_COLUMNS,
    PhaseCComponentHandoff,
)
from squadopt.evaluation.models import EvaluationFold
from squadopt.optimization.models import SolverStatus


def manifest() -> dict:
    folds = [
        f"{season}-gw{week:02d}" for season in runner.DECISION_SEASONS for week in range(1, 39)
    ][:147]
    return {
        "contract_version": "phase_c_component_oof_v1",
        "roster_contract_version": "phase_c_decision_roster_v1",
        "locked_holdout_read": False,
        "working_tree_dirty": False,
        "locked_holdout_season": "2025-26",
        "development_seasons": list(runner.DECISION_SEASONS),
        "table_columns": list(OOF_ARTIFACT_COLUMNS),
        "roster_columns": list(ROSTER_ARTIFACT_COLUMNS),
        "table_column_dtypes": dict.fromkeys(OOF_ARTIFACT_COLUMNS, "string"),
        "roster_column_dtypes": dict.fromkeys(ROSTER_ARTIFACT_COLUMNS, "string"),
        "fold_count": 147,
        "fold_ids": folds,
    }


@pytest.mark.parametrize(
    "name,value",
    [
        ("locked_holdout_read", True),
        ("working_tree_dirty", True),
        ("contract_version", "phase_c_component_oof_development_v2"),
        ("development_seasons", ["2025-26"]),
        ("table_columns", []),
        ("roster_columns", []),
        ("fold_count", 146),
        ("locked_holdout_read", 0),
    ],
)
def test_unsafe_manifest_refused_before_csv_access(name: str, value: object) -> None:
    document = manifest()
    document[name] = value
    with pytest.raises(ValueError, match="Manifest refuses"):
        runner.validate_manifest(document)


def test_manifest_decision_population_is_exact_and_chronological() -> None:
    document = manifest()
    runner.validate_manifest(document)
    document["fold_ids"][-1] = document["fold_ids"][0]
    with pytest.raises(ValueError, match="147 distinct"):
        runner.validate_manifest(document)


def test_rejected_attempt_does_not_read_tables_and_cannot_retry(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(runner, "verify_declaration", lambda *_: {"runner_commit": "synthetic"})
    reads = []
    monkeypatch.setattr(runner, "read_phase_c_component_handoff", lambda *a: reads.append(a))
    path = tmp_path / "manifest.json"
    document = manifest()
    document["locked_holdout_read"] = True
    path.write_text(json.dumps(document), encoding="utf-8")
    args = [
        "--table",
        str(tmp_path / "absent.csv"),
        "--roster",
        str(tmp_path / "absent-roster.csv"),
        "--manifest",
        str(path),
        "--prereg-commit",
        "synthetic",
        "--prereg-sha256",
        "synthetic",
        "--attempt-directory",
        str(tmp_path / "attempt"),
    ]
    with pytest.raises(ValueError, match="Manifest refuses"):
        runner.main(args)
    assert reads == []
    assert (tmp_path / "attempt/appearance_recalibration_v1.failure.json").exists()
    with pytest.raises(FileExistsError):
        runner.main(args)
    assert reads == []


def results(order: list[str], gain: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        folds=[
            SimpleNamespace(
                fold_id=fold_id,
                realized_squad_points=50.0 + gain,
                optimization_result=SimpleNamespace(
                    solver_status=SolverStatus.OPTIMAL,
                    diagnostics={},
                    has_solution=True,
                    selected_squad=pd.DataFrame({"player_id": [1, 2]}),
                ),
            )
            for fold_id in order
        ]
    )


def test_complete_paired_decisions_use_frozen_bootstrap() -> None:
    order = manifest()["fold_ids"]
    record = runner.decision_readings(results(order), results(order, 1.0), order)
    assert record["complete_for_gate"]
    assert record["paired_decisions"] == 147
    assert record["interval"] == (1.0, 1.0)
    assert record["mean_difference"] == 1.0
    assert record["changed_squads"] == 0


@pytest.mark.parametrize("defect", ["missing_pair", "clock_stop"])
def test_partial_or_clock_truncated_pairs_never_get_binding_interval(defect: str) -> None:
    order = manifest()["fold_ids"]
    base, candidate = results(order), results(order, 1.0)
    if defect == "missing_pair":
        candidate.folds.pop()
    else:
        candidate.folds[-1].optimization_result.solver_status = SolverStatus.FEASIBLE
        candidate.folds[-1].optimization_result.diagnostics = {
            "primary_status": "FEASIBLE",
            "deterministic_time_budget_exhausted": False,
        }
    record = runner.decision_readings(base, candidate, order)
    assert not record["complete_for_gate"]
    assert record["interval"] is None
    assert len(record["pairs"]) == 147


def test_row_readings_keep_nonplayers_and_undefined_positions() -> None:
    projections = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "position": ["DEF", "DEF", "GK"],
            "expected_points": [3.0, 1.0, 2.0],
        }
    )
    actual = pd.DataFrame(
        {"player_id": [1, 2, 3], "total_points": [0, 4, 0], "minutes": [0, 90, 0]}
    )
    base = EvaluationFold("2021-22-gw01", projections, actual, {"season": "2021-22"})
    candidate = EvaluationFold(
        "2021-22-gw01",
        projections.assign(expected_points=[1.0, 3.0, 2.0]),
        actual,
        {"season": "2021-22"},
    )
    readings, ranks, errors = runner.full_roster_readings((base,), (candidate,))
    assert readings["pooled"]["rows"] == 3
    assert errors["pooled"] == pytest.approx((8 / 3, 4 / 3))
    assert ranks["pooled", "DEF"] == pytest.approx((-1, 1))
    assert ("pooled", "GK") not in ranks
    assert readings["pooled"]["arms"]["base"]["nonplayer_forecast_mass"] == 5 / 6
    assert readings["2022-23"]["rows"] == 0
    assert "2022-23" not in errors


@pytest.mark.parametrize("defect", ["changed_declaration", "dirty_runner", "wrong_digest"])
def test_declaration_identity_is_binding(monkeypatch, defect: str) -> None:
    declaration = b"frozen synthetic declaration"

    def fake_git(*args: str) -> bytes:
        if args[0] == "show":
            return (
                b"changed"
                if defect == "changed_declaration" and args[1].startswith("HEAD:")
                else declaration
            )
        if args[0] == "status":
            return b" M runner.py" if defect == "dirty_runner" else b""
        return b"syntheticcommit"

    monkeypatch.setattr(runner, "_git", fake_git)
    digest = hashlib.sha256(declaration).hexdigest() if defect != "wrong_digest" else "wrong"
    with pytest.raises(ValueError, match=r"declaration|clean working tree"):
        runner.verify_declaration("synthetic", digest)


def test_synthetic_runner_writes_complete_record_with_explicit_archive_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Real preparation/calibration/report plumbing, with no historical reads or solver."""
    document = manifest()
    order = document["fold_ids"]
    records = []
    fallback = []
    for fold_id in order:
        for player in range(8):
            appeared = player % 2
            records.append(
                {
                    "fold_id": fold_id,
                    "season": fold_id[:7],
                    "target_gameweek": int(fold_id[-2:]),
                    "player_id": player,
                    "fixture_count": 1,
                    "composition_route": "component_model",
                    "appearance_probability": 0.2 + 0.6 * appeared,
                    "appearance_target": float(appeared),
                    "expected_points_if_appearance": 4.0,
                    "control_expected_points": 0.8 + 2.4 * appeared,
                    "points_target": 4.0 if appeared else float("nan"),
                    "minutes_target": 90.0 if appeared else float("nan"),
                    "position": runner.POSITIONS[player // 2],
                    "name": f"Player {player}",
                    "team_id": player + 1,
                    "price_tenths": 50,
                }
            )
        frame = pd.DataFrame(records[-8:])
        projections = frame[["player_id", "name", "team_id", "position", "price_tenths"]].assign(
            expected_points=2.0
        )
        actual = pd.DataFrame(
            {"player_id": range(8), "total_points": [0, 4] * 4, "minutes": [0, 90] * 4}
        )
        fallback.append(EvaluationFold(fold_id, projections, actual, {"season": fold_id[:7]}))
    table = pd.DataFrame(records)
    handoff = PhaseCComponentHandoff(
        rows=table,
        roster=table[
            [
                "season",
                "target_gameweek",
                "fold_id",
                "player_id",
                "name",
                "team_id",
                "position",
                "price_tenths",
            ]
        ],
        table_sha256="0" * 64,
        roster_sha256="1" * 64,
        manifest_sha256="2" * 64,
        repository_commit="3" * 40,
        model_version="synthetic",
        feature_contract_version="synthetic",
        target_contract_version="synthetic",
        dataset_contract_version="synthetic",
    )
    (tmp_path / "docs").mkdir()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(runner, "verify_declaration", lambda *_: {"runner_commit": "synthetic"})
    monkeypatch.setattr(runner, "read_phase_c_component_handoff", lambda *_: handoff)
    archive_calls = []

    def panel(_root, *, seasons):
        archive_calls.append(seasons)
        return pd.DataFrame()

    monkeypatch.setattr(runner, "build_panel", panel)

    def folds(_panel, *, seasons, projection_builder):
        assert seasons == runner.DECISION_SEASONS
        return tuple(fallback)

    monkeypatch.setattr(runner, "build_walk_forward_folds", folds)

    def comparison(changed, prepared, config):
        assert len(prepared) == 147
        assert changed.rows.control_expected_points.iloc[-1] == 4.0
        base, candidate = results(order), results(order)
        base.config = candidate.config = config
        return SimpleNamespace(control=base, component_base=candidate)

    monkeypatch.setattr(runner, "evaluate_phase_c_component_decisions", comparison)
    assert (
        runner.main(
            [
                "--table",
                "unused.csv",
                "--roster",
                "unused-roster.csv",
                "--manifest",
                str(path),
                "--archive-root",
                str(tmp_path / "unopened-archive"),
                "--prereg-commit",
                "synthetic",
                "--prereg-sha256",
                "synthetic",
                "--attempt-directory",
                str(tmp_path / "attempt"),
            ]
        )
        == 0
    )
    assert archive_calls == [("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")]
    record = json.loads(
        (tmp_path / "docs/appearance_recalibration.json").read_text(encoding="utf-8")
    )
    assert record["verdict"] == "fails"
    assert record["decisions"]["paired_decisions"] == 147
    assert record["row_readings"]["pooled"]["rows"] == 147 * 8
    assert record["probabilities"]["pooled"]["candidate_minus_base_brier"] < 0
    report = (tmp_path / "docs/appearance_recalibration.md").read_text(encoding="utf-8")
    assert "Nonplayer forecast mass" in report and "unavailable" not in report
