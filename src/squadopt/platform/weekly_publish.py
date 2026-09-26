r"""Publish one gameweek's site view: worktree, copy, commit, push, PR, in one command.

    python -m scripts.publish_gameweek_site --kind decision --gameweek 2 --run-id <run>
    python -m scripts.publish_gameweek_site --kind settled  --gameweek 1 \
        --preview <dir> --source-commit <revision>

The Friday decision publish and the Monday settled publish share one shape, and every
step of it used to be typed by hand under deadline pressure. This wraps the *local and
repository* half (a fresh worktree from ``origin/develop``, the preview copied into it, the
commit, the push, the pull request) and then prints, rather than performs, the
deliberate outward half: the merge, the develop-to-main release, the immutable
``site-...`` tag, and the Pages dispatch. Those stay human on purpose: no cron, no
auto-release, a person reads before production changes.

Idempotent by construction: an existing worktree directory is refused with the command
to remove it; an existing branch is reused only with ``--force-branch``; a copy that
changes nothing stops before creating an empty commit; a PR that already exists is
reported, not duplicated. Nothing here touches ``data/ledger``: settle itself is
``squadopt gameweek settle`` and stays a separate, deliberate act.

Nothing is solved or built here, and a tree is copied only through
:func:`copy_preview_builder`, the builder the weekly run's own ``publish`` stage uses.

A decision publish names a weekly run by ``--run-id`` (``python -m scripts.run_week`` prints
it as ``Weekly run:``) and ships that run's preview only after the checks the run's own
``publish`` stage stands on, read from the run's journal: every stage before ``publish``
completed and the league, site and scoreboard outputs still hold the bytes the run recorded;
the publication base ``origin/develop`` is the run's source revision; and the run's league
stage wrote the immutable advice record from the solve that ships. A run that recorded no
advice (one built without ``--publish`` or ``--record-advice``, or with
``--no-advice-record``) is refused unless ``--no-advice-record`` says to publish it
unrecorded, and the publish then says so.

A settled publish names a settled candidate by ``--preview`` and, with ``--source-commit``,
the revision it was built from; a candidate records no revision of its own, so the base is
checked against the operator's statement. For any gameweek the candidate is built in a clean
checkout at ``origin/develop``::

    mkdir <dir> && cp -r web/public/data <dir>/data
    python -m scripts.build_site --season 2026-27 --out <dir>

``scripts.build_site`` writes the settled season views over that copy and leaves the members'
``league/`` tree and the rest as the site carries them, which is what the settled publish did
when it ran that build inside the publication worktree. ``python -m scripts.build_settled_site``
builds only the 2026-27 gameweek 5 candidate. A candidate that lacks a top-level entry of the
carried tree is refused, because the copy would delete it from the site.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from squadopt.platform.weekly_journal import WeeklyJournalError, held_run, verify_stage_outputs

KINDS = ("decision", "settled")
WEEKLY_RUNS = Path("data/runtime/weekly")
"""Where a weekly run journals itself under its workspace; its default preview sits beside."""
PREVIEW_STAGES = ("league", "site", "scoreboard")
"""The run's stages that write the preview; the league stage also writes the advice record."""
_REVISION = re.compile(r"[0-9a-f]{40}")
SETTLED_RECIPE = (
    "A settled candidate for any gameweek is built in a clean checkout at origin/develop: copy "
    "web/public/data to <dir>/data, then run python -m scripts.build_site --season <season> "
    "--out <dir>, which writes the settled season views over that copy and leaves the rest "
    "of it as the site carries it. python -m scripts.build_settled_site builds only the "
    "2026-27 gameweek 5 candidate."
)
"""How a settled candidate is produced, named wherever a settled publish refuses one."""


def repository_root() -> Path:
    """The checkout a manual publish creates its publication worktree from.

    Resolved when it is asked for, at the publish itself, never at import. A default bound
    to the working directory at import time anchored every root under whatever subdirectory
    the operator started from (measured: ``docs/data/snapshots`` and its four siblings),
    while the Git commands, run from the same place, found the checkout on their own. The
    Git top level is the checkout; outside any checkout, the working directory is all there
    is.
    """

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
    except OSError:
        return Path.cwd().resolve()
    if completed.returncode != 0:
        return Path.cwd().resolve()
    return Path(completed.stdout.strip()).resolve()


class PublishError(RuntimeError):
    """A step refused; the message says which and why."""


@dataclass(frozen=True, slots=True)
class PublishNames:
    """Every name the publish flow derives from (season, gameweek, kind)."""

    season: str
    gameweek: int
    kind: str
    suffix: str = ""

    def __post_init__(self) -> None:
        if self.suffix and not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", self.suffix):
            raise PublishError("Publish suffix must contain letters, digits or single hyphens.")
        if self.kind not in KINDS:
            raise PublishError(f"kind must be one of {KINDS}, got {self.kind!r}.")
        if not 1 <= int(self.gameweek) <= 38:
            raise PublishError(f"gameweek must be 1..38, got {self.gameweek!r}.")
        season = str(self.season)
        if len(season) != 7 or season[4] != "-":
            raise PublishError(f"season must look like 2026-27, got {season!r}.")

    @property
    def branch(self) -> str:
        suffix = f"-{self.suffix}" if self.suffix else ""
        return f"feature/gw{self.gameweek:02d}-{self.kind}-site{suffix}"

    @property
    def worktree_directory(self) -> str:
        suffix = f"-{self.suffix}" if self.suffix else ""
        return f".codex-tmp/publications/gw{self.gameweek:02d}-{self.kind}{suffix}"

    @property
    def site_tag(self) -> str:
        return f"site-{self.season}-gw{self.gameweek:02d}-{self.kind}"

    @property
    def commit_message(self) -> str:
        return f"site: publish the gw{self.gameweek:02d} {self.kind} view"

    @property
    def pr_title(self) -> str:
        return self.commit_message


def _run(arguments: list[str], *, cwd: Path, check: bool = True) -> str:
    completed = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True)
    if check and completed.returncode != 0:
        raise PublishError(
            f"`{' '.join(arguments)}` failed ({completed.returncode}):\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout.strip()


def check_publication_base(root: Path, expected_commit: str) -> None:
    """Refuse a publication whose base is not the run's own source revision.

    A week is published from the revision the fresh ``origin/develop`` holds, so the site
    PR carries generated data on top of code develop already has and nothing else. Checked
    twice on purpose: by the weekly preflight, before a capture or a solve is spent on a run
    this stage would refuse hours later, and again here as the backstop, because develop can
    move while the run is under way.
    """

    _run(["git", "fetch", "origin"], cwd=root)
    base = _run(["git", "rev-parse", "origin/develop"], cwd=root)
    if base != expected_commit:
        raise PublishError(
            f"The publication base origin/develop is at {base[:12]} but this run's source "
            f"revision is {expected_commit[:12]}; a week is published only from the revision "
            "develop holds. Recovery: merge the pending change into develop, or check out "
            "the fresh origin/develop (git fetch origin && git switch develop && git pull "
            "--ff-only) and confirm the checkout is clean; then start a new run -- a resumed "
            "run keeps its recorded source revision."
        )


def tree_digests(root: Path) -> dict[str, str]:
    """Every file under ``root`` by its relative path, with the SHA-256 of its bytes."""

    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def copy_preview_builder(
    preview: Path, receipt: dict[str, object] | None = None
) -> Callable[[Path], None]:
    """The builder that publishes an existing preview's ``data/`` tree, and nothing else.

    The weekly run's ``publish`` stage and the manual command both hand :func:`publish` this
    builder, so both copy a preview and read it back the same way. What decides whether a
    preview may ship at all (its run finished, its source revision is the base, its advice
    was recorded) is checked before this builder is asked for: by the run's own stages, or
    by :func:`run_preview` for a manual publish. ``receipt``, when given, receives the number
    of files copied under ``published_files``.
    """

    def build(out: Path) -> None:
        # The preview is the publication. The tree the worktree carries from
        # origin/develop goes first, so nothing under it outlives the preview, and the
        # copy is then read back against the preview before a commit can name it.
        target = out / "data"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(preview, target)
        expected, actual = tree_digests(preview), tree_digests(target)
        names = expected.keys() | actual.keys()
        differing = sorted(name for name in names if expected.get(name) != actual.get(name))
        if differing:
            raise PublishError(
                "The publication copy differs from the preview: " + ", ".join(differing[:12])
            )
        if receipt is not None:
            receipt["published_files"] = len(actual)

    return build


@dataclass(frozen=True, slots=True)
class RunPreview:
    """What a weekly run's journal says about the preview it built."""

    preview: Path
    """The run's ``<out>/data`` tree: what ships."""
    source_commit: str
    """The revision the run was declared under; the publication base must be the same."""
    advice_recorded: bool
    """Whether the run's league stage wrote the advice record from the solve that ships."""
    records: Path
    """Where that record lives: the run's advice record root."""
    no_advice_record: bool
    """Whether the run itself was told ``--no-advice-record``."""


def run_preview(document: Mapping[str, Any], run_id: str, names: PublishNames) -> RunPreview:
    """Refuse a run whose preview the run itself would not have published.

    The run's ``publish`` stage starts only after every earlier stage completed, publishes
    only from the run's own source revision, and follows a league stage that recorded the
    advice unless the run was told ``--no-advice-record``. The first is checked here against
    the run's journal: every stage before
    ``publish`` completed, and the league, site and scoreboard outputs (the league stage's
    include the advice record files) still hold the bytes the run recorded. The revision and
    whether the advice was recorded are returned for the manual publish to hold itself to.
    """

    if document.get("status") == "validation_failed":
        raise PublishError(
            f"Run {run_id}'s journal refused its own resume: "
            f"{document.get('validation_error', 'no reason recorded')}. Its preview is not "
            "published; start a new run."
        )
    declaration = document["request"]
    request = declaration.get("request") or {}
    if (request.get("season"), request.get("gameweek")) != (names.season, names.gameweek):
        raise PublishError(
            f"Run {run_id} built {request.get('season')} gameweek {request.get('gameweek')}, "
            f"not {names.season} gameweek {names.gameweek}."
        )
    stages = list(document["stages"])
    planned = [stage["name"] for stage in stages]
    absent = [name for name in PREVIEW_STAGES if name not in planned]
    if absent:
        raise PublishError(f"Run {run_id} plans no {', '.join(absent)} stage.")
    before = stages[: planned.index("publish")] if "publish" in planned else stages
    unfinished = [
        f"{stage['name']} ({stage['status']})"
        for stage in before
        if stage["status"] not in {"completed", "skipped"}
    ]
    if unfinished:
        raise PublishError(
            f"Run {run_id} has not finished every stage before publish: "
            f"{', '.join(unfinished)}. A preview ships only once its run has built all of it, "
            "or the files an unfinished stage would have rewritten ship as the tree that "
            "seeded it left them. Recovery: resume the run (python -m scripts.run_week with "
            f"its arguments and --run-id {run_id} --resume) and publish once it completes."
        )
    for stage in before:
        if stage["name"] in PREVIEW_STAGES:
            try:
                verify_stage_outputs(stage)
            except (OSError, WeeklyJournalError) as error:
                raise PublishError(
                    f"Run {run_id}'s {stage['name']} stage outputs no longer hold the bytes "
                    f"the run recorded ({error}). Its preview is not published; start a new "
                    "run."
                ) from error
    commit = declaration.get("repository_commit")
    paths = declaration.get("paths") or {}
    if not isinstance(commit, str) or not commit or "out" not in paths or "records" not in paths:
        raise PublishError(
            f"Run {run_id}'s journal names no source revision or preview; it cannot be "
            "published by hand."
        )
    league = stages[planned.index("league")]
    options = declaration.get("publication_options") or {}
    return RunPreview(
        preview=Path(paths["out"]) / "data",
        source_commit=commit,
        advice_recorded=league["value"].get("advice_recorded") is True,
        records=Path(paths["records"]),
        no_advice_record=options.get("no_advice_record") is True,
    )


def next_steps(names: PublishNames, pr_url: str) -> str:
    """The outward half, printed for a person rather than performed."""

    return "\n".join(
        [
            "",
            "Deliberate steps left to a person, in order:",
            f"  1. Merge the PR once CI is green: {pr_url or '(open it above)'}",
            "  2. Release with the recipe. It cuts the two-parent release whose tree equals",
            "     develop, verifies both properties, merges the release PR, tags, dispatches",
            "     and verifies the live site:",
            f"       sh scripts/release/ship.sh --dry-run <site-PR> {names.site_tag} \\",
            "         <release-branch> <accepted-generated-at-ISO> '<summary sentence>'",
            "     Drop --dry-run only when operating it; a settled tag takes its gameweek",
            "     as a sixth argument.",
            "  3. Never squash the release to main. A squash destroys the ancestry main and",
            "     develop share, which is what made the release before #523 conflict in every",
            "     file both had touched, and scripts/release/deploy.sh refuses a main that is",
            "     not a two-parent merge whose tree equals develop.",
            '  4. docs/deployment_runbook.md, "Release in one command", carries the arguments,',
            "     the waits, and the recovery path once the window is already open.",
        ]
    )


def publish(
    names: PublishNames,
    *,
    force_branch: bool,
    dry_run: bool,
    workspace: Path | None = None,
    builder: Callable[[Path], None] | None = None,
    expected_commit: str | None = None,
    on_published: Callable[[Mapping[str, object]], None] | None = None,
) -> int:
    root = (workspace or repository_root()).resolve()
    worktree = (root / names.worktree_directory).resolve()
    if worktree == root or root not in worktree.parents:
        raise PublishError("Publication worktree must remain inside its explicit workspace.")
    if worktree.exists():
        raise PublishError(
            f"{worktree} already exists. Finish or remove it first:\n"
            f"  git worktree remove {names.worktree_directory} --force"
        )
    if expected_commit is not None:
        # The backstop of the weekly preflight's check; the fetch it does is the one the
        # worktree below is created from.
        check_publication_base(root, expected_commit)
    else:
        _run(["git", "fetch", "origin"], cwd=root)
    branch_exists = (
        _run(
            ["git", "ls-remote", "--heads", "origin", names.branch],
            cwd=root,
            check=False,
        )
        != ""
    )
    if branch_exists and not force_branch:
        raise PublishError(
            f"Branch {names.branch} already exists on origin. Re-running a publish is fine, "
            "but say so: pass --force-branch to reuse it or choose another --publish-suffix."
        )
    if dry_run:
        print(f"dry run: would create {names.branch} in {worktree}, build, commit, push, PR.")
        print(next_steps(names, ""))
        return 0
    if builder is None:
        raise PublishError(
            "A publish copies an existing preview; pass the builder copy_preview_builder "
            "returns for it."
        )

    branch_flag = "-B" if branch_exists else "-b"
    _run(
        ["git", "worktree", "add", branch_flag, names.branch, str(worktree), "origin/develop"],
        cwd=root,
    )
    try:
        builder(worktree / "web" / "public")
        _run(["git", "add", "web/public/data"], cwd=worktree)
        if _run(["git", "status", "--porcelain"], cwd=worktree) == "":
            print("The build changed nothing; there is nothing to publish.")
            if on_published is not None:
                on_published({"status": "unchanged", "source_commit": expected_commit})
            return 0
        _run(["git", "commit", "-m", names.commit_message], cwd=worktree)
        _run(["git", "push", "-u", "origin", f"{names.branch}:{names.branch}"], cwd=worktree)
        existing = _run(
            ["gh", "pr", "list", "--head", names.branch, "--json", "url", "-q", ".[0].url"],
            cwd=worktree,
            check=False,
        )
        if existing:
            pr_url = existing
            print(f"PR already open: {pr_url}")
        else:
            body = worktree / ".publication-pr-body.md"
            body.write_text(
                f"The gw{names.gameweek:02d} {names.kind} view rendered from the local "
                "ledger by scripts.publish_gameweek_site. Raw ledger and handoffs stay "
                "local; only generated public view data enters this branch.",
                encoding="utf-8",
            )
            pr_url = _run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--base",
                    "develop",
                    "--title",
                    names.pr_title,
                    "--body-file",
                    str(body),
                ],
                cwd=worktree,
            )
            print(f"PR: {pr_url}")
        if on_published is not None:
            published = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
            proof = json.loads(
                _run(
                    ["gh", "pr", "view", pr_url, "--json", "url,headRefOid,state"],
                    cwd=worktree,
                )
            )
            if proof.get("headRefOid") != published or proof.get("state") != "OPEN":
                raise PublishError(
                    "The remote PR does not confirm the generated publication commit."
                )
            on_published(
                {
                    "status": "pr_open",
                    "source_commit": expected_commit,
                    "publication_commit": published,
                    "pr_url": proof["url"],
                }
            )
    finally:
        _run(["git", "worktree", "remove", str(worktree), "--force"], cwd=root, check=False)
    print(next_steps(names, pr_url))
    return 0


def _publish_run(
    names: PublishNames,
    root: Path,
    run_id: str,
    *,
    no_advice_record: bool,
    force_branch: bool,
    dry_run: bool,
) -> int:
    """Publish a weekly run's preview, held to what the run's own publish stage holds it to.

    The run stays owned while it is published, so no resume of it rewrites the preview
    mid-copy, and the base is checked against the run's recorded source revision, the check
    whose recovery is to start a new run.
    """

    with held_run(root / WEEKLY_RUNS, run_id) as document:
        found = run_preview(document, run_id, names)
        if not found.advice_recorded and not no_advice_record:
            built = (
                "it was built with --no-advice-record"
                if found.no_advice_record
                else "it was built without --publish or --record-advice"
            )
            raise PublishError(
                f"Run {run_id} recorded no advice: {built}. A publication with no record "
                "of what each member was told cannot be reviewed later. Recovery: rebuild "
                "the week with python -m scripts.run_week --record-advice (or --publish) "
                "under a new run ID and publish that run; or pass --no-advice-record to "
                "publish this one without a record."
            )
        if not found.preview.is_dir():
            raise PublishError(f"Run {run_id}'s preview {found.preview} is not a directory.")
        print(
            f"Run {run_id}: every stage before publish completed; source revision "
            f"{found.source_commit}; preview {found.preview}."
        )
        if found.advice_recorded:
            print(f"Advice record: written by run {run_id}'s league stage under {found.records}.")
        else:
            print(
                f"Advice record: none. Run {run_id} recorded no advice, and this publish "
                "records none (--no-advice-record)."
            )
        return publish(
            names,
            force_branch=force_branch,
            dry_run=dry_run,
            workspace=root,
            builder=copy_preview_builder(found.preview),
            expected_commit=found.source_commit,
        )


def _publish_candidate(
    names: PublishNames,
    root: Path,
    candidate: Path,
    source_commit: str,
    *,
    force_branch: bool,
    dry_run: bool,
) -> int:
    """Publish a settled candidate from the revision the operator says built it.

    A settled candidate is the carried tree with the settled views written over it, so it
    holds every top-level entry the publication worktree carries. One that lacks any of them
    (the members' ``league/`` tree above all, which a ``scripts.build_site`` run into an empty
    directory never writes) is refused before a commit: the copy would delete it from the
    site.
    """

    if not _REVISION.fullmatch(source_commit):
        raise PublishError(
            "--source-commit must be the full 40-character revision the candidate was "
            "built from (git rev-parse HEAD in the checkout that built it)."
        )
    preview = candidate.resolve() / "data"
    if not preview.is_dir():
        raise PublishError(
            f"{preview} is not a directory. --preview names the settled candidate's "
            f"directory, the one holding data/. {SETTLED_RECIPE}"
        )
    print(
        f"Settled candidate {preview}; source revision {source_commit}, as --source-commit "
        "states it (the candidate records none of its own)."
    )
    copy = copy_preview_builder(preview)

    def refuse_what_it_would_delete(carried: list[str]) -> None:
        lacking = sorted(name for name in carried if not (preview / name).exists())
        if lacking:
            raise PublishError(
                f"The settled candidate {preview} lacks {', '.join(lacking)}, which the "
                "publication carries from origin/develop; publishing it would delete them "
                f"from the site. {SETTLED_RECIPE}"
            )

    # Checked before any worktree exists from the named revision, which the base must equal,
    # when this checkout holds it; the build below checks the worktree's own tree again.
    listed = _run(
        ["git", "ls-tree", "--name-only", f"{source_commit}:web/public/data"],
        cwd=root,
        check=False,
    )
    if listed:
        refuse_what_it_would_delete(listed.splitlines())

    def build(out: Path) -> None:
        carried = out / "data"
        refuse_what_it_would_delete(
            [entry.name for entry in carried.iterdir()] if carried.is_dir() else []
        )
        copy(out)

    return publish(
        names,
        force_branch=force_branch,
        dry_run=dry_run,
        workspace=root,
        builder=build,
        expected_commit=source_commit,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--gameweek", type=int, required=True)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument(
        "--run-id",
        help="decision: the weekly run whose preview ships, as scripts.run_week printed it "
        "after Weekly run:; its journal names the preview, the source revision and whether "
        "the advice was recorded",
    )
    parser.add_argument(
        "--no-advice-record",
        action="store_true",
        help="decision: publish a run that recorded no advice; the publish says it records none",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        help="settled: the candidate directory holding data/: a copy of web/public/data "
        "with scripts.build_site --out <dir> run over it (scripts.build_settled_site "
        "builds only 2026-27 gameweek 5)",
    )
    parser.add_argument(
        "--source-commit",
        help="settled: the full revision the candidate was built from; origin/develop must "
        "be at it",
    )
    parser.add_argument("--force-branch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    run_id: str | None = arguments.run_id
    candidate: Path | None = arguments.preview
    source_commit: str | None = arguments.source_commit
    # A usage error exits 2 through argparse before anything is read; only a refusal of what
    # was named is caught below.
    try:
        if arguments.kind == "decision":
            if run_id is None:
                parser.error("--kind decision needs --run-id, the weekly run whose preview ships")
            if candidate is not None or source_commit is not None:
                parser.error(
                    "--kind decision reads its preview and source revision from the run's "
                    "journal; --preview and --source-commit are for --kind settled"
                )
            return _publish_run(
                PublishNames(season=arguments.season, gameweek=arguments.gameweek, kind="decision"),
                repository_root(),
                run_id,
                no_advice_record=arguments.no_advice_record,
                force_branch=arguments.force_branch,
                dry_run=arguments.dry_run,
            )
        if candidate is None or source_commit is None:
            parser.error("--kind settled needs --preview and --source-commit")
        if run_id is not None or arguments.no_advice_record:
            parser.error("--run-id and --no-advice-record are for --kind decision")
        return _publish_candidate(
            PublishNames(season=arguments.season, gameweek=arguments.gameweek, kind="settled"),
            repository_root(),
            candidate,
            source_commit,
            force_branch=arguments.force_branch,
            dry_run=arguments.dry_run,
        )
    except (PublishError, WeeklyJournalError) as error:
        print(f"Refused: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
