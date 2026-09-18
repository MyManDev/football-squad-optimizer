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

import numpy as np
import pandas as pd

from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, ARCHIVE_REPOSITORY, SUPPORTED_SEASONS
from squadopt.evaluation import EvaluationResult
from squadopt.experiments import SCREENING_EXPERIMENT_CONTRACT_VERSION
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import FEATURE_GENERATION_CONTRACT_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "sprint2"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "sources" / "vaastav_fpl_manifest.json"
DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
BOOTSTRAP_DRAWS = 2_000


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


def _edge_series(root: Path) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    for season in DEVELOPMENT_SEASONS:
        suffix = "" if season == "2024-25" else f"_{season}"
        document = json.loads(
            (root / f"template_rival_strength{suffix}.json").read_text(encoding="utf-8")
        )
        series[season] = [float(row["difference"]) for row in document["rows"]]
    return series


def _leave_one_out(series: dict[str, list[float]], season: str) -> tuple[float, ...]:
    return tuple(v for other, values in series.items() if other != season for v in values)


def _bootstrap_gap_interval(
    claimed: np.ndarray, realized: np.ndarray, seed: int
) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    gaps = []
    n = len(claimed)
    for _ in range(BOOTSTRAP_DRAWS):
        pick = generator.integers(0, n, size=n)
        gaps.append(float(claimed[pick].mean() - realized[pick].mean()))
    return float(np.quantile(gaps, 0.05)), float(np.quantile(gaps, 0.95))


#: The deterministic work a measurement's solve may spend. Chosen from a sweep of the rotation
#: ceiling's 147 control folds on 2026-09-18: at 0.5 (the production benchmark's limit) 29 solves
#: were proved and 118 returned an incumbent; at 2.0, 89 and 58; at 5.0, 117 and 30; at 15.0, 130
#: and 17, for 1.7 times the run time of 5.0 and a mean realized score 0.007 away from it. The
#: limit does not buy reproducibility (every value reproduces); it buys proofs, and 5.0 is where
#: most solves are proved and the next step costs more than it returns.
MEASUREMENT_DETERMINISTIC_TIME_LIMIT = 5.0
#: A cap, never the binding limit: about forty times the wall time a 5.0 solve took when quiet.
MEASUREMENT_WALL_TIME_LIMIT_SECONDS = 600.0


def measurement_optimization_config() -> OptimizationConfig:
    """The solver limits of a run that writes a committed record.

    ``OptimizationConfig()`` binds on ten wall-clock seconds, so a busy machine gives the
    solver less work, a solve that would have been proved returns an incumbent, and the same
    commit writes a different record (#590: the rotation ceiling moved from 0.959 to 0.667 and
    lost five folds under load). Deterministic time measures solver work, not elapsed seconds,
    so it is the binding limit here and the wall clock is a cap far above it.
    """

    return OptimizationConfig(
        solver_time_limit_seconds=MEASUREMENT_WALL_TIME_LIMIT_SECONDS,
        solver_deterministic_time_limit=MEASUREMENT_DETERMINISTIC_TIME_LIMIT,
    )


def solver_record(*results: EvaluationResult) -> dict[str, object]:
    """What a record has to say about the solves it rests on.

    The limits the solver ran under, and how many of the solves were proved and how many
    returned an incumbent. A number over unproven solves is still a number; a reader who
    cannot tell which kind it is cannot tell whether a re-run may move it.
    """

    config = results[0].config.optimization_config
    statuses: dict[str, int] = {}
    for result in results:
        for fold in result.folds:
            name = fold.optimization_result.solver_status.value
            statuses[name] = statuses.get(name, 0) + 1
    return {
        "solver_time_limit_seconds": config.solver_time_limit_seconds,
        "solver_deterministic_time_limit": config.solver_deterministic_time_limit,
        "binding_limit": (
            "deterministic_time"
            if config.solver_deterministic_time_limit is not None
            else "wall_clock"
        ),
        "solver_status_counts": dict(sorted(statuses.items())),
    }
