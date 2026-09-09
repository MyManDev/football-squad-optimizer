"""Export the in-season blend's own out-of-sample residuals.

    python -m scripts.export_in_season_residuals

The live risk layer describes a squad's spread by calibrating on a residual history, and
#45 states the rule that makes such a description honest: the residuals must belong to the
model that is making the decision. Calibrating one model's intervals on another's describes
the spread of something that is not deciding anything.

A control residual history already exists (`scripts.export_control_residuals`,
`docs/control_residual_export.md`), and it carries `model_version = form_window_05_v1` --
the archive-fed control. From gameweek two the live decision is made by
`in-season-carry-over-v1` instead, reading only what a capture carries, so that export
cannot calibrate it. This produces the missing one.

No optimizer runs here. A residual is a projection against an outcome, one row per player
per fold, so this is a minute of work rather than the benchmark's hour of CP-SAT. The folds,
the panel cut and the projection come from `scripts.measure_in_season_blend` rather than
being rebuilt, so the residuals describe exactly the model that benchmark measured and the
producer will hand to a live decision.

The locked holdout is never read: the panel is cut to the development seasons before
anything reads a feature window.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, write_json, write_text
from scripts.measure_in_season_blend import (
    DEVELOPMENT_SEASONS,
    MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    _Inputs,
    _visible_panel,
)

from squadopt.backtest.splits import (
    BacktestConfigurationError,
    realized_points_at,
    walk_forward_decision_points,
)
from squadopt.data.sources.vaastav import ARCHIVE_COMMIT
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
    InSeasonBlendConfig,
)
from squadopt.preflight import (
    preflight_report_to_markdown,
    run_residual_export_preflight,
)

RESIDUAL_EXPORT_CONTRACT_VERSION: Final = "oos_residual_export_v1"
EVALUATION_OBJECTIVE_VERSION: Final = "single_gameweek_realized_squad_points_v1"
PREDICTED_POINTS_DECIMALS: Final = 9

# The regime this file claims. A different label from the control's, deliberately: the
# pairing rule refuses two exports claiming the same regime, and these are two regimes.
IN_SEASON_CANDIDATE_LABEL: Final = "in_season_carry_over_blend"

# The live decision carries the operational control's name; only the version distinguishes
# this path, which is why the name here is not this module's to choose either.
CONTROL_MODEL_NAME: Final = "squadopt-deterministic-baseline"

# Column order is fixed by docs/residual_export_contract.md.
RESIDUAL_COLUMNS: Final = (
    "fold_id",
    "season",
    "gameweek",
    "player_id",
    "team_id",
    "position",
    "predicted_points",
    "realized_points",
    "residual",
)

DEFAULT_TABLE_ROOT: Final = Path("artifacts/residuals")
DEFAULT_SUMMARY: Final = Path("docs/in_season_residual_export.md")


def build_residual_table(
    archive_root: Path, *, config: InSeasonBlendConfig | None = None
) -> pd.DataFrame:
    """Pair every fold's projection with the outcome read only after that decision."""

    settings = InSeasonBlendConfig() if config is None else config
    panel = _visible_panel(archive_root)
    decisions = walk_forward_decision_points(
        panel,
        seasons=DEVELOPMENT_SEASONS,
        min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    )
    if not decisions:
        raise BacktestConfigurationError("No decision points for the requested seasons.")

    inputs = _Inputs(panel, decisions)
    frames: list[pd.DataFrame] = []
    for decision in decisions:
        projection = inputs.blend(decision, settings)
        outcomes = realized_points_at(panel, decision)
        merged = projection.merge(outcomes, on="player_id", how="inner", validate="one_to_one")
        frame = pd.DataFrame(
            {
                "fold_id": decision.fold_id,
                "season": decision.season,
                "gameweek": decision.gameweek,
                "player_id": merged["player_id"],
                "team_id": merged["team_id"],
                "position": merged["position"],
                "predicted_points": merged["expected_points"].astype("float64"),
                "realized_points": merged["total_points"].astype("float64"),
            }
        )
        frame["residual"] = frame["realized_points"] - frame["predicted_points"]
        frames.append(frame)

    table = pd.concat(frames, ignore_index=True)
    table = table.sort_values(["season", "gameweek", "player_id"], kind="stable").reset_index(
        drop=True
    )
    _check(table)
    return table.loc[:, list(RESIDUAL_COLUMNS)]


def _check(table: pd.DataFrame) -> None:
    """Enforce the parts of the contract a wrong export would otherwise satisfy silently."""

    if table.empty:
        raise BacktestConfigurationError("The residual table is empty.")
    duplicated = table.duplicated(subset=["fold_id", "player_id"]).sum()
    if duplicated:
        raise BacktestConfigurationError(
            f"{duplicated} rows repeat a (fold_id, player_id) pair; the contract is one row each."
        )
    if (table["gameweek"] == 1).any():
        raise BacktestConfigurationError(
            "Opening gameweeks are present. This model needs a played gameweek, and the "
            "contract records whether they are included rather than letting them appear "
            "unnoticed."
        )
    if not bool(table["predicted_points"].notna().all()):
        raise BacktestConfigurationError("A predicted point is missing.")
    if float(table["predicted_points"].min()) < 0.0:
        raise BacktestConfigurationError("Predicted points must be non-negative.")
    residual_error = (
        table["residual"] - (table["realized_points"] - table["predicted_points"])
    ).abs()
    if float(residual_error.max()) > 1e-9:
        raise BacktestConfigurationError("residual must equal realized minus predicted.")


def manifest(
    table: pd.DataFrame, *, table_sha256: str, created_at_utc: str, repository_commit: str
) -> dict[str, object]:
    """Describe the export, in the shape the contract fixes."""

    return {
        "contract_version": RESIDUAL_EXPORT_CONTRACT_VERSION,
        "candidate_label": IN_SEASON_CANDIDATE_LABEL,
        "model_name": CONTROL_MODEL_NAME,
        "model_version": IN_SEASON_MODEL_VERSION,
        "feature_contract_version": IN_SEASON_FEATURE_CONTRACT_VERSION,
        "training_contract_version": IN_SEASON_MODEL_VERSION,
        "evaluation_objective": EVALUATION_OBJECTIVE_VERSION,
        "development_seasons": sorted({str(season) for season in table["season"]}),
        "opening_gameweeks_included": bool((table["gameweek"] == 1).any()),
        "fold_count": int(table["fold_id"].nunique()),
        "row_count": len(table),
        "repository_commit": repository_commit,
        "dataset_snapshot_id": ARCHIVE_COMMIT,
        "table_sha256": table_sha256,
        "created_at_utc": created_at_utc,
        "locked_holdout_accessed": False,
        "predicted_points_decimals": PREDICTED_POINTS_DECIMALS,
    }


def write_residual_table(table: pd.DataFrame, path: Path) -> None:
    """Serialize the byte-addressed export with the measured decimal rule."""

    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" prevents a second platform-specific translation. The checksum is
    # over these exact bytes, including the fixed nine-decimal float representation.
    with path.open("w", encoding="utf-8", newline="") as handle:
        table.to_csv(
            handle,
            index=False,
            lineterminator="\n",
            float_format=f"%.{PREDICTED_POINTS_DECIMALS}f",
        )


def summary(
    record: dict[str, object],
    table: pd.DataFrame,
    *,
    preflight_verdict: str = "not run",
    preflight_checks: int = 0,
    table_path: Path | None = None,
    manifest_path: Path | None = None,
) -> str:
    """Say what this export is for, and the one thing it must not be used for.

    The manifest travels inside this committed document, as the control export's
    record already does: a consumer that must name one export by fingerprint cannot
    do it from prose, and the table itself stays local.
    """

    residual = table["residual"]
    listed = record["development_seasons"]
    seasons = ", ".join(str(item) for item in listed) if isinstance(listed, list) else ""
    return "\n".join(
        [
            "# In-season blend residual export",
            "",
            f"Contract: `{record['contract_version']}`  ·  regime: `{record['candidate_label']}`",
            f"Identity: `{record['model_name']}` / `{record['model_version']}`",
            "",
            "The live risk layer describes a squad's spread by calibrating on a residual",
            "history, and that description is only honest if the residuals belong to the model",
            "making the decision. From gameweek two that model is",
            f"`{record['model_version']}`, and the control export already recorded carries",
            "`form_window_05_v1` -- the archive-fed control, a different model. This is the",
            "matching history for the one that decides.",
            "",
            "## What is in it",
            "",
            f"- **{record['row_count']:,} rows** across **{record['fold_count']} folds**, "
            f"seasons {seasons}.",
            "- One row per `(fold_id, player_id)`; every projection paired with the outcome",
            "  read only after that decision point.",
            f"- Residual mean {residual.mean():.4f}, standard deviation {residual.std():.4f}, "
            f"range {residual.min():.1f} to {residual.max():.1f}.",
            "",
            "## What it must not be used for",
            "",
            "**Opening gameweeks.** Every fold here is gameweek two or later, because the model",
            "needs a played gameweek to read. An opening decision is projected from carry-over",
            "and a price prior instead, and mid-season residuals do not describe that regime --",
            "assuming they do would produce a confident-looking interval with nothing behind",
            "it. The manifest states `opening_gameweeks_included: false` so a consumer can",
            "check rather than assume, and the export refuses to build if an opening gameweek",
            "appears.",
            "",
            "That refusal is the same answer the opening-week runbook already gives from the",
            "other side: a gameweek-one risk block is `not_requested`, and that is correct",
            "rather than missing.",
            "",
            "## What it does not decide",
            "",
            "Nothing on its own. It is an input a live decision may calibrate on once the",
            "wiring exists, not a claim that any interval is well calibrated. Whether these",
            "residuals produce honest coverage is a separate measurement.",
            "",
            "The locked holdout was not read: the panel is cut to the development seasons",
            "before anything reads a feature window.",
            "",
            "## Manifest",
            "",
            "```json",
            json.dumps(record, indent=2, sort_keys=True),
            "```",
            "",
            "## Preflight",
            "",
            f"- Verdict: {preflight_verdict} ({preflight_checks} checks)",
            f"- Table file: `{table_path.as_posix() if table_path else 'unknown'}` "
            "(local, not committed)",
            f"- Manifest file: `{manifest_path.as_posix() if manifest_path else 'unknown'}` "
            "(local, not committed)",
            "",
            "## Reproduction",
            "",
            "```powershell",
            r".venv\Scripts\python -m scripts.export_in_season_residuals",
            "```",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--table-root", type=Path, default=DEFAULT_TABLE_ROOT)
    parser.add_argument("--table-name", default="in_season_residuals")
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--repository-commit", default="")
    arguments = parser.parse_args()

    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    table = build_residual_table(arguments.archive_root)
    arguments.table_root.mkdir(parents=True, exist_ok=True)
    table_path = arguments.table_root / f"{arguments.table_name}.csv"
    write_residual_table(table, table_path)
    digest = hashlib.sha256(table_path.read_bytes()).hexdigest()

    record = manifest(
        table,
        table_sha256=digest,
        created_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        repository_commit=arguments.repository_commit,
    )
    manifest_path = arguments.table_root / f"{arguments.table_name}.manifest.json"
    write_json(manifest_path, record)

    report = run_residual_export_preflight(
        table, record, table_sha256=digest, artifact_label=table_path.name
    )
    print(preflight_report_to_markdown(report))
    if not report.passed:
        print("Preflight failed; the export does not satisfy its own contract.")
        return 1

    write_text(
        arguments.summary_output,
        summary(
            record,
            table,
            preflight_verdict="PASSED" if report.passed else "FAILED",
            preflight_checks=len(report.findings),
            table_path=table_path,
            manifest_path=manifest_path,
        ),
    )

    print(f"Rows        {record['row_count']:,} over {record['fold_count']} folds")
    print(f"Identity    {record['model_name']} / {record['model_version']}")
    print(f"Regime      {record['candidate_label']}")
    print(f"Opening GWs {record['opening_gameweeks_included']}")
    print(f"sha256      {digest}")
    print(f"Wrote {table_path}")
    print(f"Wrote {manifest_path}")
    print(f"Wrote {arguments.summary_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
