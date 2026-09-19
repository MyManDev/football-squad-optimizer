r"""Read where the level of the points forecast is off, over the development folds.

    python -m scripts.measure_projection_level_audit \
        --table artifacts/phase_c/phase_c_component_oof_v1.csv \
        --roster artifacts/phase_c/phase_c_decision_roster_v1.csv \
        --manifest artifacts/phase_c/phase_c_component_oof_v1.manifest.json

Protocol: ``docs/projection_level_audit_prereg.md``. Stage one only: descriptive, no candidate
is fitted and nothing is promoted. The table is the verified out-of-fold handoff of the model
the live system runs; the prior minutes come from the archive's own gameweek files. No solver
runs. The locked holdout is refused before anything is read, and the record is never
overwritten.
"""

import argparse
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, write_json, write_text

from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation.component_handoff import (
    HANDOFF_KEY,
    LOCKED_HOLDOUT_SEASON,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.projection_level import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    FIRST_TARGET_GAMEWEEK,
    FORECAST_BANDS,
    INTERVAL_LEVEL,
    PROJECTION_LEVEL_AUDIT_CONTRACT_VERSION,
    sign_agreement,
    summarise_level,
)

DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "projection_level_audit.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "projection_level_audit.md"
#: The digest `phase_c_component_evaluation` scored. A regenerated table may differ from it in
#: the last decimal of a few cells; the record says whether it did.
EVALUATED_TABLE_SHA256 = "b05f10c3fd3ab5058fe1ff720cc6ef0a4b1362a70a19dd979ad0eb0f47d12c01"
EVALUATED_ROWS = 101_447


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args(argv)


def prior_minutes_per_week(panel: pd.DataFrame, keys: pd.DataFrame) -> pd.Series:
    """Minutes a gameweek each row's player had played that season before its target gameweek.

    The divisor is the number of the season's gameweeks the archive holds before the target,
    the same for every player, as the live audit divides by the gameweeks the capture had
    scored. A player with no earlier row that season had played nothing in it, which is a
    stated nothing and not an absent figure: he was not in the game's files because he was
    not in the game.
    """

    minutes = panel.loc[:, ["season", "gameweek", "player_id", "minutes"]]
    paired = keys.loc[:, ["season", "target_gameweek", "player_id"]].reset_index()
    earlier = paired.merge(minutes, on=["season", "player_id"], how="left")
    earlier = earlier.loc[earlier["gameweek"] < earlier["target_gameweek"]]
    played = earlier.groupby("index")["minutes"].sum()
    weeks = panel.loc[:, ["season", "gameweek"]].drop_duplicates()
    before = paired.merge(weeks, on="season", how="left")
    before = before.loc[before["gameweek"] < before["target_gameweek"]]
    divisor = before.groupby("index")["gameweek"].nunique()
    total = played.reindex(keys.index, fill_value=0).astype(float)
    return total / divisor.reindex(keys.index).astype(float)


def level_table(rows: pd.DataFrame, roster: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """The handoff's rows in the audit's own columns, from the first gameweek it reads."""

    keyed = rows.merge(
        roster.loc[:, [*HANDOFF_KEY, "position"]], on=list(HANDOFF_KEY), validate="one_to_one"
    )
    keyed = keyed.loc[
        (keyed["fixture_count"] > 0) & (keyed["target_gameweek"] >= FIRST_TARGET_GAMEWEEK)
    ].reset_index(drop=True)
    return pd.DataFrame(
        {
            "season": keyed["season"].astype(str),
            "fold_id": keyed["fold_id"].astype(str),
            "player_id": keyed["player_id"].astype("int64"),
            "position": keyed["position"].astype(str),
            "forecast": keyed["control_expected_points"].astype(float),
            "realized": keyed["points_target"].astype(float),
            "appearance_forecast": keyed["appearance_probability"].astype(float),
            # The outcome of a row with no component forecast is not read against one.
            "appeared": keyed["appearance_target"]
            .astype(float)
            .where(keyed["appearance_probability"].notna()),
            "conditional_forecast": keyed["expected_points_if_appearance"].astype(float),
            "prior_minutes_per_week": prior_minutes_per_week(panel, keyed),
        }
    )


def _signed(value: object, places: int = 3) -> str:
    return f"{value:+.{places}f}" if isinstance(value, float) else "n/a"


def _interval(value: object) -> str:
    if not isinstance(value, list):
        return "n/a"
    return f"[{value[0]:+.3f}, {value[1]:+.3f}]"


def _rows(title: str, blocks: Mapping[str, Any]) -> list[str]:
    lines = [
        "",
        f"**{title}**",
        "",
        "| bucket | rows | forecast points | realized points | bias | 90% interval | "
        "who plays: bias | interval | when they play: bias | interval |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |",
    ]
    for label, block in blocks.items():
        if not block.get("rows"):
            lines.append(f"| {label} | 0 | | | | | | | | |")
            continue
        plays = block["who_plays"]
        scores = block["what_they_score_when_they_play"]
        lines.append(
            f"| {label} | {block['rows']} | {block['forecast_points']:.0f} | "
            f"{block['realized_points']:.0f} | {_signed(block['bias'])} | "
            f"{_interval(block['bias_interval'])} | {_signed(plays.get('bias'))} | "
            f"{_interval(plays.get('bias_interval'))} | {_signed(scores.get('bias'))} | "
            f"{_interval(scores.get('bias_interval'))} |"
        )
    return lines


def _markdown(record: Mapping[str, Any]) -> str:
    pooled = record["reading"]["pooled"]
    lines = [
        "# Projection level on the development folds",
        "",
        f"Contract `{record['contract_version']}`. Protocol: "
        "`docs/projection_level_audit_prereg.md`. Stage one: descriptive, nothing fitted, "
        "nothing promoted.",
        "",
        f"Table `{record['table_sha256'][:12]}` ({record['table_rows']} rows; "
        + (
            "the digest `phase_c_component_evaluation` scored"
            if record["table_is_the_evaluated_table"]
            else "not the digest `phase_c_component_evaluation` scored, see the JSON"
        )
        + f"), {pooled['rows']} rows read over {pooled['decisions']} decisions from target "
        f"gameweek {record['first_target_gameweek']}, blank rows left out "
        f"({record['rows_left_out_blank']}). Bias is realized minus forecast, so a positive "
        "bias is a forecast that ran low. Intervals resample decisions.",
    ]
    lines += _rows("By minutes a gameweek played before the decision", pooled["by_prior_minutes"])
    lines += _rows("By the size of the forecast", pooled["by_forecast_size"])
    lines += _rows("Each decision's top forty per position", pooled["top_per_position"])
    lines += [
        "",
        "## What stage two's rule says",
        "",
        "| split | bucket | pooled bias | interval off zero | seasons with the pooled sign | "
        "opens a candidate |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for verdict in record["stage_two_rule"]:
        lines.append(
            f"| {verdict['split']} | {verdict['bucket']} | {_signed(verdict['pooled_bias'])} | "
            f"{'yes' if verdict['pooled_interval_excludes_zero'] else 'no'} | "
            f"{verdict['seasons_with_the_pooled_sign']} of {verdict['seasons_read']} | "
            f"{'yes' if verdict['opens_a_candidate'] else 'no'} |"
        )
    for season, reading in record["reading"]["by_season"].items():
        lines += ["", f"## {season}"]
        lines += _rows(
            "By minutes a gameweek played before the decision", reading["by_prior_minutes"]
        )
        lines += _rows("By the size of the forecast", reading["by_forecast_size"])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    if arguments.json_output.exists():
        print(f"{arguments.json_output} exists; retire it in its own commit before re-running.")
        return 1
    handoff = read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    seasons = tuple(sorted(str(value) for value in handoff.rows["season"].unique()))
    if LOCKED_HOLDOUT_SEASON in seasons or handoff.development_contract is not None:
        print("Only the frozen v1 development handoff is read.")
        return 1
    panel = build_panel(arguments.archive_root, seasons=seasons)
    table = level_table(handoff.rows, handoff.roster, panel)
    reading = summarise_level(table)
    verdicts = [
        {"split": split, "bucket": bucket, **sign_agreement(reading, split, bucket)}
        for split, buckets in (
            ("by_prior_minutes", reading["pooled"]["by_prior_minutes"]),  # type: ignore[index]
            ("by_forecast_size", [label for label, _, _ in FORECAST_BANDS]),
        )
        for bucket in buckets
    ]
    in_scope = handoff.rows.loc[handoff.rows["target_gameweek"] >= FIRST_TARGET_GAMEWEEK]
    record: dict[str, Any] = {
        "contract_version": PROJECTION_LEVEL_AUDIT_CONTRACT_VERSION,
        "prereg": "docs/projection_level_audit_prereg.md",
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "descriptive_only": True,
        "operational_control_changed": False,
        "seasons": list(seasons),
        "locked_holdout_accessed": False,
        "table_sha256": handoff.table_sha256,
        "roster_sha256": handoff.roster_sha256,
        "manifest_sha256": handoff.manifest_sha256,
        "producer_repository_commit": handoff.repository_commit,
        "model_version": handoff.model_version,
        "table_rows": len(handoff.rows),
        "table_is_the_evaluated_table": handoff.table_sha256 == EVALUATED_TABLE_SHA256,
        "table_has_the_evaluated_row_count": len(handoff.rows) == EVALUATED_ROWS,
        "first_target_gameweek": FIRST_TARGET_GAMEWEEK,
        "rows_left_out_blank": int((in_scope["fixture_count"] <= 0).sum()),
        "interval": {
            "level": INTERVAL_LEVEL,
            "unit": "decision",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "reading": reading,
        "stage_two_rule": verdicts,
    }
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(_markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
