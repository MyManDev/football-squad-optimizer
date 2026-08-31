"""Feasibility and determinism of the Benchmark V2 ownership template."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import (
    OWNERSHIP_TEMPLATE_V2,
    EvaluationValidationError,
    audit_unconstrained_template_v1,
    build_constrained_ownership_template,
)
from squadopt.scenarios.rivals import template_rival_from_ownership


def _pool() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    identifier = 0
    for position, count in (("GK", 4), ("DEF", 12), ("MID", 14), ("FWD", 10)):
        for _ in range(count):
            identifier += 1
            rows.append(
                {
                    "player_id": identifier,
                    "name": f"Synthetic {identifier}",
                    "team_id": 1 + (identifier - 1) % 12,
                    "position": position,
                    "price_tenths": 50,
                    "ownership": 100.0 - identifier,
                }
            )
    return pd.DataFrame(rows)


def test_template_v2_builds_a_full_feasible_squad() -> None:
    result = build_constrained_ownership_template(_pool())
    squad = result.decision.squad

    assert len(squad) == 15
    assert squad["position"].value_counts().to_dict() == {
        "MID": 5,
        "DEF": 5,
        "FWD": 3,
        "GK": 2,
    }
    assert result.total_cost_tenths <= 1000
    assert int(squad["team_id"].value_counts().max()) <= 3
    assert len(result.decision.starting_xi) == 11
    assert len(result.decision.bench) == 4
    assert result.decision.completion_policy == OWNERSHIP_TEMPLATE_V2


def test_template_v2_respects_budget_when_popular_players_are_expensive() -> None:
    pool = _pool()
    pool["price_tenths"] = 40
    expensive = [1, 2, 5, 6, 7, 17, 18, 19, 31, 32]
    pool.loc[pool["player_id"].isin(expensive), "price_tenths"] = 100

    result = build_constrained_ownership_template(pool)

    assert result.total_cost_tenths <= 1000
    assert int((result.decision.squad["price_tenths"] == 100).sum()) < 15


def test_template_v2_respects_the_three_per_team_limit() -> None:
    pool = _pool()
    pool.loc[pool["player_id"] <= 12, "team_id"] = 99

    result = build_constrained_ownership_template(pool)

    assert int((result.decision.squad["team_id"] == 99).sum()) == 3


def test_template_v2_armbands_and_bench_follow_ownership() -> None:
    result = build_constrained_ownership_template(_pool())
    decision = result.decision
    ownership = decision.squad.set_index("player_id")["ownership"]
    armband_order = sorted(
        decision.starting_xi,
        key=lambda player_id: (-float(ownership.at[player_id]), player_id),
    )

    assert decision.captain_id == armband_order[0]
    assert decision.vice_captain_id == armband_order[1]
    assert decision.squad.set_index("player_id").at[decision.bench[0], "position"] == "GK"
    assert list(decision.bench[1:]) == sorted(
        decision.bench[1:],
        key=lambda player_id: (-float(ownership.at[player_id]), player_id),
    )


def test_template_v2_is_deterministic_under_row_and_ownership_ties() -> None:
    pool = _pool()
    pool["ownership"] = 50.0
    shuffled = pool.sample(frac=1.0, random_state=27).reset_index(drop=True)

    first = build_constrained_ownership_template(pool)
    second = build_constrained_ownership_template(shuffled)

    assert first.decision.starting_xi == second.decision.starting_xi
    assert first.decision.bench == second.decision.bench
    assert first.decision.captain_id == second.decision.captain_id
    assert set(first.decision.squad["player_id"]) == set(second.decision.squad["player_id"])


def test_template_v2_does_not_mutate_the_pool() -> None:
    pool = _pool()
    original = pool.copy(deep=True)

    build_constrained_ownership_template(pool)

    assert_frame_equal(pool, original)


def test_template_v2_rejects_missing_or_invalid_ownership() -> None:
    with pytest.raises(EvaluationValidationError, match="missing columns"):
        build_constrained_ownership_template(_pool().drop(columns="ownership"))

    pool = _pool()
    pool.loc[0, "ownership"] = -1.0
    with pytest.raises(EvaluationValidationError, match="Invalid ownership pool"):
        build_constrained_ownership_template(pool)


def test_v1_audit_reports_team_limit_but_not_full_squad_feasibility() -> None:
    pool = _pool()
    pool.loc[pool["player_id"] <= 12, "team_id"] = 99
    rival = template_rival_from_ownership(pool)

    audit = audit_unconstrained_template_v1(pool, rival.starter_ids)

    assert audit["team_limit_violated"] is True
    assert int(audit["max_players_from_one_team"]) > 3
    assert audit["full_squad_feasibility"] == "not_verifiable_v1_has_no_squad_or_bench"


def test_v1_audit_only_claims_a_budget_breach_when_the_xi_alone_exceeds_it() -> None:
    pool = _pool()
    pool["price_tenths"] = 100
    rival = template_rival_from_ownership(pool)

    audit = audit_unconstrained_template_v1(pool, rival.starter_ids)

    assert audit["xi_cost_tenths"] == 1100
    assert audit["xi_exceeds_full_squad_budget"] is True
