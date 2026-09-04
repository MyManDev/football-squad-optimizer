"""Assemble the play-mode price list from the three margin rehearsals, and apply the gate.

    python -m scripts.build_mode_price_list \
        --garantici <garantici.json> --agresif <agresif.json> --asiri <asiri.json>

The three inputs are `rank_objective_rehearsal_v2` artifacts, one per margin (-0.001, 0,
+5), each over the same 37 folds and four budgets. This script computes, per mode x budget,
the frequencies of finishing behind / level / ahead and the realized cost, bootstraps the
gate's separation difference over folds, and applies the gate declared in
`docs/mode_price_list_prereg.md` **as written, before any of these numbers existed**.
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scripts._experiment_cli import REPOSITORY_ROOT, artifact_metadata, write_json, write_text

LOGGER = logging.getLogger(__name__)

MODE_LABELS = {"garantici": "Garantici", "agresif": "Agresif", "asiri_agresif": "Asiri Agresif"}
BUDGET_ORDER = [0.0, 2.0, 4.0, None]


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--garantici", type=Path, required=True)
    parser.add_argument("--agresif", type=Path, required=True)
    parser.add_argument("--asiri", type=Path, required=True)
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "mode_price_list.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "mode_price_list.md"
    )
    return parser.parse_args()


def _rows(path: Path) -> list[dict[str, object]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document["rows"]
    assert isinstance(rows, list) and rows, f"{path} carries no rows"
    return rows


def _cell(rows: list[dict[str, object]], budget: float | None) -> dict[str, object]:
    sel = [r for r in rows if r["expected_points_budget"] == budget]
    gaps = np.array(
        [float(str(r["realized_score"])) - float(str(r["template_realized_score"])) for r in sel]
    )
    return {
        "folds": len(sel),
        "behind": float(np.mean(gaps < 0.0)),
        "level": float(np.mean(gaps == 0.0)),
        "ahead": float(np.mean(gaps > 0.0)),
        "ahead_by_more_than_five": float(np.mean(gaps > 5.0)),
        "mean_realized_cost": float(-gaps.mean()),
        "mean_claimed": float(np.mean([float(str(r["claimed_probability_ahead"])) for r in sel])),
        "proven_share": float(np.mean([r["solver_status"] == "OPTIMAL" for r in sel])),
    }


def _paired_behind_difference(
    garantici: list[dict[str, object]], agresif: list[dict[str, object]], budget: float | None
) -> dict[str, object]:
    """Fold-paired difference in the behind indicator, bootstrapped over folds."""

    def _behind_by_fold(rows: list[dict[str, object]]) -> dict[str, float]:
        return {
            str(r["fold_id"]): float(
                float(str(r["realized_score"])) < float(str(r["template_realized_score"]))
            )
            for r in rows
            if r["expected_points_budget"] == budget
        }

    left = _behind_by_fold(garantici)
    right = _behind_by_fold(agresif)
    shared = sorted(set(left) & set(right))
    paired = np.array([left[fold] - right[fold] for fold in shared])
    generator = np.random.default_rng(0)
    draws = np.array(
        [paired[generator.integers(0, paired.size, paired.size)].mean() for _ in range(20000)]
    )
    low, high = float(np.quantile(draws, 0.05)), float(np.quantile(draws, 0.95))
    return {
        "folds": len(shared),
        "mean_difference": float(paired.mean()),
        "interval_90": [low, high],
        "excludes_zero": bool(low > 0.0 or high < 0.0),
    }


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    inputs = {
        "garantici": _rows(arguments.garantici),
        "agresif": _rows(arguments.agresif),
        "asiri_agresif": _rows(arguments.asiri),
    }
    grid: dict[str, dict[str, dict[str, object]]] = {}
    for mode, rows in inputs.items():
        grid[mode] = {str(budget): _cell(rows, budget) for budget in BUDGET_ORDER}

    separation = _paired_behind_difference(inputs["garantici"], inputs["agresif"], 0.0)
    # The declared direction checks, pooled over budgets.
    pooled = {
        mode: {
            "behind": float(np.mean([grid[mode][str(b)]["behind"] for b in BUDGET_ORDER])),
            "ahead_by_more_than_five": float(
                np.mean([grid[mode][str(b)]["ahead_by_more_than_five"] for b in BUDGET_ORDER])
            ),
        }
        for mode in inputs
    }
    direction_garantici = pooled["garantici"]["behind"] == min(p["behind"] for p in pooled.values())
    direction_asiri = pooled["asiri_agresif"]["ahead_by_more_than_five"] == max(
        p["ahead_by_more_than_five"] for p in pooled.values()
    )
    honesty_pairs = [
        {
            "mode": mode,
            "budget": budget,
            "claimed": float(str(grid[mode][str(budget)]["mean_claimed"])),
            "realized_event_frequency": float(str(grid[mode][str(budget)]["ahead"])),
            "within_ten_points": bool(
                abs(
                    float(str(grid[mode][str(budget)]["mean_claimed"]))
                    - float(str(grid[mode][str(budget)]["ahead"]))
                )
                <= 0.10
            ),
        }
        for mode in inputs
        for budget in BUDGET_ORDER
    ]
    # The rehearsal's claimed probability is P(win under that mode's margin), so each
    # claim is read against the frequency of the event it actually claims: Garantici's
    # margin makes a level finish a win (ahead + level), Asiri Agresif's demands a win by
    # more than five (ahead_by_more_than_five), Agresif's is strictly ahead as stored.
    for pair in honesty_pairs:
        cell = grid[str(pair["mode"])][str(pair["budget"])]
        if pair["mode"] == "garantici":
            realized = float(str(cell["ahead"])) + float(str(cell["level"]))
        elif pair["mode"] == "asiri_agresif":
            realized = float(str(cell["ahead_by_more_than_five"]))
        else:
            realized = float(str(cell["ahead"]))
        pair["realized_event_frequency"] = realized
        pair["within_ten_points"] = bool(abs(pair["claimed"] - realized) <= 0.10)
    honesty = all(pair["within_ten_points"] for pair in honesty_pairs)

    verdict = {
        "separation_passes": bool(
            separation["excludes_zero"] and separation["mean_difference"] < 0.0
        ),
        "direction_garantici_passes": bool(direction_garantici),
        "direction_asiri_passes": bool(direction_asiri),
        "honesty_passes": bool(honesty),
    }
    verdict["passes"] = all(verdict.values())

    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": "mode_price_list_v1",
        "prereg": "docs/mode_price_list_prereg.md",
        "grid": grid,
        "pooled": pooled,
        "separation_garantici_vs_agresif_budget0": separation,
        "honesty_pairs": honesty_pairs,
        "verdict": verdict,
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
    grid = document["grid"]
    assert isinstance(grid, dict)
    verdict = document["verdict"]
    assert isinstance(verdict, dict)
    separation = document["separation_garantici_vs_agresif_budget0"]
    assert isinstance(separation, dict)
    lines = [
        "# The play-mode price list",
        "",
        "- Modes: **Garantici** (margin -0.001: a level finish counts), **Agresif** (margin 0:"
        " strictly ahead), **Asiri Agresif** (margin +5: clearly ahead). **Saf Puan** is the"
        " rival-independent expected-points mode and is the existing control, not re-measured"
        " here.",
        "- Same rehearsal throughout: 2024-25, 37 folds, 100 scenarios per fold,"
        " `held_out_half` claims, rival = the fold's risk-neutral squad. Gate declared in"
        " `docs/mode_price_list_prereg.md` before any number existed.",
        "",
        "| Mode | Budget | Behind | Level | Ahead | Ahead >5 | Realized cost | Claimed | Proven |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, cells in grid.items():
        for budget, cell in cells.items():
            lines.append(
                f"| {MODE_LABELS.get(mode, mode)} | {budget} | {cell['behind']:.2f} "
                f"| {cell['level']:.2f} | {cell['ahead']:.2f} "
                f"| {cell['ahead_by_more_than_five']:.2f} | {cell['mean_realized_cost']:+.2f} "
                f"| {cell['mean_claimed']:.2f} | {cell['proven_share']:.2f} |"
            )
    low, high = separation["interval_90"]
    lines += [
        "",
        "## The gate, as declared",
        "",
        f"- **Separation** (Garantici must finish behind less often than Agresif at budget 0, "
        f"fold-paired, interval clear of zero): difference "
        f"**{float(str(separation['mean_difference'])):+.3f}** [{low:+.3f}, {high:+.3f}] — "
        f"{'passes' if verdict['separation_passes'] else 'fails'}.",
        f"- **Direction, Garantici** (lowest pooled P(behind)): "
        f"{'passes' if verdict['direction_garantici_passes'] else 'fails'}.",
        f"- **Direction, Asiri Agresif** (highest pooled P(ahead by >5)): "
        f"{'passes' if verdict['direction_asiri_passes'] else 'fails'}.",
        f"- **Honesty** (each held-out claim within ten points of the frequency of the "
        f"event it claims: ahead+level for Garantici, ahead for Agresif, ahead-by-more-"
        f"than-five for Asiri Agresif): "
        f"{'passes' if verdict['honesty_passes'] else 'fails'}.",
        "",
        (
            "**The gate passes: the modes separate, each is best at what its name claims, "
            "and the claims are honest.** The selector ships on this evidence, priced "
            "against the synthetic rival; re-pricing against the ownership template is the "
            "recorded next step."
            if verdict["passes"]
            else "**The gate fails.** Per the pre-registration, the mode selector does not "
            "ship on this evidence; the failing clause above says what to revisit, and the "
            "bar is not moved after the fact."
        ),
        "",
        "Known instrument caveat, recorded in `rank_cost_calibration_note.md` and the "
        "budget-0 rounding note: at budget 0 the expected-points floor can round above the "
        "copy squad, so the Garantici budget-0 cell understates how safe the mode can be.",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
