"""Real file journals and OS process death, without production data or services."""

import errno
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from squadopt.data import atomic
from squadopt.data.errors import RenameRefusedError
from squadopt.platform.weekly_journal import (
    WeeklyJournalError,
    WeeklyReconciliationRequired,
    WeeklyRun,
    WeeklyStageResult,
    inspect_run,
)


def artifact(path: Path, value: str = "verified") -> WeeklyStageResult:
    path.write_text(value, encoding="utf-8")
    return WeeklyStageResult((path,), {"value": value})


def test_success_resume_verifies_bytes_and_never_reexecutes(tmp_path: Path) -> None:
    source = tmp_path / "capture.json"
    source.write_text("frozen")
    request = {"snapshot_id": "frozen", "source_commit": "c" * 40}
    with WeeklyRun(tmp_path, "week", request, ["build"]).hold() as run:
        run.stage("build", inputs=[source], operation=lambda: artifact(tmp_path / "view.json"))
        run.finish()
    with WeeklyRun(tmp_path, "week", request, ["build"], resume=True).hold() as run:
        result = run.stage("build", inputs=[source], operation=lambda: pytest.fail("Repeated"))
        assert result.value == {"value": "verified"}
        run.finish()
    assert inspect_run(tmp_path, "week")["status"] == "completed"
    (tmp_path / "view.json").write_text("changed")
    assert inspect_run(tmp_path, "week")["status"] == "invalid_artifacts"
    with (
        WeeklyRun(tmp_path, "week", request, ["build"], resume=True).hold() as run,
        pytest.raises(WeeklyJournalError, match="changed"),
    ):
        run.stage("build", inputs=[source], operation=lambda: pytest.fail("Repeated"))


@pytest.mark.parametrize("drift", ["capture", "new_file", "request"])
def test_capture_membership_and_request_drift_refuse_resume(tmp_path: Path, drift: str) -> None:
    source = tmp_path / "capture"
    source.mkdir()
    payload = source / "bootstrap.json"
    payload.write_text("before")
    with WeeklyRun(tmp_path, "week", {"source": 1}, ["build"]).hold() as run:
        run.stage("build", inputs=[source], operation=lambda: artifact(tmp_path / "out"))
        run.finish()
    if drift == "capture":
        payload.write_text("after")
    elif drift == "new_file":
        (source / "extra.json").write_text("added")
    with (
        pytest.raises(WeeklyJournalError, match="changed"),
        WeeklyRun(
            tmp_path, "week", {"source": 2 if drift == "request" else 1}, ["build"], resume=True
        ).hold() as run,
    ):
        run.stage("build", inputs=[source], operation=lambda: pytest.fail("Repeated"))


@pytest.mark.parametrize("failure", ["nonzero", "missing", "none", "input_changed"])
def test_exit_and_artifact_checks_are_required_for_success(tmp_path: Path, failure: str) -> None:
    source = tmp_path / "alias"
    source.write_text("before")

    def operation() -> WeeklyStageResult:
        if failure == "nonzero":
            return WeeklyStageResult((), exit_code=9)
        if failure == "missing":
            return WeeklyStageResult((tmp_path / "absent",))
        if failure == "none":
            return WeeklyStageResult(())
        source.write_text("after")
        return artifact(tmp_path / "out")

    with (
        WeeklyRun(tmp_path, "week", {}, ["build"]).hold() as run,
        pytest.raises(WeeklyJournalError),
    ):
        run.stage("build", inputs=[source], operation=operation)
    assert inspect_run(tmp_path, "week")["status"] == "failed"


@pytest.mark.parametrize("external", [False, True])
def test_real_process_crash_preserves_completed_stage_and_fences_external_retry(
    tmp_path: Path, external: bool
) -> None:
    code = """
import os, sys
from pathlib import Path
from squadopt.platform.weekly_journal import WeeklyRun, WeeklyStageResult
root = Path(sys.argv[1])
with WeeklyRun(root, "crash", {}, ["first", "second"]).hold() as run:
    out = root / "out"
    out.write_text("finished")
    run.stage("first", inputs=[], operation=lambda: WeeklyStageResult((out,)))
    run.stage("second", inputs=[], operation=lambda: os._exit(17),
              repeatable=sys.argv[2] == "False")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(tmp_path), str(external)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 17, result.stderr
    assert inspect_run(tmp_path, "crash")["status"] == ("uncertain" if external else "interrupted")
    with WeeklyRun(tmp_path, "crash", {}, ["first", "second"], resume=True).hold() as run:
        run.stage("first", inputs=[], operation=lambda: pytest.fail("First repeated"))
        if external:
            with pytest.raises(WeeklyReconciliationRequired):
                run.stage("second", inputs=[], operation=lambda: pytest.fail("External repeated"))
        else:
            run.stage("second", inputs=[], operation=lambda: artifact(tmp_path / "second"))
            run.finish()
    document = json.loads((tmp_path / "crash/run.json").read_bytes())
    if not external:
        assert [attempt["status"] for attempt in document["stages"][1]["attempts"]] == [
            "interrupted",
            "completed",
        ]


def test_active_owner_excludes_other_process_and_status_does_not_call_it_interrupted(
    tmp_path: Path,
) -> None:
    code = """
import sys
from pathlib import Path
from squadopt.platform.weekly_journal import WeeklyRun
with WeeklyRun(Path(sys.argv[1]), "held", {}, ["build"]).hold():
    print("ready", flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", code, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None and process.stdout.readline().strip() == "ready"
        assert inspect_run(tmp_path, "held")["status"] == "running"
        with (
            pytest.raises(WeeklyJournalError, match="Another process"),
            WeeklyRun(tmp_path, "held", {}, ["build"], resume=True).hold(),
        ):
            pytest.fail("Concurrent owner acquired lock")
    finally:
        process.communicate("exit\n", timeout=30)
    assert process.returncode == 0


def test_missing_and_late_completion_need_explicit_expected_time(tmp_path: Path) -> None:
    assert inspect_run(tmp_path, "absent") == {
        "run_id": "absent",
        "status": "not_started",
        "missed": None,
    }
    expected = "2026-09-09T10:00:00Z"
    assert inspect_run(tmp_path, "absent", expected_at_utc=expected, now_utc=expected)["missed"]
    with WeeklyRun(
        tmp_path, "late", {}, ["build"], clock=lambda: "2026-09-09T11:00:00Z"
    ).hold() as run:
        run.stage("build", inputs=[], operation=lambda: artifact(tmp_path / "out"))
        run.finish()
    assert inspect_run(tmp_path, "late", expected_at_utc=expected, now_utc=expected)["missed"]


def test_status_read_handle_and_terminal_replace_share_a_short_metadata_lock(
    tmp_path: Path,
) -> None:
    code = """
import sys
from pathlib import Path
from squadopt.platform.weekly_journal import inspect_run
original = Path.read_bytes
def paused_read(path):
    if path.name == "run.json":
        with path.open("rb") as stream:
            print("handle-open", flush=True)
            sys.stdin.readline()
            return stream.read()
    return original(path)
Path.read_bytes = paused_read
inspect_run(Path(sys.argv[1]), "week")
"""
    with WeeklyRun(tmp_path, "week", {}, ["build"]).hold() as run:
        process = subprocess.Popen(
            [sys.executable, "-B", "-c", code, str(tmp_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        finished = threading.Event()
        errors = []

        def publish() -> None:
            try:
                run.stage("build", inputs=[], operation=lambda: artifact(tmp_path / "out"))
                run.finish()
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=publish)
        try:
            assert process.stdout is not None
            assert process.stdout.readline().strip() == "handle-open"
            worker.start()
            assert not finished.wait(0.1), "Journal replacement crossed an open status reader"
        finally:
            _, stderr = process.communicate("release\n", timeout=30)
            if worker.ident:
                worker.join(timeout=30)
        assert process.returncode == 0, stderr
        assert finished.is_set() and errors == []
    assert inspect_run(tmp_path, "week")["status"] == "completed"


@pytest.mark.parametrize("change", ["json", "stage", "false_completion", "missing_result"])
def test_corrupt_journal_never_reports_success(tmp_path: Path, change: str) -> None:
    with WeeklyRun(tmp_path, "week", {}, ["build"]).hold():
        pass
    path = tmp_path / "week/run.json"
    doc = json.loads(path.read_bytes())
    if change == "stage":
        doc["stages"] = [None]
    elif change == "false_completion":
        doc["status"] = "completed"
    elif change == "missing_result":
        doc["stages"][0]["status"] = "completed"
    path.write_text("{" if change == "json" else json.dumps(doc))
    with pytest.raises(WeeklyJournalError):
        inspect_run(tmp_path, "week")


def test_no_path_traversal_and_no_following_artifact_links(tmp_path: Path) -> None:
    with pytest.raises(WeeklyJournalError):
        WeeklyRun(tmp_path, "../escape", {}, ["build"])
    if os.name == "nt":
        return  # Windows link creation needs host policy; reparse checks share the same guard.
    target = tmp_path / "target"
    target.write_text("private")
    link = tmp_path / "link"
    link.symlink_to(target)
    with (
        WeeklyRun(tmp_path, "week", {}, ["build"]).hold() as run,
        pytest.raises(WeeklyJournalError, match="Symlink"),
    ):
        run.stage("build", inputs=[link], operation=lambda: pytest.fail("Read linked file"))


def _refuse_journal_renames(monkeypatch: pytest.MonkeyPatch, *, times: int) -> list[str]:
    """Refuse the next ``times`` renames onto run.json the way Windows does (WinError 5).

    A reader that holds the journal open outside the metadata lock cannot be provoked on
    demand, so its error is injected. The retry's pauses are skipped, not slept.
    """

    real_replace = os.replace
    refused: list[str] = []

    def held(source: str | Path, destination: str | Path) -> None:
        if str(destination).endswith("run.json") and len(refused) < times:
            refused.append(str(destination))
            raise PermissionError(errno.EACCES, "Access is denied")
        real_replace(source, destination)

    monkeypatch.setattr("squadopt.data.atomic.os.replace", held)
    monkeypatch.setattr("squadopt.data.atomic.time.sleep", lambda _seconds: None)
    return refused


def test_a_journal_write_refused_twice_lands_on_a_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with WeeklyRun(tmp_path, "week", {}, ["build"]).hold() as run:
        refused = _refuse_journal_renames(monkeypatch, times=2)
        run.stage("build", inputs=[], operation=lambda: artifact(tmp_path / "out"))
        run.finish()
    assert len(refused) == 2
    assert inspect_run(tmp_path, "week")["status"] == "completed"
    assert not list((tmp_path / "week").glob(".weekly-*.tmp"))


def test_a_journal_write_refused_on_every_attempt_stops_with_a_named_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = tmp_path / "week" / "run.json"
    with WeeklyRun(tmp_path, "week", {}, ["build"]).hold() as run:
        before = journal.read_bytes()
        refused = _refuse_journal_renames(monkeypatch, times=atomic.RENAME_RETRY_ATTEMPTS)
        with pytest.raises(RenameRefusedError, match="refused on all"):
            run.stage("build", inputs=[], operation=lambda: pytest.fail("Ran unrecorded"))
    assert len(refused) == atomic.RENAME_RETRY_ATTEMPTS
    assert journal.read_bytes() == before
    assert not list((tmp_path / "week").glob(".weekly-*.tmp"))
