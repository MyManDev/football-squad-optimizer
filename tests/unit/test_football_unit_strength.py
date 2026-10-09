"""Synthetic source, exposure and projected-unit checks. No real sources are opened."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from squadopt.features.football_unit_inputs import (
    ClubUnit,
    NumericAttributeSpec,
    PlayerAttributes,
    PlayerMapping,
    ProjectedUnitState,
    SourceRecord,
    UnitInputCatalog,
    UnitObservation,
    UnitPlayer,
    UnitProjection,
)
from squadopt.prediction.football_unit_strength import FootballUnitStrengthModel

T = datetime(2024, 8, 1, 10, tzinfo=UTC)


def source(cutoff: datetime, **changes: Any) -> SourceRecord:
    return replace(
        SourceRecord(
            "synthetic",
            "fixture-only",
            "1",
            "synthetic",
            "a" * 64,
            cutoff - timedelta(hours=2),
            cutoff - timedelta(hours=1),
            cutoff - timedelta(days=1),
            cutoff + timedelta(days=365),
            "synthetic:unit-test",
            True,
        ),
        **changes,
    )


def unit(club: int, *, replacement: bool = False) -> ClubUnit:
    offset = 0 if club == 1 else 100
    positions = ("GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD")
    players = [UnitPlayer(offset + i, pos) for i, pos in enumerate(positions, 1)]
    if replacement:
        players[-1] = UnitPlayer(offset + 12, "FWD")
    return ClubUnit(club, tuple(players))


def catalog(
    *,
    week: int = 1,
    fixture: int = 1,
    cutoff: datetime = T,
    season: str = "2024-25",
    missing: bool = False,
) -> UnitInputCatalog:
    spec = NumericAttributeSpec(
        "finishing", "synthetic", 1, 20, "rating", "Synthetic bounded skill"
    )
    identities = tuple(range(1, 13)) + tuple(range(101, 113))
    mappings = tuple(
        PlayerMapping(
            "synthetic",
            str(i),
            i,
            1 if i < 100 else 2,
            T - timedelta(days=3650),
            T + timedelta(days=3650),
        )
        for i in identities
    )
    attributes = tuple(
        PlayerAttributes(
            "synthetic",
            str(i),
            (("finishing", None if missing else (19.0 if i in (12, 112) else 8.0)),),
        )
        for i in identities
    )
    return UnitInputCatalog(
        season,
        week,
        fixture,
        cutoff,
        (source(cutoff),),
        (spec,),
        mappings,
        attributes,
        "synthetic",
        "synthetic",
        "synthetic",
    )


def observation(
    week: int,
    *,
    replacement: bool,
    minutes: float = 90,
    own_baseline: float = 1,
    opponent_baseline: float = 1,
) -> UnitObservation:
    cutoff = T + timedelta(days=week * 7)
    return UnitObservation(
        "2024-25",
        week,
        week,
        cutoff,
        cutoff + timedelta(hours=2),
        cutoff + timedelta(hours=6),
        source(cutoff + timedelta(hours=6)),
        catalog(week=week, fixture=week, cutoff=cutoff),
        True,
        unit(1, replacement=replacement),
        unit(2),
        unit(1),
        unit(2),
        0,
        minutes,
        5 if replacement else 1,
        1,
        own_baseline,
        opponent_baseline,
    )


def observations() -> tuple[UnitObservation, ...]:
    return tuple(observation(i, replacement=i % 2 == 0) for i in range(1, 7))


def projection(*, replacement: bool = True, missing: bool = False) -> UnitProjection:
    cutoff = T + timedelta(days=56)
    return UnitProjection(
        "2024-25",
        8,
        8,
        cutoff,
        cutoff + timedelta(hours=2),
        cutoff,
        catalog(week=8, fixture=8, cutoff=cutoff, missing=missing),
        True,
        unit(1),
        unit(2),
        (ProjectedUnitState(1, unit(1, replacement=replacement), unit(2)),),
        1.4,
        0.8,
    )


@pytest.fixture
def model() -> FootballUnitStrengthModel:
    return FootballUnitStrengthModel(observations(), cutoff=T + timedelta(days=50))


def test_learned_replacement_changes_rates_without_manual_quality(model: FootballUnitStrengthModel):
    result = model.predict(projection())
    neutral = model.predict(projection(replacement=False))
    assert result.own_goal_rate > neutral.own_goal_rate
    assert result.own_replacement_gap > 0
    assert neutral.own_goal_rate == 1.4
    assert neutral.opponent_goal_rate == 0.8
    assert neutral.own_replacement_gap == 0
    assert (
        result.metadata["availability"]
        == "external once; no availability coefficient or redistribution"
    )


def test_joint_mixture_averages_absolute_rates_and_retains_nonlinear_receipts(
    model: FootballUnitStrengthModel,
):
    target = projection()
    states = (
        ProjectedUnitState(0.25, unit(1), unit(2)),
        ProjectedUnitState(0.75, unit(1, replacement=True), unit(2)),
    )
    result = model.predict(replace(target, states=states))
    strong = model.predict(target).own_goal_rate
    assert result.own_goal_rate == pytest.approx(0.25 * 1.4 + 0.75 * strong, abs=1e-14)
    assert result.own_goal_rate > 1.4 * math.exp(0.75 * math.log(strong / 1.4))
    assert math.fsum(x.probability for x in result.state_rates) == 1
    assert {x.own for x in result.state_rates} == {unit(1), unit(1, replacement=True)}


def test_exact_paired_reversal(model: FootballUnitStrengthModel):
    target = projection()
    forward = model.predict(target)
    reverse_target = replace(
        target,
        home=False,
        reference_own=target.reference_opponent,
        reference_opponent=target.reference_own,
        states=tuple(ProjectedUnitState(x.probability, x.opponent, x.own) for x in target.states),
        causal_baseline_own_goal_rate=target.causal_baseline_opponent_goal_rate,
        causal_baseline_opponent_goal_rate=target.causal_baseline_own_goal_rate,
    )
    reverse = model.predict(reverse_target)
    assert forward.own_goal_rate == reverse.opponent_goal_rate
    assert forward.opponent_goal_rate == reverse.own_goal_rate
    assert forward.club == reverse.opponent


def test_reference_neutrality_with_changed_baseline_and_venue(model: FootballUnitStrengthModel):
    target = replace(
        projection(replacement=False),
        home=False,
        causal_baseline_own_goal_rate=7.3,
        causal_baseline_opponent_goal_rate=0.3,
    )
    result = model.predict(target)
    assert result.own_goal_rate == 7.3
    assert result.opponent_goal_rate == 0.3


def test_fitted_model_cannot_be_used_before_its_fitting_cutoff():
    fitted = FootballUnitStrengthModel(observations(), cutoff=T + timedelta(days=57))
    with pytest.raises(ValueError, match="unavailable at the projection decision cutoff"):
        fitted.predict(projection())


def test_actual_away_observations_identify_venue_interaction_without_changing_baseline():
    training = tuple(
        replace(
            observation(week, replacement=True),
            home=week % 2 == 0,
            own_goals=6 if week % 2 == 0 else 1,
        )
        for week in range(1, 7)
    )
    assert any(not row.home for row in training)
    fitted = FootballUnitStrengthModel(training, cutoff=T + timedelta(days=50))
    target = projection()
    home = fitted.predict(target)
    away = fitted.predict(replace(target, home=False))
    assert home.own_goal_rate > away.own_goal_rate
    assert home.causal_baseline_own_goal_rate == away.causal_baseline_own_goal_rate == 1.4
    neutral = projection(replacement=False)
    assert fitted.predict(neutral).own_goal_rate == 1.4
    assert fitted.predict(replace(neutral, home=False)).own_goal_rate == 1.4


def test_offset_fitting_uses_baseline_weighted_exposure(monkeypatch: pytest.MonkeyPatch):
    from squadopt.prediction import football_unit_strength as module

    captured: dict[str, Any] = {}
    original = module.PoissonRegressor.fit

    def spy(self: Any, x: Any, y: Any, **kwargs: Any) -> Any:
        captured["y"] = y.copy()
        captured["weights"] = kwargs["sample_weight"].copy()
        return original(self, x, y, **kwargs)

    monkeypatch.setattr(module.PoissonRegressor, "fit", spy)
    training = (observation(1, replacement=True, minutes=30, own_baseline=3, opponent_baseline=6),)
    FootballUnitStrengthModel(training, cutoff=T + timedelta(days=50))
    np.testing.assert_array_equal(captured["weights"], [1, 2])
    np.testing.assert_array_equal(captured["y"], [5, 0.5])


def test_segment_duration_and_goal_counts_define_same_offset_likelihood():
    whole = observation(2, replacement=True)
    whole_model = FootballUnitStrengthModel((whole,), cutoff=T + timedelta(days=50))
    halves = (
        replace(whole, minutes=45, own_goals=2, opponent_goals=0),
        replace(whole, start_minute=45, minutes=45, own_goals=3, opponent_goals=1),
    )
    split_model = FootballUnitStrengthModel(halves, cutoff=T + timedelta(days=50))
    assert whole_model.predict(projection()).own_goal_rate == pytest.approx(
        split_model.predict(projection()).own_goal_rate, rel=1e-8
    )


def test_input_and_observation_order_do_not_change_features_or_predictions():
    training = observations()
    first = FootballUnitStrengthModel(training, cutoff=T + timedelta(days=50))
    reordered = tuple(
        replace(
            x,
            catalog=replace(
                x.catalog,
                sources=tuple(reversed(x.catalog.sources)),
                attributes=tuple(reversed(x.catalog.attributes)),
                mappings=tuple(reversed(x.catalog.mappings)),
                player_attributes=tuple(reversed(x.catalog.player_attributes)),
            ),
        )
        for x in reversed(training)
    )
    second = FootballUnitStrengthModel(reordered, cutoff=T + timedelta(days=50))
    a, b = first.predict(projection()), second.predict(projection())
    assert a.own_goal_rate == b.own_goal_rate
    assert a.feature_contract == b.feature_contract
    assert a.metadata == b.metadata


def test_missing_attributes_are_explicit_and_cold_start_has_zero_identity_effect(
    model: FootballUnitStrengthModel,
):
    target = projection(missing=True)
    old = target.catalog
    novel = replace(
        unit(1),
        players=tuple(UnitPlayer(13, "FWD") if x.player_id == 11 else x for x in unit(1).players),
    )
    mapped = replace(
        old,
        mappings=(
            *old.mappings,
            PlayerMapping("synthetic", "13", 13, 1, T, target.decision_cutoff + timedelta(days=1)),
        ),
    )
    result = model.predict(
        replace(target, catalog=mapped, states=(ProjectedUnitState(1, novel, unit(2)),))
    )
    assert math.isfinite(result.own_goal_rate)
    assert 13 not in result.metadata["player_vocabulary"]
    assert any("missing" in x for x in result.feature_contract)
    assert model._unit(mapped, novel)[0 : len(model.player_vocabulary)] == [
        float(i in {x.player_id for x in novel.players}) for i in model.player_vocabulary
    ]


def test_real_club_unit_does_not_apply_fpl_minimum_defender_rule():
    players = (UnitPlayer(1, "GK"), *tuple(UnitPlayer(i, "MID") for i in range(2, 12)))
    assert ClubUnit(1, players).players == players


@pytest.mark.parametrize(
    "players",
    [
        unit(1).players[:-1],
        (*unit(1).players, UnitPlayer(12, "FWD")),
        (*unit(1).players[:-1], unit(1).players[0]),
        (UnitPlayer(1, "DEF"), *unit(1).players[1:]),
        (*unit(1).players[:-1], UnitPlayer(12, "GK")),
    ],
)
def test_partial_red_card_duplicate_and_invalid_keeper_units_refused(
    players: tuple[UnitPlayer, ...],
):
    with pytest.raises(ValueError):
        ClubUnit(1, players)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "fm", "rights_reference": "synthetic:unit-test"},
        {"permitted_model_development": False},
        {"sha256": "invalid"},
        {"provider": ""},
        {"version": ""},
        {"rights_reference": ""},
        {"published_at": T + timedelta(hours=1)},
        {"valid_until": T - timedelta(days=2)},
        {"published_at": T.replace(tzinfo=None)},
    ],
)
def test_invalid_source_evidence_refused(change: dict[str, Any]):
    with pytest.raises(ValueError):
        changed = source(T, **change)
        replace(catalog(), sources=(changed,))


@pytest.mark.parametrize("field", ["published_at", "captured_at", "effective_at"])
def test_postdeadline_information_is_refused_even_before_kickoff(field: str):
    kwargs = {field: T + timedelta(minutes=30)}
    if field == "published_at":
        kwargs["captured_at"] = T + timedelta(minutes=40)
    changed = source(T, **kwargs)
    with pytest.raises(ValueError, match="decision cutoff"):
        replace(catalog(), sources=(changed,))


@pytest.mark.parametrize("value", [True, math.nan, math.inf, 0.0, 21.0])
def test_invalid_numeric_attribute_semantics_refused(value: float):
    with pytest.raises(ValueError):
        replace(
            catalog(),
            player_attributes=(PlayerAttributes("synthetic", "1", (("finishing", value),)),),
        )


def test_actual_fm_contract_requires_declared_1_to_20_scale():
    # Fictional rights evidence exercises validation, never proves actual FM permission.
    fm = source(T, kind="fm", rights_reference="fictional-test-license:model-development")
    invalid = replace(catalog().attributes[0], minimum=0)
    with pytest.raises(ValueError, match="1 to 20"):
        replace(catalog(), sources=(fm,), attributes=(invalid,))


@pytest.mark.parametrize(
    "change",
    [
        {"mappings": (*catalog().mappings, catalog().mappings[0])},
        {
            "mappings": (
                *catalog().mappings,
                replace(catalog().mappings[0], source_player_id="other"),
            )
        },
        {"attributes": catalog().attributes * 2},
        {"player_attributes": catalog().player_attributes * 2},
        {"baseline_source_id": "missing"},
        {"player_attributes": (PlayerAttributes("synthetic", "999", (("finishing", 10),)),)},
        {"player_attributes": (PlayerAttributes("synthetic", "1", (("undeclared", 10),)),)},
    ],
)
def test_catalog_ambiguity_and_missing_source_refused(change: dict[str, Any]):
    with pytest.raises(ValueError):
        replace(catalog(), **change)


def test_mapping_to_two_clubs_and_unmapped_complete_unit_refused():
    base = catalog()
    other = source(T, source_id="other")
    with pytest.raises(ValueError, match="multiple clubs"):
        replace(
            base,
            sources=(*base.sources, other),
            mappings=(*base.mappings, replace(base.mappings[0], source_id="other", club=2)),
        )
    target = projection()
    incomplete = replace(
        target.catalog,
        mappings=target.catalog.mappings[1:],
        player_attributes=target.catalog.player_attributes[1:],
    )
    with pytest.raises(ValueError, match="active persistent"):
        replace(target, catalog=incomplete)


def test_player_with_an_active_mapping_to_another_club_cannot_enter_complete_unit():
    base = catalog()
    changed = replace(
        base,
        mappings=tuple(replace(m, club=2) if m.player_id == 11 else m for m in base.mappings),
    )
    with pytest.raises(ValueError, match="active persistent mappings"):
        changed.validate_unit(unit(1))


@pytest.mark.parametrize(
    "values", ((("finishing", None), ("finishing", 5.0)), (("finishing", 5.0), ("finishing", None)))
)
def test_duplicate_attribute_name_with_missing_value_has_declared_refusal(values):
    with pytest.raises(ValueError, match="Duplicate numeric attribute"):
        PlayerAttributes("synthetic", "1", values)


def test_catalog_indexes_preserve_serialized_facts_and_explicit_missingness():
    base = catalog(missing=True)
    original = asdict(base)
    assert "_club_index" not in original and "_value_index" not in original
    assert base.value(12, base.attributes[0]) is None
    assert base.value(999, base.attributes[0]) is None
    with pytest.raises(TypeError):
        base.__dict__["_value_index"]["synthetic", 12, "finishing"] = 10
    with pytest.raises(TypeError):
        base.__dict__["_club_index"][12] = 2
    assert asdict(base) == original


def test_catalog_lookups_do_not_rescan_source_snapshots_or_temporal_mappings():
    class NoScan(tuple):
        def __iter__(self):
            raise AssertionError("A repeated lookup must not scan the original catalog.")

    base = catalog()
    object.__setattr__(base, "mappings", NoScan(base.mappings))
    object.__setattr__(base, "player_attributes", NoScan(base.player_attributes))
    base.validate_unit(unit(1))
    assert base.value(12, base.attributes[0]) == 19.0
    assert base.value(1, base.attributes[0]) == 8.0
    assert base.value(999, base.attributes[0]) is None


@pytest.mark.parametrize(
    "change",
    [
        {"states": ()},
        {"states": (ProjectedUnitState(0.9, unit(1), unit(2)),)},
        {"states": (ProjectedUnitState(0.5, unit(1), unit(2)),) * 2},
        {"captured_at": T + timedelta(days=56, minutes=1)},
        {"decision_cutoff": T + timedelta(days=56, hours=2)},
        {"fixture_id": 999},
        {"home": 1},
        {"causal_baseline_own_goal_rate": 0},
        {"causal_baseline_opponent_goal_rate": math.inf},
    ],
)
def test_incomplete_future_unscoped_or_invalid_projection_refused(change: dict[str, Any]):
    with pytest.raises(ValueError):
        replace(projection(), **change)


@pytest.mark.parametrize("probability", [0, -1, 1.1, True, math.nan])
def test_invalid_joint_state_mass_refused(probability: float):
    with pytest.raises(ValueError):
        ProjectedUnitState(probability, unit(1), unit(2))


def test_model_refuses_locked_outcomes_future_outcomes_and_overlapping_exposures():
    current = observation(1, replacement=True)
    locked_catalog = replace(current.catalog, season="2025-26")
    with pytest.raises(ValueError, match="Locked"):
        FootballUnitStrengthModel(
            (replace(current, season="2025-26", catalog=locked_catalog),),
            cutoff=T + timedelta(days=50),
        )
    with pytest.raises(ValueError, match="fitting cutoff"):
        FootballUnitStrengthModel((current,), cutoff=current.outcome_available_at)
    with pytest.raises(ValueError, match="overlapping"):
        FootballUnitStrengthModel((current, current), cutoff=T + timedelta(days=50))


def test_same_and_future_gameweeks_refused_even_with_settled_earlier_kickoff():
    target = projection()
    for week in (8, 9):
        current = observation(1, replacement=True)
        current = replace(current, gameweek=week, catalog=replace(current.catalog, gameweek=week))
        fitted = FootballUnitStrengthModel((current,), cutoff=T + timedelta(days=50))
        with pytest.raises(ValueError, match="same or a future gameweek"):
            fitted.predict(target)


def test_provider_and_attribute_definition_change_refused(model: FootballUnitStrengthModel):
    target = projection()
    for changed in (
        replace(target.catalog, sources=(replace(target.catalog.sources[0], provider="other"),)),
        replace(
            target.catalog,
            attributes=(replace(target.catalog.attributes[0], definition="Changed scale meaning"),),
        ),
    ):
        with pytest.raises(ValueError, match="differ from fit"):
            model.predict(replace(target, catalog=changed))


def test_dated_editions_and_rights_receipts_can_change_with_identical_semantics():
    training = tuple(
        replace(
            x,
            catalog=replace(
                x.catalog,
                sources=(
                    replace(
                        x.catalog.sources[0],
                        version=f"edition-{x.gameweek}",
                        rights_reference=f"synthetic:edition-{x.gameweek}",
                    ),
                ),
            ),
        )
        for x in observations()
    )
    fitted = FootballUnitStrengthModel(training, cutoff=T + timedelta(days=50))
    target = projection()
    newer = replace(
        target.catalog,
        sources=(
            replace(
                target.catalog.sources[0],
                version="edition-26",
                rights_reference="synthetic:edition-26",
                sha256="b" * 64,
            ),
        ),
    )
    result = fitted.predict(replace(target, catalog=newer))
    original = fitted.predict(target)
    assert result.own_goal_rate == original.own_goal_rate
    assert result.metadata["attribute_contract"] == original.metadata["attribute_contract"]
    assert (
        result.metadata["projection_catalog_sha256"]
        != original.metadata["projection_catalog_sha256"]
    )
    assert "edition-26" in str(result.metadata["projection_source_receipts"])
    assert "edition-2" in str(result.metadata["training_source_receipts"])


def test_one_gameweek_cannot_have_multiple_historical_decision_cutoffs():
    first = observation(1, replacement=True)
    second = observation(2, replacement=False)
    changed = replace(second, gameweek=1, catalog=replace(second.catalog, gameweek=1))
    with pytest.raises(ValueError, match="share its decision cutoff"):
        FootballUnitStrengthModel((first, changed), cutoff=T + timedelta(days=50))


def test_one_fixture_cannot_change_reference_basis_between_segments():
    first = replace(observation(1, replacement=True), minutes=45)
    second = replace(first, start_minute=45, reference_own=unit(1, replacement=True))
    with pytest.raises(ValueError, match="same predecision reference"):
        FootballUnitStrengthModel((first, second), cutoff=T + timedelta(days=50))


def test_tiny_probability_roundoff_is_explicitly_normalized():
    target = projection()
    changed = replace(
        target,
        states=(
            ProjectedUnitState(0.5, unit(1), unit(2)),
            ProjectedUnitState(0.5 + 1e-14, unit(1, replacement=True), unit(2)),
        ),
    )
    assert math.fsum(x.probability for x in changed.states) == 1
    assert changed.states[0].probability != 0.5


def test_goal_receipt_changes_training_identity_even_with_unchanged_sources():
    training = observations()
    original = FootballUnitStrengthModel(training, cutoff=T + timedelta(days=50)).predict(
        projection()
    )
    changed = (replace(training[0], own_goals=2), *training[1:])
    alternative = FootballUnitStrengthModel(changed, cutoff=T + timedelta(days=50)).predict(
        projection()
    )
    assert (
        original.metadata["training_catalog_sha256"]
        == alternative.metadata["training_catalog_sha256"]
    )
    assert (
        original.metadata["training_observation_sha256"]
        != alternative.metadata["training_observation_sha256"]
    )


def test_same_marginals_different_joint_units_do_not_produce_fabricated_independence():
    base = observation(1, replacement=False)
    training = tuple(
        replace(
            base,
            fixture_id=i,
            gameweek=i,
            decision_cutoff=T + timedelta(days=i * 7),
            kickoff=T + timedelta(days=i * 7, hours=2),
            outcome_available_at=T + timedelta(days=i * 7, hours=6),
            outcome_source=source(T + timedelta(days=i * 7, hours=6)),
            catalog=catalog(week=i, fixture=i, cutoff=T + timedelta(days=i * 7)),
            own=unit(1, replacement=bool(i % 2)),
            opponent=unit(2, replacement=bool(i // 2 % 2)),
            own_goals=1 + 3 * (i % 2) + 4 * (i // 2 % 2),
            opponent_goals=1 + 4 * (i % 2) + 3 * (i // 2 % 2),
        )
        for i in range(1, 5)
    )
    fitted = FootballUnitStrengthModel(training, cutoff=T + timedelta(days=50))
    target = projection()
    correlated = replace(
        target,
        states=(
            ProjectedUnitState(0.5, unit(1), unit(2)),
            ProjectedUnitState(0.5, unit(1, replacement=True), unit(2, replacement=True)),
        ),
    )
    anticorrelated = replace(
        target,
        states=(
            ProjectedUnitState(0.5, unit(1, replacement=True), unit(2)),
            ProjectedUnitState(0.5, unit(1), unit(2, replacement=True)),
        ),
    )
    assert fitted.predict(correlated).own_goal_rate != pytest.approx(
        fitted.predict(anticorrelated).own_goal_rate
    )


def test_fit_refuses_nonfinite_offset_target():
    current = replace(observation(1, replacement=True), causal_baseline_own_goal_rate=1e-310)
    with pytest.raises(ValueError, match="must remain finite"):
        FootballUnitStrengthModel((current,), cutoff=T + timedelta(days=50))


def test_finite_source_values_cannot_silently_overflow_train_only_scaling():
    current = observation(1, replacement=True)
    changed_catalog = replace(
        current.catalog,
        attributes=(replace(current.catalog.attributes[0], minimum=0, maximum=1e308),),
        player_attributes=tuple(
            replace(x, values=(("finishing", 1e308),)) if x.source_player_id == "12" else x
            for x in current.catalog.player_attributes
        ),
    )
    with pytest.raises(ValueError, match="standardized features must remain finite"):
        FootballUnitStrengthModel(
            (replace(current, catalog=changed_catalog),), cutoff=T + timedelta(days=50)
        )


def test_unrepresentable_goal_count_is_a_declared_range_error():
    current = replace(observation(1, replacement=True), own_goals=10**500)
    with pytest.raises(ValueError, match="supported numerical range"):
        FootballUnitStrengthModel((current,), cutoff=T + timedelta(days=50))


def test_wide_identity_training_and_prediction_use_only_sparse_relative_rows(
    monkeypatch: pytest.MonkeyPatch,
):
    from scipy.sparse import isspmatrix_csr

    from squadopt.prediction import football_unit_strength as module

    def remap_unit(original: ClubUnit, offset: int) -> ClubUnit:
        return replace(
            original,
            players=tuple(replace(p, player_id=p.player_id + offset) for p in original.players),
        )

    training = []
    for i in range(24):
        current = observation(i // 2 + 1, replacement=bool(i % 2))
        offset = i * 1000
        mapped = replace(
            current.catalog,
            fixture_id=i + 1,
            mappings=tuple(
                replace(
                    m, player_id=m.player_id + offset, source_player_id=str(m.player_id + offset)
                )
                for m in current.catalog.mappings
            ),
            player_attributes=tuple(
                replace(a, source_player_id=str(int(a.source_player_id) + offset))
                for a in current.catalog.player_attributes
            ),
        )
        training.append(
            replace(
                current,
                fixture_id=i + 1,
                catalog=mapped,
                own=remap_unit(current.own, offset),
                opponent=remap_unit(current.opponent, offset),
                reference_own=remap_unit(current.reference_own, offset),
                reference_opponent=remap_unit(current.reference_opponent, offset),
            )
        )

    captured: dict[str, Any] = {}
    original_fit = module.PoissonRegressor.fit

    def spy(self: Any, x: Any, y: Any, **kwargs: Any) -> Any:
        captured["csr"] = isspmatrix_csr(x)
        captured["shape"] = x.shape
        captured["nnz"] = x.nnz
        return original_fit(self, x, y, **kwargs)

    def refuse_dense_helper(*args: Any) -> list[float]:
        raise AssertionError("The full vocabulary dense inspection helper is not a fit path.")

    monkeypatch.setattr(module.PoissonRegressor, "fit", spy)
    monkeypatch.setattr(FootballUnitStrengthModel, "_unit", refuse_dense_helper)
    fitted = FootballUnitStrengthModel(tuple(training), cutoff=T + timedelta(days=100))
    assert captured["csr"]
    assert fitted.training_matrix_shape == captured["shape"] == (48, 2208)
    assert fitted.training_matrix_nnz == captured["nnz"] == 108
    dense_bytes = math.prod(fitted.training_matrix_shape) * 8
    assert fitted.training_matrix_storage_bytes < dense_bytes / 100
    target = projection(replacement=False)
    later = replace(
        target,
        gameweek=20,
        fixture_id=20,
        decision_cutoff=T + timedelta(days=140),
        kickoff=T + timedelta(days=140, hours=2),
        captured_at=T + timedelta(days=140),
        catalog=catalog(week=20, fixture=20, cutoff=T + timedelta(days=140)),
    )
    result = fitted.predict(later)
    assert result.own_goal_rate == later.causal_baseline_own_goal_rate


def test_sparse_storage_preserves_dense_offset_head_and_declared_column_algebra(
    monkeypatch: pytest.MonkeyPatch,
):
    from squadopt.prediction import football_unit_strength as module

    captured: dict[str, Any] = {}
    original_scale = module.StandardScaler.fit_transform
    original_fit = module.PoissonRegressor.fit

    def scale_spy(self: Any, x: Any, **kwargs: Any) -> Any:
        captured["raw"] = x.copy()
        return original_scale(self, x, **kwargs)

    def fit_spy(self: Any, x: Any, y: Any, **kwargs: Any) -> Any:
        captured["y"] = y.copy()
        captured["weights"] = kwargs["sample_weight"].copy()
        return original_fit(self, x, y, **kwargs)

    monkeypatch.setattr(module.StandardScaler, "fit_transform", scale_spy)
    monkeypatch.setattr(module.PoissonRegressor, "fit", fit_spy)
    fitted = FootballUnitStrengthModel(observations(), cutoff=T + timedelta(days=50))
    monkeypatch.setattr(module.StandardScaler, "fit_transform", original_scale)
    monkeypatch.setattr(module.PoissonRegressor, "fit", original_fit)
    scaler = module.StandardScaler(with_mean=False)
    dense = scaler.fit_transform(captured["raw"].toarray(), sample_weight=captured["weights"])
    head = module.PoissonRegressor(alpha=0.1, fit_intercept=False, max_iter=1000, tol=1e-12)
    head.fit(dense, captured["y"], sample_weight=captured["weights"])
    query = np.zeros((1, len(fitted.feature_contract)))
    for label, value in (
        ("own_player_11", -1),
        ("own_player_12", 1),
        ("own_FWD_synthetic:finishing_value", 1),
    ):
        query[0, fitted.feature_contract.index(label)] = value
        query[0, fitted.feature_contract.index("home_interaction:" + label)] = value
    expected = 1.4 * head.predict(scaler.transform(query))[0]
    assert fitted.predict(projection()).own_goal_rate == pytest.approx(expected, rel=1e-8)
    np.testing.assert_allclose(fitted._scaler.scale_, scaler.scale_, rtol=1e-14, atol=1e-14)


def test_frozen_inputs_results_and_metadata(model: FootballUnitStrengthModel):
    target = projection()
    result = model.predict(target)
    with pytest.raises(FrozenInstanceError):
        target.home = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.own_goal_rate = 0  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.metadata["regularization"] = 0  # type: ignore[index]
    assert result.causal_baseline_own_goal_rate == 1.4
    assert result.decision_cutoff == target.decision_cutoff
    assert result.season == target.season
    assert result.gameweek == 8


def test_forecast_default_head_has_no_dependency_on_unit_model():
    from squadopt.prediction.football import FOOTBALL_MODEL_VERSION, FixtureFootballModel

    assert FOOTBALL_MODEL_VERSION == "football_team_share_v1"
    assert FixtureFootballModel.model_version == FOOTBALL_MODEL_VERSION
    assert not issubclass(FootballUnitStrengthModel, FixtureFootballModel)
