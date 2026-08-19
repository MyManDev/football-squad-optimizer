"""Transport-neutral commands for the live season ledger.

The command line, a later HTTP API, and scheduled workers must all execute the same
decision and settlement behavior.  This module owns that public application seam:
callers supply typed requests, domain failures are raised before an invalid record is
published, and successful calls return typed descriptions of the files they wrote.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    CONTROL_MODEL_NAME,
    CONTROL_MODEL_VERSION,
    IN_SEASON_CONTROL_MODEL_VERSIONS,
    SUPPORTED_TARGET_GAMEWEEK,
    HeldSquad,
    LiveRiskStatus,
    Projection,
    Recommendation,
    build_recommendation,
    build_transfer_recommendation,
    extract_event_points,
    held_squad_from_ledger,
    infer_season,
    project,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
    record_decision,
    record_outcome,
    render,
    render_rules,
    summary_markdown,
)
from squadopt.optimization import OptimizationConfig

PanelBuilder = Callable[[Path], pd.DataFrame]


class DecisionVerificationError(DataError):
    """A proposed decision failed one or more publication checks."""

    def __init__(self, failures: list[str]) -> None:
        if not failures:
            raise ValueError("DecisionVerificationError needs at least one failure.")
        self.failures = tuple(failures)
        super().__init__("Decision verification failed: " + "; ".join(self.failures))


@dataclass(frozen=True, slots=True)
class DecideRequest:
    """Everything required to calculate and freeze one gameweek decision."""

    snapshot_root: Path
    ledger_root: Path
    archive_root: Path
    snapshot_id: str | None = None
    gameweek: int | None = None
    season: str | None = None
    in_season_projection: Path | None = None
    chip: str | None = None

    def __post_init__(self) -> None:
        for name in ("snapshot_root", "ledger_root", "archive_root"):
            object.__setattr__(self, name, Path(getattr(self, name)))
        if self.in_season_projection is not None:
            object.__setattr__(self, "in_season_projection", Path(self.in_season_projection))
        if self.gameweek is not None and (
            isinstance(self.gameweek, bool)
            or not isinstance(self.gameweek, int)
            or self.gameweek < 1
        ):
            raise DataError("gameweek must be a positive integer when supplied.")


@dataclass(frozen=True, slots=True)
class DecideResult:
    """A verified decision and its immutable ledger location."""

    season: str
    gameweek: int
    snapshot_id: str
    mode: str
    decision_directory: Path
    report: str
    output_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class SettleRequest:
    """Everything required to score one frozen gameweek decision."""

    snapshot_root: Path
    ledger_root: Path
    summary_root: Path
    gameweek: int
    snapshot_id: str | None = None
    season: str | None = None
    summary_output: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_root", Path(self.snapshot_root))
        object.__setattr__(self, "ledger_root", Path(self.ledger_root))
        object.__setattr__(self, "summary_root", Path(self.summary_root))
        if self.summary_output is not None:
            object.__setattr__(self, "summary_output", Path(self.summary_output))
        if (
            isinstance(self.gameweek, bool)
            or not isinstance(self.gameweek, int)
            or self.gameweek < 1
        ):
            raise DataError("settle requires a positive gameweek.")


@dataclass(frozen=True, slots=True)
class SettleResult:
    """A recorded outcome and the regenerated human-readable season summary."""

    season: str
    gameweek: int
    snapshot_id: str
    outcome_path: Path
    summary_path: Path
    summary: str

    @property
    def output_paths(self) -> tuple[Path, ...]:
        return (self.outcome_path, self.summary_path)


def _resolve_snapshot(root: Path, requested: str | None) -> tuple[str, CapturedSnapshot]:
    identifiers = list_snapshot_ids(root)
    if requested:
        if requested not in identifiers:
            raise DataError(
                f"No snapshot {requested!r} under {root}. Held: "
                f"{identifiers[-3:] if identifiers else 'none'}."
            )
        snapshot_id = requested
    elif identifiers:
        snapshot_id = identifiers[-1]
    else:
        raise DataError(
            f"No snapshots under {root}. Capture one first with "
            "'python -m scripts.capture_deadline_snapshot'."
        )
    return snapshot_id, read_snapshot(root, snapshot_id)


def verify_decision(
    recommendation: Recommendation,
    projection: Projection,
    held: HeldSquad | None = None,
) -> list[str]:
    """Apply every runbook publication check and return all failure reasons."""

    failures: list[str] = []
    settings = OptimizationConfig()

    if recommendation.model_name != CONTROL_MODEL_NAME:
        failures.append(
            f"Model is {recommendation.model_name!r}, not the operational control "
            f"{CONTROL_MODEL_NAME!r}; only the promoted control decides live squads."
        )
    if recommendation.transfers is None:
        if recommendation.model_version != CONTROL_MODEL_VERSION:
            failures.append(
                f"Model version {recommendation.model_version!r} does not match the "
                f"control version {CONTROL_MODEL_VERSION!r}."
            )
    elif recommendation.model_version not in IN_SEASON_CONTROL_MODEL_VERSIONS:
        failures.append(
            f"Model version {recommendation.model_version!r} is not a promoted in-season "
            f"control; promoted versions are {list(IN_SEASON_CONTROL_MODEL_VERSIONS)!r}. "
            "Pinning a version here is the promotion decision, not a formality."
        )
    if not recommendation.solver_proved_optimal:
        failures.append(
            f"Solver status is {recommendation.solver_status!r}; a live decision "
            "requires proven optimality."
        )

    squad_ids = {int(value) for value in recommendation.squad["player_id"]}
    xi_ids = {int(value) for value in recommendation.starting_xi["player_id"]}
    if len(recommendation.squad) != 15 or len(squad_ids) != 15:
        failures.append(f"Squad has {len(recommendation.squad)} rows, expected 15 distinct.")
    if len(recommendation.starting_xi) != 11 or len(xi_ids) != 11:
        failures.append(
            f"Starting XI has {len(recommendation.starting_xi)} rows, expected 11 distinct."
        )
    if len(recommendation.bench) != 4:
        failures.append(f"Bench has {len(recommendation.bench)} rows, expected 4.")
    if not xi_ids.issubset(squad_ids):
        failures.append("Starting XI is not a subset of the squad.")
    captain_id = int(recommendation.captain["player_id"])
    if captain_id not in xi_ids:
        failures.append(f"Captain {captain_id} is not in the starting XI.")
    transfers = recommendation.transfers
    if transfers is None and recommendation.total_cost_tenths > settings.budget_tenths:
        failures.append(
            f"Squad costs {recommendation.total_cost_tenths} tenths, over the "
            f"{settings.budget_tenths} budget."
        )
    club_counts = recommendation.squad["team_id"].value_counts()
    if not club_counts.empty and int(club_counts.max()) > settings.max_players_per_team:
        offenders = club_counts[club_counts > settings.max_players_per_team]
        failures.append(
            f"Club limit exceeded: team(s) {offenders.index.tolist()!r} supply more "
            f"than {settings.max_players_per_team} players."
        )

    unavailable = {int(player) for player in projection.unavailable_players}
    selected_unavailable = sorted(squad_ids & unavailable)
    if selected_unavailable:
        failures.append(
            f"Availability rule violated: unavailable players {selected_unavailable!r} "
            "were selected."
        )
    if recommendation.risk.status is not LiveRiskStatus.NOT_REQUESTED:
        failures.append(
            f"Risk diagnostics status is {recommendation.risk.status.value!r}; "
            "gameweek operations decide without a risk overlay, so anything else "
            "means an unexpected input reached the recommendation."
        )
    unprojected = set(projection.unprojected_players)
    selected_unprojected = sorted(squad_ids & unprojected)
    if selected_unprojected:
        failures.append(
            f"Players {selected_unprojected!r} were selected although the projection had "
            "no number for them."
        )
    failures.extend(_verify_transfers(recommendation, held))
    return failures


def _verify_transfers(recommendation: Recommendation, held: HeldSquad | None) -> list[str]:
    failures: list[str] = []
    transfers = recommendation.transfers
    if transfers is None:
        if held is not None:
            failures.append("A held squad was supplied but the decision carries no transfers.")
        return failures
    if held is None:
        failures.append("A transfer decision must be checked against the held squad.")
        return failures
    squad_ids = {int(value) for value in recommendation.squad["player_id"]}
    held_ids = set(held.squad_player_ids)
    outgoing = set(transfers.transfers_out_ids)
    incoming = set(transfers.transfers_in_ids)
    if not outgoing.issubset(held_ids):
        failures.append(f"Transfers out {sorted(outgoing - held_ids)!r} were not held.")
    if incoming & held_ids:
        failures.append(f"Transfers in {sorted(incoming & held_ids)!r} were already held.")
    if squad_ids != (held_ids - outgoing) | incoming:
        failures.append("The squad after transfers is not the held squad minus out plus in.")
    if len(outgoing) != len(incoming) or transfers.transfer_count != len(incoming):
        failures.append("Transfer counts do not agree between in, out, and the recorded count.")
    if transfers.previous_gameweek != held.decided_gameweek:
        failures.append("The transfer decision does not start from the held squad's gameweek.")
    if transfers.bank_before_tenths != held.bank_tenths:
        failures.append("The bank before transfers is not the held bank.")
    if transfers.bank_after_tenths < 0:
        failures.append(f"The bank after transfers is {transfers.bank_after_tenths} tenths.")
    expected_paid = (
        0
        if transfers.chip in {"wildcard", "freehit"}
        else max(0, transfers.transfer_count - transfers.free_transfers_before)
    )
    if transfers.paid_transfer_count != expected_paid:
        failures.append("Paid transfers are not the transfers beyond the free ones.")
    expected_hits = transfers.paid_transfer_count * transfers.transfer_hit_cost_points
    if abs(transfers.transfer_hit_points - expected_hits) > 1e-9:
        failures.append("Hit points are not the paid transfers at the hit cost.")
    if transfers.chip is not None and transfers.chip not in transfers.chips_available:
        failures.append(f"Chip {transfers.chip!r} was played although it was not offered.")
    if recommendation.total_cost_tenths != transfers.squad_sell_value_tenths:
        failures.append("The reported squad value is not the squad's sell value.")
    return failures


def decide(
    request: DecideRequest,
    *,
    panel_builder: PanelBuilder = build_panel,
    verifier: Callable[[Recommendation, Projection, HeldSquad | None], list[str]] = verify_decision,
) -> DecideResult:
    """Calculate, verify, and immutably record one gameweek decision."""

    snapshot_id, snapshot = _resolve_snapshot(request.snapshot_root, request.snapshot_id)
    season = request.season or infer_season(snapshot)
    inputs = read_inputs(snapshot, season=season, gameweek=request.gameweek)
    mode = "replay" if request.snapshot_id else "live"

    rules = read_season_rules(snapshot, season=season)
    metadata: dict[str, object] = {
        "ops_phase": "decide",
        "mode": mode,
        "season_rules_contract_version": rules.contract_version,
        "season_rules_fingerprint": rules.fingerprint,
        "awards_defensive_contribution": rules.scoring.awards_defensive_contribution,
    }
    held: HeldSquad | None = None
    if inputs.deadline.gameweek == SUPPORTED_TARGET_GAMEWEEK:
        if request.in_season_projection is not None or request.chip is not None:
            raise DataError(
                "The opening gameweek is decided from the capture alone; "
                "in-season projection and chip apply from gameweek 2 onward."
            )
        panel = panel_builder(request.archive_root)
        projection = project(inputs, panel)
        recommendation = build_recommendation(inputs, projection)
    else:
        if request.in_season_projection is None:
            raise DataError(
                f"Gameweek {inputs.deadline.gameweek} needs an in-season projection "
                "handoff for this capture from the model that produced it."
            )
        handoff = read_projection_handoff(request.in_season_projection)
        projection = project(inputs, in_season=handoff)
        held = held_squad_from_ledger(
            request.ledger_root,
            season,
            before_gameweek=inputs.deadline.gameweek,
            budget_tenths=OptimizationConfig().budget_tenths,
        )
        recommendation = build_transfer_recommendation(
            inputs, projection, held, rules, chip=request.chip
        )
        metadata["projection_handoff_fingerprint"] = handoff.fingerprint
        metadata["projection_handoff_path"] = str(request.in_season_projection)
        metadata["held_squad_decided_gameweek"] = held.decided_gameweek

    failures = verifier(recommendation, projection, held)
    if failures:
        raise DecisionVerificationError(failures)

    report = render(recommendation) + "\n" + render_rules(rules)
    directory = record_decision(
        request.ledger_root,
        recommendation,
        projection,
        report_text=report,
        metadata=metadata,
    )
    return DecideResult(
        season=season,
        gameweek=inputs.deadline.gameweek,
        snapshot_id=snapshot_id,
        mode=mode,
        decision_directory=directory,
        report=report,
        output_paths=tuple(sorted(path for path in directory.iterdir() if path.is_file())),
    )


def settle(request: SettleRequest) -> SettleResult:
    """Score a frozen decision and regenerate its season summary."""

    snapshot_id, snapshot = _resolve_snapshot(request.snapshot_root, request.snapshot_id)
    season = request.season or infer_season(snapshot)
    points = extract_event_points(snapshot, gameweek=request.gameweek)
    outcome_path = record_outcome(
        request.ledger_root,
        season,
        request.gameweek,
        points,
        source_snapshot_id=snapshot_id,
    )
    summary_path = request.summary_output or request.summary_root / f"season_ledger_{season}.md"
    summary = summary_markdown(request.ledger_root, season)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")
    return SettleResult(
        season=season,
        gameweek=request.gameweek,
        snapshot_id=snapshot_id,
        outcome_path=outcome_path,
        summary_path=summary_path,
        summary=summary,
    )
