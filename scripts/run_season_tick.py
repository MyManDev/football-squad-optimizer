"""Deprecated compatibility shell for ``squadopt season tick``."""

import os
import sys
from pathlib import Path

from squadopt.data.sources.vaastav import build_panel
from squadopt.platform.cli import CliServices
from squadopt.platform.cli import main as cli_main
from squadopt.platform.fpl_capture import capture as capture_snapshot

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _option_value(arguments: list[str], name: str) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == name and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(f"{name}="):
            return argument.split("=", 1)[1]
    return None


def _compatibility_paths(arguments: list[str]) -> list[str]:
    explicit_paths = [REPOSITORY_ROOT]
    for name in (
        "--snapshot-root",
        "--ledger-root",
        "--archive-root",
        "--handoff-root",
        "--summary-output",
    ):
        value = _option_value(arguments, name)
        if value is not None:
            explicit_paths.append(Path(value).resolve())
    workspace = Path(os.path.commonpath([str(path) for path in explicit_paths]))
    ledger = _option_value(arguments, "--ledger-root")
    runtime = (Path(ledger).resolve().parent if ledger else REPOSITORY_ROOT / "data") / "runtime"
    return [
        "--workspace-root",
        str(workspace),
        "--runtime-root",
        str(runtime),
        "--archive-root",
        str(REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"),
        "--summary-root",
        str(REPOSITORY_ROOT / "docs"),
    ]


def main() -> int:
    arguments = sys.argv[1:]
    return cli_main(
        ["season", "tick", *_compatibility_paths(arguments), *arguments],
        services=CliServices(panel_builder=build_panel, capture=capture_snapshot),
    )


if __name__ == "__main__":
    sys.exit(main())
