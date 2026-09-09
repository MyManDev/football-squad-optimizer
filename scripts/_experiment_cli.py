"""Shared provenance and artifact helpers for Sprint 2 command-line runners."""

import hashlib
import json
import os
import platform
import subprocess
from collections.abc import Sequence
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


#: The published site tree, and the one part of the checkout a run of the weekly loop
#: rewrites itself. ``run_week``'s league, site and scoreboard steps all build into it, and
#: ``status.json`` carries the hours left to the deadline, so it differs a second later --
#: a checkout that has published once is never clean again until the publish PR merges.
#:
#: Nothing under it is an input to anything this repository exports. The artifacts are built
#: from the captures under ``data/snapshots/``, the archive under ``data/raw/``, and the code
#: at ``HEAD``; no exporter reads a file from here. A change confined to this tree therefore
#: cannot change what an artifact says, and cannot stop that artifact being rebuilt from the
#: commit it records -- which is the only question the dirty-tree refusals ask.
GENERATED_SITE_TREE = "web/public/data"


def reproducibility_blockers(cwd: Path = REPOSITORY_ROOT) -> tuple[str, ...]:
    """The working-tree entries that would make an artifact unreproducible from ``HEAD``.

    ``git status --porcelain`` lines, verbatim, so a caller can name the paths rather than
    say only that something is wrong.

    Untracked paths count, and deliberately: an untracked module beside an exporter can be
    imported and change what the export computes, so this has always had to look wider than
    ``git diff``. The single exclusion is :data:`GENERATED_SITE_TREE`, for the reason stated
    there, and git does the excluding through a pathspec rather than a parser here -- a
    rename entry or a path with a space cannot be mis-read into a wrong answer.
    """

    try:
        return tuple(
            line
            for line in subprocess.run(
                ["git", "status", "--porcelain", "--", ".", f":(exclude){GENERATED_SITE_TREE}"],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            if line.strip()
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot read the working tree: {error}") from error


def _git_revision() -> tuple[str, bool]:
    """The commit an artifact would record, and whether the tree disagrees with it.

    ``dirty`` is :func:`reproducibility_blockers` reduced to a flag, so the refusals built
    on it and the pre-flight that runs before them ask exactly one question and can never
    give two answers about the same checkout.
    """

    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot record repository provenance: {error}") from error
    return revision, bool(reproducibility_blockers())


def artifact_metadata(
    *,
    panel_rows: int,
    created_utc: str | None = None,
    history_seasons: Sequence[str] | None = None,
) -> dict[str, object]:
    """Return dataset, repository, dependency, and hardware provenance.

    ``history_seasons`` is the list of seasons the caller actually loaded; callers
    that load the full supported range may omit it and keep the historical default.
    """

    revision, dirty = _git_revision()
    return {
        "created_utc": created_utc or datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": {
            "repository_commit": revision,
            "working_tree_dirty": dirty,
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
            "archive_manifest_sha256": _sha256(MANIFEST_PATH),
            "history_seasons": list(
                SUPPORTED_SEASONS if history_seasons is None else history_seasons
            ),
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
