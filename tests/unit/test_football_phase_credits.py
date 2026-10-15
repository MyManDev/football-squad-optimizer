"""Synthetic independent-total constraints for uniquely identifiable event credits."""

import json
from dataclasses import replace
from itertools import product

import pytest

from squadopt.features.football_phase_credits import (
    MAX_CREDIT_EVENTS,
    PHASE_CREDIT_BINDING_VERSION,
    PhaseCreditEvent,
    bind_unique_phase_credits,
)
from squadopt.features.football_phase_inputs import PhaseTotal


def _event(index=1, scorer=101, phase="other", own_goal=False):
    return PhaseCreditEvent(str(index), phase, scorer, own_goal, f"synthetic-event:{index}")


def _bind(events, totals, **kwargs):
    return bind_unique_phase_credits(
        events, totals, totals_evidence_ref="synthetic-final-fpl-totals", **kwargs
    )


def test_single_goal_binds_independent_fpl_assist_and_both_evidence_sources():
    result = _bind((_event(phase="penalty"),), (PhaseTotal(101, 1, 0), PhaseTotal(102, 0, 1)))
    assert len(result) == 1
    assert result[0].scorer == 101
    assert result[0].assist == 102
    assert result[0].phase == "penalty"
    assert result[0].credit_status == "final"
    assert json.loads(result[0].credit_evidence_ref) == {
        "binding_version": PHASE_CREDIT_BINDING_VERSION,
        "event": "synthetic-event:1",
        "independent_fpl_totals": "synthetic-final-fpl-totals",
    }


def test_mutual_scorers_force_cross_assists_without_provider_actor_or_phase_guess():
    events = (_event(1, 101, "corner"), _event(2, 102, "other"))
    totals = (PhaseTotal(101, 1, 1), PhaseTotal(102, 1, 1), PhaseTotal(103, 0, 0))
    result = _bind(events, totals)
    assert [(r.event_id, r.assist) for r in result] == [("1", 102), ("2", 101)]
    assert _bind(events, tuple(reversed(totals))) == result


def test_own_goal_can_have_one_attacking_assist_without_invented_scorer():
    result = _bind((_event(scorer=None, own_goal=True, phase="corner"),), (PhaseTotal(102, 0, 1),))
    assert result[0].scorer is None
    assert result[0].assist == 102
    assert result[0].own_goal


def test_complete_zero_goals_and_explicit_zero_assists_remain_distinct():
    assert _bind((), (PhaseTotal(101, 0, 0),)) == ()
    result = _bind((_event(),), (PhaseTotal(101, 1, 0), PhaseTotal(102, 0, 0)))
    assert result[0].assist is None


@pytest.mark.parametrize("phase", ["corner", "other"])
def test_same_phase_does_not_resolve_ambiguous_per_event_credit(phase):
    with pytest.raises(ValueError, match="ambiguous"):
        _bind(
            (_event(1, phase=phase), _event(2, phase=phase)),
            (PhaseTotal(101, 2, 0), PhaseTotal(102, 0, 1)),
        )


def test_no_self_assist_even_when_aggregate_credits_would_match():
    with pytest.raises(ValueError, match="no valid"):
        _bind((_event(),), (PhaseTotal(101, 1, 1),))


def test_search_budget_exhaustion_does_not_become_unique_or_ambiguous_credit():
    with pytest.raises(ValueError, match="bounded search"):
        _bind((_event(),), (PhaseTotal(101, 1, 0),), max_search_nodes=1)


@pytest.mark.parametrize("limit", [False, 0, -1, 100001, 1.0])
def test_search_limit_is_bounded_and_not_coerced(limit):
    with pytest.raises(ValueError, match="node limit"):
        _bind((), (PhaseTotal(101, 0, 0),), max_search_nodes=limit)


@pytest.mark.parametrize(
    ("events", "totals", "message"),
    [
        ([_event()], (PhaseTotal(101, 1, 0),), "immutable"),
        ((_event(),), [PhaseTotal(101, 1, 0)], "immutable"),
        ((_event(),), (), "immutable"),
        ((_event(),), (PhaseTotal(101, 1, 0), PhaseTotal(101, 0, 0)), "repeat"),
        ((_event(), _event()), (PhaseTotal(101, 2, 0),), "repeat"),
        ((_event(phase="set-piece"),), (PhaseTotal(101, 1, 0),), "phase"),
        ((_event(scorer=None),), (PhaseTotal(101, 0, 0),), "own goal"),
        ((_event(own_goal=True),), (PhaseTotal(101, 1, 0),), "own goal"),
        ((_event(scorer=True),), (PhaseTotal(101, 1, 0),), "identities"),
        ((_event(),), (PhaseTotal(102, 1, 0),), "absent"),
        ((_event(),), (PhaseTotal(101, 0, 0),), "scoring credits"),
        ((_event(),), (PhaseTotal(101, 1, 0), PhaseTotal(102, 0, 2)), "exceed"),
        ((_event(),), (PhaseTotal(101, True, 0),), "integer credits"),
        ((_event(),), (PhaseTotal(101, 1, -1),), "integer credits"),
        ((_event(),), (PhaseTotal(False, 1, 0),), "identities"),
        ((replace(_event(), source_evidence_ref=""),), (PhaseTotal(101, 1, 0),), "text"),
        ((replace(_event(), event_id=""),), (PhaseTotal(101, 1, 0),), "text"),
        (
            tuple(_event(i) for i in range(MAX_CREDIT_EVENTS + 1)),
            (PhaseTotal(101, MAX_CREDIT_EVENTS + 1, 0),),
            "bounded",
        ),
    ],
)
def test_malformed_or_inconsistent_sources_are_refused(events, totals, message):
    with pytest.raises(ValueError, match=message):
        _bind(events, totals)


def test_combined_evidence_must_fit_the_existing_phase_goal_contract():
    with pytest.raises(ValueError, match="text"):
        bind_unique_phase_credits(
            (replace(_event(), source_evidence_ref="e" * 1500),),
            (PhaseTotal(101, 1, 0),),
            totals_evidence_ref="t" * 1500,
        )


def test_small_complete_assignments_match_an_independent_exhaustive_oracle():
    # The oracle enumerates assignments directly, without the binder's cache,
    # capacity pruning or recursion. It includes ambiguity and impossibility.
    for scorers in product((101, 102, None), repeat=3):
        events = tuple(
            _event(i, scorer, own_goal=scorer is None) for i, scorer in enumerate(scorers)
        )
        for first_assists, second_assists in product(range(4), repeat=2):
            if first_assists + second_assists > 3:
                continue
            totals = (
                PhaseTotal(101, scorers.count(101), first_assists),
                PhaseTotal(102, scorers.count(102), second_assists),
            )
            expected = [
                choice
                for choice in product((None, 101, 102), repeat=3)
                if choice.count(101) == first_assists
                and choice.count(102) == second_assists
                and all(
                    assister is None or assister != scorer
                    for assister, scorer in zip(choice, scorers, strict=True)
                )
            ]
            if len(expected) == 1:
                assert tuple(row.assist for row in _bind(events, totals)) == expected[0]
            else:
                with pytest.raises(ValueError, match="ambiguous" if expected else "no valid"):
                    _bind(events, totals)
