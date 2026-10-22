"""Tracked entries are solved once before either league emits its member pages."""

import json
from dataclasses import replace

import pytest
from tests.unit.test_weekly_operations import TWO, world

from squadopt.application import advice, league_publication, league_views
from squadopt.application.advice import TRACKED_MEMBER_LINEARIZATION_LEVEL
from squadopt.application.advice_record import AdviceRecordError
from squadopt.application.entries import EntryError
from squadopt.data.errors import DataError, DataSourceError
from squadopt.platform import weekly_operations


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


def _failing_baseline(monkeypatch, stage):
    """Make entry 102's server baseline fail at ``stage``; entry 101's is untouched."""

    if stage == "solve":
        # A squad the capture's price table does not cover. The page's own solve meets
        # the same squad, so the member is refused there as well.
        original_held = advice.held_squad_from_picks

        def held(picks, **kwargs):
            if picks.entry_id == 102:
                raise EntryError(
                    "No current price for players [999]; the capture must cover the squad."
                )
            return original_held(picks, **kwargs)

        monkeypatch.setattr(advice, "held_squad_from_picks", held)
        return "No current price for players [999]"
    if stage == "advice":
        original_advise = league_publication.advise_entry

        def advise(request, **kwargs):
            if request.entry_id == 102:
                raise DataSourceError("The planner returned no plan for this squad.")
            return original_advise(request, **kwargs)

        monkeypatch.setattr(league_publication, "advise_entry", advise)
        return "The planner returned no plan"
    original_record = league_publication.build_member_baseline_record

    def record(picks, *args, **kwargs):
        if picks.entry_id == 102:
            raise AdviceRecordError("A baseline must contain the complete starting side.")
        return original_record(picks, *args, **kwargs)

    monkeypatch.setattr(league_publication, "build_member_baseline_record", record)
    return "A baseline must contain the complete starting side"


@pytest.mark.parametrize("stage", ["solve", "advice", "record"])
def test_one_failed_member_baseline_does_not_stop_the_publication(tmp_path, monkeypatch, stage):
    """A tracked member whose baseline fails is refused alone: the other member keeps its
    batch control and record, and every league still renders."""

    operation = world(
        tmp_path,
        league_ids=TWO,
        pages={352490: (101, 102), 7: (101, 102)},
        seeded_from=TWO,
        record_advice=True,
        captured=(102,),
    )
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    reason = _failing_baseline(monkeypatch, stage)
    original_page_solve = league_views.solve_member_control
    page_solves = []

    def page_solve(picks, *args, **kwargs):
        page_solves.append((picks.entry_id, kwargs.get("linearization_level")))
        return original_page_solve(picks, *args, **kwargs)

    monkeypatch.setattr(league_views, "solve_member_control", page_solve)
    result = operation._league()
    baselines = result.value["baselines"]
    assert baselines["entries"] == 1
    assert list(baselines["refused"]) == [102]
    assert reason in baselines["refused"][102]
    # Only the refused member is solved again, by each league's page, at the batch's level.
    assert page_solves == [(102, TRACKED_MEMBER_LINEARIZATION_LEVEL)] * len(TWO)
    records = list(operation.paths.baselines.rglob("advice.json"))
    assert [json.loads(path.read_bytes())["entry_id"] for path in records] == [101]
    assert all(row["advice_recorded"] for row in result.value["leagues"].values())
    for league in TWO:
        tree = operation.paths.out / "data/leagues" / str(league)
        assert (tree / "advice/101/saf-puan/1.json").is_file()
        notes = result.value["leagues"][str(league)]["member_notes"]
        if stage == "solve":
            # The page meets the same squad and refuses the member, as before the batch.
            assert not (tree / "advice/102/saf-puan/1.json").exists()
            assert reason in notes["102"]
        else:
            # The page's own solve succeeds; the member is shown without a baseline record.
            assert (tree / "advice/102/saf-puan/1.json").is_file()


def test_a_run_that_records_nothing_solves_pages_at_the_tracked_level(tmp_path, monkeypatch):
    """Without a batch the page solves the member itself, at the batch's own level, so the
    published plan does not depend on whether the run records advice."""

    operation = world(tmp_path, league_ids=(352490,), pages={352490: (101,)})
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    assert not operation.records_advice

    def unexpected(*args, **kwargs):
        pytest.fail("A run that records nothing prepared a baseline batch")

    original = league_views.solve_member_control
    levels = []

    def solve(picks, *args, **kwargs):
        control = original(picks, *args, **kwargs)
        levels.append(control.plan.diagnostics.get("linearization_level"))
        return control

    monkeypatch.setattr(weekly_operations, "prepare_tracked_baselines", unexpected)
    monkeypatch.setattr(league_views, "solve_member_control", solve)
    operation._league()
    assert levels == [TRACKED_MEMBER_LINEARIZATION_LEVEL]
