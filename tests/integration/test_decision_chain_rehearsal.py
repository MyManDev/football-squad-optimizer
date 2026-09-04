"""Synthetic end-to-end rehearsal of the real-data decision chain.

The chain rehearsed here is the one the open issues (#38, #43, #45) must eventually run
on real artifacts:

    declared candidate identity
    -> residual exports with manifests
    -> artifact preflight
    -> calendar recalibration measurement
    -> scenario-backed live-risk diagnostics
    -> live squad report

Everything is synthetic and deterministic. The rehearsal proves the handoff seams fit
together before any real artifact exists, and the negative cases prove that a broken
artifact is stopped at the seam where it first becomes wrong.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from squadopt.backtest.production_benchmark import CandidateDeclaration
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    CONTROL_MODEL_NAME,
    CONTROL_MODEL_VERSION,
    OPENING_FEATURE_CONTRACT_VERSION,
    LiveResidualHistory,
    LiveRiskBlocker,
    LiveRiskStatus,
    build_recommendation,
    project,
    read_inputs,
    render,
)
from squadopt.preflight import (
    PreflightExpectations,
    compute_table_sha256,
    run_export_pair_preflight,
    run_residual_export_preflight,
)
from squadopt.recalibration import (
    RecalibrationConfig,
    measure_calendar_recalibration,
)
from squadopt.scenarios import ScenarioConfig, ScenarioEvaluationConfig

SEASON = "2026-27"
HISTORY_SEASON = "2025-26"
RESIDUAL_SEASONS = ("2024-25", "2025-26")
RESIDUAL_GAMEWEEKS = (1, 2, 3)
CAPTURED_AT = "2026-08-13T20:11:43Z"
COMMIT = "c" * 40
SNAPSHOT_ID = "archive@rehearsal-pin"
AVAILABILITY_CONTRACT = "captured_availability_rule_v1"

REFERENCE_LABEL = "calendar_blind_control"
CANDIDATE_LABEL = "calendar_aware_candidate"

TEAMS: list[dict[str, Any]] = [
    {"id": index, "code": index * 3, "name": f"Club {index}", "short_name": f"C{index}"}
    for index in range(1, 7)
]
POSITION_SHAPE: list[tuple[int, int]] = [(1, 3), (2, 8), (3, 8), (4, 5)]


# --- the synthetic world -----------------------------------------------------


def _elements() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    code = 1000
    for element_type, count in POSITION_SHAPE:
        for index in range(count):
            code += 1
            records.append(
                {
                    "code": code,
                    "id": code - 1000,
                    "first_name": "Player",
                    "second_name": f"{code}",
                    "team": (index % 6) + 1,
                    "element_type": element_type,
                    "now_cost": 45 + (index % 4) * 5,
                    "status": "a",
                    "chance_of_playing_next_round": None,
                    "news": "",
                    "news_added": None,
                }
            )
    return records


def _capture(directory: Path) -> Any:
    bootstrap = {
        "events": [
            {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
            {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
        ],
        "teams": TEAMS,
        "elements": _elements(),
    }
    metadata = write_snapshot(
        directory,
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode("utf-8"),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    return read_snapshot(directory, metadata.snapshot_id)


def _panel() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for code in (1001, 1004, 1012):
        for gameweek in range(1, 11):
            rows.append(
                {
                    "season": HISTORY_SEASON,
                    "gameweek": gameweek,
                    "player_id": code,
                    "name": f"Player {code}",
                    "team_id": "Club 1",
                    "position": "MID",
                    "price_tenths": 50,
                    "minutes": 90,
                    "total_points": 5,
                }
            )
    return pd.DataFrame(rows)


def _residual_export(projection_table: pd.DataFrame, *, shift: float) -> pd.DataFrame:
    """One regime's export: every projected player, every fold, outcomes shared.

    ``shift`` perturbs only the predictions, so two regimes built from the same
    projection disagree on predicted points while agreeing on realized points --
    exactly what the pairing rule requires of a real reference/candidate pair.
    """

    players = projection_table.loc[:, ["player_id", "team_id", "position"]].sort_values(
        "player_id", kind="stable"
    )
    rows: list[dict[str, object]] = []
    for season in RESIDUAL_SEASONS:
        for gameweek in RESIDUAL_GAMEWEEKS:
            for row in players.itertuples(index=False):
                base = 3.0 + (int(row.player_id) % 5) * 0.5
                realized = base + float(((int(row.player_id) + gameweek) % 7) - 3) / 2.0
                predicted = max(base + shift, 0.0)
                rows.append(
                    {
                        "fold_id": f"{season}-gw{gameweek:02d}",
                        "season": season,
                        "gameweek": gameweek,
                        "player_id": int(row.player_id),
                        "team_id": str(row.team_id),
                        "position": str(row.position),
                        "predicted_points": predicted,
                        "realized_points": realized,
                        "residual": realized - predicted,
                    }
                )
    return pd.DataFrame(rows)


def _manifest(table: pd.DataFrame, *, label: str, model: tuple[str, str, str]) -> dict[str, object]:
    model_name, model_version, feature_contract = model
    return {
        "contract_version": "oos_residual_export_v1",
        "candidate_label": label,
        "model_name": model_name,
        "model_version": model_version,
        "feature_contract_version": feature_contract,
        "training_contract_version": "training_v1",
        "evaluation_objective": "single_gameweek_realized_squad_points_v1",
        "development_seasons": sorted({str(season) for season in table["season"]}),
        "opening_gameweeks_included": bool((table["gameweek"] == 1).any()),
        "fold_count": int(table["fold_id"].nunique()),
        "row_count": len(table),
        "repository_commit": COMMIT,
        "dataset_snapshot_id": SNAPSHOT_ID,
        "table_sha256": "0" * 64,
        "created_at_utc": "2026-08-15T00:00:00Z",
    }


def _fixture_rows(
    season: str, fixture_id: int, gameweek: int, home: int, away: int
) -> list[dict[str, object]]:
    common: dict[str, object] = {
        "snapshot_id": SNAPSHOT_ID,
        "captured_at_utc": None,
        "season": season,
        "gameweek": gameweek,
        "fixture_id": fixture_id,
        "kickoff_time_utc": f"{season[:4]}-09-{gameweek + 1:02d}T14:00:00Z",
        "deadline_timestamp_utc": None,
        "status": "final",
        "fixture_difficulty": 3.0,
    }
    return [
        {**common, "team_id": home, "opponent_team_id": away, "is_home": True},
        {**common, "team_id": away, "opponent_team_id": home, "is_home": False},
    ]


def _fixtures() -> pd.DataFrame:
    """A calendar with single, double, and blank team-gameweeks in every season.

    Gameweek 2 gives Club 1 (code 3) two fixtures and Club 6 (code 18) none, so the
    recalibration measurement exercises all three fixture-count groups.
    """

    codes = {index: index * 3 for index in range(1, 7)}
    rows: list[dict[str, object]] = []
    for season in RESIDUAL_SEASONS:
        fixture_id = 0
        for gameweek in (1, 3):
            for home, away in ((1, 2), (3, 4), (5, 6)):
                fixture_id += 1
                rows.extend(_fixture_rows(season, fixture_id, gameweek, codes[home], codes[away]))
        for home, away in ((1, 2), (3, 4), (1, 5)):
            fixture_id += 1
            rows.extend(_fixture_rows(season, fixture_id, 2, codes[home], codes[away]))
    frame = pd.DataFrame(rows)
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    return frame


def _team_codes() -> pd.DataFrame:
    rows = [
        {"season": season, "name": f"Club {index}", "code": index * 3}
        for season in RESIDUAL_SEASONS
        for index in range(1, 7)
    ]
    frame = pd.DataFrame(rows)
    frame["code"] = frame["code"].astype("int64")
    return frame


CONTROL_IDENTITY = (
    CONTROL_MODEL_NAME,
    CONTROL_MODEL_VERSION,
    OPENING_FEATURE_CONTRACT_VERSION,
)
CANDIDATE_IDENTITY = ("candidate-learned-rate", "0.1.0", "form_window_v1")


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    directory = tmp_path_factory.mktemp("rehearsal")
    inputs = read_inputs(_capture(directory / "capture"), season=SEASON)
    projection = project(inputs, _panel())

    reference_table = _residual_export(projection.table, shift=0.4)
    candidate_table = _residual_export(projection.table, shift=0.1)
    reference_path = directory / "reference.csv"
    candidate_path = directory / "candidate.csv"
    reference_table.to_csv(reference_path, index=False)
    candidate_table.to_csv(candidate_path, index=False)

    reference_manifest = _manifest(reference_table, label=REFERENCE_LABEL, model=CONTROL_IDENTITY)
    reference_manifest["table_sha256"] = compute_table_sha256(reference_path)
    candidate_manifest = _manifest(candidate_table, label=CANDIDATE_LABEL, model=CANDIDATE_IDENTITY)
    candidate_manifest["table_sha256"] = compute_table_sha256(candidate_path)

    return {
        "inputs": inputs,
        "projection": projection,
        "reference_table": reference_table,
        "candidate_table": candidate_table,
        "reference_path": reference_path,
        "candidate_path": candidate_path,
        "reference_manifest": reference_manifest,
        "candidate_manifest": candidate_manifest,
    }


def _declaration() -> CandidateDeclaration:
    return CandidateDeclaration(
        candidate_id="rehearsal_learned_rate_candidate",
        model_name=CANDIDATE_IDENTITY[0],
        model_version=CANDIDATE_IDENTITY[1],
        feature_contract_version=CANDIDATE_IDENTITY[2],
        changed_component="expected_points_rate",
        change_summary="Synthetic rehearsal stand-in for the #43 learned-rate candidate.",
        frozen_components=(
            "expected_minutes_stage",
            "cold_start_ladder",
            "availability_rule",
            "optimizer_contract",
            "promotion_gates",
        ),
        source_reference="https://github.com/MyManDev/football-squad-optimizer/issues/43",
    )


# --- stage 1: declared identity threads into the manifests ------------------


def test_the_declared_candidate_identity_matches_its_manifest(world: dict[str, Any]) -> None:
    """A formal gate freezes the declaration; the export must name the same model."""

    declaration = _declaration()
    manifest = world["candidate_manifest"]

    assert declaration.model_name == manifest["model_name"]
    assert declaration.model_version == manifest["model_version"]
    assert declaration.feature_contract_version == manifest["feature_contract_version"]
    assert declaration.declaration_fingerprint == _declaration().declaration_fingerprint


# --- stage 2: preflight accepts the pair ------------------------------------


def test_preflight_accepts_both_exports_and_their_pairing(world: dict[str, Any]) -> None:
    expectations = PreflightExpectations(
        fold_count=len(RESIDUAL_SEASONS) * len(RESIDUAL_GAMEWEEKS),
        row_count=len(world["reference_table"]),
        development_seasons=RESIDUAL_SEASONS,
        repository_commit=COMMIT,
        dataset_snapshot_id=SNAPSHOT_ID,
        opening_gameweeks_included=True,
    )

    for table_key, path_key, manifest_key in (
        ("reference_table", "reference_path", "reference_manifest"),
        ("candidate_table", "candidate_path", "candidate_manifest"),
    ):
        report = run_residual_export_preflight(
            world[table_key],
            world[manifest_key],
            table_sha256=compute_table_sha256(world[path_key]),
            expectations=expectations,
            artifact_label=table_key,
        )
        assert report.passed, [finding.detail for finding in report.failures]

    pair = run_export_pair_preflight(
        world["reference_table"],
        world["reference_manifest"],
        world["candidate_table"],
        world["candidate_manifest"],
    )
    assert pair.passed, [finding.detail for finding in pair.failures]


# --- stage 3: recalibration measures the accepted pair ----------------------


def test_recalibration_measures_the_pair_across_fixture_groups(
    world: dict[str, Any],
) -> None:
    settings = RecalibrationConfig(reference_candidate=REFERENCE_LABEL, candidate=CANDIDATE_LABEL)
    residuals = pd.concat(
        [
            world["reference_table"].assign(candidate=REFERENCE_LABEL),
            world["candidate_table"].assign(candidate=CANDIDATE_LABEL),
        ],
        ignore_index=True,
    )

    result = measure_calendar_recalibration(residuals, _fixtures(), _team_codes(), settings)

    groups = {entry.fixture_group for entry in result.comparisons}
    assert {"overall", "single", "double_plus", "blank"} <= groups
    repeat = measure_calendar_recalibration(residuals, _fixtures(), _team_codes(), settings)
    assert result.measurement_fingerprint == repeat.measurement_fingerprint


# --- stages 4-6: matched evidence supports live risk and the report ---------


def _history(world: dict[str, Any], **overrides: Any) -> LiveResidualHistory:
    table = overrides.pop("table", world["reference_table"])
    manifest = world["reference_manifest"]
    settings: dict[str, Any] = {
        "model_name": manifest["model_name"],
        "model_version": manifest["model_version"],
        "feature_contract_version": manifest["feature_contract_version"],
        "post_processing_contract_version": AVAILABILITY_CONTRACT,
        "source_id": f"{manifest['candidate_label']}@{manifest['table_sha256'][:12]}",
    }
    settings.update(overrides)
    return LiveResidualHistory(table, **settings)


def _recommend(world: dict[str, Any], history: LiveResidualHistory) -> Any:
    return build_recommendation(
        world["inputs"],
        world["projection"],
        risk_history=history,
        risk_scenario_config=ScenarioConfig(
            scenario_count=64, min_history_folds=2, min_player_observations=2
        ),
        risk_evaluation_config=ScenarioEvaluationConfig(points_threshold=40.0),
    )


def test_control_matched_evidence_yields_risk_backed_live_report(
    world: dict[str, Any],
) -> None:
    recommendation = _recommend(world, _history(world))

    assert recommendation.risk.status is LiveRiskStatus.AVAILABLE
    assert recommendation.risk.metrics is not None
    assert recommendation.risk.metrics.scenario_count == 64
    provenance = recommendation.risk.residual_provenance
    assert str(provenance["source_id"]).startswith(REFERENCE_LABEL)
    report = render(recommendation)
    assert "lower 10% quantile" in report
    assert "P(score < 40)" in report


def test_the_full_chain_is_deterministic_end_to_end(world: dict[str, Any]) -> None:
    first = _recommend(world, _history(world))
    second = _recommend(world, _history(world))

    assert first.risk.scenario_fingerprint == second.risk.scenario_fingerprint
    assert first.risk.metrics == second.risk.metrics
    assert [player for player in first.squad] == [player for player in second.squad]


# --- negative rehearsals: the chain stops at the broken seam ----------------


def test_a_tampered_candidate_file_is_stopped_at_preflight(
    world: dict[str, Any], tmp_path: Path
) -> None:
    tampered = tmp_path / "candidate.csv"
    tampered.write_bytes(world["candidate_path"].read_bytes() + b"tampered")

    report = run_residual_export_preflight(
        pd.read_csv(tampered),
        world["candidate_manifest"],
        table_sha256=compute_table_sha256(tampered),
    )

    assert not report.passed
    assert "table_checksum_matches_manifest" in {finding.check for finding in report.failures}


def test_exports_with_different_fold_policies_cannot_be_paired(
    world: dict[str, Any],
) -> None:
    truncated = (
        world["candidate_table"]
        .loc[world["candidate_table"]["gameweek"] != 3]
        .reset_index(drop=True)
    )
    manifest = dict(world["candidate_manifest"])
    manifest["fold_count"] = int(truncated["fold_id"].nunique())
    manifest["row_count"] = len(truncated)

    pair = run_export_pair_preflight(
        world["reference_table"], world["reference_manifest"], truncated, manifest
    )

    failed = {finding.check for finding in pair.failures}
    assert "pair_fold_policy" in failed
    assert "pair_row_keys" in failed


def test_exports_from_different_commits_cannot_be_paired(world: dict[str, Any]) -> None:
    manifest = dict(world["candidate_manifest"])
    manifest["repository_commit"] = "d" * 40

    pair = run_export_pair_preflight(
        world["reference_table"],
        world["reference_manifest"],
        world["candidate_table"],
        manifest,
    )

    assert "pair_repository_commit" in {finding.check for finding in pair.failures}


def test_gw2_only_residuals_cannot_support_the_gw1_live_target(
    world: dict[str, Any],
) -> None:
    """The GW1 rule end-to-end: midseason evidence is refused, not converted."""

    midseason = (
        world["reference_table"]
        .loc[world["reference_table"]["gameweek"] != 1]
        .reset_index(drop=True)
    )

    recommendation = _recommend(world, _history(world, table=midseason))

    assert recommendation.risk.status is LiveRiskStatus.UNAVAILABLE
    assert LiveRiskBlocker.UNSUPPORTED_OPENING_GAMEWEEK in recommendation.risk.blockers
    assert recommendation.risk.metrics is None


def test_an_unpromoted_candidate_cannot_supply_live_risk_evidence(
    world: dict[str, Any],
) -> None:
    """Candidate residuals under a candidate identity must not back a live decision."""

    recommendation = _recommend(
        world,
        _history(
            world,
            table=world["candidate_table"],
            model_name=CANDIDATE_IDENTITY[0],
            model_version=CANDIDATE_IDENTITY[1],
        ),
    )

    assert recommendation.risk.status is LiveRiskStatus.UNAVAILABLE
    assert recommendation.risk.blockers == (LiveRiskBlocker.MODEL_MISMATCH,)
