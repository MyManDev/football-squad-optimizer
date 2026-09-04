"""Publish one gameweek's site view: worktree, build, commit, push, PR — one command.

    python -m scripts.publish_gameweek_site --kind decision --gameweek 2
    python -m scripts.publish_gameweek_site --kind settled  --gameweek 1

The Friday decision publish and the Monday settled publish share one shape, and every
step of it used to be typed by hand under deadline pressure. This wraps the *local and
repository* half — a fresh worktree from ``origin/develop``, ``build_site`` into it, the
commit, the push, the pull request — and then prints, rather than performs, the
deliberate outward half: the merge, the develop-to-main release, the immutable
``site-...`` tag, and the Pages dispatch. Those stay human on purpose: no cron, no
auto-release, a person reads before production changes.

Idempotent by construction: an existing worktree directory is refused with the command
to remove it; an existing branch is reused only with ``--force-branch``; a build that
changes nothing stops before creating an empty commit; a PR that already exists is
reported, not duplicated. Nothing here touches ``data/ledger`` — settle itself is
``squadopt gameweek settle`` and stays a separate, deliberate act.
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

KINDS = ("decision", "settled")


class PublishError(RuntimeError):
    """A step refused; the message says which and why."""


@dataclass(frozen=True, slots=True)
class PublishNames:
    """Every name the publish flow derives from (season, gameweek, kind)."""

    season: str
    gameweek: int
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise PublishError(f"kind must be one of {KINDS}, got {self.kind!r}.")
        if not 1 <= int(self.gameweek) <= 38:
            raise PublishError(f"gameweek must be 1..38, got {self.gameweek!r}.")
        season = str(self.season)
        if len(season) != 7 or season[4] != "-":
            raise PublishError(f"season must look like 2026-27, got {season!r}.")

    @property
    def branch(self) -> str:
        return f"feature/gw{self.gameweek:02d}-{self.kind}-site"

    @property
    def worktree_directory(self) -> str:
        return f"../squadopt-gw{self.gameweek:02d}-{self.kind}"

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


def next_steps(names: PublishNames, pr_url: str) -> str:
    """The outward half, printed for a person rather than performed."""

    return "\n".join(
        [
            "",
            "Deliberate steps left to a person, in order:",
            f"  1. Merge the PR once CI is green: {pr_url or '(open it above)'}",
            "  2. Release develop to main (squash PR titled 'release: ...'); wait for the",
            "     green main-push CI.",
            f'  3. git tag -a {names.site_tag} <main-sha> -m "{names.site_tag}"',
            f"     git push origin {names.site_tag}",
            '  4. Dispatch the trusted workflow: gh workflow run "Deploy Pages" --ref develop '
            f"-f release_tag={names.site_tag}",
            "  5. Watch the run summary: budget, upload, identity, smoke — 7/7 or investigate.",
        ]
    )


def publish(names: PublishNames, *, force_branch: bool, dry_run: bool) -> int:
    root = REPOSITORY_ROOT
    worktree = (root / names.worktree_directory).resolve()
    if worktree.exists():
        raise PublishError(
            f"{worktree} already exists. Finish or remove it first:\n"
            f"  git worktree remove {names.worktree_directory} --force"
        )
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
            "but say so: pass --force-branch to reuse it."
        )
    if dry_run:
        print(f"dry run: would create {names.branch} in {worktree}, build, commit, push, PR.")
        print(next_steps(names, ""))
        return 0

    branch_flag = "-B" if branch_exists else "-b"
    _run(
        ["git", "worktree", "add", branch_flag, names.branch, str(worktree), "origin/develop"],
        cwd=root,
    )
    try:
        build = _run(
            [
                sys.executable,
                "-m",
                "scripts.build_site",
                "--season",
                names.season,
                "--ledger-root",
                str(root / "data" / "ledger"),
                "--snapshot-root",
                str(root / "data" / "snapshots"),
                "--log-root",
                str(root / "data" / "logs" / "season_tick"),
                "--out",
                str(worktree / "web" / "public"),
            ],
            cwd=worktree,
        )
        print(build)
        _run(["git", "add", "web/public/data"], cwd=worktree)
        if _run(["git", "status", "--porcelain"], cwd=worktree) == "":
            print("The build changed nothing; there is nothing to publish.")
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
            pr_url = _run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--base",
                    "develop",
                    "--title",
                    names.pr_title,
                    "--body",
                    f"The gw{names.gameweek:02d} {names.kind} view rendered from the local "
                    "ledger by scripts.publish_gameweek_site. Raw ledger and handoffs stay "
                    "local; only generated public view data enters this branch.",
                ],
                cwd=worktree,
            )
            print(f"PR: {pr_url}")
    finally:
        _run(["git", "worktree", "remove", str(worktree), "--force"], cwd=root, check=False)
    print(next_steps(names, pr_url))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--gameweek", type=int, required=True)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--force-branch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    try:
        names = PublishNames(
            season=arguments.season, gameweek=arguments.gameweek, kind=arguments.kind
        )
        return publish(names, force_branch=arguments.force_branch, dry_run=arguments.dry_run)
    except PublishError as error:
        print(f"Refused: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
