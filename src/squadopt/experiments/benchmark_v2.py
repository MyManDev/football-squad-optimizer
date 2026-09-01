"""Binding Benchmark V2 measurements on frozen development and live inputs."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from numbers import Real
from statistics import mean, median
from typing import Final

import pandas as pd

from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    POSITION_CODES,
    EntryPicksRecord,
    fpl_entry_picks,
    fpl_league_standings_page,
    gameweek_deadlines,
    league_standings_page_payload,
    player_codes,
    player_snapshot,
)
from squadopt.evaluation import (
    AsOfTop100Cohort,
    EvaluationValidationError,
    FrozenSquadDecision,
    RankedManager,
    ScoringPolicy,
    audit_unconstrained_template_v1,
    build_constrained_ownership_template,
    complete_optimization_decision,
    score_frozen_squad_decision,
    score_realized_squad_points,
    select_as_of_top_100,
)
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.scenarios.rivals import template_rival_from_ownership

BENCHMARK_V2_CONTRACT_VERSION: Final = "benchmark_v2"
DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")
OVERALL_LEAGUE_ID: Final = 314
TOP100_PAGES: Final = (1, 2)
_PICKS_PATTERN: Final = re.compile(r"^entry-(\d+)-picks-gw(\d{2})\.json$")


def _object(document: bytes, label: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(document.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationValidationError(f"{label} is not UTF-8 JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise EvaluationValidationError(f"{label} must be a JSON object.")
    return parsed


def _decision_from_record(
    record: EntryPicksRecord,
    *,
    player_pool: pd.DataFrame,
    codes: Mapping[int, object],
) -> FrozenSquadDecision:
    """Translate captured element ids without importing the application layer."""

    missing_elements = [element for element in record.squad if element not in codes]
    if missing_elements:
        raise EvaluationValidationError(
            f"No persistent player code for captured elements {missing_elements[:5]!r}."
        )
    translated = {element: codes[element] for element in record.squad}
    squad_ids = tuple(translated[element] for element in record.squad)
    if len(set(squad_ids)) != len(squad_ids):
        raise EvaluationValidationError(
            "Captured elements do not map to distinct persistent player codes."
        )

    indexed = player_pool.set_index("player_id", drop=False)
    missing_players = [player_id for player_id in squad_ids if player_id not in indexed.index]
    if missing_players:
        raise EvaluationValidationError(
            f"Player pool does not cover captured players {missing_players[:5]!r}."
        )
    return FrozenSquadDecision(
        squad=indexed.loc[list(squad_ids)].reset_index(drop=True),
        starting_xi=tuple(translated[element] for element in record.starting_xi),
        bench=tuple(translated[element] for element in record.squad[11:]),
        captain_id=translated[record.captain],
        vice_captain_id=translated[record.vice_captain],
        completion_policy="captured_entry_v1",
    )


def measure_settled_entry_parity(
    snapshot: CapturedSnapshot,
    *,
    season: str,
    gameweek: int,
) -> Mapping[str, object]:
    """Compare V2 with official normal-week scores without publishing identities."""

    if snapshot.metadata.source != "fpl-live":
        raise EvaluationValidationError("Entry parity requires an fpl-live snapshot.")
    bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if bootstrap is None:
        raise EvaluationValidationError("Entry parity snapshot has no bootstrap payload.")
    events = _object(bootstrap, "Bootstrap").get("events")
    if not isinstance(events, list):
        raise EvaluationValidationError("Bootstrap must carry an events array.")
    target_events = [
        event for event in events if isinstance(event, dict) and event.get("id") == gameweek
    ]
    if len(target_events) != 1 or target_events[0].get("data_checked") is not True:
        raise EvaluationValidationError(
            f"Gameweek {gameweek} is not uniquely present and data_checked in the snapshot."
        )

    codes = player_codes(bootstrap)
    pool = player_snapshot(bootstrap)
    bootstrap_document = _object(bootstrap, "Bootstrap")
    elements = bootstrap_document.get("elements")
    if not isinstance(elements, list):
        raise EvaluationValidationError("Bootstrap must carry an elements array.")
    outcomes: list[dict[str, object]] = []
    for element in elements:
        if not isinstance(element, dict) or element.get("element_type") not in POSITION_CODES:
            continue
        element_id = element.get("id")
        event_points = element.get("event_points")
        minutes = element.get("minutes")
        if (
            isinstance(element_id, bool)
            or not isinstance(element_id, int)
            or isinstance(event_points, bool)
            or not isinstance(event_points, int)
            or isinstance(minutes, bool)
            or not isinstance(minutes, int)
        ):
            raise EvaluationValidationError(
                "Bootstrap parity inputs require integer id, event_points and minutes."
            )
        outcomes.append(
            {
                "player_id": codes[element_id],
                "total_points": event_points,
                "minutes": minutes,
            }
        )
    realized = pd.DataFrame(outcomes)

    compared = 0
    exact = 0
    differences: list[float] = []
    exclusions: dict[str, int] = {"active_chip": 0, "transfer_hit": 0, "missing_history": 0}
    for name, picks_payload in sorted(snapshot.payloads.items()):
        match = _PICKS_PATTERN.match(name)
        if match is None or int(match.group(2)) != gameweek:
            continue
        entry_id = int(match.group(1))
        picks_document = _object(picks_payload, "Entry picks")
        if picks_document.get("active_chip") is not None:
            exclusions["active_chip"] += 1
            continue
        entry_history = picks_document.get("entry_history")
        if not isinstance(entry_history, dict):
            exclusions["missing_history"] += 1
            continue
        transfer_cost = entry_history.get("event_transfers_cost")
        official_points = entry_history.get("points")
        if transfer_cost != 0:
            exclusions["transfer_hit"] += 1
            continue
        if isinstance(official_points, bool) or not isinstance(official_points, int):
            exclusions["missing_history"] += 1
            continue
        history_name = f"entry-{entry_id}-history.json"
        history = snapshot.payloads.get(history_name)
        if history is None:
            exclusions["missing_history"] += 1
            continue
        source_record = fpl_entry_picks(
            picks_payload,
            history,
            entry_id=entry_id,
            season=season,
            gameweek=gameweek,
            source_snapshot_id=snapshot.metadata.snapshot_id,
        )
        decision = _decision_from_record(
            source_record,
            player_pool=pool,
            codes=codes,
        )
        score = score_frozen_squad_decision(decision, realized)
        difference = score.total_points - official_points
        compared += 1
        exact += int(difference == 0.0)
        differences.append(difference)

    if compared == 0:
        raise EvaluationValidationError("No normal-week settled entry is evaluable for parity.")
    return {
        "snapshot_id": snapshot.metadata.snapshot_id,
        "season": season,
        "gameweek": gameweek,
        "entries_compared": compared,
        "exact_matches": exact,
        "max_absolute_difference": max(abs(value) for value in differences),
        "mean_difference": mean(differences),
        "status": "passed" if exact == compared else "failed",
        "exclusions": exclusions,
    }


def validate_top100_capture(
    snapshot: CapturedSnapshot,
    *,
    target_gameweek: int,
) -> tuple[AsOfTop100Cohort, Mapping[str, object]]:
    """Validate a prospective Overall Top-100 snapshot without exposing its members."""

    if snapshot.metadata.source != "fpl-top100":
        raise EvaluationValidationError("Top-100 capture must use source 'fpl-top100'.")
    bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if bootstrap is None:
        raise EvaluationValidationError("Top-100 capture has no bootstrap payload.")
    deadlines = {deadline.gameweek: deadline for deadline in gameweek_deadlines(bootstrap)}
    if target_gameweek not in deadlines:
        raise EvaluationValidationError(f"No deadline for target gameweek {target_gameweek}.")
    deadline = deadlines[target_gameweek]
    rankings: list[RankedManager] = []
    source_updates: set[str] = set()
    for page_number in TOP100_PAGES:
        name = league_standings_page_payload(OVERALL_LEAGUE_ID, page_number)
        payload = snapshot.payloads.get(name)
        if payload is None:
            raise EvaluationValidationError(f"Top-100 capture is missing {name}.")
        page = fpl_league_standings_page(
            payload,
            league_id=OVERALL_LEAGUE_ID,
            expected_page=page_number,
        )
        source_updates.add(page.last_updated_data)
        for member in page.members:
            rank_sort = member.rank_sort
            if rank_sort is not None and rank_sort <= 100:
                rankings.append(RankedManager(entry_id=member.entry_id, rank=rank_sort))
    if len(rankings) != 100 or {record.rank for record in rankings} != set(range(1, 101)):
        raise EvaluationValidationError(
            "Top-100 snapshot must contain each rank_sort value from 1 through 100 once."
        )
    cohort = select_as_of_top_100(
        rankings,
        target_gameweek=target_gameweek,
        captured_at_utc=snapshot.metadata.captured_at_utc,
        deadline_timestamp_utc=deadline.deadline_utc,
        source_snapshot_id=snapshot.metadata.snapshot_id,
    )
    return cohort, {
        "snapshot_id": snapshot.metadata.snapshot_id,
        "target_gameweek": target_gameweek,
        "captured_at_utc": snapshot.metadata.captured_at_utc,
        "deadline_timestamp_utc": deadline.deadline_utc,
        "member_count": len(cohort.entry_ids),
        "source_update_timestamp_count": len(source_updates),
        "status": "pending_settlement",
    }


def _v1_score(starters: Sequence[object], captain: object, points: Mapping[object, float]) -> float:
    return sum(points[player_id] for player_id in starters) + points[captain]


def _row_number(row: Mapping[str, object], key: str) -> float:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, Real):
        raise EvaluationValidationError(f"Benchmark row field {key!r} is not numeric.")
    return float(value)


def measure_historical_v1_v2(
    residuals: pd.DataFrame,
    panel: pd.DataFrame,
    ownership: pd.DataFrame,
    *,
    config: OptimizationConfig | None = None,
) -> Mapping[str, object]:
    """Score V1 and V2 on identical folds, inputs and realized outcomes."""

    settings = OptimizationConfig() if config is None else config
    rows: list[dict[str, object]] = []
    for fold_id, block in residuals.groupby("fold_id", sort=True):
        season = str(block["season"].iloc[0])
        gameweek = int(block["gameweek"].iloc[0])
        if season not in DEVELOPMENT_SEASONS:
            raise EvaluationValidationError(f"Unexpected benchmark season {season!r}.")
        context = panel.loc[
            (panel["season"] == season) & (panel["gameweek"] == gameweek),
            ["player_id", "name", "price_tenths", "minutes"],
        ]
        owned = ownership.loc[
            (ownership["season"] == season) & (ownership["gameweek"] == gameweek),
            ["player_id", "selected"],
        ]
        pool = block.merge(context, on="player_id", how="left", validate="one_to_one").merge(
            owned, on="player_id", how="left", validate="one_to_one"
        )
        if bool(pool[["name", "price_tenths", "minutes"]].isna().any().any()):
            raise EvaluationValidationError(f"Fold {fold_id} has incomplete panel context.")
        pool["ownership"] = pool["selected"].fillna(0.0)
        projection = pool.loc[
            :, ["player_id", "name", "team_id", "position", "price_tenths"]
        ].copy()
        projection["expected_points"] = pool["predicted_points"].clip(lower=0.0)
        realized = pool.loc[:, ["player_id", "realized_points", "minutes"]].rename(
            columns={"realized_points": "total_points"}
        )
        points = {
            player_id: float(total_points)
            for player_id, total_points in realized.loc[
                :, ["player_id", "total_points"]
            ].itertuples(index=False, name=None)
        }

        neutral = optimize_squad(projection, settings)
        if not neutral.has_solution or neutral.captain is None:
            raise EvaluationValidationError(f"Fold {fold_id} has no feasible control squad.")
        system_v1 = score_realized_squad_points(
            neutral, realized, policy=ScoringPolicy.STARTING_XI_CAPTAIN_V1
        )
        neutral_decision = complete_optimization_decision(neutral)
        system_v2_detail = score_frozen_squad_decision(neutral_decision, realized)

        template_pool = pool.loc[
            :, ["player_id", "name", "team_id", "position", "price_tenths", "ownership"]
        ]
        template_v1 = template_rival_from_ownership(
            template_pool.loc[:, ["player_id", "position", "ownership"]]
        )
        template_v1_score = _v1_score(template_v1.starter_ids, template_v1.captain_id, points)
        template_v1_audit = audit_unconstrained_template_v1(
            template_pool, template_v1.starter_ids, settings
        )

        template_v2 = build_constrained_ownership_template(template_pool, settings)
        template_v2_under_v1 = _v1_score(
            template_v2.decision.starting_xi,
            template_v2.decision.captain_id,
            points,
        )
        template_v2_detail = score_frozen_squad_decision(template_v2.decision, realized)
        system_starters = tuple(neutral.starting_xi["player_id"].tolist())
        minute_by_player = dict(
            realized.loc[:, ["player_id", "minutes"]].itertuples(index=False, name=None)
        )
        rows.append(
            {
                "fold_id": str(fold_id),
                "season": season,
                "gameweek": gameweek,
                "system_v1": system_v1,
                "system_v2": system_v2_detail.total_points,
                "template_v1": template_v1_score,
                "template_v2_under_v1": template_v2_under_v1,
                "template_v2": template_v2_detail.total_points,
                "v1_gap_template_minus_system": template_v1_score - system_v1,
                "v2_gap_template_minus_system": (
                    template_v2_detail.total_points - system_v2_detail.total_points
                ),
                "overall_gap_change": (
                    template_v2_detail.total_points
                    - system_v2_detail.total_points
                    - template_v1_score
                    + system_v1
                ),
                "template_construction_effect_under_v1": (template_v2_under_v1 - template_v1_score),
                "system_scoring_effect": system_v2_detail.total_points - system_v1,
                "template_scoring_effect": (template_v2_detail.total_points - template_v2_under_v1),
                "system_zero_minute_starters": sum(
                    minute_by_player[player_id] == 0 for player_id in system_starters
                ),
                "template_zero_minute_starters": sum(
                    minute_by_player[player_id] == 0
                    for player_id in template_v2.decision.starting_xi
                ),
                "system_autosub_points": system_v2_detail.autosub_points,
                "template_autosub_points": template_v2_detail.autosub_points,
                "system_vice_recovered": bool(
                    system_v2_detail.captain_bonus_player_id == neutral_decision.vice_captain_id
                    and system_v2_detail.captain_bonus_player_id != neutral.captain["player_id"]
                ),
                "template_vice_recovered": bool(
                    template_v2_detail.captain_bonus_player_id
                    == template_v2.decision.vice_captain_id
                    and template_v2_detail.captain_bonus_player_id
                    != template_v2.decision.captain_id
                ),
                "v1_team_limit_violated": template_v1_audit["team_limit_violated"],
                "v1_xi_exceeds_full_squad_budget": template_v1_audit[
                    "xi_exceeds_full_squad_budget"
                ],
            }
        )
    if not rows:
        raise EvaluationValidationError("No historical Benchmark V2 fold was scored.")

    numeric = (
        "system_v1",
        "system_v2",
        "template_v1",
        "template_v2_under_v1",
        "template_v2",
        "v1_gap_template_minus_system",
        "v2_gap_template_minus_system",
        "overall_gap_change",
        "template_construction_effect_under_v1",
        "system_scoring_effect",
        "template_scoring_effect",
        "system_zero_minute_starters",
        "template_zero_minute_starters",
        "system_autosub_points",
        "template_autosub_points",
    )
    summary: dict[str, object] = {"folds": len(rows)}
    for key in numeric:
        values = [_row_number(row, key) for row in rows]
        summary[f"mean_{key}"] = mean(values)
        summary[f"median_{key}"] = median(values)
    summary["system_vice_recovery_count"] = sum(bool(row["system_vice_recovered"]) for row in rows)
    summary["template_vice_recovery_count"] = sum(
        bool(row["template_vice_recovered"]) for row in rows
    )
    summary["v1_team_limit_violation_folds"] = sum(
        bool(row["v1_team_limit_violated"]) for row in rows
    )
    summary["v1_xi_budget_violation_folds"] = sum(
        bool(row["v1_xi_exceeds_full_squad_budget"]) for row in rows
    )
    summary["all_values_finite"] = all(
        math.isfinite(_row_number(row, key)) for row in rows for key in numeric
    )
    per_season = {
        season: {
            "folds": len(season_rows),
            "mean_v1_gap": mean(
                _row_number(row, "v1_gap_template_minus_system") for row in season_rows
            ),
            "mean_v2_gap": mean(
                _row_number(row, "v2_gap_template_minus_system") for row in season_rows
            ),
            "mean_gap_change": mean(_row_number(row, "overall_gap_change") for row in season_rows),
        }
        for season in DEVELOPMENT_SEASONS
        if (season_rows := [row for row in rows if row["season"] == season])
    }
    return {
        "contract_version": BENCHMARK_V2_CONTRACT_VERSION,
        "status": "descriptive_unverified_ownership_timing",
        "seasons": list(DEVELOPMENT_SEASONS),
        "summary": summary,
        "per_season": per_season,
        "rows": rows,
    }


__all__ = [
    "BENCHMARK_V2_CONTRACT_VERSION",
    "DEVELOPMENT_SEASONS",
    "measure_historical_v1_v2",
    "measure_settled_entry_parity",
    "validate_top100_capture",
]
