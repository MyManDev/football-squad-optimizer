"""Read the pre-registered Top-100 effect at settled GW12/GW20; never solve or tune.

Only immutable captures, ledger, handoffs, exports and advice records are inputs.
No actual reading is authorized by implementing this instrument.
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT

from squadopt.application.weekly_suggestion_eval import score_recorded_advice, select_record
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FPL_LIVE_SOURCE,
    availability_snapshot,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    player_snapshot,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.evaluation.models import EvaluationValidationError
from squadopt.evaluation.top100_effect import (
    RESAMPLES,
    SEED,
    plan_changed,
    plan_reading,
    player_reading,
)
from squadopt.features.evidence_artifact import read_player_evidence_artifact
from squadopt.live import infer_season
from squadopt.live.ledger import load_entry
from squadopt.live.recommendation import InSeasonProjection, read_projection_handoff
from squadopt.prediction.availability import apply_availability
from squadopt.prediction.elite_evidence import apply_elite_evidence

CONTRACT = "top100_effect_readout_v1"
SEASON = "2026-27"
WEIGHTS = (5, 10, 20, 30, 40, 50)
PAIR_COLUMNS = ["gameweek", "weight", "difference", "changed", "published_cost"]
PLAYER_COLUMNS = ["gameweek", "player_id", "position", "m", "s", "y", "minutes"]


def checkpoint(snapshot: CapturedSnapshot, season: str, through: int) -> None:
    """Fail before consulting any projection, export, advice or outcome adapter."""
    if season != SEASON or through not in (12, 20):
        raise ValueError("Only 2026-27 GW12/GW20 are registered checkpoints.")
    if infer_season(snapshot) != season:
        raise ValueError("Outcome capture season does not match the protocol.")
    settled = scored_gameweeks(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    if not settled or max(settled) != through or not set(range(5, through + 1)) <= settled:
        raise ValueError("Checkpoint not settled, or an intervening/later week is already settled.")


def _projection(
    root: Path, capture: str, fingerprint: object, season: str, week: int
) -> InSeasonProjection:
    matches = [
        value
        for path in sorted((root / "handoffs" / "by-capture" / capture).glob("*.json"))
        if (value := read_projection_handoff(path)).fingerprint == fingerprint
    ]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous exact projection.")
    projection = matches[0]
    if (
        projection.season != season
        or projection.gameweek != week
        or projection.source_snapshot_id != capture
        or projection.evidence_fingerprint is not None
    ):
        raise ValueError("Not the same capture's unadjusted base projection.")
    return projection


def _evidence(
    root: Path, projection: InSeasonProjection, capture: CapturedSnapshot, deadline: str
) -> pd.DataFrame:
    valid: list[pd.DataFrame] = []
    points = pd.DataFrame(
        {
            "player_id": list(projection.expected_points),
            "expected_points": list(projection.expected_points.values()),
        }
    )
    pattern = f"player_evidence_v1_{projection.season}_gw{projection.gameweek:02d}_top100*.csv"
    for path in sorted(root.glob(pattern)):
        evidence = read_player_evidence_artifact(path, path.with_suffix(".manifest.json"))
        # Late exports are ineligible, never selected using any outcome statistic.
        if as_instant(str(evidence.attrs["generated_at_utc"])) > as_instant(
            capture.metadata.captured_at_utc
        ):
            continue
        try:
            apply_elite_evidence(
                points,
                evidence,
                season=projection.season,
                target_gameweek=projection.gameweek,
                deadline_timestamp_utc=deadline,
                decision_captured_at_utc=capture.metadata.captured_at_utc,
            )
        except (DataError, ValueError):
            continue
        valid.append(evidence)
    if not valid:
        raise ValueError("No eligible export under the handoff's own gate.")
    valid.sort(key=lambda table: as_instant(str(table.attrs["generated_at_utc"])))
    if (
        len(valid) > 1
        and valid[-2].attrs["generated_at_utc"] == valid[-1].attrs["generated_at_utc"]
    ):
        raise ValueError("Ambiguous evidence exports.")
    return valid[-1]


def _context(
    root: Path,
    evidence_root: Path,
    capture_id: object,
    fingerprint: object,
    season: str,
    week: int,
    deadline: str,
) -> tuple[CapturedSnapshot, InSeasonProjection, pd.DataFrame]:
    if not isinstance(capture_id, str) or not capture_id or Path(capture_id).name != capture_id:
        raise ValueError("Missing capture identity.")
    capture = read_snapshot(root / "snapshots", capture_id)
    if infer_season(capture) != season or as_instant(
        capture.metadata.captured_at_utc
    ) >= as_instant(deadline):
        raise ValueError("Capture was not available for this decision.")
    own_deadlines = {
        d.gameweek: d.deadline_utc for d in gameweek_deadlines(capture.payloads[BOOTSTRAP_PAYLOAD])
    }
    if own_deadlines.get(week) != deadline:
        raise ValueError("Decision and outcome capture disagree about the deadline.")
    projection = _projection(root, capture_id, fingerprint, season, week)
    evidence = _evidence(evidence_root, projection, capture, deadline)
    return capture, projection, evidence


def player_frame(
    capture: CapturedSnapshot,
    projection: InSeasonProjection,
    evidence: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    bootstrap = capture.payloads[BOOTSTRAP_PAYLOAD]
    points = pd.DataFrame(
        {
            "player_id": list(projection.expected_points),
            "expected_points": list(projection.expected_points.values()),
        }
    )
    scaled = apply_availability(points, availability_snapshot(bootstrap))
    # Keep every player the handoff names; missing metadata/outcomes reject the week.
    roster = player_snapshot(bootstrap)[["player_id", "position"]]
    frame = points.merge(roster, on="player_id", how="left", validate="one_to_one")
    frame["m"] = points.expected_points.to_numpy() * scaled.multiplier.to_numpy()
    frame = frame.merge(
        outcomes[["player_id", "total_points", "minutes"]],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    if frame[["position", "total_points", "minutes"]].isna().any().any():
        raise ValueError("Incomplete decided roster or outcomes.")
    support = evidence.set_index("player_id").elite_start_count_lag1 / 100.0
    frame["s"] = frame.player_id.map(support).fillna(0.0)
    frame["gameweek"] = projection.gameweek
    return frame.rename(columns={"total_points": "y"})[PLAYER_COLUMNS]


def score_pairs(
    record: Mapping[str, Any], outcomes: pd.DataFrame, week: int
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """One plain saf-puan/window1 pair per menu weight; no reconstructed plans."""
    entry = int(record["entry_id"])
    prefix = f"advice/{entry}/saf-puan/1"
    advice = [
        x
        for x in record["advice"]
        if (
            x.get("strategy") == "saf-puan"
            and x.get("window") == 1
            and x.get("rival_entry_id") is None
            and not x.get("managers_word")
        )
    ]
    base = [
        x
        for x in advice
        if x.get("published_path") == f"{prefix}.json" and x.get("top100_weight") in (None, 0)
    ]
    exclusions: Counter[str] = Counter()
    if len(base) != 1:
        return [], Counter({"missing_or_ambiguous_control": len(WEIGHTS)})
    pairs = []
    for weight in WEIGHTS:
        weighted = [
            x
            for x in advice
            if x.get("published_path") == f"{prefix}/top100-{weight}.json"
            and x.get("top100_weight") == weight
        ]
        if len(weighted) != 1:
            exclusions["missing_or_ambiguous_weight"] += 1
            continue
        try:
            control_score, _ = score_recorded_advice(record, base[0], outcomes)
            weighted_score, _ = score_recorded_advice(record, weighted[0], outcomes)
        except (DataError, EvaluationValidationError, ValueError, KeyError, TypeError):
            exclusions["incomplete_or_unscorable_pair"] += 1
            continue
        cost = weighted[0].get("expected_points_cost")
        if isinstance(cost, bool) or not isinstance(cost, int | float) or not math.isfinite(cost):
            cost = None
        pairs.append(
            {
                "gameweek": week,
                "weight": weight,
                "difference": weighted_score.net_points - control_score.net_points,
                "changed": plan_changed(base[0], weighted[0]),
                "published_cost": cost,
            }
        )
    return pairs, exclusions


def collect(root: Path, evidence_root: Path, season: str, through: int) -> dict[str, Any]:
    identifiers = list_snapshot_ids(root / "snapshots", source=FPL_LIVE_SOURCE)
    if not identifiers:
        raise ValueError("No captures available.")
    # Snapshot IDs include a sortable UTC timestamp. No historical outcome search/fallback.
    settled = read_snapshot(root / "snapshots", sorted(identifiers)[-1])
    checkpoint(settled, season, through)
    bootstrap = settled.payloads[BOOTSTRAP_PAYLOAD]
    deadlines = {d.gameweek: d.deadline_utc for d in gameweek_deadlines(bootstrap)}
    frames, pairs, provenance, omitted = [], [], [], []
    excluded_pairs: Counter[str] = Counter()
    for week in range(5, through + 1):
        stage = "settled_outcomes"
        try:
            outcomes = live_event_outcomes(
                settled.payloads[live_payload(week)], bootstrap, gameweek=week
            )
            stage = "decided_ledger"
            decision = load_entry(root / "ledger", season, week).decision
            metadata = decision.get("metadata")
            if (
                not isinstance(metadata, dict)
                or metadata.get("projection_evidence_fingerprint") is not None
            ):
                raise ValueError("Missing base identity.")
            stage = "decided_base_and_export_gate"
            capture, projection, evidence = _context(
                root,
                evidence_root,
                decision.get("snapshot_id"),
                metadata.get("projection_handoff_fingerprint"),
                season,
                week,
                deadlines[week],
            )
            stage = "complete_player_roster"
            frames.append(player_frame(capture, projection, evidence, outcomes))
            provenance.append(
                {
                    "gameweek": week,
                    "capture": capture.metadata.snapshot_id,
                    "projection": projection.fingerprint,
                    "export_sha256": evidence.attrs["table_sha256"],
                }
            )
        except (DataError, ValueError, OSError, KeyError, TypeError) as error:
            omitted.append({"gameweek": week, "reason": stage, "error_type": type(error).__name__})
            # No repair or post-hoc projection selection for either reading.
            continue
        if week == 5:
            continue
        directory = root / "advice_records" / season / f"gw{week:02d}"
        for member in sorted(directory.glob("entry-*")):
            if not member.is_dir() or not member.name.removeprefix("entry-").isdigit():
                continue
            try:
                record = select_record(
                    root / "advice_records",
                    season=season,
                    gameweek=week,
                    entry_id=int(member.name.removeprefix("entry-")),
                    deadline_utc=deadlines[week],
                )
                if record is None:
                    raise ValueError("No pre-deadline record.")
                own = record["provenance"]
                if own.get("projection_evidence_fingerprint") is not None:
                    raise ValueError("Member projection already carries uplift.")
                member_capture, member_projection, member_evidence = _context(
                    root,
                    evidence_root,
                    record["capture"]["snapshot_id"],
                    own.get("projection_handoff_fingerprint"),
                    season,
                    week,
                    deadlines[week],
                )
                scored, refused = score_pairs(record, outcomes, week)
                pairs.extend(scored)
                excluded_pairs.update(refused)
                # No member identifiers, visitor addresses or absolute paths in public artifacts.
                provenance.append(
                    {
                        "gameweek": week,
                        "member_record_sha256": hashlib.sha256(
                            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest(),
                        "publication": record["generated_at_utc"],
                        "capture": member_capture.metadata.snapshot_id,
                        "projection": member_projection.fingerprint,
                        "export_sha256": member_evidence.attrs["table_sha256"],
                    }
                )
            except (DataError, ValueError, OSError, KeyError, TypeError):
                excluded_pairs["ineligible_member_record"] += len(WEIGHTS)
    return {
        "contract_version": CONTRACT,
        "season": season,
        "through_gameweek": through,
        "protocol": "docs/top100_effect_prereg.md",
        "operational_control_changed": False,
        "solver_invoked": False,
        "outcome_capture": settled.metadata.snapshot_id,
        "bootstrap": {
            "unit": "whole_gameweek",
            "resamples": RESAMPLES,
            "seed": SEED,
            "confidence": 0.9,
        },
        "player_level": player_reading(
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PLAYER_COLUMNS)
        ),
        "plan_level": plan_reading(pd.DataFrame(pairs, columns=PAIR_COLUMNS)),
        "excluded_weeks": omitted,
        "excluded_plan_pairs": dict(excluded_pairs),
        "inputs": provenance,
        "limitations": (
            "Descriptive direction only; dependent members and nested weights are not "
            "independent samples. Cannot establish menu-sized gains of tenths of a point. "
            "No causal, promotion or top-100 ability claim. GW4 replay omitted; "
            "GW5 plans never reconstructed."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", required=True, choices=[SEASON])
    parser.add_argument("--through-gameweek", type=int, required=True, choices=[12, 20])
    parser.add_argument("--data-root", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args(argv)
    stem = REPOSITORY_ROOT / "docs" / f"top100_effect_gw{args.through_gameweek}"
    outputs = [stem.with_suffix(ext) for ext in (".json", ".md")]
    if any(path.exists() for path in outputs):
        raise ValueError("Reading already exists; no overwrite or repeat.")
    record = collect(
        args.data_root,
        args.evidence_root or args.data_root.parent / "artifacts" / "phase_b",
        args.season,
        args.through_gameweek,
    )
    payload = json.dumps(record, indent=2, allow_nan=False) + "\n"
    markdown = (
        f"# Top 100 effect: GW{args.through_gameweek}\n\n"
        "Descriptive read-out under [the frozen protocol](top100_effect_prereg.md). "
        "Nothing is fitted or promoted. All intervals resample whole gameweeks; fewer than six "
        "weeks means no interval and eight clusters make a rough interval.\n\n"
        f"{record['limitations']}\n\n"
        f"Full statistics, exclusions and input identities: [JSON twin]({outputs[0].name}).\n\n"
        "```json\n"
        + json.dumps(
            {
                k: record[k]
                for k in ("player_level", "plan_level", "excluded_weeks", "excluded_plan_pairs")
            },
            indent=2,
            allow_nan=False,
        )
        + "\n```\n"
    )
    for path, contents in zip(outputs, (payload, markdown), strict=True):
        with path.open("x", encoding="utf-8") as stream:
            stream.write(contents)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
