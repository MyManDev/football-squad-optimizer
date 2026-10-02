"""Source-bound input rules and chip resource transitions, independent of measured uplift."""

from dataclasses import replace

import pandas as pd
import pytest

from squadopt.application.football_context import bind_football_context
from squadopt.application.manager_words import (
    SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    ManagerWord,
    ManagerWords,
)
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.models import ChipAvailability, ChipUseWindow
from squadopt.planning.recourse import ObservationNode, optimize_observed_recourse
from squadopt.planning.recourse_chips import net_week_points, remaining_chips


def test_feed_percent_and_source_claim_are_distinct_and_time_checked():
    roster = pd.DataFrame({"player_id": [1, 2, 3], "club": [1, 1, 1]})
    feed = pd.DataFrame(
        {"player_id": [1, 2, 3], "status": ["d", "d", "a"], "chance_of_playing": [75, 50, 100]}
    )
    word = ManagerWord(
        2,
        "stated_full_match_unavailable",
        "manager",
        "2026-09-21T12:00:00Z",
        "instant",
        "Club",
        "https://example.org/club/press",
        "2026-09-21T13:00:00Z",
        "He can play but not the full match.",
        source_sha256="a" * 64,
        span_start=0,
        span_end=34,
        fixture_scope="upcoming_premier_league",
        scope_verified=True,
        publication_verified=True,
        publication_source="html_publication_meta",
        publication_source_sha256="b" * 64,
    )
    evidence = ManagerWords(
        "2026-27",
        6,
        "synthetic_fixture",
        "synthetic",
        "fixture",
        ("Club",),
        (word,),
        source_check=SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    )
    kwargs = dict(
        season="2026-27",
        gameweek=6,
        cutoff=pd.Timestamp("2026-09-22T12:00:00Z"),
        manager_words=evidence,
        fixture_calendar=pd.DataFrame(
            {
                "fixture": [61],
                "club": [1],
                "GW": [6],
                "kickoff": [pd.Timestamp("2026-09-23T15:00:00Z")],
            }
        ),
    )
    bound, audit = bind_football_context(roster, feed, **kwargs)
    assert bound.availability_probability.tolist() == [0.75, 0.5, 1]
    assert bound.minutes_limited.tolist() == [False, True, False]
    assert audit[0]["source_url"] == word.source_url
    bound, audit = bind_football_context(
        roster, feed, **{**kwargs, "cutoff": pd.Timestamp("2026-09-21T12:30:00Z")}
    )
    assert not bound.minutes_limited.any()
    assert audit[0]["reason"] == "ineligible_source_timing"
    absent = replace(evidence, words=(replace(word, disposition="stated_expected_absent"),))
    bound, _ = bind_football_context(roster, feed, **{**kwargs, "manager_words": absent})
    assert bound.availability_probability.tolist() == [0.75, 0, 1]
    ambiguous = replace(evidence, words=(replace(word, disposition="stated_expected_start"),))
    bound, audit = bind_football_context(roster, feed, **{**kwargs, "manager_words": ambiguous})
    assert bound.availability_probability.tolist() == [0.75, 0.5, 1]
    assert audit[0]["reason"] == "categorical_statement_has_no_probability"
    unresolved = replace(
        evidence,
        words=(
            replace(
                word,
                words=None,
                source_sha256=None,
                span_start=None,
                span_end=None,
                scope_verified=False,
                publication_verified=False,
            ),
        ),
    )
    bound, audit = bind_football_context(roster, feed, **{**kwargs, "manager_words": unresolved})
    assert not bound.minutes_limited.any()
    assert audit[0]["reason"] == "source_span_unresolved"


@pytest.mark.parametrize("chip", ["freehit", "wildcard", "3xc", "bboost"])
def test_observed_chip_plan_restores_freehit_and_consumes_only_used_right(
    known_optimum_players, small_config, chip
):
    players = known_optimum_players.copy()
    frames = [players.assign(gameweek=w, buy_price_tenths=50, sell_price_tenths=50) for w in (1, 2)]
    baseline = PlanningHorizon(pd.concat(frames, ignore_index=True))
    initial = InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1)
    config = replace(small_config, bench_weight=0, solver_time_limit_seconds=30)
    rights = ChipAvailability(
        {chip: frozenset({1, 2, 3, 4})},
        {1: chip},
        {chip: (ChipUseWindow(frozenset({1, 2}), 0), ChipUseWindow(frozenset({3, 4}), 0))},
    )
    node = ObservationNode("captured-update", 1.0, PlanningHorizon(frames[1]))
    result = optimize_observed_recourse(
        baseline,
        initial,
        [node],
        config,
        candidate_count=1,
        chips=rights,
        value_extra_free_transfer=False,
    )
    assert result.contract_version == "observed_chip_recourse_v2"
    for candidate in result.candidates:
        first = candidate.first_week
        assert first.chip == chip
        assert remaining_chips(rights, first).gameweeks_for(chip) == frozenset({3, 4})
        continuation = candidate.continuations[0].plan.weeks[0]
        assert continuation.chip is None
        assert candidate.expected_net_points == pytest.approx(
            net_week_points(first) + net_week_points(continuation)
        )
        if chip == "freehit":
            reconstructed_start = (
                set(continuation.selected_squad.player_id)
                - set(continuation.transfers_in.player_id)
            ) | set(continuation.transfers_out.player_id)
            assert reconstructed_start == set(initial.squad_player_ids)
            assert continuation.bank_before_tenths == initial.bank_tenths
