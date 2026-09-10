"""Installed weekly entry point: typed application services and a durable stage journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.features.evidence_artifact import read_player_evidence_artifact
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.live import handoff_path_for, load_entry, read_projection_handoff, read_season_rules
from squadopt.platform import cohort_capture, elite_capture
from squadopt.platform._queue_lock import QueueFileLock
from squadopt.platform.fpl_capture import capture
from squadopt.platform.projection_retention import publish_retained_handoff, retained_handoff_path
from squadopt.platform.publication_workers import league_mapper
from squadopt.platform.weekly_journal import (
    WeeklyJournalError,
    WeeklyRun,
    WeeklyStageResult,
    fingerprint_paths,
    inspect_run,
    read_run_request,
)
from squadopt.platform.weekly_publish import (
    PublishError,
    PublishNames,
    check_publication_base,
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
    log: Path
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
            out or root / "data/runtime/weekly/preview",
            root / "data/runtime/weekly",
            root / "data/logs/season_tick",
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


class WeeklyOperations:
    def __init__(
        self,
        request: WeeklyRequest,
        paths: WeeklyPaths,
        *,
        run_id: str,
        repository_commit: str,
        resume: bool = False,
        handoff: Path | None = None,
    ) -> None:
        if paths.out == paths.journal / "preview":
            paths = replace(paths, out=paths.journal / run_id / "preview")
        self.request, self.paths, self.run_id = request, paths, run_id
        self.repository_commit, self.resume = repository_commit, resume
        self.supplied_handoff = handoff
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
        if resume:
            prior = read_run_request(paths.journal, run_id)
            # Derived reads belong to the original preflight, even after this run captures
            # a newer snapshot or writes its own decision during an earlier invocation.
            self.rule_snapshot = prior["rule_snapshot"]
            self.ledger_inputs = [Path(value) for value in prior["ledger_inputs"]]
        declaration = {
            "request": asdict(request),
            "paths": {key: str(value) for key, value in asdict(paths).items()},
            "repository_commit": repository_commit,
            "package_sha256": package_fingerprint(),
            "supplied_handoff": str(handoff) if handoff else None,
            "rule_snapshot": self.rule_snapshot,
            "ledger_inputs": list(map(str, self.ledger_inputs)),
        }
        self.run = WeeklyRun(paths.journal, run_id, declaration, self.stages, resume=resume)

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
        if self.request.publish:
            # The publish stage checks this too, but only after every capture and solve
            # has been spent; asked here first so a run off the fresh origin/develop
            # refuses before it spends anything.
            try:
                check_publication_base(self.paths.workspace, self.repository_commit)
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

    def _rotation(self) -> WeeklyStageResult:
        identifier = self._capture_id()
        table, manifest = rotation_artifact(
            self.paths.rotation, self.request.season, self.request.gameweek, identifier
        )
        if not (table.is_file() and manifest.is_file()):
            export_rotation_evidence(
                RotationExportRequest(
                    self.request.season,
                    self.request.gameweek,
                    str(self.values["capture"]["deadline_utc"]),
                    identifier,
                    self.paths.snapshots,
                    self.paths.club_news_fixture,
                    self.paths.rotation,
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

    def _league(self, out: Path | None = None, *, record: bool = False) -> WeeklyStageResult:
        request = LeaguePublicationRequest(
            self.paths.snapshots,
            self._capture_id(),
            self.paths.archive,
            self.paths.registry,
            out or self.paths.out,
            self.request.league_id,
            season=self.request.season,
            gameweek=self.request.gameweek,
            handoff_path=Path(self.values["handoff"]["path"]),
            record_root=self.paths.records if record else None,
            history_record_root=self.paths.records,
        )
        with league_mapper(request, self.request.workers) as mapper:
            result = publish_league(request, mapper=mapper)
        return WeeklyStageResult(
            result.output_paths,
            {
                "snapshot_id": result.snapshot_id,
                "gameweek": result.gameweek,
                "advice_recorded": record,
            },
        )

    def _site(self, out: Path | None = None) -> WeeklyStageResult:
        result = publish_site(
            SitePublicationRequest(
                self.paths.snapshots,
                self.paths.ledger,
                self.paths.archive,
                self.paths.handoffs,
                self.run.directory,
                self.paths.log,
                out or self.paths.out,
                season=self.request.season,
                snapshot_id=self._capture_id(),
            )
        )
        return WeeklyStageResult(result.output_paths, {"snapshot_id": result.snapshot_id})

    def _scoreboard(self, out: Path | None = None) -> WeeklyStageResult:
        result = publish_scoreboard(
            ScoreboardPublicationRequest(
                self.paths.snapshots,
                self._capture_id(),
                self.paths.registry,
                self.paths.ledger,
                out or self.paths.out,
                self.request.league_id,
                season=self.request.season,
                cohort_snapshot_id=self._cohort_id(),
                elite_snapshot_id=self._elite_id(),
            )
        )
        return WeeklyStageResult(result.output_paths, {"snapshot_id": result.snapshot_id})

    def _publish(self) -> WeeklyStageResult:
        proof: dict[str, object] = {}
        private_records: list[Path] = []

        def build(out: Path) -> None:
            for result in (self._site(out), self._league(out, record=True), self._scoreboard(out)):
                fingerprint_paths(result.output_paths)
                private_records.extend(
                    path for path in result.output_paths if out not in path.parents
                )

        exit_code = publish(
            PublishNames(self.request.season, self.request.gameweek, "decision"),
            force_branch=False,
            dry_run=False,
            workspace=self.paths.workspace,
            builder=build,
            expected_commit=self.repository_commit,
            on_published=lambda value: proof.update(value),
        )
        if exit_code != 0 or not proof:
            raise WeekError("Publication did not return a verified PR/no-change receipt.")
        return self._receipt("publish", dict(proof), tuple(private_records))

    def execute(self) -> Path:
        p = self.paths
        with (
            QueueFileLock(p.journal / ".workspace.lock", timeout_seconds=0).hold(),
            self.run.hold(),
        ):
            initial_inputs = [p.registry, *self.ledger_inputs]
            if self.rule_snapshot:
                initial_inputs.append(self._snapshot_path(self.rule_snapshot))
            self.values["preflight"] = dict(
                self.run.stage("preflight", inputs=initial_inputs, operation=self._preflight).value
            )
            if "top100" in self.plan.steps:
                self.values["top100_cohort"] = dict(
                    self.run.stage("top100_cohort", inputs=[], operation=self._cohort).value
                )
                self.values["top100_picks"] = dict(
                    self.run.stage(
                        "top100_picks",
                        inputs=[self._snapshot_path(str(self._cohort_id()))],
                        operation=self._elite,
                    ).value
                )
                self.values["top100_evidence"] = dict(
                    self.run.stage(
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
                self.run.stage("capture", inputs=capture_inputs, operation=self._capture).value
            )
            selected = self._snapshot_path(self._capture_id())
            self.values["settled_outcomes"] = dict(
                self.run.stage(
                    "settled_outcomes", inputs=[p.snapshots], operation=self._settled
                ).value
            )
            if self.request.rotation:
                self.values["rotation"] = dict(
                    self.run.stage(
                        "rotation", inputs=[selected, p.club_news_fixture], operation=self._rotation
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
                self.run.stage("handoff", inputs=handoff_inputs, operation=self._handoff).value
            )
            held_handoff = Path(self.values["handoff"]["path"])
            if self.request.decide:
                self.values["decide"] = dict(
                    self.run.stage(
                        "decide",
                        inputs=[selected, held_handoff, *self.ledger_inputs],
                        operation=self._decide,
                    ).value
                )
            common = [selected, held_handoff, p.registry]
            publication_inputs = [*common, p.archive]
            self.values["league"] = dict(
                self.run.stage("league", inputs=publication_inputs, operation=self._league).value
            )
            self.values["site"] = dict(
                self.run.stage(
                    "site", inputs=[*common, p.ledger, p.log], operation=self._site
                ).value
            )
            cohort_inputs = [
                self._snapshot_path(identifier)
                for identifier in (self._cohort_id(), self._elite_id())
                if identifier
            ]
            self.values["scoreboard"] = dict(
                self.run.stage(
                    "scoreboard",
                    inputs=[*common, p.ledger, *cohort_inputs],
                    operation=self._scoreboard,
                ).value
            )
            if self.request.publish:
                self.values["publish"] = dict(
                    self.run.stage(
                        "publish",
                        inputs=[*publication_inputs, p.ledger, *cohort_inputs],
                        operation=self._publish,
                        repeatable=False,
                    ).value
                )
            return self.run.finish()


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
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, help="Preview root; default: private run-directory/preview"
    )
    parser.add_argument("--publish", action="store_true")
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
    import re

    value = supplied
    if (workspace / ".git").exists():
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=workspace, text=True
        ).strip()
        if supplied is not None and value != supplied:
            raise WeekError("Supplied source revision differs from the workspace HEAD.")
        if subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=workspace, text=True
        ).strip():
            raise WeekError("Weekly evidence requires a clean source checkout.")
    if value is None or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise WeekError(
            "A non-Git workspace requires --repository-commit with a full source revision."
        )
    return value


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
        )
        print(request.plan().describe())
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
