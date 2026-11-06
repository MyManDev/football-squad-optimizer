"""Requested history uses successful durable answers, never another solve or capture clock."""

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from scripts.export_requested_history import main, requested_history
from tests.unit import test_advice_worker as worker_tests
from tests.unit.test_api_advice_post import CONTEXT, _valid_advice_document
from tests.unit.test_public_entry_compute import BODY, ENTRY
from tests.unit.test_public_entry_compute import public as public

from squadopt.platform.advice_cache import FileAdviceCache, advice_cache_key
from squadopt.platform.advice_job_spec import AdviceJobSpec, FileAdviceJobSpecStore
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_worker import build_advice_compute
from squadopt.platform.jobs_contract import AdviceJob, JobError, _instant

CAPTURED = "2026-08-27T12:00:00Z"
COMPLETED = "2026-08-27T12:01:00Z"
DEADLINE = "2026-08-27T13:00:00Z"
CONTEXT = replace(CONTEXT, advice_contract_version="provisional_league_ui_v1")
SPEC = AdviceJobSpec(352490, 313686, "saf-puan", 1, CONTEXT)


def _key(spec):
    return advice_cache_key(
        **spec.as_payload()["context"],
        league_id=spec.league_id,
        entry_id=spec.entry_id,
        strategy=spec.strategy,
        window=spec.window,
        rival_entry_id=spec.rival_entry_id,
        switches=spec.switches,
    )


def _stored(root, spec=SPEC, *, status="completed", completed=COMPLETED):
    key = _key(spec)
    queue = FileJobQueue(root / "jobs")
    cache = FileAdviceCache(root / "cache")
    FileAdviceJobSpecStore(root / "specs").put(key, spec)
    document = json.loads(_valid_advice_document())
    document["payload"].update(
        source_snapshot_id=spec.context.capture_snapshot_id,
        league_id=spec.league_id,
        entry_id=spec.entry_id,
        window=spec.window,
    )
    raw = json.dumps(document).encode()
    queue.submit(
        AdviceJob(
            f"answer-{key}",
            "queued",
            "a" * 64,
            key,
            CAPTURED,
            CAPTURED,
            idempotency_key="private-client-idempotency-value",
        )
    )
    if status == "queued":
        cache.put(key, raw)
    else:
        job = queue.claim(at_utc=CAPTURED)
        if status == "completed":
            queue.complete(job, cache=cache, payload=raw, at_utc=completed)
        else:
            cache.put(key, raw)  # Bytes alone are not proof of successful completion.
            if status == "failed":
                queue.store(
                    job.transition(
                        "failed", at_utc=completed, error=JobError("ADVICE_FAILED", "fixture")
                    )
                )
    return key, raw, queue


def _export(root, **kwargs):
    return requested_history(
        root,
        season=CONTEXT.season,
        gameweek=CONTEXT.gameweek,
        entry_id=SPEC.entry_id,
        deadline_utc=DEADLINE,
        **kwargs,
    )


def _bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("archived", [False, True])
def test_export_preserves_exact_answer_and_real_completion_without_writing(tmp_path, archived):
    key, raw, queue = _stored(tmp_path)
    if archived:
        queue.archive(now_utc="2026-09-10T00:00:00Z")
        assert queue.jobs() == ()
    before = _bytes(tmp_path)
    (record,) = _export(tmp_path)["records"]
    assert record["cache_key"] == key
    assert record["completed_at_utc"] == COMPLETED
    assert record["response_json"].encode() == raw
    assert record["response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["request"] == SPEC.as_payload()
    assert "private-client-idempotency-value" not in json.dumps(record)
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_cached_bytes_without_a_completed_job_are_not_history(tmp_path, status):
    _stored(tmp_path, status=status)
    assert _export(tmp_path)["records"] == []


@pytest.mark.parametrize("completed", [DEADLINE, "2026-08-27T14:00:00Z"])
def test_capture_clock_cannot_backdate_a_late_answer(tmp_path, completed):
    _stored(tmp_path, completed=completed)
    assert _export(tmp_path)["records"] == []


@pytest.mark.parametrize("changed", ["commit", "handoff", "config", "public_input", "league"])
def test_new_answer_identity_in_one_capture_keeps_both_results(tmp_path, changed):
    first = replace(SPEC, switches={"public_entry": {"fingerprint": "1" * 64}})
    second = {
        "commit": replace(first, context=replace(CONTEXT, repository_commit="b" * 40)),
        "handoff": replace(
            first, context=replace(CONTEXT, projection_handoff_fingerprint="b" * 64)
        ),
        "config": replace(first, context=replace(CONTEXT, configuration_fingerprint="b" * 64)),
        "public_input": replace(first, switches={"public_entry": {"fingerprint": "2" * 64}}),
        "league": replace(first, league_id=0),
    }[changed]
    one, _, _ = _stored(tmp_path, first)
    two, _, queue = _stored(tmp_path, second)
    queue.archive(now_utc="2026-09-10T00:00:00Z")
    rows = _export(tmp_path)["records"]
    assert {row["cache_key"] for row in rows} == {one, two}
    assert len(rows) == 2


@pytest.mark.parametrize(
    "spec",
    [
        replace(SPEC, entry_id=SPEC.entry_id + 1),
        replace(SPEC, window=3),
        replace(SPEC, switches={"managers_word": {"enabled": True}}),
    ],
)
def test_other_entries_and_nonbaseline_requests_are_not_substituted(tmp_path, spec):
    _stored(tmp_path, spec)
    assert _export(tmp_path)["records"] == []


@pytest.mark.parametrize("damage", ["missing", "json", "entry", "capture", "clock", "spec"])
def test_broken_evidence_is_refused_without_repairing_or_replacing_it(tmp_path, damage):
    key, raw, _ = _stored(tmp_path)
    path = tmp_path / "cache" / key[:2] / f"{key}.json"
    document = json.loads(raw)
    if damage == "missing":
        path.unlink()
    elif damage == "json":
        path.write_bytes(b"{")
    elif damage == "spec":
        path = tmp_path / "specs" / key[:2] / f"{key}.json"
        document = SPEC.as_payload()
        document["context"]["repository_commit"] = "d" * 40
        path.write_text(json.dumps(document), encoding="utf-8")
    else:
        if damage == "entry":
            document["payload"]["entry_id"] += 1
        elif damage == "capture":
            document["payload"]["source_snapshot_id"] = "another-capture"
        else:
            document["generated_at_utc"] = DEADLINE
        path.write_text(json.dumps(document), encoding="utf-8")
    before = _bytes(tmp_path)
    with pytest.raises((ValueError, OSError)):
        _export(tmp_path)
    assert _bytes(tmp_path) == before


def test_cli_failure_produces_no_partial_json(tmp_path, capsys):
    assert (
        main(
            [
                "--store-snapshot",
                str(tmp_path),
                "--season",
                CONTEXT.season,
                "--gameweek",
                str(CONTEXT.gameweek),
                "--entry-id",
                str(SPEC.entry_id),
                "--deadline-utc",
                DEADLINE,
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused" in captured.err
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_job_in_live_and_archive_must_agree(tmp_path, conflict):
    key, _, _ = _stored(tmp_path)
    source = tmp_path / "jobs" / f"answer-{key}.json"
    archived = source.parent / "archive" / source.name
    archived.parent.mkdir(exist_ok=True)
    document = json.loads(source.read_bytes())
    if conflict:
        document["updated_at_utc"] = "2026-08-27T12:02:00Z"
    archived.write_text(json.dumps(document), encoding="utf-8")
    if conflict:
        with pytest.raises(ValueError, match="copies of a job disagree"):
            _export(tmp_path)
    else:
        assert len(_export(tmp_path)["records"]) == 1


@pytest.mark.parametrize("field", ["evidence", "top100", "preferences", "plan_weeks"])
def test_plain_request_cannot_hide_a_switched_or_windowed_payload(tmp_path, field):
    key, raw, _ = _stored(tmp_path)
    document = json.loads(raw)
    document["payload"][field] = {} if field != "plan_weeks" else []
    (tmp_path / "cache" / key[:2] / f"{key}.json").write_text(
        json.dumps(document), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        _export(tmp_path)


def test_real_public_worker_answer_survives_archive_with_no_second_fetch_or_solve(
    public, monkeypatch
):
    backend, client, fetch = public
    route = f"/api/v1/public/leagues/0/entries/{ENTRY}/advice"
    assert client.post(route, json=BODY).status_code == 202
    captured = worker_tests.world_module.GW2_CAPTURED_AT
    completed = (_instant(captured) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    deadline = (_instant(captured) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    job = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(
            backend.contexts, backend.job_specs, public_inputs=backend.public_inputs
        ),
        at_utc=captured,
        terminal_at_utc=lambda: completed,
    )
    assert job.status == "completed", job
    original = backend.cache.get(job.cache_key)
    backend.queue.archive(now_utc="2026-11-06T00:00:00Z")
    assert backend.queue.jobs() == ()
    monkeypatch.setattr(
        worker_tests.worker_module,
        "advise_menu_entry",
        lambda *a, **k: pytest.fail("History must never solve another plan"),
    )
    context = backend.contexts.current()
    (record,) = requested_history(
        backend.config.store_root,
        season=context.season,
        gameweek=context.gameweek,
        entry_id=ENTRY,
        deadline_utc=deadline,
    )["records"]
    assert record["response_json"].encode() == original
    assert record["completed_at_utc"] == completed
    assert record["request"]["switches"]["public_entry"]["fingerprint"]
    assert len(json.loads(record["response_json"])["payload"]["starting_xi"]) == 11
    fetch.assert_called_once()

    # The same archived answer reaches the product history through real captured
    # outcome joins; no second optimizer or public-team fetch is involved.
    from scripts.build_requested_history import build_requested_history

    from squadopt.data.snapshots import write_snapshot

    decision = backend.contexts.identity().snapshot
    payloads = dict(decision.payloads)
    bootstrap = json.loads(payloads["bootstrap-static.json"])
    event = next(event for event in bootstrap["events"] if event["id"] == context.gameweek)
    event.update(finished=True, data_checked=True)
    settled_at = (
        (_instant(event["deadline_time"]) + timedelta(days=3)).isoformat().replace("+00:00", "Z")
    )
    payloads["bootstrap-static.json"] = json.dumps(bootstrap).encode()
    payloads[f"event-gw{context.gameweek:02d}-live.json"] = json.dumps(
        {
            "elements": [
                {"id": player["id"], "stats": {"total_points": 2, "minutes": 90, "starts": 1}}
                for player in bootstrap["elements"]
            ]
        }
    ).encode()
    payloads[f"entry-{ENTRY}-history.json"] = json.dumps(
        {
            "current": [
                {
                    "event": context.gameweek,
                    "points": 30,
                    "total_points": 30,
                    "event_transfers_cost": 4,
                }
            ]
        }
    ).encode()
    settled = write_snapshot(
        backend.config.snapshot_root,
        source="fpl-live",
        captured_at_utc=settled_at,
        payloads=payloads,
    )
    path = build_requested_history(
        store_snapshot=backend.config.store_root,
        snapshot_root=backend.config.snapshot_root,
        as_of_snapshot_id=settled.snapshot_id,
        league_id=239,
        entry_id=ENTRY,
        gameweeks=[context.gameweek],
        out_dir=backend.config.site_data_root / "leagues" / "239",
    )
    (row,) = json.loads(path.read_bytes())["payload"]["weeks"]
    assert row["status"] == "available"
    assert row["suggested"]["gross_points"] == 24
    assert row["actual"]["net_points"] == 26
    assert row["advice_source"] == "requested_server"
    assert row["request_cache_key"] == job.cache_key
    fetch.assert_called_once()
