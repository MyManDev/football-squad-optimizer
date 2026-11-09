"""Extract the walk-forward paper's tables and figure data from committed JSON records only.

Issue #1152 lets a model extract tables from the committed records and nothing more: no
section of the paper is drafted here. This runner reads JSON records under `docs/` as they are
checked out (the Phase C candidate comparisons, the S1 and S2 calibration records of the
component samplers and the two planning measurements the paper sits beside), fits nothing,
measures nothing and opens no network connection. Every number in a table or figure file is a
value of one record, the difference of two values of one record, or an arithmetic summary of
values of one record (an observation-weighted mean over seasons, a count of statuses, the
sample standard deviation of per-fold differences, the two IID precision formulas of the
instrument record and the repository's season-aware block bootstrap of per-fold differences
at three block lengths); the file names the record and the JSON pointer (RFC 6901) of each, a
derived cell's pointer starting with `derived:` and naming the pointers it combines, so any
cell can be checked against its record.

    python -m scripts.paper_record_tables
    python -m scripts.paper_record_tables --output-dir /some/folder/outside/the/checkout

The output directory (default `artifacts/paper_record_tables/`, git-ignored; inside the
checkout only a folder under `artifacts/` is accepted) receives:

- `records.csv`: every record read and, on the last row, this extractor itself (the file the
  run executes, under its path `scripts/paper_record_tables.py`), each with the SHA-256 and the
  git blob id of its bytes after CRLF is turned into LF (so a Windows checkout under
  `core.autocrlf` gives the same digests as any other), the commit checked out and whether the
  file read is the one committed there;
- `table_*.csv` and `tables.md`: the tables; `tables.md` names below its title the commit
  checked out (or "no commit read") and whether the extractor and every record read are the
  ones committed there, so a copy of it alone keeps that tie; Markdown rounds to six
  significant digits and shows a long statement up to its first semicolon, the CSV files carry
  the record's value unchanged;
- `provenance.csv`: one row per table cell read from a record, with its record and pointer;
- `figure_*.csv`: one row per plotted point, with the record and pointers on the row;
- `checks.csv`: arithmetic checks of each record against its own detail (a recorded mean
  against the mean of its folds or seeds, a recorded count against the count of its flags, a
  gate flag against its recorded bounds, a pooled error against its seasons) and, in a git
  checkout, of each record and of the extractor against the one committed at the checked-out
  commit, with the recomputed value beside the recorded one.

The exit status is 1 when a check fails, so also when a record read or the extractor run
differs from the one committed, and when a record is missing or lacks a key this file reads
(then nothing is written); it is 0 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import statistics
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
#: This extractor's path in a checkout, where the commit read at the root is asked for its blob.
EXTRACTOR = "scripts/paper_record_tables.py"
#: The file this run executes, read as a record is read and compared with that blob.
EXTRACTOR_SOURCE = Path(__file__).resolve()
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
SOLVER_BUDGET = "docs/research/phase_c_solver_budget_cards.json"


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


DECISION = "/decision_level_reading"


def _candidate(key: str, label: str, record: str, arm: str, prefix: str) -> Candidate:
    block = DECISION
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
_V2B = "/decision_level_reading/v2_minus_v1_features"

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


def git_blob_id(content: bytes) -> str:
    """The id git gives a blob of these bytes (what `git hash-object` prints for them)."""

    header = b"blob %d\0" % len(content)
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class Digest:
    """A record's bytes as read: SHA-256 and blob id after CRLF to LF, and the raw blob id."""

    sha256_lf: str
    blob_lf: str
    blob_raw: str

    @classmethod
    def of(cls, raw: bytes) -> Digest:
        lf = raw.replace(b"\r\n", b"\n")
        return cls(hashlib.sha256(lf).hexdigest(), git_blob_id(lf), git_blob_id(raw))


def _git(root: Path, *arguments: str) -> str | None:
    """One read-only git command in `root`; None when git is absent or the command fails."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def checked_out_commit(root: Path) -> str | None:
    """HEAD of `root` when `root` is the top of a git checkout with a commit, else None."""

    top = _git(root, "rev-parse", "--show-toplevel")
    if top is None or Path(top).resolve() != root.resolve():
        return None
    return _git(root, "rev-parse", "--verify", "--quiet", "HEAD")


class Records:
    """The committed JSON records under `<root>/docs`, read once each and never written."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._documents: dict[str, Any] = {}
        self.digests: dict[str, Digest] = {}

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
            self.digests[record] = Digest.of(raw)
        return self._documents[record]

    def cell(self, record: str, pointer: str) -> Cell:
        try:
            value = resolve(self.document(record), pointer)
        except KeyError as error:
            raise RecordError(f"{record}: no key {pointer} (missing {error})") from error
        return Cell(value, record, pointer)

    def optional(self, record: str, pointer: str) -> Cell | None:
        """The cell at `pointer`, or None when the record does not hold that key."""

        try:
            return Cell(resolve(self.document(record), pointer), record, pointer)
        except KeyError:
            return None

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
    """A table; `statements` are text columns that Markdown shows to their first semicolon."""

    name: str
    title: str
    columns: tuple[str, ...]
    rows: list[dict[str, Cell]]
    statements: tuple[str, ...] = ()


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
    if isinstance(value, list | dict):
        return json.dumps(value)
    return str(value)


def _shown(value: Any, statement: bool = False) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    text = _text(value)
    if statement and ";" in text:
        text = text.split(";", 1)[0] + "; ..."
    return text.replace("|", "\\|")


def _label(value: str) -> Cell:
    return Cell(value)


def player_level_table(records: Records) -> Table:
    columns = (
        "candidate",
        "reference_arm",
        "candidate_arm",
        "reference_fold_count",
        "reference_scored_fold_count",
        "candidate_fold_count",
        "candidate_scored_fold_count",
        "reference_points_observations",
        "candidate_points_observations",
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
            "primary_reference_points_mae": at("/comparison/primary_season/control_points_mae"),
            "primary_candidate_points_mae": at("/comparison/primary_season/candidate_points_mae"),
            "verdict": at("/comparison/verdict/verdict"),
        }
        for side, arm in (("reference", "control"), ("candidate", "candidate")):
            name = at(f"/comparison/arms/{arm}/name")
            manifest = f"/arm_manifests/{_escape(str(name.value))}"
            overall = f"/comparison/metrics/{arm}/overall"
            row[f"{side}_arm"] = name
            row[f"{side}_fold_count"] = at(f"{manifest}/fold_count")
            row[f"{side}_scored_fold_count"] = at(f"{manifest}/scored_fold_count")
            row[f"{side}_points_observations"] = at(f"{overall}/points/observations")
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
        "(pooled over the record's folds: the fold counts are each arm's manifest, the "
        "observations its pooled points rows; paired differences are reference MAE minus "
        "candidate MAE, so a positive value favours the candidate)",
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
        "added_after_result",
        "descriptive_only",
        "scope",
    )
    rows = []
    for candidate in CANDIDATES:
        at = partial(records.cell, candidate.record)
        linear, mine, tally = (
            candidate.linear_arm,
            candidate.candidate_arm,
            candidate.wins_ties_losses,
        )
        row = {
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
        # Whether the reading was declared with the rule or added after the result, in the
        # record's own words: the scope always, the two flags where the record carries them.
        for column in ("added_after_result", "descriptive_only"):
            flag = records.optional(candidate.record, f"{DECISION}/{column}")
            if flag is not None:
                row[column] = flag
        row["scope"] = at(f"{DECISION}/scope")
        rows.append(row)
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
        "evaluation of the linear components against the ridge control. The scope is the "
        "record's own statement of the reading, including whether it was declared with the "
        "rule or added after the result; added_after_result and descriptive_only are shown "
        "where the record carries them, and table_candidates_reading_status gives each "
        "record's declaration, scope and note in full",
        columns,
        rows,
        statements=("scope",),
    )


def reading_status_table(records: Records) -> Table:
    """When each decision-level reading was declared, in its record's words, in full."""

    columns = (
        "candidate",
        "declaration",
        "added_after_result",
        "descriptive_only",
        "scope",
        "note",
    )
    rows = []
    for candidate in CANDIDATES:
        row = {
            "candidate": _label(candidate.label),
            "declaration": records.cell(candidate.record, "/declaration"),
        }
        for column in columns[2:]:
            cell = records.optional(candidate.record, f"{DECISION}/{column}")
            if cell is not None:
                row[column] = cell
        row["scope"] = records.cell(candidate.record, f"{DECISION}/scope")
        rows.append(row)
    return Table(
        "table_candidates_reading_status",
        "The status of each candidate's decision-level reading as its record states it: the "
        "declaration document the record names, the two flags where the record carries them, "
        "and the reading's scope and note in full",
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
        "s1_bounds_low",
        "s1_bounds_high",
        "s1_within",
        "below_q10_count",
        "below_q10_rate",
        "s2_bounds_low",
        "s2_bounds_high",
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
            # The binding foundation record keeps only its pass flags; its bounds are in its
            # Markdown pre-registration, which this file does not read.
            row["s1_within"] = records.cell(record, "/verdict/s1_passes")
            row["s2_within"] = records.cell(record, "/verdict/s2_passes")
        else:
            for gate in ("s1", "s2"):
                row[f"{gate}_bounds_low"] = records.cell(record, f"{arm}/{gate}_bounds/0")
                row[f"{gate}_bounds_high"] = records.cell(record, f"{arm}/{gate}_bounds/1")
            row["s1_within"] = records.cell(record, f"{arm}/mean_pit_within_s1_bounds")
            row["s2_within"] = records.cell(record, f"{arm}/tail_rate_within_s2_bounds")
        rows.append(row)
    return Table(
        "table_sampler_calibration",
        "S1 (mean PIT) and S2 (share of folds realized below the scenario tenth percentile) "
        "of each sampler arm, with the bounds each record holds, as each record reads them; "
        "the binding foundation record holds no bounds, only its pass flags",
        columns,
        rows,
    )


def sampler_gate_checks(records: Records) -> list[Check]:
    """Each arm's recorded S1 and S2 flags against its own value and bounds (both inclusive)."""

    checks = []
    gates = (
        ("s1", "mean_probability_integral_transform", "mean_pit_within_s1_bounds"),
        ("s2", "realized_below_lower_quantile_rate", "tail_rate_within_s2_bounds"),
    )
    for sampler, record, arm, _ in SAMPLER_ARMS:
        if arm == "/verdict":
            continue
        for gate, value, flag in gates:
            low = float(records.cell(record, f"{arm}/{gate}_bounds/0").value)
            high = float(records.cell(record, f"{arm}/{gate}_bounds/1").value)
            within = low <= float(records.cell(record, f"{arm}/{value}").value) <= high
            recorded = records.cell(record, f"{arm}/{flag}").value
            checks.append(
                Check(
                    f"{sampler} {arm}: recorded {gate.upper()} flag agrees with its value and "
                    "bounds",
                    record,
                    f"{arm}/{flag}",
                    recorded,
                    within,
                    recorded is within,
                )
            )
    return checks


SEEDS = "/seed_sensitivity_added_after_the_result"


def seed_table(records: Records) -> Table:
    columns = ("arm", "seed", "below_q10_count", "band_ceiling_count")
    rows = []
    for arm in records.keys(JOINT, f"{SEEDS}/arms"):
        counts = f"{SEEDS}/arms/{_escape(arm)}/counts_by_seed"
        ceiling = records.cell(
            JOINT, f"{SEEDS}/plug_in_lower_tail_count/{_escape(arm)}/band_ceiling_count"
        )
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


def seed_summary_table(records: Records) -> Table:
    columns = (
        "arm",
        "min_count",
        "max_count",
        "mean_count",
        "band_ceiling_count",
        "seeds_within_s2_band",
        "seeds_within_s2_band_ids",
        "fixed_count_outside_the_redrawn_folds",
        "status",
    )
    rows = []
    for arm in records.keys(JOINT, f"{SEEDS}/arms"):
        at = f"{SEEDS}/arms/{_escape(arm)}"
        row = {"arm": _label(arm)}
        for column in columns[1:-1]:
            if column == "band_ceiling_count":
                pointer = f"{SEEDS}/plug_in_lower_tail_count/{_escape(arm)}/{column}"
            else:
                pointer = f"{at}/{column}"
            row[column] = records.cell(JOINT, pointer)
        row["status"] = records.cell(JOINT, f"{SEEDS}/status")
        rows.append(row)
    return Table(
        "table_joint_sampler_seed_summary",
        "The seed reading of each arm as the joint sampler record summarises it: lower-tail "
        "counts over the redrawn seeds, the S2 band ceiling as a count, and the seeds whose "
        "count is within the band, with the record's status of the reading",
        columns,
        rows,
        statements=("status",),
    )


def seed_checks(records: Records) -> list[Check]:
    """Each arm's recorded seed summary against its counts by seed and its band ceiling.

    A seed is within the band when its count is at most the band ceiling count, the one edge
    of the S2 band the seed reading holds as a count.
    """

    checks = []
    for arm in records.keys(JOINT, f"{SEEDS}/arms"):
        at = f"{SEEDS}/arms/{_escape(arm)}"
        by_seed = records.cell(JOINT, f"{at}/counts_by_seed").value
        if not isinstance(by_seed, dict) or not by_seed:
            raise RecordError(f"{JOINT}: {at}/counts_by_seed is not a non-empty object")
        ceiling = records.cell(
            JOINT, f"{SEEDS}/plug_in_lower_tail_count/{_escape(arm)}/band_ceiling_count"
        ).value
        counts = [int(count) for count in by_seed.values()]
        within = [str(seed) for seed, count in by_seed.items() if int(count) <= int(ceiling)]
        expected: tuple[tuple[str, Any], ...] = (
            ("min_count", min(counts)),
            ("max_count", max(counts)),
            ("mean_count", statistics.fmean(counts)),
            ("seeds_within_s2_band", len(within)),
            ("seeds_within_s2_band_ids", within),
        )
        for key, recomputed in expected:
            recorded = records.cell(JOINT, f"{at}/{key}").value
            if isinstance(recomputed, float):
                holds = abs(float(recorded) - recomputed) <= FOLD_TOLERANCE
            else:
                holds = recorded == recomputed
            checks.append(
                Check(
                    f"seeds {arm}: recorded {key} equals its counts by seed",
                    JOINT,
                    f"{at}/{key}",
                    recorded,
                    recomputed,
                    holds,
                )
            )
    return checks


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


def pooled_mae_checks(records: Records) -> list[Check]:
    """Each arm's pooled points MAE and observations against its seasons."""

    checks = []
    for candidate in CANDIDATES:
        for arm in ("control", "candidate"):
            metrics = f"/comparison/metrics/{arm}"
            pooled = records.cell(candidate.record, f"{metrics}/overall/points/mean_absolute_error")
            count = records.cell(candidate.record, f"{metrics}/overall/points/observations")
            weighted = 0.0
            observations = 0
            for season in records.keys(candidate.record, f"{metrics}/by_season"):
                at = f"{metrics}/by_season/{_escape(season)}/points"
                n = int(records.cell(candidate.record, f"{at}/observations").value)
                mae = float(records.cell(candidate.record, f"{at}/mean_absolute_error").value)
                weighted += mae * n
                observations += n
            mean = weighted / observations if observations else float("nan")
            checks += [
                Check(
                    f"{candidate.key} {arm}: pooled points MAE equals the observation-weighted "
                    "mean of its seasons",
                    candidate.record,
                    pooled.pointer,
                    pooled.value,
                    mean,
                    abs(float(pooled.value) - mean) <= FOLD_TOLERANCE,
                ),
                Check(
                    f"{candidate.key} {arm}: pooled points observations equal the sum of its "
                    "seasons",
                    candidate.record,
                    count.pointer,
                    count.value,
                    observations,
                    count.value == observations,
                ),
            ]
    return checks


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


INSTRUMENT = "docs/measurement_instrument.json"
#: The precision block of the instrument record: the component arm against the ridge control.
INSTRUMENT_PRECISION = "/precision/covariates/0/unconditional_mean_precision"
#: Standard normal quantiles of the instrument record's IID formulas: a 90% half-width is
#: z(0.95) standard errors, a two-sided MDE at alpha 0.05 and power 0.8 is z(0.975) + z(0.8).
Z_90 = 1.6448536269514722
Z_MDE = 1.959963984540054 + 0.8416212335729143
#: A derived cell's pointer starts with this and then says which pointers it combines.
DERIVED = "derived: "

#: Where a record pairs the candidate at the decision level against the same reference its
#: player-level comparison uses, when that reference is not the linear arm: the wider feature
#: contract's reference is the boosted pair on v1 features at both levels.
SAME_REFERENCE_DECISION: dict[str, str] = {
    "feature_contract_v2": "/decision_level_reading/v2_minus_v1_features",
}


def _decision_reference(records: Records, candidate: Candidate) -> tuple[Cell, Cell, Cell]:
    """The decision mean and 90% interval against the candidate's player-level reference."""

    prefix = SAME_REFERENCE_DECISION.get(candidate.key)
    if prefix is None:
        mean, interval = candidate.mean, candidate.interval
    else:
        mean, interval = f"{prefix}/mean", f"{prefix}/interval_90"
    at = partial(records.cell, candidate.record)
    return at(mean), at(f"{interval}/0"), at(f"{interval}/1")


def _weighted_points_mae(records: Records, record: str, arm: str, seasons: Sequence[str]) -> Cell:
    """An arm's points MAE over `seasons`, each season weighted by its observations."""

    metrics = f"/comparison/metrics/{arm}/by_season"
    weighted = 0.0
    observations = 0
    for season in seasons:
        at = f"{metrics}/{_escape(season)}/points"
        count = int(records.cell(record, f"{at}/observations").value)
        weighted += float(records.cell(record, f"{at}/mean_absolute_error").value) * count
        observations += count
    if not observations:
        raise RecordError(f"{record}: no points observations over {', '.join(seasons)}")
    return Cell(
        weighted / observations,
        record,
        f"{DERIVED}observation-weighted mean over {','.join(seasons)} of "
        f"{metrics}/<season>/points/mean_absolute_error",
    )


def _season_points(
    records: Records, record: str, arm: str, seasons: Sequence[str]
) -> list[tuple[str, int, dict[str, float]]]:
    """Each season's points block: its pointer, observations and the three error metrics."""

    blocks = []
    for season in seasons:
        at = f"/comparison/metrics/{arm}/by_season/{_escape(season)}/points"
        count = int(records.cell(record, f"{at}/observations").value)
        values = {
            name: float(records.cell(record, f"{at}/{name}").value)
            for name in ("mean_absolute_error", "root_mean_squared_error", "mean_error")
        }
        blocks.append((at, count, values))
    if not sum(count for _, count, _ in blocks):
        raise RecordError(f"{record}: no points observations over {', '.join(seasons)}")
    return blocks


def _weighted_points_rmse(records: Records, record: str, arm: str, seasons: Sequence[str]) -> Cell:
    """An arm's points RMSE over `seasons`: the root of the observation-weighted mean of
    each season's squared RMSE, which is the RMSE over the seasons' rows together."""

    blocks = _season_points(records, record, arm, seasons)
    total = sum(count for _, count, _ in blocks)
    mean_square = sum(v["root_mean_squared_error"] ** 2 * n for _, n, v in blocks) / total
    return Cell(
        mean_square**0.5,
        record,
        f"{DERIVED}root of the observation-weighted mean of the squared "
        f"/comparison/metrics/{arm}/by_season/<season>/points/root_mean_squared_error over "
        f"{','.join(seasons)}",
    )


def _weighted_points_mean_error(
    records: Records, record: str, arm: str, seasons: Sequence[str]
) -> Cell:
    blocks = _season_points(records, record, arm, seasons)
    total = sum(count for _, count, _ in blocks)
    return Cell(
        sum(v["mean_error"] * n for _, n, v in blocks) / total,
        record,
        f"{DERIVED}observation-weighted mean over {','.join(seasons)} of "
        f"/comparison/metrics/{arm}/by_season/<season>/points/mean_error",
    )


def same_period_table(records: Records) -> Table:
    """Each candidate's accuracy and decision readings over the same seasons and reference."""

    columns = (
        "candidate",
        "reference_arm",
        "decision_seasons",
        "reference_decision_season_points_mae",
        "candidate_decision_season_points_mae",
        "decision_season_paired_difference",
        "reference_decision_season_points_rmse",
        "candidate_decision_season_points_rmse",
        "reference_decision_season_points_mean_error",
        "candidate_decision_season_points_mean_error",
        "reference_pooled_points_rmse",
        "candidate_pooled_points_rmse",
        "candidate_minus_reference_decision_mean",
        "interval_90_low",
        "interval_90_high",
    )
    rows = []
    for candidate in CANDIDATES:
        at = partial(records.cell, candidate.record)
        seasons = records.keys(candidate.record, candidate.by_season)
        reference, low, high = _decision_reference(records, candidate)
        control = _weighted_points_mae(records, candidate.record, "control", seasons)
        mine = _weighted_points_mae(records, candidate.record, "candidate", seasons)
        row = {
            "candidate": _label(candidate.label),
            "reference_arm": at("/comparison/arms/control/name"),
            "decision_seasons": _label(f"{seasons[0]} to {seasons[-1]}"),
            "reference_decision_season_points_mae": control,
            "candidate_decision_season_points_mae": mine,
            "decision_season_paired_difference": Cell(
                float(control.value) - float(mine.value),
                candidate.record,
                f"{DERIVED}reference minus candidate of the two weighted means",
            ),
            "candidate_minus_reference_decision_mean": reference,
            "interval_90_low": low,
            "interval_90_high": high,
        }
        for side, arm in (("reference", "control"), ("candidate", "candidate")):
            overall = f"/comparison/metrics/{arm}/overall/points"
            row[f"{side}_pooled_points_rmse"] = at(f"{overall}/root_mean_squared_error")
            row[f"{side}_decision_season_points_rmse"] = _weighted_points_rmse(
                records, candidate.record, arm, seasons
            )
            row[f"{side}_decision_season_points_mean_error"] = _weighted_points_mean_error(
                records, candidate.record, arm, seasons
            )
        rows.append(row)
    return Table(
        "table_candidates_same_period",
        "Each candidate against the reference arm of its own record on the seasons of the "
        "decision folds: the points MAE of both arms over those seasons (each recorded season "
        "weighted by its observations), the paired difference as reference minus candidate, "
        "both arms' points RMSE and mean error (prediction minus realized) over the same "
        "seasons, their pooled RMSE over every recorded season, and the decision reading "
        "against the same reference (the wider contract against the boosted pair at both "
        "levels)",
        columns,
        rows,
    )


def _fold_differences(records: Records, candidate: Candidate) -> list[tuple[str, float]]:
    candidate_folds = f"{candidate.candidate_arm}/folds"
    linear_folds = f"{candidate.linear_arm}/folds"
    return [
        (
            fold,
            float(records.cell(candidate.record, f"{candidate_folds}/{_escape(fold)}").value)
            - float(records.cell(candidate.record, f"{linear_folds}/{_escape(fold)}").value),
        )
        for fold in records.keys(candidate.record, candidate_folds)
    ]


def precision_table(records: Records) -> Table:
    """The IID precision diagnostics of each candidate's paired decision reading.

    The instrument record measured a 90% half-width and a minimal detectable effect for one
    comparison, the component arm against the ridge control, treating folds as independent.
    The same two formulas are applied here to each candidate's recorded per-fold differences,
    with the sample standard deviation, and the instrument row is read from its record so the
    formulas can be checked against it. Leave-one-season-out means are the mean of the other
    seasons' folds. All of it is descriptive: folds overlap in squads and weeks.
    """

    seasons = sorted(
        {
            fold[:7]
            for candidate in (*CANDIDATES, WIDER_VS_BOOSTED)
            for fold in records.keys(candidate.record, f"{candidate.candidate_arm}/folds")
        }
    )
    columns = (
        "comparison",
        "paired_folds",
        "mean",
        "standard_deviation",
        "iid_90_interval_half_width",
        "iid_mde_alpha_0_05_power_0_8",
        *(f"leave_out_{season}_mean" for season in seasons),
    )
    rows = []
    for candidate in (*CANDIDATES, WIDER_VS_BOOSTED):
        differences = _fold_differences(records, candidate)
        values = [value for _, value in differences]
        count = len(values)
        deviation = statistics.stdev(values) if count > 1 else float("nan")
        error = deviation / count**0.5
        folds = f"{candidate.candidate_arm}/folds/<fold> - {candidate.linear_arm}/folds/<fold>"
        label = (
            candidate.label
            if " vs " in candidate.label
            else f"{candidate.label} vs linear components"
        )
        row = {
            "comparison": _label(label),
            "paired_folds": records.cell(candidate.record, candidate.paired_folds),
            "mean": Cell(statistics.fmean(values), candidate.record, f"{DERIVED}mean of {folds}"),
            "standard_deviation": Cell(
                deviation, candidate.record, f"{DERIVED}sample standard deviation of {folds}"
            ),
            "iid_90_interval_half_width": Cell(
                Z_90 * error,
                candidate.record,
                f"{DERIVED}{Z_90:.6f} x standard deviation / sqrt(folds) of {folds}",
            ),
            "iid_mde_alpha_0_05_power_0_8": Cell(
                Z_MDE * error,
                candidate.record,
                f"{DERIVED}{Z_MDE:.6f} x standard deviation / sqrt(folds) of {folds}",
            ),
        }
        for season in seasons:
            rest = [value for fold, value in differences if fold[:7] != season]
            if rest:
                row[f"leave_out_{season}_mean"] = Cell(
                    statistics.fmean(rest),
                    candidate.record,
                    f"{DERIVED}mean of {folds} over the folds not in {season}",
                )
        rows.append(row)
    at = partial(records.cell, INSTRUMENT)
    rows.append(
        {
            "comparison": _label("Linear components vs ridge control (instrument record)"),
            "paired_folds": at(f"{INSTRUMENT_PRECISION}/folds"),
            "mean": at(f"{INSTRUMENT_PRECISION}/mean"),
            "standard_deviation": at(f"{INSTRUMENT_PRECISION}/standard_deviation"),
            "iid_90_interval_half_width": at(f"{INSTRUMENT_PRECISION}/iid_90_interval_half_width"),
            "iid_mde_alpha_0_05_power_0_8": at(
                f"{INSTRUMENT_PRECISION}/iid_mde_alpha_0_05_power_0_8"
            ),
        }
    )
    return Table(
        "table_candidates_precision",
        "IID precision diagnostics of each paired decision reading, by the two formulas of the "
        "instrument record (90% half-width z(0.95) x sd / sqrt(folds); two-sided MDE at alpha "
        "0.05 and power 0.8, (z(0.975) + z(0.8)) x sd / sqrt(folds)), with the sample standard "
        "deviation of the recorded per-fold differences, and the mean over the folds of the "
        "other seasons when one season is left out; the last row is the instrument record's "
        "own reading of the linear components against the ridge control. Folds overlap in "
        "squads and weeks, so these are descriptive approximations that ignore dependence, "
        "not bounds and not gates",
        columns,
        rows,
    )


def precision_checks(records: Records) -> list[Check]:
    """The instrument record's half-width and MDE against the formulas applied here."""

    at = partial(records.cell, INSTRUMENT)
    folds = int(at(f"{INSTRUMENT_PRECISION}/folds").value)
    deviation = float(at(f"{INSTRUMENT_PRECISION}/standard_deviation").value)
    error = deviation / folds**0.5
    checks = []
    for name, factor, column in (
        ("90% half-width", Z_90, "iid_90_interval_half_width"),
        ("MDE", Z_MDE, "iid_mde_alpha_0_05_power_0_8"),
    ):
        recorded = at(f"{INSTRUMENT_PRECISION}/{column}")
        checks.append(
            Check(
                f"instrument record: the {name} equals its IID formula on the recorded "
                "standard deviation and folds",
                INSTRUMENT,
                recorded.pointer,
                recorded.value,
                factor * error,
                abs(float(recorded.value) - factor * error) <= 1e-6,
            )
        )
    return checks


#: The wider contract against the boosted pair on v1 features: the same reference as its
#: player-level comparison, at the decision level.
WIDER_VS_BOOSTED = Candidate(
    key="feature_contract_v2_vs_boosted",
    label="Boosted pair, v2 feature contract vs boosted pair",
    record=FEATURES_V2,
    paired_folds=f"{_V2B}/paired_folds",
    mean=f"{_V2B}/mean",
    median=f"{_V2B}/median",
    interval=f"{_V2B}/interval_90",
    wins_ties_losses=f"{_V2B}/wins_ties_losses",
    by_season=f"{_V2B}/by_season_mean",
    candidate_arm="/decision_level_reading/arms/gbm_v2_features",
    linear_arm="/decision_level_reading/arms/gbm_v1_features",
)

#: The bootstrap of `squadopt.evaluation.statistics`, as the records describe it: moving blocks
#: within a season, a seed derived from a candidate id, percentile interval.
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 0
BOOTSTRAP_CONFIDENCE = 0.9
BLOCK_LENGTHS = (2, 4, 8)
#: The id this extractor seeds its own resamples with; a record's own id reproduces its
#: interval exactly where the record names one.
PAPER_BOOTSTRAP_ID = "paper_block_sensitivity"


def _bootstrap_seed(base_seed: int, candidate_id: str) -> int:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()
    return base_seed + int(digest[:8], 16)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def block_interval(
    differences: Sequence[tuple[str, float]], block_length: int, candidate_id: str
) -> tuple[float, float]:
    """The season-aware moving-block percentile interval of the repository's helper.

    `differences` pairs each fold's season with its paired difference, in fold order. Blocks
    are resampled within a season and never across one; the generator is seeded from the
    candidate id as the helper seeds it, so a record's own id reproduces its interval.
    """

    grouped: dict[str, list[int]] = {}
    for index, (season, _) in enumerate(differences):
        grouped.setdefault(season, []).append(index)
    generator = random.Random(_bootstrap_seed(BOOTSTRAP_SEED, candidate_id))
    means = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample: list[int] = []
        for season in sorted(grouped):
            indices = grouped[season]
            length = min(block_length, len(indices))
            starts = len(indices) - length + 1
            season_sample: list[int] = []
            while len(season_sample) < len(indices):
                start = generator.randrange(starts)
                season_sample.extend(indices[start : start + length])
            sample.extend(season_sample[: len(indices)])
        means.append(statistics.fmean(differences[index][1] for index in sample))
    alpha = (1.0 - BOOTSTRAP_CONFIDENCE) / 2.0
    return _percentile(means, alpha), _percentile(means, 1.0 - alpha)


def _recorded_bootstrap_id(records: Records, candidate: Candidate) -> Cell | None:
    """The bootstrap id a record names for this comparison, at whichever key it uses.

    The regime record keeps `interval_candidate_id` at the top of the reading, the mixture
    record `interval_method/candidate_id`, and the wider-contract record one id per
    comparison under `policy/candidate_ids`; the boosted-pair and points-only records name
    none.
    """

    block = candidate.mean.rsplit("/", 1)[0]
    for pointer in (
        f"{DECISION}/interval_candidate_id",
        f"{DECISION}/interval_method/candidate_id",
        f"{DECISION}/policy/candidate_ids/{_escape(block.rsplit('/', 1)[1])}",
    ):
        cell = records.optional(candidate.record, pointer)
        if cell is not None and isinstance(cell.value, str):
            return cell
    return None


def block_sensitivity_table(records: Records) -> tuple[Table, list[Check]]:
    """Each paired decision reading's interval at three block lengths, beside the recorded one."""

    columns = (
        "comparison",
        "paired_folds",
        "mean",
        "recorded_interval_low",
        "recorded_interval_high",
        "recorded_block_length",
        *(f"block_{length}_{side}" for length in BLOCK_LENGTHS for side in ("low", "high")),
        "bootstrap_id",
    )
    rows = []
    checks = []
    for candidate in (*CANDIDATES, WIDER_VS_BOOSTED):
        record = candidate.record
        differences = [(fold[:7], value) for fold, value in _fold_differences(records, candidate)]
        folds = f"{candidate.candidate_arm}/folds/<fold> - {candidate.linear_arm}/folds/<fold>"
        recorded_id = _recorded_bootstrap_id(records, candidate)
        bootstrap_id = str(recorded_id.value) if recorded_id is not None else PAPER_BOOTSTRAP_ID
        row = {
            "comparison": _label(candidate.label),
            "paired_folds": records.cell(record, candidate.paired_folds),
            "mean": Cell(
                statistics.fmean(value for _, value in differences),
                record,
                f"{DERIVED}mean of {folds}",
            ),
            "recorded_interval_low": records.cell(record, f"{candidate.interval}/0"),
            "recorded_interval_high": records.cell(record, f"{candidate.interval}/1"),
            "recorded_block_length": _label("4"),
        }
        for length in BLOCK_LENGTHS:
            low, high = block_interval(differences, length, bootstrap_id)
            pointer = (
                f"{DERIVED}season-aware moving-block bootstrap of {folds}: blocks of {length}, "
                f"{BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED} with id {bootstrap_id}, "
                f"{BOOTSTRAP_CONFIDENCE:.0%} percentile interval"
            )
            row[f"block_{length}_low"] = Cell(low, record, pointer)
            row[f"block_{length}_high"] = Cell(high, record, pointer)
            if length == 4 and recorded_id is not None:
                recorded = (
                    float(row["recorded_interval_low"].value),
                    float(row["recorded_interval_high"].value),
                )
                checks.append(
                    Check(
                        f"{candidate.key}: the recorded interval is reproduced at blocks of 4 "
                        "with the record's bootstrap id",
                        record,
                        candidate.interval,
                        list(recorded),
                        [low, high],
                        abs(recorded[0] - low) <= FOLD_TOLERANCE
                        and abs(recorded[1] - high) <= FOLD_TOLERANCE,
                    )
                )
        row["bootstrap_id"] = recorded_id if recorded_id is not None else _label(PAPER_BOOTSTRAP_ID)
        rows.append(row)
    table = Table(
        "table_candidates_block_sensitivity",
        "Sensitivity of each paired decision reading's 90% interval to the bootstrap block "
        "length: the recorded interval (blocks of 4) beside intervals recomputed here from the "
        "recorded per-fold differences at blocks of 2, 4 and 8 with the repository's "
        "season-aware moving-block procedure (5,000 resamples, seed 0). Where a record names "
        "its bootstrap id (the regime, mixture and wider-contract records) the block-4 interval "
        "reproduces the recorded one exactly and checks.csv says so; the boosted-pair and "
        "points-only records name none, so there the id is this extractor's own and the "
        "block-4 interval differs from the recorded one by the random stream alone",
        columns,
        rows,
    )
    return table, checks


def solver_status_table(records: Records) -> Table:
    """Solver status counts where a record holds them, and the split of one reading by status."""

    columns = (
        "record",
        "arm",
        "scope",
        "folds",
        "optimal",
        "feasible",
        "candidate_minus_linear_mean",
        "wins",
        "ties",
        "losses",
    )
    rows: list[dict[str, Cell]] = []
    frozen_folds = "/decision_comparison/folds"
    count = records.length(FROZEN_EVALUATION, frozen_folds)
    for arm, column in (
        ("component base", "component_solver_status"),
        ("ridge control", "control_solver_status"),
    ):
        statuses = [
            str(records.cell(FROZEN_EVALUATION, f"{frozen_folds}/{index}/{column}").value)
            for index in range(count)
        ]
        row = {
            "record": _label(FROZEN_EVALUATION),
            "arm": _label(arm),
            "scope": _label("frozen v1 evaluation, ten-second limit"),
            "folds": Cell(count, FROZEN_EVALUATION, f"{DERIVED}length of {frozen_folds}"),
        }
        for status in ("OPTIMAL", "FEASIBLE"):
            row[status.lower()] = Cell(
                statuses.count(status),
                FROZEN_EVALUATION,
                f"{DERIVED}count of {frozen_folds}/<fold>/{column} equal to {status}",
            )
        rows.append(row)
    arms = f"{DECISION}/arms"
    for arm, block in (
        ("linear components", f"{arms}/linear/component_solver_status_counts"),
        ("ridge control", f"{arms}/linear/ridge_control_solver_status_counts"),
        (
            "points-only boosting",
            f"{arms}/gradient_boosting_points/component_solver_status_counts",
        ),
    ):
        row = {
            "record": _label(GBM_POINTS),
            "arm": _label(arm),
            "scope": _label("decision folds, deterministic budget 5.0"),
            "folds": records.cell(GBM_POINTS, f"{DECISION}/paired_folds"),
        }
        for status in ("OPTIMAL", "FEASIBLE"):
            cell = records.optional(GBM_POINTS, f"{block}/{status}")
            row[status.lower()] = (
                cell
                if cell is not None
                else Cell(0, GBM_POINTS, f"{DERIVED}no {status} key under {block}")
            )
        rows.append(row)
    split = f"{DECISION}/added_after_the_result/by_linear_solver_status"
    for status in records.keys(GBM_POINTS, split):
        at = f"{split}/{_escape(status)}"
        rows.append(
            {
                "record": _label(GBM_POINTS),
                "arm": _label("points-only boosting minus linear components"),
                "scope": _label(f"folds the linear arm ended {status}, added after the result"),
                "folds": records.cell(GBM_POINTS, f"{at}/folds"),
                "candidate_minus_linear_mean": records.cell(
                    GBM_POINTS, f"{at}/candidate_minus_linear_mean"
                ),
                "wins": records.cell(GBM_POINTS, f"{at}/wins_ties_losses/0"),
                "ties": records.cell(GBM_POINTS, f"{at}/wins_ties_losses/1"),
                "losses": records.cell(GBM_POINTS, f"{at}/wins_ties_losses/2"),
            }
        )
    return Table(
        "table_solver_status",
        "Solver status of the decision solves where a record holds it: the frozen v1 evaluation "
        "(counted over its per-fold statuses) and the points-only boosting record (its per-arm "
        "counts, and its paired reading split by the linear arm's status). The boosted pair, "
        "wider contract, regime and mixture records hold no per-arm status counts",
        columns,
        rows,
    )


def sampler_season_table(records: Records) -> Table:
    columns = (
        "sampler",
        "record",
        "arm",
        "season",
        "fold_count",
        "mean_pit",
        "mean_pit_within_s1_bounds",
        "below_q10_count",
        "below_q10_rate",
        "tail_rate_within_s2_bounds",
    )
    rows = []
    for sampler, record, arm, _ in SAMPLER_ARMS:
        if arm == "/verdict":
            continue
        for season in records.keys(record, f"{arm}/seasons"):
            at = partial(records.cell, record)
            season_at = f"{arm}/seasons/{_escape(season)}"
            rows.append(
                {
                    "sampler": _label(sampler),
                    "record": _label(record),
                    "arm": _label(arm),
                    "season": _label(season),
                    "fold_count": at(f"{season_at}/fold_count"),
                    "mean_pit": at(f"{season_at}/mean_probability_integral_transform"),
                    "mean_pit_within_s1_bounds": at(f"{season_at}/mean_pit_within_s1_bounds"),
                    "below_q10_count": at(f"{season_at}/realized_below_lower_quantile_count"),
                    "below_q10_rate": at(f"{season_at}/realized_below_lower_quantile_rate"),
                    "tail_rate_within_s2_bounds": at(f"{season_at}/tail_rate_within_s2_bounds"),
                }
            )
    return Table(
        "table_sampler_calibration_by_season",
        "Season readings of every sampler arm whose record holds them (the binding foundation "
        "record holds pooled readings only): mean PIT and lower-tail count by season, with the "
        "record's own flags against the S1 and S2 bands, descriptive",
        columns,
        rows,
    )


def accuracy_against_decision(records: Records) -> list[dict[str, Cell]]:
    """One row per candidate: both arms' points MAE and observations by season, as recorded,
    and the decision reading against the same reference arm.

    The figure weights each season's MAE by its observations over the decision seasons (read
    from `figure_decision_by_season.csv`), so the accuracy and the decision axes cover the same
    folds and the same pair of arms."""

    rows = []
    for candidate in CANDIDATES:
        at = partial(records.cell, candidate.record)
        reference, low, high = _decision_reference(records, candidate)
        row = {
            "candidate": _label(candidate.label),
            "reference_arm": at("/comparison/arms/control/name"),
        }
        for side, arm in (("reference", "control"), ("candidate", "candidate")):
            metrics = f"/comparison/metrics/{arm}/by_season"
            for season in records.keys(candidate.record, metrics):
                season_at = f"{metrics}/{_escape(season)}/points"
                row[f"{side}_points_mae_{season}"] = at(f"{season_at}/mean_absolute_error")
                row[f"{side}_points_observations_{season}"] = at(f"{season_at}/observations")
        row["candidate_minus_reference_decision_mean"] = reference
        row["interval_90_low"] = low
        row["interval_90_high"] = high
        rows.append(row)
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
        if list(row) != columns:
            raise RecordError(f"{name}: a figure row must read the keys of the first row")
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


def _commit_line(commit: str | None, commit_checks: Sequence[Check]) -> str:
    """The commit the tables are tied to, and whether every file read is the committed one."""

    if commit is None:
        return (
            "Commit: no commit read (the root is not the top of a git checkout with a commit); "
            "`records.csv` gives the digest of the extractor and of every record read."
        )
    if all(check.holds for check in commit_checks):
        return (
            f"Commit: `{commit}`; the extractor and every record read are the ones committed there."
        )
    return (
        f"Commit: `{commit}`; the extractor or a record read is not the one committed there "
        "(`records.csv` names which), so these tables are not that commit's."
    )


def _markdown(tables: Sequence[Table], commit_line: str) -> str:
    lines = [
        "# Paper record tables",
        "",
        commit_line,
        "",
        "Extracted by `scripts/paper_record_tables.py` from committed JSON records; nothing was "
        "fitted or measured. Numbers are rounded to six significant digits here and a long "
        "statement is shown up to its first semicolon; the CSV files carry each record's value "
        "in full, `provenance.csv` names the record and JSON pointer of every cell, and "
        "`records.csv` the commit and digest of every record and of the extractor.",
    ]
    for table in tables:
        lines += ["", f"## {table.name}", "", table.title + ".", ""]
        lines.append("| " + " | ".join(table.columns) + " |")
        lines.append("|" + " --- |" * len(table.columns))
        for row in table.rows:
            cells = [
                _shown(row[column].value, column in table.statements) if column in row else ""
                for column in table.columns
            ]
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


def extractor_digest() -> Digest:
    """The bytes of the extractor this run executes, read as a record is read."""

    try:
        return Digest.of(EXTRACTOR_SOURCE.read_bytes())
    except OSError as error:
        raise RecordError(f"{EXTRACTOR}: the extractor run cannot be read ({error})") from error


#: The re-evaluated tables of the solver-budget record, with the label each row carries.
BUDGET_TABLES = (
    ("linear_dec", "linear components"),
    ("gbm_v1_dec", "boosted pair (v1 features)"),
    ("gbm_v2_dec", "wider contract (v2 features)"),
)
#: Its two paired readings, with the label each row carries.
BUDGET_PAIRS = (
    ("boosted_pair_vs_linear", "boosted pair minus linear components"),
    ("wider_contract_vs_boosted_pair", "wider contract minus boosted pair"),
)


def solver_budget_table(records: Records) -> tuple[Table, list[Check]]:
    """The solver-budget record: per re-evaluated table, how many of the recorded fold scores the
    rerun at the measurement budget reproduced when cards are ignored, the solver statuses of the
    folds that differ and of each rerun at each budget present, how many folds the official card
    rule moved; per table and arm, what the second budget changed against the first (squads,
    starting elevens, captains, objective, the gap to the bound the first budget left, realized
    score); per pair, the paired reading under the official rule and the squad overlap at each
    budget.

    Checks: the reproduced and differing folds of each table add up to the folds compared; at
    the second budget each arm's proven count in the budget block equals the one in its arm
    summary, and the budget block's mean score change times its folds equals the difference of
    the two arm means; a pair whose two tables the card rule left untouched has the same paired
    mean under both scoring conventions at each budget.
    """

    columns = (
        "comparison",
        "scope",
        "folds",
        "reproduced",
        "differing_feasible",
        "optimal",
        "feasible",
        "card_rule_folds_changed",
        "mean",
        "interval_low",
        "interval_high",
        "wins",
        "ties",
        "losses",
        "shared_squad_of_15",
        "shared_starters_of_11",
        "same_captain_folds",
        "identical_squad_folds",
        "tied_folds",
        "tied_identical_squads",
        "squad_changed",
        "xi_changed",
        "captain_changed",
        "objective_gain_mean",
        "objective_gain_max",
        "gap_to_bound_mean",
        "gap_to_bound_max",
        "score_change_folds",
        "score_change_mean",
        "proven_both",
        "proven_both_squad_changed",
    )
    at = partial(records.cell, SOLVER_BUDGET)
    budgets = [str(value) for value in at("/budgets_present").value]
    base = budgets[0]
    second = budgets[1] if len(budgets) > 1 else None

    def count(pointer: str, status: str) -> Cell:
        cell = records.optional(SOLVER_BUDGET, f"{pointer}/{status}")
        return cell or Cell(0, SOLVER_BUDGET, f"{DERIVED}no {status} key under {pointer}")

    def maybe(pointer: str, absent: str) -> Cell:
        cell = records.optional(SOLVER_BUDGET, pointer)
        if cell is None or cell.value is None:
            return Cell("", SOLVER_BUDGET, f"{DERIVED}{absent}")
        return cell

    rows: list[dict[str, Cell]] = []
    checks: list[Check] = []
    changed: dict[tuple[str, str], int] = {}
    arms = (("candidate", "{label}"), ("ridge_control", "ridge control beside the {label}"))
    for name, label in BUDGET_TABLES:
        block = f"/reproduction_at_5_0/{name}"
        compared = int(at(f"{block}/folds_compared").value)
        reproduced = int(at(f"{block}/folds_reproduced").value)
        differing = len(records.keys(SOLVER_BUDGET, f"{block}/folds_differing"))
        rows.append(
            {
                "comparison": _label(label),
                "scope": _label(f"rerun at deterministic budget {base} against its record"),
                "folds": at(f"{block}/folds_compared"),
                "reproduced": at(f"{block}/folds_reproduced"),
                "differing_feasible": count(f"{block}/differing_rerun_statuses", "FEASIBLE"),
                "optimal": at(f"{block}/rerun_statuses/OPTIMAL"),
                "feasible": count(f"{block}/rerun_statuses", "FEASIBLE"),
            }
        )
        checks.append(
            Check(
                f"{name}: the reproduced and differing folds add up to the folds compared",
                SOLVER_BUDGET,
                f"{block}/folds_compared",
                compared,
                reproduced + differing,
                compared == reproduced + differing,
            )
        )
        for budget in budgets:
            cards = at(f"/card_rule/{name}_b{budget}/folds_changed_by_the_card_rule")
            changed[(name, budget)] = int(cards.value)
            for arm, pattern in arms:
                summary = f"/arms/{name}_b{budget}/{arm}"
                rows.append(
                    {
                        "comparison": _label(pattern.format(label=label)),
                        "scope": _label(f"rerun at deterministic budget {budget}"),
                        "folds": at(f"{summary}/folds"),
                        "optimal": at(f"{summary}/statuses/OPTIMAL"),
                        "feasible": count(f"{summary}/statuses", "FEASIBLE"),
                        "card_rule_folds_changed": cards
                        if arm == "candidate"
                        else at(
                            f"/card_rule/{name}_b{budget}/ridge_control"
                            "/folds_changed_by_the_card_rule"
                        ),
                        "mean": at(f"{summary}/mean_realized_score"),
                    }
                )
        if second is None:
            continue
        for arm, pattern in arms:
            budget_block = f"/budget/{name}/{arm}"
            summary_low = f"/arms/{name}_b{base}/{arm}"
            summary_high = f"/arms/{name}_b{second}/{arm}"
            folds = int(at(f"{budget_block}/folds").value)
            rows.append(
                {
                    "comparison": _label(pattern.format(label=label)),
                    "scope": _label(f"from deterministic budget {base} to {second}"),
                    "folds": at(f"{budget_block}/folds"),
                    "optimal": at(f"{budget_block}/status_counts_high/OPTIMAL"),
                    "feasible": count(f"{budget_block}/status_counts_high", "FEASIBLE"),
                    "squad_changed": at(f"{budget_block}/squad_changed_folds"),
                    "xi_changed": at(f"{budget_block}/starting_xi_changed_folds"),
                    "captain_changed": at(f"{budget_block}/captain_changed_folds"),
                    "objective_gain_mean": maybe(
                        f"{budget_block}/objective_gain_mean", "no fold with both objectives"
                    ),
                    "objective_gain_max": maybe(
                        f"{budget_block}/objective_gain_max", "no fold with both objectives"
                    ),
                    "gap_to_bound_mean": maybe(
                        f"{budget_block}/low_budget_feasible_gap_to_bound_mean",
                        f"no unproven fold at budget {base}",
                    ),
                    "gap_to_bound_max": maybe(
                        f"{budget_block}/low_budget_feasible_gap_to_bound_max",
                        f"no unproven fold at budget {base}",
                    ),
                    "score_change_folds": at(f"{budget_block}/realized_score_change_folds"),
                    "score_change_mean": at(f"{budget_block}/realized_score_change_mean"),
                    "proven_both": at(f"{budget_block}/proven_at_both_budgets_folds"),
                    "proven_both_squad_changed": at(
                        f"{budget_block}/proven_at_both_budgets_squad_changed_folds"
                    ),
                }
            )
            proven_block = int(at(f"{budget_block}/status_counts_high/OPTIMAL").value)
            proven_summary = int(at(f"{summary_high}/statuses/OPTIMAL").value)
            checks.append(
                Check(
                    f"{name}/{arm}: the proven count at budget {second} is the same in the budget "
                    "block and the arm summary",
                    SOLVER_BUDGET,
                    f"{budget_block}/status_counts_high/OPTIMAL",
                    proven_block,
                    proven_summary,
                    proven_block == proven_summary,
                )
            )
            change_sum = float(at(f"{budget_block}/realized_score_change_mean").value) * folds
            mean_difference = (
                float(at(f"{summary_high}/mean_realized_score").value)
                - float(at(f"{summary_low}/mean_realized_score").value)
            ) * folds
            checks.append(
                Check(
                    f"{name}/{arm}: the mean score change from budget {base} to {second} times "
                    "the folds equals the difference of the two arm means times the folds",
                    SOLVER_BUDGET,
                    f"{budget_block}/realized_score_change_mean",
                    round(change_sum, 6),
                    round(mean_difference, 6),
                    abs(change_sum - mean_difference) < 1e-6,
                )
            )
    tables_of = {
        "boosted_pair_vs_linear": ("gbm_v1_dec", "linear_dec"),
        "wider_contract_vs_boosted_pair": ("gbm_v2_dec", "gbm_v1_dec"),
    }
    for pair, label in BUDGET_PAIRS:
        for budget in budgets:
            official = f"/pairs/{pair}/budget_{budget}_official_card_rule"
            ignoring = f"/pairs/{pair}/budget_{budget}_ignoring_cards"
            overlap = f"/pairs/{pair}/budget_{budget}_overlap"
            rows.append(
                {
                    "comparison": _label(label),
                    "scope": _label(f"paired at deterministic budget {budget}, official card rule"),
                    "folds": at(f"{official}/paired_folds"),
                    "mean": at(f"{official}/mean"),
                    "interval_low": at(f"{official}/interval_90/0"),
                    "interval_high": at(f"{official}/interval_90/1"),
                    "wins": at(f"{official}/wins_ties_losses/0"),
                    "ties": at(f"{official}/wins_ties_losses/1"),
                    "losses": at(f"{official}/wins_ties_losses/2"),
                    "shared_squad_of_15": at(f"{overlap}/mean_shared_squad_members_of_15"),
                    "shared_starters_of_11": at(f"{overlap}/mean_shared_starters_of_11"),
                    "same_captain_folds": at(f"{overlap}/same_captain_folds"),
                    "identical_squad_folds": at(f"{overlap}/identical_squad_folds"),
                    "tied_folds": at(f"{overlap}/tied_folds"),
                    "tied_identical_squads": at(f"{overlap}/tied_folds_with_identical_squads"),
                }
            )
            untouched = all(changed[(name, budget)] == 0 for name in tables_of[pair])
            same_mean = float(at(f"{official}/mean").value) == float(at(f"{ignoring}/mean").value)
            checks.append(
                Check(
                    f"{pair} at budget {budget}: with no fold moved by the card rule the paired "
                    "mean is the same under both scoring conventions",
                    SOLVER_BUDGET,
                    f"{official}/mean",
                    at(f"{official}/mean").value,
                    at(f"{ignoring}/mean").value,
                    same_mean if untouched else True,
                )
            )
    table = Table(
        "table_solver_budget_cards",
        "The solver-budget record: each re-evaluated table against its record (fold scores "
        "reproduced with cards ignored, the solver statuses of the differing folds), each arm's "
        "statuses, mean score and folds the official card rule moved at each budget, what the "
        "second budget changed against the first per arm, and each paired reading under the "
        "official rule with its squad overlap at each budget",
        columns,
        rows,
    )
    return table, checks


def commit_rows(
    records: Records, extractor: Digest, commit: str | None
) -> tuple[list[list[str]], list[Check]]:
    """`records.csv` rows, and in a git checkout one check per record and one for the extractor.

    A file read matches the commit when its blob id, after CRLF to LF or as read, is the one the
    commit holds at its path; a record or an extractor edited, regenerated or not committed
    fails. The extractor's row comes after the records, under its path in the checkout.
    """

    files = [(path, digest, "the record read") for path, digest in sorted(records.digests.items())]
    files.append((EXTRACTOR, extractor, "the extractor run"))
    rows: list[list[str]] = []
    checks: list[Check] = []
    for path, digest, subject in files:
        if commit is None:
            rows.append([path, digest.sha256_lf, digest.blob_lf, "", "", ""])
            continue
        committed = _git(records.root, "rev-parse", "--verify", "--quiet", f"{commit}:{path}")
        read = digest.blob_raw if committed == digest.blob_raw else digest.blob_lf
        holds = committed == read
        rows.append([path, digest.sha256_lf, digest.blob_lf, commit, committed or "", _text(holds)])
        checks.append(
            Check(
                f"{path}: {subject} is the one committed at the checked-out commit",
                path,
                "",
                committed or "",
                read,
                holds,
            )
        )
    return rows, checks


def extract(root: Path, output_dir: Path) -> tuple[list[Check], str | None]:
    """Write every table and figure file under `output_dir`.

    Returns the record checks and the commit checked out at `root` (None outside a checkout).
    """

    records = Records(root)
    tables = [
        player_level_table(records),
        decision_level_table(records),
        reading_status_table(records),
        sampler_table(records),
        seed_table(records),
        seed_summary_table(records),
        distribution_table(records),
        distribution_fold_table(records),
        planning_table(records),
        same_period_table(records),
        precision_table(records),
        solver_status_table(records),
        sampler_season_table(records),
    ]
    block_table, block_checks = block_sensitivity_table(records)
    tables.append(block_table)
    budget_table, budget_checks = solver_budget_table(records)
    tables.append(budget_table)
    fold_points, fold_checks = fold_differences(records)
    pit_points, pit_checks = sampler_folds(records)
    figures = {
        "figure_decision_fold_differences": fold_points,
        "figure_decision_by_season": decision_by_season(records),
        "figure_accuracy_against_decision": accuracy_against_decision(records),
        "figure_sampler_pit": pit_points,
    }
    checks = [
        *fold_checks,
        *pit_checks,
        *sampler_gate_checks(records),
        *seed_checks(records),
        *pooled_mae_checks(records),
        *precision_checks(records),
        *block_checks,
        *budget_checks,
    ]
    commit = checked_out_commit(records.root)
    digests, commit_checks = commit_rows(records, extractor_digest(), commit)
    checks += commit_checks

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
    files["tables.md"] = _markdown(tables, _commit_line(commit, commit_checks))
    files["records.csv"] = _csv(
        ("record", "sha256_lf", "git_blob_lf", "commit", "blob_at_commit", "matches_commit"),
        digests,
    )
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
    return checks, commit


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help=(
            "the checkout whose docs/ records are read and whose HEAD the records and this "
            "extractor are compared with (default: this one)"
        ),
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
        checks, commit = extract(root, output_dir)
    except RecordError as error:
        print(f"Paper record tables refused: {error}")
        return 1
    failed = [check for check in checks if not check.holds]
    print(f"Wrote the paper record tables to {output_dir}")
    if commit is None:
        print("  no git commit read at the root: records.csv names none to match")
    else:
        print(f"  records and the extractor compared with commit {commit}")
    print(f"  {len(checks) - len(failed)} of {len(checks)} record checks hold")
    for check in failed:
        where = " ".join(part for part in (check.record, check.pointer) if part)
        print(f"  FAILS: {check.name} ({where})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
