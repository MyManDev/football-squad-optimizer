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

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
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
    COMPONENT_ELITE_FEATURE_CONTRACT_VERSION,
    COMPONENT_ELITE_MODEL_VERSION,
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
    """Return the most recent live capture's identifier.

    Identifiers begin with the capture instant in a sortable spelling, so the newest is the
    last in lexical order — among the live captures: Top-100 and elite-picks captures share
    the root and sort after every ``fpl-live`` name, and a projection of the Overall
    standings pages is not a projection of anything.
    """

    live = list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    if not live:
        raise SystemExit(f"No {FPL_LIVE_SOURCE} captures under {snapshot_root}.")
    return live[-1]


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
    include_components: bool = False,
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
    table = snapshot.table.loc[:, ["player_id", "expected_points"]]
    if include_components:
        diagnostics["component_training_cutoff"] = provenance.training_cutoff
        diagnostics["component_training_data_fingerprint"] = provenance.training_data_fingerprint
        # The sampler needs the raw conditional point mean, including negative values.
        raw = rows.drop(columns="expected_points_if_appearance").copy()
        raw["raw_expected_points_if_appearance"] = predicted["raw_expected_points_if_appearance"]
        table = raw.merge(table, on="player_id", validate="one_to_one")
    return table, diagnostics


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
    development_only: bool = False,
    dry_run: bool = False,
    writer: Callable[[Path, InSeasonProjection], Path] = write_projection_handoff,
) -> tuple[InSeasonProjection, Path | None, dict[str, object]]:
    """Project one capture's open deadline and write the handoff for it.

    ``development_only`` restricts all historical inputs to the frozen component training
    seasons for prospective 2026-27 in-season preparation. In particular, the legacy
    fallback cannot use the withheld season's carry-over in this mode.
    """

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
    if development_only and (season != "2026-27" or target <= 1):
        raise SystemExit("--development-only requires a 2026-27 in-season capture target.")
    # Every gameweek before the target has been played, so that is the in-season sample.
    played = target - 1

    roster = player_snapshot(bootstrap)
    history = in_season_totals(bootstrap, fixtures, captured_at_utc=captured_at)
    panel = (
        build_panel(archive_root, seasons=COMPONENT_TRAINING_SEASONS)
        if development_only
        else build_panel(archive_root)
    )
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
    if development_only:
        diagnostics["fallback_training_seasons"] = list(COMPONENT_TRAINING_SEASONS)
    evidence_fingerprint: str | None = None
    # The base projection first — the component model when the capture carries settled
    # history, the legacy blend otherwise or on request — then, when the Top-100 evidence
    # is supplied, the same bounded uplift on whichever base was chosen. The two used to
    # be exclusive routes; they are one policy on two bases, and the handoff names which.
    if control_only:
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
        on_component = model_version == COMPONENT_MODEL_VERSION
        model_version = (
            COMPONENT_ELITE_MODEL_VERSION if on_component else ELITE_EVIDENCE_MODEL_VERSION
        )
        feature_contract_version = (
            COMPONENT_ELITE_FEATURE_CONTRACT_VERSION
            if on_component
            else ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION
        )
        diagnostics.update(adjusted.diagnostics)
        manifest_digest = hashlib.sha256(evidence_manifest_path.read_bytes()).hexdigest()
        diagnostics["elite_evidence_manifest_sha256"] = manifest_digest
        evidence_fingerprint = hashlib.sha256(
            f"{evidence.attrs['table_sha256']}:{manifest_digest}".encode()
        ).hexdigest()
        diagnostics["elite_evidence_base_selection"] = diagnostics.get("projection_selection")
        diagnostics["projection_selection"] = (
            "phase_c_component_elite" if on_component else "legacy_elite_candidate"
        )

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
        written = writer(path, projection)
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
