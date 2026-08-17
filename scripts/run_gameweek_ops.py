"""Run one gameweek of season operations against the ledger.

    python -m scripts.run_gameweek_ops --phase decide
    python -m scripts.run_gameweek_ops --phase decide --snapshot-id <id> --gameweek 1
    python -m scripts.run_gameweek_ops --phase decide --gameweek 2 \
        --in-season-projection handoffs/2026-27-gw02.json [--chip bboost]
    python -m scripts.run_gameweek_ops --phase settle --gameweek 1

This is the season runbook as a machine. **decide** (before the deadline) reads a
capture, builds the recommendation, verifies every runbook check as code — control
model identity, availability applied, squad structure, budget, club limit, captain
sanity, risk not silently attached — and only then freezes the decision into the
season ledger. A failed check exits 1 and records nothing: an unverified decision is
not published.

The opening gameweek is projected by the operational control from the capture and
builds a squad from scratch. Every later gameweek starts from the squad the ledger
holds and decides transfers (a one-week planning horizon, the weekly baseline the
measurements kept as control): it needs a projection handed in by its producer under
`projection_handoff_v1` — the archive holds no played gameweek of the current season
at deadline time — and the ledger must hold the previous gameweek's decision. A chip is
played only when named with `--chip`, inside its published window; the planner does
not time chips at a one-week horizon.

**settle** (after the gameweek finishes) reads a later capture, extracts realized
`event_points` for the finished gameweek, scores the frozen decision (starting XI
plus captain double), records the outcome, and regenerates the committed season
summary in `docs/`. Raw ledger entries stay local under `data/ledger/`.

Capturing is a separate, deliberate network step:

    python -m scripts.capture_deadline_snapshot

The ledger records; it never promotes. Every decision recorded here comes from the
operational control, and the decide phase proves that rather than assuming it.
"""

import argparse
import sys
from pathlib import Path

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    CHIP_NAMES,
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
from squadopt.planning import CHIP_NAMES as PLANNER_CHIP_NAMES

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
DEFAULT_LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("decide", "settle"), required=True)
    parser.add_argument(
        "--snapshot-id",
        help="use this capture; omitted, the most recent capture is used",
    )
    parser.add_argument(
        "--gameweek",
        type=int,
        help="decide: target gameweek (default: earliest open at capture time); "
        "settle: the finished gameweek to score (required)",
    )
    parser.add_argument("--season", help="override the season inferred from the capture")
    parser.add_argument(
        "--in-season-projection",
        type=Path,
        help="decide, gameweek 2 onward: the producer's projection handoff "
        "(projection_handoff_v1) for this capture and gameweek",
    )
    parser.add_argument(
        "--chip",
        choices=sorted(set(CHIP_NAMES) & set(PLANNER_CHIP_NAMES)),
        help="decide, gameweek 2 onward: play this chip now (refused outside its window "
        "or if already spent inside it)",
    )
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="settle: where the committed season summary is written "
        "(default docs/season_ledger_<season>.md)",
    )
    return parser.parse_args()


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
    """Apply every runbook check as code; each failure is a publishable reason.

    ``held`` is the squad the ledger says the decision started from; a transfer decision
    is checked against it (what left was held, what came in was not, the bank stays in
    credit, hits are what the paid transfers cost) and an opening decision must not
    carry one.
    """

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


def _decide(arguments: argparse.Namespace) -> int:
    snapshot_id, snapshot = _resolve_snapshot(arguments.snapshot_root, arguments.snapshot_id)
    season = arguments.season or infer_season(snapshot)
    inputs = read_inputs(snapshot, season=season, gameweek=arguments.gameweek)
    mode = "replay" if arguments.snapshot_id else "live"
    print(
        f"{mode}: snapshot {snapshot_id}, captured {inputs.captured_at_utc}, "
        f"targeting {season} gameweek {inputs.deadline.gameweek}"
    )

    # The season's published rules travel with the decision so a later reader knows
    # which scoring, chip, and transfer regime it was made under.
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
        if arguments.in_season_projection is not None or arguments.chip is not None:
            raise DataError(
                "The opening gameweek is decided from the capture alone; "
                "--in-season-projection and --chip apply from gameweek 2 onward."
            )
        panel = build_panel(arguments.archive_root)
        projection = project(inputs, panel)
        recommendation = build_recommendation(inputs, projection)
    else:
        if arguments.in_season_projection is None:
            raise DataError(
                f"Gameweek {inputs.deadline.gameweek} needs --in-season-projection: a "
                "projection handoff for this capture from the model that produced it."
            )
        handoff = read_projection_handoff(arguments.in_season_projection)
        # The panel is not read: identity and price come from the capture, the numbers
        # from the handoff, and the archive holds no played gameweek of this season yet.
        projection = project(inputs, in_season=handoff)
        held = held_squad_from_ledger(
            arguments.ledger_root,
            season,
            before_gameweek=inputs.deadline.gameweek,
            budget_tenths=OptimizationConfig().budget_tenths,
        )
        recommendation = build_transfer_recommendation(
            inputs, projection, held, rules, chip=arguments.chip
        )
        metadata["projection_handoff_fingerprint"] = handoff.fingerprint
        metadata["projection_handoff_path"] = str(arguments.in_season_projection)
        metadata["held_squad_decided_gameweek"] = held.decided_gameweek

    failures = verify_decision(recommendation, projection, held)
    if failures:
        print("\nDecision verification FAILED; nothing was recorded:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("Decision verification passed: all runbook checks hold.")

    report = render(recommendation)
    directory = record_decision(
        arguments.ledger_root,
        recommendation,
        projection,
        report_text=report + "\n" + render_rules(rules),
        metadata=metadata,
    )
    print(report)
    print(render_rules(rules))
    print(f"Recorded decision at {directory}")
    return 0


def _settle(arguments: argparse.Namespace) -> int:
    if arguments.gameweek is None:
        raise DataError("settle requires --gameweek: the finished gameweek to score.")
    snapshot_id, snapshot = _resolve_snapshot(arguments.snapshot_root, arguments.snapshot_id)
    season = arguments.season or infer_season(snapshot)
    points = extract_event_points(snapshot, gameweek=arguments.gameweek)
    outcome_path = record_outcome(
        arguments.ledger_root,
        season,
        arguments.gameweek,
        points,
        source_snapshot_id=snapshot_id,
    )
    print(f"Recorded outcome at {outcome_path}")

    summary_path: Path = arguments.summary_output or (
        REPOSITORY_ROOT / "docs" / f"season_ledger_{season}.md"
    )
    summary = summary_markdown(arguments.ledger_root, season)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Wrote {summary_path}")
    return 0


def main() -> int:
    arguments = _parse_arguments()
    try:
        if arguments.phase == "decide":
            return _decide(arguments)
        return _settle(arguments)
    except DataError as error:
        print(f"\nGameweek operations failed:\n  {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
