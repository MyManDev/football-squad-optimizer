"""Extract the walk-forward paper's tables and figure data from committed JSON records only.

Issue #1152 lets a model extract tables from the committed records and nothing more: no
section of the paper is drafted here. This runner reads JSON records under `docs/` as they are
checked out (the Phase C candidate comparisons, the S1 and S2 calibration records of the
component samplers and the two planning measurements the paper sits beside), fits nothing,
measures nothing and opens no network connection. Every number in a table or figure file is a
value of one record, or the difference of two values of one record, and the file names the
record and the JSON pointer (RFC 6901) of each, so any cell can be checked against its record.

    python -m scripts.paper_record_tables
    python -m scripts.paper_record_tables --output-dir /some/folder/outside/the/checkout

The output directory (default `artifacts/paper_record_tables/`, git-ignored; inside the
checkout only a folder under `artifacts/` is accepted) receives:

- `records.csv`: every record read, with the SHA-256 of its bytes, to match the reading to a
  commit;
- `table_*.csv` and `tables.md`: the tables; Markdown rounds to six significant digits, the CSV
  files carry the record's value unchanged;
- `provenance.csv`: one row per table cell read from a record, with its record and pointer;
- `figure_*.csv`: one row per plotted point, with the record and pointers on the row;
- `checks.csv`: arithmetic checks of each record against its own per-fold values (a recorded
  mean against the mean of its folds, a recorded count against the count of its fold flags),
  with the recomputed value beside the recorded one.

The exit status is 1 when a check fails, and when a record is missing or lacks a key this file
reads (then nothing is written); it is 0 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = "artifacts"
DEFAULT_OUTPUT = Path(OUTPUT_ROOT) / "paper_record_tables"
FOLD_TOLERANCE = 1e-9

GBM = "docs/research/phase_c_gradient_boosting_comparison.json"
FEATURES_V2 = "docs/research/phase_c_feature_contract_v2_comparison.json"
GBM_POINTS = "docs/research/phase_c_gradient_boosting_points_comparison.json"
REGIME = "docs/research/moe_regime.json"
MIXTURE = "docs/research/moe_mixture.json"
FROZEN_EVALUATION = "docs/phase_c_component_evaluation.json"
FOUNDATION = "docs/phase_d_component_squad_calibration.json"
BLOCK = "docs/research/team_match_block_sampler.json"
JOINT = "docs/research/moe_sampler.json"
RANK_SHRINKAGE = "docs/research/rank_conditional_shrinkage.json"
MEAN_REVERSION = "docs/research/mean_reversion_discount.json"


class RecordError(ValueError):
    """A record is missing, outside `docs/`, not JSON, or lacks a key this file reads."""


@dataclass(frozen=True)
class Cell:
    """One number or label, with the record and JSON pointer it was read from.

    A derived cell (a per-fold difference) names both pointers, joined by `` - ``.
    """

    value: Any
    record: str = ""
    pointer: str = ""


@dataclass(frozen=True)
class Candidate:
    """Where one Phase C candidate record keeps its decision-level reading."""

    key: str
    label: str
    record: str
    paired_folds: str
    mean: str
    median: str
    interval: str
    wins_ties_losses: str
    by_season: str
    candidate_arm: str
    linear_arm: str


def _candidate(key: str, label: str, record: str, arm: str, prefix: str) -> Candidate:
    block = "/decision_level_reading"
    return Candidate(
        key=key,
        label=label,
        record=record,
        paired_folds=f"{block}/paired_folds",
        mean=f"{block}/{prefix}_mean",
        median=f"{block}/{prefix}_median",
        interval=f"{block}/{prefix}_interval_90",
        wins_ties_losses=f"{block}/wins_ties_losses",
        by_season=f"{block}/by_season_mean",
        candidate_arm=f"{block}/arms/{arm}",
        linear_arm=f"{block}/arms/linear",
    )


_V2 = "/decision_level_reading/v2_features_minus_linear"

#: The five Phase C candidate records committed under docs/research, in the order they ran.
CANDIDATES: tuple[Candidate, ...] = (
    _candidate("boosted_pair", "Boosted pair", GBM, "gradient_boosting", "gbm_minus_linear"),
    Candidate(
        key="feature_contract_v2",
        label="Boosted pair, v2 feature contract",
        record=FEATURES_V2,
        paired_folds=f"{_V2}/paired_folds",
        mean=f"{_V2}/mean",
        median=f"{_V2}/median",
        interval=f"{_V2}/interval_90",
        wins_ties_losses=f"{_V2}/wins_ties_losses",
        by_season=f"{_V2}/by_season_mean",
        candidate_arm="/decision_level_reading/arms/gbm_v2_features",
        linear_arm="/decision_level_reading/arms/linear_v1_features",
    ),
    _candidate(
        "points_only_boosting",
        "Points-only boosting",
        GBM_POINTS,
        "gradient_boosting_points",
        "candidate_minus_linear",
    ),
    _candidate(
        "regime_gated_experts", "Regime-gated experts", REGIME, "regime", "candidate_minus_linear"
    ),
    _candidate("gated_mixture", "Gated mixture", MIXTURE, "mixture", "candidate_minus_linear"),
)

#: The sampler arms with an S1 and S2 reading: (sampler, record, arm pointer, folds pointer).
#: The binding foundation record keeps its reading under `verdict`; the two candidate records
#: keep one block per arm, and their per-fold rows hold the candidate at the top level.
SAMPLER_ARMS: tuple[tuple[str, str, str, str], ...] = (
    ("foundation", FOUNDATION, "/verdict", ""),
    ("foundation", BLOCK, "/control_arm", "/control_arm"),
    ("team_match_block", BLOCK, "/candidate_arm", ""),
    ("foundation", JOINT, "/control_arm", "/control_arm"),
    ("team_match_block", JOINT, "/block_arm", "/block_arm"),
    ("team_match_joint", JOINT, "/candidate_arm", ""),
)


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def resolve(document: Any, pointer: str) -> Any:
    """The value at an RFC 6901 JSON pointer; KeyError names the first token not found."""

    value = document
    if not pointer:
        return value
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    for raw in pointer[1:].split("/"):
        token = _unescape(raw)
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise KeyError(token)
    return value


class Records:
    """The committed JSON records under `<root>/docs`, read once each and never written."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._documents: dict[str, Any] = {}
        self.digests: dict[str, str] = {}

    def document(self, record: str) -> Any:
        if record not in self._documents:
            path = (self.root / record).resolve()
            docs = self.root / "docs"
            if path.suffix != ".json" or not path.is_relative_to(docs):
                raise RecordError(f"{record}: only JSON records under docs/ are read")
            if not path.is_file():
                raise RecordError(f"{record}: no such record")
            raw = path.read_bytes()
            try:
                self._documents[record] = json.loads(raw)
            except json.JSONDecodeError as error:
                raise RecordError(f"{record}: not JSON ({error})") from error
            self.digests[record] = hashlib.sha256(raw).hexdigest()
        return self._documents[record]

    def cell(self, record: str, pointer: str) -> Cell:
        try:
            value = resolve(self.document(record), pointer)
        except KeyError as error:
            raise RecordError(f"{record}: no key {pointer} (missing {error})") from error
        return Cell(value, record, pointer)

    def keys(self, record: str, pointer: str) -> list[str]:
        value = self.cell(record, pointer).value
        if not isinstance(value, dict):
            raise RecordError(f"{record}: {pointer} is not an object")
        return [str(key) for key in value]

    def length(self, record: str, pointer: str) -> int:
        value = self.cell(record, pointer).value
        if not isinstance(value, list):
            raise RecordError(f"{record}: {pointer} is not a list")
        return len(value)


@dataclass
class Table:
    name: str
    title: str
    columns: tuple[str, ...]
    rows: list[dict[str, Cell]]


@dataclass(frozen=True)
class Check:
    name: str
    record: str
    pointer: str
    recorded: Any
    recomputed: Any
    holds: bool


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _shown(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return _text(value)


def _label(value: str) -> Cell:
    return Cell(value)


def player_level_table(records: Records) -> Table:
    columns = (
        "candidate",
        "reference_arm",
        "reference_appearance_log_loss",
        "candidate_appearance_log_loss",
        "reference_minutes_mae",
        "candidate_minutes_mae",
        "reference_points_mae",
        "candidate_points_mae",
        "primary_season",
        "primary_reference_points_mae",
        "primary_candidate_points_mae",
        "primary_paired_difference",
        "primary_interval_low",
        "primary_interval_high",
        "control_era_season",
        "control_era_paired_difference",
        "control_era_interval_low",
        "control_era_interval_high",
        "verdict",
    )
    rows = []
    for candidate in CANDIDATES:
        at = partial(records.cell, candidate.record)
        row = {
            "candidate": _label(candidate.label),
            "reference_arm": at("/comparison/arms/control/name"),
            "primary_reference_points_mae": at("/comparison/primary_season/control_points_mae"),
            "primary_candidate_points_mae": at("/comparison/primary_season/candidate_points_mae"),
            "verdict": at("/comparison/verdict/verdict"),
        }
        for side, arm in (("reference", "control"), ("candidate", "candidate")):
            overall = f"/comparison/metrics/{arm}/overall"
            row[f"{side}_appearance_log_loss"] = at(f"{overall}/appearance/log_loss")
            row[f"{side}_minutes_mae"] = at(f"{overall}/minutes/mean_absolute_error")
            row[f"{side}_points_mae"] = at(f"{overall}/points/mean_absolute_error")
        for prefix, block in (("primary", "primary_season"), ("control_era", "control_era_season")):
            row[f"{prefix}_season"] = at(f"/comparison/{block}/season")
            row[f"{prefix}_paired_difference"] = at(f"/comparison/{block}/mean_paired_difference")
            row[f"{prefix}_interval_low"] = at(f"/comparison/{block}/interval_low")
            row[f"{prefix}_interval_high"] = at(f"/comparison/{block}/interval_high")
        rows.append(row)
    return Table(
        "table_candidates_player_level",
        "Player-level metrics of each candidate against the reference arm of its own record "
        "(pooled over the record's folds; paired differences are reference MAE minus candidate "
        "MAE, so a positive value favours the candidate)",
        columns,
        rows,
    )


def decision_level_table(records: Records) -> Table:
    columns = (
        "candidate",
        "paired_folds",
        "ridge_control_mean",
        "linear_component_mean",
        "candidate_component_mean",
        "linear_minus_ridge_mean",
        "candidate_minus_ridge_mean",
        "candidate_minus_linear_mean",
        "candidate_minus_linear_median",
        "interval_90_low",
        "interval_90_high",
        "wins",
        "ties",
        "losses",
    )
    rows = []
    for candidate in CANDIDATES:
        at = partial(records.cell, candidate.record)
        linear, mine, tally = (
            candidate.linear_arm,
            candidate.candidate_arm,
            candidate.wins_ties_losses,
        )
        rows.append(
            {
                "candidate": _label(candidate.label),
                "paired_folds": at(candidate.paired_folds),
                "ridge_control_mean": at(f"{linear}/ridge_control_mean"),
                "linear_component_mean": at(f"{linear}/component_mean"),
                "candidate_component_mean": at(f"{mine}/component_mean"),
                "linear_minus_ridge_mean": at(f"{linear}/diagnostics/mean_difference"),
                "candidate_minus_ridge_mean": at(f"{mine}/diagnostics/mean_difference"),
                "candidate_minus_linear_mean": at(candidate.mean),
                "candidate_minus_linear_median": at(candidate.median),
                "interval_90_low": at(f"{candidate.interval}/0"),
                "interval_90_high": at(f"{candidate.interval}/1"),
                "wins": at(f"{tally}/0"),
                "ties": at(f"{tally}/1"),
                "losses": at(f"{tally}/2"),
            }
        )
    frozen = partial(records.cell, FROZEN_EVALUATION)
    rows.append(
        {
            "candidate": _label("Linear components, frozen v1 evaluation"),
            "paired_folds": frozen("/decision_comparison/diagnostics/comparable_folds"),
            "ridge_control_mean": frozen("/decision_comparison/control/mean_realized_squad_points"),
            "linear_component_mean": frozen(
                "/decision_comparison/component_base/mean_realized_squad_points"
            ),
            "linear_minus_ridge_mean": frozen("/decision_comparison/diagnostics/mean_difference"),
        }
    )
    return Table(
        "table_candidates_decision_level",
        "Realized squad points a gameweek on the 147 frozen decision folds, each candidate's "
        "arm against the linear components of its own record; the last row is the frozen v1 "
        "evaluation of the linear components against the ridge control",
        columns,
        rows,
    )


def sampler_table(records: Records) -> Table:
    columns = (
        "sampler",
        "record",
        "arm",
        "fold_count",
        "mean_pit",
        "s1_within",
        "below_q10_count",
        "below_q10_rate",
        "s2_within",
    )
    names = {
        "fold_count": "fold_count",
        "mean_pit": "mean_probability_integral_transform",
        "below_q10_count": "realized_below_lower_quantile_count",
        "below_q10_rate": "realized_below_lower_quantile_rate",
    }
    rows = []
    for sampler, record, arm, _ in SAMPLER_ARMS:
        row = {"sampler": _label(sampler), "record": _label(record), "arm": _label(arm)}
        for column, key in names.items():
            row[column] = records.cell(record, f"{arm}/{key}")
        if arm == "/verdict":
            row["s1_within"] = records.cell(record, "/verdict/s1_passes")
            row["s2_within"] = records.cell(record, "/verdict/s2_passes")
        else:
            row["s1_within"] = records.cell(record, f"{arm}/mean_pit_within_s1_bounds")
            row["s2_within"] = records.cell(record, f"{arm}/tail_rate_within_s2_bounds")
        rows.append(row)
    return Table(
        "table_sampler_calibration",
        "S1 (mean PIT) and S2 (share of folds realized below the scenario tenth percentile) "
        "of each sampler arm, as each record reads them",
        columns,
        rows,
    )


def seed_table(records: Records) -> Table:
    base = "/seed_sensitivity_added_after_the_result"
    columns = ("arm", "seed", "below_q10_count", "band_ceiling_count")
    rows = []
    ceiling = records.cell(JOINT, f"{base}/plug_in_lower_tail_count/candidate/band_ceiling_count")
    for arm in records.keys(JOINT, f"{base}/arms"):
        counts = f"{base}/arms/{_escape(arm)}/counts_by_seed"
        for seed in records.keys(JOINT, counts):
            rows.append(
                {
                    "arm": _label(arm),
                    "seed": _label(seed),
                    "below_q10_count": records.cell(JOINT, f"{counts}/{_escape(seed)}"),
                    "band_ceiling_count": ceiling,
                }
            )
    return Table(
        "table_joint_sampler_seeds",
        "Lower-tail fold counts of the joint sampler and the block arm by scenario seed, a "
        "reading the record labels as added after the result",
        columns,
        rows,
    )


def distribution_table(records: Records) -> Table:
    base = "/distribution_scoring/components"
    columns = (
        "component",
        "arm",
        "mean_log_score",
        "mean_pit",
        "lower_tail_rate",
        "upper_tail_rate",
        "rows",
    )
    rows = []
    for component in records.keys(MIXTURE, base):
        for arm in ("control", "candidate"):
            pooled = f"{base}/{_escape(component)}/pooled/{arm}"
            row = {"component": _label(component), "arm": _label(arm)}
            for column in columns[2:]:
                row[column] = records.cell(MIXTURE, f"{pooled}/{column}")
            rows.append(row)
    return Table(
        "table_mixture_distribution",
        "Pooled predictive-distribution scores of the gated mixture and its control, on the "
        "rows that appeared (log score higher is better; tails are nominally 0.05 each)",
        columns,
        rows,
    )


def distribution_fold_table(records: Records) -> Table:
    base = "/distribution_scoring/components"
    columns: tuple[str, ...] = ("component", "season", "folds", "wins", "ties", "losses")
    columns += ("mean_difference", "interval_low", "interval_high")
    rows = []
    for component in records.keys(MIXTURE, base):
        for block in ("primary_season", "control_era_season"):
            at = f"{base}/{_escape(component)}/{block}"
            row = {"component": _label(component)}
            for column in columns[1:]:
                row[column] = records.cell(MIXTURE, f"{at}/{column}")
            rows.append(row)
    return Table(
        "table_mixture_log_score_folds",
        "Per-fold paired log-score differences of the gated mixture (candidate minus control) "
        "on the two seasons the record scores fold by fold",
        columns,
        rows,
    )


def planning_table(records: Records) -> Table:
    columns = (
        "measurement",
        "arm",
        "comparator",
        "paired_units",
        "mean_difference",
        "interval_90_low",
        "interval_90_high",
        "noise_floor",
        "status",
    )
    rows = []
    for block in ("primary_comparison", "secondary_comparison"):
        at = f"/{block}"
        rows.append(
            {
                "measurement": _label("rank_conditional_shrinkage"),
                "arm": records.cell(RANK_SHRINKAGE, f"{at}/arm"),
                "comparator": records.cell(RANK_SHRINKAGE, f"{at}/against"),
                "paired_units": records.cell(RANK_SHRINKAGE, f"{at}/paired_folds"),
                "mean_difference": records.cell(RANK_SHRINKAGE, f"{at}/mean_difference"),
                "interval_90_low": records.cell(RANK_SHRINKAGE, f"{at}/interval_90/0"),
                "interval_90_high": records.cell(RANK_SHRINKAGE, f"{at}/interval_90/1"),
                "noise_floor": records.cell(
                    RANK_SHRINKAGE, "/gate/noise_floor_points_per_gameweek"
                ),
                "status": records.cell(RANK_SHRINKAGE, "/verdict"),
            }
        )
    for index in range(records.length(MEAN_REVERSION, "/comparisons")):
        at = f"/comparisons/{index}"
        interval = f"{at}/weekly_advantage_block_bootstrap_interval"
        rows.append(
            {
                "measurement": _label("mean_reversion_discount"),
                "arm": records.cell(MEAN_REVERSION, f"{at}/variant"),
                "comparator": records.cell(MEAN_REVERSION, f"{at}/baseline"),
                "paired_units": records.cell(MEAN_REVERSION, f"{at}/paired_gameweeks"),
                "mean_difference": records.cell(
                    MEAN_REVERSION, f"{at}/mean_weekly_advantage_points"
                ),
                "interval_90_low": records.cell(MEAN_REVERSION, f"{interval}/0"),
                "interval_90_high": records.cell(MEAN_REVERSION, f"{interval}/1"),
                "noise_floor": records.cell(
                    MEAN_REVERSION, "/verdict/noise_floor_points_per_gameweek"
                ),
                "status": records.cell(MEAN_REVERSION, "/verdict/status"),
            }
        )
    return Table(
        "table_planning_measurements",
        "The two planning measurements beside the candidates: realized points a gameweek, arm "
        "minus its comparator, with each record's noise floor and status",
        columns,
        rows,
    )


def fold_differences(records: Records) -> tuple[list[dict[str, Cell]], list[Check]]:
    """Per-fold candidate minus linear scores, and each record's own arithmetic checked."""

    points: list[dict[str, Cell]] = []
    checks: list[Check] = []
    linear_reference: dict[str, Any] | None = None
    for candidate in CANDIDATES:
        record = candidate.record
        candidate_folds = f"{candidate.candidate_arm}/folds"
        linear_folds = f"{candidate.linear_arm}/folds"
        linear = records.cell(record, linear_folds).value
        differences: list[float] = []
        for fold in records.keys(record, candidate_folds):
            mine = records.cell(record, f"{candidate_folds}/{_escape(fold)}")
            theirs = records.cell(record, f"{linear_folds}/{_escape(fold)}")
            difference = float(mine.value) - float(theirs.value)
            differences.append(difference)
            points.append(
                {
                    "candidate": _label(candidate.label),
                    "fold_id": _label(fold),
                    "season": _label(fold[:7]),
                    "candidate_score": mine,
                    "linear_score": theirs,
                    "difference": Cell(difference, record, f"{mine.pointer} - {theirs.pointer}"),
                }
            )
        wins = sum(value > 0 for value in differences)
        ties = sum(value == 0 for value in differences)
        recorded_mean = records.cell(record, candidate.mean).value
        recorded_tally = records.cell(record, candidate.wins_ties_losses).value
        recorded_count = records.cell(record, candidate.paired_folds).value
        mean = sum(differences) / len(differences) if differences else float("nan")
        tally = [wins, ties, len(differences) - wins - ties]
        checks += [
            Check(
                f"{candidate.key}: recorded mean equals the mean of the fold differences",
                record,
                candidate.mean,
                recorded_mean,
                mean,
                abs(float(recorded_mean) - mean) <= FOLD_TOLERANCE,
            ),
            Check(
                f"{candidate.key}: recorded wins, ties and losses equal the fold tally",
                record,
                candidate.wins_ties_losses,
                recorded_tally,
                tally,
                list(recorded_tally) == tally,
            ),
            Check(
                f"{candidate.key}: recorded paired folds equal the folds of both arms",
                record,
                candidate.paired_folds,
                recorded_count,
                len(differences),
                recorded_count == len(differences) and len(linear) == len(differences),
            ),
        ]
        if linear_reference is None:
            linear_reference = linear
            continue
        checks.append(
            Check(
                f"{candidate.key}: linear arm folds equal the boosted pair record's linear arm",
                record,
                linear_folds,
                len(linear),
                len(linear_reference),
                linear == linear_reference,
            )
        )
    return points, checks


def sampler_folds(records: Records) -> tuple[list[dict[str, Cell]], list[Check]]:
    """Per-fold PIT and lower-tail flag of every sampler arm, and each arm's recount."""

    points: list[dict[str, Cell]] = []
    checks: list[Check] = []
    for sampler, record, arm, fold_arm in SAMPLER_ARMS:
        pits: list[float] = []
        flags = 0
        for index in range(records.length(record, "/folds")):
            fold = f"/folds/{index}"
            pit = records.cell(record, f"{fold}{fold_arm}/probability_integral_transform")
            below = records.cell(record, f"{fold}{fold_arm}/realized_below_q10")
            fold_id = str(records.cell(record, f"{fold}/fold_id").value)
            pits.append(float(pit.value))
            flags += bool(below.value)
            points.append(
                {
                    "sampler": _label(sampler),
                    "arm": _label(arm),
                    "fold_id": _label(fold_id),
                    "season": _label(fold_id[:7]),
                    "pit": pit,
                    "realized_below_q10": below,
                }
            )
        count = records.cell(record, f"{arm}/realized_below_lower_quantile_count").value
        mean_pit = records.cell(record, f"{arm}/mean_probability_integral_transform").value
        recomputed = sum(pits) / len(pits) if pits else float("nan")
        checks += [
            Check(
                f"{sampler} {arm}: recorded lower-tail count equals the count of fold flags",
                record,
                f"{arm}/realized_below_lower_quantile_count",
                count,
                flags,
                count == flags,
            ),
            Check(
                f"{sampler} {arm}: recorded mean PIT equals the mean of the fold PITs",
                record,
                f"{arm}/mean_probability_integral_transform",
                mean_pit,
                recomputed,
                abs(float(mean_pit) - recomputed) <= FOLD_TOLERANCE,
            ),
        ]
    return points, checks


def mae_against_decision(records: Records) -> list[dict[str, Cell]]:
    """One point per arm: points MAE pooled over every season of the comparison (2021-22 to
    2025-26) against squad points on the decision folds (2021-22 to 2024-25), as recorded."""

    first = CANDIDATES[0]
    points = [
        {
            "arm": _label("Linear components"),
            "points_mae_pooled_all_seasons": records.cell(
                first.record, "/comparison/metrics/control/overall/points/mean_absolute_error"
            ),
            "squad_points_decision_folds": records.cell(
                first.record, f"{first.linear_arm}/component_mean"
            ),
        }
    ]
    for candidate in CANDIDATES:
        points.append(
            {
                "arm": _label(candidate.label),
                "points_mae_pooled_all_seasons": records.cell(
                    candidate.record,
                    "/comparison/metrics/candidate/overall/points/mean_absolute_error",
                ),
                "squad_points_decision_folds": records.cell(
                    candidate.record, f"{candidate.candidate_arm}/component_mean"
                ),
            }
        )
    return points


def decision_by_season(records: Records) -> list[dict[str, Cell]]:
    rows = []
    for candidate in CANDIDATES:
        for season in records.keys(candidate.record, candidate.by_season):
            rows.append(
                {
                    "candidate": _label(candidate.label),
                    "season": _label(season),
                    "candidate_minus_linear_mean": records.cell(
                        candidate.record, f"{candidate.by_season}/{_escape(season)}"
                    ),
                }
            )
    return rows


def s2_counts(records: Records) -> list[dict[str, Cell]]:
    rows = []
    for sampler, record, arm, _ in SAMPLER_ARMS:
        scopes: list[tuple[str, str]] = [("pooled", arm)]
        if arm != "/verdict":
            scopes += [
                (season, f"{arm}/seasons/{_escape(season)}")
                for season in records.keys(record, f"{arm}/seasons")
            ]
        for scope, at in scopes:
            rows.append(
                {
                    "sampler": _label(sampler),
                    "arm": _label(arm),
                    "scope": _label(scope),
                    "fold_count": records.cell(record, f"{at}/fold_count"),
                    "below_q10_count": records.cell(
                        record, f"{at}/realized_below_lower_quantile_count"
                    ),
                }
            )
    return rows


def _csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _table_csv(rows: Iterable[dict[str, Cell]], columns: Sequence[str]) -> str:
    return _csv(
        columns,
        ([_text(row[column].value) if column in row else "" for column in columns] for row in rows),
    )


def _figure_csv(name: str, rows: list[dict[str, Cell]]) -> str:
    """One row per point: its values, then its record and the pointer of each value."""

    if not rows:
        raise RecordError(f"{name}: no rows to plot")
    columns = list(rows[0])
    sourced = [column for column in columns if rows[0][column].record]
    lines = []
    for row in rows:
        records = {row[column].record for column in sourced}
        if len(records) != 1:
            raise RecordError(f"{name}: a figure row must read one record, not {sorted(records)}")
        lines.append(
            [
                *(_text(row[column].value) for column in columns),
                records.pop(),
                *(row[column].pointer for column in sourced),
            ]
        )
    return _csv([*columns, "record", *(f"{column}_pointer" for column in sourced)], lines)


def _markdown(tables: Sequence[Table]) -> str:
    lines = [
        "# Paper record tables",
        "",
        "Extracted by `scripts/paper_record_tables.py` from committed JSON records; nothing was "
        "fitted or measured. Numbers are rounded to six significant digits here; the CSV files "
        "carry each record's value, and `provenance.csv` names the record and JSON pointer of "
        "every cell.",
    ]
    for table in tables:
        lines += ["", f"## {table.name}", "", table.title + ".", ""]
        lines.append("| " + " | ".join(table.columns) + " |")
        lines.append("|" + " --- |" * len(table.columns))
        for row in table.rows:
            cells = [_shown(row[column].value) if column in row else "" for column in table.columns]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _resolve_output(root: Path, output: Path | None) -> Path:
    """The output directory; inside the checkout it must sit under the ignored `artifacts/`."""

    root = root.resolve()
    directory = (root / (output or DEFAULT_OUTPUT)).resolve()
    allowed = root / OUTPUT_ROOT
    if directory.is_relative_to(root) and not directory.is_relative_to(allowed):
        raise RecordError(f"inside the checkout only {OUTPUT_ROOT}/ is written: {directory}")
    if directory == allowed:
        raise RecordError(f"name a folder under {OUTPUT_ROOT}/, not {OUTPUT_ROOT}/ itself")
    return directory


def extract(root: Path, output_dir: Path) -> list[Check]:
    """Write every table and figure file under `output_dir`; return the record checks."""

    records = Records(root)
    tables = [
        player_level_table(records),
        decision_level_table(records),
        sampler_table(records),
        seed_table(records),
        distribution_table(records),
        distribution_fold_table(records),
        planning_table(records),
    ]
    fold_points, fold_checks = fold_differences(records)
    pit_points, pit_checks = sampler_folds(records)
    figures = {
        "figure_decision_fold_differences": fold_points,
        "figure_decision_by_season": decision_by_season(records),
        "figure_points_mae_against_squad_points": mae_against_decision(records),
        "figure_sampler_pit": pit_points,
        "figure_s2_counts": s2_counts(records),
    }
    checks = fold_checks + pit_checks

    provenance: list[dict[str, Cell]] = [
        {
            "table": _label(table.name),
            "row": _label(str(index)),
            "column": _label(column),
            "value": cell,
            "record": _label(cell.record),
            "pointer": _label(cell.pointer),
        }
        for table in tables
        for index, row in enumerate(table.rows)
        for column, cell in row.items()
        if cell.record
    ]
    files = {f"{table.name}.csv": _table_csv(table.rows, table.columns) for table in tables}
    files["provenance.csv"] = _table_csv(
        provenance, ("table", "row", "column", "value", "record", "pointer")
    )
    files |= {f"{name}.csv": _figure_csv(name, rows) for name, rows in figures.items()}
    files["tables.md"] = _markdown(tables)
    files["records.csv"] = _csv(("record", "sha256"), sorted(records.digests.items()))
    files["checks.csv"] = _csv(
        ("check", "record", "pointer", "recorded", "recomputed", "holds"),
        (
            [
                check.name,
                check.record,
                check.pointer,
                json.dumps(check.recorded),
                json.dumps(check.recomputed),
                _text(check.holds),
            ]
            for check in checks
        ),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (output_dir / name).write_text(text, encoding="utf-8", newline="\n")
    return checks


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="the checkout whose docs/ records are read (default: this one)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"relative to --root unless absolute; default {DEFAULT_OUTPUT}",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    root: Path = arguments.root
    try:
        output_dir = _resolve_output(root, arguments.output_dir)
        checks = extract(root, output_dir)
    except RecordError as error:
        print(f"Paper record tables refused: {error}")
        return 1
    failed = [check for check in checks if not check.holds]
    print(f"Wrote the paper record tables to {output_dir}")
    print(f"  {len(checks) - len(failed)} of {len(checks)} record checks hold")
    for check in failed:
        print(f"  FAILS: {check.name} ({check.record} {check.pointer})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
