"""Produce the in-season projection handoff a mid-season decision needs.

    python -m scripts.build_projection_handoff                    # latest capture
    python -m scripts.build_projection_handoff --snapshot-id ...  # a named capture
    python -m scripts.build_projection_handoff --dry-run          # report, write nothing

The live path projects the opening gameweek itself and refuses every later one without a
handoff from the model that produced it. This is that model's entry point: it reads one
capture, projects the deadline that capture is open for, and writes the file the tick waits
for.

Three contracts are worth stating because two of them fail late rather than loudly.

The handoff must be produced from **the capture the decision will run on**: the live path
compares ``source_snapshot_id`` and refuses a projection made from a different capture,
because a projection of another roster is not a projection of this one. So on a deadline day
the order is capture, then this script, then decide -- not a handoff prepared earlier in the
week.

The default component model reads only the prior event-live documents stored in that same
capture. They carry gameweek-level minutes and points, and every one must be settled. The
legacy rollback still reads the capture's cumulative in-season counters; ``in_season_totals``
refuses a capture taken before those counters reset.

The component version and its legacy rollback are pinned in ``live``. This script reports
which route it selected, so a fallback or refusal downstream is legible rather than
mysterious.

Nothing is fetched. The capture is already on disk.
"""

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    IncompleteLiveHistoryError,
    build_live_player_history,
    fixture_snapshot,
    gameweek_deadlines,
    in_season_totals,
    live_payload,
    next_open_deadline,
    player_snapshot,
    team_codes,
    team_names,
)
from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.features.cross_season import carry_over_as_of
from squadopt.features.evidence_artifact import read_player_evidence_artifact
from squadopt.live import (
    CONTROL_MODEL_NAME,
    IN_SEASON_CONTROL_MODEL_VERSIONS,
    InSeasonProjection,
    handoff_path_for,
    infer_season,
    read_projection_handoff,
    write_projection_handoff,
)
from squadopt.prediction.component_dataset import (
    COMPONENT_FEATURE_CONFIG,
    COMPONENT_HISTORY_WINDOW,
    COMPONENT_TRAINING_SEASONS,
    build_component_modelling_frame,
    build_component_scoring_frame,
    component_feature_columns,
)
from squadopt.prediction.component_dataset import (
    FEATURE_CONTRACT_VERSION as COMPONENT_FEATURE_CONTRACT_VERSION,
)
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    fit_component_models,
    predict_components,
)
from squadopt.prediction.components import DIRECT_CONTROL_ROUTE, prepare_component_prediction
from squadopt.prediction.elite_evidence import (
    ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION,
    ELITE_EVIDENCE_MODEL_VERSION,
    apply_elite_evidence,
)
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
    InSeasonBlendConfig,
    blend_in_season_projection,
)
from squadopt.prediction.integration import PredictionProvenance
from squadopt.prediction.opening import build_opening_projection_from_snapshot

DEFAULT_SNAPSHOT_ROOT: Final = Path("data/snapshots")
DEFAULT_HANDOFF_ROOT: Final = Path("data/handoffs")


def _latest_snapshot_id(snapshot_root: Path) -> str:
    """Return the most recent capture's identifier.

    Identifiers begin with the capture instant in a sortable spelling, so the newest is the
    last in lexical order.
    """

    directories = sorted(path.name for path in snapshot_root.iterdir() if path.is_dir())
    if not directories:
        raise SystemExit(f"No captures under {snapshot_root}.")
    return directories[-1]


def _frame_fingerprint(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values(["season", "gameweek", "player_id"], kind="stable")
    return hashlib.sha256(
        ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()


def _team_bridge(bootstrap: bytes, season: str) -> pd.DataFrame:
    names = team_names(bootstrap)
    codes = team_codes(bootstrap)
    if set(names) != set(codes):
        raise SystemExit("Bootstrap team names and persistent codes do not share one id set.")
    return pd.DataFrame(
        {
            "season": season,
            "name": [names[identifier] for identifier in sorted(names)],
            "code": [codes[identifier] for identifier in sorted(names)],
        }
    )


def _component_table(
    archive_root: Path,
    *,
    bootstrap: bytes,
    fixtures: bytes,
    event_payloads: dict[int, bytes],
    season: str,
    target: int,
    source_snapshot_id: str,
    captured_at_utc: str,
    deadline_utc: str,
    fallback: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    training_panel = build_panel(archive_root, seasons=COMPONENT_TRAINING_SEASONS)
    training_fixtures = build_fixture_panel(archive_root, seasons=COMPONENT_TRAINING_SEASONS)
    training_team_codes = pd.concat(
        [
            load_team_codes(archive_root, training_season).assign(season=training_season)
            for training_season in COMPONENT_TRAINING_SEASONS
        ],
        ignore_index=True,
    )
    training = build_component_modelling_frame(
        training_panel,
        training_fixtures,
        training_team_codes,
        seasons=COMPONENT_TRAINING_SEASONS,
        config=COMPONENT_FEATURE_CONFIG,
    )
    models = fit_component_models(training, feature_columns=component_feature_columns())
    if models is None:
        raise SystemExit(
            "The declared Phase C training population is too thin to fit its component models."
        )

    current_panel, incomplete_players = build_live_player_history(
        bootstrap,
        fixtures,
        event_payloads,
        season=season,
        target_gameweek=target,
        source_snapshot_id=source_snapshot_id,
    )
    live_fixtures = fixture_snapshot(
        fixtures,
        bootstrap,
        season=season,
        snapshot_id=source_snapshot_id,
        captured_at_utc=captured_at_utc,
    )
    scoring = build_component_scoring_frame(
        current_panel,
        live_fixtures,
        _team_bridge(bootstrap, season),
        season=season,
        gameweek=target,
        config=COMPONENT_FEATURE_CONFIG,
    )
    predicted = predict_components(
        models,
        scoring,
        feature_columns=component_feature_columns(),
    )
    fallback_points = fallback.set_index("player_id")["expected_points"]
    rows = pd.DataFrame(
        {
            "player_id": scoring["player_id"].astype("int64"),
            "fixture_count": scoring["fixture_count"].astype("int64"),
            "appearance_probability": predicted["appearance_probability"],
            "expected_minutes_if_appearance": predicted["expected_minutes_if_appearance"],
            "expected_points_if_appearance": predicted["expected_points_if_appearance"],
            "fallback_expected_points": scoring["player_id"]
            .map(fallback_points)
            .where(predicted["composition_route"].eq(DIRECT_CONTROL_ROUTE)),
            "composition_route": predicted["composition_route"],
            "evidence_status": predicted["evidence_status"],
        }
    )
    last = training.sort_values(["season", "gameweek", "player_id"], kind="stable").iloc[-1]
    provenance = PredictionProvenance(
        model_name=CONTROL_MODEL_NAME,
        model_version=COMPONENT_MODEL_VERSION,
        feature_contract_version=COMPONENT_FEATURE_CONTRACT_VERSION,
        training_cutoff=f"{last['season']}:GW{int(last['gameweek']):02d}",
        training_data_fingerprint=_frame_fingerprint(training),
    )
    snapshot = prepare_component_prediction(
        rows,
        provenance,
        decision_timestamp_utc=captured_at_utc,
        decision_context={
            "source_snapshot_id": source_snapshot_id,
            "season": season,
            "gameweek": str(target),
            "deadline_utc": deadline_utc,
        },
    )
    diagnostics: dict[str, object] = {
        **dict(snapshot.diagnostics),
        "component_fingerprint": snapshot.component_fingerprint,
        "component_training_seasons": list(COMPONENT_TRAINING_SEASONS),
        "component_training_rows": len(training),
        "component_training_appearance_rows": models.appearance_rows,
        "component_training_conditional_rows": models.conditional_rows,
        "component_history_gameweeks": sorted(event_payloads),
        "component_history_incomplete_players": len(incomplete_players),
    }
    return snapshot.table.loc[:, ["player_id", "expected_points"]], diagnostics


def build(
    snapshot_root: Path,
    archive_root: Path,
    handoff_root: Path,
    *,
    snapshot_id: str | None = None,
    gameweek: int | None = None,
    config: InSeasonBlendConfig | None = None,
    evidence_table_path: Path | None = None,
    evidence_manifest_path: Path | None = None,
    control_only: bool = False,
    dry_run: bool = False,
) -> tuple[InSeasonProjection, Path | None, dict[str, object]]:
    """Project one capture's open deadline and write the handoff for it."""

    identifier = _latest_snapshot_id(snapshot_root) if snapshot_id is None else snapshot_id
    snapshot = read_snapshot(snapshot_root, identifier)
    bootstrap = snapshot.payloads[BOOTSTRAP_PAYLOAD]
    fixtures = snapshot.payloads[FIXTURES_PAYLOAD]
    captured_at = snapshot.metadata.captured_at_utc
    season = infer_season(snapshot)

    # The deadline this capture is open for, read from the capture rather than supplied,
    # for the same reason the season is: a hand-passed gameweek can be the wrong one, and
    # the live path would then refuse the handoff after the work was done.
    deadlines = gameweek_deadlines(bootstrap)
    if gameweek is None:
        target_deadline = next_open_deadline(deadlines, as_of_utc=captured_at)
    else:
        matches = [entry for entry in deadlines if entry.gameweek == gameweek]
        if not matches:
            raise SystemExit(f"Capture {identifier} publishes no gameweek {gameweek} deadline.")
        target_deadline = matches[0]
    target = target_deadline.gameweek
    # Every gameweek before the target has been played, so that is the in-season sample.
    played = target - 1

    roster = player_snapshot(bootstrap)
    history = in_season_totals(bootstrap, fixtures, captured_at_utc=captured_at)
    panel = build_panel(archive_root)
    carried = carry_over_as_of(panel, target_season=season)
    # The opening control's own output, used only where a player has neither an in-season
    # record nor a carried one, so both paths price such a player identically by
    # construction rather than by two copies of one rule agreeing.
    fallback = build_opening_projection_from_snapshot(panel, roster, season=season)

    blend = blend_in_season_projection(
        roster, carried, history, fallback, gameweeks_played=played, config=config
    )

    if (evidence_table_path is None) != (evidence_manifest_path is None):
        raise SystemExit("Evidence requires both --evidence-table and --evidence-manifest.")

    projected_table = blend.table
    model_version = IN_SEASON_MODEL_VERSION
    feature_contract_version = IN_SEASON_FEATURE_CONTRACT_VERSION
    diagnostics = dict(blend.diagnostics)
    evidence_fingerprint: str | None = None
    if evidence_table_path is not None and evidence_manifest_path is not None:
        evidence = read_player_evidence_artifact(evidence_table_path, evidence_manifest_path)
        adjusted = apply_elite_evidence(
            projected_table,
            evidence,
            season=season,
            target_gameweek=target,
            deadline_timestamp_utc=target_deadline.deadline_utc,
            decision_captured_at_utc=captured_at,
        )
        projected_table = adjusted.table
        model_version = ELITE_EVIDENCE_MODEL_VERSION
        feature_contract_version = ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION
        diagnostics.update(adjusted.diagnostics)
        manifest_digest = hashlib.sha256(evidence_manifest_path.read_bytes()).hexdigest()
        diagnostics["elite_evidence_manifest_sha256"] = manifest_digest
        evidence_fingerprint = hashlib.sha256(
            f"{evidence.attrs['table_sha256']}:{manifest_digest}".encode()
        ).hexdigest()
        diagnostics["projection_selection"] = "legacy_elite_candidate"
    elif control_only:
        diagnostics["projection_selection"] = "explicit_legacy_control"
    else:
        history_weeks = tuple(range(max(1, target - COMPONENT_HISTORY_WINDOW), target))
        missing_history = [
            week for week in history_weeks if live_payload(week) not in snapshot.payloads
        ]
        if missing_history:
            diagnostics.update(
                {
                    "projection_selection": "legacy_control_fallback",
                    "component_fallback_reason": "missing_live_history_payloads",
                    "component_missing_gameweeks": missing_history,
                }
            )
        else:
            try:
                projected_table, component_diagnostics = _component_table(
                    archive_root,
                    bootstrap=bootstrap,
                    fixtures=fixtures,
                    event_payloads={
                        week: snapshot.payloads[live_payload(week)] for week in history_weeks
                    },
                    season=season,
                    target=target,
                    source_snapshot_id=identifier,
                    captured_at_utc=captured_at,
                    deadline_utc=target_deadline.deadline_utc,
                    fallback=blend.table,
                )
            except IncompleteLiveHistoryError as error:
                diagnostics.update(
                    {
                        "projection_selection": "legacy_control_fallback",
                        "component_fallback_reason": "provisional_live_history",
                        "component_fallback_detail": str(error),
                    }
                )
            else:
                model_version = COMPONENT_MODEL_VERSION
                feature_contract_version = COMPONENT_FEATURE_CONTRACT_VERSION
                diagnostics.update(component_diagnostics)
                diagnostics["projection_selection"] = "phase_c_component_default"

    expected = {
        int(code): float(points)
        for code, points in zip(
            projected_table["player_id"].astype("int64").tolist(),
            projected_table["expected_points"].astype("float64").tolist(),
            strict=True,
        )
    }
    projection = InSeasonProjection(
        season=season,
        gameweek=target,
        source_snapshot_id=identifier,
        model_name=CONTROL_MODEL_NAME,
        model_version=model_version,
        feature_contract_version=feature_contract_version,
        expected_points=expected,
        evidence_fingerprint=evidence_fingerprint,
        diagnostics=diagnostics,
    )

    path = handoff_path_for(handoff_root, season, target)
    written: Path | None = None
    if not dry_run:
        written = write_projection_handoff(path, projection)
        # Read it back through the consumer's own reader. The fingerprint check makes this
        # a measurement of producer-consumer agreement rather than a claim about it.
        reread = read_projection_handoff(written)
        if reread.fingerprint != projection.fingerprint:
            raise SystemExit(f"The handoff written to {written} does not read back identically.")

    report: dict[str, object] = {
        "snapshot_id": identifier,
        "captured_at_utc": captured_at,
        "season": season,
        "gameweek": target,
        "gameweeks_played": played,
        "handoff_path": str(path),
        "fingerprint": projection.fingerprint,
        "model_name": CONTROL_MODEL_NAME,
        "model_version": model_version,
        "version_is_promoted": model_version in IN_SEASON_CONTROL_MODEL_VERSIONS,
        **diagnostics,
    }
    return projection, written, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    parser.add_argument(
        "--snapshot-id", default=None, help="capture to project (default: the most recent)"
    )
    parser.add_argument(
        "--control-only",
        action="store_true",
        help="explicitly roll back to the previous in-season control",
    )
    parser.add_argument(
        "--gameweek",
        type=int,
        default=None,
        help="override the deadline read from the capture; normally unnecessary",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument(
        "--evidence-table",
        type=Path,
        default=None,
        help="explicit legacy elite candidate input; requires --evidence-manifest",
    )
    parser.add_argument(
        "--evidence-manifest",
        type=Path,
        default=None,
        help="manifest paired with --evidence-table",
    )
    arguments = parser.parse_args()

    if arguments.control_only and (
        arguments.evidence_table is not None or arguments.evidence_manifest is not None
    ):
        parser.error("--control-only cannot be combined with evidence artifact arguments")

    if not arguments.snapshot_root.is_dir():
        print(f"No snapshot directory at {arguments.snapshot_root}.")
        return 1
    if not arguments.archive_root.is_dir():
        print(
            f"Archive not found at {arguments.archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    _, written, report = build(
        arguments.snapshot_root,
        arguments.archive_root,
        arguments.handoff_root,
        snapshot_id=arguments.snapshot_id,
        gameweek=arguments.gameweek,
        evidence_table_path=arguments.evidence_table,
        evidence_manifest_path=arguments.evidence_manifest,
        control_only=arguments.control_only,
        dry_run=arguments.dry_run,
    )

    print(f"Capture   {report['snapshot_id']}  ({report['captured_at_utc']})")
    print(f"Target    {report['season']} gameweek {report['gameweek']}")
    print(f"Played    {report['gameweeks_played']} gameweek(s) of in-season history")
    print()
    print("Projection routes")
    for key in (
        "players",
        "players_with_in_season_minutes",
        "players_blended_two_stage",
        "players_shrunk_against_the_price_prior",
        "players_from_carry_over_only",
        "players_priced_from_the_prior",
    ):
        print(f"  {key:42} {report[key]}")
    print(f"  {'in_season_weight':42} {report['in_season_weight']}")
    print(f"  {'carry_over_weight':42} {report['carry_over_weight']}")
    if "elite_evidence_policy_version" in report:
        print()
        print("Phase C elite evidence")
        for key in (
            "elite_evidence_policy_version",
            "elite_evidence_cohort_size",
            "elite_evidence_players_uplifted",
            "elite_evidence_mean_points_delta",
            "elite_evidence_max_points_delta",
            "elite_evidence_table_sha256",
            "elite_evidence_manifest_sha256",
        ):
            print(f"  {key:42} {report[key]}")
    if report.get("projection_selection") == "phase_c_component_default":
        print()
        print("Phase C component model")
        for key in (
            "component_training_rows",
            "component_training_appearance_rows",
            "component_training_conditional_rows",
            "component_history_gameweeks",
            "component_history_incomplete_players",
            "route:component_model",
            "route:direct_control",
            "component_fingerprint",
        ):
            print(f"  {key:42} {report[key]}")
    elif report.get("projection_selection") == "legacy_control_fallback":
        print()
        print(f"Phase C fallback  {report['component_fallback_reason']}")
    print()
    print(f"Identity  {report['model_name']} / {report['model_version']}")
    if not report["version_is_promoted"]:
        print(
            "  This version is NOT in IN_SEASON_CONTROL_MODEL_VERSIONS, so a decision "
            "made from this handoff will be refused at verification. Pinning it is the "
            "promotion decision and belongs in a reviewed change to 'live'."
        )
    print(f"Fingerprint {report['fingerprint']}")
    if written is None:
        print("\nDry run: nothing written.")
    else:
        print(f"\nWrote {written} and read it back identically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
