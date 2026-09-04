"""Behaviour tests for the component-aware scenario foundation.

Everything here is synthetic and small enough to reason about by hand: three players, a
residual pool whose two columns are deliberately linked, and ceilings wide enough that a clip
cannot hide a mistake.

The tests assert behaviour, not implementation. No test parses source text, and no private
helper name is pinned -- a rename should not fail a suite that is supposed to protect the
sampling rules.
"""

import pandas as pd
import pytest

from squadopt.prediction.integration import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioTarget,
    ScenarioValidationError,
)
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    ComponentScenarioDraw,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    component_input_summary,
    paired_conditional_residuals,
    sample_component_scenarios,
)

SEASON = "2026-27"
TARGET = ScenarioTarget(season=SEASON, gameweek=9)
PLAYERS = (101, 102, 103)


def _provenance(**overrides: object) -> ComponentScenarioProvenance:
    fields: dict[str, object] = {
        "phase_c_table_sha": "t" * 64,
        "roster_sha": "r" * 64,
        "model_version": "synthetic-component-1.0.0",
        "feature_contract_version": "synthetic-features-v1",
        "target_contract_version": "synthetic-targets-v1",
        "dataset_contract_version": "synthetic-dataset-v1",
        "season": SEASON,
        "target_gameweek": TARGET.gameweek,
        "deterministic_seed": 0,
    }
    fields.update(overrides)
    return ComponentScenarioProvenance(**fields)  # type: ignore[arg-type]


def _input_frame(**overrides: object) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "player_id": list(PLAYERS),
            "team_id": [1, 1, 2],
            "position": ["MID", "FWD", "DEF"],
            "fixture_count": [1, 1, 1],
            "appearance_probability": [0.5, 0.5, 0.5],
            # Wide of the ceiling on purpose: a clip must not be able to mask a bad draw.
            "expected_minutes_if_appearance": [45.0, 45.0, 45.0],
            "raw_expected_points_if_appearance": [4.0, 4.0, 4.0],
            "composition_route": ["component_model"] * 3,
            # The only status the Phase C contract declares today; the input contract follows
            # that tuple rather than widening it here.
            "evidence_status": ["not_requested"] * 3,
        }
    )
    for column, value in overrides.items():
        frame[column] = value
    return frame


def _inputs(frame: pd.DataFrame | None = None, **provenance: object) -> ComponentScenarioInputs:
    return ComponentScenarioInputs(
        table=_input_frame() if frame is None else frame,
        provenance=_provenance(**provenance),
    )


def _snapshot() -> object:
    table = pd.DataFrame(
        {
            "player_id": list(PLAYERS),
            "name": ["Synthetic One", "Synthetic Two", "Synthetic Three"],
            "team_id": [1, 1, 2],
            "position": ["MID", "FWD", "DEF"],
            "price_tenths": [50, 60, 45],
        }
    )
    points = pd.DataFrame({"player_id": list(PLAYERS), "expected_points": [4.0, 4.0, 4.0]})
    provenance = PredictionProvenance(
        model_name="synthetic-component-model",
        # Must equal the component provenance's: the sampler cross-checks the two.
        model_version="synthetic-component-1.0.0",
        feature_contract_version="synthetic-features-v1",
        training_cutoff=f"{SEASON}:GW08",
        training_data_fingerprint="b" * 64,
    )
    return prepare_optimizer_projection(table, points, provenance)


def _oof(folds: tuple[str, ...] = ("2026-27-gw07", "2026-27-gw08"), **overrides: object):
    """Rows whose two residuals are linked: points_residual == minutes_residual / 10."""

    records: list[dict[str, object]] = []
    for fold in folds:
        for index, player in enumerate(PLAYERS):
            minutes_residual = 10.0 * (index + 1)
            records.append(
                {
                    "fold_id": fold,
                    "player_id": player,
                    "composition_route": "component_model",
                    "appearance_target": 1,
                    "expected_minutes_if_appearance": 45.0,
                    "raw_expected_points_if_appearance": 4.0,
                    "minutes_target": 45.0 + minutes_residual,
                    "points_target": 4.0 + minutes_residual / 10.0,
                }
            )
    frame = pd.DataFrame(records)
    for column, value in overrides.items():
        frame[column] = value
    return frame


def _disjoint_oof() -> pd.DataFrame:
    """Two folds whose residuals cannot be mistaken for each other.

    ``gw07`` yields minutes residuals ``{10, 20, 30}`` and ``gw08`` yields ``{110, 120, 130}``.
    Because the two sets are disjoint, the fold a sampled cell came from is readable straight
    off the minutes matrix -- which is what makes the fold-block rule observable at all.
    """

    records: list[dict[str, object]] = []
    for offset, fold in ((0.0, "2026-27-gw07"), (100.0, "2026-27-gw08")):
        for index, player in enumerate(PLAYERS):
            minutes_residual = offset + 10.0 * (index + 1)
            records.append(
                {
                    "fold_id": fold,
                    "player_id": player,
                    "composition_route": "component_model",
                    "appearance_target": 1,
                    "expected_minutes_if_appearance": 45.0,
                    "raw_expected_points_if_appearance": 4.0,
                    "minutes_target": 45.0 + minutes_residual,
                    "points_target": 4.0 + minutes_residual / 10.0,
                }
            )
    return pd.DataFrame(records)


FOLD_RESIDUALS = {
    "2026-27-gw07": {10.0, 20.0, 30.0},
    "2026-27-gw08": {110.0, 120.0, 130.0},
}


def _fold_block_draw():
    """A draw over ``_disjoint_oof``, with a ceiling too wide to clip any residual away."""

    frame = _input_frame(appearance_probability=1.0)
    frame["fixture_count"] = 3  # ceiling 270, and the largest draw is 45 + 130
    return _sample(inputs=_inputs(frame), oof=_disjoint_oof())


def _sample(*, config: ScenarioConfig | None = None, **kwargs: object):
    inputs = kwargs.pop("inputs", None) or _inputs()
    oof = kwargs.pop("oof", None)
    oof = _oof() if oof is None else oof
    pool = paired_conditional_residuals(oof, target=TARGET)
    draw = sample_component_scenarios(
        inputs,
        _snapshot(),  # type: ignore[arg-type]
        pool,
        TARGET,
        config or ScenarioConfig(scenario_count=200, deterministic_seed=7),
    )
    assert isinstance(draw, ComponentScenarioDraw)
    return draw


# --- 1, 2. determinism -------------------------------------------------------


def test_the_same_seed_and_input_produce_the_same_matrix_and_fingerprint() -> None:
    first = _sample()
    second = _sample()

    assert first.scenarios.scenario_fingerprint == second.scenarios.scenario_fingerprint
    pd.testing.assert_frame_equal(first.scenarios.scenario_points, second.scenarios.scenario_points)


def test_a_different_seed_moves_the_draws() -> None:
    """Determinism must not be the trivial kind where the seed does nothing."""

    first = _sample(config=ScenarioConfig(scenario_count=200, deterministic_seed=7))
    second = _sample(config=ScenarioConfig(scenario_count=200, deterministic_seed=8))

    assert first.scenarios.scenario_fingerprint != second.scenarios.scenario_fingerprint
    assert not first.scenarios.scenario_points.equals(second.scenarios.scenario_points)


# --- 3, 4, 5. the appearance mixture ----------------------------------------


def test_an_impossible_appearance_yields_exactly_zero_everywhere() -> None:
    """Exactly zero, not nearly zero: a player who did not feature scored nothing."""

    scenarios = _sample(inputs=_inputs(_input_frame(appearance_probability=0.0)))

    assert (scenarios.scenarios.scenario_points.to_numpy() == 0.0).all()
    assert scenarios.scenarios.diagnostics["appearance_rate"] == 0.0


def test_a_certain_appearance_features_in_every_scenario() -> None:
    scenarios = _sample(inputs=_inputs(_input_frame(appearance_probability=1.0)))

    assert scenarios.scenarios.diagnostics["appearance_rate"] == 1.0
    assert not (scenarios.scenarios.scenario_points.to_numpy() == 0.0).all()


def test_a_blank_gameweek_scores_zero_whatever_the_probability_says() -> None:
    """No fixture is nowhere to play, so certainty of appearing cannot override it."""

    frame = _input_frame(appearance_probability=1.0)
    frame["fixture_count"] = 0
    frame["expected_minutes_if_appearance"] = 0.0

    scenarios = _sample(inputs=_inputs(frame))

    assert (scenarios.scenarios.scenario_points.to_numpy() == 0.0).all()
    assert scenarios.scenarios.diagnostics["appearance_rate"] == 0.0


# --- 6, 7. the physical range, and the one bound that must not exist --------


def test_sampled_minutes_never_exceed_ninety_per_fixture() -> None:
    frame = _input_frame(appearance_probability=1.0)
    frame["expected_minutes_if_appearance"] = 85.0  # plus a residual of up to +30

    scenarios = _sample(inputs=_inputs(frame))

    assert float(scenarios.scenarios.diagnostics["sampled_minutes_mean"]) <= 90.0


def test_a_negative_realizable_point_outcome_survives_to_the_matrix() -> None:
    """The bound that must not exist.

    An FPL score can be negative. Clipping the scenario outcome at zero would delete real
    downside and narrow every risk statistic taken from it, so a large negative residual has
    to arrive in the matrix intact.
    """

    frame = _input_frame(appearance_probability=1.0)
    frame["raw_expected_points_if_appearance"] = -6.0

    scenarios = _sample(inputs=_inputs(frame))

    assert scenarios.scenarios.scenario_points.to_numpy().min() < 0.0


# --- 8. the pairing that is the whole point ---------------------------------


def test_minutes_and_points_residuals_come_from_the_same_historical_row() -> None:
    """The dependence this phase exists to capture, checked per cell.

    The pool is built so points_residual == minutes_residual / 10. Checking only the points
    matrix cannot detect a broken pairing: every points value stays legal on its own however
    it was drawn. So the check reads both matrices for the *same* cell and asserts the two
    residuals came from one row.

    That distinction is not hypothetical. The first version of this test looked only at the
    points marginal, and a mutation that drew the two with independent indices passed it.
    """

    frame = _input_frame(appearance_probability=1.0)
    scenarios = _sample(inputs=_inputs(frame))

    points = scenarios.scenarios.scenario_points.to_numpy()
    minutes = scenarios.sampled_minutes.to_numpy()

    minutes_residual = minutes - 45.0
    points_residual = points - 4.0

    assert minutes_residual.min() > 0.0  # the pool has no zero, so nothing is a coincidence
    assert points_residual == pytest.approx(minutes_residual / 10.0)


def test_the_sampled_minutes_are_diagnostics_not_a_second_decision_matrix() -> None:
    """Minutes are published for the scorer, but the points matrix stays the public one."""

    scenarios = _sample()
    minutes = scenarios.sampled_minutes

    assert list(minutes.columns) == list(scenarios.scenarios.scenario_points.columns)
    assert minutes.shape == scenarios.scenarios.scenario_points.shape


# --- 9, 10, 11. leakage and chronology --------------------------------------


def test_the_target_fold_cannot_appear_in_its_own_history() -> None:
    with pytest.raises(ScenarioValidationError, match="its own residual history"):
        paired_conditional_residuals(_oof(folds=("2026-27-gw07", TARGET.fold_id)), target=TARGET)


@pytest.mark.parametrize("fold", ["2026-27-gw10", "2027-28-gw01"])
def test_a_history_fold_at_or_after_the_target_is_refused(fold: str) -> None:
    with pytest.raises(ScenarioValidationError, match="must precede"):
        paired_conditional_residuals(_oof(folds=("2026-27-gw07", fold)), target=TARGET)


def test_the_locked_holdout_season_is_refused() -> None:
    with pytest.raises(ScenarioValidationError, match="locked holdout"):
        _provenance(season="2025-26")


def test_too_little_history_is_refused_rather_than_sampled_from() -> None:
    with pytest.raises(ScenarioValidationError, match="Refused rather than sampled"):
        paired_conditional_residuals(
            _oof(folds=("2026-27-gw07",)), target=TARGET, min_history_folds=2
        )


# --- 12. nothing is invented -------------------------------------------------


def test_a_direct_control_row_may_not_carry_a_component_value() -> None:
    frame = _input_frame()
    frame.loc[0, "composition_route"] = "direct_control"

    with pytest.raises(ScenarioValidationError, match="invented rather than measured"):
        ComponentScenarioInputs(table=frame, provenance=_provenance())


def test_direct_control_history_produces_no_conditional_residual() -> None:
    with pytest.raises(ScenarioValidationError, match="no conditional residual exists"):
        paired_conditional_residuals(_oof(composition_route="direct_control"), target=TARGET)


def test_a_missing_conditional_target_is_excluded_rather_than_zero_filled() -> None:
    frame = _oof()
    frame.loc[0, "minutes_target"] = float("nan")

    pool = paired_conditional_residuals(frame, target=TARGET)

    assert len(pool) == len(frame) - 1
    assert not (pool.residuals["minutes_residual"] == -45.0).any()  # a zero-fill would show here


def test_an_unobserved_appearance_row_is_excluded() -> None:
    frame = _oof()
    frame["appearance_target"] = 0

    with pytest.raises(ScenarioValidationError, match="No appearance-observed"):
        paired_conditional_residuals(frame, target=TARGET)


# --- 13. purity --------------------------------------------------------------


def test_the_caller_s_frames_are_not_mutated() -> None:
    inputs_frame = _input_frame()
    oof_frame = _oof()
    before = (inputs_frame.copy(deep=True), oof_frame.copy(deep=True))

    _sample(
        inputs=ComponentScenarioInputs(table=inputs_frame, provenance=_provenance()), oof=oof_frame
    )

    pd.testing.assert_frame_equal(inputs_frame, before[0])
    pd.testing.assert_frame_equal(oof_frame, before[1])


def test_row_order_in_the_history_does_not_change_the_pool() -> None:
    straight = paired_conditional_residuals(_oof(), target=TARGET)
    shuffled = paired_conditional_residuals(
        _oof().sample(frac=1.0, random_state=3).reset_index(drop=True), target=TARGET
    )

    pd.testing.assert_frame_equal(straight.residuals, shuffled.residuals)


# --- 14. player order and provenance ----------------------------------------


def test_the_scenario_columns_carry_the_projection_s_player_order() -> None:
    scenarios = _sample()

    assert tuple(scenarios.scenarios.scenario_points.columns) == PLAYERS


def test_a_player_order_mismatch_is_refused() -> None:
    frame = _input_frame()
    frame["player_id"] = [103, 102, 101]

    with pytest.raises(ScenarioValidationError, match="same players in the same order"):
        _sample(inputs=_inputs(frame))


def test_the_set_names_its_contract_and_its_sources() -> None:
    scenarios = _sample()

    assert (
        scenarios.scenarios.diagnostics["component_contract_version"]
        == COMPONENT_SCENARIO_CONTRACT_VERSION
    )
    assert scenarios.scenarios.diagnostics["phase_c_table_sha"] == "t" * 64
    assert scenarios.scenarios.diagnostics["roster_sha"] == "r" * 64
    assert scenarios.scenarios.diagnostics["point_decomposition_applied"] is False


def test_duplicate_players_are_refused() -> None:
    frame = _input_frame()
    frame["player_id"] = [101, 101, 103]

    with pytest.raises(ScenarioValidationError, match="more than once"):
        ComponentScenarioInputs(table=frame, provenance=_provenance())


@pytest.mark.parametrize("probability", [-0.01, 1.01, float("nan")])
def test_an_out_of_range_appearance_probability_is_refused(probability: float) -> None:
    with pytest.raises(ScenarioValidationError, match="within \\[0, 1\\]"):
        ComponentScenarioInputs(
            table=_input_frame(appearance_probability=probability), provenance=_provenance()
        )


def test_the_summary_counts_routes_without_naming_players() -> None:
    summary = component_input_summary(_inputs())

    assert summary["rows"] == 3
    assert summary["component_model_rows"] == 3
    assert summary["direct_control_rows"] == 0
    assert "player_id" not in summary


# --- 15. V1 is untouched -----------------------------------------------------


def test_the_v1_entry_point_is_still_present_and_independent() -> None:
    """The foundation adds an entry point; it does not replace or wrap the old one."""

    from squadopt.scenarios import generate_scenarios

    assert callable(generate_scenarios)
    assert generate_scenarios.__module__ == "squadopt.scenarios.generator"
    assert sample_component_scenarios.__module__ == "squadopt.scenarios.components"


# --- 16. the input contract's declared vocabularies -------------------------


def test_an_unknown_composition_route_is_refused() -> None:
    """The route vocabulary is Phase C's, and this boundary does not extend it."""

    with pytest.raises(ScenarioValidationError, match="composition_route must be one of"):
        ComponentScenarioInputs(
            table=_input_frame(composition_route="blended_control"), provenance=_provenance()
        )


def test_an_undeclared_evidence_status_is_refused() -> None:
    """``available`` reads like a status, but Phase C does not declare it for this table.

    Accepting it would mean this module had coined a status of its own, and a status nothing
    else writes is a claim nothing else can check.
    """

    with pytest.raises(ScenarioValidationError, match="A status is not coined here"):
        ComponentScenarioInputs(
            table=_input_frame(evidence_status="available"), provenance=_provenance()
        )


def test_a_silently_coerced_scalar_is_refused_rather_than_rounded() -> None:
    """Two scalars that were coerced instead of checked.

    ``min_history_folds`` went through ``max(1, int(...))``, so ``True`` meant one fold and
    ``2.9`` meant two. ``player_id`` was cast, so ``101.5`` became player 101 -- one player's
    residual history attached to another player's row.
    """

    for folds in (True, 2.9, -1, 0):
        with pytest.raises(ScenarioConfigurationError, match="min_history_folds"):
            paired_conditional_residuals(_oof(), target=TARGET, min_history_folds=folds)  # type: ignore[arg-type]

    for identifiers in ([101.5, 102.0, 103.0], [True, False, True]):
        frame = _input_frame()
        frame["player_id"] = identifiers
        with pytest.raises(ScenarioValidationError, match="refused rather than truncated"):
            ComponentScenarioInputs(table=frame, provenance=_provenance())


# --- 17. the sampler's provenance preconditions -----------------------------


def test_a_direct_control_row_is_refused_by_the_sampler_rather_than_sampled_as_zero() -> None:
    """Fail closed, because the only thing available here is to invent a zero.

    The row is legal input: it carries no component value, which is exactly what a
    direct-control row must look like, so it survives the input contract. What it has no
    business doing is reaching the sampler, where a missing conditional mean would have to be
    read as zero -- a confident prediction of nothing, for a player nothing is predicted for.
    The exact-key control fallback lives in another artifact and is not bound here.
    """

    frame = _input_frame()
    frame["expected_minutes_if_appearance"] = frame["expected_minutes_if_appearance"].astype(float)
    frame.loc[0, "composition_route"] = "direct_control"
    frame.loc[
        0,
        [
            "appearance_probability",
            "expected_minutes_if_appearance",
            "raw_expected_points_if_appearance",
        ],
    ] = float("nan")

    inputs = ComponentScenarioInputs(table=frame, provenance=_provenance())
    assert component_input_summary(inputs)["direct_control_rows"] == 1  # it did survive input

    with pytest.raises(ScenarioValidationError, match="no exact-key control fallback"):
        _sample(inputs=inputs)


def test_provenance_naming_another_decision_week_is_refused() -> None:
    """A set whose provenance names a different week cannot be traced to its Phase C rows."""

    with pytest.raises(ScenarioValidationError, match="name season"):
        _sample(inputs=_inputs(season="2024-25"))

    with pytest.raises(ScenarioValidationError, match="name gameweek"):
        _sample(inputs=_inputs(target_gameweek=TARGET.gameweek + 1))


def test_a_roster_field_disagreeing_with_the_projection_is_refused() -> None:
    """The caller joins team and position on, and a stale join must not pass silently.

    Both fields decide something downstream -- position drives autosubs, team drives the team
    limit -- so disagreeing with the projection they are sampled against is not cosmetic.
    """

    for column, values in (("team_id", [9, 1, 2]), ("position", ["DEF", "FWD", "DEF"])):
        frame = _input_frame()
        frame[column] = values
        with pytest.raises(ScenarioValidationError, match=f"disagree on {column}"):
            _sample(inputs=_inputs(frame))


# --- 18. the fold block ------------------------------------------------------


def test_each_scenario_names_the_fold_it_actually_drew_from() -> None:
    """``source_fold_ids`` is a fact about the scenario, not a label from its first player.

    The first foundation commit drew every cell from the whole pool and then recorded player
    zero's fold as the whole scenario's source. That entry was only ever accidentally right.
    """

    draw = _fold_block_draw()
    residuals = draw.sampled_minutes.to_numpy() - 45.0

    assert set(draw.scenarios.source_fold_ids) == set(FOLD_RESIDUALS)  # both folds get used
    for index, fold in enumerate(draw.scenarios.source_fold_ids):
        assert set(residuals[index].tolist()) <= FOLD_RESIDUALS[fold]


def test_no_cell_in_a_scenario_draws_from_another_fold() -> None:
    """The block itself, read without reference to the recorded label.

    A pooled draw mixes the two folds inside a single scenario row almost every time across
    two hundred scenarios, so this fails loudly if the block boundary is dropped -- even if
    ``source_fold_ids`` were somehow still labelled correctly.
    """

    draw = _fold_block_draw()
    residuals = draw.sampled_minutes.to_numpy() - 45.0

    for row in residuals:
        drawn = set(row.tolist())
        assert any(drawn <= allowed for allowed in FOLD_RESIDUALS.values())


# --- 19. the component identity ---------------------------------------------


def test_the_component_fingerprint_is_deterministic_and_not_a_constant() -> None:
    draw = _sample()
    moved_seed = _sample(config=ScenarioConfig(scenario_count=200, deterministic_seed=8))

    assert draw.component_fingerprint == _sample().component_fingerprint
    assert len(draw.component_fingerprint) == 64
    assert moved_seed.component_fingerprint != draw.component_fingerprint


def test_a_changed_minutes_matrix_changes_the_component_fingerprint() -> None:
    """Identical points, one moved minute: a different result, so a different identity.

    The autosub decision is taken from the minutes, so a digest bound only to the points
    matrix would let two genuinely different draws pass as the same one. The same
    ``ScenarioSet`` is reused here, so the points matrix is byte identical by construction and
    the minutes are the only thing that moved.
    """

    draw = _sample(inputs=_inputs(_input_frame(appearance_probability=1.0)))
    moved = draw.sampled_minutes.copy(deep=True)
    assert moved.iloc[0, 0] > 0.0
    moved.iloc[0, 0] = 0.0

    with pytest.raises(ScenarioValidationError, match="component_fingerprint does not match"):
        ComponentScenarioDraw(
            scenarios=draw.scenarios,
            inputs=draw.inputs,
            sampled_minutes=moved,
            component_fingerprint=draw.component_fingerprint,
        )
