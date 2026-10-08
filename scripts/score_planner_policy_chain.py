"""The planner policy chain's two readings, `gw20` and `gw38`, each taken once.

``docs/research/planner_policy_chain_prereg.md`` fixes every rule this script applies, and the
rule numbers below are that document's. The runner (``scripts/measure_planner_policy_chain.py``)
decides the weeks and reads no outcome; this scorer reads the runner's evidence and the season's
outcome captures, once per reading, and writes the record the protocol names.

A reading refuses to start before its gameweek settles, refuses a reading the protocol does not
name, refuses a reading taken twice, and runs only from its own merge commit (rule 37). It
fetches origin before it reads any history, so that its merge commit, the readings already
taken and the release tags are read as origin holds them. The interim reading records no
verdict (rule 32). Run from a clean checkout of the scorer's merge commit, in a clone that is
not shallow and can reach origin, with E the runner's evidence directory and S the capture root
it decided from:

    python -m scripts.score_planner_policy_chain --evidence E --snapshot-root S --reading gw20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata as package_metadata
from pathlib import Path
from typing import Any, cast

import squadopt
from squadopt.application.weekly_suggestion_eval import (
    RECORDED_ADVICE_SCORING_BASIS,
    SuggestionEvaluationError,
    score_recorded_advice,
)
from squadopt.data.atomic import write_document_once
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FPL_LIVE_SOURCE,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.evaluation.live_series import DetectionPolicy, detectable_effect
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval
from squadopt.live.recommendation import read_inputs
from squadopt.live.rules import read_season_rules
from squadopt.planning.pricing import sell_price_tenths

REPOSITORY = Path(__file__).resolve().parents[1]
PROTOCOL_ID = "planner_policy_chain_v1"
SEASON = "2026-27"
PROTOCOL_FILE = "docs/research/planner_policy_chain_prereg.md"
SCORER_FILE = "scripts/score_planner_policy_chain.py"
RECORDS_DIR = REPOSITORY / "docs" / "research"
INDEX_FILE = REPOSITORY / "docs" / "measurements_index.md"
#: Rules 2 and 37: develop as origin holds it, read after the scorer's own fetch. The
#: remote-tracking ref is named in full, so that no local branch or tag of that name is read.
REMOTE = "origin"
TRACKING = f"refs/remotes/{REMOTE}"
DEVELOP = f"{TRACKING}/develop"
#: Rule 28: the two readings and the gameweek each one waits for.
READINGS: dict[str, int] = {"gw20": 20, "gw38": 38}
ARMS: tuple[str, ...] = ("served_3", "served_5", "hold_3", "hold_5", "one_week")
#: Rule 29: the primary contrasts, each pooled over the two windows.
CONTRASTS: dict[str, tuple[tuple[str, str], ...]] = {
    "A": (("served_3", "hold_3"), ("served_5", "hold_5")),
    "B": (("served_3", "one_week"), ("served_5", "one_week")),
}
#: Secondary pairings, descriptive only (rule 29).
SECONDARY_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "A_window_3": (("served_3", "hold_3"),),
    "A_window_5": (("served_5", "hold_5"),),
    "B_window_3": (("served_3", "one_week"),),
    "B_window_5": (("served_5", "one_week"),),
    "hold_minus_one_week": (("hold_3", "one_week"), ("hold_5", "one_week")),
}
#: Rule 30: the interval's policy, stated here so a later default cannot change it.
POLICY = PromotionPolicy(
    min_mean_improvement=0.5,
    confidence_level=0.90,
    bootstrap_resamples=5000,
    moving_block_length=4,
    deterministic_seed=0,
)
BLOCKS_OF_EIGHT = PromotionPolicy(
    min_mean_improvement=0.5,
    confidence_level=0.90,
    bootstrap_resamples=5000,
    moving_block_length=8,
    deterministic_seed=0,
)
#: Rule 33: the detectable effect's rates.
DETECTION = DetectionPolicy(confidence_level=0.90, power=0.80)
#: Rule 30: no interval under six scored weeks. Rule 32: no verdict under fifteen.
MIN_WEEKS_FOR_INTERVAL = 6
MIN_WEEKS_FOR_VERDICT = 15
#: Rule 26: each paid transfer is charged at the game's four points.
HIT_POINTS_CHARGED = 4.0
#: Rule 3: the planner source and the binding source, as file lists, and the test on them.
PLANNER_SOURCE: tuple[str, ...] = (
    "src/squadopt/planning/",
    "src/squadopt/live/transfers.py",
    "src/squadopt/application/advice.py",
)
BINDING_SOURCE: tuple[str, ...] = (
    "src/squadopt/platform/advice_switches.py",
    "src/squadopt/platform/football_bundle.py",
    "src/squadopt/platform/football_minute_basis.py",
    "src/squadopt/platform/capture_context.py",
    "src/squadopt/application/football_participation.py",
    "src/squadopt/application/manager_words.py",
    "src/squadopt/live/football_artifact.py",
    "src/squadopt/prediction/football.py",
)
RELEASE_TAG_PREFIX = f"site-{SEASON}-gw"
#: Rule 3: the tag shape the Pages workflow deploys (``.github/workflows/deploy-pages.yml``). A
#: tag outside it, or a lightweight tag, which that workflow rejects, deployed nothing.
RELEASE_TAG = re.compile(rf"{re.escape(RELEASE_TAG_PREFIX)}\d{{2}}-(?:decision|settled|fix\d+)")
#: Rule 3: how this scorer reads "the release tag live at the week's deadline", which the
#: protocol leaves to it; stated in each record.
RELEASE_RULE = (
    "The release live at a week's deadline is the latest annotated tag whose name has the shape "
    f"the Pages workflow deploys ({RELEASE_TAG_PREFIX}NN-decision, -settled or -fixN) and whose "
    "tagger instant falls strictly before the deadline. The tags read are origin's, as git "
    "ls-remote lists them, each recorded with its object id, and this checkout must hold every "
    "one of them under origin's object id. A tag of that shape that only this checkout holds is "
    "recorded as not on origin, and a week whose latest tag it would be is left unknown, as is a "
    "week with no such tag before its deadline or two at the latest instant. Only git is read: "
    "whether and when the workflow deployed a tag, a refused or stopped dispatch, a manual "
    "upload and a dashboard rollback are not."
)
#: Rule 3: a week whose release is unknown.
RELEASE_UNKNOWN: Mapping[str, object] = {
    "release_tag": None,
    "release_tag_object": None,
    "planner_source_same": None,
    "binding_source_same": None,
}
#: Rules 28 and 37: what a reading taken twice is to this scorer, which the protocol leaves to
#: it; stated in each record.
ONCE_RULE = (
    "A reading is refused as taken when its record or its twin exists in the checkout or in any "
    "other worktree of this repository, or was touched by any commit reachable from any ref or "
    "reflog once the scorer has fetched every branch from origin. A reading written in a "
    "separate clone is seen only once it is committed there and pushed to a branch on origin."
)
PINNED_PACKAGES: tuple[str, ...] = ("ortools", "numpy", "pandas")
#: Rule 31, stated beside every interval.
COVERAGE_NOTE = (
    "At these counts the interval is narrower than its level: in the protocol's synthetic check "
    "(400 replicates, standard deviation 11.6, true difference zero) it covered zero in 58, 76 "
    "and 82 per cent of replicates at 7, 15 and 31 weeks, and 54, 74 and 78 per cent at a lag-one "
    "autocorrelation of 0.2."
)


class ScorerError(RuntimeError):
    """A reading the protocol refuses, said before anything is written."""


# Rules 3 and 37: the scorer's own identity, and the frozen source's


def _git(*arguments: str, cwd: Path | None = None) -> str:
    """A git command's output. A command git refuses refuses the reading, in git's words."""

    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=REPOSITORY if cwd is None else cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise ScorerError(f"git {arguments[0]} failed: {error.stderr.strip()}") from error
    except (OSError, ValueError) as error:
        raise ScorerError(f"git {arguments[0]} cannot be run or read: {error}") from error
    return completed.stdout.strip()


def _git_bytes(*arguments: str, cwd: Path | None = None) -> bytes:
    """A git command's bytes, such as a file at a commit. A command git refuses refuses the
    reading, in git's words."""

    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=REPOSITORY if cwd is None else cwd,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", "replace").strip()
        raise ScorerError(f"git {arguments[0]} failed: {detail}") from error
    except OSError as error:
        raise ScorerError(f"git {arguments[0]} cannot be run: {error}") from error


def _git_code(*arguments: str) -> int:
    """The exit code of a git command that answers by it, such as ``merge-base --is-ancestor``."""

    try:
        return subprocess.run(["git", *arguments], cwd=REPOSITORY, capture_output=True).returncode
    except OSError as error:
        raise ScorerError(f"git {arguments[0]} cannot be run: {error}") from error


def _instant(text: str) -> datetime:
    """An instant git states, in UTC. One that is not an instant, or names no time zone, is
    refused."""

    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScorerError(f"The instant {text!r} cannot be read: {error}") from error
    if moment.tzinfo is None:
        raise ScorerError(f"The instant {text!r} names no time zone.")
    return moment.astimezone(UTC)


def fetch_origin() -> str:
    """Rules 2, 3, 28 and 37: what origin holds now, fetched before any history is read.

    A clean checkout of the scorer's merge commit cannot hold a commit made after it. So every
    branch on origin is fetched into the remote-tracking refs, and the season's release tags into
    the tags, before the merge commit, the readings already taken or the release tags are read.
    A release tag held here under another object than origin's is not overwritten: the fetch
    fails, and the reading is refused. Nothing is pruned, whatever the checkout's settings, so a
    branch or tag that origin no longer holds stays readable. Returns the commit develop is at on
    origin.
    """

    _git(
        "fetch",
        "--no-prune",
        REMOTE,
        f"+refs/heads/*:{TRACKING}/*",
        f"refs/tags/{RELEASE_TAG_PREFIX}*:refs/tags/{RELEASE_TAG_PREFIX}*",
    )
    return _git("rev-parse", "--verify", f"{DEVELOP}^{{commit}}")


def scorer_merge(root: Path | None = None) -> dict[str, str]:
    """Rules 2 and 37: the commit on develop's first-parent line, as origin holds it, that added
    this scorer.

    Each commit is compared with its first parent, so a squash merge is found as the squash
    commit and a normal merge as the merge commit, never as the feature commit that wrote the
    file on its branch. The line is develop's, not HEAD's own, so a checkout of a branch that
    develop never took finds no merge. The instant is the committer's, in UTC.
    """

    added = _git(
        "log",
        "--first-parent",
        "--diff-merges=first-parent",
        "--diff-filter=A",
        "--no-patch",
        "--format=%H %cI",
        "-1",
        DEVELOP,
        "--",
        SCORER_FILE,
        cwd=root,
    )
    if not added:
        raise ScorerError(
            f"{SCORER_FILE} has no commit on {DEVELOP}'s first-parent line; the scorer has "
            "not merged."
        )
    sha, instant = added.split(" ", 1)
    return {"commit": sha, "committed_utc": _instant(instant).isoformat()}


def source_identity() -> dict[str, object]:
    """Rules 2 and 37: a clean checkout at the scorer's merge commit on develop, and the bytes it
    runs.

    Origin is fetched first, so develop is read as origin holds it now. A shallow clone is
    refused: its last commit seems to add every file, and history before it cannot be read.
    """

    if _git("status", "--porcelain"):
        raise ScorerError("The checkout is not clean; the scorer's source cannot be named.")
    if not Path(squadopt.__file__).resolve().is_relative_to(REPOSITORY / "src"):
        raise ScorerError("squadopt does not resolve into this checkout's src/.")
    if _git("rev-parse", "--is-shallow-repository") != "false":
        raise ScorerError(
            "The checkout is a shallow clone; develop's line and the readings already taken "
            "cannot be read whole."
        )
    develop = fetch_origin()
    merge = scorer_merge()
    head = _git("rev-parse", "HEAD")
    if head != merge["commit"]:
        raise ScorerError(f"Run from the scorer's merge commit {merge['commit']}; HEAD is {head}.")
    if _git_code("merge-base", "--is-ancestor", head, DEVELOP) != 0:
        raise ScorerError(
            f"HEAD {head} is not an ancestor of {DEVELOP}; the scorer has not merged."
        )
    return {
        "scorer_merge_commit": merge["commit"],
        "scorer_merged_utc": merge["committed_utc"],
        "scorer_sha256": hashlib.sha256(_git_bytes("show", f"HEAD:{SCORER_FILE}")).hexdigest(),
        "protocol_sha256": hashlib.sha256(_git_bytes("show", f"HEAD:{PROTOCOL_FILE}")).hexdigest(),
        "develop_commit": develop,
        "python": platform.python_version(),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "versions": {name: package_metadata.version(name) for name in PINNED_PACKAGES},
    }


# Rules 28, 31 and 37: a reading is taken once


def record_paths(reading: str) -> tuple[str, str]:
    """Rule 36: the record and the twin a reading commits, as paths in the repository."""

    stem = f"docs/research/planner_policy_chain_{reading}"
    return f"{stem}.json", f"{stem}.md"


def committed_reading(reading: str) -> str | None:
    """Rules 28 and 37: the newest commit on any ref or reflog that touched the reading's record
    or twin.

    Read after ``source_identity`` has fetched every branch from origin, so a reading committed
    in another checkout and pushed to any branch is found, and so is one deleted later, or one
    whose commit a later push dropped from its branch after this repository had fetched it.
    """

    return (
        _git("log", "--all", "--reflog", "-1", "--format=%H", "--", *record_paths(reading)) or None
    )


def written_reading(reading: str) -> str | None:
    """Rules 28 and 37: the reading's record or twin on disk in any worktree of this
    repository, committed or not, so a reading written in one worktree is found from another."""

    for line in _git("worktree", "list", "--porcelain").splitlines():
        if not line.startswith("worktree "):
            continue
        root = Path(line.removeprefix("worktree "))
        for path in record_paths(reading):
            if (root / path).exists():
                return str(root / path)
    return None


# Rule 3: the release live at each deadline


@dataclass(frozen=True)
class ReleaseTag:
    """Rule 3: one release tag, as origin holds it, or as only this checkout holds it."""

    name: str
    object_id: str
    commit: str
    created: datetime
    on_origin: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "object_id": self.object_id,
            "commit": self.commit,
            "created_utc": self.created.isoformat(),
            "on_origin": self.on_origin,
        }


def release_tags() -> tuple[ReleaseTag, ...]:
    """Rule 3: the season's release tags, each with its object id, oldest first.

    Origin names the tags and their objects (``git ls-remote``). The tagger instant and the
    commit are read here from the same object, so a tag of origin's missing here, or held here
    under another object, is refused. A tag of that shape that only this checkout holds is kept
    and marked as not on origin: a deployed tag can go missing from origin
    (docs/architecture/branching.md, "Tag namespaces"), and no week may read an older tag in its
    place. A lightweight tag, or a name outside the shape the Pages workflow deploys, deployed
    nothing and is left out.
    """

    origin: dict[str, str] = {}
    annotated: set[str] = set()
    listed = _git("ls-remote", "--tags", REMOTE, f"refs/tags/{RELEASE_TAG_PREFIX}*")
    for line in listed.splitlines():
        object_id, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            annotated.add(name.removesuffix("^{}"))
        else:
            origin[name] = object_id
    here: dict[str, tuple[str, str, str]] = {}
    listing = _git(
        "for-each-ref",
        "--format=%(refname:strip=2)%09%(objectname)%09%(*objectname)"
        "%09%(creatordate:iso8601-strict)",
        f"refs/tags/{RELEASE_TAG_PREFIX}*",
    )
    for line in listing.splitlines():
        name, object_id, commit, created = line.split("\t")
        here[name] = (object_id, commit, created)
    tags: list[ReleaseTag] = []
    for name, object_id in sorted(origin.items()):
        if name not in annotated or not RELEASE_TAG.fullmatch(name):
            continue
        held = here.get(name)
        if held is None or held[0] != object_id:
            raise ScorerError(
                f"Release tag {name} is {object_id} on origin and "
                f"{held[0] if held else 'absent'} here; this checkout's tags must be origin's."
            )
        tags.append(ReleaseTag(name, object_id, held[1], _instant(held[2])))
    # A lightweight tag has no object under it, so its commit field is empty and it is left out.
    for name, (object_id, commit, created) in sorted(here.items()):
        if name not in origin and commit and RELEASE_TAG.fullmatch(name):
            tags.append(ReleaseTag(name, object_id, commit, _instant(created), on_origin=False))
    return tuple(sorted(tags, key=lambda tag: (tag.created, tag.name)))


def release_at(deadline: datetime, tags: Sequence[ReleaseTag]) -> ReleaseTag | None:
    """Rule 3: the release tag live at the deadline, read as the latest tag created strictly
    before it. None before the first tag, when two tags share that latest instant, or when the
    latest is a tag origin does not list."""

    before = [tag for tag in tags if tag.created < deadline]
    if not before:
        return None
    latest = max(tag.created for tag in before)
    at_latest = [tag for tag in before if tag.created == latest]
    if len(at_latest) != 1 or not at_latest[0].on_origin:
        return None
    return at_latest[0]


def _diff_quiet(left: str, right: str, paths: Sequence[str]) -> bool | None:
    completed = subprocess.run(
        ["git", "diff", "--quiet", left, right, "--", *paths],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    return None


def release_binding(
    deadline: datetime, frozen_commit: str, tags: Sequence[ReleaseTag]
) -> dict[str, object]:
    """Rule 3: whether the live release carried the frozen commit's planner and binding source.

    The test is fixed by the protocol: ``git diff --quiet <release tag> <frozen commit> --
    <paths>``, run on the tag's object as origin holds it. An empty diff means the same source;
    a non-empty one means the release differed; no release known at the deadline, or a diff git
    cannot take, is recorded as unknown.
    """

    tag = release_at(deadline, tags)
    if tag is None:
        return dict(RELEASE_UNKNOWN)
    return {
        "release_tag": tag.name,
        "release_tag_object": tag.object_id,
        "planner_source_same": _diff_quiet(tag.object_id, frozen_commit, PLANNER_SOURCE),
        "binding_source_same": _diff_quiet(tag.object_id, frozen_commit, BINDING_SOURCE),
    }


# Rule 36: the runner's evidence


@dataclass(frozen=True)
class WeekEvidence:
    gameweek: int
    receipt: Mapping[str, Any]
    manifest: Mapping[str, Any]
    records: Mapping[tuple[str, str], Mapping[str, Any]]


def _load(path: Path) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise ScorerError(f"{path} cannot be read: {error}") from error


def evidence_digest(directory: Path) -> str:
    """The runner's digest of a week's files: relative name and sha256, the manifest left out."""

    digest = hashlib.sha256()
    files = (p for p in directory.rglob("*") if p.is_file() and p.name != "manifest.json")
    for path in sorted(files):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def read_evidence(evidence: Path, through: int) -> tuple[dict[str, Any], list[WeekEvidence]]:
    """Every decided week from the first chain week through ``through``, checked against its
    manifest; a week not yet decided refuses the reading."""

    protocol_path = evidence / "protocol.json"
    if not protocol_path.is_file():
        raise ScorerError(f"{evidence} holds no protocol.json; the chain has not started.")
    protocol = _load(protocol_path)
    if protocol.get("protocol", PROTOCOL_ID) != PROTOCOL_ID or protocol.get("season") != SEASON:
        raise ScorerError("The evidence is not this protocol's.")
    first = int(protocol["first_chain_week"])
    weeks: list[WeekEvidence] = []
    for gameweek in range(first, through + 1):
        directory = evidence / f"gw{gameweek:02d}"
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise ScorerError(f"GW{gameweek:02d} is not decided; the reading waits for it.")
        manifest = _load(manifest_path)
        if int(manifest.get("gameweek", -1)) != gameweek:
            raise ScorerError(f"{manifest_path} names another gameweek.")
        recorded = manifest.get("evidence_digest")
        if recorded is not None and evidence_digest(directory) != recorded:
            raise ScorerError(f"GW{gameweek:02d}: the week's files no longer match their manifest.")
        records: dict[tuple[str, str], Mapping[str, Any]] = {}
        for name, digest in cast(Mapping[str, str], manifest.get("records", {})).items():
            path = directory / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ScorerError(f"{path} does not match the digest its manifest records.")
            record = _load(path)
            records[(str(record["profile"]), str(record["arm"]))] = record
        weeks.append(WeekEvidence(gameweek, _load(directory / "receipt.json"), manifest, records))
    return protocol, weeks


# Rule 25: the outcome capture


@dataclass(frozen=True)
class Outcome:
    gameweek: int
    deadline_utc: str | None
    snapshot: CapturedSnapshot | None
    reason: str | None

    @property
    def snapshot_id(self) -> str | None:
        return None if self.snapshot is None else self.snapshot.metadata.snapshot_id


def _captures(snapshot_root: Path) -> list[CapturedSnapshot]:
    captures = []
    for snapshot_id in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        try:
            captures.append(read_snapshot(snapshot_root, snapshot_id))
        except (DataError, ValueError, KeyError, TypeError) as error:
            raise ScorerError(f"Capture {snapshot_id} cannot be read: {error}") from error
    return captures


def _deadline(captures: Sequence[CapturedSnapshot], gameweek: int) -> str | None:
    """The deadline the newest capture states for the gameweek."""

    for capture in sorted(
        captures, key=lambda c: as_instant(c.metadata.captured_at_utc), reverse=True
    ):
        try:
            for deadline in gameweek_deadlines(capture.payloads[BOOTSTRAP_PAYLOAD]):
                if int(deadline.gameweek) == gameweek:
                    return str(deadline.deadline_utc)
        except (DataError, ValueError, KeyError, TypeError):
            continue
    return None


def settled(captures: Sequence[CapturedSnapshot], gameweek: int) -> bool:
    """Rule 28: a gameweek has settled when a capture counts it in scored_gameweeks."""

    for capture in captures:
        try:
            if gameweek in scored_gameweeks(capture.payloads[BOOTSTRAP_PAYLOAD]):
                return True
        except (DataError, ValueError, KeyError, TypeError):
            continue
    return False


def outcome_capture(captures: Sequence[CapturedSnapshot], gameweek: int) -> Outcome:
    """Rule 25: of the captures at or after the deadline whose bootstrap counts the week in
    scored_gameweeks and that hold its live payload, the latest; a tie leaves the week unscored."""

    deadline = _deadline(captures, gameweek)
    if deadline is None:
        return Outcome(gameweek, None, None, "no_capture_states_the_deadline")
    settled_here = []
    for capture in captures:
        try:
            if as_instant(capture.metadata.captured_at_utc) < as_instant(deadline):
                continue
            if gameweek not in scored_gameweeks(capture.payloads[BOOTSTRAP_PAYLOAD]):
                continue
        except (DataError, ValueError, KeyError, TypeError):
            continue
        settled_here.append(capture)
    if not settled_here:
        return Outcome(gameweek, deadline, None, "not_settled")
    with_outcomes = [c for c in settled_here if live_payload(gameweek) in c.payloads]
    if not with_outcomes:
        return Outcome(gameweek, deadline, None, "missing_outcomes")
    latest = max(as_instant(c.metadata.captured_at_utc) for c in with_outcomes)
    at_latest = [c for c in with_outcomes if as_instant(c.metadata.captured_at_utc) == latest]
    if len(at_latest) > 1:
        return Outcome(gameweek, deadline, None, "tied_outcome_captures")
    return Outcome(gameweek, deadline, at_latest[0], None)


# Rules 26 and 27: scoring a chain's week and pairing the arms


@dataclass(frozen=True)
class ChainScore:
    status: str
    gross: float
    hits: float
    net: float
    lineup: tuple[object, ...]


def _lineup_key(advice: Mapping[str, Any], hits: float) -> tuple[object, ...]:
    """Rule 27: the fifteen, the eleven, the bench order, the captain, the vice and the hits."""

    starters = [int(p) for p in advice["starting_xi"]]
    bench = [int(p) for p in advice["bench"]]
    return (
        tuple(sorted([*starters, *bench])),
        tuple(sorted(starters)),
        tuple(bench),
        int(advice["captain"]),
        int(advice["vice_captain"]),
        float(hits),
    )


def paid_hits(record: Mapping[str, Any]) -> float:
    """Rule 26: the game's four points for each paid transfer of the played first week."""

    if record.get("status") != "decided":
        return 0.0
    weeks = cast(Mapping[str, Any], record.get("plan", {})).get("weeks") or []
    first = cast(Mapping[str, Any], weeks[0]) if weeks else {}
    return HIT_POINTS_CHARGED * int(first.get("paid_transfer_count", 0))


def score_chain_week(record: Mapping[str, Any], outcomes: Any) -> ChainScore | None:
    """One chain's realized week, or None where the chain played nothing (rules 21 to 23)."""

    status = str(record.get("status"))
    advice = record.get("advice")
    if status in ("blocked", "held") or not isinstance(advice, Mapping):
        return None
    hits = paid_hits(record)
    played = {**advice, "transfer_hit_points": hits}
    try:
        suggested, _ = score_recorded_advice(record, played, outcomes)
    except (SuggestionEvaluationError, DataError, ValueError, TypeError, KeyError) as error:
        raise ScorerError(f"{record.get('profile')} {record.get('arm')}: {error}") from error
    return ChainScore(
        status,
        float(suggested.gross_points),
        float(suggested.transfer_hit_points),
        float(suggested.net_points),
        _lineup_key(advice, hits),
    )


@dataclass(frozen=True)
class WeekScores:
    gameweek: int
    outcome: Outcome
    scores: Mapping[tuple[str, str], ChainScore]
    truncated: frozenset[str]
    served_routes: Mapping[str, str]
    model_version: str | None
    missing_reason: str | None


def _route_label(record: Mapping[str, Any]) -> str:
    policy = cast(Mapping[str, Any], record.get("policy", {}))
    solver = cast(Mapping[str, Any], record.get("solver", {}))
    route = str(policy.get("route", "none"))
    outcome = (
        solver.get("observed_window_status")
        or solver.get("expected_window_status")
        or ("seed_completed" if solver.get("seed_completed") else None)
        or "none"
    )
    return f"{route}:{outcome}"


def score_week(week: WeekEvidence, outcome: Outcome) -> WeekScores:
    missing = week.manifest.get("missing_reason")
    scores: dict[tuple[str, str], ChainScore] = {}
    truncated: set[str] = set()
    routes: dict[str, str] = {}
    if outcome.snapshot is not None and missing is None:
        outcomes = live_event_outcomes(
            outcome.snapshot.payloads[live_payload(week.gameweek)],
            outcome.snapshot.payloads[BOOTSTRAP_PAYLOAD],
            gameweek=week.gameweek,
        )
        for chain, record in sorted(week.records.items()):
            scored = score_chain_week(record, outcomes)
            if scored is not None:
                scores[chain] = scored
            policy = cast(Mapping[str, Any], record.get("policy", {}))
            if policy.get("truncated"):
                truncated.add(chain[1])
            if chain[1].startswith("served_") and record.get("status") == "decided":
                routes[chain[0] + ":" + chain[1]] = _route_label(record)
    return WeekScores(
        week.gameweek,
        outcome,
        scores,
        frozenset(truncated),
        routes,
        cast(str | None, week.receipt.get("model_version")),
        cast(str | None, missing),
    )


def week_difference(
    week: WeekScores, pairs: Sequence[tuple[str, str]], *, without_failed: bool = False
) -> dict[str, Any] | None:
    """Rule 27: the mean over the squad and window pairs both arms scored that week."""

    differences = []
    zero_pairs = 0
    failed_pairs = 0
    profiles = sorted({profile for profile, _ in week.scores})
    for profile in profiles:
        for left, right in pairs:
            first, second = week.scores.get((profile, left)), week.scores.get((profile, right))
            if first is None or second is None:
                continue
            failed = "failed" in (first.status, second.status)
            if failed:
                failed_pairs += 1
                if without_failed:
                    continue
            differences.append(first.net - second.net)
            if first.lineup == second.lineup:
                zero_pairs += 1
    if not differences:
        return None
    return {
        "gameweek": week.gameweek,
        "difference": statistics.fmean(differences),
        "pairs": len(differences),
        "exact_zero_pairs": zero_pairs,
        "failed_pairs": failed_pairs,
    }


# Rules 30 to 33: intervals, autocorrelations and verdicts


def _autocorrelation(values: Sequence[float], lag: int) -> float | None:
    if len(values) <= lag + 1:
        return None
    mean = statistics.fmean(values)
    denominator = sum((v - mean) ** 2 for v in values)
    if denominator == 0.0:
        return None
    numerator = sum((values[i] - mean) * (values[i - lag] - mean) for i in range(lag, len(values)))
    return numerator / denominator


def summarize(differences: Sequence[float], candidate_id: str) -> dict[str, Any]:
    """Rules 30, 31 and 33 for one series of weekly differences, in gameweek order."""

    count = len(differences)
    summary: dict[str, Any] = {
        "weeks": count,
        "mean": statistics.fmean(differences) if count else None,
        "standard_deviation": statistics.stdev(differences) if count >= 2 else None,
        "interval": None,
        "interval_blocks_of_8": None,
        "autocorrelation": {str(lag): _autocorrelation(differences, lag) for lag in (1, 2, 3, 4)},
        "detectable_effect": None,
        "coverage_note": COVERAGE_NOTE,
    }
    if count >= MIN_WEEKS_FOR_INTERVAL:
        paired = [(SEASON, float(d)) for d in differences]
        low, high = season_aware_moving_block_interval(
            paired, policy=POLICY, candidate_id=candidate_id
        )
        summary["interval"] = [low, high]
        low8, high8 = season_aware_moving_block_interval(
            paired, policy=BLOCKS_OF_EIGHT, candidate_id=candidate_id
        )
        summary["interval_blocks_of_8"] = [low8, high8]
    deviation = summary["standard_deviation"]
    if deviation is not None and deviation > 0.0:
        summary["detectable_effect"] = detectable_effect(deviation, count, policy=DETECTION)
    return summary


def verdict(summary: Mapping[str, Any], *, final: bool) -> str | None:
    """Rule 32: the first clause that holds; the interim records no verdict."""

    if not final:
        return None
    if int(summary["weeks"]) < MIN_WEEKS_FOR_VERDICT:
        return "insufficient_evidence"
    interval = summary["interval"]
    if interval is None:
        return "insufficient_evidence"
    low, high = interval
    if high < 0.0:
        return "worse"
    if low > 0.0 and float(summary["mean"]) >= POLICY.min_mean_improvement:
        return "better"
    return "not_separated"


def _series(
    weeks: Sequence[WeekScores],
    pairs: Sequence[tuple[str, str]],
    *,
    include_truncated: bool = False,
    only_truncated: bool = False,
    without_failed: bool = False,
    keep: Any = None,
) -> list[dict[str, Any]]:
    rows = []
    for week in weeks:
        truncated = bool(
            week.truncated & {left for left, _ in pairs} | week.truncated & {r for _, r in pairs}
        )
        if only_truncated and not truncated:
            continue
        if not include_truncated and not only_truncated and truncated:
            continue
        if keep is not None and not keep(week):
            continue
        row = week_difference(week, pairs, without_failed=without_failed)
        if row is not None:
            rows.append(row)
    return rows


def _block(rows: Sequence[Mapping[str, Any]], candidate_id: str, *, final: bool) -> dict[str, Any]:
    differences = [float(row["difference"]) for row in rows]
    summary = summarize(differences, candidate_id)
    return {
        **summary,
        "exact_zero_pairs": sum(int(row["exact_zero_pairs"]) for row in rows),
        "pairs": sum(int(row["pairs"]) for row in rows),
        "weeks_listed": [int(row["gameweek"]) for row in rows],
        "verdict": verdict(summary, final=final),
    }


# Totals (rules 26 and 35): gross points, hits, free transfers, bank and sale value


def arm_totals(
    weeks: Sequence[WeekScores],
    evidence: Sequence[WeekEvidence],
    prices: Mapping[int, int] | None,
    fee: float,
) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    last_states: dict[tuple[str, str], Mapping[str, Any]] = {}
    for week in evidence:
        for chain, record in week.records.items():
            state = record.get("state_after") or record.get("state_before")
            if isinstance(state, Mapping):
                last_states[chain] = state
    for arm in ARMS:
        gross = hits = net = 0.0
        scored_weeks = 0
        for week in weeks:
            for (_profile, name), score in week.scores.items():
                if name == arm:
                    gross += score.gross
                    hits += score.hits
                    net += score.net
                    scored_weeks += 1
        free = bank = 0
        sale: float | None = 0.0
        for (_profile, name), state in last_states.items():
            if name != arm:
                continue
            free += int(state.get("free_transfers", 0))
            bank += int(state.get("bank_tenths", 0))
            if prices is None or sale is None:
                sale = None
                continue
            purchase = {
                int(k): int(v) for k, v in cast(Mapping[str, Any], state["purchase_prices"]).items()
            }
            for player in cast(Sequence[int], state["squad"]):
                current = prices.get(int(player))
                if current is None:
                    sale = None
                    break
                sale += sell_price_tenths(current, purchase[int(player)], sell_on_fee=fee)
        totals[arm] = {
            "gross_points": gross,
            "hit_points": hits,
            "net_points": net,
            "scored_chain_weeks": scored_weeks,
            "free_transfers_at_end": free,
            "bank_tenths_at_end": bank,
            "sale_value_tenths_at_end": sale,
        }
    return totals


def _paired_totals(totals: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rule 35: at the interim, gross points, hits, free transfers, bank and sale value appear
    only as paired differences between arms."""

    paired = {}
    for label, pairs in {
        **CONTRASTS,
        "hold_minus_one_week": SECONDARY_PAIRS["hold_minus_one_week"],
    }.items():
        differences: dict[str, Any] = {}
        for key in (
            "gross_points",
            "hit_points",
            "net_points",
            "free_transfers_at_end",
            "bank_tenths_at_end",
            "sale_value_tenths_at_end",
        ):
            values = []
            for left, right in pairs:
                a, b = totals[left][key], totals[right][key]
                if a is None or b is None:
                    values = []
                    break
                values.append(float(a) - float(b))
            differences[key] = sum(values) if values else None
        paired[label] = differences
    return paired


# The reading


def reading_record(
    *,
    reading: str,
    protocol: Mapping[str, Any],
    evidence: Sequence[WeekEvidence],
    captures: Sequence[CapturedSnapshot],
    identity: Mapping[str, object],
    binding: Any,
    tags: Sequence[ReleaseTag] = (),
) -> dict[str, Any]:
    final = reading == "gw38"
    frozen = str(protocol.get("repository_commit", ""))
    weeks: list[WeekScores] = []
    listed: list[dict[str, Any]] = []
    for week in evidence:
        outcome = outcome_capture(captures, week.gameweek)
        scored = score_week(week, outcome)
        weeks.append(scored)
        deadline = outcome.deadline_utc or cast(str | None, week.receipt.get("deadline_utc"))
        release = binding(as_instant(deadline), frozen) if deadline else dict(RELEASE_UNKNOWN)
        listed.append(
            {
                "gameweek": week.gameweek,
                "decision_capture": week.receipt.get("snapshot_id"),
                "deadline_utc": deadline,
                "missing_reason": scored.missing_reason,
                "outcome_capture": outcome.snapshot_id,
                "unscored_reason": None if scored.missing_reason else outcome.reason,
                "model_version": scored.model_version,
                "scored_chains": len(scored.scores),
                "truncated_arms": sorted(scored.truncated),
                "served_routes": dict(scored.served_routes),
                "release": release,
            }
        )
    contrasts = {}
    for label, pairs in CONTRASTS.items():
        candidate = f"{PROTOCOL_ID}:{label}"
        contrasts[label] = {
            "primary": _block(_series(weeks, pairs), candidate, final=final),
            "without_failed_weeks": _block(
                _series(weeks, pairs, without_failed=True), candidate, final=False
            ),
            "by_model_version": {
                version: _block(
                    _series(weeks, pairs, keep=lambda w, v=version: w.model_version == v),
                    candidate,
                    final=False,
                )
                for version in sorted({w.model_version for w in weeks if w.model_version})
            },
        }
    served_route_labels = sorted({label for w in weeks for label in w.served_routes.values()})
    by_route = {}
    for label in served_route_labels:
        by_route[label] = _block(
            _series(
                weeks, CONTRASTS["A"], keep=lambda w, lab=label: lab in w.served_routes.values()
            ),
            f"{PROTOCOL_ID}:A",
            final=False,
        )
    secondary = {
        name: _block(_series(weeks, pairs), f"{PROTOCOL_ID}:{name}", final=False)
        for name, pairs in SECONDARY_PAIRS.items()
    }
    by_squad = {}
    for profile in sorted({profile for w in weeks for profile, _ in w.scores}):
        rows = []
        for week in weeks:
            kept = WeekScores(
                week.gameweek,
                week.outcome,
                {chain: score for chain, score in week.scores.items() if chain[0] == profile},
                week.truncated,
                week.served_routes,
                week.model_version,
                week.missing_reason,
            )
            row = week_difference(kept, CONTRASTS["A"]) if not kept.truncated else None
            if row is not None:
                rows.append(row)
        by_squad[profile] = _block(rows, f"{PROTOCOL_ID}:A", final=False)
    truncated = {
        label: _block(
            _series(weeks, pairs, only_truncated=True), f"{PROTOCOL_ID}:{label}", final=False
        )
        for label, pairs in CONTRASTS.items()
    }
    last_outcome = next(
        (w.outcome for w in reversed(weeks) if w.outcome.snapshot is not None), None
    )
    prices: Mapping[int, int] | None = None
    fee = 0.5
    if last_outcome is not None and last_outcome.snapshot is not None:
        try:
            inputs = read_inputs(last_outcome.snapshot, season=SEASON)
            prices = {
                int(p): int(c)
                for p, c in zip(inputs.players.player_id, inputs.players.price_tenths, strict=True)
            }
            fee = float(
                read_season_rules(last_outcome.snapshot, season=SEASON).transfers.sell_on_fee
            )
        except (DataError, ValueError, KeyError, TypeError):
            prices = None
    totals = arm_totals(weeks, evidence, prices, fee)
    return {
        "protocol": PROTOCOL_ID,
        "season": SEASON,
        "reading": reading,
        "reading_gameweek": READINGS[reading],
        "final": final,
        "scored_on": RECORDED_ADVICE_SCORING_BASIS,
        "hit_points_charged": HIT_POINTS_CHARGED,
        "identity": dict(identity),
        "frozen_source": {
            "repository_commit": protocol.get("repository_commit"),
            "protocol_sha256": protocol.get("protocol_sha256"),
            "runner_sha256": protocol.get("runner_sha256"),
            "binding_commits": protocol.get("binding_commits"),
            "first_chain_week": protocol.get("first_chain_week"),
            "bound_week": protocol.get("bound_week"),
            "skipped_weeks": protocol.get("skipped_weeks"),
            "dropped_profiles": protocol.get("dropped_profiles"),
            "answer": protocol.get("answer"),
        },
        "interval_policy": {
            "confidence_level": POLICY.confidence_level,
            "bootstrap_resamples": POLICY.bootstrap_resamples,
            "moving_block_length": POLICY.moving_block_length,
            "deterministic_seed": POLICY.deterministic_seed,
            "min_mean_improvement": POLICY.min_mean_improvement,
            "min_weeks_for_interval": MIN_WEEKS_FOR_INTERVAL,
            "min_weeks_for_verdict": MIN_WEEKS_FOR_VERDICT,
            "detection": {"confidence_level": DETECTION.confidence_level, "power": DETECTION.power},
        },
        "weeks": listed,
        "contrasts": contrasts,
        "contrast_a_by_served_route": by_route,
        "secondary": secondary,
        "by_squad": by_squad,
        "truncated_weeks": truncated,
        "totals": {
            "paired_differences": _paired_totals(totals),
            **({"by_arm": totals} if final else {}),
        },
        "outcome_read": True,
        "locked_holdout_accessed": False,
        "binding_source_test": "git diff --quiet <release tag> <frozen commit> -- <paths>",
        "release_rule": RELEASE_RULE,
        "release_tags": [tag.to_json() for tag in tags],
        "once_rule": ONCE_RULE,
        "planner_source": list(PLANNER_SOURCE),
        "binding_source": list(BINDING_SOURCE),
    }


def _shown(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, float):
        return f"{value:+.3f}" if abs(value) < 1000 else f"{value:.1f}"
    if isinstance(value, list) and len(value) == 2:
        return f"[{value[0]:+.3f}, {value[1]:+.3f}]"
    return str(value)


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _header(*names: str) -> list[str]:
    return [_row(*names), _row(*(["---"] * len(names)))]


def _stats_row(label: str, block: Mapping[str, Any], *, interval: bool = True) -> str:
    return _row(
        label,
        block["weeks"],
        _shown(block["mean"]),
        _shown(block["standard_deviation"]),
        _shown(block["interval"]) if interval else "none",
    )


def render_markdown(record: Mapping[str, Any]) -> str:
    """The record's twin, rendered from the JSON and nothing else."""

    final = bool(record["final"])
    frozen = record["frozen_source"]["repository_commit"]
    scorer = record["identity"].get("scorer_merge_commit")
    lines = [
        f"# Planner policy chain, {record['reading']} reading",
        "",
        f"Protocol `{record['protocol']}`, season {record['season']}, read after "
        f"GW{record['reading_gameweek']} settled. {'Final' if final else 'Interim'} reading; "
        f"scored on `{record['scored_on']}` with each paid transfer charged at "
        f"{record['hit_points_charged']:.0f} points. The frozen source is `{frozen}`; the scorer "
        f"ran from `{scorer}`.",
        "",
        "## Weeks",
        "",
        *_header(
            "GW",
            "Decision capture",
            "Outcome capture",
            "Model version",
            "Scored chains",
            "Release tag",
            "Planner same",
            "Binding same",
            "Note",
        ),
    ]
    for week in record["weeks"]:
        release = week["release"]
        lines.append(
            _row(
                week["gameweek"],
                week["decision_capture"] or "none",
                week["outcome_capture"] or "none",
                week["model_version"] or "none",
                week["scored_chains"],
                release.get("release_tag") or "none",
                _shown(release.get("planner_source_same")),
                _shown(release.get("binding_source_same")),
                week["missing_reason"] or week["unscored_reason"] or "",
            )
        )
    lines += ["", record["release_rule"]]
    lines += [
        "",
        "## Primary contrasts",
        "",
        *_header(
            "Contrast",
            "Weeks",
            "Mean",
            "SD",
            "Interval (blocks of 4)",
            "Blocks of 8",
            "Detectable effect",
            "Zero pairs",
            "Verdict",
        ),
    ]
    for label, block in record["contrasts"].items():
        primary = block["primary"]
        lines.append(
            _row(
                label,
                primary["weeks"],
                _shown(primary["mean"]),
                _shown(primary["standard_deviation"]),
                _shown(primary["interval"]),
                _shown(primary["interval_blocks_of_8"]),
                _shown(primary["detectable_effect"]),
                primary["exact_zero_pairs"],
                primary["verdict"] if final else "none (interim)",
            )
        )
    lines += ["", record["contrasts"]["A"]["primary"]["coverage_note"], ""]
    lines += [
        "## Secondary, descriptive",
        "",
        *_header("Series", "Weeks", "Mean", "SD", "Interval"),
    ]
    for label, block in record["contrasts"].items():
        lines.append(_stats_row(f"{label} without failed weeks", block["without_failed_weeks"]))
        for version, vblock in block["by_model_version"].items():
            lines.append(_stats_row(f"{label} on `{version}` weeks", vblock))
    for name, block in record["secondary"].items():
        lines.append(_stats_row(name, block))
    for profile, block in record["by_squad"].items():
        lines.append(_stats_row(f"A, squad {profile}", block))
    for label, block in record["contrast_a_by_served_route"].items():
        lines.append(_stats_row(f"A where served took {label}", block))
    for label, block in record["truncated_weeks"].items():
        lines.append(_stats_row(f"{label}, truncated weeks", block, interval=False))
    lines += [
        "",
        "## Points, hits, free transfers, bank and sale value",
        "",
        *_header(
            "Pair", "Gross", "Hits", "Net", "Free transfers", "Bank (tenths)", "Sale (tenths)"
        ),
    ]
    for label, diffs in record["totals"]["paired_differences"].items():
        lines.append(
            _row(
                label,
                _shown(diffs["gross_points"]),
                _shown(diffs["hit_points"]),
                _shown(diffs["net_points"]),
                _shown(diffs["free_transfers_at_end"]),
                _shown(diffs["bank_tenths_at_end"]),
                _shown(diffs["sale_value_tenths_at_end"]),
            )
        )
    if final:
        lines += [
            "",
            *_header("Arm", "Gross", "Hits", "Net", "Scored chain weeks", "Free", "Bank", "Sale"),
        ]
        for arm, totals in record["totals"]["by_arm"].items():
            lines.append(
                _row(
                    arm,
                    f"{totals['gross_points']:.1f}",
                    f"{totals['hit_points']:.1f}",
                    f"{totals['net_points']:.1f}",
                    totals["scored_chain_weeks"],
                    totals["free_transfers_at_end"],
                    totals["bank_tenths_at_end"],
                    _shown(totals["sale_value_tenths_at_end"]),
                )
            )
    lines += [
        "",
        "## What this reading does not claim",
        "",
        "A difference between arms is a difference between these policies on constructed squads "
        "under the served football forecast; it is not a forecast of any member's result, nor "
        "evidence about windows under the current model or about releases whose planner or "
        "binding source differs from the frozen commit (the Release columns above say which weeks "
        "those were). No verdict switches anything (rule 34).",
        "",
    ]
    return "\n".join(lines)


def index_row(record: Mapping[str, Any]) -> str:
    primary = record["contrasts"]["A"]["primary"]
    b = record["contrasts"]["B"]["primary"]
    verdicts = (
        f"verdicts A {primary['verdict']}, B {b['verdict']}"
        if record["final"]
        else "interim, no verdict"
    )
    name = f"planner_policy_chain_{record['reading']}"
    scorer = str(record["identity"].get("scorer_merge_commit"))[:8]
    return (
        f"- [Planner policy chain, {record['reading']} reading](research/{name}.json) / "
        f"[readout](research/{name}.md): {primary['weeks']} scored weeks; contrast A mean "
        f"{_shown(primary['mean'])}, interval {_shown(primary['interval'])}; contrast B mean "
        f"{_shown(b['mean'])}, interval {_shown(b['interval'])}; {verdicts}. Realized points on "
        f"`{record['scored_on']}`; scorer `{scorer}`."
    )


def score(
    evidence: Path,
    snapshot_root: Path,
    reading: str,
    *,
    records_dir: Path = RECORDS_DIR,
    index_file: Path = INDEX_FILE,
) -> dict[str, Any]:
    """Rules 28 and 37: take one reading, once, from the scorer's own merge commit.

    Every refusal that needs no outcome comes before the first capture is read: the reading's
    name, its record in the checkout, the scorer's identity after a fetch of origin, its record
    in committed history or in another worktree, and the release tags. ``records_dir`` and
    ``index_file`` are for tests; the command line writes only where rule 36 names.
    """

    if reading not in READINGS:
        raise ScorerError(f"The protocol names no reading {reading!r}; it names gw20 and gw38.")
    target = records_dir / f"planner_policy_chain_{reading}.json"
    twin = target.with_suffix(".md")
    if target.exists() or twin.exists():
        raise ScorerError(f"The {reading} reading was taken already: {target} exists.")
    identity = source_identity()
    committed = committed_reading(reading)
    if committed is not None:
        raise ScorerError(
            f"The {reading} reading was taken already: its record is in committed history at "
            f"{committed}."
        )
    written = written_reading(reading)
    if written is not None:
        raise ScorerError(f"The {reading} reading was taken already: {written} exists.")
    tags = release_tags()
    captures = _captures(snapshot_root)
    gameweek = READINGS[reading]
    if not settled(captures, gameweek):
        raise ScorerError(
            f"GW{gameweek} has not settled in any capture; the {reading} reading waits."
        )
    protocol, weeks = read_evidence(evidence, gameweek)
    record = reading_record(
        reading=reading,
        protocol=protocol,
        evidence=weeks,
        captures=captures,
        identity=identity,
        binding=lambda deadline, frozen: release_binding(deadline, frozen, tags),
        tags=tags,
    )
    records_dir.mkdir(parents=True, exist_ok=True)
    write_document_once(record, target)
    twin.write_text(render_markdown(record), encoding="utf-8")
    index_text = index_file.read_text(encoding="utf-8") if index_file.exists() else ""
    if f"planner_policy_chain_{reading}" not in index_text:
        with index_file.open("a", encoding="utf-8") as handle:
            handle.write(
                ("" if index_text.endswith("\n") or not index_text else "\n")
                + index_row(record)
                + "\n"
            )
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--reading", choices=sorted(READINGS), required=True)
    arguments = parser.parse_args(argv)
    try:
        # Rules 36 and 37: the command line writes only where the protocol names, so a reading
        # cannot be taken again into another place.
        record = score(arguments.evidence, arguments.snapshot_root, arguments.reading)
    except ScorerError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    primary = record["contrasts"]["A"]["primary"]
    print(
        json.dumps(
            {
                "reading": record["reading"],
                "weeks": primary["weeks"],
                "contrast_A_mean": primary["mean"],
                "contrast_B_mean": record["contrasts"]["B"]["primary"]["mean"],
                "verdicts": {
                    label: block["primary"]["verdict"]
                    for label, block in record["contrasts"].items()
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
