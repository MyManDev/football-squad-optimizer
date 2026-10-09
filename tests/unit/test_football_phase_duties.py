"""Independent synthetic checks of phase learning and complete-state allocation."""

from __future__ import annotations

import itertools
import json
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime, timedelta

import pytest

from squadopt.features.football_phase_inputs import (
    PHASE_DEFINITION_VERSION,
    PhaseDutyCapture,
    PhaseDutyPlayer,
    PhaseGoal,
    PhaseObservation,
    PhasePlayer,
    PhaseProjection,
    PhaseSource,
    PhaseState,
    PhaseTotal,
    observation_digest,
    projection_digest,
)
from squadopt.prediction import football_phase_duties as duty_module
from squadopt.prediction.football_phase_duties import (
    FEATURE_VERSION,
    MODEL_VERSION,
    PENALTY_MISS_POLICY,
    PhaseDutyModel,
)

CUTOFF = "2026-10-09T00:00:00Z"
CODES = (101, 102, 103)


def _stamp(value: datetime) -> str:
    return value.isoformat()


def _source(kind: str, moment: str, suffix: str = "synthetic") -> PhaseSource:
    return PhaseSource(
        source_id=f"{kind}-{suffix}",
        provider="synthetic-only",
        version="synthetic-v1",
        raw_sha256="b" * 64,
        published_at=moment,
        captured_at=moment,
        source_kind=kind,
        model_use_approved=True,
        model_use_evidence_ref="synthetic-only",
    )


def _duties(season: str, captured: str, expiry: str, ranks=(1, 2, 3)) -> PhaseDutyCapture:
    return PhaseDutyCapture(
        season=season,
        snapshot_id="synthetic-priorities",
        source_fingerprint="a" * 64,
        captured_at=captured,
        valid_until=expiry,
        model_use_approved=True,
        model_use_evidence_ref="synthetic-only",
        players=tuple(
            PhaseDutyPlayer(code, 1, rank, rank, rank)
            for code, rank in zip(CODES, ranks, strict=True)
        ),
    )


def _players(minutes=(90.0, 90.0, 90.0), weights=(1.0, 1.0, 1.0)):
    return tuple(
        PhasePlayer(code, "MID", exposure, weight, weight)
        for code, exposure, weight in zip(CODES, minutes, weights, strict=True)
    )


def _observation(index=1, *, events=None, ranks=(1, 2, 3), players=None, season="2024-25"):
    kickoff = datetime(int(season[:4]), 9, 1, 15, tzinfo=UTC) + timedelta(days=index)
    decision = _stamp(kickoff - timedelta(hours=1))
    available = _stamp(kickoff + timedelta(hours=3))
    players = _players() if players is None else players
    events = (
        (PhaseGoal(f"goal-{index}", "other", 101, 102, False, "synthetic-final-credit"),)
        if events is None
        else events
    )
    totals = {
        code: [
            sum(event.scorer == code for event in events),
            sum(event.assist == code for event in events),
        ]
        for code in CODES
    }
    return PhaseObservation(
        season=season,
        gameweek=index,
        fixture=index,
        club=1,
        opponent=2,
        home=True,
        kickoff=_stamp(kickoff),
        decision_at=decision,
        outcome_available_at=available,
        duties=_duties(season, decision, _stamp(kickoff), ranks),
        baseline_source=_source("baseline", decision, str(index)),
        outcome_source=_source("phase-events", available, str(index)),
        totals_source=_source("fpl-totals", available, str(index)),
        players=players,
        events=events,
        totals=tuple(PhaseTotal(code, *totals[code]) for code in CODES),
        phase_definition_version=PHASE_DEFINITION_VERSION,
        rules_version=f"synthetic-fpl-credit-{season}",
        complete_coverage=True,
    )


def _projection(*, states=None, ranks=(1, 2, 3)):
    return PhaseProjection(
        season="2026-27",
        gameweek=6,
        fixture=600,
        club=1,
        opponent=2,
        home=True,
        kickoff="2026-10-10T15:00:00Z",
        decision_at=CUTOFF,
        duties=_duties("2026-27", "2026-10-08T00:00:00Z", "2026-10-10T15:00:00Z", ranks),
        states=(PhaseState("all-play", 1.0, _players(), 2.0, 1.0, 3.0),)
        if states is None
        else states,
        source=_source("projection", CUTOFF),
    )


def _fit(observations=None, **kwargs):
    return PhaseDutyModel(**kwargs).fit(
        (_observation(),) if observations is None else observations,
        cutoff=CUTOFF,
        allowed_seasons=("2024-25",),
        target_season="2026-27",
        target_gameweek=6,
    )


def _rank_training(phase: str):
    observations = []
    for index, ordering in enumerate(itertools.permutations((1, 2, 3)), start=1):
        first = CODES[ordering.index(1)]
        second = CODES[ordering.index(2)]
        events = tuple(
            PhaseGoal(f"{phase}-{index}-{n}", phase, first, second, False, "synthetic-credit")
            for n in range(4)
        )
        observations.append(_observation(index, events=events, ranks=ordering))
    return tuple(observations)


def test_empirical_phase_compositions_use_separate_credited_goals_and_assists():
    events = (
        PhaseGoal("p", "penalty", 101, None, False, "credit"),
        PhaseGoal("c1", "corner", 102, 101, False, "credit"),
        PhaseGoal("c2", "corner", 103, 102, False, "credit"),
        PhaseGoal("og", "other", None, 101, True, "credit"),
    )
    result = _fit((_observation(events=events),)).predict(_projection())
    assert result.goal_phase_shares == pytest.approx((1 / 3, 0, 2 / 3, 0, 0))
    assert result.assist_phase_shares == pytest.approx((0, 0, 2 / 3, 0, 1 / 3))
    assert result.metadata.goal_events == result.metadata.assist_events == 3
    assert all(head.phase != "delivered_free_kick" for head in result.metadata.recipient_heads)
    assert sum(player.goals for player in result.players) == pytest.approx(2)
    assert sum(player.assists for player in result.players) == pytest.approx(1)


@pytest.mark.parametrize("phase", ["penalty", "direct_free_kick"])
def test_learned_taker_goal_effect_changes_but_fouled_player_assist_does_not(phase):
    model = _fit(_rank_training(phase))
    original = model.predict(_projection())
    changed = model.predict(_projection(ranks=(3, 2, 1)))
    assert original.players[0].goals > original.players[2].goals
    assert changed.players[2].goals > changed.players[0].goals
    assert [p.assists for p in changed.players] == pytest.approx(
        [p.assists for p in original.players]
    )
    assist_head = next(head for head in original.metadata.recipient_heads if head.head == "assists")
    assert all(
        "rank" not in feature and "priority" not in feature for feature in assist_head.features
    )
    assert original.total_goals == changed.total_goals == 2
    assert original.total_assists == changed.total_assists == 1


@pytest.mark.parametrize("phase", ["penalty", "direct_free_kick"])
def test_taker_rank_correlation_cannot_replace_fouled_player_assist_features(phase):
    observations = []
    for index, ordering in enumerate(itertools.permutations((1, 2, 3)), start=1):
        scorer = CODES[ordering.index(1)]
        winner = CODES[ordering.index(3)]
        events = tuple(
            PhaseGoal(f"winner-{index}-{n}", phase, scorer, winner, False, "credit")
            for n in range(4)
        )
        observations.append(_observation(index, events=events, ranks=ordering))
    model = _fit(tuple(observations))
    original = model.predict(_projection())
    changed = model.predict(_projection(ranks=(3, 2, 1)))
    assert [p.assists for p in original.players] == pytest.approx([1 / 3] * 3)
    assert [p.assists for p in changed.players] == pytest.approx(
        [p.assists for p in original.players]
    )


@pytest.mark.parametrize("phase", ["corner", "delivered_free_kick"])
def test_delivery_assists_learn_captured_priorities_without_claiming_scorer_duty(phase):
    # The first priority delivers to the second priority. Recipient head directions
    # therefore differ from the penalty-goal fixture above.
    observations = []
    for index, ordering in enumerate(itertools.permutations((1, 2, 3)), start=1):
        taker = CODES[ordering.index(1)]
        scorer = CODES[ordering.index(2)]
        events = tuple(
            PhaseGoal(f"d{index}-{n}", phase, scorer, taker, False, "credit") for n in range(4)
        )
        observations.append(_observation(index, events=events, ranks=ordering))
    model = _fit(tuple(observations))
    original = model.predict(_projection())
    changed = model.predict(_projection(ranks=(3, 2, 1)))
    assert original.players[0].assists > original.players[2].assists
    assert changed.players[2].assists > changed.players[0].assists
    assert [p.goals for p in changed.players] == pytest.approx([p.goals for p in original.players])


@pytest.mark.parametrize("ranks", [(None, None, None), (1, 1, 2)])
def test_null_and_tied_priorities_preserve_equal_supported_recipients(ranks):
    result = _fit(_rank_training("penalty")).predict(_projection(ranks=ranks))
    assert result.players[0].goals == pytest.approx(result.players[1].goals)
    assert sum(player.goals for player in result.players) == pytest.approx(2)
    assert result.metadata.penalty_miss_treatment == PENALTY_MISS_POLICY


def test_absent_first_priority_has_no_share_and_live_remaining_players_receive_mass():
    state = PhaseState("first-absent", 1.0, _players(minutes=(0, 90, 90)), 2.0, 0.0, 2.0)
    result = _fit(_rank_training("penalty")).predict(_projection(states=(state,)))
    assert result.players[0].goals == result.players[0].goals_share == 0
    assert result.players[1].goals > result.players[2].goals
    assert sum(player.goals for player in result.players) == pytest.approx(2)


def test_recipient_exposure_uses_actual_minutes_once_without_appearance_weight():
    state = PhaseState("different-minutes", 1.0, _players(minutes=(90, 45, 0)), 3.0, 0.0, 3.0)
    result = _fit().predict(_projection(states=(state,)))
    assert [p.goals for p in result.players] == pytest.approx([2.0, 1.0, 0.0])
    assert [p.goals_share for p in result.players] == pytest.approx([2 / 3, 1 / 3, 0])


def test_state_intensity_and_recipient_share_are_integrated_before_averaging():
    states = (
        PhaseState("first-only", 0.5, _players(minutes=(90, 0, 0)), 1.0, 0.0, 1.0),
        PhaseState("others-only", 0.5, _players(minutes=(0, 90, 90)), 3.0, 0.0, 3.0),
    )
    result = _fit().predict(_projection(states=states))
    assert result.total_goals == 2
    assert [p.goals for p in result.players] == pytest.approx([0.5, 0.75, 0.75])
    assert result.players[0].goals != result.total_goals * 0.5
    assert result.players[0].goals_share == pytest.approx(0.25)
    assert sum(p.goals for p in result.players) == pytest.approx(result.total_goals)


def test_quarter_state_participation_is_not_applied_twice():
    states = (
        PhaseState("flagged-plays", 0.25, _players(minutes=(90, 0, 0)), 2.0, 0.0, 2.0),
        PhaseState("replacement-plays", 0.75, _players(minutes=(0, 90, 0)), 2.0, 0.0, 2.0),
    )
    result = _fit().predict(_projection(states=states))
    assert [p.goals for p in result.players] == pytest.approx([0.5, 1.5, 0])
    assert result.total_goals == 2


def test_player_tuple_reordering_cannot_exchange_persistent_recipient_credit():
    original = _projection()
    reordered = replace(
        original,
        states=(replace(original.states[0], players=tuple(reversed(original.states[0].players))),),
    )
    model = _fit(_rank_training("penalty"))
    first, second = model.predict(original), model.predict(reordered)
    assert first.players == second.players
    assert first.projection_sha256 != second.projection_sha256


def test_zero_mass_retains_meaningful_learned_share_without_creating_events():
    result = _fit().predict(_projection(states=(PhaseState("zero", 1, _players(), 0, 0, 0),)))
    assert all(p.goals == p.assists == 0 for p in result.players)
    assert [p.goals_share for p in result.players] == pytest.approx([1 / 3] * 3)
    assert [p.assists_share for p in result.players] == pytest.approx([1 / 3] * 3)
    assert result.total_goals == result.total_assists == result.physical_goal_mass == 0


def test_unavailable_whole_head_refuses_positive_mass_but_zero_is_explicit():
    empty = _observation(events=())
    model = _fit((empty,))
    with pytest.raises(ValueError, match="without historical credited events"):
        model.predict(_projection())
    result = model.predict(_projection(states=(PhaseState("zero", 1, _players(), 0, 0, 0),)))
    assert result.goal_phase_shares == result.assist_phase_shares == (0.0,) * 5
    assert (
        result.metadata.goal_status
        == result.metadata.assist_status
        == "unavailable_no_credited_events"
    )
    assert all(p.goals_share == p.assists_share == 0 for p in result.players)


def test_one_unavailable_assist_head_refuses_positive_assist_mass_only():
    events = (PhaseGoal("g", "other", 101, None, False, "credit"),)
    model = _fit((_observation(events=events),))
    with pytest.raises(ValueError, match="Phase assists unavailable"):
        model.predict(_projection())
    result = model.predict(_projection(states=(PhaseState("no-assists", 1, _players(), 1, 0, 1),)))
    assert result.total_goals == 1 and result.total_assists == 0
    assert all(p.assists_share == 0 for p in result.players)


def test_separate_marginals_refuse_impossible_same_player_credit_mass():
    state = PhaseState("impossible", 1, _players(weights=(1e9, 1e-9, 1e-9)), 1, 1, 1)
    with pytest.raises(ValueError, match="exceeds physical scoring-event mass"):
        _fit().predict(_projection(states=(state,)))


def test_goal_and_assist_concentration_can_be_valid_with_larger_physical_mass():
    state = PhaseState("physical-two", 1, _players(weights=(1e9, 1e-9, 1e-9)), 1, 1, 2)
    result = _fit().predict(_projection(states=(state,)))
    assert result.players[0].goals + result.players[0].assists == pytest.approx(2)
    assert result.physical_goal_mass == 2


def test_credited_training_event_with_zero_native_weight_refuses_instead_of_floor():
    observation = _observation(players=_players(weights=(0, 1, 1)))
    with pytest.raises(ValueError, match="no observed recipient exposure"):
        _fit((observation,))


def test_all_source_headers_are_checked_before_any_event_labels():
    malformed = replace(_observation(), events=(object(),))
    protected = replace(_observation(2), season="2025-26")
    with pytest.raises(ValueError, match="protected"):
        _fit((malformed, protected))


@pytest.mark.parametrize("gameweek", [6, 7])
def test_target_and_later_gameweek_are_refused_even_with_earlier_supplied_clocks(gameweek):
    observation = replace(_observation(season="2026-27"), gameweek=gameweek)
    with pytest.raises(ValueError, match=r"target|later"):
        PhaseDutyModel().fit(
            (observation,),
            cutoff=CUTOFF,
            allowed_seasons=("2026-27",),
            target_season="2026-27",
            target_gameweek=6,
        )


def test_duplicate_training_club_fixture_is_refused():
    with pytest.raises(ValueError, match="Duplicate"):
        _fit((_observation(), _observation()))


@pytest.mark.parametrize(
    "change",
    [
        {"gameweek": 5},
        {"season": "2027-28", "kickoff": "2027-10-10T15:00:00Z"},
        {"decision_at": "2026-10-08T23:59:59Z"},
    ],
)
def test_prediction_cannot_move_before_fitted_target_or_cutoff(change):
    projection = replace(_projection(), **change)
    if "season" in change:
        projection = replace(
            projection,
            duties=replace(
                projection.duties, season=change["season"], valid_until=change["kickoff"]
            ),
        )
    with pytest.raises(ValueError, match=r"window|cutoff"):
        _fit().predict(projection)


def test_later_projection_window_can_reuse_frozen_predecision_model():
    result = _fit().predict(replace(_projection(), gameweek=7))
    assert result.total_goals == 2


def test_metadata_binds_full_immutable_training_and_projection_receipts():
    observation = _observation()
    projection = _projection()
    result = _fit((observation,)).predict(projection)
    assert result.model_version == MODEL_VERSION and result.feature_version == FEATURE_VERSION
    assert result.projection_sha256 == projection_digest(projection)
    assert result.metadata.observation_sha256 == (observation_digest(observation),)
    receipt = result.metadata.training_receipts[0]
    assert receipt.duties == observation.duties
    assert receipt.baseline_source == observation.baseline_source
    assert receipt.outcome_source == observation.outcome_source
    assert receipt.totals_source == observation.totals_source
    assert receipt.rules_version == observation.rules_version
    json.dumps(asdict(result), allow_nan=False)
    with pytest.raises(FrozenInstanceError):
        result.players[0].goals = 999


@pytest.mark.parametrize(
    "kwargs",
    [
        {"alpha": True},
        {"alpha": float("nan")},
        {"alpha": float("inf")},
        {"alpha": -0.1},
        {"alpha": 10**400},
        {"max_iter": True},
        {"max_iter": 0},
        {"max_iter": 2.5},
    ],
)
def test_fit_configuration_rejects_coerced_and_nonfinite_values(kwargs):
    with pytest.raises(ValueError, match="finite nonnegative"):
        PhaseDutyModel(**kwargs)


@pytest.mark.parametrize("season", [None, 2026, "", "2026-26", "2025-26"])
def test_fit_target_requires_a_consistent_unprotected_season(season):
    with pytest.raises(ValueError, match="admitted target season"):
        PhaseDutyModel().fit(
            (_observation(),),
            cutoff=CUTOFF,
            allowed_seasons=("2024-25",),
            target_season=season,
            target_gameweek=6,
        )


def test_nonrepresentable_priority_is_not_coerced_to_a_finite_model_feature():
    with pytest.raises(ValueError, match=r"finite recipient feature support|positive integer"):
        _fit(_rank_training("penalty")).predict(_projection(ranks=(10**400, 2, 3)))


def test_unfitted_model_and_unavailable_observation_sequence_refuse():
    with pytest.raises(ValueError, match="fitted"):
        PhaseDutyModel().predict(_projection())
    with pytest.raises(ValueError, match="nonempty immutable"):
        _fit(())


def test_insufficient_optimizer_iterations_are_not_silently_accepted():
    with pytest.raises(ValueError, match="did not converge"):
        _fit(_rank_training("penalty"), max_iter=1)


@pytest.mark.parametrize("name", ["_phase_shares", "_coefficients"])
def test_fitted_parameter_maps_and_array_storage_are_immutable(name):
    model = _fit(_rank_training("penalty"))
    before = model.predict(_projection())
    parameters = getattr(model, name)
    key, values = next(iter(parameters.items()))
    with pytest.raises(TypeError):
        parameters[key] = values.copy()
    with pytest.raises(ValueError, match="read-only"):
        values[0] = 99
    with pytest.raises(ValueError, match="WRITEABLE"):
        values.setflags(write=True)
    with pytest.raises(AttributeError):
        setattr(model, name, {})
    assert model.predict(_projection()) == before


@pytest.mark.parametrize("name", ["alpha", "max_iter", "_metadata"])
def test_declared_fit_parameters_and_metadata_cannot_be_reassigned(name):
    model = _fit()
    before = model.predict(_projection())
    with pytest.raises(AttributeError):
        setattr(model, name, 999)
    assert model.predict(_projection()) == before


def test_used_recipient_arrays_exactly_match_recorded_fitted_coefficients():
    model = _fit(_rank_training("penalty"))
    result = model.predict(_projection())
    for head in result.metadata.recipient_heads:
        assert tuple(model._coefficients[head.head, head.phase]) == head.coefficients
    assert tuple(model._phase_shares["goals"]) == result.goal_phase_shares
    assert tuple(model._phase_shares["assists"]) == result.assist_phase_shares
    assert result.metadata.alpha == model.alpha
    assert result.metadata.max_iter == model.max_iter


def test_public_metadata_requires_fit_and_returns_the_immutable_used_fit_receipt():
    model = PhaseDutyModel()
    with pytest.raises(ValueError, match="before metadata is available"):
        _ = model.metadata
    model.fit(
        (_observation(),),
        cutoff=CUTOFF,
        allowed_seasons=("2024-25",),
        target_season="2026-27",
        target_gameweek=6,
    )
    assert model.metadata is model.predict(_projection()).metadata
    assert model.metadata.cutoff == CUTOFF
    assert model.metadata.observation_sha256 == (observation_digest(_observation()),)
    with pytest.raises(FrozenInstanceError):
        model.metadata.cutoff = "2099-01-01T00:00:00Z"
    with pytest.raises(AttributeError):
        model.metadata = None


def test_failed_refit_after_one_fitted_head_retains_entire_previous_state(monkeypatch):
    model = _fit(_rank_training("penalty"))
    before_state = model._fitted
    before_result = model.predict(_projection())
    original = duty_module._fit_recipient
    calls = 0

    def fail_second_head(groups, *, alpha, max_iter):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic second-head failure")
        return original(groups, alpha=alpha, max_iter=max_iter)

    monkeypatch.setattr(duty_module, "_fit_recipient", fail_second_head)
    with pytest.raises(ValueError, match="second-head failure"):
        model.fit(
            _rank_training("corner"),
            cutoff=CUTOFF,
            allowed_seasons=("2024-25",),
            target_season="2026-27",
            target_gameweek=6,
        )
    assert calls == 2
    assert model._fitted is before_state
    assert model.predict(_projection()) == before_result


def test_failed_first_fit_does_not_publish_any_partial_model(monkeypatch):
    model = PhaseDutyModel()

    def refuse(_groups, *, alpha, max_iter):
        raise ValueError("synthetic optimizer failure")

    monkeypatch.setattr(duty_module, "_fit_recipient", refuse)
    with pytest.raises(ValueError, match="optimizer failure"):
        model.fit(
            (_observation(),),
            cutoff=CUTOFF,
            allowed_seasons=("2024-25",),
            target_season="2026-27",
            target_gameweek=6,
        )
    assert model._fitted is None
    with pytest.raises(ValueError, match="must be fitted"):
        model.predict(_projection())


def test_successful_refit_replaces_all_parameters_and_receipts_together():
    model = _fit()
    before_state = model._fitted
    before_result = model.predict(_projection())
    model.fit(
        _rank_training("penalty"),
        cutoff=CUTOFF,
        allowed_seasons=("2024-25",),
        target_season="2026-27",
        target_gameweek=6,
    )
    result = model.predict(_projection())
    assert model._fitted is not before_state
    assert result.goal_phase_shares == (1, 0, 0, 0, 0)
    assert before_result.goal_phase_shares == (0, 0, 0, 0, 1)
    assert result.metadata.goal_events == 24
    assert before_result.metadata.goal_events == 1
    assert result.metadata.observation_sha256 != before_result.metadata.observation_sha256
    assert result.players != before_result.players


def test_prediction_uses_one_complete_snapshot_even_if_model_is_refitted_midcall(monkeypatch):
    model = _fit()
    before_result = model.predict(_projection())
    original = duty_module._probabilities
    refitted = False

    def refit_once(features, exposure, coefficients):
        nonlocal refitted
        if not refitted:
            refitted = True
            model.fit(
                _rank_training("penalty"),
                cutoff=CUTOFF,
                allowed_seasons=("2024-25",),
                target_season="2026-27",
                target_gameweek=6,
            )
        return original(features, exposure, coefficients)

    monkeypatch.setattr(duty_module, "_probabilities", refit_once)
    assert model.predict(_projection()) == before_result
    assert refitted
    assert model.predict(_projection()) != before_result
