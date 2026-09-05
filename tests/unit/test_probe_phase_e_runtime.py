"""The E2 runtime probe: one shared draw, honest pins, and nothing frozen from a partial set.

Every input is synthetic. The official scorer is replaced by a cheap starting-eleven sum in the
scoring tests so that a 1000-scenario selection costs milliseconds; the probe's plumbing,
labels and rule are what these tests pin, not the scorer, which has its own tests.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scripts import probe_phase_e_runtime as probe
from tests.fixtures.synthetic_players import make_baseline_players
from tests.unit.test_run_component_squad_calibration import _handoff

from squadopt.optimization import (
    OptimizationConfig,
    OptimizationResult,
    decision_signature,
    generate_squad_candidates,
)
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import selection
from squadopt.scenarios.components import (
    ComponentScenarioDraw,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    _component_fingerprint,
)
from squadopt.scenarios.models import (
    ScenarioConfig,
    ScenarioSet,
    ScenarioTarget,
    _scenario_fingerprint,
)

TARGET = ScenarioTarget(season="2026-27", gameweek=3)
MODEL = "synthetic-component-model"
FEATURES = "synthetic-v1"
LIVE = probe.E2_LIVE_LABELS


def _draw_factory(
    pool: pd.DataFrame, *, omit: tuple[int, ...] = ()
) -> Callable[[int], ComponentScenarioDraw]:
    """Seed -> a 1000-scenario draw over the pool minus ``omit``, noise from the seed."""

    kept = pool.loc[~pool["player_id"].isin(omit)].sort_values("player_id").reset_index(drop=True)
    snapshot = prepare_optimizer_projection(
        kept.drop(columns="expected_points"),
        kept.loc[:, ["player_id", "expected_points"]],
        PredictionProvenance(
            model_name=MODEL,
            model_version=MODEL,
            feature_contract_version=FEATURES,
            training_cutoff="2026-27:GW02",
            training_data_fingerprint="a" * 64,
        ),
    )
    ordered = snapshot.table.reset_index(drop=True)
    ids = ordered["player_id"].tolist()

    def factory(seed: int) -> ComponentScenarioDraw:
        config = ScenarioConfig(deterministic_seed=seed)
        scenario_ids = tuple(f"scenario-{index:06d}" for index in range(config.scenario_count))
        sources = tuple(
            "2026-27-gw01" if index % 2 == 0 else "2026-27-gw02"
            for index in range(len(scenario_ids))
        )
        rng = np.random.default_rng(seed)
        base = ordered["expected_points"].to_numpy(dtype="float64")
        points = pd.DataFrame(
            base + rng.normal(0.0, 2.0, size=(len(scenario_ids), len(ids))),
            index=pd.Index(scenario_ids, name="scenario_id"),
            columns=ids,
        )
        appearances = pd.DataFrame(True, index=points.index, columns=points.columns, dtype="bool")
        minutes = appearances.astype("float64") * 60.0
        scenarios = ScenarioSet(
            projections=snapshot,
            target=TARGET,
            config=config,
            scenario_ids=scenario_ids,
            source_fold_ids=sources,
            scenario_points=points,
            scenario_fingerprint=_scenario_fingerprint(
                snapshot, TARGET, config, scenario_ids, sources, points
            ),
            diagnostics={},
        )
        inputs = ComponentScenarioInputs(
            table=pd.DataFrame(
                {
                    "player_id": ids,
                    "team_id": ordered["team_id"].tolist(),
                    "position": ordered["position"].tolist(),
                    "fixture_count": [1] * len(ids),
                    "appearance_probability": [1.0] * len(ids),
                    "expected_minutes_if_appearance": [60.0] * len(ids),
                    "raw_expected_points_if_appearance": base.tolist(),
                    "composition_route": ["component_model"] * len(ids),
                    "evidence_status": ["not_requested"] * len(ids),
                }
            ),
            provenance=ComponentScenarioProvenance(
                phase_c_table_sha="a" * 64,
                roster_sha="b" * 64,
                model_version=MODEL,
                feature_contract_version=FEATURES,
                target_contract_version="synthetic-target-v1",
                dataset_contract_version="synthetic-dataset-v1",
                season=TARGET.season,
                target_gameweek=TARGET.gameweek,
                deterministic_seed=seed,
            ),
        )
        return ComponentScenarioDraw(
            scenarios=scenarios,
            inputs=inputs,
            sampled_minutes=minutes,
            sampled_appearances=appearances,
            component_fingerprint=_component_fingerprint(scenarios, inputs, minutes, appearances),
        )

    return factory


def _fast_scorer(result: OptimizationResult, draw: ComponentScenarioDraw) -> SimpleNamespace:
    """Starting eleven plus captain, per scenario: cheap, deterministic, seed-sensitive."""

    assert result.captain is not None
    eleven = result.starting_xi["player_id"].tolist()
    points = draw.scenarios.scenario_points
    totals = points.loc[:, eleven].sum(axis=1) + points.loc[:, result.captain["player_id"]]
    return SimpleNamespace(total_points=tuple(float(value) for value in totals))


@pytest.fixture
def fast_scorer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selection, "score_component_scenario_decision", _fast_scorer)
    monkeypatch.setattr(probe, "score_component_scenario_decision", _fast_scorer)


def test_a_pool_without_a_draw_records_generation_and_diversity_only() -> None:
    point = probe.DecisionPoint(
        label="2026-27-gw01",
        kind="live",
        pool=make_baseline_players(),
        draw_unavailable_reason=probe.LIVE_DRAW_UNAVAILABLE,
    )

    record = probe.probe_decision_point(point, candidate_counts=(4,), sensitivity_seeds=())

    assert record["draw_available"] is False
    (run,) = record["runs"]
    assert run["candidate_count"] == 4
    assert run["candidates_found"] == 4
    assert run["complete"] is True and run["all_optimal"] is True
    assert run["termination_status"] == "OPTIMAL"
    assert run["generation_repeat_identical"] is True
    assert run["generation_seconds"] > 0
    assert run["diversity"]["distinct_signatures"] == 4
    assert run["diversity"]["delta_k"] >= 0
    assert run["candidates"][0]["deterministic_gap"] == 0.0
    assert run["candidates"][0]["bench_only_difference"] is False
    assert run["scoring"] is None
    assert run["scoring_unavailable_reason"] == probe.LIVE_DRAW_UNAVAILABLE
    assert run["within_budget"] is None and run["budget_seconds"] is None


def test_scoring_uses_one_shared_draw_and_labels_both_pins(fast_scorer: None) -> None:
    pool = make_baseline_players()
    point = probe.DecisionPoint(
        label="2024-25-gw38",
        kind="fold",
        pool=pool,
        draw_factory=_draw_factory(pool),
        covered_player_ids=frozenset(int(value) for value in pool["player_id"]),
    )

    record = probe.probe_decision_point(point, candidate_counts=(4,), sensitivity_seeds=(1, 2))

    (run,) = record["runs"]
    scoring = run["scoring"]
    assert scoring["candidates_covered"] == 4 and scoring["candidates_eliminated"] == 0
    assert scoring["control_covered"] is True
    assert scoring["draw"]["scenario_count"] == 1000
    assert scoring["scoring_seconds_total"] > 0
    assert all("utility_int" in entry for entry in scoring["candidates"])
    production = scoring["selector_production"]
    assert production["status"] == "FALLBACK_PHASE_D_NOT_CALIBRATED"
    assert production["pin"] == [] and production["candidate_count_scored"] == 0
    assert "not scenario scoring time" in production["note"]
    diagnostic = scoring["selector_probe_pin"]
    assert diagnostic["status"] == "SELECTED"
    assert diagnostic["pin"] == [[MODEL, "component_scenario_foundation_v1"]]
    assert diagnostic["candidate_count_scored"] == 4
    assert "not the production pin" in diagnostic["note"]
    assert scoring["draw_repeat_identical"] is True
    assert scoring["selection_repeat_identical"] is True
    sensitivity = scoring["seed_sensitivity"]
    assert sensitivity["seeds"] == [0, 1, 2]
    assert set(sensitivity["selected_rank_by_seed"]) == {"0", "1", "2"}
    assert 0 <= sensitivity["selected_rank_changes"] <= 2
    assert run["budget_seconds"] == run["generation_seconds"] + scoring["scoring_seconds_total"]
    assert run["within_budget"] is True
    assert record["warnings"] == []


def test_an_uncovered_control_disables_selection_but_still_measures(fast_scorer: None) -> None:
    pool = make_baseline_players()
    control = generate_squad_candidates(pool, candidate_count=1).control
    omitted = int(decision_signature(control)[0][0])
    covered = frozenset(int(value) for value in pool["player_id"]) - {omitted}
    point = probe.DecisionPoint(
        label="2024-25-gw37",
        kind="fold",
        pool=pool,
        draw_factory=_draw_factory(pool, omit=(omitted,)),
        covered_player_ids=covered,
    )

    record = probe.probe_decision_point(point, candidate_counts=(4,), sensitivity_seeds=())

    (run,) = record["runs"]
    assert run["coverage_before_draw"]["control_covered"] is False
    scoring = run["scoring"]
    assert scoring["control_covered"] is False
    assert scoring["candidates_eliminated"] >= 1
    assert scoring["candidates"][0] == {"rank": 0, "covered": False}
    assert scoring["selector_production"]["status"] == "FALLBACK_PHASE_D_NOT_CALIBRATED"
    assert scoring["selector_probe_pin"]["status"] == "FALLBACK_SCENARIO_COVERAGE"
    assert scoring["selector_probe_pin"]["selected_candidate_rank"] == 0
    assert run["coverage_before_draw"]["candidates_eliminated"] == scoring["candidates_eliminated"]


def test_an_unsolved_control_is_a_named_run_the_rule_can_read() -> None:
    point = probe.DecisionPoint(
        label="2026-27-gw01",
        kind="live",
        pool=make_baseline_players(),
        draw_unavailable_reason=probe.LIVE_DRAW_UNAVAILABLE,
    )

    record = probe.probe_decision_point(
        point, candidate_counts=(4,), config=OptimizationConfig(budget_tenths=0)
    )
    rule = probe.candidate_count_rule(
        [record], (4,), expected_live_labels=("2026-27-gw01",), expected_fold_ids=()
    )

    (run,) = record["runs"]
    assert run["all_optimal"] is False and run["candidates_found"] == 1
    assert run["termination_status"] == "INFEASIBLE"
    assert run["candidates"] == [] and run["diversity"] is None
    assert run["scoring"] is None and "could not be solved" in run["scoring_unavailable_reason"]
    assert run["budget_seconds"] is None and run["within_budget"] is None
    assert run["generation_repeat_identical"] is True
    assert rule["per_candidate_count"]["4"]["all_optimal_and_complete"] is False
    assert rule["per_candidate_count"]["4"]["passes"] is None
    assert rule["frozen_k"] is None


def _run(
    count: int, *, optimal: bool = True, scored: bool = True, within: bool = True
) -> dict[str, object]:
    scoring = (
        {"draw_repeat_identical": True, "selection_repeat_identical": True} if scored else None
    )
    return {
        "candidate_count": count,
        "all_optimal": optimal,
        "generation_repeat_identical": True,
        "scoring": scoring,
        "within_budget": (within if scored else None),
    }


def _point(label: str, kind: str, runs: list[dict[str, object]]) -> dict[str, object]:
    return {"label": label, "kind": kind, "runs": runs}


def _full_set(**overrides: list[dict[str, object]]) -> list[dict[str, object]]:
    default = [_run(4), _run(8), _run(16)]
    points = [
        _point(label, "live", overrides.get(label.replace("-", "_"), default)) for label in LIVE
    ]
    points += [_point(fold, "fold", overrides.get(fold, default)) for fold in FOLDS]
    return points


FOLDS = tuple(f"f{index}" for index in range(1, 138))


def test_original_live_diagnostics_do_not_gate_historical_k() -> None:
    points = _full_set()
    for point in points[:3]:
        point["runs"] = [_run(count, optimal=False, scored=False) for count in (4, 8, 16)]
    rule = probe.candidate_count_rule(points, (4, 8, 16), expected_fold_ids=FOLDS)
    assert rule["frozen_k"] == 16
    assert rule["per_candidate_count"]["4"]["pools"] == 137
    assert rule["gating_population"] == "binding_development_folds_only"
    assert rule["live_readiness_established"] is False

    points[3]["runs"] = [_run(count, scored=False) for count in (4, 8, 16)]
    rule = probe.candidate_count_rule(points, (4, 8, 16), expected_fold_ids=FOLDS)
    assert rule["frozen_k"] is None


def test_subset_population_cannot_be_declared_the_complete_binding_population() -> None:
    points = _full_set()[:-1]
    rule = probe.candidate_count_rule(points, (4, 8, 16), expected_fold_ids=FOLDS[:-1])
    assert rule["frozen_k"] is None


def test_the_rule_freezes_only_on_the_exact_pool_set_with_every_count() -> None:
    complete = probe.candidate_count_rule(_full_set(), (4, 8, 16), expected_fold_ids=FOLDS)
    assert complete["pool_set_complete"] is True and complete["frozen_k"] == 16

    largest_fails = probe.candidate_count_rule(
        _full_set(f2=[_run(4), _run(8), _run(16, optimal=False)]),
        (4, 8, 16),
        expected_fold_ids=FOLDS,
    )
    assert largest_fails["frozen_k"] == 8 and largest_fails["k_passing_on_probed_pools"] == 8

    # Any deviation from the exact identities or the full count set freezes nothing.
    missing_fold = probe.candidate_count_rule(_full_set()[:-1], (4, 8, 16), expected_fold_ids=FOLDS)
    assert missing_fold["frozen_k"] is None and "incomplete" in missing_fold["frozen_k_reason"]
    duplicated = probe.candidate_count_rule(
        [*_full_set(), _point("f1", "fold", [_run(4), _run(8), _run(16)])],
        (4, 8, 16),
        expected_fold_ids=FOLDS,
    )
    assert duplicated["frozen_k"] is None and duplicated["pool_set_complete"] is False
    unknown_folds = probe.candidate_count_rule(_full_set(), (4, 8, 16))
    assert unknown_folds["frozen_k"] is None and unknown_folds["expected_fold_count"] is None
    subset = probe.candidate_count_rule(
        [_point(label, "live", [_run(8)]) for label in LIVE]
        + [_point(fold, "fold", [_run(8)]) for fold in FOLDS],
        (8,),
        expected_fold_ids=FOLDS,
    )
    assert subset["frozen_k"] is None and subset["pool_set_complete"] is False
    omitted_pair = probe.candidate_count_rule(
        _full_set(f1=[_run(4), _run(16)]), (4, 8, 16), expected_fold_ids=FOLDS
    )
    assert omitted_pair["frozen_k"] is None and omitted_pair["pool_set_complete"] is False


def test_a_failed_smallest_count_disables_phase_e_and_a_partial_probe_reports_only() -> None:
    k4_fails = probe.candidate_count_rule(
        _full_set(f1=[_run(4, within=False), _run(8), _run(16)]),
        (4, 8, 16),
        expected_fold_ids=FOLDS,
    )
    assert k4_fails["per_candidate_count"]["8"]["passes"] is True
    assert k4_fails["frozen_k"] is None and "K=4 failed" in k4_fails["frozen_k_reason"]
    assert k4_fails["k_passing_on_probed_pools"] is None

    unscored = [_point("2026-27-gw01", "live", [_run(4, scored=False)])]
    rule = probe.candidate_count_rule(
        unscored, (4,), expected_live_labels=("2026-27-gw01",), expected_fold_ids=()
    )
    assert rule["per_candidate_count"]["4"]["budget"] == "not_evaluable"
    assert rule["per_candidate_count"]["4"]["passes"] is None
    assert rule["frozen_k"] is None and "incomplete" in rule["frozen_k_reason"]


def test_fold_pool_and_inputs_carry_no_targets_and_cover_component_rows_only() -> None:
    projections = make_baseline_players().head(6)
    rows = pd.DataFrame(
        {
            "fold_id": ["2024-25-gw38"] * 3 + ["2024-25-gw37"],
            "player_id": [1, 2, 3, 1],
            "fixture_count": [1, 1, 1, 1],
            "appearance_probability": [0.9, 0.8, None, 0.9],
            "expected_minutes_if_appearance": [80.0, 70.0, None, 80.0],
            "raw_expected_points_if_appearance": [5.0, 4.0, None, 5.0],
            "composition_route": [
                "component_model",
                "component_model",
                "direct_control",
                "component_model",
            ],
            "evidence_status": ["not_requested"] * 4,
            "appearance_target": [1, 0, 1, 1],
            "minutes_target": [90, 0, 90, 90],
            "points_target": [8, 0, 2, 6],
        }
    )

    pool, inputs, covered = probe.fold_pool_and_inputs(rows, projections, "2024-25-gw38")

    assert list(pool.columns) == list(probe.POOL_COLUMNS)
    assert len(pool) == 6, "direct-control players stay in the pool the solver sees"
    assert covered == frozenset({1, 2})
    assert inputs["player_id"].tolist() == [1, 2]
    assert not any(column.endswith("_target") for column in inputs.columns)
    assert {"name", "team_id", "position", "price_tenths", "expected_points"} <= set(inputs.columns)


def test_fold_projection_blanks_the_decision_outcomes_and_fills_direct_control_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    players = make_baseline_players().head(4)
    panel = pd.concat(
        [
            players.assign(season="2024-25", gameweek=37, total_points=5, minutes=90),
            players.assign(season="2024-25", gameweek=38, total_points=7, minutes=80),
        ],
        ignore_index=True,
    )
    decision = SimpleNamespace(season="2024-25", gameweek=38, fold_id="2024-25-gw38")
    monkeypatch.setattr(probe, "rows_through", lambda frame, point: frame)
    seen: dict[str, pd.DataFrame] = {}

    def builder(visible: pd.DataFrame, point: object) -> pd.DataFrame:
        seen["visible"] = visible
        current = visible.loc[visible["gameweek"] == 38]
        return current.loc[:, ["player_id"]].assign(expected_points=1.5)

    control = probe.outcome_free_control_projection(panel, decision, builder)

    visible = seen["visible"]
    assert visible.loc[visible["gameweek"] == 38, ["total_points", "minutes"]].isna().all().all()
    assert visible.loc[visible["gameweek"] == 37, "total_points"].eq(5).all()
    assert panel["total_points"].notna().all(), "the caller's panel is untouched"
    assert list(control.columns) == ["player_id", "expected_points"]

    rows = pd.DataFrame(
        {
            "fold_id": ["2024-25-gw38"] * 4,
            "player_id": [1, 2, 3, 4],
            "control_expected_points": [4.0, np.nan, 3.0, 2.0],
            "points_target": [9, 9, 9, 9],
        }
    )
    roster = players.drop(columns="expected_points").assign(fold_id="2024-25-gw38")

    projections = probe.fold_projection_roster(rows, roster, "2024-25-gw38", control)

    assert list(projections.columns) == list(probe.POOL_COLUMNS)
    assert projections.set_index("player_id")["expected_points"].to_dict() == {
        1: 4.0,
        2: 1.5,
        3: 3.0,
        4: 2.0,
    }
    with pytest.raises(probe.ProbeError):
        probe.fold_projection_roster(rows, roster, "2024-25-gw38", control.head(2))


def test_recorded_live_pool_preserves_projection_float_bits(tmp_path: Path) -> None:
    pool = make_baseline_players()
    # The default CSV parser rounds this shortest decimal spelling down by one ULP.
    pool.loc[pool.index[0], "expected_points"] = 0.30000000000000004
    path = tmp_path / "projections.csv"
    pool.to_csv(path, index=False)

    point = probe.live_point_from_csv(f"2026-27-gw01={path}")

    assert [float(value).hex() for value in point.pool["expected_points"]] == [
        float(value).hex() for value in pool["expected_points"]
    ]


def test_the_cli_writes_an_honest_artifact_for_a_recorded_pool(tmp_path: Path) -> None:
    pool_path = tmp_path / "gw01_projections.csv"
    make_baseline_players().assign(has_prior_record=True).to_csv(pool_path, index=False)
    output = tmp_path / "probe.json"

    assert (
        probe.main(
            [
                "--live-pool",
                f"2026-27-gw01={pool_path}",
                "--candidate-counts",
                "4",
                "--skip-scoring",
                "--json-output",
                str(output),
            ]
        )
        == 0
    )

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["contract_version"] == probe.PROBE_CONTRACT_VERSION
    assert document["preregistration"] == probe.PREREGISTRATION
    assert document["preregistration_version"] == probe.PREREGISTRATION_VERSION
    assert document["source"] is None
    assert document["diagnostic_only"] is True and document["promotes_anything"] is False
    assert document["reads_realized_outcomes"] is False
    assert document["outcome_policy"] == probe.OUTCOME_POLICY
    assert document["production_pin"] == [] and document["production_pin_empty"] is True
    assert document["scoring_requested"] is False
    assert document["frozen_k"] is None and "incomplete" in document["frozen_k_reason"]
    assert document["candidate_count_rule"]["per_candidate_count"]["4"]["budget"] == "not_evaluable"
    assert document["candidate_count_rule"]["expected_fold_count"] is None
    (point,) = document["decision_points"]
    assert point["kind"] == "live" and point["pool_size"] == 24
    (run,) = point["runs"]
    assert run["scoring"] is None
    assert run["scoring_unavailable_reason"] == "scoring was not requested for this run"
    assert run["candidates_found"] == 4 and run["all_optimal"] is True
    assert {"provenance", "environment"} <= set(document)
    assert "2025-26" not in document["provenance"]["history_seasons"]


def test_cli_records_the_actual_handoff_digests_without_rehashing_other_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = _handoff()
    monkeypatch.setattr(probe, "read_phase_c_component_handoff", lambda *args: handoff)
    monkeypatch.setattr(probe, "fold_decision_points", lambda *args: ([], 0))
    output = tmp_path / "probe.json"
    assert (
        probe.main(
            [
                "--all-binding-folds",
                "--table",
                "synthetic.csv",
                "--roster",
                "synthetic-roster.csv",
                "--manifest",
                "synthetic.json",
                "--json-output",
                str(output),
            ]
        )
        == 0
    )
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["source"] == {
        "table_sha256": handoff.table_sha256,
        "roster_sha256": handoff.roster_sha256,
        "manifest_sha256": handoff.manifest_sha256,
    }


def test_the_cli_refuses_counts_outside_the_selector_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool_path = tmp_path / "pool.csv"
    make_baseline_players().to_csv(pool_path, index=False)

    assert (
        probe.main(
            [
                "--live-pool",
                f"x={pool_path}",
                "--candidate-counts",
                "5",
                "--json-output",
                str(tmp_path / "out.json"),
            ]
        )
        == 1
    )

    assert "probe refused" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()


def test_a_missing_handoff_is_refused_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        probe.main(
            [
                "--live-decision",
                f"2026-27:3:missing-snapshot:{tmp_path / 'missing.json'}",
                "--snapshot-root",
                str(tmp_path),
                "--json-output",
                str(tmp_path / "out.json"),
            ]
        )
        == 1
    )

    assert "probe refused" in capsys.readouterr().err


def test_decision_points_validate_their_shape() -> None:
    pool = make_baseline_players()
    with pytest.raises(probe.ProbeError):
        probe.DecisionPoint(label="x", kind="other", pool=pool, draw_unavailable_reason="r")
    with pytest.raises(probe.ProbeError):
        probe.DecisionPoint(label="x", kind="live", pool=pool)
    with pytest.raises(probe.ProbeError):
        probe.DecisionPoint(
            label="x",
            kind="live",
            pool=pool.drop(columns="price_tenths"),
            draw_unavailable_reason="r",
        )
    assert (
        replace(
            probe.DecisionPoint(label="x", kind="live", pool=pool, draw_unavailable_reason="r"),
            label="y",
        ).label
        == "y"
    )
