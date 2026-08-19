"""Builders: from the live path's records to ``ui_view_v1`` view models.

The primary path reads a **frozen ledger entry** (``decision.json`` plus the entry's
``projections.csv``), because that is the record a decision was made from and the only
one a reader should be shown. The in-memory path (a ``Recommendation`` just built) exists
for the moment a decision is being recorded and carries the fuller risk block; it must
agree with the ledger path on everything the ledger stores.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pandas as pd

from squadopt.application.views import (
    JsonValue,
    LedgerRowView,
    LedgerView,
    PlayerView,
    PoolPlayerView,
    PoolView,
    RecommendationView,
    RiskView,
    RivalComparisonView,
    RunLogEventView,
    StatusView,
    TickActionView,
    TransferView,
    ViewError,
    jsonable,
    positions_in_order,
    short_name,
)
from squadopt.live.ledger import LedgerEntry, load_ledger
from squadopt.live.report import Recommendation
from squadopt.live.risk import LiveRiskDiagnostics
from squadopt.live.tick import LedgerState, TickPlan

_PROJECTIONS_FILE = "projections.csv"


def _ints(value: object) -> list[int]:
    return [int(str(v)) for v in list(value)] if isinstance(value, list | tuple) else []


def _strs(value: object) -> list[str]:
    return [str(v) for v in list(value)] if isinstance(value, list | tuple) else []


def _int_map(value: object) -> dict[int, int]:
    return (
        {int(str(k)): int(str(v)) for k, v in value.items()} if isinstance(value, Mapping) else {}
    )


def _mapping(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _pair(value: object) -> tuple[float, float] | None:
    if isinstance(value, list | tuple) and len(value) == 2:
        return (float(str(value[0])), float(str(value[1])))
    return None


_UNKNOWN_POSITION = "UNK"
_LEDGER_RISK_LIMIT = (
    "The frozen ledger records the risk status only; the full risk block, when one was "
    "evaluated, is in the entry's report.txt."
)


# --- players ------------------------------------------------------------------


def _player_index(projections: pd.DataFrame) -> dict[int, dict[str, object]]:
    if not {"player_id", "name", "team_id", "position", "price_tenths", "expected_points"} <= set(
        projections.columns
    ):
        raise ViewError(
            "projections need player_id, name, team_id, position, price_tenths, expected_points."
        )
    return {
        int(str(row["player_id"])): {str(key): value for key, value in row.items()}
        for row in projections.to_dict("records")
    }


def _player(
    index: Mapping[int, Mapping[str, object]],
    player_id: int,
    *,
    role: str,
    is_captain: bool = False,
    bench_order: int | None = None,
    price_override: int | None = None,
) -> PlayerView:
    row = index.get(int(player_id))
    if row is None:
        # A player who left the projected pool (an outgoing transfer, typically): the
        # ledger still names him by id and price; the page must not invent the rest.
        return PlayerView(
            player_id=int(player_id),
            name=f"player {int(player_id)}",
            short_name=f"#{int(player_id)}",
            team="",
            position=_UNKNOWN_POSITION,
            price_tenths=int(price_override or 0),
            expected_points=0.0,
            role=role,
            is_captain=is_captain,
            bench_order=bench_order,
        )
    return PlayerView(
        player_id=int(player_id),
        name=str(row["name"]),
        short_name=short_name(str(row["name"])),
        team=str(row["team_id"]),
        position=str(row["position"]),
        price_tenths=(
            int(price_override) if price_override is not None else int(str(row["price_tenths"]))
        ),
        expected_points=float(str(row["expected_points"])),
        role=role,
        is_captain=is_captain,
        bench_order=bench_order,
    )


def _players_from_ids(
    index: Mapping[int, Mapping[str, object]],
    starters: Sequence[int],
    bench: Sequence[int],
    captain: int,
) -> tuple[tuple[PlayerView, ...], tuple[PlayerView, ...], tuple[PlayerView, ...]]:
    xi = positions_in_order(
        [_player(index, p, role="starter", is_captain=(int(p) == int(captain))) for p in starters]
    )
    bench_views = tuple(
        _player(index, p, role="bench", bench_order=order) for order, p in enumerate(bench, 1)
    )
    return (*xi, *bench_views), xi, bench_views


# --- transfers and risk --------------------------------------------------------


def _transfer_view(
    block: Mapping[str, object], index: Mapping[int, Mapping[str, object]]
) -> TransferView:
    prices_out = _int_map(block.get("sell_prices", {}))
    prices_in = _int_map(block.get("purchase_prices", {}))
    ins = tuple(
        _player(index, p, role="in", price_override=prices_in.get(p))
        for p in _ints(block.get("transfers_in", []))
    )
    outs = tuple(
        _player(index, p, role="out", price_override=prices_out.get(p))
        for p in _ints(block.get("transfers_out", []))
    )
    return TransferView(
        previous_gameweek=int(str(block["previous_gameweek"])),
        transfers_in=ins,
        transfers_out=outs,
        transfer_count=int(str(block["transfer_count"])),
        paid_transfer_count=int(str(block["paid_transfer_count"])),
        transfer_hit_points=float(str(block["transfer_hit_points"])),
        free_transfers_before=int(str(block["free_transfers_before"])),
        free_transfers_after=int(str(block["free_transfers_after"])),
        bank_before_tenths=int(str(block["bank_before_tenths"])),
        bank_after_tenths=int(str(block["bank_after_tenths"])),
        squad_sell_value_tenths=int(str(block["squad_sell_value_tenths"])),
        chip=None if block.get("chip") is None else str(block["chip"]),
        chips_available=tuple(_strs(block.get("chips_available", []))),
        planner_solver_status=str(block.get("planner_solver_status", "")),
        max_free_transfers=int(str(block.get("max_free_transfers", 0))),
        transfer_hit_cost_points=float(str(block.get("transfer_hit_cost_points", 0.0))),
    )


def _risk_from_status(status: str) -> RiskView:
    reason = {
        "not_requested": "No residual history was supplied; distributional risk was not evaluated.",
        "unavailable": "Distributional risk could not be evaluated for this decision.",
        "available": "A distributional risk view was evaluated at decision time.",
    }.get(status, "Risk status recorded without a reason.")
    return RiskView(
        status=status,
        reason=reason,
        blockers=(),
        scenario_count=None,
        lower_quantile_probability=None,
        lower_quantile_score=None,
        mean_score=None,
        mean_worst_fraction_score=None,
        worst_fraction=None,
        points_threshold=None,
        probability_below_threshold=None,
        probability_below_threshold_interval=None,
        location_shift_points=None,
        stated_limits=(_LEDGER_RISK_LIMIT,),
        rivals=(),
        residual_source=None,
    )


def _risk_view(risk: LiveRiskDiagnostics) -> RiskView:
    metrics = risk.metrics
    diagnostics = dict(risk.diagnostics)
    interval = diagnostics.get("probability_below_threshold_interval")
    comparisons = diagnostics.get("rival_comparisons", [])
    rivals = tuple(
        RivalComparisonView(
            rival=str(item["rival"]),
            probability_ahead=float(str(item["probability_ahead"])),
            probability_ahead_interval=_pair(item["probability_ahead_interval"]) or (0.0, 1.0),
            mean_difference=float(str(item["mean_difference"])),
            shared_starters=int(str(item["shared_starters"])),
        )
        for item in (comparisons if isinstance(comparisons, list | tuple) else [])
        if isinstance(item, Mapping)
    )
    return RiskView(
        status=str(risk.status.value),
        reason=str(risk.reason),
        blockers=tuple(str(b.value) for b in risk.blockers),
        scenario_count=None if metrics is None else int(metrics.scenario_count),
        lower_quantile_probability=(
            None if metrics is None else float(metrics.lower_quantile_probability)
        ),
        lower_quantile_score=None if metrics is None else float(metrics.lower_quantile_score),
        mean_score=None if metrics is None else float(metrics.mean_score),
        mean_worst_fraction_score=(
            None if metrics is None else float(metrics.mean_worst_fraction_score)
        ),
        worst_fraction=None if metrics is None else float(metrics.worst_fraction),
        points_threshold=None if metrics is None else float(metrics.points_threshold),
        probability_below_threshold=(
            None if metrics is None else float(metrics.probability_below_threshold)
        ),
        probability_below_threshold_interval=_pair(interval),
        location_shift_points=(
            None
            if diagnostics.get("location_shift_points") is None
            else float(str(diagnostics["location_shift_points"]))
        ),
        stated_limits=tuple(_strs(diagnostics.get("stated_limits", []))),
        rivals=rivals,
        residual_source=(
            None
            if risk.residual_provenance.get("source_id") is None
            else str(risk.residual_provenance["source_id"])
        ),
    )


# --- recommendations ------------------------------------------------------------


def recommendation_view_from_ledger(
    entry: LedgerEntry, projections: pd.DataFrame | None = None
) -> RecommendationView:
    """The view of a frozen decision, from its ledger entry (and its projections.csv)."""

    decision = dict(entry.decision)
    if projections is None:
        projections = pd.read_csv(entry.directory / _PROJECTIONS_FILE)
    index = _player_index(projections)
    starters = _ints(decision["starting_xi_player_ids"])
    bench_ids = _ints(decision["bench_player_ids"])
    captain = int(str(decision["captain_player_id"]))
    squad, xi, bench = _players_from_ids(index, starters, bench_ids, captain)
    transfers_block = decision.get("transfers")
    transfers = (
        _transfer_view(transfers_block, index) if isinstance(transfers_block, Mapping) else None
    )
    outcome = dict(entry.outcome) if entry.outcome is not None else None
    return RecommendationView(
        season=str(decision["season"]),
        gameweek=int(str(decision["gameweek"])),
        deadline_utc=str(decision["deadline_utc"]),
        snapshot_id=str(decision["snapshot_id"]),
        captured_at_utc=str(decision["captured_at_utc"]),
        model_name=str(decision["model_name"]),
        model_version=str(decision["model_version"]),
        feature_contract_version=str(decision["feature_contract_version"]),
        prediction_fingerprint=str(decision["prediction_fingerprint"]),
        report_contract_version=str(decision["report_contract_version"]),
        solver_status=str(decision["solver_status"]),
        solver_proved_optimal=str(decision["solver_status"]) == "OPTIMAL",
        decision_kind="transfer" if transfers is not None else "opening",
        squad=squad,
        starting_xi=xi,
        bench=bench,
        captain_player_id=captain,
        total_cost_tenths=int(str(decision["total_cost_tenths"])),
        projected_score=float(str(decision["projected_score"])),
        unavailable_player_count=int(str(decision.get("unavailable_player_count", 0))),
        risk=_risk_from_status(str(decision.get("risk_status", "not_requested"))),
        transfers=transfers,
        outcome_realized_score=(
            None if outcome is None else float(str(outcome["realized_xi_score"]))
        ),
        outcome_net_score=(None if outcome is None else float(str(outcome["realized_net_score"]))),
        settled=outcome is not None,
        metadata=_mapping(jsonable(decision.get("metadata", {}))),
    )


def recommendation_view(
    recommendation: Recommendation, *, outcome: Mapping[str, object] | None = None
) -> RecommendationView:
    """The view of a recommendation just built (fuller risk block than the ledger keeps)."""

    pool = recommendation.squad
    index = _player_index(pool)
    starters = [int(v) for v in recommendation.starting_xi["player_id"].tolist()]
    bench_ids = [int(v) for v in recommendation.bench["player_id"].tolist()]
    captain = int(recommendation.captain["player_id"])
    squad, xi, bench = _players_from_ids(index, starters, bench_ids, captain)
    transfers = None
    if recommendation.transfers is not None:
        block = recommendation.transfers.as_record()
        pool_index = dict(index)
        for frame in (
            recommendation.transfers.transfers_in,
            recommendation.transfers.transfers_out,
        ):
            if {
                "player_id",
                "name",
                "team_id",
                "position",
                "price_tenths",
                "expected_points",
            } <= set(frame.columns):
                pool_index.update(_player_index(frame))
        transfers = _transfer_view(block, pool_index)
    return RecommendationView(
        season=recommendation.season,
        gameweek=int(recommendation.gameweek),
        deadline_utc=recommendation.deadline_utc,
        snapshot_id=recommendation.snapshot_id,
        captured_at_utc=recommendation.captured_at_utc,
        model_name=recommendation.model_name,
        model_version=recommendation.model_version,
        feature_contract_version=recommendation.feature_contract_version,
        prediction_fingerprint=recommendation.prediction_fingerprint,
        report_contract_version=recommendation.contract_version,
        solver_status=recommendation.solver_status,
        solver_proved_optimal=recommendation.solver_proved_optimal,
        decision_kind="transfer" if transfers is not None else "opening",
        squad=squad,
        starting_xi=xi,
        bench=bench,
        captain_player_id=captain,
        total_cost_tenths=int(recommendation.total_cost_tenths),
        projected_score=float(recommendation.projected_score),
        unavailable_player_count=int(
            str(recommendation.diagnostics.get("unavailable_players_in_pool", 0))
        ),
        risk=_risk_view(recommendation.risk),
        transfers=transfers,
        outcome_realized_score=(
            None if outcome is None else float(str(outcome["realized_xi_score"]))
        ),
        outcome_net_score=None if outcome is None else float(str(outcome["realized_net_score"])),
        settled=outcome is not None,
        metadata={},
    )


# --- ledger and status ------------------------------------------------------------


def _ledger_row(entry: LedgerEntry) -> LedgerRowView:
    decision = dict(entry.decision)
    transfers = decision.get("transfers")
    block = transfers if isinstance(transfers, Mapping) else {}
    outcome = dict(entry.outcome) if entry.outcome is not None else None
    projected = float(str(decision["projected_score"]))
    realized = None if outcome is None else float(str(outcome["realized_xi_score"]))
    return LedgerRowView(
        cumulative_projected_score=0.0,
        cumulative_realized_score=None,
        gameweek=int(str(decision["gameweek"])),
        snapshot_id=str(decision["snapshot_id"]),
        deadline_utc=str(decision["deadline_utc"]),
        solver_status=str(decision["solver_status"]),
        decision_kind="transfer" if block else "opening",
        captain_player_id=int(str(decision["captain_player_id"])),
        projected_score=projected,
        realized_score=realized,
        projection_error=None if realized is None else realized - projected,
        transfer_count=int(str(block.get("transfer_count", 0))),
        transfer_hit_points=float(str(block.get("transfer_hit_points", 0.0))),
        realized_net_score=(None if outcome is None else float(str(outcome["realized_net_score"]))),
        chip=None if block.get("chip") is None else str(block["chip"]),
        unavailable_player_count=int(str(decision.get("unavailable_player_count", 0))),
        settled=outcome is not None,
    )


def ledger_view(root: Path, season: str) -> LedgerView:
    """Every recorded gameweek of a season, verified, with the season totals."""

    entries = load_ledger(root, season)
    rows: list[LedgerRowView] = []
    projected_so_far = 0.0
    realized_so_far: float | None = None
    for entry in entries:
        row = _ledger_row(entry)
        projected_so_far += row.projected_score
        if row.realized_score is not None:
            realized_so_far = (realized_so_far or 0.0) + row.realized_score
        rows.append(
            replace(
                row,
                cumulative_projected_score=projected_so_far,
                cumulative_realized_score=realized_so_far,
            )
        )
    settled = [row for row in rows if row.settled]
    return LedgerView(
        season=season,
        rows=tuple(rows),
        decided_gameweeks=len(rows),
        settled_gameweeks=len(settled),
        total_projected_score=float(sum(row.projected_score for row in rows)),
        total_projected_score_settled=(
            None if not settled else float(sum(row.projected_score for row in settled))
        ),
        total_realized_score=(
            None if not settled else float(sum(row.realized_score or 0.0 for row in settled))
        ),
        total_projection_error=(
            None
            if not settled
            else float(sum((row.realized_score or 0.0) - row.projected_score for row in settled))
        ),
        total_realized_net_score=(
            None if not settled else float(sum(row.realized_net_score or 0.0 for row in settled))
        ),
        total_transfer_hit_points=float(sum(row.transfer_hit_points for row in rows)),
        chips_played=tuple(row.chip for row in rows if row.chip is not None),
    )


def _recent_events(
    runlog_root: Path | None, component: str, limit: int
) -> tuple[RunLogEventView, ...]:
    if runlog_root is None:
        return ()
    directory = Path(runlog_root) / component
    if not directory.is_dir():
        return ()
    events: list[RunLogEventView] = []
    for path in sorted(directory.glob("*.jsonl"), reverse=True):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            fields = record.get("fields", {})
            events.append(
                RunLogEventView(
                    ts=str(record.get("ts", "")),
                    level=str(record.get("level", "")),
                    message=str(record.get("message", "")),
                    run_id=str(record.get("run_id", "")),
                    fields=_mapping(jsonable(fields)) if isinstance(fields, Mapping) else {},
                )
            )
            if len(events) >= limit:
                return tuple(events)
    return tuple(events)


def status_view(
    plan: TickPlan,
    *,
    ledger: LedgerState,
    runlog_root: Path | None = None,
    recent_events: int = 20,
) -> StatusView:
    """What the tick would do now (from a plan already made) and what it did recently."""

    diagnostics: Mapping[str, object] = plan.diagnostics

    def _opt_float(key: str) -> float | None:
        value = diagnostics.get(key)
        return None if value is None else float(str(value))

    def _opt_int(key: str) -> int | None:
        value = diagnostics.get(key)
        return None if value is None else int(str(value))

    return StatusView(
        now_utc=plan.now_utc,
        season=plan.season,
        latest_capture=(
            None
            if diagnostics.get("latest_capture") is None
            else str(diagnostics["latest_capture"])
        ),
        next_gameweek=_opt_int("next_gameweek"),
        next_deadline_utc=(
            None
            if diagnostics.get("next_deadline_utc") is None
            else str(diagnostics["next_deadline_utc"])
        ),
        hours_to_deadline=_opt_float("hours_to_deadline"),
        actions=tuple(
            TickActionView(
                kind=str(action.kind),
                reason=action.reason,
                gameweek=action.gameweek,
                snapshot_id=action.snapshot_id,
                handoff_path=action.handoff_path,
            )
            for action in plan.actions
        ),
        is_idle=plan.is_idle,
        decided_gameweeks=tuple(sorted(ledger.decided)),
        settled_gameweeks=tuple(sorted(ledger.settled)),
        recent_events=_recent_events(runlog_root, "season_tick", recent_events),
        tick_contract_version=plan.contract_version,
    )


def pool_view(
    entry: LedgerEntry, projections: pd.DataFrame | None = None, *, per_position: int = 12
) -> PoolView:
    """The top of the projected pool per position, with the frozen squad marked."""

    decision = dict(entry.decision)
    if projections is None:
        projections = pd.read_csv(entry.directory / _PROJECTIONS_FILE)
    index = _player_index(projections)
    starters = set(_ints(decision["starting_xi_player_ids"]))
    bench = set(_ints(decision["bench_player_ids"]))
    players: list[PoolPlayerView] = []
    for position in ("GK", "DEF", "MID", "FWD"):
        rows = sorted(
            (row for row in index.values() if str(row["position"]) == position),
            key=lambda r: (-float(str(r["expected_points"])), int(str(r["player_id"]))),
        )
        for rank, row in enumerate(rows[:per_position], 1):
            player_id = int(str(row["player_id"]))
            role = "starter" if player_id in starters else "bench" if player_id in bench else "pool"
            players.append(
                PoolPlayerView(
                    player_id=player_id,
                    name=str(row["name"]),
                    short_name=short_name(str(row["name"])),
                    team=str(row["team_id"]),
                    position=position,
                    price_tenths=int(str(row["price_tenths"])),
                    expected_points=float(str(row["expected_points"])),
                    rank_in_position=rank,
                    selected=player_id in starters or player_id in bench,
                    role=role,
                )
            )
    return PoolView(
        season=str(decision["season"]),
        gameweek=int(str(decision["gameweek"])),
        pool_size=len(index),
        per_position=per_position,
        players=tuple(players),
    )


__all__ = [
    "JsonValue",
    "ledger_view",
    "pool_view",
    "recommendation_view",
    "recommendation_view_from_ledger",
    "status_view",
]
