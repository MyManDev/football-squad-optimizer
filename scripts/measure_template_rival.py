"""How strong is the crowd? The ownership template, scored on what actually happened.

    python -m scripts.measure_template_rival

Every rank measurement so far has played against the fold's own risk-neutral squad — an
opponent nobody actually fields. The competitive modes will play against the *crowd*: the
most-owned legal eleven, built each week from the ownership figures the platform publishes.
Before any mode is priced against that rival, this measures who the rival is: how it scores
against the risk-neutral squad on realized points, week by week, over a season of folds.

Descriptive measurement only: no gate, because nothing is promoted on this evidence — it is
the context the mode price list is read in. The locked holdout is never read.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.control_residuals import build_control_residual_table
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.residual_signal_scan import load_enrichment_rows
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.scenarios.rivals import (
    TEMPLATE_RIVAL_CONTRACT_VERSION,
    template_rival_from_ownership,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "template_rival_strength.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "template_rival_strength.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    season = str(arguments.season)
    if season == "2025-26":
        print("2025-26 is the locked holdout and may not be read.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")

    LOGGER.info("Building the control's residual folds")
    panel = build_panel(arguments.archive_root)
    residuals = build_control_residual_table(panel, PolicyObjectiveConfig())
    folds = residuals.loc[residuals["season"] == season]
    if folds.empty:
        print(f"No folds for {season}.")
        return 1
    ownership = load_enrichment_rows(arguments.archive_root, (season,))
    ownership = ownership.loc[:, ["season", "gameweek", "player_id", "selected"]]
    prices = panel.loc[panel["season"] == season, ["gameweek", "player_id", "price_tenths", "name"]]

    optimization = OptimizationConfig()
    rows: list[dict[str, object]] = []
    skipped: list[str] = []
    for fold_id, block in folds.groupby("fold_id", sort=True):
        gameweek = int(block["gameweek"].iloc[0])
        pool = block.merge(
            ownership.loc[ownership["gameweek"] == gameweek, ["player_id", "selected"]],
            on="player_id",
            how="left",
        ).merge(
            prices.loc[prices["gameweek"] == gameweek, ["player_id", "price_tenths", "name"]],
            on="player_id",
            how="left",
        )
        pool["ownership"] = pool["selected"].fillna(0.0)
        try:
            rival = template_rival_from_ownership(
                pool.loc[:, ["player_id", "position", "ownership"]]
            )
        except Exception as error:
            skipped.append(f"{fold_id}: {error}")
            continue
        realized = dict(
            zip(
                (int(v) for v in pool["player_id"]),
                (float(v) for v in pool["realized_points"]),
                strict=True,
            )
        )
        template_score = float(
            sum(realized.get(int(str(p)), 0.0) for p in rival.starter_ids)
        ) + float(realized.get(int(str(rival.captain_id)), 0.0))

        projection = pool.loc[
            :, ["player_id", "name", "team_id", "position", "price_tenths"]
        ].copy()
        projection["expected_points"] = pool["predicted_points"].clip(lower=0.0)
        neutral = optimize_squad(projection, optimization)
        if not neutral.has_solution or neutral.captain is None:
            skipped.append(f"{fold_id}: risk-neutral squad infeasible")
            continue
        starters = [int(v) for v in neutral.starting_xi["player_id"]]
        captain = int(neutral.captain["player_id"])
        neutral_score = float(sum(realized.get(p, 0.0) for p in starters)) + float(
            realized.get(captain, 0.0)
        )
        overlap = len(set(starters) & {int(str(p)) for p in rival.starter_ids})
        rows.append(
            {
                "fold_id": str(fold_id),
                "gameweek": gameweek,
                "template_realized": template_score,
                "risk_neutral_realized": neutral_score,
                "difference": template_score - neutral_score,
                "shared_starters": overlap,
                "captain_shared": captain == int(str(rival.captain_id)),
            }
        )
        LOGGER.info(
            "%s template %.0f vs neutral %.0f (overlap %d)",
            fold_id,
            template_score,
            neutral_score,
            overlap,
        )

    if not rows:
        print("No fold could be measured.")
        return 1
    differences = np.array([row["difference"] for row in rows], dtype="float64")
    generator = np.random.default_rng(0)
    draws = np.array(
        [
            differences[generator.integers(0, differences.size, differences.size)].mean()
            for _ in range(20000)
        ]
    )
    summary = {
        "folds": len(rows),
        "template_mean": float(np.mean([row["template_realized"] for row in rows])),
        "risk_neutral_mean": float(np.mean([row["risk_neutral_realized"] for row in rows])),
        "mean_difference": float(differences.mean()),
        "difference_interval_90": [
            float(np.quantile(draws, 0.05)),
            float(np.quantile(draws, 0.95)),
        ],
        "template_ahead_share": float(np.mean(differences > 0.0)),
        "level_share": float(np.mean(differences == 0.0)),
        "mean_shared_starters": float(np.mean([row["shared_starters"] for row in rows])),
        "captain_shared_share": float(np.mean([row["captain_shared"] for row in rows])),
    }
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": TEMPLATE_RIVAL_CONTRACT_VERSION,
        "season": season,
        "summary": summary,
        "rows": rows,
        "skipped": skipped,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _to_markdown(document)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


def _to_markdown(document: dict[str, object]) -> str:
    summary = document["summary"]
    assert isinstance(summary, dict)
    low, high = summary["difference_interval_90"]
    lines = [
        "# The crowd as a rival: the ownership template, scored on what happened",
        "",
        f"- Contract `{document['contract_version']}`; season {document['season']}, "
        f"{summary['folds']} folds; the template is rebuilt each week from that week's "
        "ownership, captained by its most-owned starter (no captaincy share is published).",
        "- The comparison squad is the control's risk-neutral eleven for the same fold, both "
        "scored on realized points. Descriptive measurement — no gate, nothing promoted.",
        "",
        "| | Mean realized |",
        "| --- | ---: |",
        f"| Ownership template | {summary['template_mean']:.2f} |",
        f"| Risk-neutral squad | {summary['risk_neutral_mean']:.2f} |",
        "",
        f"- Template minus risk-neutral: **{summary['mean_difference']:+.2f}** per week, "
        f"90% interval [{low:+.2f}, {high:+.2f}].",
        f"- Template finishes ahead in {summary['template_ahead_share']:.0%} of weeks "
        f"(level {summary['level_share']:.0%}).",
        f"- The two elevens share {summary['mean_shared_starters']:.1f} starters on average; "
        f"the captain agrees {summary['captain_shared_share']:.0%} of the time.",
        "",
        "Reading: this is the opponent the competitive modes will actually be priced "
        "against. If the crowd is close to the risk-neutral squad, beating it costs little "
        "and the modes are cheap; if the crowd is strong, the price list must say so.",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
