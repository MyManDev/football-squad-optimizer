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


def test_failed_phase_is_saved_and_does_not_trigger_replacement_or_expansion(monkeypatch, tmp_path):
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
    study.run(tmp_path, tmp_path, "capture", tmp_path, evidence, states, output)
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
