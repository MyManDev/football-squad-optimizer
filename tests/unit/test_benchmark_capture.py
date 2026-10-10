"""Synthetic receipts prove timing, frozen membership and publication isolation."""

import json
from dataclasses import replace
from urllib.error import HTTPError

import pytest
from tests.unit.test_benchmark_v2_measurement import _parity_snapshot, _top100_page
from tests.unit.test_weekly_operations import world

from squadopt.application import weekly_plan
from squadopt.application.build import _recent_events
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, league_standings_page_payload
from squadopt.live.ledger import write_manifest
from squadopt.platform import benchmark_capture as capture
from squadopt.platform import weekly_operations as weekly
from squadopt.platform.runlog import configure_run_logging
from squadopt.platform.weekly_journal import WeeklyRun, fingerprint_paths, inspect_run

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
            BOOTSTRAP_PAYLOAD: json.dumps({**boot, "total_players": 9999999}).encode(),
            league_standings_page_payload(314, 1): _top100_page(1, 1),
            league_standings_page_payload(314, 2): _top100_page(2, 51),
        },
    )
    ledger = tmp_path / "ledger" / "2026-27" / "gw06"
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
    write_manifest(ledger)
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
            raise DataSourceError("synthetic missing") from HTTPError(
                url, 404, "Not found", {}, None
            )
        return b"{}"

    before = fingerprint_paths([root, ledger])
    picked = capture.capture_settled_picks(
        study, freeze_snapshot_id=receipt.snapshot_id, now=lambda: POST, fetcher=fetcher
    )
    result = read_snapshot(study, picked.snapshot_id)
    binding = json.loads(result.payloads["benchmark.json"])
    assert binding["members_requested"] == 100 and binding["members_readable"] == 99
    assert binding["members_unreadable"] == 1
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
    decision = (
        operation.paths.ledger / operation.request.season / f"gw{operation.request.gameweek:02d}"
    )
    decision.mkdir(parents=True)
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
    assert result.value == {"status": "unavailable", "reason": "no_cohort"}
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
    assert result.value == {"status": "unavailable", "reason": "no_cohort"}
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


def settled_fetcher(boot, *, missing=False, calls=None):
    settled = json.loads(json.dumps(boot))
    settled["events"][0].update(finished=True, data_checked=True)

    def fetcher(url):
        if calls is not None:
            calls.append(url)
        if url.endswith("/bootstrap-static/"):
            return json.dumps(settled).encode()
        if missing and "/entry/1001/" in url:
            raise DataSourceError("synthetic missing") from HTTPError(
                url, 404, "Not found", {}, None
            )
        if url.endswith("/event/6/live/"):
            return b'{"elements":[],"synthetic":"settled-event-6"}'
        if "/entry/" in url and url.endswith("/event/6/picks/"):
            return json.dumps({"synthetic_picks_url": url}).encode()
        if "/entry/" in url and url.endswith("/history/"):
            return json.dumps({"synthetic_history_url": url}).encode()
        pytest.fail(f"Unexpected synthetic URL: {url}")

    return fetcher


def weekly_fixture(tmp_path):
    root, _study, ledger, cohort, boot = inputs(tmp_path / "inputs")
    operation = world(tmp_path / "weekly")
    operation.paths = replace(operation.paths, snapshots=root, ledger=ledger.parents[1])
    operation.request = replace(operation.request, gameweek=6)
    operation.values["top100_cohort"] = {"snapshot_id": cohort.snapshot_id}
    return operation, ledger, cohort, boot


def test_weekly_success_uses_season_ledger_and_private_store_with_all_outputs(
    tmp_path, monkeypatch
):
    operation, ledger, cohort, boot = weekly_fixture(tmp_path)
    real_freeze = capture.freeze_decision
    monkeypatch.setattr(
        capture, "freeze_decision", lambda *a, **k: real_freeze(*a, **k, now=lambda: PRE)
    )
    result = operation._benchmark_freeze()
    assert result.value["status"] == "captured"
    store = operation._benchmark_root()
    assert store == operation.paths.workspace / "data/benchmark_v2_captures"
    assert all(path.is_relative_to(store) for path in result.output_paths[:-1])
    receipt = read_snapshot(store, result.value["snapshot_id"])
    binding = json.loads(receipt.payloads["benchmark.json"])
    assert set(result.output_paths[:-1]) == {
        store / receipt.metadata.snapshot_id,
        store / binding["decision_snapshot_id"],
        store / cohort.snapshot_id,
        capture.freeze_claim_path(store, 6),
    }
    assert receipt.payloads["system-decision.json"] == (ledger / "decision.json").read_bytes()
    assert (
        receipt.payloads[BOOTSTRAP_PAYLOAD]
        != read_snapshot(store, cohort.snapshot_id).payloads[BOOTSTRAP_PAYLOAD]
    )
    operation.benchmark_picks_freezes = (receipt.metadata.snapshot_id,)
    real_picks = capture.capture_settled_picks
    calls = []
    fetcher = settled_fetcher(boot, missing=True, calls=calls)
    monkeypatch.setattr(
        capture,
        "capture_settled_picks",
        lambda *a, **k: real_picks(*a, **k, now=lambda: POST, fetcher=fetcher),
    )
    picked = operation._benchmark_picks()
    value = picked.value["captures"][0]
    assert value["status"] == "captured"
    assert value["members_readable"] == 99 and value["members_unreadable"] == 1
    assert value["failure_counts"] == {"http_404": 1}
    assert store / value["outcome_snapshot_id"] in picked.output_paths
    assert store / value["snapshot_id"] in picked.output_paths
    assert sum(url.endswith("/event/6/picks/") for url in calls) == 100
    captured = read_snapshot(store, value["snapshot_id"])
    assert json.loads(captured.payloads["entry-1002-picks-gw06.json"])[
        "synthetic_picks_url"
    ].endswith("/entry/1002/event/6/picks/")
    assert json.loads(captured.payloads["entry-1002-history.json"])[
        "synthetic_history_url"
    ].endswith("/entry/1002/history/")
    outcome = read_snapshot(store, value["outcome_snapshot_id"])
    assert (
        outcome.payloads["event-gw06-live.json"] == b'{"elements":[],"synthetic":"settled-event-6"}'
    )
    assert json.loads(outcome.payloads[BOOTSTRAP_PAYLOAD])["events"][0]["data_checked"]
    assert captured.payloads[BOOTSTRAP_PAYLOAD] == outcome.payloads[BOOTSTRAP_PAYLOAD]
    assert captured.payloads[BOOTSTRAP_PAYLOAD] != receipt.payloads[BOOTSTRAP_PAYLOAD]


@pytest.mark.parametrize("failure", ["data", "os", "http_403", "http_429", "http_503"])
def test_transport_failure_creates_no_picks_receipt_or_claim_and_retry_succeeds(tmp_path, failure):
    _root, study, _ledger, _cohort, boot, frozen_receipt = frozen(tmp_path)
    fetcher = settled_fetcher(boot)

    def broken(url):
        if "/entry/1002/" in url:
            if failure.startswith("http_"):
                raise DataSourceError("synthetic request") from HTTPError(
                    url, int(failure[5:]), "failure", {}, None
                )
            raise (DataSourceError if failure == "data" else OSError)("synthetic transient")
        return fetcher(url)

    with pytest.raises(capture.BenchmarkCaptureRefused) as refused:
        capture.capture_settled_picks(
            study, freeze_snapshot_id=frozen_receipt.snapshot_id, fetcher=broken, now=lambda: POST
        )
    assert refused.value.reason == "transport_failure"
    assert not list(study.glob("fpl-benchmark-picks-*"))
    assert not capture.picks_claim_path(study, frozen_receipt.snapshot_id).exists()
    result = capture.capture_settled_picks(
        study, freeze_snapshot_id=frozen_receipt.snapshot_id, fetcher=fetcher, now=lambda: POST
    )
    assert capture.picks_claim_path(study, frozen_receipt.snapshot_id).exists()
    assert (
        json.loads(read_snapshot(study, result.snapshot_id).payloads["benchmark.json"])[
            "members_readable"
        ]
        == 100
    )


@pytest.mark.parametrize("endpoint", ["/bootstrap-static/", "/event/6/live/"])
def test_shared_endpoint_outage_is_a_retryable_transport_failure(tmp_path, endpoint):
    _root, study, _ledger, _cohort, boot, frozen_receipt = frozen(tmp_path)
    fetcher = settled_fetcher(boot)
    before = sorted(path.name for path in study.iterdir())

    def broken(url):
        if url.endswith(endpoint):
            raise DataSourceError("synthetic unreachable host")
        return fetcher(url)

    with pytest.raises(capture.BenchmarkCaptureRefused) as refused:
        capture.capture_settled_picks(
            study, freeze_snapshot_id=frozen_receipt.snapshot_id, fetcher=broken, now=lambda: POST
        )
    assert capture.refusal_code(refused.value) == "transport_failure"
    assert sorted(path.name for path in study.iterdir()) == before
    assert not capture.picks_claim_path(study, frozen_receipt.snapshot_id).exists()
    capture.capture_settled_picks(
        study, freeze_snapshot_id=frozen_receipt.snapshot_id, fetcher=fetcher, now=lambda: POST
    )
    assert capture.picks_claim_path(study, frozen_receipt.snapshot_id).exists()


def test_repeat_freeze_and_picks_return_only_the_first_claimed_ids(tmp_path):
    root, study, ledger, _cohort, boot, receipt = frozen(tmp_path)
    repeated = capture.freeze_decision(
        root,
        decision_directory=ledger,
        cohort_snapshot_id="other",
        gameweek=6,
        output_root=study,
        now=lambda: POST,
    )
    assert repeated == receipt
    assert len(list(study.glob("fpl-benchmark-decision-*"))) == 1
    picked = capture.capture_settled_picks(
        study,
        freeze_snapshot_id=receipt.snapshot_id,
        fetcher=settled_fetcher(boot),
        now=lambda: POST,
    )
    repeated_picks = capture.capture_settled_picks(
        study,
        freeze_snapshot_id=receipt.snapshot_id,
        fetcher=lambda _: pytest.fail("Repeat collection"),
        now=lambda: POST,
    )
    assert repeated_picks == picked
    assert len(list(study.glob("fpl-benchmark-picks-*"))) == 1
    assert (
        json.loads(capture.freeze_claim_path(study, 6).read_bytes())["snapshot_id"]
        == receipt.snapshot_id
    )
    assert (
        json.loads(capture.picks_claim_path(study, receipt.snapshot_id).read_bytes())["snapshot_id"]
        == picked.snapshot_id
    )


@pytest.mark.parametrize(
    "damage",
    ["missing_manifest", "changed_decision", "changed_other_file", "manifest_omits_decision"],
)
def test_freeze_refuses_unverified_decision(tmp_path, damage):
    root, study, ledger, cohort, _boot = inputs(tmp_path)
    if damage == "missing_manifest":
        (ledger / "manifest.json").unlink()
    elif damage == "changed_decision":
        doc = json.loads((ledger / "decision.json").read_bytes())
        doc["captain_player_id"] = 1010
        (ledger / "decision.json").write_text(json.dumps(doc), encoding="utf-8")
    elif damage == "changed_other_file":
        report = ledger / "report.md"
        report.write_text("original", encoding="utf-8")
        write_manifest(ledger)
        report.write_text("changed", encoding="utf-8")
    else:
        (ledger / "manifest.json").write_text('{"files":{}}', encoding="utf-8")
    with pytest.raises(DataError):
        capture.freeze_decision(
            root,
            decision_directory=ledger,
            cohort_snapshot_id=cohort.snapshot_id,
            gameweek=6,
            output_root=study,
            now=lambda: PRE,
        )
    assert not list(study.glob("fpl-benchmark-decision-*"))


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("season", "2025-26", "not_a_decision"),
        ("gameweek", 7, "not_a_decision"),
        ("snapshot_id", None, "not_a_decision"),
        ("captured_at_utc", "2026-10-10T07:00:00Z", "deadline_mismatch"),
        ("deadline_utc", "2026-10-10T11:00:00Z", "deadline_mismatch"),
        ("ordered_bench_player_ids", "remove", "not_a_decision"),
    ],
)
def test_freeze_decision_bindings_are_refused_before_any_copy(tmp_path, field, value, reason):
    root, study, ledger, cohort, _boot = inputs(tmp_path)
    decision = json.loads((ledger / "decision.json").read_bytes())
    if value == "remove":
        decision.pop(field)
    else:
        decision[field] = value
    (ledger / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    write_manifest(ledger)
    with pytest.raises(capture.BenchmarkCaptureRefused) as refused:
        capture.freeze_decision(
            root,
            decision_directory=ledger,
            cohort_snapshot_id=cohort.snapshot_id,
            gameweek=6,
            output_root=study,
            now=lambda: PRE,
        )
    assert refused.value.reason == reason
    assert not study.exists()


@pytest.mark.parametrize(
    "kind", ["late", "previous_open", "clock_before_sources", "retained_differs"]
)
def test_cohort_and_copy_guards_refuse_a_nonbinding_freeze(tmp_path, monkeypatch, kind):
    root, study, ledger, cohort, boot = inputs(tmp_path)
    clock = PRE
    if kind in {"late", "previous_open"}:
        payloads = dict(read_snapshot(root, cohort.snapshot_id).payloads)
        at = DEADLINE
        if kind == "previous_open":
            boot["events"].append(
                {**boot["events"][0], "id": 5, "deadline_time": "2026-10-09T10:00:00Z"}
            )
            payloads[BOOTSTRAP_PAYLOAD] = json.dumps(boot).encode()
            at = "2026-10-08T08:00:00Z"
        cohort = write_snapshot(root, source="fpl-top100", captured_at_utc=at, payloads=payloads)
    elif kind == "clock_before_sources":
        clock = "2026-10-10T07:59:59Z"
    else:
        source = read_snapshot(
            root, json.loads((ledger / "decision.json").read_bytes())["snapshot_id"]
        )
        write_snapshot(
            study,
            source=source.metadata.source,
            captured_at_utc=source.metadata.captured_at_utc,
            payloads=source.payloads,
        )
        original = capture.read_snapshot

        def substituted(store, identifier):
            captured = original(store, identifier)
            return (
                replace(captured, payloads={**captured.payloads, "different.json": b"{}"})
                if store == study
                else captured
            )

        monkeypatch.setattr(capture, "read_snapshot", substituted)
    with pytest.raises(DataSourceError):
        capture.freeze_decision(
            root,
            decision_directory=ledger,
            cohort_snapshot_id=cohort.snapshot_id,
            gameweek=6,
            output_root=study,
            now=lambda: clock,
        )
    assert not list(study.glob("fpl-benchmark-decision-*"))


def test_weekly_missing_decision_records_a_specific_code(tmp_path):
    operation, ledger, _cohort, _boot = weekly_fixture(tmp_path)
    (ledger / "decision.json").unlink()
    result = operation._benchmark_freeze()
    assert result.value == {"status": "unavailable", "reason": "missing_decision"}


def test_missing_decision_is_refused_before_a_freeze_run_can_start_or_resume(tmp_path):
    operation = world(tmp_path)
    kwargs = dict(
        run_id="guarded",
        repository_commit="b" * 40,
        handoff=operation.supplied_handoff,
        benchmark_freeze=True,
    )
    with pytest.raises(weekly.WeekError, match="missing_decision"):
        weekly.WeeklyOperations(operation.request, operation.paths, **kwargs)
    assert not (operation.paths.journal / "guarded").exists()
    # A later owner-created decision can start a new reviewed run, never resume the missing one.
    directory = (
        operation.paths.ledger / operation.request.season / f"gw{operation.request.gameweek:02d}"
    )
    directory.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        weekly.WeeklyOperations(operation.request, operation.paths, resume=True, **kwargs)


def test_research_journal_refusal_is_logged_without_private_error_text(tmp_path, capsys):
    operation = world(tmp_path)
    operation.run = WeeklyRun(operation.paths.journal, "private-failure", {}, ["benchmark_freeze"])
    operation.log = configure_run_logging(
        "season_tick", log_root=operation.paths.log_root, run_id="private-failure", console=False
    )
    with operation.run.hold(), pytest.raises(OSError):
        operation._stage(
            "benchmark_freeze",
            inputs=[],
            operation=lambda: (_ for _ in ()).throw(OSError("private 998877")),
        )
    text = operation.log.log_path.read_text(encoding="utf-8")
    assert "tick.week.stage.failed" in text and "research_stage_refused" in text
    assert "998877" not in text


def test_decide_precedes_freeze_and_options_are_in_declaration(tmp_path):
    operation = world(tmp_path)
    enabled = weekly.WeeklyOperations(
        replace(operation.request, decide=True),
        operation.paths,
        run_id="decide-freeze",
        repository_commit="b" * 40,
        handoff=operation.supplied_handoff,
        benchmark_freeze=True,
        benchmark_picks_freezes=("explicit-freeze",),
    )
    assert (
        enabled.stages.index("decide")
        < enabled.stages.index("benchmark_freeze")
        < enabled.stages.index("league")
    )
    assert enabled.stages.index("settled_outcomes") < enabled.stages.index("benchmark_picks")
    assert enabled.run._request["benchmark_capture_options"] == {
        "freeze": True,
        "picks_freezes": ["explicit-freeze"],
    }


def test_weekly_run_executes_both_research_stages_in_plan_order_and_resumes(tmp_path, monkeypatch):
    operation = world(tmp_path)
    # The decision step is not under test: --decide only satisfies the freeze guard here.
    monkeypatch.setattr(weekly_plan, "preflight_decide", lambda *a, **k: None)
    freeze_id = "fpl-benchmark-decision-20261009T080000Z-aaaaaaaaaaaa"
    request = replace(operation.request, decide=True)
    kwargs = dict(
        run_id="research",
        repository_commit="b" * 40,
        handoff=operation.supplied_handoff,
        benchmark_freeze=True,
        benchmark_picks_freezes=(freeze_id,),
    )
    enabled = weekly.WeeklyOperations(request, operation.paths, **kwargs)
    enabled._decide = lambda: enabled._receipt("decide", {"skipped_reason": "synthetic"})
    doc = json.loads(enabled.execute().read_bytes())
    assert doc["status"] == "completed"
    assert [stage["name"] for stage in doc["stages"]] == enabled.stages
    assert {stage["status"] for stage in doc["stages"]} == {"completed"}
    values = {stage["name"]: stage["value"] for stage in doc["stages"]}
    assert values["benchmark_freeze"] == {"status": "unavailable", "reason": "no_cohort"}
    assert values["benchmark_picks"] == {
        "captures": [
            {"freeze_snapshot_id": freeze_id, "status": "unavailable", "reason": "missing_freeze"}
        ]
    }
    events = _recent_events(operation.paths.log_root, "season_tick", 200)
    plans = [event.fields["stages"] for event in events if event.message == "tick.week.plan"]
    assert plans == [[name for name in enabled.stages if not name.startswith("benchmark_")]]
    assert not any(str(event.fields.get("stage", "")).startswith("benchmark_") for event in events)
    resumed = weekly.WeeklyOperations(request, operation.paths, resume=True, **kwargs)
    resumed._decide = lambda: pytest.fail("A completed stage ran again")
    resumed.execute()
    assert inspect_run(operation.paths.journal, "research")["status"] == "completed"


@pytest.mark.parametrize("identifier", ["", "..", "../..", "folder/id", r"folder\id"])
def test_typed_freeze_paths_are_refused_before_dry_run_or_any_stage(tmp_path, identifier):
    args = [
        "--workspace",
        str(tmp_path),
        "--season",
        "2026-27",
        "--gameweek",
        "6",
        "--league",
        "9",
        "--dry-run",
        "--benchmark-picks-freeze",
        identifier,
    ]
    assert weekly.main(args) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "damage", ["source", "season", "contract", "cohort_fingerprint", "late", "gameweek_floor"]
)
def test_picks_refuses_a_damaged_freeze_before_network_reads(tmp_path, monkeypatch, damage):
    _root, study, _ledger, _cohort, _boot, receipt = frozen(tmp_path)
    original = read_snapshot(study, receipt.snapshot_id)
    payloads = dict(original.payloads)
    binding = json.loads(payloads["benchmark.json"])
    source, at = original.metadata.source, PRE
    if damage == "source":
        source = "fpl-live"
    elif damage == "season":
        binding["season"] = "2025-26"
    elif damage == "contract":
        binding["contract_version"] = "invalid"
    elif damage == "cohort_fingerprint":
        binding["cohort_fingerprint"] = "different"
    elif damage == "gameweek_floor":
        binding["gameweek"] = 2
    else:
        at = DEADLINE
    payloads["benchmark.json"] = json.dumps(binding).encode()
    damaged = write_snapshot(study, source=source, captured_at_utc=at, payloads=payloads)
    # Bind the synthetic damaged freeze to isolate the individual validation gates.
    capture.freeze_claim_path(study, 6).write_text(
        json.dumps({"snapshot_id": damaged.snapshot_id, "fingerprint": damaged.fingerprint}),
        encoding="utf-8",
    )
    with pytest.raises(DataSourceError):
        capture.capture_settled_picks(
            study,
            freeze_snapshot_id=damaged.snapshot_id,
            now=lambda: POST,
            fetcher=lambda _: pytest.fail("Damaged freeze was fetched"),
        )
    assert not capture.picks_claim_path(study, damaged.snapshot_id).exists()


@pytest.mark.parametrize(
    "damage", ["changed_deadline", "completion_before_deadline", "backwards", "outside_season"]
)
def test_picks_deadline_and_completion_guards_never_claim_a_result(tmp_path, damage):
    _root, study, _ledger, _cohort, boot, receipt = frozen(tmp_path)
    if damage == "changed_deadline":
        boot["events"][0]["deadline_time"] = "2026-10-10T11:00:00Z"
    times = {
        "changed_deadline": [POST, POST],
        "completion_before_deadline": [POST, PRE],
        "backwards": [POST, "2026-10-13T09:59:59Z"],
        "outside_season": [POST, "2027-08-01T00:00:00Z"],
    }
    clock = iter(times[damage])
    with pytest.raises(DataSourceError):
        capture.capture_settled_picks(
            study,
            freeze_snapshot_id=receipt.snapshot_id,
            now=lambda: next(clock),
            fetcher=settled_fetcher(boot),
        )
    assert not capture.picks_claim_path(study, receipt.snapshot_id).exists()
    assert not list(study.glob("fpl-benchmark-picks-*"))


def test_cli_success_prints_coverage_and_unavailable_codes_are_distinct(
    tmp_path, monkeypatch, capsys
):
    _root, study, _ledger, _cohort, boot, receipt = frozen(tmp_path)
    result = capture.capture_settled_picks(
        study,
        freeze_snapshot_id=receipt.snapshot_id,
        now=lambda: POST,
        fetcher=settled_fetcher(boot, missing=True),
    )
    monkeypatch.setattr(capture, "capture_settled_picks", lambda *a, **k: result)
    assert (
        capture.main(["--snapshot-root", str(study), "--freeze-snapshot", receipt.snapshot_id]) == 0
    )
    assert "readable=99; unreadable=1" in capsys.readouterr().out
    for reason in ["missing_freeze", "not_settled"]:

        def refused(*args, reason=reason, **kwargs):
            raise capture.BenchmarkCaptureRefused(reason, "private 998877")

        monkeypatch.setattr(capture, "capture_settled_picks", refused)
        assert (
            capture.main(["--snapshot-root", str(study), "--freeze-snapshot", receipt.snapshot_id])
            == 1
        )
        text = capsys.readouterr().out
        assert reason in text and "998877" not in text


def test_unclaimed_freeze_and_private_retry_output_are_refused_or_hidden(
    tmp_path, monkeypatch, capsys
):
    _root, study, _ledger, _cohort, _boot, receipt = frozen(tmp_path)
    capture.freeze_claim_path(study, 6).unlink()
    with pytest.raises(capture.BenchmarkCaptureRefused, match="not the claimed week"):
        capture.capture_settled_picks(
            study,
            freeze_snapshot_id=receipt.snapshot_id,
            now=lambda: POST,
            fetcher=lambda _: pytest.fail("Unclaimed fetch"),
        )

    def shared_fetch(url):
        print("retry private 998877")
        return b"{}"

    monkeypatch.setattr(capture, "fetch", shared_fetch)
    assert capture._private_fetch("synthetic") == b"{}"
    assert capsys.readouterr().out == ""
