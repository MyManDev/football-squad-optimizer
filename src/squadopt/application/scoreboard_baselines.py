"""Reconstruct labelled human baselines from decision-time information only."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pandas as pd

from squadopt.application.scoreboard_diagnostics import score_recorded_decision
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    player_snapshot,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.evaluation.benchmarks import build_constrained_ownership_template
from squadopt.evaluation.models import EvaluationValidationError
from squadopt.features.evidence_artifact import read_player_evidence_artifact
from squadopt.live import LedgerEntry, infer_season


def baseline_score(
    pool: pd.DataFrame, outcomes: pd.DataFrame, *, captain_counts: Mapping[int, float] | None = None
) -> dict[str, object]:
    """A legal, budget-constrained synthetic squad, not an actual manager's entry."""
    try:
        frozen = build_constrained_ownership_template(pool).decision
    except EvaluationValidationError as error:
        raise DataError(f"Human baseline cannot form a proven legal squad: {error}") from error
    if captain_counts is not None:
        order = sorted(
            frozen.starting_xi,
            key=lambda player: (-captain_counts[int(str(player))], int(str(player))),
        )
        frozen = replace(frozen, captain_id=order[0], vice_captain_id=order[1])
    decision = {
        "squad_player_ids": frozen.squad["player_id"].tolist(),
        "starting_xi_player_ids": list(frozen.starting_xi),
        "bench_player_ids": list(frozen.bench),
        "ordered_bench_player_ids": list(frozen.bench),
        "captain_player_id": frozen.captain_id,
        "vice_captain_player_id": frozen.vice_captain_id,
    }
    # Ownership counts are never point predictions. Only the actual projection's
    # expected points/minutes may be used to compute the residual columns.
    result = score_recorded_decision(decision, pool, outcomes)
    return {**result, "construction": "constrained_ownership_template_v2_replay"}


def human_baseline_rows(
    entries: Sequence[LedgerEntry],
    snapshots: Sequence[CapturedSnapshot],
    *,
    evidence_root: Path | None,
    as_of_utc: str,
) -> dict[int, dict[str, dict[str, object]]]:
    """Derive labelled synthetic rows, never recover a missing decision or capture.

    The caller verifies ledger manifests and reads only the required capture IDs.
    Missing source data omits a row; corrupt inputs refuse publication.
    """
    by_id = {item.metadata.snapshot_id: item for item in snapshots}
    cutoff = as_instant(as_of_utc)
    result: dict[int, dict[str, dict[str, object]]] = {}
    for entry in entries:
        outcome = entry.outcome or {}
        settled = by_id.get(str(outcome.get("source_snapshot_id")))
        pre = by_id.get(str(entry.decision.get("snapshot_id")))
        if pre is None or settled is None or live_payload(entry.gameweek) not in settled.payloads:
            continue
        deadline = str(entry.decision.get("deadline_utc", ""))
        if not deadline:
            continue
        deadline_at = as_instant(deadline)
        if (
            BOOTSTRAP_PAYLOAD not in pre.payloads
            or BOOTSTRAP_PAYLOAD not in settled.payloads
            or infer_season(pre) != entry.season
            or infer_season(settled) != entry.season
            or as_instant(pre.metadata.captured_at_utc) >= deadline_at
            or not deadline_at < as_instant(settled.metadata.captured_at_utc) <= cutoff
            or entry.gameweek not in scored_gameweeks(settled.payloads[BOOTSTRAP_PAYLOAD])
        ):
            continue
        deadlines = {
            row.gameweek: as_instant(row.deadline_utc)
            for row in gameweek_deadlines(pre.payloads[BOOTSTRAP_PAYLOAD])
        }
        if deadlines.get(entry.gameweek) != deadline_at:
            raise DataError("Human baseline capture and decision deadlines disagree.")
        projections = pd.read_csv(entry.directory / "projections.csv")
        pool = player_snapshot(pre.payloads[BOOTSTRAP_PAYLOAD])
        prediction_columns = [
            name
            for name in ("player_id", "expected_points", "expected_minutes")
            if name in projections
        ]
        pool = pool.merge(
            projections[prediction_columns], on="player_id", how="left", validate="one_to_one"
        )
        actual = live_event_outcomes(
            settled.payloads[live_payload(entry.gameweek)],
            settled.payloads[BOOTSTRAP_PAYLOAD],
            gameweek=entry.gameweek,
        )
        raw = json.loads(pre.payloads[BOOTSTRAP_PAYLOAD])["elements"]
        ownership = {int(player["code"]): player.get("selected_by_percent") for player in raw}
        pool["ownership"] = pd.to_numeric(pool["player_id"].map(ownership), errors="coerce")
        week: dict[str, dict[str, object]] = {}
        if pool["ownership"].notna().all():
            if not pool["ownership"].between(0, 100).all():
                raise DataError("Captured ownership must be between zero and one hundred.")
            week["ownership_template"] = {
                **baseline_score(pool, actual),
                "source_snapshot_id": pre.metadata.snapshot_id,
                "outcome_snapshot_id": settled.metadata.snapshot_id,
            }
        if evidence_root is not None:
            candidates: list[pd.DataFrame] = []
            for path in sorted(
                evidence_root.glob(
                    f"player_evidence_v1_{entry.season}_gw{entry.gameweek:02d}_top100*.csv"
                )
            ):
                evidence = read_player_evidence_artifact(path, path.with_suffix(".manifest.json"))
                if not (
                    (evidence["season"] == entry.season).all()
                    and (evidence["target_gameweek"] == entry.gameweek).all()
                    and (
                        pd.to_datetime(evidence["deadline_timestamp_utc"], utc=True)
                        == pd.Timestamp(deadline)
                    ).all()
                ):
                    raise DataError("Human baseline evidence names another decision.")
                if (
                    pd.to_datetime(evidence["captured_at_utc"], utc=True)
                    <= pd.Timestamp(pre.metadata.captured_at_utc)
                ).all():
                    candidates.append(evidence)
            if candidates:
                evidence = max(candidates, key=lambda table: str(table["captured_at_utc"].max()))
                counts = evidence.set_index("player_id")
                required = ["elite_start_count_lag1", "elite_captain_count_lag1"]
                if (
                    (evidence["elite_members_observed"] == 100).all()
                    and (evidence["elite_cohort_size"] == 100).all()
                    and counts[required].notna().all().all()
                    and set(pool["player_id"]) <= set(counts.index)
                ):
                    elite_pool = pool.copy(deep=True)
                    elite_pool["ownership"] = (
                        elite_pool["player_id"].map(counts["elite_start_count_lag1"]).astype(float)
                    )
                    armbands: dict[int, float] = {
                        int(str(code)): float(value)
                        for code, value in counts["elite_captain_count_lag1"].items()
                    }
                    week["elite_xi"] = {
                        **baseline_score(elite_pool, actual, captain_counts=armbands),
                        "source_snapshot_id": str(evidence["source_snapshot_ids"].iloc[0]),
                        "outcome_snapshot_id": settled.metadata.snapshot_id,
                    }
        result[entry.gameweek] = week
    return result
