"""Ablation identity, causal table features and equal-budget research invariants."""

import importlib.util

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_football_contextual import contextual  # noqa: F401
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.bayesopt.football_search import decode, search
from squadopt.experiments.football_components import (
    FACTORIAL,
    ComponentForecast,
    Components,
    standings_features,
)
from squadopt.prediction.football_features import football_features
from squadopt.prediction.football_strength import DynamicTeamStrength


def test_factorial_endpoints_reproduce_frozen_heads(contextual):  # noqa: F811
    model, history, roster, fixtures = contextual
    target = fixtures.merge(roster.rename(columns={"player_id": "player_code"}), on="club")
    target["season"] = "2025-26"
    features = football_features(history, target, model.cutoff)
    target = pd.concat([target.drop(columns="home"), features], axis=1)
    cache = ComponentForecast(model, history, target)
    assert len({s.name for s in FACTORIAL}) == 16
    columns = [
        "expected_points",
        "goals",
        "assists",
        "clean_sheet_probability",
        "defcon_probability",
    ]
    np.testing.assert_allclose(
        cache.predict(Components())[columns], cache.base[columns], atol=1e-12
    )
    np.testing.assert_allclose(
        cache.predict(Components(True, True, True, True))[columns],
        cache.context[columns],
        atol=1e-12,
    )
    for switch in FACTORIAL:
        result = cache.predict(switch)
        assert (result.clean_sheet_probability <= result.p60 + 1e-12).all()
        assert (result.defcon_probability <= result.appearance_probability + 1e-12).all()
        groups = result.assign(fixture=target.fixture, club=target.club).groupby(
            ["fixture", "club"]
        )
        np.testing.assert_allclose(
            groups.goals.sum(), groups.team_goal_rate.first() * model.scored_fraction
        )
    attack = cache.predict(Components(True, True), attack_only=True, role_prior=4)
    np.testing.assert_allclose(attack.clean_sheet_probability, cache.base.clean_sheet_probability)
    np.testing.assert_allclose(attack.defcon_probability, cache.base.defcon_probability)
    # Captured absence affects every arm once, not just the candidate.
    unavailable = ComponentForecast(model, history, target.assign(availability_probability=0.0))
    assert unavailable.predict(Components()).expected_points.eq(0).all()


def test_standings_do_not_use_unsettled_future_other_season_or_duplicate_players():
    kickoff = pd.Timestamp("2026-08-01T12:00:00Z")
    history = pd.DataFrame(
        {
            "season": ["2026-27"] * 2 + ["2025-26"],
            "fixture": [1, 2, 3],
            "club": [1, 1, 1],
            "kickoff": [kickoff, kickoff + pd.Timedelta(days=7), kickoff],
            "team_goals": [3, 90, 90],
            "team_conceded": [0, 0, 0],
        }
    )
    target = pd.DataFrame(
        {
            "season": ["2026-27"] * 2,
            "club": [1, 1],
            "opponent": [2, 2],
            "feature_cutoff": [kickoff + pd.Timedelta(hours=3), kickoff + pd.Timedelta(hours=4)],
        }
    )
    result = standings_features(pd.concat([history, history]), target)
    assert result.own_ppg.iloc[0] == 1.35
    assert result.own_ppg.iloc[1] == (3 + 5 * 1.35) / 6
    assert result.own_gd.iloc[1] == 0.5
    assert result.opp_ppg.eq(1.35).all()


@pytest.mark.parametrize("value", [0, -1, np.nan, np.inf, True])
def test_strength_rejects_invalid_research_parameters(value):
    for field in ("half_life_days", "prior"):
        with pytest.raises(ValueError, match="finite and positive"):
            DynamicTeamStrength(
                pd.DataFrame(), cutoff=pd.Timestamp("2026-01-01T00:00:00Z"), **{field: value}
            )


def test_search_has_identical_initial_budget_no_repeat_and_best_observed_selection():
    objective = lambda p: ((p["half_life_days"] - 70) / 150) ** 2 + ((p["prior"] - 12) / 20) ** 2  # noqa: E731
    results = [search(objective, method=m, seed=2, budget=8) for m in ("random", "sklearn")]
    assert [r["loss"] for r in results[0].trials[:4]] == [r["loss"] for r in results[1].trials[:4]]
    for result in results:
        assert len({r["pool_index"] for r in result.trials}) == 8
        assert result.loss == min(r["loss"] for r in result.trials)
        assert result.loss == objective(result.parameters)
    with pytest.raises(ValueError, match="silently dropped"):
        search(lambda _: np.nan, method="random", seed=0)
    with pytest.raises(ValueError, match="coordinates"):
        decode(np.array([0, 0, 2]))


@pytest.mark.skipif(
    importlib.util.find_spec("botorch") is None, reason="optional research-bo extra"
)
def test_real_botorch_acquisition_executes():
    import torch

    torch.set_num_threads(1)
    result = search(lambda p: ((p["prior"] - 13) / 20) ** 2, method="botorch", seed=0, budget=5)
    assert len(result.trials) == 5
    assert np.isfinite(result.loss)
