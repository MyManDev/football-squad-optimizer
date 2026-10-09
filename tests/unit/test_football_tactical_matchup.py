"""Synthetic paired tactical likelihood, causal fitting and marginal checks."""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

import squadopt.prediction.football_tactical_matchup as tactical
from squadopt.features.football_tactical_inputs import (
    STYLE_DEFINITION_VERSION,
    TRAIT_DEFINITION_VERSION,
    TRAITS,
    TacticalCredit,
    TacticalJointState,
    TacticalObservation,
    TacticalPlayerState,
    TacticalProfile,
    TacticalProjection,
    TacticalSideState,
    TacticalSource,
    TacticalStyle,
    TacticalStyleFixture,
    observation_digest,
    projection_digest,
)
from squadopt.prediction.football_tactical_matchup import TacticalMatchupModel

CUTOFF = "2026-10-09T00:00:00Z"
TARGET_SEASON = "2026-27"
TARGET_GAMEWEEK = 6


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _source(kind: Any, at: str, identity: str = "synthetic") -> TacticalSource:
    return TacticalSource(
        identity, "synthetic-only", "1", "a" * 64, at, at, kind, True, "synthetic-only"
    )


def _style(club: int, season: str) -> TacticalStyle:
    year = int(season[:4])
    end = f"{year}-08-31T00:00:00Z"
    return TacticalStyle(
        club,
        season,
        f"{year}-08-01T00:00:00Z",
        end,
        (
            TacticalStyleFixture(
                club * 1000 + 1, 1, f"{year}-08-10T12:00:00Z", f"{year}-08-10T15:00:00Z", 90
            ),
            TacticalStyleFixture(
                club * 1000 + 2, 2, f"{year}-08-20T12:00:00Z", f"{year}-08-20T15:00:00Z", 90
            ),
        ),
        (10, 5, 3, 2, 15, 8),
        STYLE_DEFINITION_VERSION,
        "synthetic-mapping",
        True,
        _source("style", end),
    )


def _side(club: int, season: str, rate: float) -> TacticalSideState:
    year = int(season[:4])
    observed = f"{year}-07-01T00:00:00Z"
    players = []
    for index, (position, role, goal, assist) in enumerate(
        zip(
            ("GK", "DEF", "MID", "FWD"),
            ("goalkeeper", "defender", "midfielder", "attacker"),
            (0, 0.1, 0.2, 0.7),
            (0, 0.1, 0.7, 0.2),
            strict=True,
        ),
        start=1,
    ):
        code = club * 100 + index
        profile = TacticalProfile(
            code,
            club,
            position,
            (10,) * len(TRAITS),
            TRAIT_DEFINITION_VERSION,
            f"synthetic-uid-{code}",
            "uid",
            "synthetic-only-reviewed-mapping",
            observed,
            f"{year + 1}-07-01T00:00:00Z",
            _source("traits", observed),
        )
        players.append(TacticalPlayerState(profile, role, 90, goal, assist))
    return TacticalSideState(club, rate, 0.8, 0.5, tuple(players))


def _projection(
    index: int = 0, *, season: str = "2024-25", gameweek: int | None = None
) -> TacticalProjection:
    year = int(season[:4])
    kickoff = datetime(year, 9, 1, 12, tzinfo=UTC) + timedelta(days=index)
    if season == TARGET_SEASON:
        kickoff = datetime(year, 10, 10, 12, tzinfo=UTC) + timedelta(days=index)
    decision = _time(kickoff - timedelta(hours=1))
    return TacticalProjection(
        season,
        (TARGET_GAMEWEEK if season == TARGET_SEASON else 3 + index)
        if gameweek is None
        else gameweek,
        8000 + index,
        1,
        2,
        _time(kickoff),
        decision,
        _style(1, season),
        _style(2, season),
        (TacticalJointState("one", 1, _side(1, season, 2), _side(2, season, 1)),),
        _source("projection", decision),
    )


def _observation(
    index: int = 0,
    *,
    physical: tuple[int, int] = (3, 1),
    season: str = "2024-25",
    gameweek: int | None = None,
) -> TacticalObservation:
    projection = _projection(index, season=season, gameweek=gameweek)
    settled = _time(
        datetime.fromisoformat(projection.kickoff.replace("Z", "+00:00")) + timedelta(hours=3)
    )
    credits = tuple(
        TacticalCredit(
            p.profile.player_code,
            side.club,
            goals if p.tactical_role == "attacker" else 0,
            int(goals > 0) if p.tactical_role == "midfielder" else 0,
        )
        for side, goals in zip(
            (projection.states[0].home, projection.states[0].away), physical, strict=True
        )
        for p in side.players
    )
    return TacticalObservation(
        projection,
        settled,
        physical,
        credits,
        "synthetic-rules",
        True,
        _source("physical-goals", settled),
        _source("fpl-totals", settled),
    )


def _fit(observations: tuple[TacticalObservation, ...] | None = None) -> TacticalMatchupModel:
    return TacticalMatchupModel(max_iter=400).fit(
        observations if observations is not None else (_observation(),),
        cutoff=CUTOFF,
        allowed_seasons=("2024-25",),
        target_season=TARGET_SEASON,
        target_gameweek=TARGET_GAMEWEEK,
    )


def _players(side: Any) -> dict[int, Any]:
    return {p.player_code: p for p in side.players}


def _change_trait(side: TacticalSideState, role: str, trait: str, value: int) -> TacticalSideState:
    players = []
    for player in side.players:
        if player.tactical_role == role:
            attributes = list(player.profile.attributes)
            attributes[TRAITS.index(trait)] = value
            player = replace(player, profile=replace(player.profile, attributes=tuple(attributes)))
        players.append(player)
    return replace(side, players=tuple(players))


def _reverse(projection: TacticalProjection) -> TacticalProjection:
    return replace(
        projection,
        home_club=projection.away_club,
        away_club=projection.home_club,
        home_style=projection.away_style,
        away_style=projection.home_style,
        states=tuple(replace(s, home=s.away, away=s.home) for s in projection.states),
    )


def _gradient(function: Any, coefficients: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    values = []
    for index in range(len(coefficients)):
        left, right = coefficients.copy(), coefficients.copy()
        left[index] -= 1e-6
        right[index] += 1e-6
        values.append((function(right)[0] - function(left)[0]) / 2e-6)
    return np.array(values)


@pytest.fixture(scope="module")
def fitted() -> TacticalMatchupModel:
    return _fit()


def test_control_preserves_native_rates_shares_and_nonlinear_clean_sheet(
    fitted: TacticalMatchupModel,
) -> None:
    projection = _projection(season=TARGET_SEASON)
    result = fitted.predict(projection, control=True)
    assert result.control is True
    assert result.home.team_goal_rate == 2
    assert result.away.team_goal_rate == 1
    home = _players(result.home)
    assert home[104].goals == pytest.approx(2 * 0.8 * 0.7)
    assert home[103].assists == pytest.approx(2 * 0.8 * 0.5 * 0.7)
    assert home[101].clean_sheet_probability == pytest.approx(math.exp(-1))
    assert sum(p.goals for p in result.home.players) == pytest.approx(1.6)
    assert sum(p.assists for p in result.home.players) == pytest.approx(0.8)
    assert result.projection_sha256 == projection_digest(projection)
    assert result.metadata is fitted.metadata


def test_control_integrates_state_rate_times_share_and_clean_sheet_before_averaging(
    fitted: TacticalMatchupModel,
) -> None:
    projection = _projection(season=TARGET_SEASON)
    original = projection.states[0]
    low_players = tuple(
        replace(p, native_goal_share=v)
        for p, v in zip(original.home.players, (0, 0.1, 0.1, 0.8), strict=True)
    )
    high_players = tuple(
        replace(p, native_goal_share=v)
        for p, v in zip(original.home.players, (0, 0.1, 0.7, 0.2), strict=True)
    )
    states = (
        replace(
            original,
            state_id="low",
            weight=0.25,
            home=replace(original.home, base_goal_rate=1, players=low_players),
            away=replace(original.away, base_goal_rate=0.5),
        ),
        replace(
            original,
            state_id="high",
            weight=0.75,
            home=replace(original.home, base_goal_rate=4, players=high_players),
            away=replace(original.away, base_goal_rate=3),
        ),
    )
    result = fitted.predict(replace(projection, states=states), control=True)
    home = _players(result.home)
    assert home[104].goals == pytest.approx(0.8 * (0.25 * 1 * 0.8 + 0.75 * 4 * 0.2))
    incorrectly_factored = 0.8 * (0.25 * 1 + 0.75 * 4) * (0.25 * 0.8 + 0.75 * 0.2)
    assert abs(home[104].goals - incorrectly_factored) > 0.1
    assert home[101].clean_sheet_probability == pytest.approx(
        0.25 * math.exp(-0.5) + 0.75 * math.exp(-3)
    )
    assert abs(home[101].clean_sheet_probability - math.exp(-(0.25 * 0.5 + 0.75 * 3))) > 0.05


def test_native_share_is_already_conditioned_on_minutes_no_second_exposure_factor(
    fitted: TacticalMatchupModel,
) -> None:
    projection = _projection(season=TARGET_SEASON)
    state = projection.states[0]
    players = tuple(
        replace(p, minutes=45 if p.tactical_role == "attacker" else 90) for p in state.home.players
    )
    result = fitted.predict(
        replace(projection, states=(replace(state, home=replace(state.home, players=players)),)),
        control=True,
    )
    striker = _players(result.home)[104]
    assert striker.goals == pytest.approx(2 * 0.8 * 0.7)
    assert striker.clean_sheet_probability == 0


def test_learned_recipient_share_is_not_multiplied_by_minutes_again(
    fitted: TacticalMatchupModel,
) -> None:
    projection = _projection(season=TARGET_SEASON)
    state = projection.states[0]
    players = tuple(
        replace(p, minutes=45 if p.tactical_role == "attacker" else 90) for p in state.home.players
    )
    altered = replace(
        projection, states=(replace(state, home=replace(state.home, players=players)),)
    )
    baseline, short = fitted.predict(projection), fitted.predict(altered)
    assert short.home.team_goal_rate == baseline.home.team_goal_rate
    assert _players(short.home)[104].goals == _players(baseline.home)[104].goals
    assert _players(short.home)[104].assists == _players(baseline.home)[104].assists


def test_exact_constant_transform_is_invariant_to_weight_splitting_and_ignores_zero_weight() -> (
    None
):
    constant = np.array([[1.5], [1.5], [99.0]])
    transform = tactical._transform(
        constant, np.array([0.3, 0.7, 0]), ("constant",), "synthetic-only"
    )
    assert transform.receipt.means == (1.5,)
    assert transform.receipt.scales == (1.0,)
    assert transform.apply(constant[:2]) == pytest.approx(np.zeros((2, 1)))


def test_pair_joint_mixture_matches_independent_probability_and_gradient() -> None:
    group = tactical._PairGroup(
        np.array([[[0.2, -0.4], [0.1, 0.3]], [[-0.5, 0.6], [0.7, -0.1]]]),
        np.array([[1.5, 0.8], [0.3, 2.2]]),
        np.array([0.35, 0.65]),
        np.array([2.0, 1.0]),
    )
    beta = np.array([0.15, -0.2])
    loglike, posterior, gradient = tactical._pair_terms(group, beta)
    rates = group.bases * np.exp(group.features @ beta)
    independent = [
        w * math.exp(-h - a) * h**2 / math.factorial(2) * a
        for w, (h, a) in zip(group.weights, rates, strict=True)
    ]
    assert loglike == pytest.approx(math.log(sum(independent)))
    assert posterior == pytest.approx(np.array(independent) / sum(independent))
    assert gradient == pytest.approx(
        -_gradient(lambda b: tactical._pair_terms(group, b), beta), abs=1e-8
    )


def test_recipient_mixture_uses_one_whole_count_vector_and_gradient() -> None:
    group = tactical._RecipientGroup(
        np.array([[[1.0, -0.3], [-0.2, 0.4]], [[-0.4, 0.5], [0.7, -0.1]]]),
        np.array([[0.8, 0.2], [0.2, 0.8]]),
        np.array([0.3, 0.7]),
        np.array([2.0, 1.0]),
    )
    gamma = np.array([0.25, -0.15])
    loglike, gradient = tactical._recipient_terms(group, gamma)
    tilted = group.shares * np.exp(group.features @ gamma)
    probabilities = tilted / tilted.sum(axis=1)[:, None]
    likelihood = sum(
        w * 3 * p[0] ** 2 * p[1] for w, p in zip(group.weights, probabilities, strict=True)
    )
    assert loglike == pytest.approx(math.log(likelihood))
    assert gradient == pytest.approx(
        -_gradient(lambda g: tactical._recipient_terms(group, g), gamma), abs=1e-8
    )
    repeated_label_likelihood = sum(
        w * math.log(3 * p[0] ** 2 * p[1])
        for w, p in zip(group.weights, probabilities, strict=True)
    )
    assert abs(loglike - repeated_label_likelihood) > 0.01


def test_disjoint_recipient_states_cannot_explain_credits_with_no_shared_support() -> None:
    group = tactical._RecipientGroup(
        np.zeros((2, 2, 1)),
        np.array([[1.0, 0.0], [0.0, 1.0]]),
        np.array([0.5, 0.5]),
        np.array([1.0, 1.0]),
    )
    with pytest.raises(ValueError, match="shared projected recipient support"):
        tactical._recipient_terms(group, np.zeros(1))


def test_pair_requires_one_joint_state_with_both_positive_outcome_support() -> None:
    group = tactical._PairGroup(
        np.zeros((2, 2, 1)),
        np.array([[1.0, 0.0], [0.0, 1.0]]),
        np.array([0.5, 0.5]),
        np.array([1.0, 1.0]),
    )
    with pytest.raises(ValueError, match="positive joint-state intensity support"):
        tactical._pair_terms(group, np.zeros(1))


def test_split_identical_states_leave_fit_scalers_and_predictions_unchanged(
    fitted: TacticalMatchupModel,
) -> None:
    observation = _observation()
    state = observation.projection.states[0]
    split = replace(
        observation,
        projection=replace(
            observation.projection,
            states=(
                replace(state, state_id="first", weight=0.3),
                replace(state, state_id="second", weight=0.7),
            ),
        ),
    )
    other = _fit((split,))
    assert other.metadata.team_transform.means == pytest.approx(
        fitted.metadata.team_transform.means
    )
    assert other.metadata.team_transform.scales == pytest.approx(
        fitted.metadata.team_transform.scales
    )
    assert other.metadata.goal_transform.means == pytest.approx(
        fitted.metadata.goal_transform.means
    )
    assert other.metadata.beta == pytest.approx(fitted.metadata.beta, abs=1e-8)
    assert other.metadata.goal_gamma == pytest.approx(fitted.metadata.goal_gamma, abs=1e-7)
    left, right = (
        fitted.predict(_projection(season=TARGET_SEASON)),
        other.predict(_projection(season=TARGET_SEASON)),
    )
    assert left.home.team_goal_rate == pytest.approx(right.home.team_goal_rate, abs=1e-8)
    assert [p.goals for p in left.home.players] == pytest.approx(
        [p.goals for p in right.home.players], abs=1e-7
    )


def test_shared_pair_and_recipient_fits_are_invariant_to_home_away_reversal(
    fitted: TacticalMatchupModel,
) -> None:
    observation = _observation()
    reversed_observation = replace(
        observation,
        projection=_reverse(observation.projection),
        physical_goals=observation.physical_goals[::-1],
    )
    other = _fit((reversed_observation,))
    projection = _projection(season=TARGET_SEASON)
    original, reversed_result = fitted.predict(projection), other.predict(_reverse(projection))
    assert original.home.team_goal_rate == pytest.approx(reversed_result.away.team_goal_rate)
    assert original.away.team_goal_rate == pytest.approx(reversed_result.home.team_goal_rate)
    assert [p.goals for p in original.home.players] == pytest.approx(
        [p.goals for p in reversed_result.away.players]
    )
    assert [p.assists for p in original.away.players] == pytest.approx(
        [p.assists for p in reversed_result.home.players]
    )


def test_fitted_recipients_move_native_shares_and_preserve_club_mass(
    fitted: TacticalMatchupModel,
) -> None:
    projection = _projection(season=TARGET_SEASON)
    control, learned = fitted.predict(projection, control=True), fitted.predict(projection)
    home = _players(learned.home)
    assert (
        home[104].goals / learned.home.team_goal_rate
        > _players(control.home)[104].goals / control.home.team_goal_rate
    )
    assert (
        home[103].assists / learned.home.team_goal_rate
        > _players(control.home)[103].assists / control.home.team_goal_rate
    )
    for result_side in (learned.home, learned.away):
        assert sum(p.goals for p in result_side.players) == pytest.approx(
            result_side.team_goal_rate * 0.8
        )
        assert sum(p.assists for p in result_side.players) == pytest.approx(
            result_side.team_goal_rate * 0.8 * 0.5
        )
        assert all(
            p.goals + p.assists <= result_side.team_goal_rate + 1e-12 for p in result_side.players
        )
        assert _players(result_side)[result_side.club * 100 + 1].goals == 0


def test_training_only_scalers_use_prior_not_outcome_posterior() -> None:
    observation = _observation()
    state = observation.projection.states[0]
    home = _change_trait(state.home, "attacker", "pace", 18)
    low_players = tuple(
        replace(p, native_goal_share=value)
        for p, value in zip(home.players, (0, 0.1, 0.1, 0.8), strict=True)
    )
    high_players = tuple(
        replace(p, native_goal_share=value)
        for p, value in zip(home.players, (0, 0.1, 0.7, 0.2), strict=True)
    )
    states = (
        replace(
            state,
            state_id="low",
            weight=0.2,
            home=replace(home, base_goal_rate=0.1, players=low_players),
        ),
        replace(
            state,
            state_id="high",
            weight=0.8,
            home=replace(home, base_goal_rate=5, players=high_players),
        ),
    )
    projection = replace(observation.projection, states=states)
    first = _fit((replace(observation, projection=projection),))
    other = _fit((replace(_observation(physical=(1, 3)), projection=projection),))
    assert first.metadata.team_transform == other.metadata.team_transform
    assert first.metadata.goal_transform == other.metadata.goal_transform
    assert first.metadata.assist_transform == other.metadata.assist_transform
    assert first.metadata.beta != other.metadata.beta
    raw = tactical._team_matrix(projection).reshape(-1, len(tactical.TEAM_FEATURES))
    assert first.metadata.team_transform.means == pytest.approx(
        np.average(raw, axis=0, weights=(0.1, 0.1, 0.4, 0.4))
    )


def test_matchup_own_attacking_pace_and_opponent_defending_pace_are_learned_separately() -> None:
    observations = []
    for index, (own, opponent, outcome) in enumerate(
        ((5, 5, 3), (18, 5, 6), (5, 18, 1), (18, 18, 3))
    ):
        observation = _observation(index, physical=(outcome, 2))
        state = observation.projection.states[0]
        home = _change_trait(state.home, "attacker", "pace", own)
        away = _change_trait(
            _change_trait(state.away, "defender", "pace", opponent), "midfielder", "pace", opponent
        )
        observations.append(
            replace(
                observation,
                projection=replace(
                    observation.projection, states=(replace(state, home=home, away=away),)
                ),
            )
        )
    model = _fit(tuple(observations))
    projection = _projection(season=TARGET_SEASON)
    state = projection.states[0]

    def rate(own: int, opponent: int) -> float:
        home = _change_trait(state.home, "attacker", "pace", own)
        away = _change_trait(
            _change_trait(state.away, "defender", "pace", opponent), "midfielder", "pace", opponent
        )
        return model.predict(
            replace(projection, states=(replace(state, home=home, away=away),))
        ).home.team_goal_rate

    assert rate(18, 5) > rate(5, 5)
    assert rate(18, 18) < rate(18, 5)
    assert rate(5, 18) < rate(5, 5)


def test_immutable_metadata_parameters_scalers_and_maps_cannot_diverge(
    fitted: TacticalMatchupModel,
) -> None:
    state = fitted._fitted
    assert state is not None
    for array in (
        state.beta,
        *state.gammas.values(),
        state.team_transform.means,
        state.team_transform.scales,
        *(t.means for t in state.recipient_transforms.values()),
    ):
        with pytest.raises(ValueError):
            array.setflags(write=True)
        with pytest.raises(ValueError):
            array[0] = 99
    with pytest.raises(TypeError):
        state.gammas["goals"] = np.zeros(1)  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        fitted.metadata.cutoff = "changed"  # type: ignore[misc]
    assert tuple(state.beta) == fitted.metadata.beta
    assert tuple(state.gammas["goals"]) == fitted.metadata.goal_gamma
    assert tuple(state.team_transform.means) == fitted.metadata.team_transform.means


def test_fit_receipts_bind_all_sources_identities_and_optimizer_scope(
    fitted: TacticalMatchupModel,
) -> None:
    metadata, observation = fitted.metadata, _observation()
    receipt = metadata.training_receipts[0]
    assert receipt.observation_sha256 == observation_digest(observation)
    assert receipt.projection_sha256 == projection_digest(observation.projection)
    assert receipt.goal_source == observation.goal_source
    assert receipt.credit_source == observation.credit_source
    assert len(receipt.profiles) == 8
    assert metadata.target_season == TARGET_SEASON
    assert metadata.target_gameweek == TARGET_GAMEWEEK
    assert metadata.allowed_seasons == ("2024-25",)
    assert metadata.goal_events == 4
    assert metadata.assist_events == 2
    assert all(
        r.success
        and r.initialization == "zero_vector"
        and r.optimum_scope == "converged_local_solution_only"
        for r in metadata.optimizers
    )


def test_failed_later_recipient_fit_preserves_previous_atomic_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _fit()
    before = model._fitted
    baseline = model.predict(_projection(season=TARGET_SEASON))
    original = tactical._optimize

    def fail_assists(*args: Any, **kwargs: Any) -> Any:
        if kwargs["head"] == "assists":
            raise ValueError("synthetic recipient fit failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(tactical, "_optimize", fail_assists)
    with pytest.raises(ValueError, match="synthetic recipient fit failure"):
        model.fit(
            (_observation(physical=(5, 2)),),
            cutoff=CUTOFF,
            allowed_seasons=("2024-25",),
            target_season=TARGET_SEASON,
            target_gameweek=TARGET_GAMEWEEK,
        )
    assert model._fitted is before
    assert model.predict(_projection(season=TARGET_SEASON)) == baseline


def test_successful_refit_replaces_snapshot_without_mutating_old_receipts() -> None:
    model = _fit()
    before = model._fitted
    old = model.metadata
    model.fit(
        (_observation(physical=(5, 2)),),
        cutoff=CUTOFF,
        allowed_seasons=("2024-25",),
        target_season=TARGET_SEASON,
        target_gameweek=TARGET_GAMEWEEK,
    )
    assert model._fitted is not before
    assert model.metadata is not old
    assert old.goal_events == 4
    assert model.metadata.goal_events == 7


def test_all_headers_are_preflighted_before_any_credit_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = _observation(1, season="2025-26")
    first = _observation()

    def forbidden_decode(*args: Any, **kwargs: Any) -> None:
        pytest.fail("full label validation preceded global header refusal")

    monkeypatch.setattr(tactical, "validate_observation", forbidden_decode)
    with pytest.raises(ValueError, match="protected/unselected"):
        _fit((first, forbidden))


@pytest.mark.parametrize("gameweek", [6, 7])
def test_whole_target_and_later_gameweeks_refuse_before_labels(
    gameweek: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    observation = _observation(season=TARGET_SEASON, gameweek=gameweek)

    def forbidden_decode(*args: Any, **kwargs: Any) -> None:
        pytest.fail("target gameweek label decoding was reached")

    monkeypatch.setattr(tactical, "validate_observation", forbidden_decode)
    with pytest.raises(ValueError, match=r"target gameweek|target and later|unavailable before"):
        TacticalMatchupModel().fit(
            (observation,),
            cutoff="2026-12-01T00:00:00Z",
            allowed_seasons=(TARGET_SEASON,),
            target_season=TARGET_SEASON,
            target_gameweek=6,
        )


@pytest.mark.parametrize("kind", ["goal_source", "credit_source"])
@pytest.mark.parametrize("field", ["published_at", "captured_at"])
def test_settled_source_cutoff_equality_is_refused_before_labels(
    kind: str, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    observation = _observation()
    observation = replace(
        observation, **{kind: replace(getattr(observation, kind), **{field: CUTOFF})}
    )

    def forbidden_decode(*args: Any, **kwargs: Any) -> None:
        pytest.fail("late source reached final labels")

    monkeypatch.setattr(tactical, "validate_observation", forbidden_decode)
    with pytest.raises(ValueError, match="cutoff"):
        _fit((observation,))


def test_duplicate_fixture_and_nonfinal_observation_refuse() -> None:
    with pytest.raises(ValueError, match="occurs twice"):
        _fit((_observation(), _observation()))
    with pytest.raises(ValueError, match="must be final"):
        _fit((replace(_observation(), final=False),))


def test_historical_double_week_requires_one_decision_clock_before_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _observation(), _observation(1, gameweek=3)

    def forbidden_decode(*args: Any, **kwargs: Any) -> None:
        pytest.fail("a later historical weekly capture reached outcome decoding")

    monkeypatch.setattr(tactical, "validate_observation", forbidden_decode)
    with pytest.raises(ValueError, match="one original decision clock"):
        _fit((first, second))


def test_historical_double_week_accepts_one_semantic_instant_and_records_both_sources() -> None:
    first, second = _observation(), _observation(1, gameweek=3)
    clock = first.projection.decision_at.replace("Z", "+00:00")
    second = replace(
        second,
        projection=replace(
            second.projection,
            decision_at=clock,
            source=replace(second.projection.source, published_at=clock, captured_at=clock),
        ),
    )
    model = _fit((first, second))
    assert len(model.metadata.training_receipts) == 2
    assert model.metadata.goal_events == 8
    assert {r.fixture for r in model.metadata.training_receipts} == {8000, 8001}


def test_near_unit_raw_state_weights_are_normalized_consistently_and_receipted(
    fitted: TacticalMatchupModel,
) -> None:
    observation = _observation()
    state = observation.projection.states[0]
    factor = 1 + 5e-13
    states = (
        replace(state, state_id="first", weight=0.4 * factor),
        replace(state, state_id="second", weight=0.6 * factor),
    )
    raw_projection = replace(observation.projection, states=states)
    raw_digest = projection_digest(raw_projection)
    model = _fit((replace(observation, projection=raw_projection),))
    assert model.metadata.team_transform == fitted.metadata.team_transform
    assert model.metadata.goal_transform.means == pytest.approx(
        fitted.metadata.goal_transform.means, rel=1e-14, abs=1e-15
    )
    assert model.metadata.goal_transform.scales == pytest.approx(
        fitted.metadata.goal_transform.scales, rel=1e-14, abs=1e-15
    )
    assert model.metadata.beta == pytest.approx(fitted.metadata.beta, abs=1e-8)
    receipt = model.metadata.training_receipts[0]
    assert receipt.projection_sha256 == raw_digest
    assert math.fsum(weight for _, weight in receipt.state_weights) == 1
    assert model.metadata.state_weight_policy == "validated_unit_mass_normalized_fsum_roundoff_v1"
    assert math.fsum(s.weight for s in raw_projection.states) > 1
    target = _projection(season=TARGET_SEASON)
    target_state = target.states[0]
    target_states = tuple(
        replace(
            target_state,
            state_id=s.state_id,
            weight=s.weight,
            home=replace(target_state.home, base_goal_rate=0),
            away=replace(target_state.away, base_goal_rate=0),
        )
        for s in states
    )
    target = replace(target, states=target_states)
    result = model.predict(target)
    assert result.projection_sha256 == projection_digest(target)
    assert math.fsum(s.weight for s in result.states) == 1
    assert all(p.clean_sheet_probability == 1 for p in result.home.players)
    assert all(p.clean_sheet_probability <= 1 for p in result.away.players)
    assert result.home.team_goal_rate == 0


@pytest.mark.parametrize("change", ["wrong-season", "earlier-gameweek", "earlier-decision"])
def test_prediction_binds_fitted_target_and_cutoff(
    fitted: TacticalMatchupModel, change: str
) -> None:
    projection = _projection(season=TARGET_SEASON)
    if change == "wrong-season":
        projection = _projection()
    elif change == "earlier-gameweek":
        projection = replace(projection, gameweek=5)
    else:
        projection = replace(
            projection,
            decision_at="2026-10-08T00:00:00Z",
            source=_source("projection", "2026-10-08T00:00:00Z"),
        )
    with pytest.raises(ValueError, match=r"cutoff|target window"):
        fitted.predict(projection)


def test_future_window_gameweek_is_allowed(fitted: TacticalMatchupModel) -> None:
    result = fitted.predict(_projection(1, season=TARGET_SEASON, gameweek=7))
    assert result.home.team_goal_rate > 0


def test_no_events_is_explicitly_unavailable_but_control_and_zero_mass_are_defined() -> None:
    model = _fit((_observation(physical=(0, 0)),))
    projection = _projection(season=TARGET_SEASON)
    assert model.metadata.goal_status == "unavailable_no_credited_events"
    assert model.metadata.assist_status == "unavailable_no_credited_events"
    with pytest.raises(ValueError, match="without historical credited events"):
        model.predict(projection)
    assert model.predict(projection, control=True).home.team_goal_rate == 2
    state = projection.states[0]
    zero = replace(
        projection,
        states=(
            replace(
                state,
                home=replace(state.home, base_goal_rate=0),
                away=replace(state.away, base_goal_rate=0),
            ),
        ),
    )
    result = model.predict(zero)
    assert result.home.team_goal_rate == result.away.team_goal_rate == 0
    assert all(
        p.goals == p.assists == 0 and p.clean_sheet_probability == 1 for p in result.home.players
    )


def test_zero_native_rate_cannot_support_a_positive_final_physical_goal() -> None:
    observation = _observation()
    state = observation.projection.states[0]
    observation = replace(
        observation,
        projection=replace(
            observation.projection,
            states=(replace(state, home=replace(state.home, base_goal_rate=0)),),
        ),
    )
    with pytest.raises(ValueError, match="positive joint-state intensity support"):
        _fit((observation,))


@pytest.mark.parametrize("alpha", [True, -0.1, float("nan"), float("inf"), None])
def test_alpha_requires_explicit_finite_nonnegative_value(alpha: Any) -> None:
    with pytest.raises(ValueError, match="finite nonnegative alpha"):
        TacticalMatchupModel(alpha=alpha)


@pytest.mark.parametrize("max_iter", [True, 0, -1, 1.5])
def test_max_iter_requires_positive_integer(max_iter: Any) -> None:
    with pytest.raises(ValueError, match="positive max_iter"):
        TacticalMatchupModel(max_iter=max_iter)


def test_unfitted_metadata_prediction_and_nonboolean_control_refuse(
    fitted: TacticalMatchupModel,
) -> None:
    model = TacticalMatchupModel()
    with pytest.raises(ValueError, match="fitted before metadata"):
        _ = model.metadata
    with pytest.raises(ValueError, match="fitted before prediction"):
        model.predict(_projection(season=TARGET_SEASON))
    with pytest.raises(ValueError, match="explicit boolean"):
        fitted.predict(_projection(season=TARGET_SEASON), control=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "target_season,target_gameweek",
    [
        ("2025-26", 6),
        ("2026-28", 6),
        (TARGET_SEASON, True),
        (TARGET_SEASON, 0),
        (TARGET_SEASON, 39),
    ],
)
def test_fit_target_is_explicit_admitted_season_and_gameweek(
    target_season: str, target_gameweek: Any
) -> None:
    with pytest.raises(ValueError, match="admitted target season"):
        TacticalMatchupModel().fit(
            (_observation(),),
            cutoff=CUTOFF,
            allowed_seasons=("2024-25",),
            target_season=target_season,
            target_gameweek=target_gameweek,
        )
