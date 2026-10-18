"""Score the predictive distributions of two Phase C v2 development arms, candidate against control.

The v2 export writes a distribution sidecar beside each arm's out-of-fold table
(`<table>.distribution.csv`, declared in the manifest's ``estimator.distribution_sidecar``
block). This runner reads both arms through the development reader, refuses two arms that are
not one paired measurement (the same checks as `compare_component_oof_development`), verifies
each sidecar's digest against its manifest, joins the sidecars to the realized targets on the
rows that appeared and sit on the ``component_model`` route in both arms, and applies the
proper-scoring reading declared in ``docs/research/moe_mixture_prereg.md``: the discretised
log score and the mid-point PIT of points and minutes given an appearance, pooled and per
season, with the per-fold paired log-score difference summarised by the season-aware
moving-block interval on the primary and the control-era season.

    python -m scripts.score_component_distribution --artifact-dir <dir> --candidate-arm mixture

Writes ``distribution_scoring.json`` and ``distribution_scoring.md`` under
``<dir>/comparison_<arm>/``. Nothing here enters the points-MAE rule or promotes anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import write_json, write_text
from scripts.compare_component_oof_development import (
    CANDIDATE_ARMS,
    CONTROL_ERA_SEASON,
    PRIMARY_SEASON,
    check_paired,
    load_arm,
)
from scripts.export_component_oof import DEVELOPMENT_OOF_CONTRACT_VERSION

from squadopt.evaluation import EvaluationValidationError, PhaseCComponentHandoff
from squadopt.experiments.component_distribution_scoring import (
    KEY_COLUMNS,
    POLICY,
    render_markdown,
    score_arms,
)
from squadopt.prediction.component_models import DISTRIBUTION_COLUMNS
from squadopt.preflight import compute_table_sha256

TARGET_COLUMNS = ("appearance_target", "minutes_target", "points_target", "composition_route")


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--control", default=f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_equal")
    parser.add_argument("--candidate", default=None)
    parser.add_argument("--candidate-arm", choices=tuple(CANDIDATE_ARMS), default="mixture")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


def load_sidecar(directory: Path, name: str, handoff: PhaseCComponentHandoff) -> pd.DataFrame:
    """Read one arm's sidecar, verify it against the manifest, and attach the realized targets.

    Returns only the rows that appeared and sit on the ``component_model`` route, keyed like
    the table.
    """

    manifest = json.loads((directory / f"{name}.manifest.json").read_text(encoding="utf-8"))
    estimator = manifest.get("estimator") if isinstance(manifest, dict) else None
    declaration = estimator.get("distribution_sidecar") if isinstance(estimator, dict) else None
    if not isinstance(declaration, dict):
        raise EvaluationValidationError(
            f"Arm {name!r} declares no distribution sidecar; its estimator writes no distribution."
        )
    path = directory / str(declaration["path"])
    if not path.is_file():
        raise EvaluationValidationError(f"Sidecar {path} is missing.")
    digest = compute_table_sha256(path)
    if digest != str(declaration["sha256"]):
        raise EvaluationValidationError(f"Sidecar {path.name} does not match its manifest digest.")
    sidecar = pd.read_csv(path, dtype={"season": "string", "fold_id": "string"})
    expected = [*KEY_COLUMNS, *DISTRIBUTION_COLUMNS]
    if list(sidecar.columns) != expected:
        raise EvaluationValidationError(f"Sidecar {path.name} does not carry {expected!r}.")
    if len(sidecar) != int(declaration["row_count"]):
        raise EvaluationValidationError(f"Sidecar {path.name} row count differs from its manifest.")
    rows = handoff.rows.loc[:, [*KEY_COLUMNS, *TARGET_COLUMNS]].copy(deep=True)
    rows["season"] = rows["season"].astype("string")
    rows["fold_id"] = rows["fold_id"].astype("string")
    for column in ("target_gameweek", "player_id"):
        rows[column] = pd.to_numeric(rows[column], errors="raise").astype("int64")
        sidecar[column] = pd.to_numeric(sidecar[column], errors="raise").astype("int64")
    joined = sidecar.merge(rows, on=list(KEY_COLUMNS), how="inner", validate="one_to_one")
    if len(joined) != len(sidecar):
        raise EvaluationValidationError(
            f"{len(sidecar) - len(joined)} sidecar row(s) of {name!r} have no table row."
        )
    appeared = pd.to_numeric(joined["appearance_target"], errors="coerce") == 1
    modelled = joined["composition_route"].astype("string") == "component_model"
    kept = joined.loc[appeared & modelled].reset_index(drop=True)
    return kept


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    artifact_dir: Path = arguments.artifact_dir
    candidate_arm = str(arguments.candidate_arm)
    arm = CANDIDATE_ARMS[candidate_arm]
    candidate_name = str(arm["table"]) if arguments.candidate is None else str(arguments.candidate)
    output_dir: Path = (
        artifact_dir / f"comparison_{candidate_arm}"
        if arguments.output_dir is None
        else arguments.output_dir
    )
    try:
        control = load_arm(artifact_dir, str(arguments.control))
        candidate = load_arm(artifact_dir, candidate_name)
        check_paired(control, candidate, candidate_arm=candidate_arm)
        control_rows = load_sidecar(artifact_dir, str(arguments.control), control)
        candidate_rows = load_sidecar(artifact_dir, candidate_name, candidate)
        keys = list(KEY_COLUMNS)
        common = control_rows.loc[:, keys].merge(candidate_rows.loc[:, keys], on=keys, how="inner")
        control_rows = (
            control_rows.merge(common, on=keys, how="inner")
            .sort_values(keys)
            .reset_index(drop=True)
        )
        candidate_rows = (
            candidate_rows.merge(common, on=keys, how="inner")
            .sort_values(keys)
            .reset_index(drop=True)
        )
        report = score_arms(
            control_rows,
            candidate_rows,
            primary_season=PRIMARY_SEASON,
            control_era_season=CONTROL_ERA_SEASON,
            candidate_id=f"{arm['candidate_id']}_distribution",
            policy=POLICY,
        )
    except EvaluationValidationError as error:
        print(f"Distribution scoring refused: {error}")
        return 1

    report.update(
        {
            "candidate_arm": candidate_arm,
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "development_only": True,
            "promotes_anything": False,
            "enters_points_mae_rule": False,
            "primary_season_label": PRIMARY_SEASON,
            "control_era_season_label": CONTROL_ERA_SEASON,
            "policy": {
                "confidence_level": POLICY.confidence_level,
                "bootstrap_resamples": POLICY.bootstrap_resamples,
                "moving_block_length": POLICY.moving_block_length,
                "deterministic_seed": POLICY.deterministic_seed,
            },
            "scored_rows_rule": (
                "rows with appearance_target == 1 on the component_model route in both arms, "
                "present in both sidecars"
            ),
            "arms": {
                "control": {
                    "name": str(arguments.control),
                    "model_version": control.model_version,
                    "repository_commit": control.repository_commit,
                    "table_sha256": control.table_sha256,
                    "scored_rows": len(control_rows),
                },
                "candidate": {
                    "name": candidate_name,
                    "model_version": candidate.model_version,
                    "repository_commit": candidate.repository_commit,
                    "table_sha256": candidate.table_sha256,
                    "scored_rows": len(candidate_rows),
                },
            },
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "distribution_scoring.json"
    markdown_path = output_dir / "distribution_scoring.md"
    write_json(json_path, report)
    write_text(
        markdown_path,
        render_markdown(
            report,
            title=f"Phase C v2 distribution scoring: {candidate_arm} candidate against the control",
            lines_before=[
                f"Control `{arguments.control}` ({control.model_version}), candidate "
                f"`{candidate_name}` ({candidate.model_version}), both at commit "
                f"`{control.repository_commit[:8]}`; {len(control_rows)} scored rows; "
                f"generated {report['generated_at_utc']}. Development reading, 2025-26 read as "
                "development data; nothing here enters the points-MAE rule or promotes anything.",
            ],
        ),
    )
    components = report["components"]
    print(f"Wrote {json_path}")
    print(f"      {markdown_path}")
    if isinstance(components, dict):
        for component, block in components.items():
            if isinstance(block, dict):
                print(f"  {component:<8} reading   {block['reading']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
