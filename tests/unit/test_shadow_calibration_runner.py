"""The shadow calibration runner: what it measures, and what it refuses to claim."""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

from squadopt.experiments.residual_manifest import (
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_calibration import (
    ShadowCalibrationConfig,
    ShadowCalibrationError,
    attach_fixture_counts,
    bootstrap_interval,
    replay_identity,
    run_shadow_calibration,
)
from squadopt.experiments.shadow_report import (
    ShadowExecutionMetadata,
    report_to_dict,
    write_shadow_report,
)
from squadopt.preflight import RESIDUAL_EXPORT_COLUMNS

MODEL_NAME = "squadopt-deterministic-baseline"
MODEL_VERSION = "in-season-carry-over-v1"
FEATURE_CONTRACT = "in-season-carry-over-features-v1"
COMMIT = "c" * 40
POSITIONS = ("GK", "DEF", "MID", "FWD")
SEASONS = ("2021-22", "2022-23")
WHEN = "2026-08-28T12:00:00+00:00"


def _execution() -> ShadowExecutionMetadata:
    return ShadowExecutionMetadata(
        started_at_utc=WHEN,
        completed_at_utc="2026-08-28T12:00:01+00:00",
        elapsed_seconds=1.0,
        deterministic_seed=0,
        warnings=(),
    )


#: Wide enough that a 0.90 conformal radius fit on the early folds covers close to
#: 0.90 of the later ones: a deterministic sawtooth, not a random draw.
_RESIDUAL_CYCLE = (-3.0, -1.5, -0.5, 0.0, 0.5, 1.5, 3.0, -2.0, 2.0, 1.0)


def _table(*, gameweeks: tuple[int, ...] = tuple(range(2, 40)), players: int = 40) -> pd.DataFrame:
    rows = []
    step = 0
    for season in SEASONS:
        for gameweek in gameweeks:
            for index in range(players):
                residual = _RESIDUAL_CYCLE[step % len(_RESIDUAL_CYCLE)]
                step += 1
                predicted = 3.0 + (index % 5)
                rows.append(
                    {
                        "fold_id": f"{season}-gw{gameweek:02d}",
                        "season": season,
                        "gameweek": gameweek,
                        "player_id": 1000 + index,
                        "team_id": f"Club{index % 4}",
                        "position": POSITIONS[index % 4],
                        "predicted_points": float(predicted),
                        "realized_points": float(predicted + residual),
                        "residual": float(residual),
                    }
                )
    return pd.DataFrame(rows).loc[:, list(RESIDUAL_EXPORT_COLUMNS)]


def _calendar(table: pd.DataFrame, *, doubles_for: str = "Club0") -> pd.DataFrame:
    rows = []
    pairs = table.loc[:, ["season", "gameweek"]].drop_duplicates()
    clubs = sorted({str(value) for value in table["team_id"]})
    for season, gameweek in zip(pairs["season"], pairs["gameweek"], strict=True):
        for club in clubs:
            rows.append(
                {
                    "season": str(season),
                    "gameweek": int(gameweek),
                    "team_id": club,
                    "fixture_count": 2 if club == doubles_for else 1,
                }
            )
    return pd.DataFrame(rows)


def _bind(tmp_path: Path, table: pd.DataFrame, **overrides: object) -> object:
    tmp_path.mkdir(parents=True, exist_ok=True)
    table_path = tmp_path / "residuals.csv"
    with table_path.open("w", encoding="utf-8", newline="") as handle:
        table.to_csv(handle, index=False, lineterminator="\n")
    digest = hashlib.sha256(table_path.read_bytes()).hexdigest()
    document: dict[str, object] = {
        "contract_version": "oos_residual_export_v1",
        "candidate_label": "in_season_carry_over_blend",
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "feature_contract_version": FEATURE_CONTRACT,
        "training_contract_version": MODEL_VERSION,
        "evaluation_objective": "single_gameweek_realized_squad_points_v1",
        "development_seasons": sorted({str(season) for season in table["season"]}),
        "opening_gameweeks_included": bool((table["gameweek"] <= 1).any()),
        "fold_count": int(table["fold_id"].nunique()),
        "row_count": len(table),
        "repository_commit": COMMIT,
        "dataset_snapshot_id": "vaastav-fpl@" + "d" * 40,
        "table_sha256": digest,
        "created_at_utc": WHEN,
        "predicted_points_decimals": 9,
    }
    document.update(overrides)
    manifest_path = tmp_path / "residuals.manifest.json"
    manifest_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return load_residual_source_manifest(
        table_path,
        manifest_path,
        expect_model_name=str(document["model_name"]),
        expect_model_version=str(document["model_version"]),
    )


def _run(tmp_path: Path, table: pd.DataFrame | None = None, **config_overrides: object) -> object:
    frame = _table() if table is None else table
    manifest = _bind(tmp_path, frame)
    options: dict[str, object] = {"cutoff_fold_id": "2021-22-gw39"}
    options.update(config_overrides)
    return run_shadow_calibration(
        manifest,  # type: ignore[arg-type]
        frame,
        _calendar(frame),
        config=ShadowCalibrationConfig(**options),  # type: ignore[arg-type]
        generated_at_utc=WHEN,
        execution=_execution(),
        provenance_fingerprints={"repository_commit": COMMIT},
    )


def test_an_exact_model_run_measures_gate_p1(tmp_path: Path) -> None:
    report = _run(tmp_path)
    assert report.residual_source.model_version == MODEL_VERSION  # type: ignore[attr-defined]
    assert report.sample_size == 38  # type: ignore[attr-defined]
    gates = {gate.gate for gate in report.gate_results}  # type: ignore[attr-defined]
    assert "P1_player_coverage_pooled" in gates
    assert report.point_estimate is not None  # type: ignore[attr-defined]


def test_a_passing_p1_still_abstains_because_the_squad_gates_were_not_asked(
    tmp_path: Path,
) -> None:
    report = _run(tmp_path)
    if all(gate.passes for gate in report.gate_results):  # type: ignore[attr-defined]
        assert report.shadow_status == "abstained"  # type: ignore[attr-defined]
        assert any("S1_squad_pit_location" in reason for reason in report.reasons)  # type: ignore[attr-defined]
        assert report.shadow_status != "calibrated_internal"  # type: ignore[attr-defined]


def test_a_model_mismatch_is_refused_at_binding(tmp_path: Path) -> None:
    from squadopt.experiments.residual_manifest import ResidualSourceError

    with pytest.raises(ResidualSourceError, match="may not describe another"):
        table = _table()
        table_path = tmp_path / "r.csv"
        with table_path.open("w", encoding="utf-8", newline="") as handle:
            table.to_csv(handle, index=False, lineterminator="\n")
        digest = hashlib.sha256(table_path.read_bytes()).hexdigest()
        manifest_path = tmp_path / "r.manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "contract_version": "oos_residual_export_v1",
                    "candidate_label": "in_season_carry_over_blend",
                    "model_name": MODEL_NAME,
                    "model_version": MODEL_VERSION,
                    "feature_contract_version": FEATURE_CONTRACT,
                    "training_contract_version": MODEL_VERSION,
                    "evaluation_objective": "single_gameweek_realized_squad_points_v1",
                    "development_seasons": list(SEASONS),
                    "opening_gameweeks_included": False,
                    "fold_count": int(table["fold_id"].nunique()),
                    "row_count": len(table),
                    "repository_commit": COMMIT,
                    "dataset_snapshot_id": "vaastav-fpl@" + "d" * 40,
                    "table_sha256": digest,
                    "created_at_utc": WHEN,
                    "predicted_points_decimals": 9,
                }
            ),
            encoding="utf-8",
        )
        load_residual_source_manifest(
            table_path,
            manifest_path,
            expect_model_name="squadopt-learned-rate",
            expect_model_version="learned-rate-v2",
        )


def test_a_tampered_residual_table_is_refused_at_binding(tmp_path: Path) -> None:
    from squadopt.experiments.residual_manifest import ResidualSourceError

    table = _table()
    manifest = _bind(tmp_path, table)
    (tmp_path / "residuals.csv").write_text(
        (tmp_path / "residuals.csv").read_text(encoding="utf-8").replace("3.0", "9.0", 1),
        encoding="utf-8",
    )
    with pytest.raises(ResidualSourceError, match="changed after it was described"):
        load_residual_source_manifest(
            tmp_path / "residuals.csv",
            tmp_path / "residuals.manifest.json",
            expect_model_name=MODEL_NAME,
            expect_model_version=MODEL_VERSION,
        )
    assert manifest is not None


def test_a_table_that_is_not_the_bound_export_is_refused(tmp_path: Path) -> None:
    table = _table()
    manifest = _bind(tmp_path, table)
    with pytest.raises(ShadowCalibrationError, match="same export"):
        run_shadow_calibration(
            manifest,  # type: ignore[arg-type]
            table.head(10),
            _calendar(table),
            config=ShadowCalibrationConfig(cutoff_fold_id="2021-22-gw39"),
            generated_at_utc=WHEN,
            execution=_execution(),
            provenance_fingerprints={},
        )


def test_a_multi_week_horizon_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ShadowCalibrationError, match="single-gameweek"):
        ShadowCalibrationConfig(cutoff_fold_id="2021-22-gw39", horizon=3)


def test_a_moved_threshold_or_seed_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ShadowCalibrationError, match=r"pre-registered at 0.9"):
        ShadowCalibrationConfig(cutoff_fold_id="2021-22-gw39", confidence_level=0.80)
    with pytest.raises(ShadowCalibrationError, match="may not move"):
        ShadowCalibrationConfig(cutoff_fold_id="2021-22-gw39", bootstrap_seed=7)


def test_too_few_evaluation_folds_abstains_without_inventing_metrics(tmp_path: Path) -> None:
    report = _run(tmp_path, cutoff_fold_id="2022-23-gw20")
    assert report.shadow_status == "abstained"  # type: ignore[attr-defined]
    assert report.point_estimate is None  # type: ignore[attr-defined]
    assert report.gate_results == ()  # type: ignore[attr-defined]
    assert report.calibration_diagnostics == {}  # type: ignore[attr-defined]
    assert any("fewer than the" in reason for reason in report.reasons)  # type: ignore[attr-defined]


def test_an_uncovered_gameweek_abstains_rather_than_scoring_a_zero(tmp_path: Path) -> None:
    table = _table()
    manifest = _bind(tmp_path, table)
    calendar = _calendar(table)
    thinned = calendar.loc[calendar["gameweek"] != 30]
    report = run_shadow_calibration(
        manifest,  # type: ignore[arg-type]
        table,
        thinned,
        config=ShadowCalibrationConfig(cutoff_fold_id="2021-22-gw39"),
        generated_at_utc=WHEN,
        execution=_execution(),
        provenance_fingerprints={},
    )
    assert report.shadow_status == "abstained"
    assert report.point_estimate is None
    assert any("missing, not blank" in reason for reason in report.reasons)


def test_missing_calendar_rows_inside_a_covered_week_are_blanks_not_gaps(
    tmp_path: Path,
) -> None:
    table = _table()
    calendar = _calendar(table)
    dropped = calendar.loc[~((calendar["team_id"] == "Club3") & (calendar["gameweek"] == 5))]
    joined, uncovered = attach_fixture_counts(table, dropped)
    assert uncovered == ()
    blanks = joined.loc[(joined["team_id"] == "Club3") & (joined["gameweek"] == 5)]
    assert (blanks["fixture_count"] == 0).all()


def test_a_cutoff_outside_the_export_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ShadowCalibrationError, match=r"precedes the export|not one of"):
        _run(tmp_path, cutoff_fold_id="2019-20-gw02")


def test_the_run_is_deterministic_byte_for_byte(tmp_path: Path) -> None:
    first, second = _run(tmp_path / "a"), _run(tmp_path / "b")
    assert report_to_dict(first) == report_to_dict(second)  # type: ignore[arg-type]
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    write_shadow_report(first, out_a)  # type: ignore[arg-type]
    write_shadow_report(second, out_b)  # type: ignore[arg-type]
    assert out_a.read_bytes() == out_b.read_bytes()
    assert b"\r" not in out_a.read_bytes()


def test_replay_identity_excludes_only_the_wall_clock(tmp_path: Path) -> None:
    document = report_to_dict(_run(tmp_path))  # type: ignore[arg-type]
    other = {**document, "generated_at_utc": "2027-01-01T00:00:00+00:00"}
    assert replay_identity(document) == replay_identity(other)
    conflicting = {**document, "sample_size": document["sample_size"] + 1}  # type: ignore[operator]
    assert replay_identity(document) != replay_identity(conflicting)


def test_atomic_writer_accepts_concurrent_identical_content(tmp_path: Path) -> None:
    from scripts.run_shadow_calibration import _write_once

    target = tmp_path / "shadow.json"
    document = report_to_dict(_run(tmp_path / "source"))  # type: ignore[arg-type]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: _write_once(document, target), range(2)))

    assert sorted(outcomes) == ["replay", "written"]
    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert list(tmp_path.glob(".shadow.json.tmp-*")) == []


def test_atomic_writer_refuses_a_concurrent_conflict(tmp_path: Path) -> None:
    from scripts.run_shadow_calibration import _write_once

    target = tmp_path / "shadow.json"
    first = report_to_dict(_run(tmp_path / "first"))  # type: ignore[arg-type]
    second = {**first, "sample_size": int(first["sample_size"]) + 1}

    def attempt(document: dict[str, object]) -> str:
        try:
            return _write_once(document, target)
        except SystemExit:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (first, second)))

    assert sorted(outcomes) == ["conflict", "written"]
    assert list(tmp_path.glob(".shadow.json.tmp-*")) == []


def test_the_bootstrap_is_deterministic_and_refuses_non_finite() -> None:
    values = [0.90, 0.88, 0.92, 0.91, 0.89]
    first = bootstrap_interval(values, resamples=200, seed=0)
    second = bootstrap_interval(values, resamples=200, seed=0)
    assert first == second
    assert first[0] <= first[1]
    with pytest.raises(ShadowCalibrationError, match="non-finite"):
        bootstrap_interval([0.9, float("nan")], resamples=10, seed=0)


def test_the_report_carries_no_public_facing_probability_prose(tmp_path: Path) -> None:
    """Internal numbers are permitted; member-facing claim language is not."""

    document = json.dumps(report_to_dict(_run(tmp_path)))  # type: ignore[arg-type]
    forbidden = re.compile(r"olas.l.k|\bP\(|%", re.IGNORECASE)
    assert forbidden.search(document) is None, document[:400]


def test_the_public_site_schema_rejects_the_report(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = (
        Path(__file__).resolve().parents[2] / "docs" / "contracts" / "ui_view_v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report_to_dict(_run(tmp_path)), schema)  # type: ignore[arg-type]


def test_the_runs_own_artifact_does_not_count_as_a_dirty_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Found by running the real measurement twice: the report lands in the repository,
    so an unfiltered dirty-tree check made the second run record different provenance
    for identical numbers — a replay that read as a conflict."""

    import subprocess

    import scripts.run_shadow_calibration as cli

    output = cli.REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season.json"

    def fake_status(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="?? docs/shadow_calibration_in_season.json\n"
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_status)
    assert cli._tree_dirty_ignoring(output) is False

    def fake_status_with_source(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="?? docs/shadow_calibration_in_season.json\n M src/squadopt/x.py\n",
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_status_with_source)
    assert cli._tree_dirty_ignoring(output) is True


def test_an_unreadable_tree_is_reported_dirty_rather_than_assumed_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    import scripts.run_shadow_calibration as cli

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("git is unavailable")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    assert cli._tree_dirty_ignoring(cli.DEFAULT_OUTPUT) is True
