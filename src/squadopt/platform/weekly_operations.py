"""Installed weekly entry point: typed application services and a durable stage journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.application.advice_record import load_member_advice_record, record_directory
from squadopt.application.commands import DecideRequest, decide
from squadopt.application.evidence_io import write_json
from squadopt.application.league_publication import LeaguePublicationRequest, publish_league
from squadopt.application.player_evidence import PlayerEvidenceRequest, export_player_evidence
from squadopt.application.projection_handoff import build as build_handoff
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.application.scoreboard import ScoreboardPublicationRequest, publish_scoreboard
from squadopt.application.settled_outcomes import (
    SettledOutcomeExportError,
    SettledOutcomesRequest,
    export_settled_outcomes,
)
from squadopt.application.site_publication import SitePublicationRequest, publish_site
from squadopt.application.weekly_plan import (
    CHIP_CHOICES,
    MODE_RULE,
    WeekError,
    WeeklyRequest,
    capture_deadline,
    decision_mode_for,
    evidence_artifact,
    latest_live_snapshot,
    new_snapshot,
    prepare_week,
    rotation_artifact,
    rotation_pair_is_readable,
    rotation_source_capture,
)
from squadopt.contracts.run_logs import LOG_ROOT_NAME
from squadopt.data.errors import DataError, SourceRevisionError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.source_revision import source_revision
from squadopt.features.evidence_artifact import read_player_evidence_artifact
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.live import handoff_path_for, load_entry, read_projection_handoff, read_season_rules
from squadopt.platform import cohort_capture, elite_capture
from squadopt.platform._queue_lock import QueueFileLock
from squadopt.platform.fpl_capture import capture
from squadopt.platform.projection_retention import publish_retained_handoff, retained_handoff_path
from squadopt.platform.publication_workers import league_mapper
from squadopt.platform.runlog import RunLog, configure_run_logging
from squadopt.platform.weekly_journal import (
    WeeklyJournalError,
    WeeklyRun,
    WeeklyStageResult,
    inspect_run,
    read_run_request,
)
from squadopt.platform.weekly_publish import (
    WEEKLY_RUNS,
    PublishError,
    PublishNames,
    check_publication_base,
    copy_preview_builder,
    publish,
)


@dataclass(frozen=True, slots=True)
class WeeklyPaths:
    workspace: Path
    snapshots: Path
    archive: Path
    registry: Path
    handoffs: Path
    ledger: Path
    evidence: Path
    rotation: Path
    out: Path
    journal: Path
    log_root: Path
    """Root above every component's log directory, never qualified with a component."""
    records: Path
    club_news_fixture: Path

    @classmethod
    def under(cls, workspace: Path, *, out: Path | None = None) -> WeeklyPaths:
        root = workspace.resolve()
        return cls(
            root,
            root / "data/snapshots",
            root / "data/raw/vaastav-fpl",
            root / "data/entries/registry.json",
            root / "data/handoffs",
            root / "data/ledger",
            root / "artifacts/phase_b",
            root / "artifacts/rotation",
            out or root / WEEKLY_RUNS / "preview",
            root / WEEKLY_RUNS,
            root / LOG_ROOT_NAME,
            root / "data/advice_records",
            root / "data/sample/club_news_v1.fixture.json",
        )


def package_fingerprint() -> str:
    """Bind the actual installed Python bytes, independently of a declared Git revision."""

    package = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def recorded_capture_directories(root: Path, season: str) -> list[Path]:
    """The advice records the season's history documents read, as the run found them.

    One directory per member, week and capture. A hidden sibling is a writer's staging
    directory, never a record, and the week this run records itself is its own output.
    """

    return sorted(
        path
        for path in (root / season).glob("gw[0-9][0-9]/entry-*/*")
        if path.is_dir() and not path.name.startswith(".")
    )


_ENTRY_DIRECTORY = re.compile(r"entry-([1-9][0-9]*)")


def recorded_commits(root: Path, season: str, gameweek: int, snapshot_id: str) -> dict[int, object]:
    """The commit each member's record of one capture names, by entry id.

    Only members with a record of this capture appear. Each record is read the way every
    reader of the store reads one, through its manifest, so a record that fails its own
    digests is refused here rather than at the end of the league stage. A record that names
    no commit maps to ``None``: there is nothing to compare, and the league stage's own
    comparison of the whole record still applies to it.
    """

    week = root / season / f"gw{gameweek:02d}"
    if not week.is_dir():
        return {}
    found: dict[int, object] = {}
    for member in sorted(week.iterdir()):
        matched = _ENTRY_DIRECTORY.fullmatch(member.name)
        if matched is None or not member.is_dir():
            continue
        entry_id = int(matched.group(1))
        if not record_directory(root, season, gameweek, entry_id, snapshot_id).is_dir():
            continue
        record = load_member_advice_record(root, season, gameweek, entry_id, snapshot_id)
        provenance = record.get("provenance")
        found[entry_id] = (
            provenance.get("repository_commit") if isinstance(provenance, Mapping) else None
        )
    return found


class WeeklyOperations:
    log: RunLog
    """Set by :meth:`execute`; the stages record through it."""

    def __init__(
        self,
        request: WeeklyRequest,
        paths: WeeklyPaths,
        *,
        run_id: str,
        repository_commit: str,
        resume: bool = False,
        handoff: Path | None = None,
        record_advice: bool = False,
        publish_suffix: str = "",
        no_advice_record: bool = False,
    ) -> None:
        if paths.out == paths.journal / "preview":
            paths = replace(paths, out=paths.journal / run_id / "preview")
        self.request, self.paths, self.run_id = request, paths, run_id
        self.repository_commit, self.resume = repository_commit, resume
        self.supplied_handoff = handoff
        self.record_advice = record_advice
        self.no_advice_record = no_advice_record
        self.publish_names = PublishNames(
            request.season, request.gameweek, "decision", publish_suffix
        )
        self.values: dict[str, dict[str, Any]] = {}
        self.plan = request.plan()
        if handoff is not None and not request.skip_top100:
            raise WeekError(
                "A prebuilt --handoff requires --skip-top100; it does not apply new evidence."
            )
        self.stages = ["preflight"]
        if "top100" in self.plan.steps:
            self.stages.extend(("top100_cohort", "top100_picks", "top100_evidence"))
        self.stages.extend(("capture", "settled_outcomes"))
        if request.rotation:
            self.stages.append("rotation")
        self.stages.append("handoff")
        if request.decide:
            self.stages.append("decide")
        self.stages.extend(("league", "site", "scoreboard"))
        if request.publish:
            self.stages.append("publish")
        self.rule_snapshot = request.snapshot_id or latest_live_snapshot(paths.snapshots)
        self.ledger_inputs = sorted((paths.ledger / request.season).glob("gw*"))
        self.record_inputs = recorded_capture_directories(paths.records, request.season)
        if resume:
            prior = read_run_request(paths.journal, run_id)
            # Derived reads belong to the original preflight, even after this run captures
            # a newer snapshot or writes its own decision during an earlier invocation.
            self.rule_snapshot = prior["rule_snapshot"]
            self.ledger_inputs = [Path(value) for value in prior["ledger_inputs"]]
            self.record_inputs = [Path(value) for value in prior["record_inputs"]]
        declaration = {
            "request": asdict(request),
            "paths": {key: str(value) for key, value in asdict(paths).items()},
            "repository_commit": repository_commit,
            "package_sha256": package_fingerprint(),
            "supplied_handoff": str(handoff) if handoff else None,
            "rule_snapshot": self.rule_snapshot,
            "ledger_inputs": list(map(str, self.ledger_inputs)),
            "record_inputs": list(map(str, self.record_inputs)),
        }
        if record_advice or publish_suffix or no_advice_record:
            declaration["publication_options"] = {
                "record_advice": record_advice,
                "publish_suffix": publish_suffix,
                "no_advice_record": no_advice_record,
            }
        self.run = WeeklyRun(paths.journal, run_id, declaration, self.stages, resume=resume)

    @property
    def records_advice(self) -> bool:
        """Whether the league stage writes the advice record: publication or explicit
        recording asks for it, and ``--no-advice-record`` turns it off for a publication,
        as the league build's switch of the same name does."""

        return (self.request.publish or self.record_advice) and not self.no_advice_record

    def _receipt(
        self, name: str, value: dict[str, Any], outputs: tuple[Path, ...] = ()
    ) -> WeeklyStageResult:
        path = self.run.directory / f"{name}-{secrets.token_hex(4)}.result.json"
        write_json(path, value)
        return WeeklyStageResult((*outputs, path), value)

    def _snapshot_path(self, identifier: str) -> Path:
        return self.paths.snapshots / identifier

    def _capture_id(self) -> str:
        return str(self.values["capture"]["snapshot_id"])

    def _cohort_id(self) -> str | None:
        return self.values.get("top100_cohort", {}).get("snapshot_id", self.request.cohort_snapshot)

    def _elite_id(self) -> str | None:
        return self.values.get("top100_picks", {}).get("snapshot_id", self.request.elite_snapshot)

    def _preflight(self) -> WeeklyStageResult:
        rules = (
            read_season_rules(
                read_snapshot(self.paths.snapshots, self.rule_snapshot), season=self.request.season
            )
            if self.rule_snapshot
            else None
        )
        prepared = prepare_week(
            self.request,
            registry_path=self.paths.registry,
            snapshot_root=self.paths.snapshots,
            ledger_root=self.paths.ledger,
            evidence_root=self.paths.evidence,
            rotation_root=self.paths.rotation,
            rules=rules,
        )
        self._refuse_a_record_from_another_commit()
        if self.request.publish:
            # The publish stage checks this too, but only after every capture and solve
            # has been spent; asked here first so a run off the fresh origin/develop
            # refuses before it spends anything.
            try:
                check_publication_base(self.paths.workspace, self.repository_commit)
                publish(
                    self.publish_names,
                    force_branch=False,
                    dry_run=True,
                    workspace=self.paths.workspace,
                    expected_commit=self.repository_commit,
                )
            except PublishError as error:
                raise WeekError(str(error)) from error
        return self._receipt(
            "preflight",
            {
                "decide": prepared.decide,
                "decide_skip_reason": prepared.decide_skip_reason,
                "mode_rule": MODE_RULE,
            },
        )

    def _refuse_a_record_from_another_commit(self) -> None:
        """Stop a reused capture that already holds advice records from another commit.

        A record is immutable and carries the commit that wrote it, so the league stage
        refuses to record the same capture again from any other commit, and it finds out only
        at its end, after every member has been solved (``advice_record._reconciled``). A
        capture this run takes itself has no records yet, and a run that records nothing
        cannot conflict, so only a reused capture this run would record is read. A record
        that names no commit is not refused here: the record writer matches an unknown commit
        against a known one rather than refusing it.
        """

        capture = self.request.snapshot_id
        if capture is None or not self.records_advice:
            return
        recorded = recorded_commits(
            self.paths.records, self.request.season, self.request.gameweek, capture
        )
        by_commit: dict[str, list[int]] = {}
        for entry_id, commit in sorted(recorded.items()):
            if commit is not None and commit != self.repository_commit:
                by_commit.setdefault(str(commit), []).append(entry_id)
        if not by_commit:
            return
        named = "; ".join(
            f"{commit} ({'entry' if len(entries) == 1 else 'entries'} "
            f"{', '.join(str(entry) for entry in entries)})"
            for commit, entries in sorted(by_commit.items())
        )
        raise WeekError(
            f"Capture {capture} already has advice records for {self.request.season} gameweek "
            f"{self.request.gameweek} written by commit {named}, and this run's source "
            f"revision is {self.repository_commit}. A record is immutable, so the league stage "
            "would refuse to record this capture again from another commit, and only at its "
            "end, after every member is solved. Stopped before any capture or solve. "
            "Recovery: drop --snapshot-id so the run takes a fresh capture before the "
            "deadline, which is recorded under its own directory; or publish without "
            "recording (--publish --no-advice-record), which keeps the existing records."
        )

    def _cohort(self) -> WeeklyStageResult:
        identifier = self.request.cohort_snapshot
        if identifier is None:
            before = list_snapshot_ids(self.paths.snapshots)
            result = cohort_capture.main(
                [
                    "--target-gameweek",
                    str(self.request.gameweek),
                    "--cohort-size",
                    "100",
                    "--snapshot-root",
                    str(self.paths.snapshots),
                ]
            )
            if result != 0:
                raise WeekError(f"Top-100 cohort capture exited {result}.")
            identifier = new_snapshot(
                before, list_snapshot_ids(self.paths.snapshots), "fpl-top100-"
            )
        week, deadline, _ = capture_deadline(self.paths.snapshots, identifier)
        if week != self.request.gameweek:
            raise WeekError("The cohort capture is open for another gameweek.")
        return self._receipt(
            "cohort",
            {"snapshot_id": identifier, "deadline_utc": deadline},
            (self._snapshot_path(identifier),),
        )

    def _elite(self) -> WeeklyStageResult:
        cohort = self.values["top100_cohort"]
        identifier = self.request.elite_snapshot
        if identifier is None:
            before = list_snapshot_ids(self.paths.snapshots)
            result = elite_capture.main(
                [
                    "--cohort-snapshot",
                    str(cohort["snapshot_id"]),
                    "--target-gameweek",
                    str(self.request.gameweek),
                    "--deadline-utc",
                    str(cohort["deadline_utc"]),
                    "--snapshot-root",
                    str(self.paths.snapshots),
                ]
            )
            if result != 0:
                raise WeekError(f"Elite-picks capture exited {result}.")
            identifier = new_snapshot(
                before, list_snapshot_ids(self.paths.snapshots), "fpl-elite-picks-"
            )
        read_snapshot(self.paths.snapshots, identifier)
        return self._receipt(
            "elite", {"snapshot_id": identifier}, (self._snapshot_path(identifier),)
        )

    def _evidence(self) -> WeeklyStageResult:
        elite, cohort = str(self._elite_id()), str(self._cohort_id())
        table, manifest = evidence_artifact(
            self.paths.evidence, self.request.season, self.request.gameweek, elite
        )
        if not (table.is_file() and manifest.is_file()):
            export_player_evidence(
                PlayerEvidenceRequest(
                    self.request.season,
                    self.request.gameweek,
                    str(self.values["top100_cohort"]["deadline_utc"]),
                    self.paths.snapshots,
                    cohort,
                    (elite,),
                    self.paths.evidence,
                    table.stem,
                    self.repository_commit,
                )
            )
        read_player_evidence_artifact(table, manifest)
        return self._receipt(
            "evidence", {"table": str(table), "manifest": str(manifest)}, (table, manifest)
        )

    def _capture(self) -> WeeklyStageResult:
        identifier = self.request.snapshot_id
        if identifier is None:
            captured = capture(
                self.paths.snapshots,
                archive_root=self.paths.archive,
                entry_registry=self.paths.registry,
                league_id=self.request.league_id,
            )
            if captured is None:
                raise WeekError("The capture wrote nothing.")
            identifier = captured.snapshot_id
        week, deadline, captured_at = capture_deadline(self.paths.snapshots, identifier)
        if week != self.request.gameweek:
            raise WeekError(f"Capture is open for gameweek {week}, not {self.request.gameweek}.")
        lead = (
            datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            - datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        ).total_seconds() / 3600
        return self._receipt(
            "capture",
            {
                "snapshot_id": identifier,
                "deadline_utc": deadline,
                "captured_at_utc": captured_at,
                "lead_hours": lead,
                "in_target_lead_window": 2 <= lead <= 3,
            },
            (self._snapshot_path(identifier),),
        )

    def _settled(self) -> WeeklyStageResult:
        result = export_settled_outcomes(
            SettledOutcomesRequest(
                self.request.season,
                self.paths.snapshots,
                self.paths.rotation,
                self.run.directory / "settled-outcomes.json",
                self.run.directory / "settled-outcomes.md",
                self.repository_commit,
                self._capture_id(),
                self.request.gameweek,
            )
        )
        return self._receipt(
            "settled",
            {
                "gameweeks_exported": list(result.gameweeks_exported),
                "skipped": list(result.skipped),
            },
            result.output_paths,
        )

    def _rotation_source(self) -> Path:
        """What the rotation stage reads from, as a path the journal can fingerprint.

        A capture is a directory in the snapshot store and the fixture is a file; both are
        paths, which is what the stage's input list needs. Naming the source rather than
        always naming the fixture is what makes a resumed run notice that the week was read
        from somewhere else.
        """

        if self.request.rotation_capture is None:
            return self.paths.club_news_fixture
        return self.paths.snapshots / self.request.rotation_capture

    def _rotation(self) -> WeeklyStageResult:
        identifier = self._capture_id()
        news = self.request.rotation_capture
        # The export names its artifact after whichever capture the *claims* came from, so a
        # week read from a club-news capture is a different file from the same week read from
        # the fixture. This has to agree with `rotation_export._artifact_name` or the reuse
        # check silently stops finding anything.
        distinguishing = rotation_source_capture(identifier, news)
        table, manifest = rotation_artifact(
            self.paths.rotation, self.request.season, self.request.gameweek, distinguishing
        )
        # Readability, not existence. A pair this reader cannot open is a pair this stage does
        # not have, and exporting over it is the recovery. The alternative is the branch that
        # skips the export and then raises at the read below, on a run that cannot be retried
        # inside its own window.
        if not rotation_pair_is_readable(table, manifest):
            export_rotation_evidence(
                # Keyword arguments, deliberately. Positionally the eighth field is never
                # reached, which is why this stage could not name a capture at all: the field
                # and its refusal have existed since the capture path landed.
                RotationExportRequest(
                    season=self.request.season,
                    target_gameweek=self.request.gameweek,
                    deadline_utc=str(self.values["capture"]["deadline_utc"]),
                    snapshot=identifier,
                    snapshot_root=self.paths.snapshots,
                    club_news_fixture=None if news else self.paths.club_news_fixture,
                    output_dir=self.paths.rotation,
                    club_news_snapshot=news,
                    table_name=table.stem,
                ),
                repository_commit=self.repository_commit,
            )
        read_rotation_evidence_artifact(table, manifest)
        return self._receipt(
            "rotation", {"table": str(table), "manifest": str(manifest)}, (table, manifest)
        )

    def _handoff(self) -> WeeklyStageResult:
        target = handoff_path_for(self.paths.handoffs, self.request.season, self.request.gameweek)
        if self.supplied_handoff is not None:
            projection = read_projection_handoff(self.supplied_handoff)
            if (projection.source_snapshot_id, projection.season, projection.gameweek) != (
                self._capture_id(),
                self.request.season,
                self.request.gameweek,
            ):
                raise WeekError("Projection handoff does not match this run's exact capture/week.")
            if self.supplied_handoff.resolve() != target.resolve():
                publish_retained_handoff(target, projection)
        else:
            evidence = (
                self.values.get("top100_evidence", {})
                if self.request.projection == "component"
                else {}
            )
            projection, _, _ = build_handoff(
                self.paths.snapshots,
                self.paths.archive,
                self.paths.handoffs,
                snapshot_id=self._capture_id(),
                gameweek=self.request.gameweek,
                evidence_table_path=Path(evidence["table"]) if evidence else None,
                evidence_manifest_path=Path(evidence["manifest"]) if evidence else None,
                writer=publish_retained_handoff,
            )
        if (projection.source_snapshot_id, projection.season, projection.gameweek) != (
            self._capture_id(),
            self.request.season,
            self.request.gameweek,
        ):
            raise WeekError("Projection handoff does not match this run's exact capture/week.")
        reread = read_projection_handoff(target)
        if reread.fingerprint != projection.fingerprint:
            raise WeekError("Published handoff differs from the selected projection.")
        outputs = [target]
        retained = retained_handoff_path(
            target.parent, self._capture_id(), hashlib.sha256(target.read_bytes()).hexdigest()
        )
        if retained.is_file():
            outputs.append(retained)
        return self._receipt(
            "handoff",
            {
                "path": str(target),
                "fingerprint": projection.fingerprint,
                "source": "prebuilt" if self.supplied_handoff else "built",
                "new_evidence_applied": self.supplied_handoff is None
                and bool(self.values.get("top100_evidence"))
                and self.request.projection == "component",
            },
            tuple(outputs),
        )

    def _decide(self) -> WeeklyStageResult:
        existing = self.paths.ledger / self.request.season / f"gw{self.request.gameweek:02d}"
        if existing.is_dir():
            entry = load_entry(self.paths.ledger, self.request.season, self.request.gameweek)
            return self._receipt(
                "decide",
                {
                    "skipped_reason": "The ledger already holds this gameweek.",
                    "recorded_snapshot_id": entry.decision["snapshot_id"],
                },
                (existing,),
            )
        mode = decision_mode_for(
            reused_capture=self.request.snapshot_id is not None,
            deadline_utc=str(self.values["capture"]["deadline_utc"]),
            now_utc=datetime.now(UTC).isoformat(),
        )
        result = decide(
            DecideRequest(
                self.paths.snapshots,
                self.paths.ledger,
                self.paths.archive,
                snapshot_id=self._capture_id(),
                gameweek=self.request.gameweek,
                season=self.request.season,
                in_season_projection=Path(self.values["handoff"]["path"]),
                chip=self.request.chip,
                mode=mode,
            )
        )
        return self._receipt(
            "decide", {"snapshot_id": result.snapshot_id, "mode": result.mode}, result.output_paths
        )

    def _league(self) -> WeeklyStageResult:
        # Publication or explicit recording writes the record before history reads it,
        # unless --no-advice-record turned it off. The publish stage copies this preview
        # rather than solving again.
        record = self.records_advice
        request = LeaguePublicationRequest(
            self.paths.snapshots,
            self._capture_id(),
            self.paths.archive,
            self.paths.registry,
            self.paths.out,
            self.request.league_id,
            season=self.request.season,
            gameweek=self.request.gameweek,
            handoff_path=Path(self.values["handoff"]["path"]),
            record_root=self.paths.records if record else None,
            history_record_root=self.paths.records,
            # The manager's word rides on the rotation stage: when it ran, its table and
            # the source the claims came from reach every member's menu as a switchable,
            # priced constraint; when it did not, the index says there is none.
            rotation_evidence=(
                Path(str(self.values["rotation"]["table"])) if "rotation" in self.values else None
            ),
            club_news_source=self._rotation_source() if "rotation" in self.values else None,
            # The Top 100 menu rides on the evidence stage. The loader's own gate refuses a
            # handoff that already carries the uplift (``--projection component``), and the
            # index then says so; the published plans do not depend on the menu.
            top100_evidence=(
                Path(str(self.values["top100_evidence"]["table"]))
                if "top100_evidence" in self.values
                else None
            ),
        )
        with league_mapper(request, self.request.workers) as mapper:
            result = publish_league(request, mapper=mapper)
        return WeeklyStageResult(
            result.output_paths,
            {
                "snapshot_id": result.snapshot_id,
                "gameweek": result.gameweek,
                "advice_recorded": record,
                # What the build told the operator about individual members (a name it
                # changed, a mode or the manager's word it could not solve) and the files
                # it removed from the tree, so a run is not "completed" in silence.
                "member_notes": {
                    str(member.entry_id): member.reason
                    for member in result.report.members
                    if member.reason
                },
                "removed": list(result.report.removed),
                # Empty when the Top 100 menu was offered or never asked for.
                "top100_note": result.top100_note,
            },
        )

    def _site(self) -> WeeklyStageResult:
        result = publish_site(
            SitePublicationRequest(
                self.paths.snapshots,
                self.paths.ledger,
                self.paths.archive,
                self.paths.handoffs,
                self.run.directory,
                self.paths.log_root,
                self.paths.out,
                season=self.request.season,
                snapshot_id=self._capture_id(),
            )
        )
        return WeeklyStageResult(
            result.output_paths,
            {
                "snapshot_id": result.snapshot_id,
                "ledger_kept_from_published": result.report.ledger_kept_from_published,
            },
        )

    def _scoreboard(self) -> WeeklyStageResult:
        result = publish_scoreboard(
            ScoreboardPublicationRequest(
                self.paths.snapshots,
                self._capture_id(),
                self.paths.registry,
                self.paths.ledger,
                self.paths.out,
                self.request.league_id,
                season=self.request.season,
                cohort_snapshot_id=self._cohort_id(),
                elite_snapshot_id=self._elite_id(),
                evidence_root=self.paths.evidence,
            )
        )
        return WeeklyStageResult(
            result.output_paths,
            {
                "snapshot_id": result.snapshot_id,
                "ours_kept_from_published": list(result.ours_kept_from_published),
            },
        )

    def _published_tree(self) -> Path:
        return self.paths.workspace / "web" / "public" / "data"

    def _seed_preview(self) -> None:
        """Start the preview from the tree develop publishes, as the worktree build did.

        The builders overlay that tree and prune it, and two of them read it: the site
        keeps the published ``ledger.json`` and the scoreboard keeps its published rows when
        the ledger holds nothing. An empty preview answers those differently from a
        publication, so the preview starts where the publication starts.
        """

        target = self.paths.out / "data"
        source = self._published_tree()
        if target.exists() or not source.is_dir():
            return
        shutil.copytree(source, target)

    def _publish(self) -> WeeklyStageResult:
        proof: dict[str, object] = {}
        preview = self.paths.out / "data"
        copied: dict[str, object] = {}
        exit_code = publish(
            self.publish_names,
            force_branch=False,
            dry_run=False,
            workspace=self.paths.workspace,
            builder=copy_preview_builder(preview, copied),
            expected_commit=self.repository_commit,
            on_published=lambda value: proof.update(value),
        )
        if exit_code != 0 or not proof:
            raise WeekError("Publication did not return a verified PR/no-change receipt.")
        return self._receipt("publish", {**proof, **copied, "preview": str(preview)})

    def _stage(
        self,
        name: str,
        *,
        inputs: Sequence[Path],
        operation: Callable[[], WeeklyStageResult],
        repeatable: bool = True,
    ) -> WeeklyStageResult:
        """Run one journalled stage and record its boundary in the run log."""

        self.log.event("tick.week.stage.start", stage=name)
        try:
            result = self.run.stage(name, inputs=inputs, operation=operation, repeatable=repeatable)
        except Exception as error:
            self.log.failure("tick.week.stage.failed", stage=name, error=str(error))
            raise
        self.log.event("tick.week.stage.done", stage=name)
        return result

    def execute(self) -> Path:
        p = self.paths
        # A weekly run is the season tick driven by hand, so it records into the tick's own
        # component: the status page reads one run log, not one per entry point.
        self.log = configure_run_logging(
            "season_tick", log_root=p.log_root, run_id=self.run_id, console=False
        )
        self.log.event(
            "tick.week.plan",
            season=self.request.season,
            gameweek=self.request.gameweek,
            league=self.request.league_id,
            stages=list(self.stages),
            resume=self.resume,
        )
        if self.no_advice_record:
            # A publication with no record of what it told the members is stated where the
            # status page reads, not only in the journal's league receipt.
            self.log.event(
                "tick.week.advice_record.skipped",
                reason="--no-advice-record",
                capture=self.request.snapshot_id,
            )
        with (
            QueueFileLock(p.journal / ".workspace.lock", timeout_seconds=0).hold(),
            self.run.hold(),
        ):
            initial_inputs = [p.registry, *self.ledger_inputs]
            if self.rule_snapshot:
                initial_inputs.append(self._snapshot_path(self.rule_snapshot))
            self.values["preflight"] = dict(
                self._stage("preflight", inputs=initial_inputs, operation=self._preflight).value
            )
            if "top100" in self.plan.steps:
                self.values["top100_cohort"] = dict(
                    self._stage("top100_cohort", inputs=[], operation=self._cohort).value
                )
                self.values["top100_picks"] = dict(
                    self._stage(
                        "top100_picks",
                        inputs=[self._snapshot_path(str(self._cohort_id()))],
                        operation=self._elite,
                    ).value
                )
                self.values["top100_evidence"] = dict(
                    self._stage(
                        "top100_evidence",
                        inputs=[
                            self._snapshot_path(str(self._cohort_id())),
                            self._snapshot_path(str(self._elite_id())),
                        ],
                        operation=self._evidence,
                    ).value
                )
            capture_inputs = [p.registry]
            if self.request.snapshot_id:
                capture_inputs.append(self._snapshot_path(self.request.snapshot_id))
            self.values["capture"] = dict(
                self._stage("capture", inputs=capture_inputs, operation=self._capture).value
            )
            selected = self._snapshot_path(self._capture_id())
            self.values["settled_outcomes"] = dict(
                self._stage("settled_outcomes", inputs=[p.snapshots], operation=self._settled).value
            )
            if self.request.rotation:
                self.values["rotation"] = dict(
                    self._stage(
                        "rotation",
                        inputs=[selected, self._rotation_source()],
                        operation=self._rotation,
                    ).value
                )
            handoff_inputs = [selected]
            if self.supplied_handoff:
                handoff_inputs.append(self.supplied_handoff)
            else:
                handoff_inputs.append(p.archive)
                if self.request.projection == "component" and "top100_evidence" in self.values:
                    handoff_inputs.extend(
                        Path(self.values["top100_evidence"][key]) for key in ("table", "manifest")
                    )
            self.values["handoff"] = dict(
                self._stage("handoff", inputs=handoff_inputs, operation=self._handoff).value
            )
            held_handoff = Path(self.values["handoff"]["path"])
            if self.request.decide:
                self.values["decide"] = dict(
                    self._stage(
                        "decide",
                        inputs=[selected, held_handoff, *self.ledger_inputs],
                        operation=self._decide,
                    ).value
                )
            self._seed_preview()
            common = [selected, held_handoff, p.registry, self._published_tree()]
            top100_inputs = (
                [Path(self.values["top100_evidence"][key]) for key in ("table", "manifest")]
                if "top100_evidence" in self.values
                else []
            )
            # The history documents read every record of the season; the record this run
            # writes for its own capture is the stage's output, so a week whose records
            # moved between runs is visible as changed inputs rather than as changed bytes.
            self.values["league"] = dict(
                self._stage(
                    "league",
                    inputs=[*common, p.archive, *self.record_inputs, *top100_inputs],
                    operation=self._league,
                ).value
            )
            # The run log is not a declared input: this run appends its own records to it
            # while it works, so fingerprinting it would report "inputs changed" on every
            # resume. The status page's recent events are a live read of this machine's
            # log, this run's records included, not a frozen artifact of the week.
            self.values["site"] = dict(
                self._stage("site", inputs=[*common, p.ledger], operation=self._site).value
            )
            cohort_inputs = [
                self._snapshot_path(identifier)
                for identifier in (self._cohort_id(), self._elite_id())
                if identifier
            ]
            self.values["scoreboard"] = dict(
                self._stage(
                    "scoreboard",
                    inputs=[*common, p.ledger, p.evidence, p.snapshots, *cohort_inputs],
                    operation=self._scoreboard,
                ).value
            )
            if self.request.publish:
                # What ships is the preview tree, so that is the stage's whole input.
                self.values["publish"] = dict(
                    self._stage(
                        "publish",
                        inputs=[p.out / "data"],
                        operation=self._publish,
                        repeatable=False,
                    ).value
                )
            try:
                receipt = self.run.finish()
            except Exception as error:
                self.log.failure("tick.week.failed", error=str(error))
                raise
            self.log.event("tick.week.done", receipt=str(receipt))
            return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--season")
    parser.add_argument("--gameweek", type=int)
    parser.add_argument("--league", type=int)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--cohort-snapshot")
    parser.add_argument("--elite-snapshot")
    parser.add_argument("--skip-top100", action="store_true")
    parser.add_argument(
        "--projection", choices=("component", "component-only"), default="component"
    )
    parser.add_argument("--decide", action="store_true")
    parser.add_argument("--chip", choices=CHIP_CHOICES)
    parser.add_argument("--rotation", action="store_true")
    parser.add_argument(
        "--rotation-capture",
        help=(
            "a club-news capture id to export the rotation evidence from; without it the "
            "committed synthetic fixture is read, which is what every run did before"
        ),
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, help="Preview root; default: private run-directory/preview"
    )
    parser.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--record-advice", action="store_true", help="Record advice even without --publish."
    )
    parser.add_argument(
        "--no-advice-record",
        action="store_true",
        help="Publish without recording the advice, as the league build's switch of the same "
        "name does. The escape when the reused capture already holds records from another "
        "commit and the deadline will not wait; the existing records are kept.",
    )
    parser.add_argument(
        "--publish-suffix", default="", help="Suffix for the site publication branch."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument(
        "--expected-at", help="Explicit expected successful completion instant for status"
    )
    parser.add_argument(
        "--repository-commit", help="Declared 40-character source revision for a non-Git workspace"
    )
    parser.add_argument(
        "--handoff",
        type=Path,
        help="Reuse a verified prebuilt projection; requires --skip-top100, "
        "bypasses --projection build selection",
    )
    return parser


def _revision(workspace: Path, supplied: str | None) -> str:
    """The revision every stage of this week's journal is declared under.

    An **identity** use, so it refuses rather than publishing absence, and the strictest of
    the four: this value is the journal declaration a resume reads back and the base
    ``check_publication_base`` compares against.

    Both refusals stay here rather than moving into the shared resolver, and for one reason.
    Resolving a revision and holding a workspace to release discipline are different jobs: a
    container image has no checkout to be clean and no HEAD to contradict, and a resolver that
    enforced either would refuse a correct deployment. A weekly run is the opposite case. Its
    ``--workspace`` *is* the source tree, the point of stamping a revision is that someone can
    later rebuild the week from it, and a tree that is modified or is not on the declared
    commit makes that impossible. So the resolver answers and this function judges.

    Unlike the other three this one asks about the workspace it was pointed at rather than the
    package's own checkout, for the same reason.
    """

    try:
        revision = source_revision(declared=supplied, workspace=workspace)
    except SourceRevisionError as error:
        raise WeekError(str(error)) from error
    if revision is None:
        raise WeekError(
            "A non-Git workspace requires --repository-commit with a full source revision."
        )
    if revision.checkout is not None:
        if revision.checkout.head != revision.commit:
            # Named by origin because it is no longer only ``--repository-commit`` that can
            # reach here: an exported SQUADOPT_REPOSITORY_COMMIT does too, and an operator
            # told only that "the supplied revision" is wrong would go looking at the flag.
            raise WeekError(
                f"The {revision.origin} source revision {revision.commit} differs from the "
                f"workspace HEAD {revision.checkout.head}."
            )
        if revision.checkout.modified:
            raise WeekError("Weekly evidence requires a clean source checkout.")
    return revision.commit


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.publish_suffix and not args.publish:
        parser.error("--publish-suffix requires --publish")
    if args.no_advice_record and not args.publish:
        parser.error("--no-advice-record requires --publish")
    if args.no_advice_record and args.record_advice:
        parser.error("--no-advice-record and --record-advice contradict each other")
    root = args.workspace.resolve()
    out = (root / args.out).resolve() if args.out is not None else None
    paths = WeeklyPaths.under(root, out=out)
    try:
        if args.status:
            if not args.run_id:
                parser.error("--status needs --run-id")
            result = inspect_run(paths.journal, args.run_id, expected_at_utc=args.expected_at)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "completed" and result["missed"] is not True else 1
        if not args.season or args.gameweek is None or args.league is None:
            parser.error("--season, --gameweek and --league are required for a weekly run")
        if args.resume and not args.run_id:
            parser.error("--resume needs the original --run-id")
        request = WeeklyRequest(
            args.season,
            args.gameweek,
            args.league,
            args.snapshot_id,
            args.cohort_snapshot,
            args.elite_snapshot,
            args.skip_top100,
            args.projection,
            args.decide,
            args.chip,
            args.rotation,
            args.workers,
            args.publish,
            args.rotation_capture,
        )
        print(request.plan().describe())
        names = PublishNames(request.season, request.gameweek, "decision", args.publish_suffix)
        recording = (
            "False (--no-advice-record)"
            if args.no_advice_record
            else str(request.publish or args.record_advice)
        )
        print(
            f"Record advice: {recording}; "
            f"publish suffix: {args.publish_suffix or '(none)'}; site branch: {names.branch}"
        )
        if args.dry_run:
            print("Dry run: nothing captured, built or published.")
            return 0
        revision = _revision(root, args.repository_commit)
        run_id = args.run_id or (
            f"week-{args.season}-gw{args.gameweek:02d}-"
            f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
        )
        print(f"Weekly run: {run_id}", flush=True)
        handoff = (root / args.handoff).resolve() if args.handoff else None
        operation = WeeklyOperations(
            request,
            paths,
            run_id=run_id,
            repository_commit=revision,
            resume=args.resume,
            handoff=handoff,
            record_advice=args.record_advice,
            publish_suffix=args.publish_suffix,
            no_advice_record=args.no_advice_record,
        )
        completed = operation.execute()
        print(f"Verified weekly run: {completed}")
        print(f"Preview: {operation.paths.out}")
        if not request.publish:
            print(
                "Not published. A source-controlled publication can be requested "
                "explicitly with --publish."
            )
        return 0
    except (
        WeeklyJournalError,
        WeekError,
        DataError,
        SettledOutcomeExportError,
        PublishError,
        OSError,
        ValueError,
        KeyError,
    ) as error:
        # A stage's own refusal is stated here, at the run's boundary, rather than escaping
        # as a traceback; the journal already holds which stage stopped and why.
        print(f"run_week stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
