"""Component-aware scenario foundation: appearance, then paired conditional residuals.

Scenario V1 draws one point residual per player. Phase C measures three things V1 cannot
represent: whether a player featured at all, how many minutes he played given that he did,
and how many points he scored given that he did. The gap that matters most is the atom at
exactly zero -- a player who did not feature scored nothing, which is a different outcome
from a small negative residual, and averaging the two hides it.

This module is the seam, not the model. It adds an input contract, a paired residual pool
and a deterministic sampler. It does not fit anything, does not promote anything, and does
not change V1: ``generate_scenarios`` is untouched and its results are bit for bit what they
were.

Two decisions are worth stating where they are made rather than in a review comment.

**Points are never clipped at zero.** An FPL score can be negative, so clipping the scenario
outcome would delete real downside and quietly narrow every risk statistic taken from it. The
optimizer's non-negative *expected points* input is a separate contract about an expectation;
importing a constraint on a mean into the support of a distribution is how a tail disappears.

**The point decomposition is deliberately not applied here.** A paired draw already carries
the whole point residual. Adding V1's common/team/idiosyncratic shocks on top of it would add
the residual twice, so this foundation stops at the paired core and leaves the correlated
version to a measured step. Inventing a second correlation structure that looks right and
double counts is the failure this avoids.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from squadopt.prediction.integration import PredictionSnapshot
from squadopt.scenarios.models import (
    ScenarioConfig,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
    _scenario_fingerprint,
)

COMPONENT_SCENARIO_CONTRACT_VERSION: Final = "component_scenario_foundation_v1"

# The per-player fields a component scenario row must carry. Names follow the Phase C
# out-of-fold export (`scripts/export_component_oof.py`) rather than being coined here, so a
# caller joining that table needs no translation. ``team_id`` and ``position`` come from the
# decision roster rather than the OOF table; the caller supplies the join.
COMPONENT_INPUT_COLUMNS: Final = (
    "player_id",
    "team_id",
    "position",
    "fixture_count",
    "appearance_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
    "composition_route",
    "evidence_status",
)

# Columns the paired residual pool is derived from, in the OOF table's own names.
RESIDUAL_SOURCE_COLUMNS: Final = (
    "fold_id",
    "player_id",
    "composition_route",
    "appearance_target",
    "minutes_target",
    "points_target",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
)

# The route whose rows carry no component prediction, so no conditional residual exists for
# them and none is invented.
DIRECT_CONTROL_ROUTE: Final = "direct_control"
COMPONENT_MODEL_ROUTE: Final = "component_model"

# Declared locally: the constant also lives in ``backtest.learned``, which sits above this
# layer, so importing it would invert the dependency the layer contract enforces.
LOCKED_HOLDOUT_SEASON: Final = "2025-26"

MINUTES_PER_FIXTURE: Final = 90


@dataclass(frozen=True, slots=True)
class ComponentScenarioProvenance:
    """Where one scenario input came from. A set that cannot say is not evidence."""

    phase_c_table_sha: str
    roster_sha: str
    model_version: str
    feature_contract_version: str
    target_contract_version: str
    dataset_contract_version: str
    season: str
    target_gameweek: int
    deterministic_seed: int

    def __post_init__(self) -> None:
        blanks = [
            name
            for name in (
                "phase_c_table_sha",
                "roster_sha",
                "model_version",
                "feature_contract_version",
                "target_contract_version",
                "dataset_contract_version",
                "season",
            )
            if not str(getattr(self, name)).strip()
        ]
        if blanks:
            raise ScenarioValidationError(
                f"Component scenario provenance is missing {sorted(blanks)!r}."
            )
        if self.season == LOCKED_HOLDOUT_SEASON:
            raise ScenarioValidationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout; component scenarios are not "
                "built, listed or fingerprinted for it."
            )
        if self.target_gameweek < 1:
            raise ScenarioValidationError(
                f"target_gameweek must be at least 1, got {self.target_gameweek}."
            )


@dataclass(frozen=True, slots=True)
class ComponentScenarioInputs:
    """One decision week's per-player component expectations, with provenance.

    The frame is copied on construction, so a caller's DataFrame is never mutated and a
    later edit to theirs cannot change what was validated here.
    """

    table: pd.DataFrame
    provenance: ComponentScenarioProvenance
    contract_version: str = COMPONENT_SCENARIO_CONTRACT_VERSION

    def __post_init__(self) -> None:
        frame = _validated_component_table(self.table)
        object.__setattr__(self, "table", frame)

    @property
    def player_ids(self) -> tuple[int, ...]:
        """Players in the frame's own order, which the scenario columns must preserve."""

        return tuple(int(value) for value in self.table["player_id"])


def _validated_component_table(table: object) -> pd.DataFrame:
    if not isinstance(table, pd.DataFrame):
        raise ScenarioValidationError("Component scenario inputs must be a pandas DataFrame.")
    missing = [name for name in COMPONENT_INPUT_COLUMNS if name not in table.columns]
    if missing:
        raise ScenarioValidationError(f"Component scenario inputs are missing {missing!r}.")
    if table.empty:
        raise ScenarioValidationError("Component scenario inputs must carry at least one row.")

    frame = table.loc[:, list(COMPONENT_INPUT_COLUMNS)].copy(deep=True).reset_index(drop=True)
    if bool(frame["player_id"].duplicated().any()):
        duplicated = sorted(
            {int(v) for v in frame.loc[frame["player_id"].duplicated(), "player_id"]}
        )
        raise ScenarioValidationError(
            f"Component scenario inputs list players more than once: {duplicated[:10]!r}."
        )

    fixtures = frame["fixture_count"].to_numpy()
    if not np.all(np.equal(np.mod(fixtures.astype("float64"), 1), 0)) or bool(
        np.any(fixtures.astype("float64") < 0)
    ):
        raise ScenarioValidationError(
            "fixture_count must be a non-negative whole number of fixtures."
        )
    frame["fixture_count"] = fixtures.astype("int64")

    probability = frame["appearance_probability"].to_numpy(dtype="float64")
    if (
        not np.all(np.isfinite(probability))
        or bool(np.any(probability < 0.0))
        or bool(np.any(probability > 1.0))
    ):
        raise ScenarioValidationError("appearance_probability must be finite and within [0, 1].")

    component_rows = frame["composition_route"].astype("string") == COMPONENT_MODEL_ROUTE
    conditional = ("expected_minutes_if_appearance", "raw_expected_points_if_appearance")
    for column in conditional:
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype="float64")
        if bool(np.any(~np.isfinite(values) & component_rows.to_numpy())):
            raise ScenarioValidationError(
                f"{column} must be finite on every {COMPONENT_MODEL_ROUTE} row; a missing "
                "component value is not filled with zero."
            )
        frame[column] = values

    minutes = frame["expected_minutes_if_appearance"].to_numpy(dtype="float64")
    ceiling = frame["fixture_count"].to_numpy(dtype="float64") * MINUTES_PER_FIXTURE
    out_of_range = component_rows.to_numpy() & ((minutes < 0.0) | (minutes > ceiling))
    if bool(np.any(out_of_range)):
        raise ScenarioValidationError(
            "expected_minutes_if_appearance must lie in [0, 90 * fixture_count]."
        )

    # raw_expected_points_if_appearance is deliberately unbounded below: an FPL score can be
    # negative, and a lower bound here would be a claim about the game's rules, not the data.

    control_rows = frame["composition_route"].astype("string") == DIRECT_CONTROL_ROUTE
    invented = control_rows.to_numpy() & np.isfinite(
        frame["expected_minutes_if_appearance"].to_numpy(dtype="float64")
    )
    if bool(np.any(invented)):
        raise ScenarioValidationError(
            f"{DIRECT_CONTROL_ROUTE} rows carry no component prediction; a component value on "
            "one of them would be invented rather than measured."
        )
    return frame


@dataclass(frozen=True, slots=True)
class PairedResidualPool:
    """Minutes and points residuals kept together, per historical row.

    Kept together because that pairing *is* the mechanism: drawing the two marginally would
    destroy the minutes-points dependence this phase exists to capture, while leaving every
    marginal distribution looking correct.
    """

    target_fold_id: str
    residuals: pd.DataFrame
    history_fold_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.residuals.empty:
            raise ScenarioValidationError(
                f"No paired conditional residual survives for {self.target_fold_id}."
            )

    def __len__(self) -> int:
        return len(self.residuals)


@dataclass(frozen=True, slots=True)
class ComponentScenarioDraw:
    """A V1 ``ScenarioSet`` plus the per-cell minutes that produced it.

    Minutes ride *beside* the set rather than inside it. ``ScenarioSet.diagnostics`` is
    JSON-compatible metadata by contract and rightly refuses a matrix, and this is not a
    parallel result hierarchy: ``scenarios`` is the same object V1 produces, and
    ``scenario_points`` stays the public decision matrix. The minutes are here because the
    V2 decision scorer needs them for autosubs, and because without them the minutes-points
    pairing cannot be observed from the output at all.
    """

    scenarios: ScenarioSet
    sampled_minutes: pd.DataFrame


def paired_conditional_residuals(
    out_of_fold: pd.DataFrame,
    *,
    target: ScenarioTarget,
    min_history_folds: int = 1,
) -> PairedResidualPool:
    """Build the paired residual pool from Phase C rows strictly before ``target``.

    Pure: it reads a frame and returns a new one. Every exclusion below is a refusal to
    invent, not a convenience:

    - only ``appearance_target == 1`` rows, because a residual conditioned on an appearance
      that did not happen is undefined;
    - a missing conditional target excludes its row rather than being filled with zero;
    - ``direct_control`` rows produce nothing, because they carry no component prediction to
      take a residual against;
    - the target fold cannot appear in its own history, and every history fold must sort
      strictly before it.
    """

    if not isinstance(out_of_fold, pd.DataFrame):
        raise ScenarioValidationError("out_of_fold must be a pandas DataFrame.")
    missing = [name for name in RESIDUAL_SOURCE_COLUMNS if name not in out_of_fold.columns]
    if missing:
        raise ScenarioValidationError(f"Phase C rows are missing {missing!r}.")

    frame = out_of_fold.loc[:, list(RESIDUAL_SOURCE_COLUMNS)].copy(deep=True)
    fold_ids = frame["fold_id"].astype("string")
    if bool((fold_ids == target.fold_id).any()):
        raise ScenarioValidationError(
            f"The target fold {target.fold_id} appears in its own residual history."
        )
    # fold_id is the canonical sortable identifier V1 already uses, so "before" is the same
    # comparison here as there rather than a second chronology rule.
    later = sorted({str(value) for value in fold_ids if str(value) >= target.fold_id})
    if later:
        raise ScenarioValidationError(
            f"Residual history must precede {target.fold_id}; found {later[:5]!r}."
        )

    usable = (
        (frame["composition_route"].astype("string") == COMPONENT_MODEL_ROUTE)
        & (pd.to_numeric(frame["appearance_target"], errors="coerce") == 1)
        & np.isfinite(pd.to_numeric(frame["minutes_target"], errors="coerce"))
        & np.isfinite(pd.to_numeric(frame["points_target"], errors="coerce"))
        & np.isfinite(pd.to_numeric(frame["expected_minutes_if_appearance"], errors="coerce"))
        & np.isfinite(pd.to_numeric(frame["raw_expected_points_if_appearance"], errors="coerce"))
    )
    kept = frame.loc[usable.to_numpy()].copy()
    if kept.empty:
        raise ScenarioValidationError(
            f"No appearance-observed component row precedes {target.fold_id}, so no "
            "conditional residual exists. This is refused rather than filled with zeros."
        )

    kept["minutes_residual"] = pd.to_numeric(kept["minutes_target"]) - pd.to_numeric(
        kept["expected_minutes_if_appearance"]
    )
    kept["points_residual"] = pd.to_numeric(kept["points_target"]) - pd.to_numeric(
        kept["raw_expected_points_if_appearance"]
    )
    # Canonical order, so a caller's row order cannot change the pool or anything drawn from it.
    residuals = (
        kept.loc[:, ["fold_id", "player_id", "minutes_residual", "points_residual"]]
        .astype({"fold_id": "string", "player_id": "int64"})
        .sort_values(["fold_id", "player_id"], kind="stable")
        .reset_index(drop=True)
    )
    history = tuple(sorted({str(value) for value in residuals["fold_id"]}))
    if len(history) < max(1, int(min_history_folds)):
        raise ScenarioValidationError(
            f"{len(history)} history fold(s) precede {target.fold_id}; at least "
            f"{min_history_folds} are required. Refused rather than sampled from too little."
        )
    return PairedResidualPool(
        target_fold_id=target.fold_id,
        residuals=residuals,
        history_fold_ids=history,
    )


def sample_component_scenarios(
    inputs: ComponentScenarioInputs,
    projections: PredictionSnapshot,
    residuals: PairedResidualPool,
    target: ScenarioTarget,
    config: ScenarioConfig | None = None,
) -> ComponentScenarioDraw:
    """Draw appearance, then a paired conditional residual, into a V1-shaped ``ScenarioSet``.

    ``scenario_points`` stays the public decision matrix, in the projection's own player
    order. Sampled minutes ride in ``diagnostics`` because they are an internal by-product:
    promoting them to a second public matrix would create a parallel result hierarchy for the
    optimizer to disagree with.
    """

    settings = config if config is not None else ScenarioConfig()
    if not isinstance(projections, PredictionSnapshot):
        raise ScenarioValidationError("projections must be a PredictionSnapshot.")
    if residuals.target_fold_id != target.fold_id:
        raise ScenarioValidationError(
            f"The residual pool was built for {residuals.target_fold_id}, not {target.fold_id}."
        )
    if inputs.provenance.season == LOCKED_HOLDOUT_SEASON or target.season == LOCKED_HOLDOUT_SEASON:
        raise ScenarioValidationError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and is not sampled."
        )

    projected_ids = tuple(int(value) for value in projections.table["player_id"])
    if inputs.player_ids != projected_ids:
        raise ScenarioValidationError(
            "Component inputs and projections must list the same players in the same order; "
            "the scenario columns carry that order."
        )

    count = int(settings.scenario_count)
    players = len(projected_ids)
    generator = np.random.default_rng(_draw_seed(inputs, target, settings))

    probability = inputs.table["appearance_probability"].to_numpy(dtype="float64")
    mean_minutes = np.nan_to_num(
        inputs.table["expected_minutes_if_appearance"].to_numpy(dtype="float64")
    )
    mean_points = np.nan_to_num(
        inputs.table["raw_expected_points_if_appearance"].to_numpy(dtype="float64")
    )
    ceiling = inputs.table["fixture_count"].to_numpy(dtype="float64") * MINUTES_PER_FIXTURE

    appeared = generator.random((count, players)) < probability[None, :]
    # A blank gameweek has nowhere to play, whatever the probability says.
    appeared &= ceiling[None, :] > 0.0

    minutes_pool = residuals.residuals["minutes_residual"].to_numpy(dtype="float64")
    points_pool = residuals.residuals["points_residual"].to_numpy(dtype="float64")
    # One index per cell, used for *both* residuals: this is what keeps the pair together.
    drawn = generator.integers(0, len(minutes_pool), size=(count, players))

    minutes = np.clip(mean_minutes[None, :] + minutes_pool[drawn], 0.0, ceiling[None, :])
    # Points are not clipped: a negative FPL score is a real outcome, not an error.
    points = mean_points[None, :] + points_pool[drawn]

    minutes = np.where(appeared, minutes, 0.0)
    points = np.where(appeared, points, 0.0)

    scenario_ids = tuple(f"scenario-{index:06d}" for index in range(count))
    matrix = pd.DataFrame(
        points,
        index=pd.Index(scenario_ids, name="scenario_id"),
        columns=list(projections.table["player_id"]),
        dtype="float64",
    )
    # The per-cell minutes ride in diagnostics rather than in a second public matrix. They
    # are here for two reasons: the V2 decision scorer needs them for autosubs, and without
    # them the minutes-points pairing is unobservable from the output -- a test could only
    # check the points marginal, which a marginal draw would also satisfy.
    sampled_minutes = pd.DataFrame(
        minutes,
        index=pd.Index(scenario_ids, name="scenario_id"),
        columns=list(projections.table["player_id"]),
        dtype="float64",
    )
    source_fold_ids = tuple(
        str(value) for value in residuals.residuals["fold_id"].to_numpy()[drawn[:, 0]]
    )
    fingerprint = _scenario_fingerprint(
        projections, target, settings, scenario_ids, source_fold_ids, matrix
    )
    scenario_set = ScenarioSet(
        projections=projections,
        target=target,
        config=settings,
        scenario_ids=scenario_ids,
        source_fold_ids=source_fold_ids,
        scenario_points=matrix,
        scenario_fingerprint=fingerprint,
        diagnostics={
            "component_contract_version": COMPONENT_SCENARIO_CONTRACT_VERSION,
            "appearance_rate": float(appeared.mean()),
            "sampled_minutes_mean": float(minutes.mean()),
            "residual_pool_rows": len(residuals),
            "residual_history_folds": len(residuals.history_fold_ids),
            "point_decomposition_applied": False,
            "phase_c_table_sha": inputs.provenance.phase_c_table_sha,
            "roster_sha": inputs.provenance.roster_sha,
            "model_version": inputs.provenance.model_version,
        },
    )
    return ComponentScenarioDraw(scenarios=scenario_set, sampled_minutes=sampled_minutes)


def _draw_seed(
    inputs: ComponentScenarioInputs, target: ScenarioTarget, config: ScenarioConfig
) -> int:
    """A seed that depends on the declared seed, the target and the input provenance.

    Two different decision weeks drawn under one configured seed should not share a draw
    sequence, and two different input tables should not either.
    """

    payload = "|".join(
        (
            COMPONENT_SCENARIO_CONTRACT_VERSION,
            str(config.deterministic_seed),
            target.fold_id,
            inputs.provenance.phase_c_table_sha,
            inputs.provenance.roster_sha,
            str(inputs.provenance.deterministic_seed),
        )
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)


def component_input_summary(inputs: ComponentScenarioInputs) -> Mapping[str, object]:
    """Counts a caller can log without touching identities."""

    route = inputs.table["composition_route"].astype("string")
    status = inputs.table["evidence_status"].astype("string")
    return {
        "rows": len(inputs.table),
        "component_model_rows": int((route == COMPONENT_MODEL_ROUTE).sum()),
        "direct_control_rows": int((route == DIRECT_CONTROL_ROUTE).sum()),
        "evidence_status_counts": {
            str(name): int(value) for name, value in status.value_counts().items()
        },
    }
