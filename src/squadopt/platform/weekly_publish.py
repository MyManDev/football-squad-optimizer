"""Publish one gameweek's site view: worktree, copy, commit, push, PR, in one command.

    python -m scripts.publish_gameweek_site --kind decision --gameweek 2 --preview <dir>
    python -m scripts.publish_gameweek_site --kind settled  --gameweek 1 --preview <dir>

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

Nothing is solved or built here. ``--preview`` names a preview a weekly run already built
(``python -m scripts.run_week`` prints it as ``Preview:``), and its ``data/`` tree is
published by :func:`copy_preview_builder`, the builder the weekly run's own ``publish``
stage uses. A week is rebuilt with ``python -m scripts.run_week`` and its resumable stages;
its league stage writes the immutable advice record from the solve that ships.
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

KINDS = ("decision", "settled")


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
    builder, so a manual publish ships a preview exactly as the run would have. ``receipt``,
    when given, receives the number of files copied under ``published_files``.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--gameweek", type=int, required=True)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument(
        "--preview",
        type=Path,
        required=True,
        help="the preview a weekly run built, as scripts.run_week prints it after Preview:; "
        "its data/ tree is what ships",
    )
    parser.add_argument("--force-branch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    try:
        names = PublishNames(
            season=arguments.season, gameweek=arguments.gameweek, kind=arguments.kind
        )
        preview = arguments.preview.resolve() / "data"
        if not preview.is_dir():
            raise PublishError(
                f"{preview} is not a directory. --preview names the directory a weekly run "
                "printed after Preview:, the one holding data/. A week is built with "
                "python -m scripts.run_week."
            )
        return publish(
            names,
            force_branch=arguments.force_branch,
            dry_run=arguments.dry_run,
            builder=copy_preview_builder(preview),
        )
    except PublishError as error:
        print(f"Refused: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
