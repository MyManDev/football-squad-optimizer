"""Repository provenance and artifact writing, on the standard library only.

``_experiment_cli`` imports ``squadopt.experiments`` for its measurement helpers, so an
operational command that took these names from it loaded the laboratory as well. They live
here, and ``_experiment_cli`` imports them back, so the runners that use it get the same
objects and write the same bytes. ``tests/unit/test_run_boundary.py`` fails when an
operational command loads a laboratory module.
"""

import json
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _git_revision() -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot record repository provenance: {error}") from error
    return revision, dirty


def write_json(path: Path, value: object) -> None:
    """Write one stable UTF-8 JSON artifact, creating only its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    """Write one UTF-8 text artifact, creating only its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
