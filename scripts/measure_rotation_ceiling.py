"""Measure G0: what a perfect rotation signal would have been worth per decision.

    python -m scripts.measure_rotation_ceiling --dry-run
    python -m scripts.measure_rotation_ceiling

Executes gate G0 of ``docs/rotation_evidence_prereg.md`` on the pinned development
archive. Two arms differ by one thing: the oracle arm zeroes the expected points of every
player a perfect rotation signal would have flagged, after the projection and before the
solve. Both are scored under ``official_autosub_captain_v2``, paired fold by fold, and read
against the promotion policy's own ``min_mean_improvement``.

The oracle is hindsight by construction and the record says so. It is a ceiling: it bounds
what any reachable signal could be worth and says nothing about the signal this lane is
building. Nothing here promotes, pins or deploys anything, and the locked 2025-26 holdout
is not in the season list this run loads.
"""

import argparse
import hashlib
import json
import sys
import time
import warnings
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_text,
)

from squadopt.backtest import (
    BacktestConfigurationError,
    ProjectionBuilder,
    build_walk_forward_fold,
    build_walk_forward_folds,
    make_ridge_projection_builder,
    walk_forward_decision_points,
)
from squadopt.data import DataError
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationError,
    EvaluationFold,
    EvaluationResult,
    ScoringPolicy,
    evaluate_prepared_folds,
)
from squadopt.evaluation.rotation_ceiling import (
    ROTATION_CEILING_CONTRACT_VERSION,
    FoldDecisionDetail,
    OracleFlags,
    RotationCeilingComparison,
    RotationCeilingError,
    apply_rotation_exclusion,
    attach_realized_minutes,
    build_oracle_flags,
    compare_rotation_ceiling,
    fold_decision_details,
    fold_key,
)
from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.features import CrossSeasonConfig

#: The seasons this run loads. Passed to the loader rather than cut from a fuller panel:
#: the pre-registration says the locked holdout is "not loaded, not listed, not hashed and
#: not filtered", and filtering it out afterwards would already have read it. The archive
#: on disk does contain 2025-26 and 2026-27; neither is named here.
HISTORY_SEASONS: Final = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")

#: 2020-21 is history for the cross-season carry-over and produces no decision of its own.
DECISION_SEASONS: Final = HISTORY_SEASONS[1:]

#: Named so the check that it is absent can name it, and for no other purpose.
LOCKED_HOLDOUT_SEASON: Final = "2025-26"

#: The agreed development population. Asserted rather than reported so a run that produces
#: a different set of decisions fails loudly instead of quietly measuring something else.
EXPECTED_FOLD_COUNT: Final = 147

#: The existing paired-inference policy at its declared defaults. G0 reads
#: ``min_mean_improvement`` because a squad-points-per-decision gate is exactly what that
#: field is; no substitute threshold is invented here.
POLICY: Final = PromotionPolicy(
    min_mean_improvement=0.5,
    confidence_level=0.90,
    bootstrap_resamples=5000,
    moving_block_length=4,
    deterministic_seed=0,
)
CANDIDATE_ID: Final = "rotation-oracle-ceiling-vs-control"

DEFAULT_JSON_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "rotation_oracle_ceiling.json"
DEFAULT_MARKDOWN_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "rotation_oracle_ceiling.md"
DEFAULT_EVIDENCE_OUTPUT: Final = (
    REPOSITORY_ROOT / "artifacts" / "rotation" / "rotation_oracle_ceiling_folds.csv"
)

#: The claim G0 tests, written before the run and quoted from the pre-registration.
G0_CLAIM: Final = (
    "A perfect rotation signal would be worth at least min_mean_improvement points per "
    "decision as a default exclusion, on the development folds."
)

#: What G0 cannot license whichever way it comes out. Recorded in the artifact because a
#: ceiling is the number most likely to be quoted as if it were about our own signal.
G0_LICENSES: Final = (
    "Nothing about the signal this lane is building. G0 measures an oracle that reads the "
    "target gameweek's own minutes; a reachable signal is measured under G1 and G2. A "
    "ceiling above the threshold licenses continuing to look, not shipping anything, and a "
    "ceiling below it says no reachable signal can clear the gate as a default exclusion."
)

#: Why the arms are scored the way they are. The alternative changes the answer, so the
#: choice is recorded rather than left to the reader of the code.
SCORING_PATH_NOTE: Final = (
    "Scored with official autosubs and vice-captain fallback (official_autosub_captain_v2) "
    "through evaluation.scoring.score_frozen_squad_decision. The season-chain path was "
    "rejected: it scores starters plus the captain again with no automatic substitutions, "
    "so removing the autosub rule that recovers points from a non-appearing starter would "
    "inflate the very gain this measurement is trying to bound."
)

_EVIDENCE_COLUMNS: Final[tuple[str, ...]] = (
    "fold_id",
    "season",
    "gameweek",
    "control_points",
    "oracle_points",
    "difference",
    "control_zero_minute_starters",
    "oracle_zero_minute_starters",
    "control_autosub_points",
    "oracle_autosub_points",
    "flagged_players",
    "excluded_players_applied",
    "control_started_excluded_players",
)


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--evidence-output", type=Path, default=DEFAULT_EVIDENCE_OUTPUT)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help=(
            "re-render the markdown twin from the committed JSON record and measure "
            "nothing, so the twin is provably a function of the record"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "count the decisions and the flagged players, time one fold end to end, and "
            "write nothing"
        ),
    )
    return parser.parse_args(argv)


def _load_development_panel(archive_root: Path) -> pd.DataFrame:
    """Load exactly the declared seasons and prove that is what arrived."""

    panel = build_panel(archive_root, seasons=HISTORY_SEASONS)
    observed = {str(value) for value in panel["season"].dropna().unique()}
    if observed != set(HISTORY_SEASONS):
        raise DataError(
            "The loaded panel's seasons differ from the declared development history: "
            f"expected {sorted(HISTORY_SEASONS)!r}, observed {sorted(observed)!r}."
        )
    if LOCKED_HOLDOUT_SEASON in observed:
        raise DataError(
            f"{LOCKED_HOLDOUT_SEASON} is in the loaded panel. The holdout is not read here."
        )
    return panel


def _flags(panel: pd.DataFrame) -> OracleFlags:
    """Flag over the decision seasons only, so the counts describe what can be excluded.

    The appearance rate is grouped by ``(season, player_id)``, so dropping 2020-21 cannot
    change any rate in the seasons that do produce decisions. 2020-21 is history for the
    cross-season carry-over and has no decision to exclude anyone from, so counting its
    flags would inflate a number nothing acts on.
    """

    return build_oracle_flags(panel.loc[panel["season"].isin(DECISION_SEASONS)])


def _projection_builder() -> ProjectionBuilder:
    """The historical Ridge control, as every other development comparison builds it."""

    return make_ridge_projection_builder(cross_season=CrossSeasonConfig())


def _oracle_arm(
    control: Sequence[EvaluationFold], flags: OracleFlags
) -> tuple[tuple[EvaluationFold, ...], dict[str, int], dict[str, int]]:
    """Return the excluded arm, plus what the exclusion reached and what it could not."""

    folds: list[EvaluationFold] = []
    applied: dict[str, int] = {}
    absent: dict[str, int] = {}
    for fold in control:
        excluded = apply_rotation_exclusion(fold, flags.by_fold.get(fold_key(fold), ()))
        folds.append(excluded.fold)
        applied[fold.fold_id] = len(excluded.applied)
        absent[fold.fold_id] = len(excluded.absent)
    return tuple(folds), applied, absent


def _evaluate(folds: Sequence[EvaluationFold], *, arm: str) -> EvaluationResult:
    config = EvaluationConfig(
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        run_metadata={"study": ROTATION_CEILING_CONTRACT_VERSION, "arm": arm},
    )
    return evaluate_prepared_folds(folds, config)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _write_evidence(
    path: Path,
    comparison: RotationCeilingComparison,
    control_details: Mapping[str, Mapping[str, object]],
    oracle_details: Mapping[str, Mapping[str, object]],
    flags: OracleFlags,
    applied: Mapping[str, int],
) -> str:
    """Write the per-fold expansion to the evidence tier and return its digest.

    ADR 0003 puts a per-fold table in ``artifacts/``, which is gitignored, and requires the
    committed record to be checkable without it. The digest is the link between the two.
    """

    rows: list[dict[str, object]] = []
    for item in comparison.differences:
        control = control_details[item.fold_id]
        oracle = oracle_details[item.fold_id]
        season, gameweek = item.season, int(item.fold_id[-2:])
        rows.append(
            {
                "fold_id": item.fold_id,
                "season": season,
                "gameweek": gameweek,
                "control_points": item.control_points,
                "oracle_points": item.oracle_points,
                "difference": item.difference,
                "control_zero_minute_starters": control["zero_minute_starters"],
                "oracle_zero_minute_starters": oracle["zero_minute_starters"],
                "control_autosub_points": control["autosub_points"],
                "oracle_autosub_points": oracle["autosub_points"],
                "flagged_players": len(flags.by_fold.get((season, gameweek), ())),
                "excluded_players_applied": applied.get(item.fold_id, 0),
                "control_started_excluded_players": control["excluded_starters"],
            }
        )
    frame = pd.DataFrame.from_records(rows, columns=list(_EVIDENCE_COLUMNS))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")
    return _sha256(path)


def _detail_records(
    details: Sequence[FoldDecisionDetail],
) -> dict[str, Mapping[str, object]]:
    """The per-arm numbers the evidence table needs, keyed by fold."""

    return {
        detail.fold_id: {
            "points": detail.points,
            "zero_minute_starters": detail.zero_minute_starters,
            "autosub_points": detail.autosub_points,
            "excluded_starters": detail.excluded_starters,
        }
        for detail in details
    }


def _comparison_record(
    comparison: RotationCeilingComparison,
    *,
    interval: tuple[float, float] | None,
) -> dict[str, object]:
    return {
        "attempted_folds": comparison.attempted_folds,
        "comparable_folds": comparison.comparable_folds,
        "dropped_fold_ids": list(comparison.dropped_fold_ids),
        "oracle_wins": comparison.oracle_wins,
        "ties": comparison.ties,
        "oracle_losses": comparison.oracle_losses,
        "control_mean_points": comparison.control_mean_points,
        "oracle_mean_points": comparison.oracle_mean_points,
        "mean_difference": comparison.mean_difference,
        "median_difference": comparison.median_difference,
        "season_mean_differences": dict(comparison.season_mean_differences),
        "interval_lower": None if interval is None else interval[0],
        "interval_upper": None if interval is None else interval[1],
        "control_zero_minute_starters": comparison.control_zero_minute_starters,
        "oracle_zero_minute_starters": comparison.oracle_zero_minute_starters,
        "control_autosub_points": comparison.control_autosub_points,
        "oracle_autosub_points": comparison.oracle_autosub_points,
        "control_started_excluded_players": comparison.control_started_excluded_players,
    }


def _verdict(comparison: RotationCeilingComparison) -> dict[str, object]:
    mean = comparison.mean_difference
    meets = mean is not None and mean >= POLICY.min_mean_improvement
    return {
        "gate": "G0",
        "claim": G0_CLAIM,
        "threshold_points_per_decision": POLICY.min_mean_improvement,
        "threshold_source": "squadopt.experiments.config.PromotionPolicy.min_mean_improvement",
        "meets_threshold": meets,
        "verdict": "ceiling_at_or_above_threshold" if meets else "ceiling_below_threshold",
        "licenses": G0_LICENSES,
        "licenses_candidate_signal": False,
    }


def _limits(flags: OracleFlags) -> list[dict[str, object]]:
    """The four things a reader must know before quoting the number."""

    return [
        {
            "name": "oracle_reads_the_target_gameweek",
            "detail": (
                "The flag uses the target gameweek's own minutes. That is what makes this a "
                "ceiling and it is what every feature in the repository is forbidden to do. "
                "A gameweek's own outcome may score a decision, never inform it; this "
                "measurement stands outside that rule by construction and produces no "
                "feature, column or model input."
            ),
        },
        {
            "name": "playing_not_starting",
            "detail": (
                "The development archive carries no verified start labels, so the appearance "
                "signal is minutes > 0. The oracle marks a recent regular who did not play "
                "at all, and cannot see a regular who started and was withdrawn early. It "
                "therefore flags fewer players than a start-aware oracle would, which makes "
                "the measured ceiling conservative in that direction."
            ),
        },
        {
            "name": "no_availability_rule_in_either_arm",
            "detail": (
                "Development folds carry no availability layer, so neither arm suppresses an "
                "injured or suspended player before the solve. The oracle therefore also "
                "catches absences a live availability rule already handles, which makes the "
                "measured ceiling generous in that direction: part of the gain is not "
                "rotation at all."
            ),
        },
        {
            "name": "full_window_required",
            "detail": (
                f"A player needs all {flags.window} prior gameweeks to be eligible. With the "
                "primitive's default of one prior observation a rate of 1.0 would mean "
                "'played once', so the rule requires the whole window and a player without "
                "it is not eligible rather than being read as a regular."
            ),
        },
    ]


def _interval_reading(comparison: Mapping[str, object], verdict: Mapping[str, object]) -> str:
    """State what the interval does and does not settle, whichever way it came out.

    The pre-registered claim is about the *mean*, so the verdict is read off the mean. An
    interval that still contains the threshold does not overturn that verdict and is not
    quietly allowed to: it is a separate fact, and a reader who takes the mean without it
    would be taking a number more certain than the measurement is.
    """

    lower = cast(float, comparison["interval_lower"])
    upper = cast(float, comparison["interval_upper"])
    threshold = cast(float, verdict["threshold_points_per_decision"])
    if lower >= threshold:
        return (
            f"**Reading the interval.** The whole interval sits at or above the {threshold} "
            "threshold, so the ceiling clears it on the mean and on its lower bound alike."
        )
    if upper < threshold:
        return (
            f"**Reading the interval.** The whole interval sits below the {threshold} "
            "threshold. The ceiling does not reach it under any reading here."
        )
    excludes_zero = "excludes" if lower > 0.0 else "includes"
    return (
        f"**Reading the interval.** The mean clears the {threshold} threshold but the "
        f"interval does not: it runs from {lower:+.4f} to {upper:+.4f}, so a ceiling below "
        "the threshold is not ruled out by this measurement. The interval "
        f"{excludes_zero} zero, which is a weaker statement than clearing the gate, and the "
        "pre-registered claim is about the mean rather than the bound. A ceiling this wide "
        "is a reason to treat the number as an order of magnitude, not as a target."
    )


def _concentration_reading(comparison: Mapping[str, object]) -> str:
    """Say where the difference lives, because a mean hides both of these."""

    folds = cast(int, comparison["comparable_folds"])
    ties = cast(int, comparison["ties"])
    median = cast(float, comparison["median_difference"])
    seasons = cast(Mapping[str, float], comparison["season_mean_differences"])
    negative = sorted(season for season, value in seasons.items() if value < 0.0)
    sentence = (
        f"**Where the difference lives.** The oracle changes nothing in {ties} of {folds} "
        f"decisions and the median difference is {median:+.4f}, so the mean is carried by a "
        f"minority of folds rather than by a broad shift."
    )
    if negative:
        sentence += (
            f" It is also not consistent across seasons: {', '.join(negative)} "
            f"{'go' if len(negative) > 1 else 'goes'} the other way."
        )
    return sentence


def _autosub_reading(comparison: Mapping[str, object]) -> str:
    """Quantify what rejecting the season-chain path was worth.

    The design note above says the chain would have inflated the gain. This turns that
    claim into arithmetic over the committed numbers, so the choice is auditable rather
    than merely argued.
    """

    folds = cast(int, comparison["comparable_folds"])
    control = cast(float, comparison["control_autosub_points"])
    oracle = cast(float, comparison["oracle_autosub_points"])
    mean = cast(float, comparison["mean_difference"])
    surrendered = (control - oracle) / folds
    return (
        f"**What that choice was worth.** Autosubs recover {control / folds:.2f} points per "
        f"decision for the control and only {oracle / folds:.2f} for the oracle arm: "
        "excluding a rested regular removes the very non-appearance an autosub would have "
        f"repaired. So the arm surrenders {surrendered:.2f} points per decision of recovery "
        f"to gain {mean:+.4f} net. A scoring path with no automatic substitutions would not "
        f"have charged that {surrendered:.2f} back, and would have reported a ceiling near "
        f"{mean + surrendered:.2f} — roughly {(mean + surrendered) / mean:.1f} times the "
        "measured one. That is why the path is named in the record rather than left to the "
        "code."
    )


def _markdown(document: Mapping[str, object]) -> str:
    comparison = cast(Mapping[str, object], document["comparison"])
    verdict = cast(Mapping[str, object], document["verdict"])
    oracle = cast(Mapping[str, object], document["oracle"])
    mean = comparison["mean_difference"]
    lower = comparison["interval_lower"]
    upper = comparison["interval_upper"]
    lines = [
        "# Rotation oracle ceiling (G0)",
        "",
        f"Contract `{document['contract_version']}`, generated {document['generated_at_utc']}.",
        "Development-only reading. Nothing here is promoted, pinned or deployed, and the",
        f"locked {LOCKED_HOLDOUT_SEASON} holdout was not loaded.",
        "",
        f"**Verdict:** `{verdict['verdict']}` — paired mean difference "
        f"**{mean:+.4f}** points per decision against a threshold of "
        f"{verdict['threshold_points_per_decision']}, "
        f"{int(POLICY.confidence_level * 100)}% interval [{lower:+.4f}, {upper:+.4f}] over "
        f"{comparison['comparable_folds']}/{comparison['attempted_folds']} paired folds.",
        "",
        f"**Claim tested:** {verdict['claim']}",
        "",
        _interval_reading(comparison, verdict),
        "",
        _concentration_reading(comparison),
        "",
        f"**What it does not license:** {verdict['licenses']}",
        "",
        "## Arms",
        "",
        "| arm | mean realized squad points | zero-minute selected starters | autosub points |",
        "| --- | --- | --- | --- |",
        f"| control (Ridge, no exclusion) | {comparison['control_mean_points']:.4f} | "
        f"{comparison['control_zero_minute_starters']} | "
        f"{comparison['control_autosub_points']:.1f} |",
        f"| oracle exclusion | {comparison['oracle_mean_points']:.4f} | "
        f"{comparison['oracle_zero_minute_starters']} | "
        f"{comparison['oracle_autosub_points']:.1f} |",
        "",
        f"W/T/L for the oracle arm: **{comparison['oracle_wins']}/{comparison['ties']}/"
        f"{comparison['oracle_losses']}**; median difference "
        f"{comparison['median_difference']:+.4f}. The control started "
        f"{comparison['control_started_excluded_players']} flagged player(s) across the "
        "paired folds — the mechanism the exclusion removes.",
        "",
        "### Per season",
        "",
        "| season | mean paired difference |",
        "| --- | --- |",
    ]
    season_means = cast(Mapping[str, float], comparison["season_mean_differences"])
    for season, value in sorted(season_means.items()):
        lines.append(f"| {season} | {value:+.4f} |")
    lines += [
        "",
        "## The oracle",
        "",
        f"`{oracle['version']}`: a player is flagged when he recorded zero minutes in the "
        f"target gameweek **and** his shifted {oracle['window']}-gameweek appearance rate is "
        f"exactly 1.0. Flagged rows: **{oracle['flagged_rows']}** of "
        f"{oracle['eligible_rows']} eligible ({oracle['panel_rows']} panel rows); of the "
        f"{oracle['zero_minute_eligible_rows']} eligible zero-minute rows, the rate rule "
        "keeps only the recent regulars.",
        "",
        f"{SCORING_PATH_NOTE}",
        "",
        _autosub_reading(comparison),
        "",
        "The exclusion zeroes expected points after the projection and before the solve — "
        "the availability rule's own position and direction — and keeps every row, because "
        "dropping rows can turn a fold infeasible and would break the pairing.",
        "",
        "## Limits a reader must know before quoting the number",
        "",
    ]
    for limit in cast(Sequence[Mapping[str, object]], document["limits"]):
        lines.append(f"- **{limit['name']}** — {limit['detail']}")
    evidence = cast(Mapping[str, object], document["evidence"])
    lines += [
        "",
        "## Reproducing this",
        "",
        f"Per-fold expansion: `{evidence['path']}`, sha256 `{evidence['sha256']}`. It sits in "
        "the evidence tier (ADR 0003) and is not committed; every number above is in the "
        "committed JSON beside this file, so the record is checkable without it.",
        "",
        f"Archive commit `{cast(Mapping[str, object], document['provenance'])['archive_commit']}`, "
        f"repository commit "
        f"`{cast(Mapping[str, object], document['provenance'])['repository_commit']}`. "
        f"Seasons loaded: {', '.join(HISTORY_SEASONS)}; decisions in "
        f"{', '.join(DECISION_SEASONS)}.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _stage(label: str, started: float) -> None:
    print(f"  [{time.monotonic() - started:7.1f}s] {label}", flush=True)


def _dry_run(arguments: argparse.Namespace) -> int:
    started = time.monotonic()
    panel = _load_development_panel(arguments.archive_root)
    _stage(f"panel loaded, {len(panel)} rows", started)
    flags = _flags(panel)
    _stage(
        f"oracle flagged {flags.flagged_rows} row(s) over {len(flags.by_fold)} decision(s)",
        started,
    )
    decisions = walk_forward_decision_points(panel, seasons=DECISION_SEASONS)
    _stage(f"{len(decisions)} decision point(s)", started)

    # One fold, the last one, because it carries the most history and is therefore the
    # slowest. Timing it is the only honest way to say how long the full run takes.
    single = time.monotonic()
    control = attach_realized_minutes(
        build_walk_forward_fold(panel, decisions[-1], projection_builder=_projection_builder()),
        panel,
    )
    built = time.monotonic() - single
    oracle = apply_rotation_exclusion(control, flags.by_fold.get(fold_key(control), ())).fold
    solved = time.monotonic()
    _evaluate([control], arm="control")
    _evaluate([oracle], arm="oracle")
    per_fold = built + (time.monotonic() - solved)
    _stage(f"{decisions[-1].fold_id}: {built:.1f}s to build, {per_fold:.1f}s in total", started)

    print(f"Decisions          {len(decisions)} (expected {EXPECTED_FOLD_COUNT})")
    print(f"Flagged rows       {flags.flagged_rows} in {flags.by_season}")
    print(f"Rough total        {per_fold * len(decisions):.0f}s if every fold costs the last one")
    print("Wrote              nothing")
    return 0


def _measure(arguments: argparse.Namespace) -> dict[str, object]:
    started = time.monotonic()
    panel = _load_development_panel(arguments.archive_root)
    _stage(f"panel loaded, {len(panel)} rows", started)
    flags = _flags(panel)
    _stage(f"oracle flagged {flags.flagged_rows} row(s)", started)

    control = tuple(
        attach_realized_minutes(fold, panel)
        for fold in build_walk_forward_folds(
            panel, seasons=DECISION_SEASONS, projection_builder=_projection_builder()
        )
    )
    if len(control) != EXPECTED_FOLD_COUNT:
        raise BacktestConfigurationError(
            f"The run produced {len(control)} folds, not the agreed development population of "
            f"{EXPECTED_FOLD_COUNT}. A different population is a different measurement."
        )
    _stage(f"{len(control)} control fold(s) built", started)

    oracle, applied, absent = _oracle_arm(control, flags)
    _stage(f"{sum(applied.values())} exclusion(s) applied", started)

    control_result = _evaluate(control, arm="control")
    _stage("control arm solved", started)
    oracle_result = _evaluate(oracle, arm="oracle_exclusion")
    _stage("oracle arm solved", started)

    excluded_by_fold = {fold_key(fold): flags.by_fold.get(fold_key(fold), ()) for fold in control}
    control_details = fold_decision_details(
        control_result, control, excluded_by_fold=excluded_by_fold
    )
    oracle_details = fold_decision_details(oracle_result, oracle, excluded_by_fold=excluded_by_fold)
    comparison = compare_rotation_ceiling(
        control_details, oracle_details, attempted_folds=len(control)
    )
    interval: tuple[float, float] | None = None
    if comparison.differences:
        lower, upper = season_aware_moving_block_interval(
            [(item.season, item.difference) for item in comparison.differences],
            policy=POLICY,
            candidate_id=CANDIDATE_ID,
        )
        interval = (float(lower), float(upper))
    _stage("paired and interval taken", started)

    control_records = _detail_records(control_details)
    oracle_records = _detail_records(oracle_details)
    digest = _write_evidence(
        arguments.evidence_output,
        comparison,
        control_records,
        oracle_records,
        flags,
        applied,
    )
    return {
        "panel_rows": len(panel),
        "oracle": {
            "version": flags.version,
            "window": flags.window,
            "min_periods": flags.min_periods,
            "panel_rows": flags.panel_rows,
            "eligible_rows": flags.eligible_rows,
            "zero_minute_eligible_rows": flags.zero_minute_eligible_rows,
            "flagged_rows": flags.flagged_rows,
            "flagged_seasons": list(DECISION_SEASONS),
            "flagged_by_season": dict(flags.by_season),
            "decisions_with_a_flag": len(flags.by_fold),
            "exclusions_applied": sum(applied.values()),
            "flagged_players_absent_from_the_pool": sum(absent.values()),
        },
        "arms": {
            "control": "historical Ridge projection, no exclusion",
            "oracle_exclusion": (
                "the same projection with the flagged players' expected points set to zero "
                "before the solve"
            ),
            "scoring": SCORING_PATH_NOTE,
        },
        "policy": {
            "min_mean_improvement": POLICY.min_mean_improvement,
            "confidence_level": POLICY.confidence_level,
            "bootstrap_resamples": POLICY.bootstrap_resamples,
            "moving_block_length": POLICY.moving_block_length,
            "deterministic_seed": POLICY.deterministic_seed,
            "candidate_id": CANDIDATE_ID,
        },
        "comparison": _comparison_record(comparison, interval=interval),
        "verdict": _verdict(comparison),
        "limits": _limits(flags),
        "evidence": {
            "path": str(arguments.evidence_output.relative_to(REPOSITORY_ROOT)),
            "sha256": digest,
            "columns": list(_EVIDENCE_COLUMNS),
            "committed": False,
        },
    }


def _recorded_warnings(caught: Sequence[warnings.WarningMessage]) -> list[str]:
    return sorted({f"{item.category.__name__}: {item.message}" for item in caught})


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    if arguments.render_only:
        if not arguments.json_output.exists():
            print(f"Refused: {arguments.json_output} does not exist; there is nothing to render.")
            return 1
        published = json.loads(arguments.json_output.read_text(encoding="utf-8"))
        write_text(arguments.markdown_output, _markdown(published))
        print(f"Rendered  {arguments.markdown_output} from {arguments.json_output}")
        return 0
    if arguments.dry_run:
        try:
            return _dry_run(arguments)
        except (
            BacktestConfigurationError,
            DataError,
            EvaluationError,
            OSError,
            RotationCeilingError,
            ValueError,
        ) as error:
            print(f"Refused: {error}")
            return 1

    started = datetime.now(UTC)
    metadata = artifact_metadata(
        panel_rows=0,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=HISTORY_SEASONS,
    )
    provenance = cast(dict[str, object], metadata["provenance"])
    if provenance["working_tree_dirty"]:
        print("Refused: commit or stash working-tree changes before measuring the ceiling.")
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measured = _measure(arguments)
        except (
            BacktestConfigurationError,
            DataError,
            EvaluationError,
            OSError,
            RotationCeilingError,
            ShadowReportError,
            ValueError,
        ) as error:
            print(f"Refused: {error}")
            return 1
    completed = datetime.now(UTC)

    panel_rows = cast(int, measured.pop("panel_rows"))
    metadata = artifact_metadata(
        panel_rows=panel_rows,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=HISTORY_SEASONS,
    )
    document: dict[str, object] = {
        "contract_version": ROTATION_CEILING_CONTRACT_VERSION,
        "generated_at_utc": metadata["created_utc"],
        "descriptive_only": True,
        "promotion_decision": "not_evaluated",
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "prereg": "docs/rotation_evidence_prereg.md",
        "decision_seasons": list(DECISION_SEASONS),
        "execution": {
            "started_at_utc": started.isoformat(timespec="seconds"),
            "completed_at_utc": completed.isoformat(timespec="seconds"),
            "elapsed_seconds": (completed - started).total_seconds(),
            "warnings": _recorded_warnings(caught),
        },
        "provenance": metadata["provenance"],
        "environment": metadata["environment"],
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"Refused: {error}")
        return 1

    # Rendered from what is actually on disk, not from the document in memory. On a replay
    # the occupant is the earlier run's, and a markdown twin carrying this run's timestamp
    # beside that JSON would be a pair that disagrees with itself.
    published = json.loads(arguments.json_output.read_text(encoding="utf-8"))
    write_text(arguments.markdown_output, _markdown(published))

    comparison = cast(Mapping[str, object], published["comparison"])
    verdict = cast(Mapping[str, object], published["verdict"])
    print(f"Folds      {comparison['comparable_folds']}/{comparison['attempted_folds']}")
    print(f"Mean delta {comparison['mean_difference']}")
    print(f"Interval   [{comparison['interval_lower']}, {comparison['interval_upper']}]")
    print(f"Verdict    {verdict['verdict']} (threshold {POLICY.min_mean_improvement})")
    print(f"Wrote      {arguments.json_output} ({outcome})")
    print(f"           {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
