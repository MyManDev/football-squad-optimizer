"""E2 under an explicitly selected sampler: declared identity, an honest pin, bound checkpoints.

The sampler tests use the real component sampler on a small synthetic fold; the scoring test
keeps the cheap scorer of the probe tests. Checkpoint tests drive the CLI on recorded pools
with generation only, so every run costs a few CP-SAT solves and nothing else.
"""

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from scripts import _phase_e_checkpoints as checkpoints
from scripts import probe_phase_e_runtime as probe
from tests.fixtures.synthetic_players import make_baseline_players
from tests.unit.test_probe_phase_e_runtime import MODEL, _draw_factory, _fast_scorer
from tests.unit.test_run_component_squad_calibration import _frozen_decision

from squadopt.optimization import generate_squad_candidates
from squadopt.scenarios import selection
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    ComponentScenarioDraw,
    ConditionalResidualConfig,
)

CONDITIONAL = ConditionalResidualConfig(fraction=0.25, minimum_rows=4)
CONDITIONAL_ARGUMENTS = (
    "--sampler",
    "conditional",
    "--conditional-residual-fraction",
    "0.25",
    "--conditional-residual-minimum-rows",
    "4",
)


def test_the_sampler_choice_binds_its_settings_and_its_own_probe_contract() -> None:
    assert probe.conditional_from_arguments("foundation", None, None) is None
    with pytest.raises(probe.ProbeError):
        probe.conditional_from_arguments("foundation", 0.25, None)
    with pytest.raises(probe.ProbeError):
        probe.conditional_from_arguments("conditional", 0.25, None)
    with pytest.raises(probe.ProbeError):
        probe.conditional_from_arguments("other", None, None)
    assert probe.conditional_from_arguments("conditional", 0.25, 4) == CONDITIONAL

    assert probe.sampler_record(None)["contract_version"] == COMPONENT_SCENARIO_CONTRACT_VERSION
    assert probe.sampler_record(None)["residual_selection"] == "fold_uniform"
    assert probe.sampler_record(CONDITIONAL) == {
        "contract_version": CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
        "residual_selection": "conditional_neighbourhood",
        "conditional_residual_fraction": 0.25,
        "conditional_residual_minimum_rows": 4,
    }
    assert probe.probe_contract_version(None) == probe.PROBE_CONTRACT_VERSION
    assert probe.probe_contract_version(CONDITIONAL) == probe.DEVELOPMENT_PROBE_CONTRACT_VERSION
    assert probe.DEVELOPMENT_PROBE_CONTRACT_VERSION != probe.PROBE_CONTRACT_VERSION


def test_a_fold_point_draws_with_the_selected_sampler_on_every_seed() -> None:
    handoff, prepared, _ = _frozen_decision()
    foundation = probe._fold_point(handoff, prepared.fold_id, prepared.projections)
    conditional = probe._fold_point(
        handoff, prepared.fold_id, prepared.projections, conditional_residuals=CONDITIONAL
    )
    assert foundation.draw_factory is not None and conditional.draw_factory is not None

    for seed in (0, 3):
        base = foundation.draw_factory(seed)
        candidate = conditional.draw_factory(seed)
        assert probe.draw_sampler_version(base) == COMPONENT_SCENARIO_CONTRACT_VERSION
        assert probe.draw_sampler_version(candidate) == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
        identity = probe._draw_identity(candidate)
        assert (
            identity["component_sampler_contract_version"] == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
        )
        assert identity["residual_selection"] == "conditional_neighbourhood"
        assert identity["deterministic_seed"] == seed
        # Same appearances and source folds seed for seed; only the residual rows move.
        pd.testing.assert_frame_equal(base.sampled_appearances, candidate.sampled_appearances)
        assert base.scenarios.source_fold_ids == candidate.scenarios.source_fold_ids
        assert not base.scenarios.scenario_points.equals(candidate.scenarios.scenario_points)


def _conditional_factory(pool: pd.DataFrame) -> Callable[[int], ComponentScenarioDraw]:
    base = _draw_factory(pool)

    def factory(seed: int) -> ComponentScenarioDraw:
        draw = base(seed)
        scenarios = replace(
            draw.scenarios,
            diagnostics={
                "component_sampler_contract_version": CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
                "residual_selection": "conditional_neighbourhood",
            },
        )
        return replace(draw, scenarios=scenarios)

    return factory


def test_the_probe_pin_names_the_declared_sampler_so_a_conditional_draw_is_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selection, "score_component_scenario_decision", _fast_scorer)
    monkeypatch.setattr(probe, "score_component_scenario_decision", _fast_scorer)
    pool = make_baseline_players()
    factory = _conditional_factory(pool)
    point = probe.DecisionPoint(
        label="2024-25-gw38",
        kind="fold",
        pool=pool,
        draw_factory=factory,
        covered_player_ids=frozenset(int(value) for value in pool["player_id"]),
    )

    record = probe.probe_decision_point(point, candidate_counts=(4,), sensitivity_seeds=(1,))

    (run,) = record["runs"]
    scoring = run["scoring"]
    assert scoring["draw"]["component_sampler_contract_version"] == (
        CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    )
    assert scoring["selector_probe_pin"]["pin"] == [[MODEL, CONDITIONAL_RESIDUAL_CONTRACT_VERSION]]
    assert scoring["selector_probe_pin"]["status"] == "SELECTED"
    assert scoring["selector_probe_pin"]["candidate_count_scored"] == 4
    assert scoring["selector_production"]["status"] == "FALLBACK_PHASE_D_NOT_CALIBRATED"
    assert scoring["draw_repeat_identical"] and scoring["selection_repeat_identical"]
    assert run["within_budget"] is True

    # A pin shaped like the foundation sampler never reaches this draw's scenarios.
    candidates = generate_squad_candidates(pool, candidate_count=4)
    foundation_pin = ((MODEL, COMPONENT_SCENARIO_CONTRACT_VERSION),)
    assert probe._select(candidates, factory(0), foundation_pin)["status"] == (
        "FALLBACK_PHASE_D_NOT_CALIBRATED"
    )


def _pool_csv(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}.csv"
    make_baseline_players().to_csv(path, index=False)
    return path


def _arguments(pool: Path, output: Path, directory: Path, *extra: str) -> list[str]:
    return [
        "--live-pool",
        f"2026-27-gw01={pool}",
        "--candidate-counts",
        "4",
        "--skip-scoring",
        "--checkpoint-dir",
        str(directory),
        "--json-output",
        str(output),
        *extra,
    ]


def test_checkpoints_belong_to_one_run_identity_and_resume_only_that_run(tmp_path: Path) -> None:
    pool = _pool_csv(tmp_path, "gw01")
    directory = tmp_path / "run"
    checkpoint_path = directory / "checkpoints" / "2026-27-gw01.json"

    assert probe.main(_arguments(pool, tmp_path / "first.json", directory)) == 0
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["contract_version"] == checkpoints.CHECKPOINT_CONTRACT
    assert checkpoint["run_identity"]["sampler"] == probe.sampler_record(None)
    assert checkpoint["run_identity"]["contract_version"] == probe.PROBE_CONTRACT_VERSION
    assert checkpoint["completed_counts"] == [4] and checkpoint["kind"] == "live"
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed" and status["failed_labels"] == {}
    assert status["completed_labels"] == ["2026-27-gw01"]
    first = json.loads((tmp_path / "first.json").read_text(encoding="utf-8"))
    assert first["contract_version"] == probe.PROBE_CONTRACT_VERSION
    assert first["sampler"] == probe.sampler_record(None)
    assert first["development_only"] is False
    execution = first["execution"]
    assert execution["workers"] == 1 and execution["solver_search_workers"] == 1
    assert execution["timing_context"] == "isolated_single_process"
    assert execution["checkpoint_dir"] == str(directory) and execution["resumed_labels"] == []

    # The same identity is not silently rerun over its own checkpoints.
    assert probe.main(_arguments(pool, tmp_path / "second.json", directory)) == 1
    assert not (tmp_path / "second.json").exists()

    # With --resume the completed pool is reused exactly as it was measured.
    assert probe.main(_arguments(pool, tmp_path / "third.json", directory, "--resume")) == 0
    third = json.loads((tmp_path / "third.json").read_text(encoding="utf-8"))
    assert third["execution"]["resumed_labels"] == ["2026-27-gw01"]
    assert third["decision_points"] == first["decision_points"]

    # Another sampler is another identity: refused even with --resume, nothing overwritten.
    before = checkpoint_path.read_bytes()
    assert (
        probe.main(
            _arguments(
                pool, tmp_path / "fourth.json", directory, "--resume", *CONDITIONAL_ARGUMENTS
            )
        )
        == 1
    )
    assert checkpoint_path.read_bytes() == before
    assert not (tmp_path / "fourth.json").exists()

    # An existing artifact is never replaced.
    assert probe.main(_arguments(pool, tmp_path / "first.json", directory, "--resume")) == 1
    assert json.loads((tmp_path / "first.json").read_text(encoding="utf-8")) == first


def test_a_conditional_run_carries_the_development_contract_and_its_sampler(
    tmp_path: Path,
) -> None:
    pool = _pool_csv(tmp_path, "gw01")
    directory = tmp_path / "run"

    assert (
        probe.main(_arguments(pool, tmp_path / "out.json", directory, *CONDITIONAL_ARGUMENTS)) == 0
    )

    document = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert document["contract_version"] == probe.DEVELOPMENT_PROBE_CONTRACT_VERSION
    assert document["development_only"] is True
    assert document["sampler"] == probe.sampler_record(CONDITIONAL)
    assert document["production_pin"] == [] and document["production_pin_empty"] is True
    checkpoint = json.loads(
        (directory / "checkpoints" / "2026-27-gw01.json").read_text(encoding="utf-8")
    )
    assert checkpoint["run_identity"]["sampler"] == probe.sampler_record(CONDITIONAL)
    assert checkpoint["run_identity"]["contract_version"] == (
        probe.DEVELOPMENT_PROBE_CONTRACT_VERSION
    )


def test_a_failed_pool_is_named_in_the_status_and_no_artifact_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = _pool_csv(tmp_path, "gw01")
    directory = tmp_path / "run"
    output = tmp_path / "out.json"

    def boom(*args: object, **kwargs: object) -> None:
        raise probe.ProbeError("synthetic pool failure")

    monkeypatch.setattr(probe, "probe_decision_point", boom)

    assert probe.main(_arguments(pool, output, directory)) == 1

    assert "synthetic pool failure" in capsys.readouterr().err
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["failed_labels"] == {"2026-27-gw01": "ProbeError: synthetic pool failure"}
    assert status["completed_labels"] == []
    assert not output.exists()


def test_atomic_writes_retry_the_transient_windows_sharing_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "status.json"
    checkpoints.write_json_atomic(path, {"value": 1})
    calls = {"count": 0}
    original = os.replace

    def flaky(source: object, target: object) -> None:
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("sharing violation")
        original(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(checkpoints.os, "replace", flaky)
    monkeypatch.setattr(checkpoints, "REPLACE_PAUSE_SECONDS", 0.0)

    checkpoints.write_json_atomic(path, {"value": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 2}
    assert calls["count"] == 3
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_checkpoint_of_another_identity_is_refused_before_any_work(tmp_path: Path) -> None:
    identity = {"contract_version": "x", "repository_commit": "a" * 40}
    store = checkpoints.CheckpointStore(tmp_path / "run", identity)
    store.save(
        "2026-27-gw01",
        kind="live",
        completed_counts=[4],
        record={"label": "2026-27-gw01", "runs": [], "warnings": []},
    )
    other = checkpoints.CheckpointStore(
        tmp_path / "run", {**identity, "repository_commit": "b" * 40}
    )

    with pytest.raises(checkpoints.CheckpointError):
        other.refuse_foreign_work()
    with pytest.raises(checkpoints.CheckpointError):
        other.load("2026-27-gw01")
    loaded = store.load("2026-27-gw01")
    assert loaded is not None and loaded["completed_counts"] == [4]
    assert store.load("2026-27-gw02") is None


def _without_timings(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_timings(item) for key, item in value.items() if "_seconds" not in str(key)
        }
    if isinstance(value, list):
        return [_without_timings(item) for item in value]
    return value


@pytest.mark.slow
def test_worker_processes_probe_pools_exactly_like_one_process(tmp_path: Path) -> None:
    pools = {name: _pool_csv(tmp_path, name) for name in ("2026-27-gw01", "2026-27-gw02")}

    def run(output: Path, directory: Path, workers: int) -> int:
        return probe.main(
            [
                *(
                    part
                    for label, path in pools.items()
                    for part in ("--live-pool", f"{label}={path}")
                ),
                "--candidate-counts",
                "4",
                "--skip-scoring",
                "--workers",
                str(workers),
                "--checkpoint-dir",
                str(directory),
                "--json-output",
                str(output),
            ]
        )

    assert run(tmp_path / "serial.json", tmp_path / "serial", 1) == 0
    assert run(tmp_path / "parallel.json", tmp_path / "parallel", 2) == 0

    serial = json.loads((tmp_path / "serial.json").read_text(encoding="utf-8"))
    parallel = json.loads((tmp_path / "parallel.json").read_text(encoding="utf-8"))
    assert parallel["execution"]["workers"] == 2
    assert parallel["execution"]["timing_context"] == "concurrent_local_execution"
    assert parallel["execution"]["blas_threads"]["OPENBLAS_NUM_THREADS"] == "1"
    assert [point["label"] for point in parallel["decision_points"]] == list(pools)
    assert _without_timings(parallel["decision_points"]) == _without_timings(
        serial["decision_points"]
    )
    status = json.loads((tmp_path / "parallel" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed" and status["workers"] == 2
    assert sorted(status["completed_labels"]) == sorted(pools)
