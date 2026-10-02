"""The published score and roles stay on the same base forecast as the scored policy."""

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, ValidationError
from tests.unit.test_lineup_publication_bench_order import _points, _squad, _week

from squadopt.application.entries import EntryError
from squadopt.application.football_information import information_review_payload
from squadopt.application.lineup_publication import expected_week_points, lineup_fields
from squadopt.application.top100_weight import rebased_week
from squadopt.planning.lineup_utility import rescore_expected_week
from squadopt.platform.advice_documents import (
    information_review_schema,
    lineup_expectation_schema,
    participation_evidence_schema,
)


def scored_week():
    squad = _squad(_points(), appearance_probability=[0.5, *([1.0] * 14)])
    roster = squad.set_index("player_id", drop=False)
    starters = roster.loc[[1, 3, 4, 5, 6, 8, 9, 10, 13, 14, 15]].reset_index(drop=True)
    bench = roster.loc[[2, 12, 7, 11]].reset_index(drop=True)
    week = replace(
        _week(squad),
        starting_xi=starters,
        bench=bench,
        captain=starters.iloc[0],
        vice_captain_id=3,
        transfer_hit_points=4.0,
        projected_score=float(starters.expected_points.sum() + starters.iloc[0].expected_points),
        projected_bench_points=float(bench.expected_points.sum()),
        lineup_expectation={"version": "expected_lineup_v1"},
    )
    return rescore_expected_week(week)


def test_publication_keeps_the_scored_vice_and_bench_and_charges_the_hit_once():
    week = scored_week()
    payload = lineup_fields(week)
    assert payload["vice_captain"]["player_id"] == 3
    assert [row["player_id"] for row in payload["bench"]] == [2, 12, 7, 11]
    gross = week.lineup_expectation["expected_net_points"] + 4
    assert payload["expected_own_points"] == pytest.approx(gross)
    assert expected_week_points(week) == pytest.approx(gross)
    assert gross != pytest.approx(week.projected_score)
    assert "scoring_multipliers" not in payload["lineup_expectation"]
    assert "fingerprint" not in payload["lineup_expectation"]
    Draft202012Validator(lineup_expectation_schema()).validate(payload["lineup_expectation"])


def test_rebasing_changes_only_forecasts_and_scores_not_the_frozen_roles():
    week = scored_week()
    base = {
        int(row.player_id): float(row.expected_points) / 2
        for row in week.selected_squad.itertuples()
    }
    rebased = rebased_week(week, base)
    assert rebased.vice_captain_id == week.vice_captain_id
    assert rebased.captain.player_id == week.captain.player_id
    assert rebased.bench.player_id.tolist() == week.bench.player_id.tolist()
    assert rebased.starting_xi.player_id.tolist() == week.starting_xi.player_id.tolist()
    assert expected_week_points(rebased) == pytest.approx(expected_week_points(week) / 2)
    assert rebased.lineup_expectation["expected_net_points"] == pytest.approx(
        expected_week_points(week) / 2 - 4
    )
    assert rebased.projected_score == pytest.approx(week.projected_score / 2)
    assert rebased.bank_after_tenths == week.bank_after_tenths
    assert rebased.free_transfers_for_next_gameweek == week.free_transfers_for_next_gameweek


def test_scored_roles_cannot_silently_fall_back_to_a_different_vice():
    with pytest.raises(EntryError, match="vice-captain"):
        lineup_fields(replace(scored_week(), vice_captain_id=1))


def test_information_base_rescore_preserves_fractional_autosub_coefficients_and_roles():
    week = scored_week()
    first = {
        "starters": week.starting_xi.player_id.tolist(),
        "captain": 1,
        "vice_captain": 3,
        "bench": [2, 12, 7, 11],
    }
    terms = [
        {
            "gameweek": 6,
            "player_id": 1,
            "multiplier": 0.5,
            "forecast": 4.0,
            "baseline_forecast": 4.0,
        },
        {
            "gameweek": 7,
            "player_id": 1,
            "multiplier": 1.25,
            "forecast": 8.0,
            "baseline_forecast": 4.0,
        },
    ]
    branches = [
        {
            "id": state,
            "probability": probability,
            "point_terms": terms,
            "hit_points": 4,
            "first_action": first,
            "weeks": [
                {
                    "gameweek": gw,
                    **first,
                    "bench": [2, 11, 7, 12],
                    "in": [],
                    "out": [],
                    "chip": None,
                    "bank": 0,
                    "ft": 2,
                }
                for gw in (7, 8)
            ],
        }
        for state, probability in (("eligible", 0.75), ("unavailable", 0.25))
    ]
    plan = SimpleNamespace(
        diagnostics={
            "availability_information": {
                "reason": "compared",
                "source_snapshot_id": "synthetic",
                "captured_at_utc": "2026-09-01T00:00:00Z",
                "player_id": 1,
                "probability": 0.75,
                "gameweek": 7,
            },
            "observed_window": {
                "status": "compared",
                "chosen_index": 0,
                "candidates": [
                    {"first_in": [], "first_out": [], "first_chip": None, "branches": branches}
                ],
            },
        }
    )
    projection = SimpleNamespace(table=week.selected_squad)
    base = SimpleNamespace(
        table=pd.DataFrame({"gameweek": [6, 7], "player_id": [1, 1], "expected_points": [2.0, 2.0]})
    )
    payload = information_review_payload(plan, projection, base_horizon=base, weighted=True)
    candidate = payload["candidates"][0]
    # 0.5 * 2 + 1.25 * (2 * 8 / 4) - 4 = 2; integer casts lose both fractions.
    assert candidate["expected_net_points"] == pytest.approx(2.0)
    assert candidate["first_lineup"]["vice_captain"] == "Player 3"
    assert candidate["first_lineup"]["bench"] == ["Player 2", "Player 12", "Player 7", "Player 11"]
    assert candidate["branches"][0]["weeks"][0]["lineup"]["vice_captain"] == "Player 3"
    assert candidate["branches"][0]["weeks"][0]["lineup"]["bench"] == [
        "Player 2",
        "Player 11",
        "Player 7",
        "Player 12",
    ]
    Draft202012Validator(information_review_schema()).validate(payload)


def test_public_participation_summary_omits_internal_audit_and_checks_counts():
    summary = {
        "version": "football_participation_evidence_v1",
        "as_of": "2026-09-01T00:00:00Z",
        "gameweek": 6,
        "applied_player_count": 2,
        "unapplied_statement_count": 1,
        "captured_percentage_count": 5,
        "manager_statement_count": 3,
        "assumptions": ["source_eligibility_only"],
    }
    validator = Draft202012Validator(participation_evidence_schema())
    validator.validate(summary)
    with pytest.raises(ValidationError):
        validator.validate({**summary, "base_revision": "internal"})
    with pytest.raises(ValidationError):
        validator.validate({**summary, "applied_player_count": -1})
