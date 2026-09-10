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

The one thing this does write outside the worktree is the immutable advice record: the
rebuild is the process that emits the bytes that ship, so it is the process that records
them, into *this* checkout's ``data/advice_records`` rather than into the worktree it is
about to delete. The record is keyed by the capture, so publishing a week twice — mid-week,
then again before the deadline from a fresher capture — records both. What is refused is a
rebuild of *one* capture that disagrees with its own record, with the difference named;
``--no-advice-record`` is the deadline escape.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("decision", "settled")


def repository_root() -> Path:
    """The checkout the legacy publish reads its data from and writes its record into.

    Resolved when it is asked for -- at the construction of a :class:`LeaguePublish` or at
    the publish itself -- never at import. A default bound to the working directory at
    import time anchored every root under whatever subdirectory the operator started from
    (measured: ``docs/data/snapshots`` and its four siblings), while the Git commands, run
    from the same place, found the checkout on their own. The Git top level is the
    checkout; outside any checkout, the working directory is all there is.
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


def _data(*parts: str) -> Path:
    return repository_root().joinpath("data", *parts)


@dataclass(frozen=True, slots=True)
class LeaguePublish:
    """The league tree beside the season views: which capture, which projection, how many
    solver processes. Paths are absolute because the build runs in a fresh worktree that
    holds no data of its own; the defaults are resolved at construction, from the checkout,
    not from the working directory this module was imported in."""

    league_id: int
    snapshot_id: str
    in_season_projection: Path | None
    workers: int = 1
    cohort_snapshot: str | None = None
    elite_snapshot: str | None = None
    snapshot_root: Path = field(default_factory=lambda: _data("snapshots"))
    registry: Path = field(default_factory=lambda: _data("entries", "registry.json"))
    archive_root: Path = field(default_factory=lambda: _data("raw", "vaastav-fpl"))
    ledger_root: Path = field(default_factory=lambda: _data("ledger"))
    #: Where the rebuild's immutable advice record lands. Absolute and rooted in *this*
    #: checkout for the same reason as the roots above: the build runs in a throwaway
    #: worktree, so a record left at the build's own default would be deleted with it.
    advice_record_root: Path = field(default_factory=lambda: _data("advice_records"))
    #: False passes ``--no-advice-record`` through: the escape when a rebuild of the same
    #: capture differs from that capture's record and the deadline will not wait for the
    #: difference to be reconciled. The first record is kept; this publish adds none.
    record_advice: bool = True

    def __post_init__(self) -> None:
        if self.league_id < 1:
            raise PublishError(f"league_id must be positive, got {self.league_id!r}.")
        if not self.snapshot_id.startswith("fpl-live-"):
            raise PublishError(
                f"The league tree is built from a live capture; got {self.snapshot_id!r}."
            )
        if self.workers < 1:
            raise PublishError(f"workers must be at least 1, got {self.workers!r}.")
        if self.cohort_snapshot is not None and not self.cohort_snapshot.startswith("fpl-top100-"):
            raise PublishError(
                f"The Top-100 mean is read from an fpl-top100 capture; got "
                f"{self.cohort_snapshot!r}."
            )
        if self.elite_snapshot is not None and not self.elite_snapshot.startswith(
            "fpl-elite-picks-"
        ):
            raise PublishError(
                f"The Top-100 mean is netted from an fpl-elite-picks capture; got "
                f"{self.elite_snapshot!r}."
            )
        if self.elite_snapshot is not None and self.cohort_snapshot is None:
            raise PublishError(
                "An elite-picks capture nets a cohort; pass --cohort-snapshot with it."
            )

    def scoreboard_arguments(self, out: Path, season: str) -> list[str]:
        """The scoreboard beside the league tree: same capture, same season, the ledger.

        The season is the one the rest of the publish resolves, not one inferred again
        from the capture: the committed copy must name the same season as the views it
        is committed beside.
        """

        arguments = [
            sys.executable,
            "-m",
            "scripts.build_scoreboard",
            "--league",
            str(self.league_id),
            "--snapshot-id",
            self.snapshot_id,
            "--snapshot-root",
            str(self.snapshot_root),
            "--registry",
            str(self.registry),
            "--ledger-root",
            str(self.ledger_root),
            "--season",
            season,
            "--out",
            str(out),
        ]
        if self.cohort_snapshot is not None:
            arguments += ["--cohort-snapshot", self.cohort_snapshot]
        if self.elite_snapshot is not None:
            arguments += ["--elite-snapshot", self.elite_snapshot]
        return arguments

    def build_arguments(self, out: Path) -> list[str]:
        arguments = [
            sys.executable,
            "-m",
            "scripts.build_league_site",
            "--league",
            str(self.league_id),
            "--snapshot-id",
            self.snapshot_id,
            "--snapshot-root",
            str(self.snapshot_root),
            "--registry",
            str(self.registry),
            "--archive-root",
            str(self.archive_root),
            "--advice-record-root",
            str(self.advice_record_root),
            "--out",
            str(out),
            "--workers",
            str(self.workers),
        ]
        if self.in_season_projection is not None:
            arguments += ["--in-season-projection", str(self.in_season_projection)]
        if not self.record_advice:
            arguments.append("--no-advice-record")
        return arguments


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
        return f".codex-tmp/publications/gw{self.gameweek:02d}-{self.kind}"

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


def publish(
    names: PublishNames,
    *,
    force_branch: bool,
    dry_run: bool,
    league: LeaguePublish | None = None,
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
        if builder is not None:
            builder(worktree / "web" / "public")
        else:
            _legacy_build(worktree, root, names, league)
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


def _legacy_build(
    worktree: Path, root: Path, names: PublishNames, league: LeaguePublish | None
) -> None:
    """Source-checkout compatibility; installed weekly runs supply typed service builders."""

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
    if league is not None:
        # The members' tree beside the season views, from the same capture and the
        # same projection the decision reads; solved in this worktree's code.
        print(_run(league.build_arguments(worktree / "web" / "public"), cwd=worktree))
        # The scoreboard reads the ledger, so it follows the site views and the tree.
        print(
            _run(
                league.scoreboard_arguments(worktree / "web" / "public", names.season),
                cwd=worktree,
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--gameweek", type=int, required=True)
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--force-branch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--league", type=int, help="also build this league's member tree")
    parser.add_argument("--snapshot-id", help="the live capture the league tree reads")
    parser.add_argument("--in-season-projection", type=Path, help="the handoff it projects with")
    parser.add_argument("--workers", type=int, default=1, help="league tree solver processes")
    parser.add_argument(
        "--cohort-snapshot", help="the fpl-top100 capture the scoreboard's Top-100 mean reads"
    )
    parser.add_argument(
        "--elite-snapshot",
        help="the fpl-elite-picks capture that nets that cohort's week; without it the "
        "Top-100 mean is published gross of transfer costs and labelled gross",
    )
    parser.add_argument(
        "--no-advice-record",
        action="store_true",
        help="publish without recording what was published; the escape when a rebuild of "
        "an already recorded capture is refused and the deadline will not wait — the first "
        "record is kept and the difference stays to be reconciled afterwards",
    )
    arguments = parser.parse_args()
    try:
        names = PublishNames(
            season=arguments.season, gameweek=arguments.gameweek, kind=arguments.kind
        )
        league: LeaguePublish | None = None
        if arguments.league is not None:
            if not arguments.snapshot_id:
                raise PublishError("--league needs --snapshot-id (the live capture to read).")
            league = LeaguePublish(
                league_id=arguments.league,
                snapshot_id=arguments.snapshot_id,
                in_season_projection=arguments.in_season_projection,
                workers=arguments.workers,
                cohort_snapshot=arguments.cohort_snapshot,
                elite_snapshot=arguments.elite_snapshot,
                record_advice=not arguments.no_advice_record,
            )
        return publish(
            names, force_branch=arguments.force_branch, dry_run=arguments.dry_run, league=league
        )
    except PublishError as error:
        print(f"Refused: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
