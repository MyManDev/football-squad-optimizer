"""Tracked entries are solved once before either league emits its member pages."""

import json
from dataclasses import replace

import pytest
from tests.unit.test_weekly_operations import TWO, world

from squadopt.application import league_publication, league_views
from squadopt.data.errors import DataError


@pytest.mark.parametrize("device", [False, True])
def test_shared_member_has_one_server_solve_and_one_record(tmp_path, monkeypatch, device):
    operation = world(
        tmp_path,
        league_ids=TWO,
        pages={352490: (101,), 7: (101,)},
        seeded_from=TWO,
        record_advice=True,
    )
    if device:
        operation.request = replace(operation.request, device_league_ids=TWO, workers=8)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    original = league_publication.solve_member_control
    calls = []

    def solve(picks, *args, **kwargs):
        # The record's decision is computed before any member page exists.
        assert not list(operation.paths.out.rglob("entries/101.json"))
        calls.append(picks.entry_id)
        control = original(picks, *args, **kwargs)
        assert control.plan.diagnostics["solver_backend"] == "ortools-cp-sat"
        assert control.plan.diagnostics["linearization_level"] == 2
        assert control.plan.diagnostics["solver_deterministic_time_limit"] == 20.0
        assert control.plan.diagnostics["wall_time_limit_seconds"] == 300.0
        return control

    def unexpected_solve(*args, **kwargs):
        pytest.fail("A page repeated the already computed server baseline")

    monkeypatch.setattr(league_publication, "solve_member_control", solve)
    monkeypatch.setattr(league_views, "solve_member_control", unexpected_solve)
    result = operation._league()
    assert calls == [101]
    records = list(operation.paths.baselines.rglob("advice.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_bytes())
    assert record["source"] == "server_one_week_baseline"
    assert "league_id" not in record and "told" not in record
    assert record["advice"][0]["scoring_complete"] is True
    assert all(row["advice_recorded"] for row in result.value["leagues"].values())
    if device:
        assert not list(operation.paths.records.rglob("advice.json"))
    for league in TWO:
        tree = operation.paths.out / "data/leagues" / str(league)
        assert (tree / "entries/101.json").is_file()
        assert (tree / "history/101.json").is_file()
    assert records[0] in result.output_paths


def test_mixed_capture_batch_is_refused_before_solving(tmp_path, monkeypatch):
    operation = world(tmp_path)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    request = operation._league_request(352490, False)

    def unexpected(*args, **kwargs):
        pytest.fail("A mixed capture batch reached preparation")

    monkeypatch.setattr(league_publication, "prepare_league_publication", unexpected)
    with pytest.raises(DataError, match="one capture"):
        league_publication.prepare_tracked_baselines(
            [request, replace(request, snapshot_id="another-capture")]
        )
