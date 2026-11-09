"""The solver-budget summary: a record that carries its fold decisions and its provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import summarize_solver_budget_cards as summary

FOLDS = ("2021-22-gw02", "2021-22-gw03", "2022-23-gw02")
SQUAD = list(range(101, 116))


def _decision(
    *, status: str, objective: float, bound: float, score: float, captain: int, swap: int = 0
) -> dict[str, Any]:
    squad = [player + swap if player == 115 else player for player in SQUAD]
    return {
        "squad": list(reversed(squad)),
        "starting_xi": squad[:11],
        "bench_order": squad[11:],
        "captain_id": captain,
        "vice_captain_id": 102,
        "solver_status": status,
        "objective_value": objective,
        "best_objective_bound": bound,
        "deterministic_time_used": 1.5,
        "realized_score": score,
        "realized_score_ignoring_cards": score,
    }


def _document(budget: str, candidate_scores: dict[str, float]) -> dict[str, Any]:
    high = budget == "60.0"
    decisions = {
        fold: {
            "component_base": _decision(
                status="OPTIMAL" if high or index else "FEASIBLE",
                objective=80.0 + (0.2 if high and not index else 0.0),
                bound=86.0,
                score=candidate_scores[fold],
                captain=101,
                swap=1 if high and not index else 0,
            ),
            "control": _decision(
                status="OPTIMAL", objective=70.0, bound=70.0, score=50.0, captain=103
            ),
        }
        for index, fold in enumerate(FOLDS)
    }
    return {
        "generated_at_utc": f"2026-11-08T00:00:00+00:00 {budget}",
        "provenance": {"repository_commit": "5d5e6fbd" + "0" * 32},
        "source": {"table_sha256": "a" * 64, "producer_repository_commit": "3a3920bd" + "0" * 32},
        "measurement_options": {"solver_deterministic_budget": float(budget)},
        "solver": {"binding_limit": "deterministic_time"},
        "execution": {
            "started_at_utc": "2026-11-08T00:00:00+00:00",
            "completed_at_utc": "2026-11-08T01:00:00+00:00",
            "elapsed_seconds": 3600.0,
        },
        "decision_comparison": {"decisions": decisions},
    }


def _write_inputs(root: Path, inputs: Path) -> None:
    """Six evaluation documents and the two candidate records their scores reproduce."""

    scores = {
        "linear_dec": {FOLDS[0]: 60.0, FOLDS[1]: 61.0, FOLDS[2]: 62.0},
        "gbm_v1_dec": {FOLDS[0]: 59.0, FOLDS[1]: 61.0, FOLDS[2]: 64.0},
        "gbm_v2_dec": {FOLDS[0]: 59.0, FOLDS[1]: 62.0, FOLDS[2]: 64.0},
    }
    inputs.mkdir(parents=True)
    for name, table_scores in scores.items():
        for budget in summary.BUDGETS:
            document = _document(budget, table_scores)
            (inputs / f"eval_{name}_b{budget}.json").write_text(
                json.dumps(document, indent=1, sort_keys=True), encoding="utf-8"
            )
    research = root / "docs" / "research"
    research.mkdir(parents=True)
    (research / "phase_c_gradient_boosting_comparison.json").write_text(
        json.dumps(
            {
                "decision_level_reading": {
                    "arms": {
                        "linear": {"folds": scores["linear_dec"]},
                        "gradient_boosting": {"folds": scores["gbm_v1_dec"]},
                    },
                    "gbm_minus_linear_mean": 0.333,
                    "gbm_minus_linear_interval_90": [-1.0, 1.0],
                }
            }
        ),
        encoding="utf-8",
    )
    (research / "phase_c_feature_contract_v2_comparison.json").write_text(
        json.dumps(
            {
                "decision_level_reading": {
                    "arms": {"gbm_v2_features": {"folds": scores["gbm_v2_dec"]}},
                    "v2_minus_v1_features": {"mean": 0.333, "interval_90": [-1.0, 1.0]},
                }
            }
        ),
        encoding="utf-8",
    )


def test_the_record_keeps_every_fold_decision_and_names_what_produced_it(tmp_path: Path) -> None:
    inputs = tmp_path / "artifacts" / "paper_measure"
    _write_inputs(tmp_path, inputs)

    record = summary.summarize(inputs, tmp_path)

    assert record["budgets_present"] == ["5.0", "60.0"] and record["budgets_absent"] == []
    decisions = record["decisions"]
    assert set(decisions) == {
        f"{name}_b{budget}" for name in summary.TABLES for budget in summary.BUDGETS
    }
    first = decisions["linear_dec_b5.0"]["candidate"][FOLDS[0]]
    assert first["squad"] == " ".join(str(player) for player in SQUAD)
    assert first["starting_xi"] == " ".join(str(player) for player in SQUAD[:11])
    assert first["bench_order"] == "112 113 114 115"
    assert (first["solver_status"], first["realized_score"], first["captain_id"]) == (
        "FEASIBLE",
        60.0,
        101,
    )
    assert decisions["linear_dec_b60.0"]["candidate"][FOLDS[0]]["squad"].endswith(" 116")
    assert decisions["linear_dec_b5.0"]["ridge_control"][FOLDS[2]]["realized_score"] == 50.0

    raw = record["raw_evaluation_documents"]["gbm_v2_dec_b60.0"]
    path = inputs / "eval_gbm_v2_dec_b60.0.json"
    assert raw == {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
    }
    source = Path(summary.__file__).read_bytes().replace(b"\r\n", b"\n")
    assert record["produced_by"]["summarizer_sha256"] == hashlib.sha256(source).hexdigest()
    assert record["inputs"]["linear_dec_b5.0"]["completed_at_utc"] == "2026-11-08T01:00:00+00:00"
    assert record["inputs"]["linear_dec_b5.0"]["producer_repository_commit"].startswith("3a3920bd")
    assert set(record["produced_by"]["command_forms"]) == {"export", "evaluate", "summarize"}
    assert "--record-decisions" in record["produced_by"]["command_forms"]["evaluate"]

    # The summaries the decisions must reproduce: one unproven fold at 5.0 moved at 60.0.
    budget = record["budget"]["linear_dec"]["candidate"]
    assert (budget["squad_changed_folds"], budget["captain_changed_folds"]) == (1, 0)
    assert (budget["proven_at_both_budgets_folds"], budget["status_counts_high"]) == (
        2,
        {"OPTIMAL": 3},
    )
    assert round(budget["objective_gain_max"], 9) == 0.2
    assert budget["low_budget_feasible_gap_to_bound_max"] == 6.0
    assert record["reproduction_at_5_0"]["linear_dec"]["folds_reproduced"] == 3
    pair = record["pairs"]["boosted_pair_vs_linear"]["budget_5.0_official_card_rule"]
    assert pair["wins_ties_losses"] == [1, 1, 1] and round(pair["mean"], 3) == 0.333


def test_main_writes_the_record_and_reports_the_reproduction(tmp_path: Path, capsys: Any) -> None:
    inputs = tmp_path / "artifacts" / "paper_measure"
    _write_inputs(tmp_path, inputs)
    output = tmp_path / "docs" / "research" / "phase_c_solver_budget_cards.json"

    code = summary.main(
        ["--inputs-dir", str(inputs), "--output", str(output), "--root", str(tmp_path)]
    )

    assert code == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert "decisions" in written and "produced_by" in written
    out = capsys.readouterr().out
    assert "linear_dec: 3 of 3 fold scores reproduced" in out
    assert "wider_contract_vs_boosted_pair at 60.0: mean" in out
