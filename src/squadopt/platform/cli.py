"""Installed, cross-platform command line for live SquadOpt operations.

The parser is deliberately only a transport adapter.  Application behavior remains in
``squadopt.application``; this module resolves files, builds a reproducible
``RunContext`` and executes that service through the shared platform runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from squadopt.application import (
    DecideRequest,
    DecideResult,
    DecisionVerifier,
    SettleRequest,
    SettleResult,
    TickObserver,
    TickRequest,
    TickResult,
    TickValue,
    decide,
    run_season_tick,
    settle,
    verify_decision,
)
from squadopt.application.commands import PanelBuilder
from squadopt.data.errors import DataError
from squadopt.data.snapshots import (
    METADATA_FILENAME,
    PAYLOAD_DIRECTORY,
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotMetadata,
    list_snapshot_ids,
    read_snapshot,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    CHIP_NAMES,
    PROJECTION_HANDOFF_CONTRACT_VERSION,
    REPORT_CONTRACT_VERSION,
    SEASON_LEDGER_CONTRACT_VERSION,
)
from squadopt.live.runlog import RunLog, configure_run_logging
from squadopt.live.tick import TickAction, TickConfig, TickPlan
from squadopt.planning import CHIP_NAMES as PLANNER_CHIP_NAMES
from squadopt.platform.artifacts import FileArtifactRegistry, artifact_checksum
from squadopt.platform.context import RunContext
from squadopt.platform.fpl_capture import capture as capture_snapshot
from squadopt.platform.runtime import (
    RuntimeArtifact,
    RuntimeInputArtifact,
    RuntimeOperationResult,
    RuntimePreparationError,
    RuntimeRequest,
    RuntimeResult,
    RuntimeRunner,
)

EXIT_OK: Final = 0
EXIT_KNOWN_FAILURE: Final = 1
EXIT_UNEXPECTED_FAILURE: Final = 2
CLI_REQUEST_SCHEMA: Final = "cli_request_v1"
FILE_SCHEMA: Final = "file_v1"
COMPONENT_VERSIONS: Final[dict[str, str]] = {
    "application_commands": "application_commands_v1",
    "platform_runtime": "runtime_v1",
}
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_PLAN_KEYS = ("latest_capture", "next_gameweek", "next_deadline_utc", "hours_to_deadline")

Verifier = DecisionVerifier
Capture = Callable[[Path], SnapshotMetadata | None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CliServices:
    """Replaceable edge dependencies used by compatibility and offline tests."""

    panel_builder: PanelBuilder = build_panel
    verifier: Verifier = verify_decision
    capture: Capture = capture_snapshot
    clock: Callable[[], datetime] = field(default=_utc_now)


@dataclass(frozen=True, slots=True)
class _Paths:
    workspace: Path
    snapshot: Path
    ledger: Path
    archive: Path
    handoff: Path
    summary: Path
    runtime: Path
    log: Path | None


@dataclass(frozen=True, slots=True)
class _Input:
    path: Path
    kind: str
    schema_version: str


class _KnownCliFailure(Exception):
    """A domain rejection already safe to show to an operator."""


class _CliTickObserver(TickObserver):
    def __init__(self, log: RunLog) -> None:
        self.log = log
        self.completed = 0

    def planned(self, plan: TickPlan, *, replanned: bool) -> None:
        if replanned:
            print("re-planned after capture:")
        print(f"tick at {plan.now_utc} (season {plan.season or 'unknown'})")
        for key in _PLAN_KEYS:
            if key in plan.diagnostics:
                print(f"  {key:<20} {plan.diagnostics[key]}")
        for action in plan.actions:
            target = f" GW{action.gameweek}" if action.gameweek is not None else ""
            print(f"  -> {action.kind}{target}: {action.reason}")
        self.log.event(
            "tick.plan",
            now_utc=plan.now_utc,
            season=plan.season,
            replanned=replanned,
            actions=[
                {
                    "kind": action.kind,
                    "gameweek": action.gameweek,
                    "snapshot_id": action.snapshot_id,
                    "reason": action.reason,
                }
                for action in plan.actions
            ],
        )

    def action_started(self, action: TickAction) -> None:
        self.log.event("tick.action.start", kind=action.kind, gameweek=action.gameweek)

    def action_completed(self, action: TickAction, value: TickValue) -> None:
        if isinstance(value, SnapshotMetadata):
            print(f"captured {value.snapshot_id}")
        elif isinstance(value, DecideResult):
            _print_decide(value)
        elif isinstance(value, SettleResult):
            _print_settle(value)
        self.completed += 1
        self.log.event("tick.action.done", kind=action.kind, gameweek=action.gameweek)

    def action_failed(self, action: TickAction, error: Exception) -> None:
        self.log.failure(
            "tick.action.failed",
            kind=action.kind,
            gameweek=action.gameweek,
            error=str(error),
        )


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path.cwd(),
        help="portable artifact boundary and base for relative paths (default: current directory)",
    )
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--ledger-root", type=Path, default=Path("data/ledger"))
    parser.add_argument("--archive-root", type=Path, default=Path("data/raw/vaastav-fpl"))
    parser.add_argument("--handoff-root", type=Path, default=Path("data/handoffs"))
    parser.add_argument("--summary-root", type=Path, default=Path("docs"))
    parser.add_argument("--runtime-root", type=Path, default=Path("data/runtime"))
    parser.add_argument(
        "--log-root",
        default="data/logs",
        help="JSONL log directory relative to workspace; '-' disables file logging",
    )
    parser.add_argument(
        "--repository-commit",
        help="40-character source commit (default: git HEAD)",
    )
    parser.add_argument("--seed", type=int, default=0, help="deterministic operation seed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="squadopt", description=__doc__)
    commands = parser.add_subparsers(dest="area", required=True)

    gameweek = commands.add_parser("gameweek", help="run a gameweek command")
    gameweek_commands = gameweek.add_subparsers(dest="operation", required=True)
    decide_parser = gameweek_commands.add_parser("decide", help="verify and freeze a decision")
    _add_common_paths(decide_parser)
    decide_parser.add_argument("--snapshot-id")
    decide_parser.add_argument("--gameweek", type=int)
    decide_parser.add_argument("--season")
    decide_parser.add_argument("--in-season-projection", type=Path)
    decide_parser.add_argument(
        "--risk-residuals",
        type=Path,
        help="Exported residual table (its .manifest.json sibling binds the identity); "
        "the report then carries the squad's spread instead of not_requested.",
    )
    decide_parser.add_argument(
        "--summary-output",
        type=Path,
        help=argparse.SUPPRESS,
    )
    decide_parser.add_argument("--chip", choices=sorted(set(CHIP_NAMES) & set(PLANNER_CHIP_NAMES)))

    settle_parser = gameweek_commands.add_parser("settle", help="settle a frozen decision")
    _add_common_paths(settle_parser)
    settle_parser.add_argument("--snapshot-id")
    settle_parser.add_argument("--gameweek", type=int, required=True)
    settle_parser.add_argument("--season")
    settle_parser.add_argument("--summary-output", type=Path)

    season = commands.add_parser("season", help="run the scheduled season loop")
    season_commands = season.add_subparsers(dest="operation", required=True)
    tick_parser = season_commands.add_parser("tick", help="capture, decide or settle when due")
    _add_common_paths(tick_parser)
    tick_parser.add_argument("--season")
    tick_parser.add_argument("--now", help="UTC instant override for replay/tests")
    tick_parser.add_argument("--capture-window-hours", type=float, default=3.0)
    tick_parser.add_argument("--settle-grace-hours", type=float, default=48.0)
    tick_parser.add_argument("--settle-recapture-hours", type=float, default=12.0)
    tick_parser.add_argument("--dry-run", action="store_true")
    tick_parser.add_argument("--summary-output", type=Path)
    return parser


def _under(workspace: Path, value: Path | str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else workspace / path).resolve()


def _paths(arguments: argparse.Namespace) -> _Paths:
    workspace = Path(arguments.workspace_root).resolve()
    values = {
        "snapshot": _under(workspace, arguments.snapshot_root),
        "ledger": _under(workspace, arguments.ledger_root),
        "archive": _under(workspace, arguments.archive_root),
        "handoff": _under(workspace, arguments.handoff_root),
        "summary": _under(workspace, arguments.summary_root),
        "runtime": _under(workspace, arguments.runtime_root),
    }
    log = None if str(arguments.log_root) == "-" else _under(workspace, arguments.log_root)
    checked_paths = list(values.items())
    if log is not None:
        checked_paths.append(("log", log))
    for label, path in checked_paths:
        try:
            path.relative_to(workspace)
        except ValueError as error:
            raise DataError(f"{label} path {path} is outside workspace {workspace}.") from error
    return _Paths(workspace=workspace, log=log, **values)


def _optional_path(workspace: Path, value: Path | None) -> Path | None:
    return None if value is None else _under(workspace, value)


def _files(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root.resolve(),)
    if not root.is_dir():
        return ()
    return tuple(sorted(path.resolve() for path in root.rglob("*") if path.is_file()))


def _snapshot_files(root: Path, requested: str | None) -> tuple[str, tuple[Path, ...]]:
    identifiers = list_snapshot_ids(root)
    if requested is None:
        if not identifiers:
            raise DataError(f"No snapshots under {root}. Run 'squadopt season tick' first.")
        identifier = identifiers[-1]
    elif requested not in identifiers:
        raise DataError(f"No snapshot {requested!r} under {root}.")
    else:
        identifier = requested
    snapshot = read_snapshot(root, identifier)
    directory = root / identifier
    paths = [directory / METADATA_FILENAME]
    paths.extend(
        directory / PAYLOAD_DIRECTORY / name for name in sorted(snapshot.metadata.checksums)
    )
    return identifier, tuple(path.resolve() for path in paths)


def _relative(workspace: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace).as_posix()


def _config_document(arguments: argparse.Namespace, paths: _Paths) -> dict[str, object]:
    excluded = {"workspace_root", "repository_commit", "log_root", "runtime_root"}
    document: dict[str, object] = {}
    for key, value in sorted(vars(arguments).items()):
        if key in excluded:
            continue
        if isinstance(value, Path):
            value = _relative(paths.workspace, _under(paths.workspace, value))
        document[key] = value
    return {"contract_version": CLI_REQUEST_SCHEMA, "command": document}


def _write_request(paths: _Paths, document: dict[str, object]) -> tuple[Path, str]:
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    fingerprint = hashlib.sha256(payload).hexdigest()
    target = paths.runtime / "requests" / f"{fingerprint}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != payload:
        raise DataError(f"Runtime request collision at {target}.")
    if not target.exists():
        target.write_bytes(payload)
    return target, fingerprint


def _git_commit(workspace: Path, supplied: str | None) -> str:
    candidates = [supplied, os.environ.get("SQUADOPT_REPOSITORY_COMMIT")]
    roots = (workspace, Path(__file__).resolve().parents[3])
    for root in roots:
        if any(candidates):
            break
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            shell=False,
        )
        if result.returncode == 0:
            candidates.append(result.stdout.strip())
    value = next((candidate for candidate in candidates if candidate), "").lower()
    if not _COMMIT_PATTERN.fullmatch(value):
        raise DataError(
            "Could not resolve a 40-character repository commit; pass --repository-commit "
            "or SQUADOPT_REPOSITORY_COMMIT."
        )
    return value


def _deduplicate(inputs: Iterable[_Input]) -> tuple[_Input, ...]:
    by_path: dict[Path, _Input] = {}
    for item in inputs:
        by_path.setdefault(item.path.resolve(), item)
    return tuple(by_path[path] for path in sorted(by_path))


def _runtime(
    arguments: argparse.Namespace,
    paths: _Paths,
    inputs: Iterable[_Input],
    *,
    operation: str,
    services: CliServices,
) -> tuple[RuntimeRunner, RuntimeRequest, RunLog]:
    document = _config_document(arguments, paths)
    request_path, config_fingerprint = _write_request(paths, document)
    declared = _deduplicate(
        (_Input(request_path, "command_request", CLI_REQUEST_SCHEMA), *tuple(inputs))
    )
    runtime_inputs: list[RuntimeInputArtifact] = []
    fingerprints: dict[str, str] = {}
    for index, item in enumerate(declared):
        name = f"input_{index:04d}"
        fingerprints[name] = artifact_checksum(item.path)
        runtime_inputs.append(RuntimeInputArtifact(item.path, item.kind, item.schema_version, name))
    context = RunContext.create(
        repository_commit=_git_commit(paths.workspace, arguments.repository_commit),
        configuration_fingerprint=config_fingerprint,
        input_fingerprints=fingerprints,
        deterministic_seed=arguments.seed,
        component_versions=COMPONENT_VERSIONS,
        now=services.clock(),
    )
    log = configure_run_logging(operation, log_root=paths.log, run_id=context.run_id, console=False)
    runner = RuntimeRunner(
        FileArtifactRegistry(paths.runtime / "registry", artifact_root=paths.workspace),
        paths.runtime / "runs",
        clock=services.clock,
    )
    return runner, RuntimeRequest(operation, context, tuple(runtime_inputs)), log


def _output(path: Path) -> RuntimeArtifact:
    if path.name in {"decision.json", "outcome.json", "manifest.json"}:
        return RuntimeArtifact(path, "season_ledger", SEASON_LEDGER_CONTRACT_VERSION)
    if path.name == "report.json":
        return RuntimeArtifact(path, "recommendation_report", REPORT_CONTRACT_VERSION)
    if path.suffix == ".md":
        return RuntimeArtifact(path, "season_summary", SEASON_LEDGER_CONTRACT_VERSION)
    if path.name == METADATA_FILENAME or PAYLOAD_DIRECTORY in path.parts:
        return RuntimeArtifact(path, "fpl_snapshot", SNAPSHOT_SCHEMA_VERSION)
    return RuntimeArtifact(path, "operation_output", FILE_SCHEMA)


def _print_decide(result: DecideResult) -> None:
    print(
        f"{result.mode}: snapshot {result.snapshot_id}, targeting "
        f"{result.season} gameweek {result.gameweek}"
    )
    print("Decision verification passed: all runbook checks hold.")
    print(result.report)
    print(f"Recorded decision at {result.decision_directory}")


def _print_settle(result: SettleResult) -> None:
    print(f"Recorded outcome at {result.outcome_path}")
    print(result.summary)
    print(f"Wrote {result.summary_path}")


def _finish(result: RuntimeResult[Any]) -> int:
    if result.completed:
        print(f"Run manifest: {result.manifest_path}")
        return EXIT_OK
    assert result.failure is not None
    print(f"\n{result.operation} failed:\n  {result.failure.message}")
    if result.failure.error_type == _KnownCliFailure.__name__:
        return EXIT_KNOWN_FAILURE
    return EXIT_UNEXPECTED_FAILURE


def _run_decide(arguments: argparse.Namespace, paths: _Paths, services: CliServices) -> int:
    requested_snapshot_id = arguments.snapshot_id
    snapshot_id, snapshot_files = _snapshot_files(paths.snapshot, requested_snapshot_id)
    projection = _optional_path(paths.workspace, arguments.in_season_projection)
    residuals = _optional_path(paths.workspace, arguments.risk_residuals)
    inputs = [*(_Input(path, "fpl_snapshot", SNAPSHOT_SCHEMA_VERSION) for path in snapshot_files)]
    inputs.extend(_Input(path, "historical_archive", FILE_SCHEMA) for path in _files(paths.archive))
    inputs.extend(
        _Input(path, "season_ledger", SEASON_LEDGER_CONTRACT_VERSION)
        for path in _files(paths.ledger)
    )
    if projection is not None:
        inputs.append(_Input(projection, "projection_handoff", PROJECTION_HANDOFF_CONTRACT_VERSION))
    runner, request, log = _runtime(
        arguments, paths, inputs, operation="gameweek_decide", services=services
    )

    def operation() -> RuntimeOperationResult[DecideResult]:
        try:
            result = decide(
                DecideRequest(
                    snapshot_root=paths.snapshot,
                    ledger_root=paths.ledger,
                    archive_root=paths.archive,
                    snapshot_id=snapshot_id,
                    gameweek=arguments.gameweek,
                    season=arguments.season,
                    in_season_projection=projection,
                    risk_residuals=residuals,
                    chip=arguments.chip,
                    mode="replay" if requested_snapshot_id else "live",
                ),
                panel_builder=services.panel_builder,
                verifier=services.verifier,
            )
        except DataError as error:
            raise _KnownCliFailure(str(error)) from error
        _print_decide(result)
        return RuntimeOperationResult(result, tuple(_output(path) for path in result.output_paths))

    return _finish(runner.execute(request, operation, events=log))


def _run_settle(arguments: argparse.Namespace, paths: _Paths, services: CliServices) -> int:
    snapshot_id, snapshot_files = _snapshot_files(paths.snapshot, arguments.snapshot_id)
    inputs = [*(_Input(path, "fpl_snapshot", SNAPSHOT_SCHEMA_VERSION) for path in snapshot_files)]
    inputs.extend(
        _Input(path, "season_ledger", SEASON_LEDGER_CONTRACT_VERSION)
        for path in _files(paths.ledger)
    )
    runner, request, log = _runtime(
        arguments, paths, inputs, operation="gameweek_settle", services=services
    )
    summary_output = _optional_path(paths.workspace, arguments.summary_output)

    def operation() -> RuntimeOperationResult[SettleResult]:
        try:
            result = settle(
                SettleRequest(
                    snapshot_root=paths.snapshot,
                    ledger_root=paths.ledger,
                    summary_root=paths.summary,
                    gameweek=arguments.gameweek,
                    snapshot_id=snapshot_id,
                    season=arguments.season,
                    summary_output=summary_output,
                )
            )
        except DataError as error:
            raise _KnownCliFailure(str(error)) from error
        _print_settle(result)
        return RuntimeOperationResult(result, tuple(_output(path) for path in result.output_paths))

    return _finish(runner.execute(request, operation, events=log))


def _tick_outputs(result: TickResult) -> tuple[RuntimeArtifact, ...]:
    paths: list[Path] = []
    for performed in result.performed:
        value = performed.value
        if isinstance(value, SnapshotMetadata):
            directory = result.request.snapshot_root / value.snapshot_id
            paths.extend(_files(directory))
        elif isinstance(value, DecideResult | SettleResult):
            paths.extend(value.output_paths)
    return tuple(_output(path) for path in sorted(set(paths)))


def _run_tick(arguments: argparse.Namespace, paths: _Paths, services: CliServices) -> int:
    now_utc = arguments.now or services.clock().replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    arguments.now = now_utc
    inputs: list[_Input] = []
    inputs.extend(
        _Input(path, "fpl_snapshot", SNAPSHOT_SCHEMA_VERSION) for path in _files(paths.snapshot)
    )
    inputs.extend(_Input(path, "historical_archive", FILE_SCHEMA) for path in _files(paths.archive))
    inputs.extend(
        _Input(path, "season_ledger", SEASON_LEDGER_CONTRACT_VERSION)
        for path in _files(paths.ledger)
    )
    inputs.extend(
        _Input(path, "projection_handoff", PROJECTION_HANDOFF_CONTRACT_VERSION)
        for path in _files(paths.handoff)
    )
    runner, runtime_request, log = _runtime(
        arguments, paths, inputs, operation="season_tick", services=services
    )
    observer = _CliTickObserver(log)
    summary_output = _optional_path(paths.workspace, arguments.summary_output)

    def capture_with_archive(root: Path) -> SnapshotMetadata | None:
        return capture_snapshot(root, archive_root=paths.archive)

    capture: Capture = (
        capture_with_archive if services.capture is capture_snapshot else services.capture
    )

    def operation() -> RuntimeOperationResult[TickResult]:
        try:
            result = run_season_tick(
                TickRequest(
                    snapshot_root=paths.snapshot,
                    ledger_root=paths.ledger,
                    archive_root=paths.archive,
                    handoff_root=paths.handoff,
                    summary_root=paths.summary,
                    now_utc=now_utc,
                    season=arguments.season,
                    summary_output=summary_output,
                    config=TickConfig(
                        capture_window_hours=arguments.capture_window_hours,
                        settle_grace_hours=arguments.settle_grace_hours,
                        settle_recapture_hours=arguments.settle_recapture_hours,
                    ),
                ),
                capture=capture,
                panel_builder=services.panel_builder,
                dry_run=bool(arguments.dry_run),
                observer=observer,
            )
        except DataError as error:
            raise _KnownCliFailure(str(error)) from error
        if result.dry_run:
            print("dry run: nothing changed")
        else:
            print(f"tick done: {result.action_count} action(s) performed")
        return RuntimeOperationResult(result, _tick_outputs(result))

    return _finish(runner.execute(runtime_request, operation, events=log))


def main(argv: Sequence[str] | None = None, *, services: CliServices | None = None) -> int:
    """Parse and execute one command, returning a stable process exit code."""

    parser = build_parser()
    arguments = parser.parse_args(None if argv is None else list(argv))
    dependencies = services or CliServices()
    try:
        paths = _paths(arguments)
        if arguments.area == "gameweek" and arguments.operation == "decide":
            return _run_decide(arguments, paths, dependencies)
        if arguments.area == "gameweek" and arguments.operation == "settle":
            return _run_settle(arguments, paths, dependencies)
        return _run_tick(arguments, paths, dependencies)
    except (DataError, RuntimePreparationError, OSError, ValueError) as error:
        print(f"\nCommand failed:\n  {error}")
        return EXIT_KNOWN_FAILURE
    except Exception as error:  # installed/scheduled entry points must not fail silently
        print(f"\nCommand crashed:\n  {type(error).__name__}: {error}")
        return EXIT_UNEXPECTED_FAILURE


if __name__ == "__main__":
    sys.exit(main())
