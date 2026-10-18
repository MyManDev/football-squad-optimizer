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
import math
from collections import Counter
from dataclasses import dataclass
from numbers import Integral
from typing import Final

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype

from squadopt.evaluation.component_handoff import DEVELOPMENT_OOF_CONTRACT_VERSION
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
CONDITIONAL_RESIDUAL_CONTRACT_VERSION: Final = "component_scenario_conditional_residual_v1"
TEAM_MATCH_BLOCK_CONTRACT_VERSION: Final = "team_match_block_v1"
TEAM_MATCH_JOINT_CONTRACT_VERSION: Final = "team_match_joint_v1"
# ScenarioConfig fields the component sampler does not read; recorded on every draw so a
# reader of the config block cannot take them for applied settings.
UNUSED_SCENARIO_CONFIG_FIELDS: Final = (
    "min_player_observations",
    "player_scale_shrinkage",
    "player_location_shrinkage",
    "double_gameweek_scale",
)

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

# The source fields a club-week block is built from, per pool row. Read only for the
# ``team_match_block`` candidate: the v1 OOF table carries ``fixture_count`` but takes
# ``team_id`` and ``position`` from the decision roster, so the caller supplies that join and
# the foundation pool keeps accepting a frame without them.
TEAM_MATCH_BLOCK_SOURCE_COLUMNS: Final = ("team_id", "position", "fixture_count")
# The joint pool reads the appearance probability of every history row as well: a row's
# observed appearance and the probability it was given are what the joint draw inherits.
TEAM_MATCH_JOINT_SOURCE_COLUMNS: Final = (
    *RESIDUAL_SOURCE_COLUMNS,
    *TEAM_MATCH_BLOCK_SOURCE_COLUMNS,
    "appearance_probability",
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
    # ``None`` is the frozen path and refuses the locked holdout outright. Naming the Phase C
    # v2 development contract is the one explicit way to sample a 2025-26 decision, and it
    # marks the draw's identity so a development draw can never pass for a frozen one.
    development_contract: str | None = None

    def __post_init__(self) -> None:
        if (
            self.development_contract is not None
            and self.development_contract != DEVELOPMENT_OOF_CONTRACT_VERSION
        ):
            raise ScenarioValidationError(
                f"Unsupported development contract {self.development_contract!r}; only "
                f"{DEVELOPMENT_OOF_CONTRACT_VERSION!r} admits development scenarios."
            )
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
        if self.season == LOCKED_HOLDOUT_SEASON and self.development_contract is None:
            raise ScenarioValidationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout; component scenarios are not "
                "built, listed or fingerprinted for it outside the declared development path."
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
    # Added only on the development path, so every frozen fingerprint stays byte-identical.
    if provenance.development_contract is not None:
        metadata["development_contract"] = provenance.development_contract
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


@dataclass(frozen=True, slots=True)
class ConditionalResidualConfig:
    """Opt-in: draw each player's paired residual from history rows of similar expectation.

    Inside the scenario's source fold the rows are ordered by their own conditional
    expectation (``raw_expected_points_if_appearance``) and a player draws uniformly from the
    ``size`` rows nearest in rank to their expectation, where ``size = max(minimum_rows,
    ceil(fraction * rows_in_fold))``. A fold with no more rows than ``size`` is used whole, and
    that fallback is counted in the draw's diagnostics rather than hidden.

    Everything else is the foundation sampler: the appearance draw, the one-fold-per-scenario
    block, the minutes-points pairing, the seed stream and its order. Only *which row within
    the fold* a cell may take changes, so a draw with and without this config shares its
    appearances and source folds seed for seed.
    """

    fraction: float = 0.15
    minimum_rows: int = 30
    contract_version: str = CONDITIONAL_RESIDUAL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != CONDITIONAL_RESIDUAL_CONTRACT_VERSION:
            raise ScenarioValidationError(
                "contract_version does not match the conditional residual implementation."
            )
        if (
            isinstance(self.fraction, bool)
            or not isinstance(self.fraction, int | float)
            or not math.isfinite(float(self.fraction))
            or not 0.0 < float(self.fraction) <= 1.0
        ):
            raise ScenarioValidationError("fraction must be a finite number in (0, 1].")
        object.__setattr__(self, "fraction", float(self.fraction))
        if (
            isinstance(self.minimum_rows, bool)
            or not isinstance(self.minimum_rows, Integral)
            or int(self.minimum_rows) < 2
        ):
            raise ScenarioValidationError("minimum_rows must be an integer of at least 2.")
        object.__setattr__(self, "minimum_rows", int(self.minimum_rows))

    def window_rows(self, fold_rows: int) -> int:
        """Rows a player may draw from in a fold of ``fold_rows``; the whole fold when small."""

        return min(fold_rows, max(self.minimum_rows, math.ceil(self.fraction * fold_rows)))


@dataclass(frozen=True, slots=True)
class TeamMatchBlockConfig:
    """Opt-in: a club-week block inside the scenario's source fold.

    The foundation draws every player's paired residual row independently from the source
    fold, which destroys the within-club co-movement of residuals: a club that scores four
    lifts every attacker, a clean sheet lifts every defender. Under this config each target
    club draws one source club-week block of the chosen fold, preferring a block whose fixture
    count equals the club's own that week, and each of its players draws one row of that block
    with the same position, falling back to any row of the block. Both fallbacks are counted.

    There is no tunable number. Everything else is the foundation sampler: the appearance draw,
    the one-fold-per-scenario block, the minutes-points pairing, the seed stream and its order.
    The pool must carry ``TEAM_MATCH_BLOCK_SOURCE_COLUMNS`` per row, which
    ``paired_conditional_residuals`` keeps only when given this config.
    """

    contract_version: str = TEAM_MATCH_BLOCK_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != TEAM_MATCH_BLOCK_CONTRACT_VERSION:
            raise ScenarioValidationError(
                "contract_version does not match the team-match block implementation."
            )


@dataclass(frozen=True, slots=True)
class TeamMatchJointConfig:
    """Opt-in: the appearance and the paired residual drawn from one club-week block.

    ``TeamMatchBlockConfig`` keeps the foundation's per-player appearance Bernoulli and draws
    only the residual from a club-week block, so a source week in which a club rested six
    starters lifts no co-movement into the target squad's appearances. Under this config a
    player's appearance is inherited from the source row's own observed appearance through
    its latent uniform (``u = v * p_s`` when the row appeared, ``p_s + v * (1 - p_s)`` when it
    did not; the target appears iff ``u < p_t``), so the zero atom and the club co-movement
    come from one draw, and the conditional residual is drawn within the same block.

    There is no tunable number. The pool must be a ``TeamMatchJointPool``, which keeps the
    non-appearance rows the paired residual pool drops; nothing else may draw from one.
    """

    contract_version: str = TEAM_MATCH_JOINT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != TEAM_MATCH_JOINT_CONTRACT_VERSION:
            raise ScenarioValidationError(
                "contract_version does not match the team-match joint implementation."
            )


@dataclass(frozen=True, slots=True)
class TeamMatchJointPool(PairedResidualPool):
    """History rows for the joint draw: appeared rows with their paired residuals and the
    non-appeared rows beside them, each carrying its observed appearance and the probability
    it was given. A non-appeared row's residuals are missing, never zero, and the draw never
    reads them as residuals. ``excluded_rows`` counts what the builder refused, by reason."""

    excluded_rows: tuple[tuple[str, int], ...] = ()


def team_match_joint_pool(
    out_of_fold: pd.DataFrame,
    *,
    target: ScenarioTarget,
    min_history_folds: int = 1,
) -> TeamMatchJointPool:
    """Build the joint pool from Phase C rows strictly before ``target``.

    Pure, like ``paired_conditional_residuals``, with the same chronology rule and the same
    canonical order, and the same refusals to invent: a ``direct_control`` row produces
    nothing; an appearance target outside {0, 1} or a probability outside [0, 1] excludes its
    row; a missing club, position or fixture count excludes its row; a row with no fixture has
    nowhere to appear and is excluded; an appeared row with a missing conditional target is
    excluded rather than filled. Every exclusion is counted on the pool. A history fold with no
    appeared row is dropped, so the history folds are those of the paired residual pool.
    """

    if not isinstance(out_of_fold, pd.DataFrame):
        raise ScenarioValidationError("out_of_fold must be a pandas DataFrame.")
    missing = [name for name in TEAM_MATCH_JOINT_SOURCE_COLUMNS if name not in out_of_fold.columns]
    if missing:
        raise ScenarioValidationError(f"Phase C rows are missing {missing!r}.")
    frame = out_of_fold.loc[:, list(TEAM_MATCH_JOINT_SOURCE_COLUMNS)].copy(deep=True)
    fold_ids = frame["fold_id"].astype("string")
    if bool((fold_ids == target.fold_id).any()):
        raise ScenarioValidationError(
            f"The target fold {target.fold_id} appears in its own residual history."
        )
    later = sorted({str(value) for value in fold_ids if str(value) >= target.fold_id})
    if later:
        raise ScenarioValidationError(
            f"Residual history must precede {target.fold_id}; found {later[:5]!r}."
        )

    # Read as plain float arrays with NaN for a missing value, whatever nullable dtype the
    # caller's frame carries: every comparison below then treats a missing value as refused.
    def numbers(name: str) -> np.ndarray:
        return pd.to_numeric(frame[name], errors="coerce").to_numpy(
            dtype="float64", na_value=np.nan
        )

    route = (frame["composition_route"].astype("string") == COMPONENT_MODEL_ROUTE).to_numpy(
        dtype=bool, na_value=False
    )
    appearance = numbers("appearance_target")
    probability = numbers("appearance_probability")
    fixtures = numbers("fixture_count")
    minutes_mean = numbers("expected_minutes_if_appearance")
    points_mean = numbers("raw_expected_points_if_appearance")
    minutes_target = numbers("minutes_target")
    points_target = numbers("points_target")
    appeared = appearance == 1.0
    block_fields = (
        frame.loc[:, list(TEAM_MATCH_BLOCK_SOURCE_COLUMNS)]
        .isna()
        .any(axis=1)
        .to_numpy(dtype=bool, na_value=True)
    )
    # Each reason is read on the rows the earlier reasons admitted, so a row is counted once.
    reasons: tuple[tuple[str, np.ndarray], ...] = (
        ("direct_control_rows", ~route),
        ("appearance_target_not_binary", ~np.isin(appearance, (0.0, 1.0))),
        (
            "appearance_probability_outside_unit_interval",
            ~((probability >= 0.0) & (probability <= 1.0)),
        ),
        ("block_field_missing", block_fields | ~np.isfinite(fixtures)),
        ("no_fixture", ~(fixtures >= 1.0)),
        ("conditional_mean_missing", ~(np.isfinite(minutes_mean) & np.isfinite(points_mean))),
        (
            "appeared_target_missing",
            appeared & ~(np.isfinite(minutes_target) & np.isfinite(points_target)),
        ),
    )
    admitted = np.ones(len(frame), dtype=bool)
    excluded: list[tuple[str, int]] = []
    for reason, refused in reasons:
        hit = admitted & refused
        excluded.append((reason, int(hit.sum())))
        admitted &= ~hit
    kept = frame.loc[admitted].copy()
    if kept.empty:
        raise ScenarioValidationError(
            f"No component row precedes {target.fold_id}, so no joint draw exists. This is "
            "refused rather than filled with zeros."
        )
    kept_appeared = (pd.to_numeric(kept["appearance_target"]) == 1).to_numpy(dtype=bool)
    kept["minutes_residual"] = np.where(
        kept_appeared,
        pd.to_numeric(kept["minutes_target"]).to_numpy(dtype="float64")
        - pd.to_numeric(kept["expected_minutes_if_appearance"]).to_numpy(dtype="float64"),
        np.nan,
    )
    kept["points_residual"] = np.where(
        kept_appeared,
        pd.to_numeric(kept["points_target"]).to_numpy(dtype="float64")
        - pd.to_numeric(kept["raw_expected_points_if_appearance"]).to_numpy(dtype="float64"),
        np.nan,
    )
    kept["appearance_target"] = pd.to_numeric(kept["appearance_target"]).astype("int64")
    kept["fixture_count"] = pd.to_numeric(kept["fixture_count"]).astype("int64")
    residuals = (
        kept.loc[
            :,
            [
                "fold_id",
                "player_id",
                "minutes_residual",
                "points_residual",
                "raw_expected_points_if_appearance",
                *TEAM_MATCH_BLOCK_SOURCE_COLUMNS,
                "appearance_target",
                "appearance_probability",
            ],
        ]
        .astype(
            {
                "fold_id": "string",
                "player_id": "int64",
                "raw_expected_points_if_appearance": "float64",
                "team_id": "string",
                "position": "string",
                "appearance_probability": "float64",
            }
        )
        .sort_values(["fold_id", "player_id"], kind="stable")
        .reset_index(drop=True)
    )
    # A fold with rows but no appearance has no residual to draw for anyone who appears, so it
    # leaves the history; the folds that remain are the paired residual pool's own.
    appeared_folds = {
        str(value)
        for value in residuals.loc[residuals["appearance_target"] == 1, "fold_id"].unique()
    }
    in_history = residuals["fold_id"].isin(appeared_folds).to_numpy(dtype=bool)
    excluded.append(("rows_of_folds_without_appearance", int((~in_history).sum())))
    residuals = residuals.loc[in_history].reset_index(drop=True)
    if residuals.empty:
        raise ScenarioValidationError(
            f"No appearance-observed component row precedes {target.fold_id}, so no "
            "conditional residual exists. This is refused rather than filled with zeros."
        )
    required = _integer(min_history_folds, "min_history_folds", 1)
    history = tuple(sorted(appeared_folds))
    if len(history) < required:
        raise ScenarioValidationError(
            f"{len(history)} history fold(s) precede {target.fold_id}; at least "
            f"{required} are required. Refused rather than sampled from too little."
        )
    return TeamMatchJointPool(
        target_fold_id=target.fold_id,
        residuals=residuals,
        history_fold_ids=history,
        excluded_rows=tuple(excluded),
    )


def paired_conditional_residuals(
    out_of_fold: pd.DataFrame,
    *,
    target: ScenarioTarget,
    min_history_folds: int = 1,
    team_match_block: TeamMatchBlockConfig | None = None,
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

    ``team_match_block`` additionally keeps each row's source ``team_id``, ``position`` and
    ``fixture_count`` for the club-week blocks, and refuses a frame missing any of them. The
    row filter and the canonical order are the same either way, so a pool built with it draws
    the foundation sampler exactly as one built without.
    """

    if not isinstance(out_of_fold, pd.DataFrame):
        raise ScenarioValidationError("out_of_fold must be a pandas DataFrame.")
    if team_match_block is not None and not isinstance(team_match_block, TeamMatchBlockConfig):
        raise ScenarioValidationError("team_match_block must be a TeamMatchBlockConfig or None.")
    block_columns = TEAM_MATCH_BLOCK_SOURCE_COLUMNS if team_match_block is not None else ()
    missing = [
        name
        for name in (*RESIDUAL_SOURCE_COLUMNS, *block_columns)
        if name not in out_of_fold.columns
    ]
    if missing:
        raise ScenarioValidationError(f"Phase C rows are missing {missing!r}.")

    frame = out_of_fold.loc[:, [*RESIDUAL_SOURCE_COLUMNS, *block_columns]].copy(deep=True)
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
    if block_columns:
        if bool(kept.loc[:, list(block_columns)].isna().any().any()):
            raise ScenarioValidationError(
                "A club-week block needs team_id, position and fixture_count on every row; a "
                "missing value is refused rather than grouped as a club of its own."
            )
        kept["fixture_count"] = pd.to_numeric(kept["fixture_count"]).astype("int64")
    residuals = (
        kept.loc[
            :,
            [
                "fold_id",
                "player_id",
                "minutes_residual",
                "points_residual",
                "raw_expected_points_if_appearance",
                *block_columns,
            ],
        ]
        .astype(
            {
                "fold_id": "string",
                "player_id": "int64",
                "raw_expected_points_if_appearance": "float64",
                **({"team_id": "string", "position": "string"} if block_columns else {}),
            }
        )
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
    *,
    conditional_residuals: ConditionalResidualConfig | None = None,
    team_match_block: TeamMatchBlockConfig | None = None,
    team_match_joint: TeamMatchJointConfig | None = None,
) -> ComponentScenarioDraw:
    """Draw appearance, then a paired conditional residual, into a V1-shaped ``ScenarioSet``.

    ``conditional_residuals`` is the opt-in candidate of ``ConditionalResidualConfig`` and
    ``team_match_block`` the opt-in candidate of ``TeamMatchBlockConfig``; they are mutually
    exclusive, and with both left as ``None`` (the default) this is the frozen foundation
    sampler, bit for bit.

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
    if conditional_residuals is not None and not isinstance(
        conditional_residuals, ConditionalResidualConfig
    ):
        raise ScenarioValidationError(
            "conditional_residuals must be a ConditionalResidualConfig or None."
        )
    if team_match_block is not None and not isinstance(team_match_block, TeamMatchBlockConfig):
        raise ScenarioValidationError("team_match_block must be a TeamMatchBlockConfig or None.")
    if conditional_residuals is not None and team_match_block is not None:
        raise ScenarioValidationError(
            "conditional_residuals and team_match_block are two candidate samplers; a draw "
            "declares one or neither, never both."
        )
    if team_match_joint is not None and not isinstance(team_match_joint, TeamMatchJointConfig):
        raise ScenarioValidationError("team_match_joint must be a TeamMatchJointConfig or None.")
    if team_match_joint is not None and (
        conditional_residuals is not None or team_match_block is not None
    ):
        raise ScenarioValidationError(
            "team_match_joint is a candidate sampler of its own; a draw declares one candidate "
            "or none, never two."
        )
    # The joint pool carries non-appearance rows whose residuals are missing, so no other
    # sampler may draw from one, and the joint sampler draws from nothing else.
    if (team_match_joint is not None) != isinstance(residuals, TeamMatchJointPool):
        raise ScenarioValidationError(
            "team_match_joint draws on a TeamMatchJointPool and no other sampler does; build "
            "the pool with team_match_joint_pool for the joint sampler and with "
            "paired_conditional_residuals otherwise."
        )
    if not isinstance(projections, PredictionSnapshot):
        raise ScenarioValidationError("projections must be a PredictionSnapshot.")
    if residuals.target_fold_id != target.fold_id:
        raise ScenarioValidationError(
            f"The residual pool was built for {residuals.target_fold_id}, not {target.fold_id}."
        )
    if inputs.provenance.development_contract is None and (
        inputs.provenance.season == LOCKED_HOLDOUT_SEASON or target.season == LOCKED_HOLDOUT_SEASON
    ):
        raise ScenarioValidationError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and is not sampled outside the "
            "declared development path."
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

    history = residuals.history_fold_ids
    if team_match_joint is not None and isinstance(residuals, TeamMatchJointPool):
        # The appearance is part of the joint draw, so the cell helper returns it beside the
        # source fold and the residual row; the stream order is documented there.
        appeared, chosen, drawn, selection_diagnostics = _team_match_joint_cells(
            generator, residuals, inputs.table, probability, ceiling, count, team_match_joint
        )
    else:
        appeared = generator.random((count, players)) < probability[None, :]
        # A blank gameweek has nowhere to play, whatever the probability says.
        appeared &= ceiling[None, :] > 0.0

        # One source fold per scenario, then one row *within that fold* per player. Drawing
        # each cell from the whole pool while the set names a single source fold would make
        # ``source_fold_ids`` true only by accident; here the block is the constraint, so the
        # field is a fact. The chosen fold is a block-bootstrap boundary and nothing more: no
        # common or team shock is layered on top of it, and no team or position fallback
        # hierarchy is introduced.
        blocks = residuals.fold_blocks()
        starts = np.array([start for start, _ in blocks], dtype="int64")
        sizes = np.array([size for _, size in blocks], dtype="int64")
        chosen = generator.integers(0, len(history), size=count)
        if conditional_residuals is not None:
            drawn, selection_diagnostics = _conditional_rows(
                generator, residuals, blocks, chosen, mean_points, conditional_residuals
            )
        elif team_match_block is not None:
            drawn, selection_diagnostics = _team_match_block_rows(
                generator, residuals, blocks, chosen, inputs.table, team_match_block
            )
        else:
            offsets = generator.integers(0, sizes[chosen][:, None], size=(count, players))
            drawn = starts[chosen][:, None] + offsets
            selection_diagnostics = {
                "component_sampler_contract_version": COMPONENT_SCENARIO_CONTRACT_VERSION,
                "residual_selection": "fold_uniform",
            }

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
            **selection_diagnostics,
            "effective_settings": {
                "scenario_count": settings.scenario_count,
                "deterministic_seed": settings.deterministic_seed,
                "min_history_folds": "applied by paired_conditional_residuals, not here",
                "unused_scenario_config_fields": list(UNUSED_SCENARIO_CONFIG_FIELDS),
            },
            "phase_c_table_sha": inputs.provenance.phase_c_table_sha,
            "roster_sha": inputs.provenance.roster_sha,
            "model_version": inputs.provenance.model_version,
            **(
                {"development_contract": inputs.provenance.development_contract}
                if inputs.provenance.development_contract is not None
                else {}
            ),
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


def _conditional_rows(
    generator: np.random.Generator,
    residuals: PairedResidualPool,
    blocks: tuple[tuple[int, int], ...],
    chosen: np.ndarray,
    expectations: np.ndarray,
    config: ConditionalResidualConfig,
) -> tuple[np.ndarray, dict[str, object]]:
    """Row per cell from the source fold, restricted to the player's expectation window.

    Each fold block is ordered once by the history rows' own conditional expectation. For a
    player, the window is the ``window_rows`` rows around their rank position in that order,
    clipped so it stays inside the fold; the draw is uniform within the window. The generator
    is consumed exactly once here, after the fold choice, so the appearance and fold streams
    stay those of the foundation sampler.
    """

    pool = residuals.residuals["raw_expected_points_if_appearance"].to_numpy(dtype="float64")
    ordered_rows: list[np.ndarray] = []
    sorted_values: list[np.ndarray] = []
    windows: list[int] = []
    fallback_folds = 0
    for start, size in blocks:
        order = np.argsort(pool[start : start + size], kind="stable")
        ordered_rows.append(start + order)
        sorted_values.append(pool[start + order])
        window = config.window_rows(size)
        windows.append(window)
        fallback_folds += int(window >= size)
    flat_rows = np.concatenate(ordered_rows)
    starts = np.array([start for start, _ in blocks], dtype="int64")
    sizes = np.array([size for _, size in blocks], dtype="int64")
    window_sizes = np.array(windows, dtype="int64")
    # Rank of every player's expectation inside every fold's ordering: (folds, players).
    ranks = np.stack(
        [np.searchsorted(values, expectations, side="left") for values in sorted_values]
    )
    window_start = np.clip(ranks - (window_sizes // 2)[:, None], 0, (sizes - window_sizes)[:, None])
    count, players = chosen.shape[0], expectations.shape[0]
    offsets = generator.integers(0, window_sizes[chosen][:, None], size=(count, players))
    positions = window_start[chosen] + offsets
    drawn = flat_rows[starts[chosen][:, None] + positions]
    return drawn, {
        "component_sampler_contract_version": config.contract_version,
        "residual_selection": "conditional_neighbourhood",
        "conditional_residual_fraction": config.fraction,
        "conditional_residual_minimum_rows": config.minimum_rows,
        "conditional_residual_window_rows_mean": float(window_sizes.mean()),
        "conditional_residual_fallback_folds": fallback_folds,
        "conditional_residual_history_folds": len(blocks),
    }


def _team_match_block_rows(
    generator: np.random.Generator,
    residuals: PairedResidualPool,
    blocks: tuple[tuple[int, int], ...],
    chosen: np.ndarray,
    roster: pd.DataFrame,
    config: TeamMatchBlockConfig,
) -> tuple[np.ndarray, dict[str, object]]:
    """Row per cell from one source club-week block of the scenario's source fold.

    Within every history fold the pool's rows are grouped by source ``team_id`` into club-week
    blocks, each ordered by position. A target club is a distinct ``team_id`` of the roster, in
    order of first appearance. Per scenario and target club one block is drawn uniformly among
    the fold's blocks with the club's fixture count, or among all its blocks when none has it
    (counted); per scenario and player one row is drawn uniformly among the block's rows of the
    player's position, or among all its rows when it has none (counted). The generator is
    consumed twice here, after the fold choice: the block draw, then the row draw. Both are one
    ``integers`` call over an array of option counts, so the appearance and fold streams stay
    those of the foundation sampler.

    A block is never empty, because the blocks are the pool's own rows, so the foundation's
    fold-uniform draw has no case to cover here and no branch for it.
    """

    pool = residuals.residuals
    missing = [name for name in TEAM_MATCH_BLOCK_SOURCE_COLUMNS if name not in pool.columns]
    if missing:
        raise ScenarioValidationError(
            f"The residual pool carries no {missing!r}; build it with team_match_block to "
            "keep the club-week block fields."
        )
    teams = pool["team_id"].astype("string").to_numpy(dtype=object)
    positions = pool["position"].astype("string").to_numpy(dtype=object)
    fixtures = pool["fixture_count"].to_numpy(dtype="int64")

    target_teams = [str(value) for value in roster["team_id"]]
    target_positions = [str(value) for value in roster["position"]]
    target_fixtures = roster["fixture_count"].to_numpy(dtype="int64")
    clubs = list(dict.fromkeys(target_teams))
    club_of_player = np.array([clubs.index(team) for team in target_teams], dtype="int64")
    club_fixtures = np.zeros(len(clubs), dtype="int64")
    mixed_target_clubs = 0
    for index in range(len(clubs)):
        values = target_fixtures[club_of_player == index]
        club_fixtures[index] = values.max()
        mixed_target_clubs += int(len(set(values.tolist())) > 1)
    position_names = sorted(set(positions.tolist()) | set(target_positions))
    position_index = {name: index for index, name in enumerate(position_names)}
    player_position = np.array([position_index[name] for name in target_positions], dtype="int64")
    fixture_values = sorted(set(fixtures.tolist()) | set(club_fixtures.tolist()))
    fixture_index = {value: index for index, value in enumerate(fixture_values)}
    club_fixture = np.array([fixture_index[int(value)] for value in club_fixtures], dtype="int64")

    # Per fold: its blocks in team order, each block's rows in position order, and for every
    # fixture count the blocks that carry it. Padded to the widest fold so one fancy index
    # serves every scenario whatever fold it drew.
    folds = len(blocks)
    ordered: list[np.ndarray] = []
    block_counts = np.zeros(folds, dtype="int64")
    fold_blocks: list[list[tuple[int, int, int, dict[int, tuple[int, int]]]]] = []
    mixed_blocks = 0
    offset = 0
    for start, size in blocks:
        rows = np.arange(start, start + size)
        rows = rows[np.lexsort((positions[rows], teams[rows]))]
        ordered.append(rows)
        fold_teams = teams[rows]
        boundaries = np.flatnonzero(np.r_[True, fold_teams[1:] != fold_teams[:-1]])
        ends = np.r_[boundaries[1:], size]
        described: list[tuple[int, int, int, dict[int, tuple[int, int]]]] = []
        for block_start, block_end in zip(boundaries.tolist(), ends.tolist(), strict=True):
            block_rows = rows[block_start:block_end]
            counted = Counter(fixtures[block_rows].tolist())
            mixed_blocks += int(len(counted) > 1)
            # The rows' common fixture count; the most frequent, larger on a tie, if they differ.
            fixture = max(counted, key=lambda value: (counted[value], value))
            groups: dict[int, tuple[int, int]] = {}
            block_positions = positions[block_rows]
            for name in dict.fromkeys(block_positions.tolist()):
                members = np.flatnonzero(block_positions == name)
                groups[position_index[name]] = (
                    offset + block_start + int(members[0]),
                    int(members.size),
                )
            described.append(
                (offset + block_start, block_end - block_start, fixture_index[fixture], groups)
            )
        fold_blocks.append(described)
        block_counts[len(fold_blocks) - 1] = len(described)
        offset += size
    ordered_rows = np.concatenate(ordered)
    widest = int(block_counts.max())
    block_start_at = np.zeros((folds, widest), dtype="int64")
    block_size_at = np.zeros((folds, widest), dtype="int64")
    group_start_at = np.zeros((folds, widest, len(position_names)), dtype="int64")
    group_size_at = np.zeros((folds, widest, len(position_names)), dtype="int64")
    preferred = np.zeros((folds, len(fixture_values), widest), dtype="int64")
    preferred_count = np.zeros((folds, len(fixture_values)), dtype="int64")
    for fold, described in enumerate(fold_blocks):
        for block, (block_start, block_size, fixture, groups) in enumerate(described):
            block_start_at[fold, block] = block_start
            block_size_at[fold, block] = block_size
            for position, (group_start, group_size) in groups.items():
                group_start_at[fold, block, position] = group_start
                group_size_at[fold, block, position] = group_size
            preferred[fold, fixture, preferred_count[fold, fixture]] = block
            preferred_count[fold, fixture] += 1

    # One block per scenario and target club, among the matching blocks when any exist.
    count = chosen.shape[0]
    matching = preferred_count[chosen][:, club_fixture]
    block_high = np.where(matching > 0, matching, block_counts[chosen][:, None])
    option = generator.integers(0, block_high, size=(count, len(clubs)))
    club_block = np.where(
        matching > 0, preferred[chosen[:, None], club_fixture[None, :], option], option
    )
    blank = club_fixtures <= 0
    fixture_fallback = int(np.count_nonzero((matching == 0) & ~blank[None, :]))
    blank_cells = int(count * np.count_nonzero(blank))

    # One row per scenario and player, among the block's rows of the player's position.
    player_block = club_block[:, club_of_player]
    fold_column = chosen[:, None]
    sizes = group_size_at[fold_column, player_block, player_position[None, :]]
    starts = group_start_at[fold_column, player_block, player_position[None, :]]
    row_high = np.where(sizes > 0, sizes, block_size_at[fold_column, player_block])
    row_start = np.where(sizes > 0, starts, block_start_at[fold_column, player_block])
    offsets = generator.integers(0, row_high, size=row_high.shape)
    drawn = ordered_rows[row_start + offsets]
    position_fallback = int(np.count_nonzero(sizes == 0))
    matched_cells = count * len(clubs) - blank_cells
    return drawn, {
        "component_sampler_contract_version": config.contract_version,
        "residual_selection": "team_match_block",
        "team_match_block_history_folds": folds,
        "team_match_block_blocks_per_fold_mean": float(block_counts.mean()),
        "team_match_block_block_rows_mean": float(len(pool) / block_counts.sum()),
        "team_match_block_target_clubs": len(clubs),
        "team_match_block_fixture_fallback_cells": fixture_fallback,
        "team_match_block_fixture_fallback_rate": (
            fixture_fallback / matched_cells if matched_cells else 0.0
        ),
        "team_match_block_blank_club_cells": blank_cells,
        "team_match_block_position_fallback_cells": position_fallback,
        "team_match_block_position_fallback_rate": position_fallback / drawn.size,
        "team_match_block_mixed_fixture_blocks": mixed_blocks,
        "team_match_block_mixed_fixture_target_clubs": mixed_target_clubs,
    }


def _contiguous_groups(keys: np.ndarray) -> list[tuple[object, int, int]]:
    """``(key, start, size)`` of every run of equal keys in an already sorted array."""

    if keys.size == 0:
        return []
    boundaries = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[boundaries[1:], keys.size]
    return [
        (keys[start], int(start), int(end) - int(start))
        for start, end in zip(boundaries.tolist(), ends.tolist(), strict=True)
    ]


# Per block: start and size over every row, start and size over the appeared rows, the
# fixture index, and the position groups of each ordering.
_JointBlock = tuple[int, int, int, int, int, dict[int, tuple[int, int]], dict[int, tuple[int, int]]]


def _team_match_joint_cells(
    generator: np.random.Generator,
    pool: TeamMatchJointPool,
    roster: pd.DataFrame,
    probability: np.ndarray,
    ceiling: np.ndarray,
    count: int,
    config: TeamMatchJointConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Appearance, source fold and residual row per cell, from one club-week block.

    The generator is consumed in this order: one uniform per cell (the foundation's first
    call, in its shape), one source fold per scenario (its second call, so the source folds
    are the foundation's seed for seed), one block per scenario and target club, one source
    row per cell, and one uniform per cell for the residual re-draw. Each is one call over an
    array of option counts.

    A player's source row is drawn among the block's rows of the same position, appeared or
    not (any row of the block when the position is absent, counted). The row's observed
    appearance ``a_s`` and probability ``p_s`` give its latent uniform, ``v * p_s`` when it
    appeared and ``p_s + v * (1 - p_s)`` when it did not; the player appears iff that uniform
    is below the player's own probability and the ceiling is positive. An appearing player
    whose source row appeared takes its paired residual; one whose source row did not appear
    re-draws among the block's appeared rows of the same position, else the block's appeared
    rows, else the fold's appeared rows, each level counted. The draw checks that no appearing
    cell reads a missing residual, rather than trusting the construction.
    """

    frame = pool.residuals
    teams = frame["team_id"].astype("string").to_numpy(dtype=object)
    positions = frame["position"].astype("string").to_numpy(dtype=object)
    fixtures = frame["fixture_count"].to_numpy(dtype="int64")
    source_appeared = frame["appearance_target"].to_numpy(dtype="int64") == 1
    source_probability = frame["appearance_probability"].to_numpy(dtype="float64")
    finite_residual = np.isfinite(frame["minutes_residual"].to_numpy(dtype="float64")) & (
        np.isfinite(frame["points_residual"].to_numpy(dtype="float64"))
    )

    target_teams = [str(value) for value in roster["team_id"]]
    target_positions = [str(value) for value in roster["position"]]
    target_fixtures = roster["fixture_count"].to_numpy(dtype="int64")
    clubs = list(dict.fromkeys(target_teams))
    club_of_player = np.array([clubs.index(team) for team in target_teams], dtype="int64")
    club_fixtures = np.zeros(len(clubs), dtype="int64")
    mixed_target_clubs = 0
    for index in range(len(clubs)):
        values = target_fixtures[club_of_player == index]
        club_fixtures[index] = values.max()
        mixed_target_clubs += int(len(set(values.tolist())) > 1)
    position_names = sorted(set(positions.tolist()) | set(target_positions))
    position_index = {name: index for index, name in enumerate(position_names)}
    player_position = np.array([position_index[name] for name in target_positions], dtype="int64")
    fixture_values = sorted(set(fixtures.tolist()) | set(club_fixtures.tolist()))
    fixture_index = {value: index for index, value in enumerate(fixture_values)}
    club_fixture = np.array([fixture_index[int(value)] for value in club_fixtures], dtype="int64")

    # Two orderings of the pool, both by fold, club and position: one over every row, for the
    # source row, and one over the appeared rows, for the residual re-draw. The blocks are the
    # clubs of the first; a club with no appeared row has an empty range in the second.
    blocks = pool.fold_blocks()
    folds = len(blocks)
    ordered_all_parts: list[np.ndarray] = []
    ordered_app_parts: list[np.ndarray] = []
    block_counts = np.zeros(folds, dtype="int64")
    fold_app_start = np.zeros(folds, dtype="int64")
    fold_app_size = np.zeros(folds, dtype="int64")
    described: list[list[_JointBlock]] = []
    mixed_blocks = 0
    appeared_rows_total = 0
    offset_all = 0
    offset_app = 0
    for fold, (start, size) in enumerate(blocks):
        rows = np.arange(start, start + size)
        rows_all = rows[np.lexsort((positions[rows], teams[rows]))]
        app = rows[source_appeared[rows]]
        rows_app = app[np.lexsort((positions[app], teams[app]))]
        ordered_all_parts.append(rows_all)
        ordered_app_parts.append(rows_app)
        fold_app_start[fold] = offset_app
        fold_app_size[fold] = rows_app.size
        appeared_rows_total += int(rows_app.size)
        app_blocks = {
            key: (block_start, block_size)
            for key, block_start, block_size in _contiguous_groups(teams[rows_app])
        }
        fold_blocks: list[_JointBlock] = []
        for team, block_start, block_size in _contiguous_groups(teams[rows_all]):
            block_rows = rows_all[block_start : block_start + block_size]
            counted = Counter(fixtures[block_rows].tolist())
            mixed_blocks += int(len(counted) > 1)
            fixture = max(counted, key=lambda value: (counted[value], value))
            groups_all = {
                position_index[str(name)]: (offset_all + block_start + group_start, group_size)
                for name, group_start, group_size in _contiguous_groups(positions[block_rows])
            }
            app_start, app_size = app_blocks.get(team, (0, 0))
            app_rows = rows_app[app_start : app_start + app_size]
            groups_app = {
                position_index[str(name)]: (offset_app + app_start + group_start, group_size)
                for name, group_start, group_size in _contiguous_groups(positions[app_rows])
            }
            fold_blocks.append(
                (
                    offset_all + block_start,
                    block_size,
                    offset_app + app_start,
                    app_size,
                    fixture_index[fixture],
                    groups_all,
                    groups_app,
                )
            )
        described.append(fold_blocks)
        block_counts[fold] = len(fold_blocks)
        offset_all += size
        offset_app += int(rows_app.size)
    ordered_all = np.concatenate(ordered_all_parts)
    ordered_app = np.concatenate(ordered_app_parts)
    widest = int(block_counts.max())
    shape = (folds, widest)
    block_start_all = np.zeros(shape, dtype="int64")
    block_size_all = np.zeros(shape, dtype="int64")
    block_start_app = np.zeros(shape, dtype="int64")
    block_size_app = np.zeros(shape, dtype="int64")
    group_shape = (folds, widest, len(position_names))
    group_start_all = np.zeros(group_shape, dtype="int64")
    group_size_all = np.zeros(group_shape, dtype="int64")
    group_start_app = np.zeros(group_shape, dtype="int64")
    group_size_app = np.zeros(group_shape, dtype="int64")
    preferred = np.zeros((folds, len(fixture_values), widest), dtype="int64")
    preferred_count = np.zeros((folds, len(fixture_values)), dtype="int64")
    for fold, fold_blocks in enumerate(described):
        for block, (
            start_all,
            size_all,
            start_app,
            size_app,
            fixture,
            groups_all,
            groups_app,
        ) in enumerate(fold_blocks):
            block_start_all[fold, block] = start_all
            block_size_all[fold, block] = size_all
            block_start_app[fold, block] = start_app
            block_size_app[fold, block] = size_app
            for position, (group_start, group_size) in groups_all.items():
                group_start_all[fold, block, position] = group_start
                group_size_all[fold, block, position] = group_size
            for position, (group_start, group_size) in groups_app.items():
                group_start_app[fold, block, position] = group_start
                group_size_app[fold, block, position] = group_size
            preferred[fold, fixture, preferred_count[fold, fixture]] = block
            preferred_count[fold, fixture] += 1

    players = len(target_teams)
    latent = generator.random((count, players))
    chosen = generator.integers(0, folds, size=count)
    fold_column = chosen[:, None]

    # One block per scenario and target club, among the matching blocks when any exist.
    matching = preferred_count[chosen][:, club_fixture]
    block_high = np.where(matching > 0, matching, block_counts[chosen][:, None])
    option = generator.integers(0, block_high, size=(count, len(clubs)))
    club_block = np.where(
        matching > 0, preferred[chosen[:, None], club_fixture[None, :], option], option
    )
    blank = club_fixtures <= 0
    fixture_fallback = int(np.count_nonzero((matching == 0) & ~blank[None, :]))
    blank_cells = int(count * np.count_nonzero(blank))

    # One source row per scenario and player, among the block's rows of the player's position.
    player_block = club_block[:, club_of_player]
    sizes = group_size_all[fold_column, player_block, player_position[None, :]]
    starts = group_start_all[fold_column, player_block, player_position[None, :]]
    row_high = np.where(sizes > 0, sizes, block_size_all[fold_column, player_block])
    row_start = np.where(sizes > 0, starts, block_start_all[fold_column, player_block])
    offsets = generator.integers(0, row_high, size=row_high.shape)
    source = ordered_all[row_start + offsets]
    position_fallback = int(np.count_nonzero(sizes == 0))

    # The appearance, inherited through the source row's latent uniform.
    row_appeared = source_appeared[source]
    row_probability = source_probability[source]
    uniform = np.where(
        row_appeared,
        latent * row_probability,
        row_probability + latent * (1.0 - row_probability),
    )
    appeared = uniform < probability[None, :]
    appeared &= ceiling[None, :] > 0.0

    # The residual row: the source row itself when it appeared, else a re-draw among appeared
    # rows of the same block and position, falling back to the block, then to the fold.
    redraw = appeared & ~row_appeared
    app_sizes = group_size_app[fold_column, player_block, player_position[None, :]]
    app_starts = group_start_app[fold_column, player_block, player_position[None, :]]
    block_sizes = block_size_app[fold_column, player_block]
    block_starts = block_start_app[fold_column, player_block]
    fold_sizes = np.broadcast_to(fold_app_size[chosen][:, None], app_sizes.shape)
    fold_starts = np.broadcast_to(fold_app_start[chosen][:, None], app_sizes.shape)
    level_position = app_sizes > 0
    level_block = ~level_position & (block_sizes > 0)
    level_fold = ~level_position & ~level_block
    high = np.where(level_position, app_sizes, np.where(level_block, block_sizes, fold_sizes))
    first = np.where(level_position, app_starts, np.where(level_block, block_starts, fold_starts))
    scaled = generator.random((count, players))
    redraw_offset = np.minimum((scaled * high).astype("int64"), np.maximum(high - 1, 0))
    redrawn = ordered_app[first + redraw_offset]
    drawn = np.where(redraw, redrawn, source)
    if not bool(finite_residual[drawn[appeared]].all()):
        raise ScenarioValidationError(
            "An appearing cell would read a missing residual; the joint draw refuses rather "
            "than publishing a non-appearance's residual as an outcome."
        )

    appeared_cells = int(np.count_nonzero(appeared))
    redraw_cells = int(np.count_nonzero(redraw))
    matched_cells = count * len(clubs) - blank_cells
    diagnostics: dict[str, object] = {
        "component_sampler_contract_version": config.contract_version,
        "residual_selection": "team_match_joint",
        "team_match_joint_history_folds": folds,
        "team_match_joint_blocks_per_fold_mean": float(block_counts.mean()),
        "team_match_joint_block_rows_mean": float(len(frame) / block_counts.sum()),
        "team_match_joint_block_appeared_rows_mean": float(
            appeared_rows_total / block_counts.sum()
        ),
        "team_match_joint_target_clubs": len(clubs),
        "team_match_joint_fixture_fallback_cells": fixture_fallback,
        "team_match_joint_fixture_fallback_rate": (
            fixture_fallback / matched_cells if matched_cells else 0.0
        ),
        "team_match_joint_blank_club_cells": blank_cells,
        "team_match_joint_position_fallback_cells": position_fallback,
        "team_match_joint_position_fallback_rate": position_fallback / drawn.size,
        "team_match_joint_mixed_fixture_blocks": mixed_blocks,
        "team_match_joint_mixed_fixture_target_clubs": mixed_target_clubs,
        "team_match_joint_source_row_appearance_rate": float(row_appeared.mean()),
        "team_match_joint_sampled_appearance_rate": float(appeared.mean()),
        "team_match_joint_redraw_cells": redraw_cells,
        "team_match_joint_redraw_rate": (redraw_cells / appeared_cells if appeared_cells else 0.0),
        "team_match_joint_redraw_block_fallback_cells": int(np.count_nonzero(redraw & level_block)),
        "team_match_joint_redraw_fold_fallback_cells": int(np.count_nonzero(redraw & level_fold)),
        "team_match_joint_pool_excluded_rows": dict(pool.excluded_rows),
    }
    return appeared, chosen, drawn, diagnostics


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
