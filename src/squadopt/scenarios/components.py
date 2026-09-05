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
import json
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral
from typing import Final

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype

from squadopt.prediction.components import (
    COMPONENT_EVIDENCE_STATUSES,
    COMPONENT_MODEL_ROUTE,
    COMPONENT_PREDICTION_ROUTES,
    DIRECT_CONTROL_ROUTE,
)
from squadopt.prediction.integration import PredictionSnapshot
from squadopt.scenarios.models import (
    ScenarioConfig,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
    _digest,
    _integer,
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

# The three numbers that *are* the component prediction. A direct-control row must leave all
# three missing; a component-model row must carry all three.
_COMPONENT_VALUE_COLUMNS: Final = (
    "appearance_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
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

# The routes and evidence statuses are the Phase C contract's own
# (``squadopt.prediction.components``), imported rather than re-declared here: a second copy of
# a declared vocabulary is a second contract that can drift from the first. ``direct_control``
# rows carry no component prediction, so no conditional residual exists for them.

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
        if self.contract_version != COMPONENT_SCENARIO_CONTRACT_VERSION:
            raise ScenarioValidationError(
                "contract_version does not match this component scenario implementation; "
                f"expected {COMPONENT_SCENARIO_CONTRACT_VERSION!r}, got {self.contract_version!r}."
            )
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

    # Integral and not bool, following the identifier rule the projection contract already
    # applies. A float identifier is refused rather than truncated: 101.5 silently becoming
    # player 101 would attach one player's residual history to another's row.
    non_integral = [
        value
        for value in frame["player_id"].tolist()
        if isinstance(value, bool) or not isinstance(value, Integral)
    ]
    if non_integral:
        raise ScenarioValidationError(
            "player_id must be an integer that is not a bool; a non-integral identifier is "
            f"refused rather than truncated. Invalid examples: {non_integral[:10]!r}."
        )
    frame["player_id"] = frame["player_id"].astype("int64")

    if bool(frame["player_id"].duplicated().any()):
        duplicated = sorted(
            {int(v) for v in frame.loc[frame["player_id"].duplicated(), "player_id"]}
        )
        raise ScenarioValidationError(
            f"Component scenario inputs list players more than once: {duplicated[:10]!r}."
        )

    route = frame["composition_route"].astype("string")
    unknown_routes = sorted(
        {str(value) for value in route[~route.isin(COMPONENT_PREDICTION_ROUTES)]}
    )
    if unknown_routes:
        raise ScenarioValidationError(
            f"composition_route must be one of {list(COMPONENT_PREDICTION_ROUTES)!r}; "
            f"got {unknown_routes!r}."
        )
    status = frame["evidence_status"].astype("string")
    unknown_status = sorted(
        {str(value) for value in status[~status.isin(COMPONENT_EVIDENCE_STATUSES)]}
    )
    if unknown_status:
        raise ScenarioValidationError(
            f"evidence_status must be one of {list(COMPONENT_EVIDENCE_STATUSES)!r}; "
            f"got {unknown_status!r}. A status is not coined here."
        )

    fixtures = frame["fixture_count"].to_numpy()
    if not np.all(np.equal(np.mod(fixtures.astype("float64"), 1), 0)) or bool(
        np.any(fixtures.astype("float64") < 0)
    ):
        raise ScenarioValidationError(
            "fixture_count must be a non-negative whole number of fixtures."
        )
    frame["fixture_count"] = fixtures.astype("int64")

    # Every numeric component value is coerced once, here, so the rest of the module reads
    # float64 with NaN for "missing" instead of three different pandas null flavours.
    for column in _COMPONENT_VALUE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype="float64")

    component_rows = (route == COMPONENT_MODEL_ROUTE).to_numpy()
    control_rows = (route == DIRECT_CONTROL_ROUTE).to_numpy()

    # The probability bound is checked on component-model rows only, because a direct-control
    # row is required below to carry no probability at all. Checking finiteness on every row
    # would make the two rules contradict each other.
    probability = frame["appearance_probability"].to_numpy(dtype="float64")
    invalid_probability = component_rows & (
        ~np.isfinite(probability) | (probability < 0.0) | (probability > 1.0)
    )
    if bool(np.any(invalid_probability)):
        raise ScenarioValidationError("appearance_probability must be finite and within [0, 1].")

    for column in ("expected_minutes_if_appearance", "raw_expected_points_if_appearance"):
        values = frame[column].to_numpy(dtype="float64")
        if bool(np.any(~np.isfinite(values) & component_rows)):
            raise ScenarioValidationError(
                f"{column} must be finite on every {COMPONENT_MODEL_ROUTE} row; a missing "
                "component value is not filled with zero."
            )

    minutes = frame["expected_minutes_if_appearance"].to_numpy(dtype="float64")
    ceiling = frame["fixture_count"].to_numpy(dtype="float64") * MINUTES_PER_FIXTURE
    out_of_range = component_rows & ((minutes < 0.0) | (minutes > ceiling))
    if bool(np.any(out_of_range)):
        raise ScenarioValidationError(
            "expected_minutes_if_appearance must lie in [0, 90 * fixture_count]."
        )

    # raw_expected_points_if_appearance is deliberately unbounded below: an FPL score can be
    # negative, and a lower bound here would be a claim about the game's rules, not the data.

    # A direct-control row must leave *every* component value missing, not just the minutes.
    # This is the Phase C rule (`squadopt.prediction.components`) applied at this boundary
    # rather than a second one invented here, including its zero-fixture exemption: a blank
    # gameweek is normalized to zeros upstream, so zeros there are not an invented prediction.
    present = np.zeros(len(frame), dtype=bool)
    for column in _COMPONENT_VALUE_COLUMNS:
        present |= np.isfinite(frame[column].to_numpy(dtype="float64"))
    invented = control_rows & present & (frame["fixture_count"].to_numpy() > 0)
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

    def fold_blocks(self) -> tuple[tuple[int, int], ...]:
        """Return each fold's ``(start, size)`` row range, in ``history_fold_ids`` order.

        ``residuals`` is sorted by ``fold_id`` then ``player_id``, so every fold occupies one
        contiguous range and drawing within a fold is a start plus an offset. The boundaries
        are searched for rather than assumed: a pool that was somehow not contiguous is
        refused here instead of yielding a scenario whose cells silently span two folds.
        """

        folds = self.residuals["fold_id"].astype("string").to_numpy(dtype=object)
        wanted = np.array(self.history_fold_ids, dtype=object)
        starts = np.searchsorted(folds, wanted, side="left")
        ends = np.searchsorted(folds, wanted, side="right")
        blocks = tuple(
            (int(start), int(end) - int(start)) for start, end in zip(starts, ends, strict=True)
        )
        if any(size < 1 for _, size in blocks) or sum(size for _, size in blocks) != len(
            self.residuals
        ):
            raise ScenarioValidationError(
                f"The residual pool for {self.target_fold_id} is not one contiguous block per "
                "fold, so a per-scenario fold draw cannot be bounded to a single fold."
            )
        return blocks


def _component_fingerprint(
    scenarios: ScenarioSet,
    inputs: "ComponentScenarioInputs",
    sampled_minutes: pd.DataFrame,
    sampled_appearances: pd.DataFrame,
) -> str:
    """Digest the V1 identity, both sampled matrices and the component provenance together.

    Small and private on purpose. It follows ``_scenario_fingerprint``'s shape -- canonical
    JSON metadata, then the raw bytes of each matrix -- rather than introducing a general
    fingerprint mechanism this phase has no second use for.

    The minutes and the appearance bytes are both inside the digest because the autosub
    decision is taken from them: two draws with a byte-identical points matrix but a different
    minute or a different appearance are different results, and must not be able to share an
    identity. Both shapes are pinned by the metadata, so appending one block after the other
    is unambiguous.
    """

    provenance = inputs.provenance
    metadata = {
        "component_contract_version": inputs.contract_version,
        "scenario_fingerprint": scenarios.scenario_fingerprint,
        "phase_c_table_sha": provenance.phase_c_table_sha,
        "roster_sha": provenance.roster_sha,
        "model_version": provenance.model_version,
        "feature_contract_version": provenance.feature_contract_version,
        "target_season": scenarios.target.season,
        "target_gameweek": scenarios.target.gameweek,
        "fixture_counts": [int(value) for value in inputs.table["fixture_count"]],
    }
    digest = hashlib.sha256(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(sampled_minutes.to_numpy(dtype="<f8", copy=True).tobytes(order="C"))
    digest.update(sampled_appearances.to_numpy(dtype=bool, copy=True).tobytes(order="C"))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ComponentScenarioDraw:
    """A V1 ``ScenarioSet``, the per-cell minutes that produced it, and one identity for both.

    Minutes ride *beside* the set rather than inside it. ``ScenarioSet.diagnostics`` is
    JSON-compatible metadata by contract and rightly refuses a matrix, and this is not a
    parallel result hierarchy: ``scenarios`` is the same object V1 produces, and
    ``scenario_points`` stays the public decision matrix. The minutes are here because the
    V2 decision scorer needs them for autosubs, and because without them the minutes-points
    pairing cannot be observed from the output at all.

    ``inputs`` rides along because the two checks that belong here need it: the ``[0, 90 *
    fixture_count]`` bound needs the per-player fixture counts, and the digest needs the
    component provenance. Both are already validated and copied on that object, so carrying it
    restates nothing.

    ``sampled_appearances`` is the sampler's own Bernoulli state, published rather than left
    to be inferred. Because the conditional minute draw is clipped, ``sampled_minutes == 0``
    cannot on its own separate a player who did not feature from one who did and whose minute
    draw fell below zero -- and a decision scorer decides autosub on exactly that difference.
    Reconstructing it from ``minutes > 0`` would make the scorer's answer depend on an
    inference this object already knows the truth of.

    ``component_fingerprint`` is recomputed and compared on construction, so a matrix and an
    identity cannot be paired by assertion. ``ScenarioSet``'s own V1 fingerprint behaviour is
    untouched.
    """

    scenarios: ScenarioSet
    inputs: "ComponentScenarioInputs"
    sampled_minutes: pd.DataFrame
    sampled_appearances: pd.DataFrame
    component_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.scenarios, ScenarioSet):
            raise ScenarioValidationError("scenarios must be a ScenarioSet.")
        if not isinstance(self.inputs, ComponentScenarioInputs):
            raise ScenarioValidationError("inputs must be ComponentScenarioInputs.")
        if not isinstance(self.sampled_minutes, pd.DataFrame):
            raise ScenarioValidationError("sampled_minutes must be a pandas DataFrame.")
        if not isinstance(self.sampled_appearances, pd.DataFrame):
            raise ScenarioValidationError("sampled_appearances must be a pandas DataFrame.")

        points = self.scenarios.scenario_points
        # Copied before anything is checked, so a later edit to the caller's frame cannot
        # change what the bound and the fingerprint were verified against.
        minutes = self.sampled_minutes.copy(deep=True)
        if minutes.shape != points.shape:
            raise ScenarioValidationError(
                "sampled_minutes shape must equal the scenario points matrix."
            )
        if tuple(minutes.index.tolist()) != self.scenarios.scenario_ids:
            raise ScenarioValidationError("sampled_minutes index must equal scenario_ids.")
        if tuple(minutes.columns.tolist()) != tuple(points.columns.tolist()):
            raise ScenarioValidationError(
                "sampled_minutes columns must exactly align with the scenario points columns."
            )
        # Compared as text so a numpy identifier and a Python one are not a false mismatch.
        # This binds the columns to the *input rows* rather than only to the points columns,
        # because the ceiling below is per player and is read off those rows.
        if tuple(str(value) for value in minutes.columns) != tuple(
            str(value) for value in self.inputs.table["player_id"]
        ):
            raise ScenarioValidationError(
                "sampled_minutes columns must align with the component input player order; the "
                "minutes ceiling is read per player from those rows."
            )
        try:
            minutes = minutes.astype("float64")
        except (TypeError, ValueError) as error:
            raise ScenarioValidationError("sampled_minutes must be numeric.") from error

        values = minutes.to_numpy(dtype="float64")
        if not bool(np.isfinite(values).all()):
            raise ScenarioValidationError("sampled_minutes must be finite.")
        ceiling = self.inputs.table["fixture_count"].to_numpy(dtype="float64") * MINUTES_PER_FIXTURE
        if bool(np.any((values < 0.0) | (values > ceiling[None, :]))):
            raise ScenarioValidationError(
                "sampled_minutes must lie in [0, 90 * fixture_count]; a minute outside the "
                "calendar is not a playable outcome."
            )

        # Copied before it is checked, for the same reason the minutes are.
        appearances = self.sampled_appearances.copy(deep=True)
        if appearances.shape != points.shape:
            raise ScenarioValidationError(
                "sampled_appearances shape must equal the scenario points matrix."
            )
        if tuple(appearances.index.tolist()) != self.scenarios.scenario_ids:
            raise ScenarioValidationError("sampled_appearances index must equal scenario_ids.")
        if tuple(appearances.columns.tolist()) != tuple(points.columns.tolist()):
            raise ScenarioValidationError(
                "sampled_appearances columns must exactly align with the scenario points columns."
            )
        # Deliberately the same rule the decision scorer applies to this frame, so a frame that
        # satisfies the producer satisfies the consumer: complete, and boolean rather than a
        # 0/1 integer or an object column that merely looks like one.
        if bool(appearances.isna().any().any()) or any(
            not is_bool_dtype(dtype) for dtype in appearances.dtypes
        ):
            raise ScenarioValidationError(
                "sampled_appearances must contain complete boolean Bernoulli states; a missing, "
                "numeric or minutes-derived value is refused."
            )
        appearances = appearances.astype("bool")

        # The three ways the appearance state and the two outcome matrices could contradict
        # each other. Each is a real disagreement, not a style rule: a consumer reading one
        # matrix would draw a conclusion the other matrix denies.
        appeared = appearances.to_numpy(dtype=bool)
        point_values = points.to_numpy(dtype="float64")
        if bool(np.any(appeared & (ceiling[None, :] <= 0.0))):
            raise ScenarioValidationError(
                "sampled_appearances marks an appearance in a blank gameweek; with no fixture "
                "there is nowhere to play, whatever the probability says."
            )
        if bool(np.any(~appeared & ((values != 0.0) | (point_values != 0.0)))):
            raise ScenarioValidationError(
                "a non-appearance must score exactly zero minutes and exactly zero points; a "
                "player who did not feature scored nothing rather than approximately nothing."
            )
        if bool(np.any(appeared & (values <= 0.0))):
            raise ScenarioValidationError(
                "sampled_appearances marks an appearance with no minutes; the published minutes "
                "may not contradict the published appearance state."
            )

        fingerprint = _digest(self.component_fingerprint, "component_fingerprint")
        if fingerprint != _component_fingerprint(self.scenarios, self.inputs, minutes, appearances):
            raise ScenarioValidationError(
                "component_fingerprint does not match the scenario matrices and provenance."
            )
        object.__setattr__(self, "sampled_minutes", minutes)
        object.__setattr__(self, "sampled_appearances", appearances)
        object.__setattr__(self, "component_fingerprint", fingerprint)


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
    # Reuses the scenario config's own integer rule, so a bool, a float or a negative is a
    # named refusal rather than a silent ``max(1, int(...))`` coercion.
    required = _integer(min_history_folds, "min_history_folds", 1)
    history = tuple(sorted({str(value) for value in residuals["fold_id"]}))
    if len(history) < required:
        raise ScenarioValidationError(
            f"{len(history)} history fold(s) precede {target.fold_id}; at least "
            f"{required} are required. Refused rather than sampled from too little."
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
    order. The per-cell minutes and the per-cell Bernoulli appearance state are returned beside
    it as ``ComponentScenarioDraw.sampled_minutes`` and ``.sampled_appearances``, not inside
    ``ScenarioSet.diagnostics``: that field is JSON-compatible metadata by contract and cannot
    hold a matrix. The appearance state is published rather than inferred, because a clipped
    minute cannot distinguish a non-appearance from an appearance drawn below zero.

    One source fold is chosen per scenario, and every cell of that scenario draws its paired
    residual from a row of that fold alone. That is what makes ``source_fold_ids`` a fact
    about the scenario rather than a label taken from whichever player happened to be first.
    """

    settings = config if config is not None else ScenarioConfig()
    if not isinstance(inputs, ComponentScenarioInputs):
        raise ScenarioValidationError("inputs must be ComponentScenarioInputs.")
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

    # The inputs' own decision week has to be the one being sampled. A set whose provenance
    # names a different week cannot be traced back to the Phase C rows it claims to come from.
    if inputs.provenance.season != target.season:
        raise ScenarioValidationError(
            f"The component inputs name season {inputs.provenance.season!r}, but the target is "
            f"{target.season!r}."
        )
    if inputs.provenance.target_gameweek != target.gameweek:
        raise ScenarioValidationError(
            f"The component inputs name gameweek {inputs.provenance.target_gameweek}, but the "
            f"target is gameweek {target.gameweek}."
        )

    # Direct-control rows fail closed. No exact-key control fallback is bound in this
    # foundation, and the only alternative available here -- reading a missing component value
    # as zero -- would publish a prediction of nothing for a player nothing is predicted for.
    control = int(
        (inputs.table["composition_route"].astype("string") == DIRECT_CONTROL_ROUTE).sum()
    )
    if control:
        raise ScenarioValidationError(
            f"{control} {DIRECT_CONTROL_ROUTE} row(s) cannot be sampled: they carry no component "
            "prediction, and no exact-key control fallback is bound in this foundation. Refused "
            "rather than sampled as zero."
        )

    projected_ids = tuple(int(value) for value in projections.table["player_id"])
    if inputs.player_ids != projected_ids:
        raise ScenarioValidationError(
            "Component inputs and projections must list the same players in the same order; "
            "the scenario columns carry that order."
        )
    # The roster fields the caller joined onto the Phase C table must be the projection's own.
    # Compared as text so a numpy identifier and a Python one are not a false mismatch.
    for column in ("team_id", "position"):
        if [str(value) for value in inputs.table[column]] != [
            str(value) for value in projections.table[column]
        ]:
            raise ScenarioValidationError(
                f"Component inputs and projections disagree on {column}; the component table's "
                "roster fields must be the projection's own, not a stale join."
            )
    # Provenance the two artifacts both carry must agree. ``PredictionProvenance`` has no
    # dataset or target contract field, so ``dataset_contract_version`` and
    # ``target_contract_version`` are recorded but not cross-checked -- inventing a field to
    # compare them against would fabricate the agreement rather than verify it.
    if inputs.provenance.model_version != projections.provenance.model_version:
        raise ScenarioValidationError(
            f"model_version disagrees: the component inputs say "
            f"{inputs.provenance.model_version!r}, the projections say "
            f"{projections.provenance.model_version!r}."
        )
    if (
        inputs.provenance.feature_contract_version
        != projections.provenance.feature_contract_version
    ):
        raise ScenarioValidationError(
            f"feature_contract_version disagrees: the component inputs say "
            f"{inputs.provenance.feature_contract_version!r}, the projections say "
            f"{projections.provenance.feature_contract_version!r}."
        )

    count = int(settings.scenario_count)
    players = len(projected_ids)
    generator = np.random.default_rng(_draw_seed(inputs, target, settings))

    probability = inputs.table["appearance_probability"].to_numpy(dtype="float64")
    # No ``nan_to_num`` here. Every surviving row is a component-model row whose conditional
    # means the input contract already proved finite, so there is nothing to fill -- and
    # filling would be the bug: zero is a prediction, not the absence of one.
    mean_minutes = inputs.table["expected_minutes_if_appearance"].to_numpy(dtype="float64")
    mean_points = inputs.table["raw_expected_points_if_appearance"].to_numpy(dtype="float64")
    ceiling = inputs.table["fixture_count"].to_numpy(dtype="float64") * MINUTES_PER_FIXTURE

    appeared = generator.random((count, players)) < probability[None, :]
    # A blank gameweek has nowhere to play, whatever the probability says.
    appeared &= ceiling[None, :] > 0.0

    # One source fold per scenario, then one row *within that fold* per player. Drawing each
    # cell from the whole pool while the set names a single source fold would make
    # ``source_fold_ids`` true only by accident; here the block is the constraint, so the
    # field is a fact. The chosen fold is a block-bootstrap boundary and nothing more: no
    # common or team shock is layered on top of it, and no team or position fallback
    # hierarchy is introduced.
    history = residuals.history_fold_ids
    blocks = residuals.fold_blocks()
    starts = np.array([start for start, _ in blocks], dtype="int64")
    sizes = np.array([size for _, size in blocks], dtype="int64")
    chosen = generator.integers(0, len(history), size=count)
    offsets = generator.integers(0, sizes[chosen][:, None], size=(count, players))
    drawn = starts[chosen][:, None] + offsets

    minutes_pool = residuals.residuals["minutes_residual"].to_numpy(dtype="float64")
    points_pool = residuals.residuals["points_residual"].to_numpy(dtype="float64")
    # An appearance is floored at one minute rather than zero. Not a claim that match minutes
    # are integral: it is what stops the published minutes from contradicting the published
    # appearance, since a cell reading zero minutes *and* appeared would leave every consumer
    # to reconcile the two. ``appeared`` already implies a non-zero ceiling, so the floor can
    # never exceed it. The cost is disclosed rather than corrected: this shifts the conditional
    # minutes mean slightly upward on exactly the cells the zero clip was already distorting.
    floor = np.where(appeared, 1.0, 0.0)
    # One index per cell, used for *both* residuals: this is what keeps the pair together.
    minutes = np.clip(mean_minutes[None, :] + minutes_pool[drawn], floor, ceiling[None, :])
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
    # The per-cell minutes ride beside the set, not inside its diagnostics: that field is
    # JSON-compatible metadata by contract. They are published for two reasons -- the V2
    # decision scorer needs them for autosubs, and without them the minutes-points pairing is
    # unobservable from the output, so a test could only check the points marginal, which a
    # marginal draw would also satisfy.
    sampled_minutes = pd.DataFrame(
        minutes,
        index=pd.Index(scenario_ids, name="scenario_id"),
        columns=list(projections.table["player_id"]),
        dtype="float64",
    )
    # The Bernoulli state itself, published rather than left to be recovered from the minutes.
    # A clipped continuous quantity cannot separate "did not feature" from "featured, and the
    # minute draw fell below zero", and the autosub decision turns on precisely that.
    sampled_appearances = pd.DataFrame(
        appeared,
        index=pd.Index(scenario_ids, name="scenario_id"),
        columns=list(projections.table["player_id"]),
        dtype="bool",
    )
    # The fold each scenario actually drew from, not the fold of whichever player came first.
    source_fold_ids = tuple(history[int(index)] for index in chosen)
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
    return ComponentScenarioDraw(
        scenarios=scenario_set,
        inputs=inputs,
        sampled_minutes=sampled_minutes,
        sampled_appearances=sampled_appearances,
        component_fingerprint=_component_fingerprint(
            scenario_set, inputs, sampled_minutes, sampled_appearances
        ),
    )


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
