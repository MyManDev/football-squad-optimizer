"""Deprecated compatibility shell for ``squadopt gameweek``.

Keep this module for one release so existing runbooks and automation continue to work.
New callers should use ``squadopt gameweek decide`` or ``squadopt gameweek settle``.
"""

import os
import sys
from pathlib import Path

from squadopt.application import verify_decision
from squadopt.data.sources.vaastav import build_panel
from squadopt.platform.cli import CliServices
from squadopt.platform.cli import main as cli_main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _option_value(arguments: list[str], name: str) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == name and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(f"{name}="):
            return argument.split("=", 1)[1]
    return None


def _take_phase(arguments: list[str]) -> tuple[str | None, list[str]]:
    remaining = list(arguments)
    value = _option_value(remaining, "--phase")
    if "--phase" in remaining:
        index = remaining.index("--phase")
        del remaining[index : index + 2]
    else:
        remaining = [item for item in remaining if not item.startswith("--phase=")]
    return value, remaining


def _compatibility_paths(arguments: list[str]) -> list[str]:
    explicit_paths = [REPOSITORY_ROOT]
    for name in (
        "--snapshot-root",
        "--ledger-root",
        "--archive-root",
        "--summary-output",
        "--in-season-projection",
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
        str(DEFAULT_ARCHIVE_ROOT),
        "--summary-root",
        str(REPOSITORY_ROOT / "docs"),
    ]


def main() -> int:
    phase, arguments = _take_phase(sys.argv[1:])
    if phase not in {"decide", "settle"}:
        print("\nGameweek operations failed:\n  --phase must be decide or settle.")
        return 1
    if phase == "settle" and _option_value(arguments, "--gameweek") is None:
        print("\nGameweek operations failed:\n  settle requires --gameweek.")
        return 1
    translated = ["gameweek", phase, *_compatibility_paths(arguments), *arguments]
    return cli_main(
        translated,
        services=CliServices(panel_builder=build_panel, verifier=verify_decision),
    )


if __name__ == "__main__":
    sys.exit(main())
