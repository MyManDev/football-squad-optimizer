"""The publish flow's pure half: names, refusals, the printed outward steps, and the builder
that copies a preview into the publication.

The git/gh subprocess half is deliberately thin and exercised by the operator; what a
test can pin is everything derived, everything refused, and every byte copied.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts.publish_gameweek_site import KINDS, PublishError, PublishNames, next_steps

from squadopt.platform.weekly_publish import copy_preview_builder, tree_digests


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

    from squadopt.platform import weekly_publish

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
    command asks, so a manual publish of a preview ships what the run would have shipped."""

    from squadopt.application.weekly_plan import WeeklyRequest
    from squadopt.platform import weekly_operations, weekly_publish

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


def test_the_manual_command_publishes_the_named_preview_through_the_same_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from squadopt.platform import weekly_publish

    preview = _preview(tmp_path)
    asked: list[Path] = []
    real = weekly_publish.copy_preview_builder

    def spy(source: Path, receipt: dict[str, object] | None = None) -> Callable[[Path], None]:
        asked.append(source)
        return real(source, receipt)

    out = tmp_path / "worktree" / "web" / "public"
    published: list[PublishNames] = []

    def publish(names: PublishNames, **kwargs: Any) -> int:
        published.append(names)
        kwargs["builder"](out)
        return 0

    monkeypatch.setattr(weekly_publish, "copy_preview_builder", spy)
    monkeypatch.setattr(weekly_publish, "publish", publish)
    monkeypatch.setattr(
        sys,
        "argv",
        ["x", "--kind", "decision", "--gameweek", "5", "--preview", str(preview.parent)],
    )

    assert weekly_publish.main() == 0

    assert published == [PublishNames(season="2026-27", gameweek=5, kind="decision")]
    assert asked == [preview.parent.resolve() / "data"]
    assert _tree_bytes(out / "data") == _tree_bytes(preview)


def test_the_manual_command_solves_nothing_and_needs_a_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The solver and split-build flags are gone, ``--preview`` is required, and a preview
    without a ``data/`` tree is refused before anything is published."""

    import sys

    from squadopt.platform import weekly_publish

    def refuse(*_: object, **__: object) -> int:
        raise AssertionError("nothing may be published")

    monkeypatch.setattr(weekly_publish, "publish", refuse)
    base = ["x", "--kind", "decision", "--gameweek", "5"]
    for argv in (
        base,
        [*base, "--preview", str(tmp_path), "--league", "352490", "--snapshot-id", SNAPSHOT],
        [*base, "--preview", str(tmp_path), "--allow-split-build"],
    ):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as stopped:
            weekly_publish.main()
        assert stopped.value.code == 2

    monkeypatch.setattr(sys, "argv", [*base, "--preview", str(tmp_path)])
    assert weekly_publish.main() == 1
    assert "scripts.run_week" in capsys.readouterr().out


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
