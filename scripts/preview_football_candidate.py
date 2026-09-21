"""Run the opt-in football candidate from an explicit offline input bundle.

No network, model promotion, owner publication or live-state access. See
docs/research/football_candidate_development.md for the input/evidence contract.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from numbers import Integral
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.application.football_candidate import preview_football_candidate
from squadopt.optimization import OptimizationConfig
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.recourse import ObservationNode
from squadopt.prediction.football import FixtureFootballModel


def _identifier(value: object) -> int | str:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and value:
        return value
    raise ValueError("Decision identifiers must be integers or nonempty strings.")


def run(bundle: Path, output: Path, *, samples: int = 256, seed: int = 0) -> dict[str, Any]:
    """Read named files only; create a fresh artifact directory without overwrites."""
    if output.exists():
        raise FileExistsError("The candidate output directory must be new.")
    config = json.loads(bundle.read_text(encoding="utf-8"))
    if config.get("contract_version") != "football_candidate_bundle_v1":
        raise ValueError("Unsupported candidate bundle contract.")
    hashes = {"bundle": hashlib.sha256(bundle.read_bytes()).hexdigest()}

    def read(name: str, file: str) -> pd.DataFrame:
        path = (bundle.parent / file).resolve()
        raw = path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        frame = pd.read_csv(
            io.BytesIO(raw), dtype={"name": str, "team_id": str, "position": str, "season": str}
        )
        for column in ("kickoff", "feature_cutoff"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], utc=True)
        return frame

    train = read("training", config["training"])
    history = read("history", config["history"])
    roster = read("roster", config["roster"])
    calendar = read("calendar", config["calendar"])
    cutoff = pd.Timestamp(config["decision_cutoff"])
    model = FixtureFootballModel(train, history, cutoff=cutoff)
    holdings = config["holdings"]
    initial = InitialSquadState(
        tuple(h["player_id"] for h in holdings), config["bank_tenths"], config["free_transfers"]
    )
    observations = [
        ObservationNode(
            n["id"], n["probability"], PlanningHorizon(read("observation_" + n["id"], n["table"]))
        )
        for n in config.get("observations", [])
    ]
    result = preview_football_candidate(
        model,
        history,
        roster,
        calendar,
        initial,
        {h["player_id"]: h["purchase_price_tenths"] for h in holdings},
        gameweeks=config["gameweeks"],
        season=config["season"],
        source_snapshot_id=config["source_snapshot_id"],
        captured_at=pd.Timestamp(config["captured_at"]),
        optimization=OptimizationConfig(
            bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
        ),
        observations=observations,
        role_transitions=config.get("role_transitions", False),
        candidate_count=config.get("candidate_count", 3),
        samples=samples,
        seed=seed,
    )
    decision = result.decisions[result.recommendation]
    recourse = result.recourse
    report: dict[str, Any] = {
        "contract_version": result.contract_version,
        "model_version": result.projections.model_version,
        "source_snapshot_id": result.projections.source_snapshot_id,
        "horizon_fingerprint": result.projections.horizon_fingerprint,
        "recommendation": result.recommendation,
        "squad": [_identifier(x) for x in decision.squad.player_id],
        "starting_xi": [_identifier(x) for x in decision.starting_xi],
        "bench": [_identifier(x) for x in decision.bench],
        "captain": _identifier(decision.captain_id),
        "vice_captain": _identifier(decision.vice_captain_id),
        "solver_status": result.control.solver_status.value,
        "control_expected_net_points": result.control.total_projected_score
        - result.control.total_transfer_hit_points
        if result.control.total_projected_score is not None
        and result.control.total_transfer_hit_points is not None
        else None,
        "recourse": None
        if recourse is None
        else {
            "chosen_index": recourse.chosen_index,
            "hold_feasible": recourse.hold_feasible,
            "candidates": [
                {
                    "expected_net_points": c.expected_net_points,
                    "continuations": [
                        {
                            "observation_id": v.observation_id,
                            "probability": v.probability,
                            "extra_free_transfer_value": v.extra_free_transfer_value,
                        }
                        for v in c.continuations
                    ],
                }
                for c in recourse.candidates
            ],
        },
        "input_sha256": hashes,
        "samples": samples,
        "seed": seed,
        "production_promotion": False,
        "independent_evidence_verified": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    result.projections.table.to_csv(output / "projections.csv", index=False)
    result.components.to_csv(output / "components.csv", index=False)
    result.scenario_scores.to_csv(output / "scenario_scores.csv", index=False)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=256)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    report = run(args.bundle, args.output, samples=args.samples, seed=args.seed)
    print(
        json.dumps(
            {
                "model_version": report["model_version"],
                "solver_status": report["solver_status"],
                "production_promotion": False,
            }
        )
    )


if __name__ == "__main__":
    main()
