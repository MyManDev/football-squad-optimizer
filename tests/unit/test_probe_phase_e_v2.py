"""C v2 E2 plumbing on synthetic data: population, provenance, and isolated checkpoints."""

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts import _phase_e_development as development
from scripts import probe_phase_e_runtime as probe
from scripts import run_component_squad_calibration as binding
from scripts._phase_e_checkpoints import CheckpointError, CheckpointStore
from tests.unit.test_phase_d_v2_development_path import (
    MANIFEST,
    ROSTER,
    TABLE,
    _component_rows,
    _frozen_decision,
    _handoff,
)
from tests.unit.test_probe_phase_e_runtime import _fast_scorer, _point, _run

from squadopt.evaluation import DEVELOPMENT_OOF_CONTRACT_VERSION
from squadopt.optimization import SolverStatus, generate_squad_candidates
from squadopt.prediction.components import DIRECT_CONTROL_ROUTE
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import ConditionalResidualConfig

CONDITIONAL = ConditionalResidualConfig(fraction=0.15, minimum_rows=30)
FOLDS = tuple(f"2025-26-gw{week:02d}" for week in range(2, 12))


def _arguments(tmp_path: Path) -> list[str]:
    return [
        "--phase-c-contract",
        "development_v2",
        "--table",
        "table.csv",
        "--roster",
        "roster.csv",
        "--manifest",
        "manifest.json",
        "--expected-table-sha256",
        TABLE,
        "--expected-roster-sha256",
        ROSTER,
        "--expected-manifest-sha256",
        MANIFEST,
        "--sampler",
        "conditional",
        "--conditional-residual-fraction",
        "0.15",
        "--conditional-residual-minimum-rows",
        "30",
        "--all-development-folds",
        "--json-output",
        str(tmp_path / "probe.json"),
    ]


def test_v2_cli_requires_explicit_reference_pins_and_sampler(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    parsed = probe._parse_arguments(arguments)
    probe._validate(parsed)
    assert binding._development_from_arguments(parsed).table_sha256 == TABLE
    for flag in (
        "--expected-table-sha256",
        "--expected-roster-sha256",
        "--expected-manifest-sha256",
    ):
        missing = list(arguments)
        index = missing.index(flag)
        del missing[index : index + 2]
        assert probe.main(missing) == 1
    for changes in (
        {"sampler": "foundation"},
        {"live_components": True},
        {"binding": Path("binding.json")},
        {"phase_c_contract": "v1"},
        {"all_binding_folds": True},
    ):
        with pytest.raises(probe.ProbeError):
            probe._validate(SimpleNamespace(**{**vars(parsed), **changes}))
    assert not (tmp_path / "probe.json").exists()


@pytest.mark.parametrize("drift", ["table_sha256", "roster_sha256", "manifest_sha256", "weighting"])
def test_v2_cli_refuses_a_different_export_before_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    handoff = _handoff(_component_rows(FOLDS), development=True)
    changed = replace(handoff, **{drift: "weighted" if drift == "weighting" else "e" * 64})
    monkeypatch.setattr(binding, "read_phase_c_component_handoff", lambda *args, **kw: changed)
    monkeypatch.setattr(
        probe,
        "prepare_development_population",
        lambda *args, **kw: pytest.fail("a mismatched export reached preparation"),
    )
    assert probe.main(_arguments(tmp_path)) == 1
    assert not (tmp_path / "probe.json").exists()


def test_population_reads_only_prior_outcomes_and_applies_direct_control_abstention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _component_rows(FOLDS)
    # This fold selects the entire synthetic squad, including one direct-control player.
    rows.loc[rows["fold_id"].eq(FOLDS[-2]) & rows["player_id"].eq(1), "composition_route"] = (
        DIRECT_CONTROL_ROUTE
    )
    handoff = _handoff(rows, development=True)
    prepared, result = _frozen_decision(FOLDS[-1])
    original_population = binding._development_population
    calls: list[tuple[str, ...]] = []

    def history_only(frame, ids, *, min_history_folds):
        assert (frame["fold_id"] < ids[0]).all()
        return original_population(frame, ids, min_history_folds=min_history_folds)

    def projections(handoff, ids, root):
        calls.append(tuple(ids))
        return {fold: prepared.projections for fold in ids}, 123

    monkeypatch.setattr(binding, "_development_population", history_only)
    monkeypatch.setattr(probe, "prepare_fold_projections", projections)
    monkeypatch.setattr(probe, "optimize_squad", lambda *args: result)
    pools, count, population = probe.prepare_development_population(
        handoff, tmp_path, requested=None
    )
    assert count == 123
    assert population["history_burn_in_fold_ids"] == list(FOLDS[:8])
    assert population["history_eligible_fold_ids"] == list(FOLDS[8:])
    assert population["direct_control_abstentions"] == [FOLDS[-2]]
    assert population["eligible_fold_ids"] == list(pools) == [FOLDS[-1]]
    assert population["eligibility_complete"] is True

    # A pilot performs only its requested solve, and cannot claim a complete population.
    _, _, pilot = probe.prepare_development_population(handoff, tmp_path, requested=[FOLDS[-1]])
    assert calls == [FOLDS[8:], (FOLDS[-1],)]
    assert pilot["eligibility_complete"] is False
    with pytest.raises(probe.ProbeError, match="unknown or history-ineligible"):
        probe.prepare_development_population(handoff, tmp_path, requested=[FOLDS[0]])
    monkeypatch.setattr(
        probe,
        "optimize_squad",
        lambda *args: replace(result, solver_status=SolverStatus.INFEASIBLE),
    )
    with pytest.raises(probe.ProbeError, match="population is unresolved"):
        probe.prepare_development_population(handoff, tmp_path, requested=[FOLDS[-1]])


def test_v2_projection_masks_target_outcomes_and_loads_the_declared_seasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fold = FOLDS[-1]
    prepared, _ = _frozen_decision(fold)
    pool = prepared.projections
    rows = _component_rows((fold,)).assign(control_expected_points=2.0)
    roster = pool.drop(columns="expected_points").assign(fold_id=fold)
    handoff = replace(_handoff(rows, development=True), roster=roster)
    panel = pd.concat(
        [
            pool.assign(season="2025-26", gameweek=10, total_points=3.0, minutes=90.0),
            pool.assign(season="2025-26", gameweek=11, total_points=99.0, minutes=1.0),
        ]
    )
    decision = SimpleNamespace(fold_id=fold, season="2025-26", gameweek=11)
    loaded: list[tuple[str, ...]] = []

    def build(root, *, seasons):
        loaded.append(seasons)
        return panel

    def builder(visible, point):
        assert visible.loc[visible.gameweek.eq(11), ["total_points", "minutes"]].isna().all().all()
        assert visible.loc[visible.gameweek.eq(10), "total_points"].eq(3).all()
        return pool.loc[:, ["player_id", "expected_points"]]

    monkeypatch.setattr(probe, "build_panel", build)
    monkeypatch.setattr(probe, "walk_forward_decision_points", lambda *args, **kw: [decision])
    monkeypatch.setattr(probe, "rows_through", lambda frame, point: frame)
    monkeypatch.setattr(probe, "make_ridge_projection_builder", lambda **kw: builder)
    projections, _ = probe.prepare_fold_projections(handoff, [fold], tmp_path)
    assert loaded == [(binding.DEVELOPMENT_HISTORY_SEASONS[0], "2025-26")]
    assert set(projections[fold].columns) == set(probe.POOL_COLUMNS)
    assert panel["total_points"].notna().all()


def test_v2_draw_keeps_provenance_and_scores_only_the_explicit_development_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _handoff(_component_rows(FOLDS), development=True)
    prepared, _ = _frozen_decision(FOLDS[-1])
    point = probe._fold_point(
        handoff, FOLDS[-1], prepared.projections, conditional_residuals=CONDITIONAL
    )
    assert point.development_only and point.draw_factory is not None
    draw = point.draw_factory(0)
    assert draw.inputs.provenance.development_contract == DEVELOPMENT_OOF_CONTRACT_VERSION
    assert probe._draw_identity(draw)["development_contract"] == DEVELOPMENT_OOF_CONTRACT_VERSION
    assert draw.scenarios.config == ScenarioConfig()
    assert all(fold < FOLDS[-1] for fold in draw.scenarios.source_fold_ids)
    batch = generate_squad_candidates(prepared.projections, candidate_count=4)
    pin = ((handoff.model_version, CONDITIONAL.contract_version),)
    assert probe._select(batch, draw, pin)["status"] == "FALLBACK_PHASE_D_NOT_CALIBRATED"
    monkeypatch.setattr(probe, "score_component_scenario_decision", _fast_scorer)
    monkeypatch.setattr(development, "score_component_scenario_decision", _fast_scorer)
    record = probe._probe_scoring(point, batch, sensitivity_seeds=(1,), warnings=[])
    assert record["selector_production"]["candidate_count_scored"] == 0
    assert record["selector_probe_pin"]["status"] == "SELECTED"
    assert record["selector_probe_pin"]["candidate_count_scored"] == 4
    assert record["draw_repeat_identical"] and record["selection_repeat_identical"]


def test_v2_k_uses_the_exact_computed_population_and_keeps_live_diagnostics() -> None:
    eligible = FOLDS[8:]
    counts = (4, 8, 16)
    points = [
        _point(label, "live", [_run(k, scored=False) for k in counts])
        for label in probe.E2_LIVE_LABELS
    ]
    points += [_point(fold, "fold", [_run(k) for k in counts]) for fold in eligible]
    assert (
        probe.candidate_count_rule(points, counts, expected_fold_ids=eligible)["frozen_k"] is None
    )
    complete = probe.candidate_count_rule(
        points, counts, expected_fold_ids=eligible, phase_c_contract="development_v2"
    )
    assert complete["frozen_k"] == 16 and complete["expected_fold_count"] == 2
    for incomplete in (points[:-1], [*points, points[-1]], points[1:]):
        assert (
            probe.candidate_count_rule(
                incomplete, counts, expected_fold_ids=eligible, phase_c_contract="development_v2"
            )["frozen_k"]
            is None
        )
    points[-1]["runs"] = [_run(4, within=False), _run(8), _run(16)]
    assert (
        probe.candidate_count_rule(
            points, counts, expected_fold_ids=eligible, phase_c_contract="development_v2"
        )["frozen_k"]
        is None
    )


def test_v2_artifact_and_checkpoints_bind_reference_population_and_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = _handoff(_component_rows(FOLDS), development=True)
    prepared, result = _frozen_decision(FOLDS[-1])
    monkeypatch.setattr(binding, "read_phase_c_component_handoff", lambda *args, **kw: handoff)
    monkeypatch.setattr(
        probe,
        "prepare_fold_projections",
        lambda handoff, ids, root: ({fold: prepared.projections for fold in ids}, 0),
    )
    monkeypatch.setattr(probe, "optimize_squad", lambda *args: result)
    monkeypatch.setattr(
        probe,
        "_probe_label",
        lambda label: {"label": label, "kind": "fold", "pool_size": 15, "runs": [], "warnings": []},
    )
    argv = _arguments(tmp_path)
    assert probe.main(argv) == 0
    document = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert document["contract_version"] == probe.DEVELOPMENT_V2_PROBE_CONTRACT_VERSION
    assert document["binding"] is False and document["development_only"] is True
    assert document["reads_realized_outcomes"] is False and document["promotes_anything"] is False
    assert document["source"]["development_contract"] == DEVELOPMENT_OOF_CONTRACT_VERSION
    assert (
        document["measured_fold_ids"]
        == document["population"]["eligible_fold_ids"]
        == list(FOLDS[8:])
    )
    assert document["frozen_k"] is None
    arguments = probe._parse_arguments(argv)
    identity = probe._run_identity(
        arguments,
        CONDITIONAL,
        document["source"],
        document["provenance"],
        population=document["population"],
        measured_fold_ids=document["measured_fold_ids"],
    )
    store = CheckpointStore(tmp_path / "checkpoints", identity)
    store.save(FOLDS[-1], kind="fold", completed_counts=[4], record={})
    for field, value in (
        ("contract_version", probe.DEVELOPMENT_PROBE_CONTRACT_VERSION),
        ("source", {**document["source"], "table_sha256": "e" * 64}),
        ("population", {**document["population"], "eligible_fold_ids": [FOLDS[-1]]}),
        ("measured_fold_ids", [FOLDS[-1]]),
        ("execution", {**identity["execution"], "workers": 8}),
    ):
        changed = copy.deepcopy(identity)
        changed[field] = value
        with pytest.raises(CheckpointError, match="different probe run identity"):
            CheckpointStore(store.directory, changed).refuse_foreign_work()
