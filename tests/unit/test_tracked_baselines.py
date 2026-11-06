"""Tracked entries are solved once before either league emits its member pages."""

import functools
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
import scripts.build_league_site as build_league_site
from tests.unit.test_weekly_operations import TWO, world

from squadopt.application import advice, league_publication, league_views
from squadopt.application.advice import TRACKED_MEMBER_LINEARIZATION_LEVEL, MemberControl
from squadopt.application.advice_record import (
    MEMBER_BASELINE_RECORD_CONTRACT_VERSION,
    AdviceRecordError,
)
from squadopt.application.entries import EntryError
from squadopt.data.errors import DataError, DataSourceError
from squadopt.platform import publication_workers, weekly_operations


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
    manifest = json.loads((records[0].parent / "manifest.json").read_bytes())
    assert manifest["contract_version"] == MEMBER_BASELINE_RECORD_CONTRACT_VERSION
    stamps = []
    for league in TWO:
        tree = operation.paths.out / "data/leagues" / str(league)
        assert (tree / "entries/101.json").is_file()
        # Each league's history shows the week, league 7's from the baseline store alone
        # (under this clock the deadline has passed, so the row holds no advice).
        weeks = json.loads((tree / "history/101.json").read_bytes())["payload"]["weeks"]
        assert [(row["gameweek"], row["reason"]) for row in weeks] == [
            (2, "no_pre_deadline_record")
        ]
        stamps.append(json.loads((tree / "members.json").read_bytes())["generated_at_utc"])
    # The record is dated by the first page that showed the member, not by the batch's clock:
    # the stamp is what history reads against the deadline.
    assert record["generated_at_utc"] == stamps[0]
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


@pytest.mark.parametrize("fault", ["another-capture", "no-record-root"])
def test_a_batch_the_publication_cannot_bind_is_refused_before_any_solve(
    tmp_path, monkeypatch, fault
):
    """A batch is bound to its capture and to a store to write its records in: a batch from
    another capture, or one handed to a publication with no baseline root (which would then
    write no record without a word), is refused before the panel is built."""

    operation = world(tmp_path)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    request = operation._league_request(352490, False)
    batch = league_publication.TrackedBaselines(request.snapshot_id, {}, {}, {})
    if fault == "another-capture":
        batch = replace(batch, snapshot_id="fpl-live-20260820T120000Z-another")
    else:
        request = replace(request, baseline_record_root=None)

    def unexpected(*args, **kwargs):
        pytest.fail("A batch the publication cannot bind reached the panel")

    monkeypatch.setattr(league_publication, "build_panel", unexpected)
    with pytest.raises(DataError, match="matching baseline batch and record root"):
        league_publication.publish_league(request, baselines=batch)
    assert not list(operation.paths.out.rglob("members.json"))
    assert not operation.paths.baselines.exists()


def _register(operation, entry_id):
    """Register ``entry_id`` without capturing it: the standings list it, the capture does not."""

    registry = json.loads(operation.paths.registry.read_text(encoding="utf-8"))
    registry["entries"].append({"entry_id": entry_id, "label": f"Synthetic member {entry_id}"})
    operation.paths.registry.write_text(json.dumps(registry), encoding="utf-8")


def _failing_baseline(monkeypatch, stage):
    """Make entry 102's server baseline fail at ``stage``; entry 101's is untouched."""

    if stage == "picks":
        # Reading the picks of a registered entry the capture does not hold raises
        # DataError, not EntryError; the page's own read meets the same refusal.
        return "The capture holds no entry-102-picks-gw01.json"
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


@pytest.mark.parametrize("stage", ["picks", "solve", "advice", "record"])
def test_one_failed_member_baseline_does_not_stop_the_publication(tmp_path, monkeypatch, stage):
    """A tracked member whose baseline fails is refused alone: the other member keeps its
    batch control and record, and every league still renders."""

    operation = world(
        tmp_path,
        league_ids=TWO,
        pages={352490: (101, 102), 7: (101, 102)},
        seeded_from=TWO,
        record_advice=True,
        captured=() if stage == "picks" else (102,),
    )
    if stage == "picks":
        _register(operation, 102)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    reason = _failing_baseline(monkeypatch, stage)
    original_page_solve = league_views.solve_member_control
    page_solves = []

    def page_solve(picks, *args, **kwargs):
        page_solves.append(picks.entry_id)
        return original_page_solve(picks, *args, **kwargs)

    monkeypatch.setattr(league_views, "solve_member_control", page_solve)
    result = operation._league()
    baselines = result.value["baselines"]
    assert baselines["entries"] == 1
    assert list(baselines["refused"]) == [102]
    assert reason in baselines["refused"][102]
    # Only the refused member is solved again, by each league's page; a member whose picks
    # the capture does not hold is refused by the page before any solve.
    assert page_solves == ([] if stage == "picks" else [102] * len(TWO))
    records = list(operation.paths.baselines.rglob("advice.json"))
    assert [json.loads(path.read_bytes())["entry_id"] for path in records] == [101]
    assert all(row["advice_recorded"] for row in result.value["leagues"].values())
    for league in TWO:
        tree = operation.paths.out / "data/leagues" / str(league)
        assert (tree / "advice/101/saf-puan/1.json").is_file()
        notes = result.value["leagues"][str(league)]["member_notes"]
        if stage in ("picks", "solve"):
            # The page meets the same picks or squad and refuses the member, as before the
            # batch.
            assert not (tree / "advice/102/saf-puan/1.json").exists()
            assert reason in notes["102"]
        else:
            # The page's own solve succeeds; the member is shown without a baseline record.
            assert (tree / "advice/102/saf-puan/1.json").is_file()


def test_no_baseline_record_lands_for_a_member_whose_page_did_not_render(tmp_path, monkeypatch):
    """The batch solved both members, but member 102's page fails: the record says what a
    member was shown, so only member 101's lands."""

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
    original = league_views.advise_entry

    def advise(request, **kwargs):
        if request.entry_id == 102:
            raise DataSourceError("The page could not advise this member.")
        return original(request, **kwargs)

    # Only the page's advice fails; the batch reads league_publication's own reference.
    monkeypatch.setattr(league_views, "advise_entry", advise)
    result = operation._league()
    assert result.value["baselines"]["entries"] == 2
    assert result.value["baselines"]["refused"] == {}
    records = operation.paths.baselines.rglob("advice.json")
    assert [json.loads(path.read_bytes())["entry_id"] for path in records] == [101]
    for league in TWO:
        assert "could not advise" in result.value["leagues"][str(league)]["member_notes"]["102"]


def test_a_pool_worker_receives_its_members_batch_control(tmp_path, monkeypatch):
    """With workers, each member's batch control crosses to the worker process as bytes and
    reaches its page as the same control; a member the batch refused gets none."""

    operation = world(tmp_path)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    batch = league_publication.prepare_tracked_baselines([operation._league_request(352490, False)])
    control = batch.controls[101]
    received = {}

    def render(task, **kwargs):
        received[task.entry_id] = kwargs["controls"]
        return task.entry_id

    monkeypatch.setattr(publication_workers, "render_member", render)
    monkeypatch.setattr(publication_workers, "_WORKER_CONTEXT", {})
    tasks = [SimpleNamespace(entry_id=101), SimpleNamespace(entry_id=102)]
    with ThreadPoolExecutor(max_workers=1) as executor:
        mapper = publication_workers.pool_mapper(executor)
        bound = functools.partial(render, controls={101: control})
        assert list(mapper(bound, tasks)) == [101, 102]
    assert received[102] is None
    assert list(received[101]) == [101]
    sent = received[101][101]
    assert isinstance(sent, MemberControl) and sent is not control
    assert sent.picks == control.picks
    assert sent.linearization_level == control.linearization_level == 2
    assert sent.plan.diagnostics == control.plan.diagnostics
    assert (
        sent.transfer_config.configuration_fingerprint
        == control.transfer_config.configuration_fingerprint
    )


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


def _recorded_two_leagues(tmp_path):
    """The weekly run over both leagues with recording on: member 101 is in both."""

    operation = world(
        tmp_path,
        league_ids=TWO,
        pages={352490: (101,), 7: (101,)},
        seeded_from=TWO,
        record_advice=True,
    )
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    operation._league()
    return operation


@pytest.mark.parametrize("moved", [False, True], ids=["beside-the-records", "named"])
def test_a_by_hand_rebuild_of_a_second_league_reads_the_baselines_and_writes_none(
    tmp_path, monkeypatch, capsys, moved
):
    """``scripts.build_league_site`` rebuilds league 7 from the run's capture: its member's
    history keeps the week only the baseline store holds, and no baseline is written."""

    operation = _recorded_two_leagues(tmp_path)
    history = operation.paths.out / "data/leagues/7/history/101.json"
    weeks = json.loads(history.read_bytes())["payload"]["weeks"]
    assert [week["gameweek"] for week in weeks] == [2]
    store, named = operation.paths.baselines, []
    if moved:
        # Moved away from the records, the store is found only by the option.
        store = tmp_path / "elsewhere" / "member_baselines"
        shutil.move(operation.paths.baselines, store)
        named = ["--baseline-record-root", str(store)]
    held = sorted(path.relative_to(store) for path in store.rglob("*"))
    capsys.readouterr()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_league_site",
            "--league",
            "7",
            "--snapshot-id",
            operation.request.snapshot_id,
            "--snapshot-root",
            str(operation.paths.snapshots),
            "--out",
            str(operation.paths.out),
            "--archive-root",
            str(operation.paths.archive),
            "--registry",
            str(operation.paths.registry),
            "--in-season-projection",
            str(operation.supplied_handoff),
            "--season",
            operation.request.season,
            "--advice-record-root",
            str(operation.paths.records),
            *named,
        ],
    )
    assert build_league_site.main() == 0
    assert json.loads(history.read_bytes())["payload"]["weeks"] == weeks
    assert sorted(path.relative_to(store) for path in store.rglob("*")) == held
    printed = capsys.readouterr().out
    assert "League 7 writes no legacy advice record" in printed
    assert f"baseline records under {store}; a by-hand build writes none" in printed
