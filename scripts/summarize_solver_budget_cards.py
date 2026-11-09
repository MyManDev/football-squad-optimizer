"""Summarize the solver-budget and card-rule measurement into one committed record.

Reads the evaluation documents `scripts.evaluate_phase_c_components` wrote with
`--card-participation --record-decisions` at two solver budgets for the linear control, the
boosted pair on v1 features and the boosted pair on v2 features (the decision-season tables),
and the three committed candidate records whose fold scores they must reproduce, and writes
the record of docs/research/phase_c_solver_budget_cards_method.md: nothing is fitted or
measured here, every number is arithmetic on those documents.

    python -m scripts.summarize_solver_budget_cards --inputs-dir artifacts/paper_measure \
        --output docs/research/phase_c_solver_budget_cards.json

Pairs read: the boosted pair against the linear arm, and the boosted pair on v2 features
against the boosted pair on v1 features. Intervals use the repository's season-aware
moving-block bootstrap under the measurement policy with the candidate ids this note declares.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TABLES = ("linear_dec", "gbm_v1_dec", "gbm_v2_dec")
BUDGETS = ("5.0", "60.0")
PAIRS = (
    ("gbm_v1_dec", "linear_dec", "boosted_pair_vs_linear"),
    ("gbm_v2_dec", "gbm_v1_dec", "wider_contract_vs_boosted_pair"),
)
#: Where each table's recorded per-fold scores live, for the reproduction check.
RECORDED = {
    "linear_dec": (
        "docs/research/phase_c_gradient_boosting_comparison.json",
        "/decision_level_reading/arms/linear/folds",
    ),
    "gbm_v1_dec": (
        "docs/research/phase_c_gradient_boosting_comparison.json",
        "/decision_level_reading/arms/gradient_boosting/folds",
    ),
    "gbm_v2_dec": (
        "docs/research/phase_c_feature_contract_v2_comparison.json",
        "/decision_level_reading/arms/gbm_v2_features/folds",
    ),
}
RECORDED_PAIRS = {
    "boosted_pair_vs_linear": (
        "docs/research/phase_c_gradient_boosting_comparison.json",
        "/decision_level_reading/gbm_minus_linear_mean",
        "/decision_level_reading/gbm_minus_linear_interval_90",
    ),
    "wider_contract_vs_boosted_pair": (
        "docs/research/phase_c_feature_contract_v2_comparison.json",
        "/decision_level_reading/v2_minus_v1_features/mean",
        "/decision_level_reading/v2_minus_v1_features/interval_90",
    ),
}


def _resolve(document: Any, pointer: str) -> Any:
    for token in pointer.strip("/").split("/"):
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise SystemExit(f"{path}: not a JSON object")
    return document


def _decisions(document: dict[str, Any], arm: str = "component_base") -> dict[str, dict[str, Any]]:
    decisions = document["decision_comparison"].get("decisions")
    if not decisions:
        raise SystemExit(f"{document.get('generated_at_utc')}: no recorded decisions")
    return {fold: arms[arm] for fold, arms in decisions.items()}


def _arm_summary(mine: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """An arm's status counts and mean realized scores over its folds."""

    return {
        "folds": len(mine),
        "statuses": _statuses(mine),
        "mean_realized_score": statistics.fmean(float(a["realized_score"]) for a in mine.values()),
        "mean_realized_score_ignoring_cards": statistics.fmean(
            float(a["realized_score_ignoring_cards"]) for a in mine.values()
        ),
    }


def _interval(differences: list[tuple[str, float]], candidate_id: str) -> list[float]:
    policy = PromotionPolicy()
    low, high = season_aware_moving_block_interval(
        differences, policy=policy, candidate_id=candidate_id
    )
    return [low, high]


def _paired(
    mine: dict[str, dict[str, Any]], theirs: dict[str, dict[str, Any]], key: str, candidate_id: str
) -> dict[str, Any]:
    folds = sorted(set(mine) & set(theirs))
    differences = [(fold[:7], float(mine[fold][key]) - float(theirs[fold][key])) for fold in folds]
    values = [value for _, value in differences]
    seasons: dict[str, list[float]] = {}
    for season, value in differences:
        seasons.setdefault(season, []).append(value)
    return {
        "paired_folds": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "interval_90": _interval(differences, candidate_id),
        "candidate_id": candidate_id,
        "wins_ties_losses": [
            sum(v > 0 for v in values),
            sum(v == 0 for v in values),
            sum(v < 0 for v in values),
        ],
        "by_season_mean": {
            season: statistics.fmean(items) for season, items in sorted(seasons.items())
        },
    }


def _overlap(mine: dict[str, dict[str, Any]], theirs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    folds = sorted(set(mine) & set(theirs))
    shared_squad = [len(set(mine[f]["squad"]) & set(theirs[f]["squad"])) for f in folds]
    shared_xi = [len(set(mine[f]["starting_xi"]) & set(theirs[f]["starting_xi"])) for f in folds]
    same_captain = [mine[f]["captain_id"] == theirs[f]["captain_id"] for f in folds]
    identical = [set(mine[f]["squad"]) == set(theirs[f]["squad"]) for f in folds]
    tied = [f for f in folds if mine[f]["realized_score"] == theirs[f]["realized_score"]]
    tied_identical = sum(set(mine[f]["squad"]) == set(theirs[f]["squad"]) for f in tied)
    return {
        "folds": len(folds),
        "mean_shared_squad_members_of_15": statistics.fmean(shared_squad),
        "mean_shared_starters_of_11": statistics.fmean(shared_xi),
        "same_captain_folds": sum(same_captain),
        "identical_squad_folds": sum(identical),
        "tied_folds": len(tied),
        "tied_folds_with_identical_squads": tied_identical,
        "shared_squad_members_histogram": {
            str(k): shared_squad.count(k) for k in sorted(set(shared_squad))
        },
    }


def _reproduction(name: str, mine: dict[str, dict[str, Any]], root: Path) -> dict[str, Any]:
    record, pointer = RECORDED[name]
    recorded = _resolve(_load(root / record), pointer)
    folds = sorted(set(mine) & set(recorded))
    differing = {
        fold: {
            "recorded": recorded[fold],
            "rerun_ignoring_cards": mine[fold]["realized_score_ignoring_cards"],
            "rerun_solver_status": mine[fold]["solver_status"],
        }
        for fold in folds
        if float(recorded[fold]) != float(mine[fold]["realized_score_ignoring_cards"])
    }
    differing_statuses: dict[str, int] = {}
    for item in differing.values():
        status = item["rerun_solver_status"]
        differing_statuses[status] = differing_statuses.get(status, 0) + 1
    return {
        "record": record,
        "pointer": pointer,
        "folds_compared": len(folds),
        "folds_missing_from_rerun": sorted(set(recorded) - set(mine)),
        "folds_reproduced": len(folds) - len(differing),
        "folds_differing": differing,
        "differing_rerun_statuses": dict(sorted(differing_statuses.items())),
        "differing_sum_rerun_minus_recorded": sum(
            float(item["rerun_ignoring_cards"]) - float(item["recorded"])
            for item in differing.values()
        ),
        "rerun_statuses": _statuses(mine),
    }


def _cards(mine: dict[str, dict[str, Any]]) -> dict[str, Any]:
    changed = {
        fold: {
            "official": arm["realized_score"],
            "ignoring_cards": arm["realized_score_ignoring_cards"],
        }
        for fold, arm in mine.items()
        if arm["realized_score"] != arm["realized_score_ignoring_cards"]
    }
    return {
        "folds": len(mine),
        "folds_changed_by_the_card_rule": len(changed),
        "sum_of_changes": sum(c["official"] - c["ignoring_cards"] for c in changed.values()),
        "changed": changed,
    }


def _statuses(mine: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for arm in mine.values():
        counts[arm["solver_status"]] = counts.get(arm["solver_status"], 0) + 1
    return dict(sorted(counts.items()))


def _budget(low: dict[str, dict[str, Any]], high: dict[str, dict[str, Any]]) -> dict[str, Any]:
    folds = sorted(set(low) & set(high))
    squad_changed = [f for f in folds if set(low[f]["squad"]) != set(high[f]["squad"])]
    xi_changed = [f for f in folds if set(low[f]["starting_xi"]) != set(high[f]["starting_xi"])]
    captain_changed = [f for f in folds if low[f]["captain_id"] != high[f]["captain_id"]]
    objective_gain = [
        float(high[f]["objective_value"]) - float(low[f]["objective_value"])
        for f in folds
        if high[f]["objective_value"] is not None and low[f]["objective_value"] is not None
    ]
    gaps = []
    for f in folds:
        bound, value = low[f].get("best_objective_bound"), low[f].get("objective_value")
        if low[f]["solver_status"] == "FEASIBLE" and bound is not None and value is not None:
            gaps.append(float(bound) - float(value))
    score_change = [
        float(high[f]["realized_score"]) - float(low[f]["realized_score"]) for f in folds
    ]
    proven_both = [
        f for f in folds if low[f]["solver_status"] == high[f]["solver_status"] == "OPTIMAL"
    ]
    return {
        "folds": len(folds),
        "status_counts_low": _statuses(low),
        "status_counts_high": _statuses(high),
        "proven_at_both_budgets_folds": len(proven_both),
        "proven_at_both_budgets_squad_changed_folds": sum(
            set(low[f]["squad"]) != set(high[f]["squad"]) for f in proven_both
        ),
        "mean_realized_score_low": statistics.fmean(
            float(low[f]["realized_score"]) for f in folds
        ),
        "mean_realized_score_high": statistics.fmean(
            float(high[f]["realized_score"]) for f in folds
        ),
        "squad_changed_folds": len(squad_changed),
        "starting_xi_changed_folds": len(xi_changed),
        "captain_changed_folds": len(captain_changed),
        "objective_gain_mean": statistics.fmean(objective_gain) if objective_gain else None,
        "objective_gain_max": max(objective_gain) if objective_gain else None,
        "low_budget_feasible_gap_to_bound_mean": statistics.fmean(gaps) if gaps else None,
        "low_budget_feasible_gap_to_bound_max": max(gaps) if gaps else None,
        "realized_score_change_mean": statistics.fmean(score_change),
        "realized_score_change_folds": sum(v != 0 for v in score_change),
        "deterministic_time_used_mean_high": statistics.fmean(
            float(high[f]["deterministic_time_used"])
            for f in folds
            if high[f].get("deterministic_time_used") is not None
        ),
    }


def summarize(inputs: Path, root: Path) -> dict[str, Any]:
    """The record built from whichever of the declared budgets have all three evaluations.

    The 5.0 budget is required (it carries the reproduction check and the card rule); a
    budget whose three evaluations are not all present is left out and named under
    `budgets_absent`, so an interim record can be written while the 60.0 runs finish.
    """

    budgets = tuple(
        budget
        for budget in BUDGETS
        if all((inputs / f"eval_{name}_b{budget}.json").is_file() for name in TABLES)
    )
    if "5.0" not in budgets:
        raise SystemExit(f"{inputs}: the three budget-5.0 evaluations are required")
    documents = {
        (name, budget): _load(inputs / f"eval_{name}_b{budget}.json")
        for name in TABLES
        for budget in budgets
    }
    decisions = {key: _decisions(document) for key, document in documents.items()}
    result: dict[str, Any] = {
        "contract_version": "phase_c_solver_budget_cards_v1",
        "declaration": "docs/research/phase_c_solver_budget_cards_method.md",
        "budgets_present": list(budgets),
        "budgets_absent": [budget for budget in BUDGETS if budget not in budgets],
        "descriptive_only": True,
        "promotion_decision": "not_evaluated",
        "operational_control_changed": False,
        "locked_holdout_accessed": True,
        "locked_holdout_note": (
            "the handoff tables were exported under the v2 development scope for the four "
            "decision seasons; 2025-26 is not read by any fold here"
        ),
        "inputs": {
            f"{name}_b{budget}": {
                "generated_at_utc": document["generated_at_utc"],
                "repository_commit": document["provenance"]["repository_commit"],
                "table_sha256": document["source"]["table_sha256"],
                "measurement_options": document["measurement_options"],
                "solver": document["solver"],
                "elapsed_seconds": document["execution"]["elapsed_seconds"],
            }
            for (name, budget), document in documents.items()
        },
        "reproduction_at_5_0": {
            name: _reproduction(name, decisions[(name, "5.0")], root) for name in TABLES
        },
        "arms": {
            f"{name}_b{budget}": {
                "candidate": _arm_summary(decisions[(name, budget)]),
                "ridge_control": _arm_summary(_decisions(document, "control")),
            }
            for (name, budget), document in documents.items()
        },
        "card_rule": {
            f"{name}_b{budget}": {
                **_cards(decisions[(name, budget)]),
                "ridge_control": _cards(_decisions(document, "control")),
            }
            for (name, budget), document in documents.items()
        },
        "budget": {
            name: {
                "candidate": _budget(decisions[(name, "5.0")], decisions[(name, "60.0")]),
                "ridge_control": _budget(
                    _decisions(documents[(name, "5.0")], "control"),
                    _decisions(documents[(name, "60.0")], "control"),
                ),
            }
            for name in TABLES
        }
        if "60.0" in budgets
        else {},
        "pairs": {},
    }
    for mine, theirs, label in PAIRS:
        record, mean_pointer, interval_pointer = RECORDED_PAIRS[label]
        recorded = _load(root / record)
        block: dict[str, Any] = {
            "recorded": {
                "mean": _resolve(recorded, mean_pointer),
                "interval_90": _resolve(recorded, interval_pointer),
            },
        }
        for budget in budgets:
            for key, suffix in (
                ("realized_score_ignoring_cards", "ignoring_cards"),
                ("realized_score", "official_card_rule"),
            ):
                block[f"budget_{budget}_{suffix}"] = _paired(
                    decisions[(mine, budget)],
                    decisions[(theirs, budget)],
                    key,
                    f"paper_solver_budget_{label}_{budget}_{suffix}",
                )
            block[f"budget_{budget}_overlap"] = _overlap(
                decisions[(mine, budget)], decisions[(theirs, budget)]
            )
        result["pairs"][label] = block
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    arguments = parser.parse_args(argv)
    result = summarize(arguments.inputs_dir, arguments.root)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    for name, block in result["reproduction_at_5_0"].items():
        reproduced, compared = block["folds_reproduced"], block["folds_compared"]
        print(f"{name}: {reproduced} of {compared} fold scores reproduced")
    for label, block in result["pairs"].items():
        for budget in result["budgets_present"]:
            paired = block[f"budget_{budget}_official_card_rule"]
            print(f"{label} at {budget}: mean {paired['mean']:+.3f} {paired['interval_90']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
