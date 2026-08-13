"""Shared provenance and artifact helpers for Sprint 2 command-line runners."""

import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, ARCHIVE_REPOSITORY, SUPPORTED_SEASONS
from squadopt.experiments import SCREENING_EXPERIMENT_CONTRACT_VERSION
from squadopt.prediction import FEATURE_GENERATION_CONTRACT_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "sprint2"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "sources" / "vaastav_fpl_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


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


def artifact_metadata(*, panel_rows: int, created_utc: str | None = None) -> dict[str, object]:
    """Return dataset, repository, dependency, and hardware provenance."""

    revision, dirty = _git_revision()
    return {
        "created_utc": created_utc or datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": {
            "repository_commit": revision,
            "working_tree_dirty": dirty,
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
            "archive_manifest_sha256": _sha256(MANIFEST_PATH),
            "history_seasons": list(SUPPORTED_SEASONS),
            "history_rows": panel_rows,
            "experiment_contract_version": SCREENING_EXPERIMENT_CONTRACT_VERSION,
            "feature_generation_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
        },
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "logical_cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "ortools": version("ortools"),
        },
    }


def write_json(path: Path, value: object) -> None:
    """Write one stable UTF-8 JSON artifact, creating only its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    """Write one UTF-8 text artifact, creating only its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
