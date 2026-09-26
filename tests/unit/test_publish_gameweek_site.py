"""The publish flow: names, refusals, the printed outward steps, the builder that copies a
preview into the publication, and what the manual command checks before it copies.

The gh half is answered in these tests, never called; git runs for real against a bare
origin where a refusal has to be shown to come before any worktree or branch exists.
"""

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts.publish_gameweek_site import KINDS, PublishError, PublishNames, next_steps
from tests.unit.test_weekly_operations import (
    _fake_gh,
    _git,
    _git_checkout,
    _origin_develop_at_head,
)

from squadopt.platform import weekly_operations, weekly_publish
from squadopt.platform._queue_lock import QueueFileLock
from squadopt.platform.weekly_journal import WeeklyRun, WeeklyStageResult
from squadopt.platform.weekly_publish import WEEKLY_RUNS, copy_preview_builder, tree_digests


def test_the_names_are_derived_from_season_gameweek_and_kind() -> None:
    names = PublishNames(season="2026-27", gameweek=2, kind="decision")
    assert names.branch == "feature/gw02-decision-site"
    assert names.worktree_directory == ".codex-tmp/publications/gw02-decision"
    assert names.site_tag == "site-2026-27-gw02-decision"
    assert names.commit_message == "site: publish the gw02 decision view"


def test_settled_names_match_the_deploy_workflow_pattern() -> None:
    names = PublishNames(season="2026-27", gameweek=1, kind="settled")
    # The trusted workflow accepts ^site-\d{4}-\d{2}-gw\d{2}-(decision|settled|fix\d+)$.
    assert names.site_tag == "site-2026-27-gw01-settled"


@pytest.mark.parametrize(
    ("season", "gameweek", "kind"),
    [
        ("2026-27", 0, "decision"),
        ("2026-27", 39, "settled"),
        ("2026/27", 1, "decision"),
        ("2026-27", 1, "preview"),
    ],
)
def test_impossible_inputs_are_refused(season: str, gameweek: int, kind: str) -> None:
    with pytest.raises(PublishError):
        PublishNames(season=season, gameweek=gameweek, kind=kind)


def test_every_kind_has_a_distinct_tag() -> None:
    tags = {PublishNames(season="2026-27", gameweek=3, kind=kind).site_tag for kind in KINDS}
    assert len(tags) == len(KINDS)


def test_the_next_steps_name_the_release_recipe_and_never_a_squash() -> None:
    names = PublishNames(season="2026-27", gameweek=2, kind="decision")
    text = next_steps(names, "https://example.invalid/pr/1")
    assert "https://example.invalid/pr/1" in text
    # The recipe is named rather than copied. `scripts/release/ship.sh` is what changes when
    # the procedure changes, so a second copy in a print statement is a second thing to forget.
    assert "sh scripts/release/ship.sh --dry-run" in text
    assert "site-2026-27-gw02-decision" in text
    assert "docs/deployment_runbook.md" in text
    # The outward half is printed, never performed: these are instructions, not calls.
    assert "Drop --dry-run only when operating it" in text
    # #575 and #638. A squash destroys the ancestry main and develop share, which is what made
    # the release before #523 conflict, and `scripts/release/deploy.sh` refuses such a main.
    assert "two-parent" in text
    assert "Never squash the release to main" in text
    assert "squash PR" not in text


def test_the_dry_run_preview_carries_the_same_release_rule() -> None:
    # `publish` prints these steps on the dry-run path too, before a pull request exists, and
    # the weekly runbook has the operator run that preview first. The rule has to be there.
    names = PublishNames(season="2026-27", gameweek=2, kind="decision")
    text = next_steps(names, "")
    assert "(open it above)" in text
    assert "Never squash the release to main" in text
    assert "squash PR" not in text


SNAPSHOT = "fpl-live-20260911T100000Z-abc123def456"


def _preview(root: Path) -> Path:
    """A preview ``data/`` tree: nested, binary, and bytes a line-ending pass would change."""

    preview = root / "preview" / "data"
    (preview / "league" / "advice" / "101").mkdir(parents=True)
    (preview / "2026-27" / "gw05").mkdir(parents=True)
    (preview / "league" / "members.json").write_bytes(b'{"members": [101]}\n')
    (preview / "league" / "advice" / "101" / "index.json").write_bytes(b'{"a": 1}\r\n{"b": 2}\n')
    (preview / "2026-27" / "gw05" / "live.json").write_bytes(bytes(range(256)))
    return preview


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_builder_replaces_the_carried_tree_with_the_preview_byte_for_byte(
    tmp_path: Path,
) -> None:
    """What the worktree carried from origin/develop does not outlive the copy: a file the
    preview lacks is gone, a file it changed holds the preview's bytes, nothing is rewritten
    on the way, and nothing outside ``data/`` is touched."""

    preview = _preview(tmp_path)
    out = tmp_path / "worktree" / "web" / "public"
    (out / "data" / "league").mkdir(parents=True)
    (out / "data" / "league" / "members.json").write_bytes(b'{"members": []}\n')
    (out / "data" / "league" / "retired.json").write_bytes(b"{}\n")
    (out / "index.html").write_bytes(b"<html></html>\n")
    receipt: dict[str, object] = {}

    copy_preview_builder(preview, receipt)(out)

    assert _tree_bytes(out / "data") == _tree_bytes(preview)
    assert tree_digests(out / "data") == tree_digests(preview)
    assert receipt == {"published_files": 3}
    assert (out / "index.html").read_bytes() == b"<html></html>\n"


def test_a_copy_that_differs_from_the_preview_is_refused_before_a_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    from types import SimpleNamespace

    preview = _preview(tmp_path)

    def torn_copy(source: Path, target: Path) -> Path:
        copied = shutil.copytree(source, target)
        (target / "league" / "members.json").write_bytes(b"torn")
        return Path(copied)

    torn = SimpleNamespace(rmtree=shutil.rmtree, copytree=torn_copy)
    monkeypatch.setattr(weekly_publish, "shutil", torn)
    receipt: dict[str, object] = {}

    with pytest.raises(PublishError, match=r"differs from the preview: league/members\.json"):
        copy_preview_builder(preview, receipt)(tmp_path / "worktree" / "web" / "public")
    assert receipt == {}


def test_the_weekly_run_publishes_through_the_same_builder_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One builder, two callers: the run's publish stage asks the function the manual
    command asks, so both copy a preview and read it back the same way."""

    from squadopt.application.weekly_plan import WeeklyRequest

    assert weekly_operations.copy_preview_builder is weekly_publish.copy_preview_builder

    request = WeeklyRequest(
        "2026-27", 5, 101, snapshot_id=SNAPSHOT, skip_top100=True, workers=1, publish=True
    )
    operation = weekly_operations.WeeklyOperations(
        request,
        weekly_operations.WeeklyPaths.under(tmp_path),
        run_id="one-builder",
        repository_commit="b" * 40,
    )
    operation.run.directory.mkdir(parents=True)
    preview = _preview(operation.paths.out.parent)
    asked: list[Path] = []
    real = weekly_publish.copy_preview_builder

    def spy(source: Path, receipt: dict[str, object] | None = None) -> Callable[[Path], None]:
        asked.append(source)
        return real(source, receipt)

    out = tmp_path / "worktree" / "web" / "public"

    def publish(names: PublishNames, **kwargs: Any) -> int:
        kwargs["builder"](out)
        kwargs["on_published"]({"status": "pr_open"})
        return 0

    monkeypatch.setattr(weekly_operations, "copy_preview_builder", spy)
    monkeypatch.setattr(weekly_operations, "publish", publish)

    result = operation._publish()

    assert asked == [preview]
    assert _tree_bytes(out / "data") == _tree_bytes(preview)
    assert result.value["published_files"] == 3


COMMIT = "c" * 40
STAGES = ("preflight", "capture", "handoff", "league", "site", "scoreboard")


def _stop() -> WeeklyStageResult:
    raise OSError("synthetic stop")


def _journal(
    root: Path,
    run_id: str,
    *,
    recorded: bool = True,
    stop_at: str | None = None,
    publish: bool = False,
) -> Path:
    """A weekly run's journal as the runner leaves it, beside the preview it built.

    The stages are the runner's, in its order. The league, site and scoreboard stages declare
    preview files as their outputs, and the league stage also the member's advice record when
    it recorded one, as ``publish_league`` declares them. ``stop_at`` names a stage that
    failed; every stage after it stays pending. Returns the preview's ``data/``.
    """

    journal = root / WEEKLY_RUNS
    preview = _preview(journal / run_id)
    (preview / "league" / "scoreboard.json").write_bytes(b'{"weeks": []}\n')
    records = root / "data" / "advice_records"
    record = records / "2026-27" / "gw05" / "entry-101" / SNAPSHOT / "advice.json"
    if recorded:
        record.parent.mkdir(parents=True)
        record.write_bytes(b'{"state": {}}\n')
    written = {
        "league": [preview / "league" / "members.json", *([record] if recorded else [])],
        "site": [preview / "2026-27" / "gw05" / "live.json"],
        "scoreboard": [preview / "league" / "scoreboard.json"],
    }
    declaration = {
        "request": {"season": "2026-27", "gameweek": 5, "publish": publish},
        "paths": {"out": str(preview.parent), "records": str(records)},
        "repository_commit": COMMIT,
    }
    planned = [*STAGES, *(["publish"] if publish else [])]
    with WeeklyRun(journal, run_id, declaration, planned).hold() as run:
        for name in STAGES:
            if name == stop_at:
                with pytest.raises(OSError, match="synthetic stop"):
                    run.stage(name, inputs=[], operation=_stop)
                break
            outputs = written.get(name)
            if outputs is None:
                receipt = run.directory / f"{name}.result.json"
                receipt.write_bytes(b"{}\n")
                outputs = [receipt]
            value = {"advice_recorded": recorded} if name == "league" else {}
            run.stage(
                name,
                inputs=[],
                operation=lambda outputs=tuple(outputs), value=value: WeeklyStageResult(
                    outputs, value
                ),
            )
    return preview


def _manual(monkeypatch: pytest.MonkeyPatch, root: Path, *arguments: str) -> int:
    """The manual command, run from ``root`` as the checkout it publishes from."""

    monkeypatch.setattr(weekly_publish, "repository_root", lambda: root)
    monkeypatch.setattr(sys, "argv", ["publish_gameweek_site", *arguments])
    return weekly_publish.main()


def _nothing_published(*_: object, **__: object) -> int:
    raise AssertionError("nothing may be published")


def _no_git(arguments: list[str], *, cwd: Path, check: bool = True) -> str:
    raise AssertionError(f"no git or gh command may run: {arguments}")


DECISION = ("--kind", "decision", "--gameweek", "5")


def test_the_manual_command_publishes_a_finished_runs_preview_from_its_source_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run's journal names the preview and the source revision, and the publish is held
    to that revision (``expected_commit``) through the builder the run's own stage uses."""

    preview = _journal(tmp_path, "finished")
    asked: list[Path] = []
    real = weekly_publish.copy_preview_builder

    def spy(source: Path, receipt: dict[str, object] | None = None) -> Callable[[Path], None]:
        asked.append(source)
        return real(source, receipt)

    out = tmp_path / "worktree" / "web" / "public"
    calls: list[tuple[PublishNames, dict[str, Any]]] = []

    def publish(names: PublishNames, **kwargs: Any) -> int:
        calls.append((names, kwargs))
        kwargs["builder"](out)
        return 0

    monkeypatch.setattr(weekly_publish, "copy_preview_builder", spy)
    monkeypatch.setattr(weekly_publish, "publish", publish)

    assert _manual(monkeypatch, tmp_path, *DECISION, "--run-id", "finished") == 0

    [(names, kwargs)] = calls
    assert names == PublishNames(season="2026-27", gameweek=5, kind="decision")
    assert kwargs["expected_commit"] == COMMIT
    assert kwargs["workspace"] == tmp_path
    assert asked == [preview]
    assert _tree_bytes(out / "data") == _tree_bytes(preview)
    printed = capsys.readouterr().out
    assert f"source revision {COMMIT}; preview {preview}." in printed
    assert "Advice record: written by run finished's league stage" in printed


@pytest.mark.parametrize(
    ("stop_at", "publish", "named"),
    [
        # A --publish run stopped at its scoreboard: the preview still holds the scoreboard
        # the seeded tree carried from the last publication, and the run never reached its
        # publish stage.
        ("scoreboard", True, "scoreboard (failed)"),
        ("site", False, "site (failed), scoreboard (pending)"),
    ],
)
def test_a_run_that_has_not_finished_every_stage_before_publish_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stop_at: str,
    publish: bool,
    named: str,
) -> None:
    _journal(tmp_path, "stopped", stop_at=stop_at, publish=publish)
    monkeypatch.setattr(weekly_publish, "publish", _nothing_published)
    monkeypatch.setattr(weekly_publish, "_run", _no_git)

    assert _manual(monkeypatch, tmp_path, *DECISION, "--run-id", "stopped") == 1

    printed = capsys.readouterr().out
    assert f"Run stopped has not finished every stage before publish: {named}." in printed
    assert "--run-id stopped --resume" in printed


@pytest.mark.parametrize("changed", ["record", "preview"])
def test_a_run_whose_recorded_outputs_changed_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    changed: str,
) -> None:
    """The league stage's outputs include the advice record, so a record removed after the
    run, like a preview file edited after it, stops the publish."""

    preview = _journal(tmp_path, "changed")
    if changed == "record":
        record = tmp_path / "data/advice_records/2026-27/gw05/entry-101" / SNAPSHOT
        (record / "advice.json").unlink()
    else:
        (preview / "league" / "members.json").write_bytes(b"edited after the run\n")
    monkeypatch.setattr(weekly_publish, "publish", _nothing_published)

    assert _manual(monkeypatch, tmp_path, *DECISION, "--run-id", "changed") == 1

    printed = capsys.readouterr().out
    assert "Run changed's league stage outputs no longer hold the bytes the run recorded" in (
        printed
    )


def test_a_run_of_another_week_a_missing_run_and_a_refused_resume_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _journal(tmp_path, "gw05")
    monkeypatch.setattr(weekly_publish, "publish", _nothing_published)

    assert (
        _manual(monkeypatch, tmp_path, "--kind", "decision", "--gameweek", "6", "--run-id", "gw05")
        == 1
    )
    assert "Run gw05 built 2026-27 gameweek 5, not 2026-27 gameweek 6." in capsys.readouterr().out

    assert _manual(monkeypatch, tmp_path, *DECISION, "--run-id", "absent") == 1
    assert "No weekly run absent is journalled under" in capsys.readouterr().out

    journal = tmp_path / WEEKLY_RUNS / "gw05" / "run.json"
    document = json.loads(journal.read_bytes())
    document.update(status="validation_failed", validation_error="Stage inputs changed.")
    journal.write_text(json.dumps(document), encoding="utf-8")
    assert _manual(monkeypatch, tmp_path, *DECISION, "--run-id", "gw05") == 1
    assert "Run gw05's journal refused its own resume: Stage inputs changed." in (
        capsys.readouterr().out
    )


def test_a_run_another_process_owns_is_refused_before_its_journal_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A live run's journal is not read at all: on Windows a reader holding run.json open
    stops the run's next write."""

    from squadopt.platform import weekly_journal

    _journal(tmp_path, "live")
    monkeypatch.setattr(weekly_publish, "publish", _nothing_published)

    def unread(path: Path) -> dict[str, Any]:
        raise AssertionError(f"a live run's journal was read: {path}")

    monkeypatch.setattr(weekly_journal, "_read", unread)
    with QueueFileLock(tmp_path / WEEKLY_RUNS / "live" / ".run.lock", timeout_seconds=0).hold():
        assert _manual(monkeypatch, tmp_path, *DECISION, "--run-id", "live") == 1

    assert "Another process owns weekly run live." in capsys.readouterr().out


def test_the_manual_command_solves_nothing_and_takes_only_what_names_a_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The solver and split-build flags are gone. A decision publish names a run; a settled
    one names a candidate and the revision that built it; each refuses the other's flags."""

    monkeypatch.setattr(weekly_publish, "publish", _nothing_published)
    settled = ("--kind", "settled", "--gameweek", "5")
    candidate = ("--preview", str(tmp_path))
    for arguments in (
        DECISION,
        (*DECISION, *candidate),
        (*DECISION, "--run-id", "r", "--source-commit", COMMIT),
        (*DECISION, "--run-id", "r", "--league", "352490", "--snapshot-id", SNAPSHOT),
        (*DECISION, "--run-id", "r", "--allow-split-build"),
        (*settled, *candidate),
        (*settled, "--source-commit", COMMIT),
        (*settled, *candidate, "--source-commit", COMMIT, "--run-id", "r"),
        (*settled, *candidate, "--source-commit", COMMIT, "--no-advice-record"),
    ):
        with pytest.raises(SystemExit) as stopped:
            _manual(monkeypatch, tmp_path, *arguments)
        assert stopped.value.code == 2, arguments

    assert _manual(monkeypatch, tmp_path, *settled, *candidate, "--source-commit", COMMIT) == 1
    assert "is not a directory. --preview names the settled candidate's" in (
        capsys.readouterr().out
    )
    assert _manual(monkeypatch, tmp_path, *settled, *candidate, "--source-commit", "c0ffee1") == 1
    assert "full 40-character revision" in capsys.readouterr().out


def _recording_git(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every command the publish runs, in order; each still runs as it did before."""

    commands: list[list[str]] = []
    inner = weekly_publish._run

    def run(arguments: list[str], *, cwd: Path, check: bool = True) -> str:
        commands.append(arguments)
        return inner(arguments, cwd=cwd, check=check)

    monkeypatch.setattr(weekly_publish, "_run", run)
    return commands


def _published_tree(tmp_path: Path, origin: Path, branch: str) -> Path:
    """The committed ``web/public/data`` of ``branch``, not a line-ending conversion of it."""

    clone = tmp_path / "published"
    _git(
        tmp_path,
        "-c",
        "core.autocrlf=false",
        "clone",
        "-q",
        "--branch",
        branch,
        str(origin),
        str(clone),
    )
    return clone / "web" / "public" / "data"


def test_a_preview_only_run_is_refused_by_hand_unless_the_switch_publishes_it_unrecorded(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The runbook's standard command has no ``--publish``, so its run records no advice.
    Before the hand publish copied previews it recorded by default and skipping the record
    took ``--no-advice-record``; publishing such a run by hand keeps that rule."""

    tmp_path = tmp_path_factory.mktemp("hand")
    checkout, paths, args = _git_checkout(tmp_path)
    origin = _origin_develop_at_head(checkout)
    _fake_gh(monkeypatch, "https://example.invalid/pr/3")
    assert weekly_operations.main([*args, "--run-id", "preview-only"]) == 0
    assert not paths.records.exists()
    commands = _recording_git(monkeypatch)
    monkeypatch.chdir(checkout)
    hand = ["x", "--kind", "decision", "--gameweek", "2", "--run-id", "preview-only"]
    branch = "feature/gw02-decision-site"

    monkeypatch.setattr(sys, "argv", hand)
    assert weekly_publish.main() == 1

    printed = capsys.readouterr().out
    assert (
        "Run preview-only recorded no advice: it was built without --publish or "
        "--record-advice." in printed
    )
    assert "python -m scripts.run_week --record-advice" in printed
    assert commands == []
    assert _git(checkout, "ls-remote", "--heads", str(origin), branch) == ""

    monkeypatch.setattr(sys, "argv", [*hand, "--no-advice-record"])
    assert weekly_publish.main() == 0

    printed = capsys.readouterr().out
    assert (
        "Advice record: none. Run preview-only recorded no advice, and this publish records "
        "none (--no-advice-record)." in printed
    )
    assert not paths.records.exists()
    preview = paths.journal / "preview-only" / "preview" / "data"
    assert tree_digests(_published_tree(tmp_path, origin, branch)) == tree_digests(preview)


def test_a_recorded_run_is_published_by_hand_only_from_its_own_source_revision(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Develop moves after the run: the hand publish refuses as the run's own publish stage
    does, before ``git worktree add``, with the same recovery. With develop back at the
    run's revision the preview ships byte for byte and the run's record stays where it is."""

    tmp_path = tmp_path_factory.mktemp("rev")
    checkout, paths, args = _git_checkout(tmp_path)
    origin = _origin_develop_at_head(checkout)
    _fake_gh(monkeypatch, "https://example.invalid/pr/4")
    assert weekly_operations.main([*args, "--record-advice", "--run-id", "recorded"]) == 0
    built_at = _git(checkout, "rev-parse", "HEAD")
    moved = _git(checkout, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "merged")
    _git(checkout, "push", "-q", "origin", f"{moved}:refs/heads/develop")
    commands = _recording_git(monkeypatch)
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(
        sys, "argv", ["x", "--kind", "decision", "--gameweek", "2", "--run-id", "recorded"]
    )
    branch = "feature/gw02-decision-site"

    assert weekly_publish.main() == 1

    printed = capsys.readouterr().out
    assert (
        f"The publication base origin/develop is at {moved[:12]} but this run's source "
        f"revision is {built_at[:12]}" in printed
    )
    assert "start a new run" in printed
    assert not any(command[1:3] == ["worktree", "add"] for command in commands)
    assert not (checkout / ".codex-tmp" / "publications" / "gw02-decision").exists()
    assert _git(checkout, "ls-remote", "--heads", str(origin), branch) == ""

    _git(checkout, "push", "-q", "--force", "origin", f"{built_at}:refs/heads/develop")
    assert weekly_publish.main() == 0

    printed = capsys.readouterr().out
    assert f"Advice record: written by run recorded's league stage under {paths.records}." in (
        printed
    )
    preview = paths.journal / "recorded" / "preview" / "data"
    assert tree_digests(_published_tree(tmp_path, origin, branch)) == tree_digests(preview)
    snapshot = args[args.index("--snapshot-id") + 1]
    assert (paths.records / "2026-27/gw02/entry-101" / snapshot / "advice.json").is_file()


def test_a_settled_candidate_is_published_only_from_the_revision_it_names(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A settled candidate records no revision, so the operator names it, and the base is
    checked against that name before any worktree exists."""

    tmp_path = tmp_path_factory.mktemp("set")
    checkout = tmp_path / "checkout"
    (checkout / "web" / "public" / "data").mkdir(parents=True)
    (checkout / "web" / "public" / "data" / "members.json").write_text("previous publication")
    (checkout / ".gitignore").write_text("/.codex-tmp/\n")
    _git(checkout, "init", "-q")
    _git(checkout, "config", "user.name", "Synthetic")
    _git(checkout, "config", "user.email", "synthetic@example.invalid")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "fixture")
    head = _git(checkout, "rev-parse", "HEAD")
    origin = _origin_develop_at_head(checkout)
    _fake_gh(monkeypatch, "https://example.invalid/pr/5")
    commands = _recording_git(monkeypatch)
    # LF text only: the commit is a Git commit, and under the repository's `web/** eol=lf`
    # (or a global core.autocrlf) a CRLF text file is committed with LF endings.
    candidate = tmp_path / "candidate" / "data"
    (candidate / "2026-27" / "gw05").mkdir(parents=True)
    (candidate / "members.json").write_bytes(b'{"members": [101], "settled": true}\n')
    (candidate / "2026-27" / "gw05" / "live.json").write_bytes(bytes(range(256)))
    monkeypatch.chdir(checkout)
    settled = ["x", "--kind", "settled", "--gameweek", "5", "--preview", str(candidate.parent)]

    monkeypatch.setattr(sys, "argv", [*settled, "--source-commit", "d" * 40])
    assert weekly_publish.main() == 1

    assert f"origin/develop is at {head[:12]}" in capsys.readouterr().out
    assert not any(command[1:3] == ["worktree", "add"] for command in commands)

    monkeypatch.setattr(sys, "argv", [*settled, "--source-commit", head])
    assert weekly_publish.main() == 0

    assert f"source revision {head}, as --source-commit states it" in capsys.readouterr().out
    published = _published_tree(tmp_path, origin, "feature/gw05-settled-site")
    assert tree_digests(published) == tree_digests(candidate)


def test_a_settled_candidate_that_would_delete_a_carried_entry_is_refused_before_a_worktree(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The settled publish used to run ``scripts.build_site`` inside the publication
    worktree, over the tree it carries, so the members' ``league/`` tree stayed. The same
    build run into an empty directory lacks it, and copying that candidate in would delete
    it from the site: refused before any worktree exists, naming what is missing and the
    recipe. The recipe's candidate (the carried tree with the settled views written over it)
    ships byte for byte."""

    tmp_path = tmp_path_factory.mktemp("carried")
    checkout = tmp_path / "checkout"
    carried = checkout / "web" / "public" / "data"
    (carried / "league").mkdir(parents=True)
    (carried / "2026-27" / "gw05").mkdir(parents=True)
    (carried / "league" / "members.json").write_bytes(b'{"members": [101]}\n')
    (carried / "2026-27" / "gw05" / "live.json").write_bytes(b'{"settled": false}\n')
    (checkout / ".gitignore").write_text("/.codex-tmp/\n")
    _git(checkout, "init", "-q")
    _git(checkout, "config", "user.name", "Synthetic")
    _git(checkout, "config", "user.email", "synthetic@example.invalid")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "fixture")
    head = _git(checkout, "rev-parse", "HEAD")
    origin = _origin_develop_at_head(checkout)
    _fake_gh(monkeypatch, "https://example.invalid/pr/6")
    commands = _recording_git(monkeypatch)
    monkeypatch.chdir(checkout)
    branch = "feature/gw05-settled-site"
    commit = ("--source-commit", head)

    season_only = tmp_path / "season-only" / "data"
    (season_only / "2026-27" / "gw05").mkdir(parents=True)
    (season_only / "2026-27" / "gw05" / "live.json").write_bytes(b'{"settled": true}\n')
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "x",
            "--kind",
            "settled",
            "--gameweek",
            "5",
            "--preview",
            str(season_only.parent),
            *commit,
        ],
    )
    assert weekly_publish.main() == 1

    printed = capsys.readouterr().out
    assert f"The settled candidate {season_only.resolve()} lacks league" in printed
    assert "copy web/public/data to <dir>/data" in printed
    assert "build_settled_site builds only the 2026-27 gameweek 5 candidate" in printed
    assert not any(command[1:3] == ["worktree", "add"] for command in commands)
    assert _git(checkout, "ls-remote", "--heads", str(origin), branch) == ""

    recipe = tmp_path / "recipe" / "data"
    shutil.copytree(carried, recipe)
    (recipe / "2026-27" / "gw05" / "live.json").write_bytes(b'{"settled": true}\n')
    monkeypatch.setattr(
        sys,
        "argv",
        ["x", "--kind", "settled", "--gameweek", "5", "--preview", str(recipe.parent), *commit],
    )
    assert weekly_publish.main() == 0

    published = _published_tree(tmp_path, origin, branch)
    assert tree_digests(published) == tree_digests(recipe)
    assert (published / "league" / "members.json").read_bytes() == b'{"members": [101]}\n'


def test_the_publish_worktree_anchors_to_the_checkout_whatever_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured before the fix: a default bound to the working directory at import landed
    under the subdirectory the operator started from (``docs/data/...``). The checkout is
    resolved when the publish asks for it, from Git."""

    import subprocess

    from squadopt.platform.weekly_publish import repository_root

    checkout = tmp_path / "checkout"
    (checkout / "docs").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True, capture_output=True)
    monkeypatch.chdir(checkout / "docs")

    assert repository_root() == checkout.resolve()


def test_a_publish_never_runs_a_build_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The builder runs in process; no interpreter is shelled out, and a publish that was
    handed no builder is refused before a worktree exists."""

    import sys

    from squadopt.platform import weekly_publish

    built: list[Path] = []
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    commands: list[list[str]] = []

    def fake_run(arguments: list[str], *, cwd: Path, check: bool = True) -> str:
        commands.append(arguments)
        return ""

    monkeypatch.setattr(weekly_publish, "_run", fake_run)
    names = PublishNames(season="2026-27", gameweek=4, kind="decision")

    exit_code = weekly_publish.publish(
        names, force_branch=False, dry_run=False, workspace=workspace, builder=built.append
    )

    # An empty `git status --porcelain` is "the build changed nothing"; the point here is
    # that the builder ran and no build subprocess was ever shelled out.
    assert exit_code == 0
    assert built == [workspace / ".codex-tmp" / "publications" / "gw04-decision" / "web" / "public"]
    assert not any(argument[:1] == [sys.executable] for argument in commands)

    commands.clear()
    with pytest.raises(PublishError, match="copy_preview_builder"):
        weekly_publish.publish(names, force_branch=False, dry_run=False, workspace=workspace)
    assert not any(argument[1:3] == ["worktree", "add"] for argument in commands)
