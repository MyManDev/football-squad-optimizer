"""The player-level shadow calibration run, under the Phase 2A pre-registration.

One question, asked internally and answered honestly: do the deciding model's own
0.90 intervals cover 0.90 of what actually happened? The model is
``in-season-carry-over-v1`` — the one that decides live from gameweek two, and the
one no committed calibration wraps. Every fitted calibration on record wraps the
archive-fed control instead, which is the mismatch ``#45`` exists to prevent.

Nothing here publishes anything. The result is a ``shadow_calibration_report_v1``
document written under ``docs/`` or a local path, never under ``web/public``, and no
outcome of this run changes a member-facing surface, a contract, or a strategy's
evidence status.

Three disciplines the pre-registration fixes and this module enforces rather than
assumes:

* **The split is the prereg's, not a convenient one.** The fit sees folds up to the
  declared cutoff and nothing later; the evaluation season is scored frozen. The
  chronological instrument is reused rather than reimplemented, and the split it
  produced is checked against the cutoff afterwards.
* **A subset of the gates is not a verdict.** The pre-registration names three gates:
  P1 (player coverage) here, S1 and S2 (squad PIT and lower tail) in the squad-level
  instrument. A run that evaluates only P1 may report ``failed`` if P1 fails — a
  negative is a result — but it may never report ``calibrated_internal``, because
  two thirds of the protocol went unasked. That case is an honest ``abstained``.
* **Missing is never zero.** A fixture calendar that does not cover every evaluated
  gameweek would turn "unknown" into "blank", so the calendar's completeness is
  checked and a gap abstains instead of quietly scoring a zero-fixture cell.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import pandas as pd

from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    ResidualSourceManifest,
)
from squadopt.experiments.shadow_report import (
    PREREG_GATE_FAMILIES,
    ShadowCalibrationReport,
    ShadowExecutionMetadata,
    ShadowGateResult,
)
from squadopt.uncertainty.fixture_conformal import (
    FIXTURE_GROUPS,
    FixtureGroupConformalConfig,
    fit_and_evaluate_fixture_group_conformal,
)

SHADOW_CALIBRATION_RUN_CONTRACT_VERSION: Final = "shadow_calibration_run_v1"

#: The pre-registration's own numbers. They are constants here so a run cannot be
#: given a kinder threshold than the one committed before the result existed.
CONFIDENCE_LEVEL: Final = 0.90
POOLED_COVERAGE_TOLERANCE: Final = 0.03
GROUP_COVERAGE_TOLERANCE: Final = 0.05
MIN_GROUP_ROWS_TO_GATE: Final = 200
MIN_EVALUATION_FOLDS: Final = 30
BOOTSTRAP_SEED: Final = 0

#: The prereg's full gate set. P1 is this runner's; S1 and S2 belong to the
#: squad-level instrument and are named here so their absence is stated, not implied.
#: It is the contract's own tuple rather than a second copy: two lists of the same
#: pre-registered families are two lists that can drift apart.
PREREG_GATES: Final = PREREG_GATE_FAMILIES
RUNNER_GATES: Final = ("P1_player_coverage",)


class ShadowCalibrationError(ValueError):
    """Raised when a shadow calibration run cannot proceed at all."""


@dataclass(frozen=True, slots=True)
class ShadowCalibrationConfig:
    """The run's controls, all pinned by the pre-registration."""

    cutoff_fold_id: str
    horizon: int = 1
    confidence_level: float = CONFIDENCE_LEVEL
    min_evaluation_folds: int = MIN_EVALUATION_FOLDS
    bootstrap_seed: int = BOOTSTRAP_SEED

    def __post_init__(self) -> None:
        if self.horizon != 1:
            raise ShadowCalibrationError(
                "This runner is single-gameweek (h=1). Multi-week aggregation is out of "
                "scope for the Phase 2A pre-registration and needs its own."
            )
        if self.confidence_level != CONFIDENCE_LEVEL:
            raise ShadowCalibrationError(
                f"confidence_level is pre-registered at {CONFIDENCE_LEVEL}; a run may not "
                "choose another."
            )
        if self.bootstrap_seed != BOOTSTRAP_SEED:
            raise ShadowCalibrationError(
                f"bootstrap_seed is pre-registered at {BOOTSTRAP_SEED} and may not move."
            )
        if not self.cutoff_fold_id:
            raise ShadowCalibrationError("cutoff_fold_id is required.")


def attach_fixture_counts(
    table: pd.DataFrame, calendar: pd.DataFrame
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Join the calendar onto the residual rows, refusing to guess a gap.

    A club with no fixture in a gameweek is a blank — a represented zero. A gameweek
    the calendar does not describe at all is *missing*, and the two are not the same
    thing, so the uncovered gameweeks are returned for the caller to abstain on.
    """

    for frame, label in ((table, "table"), (calendar, "calendar")):
        if not isinstance(frame, pd.DataFrame):
            raise ShadowCalibrationError(f"{label} must be a pandas DataFrame.")
    required = {"season", "gameweek", "team_id", "fixture_count"}
    missing = sorted(required - set(calendar.columns))
    if missing:
        raise ShadowCalibrationError(f"The calendar is missing columns {missing}.")

    covered = {
        (str(season), int(gameweek))
        for season, gameweek in zip(calendar["season"], calendar["gameweek"], strict=True)
    }
    needed = {
        (str(season), int(gameweek))
        for season, gameweek in zip(table["season"], table["gameweek"], strict=True)
    }
    uncovered = tuple(f"{season}-gw{gameweek:02d}" for season, gameweek in sorted(needed - covered))

    joined = table.merge(
        calendar.loc[:, ["season", "gameweek", "team_id", "fixture_count"]],
        on=["season", "gameweek", "team_id"],
        how="left",
    )
    # Within a covered gameweek, a club absent from the calendar genuinely has no
    # fixture: that is a blank, which the conformal instrument excludes by name.
    joined["fixture_count"] = joined["fixture_count"].fillna(0).astype(int)
    return joined, uncovered


def _fold_order(table: pd.DataFrame) -> list[str]:
    folds = (
        table.loc[:, ["season", "gameweek", "fold_id"]]
        .drop_duplicates()
        .sort_values(["season", "gameweek"], kind="stable")
    )
    return [str(value) for value in folds["fold_id"].tolist()]


def _abstain(
    *,
    generated_at_utc: str,
    execution: ShadowExecutionMetadata,
    manifest: ResidualSourceManifest,
    cutoff_fold_id: str,
    sample_size: int,
    reasons: Sequence[str],
    diagnostics: Mapping[str, float | None] | None = None,
    provenance: Mapping[str, str],
) -> ShadowCalibrationReport:
    """No claim, and the reasons why — never a zero standing in for a measurement."""

    return ShadowCalibrationReport(
        generated_at_utc=generated_at_utc,
        execution=execution,
        horizon=1,
        residual_source=manifest.to_shadow_source(cutoff_fold_id=cutoff_fold_id),
        sample_size=sample_size,
        point_estimate=None,
        calibration_diagnostics=dict(diagnostics or {}),
        interval_diagnostics={},
        gate_results=(),
        shadow_status="abstained",
        reasons=tuple(reasons),
        provenance_fingerprints=dict(provenance),
    )


def run_shadow_calibration(
    manifest: ResidualSourceManifest,
    table: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    config: ShadowCalibrationConfig,
    generated_at_utc: str,
    execution: ShadowExecutionMetadata,
    provenance_fingerprints: Mapping[str, str],
) -> ShadowCalibrationReport:
    """Run gate P1 against the bound export, or abstain and say why.

    ``manifest`` must already be bound to the exact deciding model by
    ``load_residual_source_manifest``; that binding is the model-identity guarantee
    and this function refuses a table whose digest-bearing manifest does not match
    the rows it was handed.
    """

    if len(table) != manifest.row_count:
        raise ShadowCalibrationError(
            f"The table holds {len(table)} rows but its bound manifest describes "
            f"{manifest.row_count}; the two do not describe the same export."
        )
    provenance = {
        **dict(provenance_fingerprints),
        "residual_table_sha256": manifest.table_sha256,
        "residual_export_label": manifest.export_label,
        "model_identity": f"{manifest.model_name}/{manifest.model_version}",
        "run_contract_version": SHADOW_CALIBRATION_RUN_CONTRACT_VERSION,
    }
    # The cutoff is validated against the export here, before any fitting, so an
    # impossible split fails loudly rather than producing a plausible number.
    try:
        manifest.to_shadow_source(cutoff_fold_id=config.cutoff_fold_id)
    except ResidualSourceError as error:
        raise ShadowCalibrationError(str(error)) from error

    joined, uncovered = attach_fixture_counts(table, calendar)
    if uncovered:
        return _abstain(
            generated_at_utc=generated_at_utc,
            execution=execution,
            manifest=manifest,
            cutoff_fold_id=config.cutoff_fold_id,
            sample_size=0,
            reasons=(
                f"The fixture calendar does not cover {len(uncovered)} evaluated gameweeks "
                f"(first: {uncovered[0]}); an uncovered gameweek is missing, not blank, and "
                "scoring it as a zero-fixture cell would invent a calendar fact.",
            ),
            provenance=provenance,
        )

    fold_ids = _fold_order(joined)
    if config.cutoff_fold_id not in fold_ids:
        raise ShadowCalibrationError(
            f"cutoff_fold_id {config.cutoff_fold_id!r} is not one of the export's folds."
        )
    split = fold_ids.index(config.cutoff_fold_id) + 1
    evaluation_folds = fold_ids[split:]
    if len(evaluation_folds) < config.min_evaluation_folds:
        return _abstain(
            generated_at_utc=generated_at_utc,
            execution=execution,
            manifest=manifest,
            cutoff_fold_id=config.cutoff_fold_id,
            sample_size=len(evaluation_folds),
            reasons=(
                f"{len(evaluation_folds)} evaluation folds are fewer than the "
                f"pre-registered minimum of {config.min_evaluation_folds}; below the floor "
                "the protocol abstains rather than reading a number.",
            ),
            provenance=provenance,
        )

    result = fit_and_evaluate_fixture_group_conformal(
        joined,
        FixtureGroupConformalConfig(
            confidence_level=config.confidence_level,
            calibration_fold_fraction=split / len(fold_ids),
        ),
    )
    # The instrument splits by fraction; the prereg splits at a fold. Check that the
    # fraction landed exactly where the cutoff says, rather than trusting arithmetic.
    if result.calibration_folds != tuple(fold_ids[:split]):
        raise ShadowCalibrationError(
            "The chronological split did not land on the declared cutoff: the fit saw "
            f"{len(result.calibration_folds)} folds, the cutoff names {split}."
        )

    overall = result.position_metrics.get("overall")
    if overall is None:
        raise ShadowCalibrationError("The instrument returned no overall metrics.")
    pooled_coverage = float(overall.empirical_coverage)
    gates: list[ShadowGateResult] = [
        ShadowGateResult(
            gate="P1_player_coverage_pooled",
            passes=abs(pooled_coverage - config.confidence_level) <= POOLED_COVERAGE_TOLERANCE,
            observed=pooled_coverage,
            threshold=(
                f"|coverage - {config.confidence_level}| <= {POOLED_COVERAGE_TOLERANCE} "
                f"over {overall.observations} player-gameweek rows"
            ),
        )
    ]
    diagnostics: dict[str, float | None] = {
        "pooled_empirical_coverage": pooled_coverage,
        "pooled_observations": float(overall.observations),
    }
    interval_diagnostics: dict[str, float | None] = {
        "pooled_mean_interval_width": float(overall.mean_interval_width),
        "pooled_mean_absolute_error": float(overall.mean_absolute_error),
    }
    for group in FIXTURE_GROUPS:
        metrics = result.fixture_metrics.get(group)
        if metrics is None:
            diagnostics[f"{group}_empirical_coverage"] = None
            continue
        coverage = float(metrics.empirical_coverage)
        diagnostics[f"{group}_empirical_coverage"] = coverage
        diagnostics[f"{group}_observations"] = float(metrics.observations)
        interval_diagnostics[f"{group}_mean_interval_width"] = float(metrics.mean_interval_width)
        if metrics.observations < MIN_GROUP_ROWS_TO_GATE:
            # Reported, not gated — the pre-registration says a thin group cannot
            # carry a verdict, and inventing one from 40 rows would be the failure
            # mode the floor exists to prevent.
            continue
        gates.append(
            ShadowGateResult(
                gate=f"P1_player_coverage_{group}",
                passes=abs(coverage - config.confidence_level) <= GROUP_COVERAGE_TOLERANCE,
                observed=coverage,
                threshold=(
                    f"|coverage - {config.confidence_level}| <= {GROUP_COVERAGE_TOLERANCE} "
                    f"over {metrics.observations} rows (>= {MIN_GROUP_ROWS_TO_GATE} to gate)"
                ),
            )
        )

    failed = [gate.gate for gate in gates if not gate.passes]
    unasked = [gate for gate in PREREG_GATES if gate not in RUNNER_GATES]
    if failed:
        status, reasons = "failed", tuple(f"{gate} failed as measured" for gate in failed)
    else:
        # Every gate this runner asked passed. That is not the protocol's verdict:
        # the squad-level gates were never asked, so no full pass may be claimed.
        status = "abstained"
        reasons = (
            "Gate P1 passed as measured, but a partial protocol is not a verdict: "
            f"{', '.join(unasked)} belong to the squad-level instrument and were not "
            "evaluated by this player-level runner, so calibrated_internal is not "
            "claimable.",
        )

    return ShadowCalibrationReport(
        generated_at_utc=generated_at_utc,
        execution=execution,
        horizon=config.horizon,
        residual_source=manifest.to_shadow_source(cutoff_fold_id=config.cutoff_fold_id),
        sample_size=len(evaluation_folds),
        point_estimate=pooled_coverage,
        calibration_diagnostics=diagnostics,
        interval_diagnostics=interval_diagnostics,
        gate_results=tuple(gates),
        shadow_status=status,
        reasons=reasons,
        provenance_fingerprints={**provenance, "conformal_fingerprint": result.fingerprint},
    )


def replay_identity(document: Mapping[str, object]) -> dict[str, object]:
    """The part of a report two runs of the same measurement must agree on byte for byte.

    Only the wall clock is excluded. Phase 1's immutable plan artifacts set the
    precedent by stripping their own wall-clock field so an identical replay is a
    replay rather than a conflict; the same reasoning applies here, and nothing else
    is exempt — a differing number is a differing measurement.
    """

    identity = {key: value for key, value in document.items() if key != "generated_at_utc"}
    execution = identity.get("execution")
    if isinstance(execution, Mapping):
        identity["execution"] = {
            key: value
            for key, value in execution.items()
            if key not in {"started_at_utc", "completed_at_utc", "elapsed_seconds"}
        }
    return identity


def bootstrap_interval(
    values: Sequence[float], *, resamples: int, seed: int, confidence_level: float = 0.90
) -> tuple[float, float]:
    """A deterministic percentile bootstrap interval over fold-level values."""

    if not values:
        raise ShadowCalibrationError("An interval needs at least one value.")
    if any(not math.isfinite(float(value)) for value in values):
        raise ShadowCalibrationError("A non-finite value cannot enter a bootstrap.")
    import numpy as np

    generator = np.random.default_rng(seed)
    sample = np.asarray(values, dtype="float64")
    draws = generator.integers(0, len(sample), size=(resamples, len(sample)))
    means = sample[draws].mean(axis=1)
    tail = (1.0 - confidence_level) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])
    return float(low), float(high)
