"""The preregistration refuses missing evidence, hidden archive reads and claimed scores."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from scripts import measure_guarded_lookahead as study


def pair(delta=0, valid=True):
    return {
        "arms": {
            "control": {"valid": True, "weighted_net_points": 100},
            "candidate": {"valid": valid, "weighted_net_points": 100 + delta},
        }
    }


def test_budget_includes_both_constructions_two_certifications_and_hold():
    assert study.budgets() == (280, 280)
    assert len(study.case_list()) == 16
    assert study.case_list()[:4] == [
        (1000, 3, 0, "plain"),
        (1000, 5, 0, "plain"),
        (900, 3, 0, "plain"),
        (900, 5, 0, "plain"),
    ]
    assert len(set(study.case_list())) == 16


@pytest.mark.parametrize(
    "records,passed",
    [
        ([pair(0.2), pair(), pair(), pair()], True),
        ([pair(), pair(), pair(), pair()], False),
        ([pair(0.2), pair(-0.2), pair(), pair()], False),
        ([pair(0.2), pair(), pair()], False),
        ([pair(0.2), pair(), pair(), pair(valid=False)], False),
        ([pair(0.2), pair(), pair(), {"arms": {}}], False),
    ],
)
def test_fixed_gate_never_promotes_incomplete_or_unchanged_pairs(records, passed):
    assert study.screen(records, 4)["passed"] is passed
    assert study.screen(records, 4)["promotion"] is False


@pytest.mark.parametrize("fail", [False, True])
def test_holdout_exclusion_precedes_loading_and_hashing_and_restores_defaults(
    monkeypatch, tmp_path, fail
):
    defaults = study.history_source.ARCHIVE_SEASONS, study.producer.ARCHIVE_SEASONS

    def produce(snapshot, archive, *, gameweeks):
        assert study.history_source.ARCHIVE_SEASONS == study.ALLOWED_SEASONS
        assert study.producer.ARCHIVE_SEASONS == study.ALLOWED_SEASONS
        assert "2025-26" not in study.history_source.ARCHIVE_SEASONS
        assert gameweeks == tuple(range(6, 20))
        if fail:
            raise ValueError("Producer failed before any solver")
        return {"ok": True}

    monkeypatch.setattr(study.producer, "produce_football_forecast", produce)
    if fail:
        with pytest.raises(ValueError, match="Producer failed"):
            study.safe_produce(None, tmp_path, tuple(range(6, 20)))
    else:
        assert study.safe_produce(None, tmp_path, tuple(range(6, 20))) == {"ok": True}
    assert defaults == (study.history_source.ARCHIVE_SEASONS, study.producer.ARCHIVE_SEASONS)


def test_wall_or_early_stop_does_not_masquerade_as_equal_deterministic_budget():
    assert study.phase_fair({}, "OPTIMAL")
    assert not study.phase_fair({}, "FEASIBLE")
    assert not study.phase_fair({"primary_search_status": "UNKNOWN"}, "FEASIBLE")
    assert study.phase_fair({"deterministic_time_budget_exhausted": True}, "FEASIBLE")
    assert not study.phase_fair(
        {"tiebreak_attempted": True, "tiebreak_completed": False}, "OPTIMAL"
    )


def test_select_current_certified_objective_not_claimed_raw_or_submitted_value():
    a = SimpleNamespace(objective_value=1e9, diagnostics={"scaled_model_objective_value": 10})
    b = SimpleNamespace(objective_value=-1e9, diagnostics={"scaled_model_objective_value": 11})
    assert study.chosen_seed([a, b]) == 1
    b.diagnostics["scaled_model_objective_value"] = 10
    assert study.chosen_seed([a, b]) == 0


def test_selected_real_certified_seed_is_rescored_and_reusable(known_optimum_players, small_config):
    from tests.unit.test_planner_incumbent import problem

    from squadopt.planning import TransferPlanningConfig, optimize_transfer_plan
    from squadopt.planning.segmented import plan_in_segments

    horizon, state, config = problem(known_optimum_players, small_config, 5)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    seeds = [
        plan_in_segments(horizon, state, config, segment_lengths=lengths, transfer=settings)
        for lengths in ((1,) * 5, (3, 2))
    ]
    certified = [
        optimize_transfer_plan(
            horizon,
            state,
            config,
            settings,
            incumbent_plan=replace(seed, objective_value=1e9),
            protect_incumbent=True,
        )
        for seed in seeds
    ]
    selected = certified[study.chosen_seed(certified)]
    final = optimize_transfer_plan(
        horizon, state, config, settings, incumbent_plan=selected, protect_incumbent=True
    )
    assert (
        final.diagnostics["scaled_model_objective_value"]
        >= selected.diagnostics["scaled_model_objective_value"]
    )
    assert final.objective_value < 1e9


@pytest.mark.parametrize("method", study.METHODS)
def test_failed_phase_is_saved_and_does_not_trigger_replacement_or_expansion(
    monkeypatch, tmp_path, method
):
    import json
    from datetime import UTC, datetime, timedelta

    import pandas as pd

    evidence = tmp_path / "evidence.csv"
    evidence.write_text("fixed evidence", encoding="utf-8")
    states = tmp_path / "states.json"
    states.write_text(
        json.dumps({str(p): {"ids": [1], "bank": 0, "ft": 1} for p in (1000, 900)}),
        encoding="utf-8",
    )
    horizon = SimpleNamespace(
        gameweeks=tuple(range(6, 20)),
        table=pd.DataFrame(
            {"gameweek": [6], "player_id": [1], "position": ["MID"], "expected_points": [5]}
        ),
    )
    monkeypatch.setattr(study, "CUTOFF", datetime.now(UTC) + timedelta(days=1))
    monkeypatch.setattr(study, "prepare", lambda *a: (None, None, SimpleNamespace(projection=None)))
    monkeypatch.setattr(study, "top100_manifest_path", lambda p: evidence)
    monkeypatch.setattr(study, "load_top100_counts", lambda *a, **kw: SimpleNamespace(counts={}))
    monkeypatch.setattr(study, "to_planning_horizon", lambda *a: horizon)
    monkeypatch.setattr(study, "weighted_horizon", lambda *a: None)

    def fail(*a, **kw):
        raise ValueError("Controlled early failure")

    def segment(*a, **kw):
        return study.segmented.optimize_transfer_plan(*a)

    monkeypatch.setattr(study.segmented, "plan_in_segments", segment)
    monkeypatch.setattr(study, "optimize_transfer_plan", fail)
    output = tmp_path / "study"
    monkeypatch.setattr(study, "validate_reference", lambda *a: None)
    study.run(
        tmp_path,
        tmp_path,
        "capture",
        tmp_path,
        evidence,
        states,
        output,
        method=method,
        reference_study=tmp_path,
    )
    records = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(records) == 4
    for record in records:
        assert set(record["arms"]) == {"control", "candidate"}
        for arm in record["arms"].values():
            assert arm["valid"] is False
            assert len(arm["phases"]) == 1
            assert arm["phases"][0]["actual_det"] is None
            assert arm["phases"][0]["error"] == "Controlled early failure"
    assert (
        json.loads((output / "summary.json").read_text(encoding="utf-8"))["core"]["passed"] is False
    )


@pytest.mark.parametrize(
    "status,used,valid",
    [
        ("UNKNOWN", 0.1, False),
        ("FEASIBLE", 0.1, False),
        ("FEASIBLE", 1, True),
        ("UNKNOWN", 1, True),
        ("OPTIMAL", 0.1, True),
        ("INFEASIBLE", 0.1, True),
    ],
)
def test_control_hold_probe_early_stop_is_part_of_fairness(status, used, valid):
    diagnostics = {
        "hold_protection": {
            "status": status,
            "deterministic_time": used,
            "deterministic_time_limit": 1,
        }
    }
    assert study.phase_fair(diagnostics, "OPTIMAL") is valid


@pytest.mark.parametrize("method", study.METHODS)
def test_method_budget_and_unknown_method_refusal(method):
    assert study.budgets(method) == (280, 280)
    with pytest.raises(ValueError, match="Unknown"):
        study.budgets("unregistered")


@pytest.mark.parametrize(
    "method,fault",
    [
        ("two_seed_v1", None),
        ("single_seed_v1", None),
        ("single_seed_v1", "corrupt_seed"),
        ("single_seed_v1", "exhausted"),
    ],
)
def test_registered_method_calls_use_same_state_and_only_their_declared_phases(
    known_optimum_players, small_config, monkeypatch, tmp_path, method, fault
):
    import json
    from datetime import UTC, datetime, timedelta

    from tests.unit.test_planner_incumbent import problem

    from squadopt.planning import PlanningHorizon

    horizon, initial, _ = problem(known_optimum_players, small_config, 14)
    ids = {player: index + 1 for index, player in enumerate(horizon.table.player_id.unique())}
    horizon = PlanningHorizon(horizon.table.assign(player_id=horizon.table.player_id.map(ids)))
    states = tmp_path / "states.json"
    states.write_text(
        json.dumps(
            {
                str(profile): {
                    "ids": [ids[p] for p in initial.squad_player_ids],
                    "bank": 0,
                    "ft": 1,
                }
                for profile in (1000, 900)
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.csv"
    evidence.write_text("fixed", encoding="utf-8")
    monkeypatch.setattr(study, "CUTOFF", datetime.now(UTC) + timedelta(days=1))
    monkeypatch.setattr(study, "prepare", lambda *a: (None, None, SimpleNamespace(projection=None)))
    monkeypatch.setattr(study, "top100_manifest_path", lambda p: evidence)
    monkeypatch.setattr(study, "load_top100_counts", lambda *a, **kw: SimpleNamespace(counts={}))
    monkeypatch.setattr(study, "weighted_horizon", lambda *a: None)
    monkeypatch.setattr(study, "to_planning_horizon", lambda *a: horizon)
    monkeypatch.setattr(study, "OptimizationConfig", lambda **kw: replace(small_config, **kw))
    if fault == "corrupt_seed":
        build = study.segmented.plan_in_segments

        def corrupt(*a, **kw):
            return replace(build(*a, **kw), horizon_fingerprint="0" * 64)

        monkeypatch.setattr(study.segmented, "plan_in_segments", corrupt)
    if fault == "exhausted":
        import squadopt.planning.optimizer as core

        real_solve = study.optimize_transfer_plan
        real_used = core._deterministic_time_used

        def solve(*a, **kw):
            if not kw.get("protect_incumbent"):
                return real_solve(*a, **kw)
            calls = 0

            def used(solver, status):
                nonlocal calls
                calls += 1
                return 253.0 if calls == 1 else real_used(solver, status)

            with monkeypatch.context() as scoped:
                scoped.setattr(core, "_deterministic_time_used", used)
                return real_solve(*a, **kw)

        monkeypatch.setattr(study, "optimize_transfer_plan", solve)
    references = []
    monkeypatch.setattr(study, "validate_reference", lambda *a: references.append(a))
    output = tmp_path / "study"
    study.run(
        tmp_path,
        tmp_path,
        "capture",
        tmp_path,
        evidence,
        states,
        output,
        method=method,
        reference_study=tmp_path,
    )
    records = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(records) == 4  # Exact optimum in both arms: no gain, no expansion.
    assert bool(references) == (method == "single_seed_v1")
    for record in records:
        control, candidate = (record["arms"][arm] for arm in ("control", "candidate"))
        assert control["valid"]
        if fault == "corrupt_seed":
            assert not candidate["valid"]
            assert candidate["error_type"] == "TransferPlanningValidationError"
            assert candidate["stage"] == "final"
            assert candidate["recorded_det"] > 0
            assert candidate["actual_det"] is None
            assert not candidate["cost_complete"]
            continue
        assert candidate["valid"]
        assert candidate["weighted_net_points"] == pytest.approx(control["weighted_net_points"])
        if fault == "exhausted":
            assert candidate["diagnostics"]["primary_search_status"] == "UNKNOWN"
            assert candidate["diagnostics"]["incumbent_protection"]["selected"]
            assert candidate["diagnostics"]["best_objective_bound"] is None
        phases = candidate["phases"]
        assert sum(p["configured_det"] for p in phases) == 280
        assert len(phases) == (15 if method == "single_seed_v1" else 19)
        assert all("hold_protection" not in p["diagnostics"] for p in phases)
        assert phases[-1]["diagnostics"]["incumbent_protection"]["claimed_objective_used"] is False
        assert candidate["actual_det"] == pytest.approx(sum(p["actual_det"] for p in phases))
        assert candidate["cost_complete"]
        if method == "single_seed_v1":
            assert [p["stage"] for p in phases] == ["sequential"] * 14 + ["final"]
            assert phases[-1]["configured_det"] == 252
    assert json.loads((output / "protocol.json").read_text())["method"] == method


@pytest.mark.parametrize("separator", ["/", "\\"])
@pytest.mark.parametrize("changed", [None, "states", "core", "forecast", "capture"])
def test_reference_gate_refuses_changed_inputs_before_comparison(tmp_path, changed, separator):
    import json

    old, new = tmp_path / "old", tmp_path / "new"
    for folder in (old, new):
        folder.mkdir()
        study.write_json(
            folder / "protocol.json",
            {
                "states_sha256": "states",
                "top100_sha256": "top",
                "top100_manifest_sha256": "manifest",
                "allowed_archive_seasons": ["allowed"],
                "source_sha256": {
                    "src/squadopt/planning/optimizer.py": "core",
                    separator.join(("scripts", "measure_guarded_lookahead.py")): folder.name,
                },
            },
        )
        for name in ("forecast14.json", "forecast5.json"):
            study.write_json(
                folder / name,
                {
                    "fingerprint": name,
                    "source_snapshot_id": "capture",
                    "archive_hashes": {"ok": "hash"},
                },
            )
        study.write_json(
            folder / "forecast-provenance.json",
            {
                "source_fingerprint": "source",
                "source_snapshot_id": "capture",
                "archive_hashes": {"ok": "hash"},
            },
        )
        study.write_json(folder / "results.json", [])
    if changed:
        filename = (
            "protocol.json"
            if changed in ("states", "core")
            else ("forecast14.json" if changed == "forecast" else "forecast-provenance.json")
        )
        path = new / filename
        data = json.loads(path.read_text())
        if changed == "states":
            data["states_sha256"] = "different"
        elif changed == "core":
            data["source_sha256"]["src/squadopt/planning/optimizer.py"] = "different"
        elif changed == "forecast":
            data["fingerprint"] = "different"
        else:
            data["source_fingerprint"] = "different"
        study.write_json(path, data)
        with pytest.raises(ValueError, match="Reference"):
            study.validate_reference(new, old)
        assert not (new / "reference-check.json").exists()
    else:
        study.validate_reference(new, old)
        assert json.loads((new / "reference-check.json").read_text())["reused_development_data"]


def test_single_seed_requires_reference_before_any_preparation(tmp_path, monkeypatch):
    def forbidden(*a):
        pytest.fail("No fitting or solving before reference requirement.")

    monkeypatch.setattr(study, "prepare", forbidden)
    with pytest.raises(ValueError, match="reference"):
        study.run(
            tmp_path,
            tmp_path,
            "capture",
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path / "output",
            method="single_seed_v1",
        )
    assert not (tmp_path / "output").exists()
