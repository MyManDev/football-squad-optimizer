"""A running backend yields immutable history evidence without stopping or repairing it."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.unit.test_requested_history_export import SPEC, _bytes, _export, _stored

from squadopt.platform import requested_history_snapshot as snapshot
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.storage._queue_lock import QueueFileLock

NOW = datetime(2026, 11, 6, 10, tzinfo=UTC)


def capture(store, output, **kwargs):
    return snapshot.snapshot_requested_history(store, output, clock=lambda: NOW, **kwargs)


@pytest.mark.parametrize("archived", [False, True])
def test_completed_answers_are_verified_and_source_bytes_and_private_keys_stay_private(
    tmp_path, archived
):
    store, output = tmp_path / "backend", tmp_path / "history"
    _, _, queue = _stored(store)
    if archived:
        assert queue.archive(now_utc=NOW.isoformat())
    before = _bytes(store)
    result = capture(store, output)
    assert snapshot.read_history_snapshot(result.source) == result
    assert _export(result.store) == _export(store)
    assert _bytes(store) == before
    (job_path,) = (result.store / "jobs").glob("*.json")
    assert AdviceJob.from_payload(json.loads(job_path.read_bytes())).idempotency_key is None
    assert b"private-client-idempotency-value" not in job_path.read_bytes()
    assert not list(output.glob(".building-*"))


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_cache_bytes_without_completed_job_never_become_history(tmp_path, status):
    store = tmp_path / "backend"
    _stored(store, status=status)
    result = capture(store, tmp_path / "history")
    assert _export(result.store)["records"] == []
    assert not list((result.store / "cache").rglob("*.json"))


def test_archiving_after_metadata_freeze_cannot_drop_a_completed_answer(tmp_path, monkeypatch):
    store = tmp_path / "backend"
    _, _, queue = _stored(store)
    freeze = snapshot._frozen_jobs

    def move(*args, **kwargs):
        frozen = freeze(*args, **kwargs)
        assert queue.archive(now_utc=NOW.isoformat())
        return frozen

    monkeypatch.setattr(snapshot, "_frozen_jobs", move)
    result = capture(store, tmp_path / "history")
    assert queue.jobs() == ()
    assert len(_export(result.store)["records"]) == 1


def test_job_finishing_after_freeze_is_excluded_even_with_the_same_second_clock(
    tmp_path, monkeypatch
):
    store = tmp_path / "backend"
    _, raw, queue = _stored(store, status="running")
    (running,) = queue.jobs()
    freeze = snapshot._frozen_jobs

    def finish(*args, **kwargs):
        frozen = freeze(*args, **kwargs)
        queue.complete(
            running, cache=FileAdviceCache(store / "cache"), payload=raw, at_utc=NOW.isoformat()
        )
        return frozen

    monkeypatch.setattr(snapshot, "_frozen_jobs", finish)
    result = capture(store, tmp_path / "history")
    assert queue.load(running.job_id).status == "completed"
    assert _export(result.store)["records"] == []


def test_answer_copying_holds_no_queue_lock(tmp_path, monkeypatch):
    store = tmp_path / "backend"
    _stored(store)
    export = snapshot._requested_history

    def inspect(*args, **kwargs):
        with QueueFileLock(store / "jobs/.queue.lock", timeout_seconds=0).hold():
            return export(*args, **kwargs)

    monkeypatch.setattr(snapshot, "_requested_history", inspect)
    assert capture(store, tmp_path / "history").source.is_file()


def test_repeated_checks_and_archiving_reuse_exact_unchanged_evidence(tmp_path):
    store, output = tmp_path / "backend", tmp_path / "history"
    _, _, queue = _stored(store)
    first = capture(store, output)
    held = _bytes(output)
    assert queue.archive(now_utc=NOW.isoformat())
    checked = snapshot.snapshot_requested_history(
        store, output, clock=lambda: NOW + timedelta(hours=1), reuse_unchanged=True
    )
    assert checked == first
    assert _bytes(output) == held
    assert not list(output.glob(".building-*"))


def test_a_new_completed_request_advances_the_receipt_but_a_waiting_one_does_not(tmp_path):
    store, output = tmp_path / "backend", tmp_path / "history"
    _stored(store)
    first = capture(store, output)
    _, raw, queue = _stored(store, replace(SPEC, entry_id=SPEC.entry_id + 1), status="running")
    assert capture(store, output, reuse_unchanged=True) == first
    running = next(job for job in queue.jobs() if job.status == "running")
    queue.complete(
        running, cache=FileAdviceCache(store / "cache"), payload=raw, at_utc=NOW.isoformat()
    )
    second = capture(store, output, reuse_unchanged=True)
    assert second.store != first.store
    assert len(list((second.store / "jobs").glob("*.json"))) == 2
    assert first.store.is_dir()


def test_size_limit_preserves_previous_receipt_and_removes_staging(tmp_path):
    store, output = tmp_path / "backend", tmp_path / "history"
    _stored(store)
    first = capture(store, output)
    held = _bytes(output)
    with pytest.raises(ValueError, match="byte limit"):
        capture(store, output, max_snapshot_bytes=1)
    assert snapshot.read_history_snapshot(first.source) == first
    assert _bytes(output) == held
    assert not list(output.glob(".building-*"))


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_size_limits_are_rejected_before_writing(tmp_path, limit):
    store, output = tmp_path / "backend", tmp_path / "history"
    _stored(store)
    with pytest.raises(ValueError, match="positive integer"):
        capture(store, output, max_snapshot_bytes=limit)
    assert not output.exists()


@pytest.mark.parametrize("failure", ["cache", "backup", "receipt"])
def test_failure_leaves_previous_snapshot_receipt_and_store_unchanged(
    tmp_path, monkeypatch, failure
):
    store, output = tmp_path / "backend", tmp_path / "history"
    key, _, _ = _stored(store)
    first = capture(store, output)
    prior = first.source.read_bytes()
    if failure == "cache":
        (store / "cache" / key[:2] / f"{key}.json").write_bytes(b"broken json")
    elif failure == "backup":
        monkeypatch.setattr(
            snapshot,
            "create_backup",
            lambda *a, **k: (_ for _ in ()).throw(OSError("interrupted backup")),
        )
    else:
        monkeypatch.setattr(
            snapshot,
            "replace_retrying",
            lambda *a: (_ for _ in ()).throw(OSError("interrupted receipt")),
        )
    before = _bytes(store)
    with pytest.raises((OSError, ValueError)):
        capture(store, output)
    assert first.source.read_bytes() == prior
    assert snapshot.read_history_snapshot(first.source) == first
    assert _bytes(store) == before


@pytest.mark.parametrize("damage", ["content", "missing", "extra", "manifest", "path"])
def test_receipt_refuses_changed_or_redirected_snapshot(tmp_path, damage):
    store = tmp_path / "backend"
    _stored(store)
    result = capture(store, tmp_path / "history")
    cache = next((result.store / "cache").rglob("*.json"))
    if damage == "content":
        cache.write_bytes(cache.read_bytes() + b"\n")
    elif damage == "missing":
        cache.unlink()
    elif damage == "extra":
        (result.store / "extra.json").write_text("{}")
    elif damage == "manifest":
        manifest = result.store.parent.parent / "manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b"\n")
    else:
        record = json.loads(result.source.read_bytes())
        record["backup"] = "../../backend"
        result.source.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        snapshot.read_history_snapshot(result.source)


def test_metadata_lock_budget_refuses_before_publishing_and_releases_lock(tmp_path, monkeypatch):
    store, output = tmp_path / "backend", tmp_path / "history"
    _stored(store)
    readings = iter([0.0, 2.0])
    # Patch this module's time object, not the process-shared queue clock.
    from types import SimpleNamespace

    monkeypatch.setattr(snapshot, "time", SimpleNamespace(monotonic=lambda: next(readings)))
    with pytest.raises(TimeoutError, match="lock budget"):
        capture(store, output)
    assert not (output / "latest.json").exists()
    with QueueFileLock(store / "jobs/.queue.lock", timeout_seconds=0).hold():
        pass


def test_snapshot_destination_cannot_overlap_live_store(tmp_path):
    store = tmp_path / "backend"
    _stored(store)
    for destination in (store, store / "snapshot", tmp_path):
        with pytest.raises(ValueError, match="disjoint"):
            capture(store, destination)


def test_an_older_clock_cannot_replace_a_newer_snapshot(tmp_path):
    store, output = tmp_path / "backend", tmp_path / "history"
    _stored(store)
    first = capture(store, output)
    prior = first.source.read_bytes()
    with pytest.raises(ValueError, match="older snapshot clock"):
        snapshot.snapshot_requested_history(store, output, clock=lambda: NOW - timedelta(days=1))
    assert first.source.read_bytes() == prior


def test_disagreeing_live_and_archived_records_are_not_silently_reconciled(tmp_path):
    store, output = tmp_path / "backend", tmp_path / "history"
    _stored(store)
    job = next((store / "jobs").glob("*.json"))
    archive = store / "jobs/archive" / job.name
    archive.parent.mkdir()
    archive.write_bytes(b"{}")
    before = _bytes(store)
    with pytest.raises(ValueError, match="copies of a job disagree"):
        capture(store, output)
    assert _bytes(store) == before
    assert not (output / "latest.json").exists()


def test_cli_emits_only_private_receipt_location_and_digest(tmp_path, capsys):
    store = tmp_path / "backend"
    _stored(store)
    assert snapshot.main(["--store", str(store), "--output-root", str(tmp_path / "history")]) == 0
    output = capsys.readouterr().out
    assert "private-client-idempotency-value" not in output
    assert set(json.loads(output)) == {"receipt", "manifest_sha256"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX service ownership and permission modes")
def test_group_sharing_is_opt_in_and_never_grants_world_access(tmp_path):
    store, output = tmp_path / "backend", tmp_path / "history"
    _stored(store)
    private = capture(store, output)
    assert output.stat().st_mode & 0o777 == 0o700
    assert private.source.stat().st_mode & 0o777 == 0o600
    assert private.store.parent.parent.stat().st_mode & 0o777 == 0o700
    shared = capture(store, output, group_readable=True)
    assert output.stat().st_mode & 0o777 == 0o750
    assert shared.source.stat().st_mode & 0o777 == 0o640
    backup = shared.store.parent.parent
    for path in (backup, *backup.rglob("*")):
        assert path.stat().st_mode & 0o777 == (0o750 if path.is_dir() else 0o640)
