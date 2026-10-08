"""The planner policy chain's two readings, `gw20` and `gw38`, each taken once.

``docs/research/planner_policy_chain_prereg.md`` fixes every rule this script applies, and the
rule numbers below are that document's. The runner (``scripts/measure_planner_policy_chain.py``)
decides the weeks and reads no outcome; this scorer reads the runner's evidence and the season's
outcome captures, once per reading, and writes the record the protocol names.

A reading refuses to start before its gameweek settles, refuses a reading the protocol does not
name, refuses a reading taken twice, and runs only from its own merge commit (rule 37). It
fetches origin before it reads any history, so that its merge commit, the readings already
taken, the release tags and the interim record are read as origin holds them. The interim
reading records no verdict (rule 32). The final reading reads the interim record from origin's
develop, as the commit that first added it holds it, so the interim record is merged before the
final reading is taken, and it lists each interim week whose outcome capture changed with both
scores (rule 25). Everything a reading writes is rendered before the first write, the twin and
the index row from the record's own bytes (rule 36).

Run from a clean checkout of the scorer's merge commit, in a clone that is not shallow and can
reach origin, with E the runner's evidence directory, S the capture root it decided from, R the
receipts the operator posted on the chain's tracking issue (rule 24), in the shape
``read_receipts`` states, and P the producer changes that keep a version name as the operator
declared them there (rule 6), in the shape ``read_producer_changes`` states, or the word none.
R and P are kept outside the checkout, because an untracked file leaves the tree unclean and
the reading is refused:

    python -m scripts.score_planner_policy_chain --evidence E --snapshot-root S --receipts R
        --producer-changes P --reading gw20
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
from collections.abc import Callable, Iterable, Mapping, Sequence
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
from squadopt.data.atomic import document_bytes, write_bytes_once, write_document_once
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FPL_LIVE_SOURCE,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    player_snapshot,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.evaluation.live_series import DetectionPolicy, detectable_effect
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval
from squadopt.live.recommendation import infer_season
from squadopt.live.rules import read_season_rules
from squadopt.planning.pricing import sell_price_tenths

REPOSITORY = Path(__file__).resolve().parents[1]
PROTOCOL_ID = "planner_policy_chain_v1"
SEASON = "2026-27"
PROTOCOL_FILE = "docs/research/planner_policy_chain_prereg.md"
RUNNER_FILE = "scripts/measure_planner_policy_chain.py"
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
#: Rule 25: the reading whose record the final reading compares its weeks with.
INTERIM_READING = "gw20"
ARMS: tuple[str, ...] = ("served_3", "served_5", "hold_3", "hold_5", "one_week")
#: Rule 14: each arm's window in weeks, and the last gameweek a window may reach.
WINDOW_WEEKS: dict[str, int] = {
    "served_3": 3,
    "served_5": 5,
    "hold_3": 3,
    "hold_5": 5,
    "one_week": 1,
}
LAST_GAMEWEEK = 38
#: Rule 6: the model versions the protocol admits, and the one whose week may bind without its
#: ready bundle's marker or its components file; each reading reports such weeks apart.
ADMITTED_MODEL_VERSIONS: tuple[str, ...] = (
    "football_team_share_v1",
    "football_joint_role_minutes_v1",
    "football_joint_role_retained_history_v1",
)
TEAM_SHARE_VERSION = "football_team_share_v1"
#: Rule 6: what a reading reads when the operator declared no producer change.
NO_PRODUCER_CHANGES: Mapping[str, Any] = {"source": None, "changes": ()}
#: Rule 9: the three constructed squads, named as the runner names them, by budget in tenths.
PROFILES: tuple[str, ...] = ("p1000", "p950", "p900")
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
#: Rules 29 and 35: the pairings each squad is reported for, and the paired totals are given for.
REPORTED_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    **CONTRASTS,
    "hold_minus_one_week": SECONDARY_PAIRS["hold_minus_one_week"],
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
    "other worktree of this repository, when the checkout's measurements index already links its "
    "record, or when either file was touched by any commit reachable from any ref or reflog once "
    "the scorer has fetched every branch from origin. A reading written in a separate clone is "
    "seen only once it is committed there and pushed to a branch on origin."
)
PINNED_PACKAGES: tuple[str, ...] = ("ortools", "numpy", "pandas")
#: Rules 3 and 28: the fields of the runner's protocol.json that each record repeats. Both
#: readings read one chain, so the final reading refuses an interim record that differs in any.
FROZEN_SOURCE_FIELDS: tuple[str, ...] = (
    "repository_commit",
    "protocol_sha256",
    "runner_sha256",
    "binding_commits",
    "first_chain_week",
    "bound_week",
    "skipped_weeks",
    "dropped_profiles",
    "answer",
)
#: Rules 2 and 3, as each record states it: what the scorer reads again from git at the frozen
#: commit.
FROZEN_SOURCE_CHECK = (
    "protocol_sha256 and runner_sha256 are the sha256 of git show <frozen commit>:<file>. "
    "binding_commits are the commits that added the protocol and the runner on the frozen "
    "commit's first-parent line, and the frozen commit is the later of the two. The frozen "
    "commit lies on the first-parent line of the commit the scorer ran from, so it is a merge on "
    "develop and never a feature commit (rule 2)."
)
#: Rule 24, as each record states it: where the receipts came from and what was held to them.
RECEIPTS_RULE = (
    "The frozen commit and each week's manifest sha256, as the operator posted them on the "
    "chain's tracking issue, are transcribed into a receipts file, recorded by its sha256. Each "
    "value names the comment it was posted in. The scorer does not read the issue itself. It "
    "held protocol.json's frozen commit, and the bytes of every manifest the reading reads, to "
    "these values and refused any difference."
)
#: Rule 36: the files a week holds beside its records. Every other JSON document in a week's
#: directory is a record. The atomic writer's temporaries carry another suffix, and the week's
#: evidence_digest covers them like any other file.
WEEK_FILES: frozenset[str] = frozenset({"manifest.json", "receipt.json", "forecast.json"})
WEEK_DIRECTORY = re.compile(r"gw(\d{2})")
FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
FULL_SHA256 = re.compile(r"[0-9a-f]{64}")
#: Rule 25: the runner never opens a capture named before the season opens, and leaves out one
#: whose bootstrap names another season (its SEASON_OPENS and capture_inventory). So does the
#: scorer.
SEASON_OPENS = datetime(2026, 6, 1, tzinfo=UTC)
CAPTURE_INSTANT = re.compile(r"-(\d{8}T\d{6}Z)-")
#: Rule 25, as each record states it: the captures a week's outcome capture is chosen from, and
#: the deadline it is chosen against.
CAPTURE_SET_RULE = (
    "The outcome captures are read as the runner takes its inventory: every fpl-live capture "
    f"under the snapshot root whose bootstrap names season {SEASON}. A capture named before "
    f"{SEASON_OPENS:%Y-%m-%d} is never opened, and any other capture that cannot be read refuses "
    "the reading. A week's deadline is the one its receipt records, which its decision capture "
    "stated. Only a week whose receipt states none takes the deadline the newest capture states."
)
#: Rule 26, as each record states it: the capture the end state's sale value is read from, which
#: the protocol does not name.
END_PRICES_RULE = (
    "The end state is valued at the prices and the sell-on fee of the reading gameweek's own "
    "outcome capture (rule 25), each held player sold as rule 18 sells him. No earlier week's "
    "capture stands in for it. When there is no such capture, or it cannot be read, no sale value "
    "is stated and the reason is recorded. A chain that holds a player the capture does not "
    "price gets no sale value (rule 23)."
)
#: Rule 31, stated beside every interval: how often the check's interval covered zero, and how
#: often its upper bound fell below zero, the rate that bears on the `worse` clause.
COVERAGE_NOTE = (
    "At these counts the interval is narrower than its level: in the protocol's synthetic check "
    "(400 replicates, standard deviation 11.6, true difference zero) it covered zero in 58, 76 "
    "and 82 per cent of replicates at 7, 15 and 31 weeks, and its upper bound fell below zero in "
    "20, 12 and 12 per cent. At a lag-one autocorrelation of 0.2 it covered zero in 54, 74 and 78 "
    "per cent, and fell below zero in 26, 15 and 10 per cent."
)
#: Where the protocol leaves the scorer a choice, the narrowest reading, stated in every record.
CHOICES: dict[str, str] = {
    "truncation": (
        "Rule 14 is applied pair by pair. A squad and window pair either of whose arms was "
        "truncated that week enters no series but the truncated block of contrast A or B, which "
        "rule 14 keeps beside them, and a truncated pair of hold minus one_week enters none. A "
        "week enters a series when one of its pairs does, so GW35 and GW36 enter contrasts A and "
        "B on their three-week pairs. Every other series and squad takes the untruncated pairs "
        "only. The totals count every played week, truncated ones included. A decided or failed "
        "record whose truncation is not the one rule 14 gives refuses the reading."
    ),
    "served_route": (
        "Contrast A by route and outcome gives each squad and window pair its own served chain's "
        "label: the route and its version, the observed window's status on the observed route, "
        "the expected window's status and chosen proposal on the expected route, and whether the "
        "guarded construction completed (true, false, or none where the plan carries none). A "
        "failed served chain played its held team, so it is labelled by its failure. A pair whose "
        "hold chain failed stays under its served chain's label, as rule 22 keeps it in the "
        "pairs. Only the untruncated pairs contrast A takes are split, and a label with none of "
        "them gets no block."
    ),
    "team_share_without_marker_or_components": (
        "A week that bound is reported apart for contrasts A and B under rule 6 when its receipt "
        "states football_team_share_v1 and does not record both the ready bundle's marker and "
        "the components file as present; a presence the receipt does not record counts as "
        "absent. Such a week stays in every pooled series."
    ),
    "producer_changes": (
        "A producer change that keeps its version name is taken only as the operator declares "
        "it, with its version, its first week and the declaration's source, and the record "
        "states when none was declared; the scorer infers no change from the receipts. Each "
        "declared change is reported apart for contrasts A and B, over the weeks of its version "
        "from its first week up to the next change declared for that version. A declared first "
        "week before the chain's first week, or one this reading decided under another version, "
        "refuses the reading."
    ),
    "without_failed_weeks": (
        "Rule 22 calls one squad's failed arm in one gameweek a failed week, so each contrast "
        "without failed weeks leaves out every pair in which either arm failed and keeps that "
        "gameweek's other pairs; a gameweek leaves that series only when no pair is left. Every "
        "block counts its pairs in which an arm failed, and the series without failed weeks "
        "counts the ones it left out."
    ),
    "by_squad": (
        "Rule 29 names each squad and no contrast, so each squad is reported for contrast A, "
        "contrast B and hold minus one_week, each on that squad's own pairs under the series rule "
        "every other block uses."
    ),
    "proved_share": (
        "Rule 20's share is taken over the plans each arm played: its decided records whose "
        "solver.proved is true, over its decided records, in every week of the reading, "
        "truncated weeks included. The runner records an observed comparison, published "
        "FEASIBLE, as not proved. A failed arm played its held team and no plan, so its failed "
        "weeks are counted beside the share and not in it."
    ),
    "blocked_chains": (
        "Rule 23: a blocked chain is listed in every week of the reading from the week it was "
        "blocked in, with that week and the reason its record states. Rule 22: each failed arm "
        "is listed in its week, with the reason its record states."
    ),
    "model_versions": (
        "Rules 6 and 29: each contrast is also reported for each model version a week that is "
        "not missing was served under, on that version's scored weeks, from the first such week. "
        "A version whose weeks were all unscored keeps a block with no weeks, so its first week "
        "stays recorded. A missing week opens no block, whatever version its receipt names."
    ),
    "changed_outcome_captures": (
        "Rule 25: each reading keeps, for each week, the weekly difference of contrasts A and B "
        "beside its outcome capture id, as the paired differences rule 35 allows at the interim. "
        "The final reading reads the interim record from origin's develop, as the first commit on "
        "develop's first-parent line that added it holds it (rule 24: the first record stands). "
        "That record must name this scorer's merge commit, every protocol.json field this reading "
        "records, the same weeks and, for each, the decision capture, the missing reason and the "
        "manifest sha256 this reading holds it to. Every interim week that is not missing and "
        "whose outcome capture id differs, to or from none included, is listed with both ids and "
        "both weekly differences. A week whose outcome capture did not change must give the "
        "differences the interim recorded, or the reading is refused."
    ),
}


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


# Rule 25: the interim record, read again at the final reading


@dataclass(frozen=True)
class InterimRecord:
    """The interim record as develop on origin holds it: its document, the commit on develop's
    first-parent line that first added it, the develop commit it was read at and the sha256 of
    its bytes."""

    record: Mapping[str, Any]
    added_commit: str
    develop_commit: str
    sha256: str


def interim_reading() -> InterimRecord:
    """Rule 25: the interim record, read from develop as origin holds it.

    Read after ``source_identity`` has fetched origin. The scorer runs from its own merge
    commit, which the interim record postdates, so the record is read from develop's history and
    never from the checkout. Rule 24's first record stands: the record is read as the first
    commit on develop's first-parent line that added it holds it, so a later edit on develop is
    never read in its place, and a record on a branch develop has not taken is not read at all.
    """

    path, _ = record_paths(INTERIM_READING)
    develop = _git("rev-parse", "--verify", f"{DEVELOP}^{{commit}}")
    added = _git(
        "log",
        "--first-parent",
        "--diff-merges=first-parent",
        "--diff-filter=A",
        "--reverse",
        "--no-patch",
        "--format=%H",
        develop,
        "--",
        path,
    ).split()
    if not added:
        raise ScorerError(
            "The final reading lists each week whose outcome capture changed since the interim "
            f"(rule 25), and develop on origin holds no {path}: the interim reading is merged "
            "before the final one is taken."
        )
    # The trailing "--" names the argument a revision, so git never looks for it on disk.
    raw = _git_bytes("show", f"{added[0]}:{path}", "--")
    try:
        record = json.loads(raw.decode("utf-8"))
    except ValueError as error:
        raise ScorerError(f"{path} as {added[0]} added it is not JSON: {error}") from error
    if not isinstance(record, dict):
        raise ScorerError(f"{path} as {added[0]} added it is not a record.")
    return InterimRecord(record, added[0], develop, hashlib.sha256(raw).hexdigest())


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _week_score(week: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "outcome_capture": week.get("outcome_capture"),
        "unscored_reason": week.get("unscored_reason"),
        "differences": week.get("differences"),
    }


def changed_since_interim(
    interim: InterimRecord,
    weeks: Sequence[Mapping[str, Any]],
    identity: Mapping[str, object],
    frozen_source: Mapping[str, Any],
    manifests: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Rule 25: each interim week whose outcome capture changed by this reading, listed with
    both capture ids and both weekly differences of each primary contrast.

    The interim record must be this protocol's interim reading of the same chain: scored from
    this scorer's merge commit (rule 37), on the protocol.json fields this reading records
    (rule 3), over the same weeks, each with the decision capture, the missing reason and the
    manifest sha256 this reading holds it to (rule 24). A week whose outcome capture did not
    change must give the differences the interim recorded. ``weeks`` are this reading's listed
    weeks and ``manifests`` the receipts it held them to.
    """

    earlier = interim.record
    path, _ = record_paths(INTERIM_READING)
    named = (earlier.get("protocol"), earlier.get("season"), earlier.get("reading"))
    if named != (PROTOCOL_ID, SEASON, INTERIM_READING):
        raise ScorerError(f"{path} on develop is not this protocol's interim record.")
    scorer = _mapping(earlier.get("identity")).get("scorer_merge_commit")
    if scorer != identity.get("scorer_merge_commit"):
        raise ScorerError(
            f"The interim record was scored from {scorer}, and this reading runs from "
            f"{identity.get('scorer_merge_commit')}: rule 37 runs both from one merge commit."
        )
    source = _mapping(earlier.get("frozen_source"))
    differing = [key for key in FROZEN_SOURCE_FIELDS if source.get(key) != frozen_source.get(key)]
    if differing:
        raise ScorerError(
            "The interim record was read from another frozen source (rule 3): its "
            f"{', '.join(differing)} differ from this reading's."
        )
    before_weeks = earlier.get("weeks")
    if not isinstance(before_weeks, list) or not all(
        isinstance(week, Mapping) for week in before_weeks
    ):
        raise ScorerError(f"{path} on develop lists no weeks.")
    now = {int(week["gameweek"]): week for week in weeks}
    through = READINGS[INTERIM_READING]
    if [week.get("gameweek") for week in before_weeks] != sorted(g for g in now if g <= through):
        raise ScorerError(
            f"The interim record lists other weeks than this reading's through GW{through}."
        )
    posted = _mapping(_mapping(earlier.get("receipts")).get("manifests"))
    changed: list[dict[str, Any]] = []
    for before in before_weeks:
        gameweek = int(before["gameweek"])
        after = now[gameweek]
        name = f"gw{gameweek:02d}"
        same = (
            before.get("decision_capture") == after.get("decision_capture")
            and before.get("missing_reason") == after.get("missing_reason")
            and _mapping(posted.get(name)).get("sha256")
            == _mapping(manifests.get(name)).get("sha256")
        )
        if not same:
            raise ScorerError(
                f"GW{gameweek:02d}: the interim record was read from other decisions than this "
                "reading's (rule 24)."
            )
        if after.get("missing_reason") is not None:
            continue
        if before.get("outcome_capture") == after.get("outcome_capture"):
            if _canonical(before.get("differences")) != _canonical(after.get("differences")):
                raise ScorerError(
                    f"GW{gameweek:02d}: the interim read the same outcome capture and recorded "
                    "other differences."
                )
            continue
        changed.append(
            {"gameweek": gameweek, "interim": _week_score(before), "final": _week_score(after)}
        )
    return {
        "record": path,
        "read_from": DEVELOP,
        "develop_commit": interim.develop_commit,
        "added_commit": interim.added_commit,
        "sha256": interim.sha256,
        "scorer_merge_commit": scorer,
        "interim_weeks": len(before_weeks),
        "changed_weeks": changed,
    }


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


# Rules 2 and 3: the frozen source, read again from git


def _binding_commits(frozen: str, *, root: Path | None = None) -> dict[str, dict[str, str]]:
    """Rule 2 as the runner applied it at the frozen commit: the commits that added the protocol
    and the runner on that commit's first-parent line, each compared with its first parent, each
    with its committer instant in UTC and its place on the line."""

    commits = {}
    for name, path in (("protocol", PROTOCOL_FILE), ("runner", RUNNER_FILE)):
        added = _git(
            "log",
            "--first-parent",
            "--diff-merges=first-parent",
            "--diff-filter=A",
            "--no-patch",
            "--format=%H %cI",
            "-1",
            frozen,
            "--",
            path,
            cwd=root,
        )
        if not added:
            raise ScorerError(f"{path} was never added on the line of the frozen commit {frozen}.")
        sha, instant = added.split(" ", 1)
        position = int(_git("rev-list", "--first-parent", "--count", sha, "--", cwd=root))
        commits[name] = {
            "commit": sha,
            "committed_utc": _instant(instant).isoformat(),
            "line_position": str(position),
        }
    return commits


def _frozen_bytes(frozen: str, path: str, root: Path | None) -> bytes:
    """A file's bytes at the frozen commit, as ``git show HEAD:<file>`` gave them to the runner
    with HEAD at that commit. A commit or a file git does not hold refuses the reading."""

    try:
        # The trailing "--" names the argument a revision, so git never looks for it on disk.
        return _git_bytes("show", f"{frozen}:{path}", "--", cwd=root)
    except ScorerError as error:
        raise ScorerError(f"git cannot read the frozen commit {frozen}: {error}") from error


def check_frozen_source(protocol: Mapping[str, Any], *, root: Path | None = None) -> None:
    """Rules 2 and 3: protocol.json's frozen source, read again from git at its own commit.

    The runner recorded the sha256 of this protocol and of itself as ``git show HEAD:<file>``
    with HEAD at the frozen commit, and the two merges that bound the chain on that commit's
    first-parent line, the frozen commit being the later. The scorer reads all of it again from
    the commit and refuses any difference, so protocol.json says nothing about its source that
    the repository does not. A merge is a commit on develop's first-parent line, never the
    feature commit that wrote the file, and a runner run from a feature commit would name that
    commit its own merge. The scorer runs from its own merge commit on develop (rule 37), so the
    frozen commit must lie on the first-parent line of the commit the scorer runs from.
    """

    frozen = str(protocol.get("repository_commit"))
    if not FULL_COMMIT.fullmatch(frozen):
        raise ScorerError(f"protocol.json names no full frozen commit: {frozen!r}.")
    for key, path in (("protocol_sha256", PROTOCOL_FILE), ("runner_sha256", RUNNER_FILE)):
        digest = hashlib.sha256(_frozen_bytes(frozen, path, root)).hexdigest()
        if protocol.get(key) != digest:
            raise ScorerError(
                f"protocol.json's {key} is not the sha256 of {path} at the frozen commit."
            )
    commits = _binding_commits(frozen, root=root)
    if protocol.get("binding_commits") != commits:
        raise ScorerError(
            "protocol.json's binding_commits are not the merges on the frozen commit's line."
        )
    later = max(
        commits.values(),
        key=lambda entry: (int(entry["line_position"]), _instant(entry["committed_utc"])),
    )
    if later["commit"] != frozen:
        raise ScorerError(
            f"The frozen commit {frozen} is not the later of the two merges that bound the chain."
        )
    if frozen not in _git("rev-list", "--first-parent", "HEAD", "--", cwd=root).split():
        raise ScorerError(
            f"The frozen commit {frozen} is not on the first-parent line the scorer runs from, "
            "so it is no merge on develop: a feature commit is never the frozen source (rule 2)."
        )


# Rule 36: the runner's evidence


@dataclass(frozen=True)
class WeekEvidence:
    gameweek: int
    receipt: Mapping[str, Any]
    manifest: Mapping[str, Any]
    records: Mapping[tuple[str, str], Mapping[str, Any]]


def _document(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        document = json.loads(raw.decode("utf-8"))
    except ValueError as error:
        raise ScorerError(f"{path} cannot be read: {error}") from error
    if not isinstance(document, dict):
        raise ScorerError(f"{path} is not a JSON object.")
    return cast(dict[str, Any], document)


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ScorerError(f"{path} cannot be read: {error}") from error
    return _document(raw, path)


# Rule 24: the receipts the operator posted


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """An operator's JSON object, refused when it gives a key twice, so that no value is lost to
    a later one of the same name."""

    names = [name for name, _ in pairs]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"the file gives {repeated} more than once")
    return dict(pairs)


def _posted(entry: object, key: str, pattern: re.Pattern[str], label: str) -> dict[str, str]:
    if not isinstance(entry, dict) or set(entry) != {key, "posted"}:
        raise ScorerError(f"The receipt for {label} must hold exactly {key!r} and 'posted'.")
    value, posted = entry[key], entry["posted"]
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ScorerError(f"The receipt for {label} holds no full {key}: {value!r}.")
    if not isinstance(posted, str) or not posted.strip():
        raise ScorerError(f"The receipt for {label} does not name the comment it was posted in.")
    return {key: value, "posted": posted}


def read_receipts(path: Path) -> dict[str, Any]:
    """Rule 24: the frozen commit and each week's manifest sha256, as the operator posted them
    on the chain's tracking issue, transcribed into one JSON file:

        {"tracking_issue": "<issue URL>",
         "frozen_commit": {"commit": "<40 hex>", "posted": "<comment URL>"},
         "manifests": {"gw06": {"sha256": "<64 hex>", "posted": "<comment URL>"}, ...}}

    Each value names the comment it was posted in. The scorer does not read the issue itself:
    it holds the evidence to these values and repeats them in the record, where a reader can
    hold them to the issue. A key given twice, a value cut short or a missing comment is
    refused. A byte order mark, which Windows PowerShell 5.1 writes with UTF-8, is read past;
    the file's sha256 is of its bytes as they stand.
    """

    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except (OSError, ValueError) as error:
        raise ScorerError(f"The receipts file {path} cannot be read: {error}") from error
    if not isinstance(document, dict) or set(document) != {
        "tracking_issue",
        "frozen_commit",
        "manifests",
    }:
        raise ScorerError(
            "The receipts file must hold exactly tracking_issue, frozen_commit and manifests."
        )
    issue = document["tracking_issue"]
    if not isinstance(issue, str) or not issue.strip():
        raise ScorerError("The receipts file does not name the chain's tracking issue.")
    manifests = document["manifests"]
    if not isinstance(manifests, dict):
        raise ScorerError("The receipts file's manifests must map each gwNN to its receipt.")
    checked: dict[str, dict[str, str]] = {}
    for name, entry in sorted(manifests.items()):
        week = WEEK_DIRECTORY.fullmatch(name)
        if week is None or not 1 <= int(week.group(1)) <= READINGS["gw38"]:
            raise ScorerError(f"The receipts name {name!r}, which is no gameweek directory.")
        checked[name] = _posted(entry, "sha256", FULL_SHA256, name)
    return {
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "tracking_issue": issue,
        "frozen_commit": _posted(document["frozen_commit"], "commit", FULL_COMMIT, "the commit"),
        "manifests": checked,
    }


def evidence_digest(directory: Path) -> str:
    """The runner's digest of a week's files: relative name and sha256, the manifest left out."""

    digest = hashlib.sha256()
    files = (p for p in directory.rglob("*") if p.is_file() and p.name != "manifest.json")
    for path in sorted(files):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def _first_chain_week(protocol: Mapping[str, Any]) -> int:
    """Rules 2 and 9: the first chain week, held to the bound week and the weeks the protocol
    record says were skipped from it."""

    try:
        first = int(protocol["first_chain_week"])
        bound = int(protocol["bound_week"])
        skipped = [int(entry["gameweek"]) for entry in protocol["skipped_weeks"]]
    except (KeyError, TypeError, ValueError) as error:
        raise ScorerError(f"protocol.json cannot state its first chain week: {error!r}") from error
    if bound > first or skipped != list(range(bound, first)):
        raise ScorerError(
            f"protocol.json's first chain week GW{first:02d} does not follow its bound week "
            f"GW{bound:02d} and the weeks it lists as skipped."
        )
    return first


def _kept_records(protocol: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """Rule 9: every squad the protocol builds and the record does not drop, times every arm,
    by the name the runner writes its record under."""

    dropped = protocol.get("dropped_profiles")
    if not isinstance(dropped, dict) or not set(dropped) <= set(PROFILES):
        raise ScorerError(f"protocol.json drops {dropped!r}, which are not the protocol's squads.")
    return {
        f"{profile}-{arm}.json": (profile, arm)
        for profile in PROFILES
        if profile not in dropped
        for arm in ARMS
    }


def _differ(found: set[str], kept: Mapping[str, object]) -> str:
    return f"missing {sorted(set(kept) - found)}, not kept {sorted(found - set(kept))}"


def _week_evidence(
    evidence: Path,
    gameweek: int,
    receipt: Mapping[str, str] | None,
    kept: Mapping[str, tuple[str, str]],
    frozen: str,
) -> WeekEvidence:
    """One decided week, checked in order: its manifest's bytes against the sha256 posted for
    it, the week's files against the manifest's evidence_digest, the records the manifest lists
    and the records beside it against the kept chains, and each record against its own digest,
    its path and the frozen commit it was decided from."""

    label = f"GW{gameweek:02d}"
    directory = evidence / f"gw{gameweek:02d}"
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ScorerError(f"{label} is not decided; the reading waits for it.")
    if receipt is None:
        raise ScorerError(f"{label}: no manifest sha256 was posted for it (rule 24).")
    try:
        raw = manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            raise ScorerError(
                f"{label}: the manifest is not the one posted in {receipt['posted']}."
            )
        manifest = _document(raw, manifest_path)
        named = (manifest.get("gameweek"), manifest.get("protocol"), manifest.get("season"))
        if named != (gameweek, PROTOCOL_ID, SEASON):
            raise ScorerError(f"{manifest_path} names another gameweek, protocol or season.")
        recorded = manifest.get("evidence_digest")
        if not isinstance(recorded, str):
            raise ScorerError(f"{label}: the manifest records no evidence_digest.")
        if evidence_digest(directory) != recorded:
            raise ScorerError(f"{label}: the week's files no longer match their manifest.")
        listed = manifest.get("records")
        if not isinstance(listed, dict) or set(listed) != set(kept):
            found = set(listed) if isinstance(listed, dict) else set()
            raise ScorerError(
                f"{label}: the manifest's records are not the kept chains: {_differ(found, kept)}."
            )
        beside = {
            path.name
            for path in directory.glob("*.json")
            if path.is_file() and path.name not in WEEK_FILES
        }
        if beside != set(kept):
            raise ScorerError(
                f"{label}: the records beside the manifest are not the kept chains: "
                f"{_differ(beside, kept)}."
            )
        records: dict[tuple[str, str], Mapping[str, Any]] = {}
        for name, (profile, arm) in sorted(kept.items()):
            path = directory / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != listed[name]:
                raise ScorerError(f"{path} does not match the digest its manifest records.")
            record = _load(path)
            stated = (record.get("profile"), record.get("arm"), record.get("gameweek"))
            if stated != (profile, arm, gameweek):
                raise ScorerError(
                    f"{path} records {stated}, not the chain and week its path names."
                )
            if (record.get("protocol"), record.get("season")) != (PROTOCOL_ID, SEASON):
                raise ScorerError(f"{path} is not this protocol's.")
            provenance = record.get("provenance")
            if not isinstance(provenance, dict) or provenance.get("repository_commit") != frozen:
                raise ScorerError(f"{path} was not decided from the frozen commit (rule 3).")
            records[(profile, arm)] = record
        week_receipt = _load(directory / "receipt.json")
        if week_receipt.get("gameweek") != gameweek:
            raise ScorerError(f"{directory / 'receipt.json'} names another gameweek.")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ScorerError(f"{label}: the week's evidence cannot be read: {error!r}") from error
    return WeekEvidence(gameweek, week_receipt, manifest, records)


def _starts_alike(week: WeekEvidence) -> None:
    """Rule 10: in the first chain week every arm of a squad plans from the same state. A week
    reached after an earlier decided week holds the states the arms' own decisions left, which
    differ wherever the arms did, so such a week is never named the first chain week (rules 2
    and 9)."""

    for profile in sorted({profile for profile, _ in week.records}):
        states = {
            json.dumps(week.records[(profile, arm)].get("state_before"), sort_keys=True)
            for arm in ARMS
        }
        if len(states) != 1:
            raise ScorerError(
                f"GW{week.gameweek:02d} is not where squad {profile}'s chains start: its arms "
                "plan from different states (rule 10)."
            )


def read_evidence(
    evidence: Path, through: int, receipts: Mapping[str, Any]
) -> tuple[dict[str, Any], list[WeekEvidence]]:
    """Every decided week from the first chain week through ``through``, each held to the
    receipts posted for it (rule 24) and to its own manifest (rule 36); a week not yet decided
    refuses the reading.

    protocol.json must name this protocol and season, and the frozen commit the operator
    posted. Its first chain week must follow the skipped weeks it lists, and no week directory
    or posted receipt may lie before it. Each week's records must be exactly the kept chains,
    every squad not dropped times every arm, as the manifest lists them and as the documents
    beside it, and each record must name the chain and week its path does. In the first chain
    week every arm of a squad must hold the same state_before (rule 10).
    """

    protocol_path = evidence / "protocol.json"
    if not protocol_path.is_file():
        raise ScorerError(f"{evidence} holds no protocol.json; the chain has not started.")
    protocol = _load(protocol_path)
    if protocol.get("protocol") != PROTOCOL_ID or protocol.get("season") != SEASON:
        raise ScorerError("The evidence is not this protocol's.")
    frozen = cast(Mapping[str, str], receipts["frozen_commit"])
    if protocol.get("repository_commit") != frozen["commit"]:
        raise ScorerError(
            f"protocol.json names the frozen commit {protocol.get('repository_commit')!r}; "
            f"{frozen['posted']} posted {frozen['commit']}."
        )
    first = _first_chain_week(protocol)
    early = sorted(
        path.name
        for path in evidence.glob("gw*")
        if (match := WEEK_DIRECTORY.fullmatch(path.name)) and int(match.group(1)) < first
    )
    if early:
        raise ScorerError(f"{early} lie before the first chain week GW{first:02d}.")
    posted = cast(Mapping[str, Mapping[str, str]], receipts["manifests"])
    early = sorted(name for name in posted if int(name[2:]) < first)
    if early:
        raise ScorerError(f"Receipts were posted for {early}, before the first chain week.")
    kept = _kept_records(protocol)
    weeks = [
        _week_evidence(evidence, gameweek, posted.get(f"gw{gameweek:02d}"), kept, frozen["commit"])
        for gameweek in range(first, through + 1)
    ]
    if weeks:
        _starts_alike(weeks[0])
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


def _named_before_season(snapshot_id: str) -> bool:
    match = CAPTURE_INSTANT.search(snapshot_id)
    if match is None:
        return False
    named = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return named < SEASON_OPENS


def _captures(snapshot_root: Path) -> list[CapturedSnapshot]:
    """The season's live captures, as the runner takes its inventory: a capture named before
    the season opens is never opened, one whose bootstrap names another season is left out, and
    any other that cannot be read refuses the reading, since it could be a week's latest."""

    captures = []
    for snapshot_id in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        if _named_before_season(snapshot_id):
            continue
        try:
            capture = read_snapshot(snapshot_root, snapshot_id)
            if infer_season(capture) != SEASON:
                continue
        except (DataError, ValueError, KeyError, TypeError) as error:
            raise ScorerError(f"Capture {snapshot_id} cannot be read: {error}") from error
        captures.append(capture)
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


def week_deadline(
    captures: Sequence[CapturedSnapshot], week: WeekEvidence
) -> tuple[str | None, str | None]:
    """The week's deadline and where it was read. The receipt's is the deadline the decision
    capture stated, which the runner decided after (rules 5 and 36). Only a week whose receipt
    states none, one with no decision capture, takes the newest capture's. A receipt deadline
    that is not an instant refuses the reading."""

    stated = week.receipt.get("deadline_utc")
    if stated is not None:
        if not isinstance(stated, str):
            raise ScorerError(f"GW{week.gameweek:02d}'s receipt states no readable deadline.")
        try:
            _instant(stated)
        except ScorerError as error:
            raise ScorerError(f"GW{week.gameweek:02d}'s receipt: {error}") from error
        return stated, "receipt"
    newest = _deadline(captures, week.gameweek)
    return newest, None if newest is None else "newest_capture"


def settled(captures: Sequence[CapturedSnapshot], gameweek: int) -> bool:
    """Rule 28: a gameweek has settled when a capture counts it in scored_gameweeks."""

    for capture in captures:
        try:
            if gameweek in scored_gameweeks(capture.payloads[BOOTSTRAP_PAYLOAD]):
                return True
        except (DataError, ValueError, KeyError, TypeError):
            continue
    return False


def outcome_capture(
    captures: Sequence[CapturedSnapshot], gameweek: int, deadline: str | None = None
) -> Outcome:
    """Rule 25: of the captures at or after the deadline whose bootstrap counts the week in
    scored_gameweeks and that hold its live payload, the latest; a tie leaves the week unscored.
    ``deadline`` is the week's own (``week_deadline``); without one, the newest capture's."""

    if deadline is None:
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
    #: Rule 14: the chains, as (profile, arm), whose window was truncated that week.
    truncated: frozenset[tuple[str, str]]
    #: Rule 13: each scored served chain's label, by (profile, arm).
    served_splits: Mapping[tuple[str, str], str]
    model_version: str | None
    missing_reason: str | None
    #: Rule 6: a team share week bound without its marker or its components file.
    team_share_apart: bool = False


def truncated_by_rule_14(arm: str, gameweek: int) -> bool:
    """Rule 14: a window decided at the gameweek is truncated when it would reach past GW38."""

    if arm not in WINDOW_WEEKS:
        raise ScorerError(f"GW{gameweek:02d}: {arm!r} is not one of the protocol's arms.")
    return gameweek + WINDOW_WEEKS[arm] - 1 > LAST_GAMEWEEK


def _label_value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def served_split(record: Mapping[str, Any]) -> str:
    """Rule 13: the label contrast A is split by, read from one served chain's record.

    A failed chain played its held team (rule 22), so it is labelled by its failure. Otherwise
    the label names the route and its version, the observed window's status on the observed
    route, the expected window's status and chosen proposal on the expected route, and whether
    the guarded construction completed: true, false, or none where the plan carries none.
    """

    if record.get("status") == "failed":
        return f"failed={_label_value(record.get('reason'))}"
    policy = cast(Mapping[str, Any], record.get("policy") or {})
    solver = cast(Mapping[str, Any], record.get("solver") or {})
    route = _label_value(policy.get("route"))
    parts = [f"route={route}", f"version={_label_value(policy.get('route_version'))}"]
    if route == "observed":
        parts.append(f"observed={_label_value(solver.get('observed_window_status'))}")
    if route == "expected":
        parts.append(f"expected={_label_value(solver.get('expected_window_status'))}")
        parts.append(f"chosen={_label_value(solver.get('expected_window_chosen'))}")
    parts.append(f"seed_completed={_label_value(solver.get('seed_completed'))}")
    return ":".join(parts)


def team_share_apart(receipt: Mapping[str, Any]) -> bool:
    """Rule 6: a team share week whose receipt does not record both its ready bundle's marker
    and its components file as present is reported apart."""

    both = receipt.get("ready_bundle_present") is True and receipt.get("components_present") is True
    return receipt.get("model_version") == TEAM_SHARE_VERSION and not both


def score_week(week: WeekEvidence, outcome: Outcome) -> WeekScores:
    """One week's scored chains, the chains rule 14 truncated, each scored served chain's
    label (rule 13), and whether rule 6 reports the week apart.

    Each decided or failed record's truncation is held to rule 14's, whether or not the week
    is scored; held and blocked records carry no window.
    """

    missing = week.manifest.get("missing_reason")
    scores: dict[tuple[str, str], ChainScore] = {}
    truncated: set[tuple[str, str]] = set()
    splits: dict[tuple[str, str], str] = {}
    for chain, record in sorted(week.records.items()):
        if record.get("status") in ("blocked", "held"):
            continue
        policy = record.get("policy")
        stated = policy.get("truncated") if isinstance(policy, Mapping) else None
        if not isinstance(stated, bool):
            raise ScorerError(
                f"GW{week.gameweek:02d} {chain[0]} {chain[1]}: the record states no truncation, "
                "which rule 14 fixes."
            )
        if stated != truncated_by_rule_14(chain[1], week.gameweek):
            raise ScorerError(
                f"GW{week.gameweek:02d} {chain[0]} {chain[1]}: the record's truncation is "
                f"{stated}, and rule 14 says {not stated}."
            )
        if stated:
            truncated.add(chain)
    if outcome.snapshot is not None and missing is None:
        outcomes = live_event_outcomes(
            outcome.snapshot.payloads[live_payload(week.gameweek)],
            outcome.snapshot.payloads[BOOTSTRAP_PAYLOAD],
            gameweek=week.gameweek,
        )
        for chain, record in sorted(week.records.items()):
            scored = score_chain_week(record, outcomes)
            if scored is None:
                continue
            scores[chain] = scored
            if chain[1].startswith("served_"):
                splits[chain] = served_split(record)
    return WeekScores(
        gameweek=week.gameweek,
        outcome=outcome,
        scores=scores,
        truncated=frozenset(truncated),
        served_splits=splits,
        model_version=cast(str | None, week.receipt.get("model_version")),
        missing_reason=cast(str | None, missing),
        team_share_apart=missing is None and team_share_apart(week.receipt),
    )


def week_difference(
    week: WeekScores,
    pairs: Sequence[tuple[str, str]],
    *,
    truncated_pairs: bool = False,
    without_failed: bool = False,
    keep_pair: Callable[..., bool] | None = None,
) -> dict[str, Any] | None:
    """Rule 27: the mean over the squad and window pairs both arms scored that week.

    Rule 14 is applied pair by pair: a pair either of whose arms was truncated that week is
    taken only when ``truncated_pairs`` asks for the truncated pairs, and then only such pairs
    are taken. ``keep_pair`` narrows the pairs further, by the week, the profile and the pair's
    left arm.
    """

    differences = []
    zero_pairs = 0
    failed_pairs = 0
    profiles = sorted({profile for profile, _ in week.scores})
    for profile in profiles:
        for left, right in pairs:
            first, second = week.scores.get((profile, left)), week.scores.get((profile, right))
            if first is None or second is None:
                continue
            truncated = bool({(profile, left), (profile, right)} & week.truncated)
            if truncated != truncated_pairs:
                continue
            if keep_pair is not None and not keep_pair(week, profile, left):
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
    truncated_pairs: bool = False,
    without_failed: bool = False,
    keep: Callable[..., bool] | None = None,
    keep_pair: Callable[..., bool] | None = None,
) -> list[dict[str, Any]]:
    """One row for each week that ``keep`` takes and in which at least one pair remains.

    ``keep`` and ``keep_pair`` are typed loosely because their lambdas bind loop values through
    default arguments.
    """

    rows = []
    for week in weeks:
        if keep is not None and not keep(week):
            continue
        row = week_difference(
            week,
            pairs,
            truncated_pairs=truncated_pairs,
            without_failed=without_failed,
            keep_pair=keep_pair,
        )
        if row is not None:
            rows.append(row)
    return rows


def _squad_blocks(
    weeks: Sequence[WeekScores], pairs: Sequence[tuple[str, str]], candidate_id: str
) -> dict[str, dict[str, Any]]:
    """Rule 29: one block for each squad, over the same pairs as the contrast it splits."""

    blocks = {}
    for profile in sorted({profile for week in weeks for profile, _ in week.scores}):
        rows = _series(weeks, pairs, keep_pair=lambda _week, p, _left, want=profile: p == want)
        blocks[profile] = _block(rows, candidate_id, final=False)
    return blocks


def _route_blocks(weeks: Sequence[WeekScores]) -> dict[str, dict[str, Any]]:
    """Rules 13 and 29: contrast A split by each pair's own served chain's label."""

    blocks = {}
    for split in sorted({split for week in weeks for split in week.served_splits.values()}):
        rows = _series(
            weeks,
            CONTRASTS["A"],
            keep_pair=lambda week, profile, left, s=split: (
                week.served_splits.get((profile, left)) == s
            ),
        )
        if rows:
            blocks[split] = _block(rows, f"{PROTOCOL_ID}:A", final=False)
    return blocks


def _block(rows: Sequence[Mapping[str, Any]], candidate_id: str, *, final: bool) -> dict[str, Any]:
    differences = [float(row["difference"]) for row in rows]
    summary = summarize(differences, candidate_id)
    return {
        **summary,
        "exact_zero_pairs": sum(int(row["exact_zero_pairs"]) for row in rows),
        # Rule 22: a failed arm's pairs stay in the pairs, and each block counts them.
        "failed_pairs": sum(int(row["failed_pairs"]) for row in rows),
        "pairs": sum(int(row["pairs"]) for row in rows),
        "weeks_listed": [int(row["gameweek"]) for row in rows],
        "verdict": verdict(summary, final=final),
    }


def _week_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A week's row of a primary series, as that week's entry keeps it (rule 25)."""

    if row is None:
        return None
    return {key: row[key] for key in ("difference", "pairs", "exact_zero_pairs", "failed_pairs")}


def _model_versions(weeks: Sequence[WeekScores]) -> dict[str, int]:
    """Rules 6 and 29: each model version a week that is not missing was served under, with the
    first such week.

    A missing week bound no forecast, so the version its receipt names, which may be one rule 6
    does not admit, opens no block. An unscored week was served under its version, so it can be
    a version's first week.
    """

    first: dict[str, int] = {}
    for week in weeks:
        if week.missing_reason is None and week.model_version:
            first.setdefault(week.model_version, week.gameweek)
    return dict(sorted(first.items()))


# Rules 20, 22 and 23: what each chain did besides its points


def _by_budget(profiles: Iterable[str]) -> list[str]:
    """Squads in the protocol's order, the largest budget first (rule 9)."""

    named = set(profiles)
    return [p for p in PROFILES if p in named] + sorted(named - set(PROFILES))


def _chain_order(chain: tuple[str, str]) -> tuple[int, str, int, str]:
    profile, arm = chain
    return (
        PROFILES.index(profile) if profile in PROFILES else len(PROFILES),
        profile,
        ARMS.index(arm) if arm in ARMS else len(ARMS),
        arm,
    )


def chain_statuses(
    evidence: Sequence[WeekEvidence],
) -> dict[int, dict[str, list[dict[str, Any]]]]:
    """Rules 22 and 23: for each week, every chain blocked by then, with the week it was blocked
    from, and every arm that failed that week, each with the reason its record states. Chains
    are listed by budget, then in the order of ARMS."""

    blocked_from: dict[tuple[str, str], int] = {}
    listed: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for week in evidence:
        blocked: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for chain in sorted(week.records, key=_chain_order):
            record = week.records[chain]
            if record.get("status") == "blocked":
                first = blocked_from.setdefault(chain, week.gameweek)
                blocked.append(
                    {
                        "profile": chain[0],
                        "arm": chain[1],
                        "blocked_from": first,
                        "reason": record.get("reason"),
                    }
                )
            elif record.get("status") == "failed":
                failed.append(
                    {"profile": chain[0], "arm": chain[1], "reason": record.get("reason")}
                )
        listed[week.gameweek] = {"blocked_chains": blocked, "failed_chains": failed}
    return listed


def proved_plans(evidence: Sequence[WeekEvidence]) -> dict[str, dict[str, Any]]:
    """Rule 20: for each arm, its decided plans that its own search proved OPTIMAL, over its
    decided plans, in every week of the reading. The runner records an observed comparison,
    published FEASIBLE, as not proved. A failed week is no plan the arm played, so it is counted
    beside the share and not in it."""

    tallies = {arm: {"decided": 0, "proved": 0, "failed": 0} for arm in ARMS}
    for week in evidence:
        for (_profile, arm), record in week.records.items():
            tally = tallies.get(arm)
            if tally is None:
                continue
            if record.get("status") == "decided":
                tally["decided"] += 1
                if _mapping(record.get("solver")).get("proved") is True:
                    tally["proved"] += 1
            elif record.get("status") == "failed":
                tally["failed"] += 1
    return {
        arm: {
            **tally,
            "proved_share": tally["proved"] / tally["decided"] if tally["decided"] else None,
        }
        for arm, tally in tallies.items()
    }


# Totals (rules 26 and 35): gross points, hits, free transfers, bank and sale value


@dataclass(frozen=True)
class EndPrices:
    """Rule 26: the prices and the fee the end state is valued at, and where they were read."""

    gameweek: int
    capture: str | None
    prices: Mapping[int, int] | None
    fee: float | None
    reason: str | None


def end_prices(weeks: Sequence[WeekScores], gameweek: int) -> EndPrices:
    """Rule 26: the end state is valued at the prices and the sell-on fee of the reading
    gameweek's own outcome capture (rule 25), the capture the reading closes on. No earlier
    week's capture stands in for it: when there is none, or it cannot be read, no sale value is
    stated and the reason is recorded."""

    outcome = next((week.outcome for week in weeks if week.gameweek == gameweek), None)
    if outcome is None:
        return EndPrices(gameweek, None, None, None, "reading_week_not_read")
    if outcome.snapshot is None:
        return EndPrices(gameweek, None, None, None, f"reading_week_unscored:{outcome.reason}")
    try:
        players = player_snapshot(outcome.snapshot.payloads[BOOTSTRAP_PAYLOAD])
        prices = {
            int(player): int(price)
            for player, price in zip(players["player_id"], players["price_tenths"], strict=True)
        }
        fee = float(read_season_rules(outcome.snapshot, season=SEASON).transfers.sell_on_fee)
    except (DataError, ValueError, KeyError, TypeError) as error:
        reason = f"prices_unreadable:{type(error).__name__}: {error}"
        return EndPrices(gameweek, outcome.snapshot_id, None, None, reason)
    return EndPrices(gameweek, outcome.snapshot_id, prices, fee, None)


def _end_states(evidence: Sequence[WeekEvidence]) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Each chain's state at the end of the reading: its last week's state after, or the state
    a blocked chain stays in (rule 23)."""

    states: dict[tuple[str, str], Mapping[str, Any]] = {}
    for week in evidence:
        for chain, record in week.records.items():
            state = record.get("state_after") or record.get("state_before")
            if isinstance(state, Mapping):
                states[chain] = state
    return states


def sale_value_tenths(
    state: Mapping[str, Any], prices: Mapping[int, int], fee: float
) -> int | None:
    """Rule 18's sale price for each held player at these prices and this fee, summed; None
    when a held player has no price (rule 23: no sale is invented)."""

    purchase = {
        int(k): int(v) for k, v in cast(Mapping[str, Any], state["purchase_prices"]).items()
    }
    total = 0
    for player in cast(Sequence[int], state["squad"]):
        current = prices.get(int(player))
        if current is None:
            return None
        total += sell_price_tenths(current, purchase[int(player)], sell_on_fee=fee)
    return total


def unpriced_chains(evidence: Sequence[WeekEvidence], end: EndPrices) -> list[str]:
    """The chains whose end state holds a player the pricing capture does not price."""

    if end.prices is None or end.fee is None:
        return []
    return sorted(
        f"{profile}:{arm}"
        for (profile, arm), state in _end_states(evidence).items()
        if sale_value_tenths(state, end.prices, end.fee) is None
    )


def arm_totals(
    weeks: Sequence[WeekScores],
    evidence: Sequence[WeekEvidence],
    prices: Mapping[int, int] | None,
    fee: float | None,
) -> dict[str, dict[str, Any]]:
    """Rules 26 and 35: each arm's realized points, and its chains' end state summed. The sale
    value is None without prices or a fee, or when one of the arm's chains holds a player with
    no price."""

    totals: dict[str, dict[str, Any]] = {}
    last_states = _end_states(evidence)
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
        sale: float | None = None if prices is None or fee is None else 0.0
        for (_profile, name), state in last_states.items():
            if name != arm:
                continue
            free += int(state.get("free_transfers", 0))
            bank += int(state.get("bank_tenths", 0))
            if sale is not None and prices is not None and fee is not None:
                value = sale_value_tenths(state, prices, fee)
                sale = None if value is None else sale + value
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
    for label, pairs in REPORTED_PAIRS.items():
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


# Rule 6: the producer changes that keep a version name, as the operator declares them


def declared_producer_changes(document: object) -> dict[str, Any]:
    """Rule 6: a declaration names its source and, for each change, an admitted model version
    and the first week it served; anything else refuses the reading before it starts."""

    if (
        not isinstance(document, Mapping)
        or set(document) != {"source", "changes"}
        or not isinstance(document["source"], str)
        or not document["source"].strip()
        or not isinstance(document["changes"], list)
    ):
        raise ScorerError(
            "A producer change declaration holds its source and a list of changes, and nothing "
            "else."
        )
    checked: list[dict[str, Any]] = []
    for change in document["changes"]:
        if not isinstance(change, Mapping) or set(change) != {"model_version", "first_week"}:
            raise ScorerError(
                "Each declared producer change names its model_version and first_week."
            )
        version, first = change["model_version"], change["first_week"]
        if version not in ADMITTED_MODEL_VERSIONS:
            raise ScorerError(
                f"A declared producer change names {version!r}, not a rule 6 version."
            )
        if isinstance(first, bool) or not isinstance(first, int) or not 1 <= first <= LAST_GAMEWEEK:
            raise ScorerError(f"A declared producer change names {first!r}, which is no gameweek.")
        entry = {"model_version": version, "first_week": first}
        if entry in checked:
            raise ScorerError(
                f"The producer change of {version} from GW{first:02d} is declared twice."
            )
        checked.append(entry)
    return {
        "source": document["source"],
        "changes": sorted(checked, key=lambda c: (int(c["first_week"]), str(c["model_version"]))),
    }


def read_producer_changes(value: str) -> dict[str, Any]:
    """Rule 6: the producer changes the operator declared on the chain's tracking issue,
    transcribed into one JSON file, or the word ``none`` when none was declared:

        {"source": "<comment URL>",
         "changes": [{"model_version": "<admitted version>", "first_week": <gameweek>}, ...]}

    A key given twice is refused, so that no declared change is lost to a later key. A byte
    order mark, which Windows PowerShell 5.1 writes with UTF-8, is read past.
    """

    if value == "none":
        return {"source": None, "changes": []}
    path = Path(value)
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except (OSError, ValueError) as error:
        raise ScorerError(
            f"The producer change declaration {path} cannot be read: {error}"
        ) from error
    return declared_producer_changes(document)


def producer_change_name(change: Mapping[str, Any]) -> str:
    """Rule 6: a declared change, named by its version and its first week."""

    return f"{change['model_version']} from GW{int(change['first_week']):02d}"


def producer_change_weeks(
    weeks: Sequence[WeekScores], changes: Sequence[Mapping[str, Any]], first_week: int
) -> dict[int, str]:
    """Rule 6: each week that follows a declared producer change of its own version, named by
    that change; a week belongs to the latest change of its version at or before it.

    A declared first week before the chain's first week, or one this reading decided under
    another version, contradicts the evidence and refuses the reading.
    """

    by_week = {week.gameweek: week for week in weeks}
    for change in changes:
        first, version = int(change["first_week"]), str(change["model_version"])
        if first < first_week:
            raise ScorerError(
                f"The producer change declared from GW{first:02d} precedes the chain's first "
                f"week, GW{first_week:02d}."
            )
        week = by_week.get(first)
        if week is not None and week.missing_reason is None and week.model_version != version:
            raise ScorerError(
                f"The producer change declared from GW{first:02d} names {version}, and that "
                f"week's receipt states {week.model_version}."
            )
    named: dict[int, str] = {}
    for week in weeks:
        own = [
            change
            for change in changes
            if change["model_version"] == week.model_version
            and int(change["first_week"]) <= week.gameweek
        ]
        if own:
            latest = max(own, key=lambda change: int(change["first_week"]))
            named[week.gameweek] = producer_change_name(latest)
    return named


# The reading


def reading_record(
    *,
    reading: str,
    protocol: Mapping[str, Any],
    evidence: Sequence[WeekEvidence],
    captures: Sequence[CapturedSnapshot],
    identity: Mapping[str, object],
    binding: Any,
    receipts: Mapping[str, Any],
    tags: Sequence[ReleaseTag] = (),
    producer_changes: Mapping[str, Any] = NO_PRODUCER_CHANGES,
    interim: InterimRecord | None = None,
) -> dict[str, Any]:
    """One reading's record. The final reading takes ``interim``, the interim record as develop
    holds it, and lists each interim week whose outcome capture changed (rule 25)."""

    final = reading == "gw38"
    if final and interim is None:
        raise ScorerError(
            "The final reading lists each week whose outcome capture changed since the interim "
            "(rule 25), so it reads the interim record first."
        )
    frozen = str(protocol.get("repository_commit", ""))
    statuses = chain_statuses(evidence)
    weeks: list[WeekScores] = []
    listed: list[dict[str, Any]] = []
    for week in evidence:
        deadline, deadline_source = week_deadline(captures, week)
        outcome = outcome_capture(captures, week.gameweek, deadline)
        scored = score_week(week, outcome)
        weeks.append(scored)
        release = binding(as_instant(deadline), frozen) if deadline else dict(RELEASE_UNKNOWN)
        listed.append(
            {
                "gameweek": week.gameweek,
                "decision_capture": week.receipt.get("snapshot_id"),
                "deadline_utc": deadline,
                "deadline_source": deadline_source,
                "missing_reason": scored.missing_reason,
                "outcome_capture": outcome.snapshot_id,
                "unscored_reason": None if scored.missing_reason else outcome.reason,
                "model_version": scored.model_version,
                "ready_bundle_present": week.receipt.get("ready_bundle_present"),
                "components_present": week.receipt.get("components_present"),
                "team_share_without_marker_or_components": scored.team_share_apart,
                "scored_chains": len(scored.scores),
                "truncated_arms": sorted({arm for _, arm in scored.truncated}),
                "served_routes": {
                    f"{profile}:{arm}": split
                    for (profile, arm), split in sorted(scored.served_splits.items())
                },
                "release": release,
                **statuses[week.gameweek],
            }
        )
    declared = [dict(change) for change in producer_changes["changes"]]
    after_change = producer_change_weeks(weeks, declared, _first_chain_week(protocol))
    for entry in listed:
        entry["producer_change"] = after_change.get(int(entry["gameweek"]))
    versions = _model_versions(weeks)
    weekly: dict[str, dict[int, Mapping[str, Any]]] = {}
    contrasts = {}
    for label, pairs in CONTRASTS.items():
        candidate = f"{PROTOCOL_ID}:{label}"
        rows = _series(weeks, pairs)
        weekly[label] = {int(row["gameweek"]): row for row in rows}
        primary = _block(rows, candidate, final=final)
        without = _block(_series(weeks, pairs, without_failed=True), candidate, final=False)
        # Rule 22: the series without failed weeks leaves out exactly the failed pairs the
        # primary keeps, a gameweek whose every pair failed included.
        without["failed_pairs"] = primary["failed_pairs"]
        contrasts[label] = {
            "primary": primary,
            "without_failed_weeks": without,
            "by_model_version": {
                version: {
                    "first_week": first_week,
                    **_block(
                        _series(weeks, pairs, keep=lambda w, v=version: w.model_version == v),
                        candidate,
                        final=False,
                    ),
                }
                for version, first_week in versions.items()
            },
            "team_share_without_marker_or_components": _block(
                _series(weeks, pairs, keep=lambda w: w.team_share_apart), candidate, final=False
            ),
            "after_producer_change": {
                name: _block(
                    _series(weeks, pairs, keep=lambda w, n=name: after_change.get(w.gameweek) == n),
                    candidate,
                    final=False,
                )
                for name in sorted({producer_change_name(change) for change in declared})
            },
        }
    # Rule 25: each week keeps the weekly difference each primary contrast pooled, beside its
    # outcome capture, so the final reading can list a week whose capture changed with both
    # scores. Rule 35 allows paired differences at the interim.
    for entry in listed:
        gameweek = int(entry["gameweek"])
        entry["differences"] = {
            label: _week_row(weekly[label].get(gameweek)) for label in CONTRASTS
        }
    by_route = _route_blocks(weeks)
    secondary = {
        name: _block(_series(weeks, pairs), f"{PROTOCOL_ID}:{name}", final=False)
        for name, pairs in SECONDARY_PAIRS.items()
    }
    # Rule 29: each squad, for each pairing it is reported for, on its own pairs.
    by_squad = {
        label: _squad_blocks(weeks, pairs, f"{PROTOCOL_ID}:{label}")
        for label, pairs in REPORTED_PAIRS.items()
    }
    truncated = {
        label: _block(
            _series(weeks, pairs, truncated_pairs=True), f"{PROTOCOL_ID}:{label}", final=False
        )
        for label, pairs in CONTRASTS.items()
    }
    end = end_prices(weeks, READINGS[reading])
    totals = arm_totals(weeks, evidence, end.prices, end.fee)
    frozen_source = {key: protocol.get(key) for key in FROZEN_SOURCE_FIELDS}
    manifests = {
        f"gw{week.gameweek:02d}": dict(receipts["manifests"][f"gw{week.gameweek:02d}"])
        for week in evidence
    }
    return {
        "protocol": PROTOCOL_ID,
        "season": SEASON,
        "reading": reading,
        "reading_gameweek": READINGS[reading],
        "final": final,
        "scored_on": RECORDED_ADVICE_SCORING_BASIS,
        "hit_points_charged": HIT_POINTS_CHARGED,
        "identity": dict(identity),
        "receipts": {
            "rule": RECEIPTS_RULE,
            "file_sha256": receipts["file_sha256"],
            "tracking_issue": receipts["tracking_issue"],
            "frozen_commit": dict(receipts["frozen_commit"]),
            "manifests": manifests,
        },
        "frozen_source": {**frozen_source, "checked": FROZEN_SOURCE_CHECK},
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
        "outcome_captures": {"rule": CAPTURE_SET_RULE, "read": len(captures)},
        "producer_changes": {
            "source": producer_changes["source"],
            "declared": declared,
            "statement": (
                "Each declared producer change is reported apart for each primary contrast."
                if declared
                else "No producer change that keeps a version name was declared, so no week is "
                "reported apart for one."
            ),
        },
        "weeks": listed,
        "proved_plans": proved_plans(evidence),
        "contrasts": contrasts,
        "contrast_a_by_served_route": by_route,
        "secondary": secondary,
        "by_squad": by_squad,
        "truncated_weeks": truncated,
        "changed_since_interim": (
            changed_since_interim(interim, listed, identity, frozen_source, manifests)
            if final and interim is not None
            else None
        ),
        "totals": {
            "end_state_prices": {
                "rule": END_PRICES_RULE,
                "gameweek": end.gameweek,
                "outcome_capture": end.capture,
                "sell_on_fee": end.fee,
                "reason": end.reason,
                "unpriced_chains": unpriced_chains(evidence, end),
            },
            "paired_differences": _paired_totals(totals),
            **({"by_arm": totals} if final else {}),
        },
        "outcome_read": True,
        "locked_holdout_accessed": False,
        "binding_source_test": "git diff --quiet <release tag> <frozen commit> -- <paths>",
        "release_rule": RELEASE_RULE,
        "release_tags": [tag.to_json() for tag in tags],
        "once_rule": ONCE_RULE,
        "choices": dict(CHOICES),
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


def _receipts_note(receipts: Mapping[str, Any]) -> str:
    frozen = receipts["frozen_commit"]
    return (
        f"The frozen commit and the {len(receipts['manifests'])} weekly manifests read here "
        f"match the receipts transcribed from {receipts['tracking_issue']} (the commit from "
        f"{frozen['posted']}) into a file whose sha256 is `{receipts['file_sha256']}`. The "
        "scorer did not read the issue itself."
    )


def _priced_note(end: Mapping[str, Any]) -> str:
    if end["reason"] is not None:
        return (
            f"No sale value is stated: GW{end['gameweek']}'s outcome capture gives no prices "
            f"({end['reason']})."
        )
    note = (
        f"Sale values are at the prices in `{end['outcome_capture']}`, GW{end['gameweek']}'s "
        f"outcome capture, with its sell-on fee of {end['sell_on_fee']}."
    )
    unpriced = end["unpriced_chains"]
    if unpriced:
        note += f" No sale is invented for {', '.join(unpriced)}: each holds an unpriced player."
    return note


def _difference(row: Mapping[str, Any] | None) -> str:
    return "none" if row is None else _shown(float(row["difference"]))


def _share(value: object) -> str:
    return "none" if value is None else f"{float(cast(float, value)):.3f}"


def _capture(side: Mapping[str, Any]) -> str:
    if side["outcome_capture"] is not None:
        return str(side["outcome_capture"])
    return f"none ({side['unscored_reason']})" if side["unscored_reason"] else "none"


def _chain_lines(record: Mapping[str, Any]) -> list[str]:
    """Rules 20, 22 and 23: the blocked chains, the failed arms and each arm's proved plans."""

    blocked: dict[tuple[str, str], tuple[int, str]] = {}
    failed: list[str] = []
    for week in record["weeks"]:
        for chain in week["blocked_chains"]:
            key = (str(chain["profile"]), str(chain["arm"]))
            blocked.setdefault(key, (int(chain["blocked_from"]), _shown(chain["reason"])))
        for chain in week["failed_chains"]:
            failed.append(
                _row(week["gameweek"], chain["profile"], chain["arm"], _shown(chain["reason"]))
            )
    lines = ["", "## Blocked chains and failed arms", ""]
    if not blocked and not failed:
        lines.append("No chain was blocked and no arm failed.")
    for (profile, arm), (first, reason) in blocked.items():
        lines.append(
            f"- `{profile}` `{arm}`: blocked from GW{first:02d} ({reason}); no decision and no "
            "pair from then on (rule 23)."
        )
    if failed:
        lines += ([""] if blocked else []) + [*_header("GW", "Squad", "Arm", "Failure"), *failed]
    lines += [
        "",
        "## Plans proved OPTIMAL",
        "",
        "Each arm's decided plans that its own search proved OPTIMAL, over its decided plans. An "
        "observed comparison is published FEASIBLE and is not counted as proved (rule 20). A "
        "failed week played the held team and no plan, so it is counted beside the share.",
        "",
        *_header("Arm", "Decided plans", "Proved", "Share", "Failed weeks"),
    ]
    for arm in ARMS:
        tally = record["proved_plans"][arm]
        lines.append(
            _row(
                arm,
                tally["decided"],
                tally["proved"],
                _share(tally["proved_share"]),
                tally["failed"],
            )
        )
    return lines


def _changed_lines(changed: Mapping[str, Any]) -> list[str]:
    """Rule 25: each interim week whose outcome capture changed, with both captures and both
    weekly differences of each primary contrast."""

    lines = [
        "## Weeks whose outcome capture changed since the interim",
        "",
        f"The interim record `{changed['record']}` was read from `{changed['read_from']}` at "
        f"`{changed['develop_commit']}`, as commit `{changed['added_commit']}` added it (sha256 "
        f"`{changed['sha256']}`). It was scored from `{changed['scorer_merge_commit']}`, as this "
        f"reading was, over {changed['interim_weeks']} weeks.",
        "",
    ]
    if not changed["changed_weeks"]:
        return [*lines, "No interim week's outcome capture changed.", ""]
    names = [f"{label} {side}" for label in CONTRASTS for side in ("interim", "final")]
    lines += _header("GW", "Interim capture", "Final capture", *names)
    for week in changed["changed_weeks"]:
        interim, final = week["interim"], week["final"]
        cells = [
            _difference((side["differences"] or {}).get(label))
            for label in CONTRASTS
            for side in (interim, final)
        ]
        lines.append(_row(week["gameweek"], _capture(interim), _capture(final), *cells))
    return [*lines, ""]


def render_markdown(record: Mapping[str, Any]) -> str:
    """The record's twin, rendered from the JSON and nothing else (rule 36).

    Every mapping is walked in the protocol's order (CONTRASTS, the secondary pairings, the
    reported pairings, squads by budget and ARMS) or in sorted order, never in the order its keys
    were stored, so the twin is the same whether it is rendered from the record in memory or from
    its JSON, whose keys are sorted.
    """

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
        _receipts_note(record["receipts"]),
        "",
        "## Weeks",
        "",
        *_header(
            "GW",
            "Decision capture",
            "Outcome capture",
            "Model version",
            "Scored chains",
            *CONTRASTS,
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
                *(_difference(week["differences"][label]) for label in CONTRASTS),
                release.get("release_tag") or "none",
                _shown(release.get("planner_source_same")),
                _shown(release.get("binding_source_same")),
                week["missing_reason"] or week["unscored_reason"] or "",
            )
        )
    lines += ["", record["release_rule"]]
    captures = record["outcome_captures"]
    lines += ["", f"{captures['rule']} This reading read {captures['read']} captures."]
    apart = [
        f"GW{week['gameweek']:02d}"
        for week in record["weeks"]
        if week["team_share_without_marker_or_components"]
    ]
    changes = record["producer_changes"]
    declared = ", ".join(producer_change_name(change) for change in changes["declared"])
    lines += [
        "",
        "Team share weeks bound without their ready bundle's marker or components file, "
        f"reported apart (rule 6): {', '.join(apart) or 'none'}.",
        "",
        "Producer changes that keep a version name (rule 6): "
        + (f"{declared}, declared at {changes['source']}." if declared else "none declared."),
    ]
    lines += _chain_lines(record)
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
            "Failed pairs",
            "Verdict",
        ),
    ]
    for label in CONTRASTS:
        primary = record["contrasts"][label]["primary"]
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
                primary["failed_pairs"],
                primary["verdict"] if final else "none (interim)",
            )
        )
    lines += ["", record["contrasts"]["A"]["primary"]["coverage_note"], ""]
    if record["changed_since_interim"] is not None:
        lines += _changed_lines(record["changed_since_interim"])
    lines += [
        "## Secondary, descriptive",
        "",
        *_header("Series", "Weeks", "Mean", "SD", "Interval"),
    ]
    for label in CONTRASTS:
        block = record["contrasts"][label]
        lines.append(_stats_row(f"{label} without failed weeks", block["without_failed_weeks"]))
        versions = block["by_model_version"]
        for version in sorted(versions):
            vblock = versions[version]
            lines.append(
                _stats_row(
                    f"{label} on `{version}` weeks, from GW{int(vblock['first_week']):02d}",
                    vblock,
                )
            )
        lines.append(
            _stats_row(
                f"{label} on team share weeks without marker or components",
                block["team_share_without_marker_or_components"],
            )
        )
        after = block["after_producer_change"]
        for name in sorted(after):
            lines.append(_stats_row(f"{label} after the producer change of `{name}`", after[name]))
    for name in SECONDARY_PAIRS:
        lines.append(_stats_row(name, record["secondary"][name]))
    for label in REPORTED_PAIRS:
        squads = record["by_squad"][label]
        for profile in _by_budget(squads):
            lines.append(_stats_row(f"{label}, squad {profile}", squads[profile]))
    routes = record["contrast_a_by_served_route"]
    for label in sorted(routes):
        lines.append(_stats_row(f"A where served is `{label}`", routes[label]))
    for label in CONTRASTS:
        lines.append(
            _stats_row(
                f"{label}, truncated weeks", record["truncated_weeks"][label], interval=False
            )
        )
    lines += [
        "",
        "## Points, hits, free transfers, bank and sale value",
        "",
        _priced_note(record["totals"]["end_state_prices"]),
        "",
        *_header(
            "Pair", "Gross", "Hits", "Net", "Free transfers", "Bank (tenths)", "Sale (tenths)"
        ),
    ]
    for label in REPORTED_PAIRS:
        diffs = record["totals"]["paired_differences"][label]
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
        for arm in ARMS:
            totals = record["totals"]["by_arm"][arm]
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
    lines += ["", "## Choices the protocol leaves to the scorer", ""]
    lines += [f"- `{name}`: {record['choices'][name]}" for name in sorted(record["choices"])]
    lines += [
        "",
        "## What this reading does not claim",
        "",
        "A difference between arms is a difference between these policies on constructed squads "
        "under the served football forecast; it is not a forecast of any member's result, nor "
        "evidence about windows under the current model, about truncated windows or about "
        "releases whose planner or binding source differs from the frozen commit (the Release "
        "columns above say which weeks those were). A football_team_share_v1 week bound without "
        "its ready bundle's marker or components file cannot be told apart from a week served "
        "without them; such weeks are reported apart, and this reading claims nothing about what "
        "their members were served. No verdict switches anything (rule 34).",
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
    receipts: Path,
    records_dir: Path = RECORDS_DIR,
    index_file: Path = INDEX_FILE,
    producer_changes: Mapping[str, Any] = NO_PRODUCER_CHANGES,
) -> dict[str, Any]:
    """Rules 24, 28 and 37: take one reading, once, from the scorer's own merge commit, on
    evidence held to the receipts posted for it and on a frozen source git still holds.

    These come before the first capture is read: the reading's name, its record, its twin and
    its row in the measurements index in the checkout, the scorer's identity after a fetch of
    origin, its record in committed history or in another worktree, the release tags, the
    receipts file and, for the final reading, the interim record on develop (rule 25). The
    evidence, the frozen source, each record's truncation (rule 14) and the producer changes
    declared (rule 6) are checked once the gameweek has settled. Everything the reading writes
    is rendered before the first write: the record's bytes, the twin rendered from those bytes
    (rule 36) and the index row. The record is then written once, the twin once, and the index
    row is appended last, so a failure before the writes leaves nothing behind. A failure
    between them leaves a reading a retry refuses as taken, naming what exists. Returns the
    record as written. ``producer_changes`` is the declaration as ``read_producer_changes``
    returns it. ``records_dir`` and ``index_file`` are for tests; the command line writes only
    where rule 36 names.
    """

    if reading not in READINGS:
        raise ScorerError(f"The protocol names no reading {reading!r}; it names gw20 and gw38.")
    name = f"planner_policy_chain_{reading}"
    target = records_dir / f"{name}.json"
    twin = target.with_suffix(".md")
    try:
        index_text = index_file.read_text(encoding="utf-8") if index_file.exists() else ""
    except (OSError, ValueError) as error:
        raise ScorerError(f"{index_file} cannot be read: {error}") from error
    taken = [f"{path} exists" for path in (target, twin) if path.exists()]
    if f"research/{name}.json" in index_text:
        taken.append(f"{index_file} links its record")
    if taken:
        raise ScorerError(f"The {reading} reading was taken already: {'; '.join(taken)}.")
    identity = source_identity()
    committed = committed_reading(reading)
    if committed is not None:
        raise ScorerError(
            f"The {reading} reading was taken already: its record is in committed history at "
            f"{committed}."
        )
    elsewhere = written_reading(reading)
    if elsewhere is not None:
        raise ScorerError(f"The {reading} reading was taken already: {elsewhere} exists.")
    tags = release_tags()
    posted = read_receipts(receipts)
    interim = interim_reading() if reading == "gw38" else None
    captures = _captures(snapshot_root)
    gameweek = READINGS[reading]
    if not settled(captures, gameweek):
        raise ScorerError(
            f"GW{gameweek} has not settled in any capture; the {reading} reading waits."
        )
    protocol, weeks = read_evidence(evidence, gameweek, posted)
    check_frozen_source(protocol)
    record = reading_record(
        reading=reading,
        protocol=protocol,
        evidence=weeks,
        captures=captures,
        identity=identity,
        binding=lambda deadline, frozen: release_binding(deadline, frozen, tags),
        receipts=posted,
        tags=tags,
        producer_changes=producer_changes,
        interim=interim,
    )
    # write_document_once writes document_bytes(record), so the twin and the row are rendered
    # from the bytes the record is written as, whatever order its keys were built in.
    payload = document_bytes(record)
    written = cast(dict[str, Any], json.loads(payload))
    twin_bytes = render_markdown(written).encode("utf-8")
    row = index_row(written)
    records_dir.mkdir(parents=True, exist_ok=True)
    write_document_once(record, target)
    write_bytes_once(twin_bytes, twin)
    with index_file.open("a", encoding="utf-8") as handle:
        handle.write(("" if index_text.endswith("\n") or not index_text else "\n") + row + "\n")
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    # Rule 24: the frozen commit and each week's manifest sha256 as posted on the tracking issue.
    parser.add_argument("--receipts", type=Path, required=True)
    # Rule 6: the producer changes that keep a version name, as the operator declared them on
    # the tracking issue, in a JSON file; the word none states that none was declared.
    parser.add_argument("--producer-changes", required=True)
    parser.add_argument("--reading", choices=sorted(READINGS), required=True)
    arguments = parser.parse_args(argv)
    try:
        # Rules 36 and 37: the command line writes only where the protocol names, so a reading
        # cannot be taken again into another place.
        record = score(
            arguments.evidence,
            arguments.snapshot_root,
            arguments.reading,
            receipts=arguments.receipts,
            producer_changes=read_producer_changes(arguments.producer_changes),
        )
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
                    label: record["contrasts"][label]["primary"]["verdict"] for label in CONTRASTS
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
