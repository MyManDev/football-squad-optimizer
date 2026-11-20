"""Three-week repair admission retains the original rules, capture and run budget."""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as world
from tests.unit.test_api_advice_post import ADVICE_URL, _run_ref, _world

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.live.transfers import HorizonNoSolutionError
from squadopt.optimization import SolverStatus, SolverWallTimeLimit
from squadopt.platform import advice_worker
from squadopt.platform.advice_job_spec import (
    FileAdviceJobSpecStore,
    replays_witness,
    single_rule_edit,
)
from squadopt.platform.advice_runs import FileRunStore
from squadopt.platform.backend_runtime import build_backend
from squadopt.platform.jobs_contract import JobError


def _spec(preferences, chip=None):
    switches = {"preferences": {"value": DecisionPreferences.parse(preferences).canonical()}}
    if chip:
        switches["chip"] = {"chip": chip}
    return world._spec(window=3, switches=switches)


@pytest.mark.parametrize(
    ("original", "repaired"),
    [
        (
            {"club_counts": [{"club": "A", "count": 2}]},
            {"club_counts": [{"club": "A", "count": 1}]},
        ),
        ({"min_bank": {"tenths": 25, "week": 2}}, {"min_bank": {"tenths": 20, "week": 2}}),
        ({"week_rules": [{"week": 2, "rules": {"no_hits": True}}]}, {}),
        ({"max_hit_points": 4}, {"max_hit_points": 8}),
        (
            {"frozen_weeks": [{"week": 3, "transfers_in": [], "transfers_out": [], "chip": None}]},
            {},
        ),
        ({"wildcard_week": 3}, {"save_chips": True}),
    ],
)
def test_repair_changes_one_scoped_rule_and_preserves_unrelated_rules(original, repaired):
    assert single_rule_edit(_spec(original), _spec(repaired))
    assert not single_rule_edit(_spec(original), _spec({**repaired, "avoid_players": [199]}))


def test_only_the_requested_chip_can_resolve_a_known_chip_entitlement_failure():
    request = _spec({"no_hits": True}, chip="wildcard")
    assert single_rule_edit(
        request, _spec({"no_hits": True, "save_chips": True}), known_chip_conflict=True
    )
    assert not single_rule_edit(request, _spec({}, chip="wildcard"), known_chip_conflict=True)
    assert not single_rule_edit(_spec({"max_hit_points": 4}), _spec({"max_hit_points": 0}))


@pytest.mark.parametrize(
    "error",
    [
        JobError("ADVICE_FAILED", "Stopped."),
        JobError("PLAN_NOT_FOUND", "No evidence."),
        JobError("CHIP_HISTORY_UNKNOWN", "No history."),
        JobError("RUN_BUDGET_EXHAUSTED", "Exhausted."),
    ],
)
def test_repair_fails_closed_for_missing_unproved_and_exhausted_bases(tmp_path, error):
    client, _, queue = _world(
        tmp_path,
        llmopt_vnext=True,
        runs=FileRunStore(tmp_path / "runs"),
        specs=FileAdviceJobSpecStore(tmp_path / "specs"),
    )
    base = {"strategy": "saf-puan", "window": 3, "preferences": {"no_hits": True}}
    assert client.post(ADVICE_URL, json={**base, "run": _run_ref()}).status_code == 202
    job = queue.claim(at_utc="2026-08-27T12:01:00Z")
    queue.store(job.transition("failed", at_utc="2026-08-27T12:01:00Z", error=error))
    repaired = {**base, "preferences": {}, "run": _run_ref(stage="repair")}
    refusal = client.post(ADVICE_URL, json=repaired)
    assert refusal.json()["error"]["code"] == "RUN_BASE_REQUIRED"
    assert len(queue.jobs()) == 1


def test_real_worker_conflict_candidates_and_selected_replay_stay_in_one_run(tmp_path, monkeypatch):
    backend = world._deployment(tmp_path, monkeypatch, last_gameweek=5, llmopt_vnext=True)[
        "backend"
    ]
    client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
    closed = build_backend(replace(backend.config, llmopt_vnext=False))
    off = TestClient(app_for_capture(closed, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
    caps = client.get(f"/api/v1/leagues/{world.LEAGUE_ID}/capabilities").json()
    assert caps["verified_repairs"] is True
    original = {"no_hits": True, "save_chips": True, "min_bank": {"tenths": 10000}}

    def ask(stage, prefs, session=client, identifier="a" * 32):
        return session.post(
            route,
            json={
                "strategy": "saf-puan",
                "window": 3,
                "run": _run_ref(identifier, stage=stage),
                "preferences": prefs,
            },
        )

    def work():
        assert world._work(backend) == 1

    base = ask("base", original)
    assert base.status_code == 202, base.text
    work()
    refused = backend.queue.load(base.json()["job_id"])
    assert refused.error.code == "PLAN_NOT_FOUND"
    assert refused.error.infeasibility is not None
    status_url = f"/api/v1/advice-jobs/{base.json()['job_id']}"
    assert off.get(status_url).json() == client.get(status_url).json()
    candidate = {"no_hits": True, "save_chips": True}
    assert ask("followup", candidate).json()["error"]["code"] == "RUN_BASE_REQUIRED"
    assert ask("repair", {"save_chips": True}).json()["error"]["code"] == "RUN_REPAIR_INVALID"
    first = ask("repair", candidate)
    assert first.status_code == 202, first.text
    assert ask("repair", candidate, off).json() == first.json()
    assert world._work(closed) == 1
    assert off.get(f"/api/v1/advice-jobs/{first.json()['job_id']}").json()["status"] == "completed"
    witness = ask("repair", candidate)
    assert witness.status_code == 200, witness.text
    assert ask("repair", candidate, off).content == witness.content
    rows = witness.json()["payload"]["plan_weeks"]
    pins = [
        {
            "week": i,
            "chip": row["chip"],
            "transfers_in": [p["player_id"] for p in row["transfers_in"]],
            "transfers_out": [p["player_id"] for p in row["transfers_out"]],
            "starting_xi": [p["player_id"] for p in row["lineup"]["starting_xi"]],
            "captain": row["lineup"]["captain"]["player_id"],
        }
        for i, row in enumerate(rows, 1)
    ]
    wrong = {
        **pins[0],
        "captain": next(p for p in pins[0]["starting_xi"] if p != pins[0]["captain"]),
    }
    forged = ask("repair", {**candidate, "frozen_weeks": [wrong, *pins[1:]]})
    assert forged.json()["error"]["code"] == "RUN_REPAIR_INVALID"
    before = backend.runs.path.read_bytes()
    for refused in (
        ask("repair", {**candidate, "min_bank": {"tenths": 9999}}, off),
        ask("repair", {**candidate, "frozen_weeks": pins}, off),
        ask("repair", candidate, off, "c" * 32),
    ):
        assert (
            refused.status_code == 409
            and refused.json()["error"]["code"] == "LLMOPT_VNEXT_DISABLED"
        )
    assert backend.runs.path.read_bytes() == before and len(backend.queue.jobs()) == 2
    # The second candidate still cannot produce a third proposal or consume the replay slot.
    second = ask("repair", {**candidate, "min_bank": {"tenths": 9999}})
    assert second.status_code == 202, second.text
    work()
    assert (
        ask("repair", {**candidate, "min_bank": {"tenths": 9998}}).json()["error"]["code"]
        == "RUN_BUDGET_EXHAUSTED"
    )
    verify = {**candidate, "frozen_weeks": pins}
    accepted = ask("repair", verify)
    assert accepted.status_code == 202, accepted.text
    work()
    checked = ask("repair", verify)
    assert checked.status_code == 200, checked.text
    for before, after in zip(rows, checked.json()["payload"]["plan_weeks"], strict=True):
        for key in ("chip", "transfers_in", "transfers_out", "transfer_hit_points"):
            assert before[key] == after[key]
        assert before["lineup"]["captain"] == after["lineup"]["captain"]
        assert sorted(p["player_id"] for p in before["lineup"]["starting_xi"]) == sorted(
            p["player_id"] for p in after["lineup"]["starting_xi"]
        )
        assert before["expected_points"] - before["transfer_hit_points"] == (
            after["expected_points"] - after["transfer_hit_points"]
        )
    assert len(backend.queue.jobs()) == 4
    state = json.loads(backend.runs.path.read_bytes())
    run = state["runs"][_run_ref()["run_id"]]
    assert run["reserved"] == 488
    assert len(run["repair_candidates"]) == 2

    first_spec = backend.job_specs.get(backend.queue.load(first.json()["job_id"]).cache_key)
    verified_spec = backend.job_specs.get(backend.queue.load(accepted.json()["job_id"]).cache_key)
    stale = witness.json()
    stale["payload"]["source_snapshot_id"] = "older-capture"
    assert not replays_witness(first_spec, verified_spec, json.dumps(stale).encode())

    # A preflight conflict starts with a completed, possibly already cached edit.
    # Both the witnessed edit and its verified replay are hits for this new run.
    for stage, selections in [("base", candidate), ("repair", verify)]:
        hit = client.post(
            route,
            json={
                "strategy": "saf-puan",
                "window": 3,
                "preferences": selections,
                "run": _run_ref("b" * 32, stage=stage),
            },
        )
        assert hit.status_code == 200, hit.text
    assert len(backend.queue.jobs()) == 4
    assert json.loads(backend.runs.path.read_bytes())["runs"]["b" * 32]["reserved"] == 0
    assert ask("repair", verify, off, "b" * 32).content == checked.content
    assert ask("base", verify, client, "d" * 32).status_code == 200
    before = backend.runs.path.read_bytes()
    fresh = ask("repair", candidate, off, "d" * 32)
    assert fresh.status_code == 409 and fresh.json()["error"]["code"] == "LLMOPT_VNEXT_DISABLED"
    assert backend.runs.path.read_bytes() == before and len(backend.queue.jobs()) == 4
    assert client.post(f"/api/v1/llmopt/runs/{'a' * 32}/cancel", json={}).status_code == 200
    assert ask("repair", verify).json()["error"]["code"] == "RUN_CANCELLED"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SolverWallTimeLimit("Stopped at the wall limit."), "RUN_BUDGET_EXHAUSTED"),
        (
            HorizonNoSolutionError(
                "Expired.", status=SolverStatus.UNKNOWN, wall_time_exhausted=True
            ),
            "RUN_BUDGET_EXHAUSTED",
        ),
        (HorizonNoSolutionError("No conclusion.", status=SolverStatus.UNKNOWN), "ADVICE_FAILED"),
    ],
)
def test_only_typed_wall_time_exhaustion_is_a_run_budget_outcome(
    tmp_path, monkeypatch, error, expected
):
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"

    def stopped(*args, **kwargs):
        raise error

    monkeypatch.setattr(advice_worker, "advise_menu_entry", stopped)
    body = {"strategy": "saf-puan", "window": 3, "preferences": {"no_hits": True}}
    for with_run, code in [(True, expected), (False, "ADVICE_FAILED")]:
        backend = world._deployment(
            tmp_path / str(with_run), monkeypatch, last_gameweek=5, llmopt_vnext=with_run
        )["backend"]
        client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
        result = client.post(route, json={**body, **({"run": _run_ref()} if with_run else {})})
        assert result.status_code == 202, result.text
        assert world._work(backend) == 1
        job = backend.queue.load(result.json()["job_id"])
        assert job.error.code == code
        assert job.error.infeasibility is None
