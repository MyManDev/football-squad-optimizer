"""Run the one frozen appearance recalibration and record all three gate clauses.

Requires explicit v1 artifact paths and a committed preregistration identity. Synthetic
tests exercise helpers without opening historical rows. There is no retry or variant flag.
"""

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    measurement_optimization_config,
    solver_record,
)

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    EvaluationConfig,
    ScoringPolicy,
    evaluate_phase_c_component_decisions,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.appearance_recalibration import (
    CONTRACT_VERSION,
    DECISION_SEASONS,
    recalibrate_appearance,
    reliability,
)
from squadopt.evaluation.component_decisions import prepare_phase_c_component_folds
from squadopt.evaluation.component_handoff import OOF_ARTIFACT_COLUMNS, ROSTER_ARTIFACT_COLUMNS
from squadopt.evaluation.models import EvaluationFold, EvaluationResult
from squadopt.evaluation.prediction_gate import DEFAULT_PREDICTION_GATE, evaluate_prediction_gate
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval
from squadopt.features import CrossSeasonConfig
from squadopt.optimization import wall_clock_stopped_the_search

PREREG = "docs/appearance_recalibration_prereg.md"
GATE_FINGERPRINT = "798c82f567e97874b98055277ae5ced42b1916c2a568258b59553ad2cb613f11"
HISTORY_SEASONS = ("2020-21", *DECISION_SEASONS)
POSITIONS = ("GK", "DEF", "MID", "FWD")


def validate_manifest(document: dict[str, Any]) -> None:
    """Refuse holdout, producer and schema mismatches before touching either CSV."""
    required = {
        "contract_version": "phase_c_component_oof_v1",
        "roster_contract_version": "phase_c_decision_roster_v1",
        "locked_holdout_read": False,
        "working_tree_dirty": False,
        "locked_holdout_season": "2025-26",
        "development_seasons": list(DECISION_SEASONS),
        "table_columns": list(OOF_ARTIFACT_COLUMNS),
        "roster_columns": list(ROSTER_ARTIFACT_COLUMNS),
        "fold_count": 147,
    }
    for name, expected in required.items():
        value = document.get(name)
        if value != expected or (isinstance(expected, bool) and value is not expected):
            raise ValueError(f"Manifest refuses frozen field {name}.")
    for name, columns in (
        ("table_column_dtypes", OOF_ARTIFACT_COLUMNS),
        ("roster_column_dtypes", ROSTER_ARTIFACT_COLUMNS),
    ):
        dtypes = document.get(name)
        if (
            not isinstance(dtypes, dict)
            or set(dtypes) != set(columns)
            or any(not isinstance(value, str) or not value for value in dtypes.values())
        ):
            raise ValueError(f"Manifest refuses frozen schema {name}.")
    folds = document.get("fold_ids")
    if (
        not isinstance(folds, list)
        or len(folds) != 147
        or any(not isinstance(item, str) or item[:7] not in DECISION_SEASONS for item in folds)
        or folds != sorted(set(folds))
    ):
        raise ValueError("Manifest must declare 147 distinct chronological development decisions.")


def _git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=REPOSITORY_ROOT)


def verify_declaration(commit: str, digest: str) -> dict[str, str]:
    """Bind a clean runner to the exact committed declaration, not a mutable filename."""
    declared = _git("show", f"{commit}:{PREREG}")
    current = _git("show", f"HEAD:{PREREG}")
    if hashlib.sha256(declared).hexdigest() != digest or current != declared:
        raise ValueError("Committed declaration digest or runner declaration differs.")
    if _git("status", "--porcelain").strip():
        raise ValueError("The measurement runner requires a clean working tree.")
    if DEFAULT_PREDICTION_GATE.fingerprint != GATE_FINGERPRINT:
        raise ValueError("The frozen gate policy has changed.")
    return {
        "declaration_commit": _git("rev-parse", commit).decode().strip(),
        "declaration_sha256": digest,
        "runner_commit": _git("rev-parse", "HEAD").decode().strip(),
        "gate_fingerprint": GATE_FINGERPRINT,
    }


def full_roster_readings(
    base: tuple[EvaluationFold, ...], candidate: tuple[EvaluationFold, ...]
) -> tuple[
    dict[str, Any], dict[tuple[str, str], tuple[float, float]], dict[str, tuple[float, float]]
]:
    """Same-key all-row MAE, within-position rank and zero-minute forecast mass."""
    blocks = []
    if [fold.fold_id for fold in base] != [fold.fold_id for fold in candidate]:
        raise ValueError("Forecast arms have different decisions.")
    for control, changed in zip(base, candidate, strict=True):
        frame = (
            control.projections[["player_id", "position", "expected_points"]]
            .rename(columns={"expected_points": "base"})
            .merge(
                changed.projections[["player_id", "expected_points"]].rename(
                    columns={"expected_points": "candidate"}
                ),
                on="player_id",
                validate="one_to_one",
                how="outer",
            )
            .merge(control.realized_points, on="player_id", validate="one_to_one", how="outer")
        )
        if frame[["base", "candidate", "position", "total_points", "minutes"]].isna().any().any():
            raise ValueError("Forecast arms and outcomes must cover identical complete rosters.")
        frame["season"] = str(control.metadata["season"])
        blocks.append(frame)
    table = pd.concat(blocks, ignore_index=True)
    readings: dict[str, Any] = {}
    ranks: dict[tuple[str, str], tuple[float, float]] = {}
    errors: dict[str, tuple[float, float]] = {}
    for season in (*DECISION_SEASONS, "pooled"):
        held = table if season == "pooled" else table.loc[table.season.eq(season)]
        block: dict[str, Any] = {"rows": len(held), "arms": {}, "within_position_rank": {}}
        for arm in ("base", "candidate"):
            total = float(held[arm].sum())
            block["arms"][arm] = {
                "mae": float((held[arm] - held.total_points).abs().mean()) if len(held) else None,
                "nonplayer_forecast_mass": (
                    float(held.loc[held.minutes.eq(0), arm].sum()) / total if total else None
                ),
            }
        if len(held):
            errors[season] = tuple(block["arms"][a]["mae"] for a in ("base", "candidate"))
        for position in POSITIONS:
            subset = held.loc[held.position.eq(position)]
            pair = []
            for arm in ("base", "candidate"):
                value = (
                    float(subset[arm].rank(method="average").corr(subset.total_points.rank()))
                    if len(subset) > 1
                    and subset[arm].nunique() > 1
                    and subset.total_points.nunique() > 1
                    else math.nan
                )
                pair.append(value if math.isfinite(value) else None)
            block["within_position_rank"][position] = {"rows": len(subset), "pair": pair}
            if pair[0] is not None and pair[1] is not None:
                ranks[season, position] = (float(pair[0]), float(pair[1]))
        readings[season] = block
    return readings, ranks, errors


def decision_readings(
    base: EvaluationResult, candidate: EvaluationResult, order: list[str]
) -> dict[str, Any]:
    """Keep every attempted pair and withhold binding evidence after a clock stop."""
    arms = {}
    for name, result in (("base", base), ("candidate", candidate)):
        arms[name] = {fold.fold_id: fold for fold in result.folds}
    pairs = []
    for fold_id in order:
        record: dict[str, Any] = {"fold_id": fold_id, "season": fold_id[:7]}
        for name, folds in arms.items():
            fold = folds.get(fold_id)
            record[name] = (
                None
                if fold is None
                else {
                    "score": fold.realized_squad_points,
                    "status": fold.optimization_result.solver_status.value,
                    "clock_stopped": wall_clock_stopped_the_search(
                        fold.optimization_result.solver_status, fold.optimization_result.diagnostics
                    ),
                }
            )
        left, right = record["base"], record["candidate"]
        record["difference"] = (
            float(right["score"] - left["score"])
            if left is not None
            and right is not None
            and left["score"] is not None
            and right["score"] is not None
            else None
        )
        pairs.append(record)
    complete = len(order) == 147 and all(
        p["difference"] is not None
        and not p["base"]["clock_stopped"]
        and not p["candidate"]["clock_stopped"]
        for p in pairs
    )
    differences = [(p["season"], p["difference"]) for p in pairs if p["difference"] is not None]
    by_season = {
        season: sum(v for s, v in differences if s == season)
        / sum(s == season for s, _ in differences)
        for season in DECISION_SEASONS
        if any(s == season for s, _ in differences)
    }
    interval = (
        season_aware_moving_block_interval(
            differences,
            policy=PromotionPolicy(
                bootstrap_resamples=2000, moving_block_length=4, deterministic_seed=0
            ),
            candidate_id=CONTRACT_VERSION,
        )
        if complete
        else None
    )
    return {
        "complete_for_gate": complete,
        "pairs": pairs,
        "paired_decisions": len(differences),
        "mean_difference": sum(v for _, v in differences) / len(differences)
        if differences
        else None,
        "interval": interval,
        "by_season": by_season,
        "wins": sum(v > 0 for _, v in differences),
        "ties": sum(v == 0 for _, v in differences),
        "losses": sum(v < 0 for _, v in differences),
        "changed_squads": sum(
            set(arms["base"][f].optimization_result.selected_squad.player_id)
            != set(arms["candidate"][f].optimization_result.selected_squad.player_id)
            for f in order
            if f in arms["base"]
            and f in arms["candidate"]
            and arms["base"][f].optimization_result.has_solution
            and arms["candidate"][f].optimization_result.has_solution
        ),
    }


def _write_exclusive(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("table", "roster", "manifest"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--prereg-commit", required=True)
    parser.add_argument("--prereg-sha256", required=True)
    parser.add_argument("--attempt-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = [
        REPOSITORY_ROOT / "docs" / f"appearance_recalibration.{ext}" for ext in ("json", "md")
    ]
    if any(path.exists() for path in outputs):
        raise ValueError("Measurement outputs already exist; overwrite is forbidden.")
    provenance = verify_declaration(args.prereg_commit, args.prereg_sha256)
    args.attempt_directory.mkdir(parents=True, exist_ok=True)
    marker = args.attempt_directory / "appearance_recalibration_v1.attempt.json"
    started = datetime.now(UTC)
    _write_exclusive(marker, json.dumps({**provenance, "started_at": started.isoformat()}))
    try:
        document = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_manifest(document)
        handoff = read_phase_c_component_handoff(args.table, args.roster, args.manifest)
        transformed = recalibrate_appearance(handoff.rows)
        print(
            "Verified frozen inputs; prior-only calibration fixed before paired solves.", flush=True
        )
        panel = build_panel(args.archive_root, seasons=HISTORY_SEASONS)
        fallback = build_walk_forward_folds(
            panel,
            seasons=DECISION_SEASONS,
            projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
        )
        base = prepare_phase_c_component_folds(handoff, fallback)
        changed = replace(
            handoff, rows=handoff.rows.assign(control_expected_points=transformed.points)
        )
        candidate = prepare_phase_c_component_folds(changed, base)
        row_readings, ranks, errors = full_roster_readings(base, candidate)
        probability_readings: dict[str, Any] = {}
        for season in (*DECISION_SEASONS, "pooled"):
            mask = transformed.eligible & (
                True if season == "pooled" else handoff.rows.season.eq(season)
            )
            target = handoff.rows.loc[mask, "appearance_target"]
            probability_readings[season] = {
                "base": reliability(handoff.rows.loc[mask, "appearance_probability"], target),
                "candidate": reliability(transformed.probabilities.loc[mask], target),
            }
            before = probability_readings[season]["base"]["brier"]
            after = probability_readings[season]["candidate"]["brier"]
            probability_readings[season]["candidate_minus_base_brier"] = (
                float(after) - float(before) if after is not None and before is not None else None
            )
        config = EvaluationConfig(
            optimization_config=measurement_optimization_config(),
            scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
            run_metadata={"study": CONTRACT_VERSION},
        )
        comparison = evaluate_phase_c_component_decisions(changed, base, config)
        decisions = decision_readings(
            comparison.control, comparison.component_base, document["fold_ids"]
        )
        complete = decisions["complete_for_gate"]
        gate = evaluate_prediction_gate(
            seasons=DECISION_SEASONS,
            positions=POSITIONS,
            ranks=ranks,
            errors=errors,
            decision_mean=decisions["mean_difference"] if complete else None,
            decision_interval=decisions["interval"] if complete else None,
            decision_by_season=decisions["by_season"] if complete else {},
        )
        record = {
            "contract_version": CONTRACT_VERSION,
            "prereg": PREREG,
            **provenance,
            "generated_at_utc": started.isoformat(),
            "operational_control_changed": False,
            "locked_holdout_accessed": False,
            "verdict": gate.verdict,
            "gate": asdict(gate),
            "table_sha256": handoff.table_sha256,
            "roster_sha256": handoff.roster_sha256,
            "manifest_sha256": handoff.manifest_sha256,
            "producer_repository_commit": handoff.repository_commit,
            "solver": solver_record(comparison.control, comparison.component_base),
            "bootstrap": {
                "confidence_level": 0.9,
                "resamples": 2000,
                "block_length": 4,
                "base_seed": 0,
                "candidate_id": CONTRACT_VERSION,
            },
            "software": {
                name: version(name) for name in ("numpy", "pandas", "scikit-learn", "ortools")
            },
            "python": sys.version.split()[0],
            "probabilities": probability_readings,
            "historical_brier_reference": 0.10734,
            "row_readings": row_readings,
            "training_counts": transformed.training_counts.to_dict("records"),
            "direct_control_rows": int(handoff.rows.composition_route.ne("component_model").sum()),
            "blank_rows": int(handoff.rows.fixture_count.eq(0).sum()),
            "decisions": decisions,
            "elapsed_seconds": (datetime.now(UTC) - started).total_seconds(),
        }
        _write_exclusive(outputs[0], json.dumps(record, indent=2, allow_nan=False) + "\n")
        _write_exclusive(outputs[1], markdown(record))
        print(markdown(record), flush=True)
    except Exception as error:
        # Detailed exceptions stay local; no private path is published in a measurement.
        _write_exclusive(
            args.attempt_directory / "appearance_recalibration_v1.failure.json",
            json.dumps({"type": type(error).__name__, "message": str(error)}),
        )
        raise
    return 0


def markdown(record: dict[str, Any]) -> str:
    paired = record["decisions"]
    probability = record["probabilities"]["pooled"]
    introduction = (
        "# Appearance recalibration\n\n"
        f"Verdict **{record['verdict']}** under `{CONTRACT_VERSION}`. "
        f"Ranking: {record['gate']['ranking']}; error: {record['gate']['error']}; "
        f"decisions: {record['gate']['decision']}.\n\n"
        f"Same-row Brier: {probability['base']['brier']} before, "
        f"{probability['candidate']['brier']} after. Historical reference 0.10734 "
        "is not substituted for this paired base.\n\n"
        f"Paired decisions: {paired['paired_decisions']}; mean candidate minus base "
        f"{paired['mean_difference']}; 90% interval {paired['interval']}; "
        f"complete for gate: {paired['complete_for_gate']}.\n\n"
        "The [JSON twin](appearance_recalibration.json) retains seasonal/positional readings, "
        "reliability bins, "
        "training counts, solver statuses and input/declaration identities. "
        "See [the frozen declaration](appearance_recalibration_prereg.md).\n\n"
        "Historical 2021-25 scoring has no DEFCON. This does not establish live DEFCON "
        "performance or top-100 ability and does not promote an operational model.\n"
    )

    def number(value: object) -> str:
        return f"{value:.6f}" if isinstance(value, int | float) else "unavailable"

    lines = [
        introduction,
        "## Same-row probability and full-roster point readings",
        "",
        "All pairs below are base / candidate. Brier uses eligible component rows; "
        "MAE and nonplayer forecast mass use the full roster, including fallbacks and blanks.",
        "",
        "| Season | Brier | Point MAE | Nonplayer forecast mass |",
        "| --- | --- | --- | --- |",
    ]
    for season in (*DECISION_SEASONS, "pooled"):
        probability = record["probabilities"][season]
        arms = record["row_readings"][season]["arms"]
        brier = " / ".join(number(probability[a]["brier"]) for a in ("base", "candidate"))
        mae = " / ".join(number(arms[a]["mae"]) for a in ("base", "candidate"))
        mass = " / ".join(number(arms[a]["nonplayer_forecast_mass"]) for a in ("base", "candidate"))
        lines.append(f"| {season} | {brier} | {mae} | {mass} |")
    lines += [
        "",
        "## Pooled within-position ranking",
        "",
        "| Position | Rows | Base Spearman | Candidate Spearman |",
        "| --- | ---: | ---: | ---: |",
    ]
    for position, block in record["row_readings"]["pooled"]["within_position_rank"].items():
        left, right = block["pair"]
        lines.append(f"| {position} | {block['rows']} | {number(left)} | {number(right)} |")
    lines += [
        "",
        "## Paired decisions by season",
        "",
        "Descriptive means below are not binding when the complete-pair/clock-stop check fails.",
        "",
        "| Season | Candidate minus base |",
        "| --- | ---: |",
    ]
    lines += [f"| {season} | {number(value)} |" for season, value in paired["by_season"].items()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
