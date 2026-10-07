"""Synthetic receipts prove timing, frozen membership and publication isolation."""

import json
from dataclasses import replace

import pytest
from tests.unit.test_benchmark_v2_measurement import _parity_snapshot, _top100_page
from tests.unit.test_weekly_operations import world

from squadopt.application.build import _recent_events
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, league_standings_page_payload
from squadopt.platform import benchmark_capture as capture
from squadopt.platform.runlog import configure_run_logging
from squadopt.platform.weekly_journal import WeeklyRun, fingerprint_paths

DEADLINE = "2026-10-10T10:00:00Z"
PRE = "2026-10-10T08:00:00Z"
POST = "2026-10-13T10:00:00Z"


def inputs(tmp_path):
    root = tmp_path / "normal-store"
    study = tmp_path / "study-store"
    boot = json.loads(_parity_snapshot().payloads[BOOTSTRAP_PAYLOAD])
    boot["events"][0].update(id=6, deadline_time=DEADLINE, finished=False, data_checked=False)
    for player in boot["elements"]:
        player["selected_by_percent"] = str(100 - player["id"])
    raw = json.dumps(boot).encode()
    source = write_snapshot(
        root, source="fpl-live", captured_at_utc=PRE, payloads={BOOTSTRAP_PAYLOAD: raw}
    )
    cohort = write_snapshot(
        root,
        source="fpl-top100",
        captured_at_utc=PRE,
        payloads={
            BOOTSTRAP_PAYLOAD: raw,
            league_standings_page_payload(314, 1): _top100_page(1, 1),
            league_standings_page_payload(314, 2): _top100_page(2, 51),
        },
    )
    ledger = tmp_path / "ledger" / "gw06"
    ledger.mkdir(parents=True)
    decision = {
        "season": "2026-27",
        "gameweek": 6,
        "snapshot_id": source.snapshot_id,
        "captured_at_utc": PRE,
        "deadline_utc": DEADLINE,
        "squad_player_ids": list(range(1001, 1016)),
        "starting_xi_player_ids": [
            1001,
            1003,
            1004,
            1005,
            1006,
            1008,
            1009,
            1010,
            1011,
            1013,
            1014,
        ],
        "ordered_bench_player_ids": [1002, 1007, 1012, 1015],
        "captain_player_id": 1008,
        "vice_captain_player_id": 1009,
        "completion_policy": "frozen_test",
        "model_version": "synthetic-v1",
    }
    (ledger / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    return root, study, ledger, cohort, boot


def frozen(tmp_path):
    root, study, ledger, cohort, boot = inputs(tmp_path)
    receipt = capture.freeze_decision(
        root,
        decision_directory=ledger,
        cohort_snapshot_id=cohort.snapshot_id,
        gameweek=6,
        output_root=study,
        now=lambda: PRE,
    )
    return root, study, ledger, cohort, boot, receipt


def test_freeze_is_an_exact_private_copy_and_never_changes_normal_inputs(tmp_path):
    root, study, ledger, cohort, _boot = inputs(tmp_path)
    before = fingerprint_paths([root, ledger])
    receipt = capture.freeze_decision(
        root,
        decision_directory=ledger,
        cohort_snapshot_id=cohort.snapshot_id,
        gameweek=6,
        output_root=study,
        now=lambda: PRE,
    )
    result = read_snapshot(study, receipt.snapshot_id)
    assert result.payloads["system-decision.json"] == (ledger / "decision.json").read_bytes()
    binding = json.loads(result.payloads["benchmark.json"])
    assert binding["template_configuration"] == {
        "budget_tenths": 1000,
        "max_players_per_team": 3,
        "expected_points_scale": 1000,
    }
    assert read_snapshot(study, cohort.snapshot_id).metadata == cohort
    assert fingerprint_paths([root, ledger]) == before
    assert not (root / receipt.snapshot_id).exists()


@pytest.mark.parametrize("at", [DEADLINE, "2026-10-10T11:00:00Z"])
def test_late_freeze_creates_no_research_receipt(tmp_path, at):
    root, study, ledger, cohort, _boot = inputs(tmp_path)
    with pytest.raises(DataSourceError, match="not pre-deadline"):
        capture.freeze_decision(
            root,
            decision_directory=ledger,
            cohort_snapshot_id=cohort.snapshot_id,
            gameweek=6,
            output_root=study,
            now=lambda: at,
        )
    assert not study.exists()


def test_deadline_crossed_while_retaining_sources_never_gets_a_freeze(tmp_path):
    root, study, ledger, cohort, _boot = inputs(tmp_path)
    clock = iter([PRE, DEADLINE])
    with pytest.raises(DataSourceError, match="not pre-deadline"):
        capture.freeze_decision(
            root,
            decision_directory=ledger,
            cohort_snapshot_id=cohort.snapshot_id,
            gameweek=6,
            output_root=study,
            now=lambda: next(clock),
        )
    assert not list(study.glob("fpl-benchmark-decision-*"))


def test_early_picks_make_no_network_request(tmp_path):
    _root, study, _ledger, _cohort, _boot, receipt = frozen(tmp_path)
    with pytest.raises(DataSourceError, match="before the target deadline"):
        capture.capture_settled_picks(
            study,
            freeze_snapshot_id=receipt.snapshot_id,
            now=lambda: PRE,
            fetcher=lambda _: pytest.fail("Premature network read"),
        )


def test_unchecked_week_never_fetches_member_picks(tmp_path):
    _root, study, _ledger, _cohort, boot, receipt = frozen(tmp_path)
    calls = []

    def fetcher(url):
        calls.append(url)
        return json.dumps(boot).encode()

    with pytest.raises(DataSourceError, match="not finished and checked"):
        capture.capture_settled_picks(
            study, freeze_snapshot_id=receipt.snapshot_id, now=lambda: POST, fetcher=fetcher
        )
    assert len(calls) == 1 and calls[0].endswith("/bootstrap-static/")


def test_settled_picks_keep_original_100_and_never_backfill(tmp_path):
    root, study, ledger, _cohort, boot, receipt = frozen(tmp_path)
    boot["events"][0].update(finished=True, data_checked=True)
    calls = []

    def fetcher(url):
        calls.append(url)
        if url.endswith("/bootstrap-static/"):
            return json.dumps(boot).encode()
        if "/entry/1001/" in url:
            raise DataSourceError("synthetic unreadable member")
        return b"{}"

    before = fingerprint_paths([root, ledger])
    picked = capture.capture_settled_picks(
        study, freeze_snapshot_id=receipt.snapshot_id, now=lambda: POST, fetcher=fetcher
    )
    result = read_snapshot(study, picked.snapshot_id)
    binding = json.loads(result.payloads["benchmark.json"])
    assert binding["members_requested"] == 100 and binding["members_readable"] == 99
    assert binding["members_unreadable"] == 1
    assert all("/entry/1101/" not in url for url in calls)
    assert sum(url.endswith("/event/6/picks/") for url in calls) == 100
    assert "entry-1001-picks-gw06.json" not in result.payloads
    assert "entry-1100-picks-gw06.json" in result.payloads
    outcome = read_snapshot(study, binding["outcome_snapshot_id"])
    assert outcome.metadata.source == "fpl-live" and "event-gw06-live.json" in outcome.payloads
    assert fingerprint_paths([root, ledger]) == before


def test_holdout_id_is_refused_before_disk_access(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "read_snapshot", lambda *a: pytest.fail("Holdout was opened"))
    with pytest.raises(DataSourceError, match="outside the live season"):
        capture.read_live_capture(tmp_path, "fpl-live-20251010T080000Z-aabbcc")


def test_weekly_capture_stages_are_explicit_and_never_add_a_decision(tmp_path):
    operation = world(tmp_path)
    assert not any(stage.startswith("benchmark") for stage in operation.stages)
    enabled = type(operation)(
        operation.request,
        operation.paths,
        run_id="benchmark",
        repository_commit="b" * 40,
        handoff=operation.supplied_handoff,
        benchmark_freeze=True,
        benchmark_picks_freezes=("explicit-freeze",),
    )
    assert "decide" not in enabled.stages
    assert enabled.stages.index("benchmark_picks") > enabled.stages.index("settled_outcomes")
    assert enabled.stages.index("benchmark_freeze") < enabled.stages.index("league")
    assert enabled.benchmark_picks_freezes == ("explicit-freeze",)


def test_unavailable_research_input_leaves_publication_tree_and_ledger_unchanged(tmp_path):
    operation = world(tmp_path)
    operation.request = replace(operation.request, gameweek=6)
    public = operation.paths.out / "data"
    public.mkdir(parents=True, exist_ok=True)
    (public / "member.json").write_bytes(b"published sentinel")
    before = fingerprint_paths([public], allow_missing=True)
    result = operation._benchmark_freeze()
    assert result.value == {"status": "unavailable"}
    assert fingerprint_paths([public], allow_missing=True) == before
    assert not operation.paths.ledger.exists()


def test_cli_refusal_does_not_print_raw_member_failure(tmp_path, monkeypatch, capsys):
    def refused(*a, **k):
        raise DataSourceError("private synthetic entry 998877")

    monkeypatch.setattr(capture, "capture_settled_picks", refused)
    assert capture.main(["--snapshot-root", str(tmp_path), "--freeze-snapshot", "private"]) == 1
    assert "998877" not in capsys.readouterr().out


def test_private_research_stage_never_changes_the_member_status_event_feed(tmp_path):
    operation = world(tmp_path)
    operation.run = WeeklyRun(operation.paths.journal, "private-only", {}, ["benchmark_freeze"])
    operation.log = configure_run_logging(
        "season_tick", log_root=operation.paths.log_root, run_id="private-only", console=False
    )
    operation.log.event("synthetic.control")
    before = _recent_events(operation.paths.log_root, "season_tick", 20)
    with operation.run.hold():
        result = operation._stage(
            "benchmark_freeze", inputs=[], operation=operation._benchmark_freeze
        )
    assert result.value == {"status": "unavailable"}
    assert all(path.is_file() for path in result.output_paths)
    assert _recent_events(operation.paths.log_root, "season_tick", 20) == before


def test_backwards_freeze_clock_never_writes_a_decision_receipt(tmp_path):
    root, study, ledger, cohort, _boot = inputs(tmp_path)
    times = iter(["2026-10-10T09:00:00Z", PRE])
    with pytest.raises(DataSourceError, match="clock moved backwards"):
        capture.freeze_decision(
            root,
            decision_directory=ledger,
            cohort_snapshot_id=cohort.snapshot_id,
            gameweek=6,
            output_root=study,
            now=lambda: next(times),
        )
    assert not list(study.glob("fpl-benchmark-decision-*"))
